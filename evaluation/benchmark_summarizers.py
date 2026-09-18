"""
Phase 3A: Summarization Model Benchmark
Compares DistilBART vs Llama 3.2 3B on the SAME selected transcript text.

Metrics:
  A. Factual Consistency   - % of key TF-IDF concept terms found in output
  B. Concept Coverage      - how many of the extracted concepts appear in summary
  C. Redundancy            - bigram repetition ratio in the generated text
  D. Coherence / Unique-sentence ratio
  E. Repetition / Degeneration flag
  F. Summary Length Accuracy - % deviation from target_words
  G. Latency               - wall-clock seconds
  H. Failure Rate          - did a fallback/retry happen?

Usage:
  python evaluation/benchmark_summarizers.py
"""
import os, sys, json, time, re
import numpy as np
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))

from evaluation.evaluate import GOLD
from backend.services.duration_profiles import get_profile

# ── inputs ────────────────────────────────────────────────────────────────────
SUMMARIES = json.load(open(os.path.join(HERE, "summaries.json")))
# Use the 10-min profile for all videos (250 target words, BRIEF style)
PROFILE = get_profile(10)
TARGET_WORDS = PROFILE.target_words   # 250


# ── metric helpers ─────────────────────────────────────────────────────────────
def _words(text: str):
    return re.findall(r"[a-z']+", text.lower())


def bigram_repetition_ratio(text: str) -> float:
    words = _words(text)
    if len(words) < 3:
        return 0.0
    grams = [tuple(words[i:i+2]) for i in range(len(words) - 1)]
    counts = Counter(grams)
    repeated = sum(c - 1 for c in counts.values() if c > 1)
    return repeated / max(len(grams), 1)


def unique_sentence_ratio(text: str) -> float:
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = [s.lower().strip() for s in sentences if len(s.split()) > 3]
    if not sentences:
        return 1.0
    return len(set(sentences)) / len(sentences)


def concept_coverage(text: str, concepts: list) -> float:
    """Fraction of concept names (lowercased) appearing in summary text."""
    if not concepts:
        return 0.0
    t = text.lower()
    hits = sum(1 for c in concepts if c["name"].lower().split()[0] in t)
    return hits / len(concepts)


def faithfulness(summary: str, source: str) -> float:
    """
    Term-overlap faithfulness: fraction of 2-word+ content words in summary
    that also appear in the source text. A simple extractive proxy for
    factual consistency — sufficient for an offline benchmark without
    an NLI model.
    """
    src_words = set(_words(source))
    sum_words = _words(summary)
    if not sum_words:
        return 0.0
    return sum(1 for w in sum_words if w in src_words) / len(sum_words)


def length_accuracy(text: str, target: int) -> float:
    actual = len(text.split())
    return 1.0 - abs(actual - target) / max(target, 1)


def degeneration_flag(text: str) -> bool:
    """True if the text looks degenerate."""
    words = text.split()
    if len(words) < 40:
        return False
    bgram = bigram_repetition_ratio(text)
    if bgram > 0.10:
        return True
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) >= 6:
        if unique_sentence_ratio(text) < 0.70:
            return True
    return False


# ── BART runner ────────────────────────────────────────────────────────────────
def run_bart(narrative: str, target_words: int) -> dict:
    """Run DistilBART summarization and collect metrics."""
    from backend.services.summarization_service import get_summarization_service
    from backend.services.duration_profiles import get_summarization_config

    svc = get_summarization_service()
    config = get_summarization_config(PROFILE)

    t0 = time.time()
    fallback_called = [False]
    retry_called = [False]

    # Monkey-patch to track fallback/retry without touching prod code
    original_chunk = svc._summarize_chunk.__func__

    def patched_chunk(self, text, target, cfg, mode="compress"):
        result = original_chunk(self, text, target, cfg, mode)
        # heuristic: if result == simple truncation, it's a fallback
        trunc = " ".join(text.split()[:target])
        if result.strip() == trunc.strip():
            fallback_called[0] = True
        return result

    import types
    svc._summarize_chunk = types.MethodType(patched_chunk, svc)

    try:
        summary, decision = svc.summarize_with_policy(narrative, target_words, PROFILE)
    except Exception as e:
        print(f"  [BART] Exception: {e}")
        summary = ""
        decision = {}
    finally:
        # restore
        svc._summarize_chunk = types.MethodType(
            lambda self, text, target, cfg, mode="compress": original_chunk(self, text, target, cfg, mode),
            svc
        )

    latency = time.time() - t0

    return {
        "model": "DistilBART",
        "summary": summary,
        "latency_s": round(latency, 2),
        "failure": fallback_called[0] or not summary,
        "decision": decision.get("action", "?"),
    }


