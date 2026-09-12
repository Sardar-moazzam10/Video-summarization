const fs = require('fs');
const file = '/home/weiblocks/Desktop/Video-summarization/src/MergedPodcastPlayer.js';
let content = fs.readFileSync(file, 'utf8');

// In fetchStatus()
content = content.replace(
  "        if (currentStatus === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(currentStatus) || visitedStages.has('video_ready')) {\n          axios.get(`${API_BASE_URL}/api/v1/merge/${mergeId}/result`)",
  "        if ((currentStatus === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(currentStatus) || visitedStages.has('video_ready')) && !videoUrl) {\n          axios.get(`${API_BASE_URL}/api/v1/merge/${mergeId}/result`)"
);

// In SSE onmessage
content = content.replace(
  "          } else if (data.status === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(data.status)) {\n            axios.get(`${API_BASE_URL}/api/v1/merge/${mergeId}/result`)",
  "          } else if ((data.status === 'video_ready' || ['summarizing', 'enriching', 'generating_voice'].includes(data.status)) && !videoUrl) {\n            axios.get(`${API_BASE_URL}/api/v1/merge/${mergeId}/result`)"
);

fs.writeFileSync(file, content);
console.log("Patched frontend");
