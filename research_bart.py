import asyncio
import time
import builtins
import sys

original_print = builtins.print
def timestamped_print(*args, **kwargs):
    now = time.time()
    ms = int((now % 1) * 1000)
    ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))
    original_print(f"[{ts}.{ms:03d}]", *args, **kwargs)
    sys.stdout.flush()

builtins.print = timestamped_print

from backend.services.transcript_service import get_transcript_service
from backend.services.duration_profiles import get_profile, get_summarization_config
from backend.services.summarization_service import get_summarization_service, _get_pipeline, _model, _tokenizer_lock
from backend.models.job import MergeJob
from backend.api.merge import run_semantic_selection, fetch_transcripts_with_segments
from backend.services.fusion_engine import get_fusion_engine
import torch
import copy

async def main():
    print("Loading models (not timed in benchmark)...")
    service = get_summarization_service()
    pipe = _get_pipeline()
    fusion = get_fusion_engine()
    
    # 1. Get raw transcript
    flat_dict, segments_dict = await fetch_transcripts_with_segments(["_QXjl-4IuzY"])
    flat_text = flat_dict["_QXjl-4IuzY"]
    segments = segments_dict["_QXjl-4IuzY"]
    
    # 2. Emulate 10 minute run to get the text input to BART
    job = MergeJob(
        job_id="test_bart", video_ids=["_QXjl-4IuzY"],
        target_duration_minutes=10, highlight_duration_seconds=600,
        style="analytical"
    )
    
    res1 = fusion.fuse_transcripts({"_QXjl-4IuzY": flat_text})
    
    semantic = await run_semantic_selection(
        job, {"_QXjl-4IuzY": segments}, res1.narrative, lambda x: None
    )
    selected_segs = semantic["highlights"]
    
    selected_text = " ".join([s["text"] for s in selected_segs])
    selected_text_dict = {"_QXjl-4IuzY": selected_text}
    res2 = fusion.fuse_transcripts(selected_text_dict)
    
    bart_input = res2.narrative
    input_words = len(bart_input.split())
    print(f"BART INPUT WORDS: {input_words}")
    
    profile = get_profile(10)
    base_config = get_summarization_config(profile)
    
    configs_to_test = [
        ("A. Current Settings", base_config, False, 800),
    ]
    
    config_b = copy.deepcopy(base_config)
    config_b.num_beams = 2
    configs_to_test.append(("B. num_beams = 2", config_b, False, 800))
    
    config_c = copy.deepcopy(base_config)
    config_c.num_beams = 1
    configs_to_test.append(("C. num_beams = 1", config_c, False, 800))
    
    config_d = copy.deepcopy(base_config)
    # Reduced max tokens by shrinking max_output_length
    config_d.max_output_length = int(config_d.max_output_length * 0.7)
    configs_to_test.append(("D. reduced max_output_length", config_d, False, 800))
    
    configs_to_test.append(("E. inference_mode", base_config, True, 800))
    
    configs_to_test.append(("F. alternative chunk sizing (600 words)", base_config, False, 600))
    configs_to_test.append(("F. alternative chunk sizing (400 words)", base_config, False, 400))
    
    target_budget = 350 # 10 min profile target
    
    import backend.services.summarization_service as ss
    
    for name, conf, use_inference_mode, chunk_size in configs_to_test:
        print(f"\n--- Testing: {name} ---")
        service.max_chunk_words = chunk_size
        
        # Monkey patch _get_pipeline for inference_mode
        if use_inference_mode:
            def mock_summarize(text, max_length=150, min_length=40,
                   do_sample=False, num_beams=4,
                   length_penalty=2.0, early_stopping=True,
                   no_repeat_ngram_size=3, repetition_penalty=1.0,
                   **kwargs):
                with _tokenizer_lock:
                    inputs = ss._tokenizer(
                        text, return_tensors="pt",
                        max_length=1024, truncation=True, padding=True,
                    )
                with torch.inference_mode():
                    ids = ss._model.generate(
                        inputs["input_ids"],
                        attention_mask=inputs["attention_mask"],
                        max_length=max_length,
                        min_length=min_length,
                        do_sample=do_sample,
                        num_beams=num_beams,
                        length_penalty=length_penalty,
                        early_stopping=early_stopping,
                        no_repeat_ngram_size=no_repeat_ngram_size,
                        repetition_penalty=repetition_penalty,
                    )
                with _tokenizer_lock:
                    summary = ss._tokenizer.decode(ids[0], skip_special_tokens=True)
                return [{"summary_text": summary}]
                
            original_pipe = ss._get_pipeline
            ss._get_pipeline = lambda: mock_summarize
        else:
            # ensure standard
            original_pipe = ss._get_pipeline
        
        t0 = time.time()
        output, decision = service.summarize_with_policy(
            bart_input, target_budget, profile, embedder=fusion.embedder
        )
        t1 = time.time()
        
        ss._get_pipeline = original_pipe # restore
        
        out_words = len(output.split())
        
        print(f"Generation time: {t1-t0:.2f}s")
        print(f"Output Words: {out_words}")
        print(f"Snippet: {output[:300]}...")

if __name__ == "__main__":
    asyncio.run(main())
