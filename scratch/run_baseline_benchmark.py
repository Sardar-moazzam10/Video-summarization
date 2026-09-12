import asyncio
import time
import builtins
import sys
import os
import psutil
import threading
import copy

from dotenv import load_dotenv
load_dotenv()
os.environ["VIDEO_CACHE_ENABLED"] = "1"

from backend.models.job import MergeJob
from backend.api.merge import get_jobs_collection, _active_jobs, fetch_transcripts_with_segments
from backend.services.fusion_engine import get_fusion_engine
from backend.services.duration_profiles import get_profile, get_summarization_config
from backend.services.semantic_segmenter import build_semantic_segments
from backend.services.concept_extractor import extract_concepts
from backend.services.coverage_selector import SelectionWeights, select_segments
from backend.services.video_service import get_video_service
from backend.services.summarization_service import get_summarization_service
from backend.api.merge import _generate_local_enrichment, _extract_audio_from_reel
from backend.core.config import get_settings

video_id = "_QXjl-4IuzY"
target_duration_minutes = 10
highlight_seconds = 600

class BaselineTracker:
    def __init__(self):
        self.timings = {}
        self.metrics = {}
        self.cpu_samples = []
        self.mem_samples = []
        self.monitoring = False

    def start_monitoring(self):
        self.monitoring = True
        self.cpu_samples = []
        self.mem_samples = []
        def _monitor():
            while self.monitoring:
                self.cpu_samples.append(psutil.cpu_percent(interval=0.2))
                self.mem_samples.append(psutil.virtual_memory().used / (1024**2))
        self.thread = threading.Thread(target=_monitor)
        self.thread.daemon = True
        self.thread.start()

    def stop_monitoring(self):
        self.monitoring = False
        if hasattr(self, 'thread'):
            self.thread.join(timeout=1.0)
        avg_cpu = sum(self.cpu_samples) / max(len(self.cpu_samples), 1)
        max_mem = max(self.mem_samples) if self.mem_samples else 0
        return avg_cpu, max_mem

