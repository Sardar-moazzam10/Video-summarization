# Semantic Summarization Pipeline

How VidFusion decides which parts of a long video end up in a short one.

This document covers the selection pipeline added on top of the existing
architecture. Nothing was replaced: Whisper/yt-dlp transcription, the SBERT
fusion engine, BART summarization, Ollama, FAISS and the FFmpeg assembler all
work exactly as before. What changed is *what gets selected* and *what happens
to the summary text*.

---

## 1. The problems this solves

All three were measured on real completed jobs in this repository's own
MongoDB, not inferred from reading the code.

### Problem 1 — selection was beginning-heavy

`segment_extractor._select_within_budget()` sorted candidate clips by score and
took them until the budget filled. The score had no memory and no term for
*where in the video* a candidate came from.

| Job | Source | Requested | Budget used | Deciles hit | First-half share |
|---|---|---|---|---|---|
| `d0781c99` | 24.8 min | 5 min | 99% | 8/10 | **80%** |
| `24c295a1` | 14.7 min | 5 min | **154%** | 8/10 | **70%** |
| `5b8d9ffc` | 24.8 min | 10 min | **8%** | **3/10** | **100%** |
| `148de50a` | 82 min | 10 min | **352%** | 10/10 | 53% |

Two separate defects are visible: content starvation in the later part of the
video, and a budget that was both undershot (8%) and overshot (352%) because
padding was counted in `_select_within_budget`, added again in
`_format_for_merge`, then counted a third time in `_fit_to_duration`.

### Problem 2 — BART was silently bypassed

`summarization_service.hierarchical_summarize()` opened with:

```python
if word_count <= target_words:
    return text
```

One test doing two jobs. It asks "is this long enough to need compressing?" and
treats the answer as "is this good enough to ship?".

| Job | Profile | Target | Narrative | Ran BART? | Connective artifacts |
|---|---|---|---|---|---|
| `d0781c99` | 5 min | 750 | 757 words | yes | 0 |
| `f39f1089` | 10 min | 1500 | 820 words | **no** | **19** |

Same engine, same video. The only difference was which side of the threshold the
narrative landed on. The artifacts come from
`fusion_engine._synthesize_narrative()`, which glues cluster representatives
together with a rotating list of connectives.

On an auto-caption transcript the damage is worse than "starts with
Additionally". Because the preceding cluster has no terminal punctuation, the
connective lands *inside* a sentence:

```
...If I have to do it now, I will come late Additionally, To reach four and
five we need Brain cheat code...
```

### Problem 3 — no concept extraction

Nothing in the pipeline identified what a video was *about*. Selection scored
every candidate by similarity to one abstractive summary, which makes that
summary a bottleneck: a 1-hour podcast compressed to 800 words mentions
"overfitting" once, so every clip about overfitting competes for the similarity
mass of a single sentence, and topics the summary skipped can never win a slot.

### Problem 4 — the selection unit was a clip, not a thought

`_group_transcript_segments()` cut on a word-count and duration floor with a
*soft* preference for a sentence ending, capped at 1.6x the floor. On an
unpunctuated transcript the preference never fires, so clips routinely began
mid-explanation.

---

## 2. Architecture

```
transcript entries (1-5s each, cut for display width)
        |
        v
  build_sentences()                     semantic_segmenter.py
        |   punctuation, or pause + length when there is none
        v
  SENTENCES (start, end, text)
        |
        v
  segment_semantically()                semantic_segmenter.py
        |   TextTiling depth over SBERT block similarity
        v
  SEMANTIC SEGMENTS  <- the unit that is selected and cut
        |
        +---------------------------+
        |                           |
        v                           v
  extract_concepts()          (segment embeddings, reused)
  concept_extractor.py
        |   overlapping chunks -> Ollama JSON -> SBERT merge -> global rank
        v
  CONCEPTS (name, importance, reason, evidence, timestamps)
        |                           |
        +------------+--------------+
                     v
            select_segments()        coverage_selector.py
                     |   budgeted submodular maximisation
                     v
            SELECTED SEGMENTS
                     |
        +------------+------------+
        v                         v
  compute_selection_metrics()   generate_highlight_reel()
  summary_metrics.py            video_service.py (unchanged)
```

### 2.1 Semantic segmentation — `semantic_segmenter.py`

Boundaries are derived, never hardcoded. For each gap between sentence *i* and
*i+1*, the block of 3 sentences before is compared against the 3 after using
SBERT centroid cosine. A gap that is a local minimum *and* below the
transcript's mean similarity is a topic shift.

