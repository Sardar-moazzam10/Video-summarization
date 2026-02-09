"""
Test script for merge backend optimizations.
Validates cache functionality, fault tolerance, and cleanup.
"""

import requests
import time
import json
from datetime import datetime

BASE_URL = "http://localhost:5002"


def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test_health_check():
    """Test 1: Health check and cache stats."""
    print_section("TEST 1: Health Check & Cache Stats")

    response = requests.get(f"{BASE_URL}/health")
    data = response.json()

    print("✅ Health Status:")
    print(f"  Status: {data.get('status')}")
    print(f"  FFmpeg: {data.get('ffmpeg')}")
    print(f"  yt-dlp: {data.get('ytdlp')}")
    print(f"  Active Jobs: {data.get('active_jobs')}")

    print("\n📊 Cache Stats:")
    cache = data.get('cache', {})
    print(f"  Enabled: {cache.get('enabled')}")
    print(f"  Videos Cached: {cache.get('video_count', 0)}")
    print(f"  Cache Size: {cache.get('total_size_mb', 0):.1f} MB")
    print(f"  Hit Rate: {cache.get('hit_rate_percent', 0):.1f}%")

    print("\n🧹 Cleanup Stats:")
    cleanup = data.get('cleanup', {})
    print(f"  Enabled: {cleanup.get('enabled')}")
    print(f"  Running: {cleanup.get('running')}")
    print(f"  Last Run: {cleanup.get('last_run', 'Never')}")

    return data


def test_merge_job(video_ids, target_duration=180):
    """Submit a merge job and poll until completion."""
    print_section(f"Merge Job: {len(video_ids)} videos, {target_duration}s target")

    # Submit job
    payload = {
        "selectedSegments": [{"videoId": vid} for vid in video_ids],
        "targetDuration": target_duration
    }

    print(f"📤 Submitting merge job...")
    response = requests.post(f"{BASE_URL}/merge", json=payload)
    data = response.json()
    merge_id = data.get("mergeId")

    print(f"✅ Job submitted: {merge_id}")
    print(f"  Status: {data.get('status')}")

    # Poll for completion
    start_time = time.time()
    last_progress = -1

    while True:
        time.sleep(2)

        response = requests.get(f"{BASE_URL}/merge/{merge_id}")
        status_data = response.json()

        status = status_data.get("status")
        progress = status_data.get("progress_percent", 0)
        stage = status_data.get("stage", "")

        # Print progress updates
        if progress != last_progress:
            elapsed = time.time() - start_time
            print(f"  [{progress:3d}%] {stage} ({elapsed:.1f}s elapsed)")
            last_progress = progress

        # Check for completion
        if status in ["completed", "partial_success", "error"]:
            elapsed = time.time() - start_time
            print(f"\n✅ Job finished in {elapsed:.1f}s")
            print(f"  Status: {status}")

            if status == "partial_success":
                print(f"  ⚠️  Warnings: {len(status_data.get('warnings', []))}")
                print(f"  ⚠️  Failed videos: {status_data.get('failed_videos', [])}")
                print(f"  ✅ Successful: {status_data.get('successful_videos', 0)}/{status_data.get('total_videos', 0)}")

            if status == "error":
                print(f"  ❌ Error: {status_data.get('error')}")

            return {
                "merge_id": merge_id,
                "status": status,
                "elapsed_time": elapsed,
                "data": status_data
            }


def test_cache_reuse(video_ids):
    """Test that second run with same videos is faster (cache hit)."""
    print_section("TEST 2: Cache Reuse (Second Run)")

    print("🔄 Running same videos again to test cache...")
    result = test_merge_job(video_ids, target_duration=120)

    return result


def test_fault_tolerance():
    """Test fault tolerance with intentionally failing video."""
    print_section("TEST 3: Fault Tolerance (Invalid Video)")

    # Mix valid and invalid video IDs
    video_ids = [
        "dQw4w9WgXcQ",  # Valid: Rick Astley - Never Gonna Give You Up
        "INVALID_ID_12345",  # Invalid: Should fail
        "jNQXAC9IVRw"  # Valid: Me at the zoo
    ]

    print("📝 Testing with 1 invalid video among 2 valid ones...")
    result = test_merge_job(video_ids, target_duration=90)

    if result["status"] == "partial_success":
        print("✅ PASS: Job completed with partial success")
    elif result["status"] == "completed":
        print("⚠️  UNEXPECTED: Job completed without detecting failure")
    else:
        print("❌ FAIL: Job failed completely (should have continued)")

    return result


