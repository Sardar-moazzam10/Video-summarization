from backend.main import request_counts_toward_rate_limit

def test_polling_and_transcript_requests_do_not_count():
    assert not request_counts_toward_rate_limit("/api/v1/merge/job-1", "GET")
    assert not request_counts_toward_rate_limit("/api/v1/transcript/anything", "GET")
    assert not request_counts_toward_rate_limit("/api/v1/rights/job/job-1/manifest", "OPTIONS")

def test_normal_search_and_history_still_count():
    assert request_counts_toward_rate_limit("/api/v1/youtube/search", "GET")
    assert request_counts_toward_rate_limit("/api/v1/auth/user-history", "POST")
