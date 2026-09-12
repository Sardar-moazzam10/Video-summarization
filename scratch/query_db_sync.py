from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["video_summarization"]
jobs = db["jobs"]

job10 = list(jobs.find({"target_duration_minutes": 10}).sort("created_at", -1).limit(1))[0]
job15 = list(jobs.find({"target_duration_minutes": 15}).sort("created_at", -1).limit(1))[0]

for job in [job10, job15]:
    print(f"=== {job['target_duration_minutes']} MINUTE JOB ===")
    print(f"Status: {job.get('status')}")
    print(f"Video URL: {job.get('video_url')}")
    print(f"Summary Length: {len(job.get('summary_text', ''))} chars")
    meta = job.get('metadata', {})
    
    # Try to find segment count
    # Check selection_metrics in job for full details
    sel_metrics = job.get('selection_metrics', {})
    print(f"Segments Selected: {sel_metrics.get('num_segments')}")
    print(f"Concepts Covered: {sel_metrics.get('unique_concepts')}")
    print(f"Timeline Coverage: {sel_metrics.get('timeline_coverage_percent')}%")
    print(f"Final Duration: {meta.get('final_duration_seconds', sel_metrics.get('actual_seconds'))}")
