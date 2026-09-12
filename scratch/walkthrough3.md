# Real API Regression Fixes

## P0: JSONResponse Scoping Bug (Fully Fixed)
**Why it persisted:** My previous fix successfully removed the local import and resolved the scoping issue, but the `uvicorn` backend was running in a standard detached terminal *without* the `--reload` flag. Because of this, the server continued serving the old cached bytecode where the bug still existed.
**Fix & Verification:** I ran a manual `pkill -f uvicorn` to completely destroy the stale processes, then booted a fresh server. I also wrote and ran a dedicated regression test (`backend/tests/run_test.py`) that successfully floods the API 61 times and confirms it returns a clean HTTP 429 without throwing `UnboundLocalError`.

## P0: `/result` Normal Processing Response (State Machine Trace)
**Root Cause of the 400s:** I instrumented the state machine and traced the sequence. You correctly identified the anomaly! The job reaches `VIDEO_READY`, exposing the video. However, immediately after, the backend performs a *second pass* reconstruction over the transcript. This transitions the job status back to `FUSING`. Because `FUSING` was not whitelisted as a valid mid-flight status in `get_job_result`, the endpoint correctly (from its perspective) rejected the request with a 400.
**Fix:** I audited the entire state machine and explicitly added `JobStatus.FUSING.value` to the `video_ready_statuses` set in `backend/api/merge.py`. The endpoint now correctly returns HTTP 200 with `summary_pending: true` during this second fusion pass.

## P0: Frontend Polling Request Storm (Fixed)
**Root Cause:** I audited every caller of `GET /result` in `MergedPodcastPlayer.js`. The issue was inside both the polling fallback loop and the SSE `onmessage` handler. Whenever the frontend encountered a mid-flight status (like `video_ready` or `summarizing`), it unconditionally fired `axios.get('/result')`. Since the backend emits progress percentage ticks every few seconds during these stages, the frontend was spamming the endpoint on *every single tick*.
**Fix:** I introduced a persistent `videoFetchedRef`. When the status enters `video_ready` (or subsequent mid-flight stages), the frontend now fetches `/result` **exactly once** to retrieve the playable video URL. Once obtained, it halts all `/result` requests and patiently waits for the final `COMPLETED` signal.

## P1: Acceptance Test
I ran a full mock simulation script representing the frontend flow on the fresh, non-reloading backend:
- The script successfully triggered `VIDEO_READY` and fetched `/result` returning HTTP 200.
- It progressed into `FUSING` and `SUMMARIZING` without throwing any 400 errors.
- It fetched `/result` exactly once during the mid-flight phase.
- No `UnboundLocalError` or 500s were emitted.
- The pipeline successfully reached `COMPLETED` and ran `/evaluate`.
