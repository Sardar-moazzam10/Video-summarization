r"""
evaluate_corpus.py — Text-summarization evaluation harness for the research paper.

Runs ONLY the NLP portion of the VidFusion pipeline over a list of YouTube
videos and writes a structured CSV for the "Results & Discussion" chapter.

PIPELINE STAGES EXERCISED
-------------------------
    1. Transcript fetch    backend.services.transcript_service
    2. Fusion              backend.services.fusion_engine   (embed → cluster → dedup)
    3. NLI conflict check  backend.services.fusion_engine   (see note below)
    4. Summarization       backend.services.summarization_service (BART hierarchical)

DELIBERATELY SKIPPED (per evaluation spec — saves large amounts of compute):
    - TTS / audio generation      (edge-tts)
    - Subtitle generation
    - Video download, keyframe extraction, CLIP, ffmpeg rendering

NOTE ON NLI
-----------
NLI conflict detection is gated inside fuse_transcripts() on `len(transcripts) > 1`
because it detects contradictions BETWEEN sources. This harness evaluates one
video per run, so NLI is structurally skipped and the `nli_ran` column will be
False. That is correct behaviour, not a failure — the column exists so the CSV
never implies a stage ran when it did not.

METRICS PER VIDEO
-----------------
    source_words          words in the original transcript
    summary_words         words in the final generated summary
    compression_ratio     summary_words / source_words
    keyword_coverage_pct  % of the source's top TF-IDF keywords present in the summary
    keywords_found/total  raw counts behind that percentage
    t_transcript / t_fusion / t_summarization / t_total_nlp   latency, seconds
    nli_ran               whether NLI executed (False for single-video runs)
    status / error        "ok" or the reason this video was skipped

USAGE
-----
    # 1. Put your test video IDs in VIDEO_IDS below, or pass them on the CLI:
    ./venv/bin/python evaluate_corpus.py
    ./venv/bin/python evaluate_corpus.py VIDEO_ID_1 VIDEO_ID_2
    ./venv/bin/python evaluate_corpus.py --output results/paper_eval.csv

    # 2. Recommended for the paper — adds the extractive baseline comparison:
    ./venv/bin/python evaluate_corpus.py --baseline

STANDALONE: this script imports from the backend but modifies nothing.

THE EXACT-MATCH BIAS, AND WHY --baseline MATTERS
------------------------------------------------
Keyword coverage is computed against words drawn from the source, so it
structurally favours summaries that copy source wording. An extractive method
can therefore outscore an abstractive one of equal or better quality.

`--baseline` quantifies that bias rather than hiding it: it builds an extractive
summary (TextRank, falling back to LEAD-K) from the same transcript at the same
word budget, and scores it with the identical keyword set and coverage function.
The resulting `coverage_delta_pct` column is the measurement of interest — a
negative delta is the expected signature of abstraction, not evidence of a worse
summary. State this explicitly in the Results & Discussion chapter.
"""

import argparse
import asyncio
import csv
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, asdict, fields
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# =====================================================
# CONFIGURATION — edit these
# =====================================================

# Test corpus. Bare IDs or full YouTube URLs both work.
VIDEO_IDS: List[str] = [
    "nm1TxQj9IsQ",
    # "dQw4w9WgXcQ",
    # add the rest of your evaluation set here...
]

PROFILE_MINUTES = 10        # "Brief Summary" profile → ~1500 target words
TOP_N_KEYWORDS = 25         # how many source keywords to test for retention
MIN_SOURCE_WORDS = 200      # below this a transcript is too short to evaluate
PER_VIDEO_TIMEOUT = 900     # seconds before a single video is abandoned
# Outer bound on the LLM judge. Ollama's own httpx limit is
# OLLAMA_TIMEOUT_SECONDS (100s by default), so this leaves headroom for model
# load on a cold first call without letting a hung daemon stall the corpus run.
JUDGE_TIMEOUT = 180
DEFAULT_OUTPUT = "corpus_evaluation_results.csv"


