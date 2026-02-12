"""
Voice Service - 100% FREE Text-to-Speech using Microsoft Edge TTS

Edge TTS is completely free with no API limits, high quality voices,
and supports multiple languages and styles.

Available voices: https://github.com/rany2/edge-tts
"""

import edge_tts
import asyncio
import hashlib
import os
from typing import Optional
from pathlib import Path


# Available FREE voices (all high quality)
AVAILABLE_VOICES = {
    # English - US
    "aria": {"id": "en-US-AriaNeural", "name": "Aria", "gender": "Female", "style": "professional"},
    "guy": {"id": "en-US-GuyNeural", "name": "Guy", "gender": "Male", "style": "friendly"},
    "jenny": {"id": "en-US-JennyNeural", "name": "Jenny", "gender": "Female", "style": "conversational"},
    "davis": {"id": "en-US-DavisNeural", "name": "Davis", "gender": "Male", "style": "calm"},
    "amber": {"id": "en-US-AmberNeural", "name": "Amber", "gender": "Female", "style": "warm"},
    "andrew": {"id": "en-US-AndrewNeural", "name": "Andrew", "gender": "Male", "style": "confident"},
    "ashley": {"id": "en-US-AshleyNeural", "name": "Ashley", "gender": "Female", "style": "cheerful"},
    "brandon": {"id": "en-US-BrandonNeural", "name": "Brandon", "gender": "Male", "style": "casual"},
    "christopher": {"id": "en-US-ChristopherNeural", "name": "Christopher", "gender": "Male", "style": "reliable"},
    "cora": {"id": "en-US-CoraNeural", "name": "Cora", "gender": "Female", "style": "positive"},
    "elizabeth": {"id": "en-US-ElizabethNeural", "name": "Elizabeth", "gender": "Female", "style": "pleasant"},
    "eric": {"id": "en-US-EricNeural", "name": "Eric", "gender": "Male", "style": "rational"},
    "jacob": {"id": "en-US-JacobNeural", "name": "Jacob", "gender": "Male", "style": "empathetic"},
    "jane": {"id": "en-US-JaneNeural", "name": "Jane", "gender": "Female", "style": "hopeful"},
    "jason": {"id": "en-US-JasonNeural", "name": "Jason", "gender": "Male", "style": "lyrical"},
    "michelle": {"id": "en-US-MichelleNeural", "name": "Michelle", "gender": "Female", "style": "friendly"},
    "monica": {"id": "en-US-MonicaNeural", "name": "Monica", "gender": "Female", "style": "friendly"},
    "nancy": {"id": "en-US-NancyNeural", "name": "Nancy", "gender": "Female", "style": "friendly"},
    "roger": {"id": "en-US-RogerNeural", "name": "Roger", "gender": "Male", "style": "lively"},
    "sara": {"id": "en-US-SaraNeural", "name": "Sara", "gender": "Female", "style": "cheerful"},
    "steffan": {"id": "en-US-SteffanNeural", "name": "Steffan", "gender": "Male", "style": "cheerful"},
    "tony": {"id": "en-US-TonyNeural", "name": "Tony", "gender": "Male", "style": "cheerful"},

    # English - UK
    "sonia": {"id": "en-GB-SoniaNeural", "name": "Sonia (British)", "gender": "Female", "style": "professional"},
    "ryan": {"id": "en-GB-RyanNeural", "name": "Ryan (British)", "gender": "Male", "style": "professional"},

    # English - Australia
    "natasha": {"id": "en-AU-NatashaNeural", "name": "Natasha (Australian)", "gender": "Female", "style": "professional"},
    "william": {"id": "en-AU-WilliamNeural", "name": "William (Australian)", "gender": "Male", "style": "professional"},

    # English - India
    "neerja": {"id": "en-IN-NeerjaNeural", "name": "Neerja (Indian)", "gender": "Female", "style": "professional"},
    "prabhat": {"id": "en-IN-PrabhatNeural", "name": "Prabhat (Indian)", "gender": "Male", "style": "professional"},
}

# Default voice for narration
DEFAULT_VOICE = "aria"


