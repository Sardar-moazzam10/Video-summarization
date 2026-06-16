# =====================================================
# AI Video Summarizer - Multi-stage Docker Build
# =====================================================

# Stage 1: Build React frontend
FROM node:18-alpine AS frontend-build
WORKDIR /app
COPY package*.json ./
RUN npm ci --silent
COPY src/ ./src/
COPY public/ ./public/
RUN npm run build

# Stage 2: Python backend with ML models
FROM python:3.12-slim
WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp && \
    chmod a+rx /usr/local/bin/yt-dlp && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download ML models during build (avoids first-run delay)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"
RUN python -c "from transformers import AutoTokenizer, AutoModelForSeq2SeqLM; AutoTokenizer.from_pretrained('sshleifer/distilbart-cnn-12-6'); AutoModelForSeq2SeqLM.from_pretrained('sshleifer/distilbart-cnn-12-6')"

# Backend code
COPY backend/ ./backend/

# Frontend build
COPY --from=frontend-build /app/build ./static/

# Create cache directories
RUN mkdir -p audio_cache faiss_index

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
