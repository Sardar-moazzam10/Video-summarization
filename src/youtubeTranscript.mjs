/**
 * Fetch transcript for a given YouTube video ID
 * @param {string} videoId - The YouTube video ID
 * @returns {Array} - Array of transcript entries or empty array if unavailable
 */
export const fetchTranscript = async (videoId) => {
  try {
    const response = await fetch(`http://localhost:8000/api/v1/transcript?videoId=${videoId}`);
    if (!response.ok) {
      throw new Error(`Error: ${response.status}`);
    }

    const data = await response.json();

    // Backend returns { transcript: [...], source, cached } — unwrap it
    const transcript = Array.isArray(data) ? data : data?.transcript || [];

    if (!Array.isArray(transcript) || transcript.length === 0) {
      console.warn("Transcript API returned empty or invalid format:", data.error || data);
      return [];
    }

    return transcript;
  } catch (error) {
    console.error('🔥 Error fetching transcript:', error.message);
    return [];
  }
};

/**
 * Search for a keyword in the transcript
 * @param {Array} transcript - Transcript array from fetchTranscript
 * @param {string} keyword - Keyword to search for
 * @returns {Array} - Array of matches with text and timestamps
 */
export const searchKeywordInTranscript = (transcript, keyword) => {
  if (!transcript || transcript.length === 0) return [];

  const lowerKeyword = keyword.toLowerCase();

  return transcript
    .filter((entry) => entry.text.toLowerCase().includes(lowerKeyword))
    .map((entry) => ({
      text: entry.text,
      timestamp: entry.start,
    }));
};

// ✅ Example Usage for Testing
(async () => {
  const videoId = 'UF8uR6Z6KLc'; // Example video
  console.log(`📺 Fetching transcript for: ${videoId}`);

  const transcript = await fetchTranscript(videoId);

  if (transcript.length > 0) {
    console.log('✅ Transcript fetched successfully:', transcript);

    const keyword = 'habit';
    const matches = searchKeywordInTranscript(transcript, keyword);
    console.log(`🔍 Matches for "${keyword}":`, matches);
  } else {
    console.log('❌ No transcript available for this video.');
  }
})();
