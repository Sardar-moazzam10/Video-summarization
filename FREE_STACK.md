# 100% FREE Technology Stack

> Zero cost to run. No API keys required for core functionality.

---

## Summary

This application runs entirely on **FREE** tools and services. You don't need to pay anything to use all features.

---

## Complete FREE Stack

### Backend (Python)

| Component | Tool | Cost | Notes |
|-----------|------|------|-------|
| **Web Framework** | FastAPI | FREE | Open source, high performance |
| **Database** | MongoDB Atlas | FREE | 512MB free tier |
| **Transcript** | youtube-transcript-api | FREE | No API key needed |
| **Transcript Fallback** | yt-dlp | FREE | Open source |
| **Summarization** | BART / T5 | FREE | Local HuggingFace models |
| **Embeddings** | sentence-transformers | FREE | Local MiniLM model |
| **Text-to-Speech** | Microsoft Edge TTS | FREE | No limits, 20+ voices |
| **Authentication** | bcrypt + JWT | FREE | python-jose + passlib |
| **Rate Limiting** | Custom middleware | FREE | Built-in |

### Frontend (React)

| Component | Tool | Cost | Notes |
|-----------|------|------|-------|
| **Framework** | React 18 | FREE | Open source |
| **Styling** | Tailwind CSS | FREE | Open source |
| **Animations** | Framer Motion | FREE | Open source |
| **HTTP Client** | Axios | FREE | Open source |
| **Routing** | React Router | FREE | Open source |

### DevOps

| Component | Tool | Cost | Notes |
|-----------|------|------|-------|
| **Containerization** | Docker | FREE | Open source |
| **Version Control** | Git | FREE | Open source |
| **Hosting (Option)** | Railway | FREE | 500 hours/month |
| **Hosting (Option)** | Render | FREE | 750 hours/month |
| **Hosting (Option)** | Vercel | FREE | For frontend |

---

## Text-to-Speech: Edge TTS

Microsoft Edge TTS is **100% FREE** with:

- **No API key required**
- **No usage limits**
- **20+ high-quality neural voices**
- **Multiple languages and accents**

### Available Voices

```
English (US):
- Aria (Female) - Professional
- Guy (Male) - Friendly
- Jenny (Female) - Conversational
- Davis (Male) - Calm
- Michelle (Female) - Friendly

English (UK):
- Sonia (Female) - Professional
- Ryan (Male) - Professional

English (Australia):
- Natasha (Female)
- William (Male)

English (India):
- Neerja (Female)
- Prabhat (Male)
```

### Usage

```python
from backend.services.voice_service import get_voice_service

service = get_voice_service()

# Generate audio (FREE!)
audio = await service.generate_audio(
    text="Hello, this is a test.",
    voice_key="aria"  # or "guy", "jenny", etc.
)
```

---

## AI Models (All FREE, Run Locally)

### Summarization
- **Model**: facebook/bart-large-cnn OR t5-small
- **Size**: ~500MB - 1.5GB
- **Runs on**: CPU (GPU optional)

### Semantic Embeddings
- **Model**: all-MiniLM-L6-v2
- **Size**: ~90MB
- **Speed**: Very fast on CPU

### Topic Clustering
- **Algorithm**: AgglomerativeClustering (scikit-learn)
- **Cost**: FREE (local computation)

---

## Database: MongoDB Atlas Free Tier

- **Storage**: 512MB
- **Connections**: 100 concurrent
- **Features**: All core features available
- **Signup**: https://mongodb.com/atlas

---

## Removed Paid Dependencies

The following paid services have been **removed** or made **optional**:

| Service | Status | Replacement |
|---------|--------|-------------|
| ElevenLabs TTS | REMOVED | Edge TTS (FREE) |
| OpenAI GPT | OPTIONAL | BART/T5 (FREE) |
| YouTube Data API | NOT NEEDED | youtube-transcript-api (FREE) |
| Paid Hosting | OPTIONAL | Railway/Render free tier |

---

## Environment Variables

Only these are required:

```bash
# Required
MONGODB_URI=mongodb+srv://...  # Free Atlas connection string
SECRET_KEY=your-secret-key-here  # Any random string

# Optional (not needed for core functionality)
# ELEVEN_API_KEY=  # NOT NEEDED - using Edge TTS
# OPENAI_API_KEY=  # NOT NEEDED - using local models
```

---

## Cost Breakdown

| Usage Level | Monthly Cost |
|-------------|--------------|
| Development | $0.00 |
| 100 users/day | $0.00 |
| 1000 users/day | $0.00* |
| 10000+ users/day | Consider paid hosting |

*Free tier limits apply for hosting. Self-hosted = always free.

---

## Quick Start (Free)

```bash
# 1. Clone and install
cd Video-summarization
pip install -r requirements.txt

# 2. Set up free MongoDB Atlas
# Visit: https://mongodb.com/atlas
# Create free cluster, get connection string

# 3. Create .env file
echo "MONGODB_URI=your_atlas_uri" > .env
echo "SECRET_KEY=any_random_string" >> .env

# 4. Run backend
uvicorn backend.main:app --reload --port 8000

# 5. Run frontend (separate terminal)
npm start
```

---

## Verification

Test that everything works:

```bash
# Health check
curl http://localhost:8000/health

# List FREE voices
curl http://localhost:8000/api/v1/voice/voices

# Generate FREE audio
curl -X POST http://localhost:8000/api/v1/voice/generate \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, this is free!", "voice": "aria"}'
```

---

**Total Cost: $0.00** 🎉
