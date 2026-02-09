#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick verification script for merge backend optimizations.
Tests individual modules without requiring the full backend.
"""

import os
import sys
import tempfile
import shutil
from datetime import datetime

# Ensure UTF-8 output for Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

def print_header(text):
    """Print formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)

def test_imports():
    """Test 1: Verify all new modules can be imported."""
    print_header("TEST 1: Module Imports")

    modules = [
        'video_cache_manager',
        'cleanup_scheduler'
    ]

    success = True
    for module_name in modules:
        try:
            __import__(module_name)
            print(f"  [PASS] {module_name}")
        except Exception as e:
            print(f"  [FAIL] {module_name}: {e}")
            success = False

    return success

def test_video_cache_manager():
    """Test 2: Video cache manager functionality."""
    print_header("TEST 2: Video Cache Manager")

    try:
        from video_cache_manager import VideoCacheManager, VIDEO_CACHE_ENABLED

        print(f"  Cache enabled: {VIDEO_CACHE_ENABLED}")

        # Create instance
        cache_manager = VideoCacheManager()
        print("  [PASS] VideoCacheManager instance created")

        # Test cache stats
        stats = cache_manager.get_cache_stats()
        print(f"  [PASS] Cache stats retrieved")
        print(f"    - Enabled: {stats.get('enabled')}")
        print(f"    - Video count: {stats.get('video_count', 0)}")
        print(f"    - Size: {stats.get('total_size_mb', 0):.1f} MB")
        print(f"    - Max size: {stats.get('max_size_gb', 0)} GB")
        print(f"    - Hit rate: {stats.get('hit_rate_percent', 0):.1f}%")

        # Test cache directory structure
        video_cache_dir = cache_manager.cache_dir
        exists = os.path.exists(video_cache_dir)
        print(f"  [{'PASS' if exists else 'INFO'}] Cache directory: {video_cache_dir}")

        # Test cleanup (dry run)
        print("  Testing cleanup functionality...")
        cleanup_results = cache_manager.cleanup_old_cache()
        print(f"  [PASS] Cleanup executed")
        print(f"    - Removed: {cleanup_results.get('removed_count', 0)} videos")
        print(f"    - Freed: {cleanup_results.get('freed_space_mb', 0):.1f} MB")

        return True

    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False

def test_cleanup_scheduler():
    """Test 3: Cleanup scheduler functionality."""
    print_header("TEST 3: Cleanup Scheduler")

    try:
        from cleanup_scheduler import CleanupScheduler, ENABLE_AUTO_CLEANUP

        print(f"  Auto cleanup enabled: {ENABLE_AUTO_CLEANUP}")

        # Create instance
        scheduler = CleanupScheduler()
        print("  [PASS] CleanupScheduler instance created")

        # Test stats
        stats = scheduler.get_stats()
        print(f"  [PASS] Scheduler stats retrieved")
        print(f"    - Enabled: {stats.get('enabled')}")
        print(f"    - Running: {stats.get('running')}")
        print(f"    - Interval: {stats.get('interval_hours')} hours")
        print(f"    - Total runs: {stats.get('total_runs', 0)}")

        # Test manual cleanup (safe - just checks directories)
        print("  Testing manual cleanup...")
        results = scheduler.run_manual_cleanup()
        print(f"  [PASS] Manual cleanup executed")

        totals = results.get('totals', {})
        print(f"    - Total removed: {totals.get('total_removed', 0)} items")
        print(f"    - Total freed: {totals.get('total_freed_mb', 0):.1f} MB")

        # Show breakdown
        merge_work = results.get('merge_work', {})
        trans_temp = results.get('transcription_temp', {})
        vid_cache = results.get('video_cache', {})

        print(f"    - Merge work dirs: {merge_work.get('removed', 0)}")
        print(f"    - Transcription temps: {trans_temp.get('removed', 0)}")
        print(f"    - Video cache entries: {vid_cache.get('removed_count', 0)}")

        return True

    except Exception as e:
        print(f"  [FAIL] {e}")
        import traceback
        traceback.print_exc()
        return False

