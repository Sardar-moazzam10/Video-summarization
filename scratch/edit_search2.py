import re

with open('/home/weiblocks/Desktop/Video-summarization/src/SearchByKeywordsPage.js', 'r') as f:
    content = f.read()

# The block to replace starts with: {/* Bottom action bar — merge takes priority when videos are selected */}
# And ends with: </svg> Auto-select Best Moments </button> </motion.div> ) : null}
# Let's just find the start and end indices.

start_idx = content.find("{/* Bottom action bar")
end_idx = content.find(") : null}", start_idx) + len(") : null}")

multi_select = """
        {/* Using MultiSelectBar instead of custom bottom bar */}
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

if start_idx != -1 and end_idx != -1:
    new_content = content[:start_idx] + multi_select + content[end_idx:]
    with open('/home/weiblocks/Desktop/Video-summarization/src/SearchByKeywordsPage.js', 'w') as f:
        f.write(new_content)
    print("Replaced successfully")
else:
    print("Could not find block")
