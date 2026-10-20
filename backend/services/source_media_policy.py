"""Select source audio before optimizing bitrate, so dubs never win on size."""

AUDIO_SELECTION_POLICY = "original-audio-v1"

# YouTube marks original tracks with language_preference=10. Do not cap their
# bitrate: the original may only exist above 64 kbps while dubs exist below it.
# Unlabelled sources use yt-dlp's language ranking before quality/bitrate.
SOURCE_AUDIO_FORMAT = "bestaudio[language_preference>=10]/bestaudio"
SOURCE_VIDEO_FORMAT = (
    "bestvideo[height<=360][ext=mp4]+bestaudio[language_preference>=10]/"
    "best[height<=360][ext=mp4][language_preference>=10]/"
    "bestvideo[height<=360][ext=mp4]+bestaudio/"
    "best[height<=360][ext=mp4]/worst[ext=mp4]/worst"
)
SOURCE_AUDIO_OPTIONS = [
    "--ignore-config", "--no-playlist", "--format-sort", "lang,quality",
]
