# AI Video Summarizer - Production Roadmap

> Inspired by Recall.ai | Designed for FYP Excellence

---

## Executive Summary

Transform raw YouTube content into **distilled knowledge outputs** that respect user time while preserving intellectual value. The system should feel like having a brilliant assistant who watches videos for you and reports back with perfect clarity.

**Core Promise:** "Understand everything important without watching the originals."

---

## Part 1: System Architecture

### Current State vs Target State

```
CURRENT (Prototype)                    TARGET (Production)
┌─────────────────────┐               ┌─────────────────────────────────────┐
│  Monolithic Flask   │               │         API Gateway (FastAPI)        │
│  + React Frontend   │      →        ├─────────────────────────────────────┤
│  (tightly coupled)  │               │  ┌─────────┐ ┌─────────┐ ┌────────┐ │
└─────────────────────┘               │  │Transcript│ │ Fusion  │ │ Voice  │ │
                                      │  │ Service │ │ Engine  │ │Service │ │
                                      │  └────┬────┘ └────┬────┘ └───┬────┘ │
                                      │       └──────┬────┴─────┬────┘      │
                                      │         ┌────▼────┐                 │
                                      │         │ MongoDB │                 │
                                      │         │ + Redis │                 │
                                      │         └─────────┘                 │
                                      └─────────────────────────────────────┘
```

### Recommended Directory Structure

```
video-summarizer/
├── backend/
│   ├── api/                      # FastAPI routes
│   │   ├── __init__.py
│   │   ├── auth.py              # Authentication endpoints
│   │   ├── transcript.py        # Transcript retrieval
│   │   ├── summarize.py         # Single video summarization
│   │   ├── merge.py             # Multi-video fusion
│   │   └── voice.py             # TTS generation
│   │
│   ├── core/                    # Shared utilities
│   │   ├── config.py            # Environment configuration
│   │   ├── database.py          # MongoDB connection
│   │   ├── security.py          # JWT, bcrypt, rate limiting
│   │   └── exceptions.py        # Custom error classes
│   │
│   ├── services/                # Business logic (SWAPPABLE)
│   │   ├── transcript/
│   │   │   ├── base.py          # Abstract interface
│   │   │   ├── youtube_api.py   # Primary: youtube-transcript-api
│   │   │   └── ytdlp.py         # Fallback: yt-dlp
│   │   │
│   │   ├── summarization/
│   │   │   ├── base.py          # Abstract interface
│   │   │   ├── bart.py          # BART-large-CNN
│   │   │   ├── t5.py            # T5 (fallback)
│   │   │   └── openai.py        # GPT-4 (premium tier)
│   │   │
│   │   ├── fusion/
│   │   │   ├── engine.py        # Multi-video fusion logic
│   │   │   ├── clustering.py    # Topic clustering
│   │   │   └── deduplication.py # Semantic deduplication
│   │   │
│   │   └── voice/
│   │       ├── base.py          # Abstract interface
│   │       ├── elevenlabs.py    # ElevenLabs TTS
│   │       ├── edge_tts.py      # Microsoft Edge TTS (FREE)
│   │       └── gtts.py          # Google TTS (fallback)
│   │
│   ├── models/                  # Pydantic schemas
│   │   ├── job.py               # Job state machine
│   │   ├── user.py              # User model
│   │   └── summary.py           # Summary output model
│   │
│   └── main.py                  # FastAPI application entry
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── common/          # Reusable UI atoms
│   │   │   │   ├── Button.jsx
│   │   │   │   ├── Card.jsx
│   │   │   │   ├── Input.jsx
│   │   │   │   ├── Skeleton.jsx
│   │   │   │   └── Toast.jsx
│   │   │   │
│   │   │   ├── layout/          # Page structure
│   │   │   │   ├── Header.jsx
│   │   │   │   ├── Sidebar.jsx
│   │   │   │   └── Footer.jsx
│   │   │   │
│   │   │   ├── video/           # Video-specific components
│   │   │   │   ├── VideoInput.jsx
│   │   │   │   ├── VideoCard.jsx
│   │   │   │   └── VideoGrid.jsx
│   │   │   │
│   │   │   └── summary/         # Summary display
│   │   │       ├── DurationSelector.jsx
│   │   │       ├── ProgressTracker.jsx
│   │   │       ├── SummaryPanel.jsx
│   │   │       └── AudioPlayer.jsx
│   │   │
│   │   ├── pages/
│   │   │   ├── HomePage.jsx
│   │   │   ├── SummarizePage.jsx
│   │   │   ├── ResultPage.jsx
│   │   │   └── HistoryPage.jsx
│   │   │
│   │   ├── hooks/               # Custom React hooks
│   │   │   ├── useJob.js        # Job polling logic
│   │   │   ├── useAuth.js       # Authentication state
│   │   │   └── useToast.js      # Notification system
│   │   │
│   │   ├── services/            # API client layer
│   │   │   └── api.js           # Axios configuration
│   │   │
│   │   └── styles/
│   │       ├── globals.css      # Tailwind + custom tokens
│   │       └── animations.css   # Framer Motion presets
│   │
│   └── tailwind.config.js
│
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Part 2: AI Pipeline Architecture

### The Knowledge Extraction Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        KNOWLEDGE EXTRACTION PIPELINE                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌───────┐ │
│  │  INPUT   │───▶│TRANSCRIPT│───▶│ ANALYSIS │───▶│ COMPRESS │───▶│OUTPUT │ │
│  │YouTube   │    │Retrieval │    │ & Fusion │    │ & Format │    │Summary│ │
│  │  URLs    │    │          │    │          │    │          │    │       │ │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘    └───────┘ │
│       │               │               │               │               │     │
│       ▼               ▼               ▼               ▼               ▼     │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐   │
│  │Validate │    │ Cache   │    │ Cluster │    │Duration │    │ Format  │   │
│  │& Fetch  │    │ Check   │    │ Topics  │    │ Profile │    │ Output  │   │
│  │Metadata │    │MongoDB  │    │Sentence │    │Adaptive │    │Markdown │   │
│  │         │    │         │    │  BERT   │    │Compress │    │  JSON   │   │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘    └─────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Stage 1: Transcript Retrieval

```python
# backend/services/transcript/base.py
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

