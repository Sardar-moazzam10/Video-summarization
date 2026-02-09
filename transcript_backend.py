from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, NoTranscriptFound,
    VideoUnavailable, CouldNotRetrieveTranscript
)
from transformers import pipeline
import re
import traceback
import subprocess
import json
import time
import torch
import requests
import xml.etree.ElementTree as ET
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from pymongo import MongoClient
from datetime import datetime
import whisper
import os

# === Configuration ===
device = "cpu"
COOKIE_FILE_PATH = os.path.abspath("cookies.txt")
summarizer = pipeline("summarization", model="t5-small", tokenizer="t5-small")

app = Flask(__name__)
CORS(app)

# === MongoDB ===
client = MongoClient("mongodb+srv://hamzaarif725725:hamzapodcastly@podcastlycluster.hyrqok6.mongodb.net/")
db = client['user-auth']
transcripts_collection = db['transcripts']

# === Fallback 1: yt-dlp with cookies ===
def fetch_transcript_ytdlp(video_id):
    try:
        print("🚨 Falling back to yt-dlp auto-sub with cookies...")
        url = f"https://www.youtube.com/watch?v={video_id}"
        cmd = [
            "yt-dlp",
            "--write-auto-sub", "--skip-download",
            "--cookies", COOKIE_FILE_PATH,
            "--sub-lang", "en", "--sub-format", "json3",
            "--no-warnings", "--quiet", "--print", "subtitle-json",
            url
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
        if result.returncode != 0:
            raise RuntimeError("yt-dlp failed.")
        data = json.loads(result.stdout)
        transcript = []
        for event in data.get("events", []):
            if "segs" in event:
                text = "".join(seg.get("utf8", "") for seg in event["segs"])
                start = float(event.get("tStartMs", 0)) / 1000
                duration = float(event.get("dDurationMs", 0)) / 1000
                transcript.append({"text": text, "start": start, "duration": duration})
        return transcript
    except Exception as e:
        print(f"❌ yt-dlp error: {e}")
        return None

# === Fallback 2: Selenium ===
def fetch_transcript_selenium(video_id):
    try:
        print("🧪 Falling back to Selenium...")
        url = f"https://www.youtube.com/watch?v={video_id}"
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--log-level=3")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(url)
        time.sleep(5)
        page_source = driver.page_source
        driver.quit()
        match = re.search(r'ytInitialPlayerResponse\s*=\s*({.*?});', page_source)
        if not match:
            raise Exception("ytInitialPlayerResponse not found")
        player_response = json.loads(match.group(1))
        caption_url = player_response['captions']['playerCaptionsTracklistRenderer']['captionTracks'][0]['baseUrl']
        response = requests.get(caption_url)
        root = ET.fromstring(response.text)
        transcript = []
        for text in root.findall('text'):
            start = float(text.attrib['start'])
            duration = float(text.attrib.get('dur', 0))
            content = text.text or ''
            transcript.append({
                "text": content.replace('\n', ' '),
                "start": start,
                "duration": duration
            })
        return transcript
    except Exception as e:
        print(f"❌ Selenium error: {e}")
        return None

# === Fallback 3: Whisper AI ===
def fetch_transcript_whisper(video_id):
    try:
        print("🎤 Falling back to Whisper transcription...")
        url = f"https://www.youtube.com/watch?v={video_id}"
        output_filename = f"{video_id}.mp3"
        cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "-o", output_filename, url]
        subprocess.run(cmd, check=True)
        model = whisper.load_model("base")
        result = model.transcribe(output_filename)
        transcript = []
        for segment in result["segments"]:
            transcript.append({
                "text": segment["text"],
                "start": segment["start"],
                "duration": segment["end"] - segment["start"]
            })
        os.remove(output_filename)
        return transcript
    except Exception as e:
        print(f"❌ Whisper error: {e}")
        return None

# === Main Transcript Fetcher ===
@app.route('/transcript', methods=['GET'])
def get_transcript():
    video_id = request.args.get('videoId')
    if not video_id:
        return jsonify({"error": "Video ID is required"}), 400
    print(f"📺 Requesting transcript for video ID: {video_id}")

    # 1. MongoDB cache
    cached = transcripts_collection.find_one({"video_id": video_id}, {"_id": 0})
    if cached:
        print("📦 Transcript found in MongoDB.")
        return jsonify(cached["transcript"]), 200

    # 2. Try YouTubeTranscriptApi
    for attempt in range(3):
        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id)
            formatted = [{"text": t["text"], "start": t["start"], "duration": t["duration"]} for t in transcript]
            transcripts_collection.insert_one({
                "video_id": video_id,
                "transcript": formatted,
                "fetched_at": datetime.utcnow(),
                "source": "youtube_api"
            })
            print("✅ Saved transcript from YouTubeTranscriptApi to MongoDB.")
            return jsonify(formatted), 200
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, CouldNotRetrieveTranscript) as e:
            print(f"⚠️ API attempt {attempt+1} failed: {e}")
            time.sleep(1 + attempt)
        except Exception as e:
            print(f"🔥 Unexpected error: {e}")
            traceback.print_exc()
            time.sleep(1)

    # 3. Fallbacks
    for method, label in [
        (fetch_transcript_ytdlp, "yt_dlp"),
        (fetch_transcript_selenium, "selenium"),
        (fetch_transcript_whisper, "whisper")
    ]:
        transcript = method(video_id)
        if transcript:
            transcripts_collection.insert_one({
                "video_id": video_id,
                "transcript": transcript,
                "fetched_at": datetime.utcnow(),
                "source": label
            })
            print(f"✅ Saved {label} transcript to MongoDB.")
            return jsonify(transcript), 200

    return jsonify({"error": "Transcript not available via any method."}), 403

# === Segment Transcript ===
@app.route('/segment-transcript', methods=['POST'])
def segment_transcript():
    data = request.get_json()
    video_id = data.get("videoId")
    start_time = data.get("start")
    end_time = data.get("end")
    if not video_id or start_time is None or end_time is None:
        return jsonify({"error": "Missing videoId, start or end time"}), 400
    print(f"🔍 Segment for {video_id} from {start_time}s to {end_time}s")
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        segment_texts = [entry["text"] for entry in transcript if start_time <= entry["start"] <= end_time]
        return jsonify({"segmentTranscript": " ".join(segment_texts)}), 200
    except Exception as e:
        print(f"🔥 Segment error: {e}")
        return jsonify({"error": f"Failed to retrieve segment: {e}"}), 500

# === Summarize Transcript ===
@app.route('/summarize', methods=['POST'])
def summarize_transcript():
    data = request.get_json()
    transcript_text = data.get("transcript", "")
    if not transcript_text:
        return jsonify({"error": "Transcript is required."}), 400
    try:
        print("🧠 Summarizing...")
        max_length = 400
        input_text = re.sub(r'\s+', ' ', transcript_text.strip().replace('\n', ' '))
        if len(input_text.split()) > max_length:
            input_text = ' '.join(input_text.split()[:max_length])
        input_text = "summarize: " + input_text
        summary = summarizer(input_text, max_length=80, min_length=30, do_sample=False)[0]['summary_text']
        print("✅ Summarized.")
        return jsonify({"summary": summary})
    except Exception as e:
        print(f"🔥 Summarization error: {e}")
        return jsonify({"error": f"Failed to summarize: {e}"}), 500

# === Start Flask Server ===
if __name__ == '__main__':
    print("✅ Transcript backend running at http://localhost:5001")
    app.run(port=5001, debug=True)
