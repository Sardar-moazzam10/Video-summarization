with open('/home/weiblocks/Desktop/Video-summarization/src/MergedPodcastPlayer.js', 'r') as f:
    content = f.read()

content = content.replace(
  "        if (currentStatus === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(currentStatus) || visitedStages.has('video_ready')) {\n          axios.get(`${API_BASE_URL}/api/v1/merge/${mergeId}/result`)",
  "        if ((currentStatus === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(currentStatus) || visitedStages.has('video_ready')) && !videoUrl) {\n          axios.get(`${API_BASE_URL}/api/v1/merge/${mergeId}/result`)"
)

content = content.replace(
  "          } else if (data.status === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(data.status)) {\n            axios.get(`${API_BASE_URL}/api/v1/merge/${mergeId}/result`)",
  "          } else if ((data.status === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(data.status)) && !videoUrl) {\n            axios.get(`${API_BASE_URL}/api/v1/merge/${mergeId}/result`)"
)

with open('/home/weiblocks/Desktop/Video-summarization/src/MergedPodcastPlayer.js', 'w') as f:
    f.write(content)
print("Patched frontend")
