with open('backend/services/transcript_service.py', 'r') as f:
    content = f.read()

import re

# We will just replace the messed up block.
bad_block = """        await append_event(
            source_id=video_id,
            operation="metadata_read",
            phase="succeeded",
            method="transcript_cache",
            outcome_code="not_found",
            cache_result="miss",
        )
                else:"""

good_block = """                else:
                    print(f"[Transcript] Fast search: cached transcript for {video_id} is non-English — skipping")
                    return None
            print(f"[Transcript] Cached transcript for {video_id} failed the sanity "
                  f"check — refetching instead of reusing it")
        
        await append_event(
            source_id=video_id,
            operation="metadata_read",
            phase="succeeded",
            method="transcript_cache",
            outcome_code="not_found",
            cache_result="miss",
        )"""

content = content.replace(bad_block, good_block)

with open('backend/services/transcript_service.py', 'w') as f:
    f.write(content)
