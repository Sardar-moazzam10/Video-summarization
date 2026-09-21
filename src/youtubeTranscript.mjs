import { API_BASE_URL, authenticatedFetch } from './config/api.js';

/**
 * Normalizes text for robust comparison:
 * - Converts to lower case
 * - Replaces dashes/underscores/slashes with spaces
 * - Strips non-alphanumeric characters except spaces
 * - Collapses whitespace
 */
export const normalizeText = (str = '') =>
  str
    .toLowerCase()
    .replace(/[-_/\\+]/g, ' ')
    .replace(/[^\w\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim();

/**
 * Basic word stemmer for simple English plurals/suffixes (e.g. networks -> network)
 */
export const stemWord = (word = '') => {
  if (!word || word.length <= 3) return word || '';
  if (word.endsWith('ies') && word.length > 4) return word.slice(0, -3) + 'y';
  if (word.endsWith('es') && word.length > 4) {
    if (word.endsWith('sses') || word.endsWith('shes') || word.endsWith('ches') || word.endsWith('xes')) {
      return word.slice(0, -2);
    }
  }
  if (word.endsWith('s') && !word.endsWith('ss') && word.length > 3) {
    return word.slice(0, -1);
  }
  return word;
};

/**
 * Fetch transcript for a given YouTube video ID.
 *
 * @param {string} videoId - The YouTube video ID
 * @param {object} options - { signal, allowWhisper: boolean }
 * @returns {Promise<Array>} - Array of transcript entries
 */
export const fetchTranscript = async (videoId, options = {}) => {
  const allowWhisper = options.allowWhisper ?? true;
  const fastSearch = options.fastSearch ?? (!allowWhisper);
  const url = `${API_BASE_URL}/api/v1/transcript?videoId=${encodeURIComponent(videoId)}&allow_whisper=${allowWhisper}&fast_search=${fastSearch}`;

  try {
    const response = await authenticatedFetch(url, {
      signal: options.signal,
    });

    if (!response.ok) {
      if (response.status === 401) {
        const err = new Error('Authentication expired or invalid. Please log in again.');
        err.status = 401;
        throw err;
      }
      if (response.status === 404) {
        // Video has no captions available
        return [];
      }
      const err = new Error(`Transcript fetch failed with HTTP ${response.status}`);
      err.status = response.status;
      throw err;
    }

    const data = await response.json();
    const transcript = Array.isArray(data) ? data : data?.transcript || [];

    if (!Array.isArray(transcript) || transcript.length === 0) {
      return [];
    }

    return transcript;
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    if (error.status === 401) throw error;

    if (error.message && (error.message.includes('Failed to fetch') || error.message.includes('NetworkError'))) {
      const netErr = new Error('Backend server is unreachable. Please verify it is running on http://localhost:8000.');
      netErr.isNetworkError = true;
      throw netErr;
    }

    console.warn(`[Transcript] Notice for video ${videoId}:`, error.message);
    return [];
  }
};

/**
 * Search for a keyword in the transcript with sliding window and token awareness.
 *
 * Distinguishes:
 * - isExact: true (exact verbatim phrase, single segment or adjacent boundary)
 * - isExact: false (inflection/stemmed match such as plural/singular)
 *
 * @param {Array} transcript - Array of { text, start, duration }
 * @param {string} keyword - Keyword or phrase to search for
 * @returns {Array} - Matching moments with text, context, timestamp, isExact
 */
const STOP_WORDS = new Set(['and', 'the', 'for', 'with', 'from', 'about', 'this', 'that', 'into', 'over']);

/**
 * Extracts candidate search terms from a keyword input.
 * Handles comma-separated keywords and conjunctions ("and", "&", "vs", "or").
 */
export const extractSearchTerms = (keyword = '') => {
  const trimmed = keyword.trim();
  if (!trimmed) return [];

  const terms = [trimmed];
  const seen = new Set([trimmed.toLowerCase()]);

  const addTerm = (term) => {
    const s = term.trim();
    const lower = s.toLowerCase();
    if (s.length >= 2 && !STOP_WORDS.has(lower) && !seen.has(lower)) {
      seen.add(lower);
      terms.push(s);
    }
  };

  // Comma-separated terms (e.g. "linear regression, logistic regression")
  if (trimmed.includes(',')) {
    trimmed.split(',').forEach(addTerm);
  }

  // Conjunction-separated phrases (e.g. "linear regression and logistic regression")
  const conjParts = trimmed.split(/\s+(?:and|&|vs|or)\s+/i);
  if (conjParts.length > 1) {
    conjParts.forEach(addTerm);
  }

  return terms;
};

/**
 * Search for a single keyword in the transcript with sliding window and token awareness.
 */
export const searchSingleKeywordInTranscript = (transcript, keyword) => {
  if (!transcript || !Array.isArray(transcript) || transcript.length === 0) return [];
  if (!keyword || !keyword.trim()) return [];

  const normKw = normalizeText(keyword);
  if (!normKw) return [];

  const kwTokens = normKw.split(/\s+/).filter(Boolean);
  const stemmedKw = kwTokens.map(stemWord).join(' ');
  const firstKwStem = kwTokens.length ? stemWord(kwTokens[0]) : '';

  const matches = [];
  const seenTimestamps = new Set();

  for (let i = 0; i < transcript.length; i++) {
    const entry = transcript[i];
    if (!entry || !entry.text) continue;

    const normEntry = normalizeText(entry.text);
    const entryTokens = normEntry.split(/\s+/).filter(Boolean);
    const stemmedEntry = entryTokens.map(stemWord).join(' ');

    let matched = false;
    let isExact = false;
    let matchedText = entry.text;
    let endIdx = i;

    // 1. Single-segment exact match
    if (normEntry.includes(normKw)) {
      matched = true;
      isExact = true;
    }
    // 2. Single-segment stemmed match (e.g. neural network vs neural networks)
    else if (stemmedEntry.includes(stemmedKw)) {
      matched = true;
      isExact = false;
    }
    // 3. Sliding window across caption boundaries (up to 2 adjacent segments)
    else if (kwTokens.length > 1 && (normEntry.includes(kwTokens[0]) || stemmedEntry.includes(firstKwStem))) {
      for (let w = 1; w <= 2 && (i + w) < transcript.length; w++) {
        const windowEntries = transcript.slice(i, i + w + 1);
        const combined = windowEntries.map((e) => e.text).join(' ');
        const normCombined = normalizeText(combined);
        const combinedStemmed = normCombined.split(/\s+/).filter(Boolean).map(stemWord).join(' ');

        if (normCombined.includes(normKw)) {
          matched = true;
          isExact = true;
          matchedText = combined;
          endIdx = i + w;
          break;
        } else if (combinedStemmed.includes(stemmedKw)) {
          matched = true;
          isExact = false;
          matchedText = combined;
          endIdx = i + w;
          break;
        }
      }
    }

    if (matched) {
      const timeKey = Math.floor(entry.start);
      if (!seenTimestamps.has(timeKey)) {
        seenTimestamps.add(timeKey);
        const prev = i > 0 ? transcript[i - 1].text : '';
        const next = endIdx < transcript.length - 1 ? transcript[endIdx + 1].text : '';
        const contextText = [prev, matchedText, next].filter(Boolean).join(' ').trim();

        matches.push({
          text: matchedText,
          contextText,
          timestamp: entry.start,
          start: entry.start,
          isExact,
        });
      }
      i = endIdx; // Advance outer loop past the matched window
    }
  }

  return matches;
};

/**
 * Search for keyword(s) in the transcript with support for multi-term queries.
 *
 * @param {Array} transcript - Array of { text, start, duration }
 * @param {string} keyword - Keyword, phrase, or compound query (e.g. "linear regression and logistic regression")
 * @returns {Array} - Matching moments with text, context, timestamp, isExact
 */
export const searchKeywordInTranscript = (transcript, keyword) => {
  if (!transcript || !Array.isArray(transcript) || transcript.length === 0) return [];
  if (!keyword || !keyword.trim()) return [];

  const searchTerms = extractSearchTerms(keyword);
  if (searchTerms.length <= 1) {
    return searchSingleKeywordInTranscript(transcript, keyword);
  }

  // Multi-term / compound query:
  const matchesMap = new Map();

  for (let idx = 0; idx < searchTerms.length; idx++) {
    const term = searchTerms[idx];
    const subMatches = searchSingleKeywordInTranscript(transcript, term);
    for (const m of subMatches) {
      const key = Math.floor(m.timestamp);
      if (!matchesMap.has(key)) {
        matchesMap.set(key, m);
      } else if (m.isExact && !matchesMap.get(key).isExact) {
        matchesMap.set(key, m);
      }
    }
  }

  const sortedMatches = Array.from(matchesMap.values()).sort((a, b) => a.timestamp - b.timestamp);
  const deduplicated = [];
  for (const match of sortedMatches) {
    if (deduplicated.length === 0) {
      deduplicated.push(match);
      continue;
    }
    const last = deduplicated[deduplicated.length - 1];
    if (Math.abs(match.timestamp - last.timestamp) < 3.5) {
      if (match.isExact && !last.isExact) {
        deduplicated[deduplicated.length - 1] = match;
      }
      continue;
    }
    deduplicated.push(match);
  }

  return deduplicated;
};
