"""
End-to-End Test — AI Video Summarization Project
Tests the full flow: Health → Auth → Transcript → Summarize → Merge Job → Result

Usage:
    python test_full_flow.py

Uses video qoyrFXKBAdM (short, already cached) to keep test fast.
"""

import requests
import time
import sys
import uuid
import json

BASE = "http://localhost:8000"
TEST_VIDEO = "qoyrFXKBAdM"   # short cached video ~66MB
TEST_VIDEO_2 = "cP9JZ85m2Ao"  # second short cached video ~62MB

# ─── Colour helpers ────────────────────────────────────────────────────────────
GRN  = "\033[92m"
RED  = "\033[91m"
YLW  = "\033[93m"
BLU  = "\033[94m"
RST  = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0

def ok(msg):
    global passed
    passed += 1
    print(f"  {GRN}✓{RST}  {msg}")

def fail(msg, detail=""):
    global failed
    failed += 1
    print(f"  {RED}✗{RST}  {msg}")
    if detail:
        print(f"       {RED}{detail}{RST}")

def section(title):
    print(f"\n{BOLD}{BLU}{'─'*55}{RST}")
    print(f"{BOLD}{BLU}  {title}{RST}")
    print(f"{BOLD}{BLU}{'─'*55}{RST}")

def warn(msg):
    print(f"  {YLW}⚠{RST}  {msg}")


# ─── 1. HEALTH CHECK ───────────────────────────────────────────────────────────
section("1 · Health Check")
try:
    r = requests.get(f"{BASE}/", timeout=8)
    assert r.status_code == 200, f"HTTP {r.status_code}"
    data = r.json()
    ok(f"Backend alive — {data.get('name')} v{data.get('version')}")
except Exception as e:
    fail("Backend not reachable", str(e))
    print(f"\n{RED}Cannot continue — start the backend first:{RST}")
    print("  source venv/bin/activate && uvicorn backend.main:app --reload --port 8000")
    sys.exit(1)

try:
    r = requests.get(f"{BASE}/health", timeout=8)
    assert r.status_code == 200
    ok("Health endpoint OK")
except Exception as e:
    fail("/health endpoint", str(e))


# ─── 2. AUTH — SIGNUP ──────────────────────────────────────────────────────────
section("2 · Auth — Signup")
uid = uuid.uuid4().hex[:8]
TEST_USER = {
    "firstName": "Test",
    "lastName": "User",
    "email": f"testuser_{uid}@test.com",
    "username": f"testuser_{uid}",
    "password": "TestPass123",
    "role": "user"
}

try:
    r = requests.post(f"{BASE}/api/v1/auth/signup", json=TEST_USER, timeout=10)
    if r.status_code in (200, 201):
        ok(f"Signup OK — user: {TEST_USER['username']}")
    elif r.status_code == 409:
        warn("User already exists (re-run — using existing user)")
    else:
        fail(f"Signup failed HTTP {r.status_code}", r.text[:200])
except Exception as e:
    fail("Signup request failed", str(e))


# ─── 3. AUTH — LOGIN ───────────────────────────────────────────────────────────
section("3 · Auth — Login")
TOKEN = None
try:
    r = requests.post(f"{BASE}/api/v1/auth/login", json={
        "login": TEST_USER["username"],
        "password": TEST_USER["password"]
    }, timeout=10)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    data = r.json()
    TOKEN = data.get("access_token")
    assert TOKEN, "No access_token in response"
    ok(f"Login OK — JWT received ({len(TOKEN)} chars)")
except Exception as e:
    fail("Login failed", str(e))
    TOKEN = None

AUTH = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


# ─── 4. AUTH — GET PROFILE ─────────────────────────────────────────────────────
section("4 · Auth — Get User Profile")
try:
    r = requests.get(f"{BASE}/api/v1/auth/user/{TEST_USER['username']}", headers=AUTH, timeout=8)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:150]}"
    profile = r.json()
    ok(f"Profile: {profile.get('firstName')} {profile.get('lastName')} / role={profile.get('role')}")
except Exception as e:
    fail("Get profile failed", str(e))


# ─── 5. TRANSCRIPT FETCH ───────────────────────────────────────────────────────
section("5 · Transcript Fetch")
TRANSCRIPT_TEXT = None
try:
    r = requests.get(f"{BASE}/api/v1/transcript/", params={"videoId": TEST_VIDEO}, headers=AUTH, timeout=30)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    data = r.json()
    segments = data.get("transcript", [])
    TRANSCRIPT_TEXT = " ".join(s.get("text","") for s in segments)
    word_count = len(TRANSCRIPT_TEXT.split())
    source = data.get("source", "unknown")
    ok(f"Transcript fetched — {len(segments)} segments, {word_count} words (source: {source})")
