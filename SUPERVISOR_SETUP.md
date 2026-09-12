# Supervisor Setup Guide: VidFusion
This document provides instructions for a fresh-machine deployment of the VidFusion platform.

## A. Prerequisites
1. **Python**: 3.12+ (tested on 3.12.3)
2. **Node.js**: v20+ (tested on v20.20.0) with `npm`
3. **FFmpeg**: v6.1+ (must be installed on the system, e.g., `sudo apt install ffmpeg`)
4. **MongoDB**: v7+ (running locally via Docker or native)
5. **Git**

## B. Installation
1. Clone the repository:
   ```bash
   git clone <repository_url>
   cd Video-summarization
   ```
2. Set up the Python virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
   *(Note: This installs `yt-dlp` into the virtual environment automatically).*
3. Install frontend dependencies:
   ```bash
   npm install
   ```

## C. Environment Setup
Create a `.env` file in the root directory (using `.env.example` as a template):
```bash
cp .env.example .env
```
**Required API Keys**:
- `REACT_APP_YOUTUBE_API_KEY`: Required for the frontend to perform YouTube keyword searches.
- `JWT_SECRET_KEY`: Can be any secure random string.
*(No other API keys are strictly required. Gemini/OpenAI are disabled by default).*

## D. MongoDB Setup
The backend requires a MongoDB connection. The easiest way is via Docker:
```bash
sudo docker compose up -d mongo
```
Verify it is running on `mongodb://localhost:27017/`. (If you use a cloud Atlas URI, update `MONGODB_URI` in `.env`).

## E. Model Pre-download/Cache Setup
The CORE pipeline relies entirely on open-source HuggingFace models. They will automatically download on the first run, but you can pre-warm the cache to avoid timeouts during demonstration:
```bash
source venv/bin/activate
python prewarm_demo.py
```
**Models Downloaded**:
- **Summarization**: `sshleifer/distilbart-cnn-12-6`
- **Embedding/Semantic Search**: `BAAI/bge-base-en-v1.5`
- **Transcription**: `openai/whisper` (base)

**Note on Ollama**:
Ollama is strictly **OPTIONAL**. 
- The CORE pipeline uses TF-IDF keyphrase extraction and FAISS raw segment retrieval if Ollama is not detected.
- **No code will crash if Ollama is absent.**
- `ENABLE_CONCEPT_LLM=false` in `.env` by default.

## F. Backend Start
Ensure the virtual environment is activated and start the FastAPI server:
```bash
source venv/bin/activate
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

## G. Frontend Start
In a new terminal window, start the React development server:
```bash
npm start
```
The application will be available at `http://localhost:3000`.

## H. Verification Checklist
- [ ] MongoDB is running and accessible on port 27017.
- [ ] `ffmpeg -version` works in the terminal.
- [ ] `yt-dlp --version` works inside the `venv`.
- [ ] Backend starts without fatal errors (warnings about Ollama are normal).
- [ ] Frontend successfully loads and can search videos (YouTube API Key working).

## I. Common Failure Recovery
- **"ffmpeg: command not found"**: Ensure FFmpeg is installed system-wide (`sudo apt install ffmpeg`).
- **"429 Too Many Requests" on YouTube Search**: The `REACT_APP_YOUTUBE_API_KEY` is exhausted or invalid.
- **Backend crashes on startup with FAISS error**: Delete the `faiss_index` directory and restart (dimension mismatch).
- **Video fails to download**: Run `pip install -U yt-dlp` in the `venv` to get the latest YouTube patches.
- **"Connection refused" to MongoDB**: Ensure the Docker container is running (`docker ps`) or update `MONGODB_URI`.
