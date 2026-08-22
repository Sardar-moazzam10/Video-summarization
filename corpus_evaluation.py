r"""
Corpus Evaluation Harness — empirical results for the thesis "Results & Discussion".

Runs the VidFusion summarization pipeline over a batch of videos and produces a
per-video metrics table plus aggregate statistics, with BASELINES to compare
against. Designed to be started and left running overnight.

WHAT IT MEASURES
----------------
For every video, three summarization conditions are scored against the SAME
reference (the original transcript), so the comparison is fair:

    system    — the VidFusion pipeline (fusion → BART hierarchical summary)
    lead_k    — LEAD-K baseline: the first K sentences of the transcript
    textrank  — TextRank baseline: graph-centrality extractive summary

and two clip-selection conditions:

    system    — segment_extractor's hybrid SBERT+TF-IDF scoring
    random    — randomly chosen segments within the same time budget (seeded)

Two quality checks (both reference-free — no human summaries needed):

    CHECK A  Summary fidelity   — summary vs original transcript
    CHECK B  Video↔summary      — selected clip transcripts vs the summary

Each check reports keyword coverage (TF-IDF, "are the important words kept?")
and semantic coverage (SBERT, "is every topic represented?").

WHY NO VIDEO DOWNLOAD
---------------------
Clip selection needs only the transcript and the summary — visual_keyframes is
optional. Skipping the download makes a 30-video corpus run take ~30 minutes
instead of several hours, and use no disk. Rendering is a separate concern and
is measured by the pipeline's own timings, not here.

USAGE
-----
    # 1. Create a corpus file: one "video_id,category" per line
    #    (category is optional but recommended — the thesis table breaks down by it)
    cat > corpus.txt <<'EOF'
    dQw4w9WgXcQ,podcast
    nm1TxQj9IsQ,podcast
    abc123XYZ99,lecture
    EOF

    # 2. Run it (resumable — safe to Ctrl-C and restart)
    ./venv/bin/python corpus_evaluation.py --corpus corpus.txt

    # Ad-hoc list instead of a file
    ./venv/bin/python corpus_evaluation.py VIDEO_ID_1 VIDEO_ID_2

    # Overnight run with the LLM judge as well (adds ~30-90s per video)
    ./venv/bin/python corpus_evaluation.py --corpus corpus.txt --llm-judge

    # Re-aggregate an existing results file without re-running anything
    ./venv/bin/python corpus_evaluation.py --corpus corpus.txt --aggregate-only

OUTPUT
------
    results/corpus_results.csv    one row per video — paste into the thesis
    results/corpus_results.json   full detail (missed keywords, uncovered topics)
    results/corpus_summary.txt    mean ± std per category — the headline table

Results are written incrementally after each video, so an overnight crash never
loses completed work, and re-running skips videos already present.
"""

import argparse
import asyncio
import csv
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fixed seed so the random-clip baseline is reproducible for the thesis.
RANDOM_SEED = 42

DEFAULT_OUTDIR = "results"
DEFAULT_PROFILE_MINUTES = 10   # research profile — NOT the 2-min Express demo profile


# ──────────────────────────────────────────────────────────────────────────────
# Corpus loading
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CorpusItem:
    video_id: str
    category: str = "uncategorised"


def load_corpus(path: str) -> List[CorpusItem]:
    """Read 'video_id[,category]' lines. Blank lines and # comments ignored."""
    items: List[CorpusItem] = []
    from backend.services.transcript_service import extract_video_id

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            vid = extract_video_id(parts[0])
            category = parts[1] if len(parts) > 1 and parts[1] else "uncategorised"
            items.append(CorpusItem(video_id=vid, category=category))
    return items


# ──────────────────────────────────────────────────────────────────────────────
# Baseline summarizers (zero extra dependencies)
# ──────────────────────────────────────────────────────────────────────────────

def _sentences(text: str, min_words: int = 4) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [s.strip() for s in parts if len(s.split()) >= min_words]


def baseline_lead_k(transcript_text: str, target_words: int) -> str:
    """
    LEAD-K: take sentences from the start until the word budget is hit.

    The standard cheap baseline in summarization literature — surprisingly hard
    to beat on news, and a fair floor for any abstractive system.
    """
    out, count = [], 0
    for s in _sentences(transcript_text):
        out.append(s)
        count += len(s.split())
        if count >= target_words:
            break
    return " ".join(out)


