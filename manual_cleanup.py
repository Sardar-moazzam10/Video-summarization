# -*- coding: utf-8 -*-
"""
Manual Cleanup Script - Clean existing temp directories and cache.
Run this once to clean up existing 6.2GB of uncleaned temp files.
"""

import os
import sys
import shutil
from datetime import datetime

# Ensure UTF-8 output for Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
AUDIO_CACHE_DIR = os.path.join(BASE_DIR, "audio_cache")


def get_dir_size(path):
    """Calculate total size of directory in bytes."""
    total_size = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if os.path.exists(filepath):
                    total_size += os.path.getsize(filepath)
    except Exception as e:
        print(f"WARNING: Error calculating size for {path}: {e}")
    return total_size


def clean_directory(base_dir, prefix, dry_run=True):
    """Clean directories matching prefix."""
    if not os.path.exists(base_dir):
        print(f"WARNING: Directory not found: {base_dir}")
        return {"removed": 0, "freed_mb": 0}

    removed_count = 0
    freed_bytes = 0

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Scanning {base_dir} for '{prefix}*' directories...")

    for item in os.listdir(base_dir):
        item_path = os.path.join(base_dir, item)

        if not item.startswith(prefix) or not os.path.isdir(item_path):
            continue

        try:
            # Get directory info
            mtime = datetime.fromtimestamp(os.path.getmtime(item_path))
            dir_size = get_dir_size(item_path)
            age_hours = (datetime.now() - mtime).total_seconds() / 3600

            print(f"  [DIR] {item} - {dir_size / (1024*1024):.1f} MB - {age_hours:.1f}h old")

            if not dry_run:
                shutil.rmtree(item_path, ignore_errors=False)
                print(f"    [REMOVED]")

            removed_count += 1
            freed_bytes += dir_size

        except Exception as e:
            print(f"    ERROR: {e}")

    return {"removed": removed_count, "freed_mb": freed_bytes / (1024 * 1024)}


def main():
    print("=" * 70)
    print("MANUAL CLEANUP SCRIPT")
    print("=" * 70)
    print("\nThis script will clean up old temporary directories:")
    print("  - audio_cache/merge_work/merge_* (merge temp directories)")
    print("  - audio_cache/transcribe_* (transcription temp directories)")
    print("\n" + "=" * 70)

    # Dry run first
    print("\nPHASE 1: DRY RUN (scanning only, no deletion)")
    print("=" * 70)

    merge_stats = clean_directory(os.path.join(AUDIO_CACHE_DIR, "merge_work"), "merge_", dry_run=True)
    transcribe_stats = clean_directory(AUDIO_CACHE_DIR, "transcribe_", dry_run=True)

    total_removed = merge_stats["removed"] + transcribe_stats["removed"]
    total_freed_mb = merge_stats["freed_mb"] + transcribe_stats["freed_mb"]

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Total directories found: {total_removed}")
    print(f"  Total space to free: {total_freed_mb:.1f} MB ({total_freed_mb / 1024:.2f} GB)")
    print("=" * 70)

    if total_removed == 0:
        print("\nNo temp directories found to clean!")
        return

    # Confirm deletion
    print("\nWARNING: This will permanently delete these directories!")
    response = input("\nProceed with cleanup? (yes/no): ").strip().lower()

    if response != "yes":
        print("\nCleanup cancelled.")
        return

    # Actual cleanup
    print("\nPHASE 2: CLEANUP (deleting directories)")
    print("=" * 70)

    merge_stats = clean_directory(os.path.join(AUDIO_CACHE_DIR, "merge_work"), "merge_", dry_run=False)
    transcribe_stats = clean_directory(AUDIO_CACHE_DIR, "transcribe_", dry_run=False)

    total_removed = merge_stats["removed"] + transcribe_stats["removed"]
    total_freed_mb = merge_stats["freed_mb"] + transcribe_stats["freed_mb"]

    print("\n" + "=" * 70)
    print("CLEANUP COMPLETE")
    print("=" * 70)
    print(f"  Directories removed: {total_removed}")
    print(f"  Space freed: {total_freed_mb:.1f} MB ({total_freed_mb / 1024:.2f} GB)")
    print("=" * 70)


if __name__ == "__main__":
    main()
