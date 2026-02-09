## YouTube Search App – Developer Guide (Read Me First)

> **🚀 NEW: Merge Backend Optimizations Implemented!**
> The merge backend has been optimized for 60-70% faster processing, improved reliability, and automatic cleanup.
> See [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) for details.

This `README` is written for **you as a new developer** on this project.  
It explains **what the app does**, **how the flow works end‑to‑end**, and **where to change things** in the codebase.

---

### 1. What this project does (high level)

This is a **full‑stack “podcast from YouTube” app**:

- **Search YouTube videos** (by title or keywords).
- **Play videos** inside the app.
- **Fetch transcripts** of YouTube videos (with multiple fallback methods).
- **Summarize** long transcripts with AI.
- **Create merged podcast segments** from multiple videos.
- **Generate AI voiceovers** for text using ElevenLabs.
- **Handle users** (signup/login, password reset, profile).
- **Track history** (searches, transcript views, etc.) in MongoDB.

You mainly work in:

- **Frontend (React)**: `src/`
- **Python backends (Flask)**: `auth_backend.py`, `transcript_backend.py`, `merge_backend.py`, `app/`
- **Node transcript proxy (Express)**: `server.js`

---

### 2. How the user flow works (step by step)

#### 2.0 Simple user instructions (non‑technical)

If you just want to **use the app** (not think about the code), these are the main steps:

1. **Search any podcast**  
   - Go to the search page and type your topic/title.
2. **See a list of videos**  
   - The app shows matching YouTube podcast videos.
3. **Use the merge option**  
   - For supported flows you will see an option to **merge** videos or best moments.
4. **Select videos for merging**  
   - Choose which videos (or segments) you want to include.
5. **See a video summary with important moments**  
   - The app uses transcript + AI to find important timestamps and show a summary view.
6. **Click merge**  
   - The app sends your selected items to the merge backend.
7. **Get a new combined experience**  
   - You are taken to a **merged player** where the selected segments are played together as one continuous podcast‑style experience.

The rest of this section explains how each of these steps is implemented in code.

#### 2.1 Auth and navigation

- User opens `http://localhost:3000`.
- Routing is handled in `src/App.js` using `react-router-dom`.
- Main routes:
  - **`/login`** – login screen (`pages/LoginPage.js`)
  - **`/signup`** – register user (`pages/SignupPage.js`)
  - **`/forgot-password`, `/verify-code`, `/reset-password`** – password reset flow
  - **`/manage-account`** – redirects to:
    - `/account-info` for normal users
    - `/admin-account-info` for admins
- **After login**, user info (including `role`) is stored in `localStorage` and used by:
  - `ProtectedRoute.js` – protects user and admin routes.
  - User panel pages in `panel_pages/`.
  - Admin panel pages in `admin_pages/`.

**If you want to change navigation or add new pages**, start with `src/App.js`.

---

#### 2.2 Searching for videos

- Pages:
  - `SearchPage.js` – **search by title/topic** (route `/search-by-title`).
  - `SearchByKeywordsPage.js` – **search by keywords** (route `/search-by-keywords` and `/search/:query`).
- The main search logic uses:
  - `youtubeApi.js` and/or `api.js` / `authApi.js` / `suggestedPodcastsApi.js` depending on the feature.
  - `SearchBar.js` for the search input.
  - `VideoList.js` + `VideoCard.js` to display results.
- On a successful search, `SearchPage.js`:
  - Saves results in `localStorage` under `searchedVideos`.
  - Logs the search in MongoDB via `POST http://localhost:5000/api/user-history`.

**To change search behavior or result layout:**

- UI / text: edit `SearchPage.js`, `SearchBar.js`, `VideoCard.js`, `VideoList.js`.
- API call to YouTube: edit `youtubeApi.js`.
- How search is saved to history: see `SearchPage.js` and `auth_backend.py` (history routes).

---

#### 2.3 Playing videos

- When user clicks a video card, they are sent to **`/video-player`** (or `/video-player/:videoId`) and rendered by:
  - `VideoPlayerPage.js`
