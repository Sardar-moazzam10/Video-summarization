# VidFusion: architecture, functionality, rights, and FYP readiness audit

Audit date: 19 September 2026. Reviewed revision: `28a8398`.

This is an audit and proposed implementation plan, not a declaration that the proposed fixes are implemented. Application source was not changed during this review. The supplied project brief was read alongside the implementation; where they disagree, executable code and observations take precedence.

## 1. Verdict and product purpose

VidFusion has a substantial working prototype, including real single-video and multi-video highlight rendering. It is not yet ready for public deployment. Replacing the entire stack would waste useful work: the largest obstacles are incorrect cross-source metadata, broken workflow integration, incomplete authorization, fragile job execution, and unsupported quality/copyright claims.

Recommended positioning:

> VidFusion helps students, educators, and creators find important moments in long speech-based videos, combine useful material across sources, and produce traceable summaries and editable short clips from material they are authorized to use.

The user problems are time spent watching long recordings, finding a specific explanation, removing repetition across recordings, and manually editing reusable clips. A timestamped result is valuable even when generating another video is unnecessary. Students primarily need understanding and navigation; creators additionally need editing, licensing records, and export controls.

Start with lectures, tutorials, interviews, and podcasts. Do not promise equally good results on sports, silent demonstrations, music videos, visually dependent recordings, every language, arbitrary input lengths, or guaranteed viral shorts.

## 2. What was actually verified

Evidence types below are deliberately separate. Reading a route is not an end-to-end test, an existing output is not a fresh generation, and a mocked browser workflow is not a live integration test.

| Check | Observation | What this establishes |
| --- | --- | --- |
| Fresh backend suite: `venv/bin/python -m pytest tests/ -q --timeout=60` | 292 passed, 2 failed, 291 warnings; 188.27 seconds | Broad regression coverage, but the suite is not green |
| Additional backend smoke suite: `backend/tests/test_main.py` | 1 passed | This test directory is outside the configured main test path |
| Previously run frontend checks on this same revision | 40 tests in 5 suites passed; production build succeeded with 7 ESLint warnings | Frontend compiles; does not prove all browser flows work |
| Live `/health` | HTTP 200 | API liveness only, not database/model readiness |
| Live duration profiles | 5, 10, 15, 20, 30 minutes | Actual selectable summary-duration modes |
| Live existing single/multi job result endpoints | HTTP 200, completed semantic jobs, output-video URLs | Stored jobs can be retrieved; these were not newly generated jobs |
| Live transcript URL request | 206 entries; `source=youtube_api`, `cached=true` | The endpoint accepts a full YouTube URL and returns this cached transcript |
| Real Transcript page in Chrome | URL submission displayed transcript/download controls | Browser-to-backend cached transcript path works |
| Keywords browser workflow with controlled network fixtures | Summarize navigated to an unregistered route, then `/login` | Reproducible frontend routing defect; fixtures did not create real jobs |
| Fresh synthetic render through current `VideoService` | Two source clips produced a 4.021333-second H.264/AAC 1280×720 MP4; full FFmpeg decode succeeded | Current trimming/concatenation works on this small controlled input, not a test of AI quality or YouTube retrieval |
| Six existing end-to-end MP4 artifacts re-probed | See below | Real summary media exists, not just JSON/status simulations |

The browser used a synthetic localStorage user and intercepted history writes. This was not a real login/security test. No real account was created, reset, or deleted to demonstrate vulnerabilities.

The two backend failures are:

- `test_language_abort_safety_handles_none`: patches `backend.api.merge.transcription_service`, which is not present, and fails before exercising the intended behavior.
- `test_selector_stops_early_for_negative_gain`: reads nonexistent `SelectionResult.selected_duration`; the actual field is `total_duration`. The observed trace also contains positive gains, so simply renaming the assertion will not prove negative-gain early stopping.

An isolated daemon-stub test that appeared to hang inside the restricted execution environment passed outside it in 0.53 seconds. The earlier apparent hang should not be treated as an established project defect. Several tests load actual models/indexes, so the distinction between unit and integration tests needs improvement.

### Existing media evidence

These artifacts predate this audit. Durations were freshly measured with `ffprobe`.

