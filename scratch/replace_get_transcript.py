import re

with open('backend/services/transcript_service.py', 'r') as f:
    lines = f.readlines()

start_idx = -1
end_idx = -1
for i, line in enumerate(lines):
    if "def get_transcript(" in line:
        start_idx = i
    if "return transcript" in line and start_idx != -1 and i > start_idx + 200:
        end_idx = i
        break

# Actually it's easier to use sed or string match if I know the exact bounds.