- `VideoPlayerPage.js`:
  - Gets `video` and `videosList` via `react-router` `location.state`.
  - Shows a YouTube `<iframe>` for the main video.
  - Renders a “More on this topic” section using `videosList`.

**To change how video playback looks or behaves**, edit `VideoPlayerPage.js`.

---

#### 2.4 Fetching and viewing transcripts

There are **two pieces**: frontend (`TranscriptViewer`) and backend (`transcript_backend.py` / `server.js`).

- Frontend:
  - `TranscriptViewer.js` (route `/transcript-viewer` and `/transcript-viewer/:videoId`).
  - Uses `fetchTranscript` from `api.js` to call backend.
  - Lets user:
    - Enter a YouTube **video ID**.
    - Click **Fetch Transcript**.
    - View timestamped transcript.
    - **Copy** transcript.
    - **Download** plain text or text with timestamps.
  - Logs transcript views to history (`/api/user-history`).

- Backends:
  - `transcript_backend.py` – **main transcript backend** on port **5001**:
    - Endpoint `GET /transcript?videoId=<id>`
      - Checks MongoDB cache (`transcripts` collection).
      - Tries **YouTubeTranscriptApi** up to 3 times.
      - If that fails, falls back in order to:
        1. `fetch_transcript_ytdlp` (yt‑dlp with cookies).
        2. `fetch_transcript_selenium` (Selenium scraping).
        3. `fetch_transcript_whisper` (download audio + Whisper transcription).
    - Writes transcript to MongoDB with fields `{ video_id, transcript, fetched_at, source }`.
  - `server.js` – **Node proxy server** on port **8080**:
    - Endpoint `GET /proxy/:videoId`.
    - Fetches full YouTube page HTML, extracts `captionTracks` JSON with `cheerio`, and returns a structured transcript array.
    - Used as an additional way to get transcripts where direct APIs fail.

**To change transcript behavior:**

- Frontend UI / buttons: edit `TranscriptViewer.js`.
- Which backend URL is called: edit `api.js` or `youtubeTranscript.mjs`.
- Fallback logic & caching: edit `transcript_backend.py`.
- HTML scraping from YouTube: edit `server.js`.

---

#### 2.5 Summarization and “best moments”

- The **summarization API** lives in `transcript_backend.py`:
  - Endpoint `POST /summarize`:
    - Uses `transformers.pipeline("summarization", model="t5-small")`.
    - Cleans and truncates input text.
    - Returns `{"summary": "<short text>"}`.
- The **frontend player for summarized moments** is `SummarizedPlayer.js` (route `/summarized-player`):
  - Expects `location.state.videoData` in the shape:
    - `[ { videoId: string, timestamps: number[] }, ... ]`
  - Renders:
    - `<YouTube>` player (`react-youtube`).
    - Buttons to switch between videos.
    - Buttons to **jump to timestamps** inside the current video.

**To change summarization logic:**

- Model or parameters: edit `summarizer` and `summarize_transcript()` in `transcript_backend.py`.
- How timestamps or UI are presented: edit `SummarizedPlayer.js` and `SummarizedPlayer.css`.

---

#### 2.6 Merging segments and generating voiceovers

- Backend: `merge_backend.py` (Flask, port **5002**).

  - `POST /merge`
    - Input: `{ selectedSegments: [{ videoId: string, ... }, ...] }`.
    - For each videoId, calls `generate_trimmed_segment(video_id)`:
      - Currently **simulates** a 4–5 minute random segment within a 20‑minute range.
    - Stores auto‑trimmed segments in memory `stored_merges[merge_id]`.
    - Returns `{ mergeId }`.

  - `GET /merge/<merge_id>`
    - Returns stored segments for that merge ID.

  - `POST /voiceover`
    - Expects `{ text: string, voice_id?: string }`.
    - Calls ElevenLabs **Text‑to‑Speech streaming API**.
    - Streams back `audio/mpeg`.

- Frontend:
  - `MergedPodcastPlayer.js` (route `/merged-player/:mergeId`) – plays back merged segments.
  - `TrimTestPage.js` – testing UI for trimming / merging.

**To change how segments are selected or how voiceover works:**

