import asyncio
from backend.api.merge import process_merge_job, MergeJob, _active_jobs
import backend.services.summarization_service
from unittest.mock import patch

job_id = "test_1"
_active_jobs[job_id] = MergeJob(
    job_id=job_id,
    video_ids=["xAt1xcC6qfM"],
    target_duration_minutes=10,
)

async def main():
    original_summarize = backend.services.summarization_service.SummarizationService.summarize_with_policy
    def hook(self, text, target_words, profile, embedder=None):
        print(f"CALLED summarize_with_policy with target_words={target_words}")
        return "", {"action": "pass", "reason": "mock"}
    
    with patch.object(backend.services.summarization_service.SummarizationService, 'summarize_with_policy', new=hook):
        try:
            await process_merge_job(job_id)
        except Exception as e:
            pass

if __name__ == "__main__":
    asyncio.run(main())
