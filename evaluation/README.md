# Selection evaluation harness

Measures the semantic selector against a hand-authored gold standard. Nothing
here changes the pipeline; it only scores it.

## The dataset

`gold.json` — 103 important concepts across 7 videos and 5 genres:

| video | genre | length | concepts |
|---|---|---|---|
| `7eh4d6sabA0` | tutorial (Python ML) | 50 min | 16 |
| `8wmn7k1TTcI` | tutorial (DSA arrays) | 54 min | 15 |
| `nm1TxQj9IsQ` | podcast (Huberman, sleep) | 82 min | 17 |
| `E4rTyhYfZhE` | interview (Robbins x Lembke) | 79 min | 20 |
| `kyQ0CRkYhy4` | technical lecture (neural nets) | 57 min | 15 |
| `jGwO_UgTS7I` | technical lecture (CS229) | 75 min | 9 |
| `HVqWN7IVzwU` | educational/general (shiny object syndrome) | 39 min | 11 |

Each concept has a tier (`core` = the video is materially incomplete without it,
`secondary` = worth having) and the time windows where it is substantively
discussed.

**The gold set is hand-authored from reading the transcripts.** It is
deliberately NOT derived from TF-IDF, SBERT or anything else the pipeline uses —
otherwise the evaluation would be scoring the system against itself. `skim.py`
produces the condensed timestamped read used to write it.

For `HVqWN7IVzwU` the author enumerates his nine points verbatim near the end, so
that gold set is author-declared rather than annotator-interpreted.

## Metrics

| metric | definition |
|---|---|
| concept recall | tier-weighted share of gold concepts a selection touches (>= 8s of a window) |
| concept precision | share of selected time that falls inside some gold window |
| redundancy | share of gold-hit time spent re-covering an already-covered concept |
| temporal coverage | deciles of the source occupied |
| complete-thought | share of segments starting AND ending on a sentence boundary with >= 2 sentences |
| mid-sentence cuts | segment boundaries not on a sentence boundary |
| duration accuracy | 1 - |actual - reachable| / reachable, where reachable = min(budget, selectable pool) |

## Running

    venv/bin/python evaluation/evaluate.py     # 7 videos x 5 durations x 3 objectives -> results.json
    venv/bin/python evaluation/analyse.py      # overall / per-genre / per-duration tables
    venv/bin/python evaluation/sweep.py        # coverage-weight sweep + leave-one-genre-out

`sweep.py` caches each video's analysis to `analyses.pkl`, so re-running the
sweep is fast. Delete that file if the segmenter or concept extractor changes.

## Headline finding

Coverage weight 0.35 (concept 0.25) beat the shipped 0.25/0.35 on 28 of 35
video x duration cells (sign test p = 0.00003), and leave-one-genre-out selected
0.35 for every held-out genre. See the conversation report for the reasoning.