class TranscriptProvider(ABC):
    """Abstract interface for transcript providers - enables swapping"""

    @abstractmethod
    async def get_transcript(self, video_id: str) -> Optional[List[Dict]]:
        """
        Returns: [{"text": "...", "start": 0.0, "duration": 2.5}, ...]
        """
        pass

    @abstractmethod
    def supports_language(self, lang_code: str) -> bool:
        pass


class TranscriptService:
    """Orchestrates multiple providers with fallback logic"""

    def __init__(self, providers: List[TranscriptProvider], cache):
        self.providers = providers  # Priority order
        self.cache = cache

    async def get_transcript(self, video_id: str) -> Dict:
        # 1. Check cache first
        cached = await self.cache.get(f"transcript:{video_id}")
        if cached:
            return {"transcript": cached, "source": "cache", "cached": True}

        # 2. Try providers in order
        for provider in self.providers:
            try:
                transcript = await provider.get_transcript(video_id)
                if transcript:
                    await self.cache.set(f"transcript:{video_id}", transcript, ttl=86400*7)
                    return {"transcript": transcript, "source": provider.name, "cached": False}
            except Exception as e:
                continue  # Try next provider

        return None
```

### Stage 2: Content Analysis & Fusion

```python
# backend/services/fusion/engine.py
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering
import numpy as np

