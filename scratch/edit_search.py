import re

with open('/home/weiblocks/Desktop/Video-summarization/src/SearchByKeywordsPage.js', 'r') as f:
    content = f.read()

# Import MultiSelectBar
content = content.replace("import './VideoCard.css';", "import './VideoCard.css';\nimport MultiSelectBar from './components/merge/MultiSelectBar.jsx';")

# Add handleMerge
handle_merge_code = """
  const handleMerge = async (durationMinutes) => {
    if (selectedVideos.length < 1) return;
    
    // We already have loading state, but let's re-use it or set a merge state
    setLoading(true);
    try {
      const token = localStorage.getItem('access_token') || '';
      const res = await fetch(`${API_BASE_URL}/api/v1/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          video_ids: selectedVideos,
          target_duration_minutes: durationMinutes,
          generate_audio: true,
          generate_video: false,
          style: 'educational',
        }),
      });
      
      if (!res.ok) throw new Error('Merge failed');
      const data = await res.json();
      
      const selectedResults = results.filter((r) => selectedVideos.includes(r.video.id.videoId));
      const videoData = selectedResults.map(r => ({
        id: r.video.id?.videoId,
        title: r.video.snippet?.title,
        thumbnail: r.video.snippet?.thumbnails?.medium?.url || r.video.snippet?.thumbnails?.default?.url,
      }));
      
      navigate('/merged-podcast-player', {
        state: { 
          jobId: data.job_id,
          videoData: videoData,
          durations: data.durations || {},
          totalDuration: data.total_duration || 0
        }
      });
    } catch (e) {
      console.error(e);
      setLoading(false);
    }
  };
"""

# Insert handleMerge just before handleOpenMergePreview
content = content.replace("  const handleOpenMergePreview = () => {", handle_merge_code + "\n  const handleOpenMergePreview = () => {")

# Remove the bottom action bar block and replace with MultiSelectBar
# The bottom bar starts with {/* Bottom action bar
bottom_bar_regex = re.compile(r'\{\/\*\s*Bottom action bar.*?<\/div>\n          <\/motion\.div>\n        \)\s*\}', re.DOTALL)
multi_select = """
        <MultiSelectBar
          selectedVideos={results.filter(r => selectedVideos.includes(r.video.id.videoId)).map(r => ({
            id: r.video.id.videoId,
            title: r.video.snippet.title,
            thumbnail: r.video.snippet.thumbnails?.medium?.url || r.video.snippet.thumbnails?.default?.url
          }))}
          onRemove={(id) => setSelectedVideos(prev => prev.filter(vid => vid !== id))}
          onClear={() => setSelectedVideos([])}
          onMerge={handleMerge}
          isLoading={loading}
        />
"""
content = bottom_bar_regex.sub(multi_select, content)

with open('/home/weiblocks/Desktop/Video-summarization/src/SearchByKeywordsPage.js', 'w') as f:
    f.write(content)
print("Done")
