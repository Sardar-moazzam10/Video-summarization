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
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download ML models during build (avoids first-run delay)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
RUN python -c "from transformers import pipeline; pipeline('summarization', model='facebook/bart-large-cnn')"

# Backend code
COPY backend/ ./backend/

# Frontend build
COPY --from=frontend-build /app/build ./static/

# Create cache directories
RUN mkdir -p audio_cache faiss_index

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