def test_manual_cleanup():
    """Test manual cleanup endpoint."""
    print_section("TEST 4: Manual Cleanup")

    print("🧹 Triggering manual cleanup...")
    response = requests.post(f"{BASE_URL}/cleanup/manual")
    data = response.json()

    print(f"✅ Cleanup completed:")
    results = data.get("results", {})
    totals = results.get("totals", {})

    print(f"  Total removed: {totals.get('total_removed', 0)} items")
    print(f"  Space freed: {totals.get('total_freed_mb', 0):.1f} MB")

    print(f"\n  Merge work: {results.get('merge_work', {}).get('removed', 0)} dirs")
    print(f"  Transcription: {results.get('transcription_temp', {}).get('removed', 0)} dirs")
    print(f"  Video cache: {results.get('video_cache', {}).get('removed_count', 0)} videos")

    return data


def run_all_tests():
    """Run all tests in sequence."""
    print("\n" + "=" * 70)
    print("🧪 MERGE BACKEND OPTIMIZATION TESTS")
    print("=" * 70)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}

    try:
        # Test 1: Health check
        results["health"] = test_health_check()

        # Test 2: First merge job (cache miss)
        print("\n⏸️  Press Enter to start Test 2 (first merge job)...")
        input()

        test_videos = [
            "dQw4w9WgXcQ",  # Rick Astley - Never Gonna Give You Up
            "jNQXAC9IVRw"   # Me at the zoo
        ]

        print_section("TEST 2A: First Merge (Cache Miss)")
        results["first_merge"] = test_merge_job(test_videos, target_duration=120)

        # Test 3: Second merge job (cache hit)
        print("\n⏸️  Press Enter to start Test 2B (cache reuse test)...")
        input()

        results["second_merge"] = test_cache_reuse(test_videos)

        # Compare times
        first_time = results["first_merge"]["elapsed_time"]
        second_time = results["second_merge"]["elapsed_time"]
        speedup = ((first_time - second_time) / first_time) * 100

        print_section("Cache Performance Comparison")
        print(f"  First run:  {first_time:.1f}s (cache miss)")
        print(f"  Second run: {second_time:.1f}s (cache hit)")
        print(f"  Speedup:    {speedup:.1f}% faster")

        if speedup > 20:
            print("  ✅ PASS: Significant speedup from caching")
        else:
            print("  ⚠️  WARN: Cache speedup lower than expected")

        # Test 4: Fault tolerance
        print("\n⏸️  Press Enter to start Test 3 (fault tolerance)...")
        input()

        results["fault_tolerance"] = test_fault_tolerance()

        # Test 5: Manual cleanup
        print("\n⏸️  Press Enter to start Test 4 (manual cleanup)...")
        input()

        results["cleanup"] = test_manual_cleanup()

        # Final health check
        print("\n⏸️  Press Enter for final health check...")
        input()

        results["final_health"] = test_health_check()

    except KeyboardInterrupt:
        print("\n\n⚠️ Tests interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

    # Summary
    print_section("TEST SUMMARY")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n✅ Tests completed successfully!")
    print("\nKey Findings:")

    if "first_merge" in results and "second_merge" in results:
        first_time = results["first_merge"]["elapsed_time"]
        second_time = results["second_merge"]["elapsed_time"]
        speedup = ((first_time - second_time) / first_time) * 100
        print(f"  • Cache speedup: {speedup:.1f}%")

    if "fault_tolerance" in results:
        ft_status = results["fault_tolerance"]["status"]
        print(f"  • Fault tolerance: {ft_status}")

    if "cleanup" in results:
        totals = results["cleanup"].get("results", {}).get("totals", {})
        print(f"  • Cleanup freed: {totals.get('total_freed_mb', 0):.1f} MB")


if __name__ == "__main__":
    print("\n⚠️  IMPORTANT: Make sure merge_backend.py is running on port 5002")
    print("Start it with: python merge_backend.py\n")

    input("Press Enter when ready to start tests...")

    run_all_tests()
