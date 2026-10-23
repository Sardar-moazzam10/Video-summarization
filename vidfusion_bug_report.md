# VidFusion Bug Report — End-to-End QA Testing

**Environment**: Local Development (`http://localhost:3001` / API `http://localhost:8000`)  
**Tested On**: Real Google Chrome Instance via Playwright MCP Server  
**Testing Date**: October 23, 2026  
**Auditor**: Antigravity QA Agent  

---

## Summary of Confirmed Bugs

| # | Bug Title | Location | Severity |
|---|---|---|---|
| 1 | Fatal Runtime Crash (`ReferenceError: Cannot access 'loadPlayer' before initialization`) | Trim Test Page (`/trim-test`) | **Critical** |
| 2 | Completed Merge Jobs Without Explicit `text_component` Subdocument Permanently Stuck in "Generating AI Summary..." State | Merge Result Player (`/merged-player/:mergeId`) | **High** |
| 3 | Invalid Verification Code Submissions Display Misleading "Network Error" Due to Hardcoded Axios Catch Block | Auth / Verify Code Page (`/verify-code`) | **Medium** |
| 4 | Direct Route Navigation to `/video-player/:videoId` Ignores URL Parameter and Shows "No video selected" Error | Single Video Player Page (`/video-player/:videoId`) | **Medium** |

---

## Detailed Bug Reports

### Bug 1: Fatal Runtime Crash (`ReferenceError: Cannot access 'loadPlayer' before initialization`)

1. **Bug Title**: Fatal Runtime Crash in TrimTestPage Due to TDZ Access of `loadPlayer`
2. **Location**: `src/TrimTestPage.js` (Lines 145–150) -> Route `/trim-test`
3. **Steps to Reproduce**:
   1. Start the React frontend application (`npm start` on port 3001).
   2. Log in with any valid user credentials or navigate directly to `http://localhost:3001/trim-test`.
   3. Observe the browser viewport and browser console.
4. **Expected vs Actual Behavior**:
   - **Expected**: The Trim Test page loads its UI containing the YouTube URL input form, merge controls, and player placeholders.
   - **Actual**: The entire React component crashes fatally on mount with unhandled `ReferenceError: Cannot access 'loadPlayer' before initialization`. React unmounts the whole application DOM tree, leaving a completely blank white screen.
5. **Screenshot**:
   ![Fatal Runtime Crash on TrimTestPage](/home/weiblocks/Desktop/Video-summarization/bug_screenshots/bug_trim_test_crash.png)
