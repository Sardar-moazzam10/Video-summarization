import axios from 'axios';

const API_KEY = process.env.REACT_APP_YOUTUBE_API_KEY;
const BASE_URL = 'https://www.googleapis.com/youtube/v3';

const DEFAULT_OPTIONS = {
  appendPodcast: false, // when true, " podcast" is appended to the query
  duration: 'any',      // YouTube videoDuration: 'any' | 'short' | 'medium' | 'long'
};

/**
 * Fetch videos for a search query.
 *
 * @param {string} searchQuery      Raw user query — sent verbatim unless appendPodcast is set.
 * @param {object} [options]        { appendPodcast, duration }
 * @returns {Promise<Array>}        YouTube search items (empty array on failure).
 */
export const fetchVideos = async (searchQuery, options = {}) => {
  const { appendPodcast, duration } = { ...DEFAULT_OPTIONS, ...options };

  try {
    const q = appendPodcast ? `${searchQuery} podcast` : searchQuery;

    const response = await axios.get(`${BASE_URL}/search`, {
      params: {
        part: 'snippet',
        q,
        type: 'video',
        videoDuration: duration,
        maxResults: 20,
        key: API_KEY,
      },
    });

    const items = response.data?.items || [];

    // The local relevance filter only exists to counteract the injected " podcast"
    // suffix pulling in off-topic results. A plain search is already ranked by
    // YouTube's relevance, so filtering it locally would only drop valid hits.
    if (!appendPodcast) return items;

    // Words of 3+ chars only; short queries ("AI", "F1") would otherwise yield an
    // empty word list and filter every result out.
    const queryWords = searchQuery.toLowerCase().split(/\s+/).filter((w) => w.length > 2);
    if (queryWords.length === 0) return items;

    const relevantVideos = items.filter((video) => {
      const title = (video.snippet?.title || '').toLowerCase();
      const description = (video.snippet?.description || '').toLowerCase();
      return queryWords.some((word) => title.includes(word) || description.includes(word));
    });

    // Never return nothing when YouTube did return results.
    return relevantVideos.length > 0 ? relevantVideos : items;
  } catch (error) {
    console.error('Error fetching videos:', error);
    return [];
  }
};
