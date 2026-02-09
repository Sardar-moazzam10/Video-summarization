"""
Summarization Service - Dedicated service for text summarization.
Features:
- Disk caching of summaries in summaries/<video_id>.txt
- T5-small model for summarization
- Background task execution via ThreadPoolExecutor
- De-duplication of text before summarizing
"""

import os
import re
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Any, Optional, List
from transformers import pipeline

# === Configuration ===
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
SUMMARIES_DIR = os.path.join(BASE_DIR, "summaries")

os.makedirs(SUMMARIES_DIR, exist_ok=True)

# === Summarizer Model (Lazy Loading) ===
_summarizer = None
_summarizer_lock = threading.Lock()
_inference_lock = threading.Lock()  # Lock for inference

def get_summarizer():
    """Load T5-small summarizer model."""
    global _summarizer
    with _summarizer_lock:
        if _summarizer is None:
            print("🧠 Loading T5-small summarizer...")
            _summarizer = pipeline("summarization", model="t5-small", tokenizer="t5-small")
            print("✅ Summarizer loaded successfully")
    return _summarizer


def remove_duplicates(text: str) -> str:
    """Remove repeated sentences from text."""
    sentences = re.split(r'(?<=[.!?]) +', text)
    unique_sentences = []
    seen = set()
    for s in sentences:
        clean = s.strip().lower()
        if clean not in seen and len(clean) > 10:
            unique_sentences.append(s)
            seen.add(clean)
    return " ".join(unique_sentences)


