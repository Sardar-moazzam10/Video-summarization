import re

# 1. Transcript Service
with open('backend/services/transcript_service.py', 'r') as f:
    ts = f.read()

# Fix the import
ts = ts.replace(
"""Also handles:
  - Video ID extraction from URLs
  - MongoDB caching
from .acquisition_service import append_event
  - Multi-language support with English translation
  - Retry logic for transient failures
\"\"\"""",
"""Also handles:
  - Video ID extraction from URLs
  - MongoDB caching
  - Multi-language support with English translation
  - Retry logic for transient failures
\"\"\"
from .acquisition_service import append_event""")

# Instrument Cache hits and misses
ts = ts.replace(
'''        cached = await self.transcripts.find_one({"video_id": video_id})
        if cached:
            if self._transcript_is_sane(cached.get("transcript")):
                return {
                    "transcript": cached["transcript"],
                    "source": cached.get("source", "cache"),
                    "cached": True,
                }
            cached_transcript = cached.get("transcript")
            if self._transcript_is_sane(cached_transcript):
                # For fast_search, only reuse cached transcript if it is English
                if not fast_search or self._detect_transcript_language(cached_transcript) == "en":
                    return {
                        "transcript": cached_transcript,
                        "source": cached.get("source", "cache"),
                        "cached": True,
                    }''',
'''        await append_event(
            source_id=video_id,
            operation="metadata_read",
            phase="attempted",
            method="transcript_cache",
            outcome_code="started",
        )
        cached = await self.transcripts.find_one({"video_id": video_id})
        if cached:
            if self._transcript_is_sane(cached.get("transcript")):
                await append_event(
                    source_id=video_id,
                    operation="metadata_read",
                    phase="succeeded",
                    method="transcript_cache",
                    outcome_code="success",
                    cache_result="hit",
                )
                return {
                    "transcript": cached["transcript"],
                    "source": cached.get("source", "cache"),
                    "cached": True,
                }
            cached_transcript = cached.get("transcript")
            if self._transcript_is_sane(cached_transcript):
                if not fast_search or self._detect_transcript_language(cached_transcript) == "en":
                    await append_event(
                        source_id=video_id,
                        operation="metadata_read",
                        phase="succeeded",
                        method="transcript_cache",
                        outcome_code="success",
                        cache_result="hit",
                    )
                    return {
                        "transcript": cached_transcript,
                        "source": cached.get("source", "cache"),
                        "cached": True,
                    }
        await append_event(
            source_id=video_id,
            operation="metadata_read",
            phase="succeeded",
            method="transcript_cache",
            outcome_code="not_found",
            cache_result="miss",
        )''')

with open('backend/services/transcript_service.py', 'w') as f:
    f.write(ts)


# 2. Rights Service
with open('backend/services/rights_service.py', 'r') as f:
    rs = f.read()

if "from .acquisition_service import append_event" not in rs:
    rs = rs.replace("from typing import Dict, List, Optional, Tuple", "from typing import Dict, List, Optional, Tuple\\nfrom .acquisition_service import append_event")

rs = rs.replace(
'''        if api_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={
                            "part": "status,snippet",
                            "id": ",".join(missing_ids),
                            "key": api_key,
                        },
                    )''',
'''        if api_key:
            try:
                for mid in missing_ids:
                    await append_event(
                        source_id=mid,
                        operation="metadata_read",
                        phase="attempted",
                        method="youtube_api_videos_list",
                        outcome_code="started"
                    )
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://www.googleapis.com/youtube/v3/videos",
                        params={
                            "part": "status,snippet",
                            "id": ",".join(missing_ids),
                            "key": api_key,
                        },
                    )
                for mid in missing_ids:
                    await append_event(
                        source_id=mid,
                        operation="metadata_read",
                        phase="succeeded" if not resp.is_error else "failed",
                        method="youtube_api_videos_list",
                        outcome_code="success" if not resp.is_error else "error"
                    )''')

with open('backend/services/rights_service.py', 'w') as f:
    f.write(rs)

