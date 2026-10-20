import asyncio
from time import perf_counter
from backend.core.database import get_sync_database
from backend.models.job import MergeJob
from backend.api.merge import run_semantic_selection

def get_raw_segments():
    db = get_sync_database()
    doc = db.transcripts.find_one({"video_id": "kqtD5dpn9C8"})
    if not doc or not doc.get("transcript"):
        raise RuntimeError("Transcript for kqtD5dpn9C8 not found in MongoDB")
    return {"kqtD5dpn9C8": doc["transcript"]}

async def main():
    raw_segments = get_raw_segments()
    print(f"Loaded {len(raw_segments['kqtD5dpn9C8'])} raw segments for kqtD5dpn9C8")

    job = MergeJob(
        job_id="reproduce-scenario4-test",
        user_id="test",
        video_ids=["kqtD5dpn9C8"],
        target_duration_minutes=30,
        highlight_duration_seconds=1800.0,
    )

    t0 = perf_counter()
    result = await run_semantic_selection(
        job=job,
        raw_segments=raw_segments,
        semantic_bias_text="",
    )
    t_elapsed = perf_counter() - t0
    print(f"Finished run_semantic_selection in {t_elapsed:.2f}s")

    if not result:
        print("RESULT IS NONE!")
        return

    metrics = result.get("metrics", {})
    highlights = result.get("highlights", [])
    print("--- VERIFICATION RESULTS ---")
    for field in (
        "requested_duration", "selector_duration", "post_boundary_duration",
        "post_cta_duration", "post_reconciliation_duration",
        "final_manifest_duration", "rendered_duration", "final_budget_fill_ratio",
        "largest_physical_block_seconds", "adjacent_same_source_merges",
        "cta_spans_detected", "cta_spans_removed", "cta_removed_seconds",
        "incomplete_explanation_rejections", "refill_candidates_total",
        "refill_candidates_examined", "refill_candidates_added",
        "rejected_reason_counts", "eligible_remaining_candidates",
        "eligible_remaining_duration", "infeasibility_proven",
        "infeasibility_reason", "semantic_segment_duration_distribution",
        "max_merged_block_seconds",
    ):
        print(f"{field}:", metrics.get(field))
    print("num_segments (manifest):", len(highlights))
    print("semantic_cores_selected:", metrics.get("semantic_cores_selected"))
    print("candidates_rejected_without_closure:", metrics.get("candidates_rejected_without_closure"))
    print("closure_rejections_during_reconciliation:", metrics.get("closure_rejections_during_reconciliation"))
    print("final_budget_fill_ratio:", metrics.get("final_budget_fill_ratio"))
    print("bounded_infeasibility_evidence:", metrics.get("bounded_infeasibility_evidence"))
    for idx, h in enumerate(highlights):
        print(f"Clip {idx}: start={h.get('start_time'):.2f} end={h.get('end_time'):.2f} dur={h.get('end_time', 0)-h.get('start_time', 0):.2f}s text[:60]={h.get('text', '')[:60]}...")

if __name__ == "__main__":
    asyncio.run(main())
