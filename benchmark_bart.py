import asyncio
import time
import os
from backend.services.transcript_service import get_transcript_service
from backend.services.duration_profiles import get_profile
from backend.services.summarization_service import get_summarization_service, _get_pipeline
from backend.models.job import MergeJob
from backend.api.merge import run_semantic_selection, fetch_transcripts_with_segments
from backend.services.fusion_engine import get_fusion_engine

async def main():
    print("Loading models (not timed in benchmark)...")
    service = get_summarization_service()
    _ = _get_pipeline()
    fusion = get_fusion_engine()
    
    # 1. Get raw transcript
    flat_dict, segments_dict = await fetch_transcripts_with_segments(["xAt1xcC6qfM"])
    flat_text = flat_dict["xAt1xcC6qfM"]
    segments = segments_dict["xAt1xcC6qfM"]
    
    # 2. Emulate 10 minute run to get the text input to BART
    job = MergeJob(
        job_id="test", video_ids=["xAt1xcC6qfM"],
        target_duration_minutes=10, highlight_duration_seconds=600,
        style="analytical"
    )
    
    # First pass fusion
    res1 = fusion.fuse_transcripts({"xAt1xcC6qfM": flat_text})
    
    # Selection
    semantic = await run_semantic_selection(
        job, {"xAt1xcC6qfM": segments}, res1.narrative, lambda x: None
    )
    selected_segs = semantic["highlights"]
    
    # Second pass fusion (this goes into BART)
    text_to_fuse = {
        seg["video_id"]: " ".join([s["text"] for s in selected_segs if s["video_id"] == seg["video_id"]])
        for seg in selected_segs
    }
    # Wait, the second pass in merge.py is:
    # " ".join(s["text"] for s in all_highlights)
    selected_text = " ".join([s["text"] for s in selected_segs])
    selected_text_dict = {"xAt1xcC6qfM": selected_text}
    res2 = fusion.fuse_transcripts(selected_text_dict)
    
    bart_input = res2.narrative
    input_words = len(bart_input.split())
    
    import backend.services.summarization_service as ss
    tokenizer = ss._tokenizer
    
    input_tokens = len(tokenizer.encode(bart_input))
    print(f"BART INPUT WORDS: {input_words}")
    print(f"BART INPUT TOKENS: {input_tokens}")
    print("="*40)
    
    profile = get_profile(10)
    budgets = [250, 350, 500, 650, 800]
    
    for budget in budgets:
        print(f"\n--- Testing Target Words: {budget} ---")
        t0 = time.time()
        output, decision = service.summarize_with_policy(
            bart_input, budget, profile, embedder=fusion.embedder
        )
        t1 = time.time()
        
        out_words = len(output.split())
        out_tokens = len(tokenizer.encode(output))
        
        print(f"Generation time: {t1-t0:.2f}s")
        print(f"Decision: {decision}")
        print(f"Output Words: {out_words}")
        print(f"Output Tokens: {out_tokens}")
        print(f"Compression (Words): {out_words / max(1, input_words) * 100:.1f}%")
        print(f"Snippet: {output[:150]}...")
        
if __name__ == "__main__":
    asyncio.run(main())