class VoiceService:
    """
    FREE Text-to-Speech service using Microsoft Edge TTS

    Features:
    - 100% FREE (no API keys, no limits)
    - High quality neural voices
    - Multiple languages and accents
    - Audio caching for efficiency
    - SSML support for advanced control
    """

    def __init__(self, cache_dir: str = "audio_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

    def get_available_voices(self) -> list:
        """Get list of available voices"""
        return [
            {
                "key": key,
                "id": voice["id"],
                "name": voice["name"],
                "gender": voice["gender"],
                "style": voice["style"]
            }
            for key, voice in AVAILABLE_VOICES.items()
        ]

    def _get_cache_path(self, text: str, voice_key: str) -> Path:
        """Generate cache file path based on content hash"""
        content_hash = hashlib.md5(f"{text}:{voice_key}".encode()).hexdigest()
        return self.cache_dir / f"{content_hash}.mp3"

    async def generate_audio(
        self,
        text: str,
        voice_key: str = DEFAULT_VOICE,
        rate: str = "+0%",
        pitch: str = "+0Hz",
        volume: str = "+0%"
    ) -> bytes:
        """
        Generate speech audio from text using Edge TTS

        Args:
            text: Text to convert to speech
            voice_key: Voice identifier (e.g., "aria", "guy", "sonia")
            rate: Speech rate adjustment (e.g., "+10%", "-5%")
            pitch: Pitch adjustment (e.g., "+5Hz", "-10Hz")
            volume: Volume adjustment (e.g., "+10%", "-5%")

        Returns:
            Audio bytes (MP3 format)
        """
        # Check cache first
        cache_path = self._get_cache_path(text, voice_key)
        if cache_path.exists():
            print(f"[CACHE] Using cached audio for voice={voice_key}")
            return cache_path.read_bytes()

        # Get voice ID
        voice_info = AVAILABLE_VOICES.get(voice_key, AVAILABLE_VOICES[DEFAULT_VOICE])
        voice_id = voice_info["id"]

        print(f"[TTS] Generating audio with voice={voice_id} ({len(text)} chars)")

        # Generate audio using Edge TTS
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice_id,
            rate=rate,
            pitch=pitch,
            volume=volume
        )

        # Collect audio chunks
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        audio_bytes = b''.join(audio_chunks)

        # Cache the result
        cache_path.write_bytes(audio_bytes)
        print(f"[TTS] Generated and cached {len(audio_bytes)} bytes")

        return audio_bytes

    async def generate_audio_file(
        self,
        text: str,
        output_path: str,
        voice_key: str = DEFAULT_VOICE,
        **kwargs
    ) -> str:
        """
        Generate audio and save directly to file

        Args:
            text: Text to convert
            output_path: Where to save the MP3 file
            voice_key: Voice to use
            **kwargs: Additional parameters (rate, pitch, volume)

        Returns:
            Path to saved audio file
        """
        audio_bytes = await self.generate_audio(text, voice_key, **kwargs)
        Path(output_path).write_bytes(audio_bytes)
        return output_path

    async def generate_with_ssml(
        self,
        ssml_text: str,
        voice_key: str = DEFAULT_VOICE
    ) -> bytes:
        """
        Generate audio from SSML for advanced control

        SSML allows:
        - Pauses: <break time="500ms"/>
        - Emphasis: <emphasis level="strong">word</emphasis>
        - Prosody: <prosody rate="slow" pitch="+2st">text</prosody>
        """
        voice_info = AVAILABLE_VOICES.get(voice_key, AVAILABLE_VOICES[DEFAULT_VOICE])
        voice_id = voice_info["id"]

        communicate = edge_tts.Communicate(ssml_text, voice_id)

        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        return b''.join(audio_chunks)

    async def generate_audio_with_subtitles(
        self,
        text: str,
        audio_path: str,
        subtitle_path: str,
        voice_key: str = DEFAULT_VOICE,
        **kwargs
    ) -> tuple:
        """
        Generate audio + SRT subtitles using Edge TTS SubMaker.

        Args:
            text: Text to convert
            audio_path: Where to save the MP3 file
            subtitle_path: Where to save the SRT file
            voice_key: Voice to use

        Returns:
            Tuple of (audio_path, subtitle_path)
        """
        voice_info = AVAILABLE_VOICES.get(voice_key, AVAILABLE_VOICES[DEFAULT_VOICE])
        voice_id = voice_info["id"]

        print(f"[TTS] Generating audio+subtitles with voice={voice_id}")

        communicate = edge_tts.Communicate(text=text, voice=voice_id, **kwargs)
        submaker = edge_tts.SubMaker()

        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                submaker.feed(chunk)

        # Write audio
        audio_bytes = b''.join(audio_chunks)
        Path(audio_path).write_bytes(audio_bytes)

        # Write SRT subtitles
        srt_content = submaker.get_srt()
        Path(subtitle_path).write_text(srt_content, encoding="utf-8")

        print(f"[TTS] Audio: {len(audio_bytes)} bytes, Subtitles: {subtitle_path}")
        return audio_path, subtitle_path

    def format_for_narration(self, text: str) -> str:
        """
        Format text for better narration quality

        - Add pauses between paragraphs
        - Clean up special characters
        - Improve pronunciation hints
        """
        # Split into paragraphs
        paragraphs = text.split('\n\n')

        # Add slight pauses between sections
        formatted_parts = []
        for i, para in enumerate(paragraphs):
            # Clean up the paragraph
            para = para.strip()
            if not para:
                continue

            # Add transition phrases if this isn't the first paragraph
            if i > 0 and not para.startswith(('Additionally', 'Furthermore', 'Moreover', 'However', 'In contrast')):
                # Small pause indicator (Edge TTS handles natural pauses)
                para = f"... {para}"

            formatted_parts.append(para)

        return '\n\n'.join(formatted_parts)

    def clear_cache(self) -> int:
        """Clear all cached audio files"""
        count = 0
        for file in self.cache_dir.glob("*.mp3"):
            file.unlink()
            count += 1
        return count

    def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        files = list(self.cache_dir.glob("*.mp3"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "files": len(files),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "cache_dir": str(self.cache_dir)
        }


# Singleton instance
_voice_service: Optional[VoiceService] = None


def get_voice_service() -> VoiceService:
    """Get or create voice service instance"""
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceService()
    return _voice_service


# Quick test function
async def test_voice():
    """Test the voice service"""
    service = get_voice_service()

    print("Available voices:", len(service.get_available_voices()))

    test_text = "Hello! This is a test of the free Microsoft Edge text to speech service. It sounds natural and is completely free to use."

    audio = await service.generate_audio(test_text, voice_key="aria")
    print(f"Generated {len(audio)} bytes of audio")

    return audio


if __name__ == "__main__":
    asyncio.run(test_voice())
