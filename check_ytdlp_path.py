"""
Check which yt-dlp binary is being used
"""
import sys
import os

# Show Python info
print(f"Python executable: {sys.executable}")
print(f"Python prefix: {sys.prefix}")
print(f"In venv: {hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)}")

# Import and check
from transcription_service import YTDLP_BIN
print(f"\nyt-dlp binary that will be used: {YTDLP_BIN}")
print(f"File exists: {os.path.exists(YTDLP_BIN)}")

# Check version
import subprocess
try:
    result = subprocess.run([YTDLP_BIN, "--version"], capture_output=True, text=True)
    print(f"yt-dlp version: {result.stdout.strip()}")
except Exception as e:
    print(f"Error checking version: {e}")
