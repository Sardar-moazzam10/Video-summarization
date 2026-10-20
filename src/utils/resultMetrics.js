/**
 * Utility functions for formatting result page metrics with robust contract guarantees.
 */

/**
 * Formats compression ratio safely into a percentage or unavailable state.
 *
 * Semantic meaning: summary length as a fraction of the total original source material length.
 * Clamped strictly between 0% and 100% (never >100%, never negative, never NaN).
 *
 * @param {number|null|undefined} compressionRatio - Fraction between 0.0 and 1.0
 * @param {number|null|undefined} totalSourceWords - Total words in the input source material
 * @param {number|null|undefined} outputWords - Words in the generated summary
 * @returns {string} e.g. "10%", "100%", or "—" when unavailable
 */
export const formatCompressionMetric = (compressionRatio, totalSourceWords, outputWords) => {
  if (
    compressionRatio == null ||
    isNaN(Number(compressionRatio)) ||
    totalSourceWords == null ||
    Number(totalSourceWords) <= 0 ||
    outputWords == null ||
    Number(outputWords) <= 0
  ) {
    return '—';
  }

  const raw = Number(compressionRatio);
  const clamped = Math.min(Math.max(raw, 0.0), 1.0);
  return `${(clamped * 100).toFixed(0)}%`;
};

/**
 * Resolves the list of topic strings from either fusion_metadata.topics_found or job concepts.
 *
 * @param {Array|null|undefined} topicsFound - List of topic strings
 * @param {Array|null|undefined} concepts - List of concept objects or strings
 * @returns {Array<string>} Clean deduplicated non-empty topic strings
 */
export const resolveTopicsList = (topicsFound, concepts) => {
  if (Array.isArray(topicsFound) && topicsFound.length > 0) {
    const valid = topicsFound.map((t) => (typeof t === 'string' ? t.trim() : '')).filter(Boolean);
    if (valid.length > 0) return valid;
  }

  if (Array.isArray(concepts) && concepts.length > 0) {
    const valid = concepts
      .map((c) => {
        if (typeof c === 'string') return c.trim();
        if (c && typeof c.name === 'string') return c.name.trim();
        return '';
      })
      .filter(Boolean);
    if (valid.length > 0) {
      return Array.from(new Set(valid));
    }
  }

  return [];
};

/**
 * Formats the topics count for display.
 * Returns the count if meaningful topics are available, or a neutral "—" state instead of misleading 0.
 *
 * @param {Array|null|undefined} topicsFound
 * @param {Array|null|undefined} concepts
 * @returns {string|number} e.g. 10 or "—"
 */
export const formatTopicsCount = (topicsFound, concepts) => {
  const topics = resolveTopicsList(topicsFound, concepts);
  return topics.length > 0 ? topics.length : '—';
};