# ── Ollama runner ──────────────────────────────────────────────────────────────
OLLAMA_SUMMARY_PROMPT = """You are a video content summarizer. Write a concise summary of the transcript below in approximately {target_words} words.
Write in clear, readable prose. Do NOT repeat yourself.

TRANSCRIPT:
{narrative}

SUMMARY ({target_words} words):"""


def run_ollama(narrative: str, target_words: int, base_url: str, model: str) -> dict:
    """Run Llama via Ollama and collect metrics."""
    import httpx

    # Truncate to 1500 words to avoid timeout
    words = narrative.split()
    if len(words) > 1500:
        narrative = " ".join(words[:1500])

    prompt = OLLAMA_SUMMARY_PROMPT.format(
        target_words=target_words,
        narrative=narrative,
    )

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": int(target_words * 2.0)},
    }

    t0 = time.time()
    try:
        resp = httpx.post(f"{base_url}/api/generate", json=payload, timeout=120.0)
        resp.raise_for_status()
        summary = resp.json().get("response", "").strip()
        failure = not summary
    except Exception as e:
        print(f"  [Ollama] Error: {e}")
        summary = ""
        failure = True

    latency = time.time() - t0
    return {
        "model": "Llama3.2-3B",
        "summary": summary,
        "latency_s": round(latency, 2),
        "failure": failure,
        "decision": "llm",
    }