6. **Suggested Fix**:
   In [src/TrimTestPage.js](file:///home/weiblocks/Desktop/Video-summarization/src/TrimTestPage.js#L145-L155), the `useEffect` on line 147 references `loadPlayer` before its `const loadPlayer = useCallback(...)` definition on line 150:
   ```javascript
   // Move `loadPlayer` definition ABOVE the useEffect:
   const loadPlayer = useCallback(() => {
     // ...
   }, [segments, playSegment]);

   useEffect(() => {
     if (durationsReady) loadPlayer();
   }, [durationsReady, loadPlayer]);
   ```
7. **Severity**: **Critical**

---

### Bug 2: Completed Merge Jobs Without Explicit `text_component` Subdocument Permanently Stuck in "Generating AI Summary..." State

1. **Bug Title**: Completed Jobs With Default `text_component.status === 'queued'` Suppress AI Summary and Export Controls
2. **Location**: `src/MergedPodcastPlayer.js` (Lines 215–217, 678–681, 873) and `backend/api/merge.py` (Line 133) -> Route `/merged-player/:mergeId`
3. **Steps to Reproduce**:
   1. Open any completed merge job created via unified pipeline or where MongoDB stores `status: "completed"`, `summary_text`, and `rich_output` without a nested `text_component` document (e.g. `http://localhost:3001/merged-player/3cafcdde-a995-4cbe-a238-815deb5b70d6`).
   2. Observe the page header subtitle, the "Generating Summary" section, and the "AI Summary" card.
   3. Check the bottom of the page for export action buttons (Copy Text, Download TXT, Download PDF).
4. **Expected vs Actual Behavior**:
   - **Expected**: Because the job is `status: "completed"` with fully generated text in `summary_text` and `rich_output.summary`, the header should state *"Your summary is ready"*, the generated AI Summary paragraphs should be displayed, and the export buttons should be clickable.
   - **Actual**: 
     - The page subtitle permanently displays *"Highlight video ready — generating AI summary..."*.
     - The progress indicator card permanently displays active spinning stages for *Summarizing*, *AI Enriching*, and *Voice Gen*.
     - The "AI Summary" card hides the generated text and permanently displays italicized *"Generating AI summary…"*.
     - All Export buttons (Copy Text, Download TXT, Download PDF) are completely hidden from the user because `!summaryPending` evaluates to `false`.
5. **Screenshot**:
   ![AI Summary Card Stuck in Generating State](/home/weiblocks/Desktop/Video-summarization/bug_screenshots/bug_ai_summary_card_stuck.png)
   ![Full Viewport Showing Stuck Progress Spinners and Missing Exports](/home/weiblocks/Desktop/Video-summarization/bug_screenshots/bug_summary_stuck_generating.png)
6. **Suggested Fix**:
   - In [backend/api/merge.py](file:///home/weiblocks/Desktop/Video-summarization/backend/api/merge.py#L118-L140), if the parent job `status` is already `"completed"` or `"partial_success"` and `text_component` is missing from the database record, default `text_component.status` to `ComponentStatus.READY` rather than `QUEUED`:
     ```python
     text_default = (
         ComponentStatus.READY
         if value.get("status") in ("completed", "partial_success") and bool(value.get("summary_text"))
         else ComponentStatus.QUEUED
     )
     text = _component_state(value.get("text_component"), default_status=text_default)
     ```
   - In [src/MergedPodcastPlayer.js](file:///home/weiblocks/Desktop/Video-summarization/src/MergedPodcastPlayer.js#L215-L217), guard `summaryPending` against terminal job states:
     ```javascript
     const summaryPending = !isFinal && (
       textComponent
         ? ['queued', 'running'].includes(textComponent.status)
         : (hasVideoReady && status !== 'error')
     );
     ```
7. **Severity**: **High**

---

### Bug 3: Invalid Verification Code Submissions Display Misleading "Network Error" Due to Hardcoded Axios Catch Block

1. **Bug Title**: Hardcoded "Network Error" Response in `verifyCode` Masks Real Backend Validation Failures
2. **Location**: `src/pages/authExtraApi.js` (Lines 18–24) and `src/pages/VerifyCodePage.js` (Line 41) -> Route `/verify-code`
3. **Steps to Reproduce**:
   1. Navigate to `/forgot-password` and submit a registered email address (`qatest2026@testmail.com`).
   2. When redirected to `/verify-code`, enter any incorrect 6-digit verification code (e.g., `1 2 3 4 5 6`).
   3. Click the **Verify Code** button.
   4. Observe the error message banner displayed below the input boxes.
4. **Expected vs Actual Behavior**:
   - **Expected**: The UI displays the error returned by the backend: *"Invalid or expired verification code"* or *"Incorrect code. 4 attempts remaining."*
   - **Actual**: The backend returns HTTP 400 Bad Request, but `authExtraApi.js` catches the Axios exception and returns `{ success: false, message: 'Network Error' }`. The user is shown a misleading red banner reading `"Network Error"`, suggesting network or server connectivity failure.
5. **Screenshot**:
   ![Misleading Network Error on Invalid Verification Code](/home/weiblocks/Desktop/Video-summarization/bug_screenshots/bug_verify_code_network_error.png)
6. **Suggested Fix**:
   In [src/pages/authExtraApi.js](file:///home/weiblocks/Desktop/Video-summarization/src/pages/authExtraApi.js#L18-L24), extract the backend error detail before falling back to generic network error:
   ```javascript
   export const verifyCode = async (email, code) => {
     try {
       const response = await axios.post(`${API_BASE_URL}/api/v1/auth/verify-code`, { email, code });
       return response.data;
     } catch (error) {
       console.error('Error verifying code:', error);
       const detail = error.response?.data?.detail;
       return {
         success: false,
         message: typeof detail === 'string' ? detail : 'Invalid verification code. Please check and try again.',
       };
     }
   };
   ```
   Apply the same pattern to `sendVerificationCode` and `resetPassword` in that module.
7. **Severity**: **Medium**

---

### Bug 4: Direct Route Navigation to `/video-player/:videoId` Ignores URL Parameter and Shows "No video selected" Error

1. **Bug Title**: VideoPlayerPage Fails on Direct Link or Refresh Due to Relying Exclusively on `location.state`
2. **Location**: `src/VideoPlayerPage.js` (Lines 7–42) & `src/App.js` (Line 110) -> Route `/video-player/:videoId`
3. **Steps to Reproduce**:
   1. Log into VidFusion.
   2. Open a direct video link or refresh the page while on a video player route: `http://localhost:3001/video-player/IHZwWFHWa-w`.
   3. Observe the rendered view.
4. **Expected vs Actual Behavior**:
   - **Expected**: The component extracts `videoId` from `useParams()`, mounts the YouTube embed player for `IHZwWFHWa-w`, and allows the user to watch the video.
   - **Actual**: The component ignores `useParams()` and only checks `location.state?.video`. Because `location.state` is `undefined` on direct navigation or page refresh, it displays *"No video selected"* with a *"Go Home"* button.
5. **Screenshot**:
   ![Direct Route Video Player Shows No Video Selected](/home/weiblocks/Desktop/Video-summarization/bug_screenshots/bug_video_player_route_param_ignored.png)
6. **Suggested Fix**:
   In [src/VideoPlayerPage.js](file:///home/weiblocks/Desktop/Video-summarization/src/VideoPlayerPage.js#L1-L45):
   1. Import `useParams` from `react-router-dom`: `const { videoId: paramVideoId } = useParams();`
   2. Fallback to `paramVideoId` if `video` is absent in `location.state`:
      ```javascript
      const effectiveVideoId = video?.id?.videoId || video?.id || paramVideoId;
      if (!effectiveVideoId) {
        return (/* No video selected view */);
      }
      ```
   3. Render `<iframe src={`https://www.youtube.com/embed/${effectiveVideoId}`} ... />`.
7. **Severity**: **Medium**
