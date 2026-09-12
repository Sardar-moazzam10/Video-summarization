# Bug Fixes & Audit Results

## P0: State Machine Bug (Unsupported Languages)
**Root Cause:** The `job_warning` variable was being overloaded. When a video in an unsupported language (like Hindi) was processed, the backend correctly skipped summarization and populated `job_warning` with an abort message. However, the video generation block was gated by `if job.generate_video ... and not job_warning:`. Because `job_warning` was set, the backend **completely skipped generating the video highlight reel**. As a result, it skipped the `VIDEO_READY` status and jumped straight to the terminal `PARTIAL_SUCCESS` state, causing the frontend to immediately show the final results UI.

**Fix:** I decoupled the error states by introducing a dedicated `video_error` flag in `backend/api/merge.py`. Video generation now evaluates independently of text-summarization warnings. The highlight reel will generate as expected, and the frontend will stay on the processing screen until `VIDEO_READY` is emitted.

## P1: Quality Check
I audited the `/evaluate` endpoint. It already correctly handles jobs without summaries by returning a structured `{ "unavailable": True }` payload. The frontend also successfully intercepts this and displays the yellow "Quality Check Unavailable" notice (as shown in your screenshot), ensuring no 500 errors occur.

## P2: Media Probe Timeout
The 20-second timeout during `POST /merge` is caused by YouTube periodically rate-limiting `yt-dlp` metadata requests.
Previously, the `MergePreviewPage` called the `/durations` endpoint to pre-warm the cache. Because we simplified the UI to bypass the preview page, `POST /merge` now takes the full hit of the `yt-dlp` request.
*As requested, I did not change this logic.* The backend correctly fails fast with a 422 error, and the frontend handles it cleanly by asking the user to try again.

## P3: Target Duration Check
The UI's `MultiSelectBar` correctly defaults to 10 minutes. The log showing `900s for a 15 minutes reel` is correct because the backend automatically scales the reel to 900 seconds (`15 * 60`) for 15-minute requests.
However, I discovered that during the recent UI simplification, I accidentally hardcoded `generate_video: false` in `SearchByKeywordsPage.js`. I have corrected this so the payload properly sends `generate_video: true` again.