def baseline_textrank(transcript_text: str, target_words: int) -> str:
    """
    TextRank extractive baseline: TF-IDF sentence vectors → cosine similarity
    graph → power-iteration centrality → top sentences in original order.

    Implemented with sklearn/numpy only, so it adds no dependencies.
    """
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer

    sents = _sentences(transcript_text)
    if len(sents) <= 3:
        return " ".join(sents)

    try:
        tfidf = TfidfVectorizer(stop_words="english", max_features=5000).fit_transform(sents)
    except ValueError:
        return baseline_lead_k(transcript_text, target_words)

    # Cosine similarity graph (rows already L2-normalised by TfidfVectorizer)
    sim = (tfidf @ tfidf.T).toarray()
    np.fill_diagonal(sim, 0.0)

    row_sums = sim.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1e-9
    transition = sim / row_sums

    # Power iteration with damping (PageRank)
    n = len(sents)
    scores = np.ones(n) / n
    damping = 0.85
    for _ in range(50):
        new = (1 - damping) / n + damping * (transition.T @ scores)
        if np.abs(new - scores).sum() < 1e-6:
            scores = new
            break
        scores = new

    # Take highest-scoring sentences up to the budget, then restore reading order
    ranked = sorted(range(n), key=lambda i: scores[i], reverse=True)
    chosen, count = [], 0
    for idx in ranked:
        chosen.append(idx)
        count += len(sents[idx].split())
        if count >= target_words:
            break
    chosen.sort()
    return " ".join(sents[i] for i in chosen)


def baseline_random_clips(
    transcript_segments: List[Dict],
    target_seconds: float,
    seed: int = RANDOM_SEED,
) -> List[Dict]:
    """Randomly select grouped segments within the same time budget as the system."""
    import random
    from backend.services.segment_extractor import group_transcript_segments

    groups = group_transcript_segments(transcript_segments)
    if not groups:
        return []

    rng = random.Random(seed)
    pool = groups[:]
    rng.shuffle(pool)

    chosen, total = [], 0.0
    for g in pool:
        dur = g["end_time"] - g["start_time"]
        if dur <= 0:
            continue
        if total + dur > target_seconds:
            continue
        chosen.append(g)
        total += dur
        if total >= target_seconds:
            break

    chosen.sort(key=lambda g: g["start_time"])
    return chosen


# ──────────────────────────────────────────────────────────────────────────────
# Per-video evaluation
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class VideoResult:
    video_id: str
    category: str
    status: str = "ok"
    error: str = ""

    # Source properties
    source_words: int = 0
    source_duration_sec: float = 0.0
    source_segments: int = 0

    # System output
    summary_words: int = 0
    compression_ratio: float = 0.0
    num_clips: int = 0
    clips_duration_sec: float = 0.0

    # CHECK A — summary fidelity (system vs baselines)
    a_system_keyword: Optional[float] = None
    a_system_semantic: Optional[float] = None
    a_lead_keyword: Optional[float] = None
    a_lead_semantic: Optional[float] = None
    a_textrank_keyword: Optional[float] = None
    a_textrank_semantic: Optional[float] = None

    # CHECK B — clips vs summary (system vs random baseline)
    b_system_keyword: Optional[float] = None
    b_system_semantic: Optional[float] = None
    b_random_keyword: Optional[float] = None
    b_random_semantic: Optional[float] = None

    # Optional LLM judge (Check A only — the expensive one)
    a_llm_faithfulness: Optional[float] = None
    a_llm_coverage: Optional[float] = None

    # Timings (seconds)
    t_transcript: float = 0.0
    t_fusion: float = 0.0
    t_summary: float = 0.0
    t_clips: float = 0.0
    t_scoring: float = 0.0
    t_total: float = 0.0

    # Detail kept for the JSON report / appendix only
    detail: dict = field(default_factory=dict)