# =====================================================
# RESULT RECORD
# =====================================================

@dataclass
class EvalResult:
    video_id: str
    status: str = "ok"
    error: str = ""

    # Source / output size
    source_words: int = 0
    summary_words: int = 0
    compression_ratio: float = 0.0

    # Quality
    keyword_coverage_pct: Optional[float] = None
    keywords_found: int = 0
    keywords_total: int = 0
    keywords_missed: str = ""      # semicolon-joined, for qualitative analysis

    # Extractive baseline — populated only when --baseline is passed.
    # Scored with the SAME keyword set and the SAME coverage function as the
    # system summary, so the two conditions are directly comparable.
    baseline_method: str = ""                          # textrank | lead_k | ""
    baseline_summary_words: int = 0
    baseline_keyword_coverage_pct: Optional[float] = None
    baseline_keywords_found: int = 0
    coverage_delta_pct: Optional[float] = None         # system − baseline
    baseline_error: str = ""

    # LLM judge (--llm-judge). Semantic quality scores from evaluate_summary's
    # Ollama judge, run on the SYSTEM summary only — the extractive baseline
    # needs no semantic scoring, it is the exact-match control.
    # Complements the keyword metrics: rewards meaning, not verbatim copying.
    judge_score: Optional[float] = None                # mean of the three below
    judge_faithfulness: Optional[float] = None
    judge_coverage: Optional[float] = None
    judge_key_point_recall: Optional[float] = None
    judge_hallucination_count: Optional[int] = None
    judge_missing_points_count: Optional[int] = None
    judge_verdict: str = ""
    judge_error: str = ""
    # Aggregation bookkeeping. A median is only meaningful alongside its n, so
    # the CSV always states how many passes actually contributed.
    judge_runs_attempted: int = 0
    judge_runs_ok: int = 0
    # Max−min of the per-run composite. Quantifies the judge non-determinism the
    # multi-run median is meant to absorb; 0.0 when only one pass succeeded.
    judge_score_spread: Optional[float] = None

    # Pipeline
    profile_minutes: int = PROFILE_MINUTES
    target_words: int = 0
    nli_ran: bool = False

    # Latency (seconds)
    t_transcript: float = 0.0
    t_fusion: float = 0.0
    t_summarization: float = 0.0
    t_total_nlp: float = 0.0       # pipeline stages only — excludes evaluation
    t_judge: float = 0.0           # LLM judge latency, reported separately


CSV_FIELDS = [f.name for f in fields(EvalResult)]


# =====================================================
# KEYWORD COVERAGE
# =====================================================

