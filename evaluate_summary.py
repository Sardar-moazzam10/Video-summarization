r"""
Summary & Highlight-Video Quality Evaluator
============================================

There are TWO different correctness questions in this pipeline, and this tool
scores them SEPARATELY (two badges):

    YouTube video
         │  transcript
    AI SUMMARY     ◄── CHECK A: is the summary a TRUE summary of the video?
         │             (summary  vs  original transcript)
    pick clips from transcript
         │
    HIGHLIGHT VIDEO ◄── CHECK B: does the generated video REPRESENT the summary?
                       (selected clip transcripts  vs  summary)

  CHECK A — "Summary fidelity" → shown on the AI-summary side.
      Did the AI capture the important content of the real video, with no
      guessed / invented words? Compared against the original transcript
      (the ground truth). A low score = the summary is wrong/incomplete.

  CHECK B — "Video↔Summary match" → shown on the video side. EXPECT ~100%.
      The highlight clips are selected by matching transcript segments to the
      summary, so the clips SHOULD cover everything the summary says. This
      verifies that — every summary sentence should have a clip that represents
      it. A low score = the video drifted from its own summary (a real bug).

Each check uses up to 3 independent metrics (each 0-100):
  - Keyword coverage  : important phrases (TF-IDF) actually present — "no guessing"
  - Semantic coverage : SBERT — every part represented, not just fluent overlap
  - LLM judge (Ollama): faithfulness / coverage with reasons (uses your local LLM)

No human-written reference is needed — the original transcript and the summary
ARE the references.

USAGE
-----
A) From a MongoDB video_id (reads cached transcript; you supply summary + clips):

    ./venv/bin/python evaluate_summary.py \
        --video-id dQw4w9WgXcQ \
        --summary-file summaries/dQw4w9WgXcQ.txt \
        --clips-file clips.json

B) Fully offline:

    ./venv/bin/python evaluate_summary.py \
        --transcript-file transcript.json \   # [{text,start,duration}, ...]
        --summary-file summary.txt \
        --clips-file clips.json

C) As a library (for an API endpoint / a test):

    from evaluate_summary import evaluate
    report = await evaluate(transcript_segments, summary_text, clips)
    print(report["check_a"]["score"], report["check_b"]["score"])

clips.json = output of segment_extractor: [{"start_time":..,"end_time":..,"text":".."}]

Flags: --no-llm (skip the Ollama judge), --json (machine-readable output).
"""

import argparse
import asyncio
import json
import os
import re
import sys
from typing import List, Dict, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Loaders
# ──────────────────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _transcript_to_text(segments: List[Dict]) -> str:
    return " ".join(s.get("text", "").strip() for s in segments if s.get("text"))


def _clips_to_text(clips: List[Dict]) -> str:
    """Clip transcripts — what the highlight video actually shows/says."""
    return " ".join(c.get("text", "").strip() for c in clips if c.get("text"))


