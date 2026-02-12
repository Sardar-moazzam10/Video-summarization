"""
Voice API Routes - FREE Text-to-Speech using Microsoft Edge TTS

All voice features are 100% FREE:
- No API keys required
- No usage limits
- High quality neural voices
- Multiple languages and accents

Available voices: 20+ English voices (US, UK, AU, IN)
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import io

from ..services.voice_service import get_voice_service, AVAILABLE_VOICES

router = APIRouter(prefix="/api/v1/voice", tags=["voice"])


class TextToSpeechRequest(BaseModel):
    """Request body for TTS generation"""
    text: str
    voice: Optional[str] = "aria"  # Default to Aria (professional female)
    rate: Optional[str] = "+0%"    # Speech rate: -50% to +100%
    pitch: Optional[str] = "+0Hz"  # Pitch adjustment


class VoiceInfo(BaseModel):
    """Voice information for display"""
    key: str
    id: str
    name: str
    gender: str
    style: str


# =====================================================
# ENDPOINTS
# =====================================================

@router.get("/voices")
async def list_voices():
    """
    Get list of all available FREE voices.

    Returns:
        List of voice options with name, gender, and style info.
    """
    service = get_voice_service()
    voices = service.get_available_voices()

    return {
        "total": len(voices),
        "cost": "FREE",
        "provider": "Microsoft Edge TTS",
        "voices": voices,
        "recommended": [
            {"key": "aria", "description": "Professional female voice (default)"},
            {"key": "guy", "description": "Friendly male voice"},
            {"key": "jenny", "description": "Conversational female voice"},
            {"key": "sonia", "description": "British professional female"},
        ]
    }


@router.post("/generate")
async def generate_speech(request: TextToSpeechRequest):
    """
    Generate speech audio from text.

    This endpoint is 100% FREE - no API keys or limits.

    Args:
        text: Text to convert to speech
        voice: Voice key (default: aria)
        rate: Speech rate adjustment (e.g., "+10%", "-5%")
        pitch: Pitch adjustment (e.g., "+5Hz", "-10Hz")

    Returns:
        Audio stream (MP3 format)
    """
    if not request.text or len(request.text.strip()) == 0:
        raise HTTPException(400, "Text is required")

    if len(request.text) > 50000:
        raise HTTPException(400, "Text too long. Maximum 50,000 characters.")

    # Validate voice
    if request.voice not in AVAILABLE_VOICES:
        raise HTTPException(
            400,
            f"Unknown voice '{request.voice}'. Use /voices endpoint to see available options."
        )

    try:
        service = get_voice_service()

        audio_bytes = await service.generate_audio(
            text=request.text,
            voice_key=request.voice,
            rate=request.rate,
            pitch=request.pitch
        )

        # Return as streaming response
        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "attachment; filename=speech.mp3",
                "X-Voice-Provider": "Edge-TTS-FREE",
                "X-Voice-Used": request.voice,
            }
        )

    except Exception as e:
        raise HTTPException(500, f"Voice generation failed: {str(e)}")


@router.get("/preview/{voice_key}")
async def preview_voice(voice_key: str):
    """
    Preview a voice with sample text.

    Args:
        voice_key: Voice identifier (e.g., "aria", "guy")

    Returns:
        Audio stream with sample narration
    """
    if voice_key not in AVAILABLE_VOICES:
        raise HTTPException(404, f"Voice '{voice_key}' not found")

    voice_info = AVAILABLE_VOICES[voice_key]
    sample_text = f"Hello! I'm {voice_info['name']}. I can help narrate your video summaries with a {voice_info['style']} tone. This is completely free to use!"

    try:
        service = get_voice_service()
        audio_bytes = await service.generate_audio(
            text=sample_text,
            voice_key=voice_key
        )

        return StreamingResponse(
            io.BytesIO(audio_bytes),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f"attachment; filename=preview_{voice_key}.mp3"
            }
        )

    except Exception as e:
        raise HTTPException(500, f"Preview generation failed: {str(e)}")


@router.get("/cache/stats")
async def get_cache_stats():
    """
    Get voice cache statistics.

    Shows how much audio has been cached to avoid regeneration.
    """
    service = get_voice_service()
    return {
        "provider": "Edge TTS (FREE)",
        "cache": service.get_cache_stats()
    }


@router.delete("/cache")
async def clear_cache():
    """
    Clear the audio cache.

    Use this if you want to regenerate all audio fresh.
    """
    service = get_voice_service()
    count = service.clear_cache()
    return {
        "message": f"Cleared {count} cached audio files",
        "provider": "Edge TTS (FREE)"
    }
