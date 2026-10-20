"""Regression: a low-bitrate dub must not displace the original speaker."""
import json

from yt_dlp import YoutubeDL

from backend.services.source_media_policy import (
    AUDIO_SELECTION_POLICY, SOURCE_AUDIO_FORMAT, SOURCE_VIDEO_FORMAT,
)
from video_cache_manager import VideoCacheManager


def select_formats(expression, formats):
    with YoutubeDL({'quiet': True, 'format': expression}) as downloader:
        selector = downloader.build_format_selector(expression)
        return list(selector({
            'formats': formats, 'has_merged_format': False,
            'incomplete_formats': False,
        }))


def test_original_above_bitrate_cap_wins_over_polish_dub():
    formats = [
        dict(format_id='video', url='https://example.com/video', ext='mp4',
             vcodec='h264', acodec='none', height=360),
        dict(format_id='original', url='https://example.com/en', ext='m4a',
             vcodec='none', acodec='aac', abr=128, language_preference=10),
        dict(format_id='dub', url='https://example.com/pl', ext='m4a',
             vcodec='none', acodec='aac', abr=48, language_preference=-1),
    ]
    selected = select_formats(SOURCE_VIDEO_FORMAT, formats)[0]
    assert selected['requested_formats'][1]['format_id'] == 'original'
    assert select_formats(SOURCE_AUDIO_FORMAT, formats)[0]['format_id'] == 'original'


def test_unlabelled_single_language_source_still_works():
    formats = [dict(format_id='audio', url='https://example.com/audio', ext='m4a',
                    vcodec='none', acodec='aac', abr=128)]
    assert select_formats(SOURCE_AUDIO_FORMAT, formats)[0]['format_id'] == 'audio'


def test_legacy_cache_is_preserved_but_not_reused(tmp_path, monkeypatch):
    manager = VideoCacheManager()
    manager.cache_dir = str(tmp_path)
    directory = tmp_path / 'source'
    directory.mkdir()
    video = directory / 'video.mp4'
    video.write_bytes(b'legacy-dub')
    metadata = directory / 'metadata.json'
    metadata.write_text(json.dumps({'video_id': 'source'}))
    monkeypatch.setattr(manager, '_validate_cached_video', lambda _: True)
    assert manager.get_cached_video('source') is None
    assert video.read_bytes() == b'legacy-dub'
    metadata.write_text(json.dumps({'audio_selection_policy': AUDIO_SELECTION_POLICY}))
    assert manager.get_cached_video('source') == str(video)