- Segment logic: edit `generate_trimmed_segment()` and `/merge` in `merge_backend.py`.
- ElevenLabs settings (model, stability, voice): edit `/voiceover` in `merge_backend.py`.
- UI for merged content: edit `MergedPodcastPlayer.js`.

---

#### 2.7 History, user profile, and admin panel

- Backend: `auth_backend.py` (Flask, port **5000**).

  - **Auth routes**
    - `POST /api/signup` – create user.
    - `POST /api/login` – login with username or email.
  - **Password reset**
    - `POST /api/send-verification-code`
    - `POST /api/verify-code`
    - `POST /api/reset-password`
  - **Profile**
    - `GET /api/user/<username>`
    - `PUT /api/user/update/<username>`
    - `DELETE /api/user/delete/<username>`
    - `PUT /api/user/update-password/<username>`
  - **History**
    - `POST /api/user-history`
    - `GET /api/user-history/<username>`
    - `DELETE /api/user-history/delete/<username>`
    - `DELETE /api/user-history/delete-one`
  - **Admin**
    - `GET /api/users` – list all users (no passwords).

- Frontend:
  - User panel pages: `panel_pages/AccountInfoPage.js`, `SecurityPage.js`, `HistoryPage.js`.
  - Admin pages: `admin_pages/AdminAccountInfoPage.js`, `AdminSecurityPage.js`, `AdminHistoryPage.js`, `AdminUserListPage.js`.
  - Extra API helper files: `authApi.js`, `pages/authExtraApi.js`, `api.js`.

**To change what is stored per user, or the history behavior**, edit `auth_backend.py` and corresponding frontend panel pages.

---

### 3. Project structure (what is where)

**Root level**

- `package.json` – React app dependencies and scripts.
- `requirements.txt` – Python dependencies for all Flask backends.
- `auth_backend.py` – user auth, profile, history (Flask @ 5000).
- `transcript_backend.py` – transcript fetching + summarization (Flask @ 5001).
- `merge_backend.py` – merge segments + ElevenLabs voiceover (Flask @ 5002).
- `server.js` – Node proxy for YouTube transcript HTML parsing (@ 8080).
- `generate_cookies_txt.py` – helper to create `cookies.txt` from your browser.
- `cookies.txt` – used by `yt-dlp` for authenticated transcript fetching.
- `app/` – Python package with extra auth/db routing (`__init__.py`, `auth_routes.py`, `db_config.py`).
- `youtube-proxy/` – separate Node package for proxy logic (if you run it standalone).

**Frontend (`src/`) – main React app**

- `App.js` – routing and page wiring.
- `Navbar.js`, `Footer.js`, `Background.css`, `App.css` – shared layout and styling.
- `SearchPage.js`, `SearchByKeywordsPage.js`, `SuggestedPodcastsPage.js` – search and discovery.
- `VideoPlayerPage.js`, `TranscriptViewer.js`, `SummarizedPlayer.js`, `MergedPodcastPlayer.js`, `TrimTestPage.js`, `TestTranscriptPage.js` – media and transcript experiences.
- `pages/` – login/signup/forgot/reset, user dashboard routing.
- `panel_pages/`, `admin_pages/` – user and admin panels.
- `ProtectedRoute.js` – role‑based route protection.
- `api.js`, `authApi.js`, `suggestedPodcastsApi.js`, `youtubeApi.js`, `youtubeTranscript.mjs` – API helper modules.
- `utils/punctuateText.js` – utility for fixing transcript punctuation.

---

### 4. Setup & running (quick start)

#### 4.1 Prerequisites

- **Node.js** v18+
- **Python** 3.9+
- **MongoDB Atlas** account (or local MongoDB)
- **ElevenLabs API key** (for voiceover)
- **Chrome** + **ChromeDriver** (Selenium fallback)
- **yt-dlp** installed globally (`pip install yt-dlp` or OS package)

#### 4.2 Install dependencies

```bash
cd youtube-search-app

# Frontend
npm install

# Python (backends)
python -m venv venv
venv\Scripts\activate           # on Windows
pip install -r requirements.txt
```

#### 4.3 Environment / secrets

Create a `.env` file or set environment variables (recommended instead of hardcoding):

