from backend.api.merge import _merge_overlapping_clips

def test_merge_overlapping_clips_removes_boundary_echo():
    # Simulate clips from the semantic segmenter where adjacent segments overlap by 1 second.
    # Clip 1 ends at 20.0, Clip 2 starts at 19.0.
    clips = [
        {
            "video_id": "_QXjl-4IuzY",
            "start_time": 10.0,
            "end_time": 20.0,
            "text": "...machine learning is the subfield of AI",
        },
        {
            "video_id": "_QXjl-4IuzY",
            "start_time": 19.0,
            "end_time": 30.0,
            "text": "...field of AI, but the main goal...",
        },
    ]

    merged = _merge_overlapping_clips(clips)
    
    assert len(merged) == 1, "Clips should be merged into a single clip"
    assert merged[0]["start_time"] == 10.0
    assert merged[0]["end_time"] == 30.0
    assert "...machine learning is the subfield of AI" in merged[0]["text"]
    assert "...field of AI, but the main goal..." in merged[0]["text"]


def test_does_not_merge_unrelated_videos():
    clips = [
        {
            "video_id": "video1",
            "start_time": 10.0,
            "end_time": 20.0,
            "text": "test 1",
        },
        {
            "video_id": "video2",
            "start_time": 19.0,
            "end_time": 30.0,
            "text": "test 2",
        },
    ]

    merged = _merge_overlapping_clips(clips)
    assert len(merged) == 2, "Should not merge clips from different videos"

def test_does_not_merge_gapped_clips():
    clips = [
        {
            "video_id": "video1",
            "start_time": 10.0,
            "end_time": 20.0,
            "text": "test 1",
        },
        {
            "video_id": "video1",
            "start_time": 25.0,
            "end_time": 30.0,
            "text": "test 2",
        },
    ]

    merged = _merge_overlapping_clips(clips)
    assert len(merged) == 2, "Should not merge clips with a time gap > 0.1s"
