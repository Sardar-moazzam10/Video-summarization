"""
Quick test script to verify YouTube download fix
"""
import subprocess
import os
import tempfile
import shutil

# Test video ID (short video)
TEST_VIDEO_ID = "jNQXAC9IVRw"  # "Me at the zoo" - first YouTube video (18 seconds)

def test_download():
    # Use venv's yt-dlp
    ytdlp_bin = os.path.join(".venv", "Scripts", "yt-dlp.exe")

    # Create temp directory
    work_dir = tempfile.mkdtemp(prefix="test_download_")
    output_path = os.path.join(work_dir, f"{TEST_VIDEO_ID}_test.mp3")

    try:
        print(f"Testing YouTube download with video ID: {TEST_VIDEO_ID}")
        print(f"Output directory: {work_dir}")

        cmd = [
            ytdlp_bin,
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
            "--extractor-args", "youtube:player_client=web,mweb",
            "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "-x", "--audio-format", "mp3",
            "-o", output_path,
            f"https://www.youtube.com/watch?v={TEST_VIDEO_ID}",
        ]

        print("Running yt-dlp...")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0 and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            print(f"SUCCESS! Downloaded {file_size:,} bytes")
            print(f"File: {output_path}")
            return True
        else:
            print("FAILED!")
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            return False

    finally:
        # Cleanup
        if os.path.exists(work_dir):
            shutil.rmtree(work_dir, ignore_errors=True)
            print(f"Cleaned up test directory")

if __name__ == "__main__":
    success = test_download()
    exit(0 if success else 1)
