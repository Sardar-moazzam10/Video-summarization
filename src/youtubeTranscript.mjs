import { API_BASE_URL } from './config/api.js';

/**
 * Fetch transcript for a given YouTube video ID
 * @param {string} videoId - The YouTube video ID
 * @returns {Array} - Array of transcript entries or empty array if unavailable
 */
export const fetchTranscript = async (videoId, options = {}) => {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/transcript?videoId=${videoId}`, {
      signal: options.signal
    });
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
  const matches = [];

  for (let i = 0; i < transcript.length; i++) {
    const entry = transcript[i];
    if (entry.text.toLowerCase().includes(lowerKeyword)) {
      // Build context from previous, current, and next sentences
      const prev = i > 0 ? transcript[i - 1].text : '';
      const next = i < transcript.length - 1 ? transcript[i + 1].text : '';
      
      const textWithContext = [prev, entry.text, next]
        .filter(t => t.trim())
        .join(' ')
        .trim();

      matches.push({
        text: entry.text,
        contextText: textWithContext,
        timestamp: entry.start,
      });
    }
  }

  return matches;
};