except Exception as e:
    fail("Transcript fetch failed", str(e))


# ─── 6. SUMMARIZE TEXT ─────────────────────────────────────────────────────────
section("6 · Text Summarization (BART)")
SUMMARY = None
if TRANSCRIPT_TEXT:
    try:
        r = requests.post(f"{BASE}/api/v1/transcript/summarize",
            json={"text": TRANSCRIPT_TEXT[:3000], "style": "brief"},
            headers=AUTH, timeout=120)
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        data = r.json()
        SUMMARY = data.get("summary", "")
        ok(f"Summary: {len(SUMMARY.split())} words — \"{SUMMARY[:80]}...\"")
    except Exception as e:
        fail("Summarization failed", str(e))
else:
    warn("Skipped — no transcript text available")


# ─── 7. SEMANTIC SEARCH ────────────────────────────────────────────────────────
section("7 · Semantic Search (FAISS)")
try:
    r = requests.get(f"{BASE}/api/v1/search/", params={"q": "technology artificial intelligence", "top_k": 3},
        headers=AUTH, timeout=15)
    if r.status_code == 200:
        results = r.json().get("results", [])
        ok(f"Search OK — {len(results)} results returned")
    elif r.status_code == 404:
        warn("Search index empty (no videos indexed yet — normal for fresh install)")
    else:
        fail(f"Search HTTP {r.status_code}", r.text[:150])
except Exception as e:
    fail("Search failed", str(e))


# ─── 8. VOICE GENERATION ───────────────────────────────────────────────────────
section("8 · Voice Generation (Edge TTS)")
try:
    r = requests.get(f"{BASE}/api/v1/voice/voices", headers=AUTH, timeout=10)
    assert r.status_code == 200, f"HTTP {r.status_code}"
    voices = r.json().get("voices", [])
    ok(f"Voice list OK — {len(voices)} voices available")
except Exception as e:
    fail("Voice list failed", str(e))

try:
    r = requests.post(f"{BASE}/api/v1/voice/generate",
        json={"text": "This is a test of the AI voice narration system.", "voice_key": "aria"},
        headers=AUTH, timeout=30)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
    audio_bytes = len(r.content)
    ok(f"TTS generate OK — {audio_bytes:,} bytes of audio")
except Exception as e:
    fail("TTS generate failed", str(e))


# ─── 9. MERGE JOB — CREATE ─────────────────────────────────────────────────────
section("9 · Merge Job — Create (audio-only, no video to keep test fast)")
JOB_ID = None
try:
    r = requests.post(f"{BASE}/api/v1/merge", json={
        "video_ids": [TEST_VIDEO, TEST_VIDEO_2],
        "target_duration_minutes": 5,
        "style": "brief",
        "generate_audio": True,
        "generate_video": False,   # skip video gen to keep test under 3 min
        "voice_id": "aria"
    }, headers=AUTH, timeout=15)
    assert r.status_code in (200, 202), f"HTTP {r.status_code}: {r.text[:300]}"
    data = r.json()
    JOB_ID = data.get("job_id")
    assert JOB_ID, "No job_id in response"
    ok(f"Merge job created — ID: {JOB_ID}")
    ok(f"Estimated time: {data.get('estimated_seconds', '?')}s")
except Exception as e:
    fail("Merge job creation failed", str(e))


# ─── 10. MERGE JOB — POLL STATUS ───────────────────────────────────────────────
section("10 · Merge Job — Poll Status")
FINAL_STATUS = None
if JOB_ID:
    print(f"   Polling (max 10 min)...")
    deadline = time.time() + 600
    last_stage = ""
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE}/api/v1/merge/{JOB_ID}", headers=AUTH, timeout=10)
            assert r.status_code == 200
            data = r.json()
            status   = data.get("status", "")
            progress = data.get("progress_percent", 0)
            stage    = data.get("stage_message", "")

            if stage != last_stage:
                print(f"   {YLW}→{RST} [{progress:3d}%] {stage}")
                last_stage = stage

            if status in ("completed", "partial_success"):
                FINAL_STATUS = status
                ok(f"Job finished — status: {BOLD}{status}{RST}")
                break
            elif status == "error":
                FINAL_STATUS = "error"
                fail(f"Job error: {data.get('error', 'unknown')}")
                break
        except Exception as e:
            warn(f"Poll error: {e}")
        time.sleep(5)
    else:
        fail("Job timed out after 5 minutes")
else:
    warn("Skipped — no job ID")