async def evaluate_video(
    item: CorpusItem,
    profile_minutes: int,
    clip_seconds: int,
    use_llm: bool,
    top_n_keywords: int,
) -> VideoResult:
    """Run the pipeline for one video and score it against all baselines."""
    from backend.services.transcript_service import get_transcript_service
    from backend.services.fusion_engine import get_fusion_engine
    from backend.services.summarization_service import get_summarization_service
    from backend.services.duration_profiles import get_profile
    from backend.services.segment_extractor import extract_highlight_segments
    from evaluate_summary import (
        extract_top_keywords, keyword_coverage, semantic_coverage, _clean,
    )

    res = VideoResult(video_id=item.video_id, category=item.category)
    t_start = time.perf_counter()

    # ---- 1. Transcript -------------------------------------------------
    t0 = time.perf_counter()
    svc = await get_transcript_service()
    tx = await svc.get_transcript(item.video_id)
    res.t_transcript = time.perf_counter() - t0

    if not tx or not tx.get("transcript"):
        res.status = "no_transcript"
        res.error = "transcript unavailable"
        res.t_total = time.perf_counter() - t_start
        return res

    segments = tx["transcript"]
    transcript_text = _clean(" ".join(s.get("text", "") for s in segments))
    res.source_segments = len(segments)
    res.source_words = len(transcript_text.split())
    if segments:
        last = segments[-1]
        res.source_duration_sec = round(
            float(last.get("start", 0)) + float(last.get("duration", 0)), 1
        )

    if res.source_words < 200:
        res.status = "too_short"
        res.error = f"only {res.source_words} words"
        res.t_total = time.perf_counter() - t_start
        return res

    profile = get_profile(profile_minutes)
    target_words = profile.target_words

    # ---- 2. Fusion -----------------------------------------------------
    t0 = time.perf_counter()
    fusion = get_fusion_engine().fuse_transcripts(
        transcripts={item.video_id: transcript_text},
        target_words=target_words,
        include_sources=profile.include_sources,
        include_transitions=profile.include_transitions,
    )
    res.t_fusion = time.perf_counter() - t0

    # ---- 3. Summarization ----------------------------------------------
    t0 = time.perf_counter()
    summary = get_summarization_service().hierarchical_summarize(
        text=fusion.narrative, target_words=target_words, profile=profile,
    )
    res.t_summary = time.perf_counter() - t0
    summary = _clean(summary)
    res.summary_words = len(summary.split())
    if res.source_words:
        res.compression_ratio = round(res.summary_words / res.source_words, 4)

    if not summary:
        res.status = "empty_summary"
        res.error = "summarizer returned nothing"
        res.t_total = time.perf_counter() - t_start
        return res

    # ---- 4. Clip selection ---------------------------------------------
    t0 = time.perf_counter()
    clips = extract_highlight_segments(
        video_id=item.video_id,
        transcript_segments=segments,
        summary_text=summary,
        target_duration_seconds=clip_seconds,
        visual_keyframes=None,          # text-only path — no video download needed
    )
    res.t_clips = time.perf_counter() - t0
    res.num_clips = len(clips)
    res.clips_duration_sec = round(
        sum(c["end_time"] - c["start_time"] for c in clips), 1
    )

    # ---- 5. Baselines ---------------------------------------------------
    lead_summary = baseline_lead_k(transcript_text, target_words)
    textrank_summary = baseline_textrank(transcript_text, target_words)
    random_clips = baseline_random_clips(segments, clip_seconds)

    # ---- 6. Scoring -----------------------------------------------------
    t0 = time.perf_counter()

    # One keyword set extracted from the SOURCE, reused for every condition,
    # so system and baselines are measured against an identical reference.
    source_keywords = extract_top_keywords(transcript_text, top_n=top_n_keywords)

    def score_a(text: str) -> Tuple[Optional[float], Optional[float], dict]:
        kw = keyword_coverage(source_keywords, text)
        sem = semantic_coverage(transcript_text, text, unit="chunk")
        return kw["score"], sem.get("score"), {"keyword": kw, "semantic": sem}

    a_sys = score_a(summary)
    a_lead = score_a(lead_summary)
    a_tr = score_a(textrank_summary)

    res.a_system_keyword, res.a_system_semantic = a_sys[0], a_sys[1]
    res.a_lead_keyword, res.a_lead_semantic = a_lead[0], a_lead[1]
    res.a_textrank_keyword, res.a_textrank_semantic = a_tr[0], a_tr[1]

    # CHECK B — do the clips represent the summary?
    summary_keywords = extract_top_keywords(
        summary, top_n=min(20, max(8, res.summary_words // 12))
    )

    def score_b(clip_list: List[Dict]) -> Tuple[Optional[float], Optional[float], dict]:
        text = _clean(" ".join(c.get("text", "") for c in clip_list))
        if not text:
            return None, None, {}
        kw = keyword_coverage(summary_keywords, text)
        sem = semantic_coverage(summary, text, unit="sentence")
        return kw["score"], sem.get("score"), {"keyword": kw, "semantic": sem}

    b_sys = score_b(clips)
    b_rand = score_b(random_clips)
    res.b_system_keyword, res.b_system_semantic = b_sys[0], b_sys[1]
    res.b_random_keyword, res.b_random_semantic = b_rand[0], b_rand[1]

    res.t_scoring = time.perf_counter() - t0

    # ---- 7. Optional LLM judge ------------------------------------------
    if use_llm:
        from evaluate_summary import ollama_judge, JUDGE_A_PROMPT
        judge = await ollama_judge(
            transcript_text, summary, JUDGE_A_PROMPT,
            ["faithfulness", "coverage", "key_point_recall"],
        )
        if isinstance(judge.get("faithfulness"), (int, float)):
            res.a_llm_faithfulness = float(judge["faithfulness"])
        if isinstance(judge.get("coverage"), (int, float)):
            res.a_llm_coverage = float(judge["coverage"])
        res.detail["llm_judge"] = judge

    res.detail.update({
        "check_a": {"system": a_sys[2], "lead_k": a_lead[2], "textrank": a_tr[2]},
        "check_b": {"system": b_sys[2], "random": b_rand[2]},
        "baseline_word_counts": {
            "lead_k": len(lead_summary.split()),
            "textrank": len(textrank_summary.split()),
        },
        "random_clip_count": len(random_clips),
        "fusion_topics": len(getattr(fusion, "topics", []) or []),
    })

    res.t_total = time.perf_counter() - t_start
    return res


# ──────────────────────────────────────────────────────────────────────────────
# Incremental persistence (crash-safe)
# ──────────────────────────────────────────────────────────────────────────────

CSV_FIELDS = [f for f in VideoResult.__dataclass_fields__ if f != "detail"]


def load_done(csv_path: str) -> set:
    """video_ids already present in the results file, so re-runs skip them."""
    if not os.path.exists(csv_path):
        return set()
    done = set()
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("video_id"):
                    done.add(row["video_id"])
    except Exception:
        pass
    return done


def append_row(csv_path: str, json_path: str, res: VideoResult) -> None:
    """Append one result to both reports immediately (survives a crash)."""
    is_new = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if is_new:
            w.writeheader()
        row = {k: v for k, v in asdict(res).items() if k != "detail"}
        w.writerow(row)

    # JSON Lines — one full record per line, trivially appendable
    with open(json_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(res), ensure_ascii=False) + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# Aggregation — the table that goes in the thesis
# ──────────────────────────────────────────────────────────────────────────────

def _mean_std(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return None, None
    mean = statistics.mean(vals)
    std = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return round(mean, 1), round(std, 1)


def _fmt(mean: Optional[float], std: Optional[float]) -> str:
    if mean is None:
        return "     n/a"
    return f"{mean:5.1f} ± {std:4.1f}"


def aggregate(csv_path: str, out_path: str) -> str:
    """Build mean ± std tables overall and per category."""
    if not os.path.exists(csv_path):
        return "No results file to aggregate."

    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "ok":
                continue
            conv = {}
            for k, v in row.items():
                if k in ("video_id", "category", "status", "error"):
                    conv[k] = v
                else:
                    try:
                        conv[k] = float(v) if v not in ("", None) else None
                    except ValueError:
                        conv[k] = None
            rows.append(conv)

    if not rows:
        return "No successful runs to aggregate yet."

    lines: List[str] = []
    W = 78
    lines.append("=" * W)
    lines.append("  VIDFUSION — CORPUS EVALUATION RESULTS")
    lines.append("=" * W)
    lines.append(f"  Videos evaluated (status=ok): {len(rows)}")

    cats = sorted({r["category"] for r in rows})
    lines.append(f"  Categories: {', '.join(cats)}")
    lines.append("")

    def block(title: str, subset: List[dict]) -> None:
        lines.append("-" * W)
        lines.append(f"  {title}  (n={len(subset)})")
        lines.append("-" * W)

        lines.append("")
        lines.append("  CHECK A — Summary fidelity vs original transcript (%)")
        lines.append("    Condition      Keyword coverage    Semantic coverage")
        for label, kk, sk in (
            ("VidFusion", "a_system_keyword", "a_system_semantic"),
            ("LEAD-K",    "a_lead_keyword",   "a_lead_semantic"),
            ("TextRank",  "a_textrank_keyword", "a_textrank_semantic"),
        ):
            km, ks = _mean_std([r.get(kk) for r in subset])
            sm, ss = _mean_std([r.get(sk) for r in subset])
            lines.append(f"    {label:<13}  {_fmt(km, ks)}        {_fmt(sm, ss)}")

        lines.append("")
        lines.append("  CHECK B — Selected clips vs summary (%)")
        lines.append("    Condition      Keyword coverage    Semantic coverage")
        for label, kk, sk in (
            ("VidFusion", "b_system_keyword", "b_system_semantic"),
            ("Random",    "b_random_keyword", "b_random_semantic"),
        ):
            km, ks = _mean_std([r.get(kk) for r in subset])
            sm, ss = _mean_std([r.get(sk) for r in subset])
            lines.append(f"    {label:<13}  {_fmt(km, ks)}        {_fmt(sm, ss)}")

        # LLM judge only if it was run
        llm = [r.get("a_llm_faithfulness") for r in subset if r.get("a_llm_faithfulness") is not None]
        if llm:
            fm, fs = _mean_std([r.get("a_llm_faithfulness") for r in subset])
            cm, cs = _mean_std([r.get("a_llm_coverage") for r in subset])
            lines.append("")
            lines.append("  LLM JUDGE (Ollama)")
            lines.append(f"    Faithfulness   {_fmt(fm, fs)}")
            lines.append(f"    Coverage       {_fmt(cm, cs)}")

        lines.append("")
        lines.append("  SOURCE / OUTPUT")
        for label, key, unit in (
            ("Source length", "source_duration_sec", "s"),
            ("Source words", "source_words", "w"),
            ("Summary words", "summary_words", "w"),
            ("Clips selected", "num_clips", ""),
        ):
            m, s = _mean_std([r.get(key) for r in subset])
            lines.append(f"    {label:<16} {m if m is not None else 'n/a'} {unit}"
                         f"  (std {s if s is not None else 'n/a'})")
        cr, _ = _mean_std([(r.get("compression_ratio") or 0) * 100 for r in subset])
        lines.append(f"    {'Compression':<16} {cr}% of source")

        lines.append("")
        lines.append("  PROCESSING TIME (seconds, mean)")
        for label, key in (
            ("Transcript", "t_transcript"), ("Fusion", "t_fusion"),
            ("Summarization", "t_summary"), ("Clip selection", "t_clips"),
            ("Scoring", "t_scoring"), ("TOTAL", "t_total"),
        ):
            m, s = _mean_std([r.get(key) for r in subset])
            lines.append(f"    {label:<16} {m if m is not None else 'n/a':>7} s  (std {s})")

        # Throughput — the answer to "how does it scale?"
        durs = [r.get("source_duration_sec") or 0 for r in subset]
        tots = [r.get("t_total") or 0 for r in subset]
        if sum(durs) > 0:
            ratio = sum(tots) / (sum(durs) / 60.0)
            lines.append(f"    {'Throughput':<16} {ratio:.1f} s of processing per minute of source video")
        lines.append("")

    block("OVERALL", rows)
    if len(cats) > 1:
        for c in cats:
            block(f"CATEGORY: {c}", [r for r in rows if r["category"] == c])

    lines.append("=" * W)
    report = "\n".join(lines)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    return report


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

async def _main() -> int:
    p = argparse.ArgumentParser(
        description="Run VidFusion over a corpus and produce thesis-ready metrics.",
    )
    p.add_argument("video_ids", nargs="*", help="Video IDs/URLs (or use --corpus)")
    p.add_argument("--corpus", help="File with 'video_id[,category]' per line")
    p.add_argument("--outdir", default=DEFAULT_OUTDIR, help=f"Output dir (default {DEFAULT_OUTDIR})")
    p.add_argument("--profile", type=int, default=DEFAULT_PROFILE_MINUTES,
                   help=f"Duration profile in minutes (default {DEFAULT_PROFILE_MINUTES}; "
                        "do NOT use 2 — that is the Express demo profile)")
    p.add_argument("--clip-seconds", type=int, default=120,
                   help="Clip time budget for Check B (default 120)")
    p.add_argument("--top-n", type=int, default=25, help="Top keywords tested (default 25)")
    p.add_argument("--llm-judge", action="store_true",
                   help="Also run the Ollama judge (adds ~30-90s per video)")
    p.add_argument("--timeout", type=int, default=900,
                   help="Per-video timeout in seconds (default 900)")
    p.add_argument("--limit", type=int, help="Only process the first N videos (smoke test)")
    p.add_argument("--force", action="store_true", help="Re-run videos already in the results file")
    p.add_argument("--aggregate-only", action="store_true",
                   help="Rebuild the summary from existing results; run nothing")
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    csv_path = os.path.join(args.outdir, "corpus_results.csv")
    json_path = os.path.join(args.outdir, "corpus_results.json")
    sum_path = os.path.join(args.outdir, "corpus_summary.txt")

    if args.aggregate_only:
        print(aggregate(csv_path, sum_path))
        print(f"\nWritten: {sum_path}")
        return 0

    # Build the work list
    if args.corpus:
        items = load_corpus(args.corpus)
    elif args.video_ids:
        from backend.services.transcript_service import extract_video_id
        items = [CorpusItem(video_id=extract_video_id(v)) for v in args.video_ids]
    else:
        p.error("give video IDs or --corpus")

    if args.profile == 2:
        print("WARNING: profile=2 is the Express DEMO profile. Research results "
              "should use a longer profile (10 recommended) — a very short summary "
              "covers less of the source and understates coverage.\n")

    if args.limit:
        items = items[:args.limit]

    done = set() if args.force else load_done(csv_path)
    todo = [it for it in items if it.video_id not in done]

    print("=" * 72)
    print("  VIDFUSION CORPUS EVALUATION")
    print("=" * 72)
    print(f"  corpus:      {len(items)} video(s)")
    print(f"  already done: {len(items) - len(todo)} (skipping; use --force to redo)")
    print(f"  to process:  {len(todo)}")
    print(f"  profile:     {args.profile} min")
    print(f"  LLM judge:   {'ON (slow)' if args.llm_judge else 'off'}")
    print(f"  output:      {args.outdir}/")
    print("=" * 72)

    ok = failed = 0
    run_start = time.perf_counter()

    for i, item in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] {item.video_id}  ({item.category})")
        try:
            res = await asyncio.wait_for(
                evaluate_video(
                    item, args.profile, args.clip_seconds,
                    args.llm_judge, args.top_n,
                ),
                timeout=args.timeout,
            )
        except asyncio.TimeoutError:
            res = VideoResult(video_id=item.video_id, category=item.category,
                              status="timeout", error=f"exceeded {args.timeout}s")
        except Exception as e:                     # keep the batch alive
            res = VideoResult(video_id=item.video_id, category=item.category,
                              status="error", error=f"{type(e).__name__}: {e}"[:300])

        append_row(csv_path, json_path, res)

        if res.status == "ok":
            ok += 1
            print(f"    OK  {res.t_total:.1f}s | "
                  f"A: kw {res.a_system_keyword} / sem {res.a_system_semantic} "
                  f"(LEAD {res.a_lead_keyword} / TR {res.a_textrank_keyword}) | "
                  f"B: kw {res.b_system_keyword} (rand {res.b_random_keyword})")
        else:
            failed += 1
            print(f"    SKIP [{res.status}] {res.error}")

    elapsed = time.perf_counter() - run_start
    print(f"\nProcessed {ok + failed} video(s) in {elapsed / 60:.1f} min "
          f"— {ok} ok, {failed} skipped/failed")

    print("\n" + aggregate(csv_path, sum_path))
    print(f"\nWritten:\n  {csv_path}\n  {json_path}\n  {sum_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