| Artifact | Input sources / represented sources | Requested duration | Actual MP4 duration | Written-summary words |
| --- | --- | --- | --- | --- |
| `e2e_5m.json` | 1 / 1 | 5 minutes | 287.39 seconds | 90 |
| `e2e_10m.json` | 1 / 1 | 10 minutes | 579.59 seconds | 171 |
| `e2e_15m.json` | 1 / 1 | 15 minutes | 873.25 seconds | 382 |
| `e2e_multi_5m.json` | 3 / 2 | 5 minutes | 286.59 seconds | 75 |
| `e2e_multi_10m.json` | 3 / 3 | 10 minutes | 578.96 seconds | 134 |
| `e2e_multi_15m.json` | 3 / 3 | 15 minutes | 801.79 seconds | 119 |

The corresponding media is under `audio_cache/highlights/`. The five-minute multi-source job omits one source; that can be legitimate under global selection, but the UI must explain it. Every inspected multi-source artifact also contained three concept windows whose end preceded their start: evidence of the source-timeline defect described below.

These results do not establish consistently coherent edits, exact requested durations, good abstract quality, fresh uncached network reliability, or success at every advertised duration. Some script-based historical tests bypass HTTP validation and mock sleeps. A full fresh, permission-cleared browser-to-render test remains a release gate.

## 3. Feature inventory

| Feature | Current status | Main qualification |
| --- | --- | --- |
| Single-video summary MP4 | Implemented; real output verified | Boundary quality and summary grounding need evaluation |
| Multi-video summary MP4 | Implemented; real output verified | Serious cross-source timestamp and ordering defects |
| Duration selection | Implemented | Options are **5, 10, 15, 20, 30 minutes**, not 5–30 keywords; duration is currently approximate |
| URL-to-transcript page | Implemented; cached live browser path verified | Retrieval errors are masked; uncached availability/language behavior varies |
| Keywords search | Partially implemented, not an integrated working feature | Literal per-caption matches, broken merge navigation, query discarded during merge |
| Written summary/enrichment | Implemented with fallbacks | Quality/length inconsistent; some labels and metrics overclaim |
| Output video/audio retrieval | Implemented | Ownership and retention protection are inadequate |
| Reel subtitle export | Incomplete | Route exists, but reviewed merge jobs have no generated subtitle path |
| Accounts/history/admin | Implemented but unsafe for deployment | Authorization/reset/signup vulnerabilities |
| Local-video upload | Missing from the main processing workflow | Needs source abstraction, validation, storage, and rights records |
| Purpose-built vertical shorts | Missing | A short highlight reel is not a complete shorts workflow |
| Rights management and publishing gate | Missing | No defensible copyright-safety mechanism |
| Direct social publishing | Missing | Needs platform-specific OAuth, approvals, consent, and status handling |
| Chat/assistant/contact extras | Mixed/optional | Canned assistant claims are inaccurate; contact success UI does not send a message |

There is no meaningful “X% complete” figure from counting pages. Section 11 instead defines 12 bounded implementation work packages with acceptance conditions.

## 4. Present architecture and algorithm

### Actual stack

- Frontend: React 18, React Router, Create React App/react-scripts, Tailwind, Framer Motion.
- Backend: one FastAPI application in `backend/main.py`, routing authentication, transcripts, merging, search, and chat.
- State: MongoDB through Motor; jobs and accounts in the database; media/model caches on local disk; FAISS for vector retrieval.
- Transcript acquisition: YouTube caption approaches with yt-dlp/Whisper fallback; translation attempts and language gating.
- Semantic representation: `BAAI/bge-base-en-v1.5` sentence embeddings, semantic segmentation, TF-IDF concept extraction by default, optional local-model extraction.
- Selection: global duration-budgeted greedy scoring combining concept coverage, relevance, temporal coverage, coherence proxies, and redundancy penalties.
- Text generation: `sshleifer/distilbart-cnn-12-6` for the principal written-summary path. A separate legacy T5-small path is used for transcript preview summaries.
- Media: FFmpeg/FFprobe, existing audio/visual helpers, source-video download/cache, original-audio extraction from the rendered reel.
- Optional local LLM: Ollama; concept extraction and merge enrichment are disabled by default for CPU practicality.

The README, viva notes, some comments, and the canned assistant describe different generations of this architecture. Flask, T5, random merging, ElevenLabs, CLIP, MiniLM, and Ollama should not be presented as universally active components of today's principal pipeline.

### Main video-enabled workflow