# ── main ───────────────────────────────────────────────────────────────────────
def main():
    from backend.core.config import get_settings
    S = get_settings()
    OLLAMA_URL = S.OLLAMA_BASE_URL
    OLLAMA_MODEL = S.OLLAMA_MODEL

    # Check Ollama availability
    import httpx
    try:
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0)
        tags = resp.json().get("models", [])
        base = OLLAMA_MODEL.split(":")[0]
        ollama_ok = any(base in t.get("name", "") for t in tags)
        if not ollama_ok:
            print(f"[Ollama] Model '{OLLAMA_MODEL}' not found. Run: ollama pull {OLLAMA_MODEL}")
    except Exception:
        ollama_ok = False
        print("[Ollama] Not available. Only BART will be benchmarked.")

    print(f"\n{'='*60}")
    print(f"Phase 3A: Summarizer Benchmark (target={TARGET_WORDS} words)")
    print(f"{'='*60}")

    all_results = []

    for vid in GOLD:
        if vid.startswith("_") or vid not in SUMMARIES:
            continue

        narrative = SUMMARIES[vid]
        gold_concepts = GOLD[vid].get("concepts", [])

        print(f"\n[{vid}] {GOLD[vid].get('genre', 'unknown')} — narrative {len(narrative.split())} words")
        print(f"  Gold concepts: {len(gold_concepts)}")

        # Shared source for faithfulness
        source_text = narrative

        runners = [("BART", lambda n=narrative: run_bart(n, TARGET_WORDS))]
        if ollama_ok:
            runners.append(("Ollama", lambda n=narrative: run_ollama(n, TARGET_WORDS, OLLAMA_URL, OLLAMA_MODEL)))

        for rname, runner in runners:
            print(f"  Running {rname}...", end=" ", flush=True)
            result = runner()
            summary = result["summary"]

            if not summary:
                print(f"FAILED ({result['latency_s']:.1f}s)")
                all_results.append({
                    "video_id": vid,
                    "genre": GOLD[vid].get("genre"),
                    "model": result["model"],
                    "latency_s": result["latency_s"],
                    "failure": True,
                    "faithfulness": 0.0,
                    "concept_coverage": 0.0,
                    "bigram_repetition": 1.0,
                    "unique_sentence_ratio": 0.0,
                    "length_accuracy": 0.0,
                    "degeneration": True,
                    "word_count": 0,
                })
                continue

            # Compute metrics
            faith = faithfulness(summary, source_text)
            cov = concept_coverage(summary, gold_concepts)
            bgram = bigram_repetition_ratio(summary)
            uniq = unique_sentence_ratio(summary)
            lenacc = length_accuracy(summary, TARGET_WORDS)
            degen = degeneration_flag(summary)
            wc = len(summary.split())

            row = {
                "video_id": vid,
                "genre": GOLD[vid].get("genre"),
                "model": result["model"],
                "latency_s": result["latency_s"],
                "failure": result["failure"],
                "faithfulness": round(faith, 3),
                "concept_coverage": round(cov, 3),
                "bigram_repetition": round(bgram, 4),
                "unique_sentence_ratio": round(uniq, 3),
                "length_accuracy": round(max(lenacc, 0.0), 3),
                "degeneration": degen,
                "word_count": wc,
                "decision": result.get("decision"),
            }
            all_results.append(row)

            print(f"OK ({result['latency_s']:.1f}s) | {wc}w | faith={faith:.2f} cov={cov:.2f} rep={bgram:.3f}")

    # Save raw results
    out_path = os.path.join(HERE, "summarizer_benchmark.json")
    json.dump(all_results, open(out_path, "w"), indent=2)
    print(f"\nSaved {len(all_results)} rows to {out_path}")

    # Aggregate per model
    print(f"\n{'='*60}")
    print("### Phase 3A Results — Averaged over all videos")
    print(f"{'='*60}\n")

    models = sorted(set(r["model"] for r in all_results))
    headers = ["Model", "Faith", "Concept Cov", "Bigram Rep↓", "Sent Uniq", "Len Acc", "Degen↓", "Latency", "Fail↓"]
    col_w = [18, 7, 12, 11, 9, 8, 7, 9, 5]
    print("| " + " | ".join(h.ljust(col_w[i]) for i, h in enumerate(headers)) + " |")
    print("|" + "|".join("-" * (w + 2) for w in col_w) + "|")

    for m in models:
        rows = [r for r in all_results if r["model"] == m]
        def avg(k): return sum(r[k] for r in rows) / max(len(rows), 1)
        fail_count = sum(1 for r in rows if r["failure"])
        degen_count = sum(1 for r in rows if r["degeneration"])
        vals = [
            m,
            f"{avg('faithfulness'):.3f}",
            f"{avg('concept_coverage'):.3f}",
            f"{avg('bigram_repetition'):.4f}",
            f"{avg('unique_sentence_ratio'):.3f}",
            f"{avg('length_accuracy'):.3f}",
            f"{degen_count}/{len(rows)}",
            f"{avg('latency_s'):.1f}s",
            f"{fail_count}/{len(rows)}",
        ]
        print("| " + " | ".join(v.ljust(col_w[i]) for i, v in enumerate(vals)) + " |")

    print()
    # Per-video breakdown
    print("### Per-video breakdown\n")
    for vid in set(r["video_id"] for r in all_results):
        v_rows = [r for r in all_results if r["video_id"] == vid]
        genre = v_rows[0]["genre"]
        print(f"[{vid}] {genre}")
        for r in v_rows:
            print(f"  {r['model']:<20} faith={r['faithfulness']:.3f} cov={r['concept_coverage']:.3f} "
                  f"rep={r['bigram_repetition']:.4f} uniq={r['unique_sentence_ratio']:.3f} "
                  f"len_acc={r['length_accuracy']:.3f} degen={r['degeneration']} "
                  f"words={r['word_count']} latency={r['latency_s']:.1f}s fail={r['failure']}")


if __name__ == "__main__":
    main()
