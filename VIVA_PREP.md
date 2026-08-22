# VidFusion — Viva Prep Guide

A code-grounded prep guide for your final-year-project viva: what it does, exactly how it works stage by stage, why each tool was chosen, and how to answer honestly when a question goes past what you remember.

---

## 30-Second Pitch — say this first

> "VidFusion lets a user pick one or more videos on any topic, choose an output length — 5, 10, 15, or 20 minutes — and get back an AI-generated summary: a fused, deduplicated text narrative, key takeaways, and an automatically edited highlight video. Under the hood it runs transcript extraction, cross-video topic fusion, abstractive summarization, and importance-based clip selection — all with free, locally-run models, so there's no per-request API cost."

---

## 1. Core Features

- **Multi-video fusion** — select 1–10 videos on a topic; the system clusters shared ideas, removes cross-video repetition, and flags disagreements between sources.
- **Custom duration** — output length is user-chosen: 2, 5, 10, 15, or 20 minutes, controlling both summary length and highlight-video length.
- **Resilient transcripts** — 3-tier fallback: YouTube's own captions → yt-dlp-extracted subtitles → Whisper speech-to-text, so a missing-captions video still works.
- **Multilingual input** — non-English transcripts are auto-detected and machine-translated to English (NLLB-200) before fusion.
- **Auto-edited highlight video** — the most important moments (by relevance to the summary) are cut and stitched into one video with ffmpeg, narrated by TTS.
- **Semantic search + chat** — every processed video is embedded into a FAISS index; users can search across their library or ask a chat question answered by a local LLM grounded in the transcript.
- **Automated quality scoring** — two 0–100 scores (summary fidelity, video↔summary match) computed from keyword coverage, semantic similarity, and an optional LLM judge.
- **Free & local by design** — every model in the pipeline is open-source and runs on the student's own machine — no paid API required.

---

## 2. Pipeline Walkthrough

This is the true, code-verified order of operations for "user submits a job." Learn this sequence — it answers most "walk me through it" questions on its own.

| # | Stage | Tool | What happens |
|---|-------|------|---------------|
| 1 | **Submit & queue** | FastAPI BackgroundTasks | User picks videos + a duration; backend validates (max 10 videos), converts minutes to a hard seconds budget, saves a job record to MongoDB, and starts processing in the background. Frontend polls/streams for progress. `merge.py:146-201` |
| 2 | **Transcribe** | YouTube API → yt-dlp → Whisper | All videos transcribed in parallel. Each tries YouTube's transcript API first, then yt-dlp subtitles, then Whisper STT as a last resort. `merge.py:622, 1128` |
| 3 | **Normalize language** | langdetect + NLLB-200 | Language detected from first ~3,000 chars. Non-English transcripts machine-translated to English. `merge.py:634-695` |
| 4 | **Index for search** | BGE embeddings + FAISS | Transcripts embedded and written into the FAISS vector index immediately — powers Search and Chat later. `merge.py:698-709` |
| 5 | **Pick duration profile** | duration_profiles.py | Chosen minute value looks up a target word count (e.g. 10 min → ~1,500 words). `merge.py:719` |
| 6 | **Fuse across videos** | fusion_engine.py | The core "multi-video AI" step — see Deep Dive below. `merge.py:737` |
| 7 | **Summarize** | DistilBART | Fused narrative compressed further until close to target length. `merge.py:759` |
| 8 | **Enrich** | TF-IDF (default) / Ollama (optional) | TLDR line, 5 key takeaways, 3 chapters generated. Ollama version exists but is off by default — too slow on CPU. `merge.py:786-842` |
| 9 | **Build highlight video** | segment_extractor.py + ffmpeg | Source videos downloaded; segments scored by relevance to the summary; top non-overlapping segments packed to fill the time budget; stitched with ffmpeg; narration layered in. `merge.py:857-1061` |
| 10 | **Done** | MongoDB | Job marked complete; summary, TLDR, takeaways, chapters, and video persisted and served. `merge.py:576+` |

---

