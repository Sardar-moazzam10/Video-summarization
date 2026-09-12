# API Regression Fixes & Audit

## P0: JSONResponse Scoping Bug (Fixed)
**Root Cause:** Inside `backend/main.py`'s `rate_limit_middleware`, there was an `except BaseException` block containing an inline import `from fastapi.responses import JSONResponse`. In Python, importing or assigning a variable anywhere inside a function makes it a local variable for the *entire* function scope. When the rate-limiter check at the top of the function tried to `return JSONResponse(...)`, it threw an `UnboundLocalError` because the local variable wasn't defined yet. Furthermore, this meant that *any* client disconnect (which raises `asyncio.CancelledError`) triggered a 500 error instead of a 499.

**Fix:** I removed the inline import and properly scoped the block. I also added a manual regression script (`backend/tests/run_test.py`) that hits the API 61 times and asserts that it correctly returns HTTP 429 without crashing.

## P0: `/result` Normal Processing Response (Fixed)
**Root Cause:** The `get_job_result` endpoint strictly required the database status to be `COMPLETED`, `PARTIAL_SUCCESS`, or `VIDEO_READY`. However, immediately after hitting `VIDEO_READY`, the background task progresses to `SUMMARIZING`, `ENRICHING`, etc. When the frontend polled the endpoint during these background stages, the endpoint saw unallowed statuses and threw a 400 Bad Request.

**Fix:** I updated `allowed_statuses` in `get_job_result` to accept `SUMMARIZING`, `ENRICHING`, and `GENERATING_VOICE` alongside `VIDEO_READY`. For all these mid-flight statuses, it now correctly returns HTTP 200 with `summary_pending: true` and the video URL, without throwing 400 errors.

## P1: Frontend Polling Storm (Fixed)
**Root Cause:** The frontend uses Server-Sent Events (SSE) to receive progress updates. Every time it received an event with a status of `video_ready` (or mid-flight text generation statuses), the SSE event handler executed `axios.get('/result')`. Since the backend emits frequent progress updates during summarization (e.g. 70%, 75%, 80%), the frontend was spamming the `/result` endpoint on every tick! Because these were previously met with 400 errors, the `.catch(() => {})` silenced them, masking the storm.

**Fix:** I introduced a `videoFetchedRef` in `MergedPodcastPlayer.js`. Now, when the frontend transitions into the `video_ready` phase, it requests `/result` *exactly once* to retrieve the video URL, and then waits patiently for the final `completed` signal without generating a request storm.

## P1: Rate Limiter & Evaluate/Audio Verification
**Rate Limiter:** With the frontend polling storm eliminated (it now only polls once to get the video), normal usage will stay well under the 60 requests/minute threshold.
**Evaluate / Audio:** 
- The cascading 500 errors you saw on `/evaluate` and `/audio` were entirely side-effects of the `JSONResponse` bug triggered by browser request aborts/disconnects. Since the middleware is now fixed, these will gracefully terminate.
- The `QualityPanel` strictly guards itself behind `isFinal && !resultData?.summary_unavailable`, guaranteeing it only evaluates when a text summary actually exists.