def load_transcript_from_file(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "transcript" in data:
        data = data["transcript"]
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of transcript segments")
    return data


async def load_transcript_from_db(video_id: str) -> List[Dict]:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from backend.services.transcript_service import get_transcript_service, extract_video_id
    svc = await get_transcript_service()
    result = await svc.get_transcript(extract_video_id(video_id))
    if not result or not result.get("transcript"):
        raise RuntimeError(f"No transcript found/fetchable for video_id={video_id}")
    return result["transcript"]


# ──────────────────────────────────────────────────────────────────────────────
# Shared metric primitives
# ──────────────────────────────────────────────────────────────────────────────

def extract_top_keywords(source_text: str, top_n: int = 25) -> List[str]:
    """Top-N important phrases of source_text via TF-IDF over its own sentences."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    import numpy as np

    sentences = [s for s in re.split(r"(?<=[.!?])\s+", source_text) if len(s.split()) >= 4]
    if len(sentences) < 2:
        sentences = [source_text] if source_text.strip() else []
    if not sentences:
        return []

    vec = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
        max_features=3000,
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z-]{2,}\b",
    )
    try:
        matrix = vec.fit_transform(sentences)
    except ValueError:
        return []

    scores = np.asarray(matrix.sum(axis=0)).flatten()
    terms = vec.get_feature_names_out()
    ranked = sorted(zip(terms, scores), key=lambda x: x[1], reverse=True)

    chosen: List[str] = []
    for term, _ in ranked:
        if any(term in c or c in term for c in chosen):
            continue
        chosen.append(term)
        if len(chosen) >= top_n:
            break
    return chosen


def keyword_coverage(keywords: List[str], target_text: str) -> Dict:
    """% of `keywords` that appear in target_text (word-boundary match)."""
    target = " " + _clean(target_text).lower() + " "
    hits, misses = [], []
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", target):
            hits.append(kw)
        else:
            misses.append(kw)
    score = (len(hits) / len(keywords) * 100) if keywords else None
    return {"score": round(score, 1) if score is not None else None,
            "hits": hits, "misses": misses, "total_keywords": len(keywords)}


def _sbert_model():
    from backend.services.fusion_engine import get_sentence_transformer
    return get_sentence_transformer()


def _l2(v):
    import numpy as np
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(n < 1e-9, 1e-9, n)


def semantic_coverage(reference_text: str, candidate_text: str,
                      unit: str = "chunk", chunk_words: int = 80,
                      hit_threshold: float = 0.45) -> Dict:
    """
    Generic semantic coverage: what fraction of the REFERENCE is represented in
    the CANDIDATE.

    - Check A: reference = full transcript (chunks), candidate = summary.
               "Does the summary cover the video's topics?"
    - Check B: reference = summary (sentences), candidate = clip transcripts.
               "Do the clips cover everything the summary says?"  unit='sentence'
    """
    import numpy as np
    try:
        model = _sbert_model()
    except Exception as e:
        return {"score": None, "error": f"SBERT unavailable: {e}"}

    # Build reference units
    if unit == "sentence":
        ref_units = [s for s in re.split(r"(?<=[.!?])\s+", reference_text) if len(s.split()) >= 4]
        ref_label = "summary sentences"
    else:
        words = reference_text.split()
        ref_units = [" ".join(words[i:i + chunk_words]) for i in range(0, len(words), chunk_words)]
        ref_units = [c for c in ref_units if len(c.split()) >= 10]
        ref_label = "topic chunks"

    cand_units = [s for s in re.split(r"(?<=[.!?])\s+", candidate_text) if len(s.split()) >= 3]
    if not ref_units or not cand_units:
        return {"score": None, "error": "Not enough text to compare"}

    embs = model.encode(ref_units + cand_units, show_progress_bar=False)
    ref_e, cand_e = embs[:len(ref_units)], embs[len(ref_units):]
    sim = _l2(ref_e) @ _l2(cand_e).T              # [ref, cand]
    best = sim.max(axis=1)
    covered = int((best >= hit_threshold).sum())
    score = covered / len(ref_units) * 100

    worst_idx = np.argsort(best)[:3]
    uncovered = [{"similarity": round(float(best[i]), 2),
                  "text": ref_units[i][:160] + ("..." if len(ref_units[i]) > 160 else "")}
                 for i in worst_idx if best[i] < hit_threshold]

    return {"score": round(score, 1), "covered": covered, "total": len(ref_units),
            "unit": ref_label, "threshold": hit_threshold, "least_covered": uncovered}


# ──────────────────────────────────────────────────────────────────────────────
# LLM judge — Ollama (local)
# ──────────────────────────────────────────────────────────────────────────────

JUDGE_A_PROMPT = """You are a strict evaluator. Below is the FULL transcript of a
video and a SUMMARY produced by an automated system. Judge ONLY against the
transcript — do not use outside knowledge.

Output ONLY valid JSON with these keys (scores are 0-100):
{{
  "faithfulness": 0,        // are all summary claims supported by the transcript? penalize invented/guessed facts
  "coverage": 0,            // does the summary capture the transcript's most important points?
  "key_point_recall": 0,    // of the 3-5 most important transcript points, how many appear in the summary?
  "hallucinations": [],     // claims in the summary NOT supported by the transcript
  "missing_key_points": [], // important transcript points the summary omitted
  "verdict": ""             // one sentence overall judgment
}}

TRANSCRIPT:
{reference}

SUMMARY:
{candidate}

JSON output:"""

JUDGE_B_PROMPT = """You are a strict evaluator. Below is a SUMMARY of a video and
the TRANSCRIPT of the highlight clips that were selected to build a short video
FROM that summary. Judge whether the clips represent the summary.

Output ONLY valid JSON with these keys (scores are 0-100):
{{
  "representation": 0,      // do the clips collectively represent what the summary says?
  "coverage": 0,           // is each main point of the summary backed by at least one clip?
  "off_topic": [],         // clip content that does NOT relate to the summary
  "summary_points_missing_from_clips": [],  // summary points no clip represents
  "verdict": ""            // one sentence overall judgment
}}

SUMMARY:
{reference}

SELECTED CLIP TRANSCRIPTS:
{candidate}

JSON output:"""


async def ollama_judge(reference_text: str, candidate_text: str, prompt_template: str,
                       score_keys: List[str]) -> Dict:
    try:
        from backend.services.ollama_service import get_ollama_service
        svc = get_ollama_service()
    except Exception as e:
        return {"score": None, "error": f"Ollama import failed: {e}"}

    if not svc.is_available():
        return {"score": None, "error": "Ollama not running / model not pulled — skipped"}

    prompt = prompt_template.format(reference=reference_text[:16000], candidate=candidate_text[:8000])
    raw = await asyncio.to_thread(svc._generate, prompt, True)   # expect_json=True
    if not raw:
        return {"score": None, "error": "Ollama returned no response"}

    data = svc._parse_json(raw)
    if not data:
        return {"score": None, "error": "Could not parse judge JSON", "raw": raw[:300]}

    nums = [data.get(k) for k in score_keys if isinstance(data.get(k), (int, float))]
    data["score"] = round(sum(nums) / len(nums), 1) if nums else None
    return data


# ──────────────────────────────────────────────────────────────────────────────
# The two checks
# ──────────────────────────────────────────────────────────────────────────────

async def check_a_summary_fidelity(transcript_text: str, summary_text: str,
                                   top_n: int, use_llm: bool) -> Dict:
    """Is the AI summary a faithful summary of the original video?"""
    keywords = extract_top_keywords(transcript_text, top_n=top_n)
    kw = keyword_coverage(keywords, summary_text)
    sem = semantic_coverage(transcript_text, summary_text, unit="chunk")
    llm = (await ollama_judge(transcript_text, summary_text, JUDGE_A_PROMPT,
                              ["faithfulness", "coverage", "key_point_recall"])
           if use_llm else {"score": None, "error": "disabled (--no-llm)"})

    parts = [m["score"] for m in (kw, sem, llm) if m.get("score") is not None]
    score = round(sum(parts) / len(parts), 1) if parts else None
    return {"name": "Summary fidelity (summary vs original video)",
            "score": score, "verdict": _verdict_a(score),
            "keyword_coverage": {**kw, "top_keywords": keywords},
            "semantic_coverage": sem, "llm_judge": llm}


async def check_b_video_summary_match(summary_text: str, clips: List[Dict],
                                      use_llm: bool) -> Dict:
    """Do the generated highlight clips represent the summary? (expect ~100%)"""
    clips_text = _clips_to_text(clips)
    if not clips:
        return {"name": "Video↔Summary match (clips vs summary)", "score": None,
                "verdict": "No clips provided — pass --clips-file to evaluate the video",
                "keyword_coverage": None, "semantic_coverage": None, "llm_judge": None}

    # Keywords of the SUMMARY should appear in the clips' transcripts
    keywords = extract_top_keywords(summary_text, top_n=min(20, max(8, len(summary_text.split()) // 12)))
    kw = keyword_coverage(keywords, clips_text)
    # Every summary SENTENCE should be represented by some clip
    sem = semantic_coverage(summary_text, clips_text, unit="sentence")
    llm = (await ollama_judge(summary_text, clips_text, JUDGE_B_PROMPT,
                              ["representation", "coverage"])
           if use_llm else {"score": None, "error": "disabled (--no-llm)"})

    parts = [m["score"] for m in (kw, sem, llm) if m.get("score") is not None]
    score = round(sum(parts) / len(parts), 1) if parts else None
    return {"name": "Video↔Summary match (clips vs summary)",
            "score": score, "verdict": _verdict_b(score),
            "keyword_coverage": {**kw, "top_keywords": keywords},
            "semantic_coverage": sem, "llm_judge": llm}


def _verdict_a(s: Optional[float]) -> str:
    if s is None:
        return "INCONCLUSIVE"
    if s >= 75:
        return "GOOD — summary faithfully captures the video's important content"
    if s >= 55:
        return "FAIR — captures the gist but misses/dilutes some key points"
    return "WEAK — important content missing or unsupported (possible guessing)"


def _verdict_b(s: Optional[float]) -> str:
    if s is None:
        return "INCONCLUSIVE"
    if s >= 85:
        return "GOOD — the video closely represents its summary (as expected)"
    if s >= 65:
        return "FAIR — most of the summary is shown, but some points have no clip"
    return "WEAK — the video drifted from its own summary (selection bug?)"


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────────────

async def evaluate(transcript_segments: List[Dict], summary_text: str,
                   clips: Optional[List[Dict]] = None,
                   top_n_keywords: int = 25, use_llm: bool = True) -> Dict:
    transcript_text = _clean(_transcript_to_text(transcript_segments))
    summary_text = _clean(summary_text)
    clips = clips or []

    a = await check_a_summary_fidelity(transcript_text, summary_text, top_n_keywords, use_llm)
    b = await check_b_video_summary_match(summary_text, clips, use_llm)

    return {
        "source_words": len(transcript_text.split()),
        "summary_words": len(summary_text.split()),
        "num_clips": len(clips),
        "check_a": a,   # badge on the AI-summary side
        "check_b": b,   # badge on the video side
    }


# ──────────────────────────────────────────────────────────────────────────────
# Pretty printer
# ──────────────────────────────────────────────────────────────────────────────

def _print_check(c: Dict) -> None:
    print(f"\n  ── {c['name']} ──")
    s = c["score"]
    print(f"     SCORE: {s if s is not None else 'N/A'}%   →   {c['verdict']}")

    kw = c.get("keyword_coverage")
    if kw and kw.get("score") is not None:
        print(f"     • Keyword coverage : {kw['score']:>5}%  "
              f"({len(kw['hits'])}/{kw['total_keywords']} important words present)")
        if kw["misses"]:
            print(f"         missing: {', '.join(kw['misses'][:8])}"
                  + (" ..." if len(kw["misses"]) > 8 else ""))

    sem = c.get("semantic_coverage")
    if sem and sem.get("score") is not None:
        print(f"     • Semantic coverage: {sem['score']:>5}%  "
              f"({sem['covered']}/{sem['total']} {sem['unit']} represented)")
        for t in sem.get("least_covered", []):
            print(f"         not covered (sim {t['similarity']}): \"{t['text']}\"")
    elif sem and sem.get("error"):
        print(f"     • Semantic coverage: skipped ({sem['error']})")

    lj = c.get("llm_judge")
    if lj and lj.get("score") is not None:
        print(f"     • LLM judge (Ollama): {lj['score']:>5}%")
        for k in ("hallucinations", "off_topic", "missing_key_points",
                  "summary_points_missing_from_clips"):
            if lj.get(k):
                print(f"         {k.replace('_', ' ')}:")
                for item in lj[k][:4]:
                    print(f"           - {item}")
        if lj.get("verdict"):
            print(f"         judge: {lj['verdict']}")
    elif lj and lj.get("error"):
        print(f"     • LLM judge (Ollama): skipped ({lj['error']})")


def print_report(r: Dict) -> None:
    line = "=" * 66
    print(f"\n{line}\n  VIDEO SUMMARY QUALITY SCORECARD\n{line}")
    print(f"  Source: {r['source_words']} words | Summary: {r['summary_words']} words "
          f"| Clips: {r['num_clips']}")
    print("\n  [A] SHOWN ON THE AI-SUMMARY SIDE")
    _print_check(r["check_a"])
    print("\n  [B] SHOWN ON THE VIDEO SIDE  (should be high — video is built from summary)")
    _print_check(r["check_b"])
    print(f"\n{line}")
    a, b = r["check_a"]["score"], r["check_b"]["score"]
    print(f"  SUMMARY BADGE : {a if a is not None else 'N/A'}%")
    print(f"  VIDEO  BADGE  : {b if b is not None else 'N/A'}%")
    print(f"{line}\n")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

async def _main():
    p = argparse.ArgumentParser(description="Evaluate summary fidelity & video↔summary match")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--video-id", help="Read transcript from MongoDB cache by video_id")
    src.add_argument("--transcript-file", help="JSON: [{text,start,duration}, ...]")

    p.add_argument("--summary-file", required=True, help="Plain-text generated summary")
    p.add_argument("--clips-file", help="JSON of selected clips [{start_time,end_time,text}]")
    p.add_argument("--top-n", type=int, default=25, help="Top keywords to test for Check A")
    p.add_argument("--no-llm", action="store_true", help="Skip the Ollama LLM judge")
    p.add_argument("--json", action="store_true", help="Print raw JSON")
    args = p.parse_args()

    transcript = (await load_transcript_from_db(args.video_id) if args.video_id
                  else load_transcript_from_file(args.transcript_file))

    with open(args.summary_file, "r", encoding="utf-8") as f:
        summary = f.read()

    clips = None
    if args.clips_file:
        with open(args.clips_file, "r", encoding="utf-8") as f:
            clips = json.load(f)

    report = await evaluate(transcript, summary, clips,
                            top_n_keywords=args.top_n, use_llm=not args.no_llm)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_report(report)


if __name__ == "__main__":
    asyncio.run(_main())