- **MongoDB URI** (currently hardcoded in `auth_backend.py` and `transcript_backend.py`).
- **ELEVEN_API_KEY** (used in `merge_backend.py`).
- **Mail credentials** for password reset (currently configured in `auth_backend.py`).

For development you can keep the existing hardcoded values, but for production **you must move them to env vars**.

#### 4.4 Run services

In separate terminals, from project root:

```bash
# 1. Auth backend (port 5000)
python auth_backend.py

# 2. Transcript backend (port 5001)
python transcript_backend.py

# 3. Merge + voiceover backend (port 5002)
python merge_backend.py

# 4. Node proxy (port 8080)
node server.js

# 5. Frontend React app (port 3000)
npm start
```

Then open `http://localhost:3000` in your browser.

---

### 5. Database schema (MongoDB)

#### 5.1 Users (`users` collection)

```json
{
  "firstName": "string",
  "lastName": "string",
  "email": "string",
  "username": "string",
  "password": "hashed_string",
  "role": "user | admin"
}
```

#### 5.2 History (`history` collection)

```json
{
  "username": "string",
  "type": "watch | search | transcript-view",
  "videoId": "string (optional, depends on type)",
  "query": "string (for type = search)",
  "timestamp": "ISO_date"
}
```

#### 5.3 Transcripts (`transcripts` collection)

```json
{
  "video_id": "string",
  "transcript": [
    { "text": "string", "start": 0.0, "duration": 3.4 }
  ],
  "fetched_at": "ISO_date",
  "source": "youtube_api | yt_dlp | selenium | whisper"
}
```

---

### 6. API endpoints (summary)

- **Auth backend – `auth_backend.py` (port 5000)**
  - `POST /api/signup`
  - `POST /api/login`
  - `POST /api/send-verification-code`
  - `POST /api/verify-code`
  - `POST /api/reset-password`
  - `GET /api/user/<username>`
  - `PUT /api/user/update/<username>`
  - `DELETE /api/user/delete/<username>`
  - `PUT /api/user/update-password/<username>`
  - `POST /api/user-history`
  - `GET /api/user-history/<username>`
  - `DELETE /api/user-history/delete/<username>`
  - `DELETE /api/user-history/delete-one`
  - `GET /api/users`

- **Transcript backend – `transcript_backend.py` (port 5001)**
  - `GET /transcript?videoId=<id>`
  - `POST /segment-transcript`
  - `POST /summarize`

- **Merge backend – `merge_backend.py` (port 5002)**
  - `POST /merge`
  - `GET /merge/<merge_id>`
  - `POST /voiceover`

- **Proxy server – `server.js` (port 8080)**
  - `GET /proxy/:videoId`

---

### 7. Where to start if you want to make changes

- **Change colors, layout, text**  
  - Edit `App.css`, `Background.css`, `Navbar.css`, `Footer.css`, and individual page components (e.g. `SearchPage.js`, `TranscriptViewer.js`).

- **Change which data is saved for users or history**  
  - Backend: `auth_backend.py` (`users`, `history` logic).  
  - Frontend: `panel_pages/HistoryPage.js`, `panel_pages/AccountInfoPage.js`, `admin_pages/*`.

- **Change how transcripts are fetched or summarized**  
  - `transcript_backend.py` – logic + fallbacks + summarizer.  
  - `server.js` – YouTube HTML scraping.

- **Change how merging/voiceover works**  
  - `merge_backend.py` – segment generation + ElevenLabs API.

- **Add a new page**  
  - Create a React component in `src/`, and register a route in `App.js`.

If you tell me what kind of change you want to make (for example “change the search algorithm” or “simplify transcript fallback”), I can point you to the exact lines and suggest concrete edits.

---

### 8. Testing & debugging

- **Cypress** E2E tests are configured in `cypress.config.cjs`.
  - Run: `npx cypress run` or `npx cypress open`.
- For backend debugging, run Flask apps with `debug=True` (already set in the `if __name__ == '__main__'` blocks).
- Check that ports `3000`, `5000`, `5001`, `5002`, `8080` are not used by other apps.

---

This `README` should give you the **big picture** and a **map of files** so you can confidently start modifying the project.