class SummarizationService:
    """
    Service for summarizing transcripts with disk caching.
    """
    
    def __init__(self, max_workers: int = 2):
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="summarize_")
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
    
    def get_cache_path(self, video_id: str) -> str:
        """Get the path to cached summary file."""
        return os.path.join(SUMMARIES_DIR, f"{video_id}.txt")
    
    def get_json_cache_path(self, video_id: str) -> str:
        """Get the path to cached summary JSON."""
        return os.path.join(SUMMARIES_DIR, f"{video_id}.json")
    
    def is_cached(self, video_id: str) -> bool:
        """Check if summary is already cached on disk."""
        return os.path.exists(self.get_json_cache_path(video_id))
    
    def get_cached_summary(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Load summary from disk cache if available."""
        json_path = self.get_json_cache_path(video_id)
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"📦 Using cached summary for {video_id}")
                    return data
            except Exception as e:
                print(f"⚠️ Failed to load cached summary: {e}")
        return None
    
    def save_summary(self, video_id: str, summary: str, original_length: int):
        """Save summary to disk cache."""
        # Save JSON with metadata
        json_path = self.get_json_cache_path(video_id)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                "video_id": video_id,
                "summary": summary,
                "original_length": original_length,
                "summary_length": len(summary),
                "cached_at": datetime.now().isoformat()
            }, f, indent=2)
        
        # Save plain text for quick access
        txt_path = self.get_cache_path(video_id)
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(summary)
        
        print(f"💾 Cached summary for {video_id}")
    
    def summarize_text(self, text: str, max_input_tokens: int = 1024, 
                       max_summary_length: int = 150, min_summary_length: int = 40) -> str:
        """
        Summarize text using T5-small model.
        
        Args:
            text: Input text to summarize
            max_input_tokens: Maximum tokens to use from input
            max_summary_length: Maximum summary length
            min_summary_length: Minimum summary length
            
        Returns:
            Summary string
        """
        # Clean and de-duplicate
        clean_text = remove_duplicates(text)
        
        # Limit input tokens for T5
        input_tokens = clean_text.split()
        if len(input_tokens) > max_input_tokens:
            clean_text = " ".join(input_tokens[:max_input_tokens])
        
        # Add summarize prefix for T5
        input_text = "summarize: " + clean_text
        
        # Get summarizer
        summarizer = get_summarizer()
        
        # Generate summary
        with _inference_lock:
            result = summarizer(
                input_text, 
                max_length=max_summary_length, 
                min_length=min_summary_length, 
                do_sample=False
            )
        
        return result[0]['summary_text']
    
    def summarize_video(self, video_id: str, transcript_text: str, 
                        force: bool = False) -> Dict[str, Any]:
        """
        Summarize a video transcript. Uses cache if available.
        
        Args:
            video_id: YouTube video ID
            transcript_text: Full transcript text
            force: If True, bypass cache
            
        Returns:
            Dict with summary and metadata
        """
        # Check cache first (unless forced)
        if not force:
            cached = self.get_cached_summary(video_id)
            if cached:
                return cached
        
        print(f"🧠 Summarizing {video_id}...")
        
        # Generate summary
        summary = self.summarize_text(transcript_text)
        
        # Create output
        output = {
            "video_id": video_id,
            "summary": summary,
            "original_length": len(transcript_text),
            "summary_length": len(summary),
            "cached_at": datetime.now().isoformat()
        }
        
        # Cache the result
        self.save_summary(video_id, summary, len(transcript_text))
        
        print(f"✅ Summary generated for {video_id}: {summary[:80]}...")
        
        return output
    
    def summarize_multiple(self, transcripts: Dict[str, str], 
                           progress_callback=None) -> Dict[str, Dict[str, Any]]:
        """
        Summarize multiple transcripts.
        
        Args:
            transcripts: Dict mapping video_id to transcript text
            progress_callback: Optional callback(video_id, index, total, result)
            
        Returns:
            Dict mapping video_id to summary data
        """
        results = {}
        total = len(transcripts)
        
        for idx, (video_id, text) in enumerate(transcripts.items()):
            try:
                result = self.summarize_video(video_id, text)
                results[video_id] = result
                
                if progress_callback:
                    progress_callback(video_id, idx + 1, total, result)
                    
            except Exception as e:
                print(f"❌ Failed to summarize {video_id}: {e}")
                results[video_id] = {"error": str(e)}
        
        return results
    
    def summarize_unified(self, video_ids: List[str], transcripts: Dict[str, str]) -> str:
        """
        Create a unified summary from multiple video transcripts.
        
        Args:
            video_ids: List of video IDs in order
            transcripts: Dict mapping video_id to transcript text
            
        Returns:
            Unified summary string
        """
        # Combine all transcripts
        unified_text = ""
        for vid in video_ids:
            if vid in transcripts:
                unified_text += transcripts[vid] + " "
        
        unified_text = unified_text.strip()
        
        if not unified_text:
            return "No transcript content available for summarization."
        
        print(f"🧠 Creating unified summary for {len(video_ids)} videos...")
        
        # Generate summary with slightly longer output for unified content
        summary = self.summarize_text(
            unified_text, 
            max_input_tokens=1024,
            max_summary_length=200,
            min_summary_length=50
        )
        
        return summary
    
    def summarize_for_duration(self, video_ids: List[str], transcripts: Dict[str, str],
                                target_duration_seconds: int) -> Dict[str, Any]:
        """
        Summarize content to target a specific playback duration.
        
        Uses ~150 words per minute (WPM) for spoken content estimation.
        This method creates summaries sized appropriately for the target duration.
        
        Args:
            video_ids: List of video IDs in order
            transcripts: Dict mapping video_id to transcript text
            target_duration_seconds: Target duration in seconds
            
        Returns:
            Dict with summary_text, estimated_word_count, estimated_duration_seconds
        """
        # Calculate target word count (~150 words per minute for natural speech)
        WORDS_PER_MINUTE = 150
        target_words = int((target_duration_seconds / 60) * WORDS_PER_MINUTE)
        
        print(f"🎯 Summarization target: {target_duration_seconds}s → ~{target_words} words")
        
        # Combine all transcripts
        unified_text = ""
        for vid in video_ids:
            if vid in transcripts:
                unified_text += transcripts[vid] + " "
        unified_text = unified_text.strip()
        
        if not unified_text:
            return {
                "summary_text": "No transcript content available.",
                "estimated_word_count": 0,
                "estimated_duration_seconds": 0
            }
        
        # Calculate summary length based on target (T5 output is in tokens ≈ words)
        # For longer durations, we need longer summaries
        # T5-small max output is typically around 512 tokens
        max_summary_tokens = min(512, max(100, target_words // 3))  # Aim for ~1/3 of target words
        min_summary_tokens = max(30, max_summary_tokens // 3)
        
        # Generate summary with duration-appropriate length
        summary = self.summarize_text(
            unified_text,
            max_input_tokens=1024,
            max_summary_length=max_summary_tokens,
            min_summary_length=min_summary_tokens
        )
        
        # Calculate actual word count and estimated duration
        actual_words = len(summary.split())
        estimated_duration = (actual_words / WORDS_PER_MINUTE) * 60
        
        print(f"✅ Generated summary: {actual_words} words → ~{estimated_duration:.1f}s")
        
        return {
            "summary_text": summary,
            "estimated_word_count": actual_words,
            "estimated_duration_seconds": estimated_duration,
            "target_duration_seconds": target_duration_seconds,
            "target_words": target_words
        }
    
    def summarize_async(self, video_id: str, transcript_text: str) -> str:
        """
        Start async summarization job.
        Returns job_id for status tracking.
        """
        job_id = f"sum_{video_id}_{datetime.now().strftime('%H%M%S')}"
        
        with self._lock:
            self.jobs[job_id] = {
                "video_id": video_id,
                "status": "pending",
                "result": None,
                "error": None,
                "created_at": datetime.now().isoformat()
            }
        
        def _run():
            try:
                with self._lock:
                    self.jobs[job_id]["status"] = "processing"
                
                result = self.summarize_video(video_id, transcript_text)
                
                with self._lock:
                    self.jobs[job_id]["status"] = "completed"
                    self.jobs[job_id]["result"] = result
                    
            except Exception as e:
                with self._lock:
                    self.jobs[job_id]["status"] = "error"
                    self.jobs[job_id]["error"] = str(e)
        
        self.executor.submit(_run)
        return job_id
    
    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status of async summarization job."""
        with self._lock:
            return self.jobs.get(job_id)


# Singleton instance
_summarization_service = None

def get_summarization_service() -> SummarizationService:
    """Get singleton SummarizationService instance."""
    global _summarization_service
    if _summarization_service is None:
        _summarization_service = SummarizationService()
    return _summarization_service


# === Flask API (optional, for standalone use) ===
if __name__ == "__main__":
    from flask import Flask, request, jsonify
    from flask_cors import CORS
    
    app = Flask(__name__)
    CORS(app)
    
    service = get_summarization_service()
    
    @app.route('/summarize', methods=['POST'])
    def summarize_endpoint():
        """POST /summarize - Summarize transcript text."""
        data = request.get_json()
        
        video_id = data.get("video_id", "unknown")
        transcript = data.get("transcript", "")
        
        if not transcript:
            return jsonify({"error": "Transcript is required"}), 400
        
        try:
            result = service.summarize_video(video_id, transcript)
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    @app.route('/summarize/<video_id>', methods=['GET'])
    def get_summary(video_id):
        """GET /summarize/<video_id> - Get cached summary."""
        if service.is_cached(video_id):
            cached = service.get_cached_summary(video_id)
            return jsonify(cached)
        return jsonify({"error": "Summary not cached"}), 404
    
    @app.route('/summarize/cached', methods=['GET'])
    def list_cached():
        """GET /summarize/cached - List all cached summaries."""
        cached = []
        for fname in os.listdir(SUMMARIES_DIR):
            if fname.endswith('.json'):
                video_id = fname.replace('.json', '')
                cached.append(video_id)
        return jsonify({"cached_summaries": cached})
    
    print("✅ Summarization service running at http://localhost:5004")
    app.run(port=5004, debug=True)
