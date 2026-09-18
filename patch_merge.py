import re
with open('backend/api/merge.py', 'r') as f:
    content = f.read()

# Replace the per-video loop with the global execution flow
old_loop = r"""    all_selected = \[\]
    baselines = \[\]
    all_concepts = \[\]
    all_trace = \[\]
    per_video = \{\}

    for vid, segs in raw_segments\.items\(\):
.*?            # 0/0 result can never be presented as concept-driven selection\.
            "concepts_omitted_for_budget": result\.concepts_omitted_for_budget,
        \}"""

new_flow = """    all_selected = []
    baselines = []
    all_concepts = []
    all_trace = []
    per_video = {}

    global_segments = []
    
    for vid, segs in raw_segments.items():
        if not segs:
            continue

        # --- 1. semantic segmentation ---
        await say(f"Building semantic segments for {vid}...")
        segments = await asyncio.to_thread(
            build_semantic_segments,
            segs,
            vid,
            settings.SEGMENT_MIN_SECONDS,
            settings.SEGMENT_MAX_SECONDS,
        )
        if not segments:
            print(f"[Semantic] {vid}: no semantic segments (unusable timestamps) — skipping")
            continue
        print(f"[Semantic] {vid}: {len(segs)} caption entries -> {len(segments)} complete thoughts "
              f"(avg {sum(s.duration for s in segments) / len(segments):.0f}s)")
        global_segments.extend(segments)

    # --- 2. concept extraction (Global) ---
    await say(f"Extracting key concepts globally across {len(raw_segments)} videos...")
    total_len = sum(durations.values())
    try:
        concepts = await extract_concepts(
            global_segments,
            total_duration=total_len,
            top_k=settings.CONCEPT_TOP_K,
            use_llm=settings.ENABLE_CONCEPT_LLM,
            per_chunk_timeout=settings.CONCEPT_CHUNK_TIMEOUT_SECONDS,
            total_timeout=settings.CONCEPT_TOTAL_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        print(f"[Semantic] Concept extraction failed globally: {exc}")
        concepts = []

    if not concepts:
        print(f"[Semantic] WARNING: 0 concepts extracted globally — "
              f"concept-driven selection is DISABLED; falling back to relevance + temporal coverage only")

    # --- 3. budgeted selection (Global) ---
    await say(f"Selecting the best {budget:.0f}s from the global candidate pool...")
    result = await asyncio.to_thread(
        select_segments,
        global_segments,
        budget,
        concepts,
        weights,
        summary_embedding,
        None,
        durations,  # Dict of video durations
    )
    
    if result.segments:
        baselines.append(result.baseline_similarity)
        all_selected.extend(result.segments)
        all_concepts.extend(concepts)
        all_trace.extend(result.trace)
        
        # Approximate per-video stats
        for vid in raw_segments:
            vid_selected = [s for s in result.segments if getattr(s, "video_id", "") == vid]
            vid_cands = [s for s in global_segments if getattr(s, "video_id", "") == vid]
            if not vid_cands:
                continue
            per_video[vid] = {
                "candidates": len(vid_cands),
                "selected": len(vid_selected),
                "seconds": round(sum(s.duration for s in vid_selected), 1),
                "budget": 0.0,
                "concepts_found": len(concepts),
                "concepts_covered": result.concepts_covered,
                "concepts_omitted_for_budget": result.concepts_omitted_for_budget,
            }"""

content = re.sub(old_loop, new_flow, content, flags=re.DOTALL)

# Remove `budgets = _allocate_budgets(durations, budget)`
content = re.sub(r'    budgets = _allocate_budgets\(durations, budget\)\n', '', content)

with open('backend/api/merge.py', 'w') as f:
    f.write(content)