1. Validate a merge request and available source durations; persist a job and schedule an in-process background task.
2. Obtain timestamped transcripts, attempt translation, and determine supported language capabilities. Indexing is best effort.
3. Run first-pass transcript fusion to produce a relevance reference.
4. Build semantic segments per source, extract concepts from the pooled segments, and select against a global time budget.
5. Download/resolve media, convert selections to clips, and render a highlight reel. Save video readiness before all text work finishes.
6. Fuse selected text again, summarize it with BART, and produce local enrichment. Optionally extract the original reel audio.
7. Persist results; preserve a usable video when text generation fails, using partial-success behavior.

The video-first partial-success design is worth keeping. However, video-disabled requests use a different text path; do not claim every mode summarizes only rendered clips.

### Highest-impact algorithm defects

**A. Concepts lose their source identity.** In `backend/api/merge.py:1055`, source-local segments enter a global pool. `backend/services/concept_extractor.py:228` chunks that pool without retaining a source ID. A small reproduction with source A at 300–330 seconds followed by source B at 0–30 seconds yielded a chunk starting at 300 and ending at 30, with no `video_id`.

Candidate-window and affinity logic in `backend/services/coverage_selector.py:207` and `:380` also compares bare timestamps across sources. Consequently, a concept at 60 seconds in A can influence unrelated content at 60 seconds in B. The fix is source-local chunking and `ConceptOccurrence(source_id, start, end)` records, followed by global merging of concept meanings—not global merging of unqualified timestamps.

**B. Narrative order is discarded.** Selection can invoke narrative ordering, but `backend/api/merge.py:1185` sorts selected segments again by `(video_id, start_time)` before rendering. Preserve one explicit ordered edit list. Consolidate overlapping intervals per source before narrative ordering; `_merge_overlapping_clips` also needs correct reverse-order handling.

**C. Selected content and rendered content can diverge.** Failed downloads filter highlights without rerunning allocation/recomputing all reporting. Trimming can skip failed clips while summaries and metrics still reflect the original selection. Build summaries, captions, provenance, and final quality reports from the exact successfully rendered edit list. Return explicit omissions/partial success; never silently describe footage that was not exported.

**D. Approximate length is confused with quality.** The selector's minimum-fill policy can postpone negative-gain stopping until roughly 90% of budget. This conflicts with an unconditional “never add filler” claim. Define duration as an upper budget, allow a shorter coherent answer, and explain any substantial shortfall. Offer different behavior only as an explicit user option.

**E. Repeated compression can lose useful facts.** First-pass fusion, selection, second-pass fusion, and final abstraction can compound omissions. Preserve selected source facts and qualifiers. Benchmark per-topic summarization with source links and an extractive fallback against the present pipeline before replacing the model.

**F. Performance work should precede larger models.** Some CPU-heavy operations remain synchronous inside job orchestration. Embeddings are recomputed, some pairwise operations grow quadratically, the relevance reference is truncated, and cross-encoder loading is costly. Cache by media hash, transcript revision, model revision, and preprocessing configuration; profile stage latency and memory before optimizing.

**G. Language gating is incomplete assurance.** Preventing an English summary on unsupported text does not make an English embedding model suitable for selecting Hindi/Urdu segments. Preserve original and translated transcripts separately and declare support per operation. Mixed-language failures must be visible per source rather than silently implying uniform support.

The selector is a reasonable FYP engineering approach. It should be described as a coverage-aware budgeted heuristic unless the exact implemented objective and constraints are formally proved to satisfy a stated approximation theorem. Existing adaptive scaling, penalties, and grouped candidates are not enough evidence for a universal submodular guarantee.

## 5. Keywords: the most valuable use case

Rename it **Find moments** or **Search inside videos**.

Example: a student selects three lectures and asks “Where is overfitting explained?” VidFusion returns short, timestamped passages from those recordings, lets the student jump to the originals, and optionally produces a focused recap. A creator can similarly find every discussion of a product feature in their own recordings.

This is more useful than finding videos whose captions happen to contain a string. It also avoids transcribing many unrelated public videos just to discover whether they mention a keyword.

### Why today's page is incomplete

- It searches YouTube, retrieves transcripts for candidate videos, and performs literal matches within individual caption entries.
- A phrase split between “we study neural” and “networks today” is missed. This was reproduced with the actual matching helper.
- It does not use the project's FAISS search route for semantic moment retrieval.
- `src/SearchByKeywordsPage.js:241` sends video IDs and duration to merge, but not the query or matched intervals.
- The active handler navigates to `/merged-podcast-player`, which is unregistered; the browser reproduction ended at `/login`.
- Backend vector-search results omit the timestamps that indexing can store.
- Transcript failures are converted to empty arrays by `src/api.js`; “unavailable transcript” can look like “no relevant match.”

