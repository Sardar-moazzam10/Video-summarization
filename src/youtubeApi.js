import axios from 'axios';
import { API_BASE_URL } from './config/api.js';

const SEARCH_URL = `${API_BASE_URL}/api/v1/youtube/search`;

const DEFAULT_OPTIONS = {
  appendPodcast: false, // when true, " podcast" is appended to the query
  duration: 'any',      // YouTube videoDuration: 'any' | 'short' | 'medium' | 'long'
  maxResults: 20,
  license: 'any',       // 'any' | 'creativeCommon' | 'youtube'
  includeRights: true,  // when true, requests status.license enrichment
};

/**
 * Fetch videos for a search query.
 *
 * @param {string} searchQuery      Raw user query — sent verbatim unless appendPodcast is set.
 * @param {object} [options]        { appendPodcast, duration, maxResults }
 * @param {object} [options]        { appendPodcast, duration, maxResults, license, includeRights }
 * @returns {Promise<Array>}        YouTube search items; rejects with a user-facing error on failure.
 */
export const fetchVideos = async (searchQuery, options = {}) => {
  const { appendPodcast, duration, maxResults, license, includeRights } = {
    ...DEFAULT_OPTIONS,
    ...options,
  };

  const q = appendPodcast ? `${searchQuery} podcast` : searchQuery;

  try {
    const params = {
      q,
      duration,
      max_results: maxResults,
    };
    if (license && license !== 'any') {
      params.license = license;
    }
    if (includeRights) {
      params.include_rights = true;
    }

    const response = await axios.get(SEARCH_URL, { params });

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
    const reason = error.response?.data?.error?.errors?.[0]?.reason;
    const apiMessage = error.response?.data?.detail || error.response?.data?.error?.message;

    if (reason === 'quotaExceeded' || reason === 'dailyLimitExceeded') {
      throw new Error('YouTube search quota has been reached. Please try again later.');
    }
    if (reason === 'keyInvalid' || reason === 'accessNotConfigured') {
      throw new Error('YouTube search is not configured correctly. Please contact the administrator.');
    }
    if (!error.response) {
      throw new Error('Could not connect to YouTube. Check your internet connection and try again.');
    }

    throw new Error(apiMessage || 'YouTube search failed. Please try again.');
  }
};