# ─── 11. MERGE JOB — RESULT ────────────────────────────────────────────────────
section("11 · Merge Job — Final Result")
if JOB_ID and FINAL_STATUS in ("completed", "partial_success"):
    try:
        r = requests.get(f"{BASE}/api/v1/merge/{JOB_ID}/result", headers=AUTH, timeout=10)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        result = r.json()

        summary = result.get("summary_text", "")
        audio_url = result.get("audio_url")
        video_url = result.get("video_url")
        rich = result.get("rich_output") or {}
        chapters = rich.get("chapters", [])
        takeaways = rich.get("key_takeaways", [])
        highlights = result.get("highlight_segments", [])

        ok(f"Summary: {len(summary.split())} words")
        ok(f"Audio URL: {audio_url or 'not generated'}")
        ok(f"Video URL: {video_url or 'not generated (skipped)'}")
        ok(f"Chapters: {len(chapters)}")
        ok(f"Key takeaways: {len(takeaways)}")
        ok(f"Highlight segments: {len(highlights)}")

        if summary:
            print(f"\n   {BLU}Summary preview:{RST}")
            print(f"   {summary[:300]}...")

    except Exception as e:
        fail("Result fetch failed", str(e))
else:
    warn("Skipped — job did not complete successfully")


# ─── 12. AUDIO DOWNLOAD ────────────────────────────────────────────────────────
section("12 · Audio Download")
if JOB_ID and FINAL_STATUS in ("completed", "partial_success"):
    try:
        r = requests.get(f"{BASE}/api/v1/merge/{JOB_ID}/audio", headers=AUTH, timeout=15)
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:150]}"
        size = len(r.content)
        ok(f"Audio downloaded — {size:,} bytes ({size//1024} KB)")
    except Exception as e:
        fail("Audio download failed", str(e))
else:
    warn("Skipped — no completed job")


# ─── 13. EXPORT (PDF) ──────────────────────────────────────────────────────────
section("13 · Export Summary as PDF")
if JOB_ID and FINAL_STATUS in ("completed", "partial_success"):
    try:
        r = requests.get(f"{BASE}/api/v1/merge/{JOB_ID}/export",
            params={"format": "pdf"}, headers=AUTH, timeout=15)
        if r.status_code == 200:
            ok(f"PDF export OK — {len(r.content):,} bytes")
        else:
            fail(f"PDF export HTTP {r.status_code}", r.text[:150])
    except Exception as e:
        fail("PDF export failed", str(e))
else:
    warn("Skipped — no completed job")


# ─── 14. HISTORY LOGGING ───────────────────────────────────────────────────────
section("14 · User History")
try:
    r = requests.post(f"{BASE}/api/v1/auth/user-history", json={
        "username": TEST_USER["username"],
        "type": "merge",
        "videoId": TEST_VIDEO,
        "jobId": JOB_ID or "test-job",
        "videoCount": 2,
    }, headers=AUTH, timeout=10)
    assert r.status_code in (200, 201), f"HTTP {r.status_code}: {r.text[:150]}"
    ok("History logged")
except Exception as e:
    fail("History log failed", str(e))

try:
    r = requests.get(f"{BASE}/api/v1/auth/user-history/{TEST_USER['username']}", headers=AUTH, timeout=10)
    assert r.status_code == 200, f"HTTP {r.status_code}"
    items = r.json()
    count = len(items) if isinstance(items, list) else items.get("count", "?")
    ok(f"History fetch OK — {count} items")
except Exception as e:
    fail("History fetch failed", str(e))


# ─── 15. CLEANUP ───────────────────────────────────────────────────────────────
section("15 · Cleanup Test User")
try:
    r = requests.delete(f"{BASE}/api/v1/auth/user/delete/{TEST_USER['username']}", headers=AUTH, timeout=10)
    if r.status_code in (200, 204):
        ok(f"Test user deleted")
    else:
        warn(f"Delete returned HTTP {r.status_code} (may be OK)")
except Exception as e:
    warn(f"Cleanup failed: {e}")


# ─── FINAL REPORT ──────────────────────────────────────────────────────────────
total = passed + failed
print(f"\n{BOLD}{'═'*55}{RST}")
print(f"{BOLD}  RESULTS: {GRN}{passed} passed{RST}  {RED}{failed} failed{RST}  / {total} total{RST}")
print(f"{BOLD}{'═'*55}{RST}\n")

if failed == 0:
    print(f"{GRN}{BOLD}  ✓ All tests passed — project is ready!{RST}\n")
elif failed <= 2:
    print(f"{YLW}{BOLD}  ⚠ Minor issues — check failures above{RST}\n")
else:
    print(f"{RED}{BOLD}  ✗ Multiple failures — review logs above{RST}\n")

sys.exit(0 if failed == 0 else 1)
