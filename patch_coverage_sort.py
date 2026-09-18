import re
with open('backend/services/coverage_selector.py', 'r') as f:
    content = f.read()

content = content.replace(
    'chosen.sort(key=lambda s: (getattr(s, "video_id", ""), s.start_time))',
    """try:
        from .narrative_sorter import sort_segments
        chosen = sort_segments(chosen, embedder)
        result.segments = chosen
    except Exception as e:
        print(f"[Selector] Narrative sort failed: {e}, falling back")
        chosen.sort(key=lambda s: (getattr(s, "video_id", ""), s.start_time))"""
)

with open('backend/services/coverage_selector.py', 'w') as f:
    f.write(content)
