with open('/home/weiblocks/Desktop/Video-summarization/src/MergedPodcastPlayer.js', 'r') as f:
    content = f.read()

# Add videoFetchedRef
content = content.replace(
    "  const lastStatusRef = useRef('');",
    "  const lastStatusRef = useRef('');\n  const videoFetchedRef = useRef(false);"
)

# Fix fetchStatus
content = content.replace(
    "        if ((currentStatus === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(currentStatus) || visitedStages.has('video_ready')) && !videoUrl) {",
    "        if ((currentStatus === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(currentStatus) || visitedStages.has('video_ready')) && !videoFetchedRef.current) {\n          videoFetchedRef.current = true;"
)

# Fix SSE
content = content.replace(
    "          } else if ((data.status === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(data.status)) && !videoUrl) {",
    "          } else if ((data.status === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(data.status)) && !videoFetchedRef.current) {\n            videoFetchedRef.current = true;"
)

with open('/home/weiblocks/Desktop/Video-summarization/src/MergedPodcastPlayer.js', 'w') as f:
    f.write(content)

print("patched")
