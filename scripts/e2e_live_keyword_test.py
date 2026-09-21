import httpx
import time
import asyncio
import json
from backend.core.database import get_database
from backend.core.security import create_access_token

BASE_URL = "http://127.0.0.1:8000"
QUERY = "linear regression and logistic regression"

async def get_auth_token():
    db = await get_database()
    user = await db["users"].find_one()
    if not user:
        raise RuntimeError("No user found in database for auth")
    token = create_access_token({
        "sub": str(user.get("user_id") or user.get("username")),
        "auth_version": int(user.get("auth_version", 0)),
        "role": user.get("role", "user")
    })
    return token

async def test_live_keyword_search():
    token = await get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    print(f"1. Querying live backend YouTube search for: '{QUERY}'...")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        search_res = await client.get(
            f"{BASE_URL}/api/v1/youtube/search",
            params={"q": QUERY, "max_results": 10},
            headers=headers
        )
        if search_res.status_code != 200:
            print(f"Search API returned {search_res.status_code}: {search_res.text}")
            return
        
        data = search_res.json()
        videos = data.get("items", []) or data.get("videos", [])
        print(f"Found {len(videos)} videos from search API.")

        scanned = 0
        searchable = 0
        skipped = 0
        matched = 0
        total_moments = 0

        start_time = time.perf_counter()

        async def fetch_one(video):
            nonlocal scanned, searchable, skipped, matched, total_moments
            vid_id = video.get("id")
            if isinstance(vid_id, dict):
                vid_id = vid_id.get("videoId")
            elif not vid_id:
                vid_id = video.get("videoId")
            
            title = video.get("snippet", {}).get("title", video.get("title", ""))

            scanned += 1
            t0 = time.perf_counter()
            try:
                res = await client.get(
                    f"{BASE_URL}/api/v1/transcript",
                    params={"videoId": vid_id, "allow_whisper": "false", "fast_search": "true"},
                    headers=headers
                )
                dt = (time.perf_counter() - t0) * 1000
                if res.status_code == 200:
                    t_data = res.json()
                    transcript = t_data.get("transcript") or []
                    if transcript:
                        searchable += 1
                        # Check keyword matching
                        terms = ["linear regression", "logistic regression"]
                        matches = []
                        for entry in transcript:
                            txt = entry.get("text", "").lower()
                            if any(t in txt for t in terms):
                                matches.append(entry)
                        if matches:
                            matched += 1
                            total_moments += len(matches)
                            print(f"  [MATCH] {vid_id} ({title[:30]}): {len(matches)} moments ({dt:.0f}ms)")
                        else:
                            print(f"  [SEARCHABLE NO-MATCH] {vid_id} ({title[:30]}) ({dt:.0f}ms)")
                    else:
                        skipped += 1
                        print(f"  [SKIPPED] {vid_id} ({title[:30]}): empty transcript ({dt:.0f}ms)")
                else:
                    skipped += 1
                    print(f"  [SKIPPED] {vid_id} ({title[:30]}): HTTP {res.status_code} ({dt:.0f}ms)")
            except Exception as e:
                skipped += 1
                print(f"  [ERROR] {vid_id}: {e}")

        # Run with concurrency 4 just like React frontend worker
        sem = asyncio.Semaphore(4)
        async def bounded_fetch(v):
            async with sem:
                await fetch_one(v)

        await asyncio.gather(*(bounded_fetch(v) for v in videos))
        total_time = time.perf_counter() - start_time

        print("\n=== E2E LIVE TEST REPORT ===")
        print(f"Query            : '{QUERY}'")
        print(f"Total Search Time: {total_time:.2f}s")
        print(f"Videos Scanned   : {scanned}")
        print(f"Videos Searchable: {searchable}")
        print(f"Videos Skipped   : {skipped}")
        print(f"Videos Matched   : {matched}")
        print(f"Total Moments    : {total_moments}")
        print("============================\n")

if __name__ == "__main__":
    asyncio.run(test_live_keyword_search())