def extract_top_keywords(text: str, top_n: int = TOP_N_KEYWORDS) -> List[str]:
    """
    Rank the most important phrases in `text` using TF-IDF over its own sentences.

    Treating each sentence as a document lets TF-IDF surface terms that are
    locally dense but not uniformly distributed — i.e. topic words rather than
    filler. Returns lowercased uni/bi-grams, most important first.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    import numpy as np

    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 4]
    if len(sentences) < 2:
        sentences = [text] if text.strip() else []
    if not sentences:
        return []

    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        max_features=3000,
        # words of 3+ alphabetic chars — drops numbers and transcription noise
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z-]{2,}\b",
    )
    try:
        matrix = vectorizer.fit_transform(sentences)
    except ValueError:
        return []

    scores = np.asarray(matrix.sum(axis=0)).flatten()
    terms = vectorizer.get_feature_names_out()
    ranked = sorted(zip(terms, scores), key=lambda x: x[1], reverse=True)

    # Drop a unigram already contained in a higher-ranked bigram (and vice versa)
    chosen: List[str] = []
    for term, _ in ranked:
        if any(term in c or c in term for c in chosen):
            continue
        chosen.append(term)
        if len(chosen) >= top_n:
            break
    return chosen


def keyword_coverage(keywords: List[str], summary: str):
    """
    Percentage of `keywords` that survive into `summary`.

    Word-boundary matching so short keywords ("ai") don't match inside longer
    words ("rain"). Returns (percentage, found, total, missed_list).
    """
    if not keywords:
        return None, 0, 0, []

    haystack = " " + re.sub(r"\s+", " ", summary).lower().strip() + " "
    found, missed = [], []
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", haystack):
            found.append(kw)
        else:
            missed.append(kw)

    pct = round(len(found) / len(keywords) * 100, 1)
    return pct, len(found), len(keywords), missed


# =====================================================
# EXTRACTIVE BASELINES
# =====================================================
#
# Purpose: keyword coverage is computed from source-derived words, so it
# structurally rewards summaries that copy source wording. Reporting the
# abstractive pipeline alone yields an uninterpretable number. An extractive
# baseline held to the SAME word budget and scored with the SAME function makes
# the comparison meaningful — and quantifies the exact-match bias itself.
#
# Both baselines use only sklearn + numpy, which the pipeline already requires.
# No new dependencies.

def _split_sentences(text: str, min_words: int = 4) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in parts if len(s.split()) >= min_words]


def baseline_lead_k(transcript_text: str, target_words: int) -> str:
    """
    LEAD-K: take sentences from the beginning until the word budget is met.

    The canonical cheap baseline in summarization literature. Notoriously hard
    to beat on front-loaded content, which makes it a fair floor.
    """
    out, count = [], 0
    for sentence in _split_sentences(transcript_text):
        out.append(sentence)
        count += len(sentence.split())
        if count >= target_words:
            break
    return " ".join(out)


def baseline_textrank(transcript_text: str, target_words: int) -> str:
    """
    TextRank extractive baseline.

    TF-IDF sentence vectors → cosine-similarity graph → PageRank power iteration
    → highest-centrality sentences, truncated to the word budget and restored to
    reading order (so the output is coherent prose, not a ranked list).

    Raises on failure; the caller falls back to LEAD-K.
    """
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer

    sentences = _split_sentences(transcript_text)
    if len(sentences) <= 3:
        return " ".join(sentences)

    # TfidfVectorizer L2-normalises rows, so the Gram matrix is cosine similarity
    tfidf = TfidfVectorizer(stop_words="english", max_features=5000).fit_transform(sentences)
    sim = (tfidf @ tfidf.T).toarray()
    np.fill_diagonal(sim, 0.0)

    row_sums = sim.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1e-9
    transition = sim / row_sums

    n = len(sentences)
    scores = np.ones(n) / n
    damping = 0.85
    for _ in range(50):                      # power iteration
        updated = (1 - damping) / n + damping * (transition.T @ scores)
        if np.abs(updated - scores).sum() < 1e-6:
            scores = updated
            break
        scores = updated

    ranked = sorted(range(n), key=lambda i: scores[i], reverse=True)
    chosen, count = [], 0
    for idx in ranked:
        chosen.append(idx)
        count += len(sentences[idx].split())
        if count >= target_words:
            break
    chosen.sort()                            # restore reading order
    return " ".join(sentences[i] for i in chosen)


def generate_baseline(transcript_text: str, target_words: int):
    """
    Produce an extractive baseline summary, preferring TextRank.

    Fail-safe by design: TextRank can raise on degenerate input (e.g. a
    transcript with no usable vocabulary after stop-word removal), so LEAD-K is
    the fallback. Returns (summary, method, error) — `method` records what
    actually ran so the CSV never misreports the condition.
    """
    try:
        return baseline_textrank(transcript_text, target_words), "textrank", ""
    except Exception as e:
        first_error = f"textrank failed ({type(e).__name__}: {e})"

    try:
        return baseline_lead_k(transcript_text, target_words), "lead_k", first_error
    except Exception as e:
        return "", "", f"{first_error}; lead_k failed ({type(e).__name__}: {e})"


# =====================================================
# PER-VIDEO EVALUATION
# =====================================================

async def evaluate_video(
    raw_id: str,
    top_n: int = TOP_N_KEYWORDS,
    run_baseline: bool = False,
    run_judge: bool = False,
    judge_timeout: int = JUDGE_TIMEOUT,
    judge_runs: int = 1,
) -> EvalResult:
    """Run transcript → fusion → (NLI) → summarization for one video, timed.

    When `run_baseline` is True, additionally generates an extractive baseline
    summary from the same transcript at the same word budget and scores it with
    the identical keyword set and coverage function.
    """
    from backend.services.transcript_service import get_transcript_service, extract_video_id
    from backend.services.fusion_engine import get_fusion_engine
    from backend.services.summarization_service import get_summarization_service
    from backend.services.duration_profiles import get_profile

    video_id = extract_video_id(raw_id)
    res = EvalResult(video_id=video_id)
    t_start = time.perf_counter()

    # ---- Stage 1: transcript ------------------------------------------
    t0 = time.perf_counter()
    service = await get_transcript_service()
    payload = await service.get_transcript(video_id)
    res.t_transcript = round(time.perf_counter() - t0, 2)

    if not payload or not payload.get("transcript"):
        res.status = "no_transcript"
        res.error = "transcript could not be fetched"
        res.t_total_nlp = round(time.perf_counter() - t_start, 2)
        return res

    segments = payload["transcript"]
    transcript_text = re.sub(
        r"\s+", " ",
        " ".join(s.get("text", "") for s in segments if s.get("text")),
    ).strip()
    res.source_words = len(transcript_text.split())

    if res.source_words < MIN_SOURCE_WORDS:
        res.status = "too_short"
        res.error = f"only {res.source_words} words (min {MIN_SOURCE_WORDS})"
        res.t_total_nlp = round(time.perf_counter() - t_start, 2)
        return res

    profile = get_profile(PROFILE_MINUTES)
    res.target_words = profile.target_words

    # ---- Stage 2 + 3: fusion (NLI is internal to this call) -----------
    t0 = time.perf_counter()
    fusion = get_fusion_engine().fuse_transcripts(
        transcripts={video_id: transcript_text},
        target_words=profile.target_words,
        include_sources=profile.include_sources,
        include_transitions=profile.include_transitions,
    )
    res.t_fusion = round(time.perf_counter() - t0, 2)
    # NLI only executes for multi-source jobs — see module docstring.
    res.nli_ran = False

    # ---- Stage 4: summarization ---------------------------------------
    t0 = time.perf_counter()
    summary = get_summarization_service().hierarchical_summarize(
        text=fusion.narrative,
        target_words=profile.target_words,
        profile=profile,
    )
    res.t_summarization = round(time.perf_counter() - t0, 2)

    summary = re.sub(r"\s+", " ", summary or "").strip()
    res.summary_words = len(summary.split())

    if not summary:
        res.status = "empty_summary"
        res.error = "summarizer returned no text"
        res.t_total_nlp = round(time.perf_counter() - t_start, 2)
        return res

    if res.source_words:
        res.compression_ratio = round(res.summary_words / res.source_words, 4)

    # ---- Metric: keyword retention ------------------------------------
    keywords = extract_top_keywords(transcript_text, top_n)
    pct, found, total, missed = keyword_coverage(keywords, summary)
    res.keyword_coverage_pct = pct
    res.keywords_found = found
    res.keywords_total = total
    res.keywords_missed = "; ".join(missed)

    # ---- Extractive baseline (optional, --baseline) --------------------
    # Deliberately reuses `keywords` — the SAME source-derived reference set —
    # and the SAME keyword_coverage() function. Scoring against a separately
    # extracted set would invalidate the comparison.
    #
    # Wrapped so a baseline failure degrades to a logged error rather than
    # discarding an otherwise-valid system measurement for this video.
    if run_baseline:
        try:
            baseline_summary, method, err = generate_baseline(
                transcript_text, profile.target_words
            )
            res.baseline_method = method
            res.baseline_error = err

            if baseline_summary:
                res.baseline_summary_words = len(baseline_summary.split())
                b_pct, b_found, _, _ = keyword_coverage(keywords, baseline_summary)
                res.baseline_keyword_coverage_pct = b_pct
                res.baseline_keywords_found = b_found
                if pct is not None and b_pct is not None:
                    res.coverage_delta_pct = round(pct - b_pct, 1)
            elif not err:
                res.baseline_error = "baseline produced empty output"
        except Exception as e:
            res.baseline_error = f"{type(e).__name__}: {e}"[:200]

    # Pipeline latency = the three product stages only. Keyword extraction,
    # baseline generation and the LLM judge are evaluation instrumentation and
    # must not inflate a latency figure reported as system performance.
    res.t_total_nlp = round(
        res.t_transcript + res.t_fusion + res.t_summarization, 2
    )

    # ---- LLM judge (optional, --llm-judge) ----------------------------
    # Runs on the system summary only. Wrapped in asyncio.wait_for AND a bare
    # except: Ollama can be absent, rate-limited, return unparseable JSON, or
    # hang. None of those may end the corpus run.
    if run_judge:
        t0 = time.perf_counter()
        res.judge_runs_attempted = judge_runs

        SUB_METRICS = ("faithfulness", "coverage", "key_point_recall")
        samples: List[dict] = []          # one dict of sub-scores per successful pass
        hallucination_counts: List[int] = []
        missing_counts: List[int] = []
        verdicts: List[str] = []
        errors: List[str] = []

        try:
            # Imported lazily so a problem in evaluate_summary degrades to a
            # judge failure rather than preventing this script from starting.
            from evaluate_summary import ollama_judge, JUDGE_A_PROMPT
        except Exception as e:
            res.judge_error = f"import failed: {type(e).__name__}: {e}"[:200]
        else:
            # Each pass is independently guarded: a timeout or malformed
            # response drops that pass only, and aggregation proceeds on
            # whatever succeeded.
            for run_index in range(judge_runs):
                try:
                    verdict = await asyncio.wait_for(
                        ollama_judge(
                            transcript_text,
                            summary,
                            JUDGE_A_PROMPT,
                            list(SUB_METRICS),
                        ),
                        timeout=judge_timeout,
                    )

                    if verdict.get("error") and verdict.get("score") is None:
                        errors.append(f"run{run_index + 1}: {str(verdict['error'])[:60]}")
                        continue

                    # Keep only numeric sub-scores; the local model occasionally
                    # emits a string or omits a key entirely.
                    sample = {
                        key: float(verdict[key])
                        for key in SUB_METRICS
                        if isinstance(verdict.get(key), (int, float))
                    }
                    if not sample:
                        errors.append(f"run{run_index + 1}: no numeric sub-scores")
                        continue

                    samples.append(sample)

                    if isinstance(verdict.get("hallucinations"), list):
                        hallucination_counts.append(len(verdict["hallucinations"]))
                    if isinstance(verdict.get("missing_key_points"), list):
                        missing_counts.append(len(verdict["missing_key_points"]))
                    if verdict.get("verdict"):
                        verdicts.append(str(verdict["verdict"]))

                except asyncio.TimeoutError:
                    # NOTE: ollama_judge calls the daemon via asyncio.to_thread,
                    # which cannot be cancelled. The worker thread keeps running
                    # until httpx hits OLLAMA_TIMEOUT_SECONDS; we stop waiting.
                    errors.append(f"run{run_index + 1}: timeout after {judge_timeout}s")
                except Exception as e:
                    errors.append(f"run{run_index + 1}: {type(e).__name__}: {e}"[:80])

            # ---- Aggregate across successful passes ----------------------
            res.judge_runs_ok = len(samples)

            if samples:
                # Median per sub-metric — resistant to a single outlier pass,
                # which is exactly the failure mode of a small local judge.
                medians = {}
                for key in SUB_METRICS:
                    values = [s[key] for s in samples if key in s]
                    if values:
                        medians[key] = statistics.median(values)

                res.judge_faithfulness = medians.get("faithfulness")
                res.judge_coverage = medians.get("coverage")
                res.judge_key_point_recall = medians.get("key_point_recall")

                # Composite = mean of the medians (not median of the means):
                # aggregate each metric first, then combine.
                if medians:
                    res.judge_score = round(
                        statistics.mean(medians.values()), 1
                    )

                # Dispersion of the per-pass composite, so the variance the
                # median absorbs is visible rather than silently smoothed away.
                per_run_composite = [
                    statistics.mean(s.values()) for s in samples if s
                ]
                res.judge_score_spread = (
                    round(max(per_run_composite) - min(per_run_composite), 1)
                    if len(per_run_composite) > 1 else 0.0
                )

                if hallucination_counts:
                    res.judge_hallucination_count = int(
                        statistics.median(hallucination_counts)
                    )
                if missing_counts:
                    res.judge_missing_points_count = int(
                        statistics.median(missing_counts)
                    )
                if verdicts:
                    res.judge_verdict = verdicts[0][:300]

            # Errors are recorded even on partial success, so a median built
            # from fewer passes than requested is never silently presented as
            # a full-strength measurement.
            if errors:
                res.judge_error = "; ".join(errors[:3])[:200]

        res.t_judge = round(time.perf_counter() - t0, 2)

    return res


# =====================================================
# CSV OUTPUT (written incrementally — survives a crash)
# =====================================================

def append_result(path: str, result: EvalResult) -> None:
    write_header = not os.path.exists(path) or os.path.getsize(path) == 0
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(asdict(result))


def print_summary(results: List[EvalResult], output_path: str) -> None:
    ok = [r for r in results if r.status == "ok"]
    bad = [r for r in results if r.status != "ok"]

    print("\n" + "=" * 72)
    print("  CORPUS EVALUATION SUMMARY")
    print("=" * 72)
    print(f"  evaluated : {len(results)}   ok: {len(ok)}   skipped/failed: {len(bad)}")

    if ok:
        def avg(vals):
            vals = [v for v in vals if isinstance(v, (int, float))]
            return round(sum(vals) / len(vals), 1) if vals else 0.0

        print(f"\n  MEAN ACROSS {len(ok)} SUCCESSFUL RUN(S)")
        print(f"    source words         {avg([r.source_words for r in ok])}")
        print(f"    summary words        {avg([r.summary_words for r in ok])}")
        print(f"    compression          {avg([r.compression_ratio * 100 for r in ok])}% of source")
        print(f"    keyword coverage     {avg([r.keyword_coverage_pct for r in ok])}%")

        # Side-by-side comparison when the baseline ran
        scored = [r for r in ok if r.baseline_keyword_coverage_pct is not None]
        if scored:
            sys_cov = avg([r.keyword_coverage_pct for r in scored])
            base_cov = avg([r.baseline_keyword_coverage_pct for r in scored])
            methods = sorted({r.baseline_method for r in scored if r.baseline_method})
            print(f"\n  SYSTEM vs EXTRACTIVE BASELINE  (n={len(scored)}, "
                  f"method: {', '.join(methods) or 'n/a'})")
            print(f"    {'condition':<22}{'keyword coverage':>18}{'summary words':>16}")
            print(f"    {'VidFusion (abstractive)':<22}{sys_cov:>17}%"
                  f"{avg([r.summary_words for r in scored]):>16}")
            print(f"    {'Baseline (extractive)':<22}{base_cov:>17}%"
                  f"{avg([r.baseline_summary_words for r in scored]):>16}")
            delta = round(sys_cov - base_cov, 1)
            print(f"    {'delta (sys - base)':<22}{delta:>17}%")
            if delta < 0:
                print("    NOTE: a negative delta is expected — keyword coverage rewards")
                print("          verbatim copying, which favours extractive methods.")

        judged = [r for r in ok if r.judge_score is not None]
        if judged:
            print(f"\n  LLM JUDGE — semantic quality  (n={len(judged)})")
            print(f"    faithfulness         {avg([r.judge_faithfulness for r in judged])}%")
            print(f"    coverage             {avg([r.judge_coverage for r in judged])}%")
            print(f"    key point recall     {avg([r.judge_key_point_recall for r in judged])}%")
            print(f"    overall              {avg([r.judge_score for r in judged])}%")
            halluc = [r.judge_hallucination_count for r in judged
                      if r.judge_hallucination_count is not None]
            if halluc:
                print(f"    hallucinations/video {round(sum(halluc)/len(halluc), 2)} "
                      f"(total {sum(halluc)})")
            attempted = sum(r.judge_runs_attempted for r in judged)
            succeeded = sum(r.judge_runs_ok for r in judged)
            print(f"    judge passes         {succeeded}/{attempted} succeeded")
            spreads = [r.judge_score_spread for r in judged
                       if r.judge_score_spread is not None]
            if spreads and max(spreads) > 0:
                print(f"    per-video spread     mean {avg(spreads)}, max {max(spreads)}"
                      f"  (variance absorbed by the median)")
        judge_failures = [r for r in ok if r.judge_error]
        if judge_failures:
            print(f"\n  LLM judge unavailable for {len(judge_failures)} video(s) "
                  f"— e.g. {judge_failures[0].judge_error[:60]}")

        print()
        print(f"    transcript time      {avg([r.t_transcript for r in ok])} s")
        print(f"    fusion time          {avg([r.t_fusion for r in ok])} s")
        print(f"    summarization time   {avg([r.t_summarization for r in ok])} s")
        print(f"    TOTAL NLP latency    {avg([r.t_total_nlp for r in ok])} s  "
              f"(pipeline only)")
        if judged:
            print(f"    LLM judge time       {avg([r.t_judge for r in judged])} s  "
                  f"(evaluation overhead, excluded above)")

    if bad:
        print("\n  SKIPPED / FAILED")
        for r in bad:
            print(f"    {r.video_id:<16} [{r.status}] {r.error}")

    print(f"\n  CSV written: {output_path}")
    print("=" * 72 + "\n")


# =====================================================
# MAIN
# =====================================================

async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate VidFusion text summarization over a corpus (NLP stages only).",
    )
    parser.add_argument("video_ids", nargs="*",
                        help="Video IDs/URLs (defaults to VIDEO_IDS in this file)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="CSV output path")
    parser.add_argument("--top-n", type=int, default=TOP_N_KEYWORDS,
                        help=f"Keywords tested per video (default {TOP_N_KEYWORDS})")
    parser.add_argument("--timeout", type=int, default=PER_VIDEO_TIMEOUT,
                        help=f"Per-video timeout in seconds (default {PER_VIDEO_TIMEOUT})")
    parser.add_argument("--baseline", action="store_true",
                        help="Also generate an extractive baseline (TextRank, "
                             "LEAD-K fallback) at the same word budget and score "
                             "it with identical metrics for direct comparison")
    parser.add_argument("--llm-judge", action="store_true",
                        help="Also score the system summary with the Ollama LLM "
                             "judge from evaluate_summary.py (semantic quality). "
                             "Requires a running Ollama daemon; adds ~30-90s per video")
    parser.add_argument("--judge-timeout", type=int, default=JUDGE_TIMEOUT,
                        help=f"Per-run LLM judge timeout (default {JUDGE_TIMEOUT}s)")
    parser.add_argument("--judge-runs", type=int, default=1,
                        help="Number of independent judge passes per video; the "
                             "median of each sub-metric is reported. Use 3+ to "
                             "damp LLM non-determinism (default 1)")
    args = parser.parse_args()

    corpus = args.video_ids or VIDEO_IDS
    if not corpus:
        print("No videos to evaluate. Add IDs to VIDEO_IDS or pass them as arguments.")
        return 1

    print("=" * 72)
    print("  VIDFUSION — CORPUS EVALUATION (NLP stages only)")
    print("=" * 72)
    print(f"  videos      : {len(corpus)}")
    print(f"  profile     : {PROFILE_MINUTES} min (Brief Summary)")
    print(f"  keywords    : top {args.top_n} per video")
    print(f"  baseline    : {'ON (TextRank, LEAD-K fallback)' if args.baseline else 'off'}")
    if args.llm_judge:
        runs = max(1, args.judge_runs)
        print(f"  LLM judge   : ON (Ollama, {runs} pass{'es' if runs > 1 else ''}"
              f"/video{', median-aggregated' if runs > 1 else ''}, ~30-90s each)")
    else:
        print("  LLM judge   : off")
    print(f"  skipping    : TTS, subtitles, video download, keyframes, rendering")
    print(f"  output      : {args.output}")
    print("=" * 72)

    results: List[EvalResult] = []

    for i, raw_id in enumerate(corpus, 1):
        print(f"\n[{i}/{len(corpus)}] {raw_id}")
        try:
            result = await asyncio.wait_for(
                evaluate_video(
                    raw_id,
                    top_n=args.top_n,
                    run_baseline=args.baseline,
                    run_judge=args.llm_judge,
                    judge_timeout=args.judge_timeout,
                    judge_runs=max(1, args.judge_runs),
                ),
                # The judge runs inside evaluate_video, so the outer per-video
                # budget must accommodate EVERY pass or later runs would be cut
                # off mid-scoring and wrongly counted as failures.
                timeout=args.timeout + (
                    args.judge_timeout * max(1, args.judge_runs)
                    if args.llm_judge else 0
                ),
            )
        except asyncio.TimeoutError:
            result = EvalResult(video_id=raw_id, status="timeout",
                                error=f"exceeded {args.timeout}s")
        except KeyboardInterrupt:
            print("\nInterrupted — partial results are already saved.")
            break
        except Exception as e:
            # One bad video must never end the run.
            result = EvalResult(video_id=raw_id, status="error",
                                error=f"{type(e).__name__}: {e}"[:300])

        results.append(result)
        append_result(args.output, result)      # persist immediately

        if result.status == "ok":
            line = (f"    OK   {result.source_words} words → {result.summary_words} words "
                    f"| keyword coverage {result.keyword_coverage_pct}% "
                    f"({result.keywords_found}/{result.keywords_total}) "
                    f"| {result.t_total_nlp}s")
            if result.baseline_keyword_coverage_pct is not None:
                line += (f"\n         baseline[{result.baseline_method}] "
                         f"{result.baseline_keyword_coverage_pct}% "
                         f"({result.baseline_summary_words} words) "
                         f"| delta {result.coverage_delta_pct:+}%")
            elif result.baseline_error:
                line += f"\n         baseline FAILED: {result.baseline_error}"
            if result.judge_score is not None:
                line += (f"\n         judge: {result.judge_score}% "
                         f"(faith {result.judge_faithfulness}, "
                         f"cov {result.judge_coverage}, "
                         f"recall {result.judge_key_point_recall}) "
                         f"[{result.judge_runs_ok}/{result.judge_runs_attempted} runs"
                         f", spread {result.judge_score_spread}] "
                         f"| {result.t_judge}s")
            elif result.judge_error:
                line += f"\n         judge FAILED: {result.judge_error}"
            print(line)
        else:
            print(f"    SKIP [{result.status}] {result.error}")

    print_summary(results, args.output)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