async def run_baseline_pass(run_id: str):
    tracker = BaselineTracker()
    tracker.start_monitoring()
    t_start = time.time()

    # 1. Transcript time
    t0 = time.time()
    transcripts, raw_segments = await fetch_transcripts_with_segments([video_id])
    t1 = time.time()
    tracker.timings['transcript_time'] = t1 - t0

    # 2. Initial Fusion time
    t0 = time.time()
    profile = get_profile(target_duration_minutes)
    fusion_budget = profile.target_minutes * profile.words_per_minute
    fusion_engine = get_fusion_engine()
    res_initial = fusion_engine.fuse_transcripts(
        transcripts=transcripts,
        target_words=fusion_budget,
        include_sources=profile.include_sources,
        include_transitions=profile.include_transitions,
        raw_segments=raw_segments
    )
    t1 = time.time()
    tracker.timings['initial_fusion_time'] = t1 - t0

    # 3. Download / Ensure video cached
    video_svc = get_video_service()
    video_paths = await video_svc.download_videos([video_id], job_id=run_id, progress_callback=None)

    # 4. Semantic segmentation time
    t0 = time.time()
    segs = raw_segments.get(video_id, [])
    settings = get_settings()
    semantic_segs = await asyncio.to_thread(
        build_semantic_segments,
        segs,
        video_id,
        settings.SEGMENT_MIN_SECONDS,
        settings.SEGMENT_MAX_SECONDS,
    )
    t1 = time.time()
    tracker.timings['semantic_segmentation_time'] = t1 - t0

    # 5. Concept extraction time
    t0 = time.time()
    dur = segs[-1]['start'] + segs[-1]['duration'] if segs else 0
    concepts = await extract_concepts(
        semantic_segs,
        total_duration=dur,
        top_k=settings.CONCEPT_TOP_K,
        use_llm=settings.ENABLE_CONCEPT_LLM,
        per_chunk_timeout=settings.CONCEPT_CHUNK_TIMEOUT_SECONDS,
        total_timeout=settings.CONCEPT_TOTAL_TIMEOUT_SECONDS,
    )
    t1 = time.time()
    tracker.timings['concept_extraction_time'] = t1 - t0

    # 6. Selection time
    t0 = time.time()
    from backend.services.fusion_engine import get_sentence_transformer
    embedder = get_sentence_transformer()
    summary_emb = embedder.encode([res_initial.narrative[:4000]], show_progress_bar=False)[0] if res_initial.narrative else None
    weights = SelectionWeights.from_settings(settings)
    selection_res = await asyncio.to_thread(
        select_segments,
        semantic_segs,
        float(highlight_seconds),
        concepts,
        weights,
        summary_emb,
        None,
        dur
    )
    t1 = time.time()
    tracker.timings['selection_time'] = t1 - t0

    highlights = []
    for s in sorted(selection_res.segments, key=lambda x: (x.video_id, x.start_time)):
        highlights.append({
            "video_id": s.video_id,
            "start_time": round(max(0.0, s.start_time), 3),
            "end_time": round(s.end_time, 3),
            "importance_score": round(float(s.boundary_confidence), 4),
            "text": s.text,
        })

    # 7. Video rendering time
    t0 = time.time()
    from backend.services.video_service import MAX_CONCURRENT_CLIP_ENCODES
    tracker.metrics['num_ffmpeg_workers'] = MAX_CONCURRENT_CLIP_ENCODES
    video_path = await video_svc.generate_highlight_reel(
        job_id=run_id,
        highlight_segments=highlights,
        video_paths=video_paths,
        audio_path=None,
        progress_callback=None
    )
    t1 = time.time()
    tracker.timings['video_rendering_time'] = t1 - t0
    
    # Checkpoint: Video Ready Time
    t_video_ready = time.time() - t_start
    tracker.timings['video_ready_time'] = t_video_ready

    # 8. Audio extraction time
    t0 = time.time()
    audio_path = await asyncio.to_thread(_extract_audio_from_reel, video_path, run_id)
    t1 = time.time()
    tracker.timings['audio_extraction_time'] = t1 - t0

    # 9. Second Pass Fusion & BART time
    t0_bart = time.time()
    selected_text = " ".join([h['text'] for h in highlights])
    res_selected = fusion_engine.fuse_transcripts(
        transcripts={video_id: selected_text},
        target_words=fusion_budget,
        include_sources=profile.include_sources,
        include_transitions=profile.include_transitions,
    )
    bart_input = res_selected.narrative

    summarization_svc = get_summarization_service()
    
    # Summarize with policy
    summary_text, decision = summarization_svc.summarize_with_policy(
        bart_input, profile.target_words, profile, embedder=fusion_engine.embedder
    )
    
    from backend.services.summarization_service import _tokenizer
    in_tokens = len(_tokenizer.encode(bart_input))
    t1_bart = time.time()
    tracker.timings['bart_time'] = t1_bart - t0_bart

    out_tokens = len(_tokenizer.encode(summary_text))
    tracker.metrics['bart_input_tokens'] = in_tokens
    tracker.metrics['bart_output_tokens'] = out_tokens
    tracker.metrics['num_bart_chunks'] = decision.total_chunks if hasattr(decision, 'total_chunks') else 1

    # 10. Enrichment time
    t0 = time.time()
    rich_out = _generate_local_enrichment(summary_text, "analytical")
    t1 = time.time()
    tracker.timings['enrichment_time'] = t1 - t0

    t_total = time.time() - t_start
    tracker.timings['total_completion_time'] = t_total

    avg_cpu, max_mem = tracker.stop_monitoring()
    tracker.metrics['avg_cpu_percent'] = round(avg_cpu, 1)
    tracker.metrics['peak_mem_mb'] = round(max_mem, 1)

    return tracker.timings, tracker.metrics

async def main():
    print("--- WARMING UP MODEL / PIPELINE ---")
    await run_baseline_pass("prewarm")
    
    print("\n=== BASELINE RUN 1 ===")
    t1, m1 = await run_baseline_pass("run_1")
    
    print("\n=== BASELINE RUN 2 ===")
    t2, m2 = await run_baseline_pass("run_2")

    print("\n================ BASELINE RESULTS SUMMARY ================")
    print(f"{'Metric':<30} | {'Run 1':<10} | {'Run 2':<10} | {'Median':<10}")
    print("-" * 70)
    for k in t1.keys():
        v1 = t1[k]
        v2 = t2[k]
        med = (v1 + v2) / 2.0
        print(f"{k:<30} | {v1:<10.2f} | {v2:<10.2f} | {med:<10.2f}")
    print("-" * 70)
    for k in m1.keys():
        print(f"{k:<30} | {m1[k]!s:<10} | {m2[k]!s:<10}")

if __name__ == "__main__":
    asyncio.run(main())