## 3. Tool Choices, Justified

Panels ask *"why this and not X"* more often than *"what is this."* Have the real reason ready for each.

| Tool | Role | Why this one |
|------|------|---------------|
| **FastAPI** | Backend framework | Async-native (important for parallel transcript fetching + long jobs), auto OpenAPI docs, faster than Flask for I/O-bound work. |
| **DistilBART** (`sshleifer/distilbart-cnn-12-6`) | Summarization | 306 MB vs. 1.6 GB for full BART-large, at ~95% of the quality — right trade-off for a laptop with no GPU. |
| **BGE-base-en-v1.5** | Sentence embeddings | Ranked #1 on MTEB benchmark in 2024 among comparably-sized models; used for fusion clustering, search, and chat retrieval. |
| **Ollama** (`llama3.2:3b`) | Local LLM (chat + judge) | Runs fully offline, no API key or per-call cost — replaced an earlier Gemini-API integration entirely. Required for a zero-budget project. |
| **Whisper** (`base`) | STT fallback | Only invoked when YouTube captions AND yt-dlp subtitles are both unavailable. "base" balances ~3.4x real-time CPU speed against accuracy. |
| **NLLB-200** (`distilled-600M`) | Translation | One open model covering 200 languages — avoids needing per-language-pair models. |
| **FAISS** | Vector search | In-process, no separate DB server to host — ideal for a self-hosted FYP deployment. |
| **MongoDB** | Primary database | Job records are naturally document-shaped (nested segments, variable fields per job) — fits better than rigid relational tables. |
| **ffmpeg** | Video assembly | Industry-standard, free, scriptable — no viable free alternative with comparable format support. |
| **edge-tts** | Narration voice | Free, no API key, notably higher quality than most offline TTS engines. |

---

## 4. Deep Dives

### 4.1 How multi-video fusion really works

The most technically interesting part of the project — most likely to get probed.

1. **Split → embed → cluster.** Every transcript is split into candidate sentences (5–100 words), embedded with BGE, and clustered **across all selected videos together** using agglomerative clustering on cosine distance — so a sentence from video A and a similar one from video C land in the same cluster regardless of source.
2. **Rank by cross-video importance.** Each cluster's importance score = `sentence_count × number_of_distinct_source_videos` — a topic three videos mention outranks one only one video covers.
3. **Deduplicate within a cluster.** Sentences are kept greedily only if their cosine similarity to every sentence already kept is below **0.82** — this removes near-identical statements repeated across videos.
4. **Detect disagreement between sources.** With 2+ videos, a small NLI (natural-language-inference) model compares statements from different videos in the same cluster and flags a contradiction on high-confidence `CONTRADICTION`, falling back to a keyword heuristic on error. Single-video jobs skip this — nothing to compare.
5. **Write the narrative.** Top clusters, in importance order, are stitched into one flowing narrative with transition phrases, stopping at the target word count.

*`fusion_engine.py:110-538`*

### 4.2 How duration control actually works