- A boundary is honoured only if both sides clear `SEGMENT_MIN_SECONDS`.
- A boundary is *forced* at `SEGMENT_MAX_SECONDS`, placed at the weakest gap in
  the legal window — a forced cut at the least-connected point beats one at an
  arbitrary word count.
- A too-short trailing segment is folded into its neighbour. Nothing is
  discarded; discarding is what made the old grouper lose whole minutes.

Every segment starts at a sentence start and ends at a sentence end, so a clip
can never open or close mid-sentence. `completeness` is 1.0 by construction.

### 2.2 Concept extraction — `concept_extractor.py`

Hierarchical, so the full transcript never goes to the LLM:

1. Chunk into ~450-word overlapping windows carrying their time range.
2. One Ollama call per chunk, `format: json`, asking for concept name,
   importance, reason and a supporting quote.
3. Merge duplicates: exact normalised names first, then SBERT agglomerative
   clustering of `"name. reason"`.
4. Rank globally: `importance x log(support) x sqrt(temporal spread)`.

Design decisions worth knowing:

- **Chunks are sampled evenly, never truncated.** Above `MAX_LLM_CHUNKS` the
  chunks are spread across the whole timeline. Taking the first N would
  reintroduce exactly the beginning bias this project exists to remove.
- **The merge threshold self-calibrates.** An absolute cosine threshold is not
  portable between encoders: `all-MiniLM-L6-v2` spreads unrelated short strings
  around 0.2-0.4 while the configured `BAAI/bge-base-en-v1.5` packs them above
  0.7. Tuned for the former, 0.72 merged every concept of a real 25-minute video
  into a single cluster named "work". The operating threshold is now the higher
  of that floor and the p95 of the *observed* pairwise similarities.
- **Concurrency is bounded to 2.** Not a throughput knob — a correctness one.
  Ollama serialises generation, so firing 14 chunk requests at once puts twelve
  in a queue where they burn their per-chunk timeout waiting rather than
  generating. Every chunk then "times out" against a perfectly healthy daemon.
- **A total timeout keeps what finished.** `asyncio.wait` returns
  `(done, pending)`; the earlier `wait_for(gather(...))` raised and discarded
  every completed chunk along with the slow one.
- **The HTTP timeout is set below the asyncio one.** `asyncio.wait_for` cannot
  kill a thread started by `asyncio.to_thread`, so if the asyncio timeout fired
  first the request would keep generating and keep holding a daemon slot.