### Proposed workflow

1. Select owned/permission-cleared videos from a library; process/index each once.
2. Enter a question or phrase, with suggested topic chips as optional shortcuts.
3. Search overlapping sentence windows using lexical matching plus BGE embeddings. Rank fusion is a useful low-cost baseline; it does not require adopting Elasticsearch. [RRF reference](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion).
4. Return source ID/title, start/end timestamps, quoted evidence, and a seek link. Merge nearby relevant windows while preserving complete thoughts.
5. Add selected moments to a focused summary. Pass query intent through the API and enforce a calibrated relevance threshold.
6. If insufficient relevant material exists, return fewer results or a shorter summary—not unrelated filler. Clearly distinguish no match, retrieval failure, unsupported language, and processing still underway.

Do not label cosine similarity as a probability of correctness. Evaluate exact terms, paraphrases, cross-caption phrases, multilingual queries if supported, and irrelevant queries. User/account filtering must happen before results are returned.

There is currently no verified 5–30 keyword-count setting. Keep keyword/topic count separate from summary duration if added later; a user should not have to supply 30 words to obtain a useful result.

## 6. Free-resource technology decisions

“Free” should mean no mandatory paid API, with documented software/model licenses—not unlimited free compute or guaranteed public hosting.

| Component | Decision | Reason / verification required |
| --- | --- | --- |
| React, Router, Tailwind | Keep | Suitable for the application; no rewrite needed |
| Create React App | Migrate to Vite after core fixes | CRA was sunset; do this as an isolated tooling change, not a UI rewrite. [React announcement](https://react.dev/blog/2025/02/14/sunsetting-create-react-app) |
| FastAPI | Keep | Appropriate API layer; separate long-running processing from request workers. [Background-task guidance](https://fastapi.tiangolo.com/tutorial/background-tasks/) |
| MongoDB | Keep initially | Existing data model is adequate; access control matters more than changing databases |
| Motor | Migrate to PyMongo Async | Official docs say deprecated since May 2025, end of ordinary support May 2026, critical fixes until May 2027. [Motor docs](https://motor.readthedocs.io/en/latest/) |
| BGE-base English | Keep as measured baseline | MIT license; do not call it universally best or suitable for every language. Benchmark a smaller model only if latency requires it. [Model card](https://huggingface.co/BAAI/bge-base-en-v1.5) |
| FAISS | Keep for bounded local libraries | Preserve source/timestamps, isolate users, protect writes, and version indexes by exact embedding model/preprocessing—not dimension alone |
| TF-IDF concepts | Keep baseline | Cheap and deterministic; repair occurrence metadata and evaluate coverage before adding expensive extraction |
| DistilBART | Keep baseline | English summarizer with Apache-2.0 license; improve grounding and input construction first. [Model repository](https://huggingface.co/sshleifer/distilbart-cnn-12-6/tree/main) |
| T5-small preview path | Consolidate | One maintained summary service avoids inconsistent truncation and behavior |
| Whisper fallback | Benchmark faster-whisper | CTranslate2/int8 CPU inference, VAD, and word timing are promising; compare quality and speed on this machine, not another machine's advertised benchmark. [Official implementation](https://github.com/SYSTRAN/faster-whisper) |
| FFmpeg/FFprobe | Keep | Suitable rendering/probing tools; audit distribution licenses, especially GPL-enabled builds/libx264. [FFmpeg legal guidance](https://www.ffmpeg.org/legal.html) |
| Ollama / larger local LLM | Optional, off critical path | Existing CPU timings do not justify making it mandatory. A small Apache-2.0 model such as Qwen3-1.7B is a candidate experiment, not a proven upgrade. [Model card](https://huggingface.co/Qwen/Qwen3-1.7B) |
| NLLB fallback | Do not treat as unrestricted product dependency | Model is CC-BY-NC-4.0 and described for research, not production deployment. Academic experimentation is distinct from commercial product permission. [Model card](https://huggingface.co/facebook/nllb-200-distilled-600M) |
| Unofficial online translation | Avoid as a reliability/privacy foundation | No project-controlled availability guarantee; make external transfer explicit and optional |

For English MVP inputs, the existing model family is sufficient to establish a strong baseline. For Urdu/Hindi, benchmark a separately declared multilingual mode, including transcription, translation, retrieval, and summary quality. Switching embeddings requires a full reindex and language-specific evaluation. Quantized embeddings are another measured optimization option. [Sentence Transformers efficiency guidance](https://sbert.net/docs/sentence_transformer/usage/efficiency.html).

The inspected development machine has a Ryzen 5 PRO 3500U and approximately 13 GiB usable RAM. Start with one heavy job at a time, bounded input sizes, cached models, and a durable worker. Do not promise simultaneous long-video transcription, BART, a multi-billion-parameter LLM, and multiple renders without measuring peak memory.

Use a local/university machine for the FYP demonstration. Hugging Face's basic free Spaces allocation is CPU-based with nonpersistent storage; that is not an unlimited durable video-processing backend. Colab resources and runtimes are not guaranteed and are unsuitable as an always-on service. [Spaces overview](https://huggingface.co/docs/hub/spaces-overview), [Colab FAQ](https://research.google.com/colaboratory/intl/en-GB/faq.html).

## 7. Shorts: a practical implementation design

This feature should reuse ingestion, transcription, embeddings, source metadata, and rendering, but use a different selection objective from a long summary. A long summary covers many topics; a good short communicates one self-contained idea.

### MVP pipeline

1. Accept validated local uploads and other explicitly supported, authorized source inputs. Record language, duration, dimensions, owner, media hash, and rights status.
2. Obtain sentence and preferably word timestamps. Preserve the original audio and transcript.
3. Build contiguous candidate passages from the full source transcript, not just the long-summary selections. Start with configurable 30/45/60-second targets while allowing shorter complete passages.
4. Rank for a clear opening, useful information, standalone comprehensibility, complete ending, audio quality, and few context-dependent references. These are measurable heuristics, not proof of virality.
5. Select diverse candidates across the output set. Preserve caveats, negations, and disagreements; similarity alone must not erase a contradictory viewpoint.
6. Let users preview candidates, edit titles, and adjust boundaries with sentence snapping.
7. Export 9:16 video with conservative fit/padding or user-controlled cropping; keep slides readable. Face detection can assist later, but is not equivalent to identifying the active speaker. [MediaPipe face detection](https://developers.google.com/edge/mediapipe/solutions/vision/face_detector).
8. Add editable captions, downloadable SRT, local-output timestamps, audio-level normalization, and source/attribution metadata. Avoid adding music by default.
9. Download for manual publishing first. Add platform-specific OAuth publishing only after rights, authorization, and reliability gates pass.

If a recording has no suitable standalone moment, offer fewer/no clips and explain why. Do not manufacture a requested count through incomplete sentences or misleading combinations.

“Any length” must become a documented supported limit based on measurement: maximum file size, duration, resolution, disk usage, jobs per user, and runtime. Longer sources need chunking, resumable jobs, and checkpoint reuse. The minimum supported short clip should not be constrained by the existing five-minute long-summary mode.

YouTube supports Shorts up to three minutes under its current classification rules; keep platform presets configurable and recheck rules when publishing. Its help pages also announce a Content ID handling change effective 24 September 2026, which is later than this audit date. Do not confuse announced future behavior with current guarantees. [YouTube Shorts guidance](https://support.google.com/youtube/answer/15424877?hl=en), [rights-holder guidance](https://support.google.com/youtube/answer/13053317?hl=en-GB).

## 8. Copyright and platform compliance

There is no honest way to guarantee that arbitrary third-party videos become safe to republish after summarization. Cropping, shortening, subtitles, credit, disclaimers, or AI processing do not automatically create permission. [YouTube copyright myths](https://support.google.com/youtube/answer/2797449?hl=en).

This is product-risk guidance, not a legal opinion on a particular work. Obtain jurisdiction-specific legal review before launching public redistribution features. U.S. fair use is fact-dependent, with no universally safe percentage or number of seconds. Pakistan has its own exceptions; the historical WIPO-hosted text is not a substitute for checking the currently applicable consolidated law. An academic project is not a blanket authorization for users to republish clips commercially. [U.S. Copyright Office](https://copyright.gov/fair-use/), [Pakistan ordinance text on WIPO Lex](https://www.wipo.int/wipolex/en/text/129350).

### Four separate questions

| Question | What VidFusion must not assume |
| --- | --- |
| Does the user have reproduction/adaptation/distribution rights? | A public URL or upload checkbox is proof of ownership |
| Is the acquisition method permitted by the source platform? | Creator permission automatically authorizes every downloader/API use |
| Could Content ID or a rightsholder make a claim? | Licensed content is guaranteed never to receive a claim |
| Is the output monetizable under platform policies? | Copyright permission guarantees monetization |

The YouTube API developer policies restrict downloading/importing/caching audiovisual content and separating audio without the required authorization. The current combination of API discovery and yt-dlp/audio extraction therefore needs a platform-policy review; it must not be marketed as an automatically compliant downloader. Prefer creator-uploaded originals for editing/publishing and official discovery/embeds for viewing. [YouTube developer policies](https://developers.google.com/youtube/terms/developer-policies).

The official captions-download endpoint requires appropriate authorization to edit the video. It is not a drop-in official route to arbitrary public transcripts. Public-caption scraping remains an availability/compliance risk, so support uploaded transcripts or authorized transcription sources. [Captions download documentation](https://developers.google.com/youtube/v3/docs/captions/download).

YouTube's reused-content/inauthentic-content monetization review is separate from copyright permission. A collection of lightly edited clips can fail monetization rules even when the uploader has permission. Added commentary is not itself a legal or monetization guarantee. [YouTube monetization policies](https://support.google.com/youtube/answer/1311392?hl=en).

### Source policy

- **User's own original recording:** preferred, but confirm music, slides, guest contributions, identifiable participants, and other embedded third-party material.
- **Written permission:** record whether editing, redistribution, commercial use, and the intended platforms are covered.
- **CC BY:** potentially suitable for adaptations with required attribution and conditions. Retain creator, title where provided, source, license/version, and modification information. Do not assume the uploader owns every embedded element.
- **Other Creative Commons licenses:** evaluate individually. NC restricts commercial uses, ND restricts sharing adaptations, and SA imposes additional conditions; do not label every CC source freely reusable.
- **Public domain:** record a verifiable basis and relevant jurisdiction; age alone or an uploader's label is insufficient evidence.
- **Unknown rights:** do not enable the publishing/export-for-publication workflow based on an unsupported assumption of permission.

License permissions can coexist with privacy, publicity, or other restrictions; Creative Commons licenses do not guarantee all necessary rights. [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), [Creative Commons FAQ](https://creativecommons.org/faq/).

### Required product controls

Create a rights record per source: owner, acquisition method, creator/source URL, license and version, permission evidence, date, derivative/commercial/platform scope, and music/third-party declarations. Distinguish user attestation, verified metadata, and manual review; never imply a checkbox proves legal clearance.

Maintain an edit manifest mapping every output interval to its original source interval. Check every included source for a multi-video export, produce attribution text, and show unresolved restrictions before enabling publication. Add a complaint/removal process, retention controls, and deletion handling. These reduce risk; they do not guarantee legal safety.

Do not build a fake “copyright-free percentage” detector. YouTube's Content ID API is restricted to eligible partners and is not a universal free rights-clearance service. [Content ID API overview](https://developers.google.com/youtube/partner).

Manual export is the appropriate first milestone. Direct YouTube uploads require OAuth; uploads from qualifying unverified API projects are restricted to private visibility until an audit is passed. Publication must always require explicit user confirmation, with separately handled platform policies and errors. Music permissions may not transfer between platforms. [YouTube upload API](https://developers.google.com/youtube/v3/docs/videos/insert).

For the supervisor demonstration, use your own music-free recordings and participant permissions. This makes the actual technical contribution demonstrable without depending on an untested legal theory.

## 9. Security and deployment blockers

### P0: fix before exposing the application

1. **Public admin creation:** `backend/models/user.py:9` allows signup input `role=admin`; the signup path passes that role into account creation. A schema-only reproduction accepted it. Public signup must assign `user` server-side; privileged provisioning needs a separate protected process.
2. **Unbound password reset:** `backend/api/auth.py:65` accepts email/new password without requiring a validated, single-use reset authorization. Verification codes need secure generation/storage, expiry, attempt limits, and purpose binding; the reset must consume the verified token.
3. **Missing authorization/ownership:** user/profile/history operations and expensive/media/job routes do not consistently enforce authenticated ownership. `MergeJob.user_id` is optional and not assigned in job creation. Apply deny-by-default access checks and tests for user A accessing user B's records.
4. **Tracked credential:** `app/db_config.py` contains a credential. Do not reproduce it in documentation. Rotate it at the provider, remove it from source, and assess history exposure. Removing a file alone does not revoke the credential; rewriting history requires coordination.
5. **Signing-key documentation mismatch:** setup examples name `JWT_SECRET_KEY`, but settings expect `SECRET_KEY`. Missing configuration creates a random process key, breaking stable authentication across restarts/workers. Validate production settings at startup.

No account takeover or destructive account operation was executed during the audit. These findings come from route/service/schema inspection and non-mutating checks.

### P1: reliability and packaging

- FastAPI in-process background tasks are not a durable queue. A restart can strand jobs; CPU-heavy work can hurt API responsiveness. Add a separate bounded worker with persisted stages, leases/heartbeats, retry limits, cancellation, and restart recovery. Preserve video-first partial success.
- Protect FAISS writes and model concurrency; initially use one processing worker. Avoid exposing global search results across accounts.
- Centralize input validation, media probing, disk quotas, subprocess timeouts, and orphan cleanup. Future URL fetching must also prevent SSRF and unsafe redirect targets.
- SSE terminal handling needs `partial_success` and cancellation paths, not only completed/error. Admission limits should control expensive jobs separately from polling; a per-IP request counter is insufficient.
- Fix URL encoding and distinguish transcript failure from empty content. Resolve the configured-but-missing refresh-token endpoint contract.
- The Dockerfile omits root Python helpers imported by runtime paths, including the quality evaluator. It copies a frontend build into `static/`, but the FastAPI app does not mount/serve that SPA. It omits Tailwind/PostCSS configuration from the frontend build context and does not establish a usable remote API configuration.
- Compose does not provide complete production settings, durable input-video storage, or dependency readiness checks; MongoDB is published to the host unnecessarily for a public single-host deployment. Review network exposure rather than deploying defaults.
- Pin compatible dependencies and model revisions; remove reliance on changing “latest” downloader builds. Use a currently supported Node build image during the frontend migration.
- Add database/model/FFmpeg readiness separately from liveness. Test a clean installation rather than relying on a prewarmed developer environment.
- Make index migration non-destructive and explicit: the current startup dimension check can delete an index, while dimension alone cannot identify which embedding model produced it.

Keep a modular monolith plus a worker. There is no demonstrated need for Kubernetes, microservices, a paid vector database, or a large cloud GPU cluster for this FYP.

## 10. Evaluation and supervisor presentation

Existing automatic scores are useful diagnostics, not independent proof of quality. For example, `evaluation/benchmark_summarizers.py:66` calls source-word overlap “faithfulness”; it cannot detect a changed relationship or negation. Its concept coverage is also a weak lexical proxy. A high overlap score is not “97% factual accuracy.” A segmenter's own boundary labels do not establish human-perceived completeness.

Stored small BART/Ollama benchmarks suggest keeping BART as the CPU baseline, but they have few trials, failures, and insufficient independent evaluation. They cannot prove that the model is best generally. Historical sweep results must not be presented as fresh held-out validation.

### Minimum defensible evaluation plan

- Assemble a permission-cleared corpus spanning lectures, interviews, redundant multi-source material, and difficult audio; explicitly separate unsupported cases.
- Keep tuning and final evaluation sources separate. Record revision, configuration, model versions, hardware, language, and cold/warm cache conditions.
- Compare equal-budget baselines: first-N minutes, simple lexical relevance, semantic relevance, and the proposed coverage-aware selector. For multi-source selection, compare equal allocation with global allocation.
- Ask at least two human reviewers to assess topic coverage, complete thoughts, redundancy, coherence, factual consistency, and whether a short stands alone. Record disagreements, not just averages.
- Measure transcript WER where reference transcripts exist, retrieval relevance/Recall@k or nDCG, duration deviation, exact source provenance, artifact validity, processing-time/source-time ratio, peak RAM, success/partial-failure rate, and restart recovery.
- Test queries with no answer, phrases spanning captions, repeated timestamps across different sources, missing media, unsupported languages, short inputs, and tampered ownership IDs.
- Require every exported interval and caption to map to the final edit manifest. Report omitted sources, unsupported operations, and summary unavailability explicitly.

### Honest viva explanation

> We use pretrained speech and language models, rather than claiming to train a new foundation model. Our contribution is a source-aware pipeline that selects complete, useful passages under a time budget, reduces cross-video repetition, preserves traceability, and supports query-focused retrieval and rights-aware reuse. We evaluate its quality and runtime against simpler baselines.

That statement describes the intended corrected system. Until the source-tracking fixes land, present those as known limitations rather than completed achievements.

Demo sequence: own uploaded recording → transcript and timestamp jump → five-minute summary with source evidence → two-source summary with allocation explanation → query-focused moments → editable captioned short → rights/attribution export. Also demonstrate one graceful failure. Have a precomputed, clearly labeled backup; do not pretend cached output is newly generated.

Rewrite README, supervisor setup, viva notes, and UI claims from the verified implementation. Include architecture/data models, requirements, algorithm pseudocode, experiments, limitations, license inventory, reproducible setup, and a short demo script.

## 11. Implementation order: 12 work packages

These are planning units, not equal-size features or a percentage estimate. Packages 1–11 define the proposed FYP-ready scope; direct social publishing is a post-FYP extension unless explicitly required.

| ID | Work package | Acceptance condition |
| --- | --- | --- |
| 1 | Authentication, ownership, secrets | No public admin assignment; secure reset; cross-user requests denied; exposed credential rotated; stable signing configuration |
| 2 | Source-aware concepts and selection | No cross-source chunks/inverted ranges; source-qualified occurrences; regression tests with overlapping source timestamps |
| 3 | Ordered render manifest and grounded outputs | Render order preserved; summaries/captions/metrics reflect only successful clips; omissions explicit |
| 4 | Repair existing UI/API workflows | Keywords route fixed; duration contract consistent; transcript errors/URL encoding correct; refresh/progress behavior coherent |
| 5 | Uploads, library, and rights records | Validated owned uploads reach existing pipeline; storage quotas; source ownership; evidence/attribution and publication gating |
| 6 | Find moments and focused summaries | Timestamped hybrid retrieval; query reaches selector; no-match behavior; permission filtering and relevance tests |
| 7 | Durable processing and resource limits | Worker concurrency bounded; restart/cancel/retry tested; stage/model caches versioned; no silent stuck jobs |
| 8 | Shorts candidate selection | Complete standalone candidates; quality/diversity criteria; fewer/no-result handling; source-backed titles |
| 9 | Shorts preview, captions, and export | Editable bounds/crop/text; valid portrait MP4/SRT; synced captions/audio; attribution and rights checks |
| 10 | Reproducible deployment | Clean-install smoke test; frontend served correctly; supported pinned toolchain; readiness; persistent storage; no exposed database |
| 11 | Evaluation, documentation, and viva package | Held-out comparisons, human review, honest limitations, license inventory, reproducible demo and report |
| 12 | Optional platform publishing | OAuth/token protection; explicit publish approval; required platform audits; retry/status handling; no copyright/monetization guarantees |

Implementation should begin with packages 1–3, before adding another model or publishing feature. Package 4 provides visible usability wins. Establish uploads and rights before creator shorts, and complete worker/resource controls before advertising long inputs.

### Keep, defer, and retire

Keep the central summary/multi-summary/transcript flows, useful history/downloads, the duration budget, source references, and the existing local/free baseline models.

Add focused moment retrieval, owned uploads, source/rights tracking, reliable captioned shorts, and honest progress/failure states.

Defer mandatory local-LLM chat, broad automatic public-video scraping, advanced active-speaker reframing, every-language support, multi-platform automatic publishing, and arbitrary-length claims until the core is measured and stable.

Remove misleading UI claims and fake success behavior. Retire duplicate legacy servers and developer-only trim/test routes from the product entry points after checking dependencies. Archive useful experiments instead of deleting research or caches. A canned FAQ can remain only if accurately labeled and updated; it should not pretend to be a live AI assistant.

## 12. Boundaries of this audit

The review covered the supplied brief, principal frontend/backend flows, algorithm/services, configuration, deployment files, tests, selected stored evaluation artifacts, live read-only endpoints, browser diagnostics, and official external documentation. It is not a formal penetration test, exhaustive dependency-license audit, full legal clearance, or proof of every media/language/platform combination.

No new full-length uncached AI summarization benchmark, clean Docker deployment, public upload, or platform OAuth flow was completed. Those are explicit next-stage acceptance checks. No paid resource is required for the proposed local FYP baseline, but CPU time, storage, electricity, bandwidth, and any public hosting still have real operating constraints.