class FusionEngine:
    """
    Intelligent multi-video content fusion

    Key capabilities:
    1. Semantic clustering - group related ideas across videos
    2. Deduplication - remove redundant content
    3. Conflict detection - identify disagreements
    4. Narrative synthesis - create coherent flow
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.embedder = SentenceTransformer(model_name)
        self.similarity_threshold = 0.85

    async def fuse(self, transcripts: List[Dict], target_duration: int) -> Dict:
        """
        Main fusion entry point

        Args:
            transcripts: List of transcript objects with video metadata
            target_duration: Target output duration in minutes

        Returns:
            {
                "fused_text": "...",
                "topics": [...],
                "conflicts": [...],
                "metadata": {...}
            }
        """
        # 1. Extract and clean sentences
        all_sentences = self._extract_sentences(transcripts)

        # 2. Generate embeddings
        embeddings = self.embedder.encode(all_sentences)

        # 3. Cluster by topic
        clusters = self._cluster_topics(embeddings, all_sentences)

        # 4. Deduplicate within clusters
        unique_content = self._deduplicate(clusters, embeddings)

        # 5. Detect conflicts
        conflicts = self._detect_conflicts(unique_content, embeddings)

        # 6. Synthesize narrative
        narrative = self._synthesize_narrative(unique_content, target_duration)

        return {
            "fused_text": narrative,
            "topics": [c["topic"] for c in clusters],
            "conflicts": conflicts,
            "metadata": {
                "source_sentences": len(all_sentences),
                "unique_sentences": len(unique_content),
                "dedup_ratio": len(unique_content) / len(all_sentences),
                "clusters": len(clusters)
            }
        }

    def _cluster_topics(self, embeddings, sentences):
        """Group sentences by semantic similarity"""
        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=0.5,
            metric='cosine',
            linkage='average'
        )
        labels = clustering.fit_predict(embeddings)

        clusters = {}
        for idx, label in enumerate(labels):
            if label not in clusters:
                clusters[label] = {"sentences": [], "embeddings": []}
            clusters[label]["sentences"].append(sentences[idx])
            clusters[label]["embeddings"].append(embeddings[idx])

        # Generate topic labels for each cluster
        for label, cluster in clusters.items():
            cluster["topic"] = self._generate_topic_label(cluster["sentences"])

        return list(clusters.values())

    def _deduplicate(self, clusters, embeddings):
        """Remove semantically similar sentences, keeping the best representative"""
        unique = []
        seen_embeddings = []

        for cluster in clusters:
            for i, sentence in enumerate(cluster["sentences"]):
                emb = cluster["embeddings"][i]

                # Check if similar to any seen sentence
                is_duplicate = False
                for seen_emb in seen_embeddings:
                    similarity = np.dot(emb, seen_emb) / (np.linalg.norm(emb) * np.linalg.norm(seen_emb))
                    if similarity > self.similarity_threshold:
                        is_duplicate = True
                        break

                if not is_duplicate:
                    unique.append(sentence)
                    seen_embeddings.append(emb)

        return unique

    def _detect_conflicts(self, sentences, embeddings):
        """Identify contradicting statements"""
        conflicts = []
        # Use NLI model or keyword patterns to detect contradictions
        contradiction_patterns = [
            ("increase", "decrease"),
            ("beneficial", "harmful"),
            ("should", "should not"),
            ("always", "never"),
        ]

        for i, sent1 in enumerate(sentences):
            for j, sent2 in enumerate(sentences[i+1:], i+1):
                for pos, neg in contradiction_patterns:
                    if pos in sent1.lower() and neg in sent2.lower():
                        conflicts.append({
                            "statement_1": sent1,
                            "statement_2": sent2,
                            "type": f"{pos}_vs_{neg}"
                        })

        return conflicts[:5]  # Limit to top 5 conflicts

    def _synthesize_narrative(self, sentences, target_duration):
        """Create coherent narrative with transitions"""
        target_words = target_duration * 150  # ~150 WPM average

        transitions = [
            "Additionally, ",
            "Furthermore, ",
            "Building on this, ",
            "In contrast, ",
            "Similarly, ",
            "Notably, ",
            "To elaborate, ",
        ]

        narrative_parts = []
        current_words = 0

        for i, sentence in enumerate(sentences):
            words = len(sentence.split())
            if current_words + words > target_words:
                break

            if i > 0 and i % 3 == 0:  # Add transition every 3 sentences
                sentence = transitions[i % len(transitions)] + sentence

            narrative_parts.append(sentence)
            current_words += words

        return "\n\n".join(narrative_parts)
```

### Stage 3: Duration-Based Compression

```python
# backend/services/summarization/duration_profiles.py
from dataclasses import dataclass
from typing import Literal

@dataclass
class DurationProfile:
    """
    Defines compression behavior based on target duration
    """
    name: str
    minutes: int
    target_words: int
    style: Literal["headline", "brief", "standard", "comprehensive"]
    max_topics: int
    include_examples: bool
    include_transitions: bool
    wpm: int  # Words per minute for audio
    description: str

# Pre-defined profiles
DURATION_PROFILES = {
    5: DurationProfile(
        name="Quick Digest",
        minutes=5,
        target_words=750,
        style="headline",
        max_topics=5,
        include_examples=False,
        include_transitions=False,
        wpm=150,
        description="Key highlights only. Perfect for quick updates."
    ),
    10: DurationProfile(
        name="Brief Summary",
        minutes=10,
        target_words=1500,
        style="brief",
        max_topics=8,
        include_examples=True,
        include_transitions=True,
        wpm=150,
        description="Main ideas with supporting context."
    ),
    15: DurationProfile(
        name="Full Summary",
        minutes=15,
        target_words=2250,
        style="standard",
        max_topics=12,
        include_examples=True,
        include_transitions=True,
        wpm=150,
        description="Comprehensive coverage with examples."
    ),
    20: DurationProfile(
        name="Deep Dive",
        minutes=20,
        target_words=3000,
        style="comprehensive",
        max_topics=15,
        include_examples=True,
        include_transitions=True,
        wpm=150,
        description="Maximum detail and nuance."
    ),
}


class AdaptiveSummarizer:
    """
    Adjusts summarization based on duration profile
    """

    def __init__(self, model):
        self.model = model

    async def summarize(self, text: str, profile: DurationProfile) -> str:
        """
        Generate summary matching the duration profile
        """
        # Calculate compression parameters
        input_words = len(text.split())
        compression_ratio = profile.target_words / input_words

        # Adjust model parameters based on style
        if profile.style == "headline":
            max_length = 150
            min_length = 50
        elif profile.style == "brief":
            max_length = 300
            min_length = 100
        elif profile.style == "standard":
            max_length = 500
            min_length = 200
        else:  # comprehensive
            max_length = 800
            min_length = 400

        # Multi-pass summarization for long content
        if input_words > 4000:
            return await self._progressive_summarize(text, profile)

        # Single-pass for shorter content
        return self.model.summarize(
            text,
            max_length=max_length,
            min_length=min_length
        )

    async def _progressive_summarize(self, text: str, profile: DurationProfile) -> str:
        """
        Multi-pass summarization for very long content

        Pass 1: Chunk and summarize sections
        Pass 2: Synthesize section summaries
        Pass 3: Final polish and formatting
        """
        # Split into chunks of ~2000 words
        words = text.split()
        chunk_size = 2000
        chunks = [' '.join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]

        # Pass 1: Summarize each chunk
        chunk_summaries = []
        for chunk in chunks:
            summary = self.model.summarize(chunk, max_length=300, min_length=100)
            chunk_summaries.append(summary)

        # Pass 2: Combine and re-summarize
        combined = ' '.join(chunk_summaries)

        # Pass 3: Final summarization to target length
        final = self.model.summarize(
            combined,
            max_length=profile.target_words // 2,  # Account for expansion in formatting
            min_length=profile.target_words // 4
        )

        return final
```

### Stage 4: Voice Generation (Swappable)

```python
# backend/services/voice/base.py
from abc import ABC, abstractmethod
from typing import Optional

class VoiceProvider(ABC):
    """Abstract interface for TTS providers"""

    name: str
    supports_ssml: bool
    max_characters: int

    @abstractmethod
    async def generate(self, text: str, voice_id: str = None) -> bytes:
        """Generate audio bytes from text"""
        pass

    @abstractmethod
    def get_available_voices(self) -> list:
        """List available voice options"""
        pass


# backend/services/voice/edge_tts.py (FREE option)
import edge_tts

class EdgeTTSProvider(VoiceProvider):
    """
    Microsoft Edge TTS - FREE, high quality
    Recommended for cost-sensitive deployments
    """

    name = "edge_tts"
    supports_ssml = True
    max_characters = 100000

    async def generate(self, text: str, voice_id: str = "en-US-AriaNeural") -> bytes:
        communicate = edge_tts.Communicate(text, voice_id)
        audio_chunks = []

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        return b''.join(audio_chunks)

    def get_available_voices(self) -> list:
        return [
            {"id": "en-US-AriaNeural", "name": "Aria (Female)", "style": "professional"},
            {"id": "en-US-GuyNeural", "name": "Guy (Male)", "style": "friendly"},
            {"id": "en-US-JennyNeural", "name": "Jenny (Female)", "style": "conversational"},
            {"id": "en-GB-SoniaNeural", "name": "Sonia (British Female)", "style": "professional"},
        ]


# backend/services/voice/elevenlabs.py (Premium option)
import aiohttp

class ElevenLabsProvider(VoiceProvider):
    """
    ElevenLabs - Premium quality, costs money
    Use for production with paying users
    """

    name = "elevenlabs"
    supports_ssml = False
    max_characters = 5000

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.elevenlabs.io/v1"

    async def generate(self, text: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM") -> bytes:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/text-to-speech/{voice_id}",
                headers={"xi-api-key": self.api_key},
                json={
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75
                    }
                }
            ) as response:
                return await response.read()


# backend/services/voice/service.py
class VoiceService:
    """
    Orchestrates voice generation with caching and fallbacks
    """

    def __init__(self, providers: list, cache):
        self.providers = {p.name: p for p in providers}
        self.cache = cache
        self.default_provider = providers[0].name

    async def generate(
        self,
        text: str,
        provider_name: str = None,
        voice_id: str = None
    ) -> bytes:
        # Check cache by content hash
        content_hash = hashlib.md5(text.encode()).hexdigest()
        cache_key = f"audio:{content_hash}:{provider_name}:{voice_id}"

        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        # Generate fresh audio
        provider = self.providers.get(provider_name or self.default_provider)
        audio = await provider.generate(text, voice_id)

        # Cache for 7 days
        await self.cache.set(cache_key, audio, ttl=86400*7)

        return audio
```

---

## Part 3: UI/UX Design System (Recall.ai Inspired)

### Design Tokens

```javascript
// tailwind.config.js
module.exports = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Primary palette (Recall.ai inspired)
        brand: {
          50: '#eef6ff',
          100: '#d9ebff',
          200: '#bcdeff',
          300: '#8ecaff',
          400: '#58adff',
          500: '#478BE0',  // Primary accent
          600: '#2F61A0',  // Hover state
          700: '#1e4a7c',
          800: '#1c3d5f',
          900: '#1c3550',
          950: '#000212',  // Deep background
        },

        // Surface colors
        surface: {
          DEFAULT: '#0a0f1a',
          elevated: '#111827',
          overlay: 'rgba(17, 24, 39, 0.95)',
        },

        // Text hierarchy
        content: {
          primary: '#ffffff',
          secondary: 'rgba(255, 255, 255, 0.7)',
          tertiary: 'rgba(255, 255, 255, 0.5)',
          muted: 'rgba(255, 255, 255, 0.3)',
        },

        // Semantic colors
        success: '#22c55e',
        warning: '#f59e0b',
        error: '#ef4444',
        info: '#3b82f6',
      },

      fontFamily: {
        sans: ['Montserrat', 'Inter', 'system-ui', 'sans-serif'],
        display: ['Montserrat', 'sans-serif'],
      },

      animation: {
        'slide-up': 'slideUp 0.5s ease-out',
        'fade-in': 'fadeIn 0.3s ease-out',
        'pulse-ring': 'pulseRing 2s ease-in-out infinite',
        'gradient-shift': 'gradientShift 3s ease infinite',
      },

      keyframes: {
        slideUp: {
          '0%': { transform: 'translateY(20px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        pulseRing: {
          '0%, 100%': { transform: 'scale(1)', opacity: '0.5' },
          '50%': { transform: 'scale(1.5)', opacity: '0' },
        },
        gradientShift: {
          '0%, 100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },
      },

      backgroundImage: {
        'gradient-radial': 'radial-gradient(circle at center, var(--tw-gradient-stops))',
        'gradient-text': 'linear-gradient(135deg, #478BE0 0%, #ffffff 100%)',
      },
    },
  },
}
```

### Core Component Library

```jsx
// src/components/common/GradientText.jsx
export const GradientText = ({ children, className = "" }) => (
  <span className={`
    bg-gradient-to-r from-brand-500 via-brand-400 to-white
    bg-clip-text text-transparent
    ${className}
  `}>
    {children}
  </span>
);

// src/components/common/Card.jsx
export const Card = ({ children, className = "", glow = false }) => (
  <div className={`
    bg-surface-elevated rounded-2xl
    border border-white/10
    backdrop-blur-sm
    transition-all duration-300
    ${glow ? 'shadow-lg shadow-brand-500/20 hover:shadow-brand-500/30' : ''}
    ${className}
  `}>
    {children}
  </div>
);

// src/components/common/Button.jsx
export const Button = ({
  children,
  variant = "primary",
  size = "md",
  loading = false,
  ...props
}) => {
  const variants = {
    primary: "bg-brand-500 hover:bg-brand-600 text-white",
    secondary: "bg-white/10 hover:bg-white/20 text-white border border-white/20",
    ghost: "hover:bg-white/5 text-content-secondary",
  };

  const sizes = {
    sm: "px-4 py-2 text-sm",
    md: "px-6 py-3 text-base",
    lg: "px-8 py-4 text-lg",
  };

  return (
    <button
      className={`
        ${variants[variant]}
        ${sizes[size]}
        rounded-xl font-medium
        transition-all duration-200
        disabled:opacity-50 disabled:cursor-not-allowed
        flex items-center justify-center gap-2
      `}
      disabled={loading}
      {...props}
    >
      {loading && (
        <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
        </svg>
      )}
      {children}
    </button>
  );
};

// src/components/common/ProgressRing.jsx
export const ProgressRing = ({ progress, size = 120, strokeWidth = 8 }) => {
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - (progress / 100) * circumference;

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg className="transform -rotate-90" width={size} height={size}>
        {/* Background circle */}
        <circle
          className="text-white/10"
          strokeWidth={strokeWidth}
          stroke="currentColor"
          fill="transparent"
          r={radius}
          cx={size / 2}
          cy={size / 2}
        />
        {/* Progress circle */}
        <circle
          className="text-brand-500 transition-all duration-500"
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          stroke="currentColor"
          fill="transparent"
          r={radius}
          cx={size / 2}
          cy={size / 2}
        />
      </svg>
      {/* Center content */}
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-2xl font-bold text-white">{Math.round(progress)}%</span>
      </div>
      {/* Pulse ring */}
      <div className="absolute inset-0 rounded-full border-2 border-brand-500/30 animate-pulse-ring" />
    </div>
  );
};
```

### Page Layouts

```jsx
// src/pages/HomePage.jsx - Recall.ai inspired landing
import { motion } from 'framer-motion';
import { GradientText, Button, Card } from '../components/common';

const HomePage = () => {
  return (
    <div className="min-h-screen bg-brand-950">
      {/* Hero Section */}
      <section className="relative overflow-hidden">
        {/* Background gradient */}
        <div className="absolute inset-0 bg-gradient-radial from-brand-500/20 via-transparent to-transparent" />

        <div className="relative max-w-6xl mx-auto px-6 pt-32 pb-20">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="text-center"
          >
            <h1 className="text-5xl md:text-7xl font-bold mb-6">
              <GradientText>Summarize Anything,</GradientText>
              <br />
              <span className="text-white">Forget Nothing</span>
            </h1>

            <p className="text-xl text-content-secondary max-w-2xl mx-auto mb-10">
              Transform hours of YouTube content into distilled knowledge
              in minutes. AI-powered summaries that respect your time.
            </p>

            <div className="flex gap-4 justify-center">
              <Button size="lg">
                Start Summarizing
              </Button>
              <Button variant="secondary" size="lg">
                Watch Demo
              </Button>
            </div>
          </motion.div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="max-w-6xl mx-auto px-6 py-20">
        <div className="grid md:grid-cols-3 gap-6">
          {features.map((feature, idx) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: idx * 0.1 }}
            >
              <Card className="p-6 h-full hover:border-brand-500/50">
                <div className="w-12 h-12 rounded-xl bg-brand-500/20 flex items-center justify-center mb-4">
                  {feature.icon}
                </div>
                <h3 className="text-xl font-semibold text-white mb-2">
                  {feature.title}
                </h3>
                <p className="text-content-secondary">
                  {feature.description}
                </p>
              </Card>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Duration Selector Preview */}
      <section className="max-w-4xl mx-auto px-6 py-20">
        <h2 className="text-3xl font-bold text-center text-white mb-12">
          Choose Your <GradientText>Depth</GradientText>
        </h2>

        <div className="grid grid-cols-4 gap-4">
          {[5, 10, 15, 20].map((minutes) => (
            <Card
              key={minutes}
              className="p-6 text-center cursor-pointer hover:border-brand-500"
            >
              <div className="text-4xl font-bold text-brand-500 mb-2">
                {minutes}
              </div>
              <div className="text-sm text-content-secondary">minutes</div>
              <div className="text-xs text-content-tertiary mt-2">
                {minutes === 5 && "Quick Digest"}
                {minutes === 10 && "Brief Summary"}
                {minutes === 15 && "Full Coverage"}
                {minutes === 20 && "Deep Dive"}
              </div>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
};

const features = [
  {
    icon: "🎯",
    title: "Smart Compression",
    description: "AI extracts key insights while preserving essential context and nuance."
  },
  {
    icon: "🔗",
    title: "Multi-Video Fusion",
    description: "Combine multiple sources into one coherent knowledge output."
  },
  {
    icon: "🎙️",
    title: "Audio Narration",
    description: "Listen to your summaries with natural AI-generated voice."
  },
];
```

---

## Part 4: API Contracts

### RESTful API Design

```yaml
# OpenAPI 3.0 Specification

openapi: 3.0.3
info:
  title: Video Summarizer API
  version: 2.0.0
  description: AI-powered video summarization service

servers:
  - url: http://localhost:8000/api/v1

paths:
  /summarize:
    post:
      summary: Create new summarization job
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - video_ids
                - duration_minutes
              properties:
                video_ids:
                  type: array
                  items:
                    type: string
                  minItems: 1
                  maxItems: 10
                  example: ["dQw4w9WgXcQ", "9bZkp7q19f0"]
                duration_minutes:
                  type: integer
                  enum: [5, 10, 15, 20]
                  example: 10
                generate_audio:
                  type: boolean
                  default: false
                voice_provider:
                  type: string
                  enum: ["edge_tts", "elevenlabs"]
                  default: "edge_tts"
      responses:
        '202':
          description: Job accepted
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/JobCreated'

  /jobs/{job_id}:
    get:
      summary: Get job status
      parameters:
        - name: job_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: Job status
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/JobStatus'

  /jobs/{job_id}/result:
    get:
      summary: Get completed job result
      parameters:
        - name: job_id
          in: path
          required: true
          schema:
            type: string
            format: uuid
      responses:
        '200':
          description: Job result
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/JobResult'

components:
  schemas:
    JobCreated:
      type: object
      properties:
        job_id:
          type: string
          format: uuid
        status:
          type: string
          example: "pending"
        estimated_seconds:
          type: integer
          example: 120

    JobStatus:
      type: object
      properties:
        job_id:
          type: string
          format: uuid
        status:
          type: string
          enum: [pending, transcribing, analyzing, fusing, summarizing, generating_voice, completed, error]
        progress_percent:
          type: integer
          minimum: 0
          maximum: 100
        stage_message:
          type: string
        eta_seconds:
          type: integer
          nullable: true

    JobResult:
      type: object
      properties:
        job_id:
          type: string
          format: uuid
        status:
          type: string
        summary:
          type: object
          properties:
            text:
              type: string
            word_count:
              type: integer
            reading_time_minutes:
              type: number
        audio_url:
          type: string
          nullable: true
        metadata:
          type: object
          properties:
            source_videos:
              type: integer
            total_source_words:
              type: integer
            compression_ratio:
              type: number
            topics:
              type: array
              items:
                type: string
            conflicts:
              type: array
              items:
                type: object
            processing_time_seconds:
              type: number
```

---

## Part 5: Cost Optimization Strategy

### Free vs Paid Component Matrix

| Component | Free Option | Paid Option | When to Upgrade |
|-----------|-------------|-------------|-----------------|
| **Transcript** | youtube-transcript-api | - | Already free |
| **Summarization** | BART-large-CNN (local) | OpenAI GPT-4 | Premium tier users |
| **Embeddings** | all-MiniLM-L6-v2 (local) | OpenAI embeddings | Never needed |
| **TTS** | Edge TTS (Microsoft) | ElevenLabs | Paying users |
| **Database** | MongoDB Atlas Free | Atlas M10+ | >5GB data |
| **Cache** | In-memory dict | Redis Cloud | >100 concurrent |
| **Hosting** | Railway/Render free | AWS/GCP | Scale >1000 users |

### Cost Per Summary Estimate

```
FREE TIER (self-hosted models):
├── Transcript fetch: $0.00
├── Summarization (BART local): $0.00 (CPU time only)
├── Fusion (MiniLM local): $0.00
├── TTS (Edge TTS): $0.00
└── Total: $0.00 per summary (just compute costs)

PREMIUM TIER (external APIs):
├── Transcript fetch: $0.00
├── Summarization (GPT-4): ~$0.03-0.10 per summary
├── Fusion (local): $0.00
├── TTS (ElevenLabs): ~$0.01 per 100 chars
└── Total: ~$0.05-0.15 per summary
```

### Caching Strategy

```python
# backend/core/cache.py
from functools import lru_cache
import hashlib
from datetime import datetime, timedelta

class CacheManager:
    """
    Multi-layer caching for cost optimization

    Layer 1: In-memory LRU (hot data, 1000 items)
    Layer 2: MongoDB (warm data, 7 days TTL)
    Layer 3: Optional Redis (for multi-instance deployments)
    """

    def __init__(self, db, redis_client=None):
        self.db = db
        self.cache_collection = db["cache"]
        self.redis = redis_client
        self._memory_cache = {}

    async def get(self, key: str):
        # Layer 1: Memory
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if entry["expires_at"] > datetime.utcnow():
                return entry["value"]
            else:
                del self._memory_cache[key]

        # Layer 2: Redis (if available)
        if self.redis:
            value = await self.redis.get(key)
            if value:
                return value

        # Layer 3: MongoDB
        entry = await self.cache_collection.find_one({"key": key})
        if entry and entry["expires_at"] > datetime.utcnow():
            # Promote to memory cache
            self._memory_cache[key] = entry
            return entry["value"]

        return None

    async def set(self, key: str, value, ttl: int = 86400):
        expires_at = datetime.utcnow() + timedelta(seconds=ttl)
        entry = {"key": key, "value": value, "expires_at": expires_at}

        # Memory cache (limit size)
        if len(self._memory_cache) < 1000:
            self._memory_cache[key] = entry

        # Redis (if available)
        if self.redis:
            await self.redis.setex(key, ttl, value)

        # MongoDB (persistent)
        await self.cache_collection.update_one(
            {"key": key},
            {"$set": entry},
            upsert=True
        )

    def cache_key_for_transcript(self, video_id: str) -> str:
        return f"transcript:{video_id}"

    def cache_key_for_audio(self, text: str, provider: str, voice: str) -> str:
        content_hash = hashlib.md5(text.encode()).hexdigest()
        return f"audio:{content_hash}:{provider}:{voice}"
```

---

## Part 6: Scalability Architecture

### Horizontal Scaling Design

```
                    ┌─────────────────┐
                    │  Load Balancer  │
                    │    (Nginx)      │
                    └────────┬────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
     ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
     │  FastAPI    │  │  FastAPI    │  │  FastAPI    │
     │  Instance 1 │  │  Instance 2 │  │  Instance 3 │
     └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
            │                │                │
            └────────────────┼────────────────┘
                             │
                    ┌────────▼────────┐
                    │     Redis       │
                    │  (Job Queue)    │
                    └────────┬────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
     ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐
     │   Worker    │  │   Worker    │  │   Worker    │
     │  (AI/GPU)   │  │  (AI/GPU)   │  │  (AI/GPU)   │
     └─────────────┘  └─────────────┘  └─────────────┘
```

### Job Queue Implementation

```python
# backend/core/queue.py
import asyncio
from typing import Callable, Dict
import uuid

class JobQueue:
    """
    Simple job queue for background processing
    Can be replaced with Celery/RQ for production
    """

    def __init__(self, db):
        self.db = db
        self.jobs_collection = db["jobs"]
        self.workers: Dict[str, Callable] = {}
        self._running = False

    def register_worker(self, job_type: str, handler: Callable):
        """Register a handler for a job type"""
        self.workers[job_type] = handler

    async def enqueue(self, job_type: str, payload: dict) -> str:
        """Add job to queue"""
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "type": job_type,
            "payload": payload,
            "status": "pending",
            "progress_percent": 0,
            "stage_message": "Queued",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        await self.jobs_collection.insert_one(job)
        return job_id

    async def update_job(self, job_id: str, **updates):
        """Update job status"""
        updates["updated_at"] = datetime.utcnow()
        await self.jobs_collection.update_one(
            {"job_id": job_id},
            {"$set": updates}
        )

    async def start_worker(self):
        """Start processing jobs (run in background)"""
        self._running = True
        while self._running:
            # Find and claim a pending job
            job = await self.jobs_collection.find_one_and_update(
                {"status": "pending"},
                {"$set": {"status": "processing", "updated_at": datetime.utcnow()}},
                sort=[("created_at", 1)]
            )

            if job:
                handler = self.workers.get(job["type"])
                if handler:
                    try:
                        await handler(job["job_id"], job["payload"], self.update_job)
                    except Exception as e:
                        await self.update_job(
                            job["job_id"],
                            status="error",
                            error=str(e)
                        )
            else:
                # No jobs, wait before checking again
                await asyncio.sleep(1)

    def stop(self):
        self._running = False
```

---

## Part 7: Testing Strategy

### Test Pyramid

```
                    ┌─────────┐
                    │   E2E   │  ← Cypress (critical flows)
                    │  Tests  │
                    └────┬────┘
                         │
                ┌────────▼────────┐
                │  Integration    │  ← pytest (API endpoints)
                │     Tests       │
                └────────┬────────┘
                         │
            ┌────────────▼────────────┐
            │       Unit Tests        │  ← pytest (services, utils)
            │                         │
            └─────────────────────────┘
```

### Key Test Cases

```python
# tests/test_fusion.py
import pytest
from backend.services.fusion.engine import FusionEngine

@pytest.fixture
def fusion_engine():
    return FusionEngine(model_name="all-MiniLM-L6-v2")

class TestFusionEngine:

    def test_deduplication_removes_similar_sentences(self, fusion_engine):
        """Verify deduplication reduces redundant content by >20%"""
        transcripts = [
            {"sentences": ["AI is transforming healthcare", "AI is revolutionizing medicine"]},
            {"sentences": ["Machine learning helps diagnose diseases", "ML aids in medical diagnosis"]}
        ]

        result = fusion_engine.fuse(transcripts, target_duration=10)

        # Should remove near-duplicates
        assert result["metadata"]["dedup_ratio"] < 0.8  # At least 20% removed

    def test_conflict_detection_finds_contradictions(self, fusion_engine):
        """Verify conflicts are detected between opposing statements"""
        transcripts = [
            {"sentences": ["Coffee consumption should increase"]},
            {"sentences": ["Coffee consumption should decrease"]}
        ]

        result = fusion_engine.fuse(transcripts, target_duration=10)

        assert len(result["conflicts"]) > 0
        assert "increase" in str(result["conflicts"]) or "decrease" in str(result["conflicts"])

    def test_duration_profile_affects_output_length(self, fusion_engine):
        """Verify 5-min summary is shorter than 20-min"""
        transcripts = [{"sentences": ["..."] * 100}]  # Long input

        short_result = fusion_engine.fuse(transcripts, target_duration=5)
        long_result = fusion_engine.fuse(transcripts, target_duration=20)

        short_words = len(short_result["fused_text"].split())
        long_words = len(long_result["fused_text"].split())

        assert short_words < long_words
        assert short_words < 1000  # ~5 min @ 150 WPM
        assert long_words > 2500   # ~20 min @ 150 WPM


# tests/e2e/summarize.cy.js
describe('Video Summarization Flow', () => {

  it('completes full summarization flow', () => {
    cy.visit('/');

    // Enter video URL
    cy.get('[data-testid="video-input"]')
      .type('https://youtube.com/watch?v=dQw4w9WgXcQ');

    // Select duration
    cy.get('[data-testid="duration-10"]').click();

    // Start summarization
    cy.get('[data-testid="summarize-btn"]').click();

    // Wait for completion (with progress checks)
    cy.get('[data-testid="progress-ring"]', { timeout: 120000 })
      .should('contain', '100%');

    // Verify result
    cy.get('[data-testid="summary-text"]')
      .should('be.visible')
      .and('have.length.greaterThan', 100);
  });

  it('handles multi-video fusion', () => {
    cy.visit('/');

    // Add multiple videos
    cy.get('[data-testid="video-input"]').eq(0).type('video1_url');
    cy.get('[data-testid="add-video-btn"]').click();
    cy.get('[data-testid="video-input"]').eq(1).type('video2_url');

    cy.get('[data-testid="summarize-btn"]').click();

    // Verify fusion metadata
    cy.get('[data-testid="metadata-topics"]')
      .should('exist');
    cy.get('[data-testid="metadata-compression"]')
      .should('contain', '%');
  });
});
```

---

## Part 8: Deployment Checklist

### Pre-Launch Security

- [ ] All secrets in `.env`, never in code
- [ ] Passwords hashed with bcrypt (cost factor 12+)
- [ ] JWT tokens with proper expiration (access: 1h, refresh: 7d)
- [ ] Rate limiting enabled (60 req/min per IP)
- [ ] CORS restricted to specific origins
- [ ] Input validation on all endpoints
- [ ] SQL/NoSQL injection prevention
- [ ] XSS protection headers

### Performance Optimization

- [ ] Transcript caching (7 day TTL)
- [ ] Audio caching by content hash
- [ ] Lazy model loading (load on first request)
- [ ] Connection pooling for MongoDB
- [ ] Gzip compression for API responses
- [ ] CDN for static assets

### Monitoring & Observability

- [ ] Health check endpoints (`/health`, `/ready`)
- [ ] Structured logging (JSON format)
- [ ] Error tracking (Sentry free tier)
- [ ] Performance metrics (response times)
- [ ] Job queue depth monitoring

### Docker Deployment

```yaml
# docker-compose.yml
version: '3.8'

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - MONGODB_URI=${MONGODB_URI}
      - SECRET_KEY=${SECRET_KEY}
      - ELEVENLABS_API_KEY=${ELEVENLABS_API_KEY}
    depends_on:
      - mongo
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - backend

  mongo:
    image: mongo:6
    volumes:
      - mongo_data:/data/db
    environment:
      - MONGO_INITDB_DATABASE=video_summarizer

  # Optional: Redis for production scaling
  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data

volumes:
  mongo_data:
  redis_data:
```

---

## Part 9: Recommended Tool Stack

### Backend (Python)

| Purpose | Tool | Why |
|---------|------|-----|
| Framework | FastAPI | Async, auto-docs, type hints |
| Database | MongoDB + Motor | Flexible schema, async driver |
| ORM/ODM | Pydantic | Validation, serialization |
| Auth | python-jose + passlib | Industry standard JWT/bcrypt |
| AI Models | transformers + sentence-transformers | HuggingFace ecosystem |
| TTS | edge-tts | Free, high quality |
| Task Queue | Built-in async | Simple; upgrade to Celery if needed |

### Frontend (React)

| Purpose | Tool | Why |
|---------|------|-----|
| Framework | React 18 | Industry standard |
| Styling | Tailwind CSS | Utility-first, fast iteration |
| Animation | Framer Motion | Declarative, performant |
| State | React Context | Simple; upgrade to Zustand if needed |
| HTTP | Axios | Interceptors, error handling |
| Forms | React Hook Form | Performance, validation |

### DevOps

| Purpose | Tool | Why |
|---------|------|-----|
| Containerization | Docker | Consistent environments |
| CI/CD | GitHub Actions | Free for public repos |
| Hosting | Railway / Render | Free tier, easy deploy |
| Monitoring | Sentry | Free tier, excellent DX |
| CDN | Cloudflare | Free tier, global |

---

## Part 10: Implementation Phases

### Phase 1: Foundation (Week 1-2)
- [ ] Finalize directory structure
- [ ] Implement abstract interfaces for swappable components
- [ ] Set up authentication with JWT
- [ ] Create core API endpoints
- [ ] Implement transcript service with caching

### Phase 2: AI Pipeline (Week 3-4)
- [ ] Implement fusion engine with sentence-transformers
- [ ] Add duration profiles and adaptive summarization
- [ ] Implement conflict detection
- [ ] Add voice generation with Edge TTS (free)
- [ ] Test multi-video fusion quality

### Phase 3: Frontend Polish (Week 5)
- [ ] Implement Recall.ai-inspired design system
- [ ] Create animated components (progress ring, cards)
- [ ] Build responsive layouts
- [ ] Add skeleton loaders and error states

### Phase 4: Testing & Launch (Week 6)
- [ ] Write unit tests for services
- [ ] Write integration tests for API
- [ ] Write E2E tests for critical flows
- [ ] Performance optimization
- [ ] Deploy to production

---

## Appendix: Quick Reference

### Environment Variables

```bash
# .env.example
MONGODB_URI=mongodb://localhost:27017/video_summarizer
SECRET_KEY=your-super-secret-key-change-in-production
ELEVENLABS_API_KEY=optional-for-premium-tts
YOUTUBE_API_KEY=optional-for-metadata
RATE_LIMIT_PER_MINUTE=60
JWT_ACCESS_EXPIRE_MINUTES=60
JWT_REFRESH_EXPIRE_DAYS=7
```

### API Quick Start

```bash
# Start backend
cd backend && uvicorn main:app --reload

# Start frontend
cd frontend && npm start

# Test transcript
curl "http://localhost:8000/api/v1/transcript?videoId=dQw4w9WgXcQ"

# Create summarization job
curl -X POST "http://localhost:8000/api/v1/summarize" \
  -H "Content-Type: application/json" \
  -d '{"video_ids": ["dQw4w9WgXcQ"], "duration_minutes": 10}'

# Check job status
curl "http://localhost:8000/api/v1/jobs/{job_id}"

# Get result
curl "http://localhost:8000/api/v1/jobs/{job_id}/result"
```

---

*Document Version: 2.0 | Last Updated: 2026-02-11*
*Designed for FYP Excellence*