def test_configuration():
    """Test 4: Configuration file."""
    print_header("TEST 4: Configuration")

    try:
        env_path = os.path.join(os.path.dirname(__file__), '.env')
        exists = os.path.exists(env_path)

        print(f"  [{'PASS' if exists else 'WARN'}] .env file {'exists' if exists else 'not found'}")

        if exists:
            print(f"  Location: {env_path}")
            with open(env_path, 'r') as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
            print(f"  Configuration lines: {len(lines)}")

            # Show key settings
            key_settings = [
                'VIDEO_CACHE_ENABLED',
                'VIDEO_CACHE_MAX_SIZE_GB',
                'ENABLE_AUTO_CLEANUP',
                'CLEANUP_INTERVAL_HOURS',
                'DOWNLOAD_RETRY_ATTEMPTS'
            ]

            print("\n  Key settings:")
            for setting in key_settings:
                value = os.getenv(setting, 'not set')
                print(f"    - {setting}: {value}")

        return True

    except Exception as e:
        print(f"  [FAIL] {e}")
        return False

def test_directory_structure():
    """Test 5: Directory structure."""
    print_header("TEST 5: Directory Structure")

    try:
        base_dir = os.path.dirname(__file__)
        audio_cache = os.path.join(base_dir, 'audio_cache')

        directories = {
            'audio_cache': audio_cache,
            'merge_work': os.path.join(audio_cache, 'merge_work'),
            'merged': os.path.join(audio_cache, 'merged'),
            'video_cache': os.path.join(audio_cache, 'video_cache'),
            'transcripts': os.path.join(base_dir, 'transcripts')
        }

        for name, path in directories.items():
            exists = os.path.exists(path)
            status = "EXISTS" if exists else "MISSING"

            size_info = ""
            if exists:
                # Count items
                try:
                    items = os.listdir(path)
                    size_info = f" ({len(items)} items)"
                except:
                    size_info = " (access error)"

            print(f"  [{status}] {name}: {path}{size_info}")

        return True

    except Exception as e:
        print(f"  [FAIL] {e}")
        return False

def test_file_existence():
    """Test 6: Verify all new files exist."""
    print_header("TEST 6: New Files")

    base_dir = os.path.dirname(__file__)

    files = {
        'Modules': [
            'video_cache_manager.py',
            'cleanup_scheduler.py'
        ],
        'Scripts': [
            'manual_cleanup.py',
            'test_merge_optimizations.py',
            'verify_optimizations.py'
        ],
        'Documentation': [
            'OPTIMIZATION_GUIDE.md',
            'IMPLEMENTATION_SUMMARY.md',
            'QUICKSTART_OPTIMIZATIONS.md'
        ],
        'Configuration': [
            '.env'
        ]
    }

    all_exist = True
    for category, file_list in files.items():
        print(f"\n  {category}:")
        for filename in file_list:
            path = os.path.join(base_dir, filename)
            exists = os.path.exists(path)
            status = "EXISTS" if exists else "MISSING"

            size_info = ""
            if exists:
                size = os.path.getsize(path)
                size_info = f" ({size:,} bytes)"

            print(f"    [{status}] {filename}{size_info}")

            if not exists:
                all_exist = False

    return all_exist

def run_all_tests():
    """Run all verification tests."""
    print("\n" + "=" * 70)
    print("  MERGE BACKEND OPTIMIZATION VERIFICATION")
    print("=" * 70)
    print(f"  Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    results = {}

    # Run tests
    results['imports'] = test_imports()
    results['files'] = test_file_existence()
    results['config'] = test_configuration()
    results['directories'] = test_directory_structure()
    results['video_cache'] = test_video_cache_manager()
    results['cleanup'] = test_cleanup_scheduler()

    # Summary
    print_header("VERIFICATION SUMMARY")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print(f"\n  Tests passed: {passed}/{total}")
    print(f"  Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    for test_name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {test_name}")

    print("\n" + "=" * 70)

    if all(results.values()):
        print("  ALL TESTS PASSED!")
        print("=" * 70)
        print("\n  Next steps:")
        print("    1. Install dependencies: pip install -r requirements.txt")
        print("    2. Clean existing temps: python manual_cleanup.py")
        print("    3. Start backend: python merge_backend.py")
        print("    4. Run full tests: python test_merge_optimizations.py")
        return 0
    else:
        print("  SOME TESTS FAILED - Review errors above")
        print("=" * 70)
        return 1

if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