- **Text length**: fixed word-count target per profile (e.g. 10 min → ~1,500 words), passed into both fusion and summarization as a soft ceiling (~10-15% overshoot allowed, so sentences aren't chopped mid-thought).
- **Video length**: a separate mechanism entirely — minutes convert to a hard seconds budget; clips are greedily packed by importance score until the budget is filled (with a minimum gap so clips never overlap). Text length and video length are governed independently.

*`duration_profiles.py:84-177` · `merge.py:168-170, 719-720`*

### 4.3 How clips are selected for the highlight video

Designed as a 4-signal blend — semantic similarity to the summary (30%), keyword/TF-IDF overlap (15%), visual-quality via CLIP or audio-energy (35%), temporal-attention (20%) — but **visual scoring is off by default** for speed. Out of the box it runs a simpler **70% semantic / 30% TF-IDF** blend. Selection itself is greedy: segments sorted by score, highest-scoring added until the time budget fills, skipping anything that would overlap an already-chosen segment.

*`segment_extractor.py:180-393`*

### 4.4 How summary quality is measured

Two independent 0–100 scores:
- **Summary fidelity** — keyword coverage (do transcript's top TF-IDF terms appear in the summary?) + semantic coverage (SBERT similarity, transcript chunks vs. summary sentences) + optional LLM-judge (Ollama rates faithfulness/coverage/key-point recall).
- **Video↔summary match** — same three checks, but comparing selected clips' own transcript text against the summary.

Both are a plain, unweighted average of whichever sub-metrics ran — transparent and explainable rather than one opaque number.

*`evaluate_summary.py` · `merge.py:281-349`*

### 4.5 How "chat with your video" works

Standard RAG pattern: question embedded with the same BGE model → FAISS returns most similar indexed transcript chunks (cosine via normalized inner product) → top results assembled into a labeled context block → context + question sent to local Ollama with an instruction to answer only from context (and say so if not covered). If Ollama isn't running, it degrades gracefully — shows raw top-matching transcript snippets instead of failing.

*`chat.py:49-121` · `vector_store.py:224-268` · `ollama_service.py:58-66`*

### 4.6 Auth, briefly

Standard JWT (HS256, 24h expiry) with bcrypt-hashed passwords. Nice detail: the system quietly upgrades any legacy SHA-256 password hash to bcrypt the next time that user logs in successfully — a real migration path, not just documentation.

*`backend/core/security.py` · `auth_service.py:110-121`*

---

## 5. Panel Q&A Bank

### Overview questions

**Q: What problem does this project solve?**
Watching several long videos on one topic to extract what matters is slow. This system lets a user pick multiple videos, choose how much time they want to spend, and get a single fused summary plus an edited highlight video.

**Q: Who is this for?**
Anyone researching a topic across multiple videos — students, researchers, content reviewers — who wants the combined signal from several sources without watching all of them start to finish.

**Q: What makes this different from just summarizing one video?**
The fusion stage — it doesn't summarize each video separately and concatenate; it clusters ideas **across** all selected videos together, removes repeated content, and can flag when sources disagree.

### Technical questions

**Q: Walk me through what happens when I click submit.**
Use the 10-step pipeline table above, in order.

**Q: How do you make sure the video isn't just cutting random clips?**
Every candidate clip is scored for semantic similarity to the already-generated text summary — clips are chosen because their content matches what the summary says is important, then packed greedily by score until the target duration fills.

**Q: How does the system handle a video with no captions?**
Three-tier fallback: YouTube's transcript API → yt-dlp subtitles → Whisper speech-to-text on the audio directly.

**Q: How is duplicate content across videos removed?**
Sentences from every video are embedded and clustered together first, so duplicate ideas land in the same cluster; within a cluster a sentence is kept only if it's not too similar (cosine similarity under 0.82) to one already kept.

**Q: Is background job processing scalable — what about 100 concurrent users?**
Honestly, not at that scale yet — jobs run as in-process FastAPI background tasks on a single server, fine for a demo/FYP deployment. Scaling further means a real task queue (Celery/RQ) with multiple workers.

### "Why this, not X" questions

**Q: Why not just use ChatGPT or Gemini's API for summarization?**
Cost and control. A paid per-request API doesn't fit a zero-budget student project and creates external dependency. Every model here runs locally and free — Ollama specifically replaced an earlier Gemini integration for this reason.

**Q: Why MongoDB instead of a relational database?**
Job records carry deeply nested, variable-shape data (segments, scores, chapters differ per job) — maps naturally onto documents without a rigid, heavily-joined schema.

**Q: Why Whisper only as a fallback, not the primary source?**
Speed and accuracy — YouTube's captions and yt-dlp subtitles are faster and typically cleaner, and already available for most videos. Whisper only runs when both are missing.

**Q: Why DistilBART and not a larger model?**
Size-to-quality trade-off for CPU-only hardware — roughly a fifth the size of BART-large at ~95% of its quality.

### Limitations questions

**Q: What's the biggest weakness of the current system?**
Two honest ones: background jobs run in-process rather than on a real task queue, capping concurrent throughput; and visual-quality scoring for clip selection is implemented but off by default, so clip selection today relies mainly on transcript relevance, not what's visually happening in frame.

**Q: Could the summary hallucinate or misrepresent the source?**
It's a real risk with any abstractive summarizer — exactly why the quality-evaluation endpoint exists, checking semantic/keyword coverage and optionally running an LLM-judge pass looking for unsupported claims.

**Q: What about copyright, using other people's YouTube videos?**
The system only processes videos the user chooses to submit and produces a derivative summary/highlight for that user's own reference — same category of use as existing note-taking or clipping tools; it doesn't redistribute source video.

---

## 6. Honest Gaps to Own, Not Hide

A panel respects *"here's a known limitation and why it's an acceptable trade-off for this scope"* far more than a confident overclaim that falls apart under one follow-up question. These are real, verified simplifications in the codebase.

1. **Password-reset codes don't enforce their stated expiry.** The email says 10 minutes, but the check only compares the code value — no timestamp check.
   *If asked:* "That's a known gap — the fix is a straightforward timestamp check alongside the existing code comparison, not a redesign."

2. **Background jobs are in-process, not a dedicated task queue.** Fine for a single-server demo, doesn't scale to many concurrent jobs.
   *If asked:* "For this scope a task queue like Celery would be over-engineering; it's the natural next step for production scale."

3. **Clustering cluster-count is a fixed heuristic, not learned.** `max(3, min(sentence_count/5, 20))` — hand-tuned, not derived from data automatically.
   *If asked:* "It's a heuristic that worked well across the video lengths I tested with; a more advanced version could pick cluster count adaptively, e.g. via silhouette score."

4. **Visual/CLIP-based clip scoring exists but is off by default.** The default path is really a 2-signal semantic+keyword scorer.
   *Don't claim visual scoring is active unless you've explicitly enabled it for the demo.*

5. **Sentence splitting is regex-based**, not a proper NLP sentence tokenizer — can occasionally misparse abbreviations or unusual punctuation.
   *If asked:* "A dedicated tokenizer like spaCy's would be more robust; regex splitting was accurate enough for spoken-transcript text in testing."

6. **The quality score is an unweighted average** of whichever sub-checks ran, no weighting between them.
   *If asked:* "Keeping it unweighted keeps the score interpretable and easy to explain — a weighted or learned combination is a natural extension."

---

## 7. Confidence Tips for Viva Day

Aap material se full waqif ho — ab bas delivery pe kaam karna hai.

- **Answer shape**: Har jawab pehle ek seedha 1-line answer se shuru karo, phir 2–3 sentence mechanism, phir agar relevant ho to ek honest limitation. Yeh structure aapko ghoomne nahi deta.
- **Agar bhool jao**: Kabhi khamosh mat baitho. *"Sir/Ma'am, exact implementation detail abhi recall nahi ho raha, lekin overall design yeh tha ke..."* — phir jo pata hai us par bridge karo.
- **"Why not X" ke liye ready raho**: Panel har tool ke liye "why not the obvious alternative" zaroor poochta hai. §3 (Tool Choices) ek baar zubani bol kar practice karo.
- **Gaps ko chupao mat**: *"Yeh ek known limitation hai, future work mein X se improve karenge"* — is line se aap zyada mature aur trustworthy lagte ho.
- **Pipeline ko zubani bolo**: 10-step pipeline ko ek dafa loudly, without looking, bol kar practice karo — sabse common "walk me through it" question ka jawab hai.
- **Demo se pehle**: Agar visual scoring wala feature demo mein on nahi hai, to "hum CLIP se best frames select karte hain" mat bolo — jo default mein chal raha hai wahi bolo (semantic + keyword).

> **Fallback line — memorize this one:**
> *"That specific detail I'd want to double-check in the code before committing to an exact answer — but at a high level, the design principle behind that part of the system was [X], because [reason]."*

---

*Prep guide grounded in the codebase at time of writing. Re-verify file:line citations against the repo if the code changes before your viva.*