Fallback chain: Ollama unavailable or unproductive -> TF-IDF keyphrases (with a
spoken-filler stop list on top of sklearn's written-English one) -> empty list,
after which the optimizer runs on relevance and coverage alone.

### 2.3 The optimizer — `coverage_selector.py`

Maximise total value under a time budget, where value is **submodular** — the
gain from adding a segment shrinks as similar material is already selected. That
single property yields diversity, redundancy avoidance and coverage without
separate machinery for each.

```
value(S) = W_CONCEPT   * concept_coverage(S)               <- facility location
         + W_SEMANTIC  * relevance(S) * (1 - redundancy)   <- MMR-discounted
         + W_COVERAGE  * temporal_coverage(S) * value(S)   <- concave, value-gated
         + W_COHERENCE * coherence(S)
         - W_REDUNDANCY * redundancy(S)
         - W_DURATION  * relative_length(S)
```

Selection is **cost-benefit greedy**: each step takes the best marginal gain
*per second*, not the best absolute gain. That stops one 90-second segment from
eating a 300-second budget, and it is the standard `1/2(1 - 1/e)` approximation
for budgeted submodular maximisation.

Four decisions that took measurement to get right:

1. **Coverage is concave, not a quota.** `sum over bins of sqrt(seconds in bin)`.
   Adding the first 30s to an empty bin gains `sqrt(30) = 5.48`; adding 30s to a
   bin holding 60 gains `sqrt(90) - sqrt(60) = 1.74`. Under-represented regions
   are worth ~3x more, and no bin is ever mandatory.

2. **Coverage is normalised by a typical segment, not a whole bin.** A bin of a
   25-minute video is 150s while a segment is 20-90s, so normalising by the bin
   caps a virgin-region segment at `sqrt(30)/sqrt(150) = 0.45` while relevance
   still spans `[0, 1]` — coverage would be permanently outranked by the very
   signal causing the bias.

3. **Coverage is gated by the segment's own value.** Rewarding an empty region
   unconditionally turns the coverage term into a quota: dead air scores full
   coverage credit for being somewhere nothing else is, and the reel fills with
   silence and ad reads. The reward is scaled by `max(relevance, concept
   affinity)`, with a floor so merely-average material in a late region is not
   starved.

4. **Redundancy discounts relevance before it is also penalised.** Subtracting a
   penalty alone is not enough: a segment identical to one already selected still
   scored *full* relevance, because relevance asks "is this on-topic?" and a
   duplicate of an on-topic segment trivially is. The tenth explanation of
   overfitting was claiming credit for being about overfitting.

Two guards:

- `OVERSHOOT_TOLERANCE` (8%) — a segment may exceed the remaining budget rather
  than be truncated. Preserving a complete thought beats hitting an exact second.
- `SELECT_MIN_BUDGET_FILL` (0.90) — the optimizer may stop early when nothing
  left adds value, but only once the reel is 90% built. Without this guard, dense
  material where every segment resembles every other drives the best marginal
  gain negative after a handful of picks and the job ships a near-empty reel.
  That is not hypothetical: job `5b8d9ffc` returned 49 seconds against a
  600-second budget.

### 2.4 Summarization policy — `summarization_policy.py`

Compression and coherence are now separate questions.

| Condition | Action |
|---|---|
| `words > target * 1.15` | `compress` — hierarchical BART, unchanged |
| within budget, incoherent | `rewrite` — strip artifacts, drop restatements, length-preserving BART |
| within budget, coherent | `clean` — remove scaffolding, no model call |
| empty | `pass` |

Coherence is assessed by three independent symptoms, any one of which fails:
connective density (sentence-initial **and** mid-sentence), fragment rate, and
adjacent-sentence self-similarity.

Forcing BART on everything was the other obvious fix and is worse: on an already
clean 300-word narrative a compression model drops real content and costs
seconds for nothing.

The dedup pass inside `rewrite` is bounded by `MAX_DEDUP_LOSS` (50%). A pass
that would delete most of the text has mistaken structurally similar sentences
for restatements; shipping a summary with 90% of its content removed is a worse
failure than leaving some repetition in.

### 2.5 Metrics — `summary_metrics.py`

Every claim is checkable. Computed once per job, stored on the job document, and
returned by `GET /api/v1/merge/{job_id}/result` as `selection_metrics`.

Reported: requested vs actual duration, duration accuracy, segment count, cut
count, timeline coverage %, deciles occupied, the full decile histogram,
first/second-half share, unique concepts, average concept importance, redundancy
%, earliest and latest timestamp, and min/avg/max segment length.

**Redundancy is relative, not absolute.** Cosine similarity between two passages
of one podcast is high simply because they are one podcast in one voice on one
subject, and how high depends on the encoder. Scoring against a fixed floor
reported 59% redundancy for a selection that was in fact more diverse than the
source it came from. The figure is now measured against `baseline_similarity` —
the mean nearest-neighbour similarity across *all* candidate segments of the
same video — so it answers the question actually being asked: are these clips
more alike than an arbitrary handful from this video would be? 0% means at or
below the video's own baseline.

---

## 3. Duration modes

One optimizer serves every mode. Only the budget changes.

| Minutes | Mode | Summary target | Reel budget |
|---|---|---|---|
| 2 | Express | 300 words | 120 s |
| 5 | Quick Highlights | 750 words | 300 s |
| 10 | Key Concepts | 1500 words | 600 s |
| 15 | Balanced Summary | 2200 words | 900 s |
| 20 | Detailed Summary | 2800 words | 1200 s |
| 30 | Comprehensive Summary | 4200 words | 1800 s |

---

## 4. Configuration

All in `.env`; defaults in `backend/core/config.py`.

| Setting | Default | Meaning |
|---|---|---|
| `ENABLE_SEMANTIC_SELECTION` | `true` | Master switch; `false` restores the legacy scorer |
| `ENABLE_CONCEPT_LLM` | `false` | Ollama concepts; `false` uses TF-IDF keyphrases (see below) |
| `CONCEPT_CHUNK_TIMEOUT_SECONDS` | `45` | Wall clock for one Ollama call |
| `CONCEPT_TOTAL_TIMEOUT_SECONDS` | `300` | Wall clock for the whole concept stage |
| `CONCEPT_TOP_K` | `25` | Concepts kept after global ranking |
| `SEGMENT_MIN_SECONDS` | `20` | Floor for one complete thought |
| `SEGMENT_MAX_SECONDS` | `90` | Ceiling for one complete thought |
| `SELECT_CONCEPT_WEIGHT` | `0.35` | Explains a high-importance concept |
| `SELECT_SEMANTIC_WEIGHT` | `0.20` | On-topic for the video overall |
| `SELECT_COVERAGE_WEIGHT` | `0.25` | From an under-represented region |
| `SELECT_COHERENCE_WEIGHT` | `0.10` | Clean, complete thought |
| `SELECT_REDUNDANCY_PENALTY` | `0.25` | Says what an already-picked segment said |
| `SELECT_DURATION_PENALTY` | `0.05` | Mild bias toward shorter picks |
| `SELECT_MIN_BUDGET_FILL` | `0.90` | How full before an early stop is allowed |

Concept + coverage together (0.60) deliberately outweigh raw relevance (0.20).
Relevance alone is what produced the beginning-heavy selections: early segments
introduce the topic and therefore look most similar to any summary of it.

---

## 5. Failure handling

Every stage degrades rather than failing the job.

| Failure | Behaviour |
|---|---|
| No timestamps in transcript | `build_semantic_segments` returns `[]`; legacy scorer runs |
| Video shorter than the budget | All segments kept, overlaps still dropped |
| Very short video | Single segment; segmentation short-circuits |
| SBERT unavailable | Duration-only boundaries; concept and redundancy terms disabled |
| Ollama down or slow | TF-IDF keyphrase concepts |
| Ollama returns junk | `_parse_json` returns `None`; that chunk contributes nothing |
| No concepts found | Optimizer runs on relevance + coverage + coherence |
| Segment longer than remaining budget | Skipped, never truncated |
| Overlapping candidates | Dropped after the overlapping pick is taken |
| Duplicate concepts | Merged by name, then semantically |
| Concept spanning two chunks | Chunk overlap (15%) plus semantic merge |
| Whole semantic pipeline throws | Caught in `merge.py`; legacy scorer runs |

---

## 6. Running it

```bash
# Backend. .env changes need a restart — uvicorn --reload only watches .py
venv/bin/python -m uvicorn backend.main:app --reload --port 8000

# Optional: Ollama for LLM concept extraction
ollama serve && ollama pull llama3.2:3b

# Tests (no model downloads, no network)
venv/bin/python -m pytest tests/ -q
```

Submit a job:

```bash
curl -X POST http://localhost:8000/api/v1/merge \
  -H "Content-Type: application/json" \
  -d '{"video_ids":["VIDEO_ID"],"target_duration_minutes":10,"generate_video":true}'
```

The result carries the new fields:

```
GET /api/v1/merge/{job_id}/result
  -> concepts[]                 ranked concepts with timestamps and reasons
  -> selection_metrics{}        the validation report in section 2.5
  -> selection_trace[]          per-pick gain breakdown
  -> summarization_decision{}   which policy branch ran, and why
  -> selection_mode             "semantic" or "legacy"
```

---

## 7. Known limitations

- **The LLM concept path is off by default, and that is a hardware verdict.**
  Benchmarked on this machine, one chunk per row:

  | Chunk | Prompt tokens | Generated | Time |
  |---|---|---|---|
  | 450 words | 799 | 99 | 179.7 s |
  | 700 words | 1107 | 175 | 183.9 s |

  About 180 s per chunk, and the split shows why: the cost is prompt
  evaluation, not generation, so capping `num_predict` does not help. (A repeat
  of the first row returned in 66.8 s, but only because an identical prefix was
  still in Ollama's KV cache — in a real run every chunk is different text, so
  that figure does not apply.) A 25-minute video is 14 sampled chunks, roughly
  21 minutes at two in flight, before the stage times out and falls back
  anyway. That is the same conclusion this codebase already reached for
  `ENABLE_OLLAMA_ENRICHMENT`.

  The TF-IDF fallback is not a stub: with the spoken-filler stop list it pulls
  real domain vocabulary out of a real podcast — on an 82-minute sleep episode,
  *light, sleep, melatonin, sunlight, cortisol, adenosine, caffeine*. What it
  cannot give you is the LLM path's `reason` and `evidence` fields, or a concept
  named in words the speaker did not literally use. Set
  `ENABLE_CONCEPT_LLM=true` on a GPU machine; the code path is complete and
  covered by tests.
- **Segmentation adds one SBERT pass** over every sentence in the transcript.
  The segment vectors are reused by the optimizer so there is only one pass, but
  it is still work the legacy path did not do.
- **Diarisation is not used.** Speaker changes are a strong boundary signal and
  are currently invisible to the segmenter.
- **Visual signal is off by default** (`MERGE_ENABLE_VISUAL_SCORING=0`) and the
  semantic path does not consume keyframes at all.
- **Coverage is measured on the transcript timeline**, so long unspoken stretches
  (music, demos) count as timeline the optimizer will try to represent.
