# =====================================================
# AI Video Summarizer - Multi-stage Docker Build
# =====================================================

# Stage 1: Build React frontend
FROM node:22-alpine AS frontend-build
WORKDIR /app
COPY package*.json ./
RUN npm ci --silent
COPY src/ ./src/
COPY public/ ./public/
RUN npm run build

# Stage 2: Python backend with ML models and Node.js 22 runtime
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    NODE_PATH=/usr/bin/node

# System dependencies: FFmpeg, curl, certificates, and Node.js 22 (for yt-dlp EJS challenges)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl ca-certificates gnupg && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download ML models during build (avoids first-run delay)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"
RUN python -c "from transformers import AutoTokenizer, AutoModelForSeq2SeqLM; AutoTokenizer.from_pretrained('sshleifer/distilbart-cnn-12-6'); AutoModelForSeq2SeqLM.from_pretrained('sshleifer/distilbart-cnn-12-6')"
# Verify librosa + ffmpeg work (audio energy scorer — replaces CLIP)
RUN python -c "import librosa; import numpy as np; print('librosa OK:', librosa.__version__)"

# Application source code
COPY backend/ ./backend/
COPY video_cache_manager.py ./
COPY cookies.txt* ./

# Frontend production build for single-port serving
COPY --from=frontend-build /app/build ./build/
COPY --from=frontend-build /app/build ./static/

# Create persistent cache directories
RUN mkdir -p audio_cache/highlights audio_cache/video_cache audio_cache/video_downloads faiss_index

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
