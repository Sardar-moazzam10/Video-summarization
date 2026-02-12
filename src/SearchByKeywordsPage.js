import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { fetchVideos } from './youtubeApi.js';
import { fetchTranscript, searchKeywordInTranscript } from './youtubeTranscript.mjs';

const SearchByKeywordsPage = () => {
  const [keyword, setKeyword] = useState('');
  const [results, setResults] = useState([]);
  const [expandedSummaries, setExpandedSummaries] = useState({});
  const [selectedVideos, setSelectedVideos] = useState([]);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const savedKeyword = sessionStorage.getItem('keyword');
    const savedResults = sessionStorage.getItem('results');
    if (savedKeyword && savedResults) {
      setKeyword(savedKeyword);
      setResults(JSON.parse(savedResults));
    }
  }, []);

  const fetchSummary = async (transcriptText) => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: transcriptText }),
      });
      const data = await response.json();
      return data.summary || 'No summary available.';
    } catch (err) {
      console.error('Summary error:', err);
      return 'Summary generation failed.';
    }
  };

  const handleSearch = async () => {
    if (!keyword.trim()) return;
    setResults([]);
    setSelectedVideos([]);
    setLoading(true);

    try {
      const videos = await fetchVideos(keyword);
      const matches = [];

      for (const video of videos) {
        const transcript = await fetchTranscript(video.id.videoId);
        if (transcript) {
          const keywordMatches = searchKeywordInTranscript(transcript, keyword);
          if (keywordMatches.length > 0) {
            const transcriptText = transcript.map((e) => e.text).join(' ');
            const summary = await fetchSummary(transcriptText);
            matches.push({ video, matches: keywordMatches, summary, transcript });
          }
        }
      }

      setResults(matches);
      sessionStorage.setItem('keyword', keyword);
      sessionStorage.setItem('results', JSON.stringify(matches));

      const username = JSON.parse(localStorage.getItem('user'))?.username;
      if (username) {
        await fetch('http://localhost:8000/api/v1/auth/user-history', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username,
            type: 'search',
            query: keyword,
            timestamp: new Date().toISOString(),
          }),
        });
      }
    } catch (err) {
      console.error('Search error:', err);
    } finally {
      setLoading(false);
    }
  };

  const toggleSelect = (videoId) => {
    setSelectedVideos((prev) =>
      prev.includes(videoId) ? prev.filter((id) => id !== videoId) : [...prev, videoId]
    );
  };

  const toggleSummary = (index) => {
    setExpandedSummaries((prev) => ({ ...prev, [index]: !prev[index] }));
  };

  const handleOpenMergePreview = () => {
    const selectedResults = results.filter((r) => selectedVideos.includes(r.video.id.videoId));
    if (selectedResults.length < 2) {
      alert('Please select at least 2 videos to merge.');
      return;
    }
    try {
      sessionStorage.setItem('mergePreviewSelectedResults', JSON.stringify(selectedResults));
    } catch (e) {
      console.warn('Could not persist merge preview selection:', e);
    }
    navigate('/merge-preview', { state: { selectedResults } });
  };

  const handleSummarize = () => {
    if (results.length < 3) return alert('At least 3 results are needed to summarize!');
    const topThree = results.slice(0, 3).map((r) => ({
      videoId: r.video.id.videoId,
      timestamps: r.matches.slice(0, 5).map((m) => Math.floor(m.timestamp)),
    }));
    navigate('/summarized-player', { state: { videoData: topThree } });
  };

  return (
    <div style={styles.page}>
      <div style={styles.bgGrid} />
      <div style={styles.bgGlow} />

      <div style={styles.container}>
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          style={styles.header}
        >
          <div style={styles.iconWrap}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#478BE0" strokeWidth="2">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
          </div>
          <h1 style={styles.title}>Search by Keywords</h1>
          <p style={styles.subtitle}>Find videos by searching inside their transcripts</p>
        </motion.div>

        {/* Search bar */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          style={styles.searchCard}
        >
          <div style={styles.inputRow}>
            <div style={styles.inputWrap}>
              <svg style={styles.inputIcon} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <input
                type="text"
                placeholder="Enter keyword to search transcripts..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                style={styles.input}
              />
            </div>
            <button onClick={handleSearch} style={styles.searchBtn} disabled={loading}>
              {loading ? <span style={styles.spinner} /> : 'Search'}
            </button>
          </div>
        </motion.div>

        {/* Loading */}
        {loading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            style={styles.loadingWrap}
          >
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
              style={styles.loadingSpinner}
            />
            <span style={styles.loadingText}>Searching transcripts... this may take a moment</span>
          </motion.div>
        )}

        {/* Results */}
        {results.map((result, index) => {
          const videoId = result.video.id.videoId;
          return (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.1 + index * 0.06 }}
              style={styles.resultCard}
            >
              <h3 style={styles.resultTitle}>{result.video.snippet.title}</h3>
              <div style={styles.resultBody}>
                <img
                  src={result.video.snippet.thumbnails.medium.url}
                  alt="thumb"
                  style={styles.thumbnail}
                />
                <div style={styles.matchesList}>
                  {result.matches.slice(0, 5).map((m, i) => (
                    <a
                      key={i}
                      href={`https://www.youtube.com/watch?v=${videoId}&t=${Math.floor(m.timestamp)}s`}
                      target="_blank"
                      rel="noreferrer"
                      style={styles.matchLink}
                      onClick={() => {
                        const username = JSON.parse(localStorage.getItem('user'))?.username;
                        if (username) {
                          fetch('http://localhost:8000/api/v1/auth/user-history', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                              username,
                              type: 'watch',
                              videoId,
                              title: result.video.snippet.title,
                              timestamp: new Date().toISOString(),
                            }),
                          });
                        }
                      }}
                    >
                      <span style={styles.matchTime}>
                        {new Date(m.timestamp * 1000).toISOString().substr(11, 8)}
                      </span>
                      <span style={styles.matchText}>{m.text}</span>
                    </a>
                  ))}
                </div>
              </div>

              {/* Actions */}
              <div style={styles.resultActions}>
                <label style={styles.mergeLabel}>
                  <input
                    type="checkbox"
                    checked={selectedVideos.includes(videoId)}
                    onChange={() => toggleSelect(videoId)}
                    style={styles.checkbox}
                  />
                  Add to merge
                </label>
                <button onClick={() => toggleSummary(index)} style={styles.summaryBtn}>
                  {expandedSummaries[index] ? 'Hide Summary' : 'Show Summary'}
                  <svg
                    width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                    style={{ transform: expandedSummaries[index] ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}
                  >
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </button>
              </div>

              {/* Summary */}
              {expandedSummaries[index] && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  style={styles.summaryWrap}
                >
                  <p style={styles.summaryText}>{result.summary}</p>
                </motion.div>
              )}
            </motion.div>
          );
        })}

        {/* Bottom actions */}
        {results.length >= 3 && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            style={styles.bottomBar}
          >
            <button onClick={handleSummarize} style={styles.primaryBtn}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="5 3 19 12 5 21 5 3" fill="rgba(255,255,255,0.2)"/>
              </svg>
              Best Moments
            </button>
          </motion.div>
        )}

        {selectedVideos.length >= 2 && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            style={styles.bottomBar}
          >
            <button onClick={handleOpenMergePreview} style={styles.mergeBtn}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/>
              </svg>
              Preview & Merge ({selectedVideos.length} videos)
            </button>
          </motion.div>
        )}

        {/* Empty state */}
        {!loading && results.length === 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            style={styles.emptyState}
          >
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="rgba(71,139,224,0.25)" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            <p style={styles.emptyText}>Search for a keyword to find matching video transcripts</p>
          </motion.div>
        )}
      </div>
    </div>
  );
};

const styles = {
  page: {
    background: '#000212',
    minHeight: '100vh',
    position: 'relative',
    overflow: 'hidden',
  },
  bgGrid: {
    position: 'absolute',
    inset: 0,
    backgroundImage: 'linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)',
    backgroundSize: '60px 60px',
    mask: 'radial-gradient(ellipse at 50% 0%, black 0%, transparent 70%)',
    WebkitMask: 'radial-gradient(ellipse at 50% 0%, black 0%, transparent 70%)',
    pointerEvents: 'none',
  },
  bgGlow: {
    position: 'absolute',
    top: '-20%',
    left: '50%',
    transform: 'translateX(-50%)',
    width: '800px',
    height: '400px',
    background: 'radial-gradient(ellipse, rgba(71,139,224,0.08) 0%, transparent 70%)',
    pointerEvents: 'none',
  },
  container: {
    position: 'relative',
    zIndex: 1,
    maxWidth: '900px',
    margin: '0 auto',
    padding: '100px 20px 60px',
  },
  header: {
    textAlign: 'center',
    marginBottom: '32px',
  },
  iconWrap: {
    width: '56px',
    height: '56px',
    borderRadius: '16px',
    background: 'rgba(71,139,224,0.1)',
    border: '1px solid rgba(71,139,224,0.15)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    margin: '0 auto 16px',
  },
  title: {
    fontSize: '32px',
    fontWeight: 700,
    color: '#fff',
    margin: '0 0 8px',
    letterSpacing: '-0.02em',
  },
  subtitle: {
    fontSize: '15px',
    color: 'rgba(255,255,255,0.45)',
    margin: 0,
  },
  searchCard: {
    background: 'rgba(17,24,39,0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '20px',
    marginBottom: '24px',
  },
  inputRow: {
    display: 'flex',
    gap: '12px',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  inputWrap: {
    flex: 1,
    minWidth: '250px',
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
  },
  inputIcon: {
    position: 'absolute',
    left: '14px',
    color: 'rgba(255,255,255,0.3)',
    pointerEvents: 'none',
  },
  input: {
    width: '100%',
    padding: '12px 14px 12px 42px',
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '12px',
    color: '#fff',
    fontSize: '14px',
    outline: 'none',
    fontFamily: 'inherit',
    transition: 'border-color 0.2s',
    boxSizing: 'border-box',
  },
  searchBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '12px 28px',
    background: 'linear-gradient(135deg, #478BE0, #2F61A0)',
    color: '#fff',
    border: 'none',
    borderRadius: '12px',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
    whiteSpace: 'nowrap',
    boxShadow: '0 2px 10px rgba(71,139,224,0.25)',
    transition: 'all 0.2s',
  },
  spinner: {
    display: 'inline-block',
    width: '18px',
    height: '18px',
    border: '2px solid rgba(255,255,255,0.3)',
    borderTopColor: '#fff',
    borderRadius: '50%',
    animation: 'spin 0.6s linear infinite',
  },
  loadingWrap: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '12px',
    padding: '32px',
  },
  loadingSpinner: {
    width: '20px',
    height: '20px',
    border: '2px solid rgba(71,139,224,0.2)',
    borderTopColor: '#478BE0',
    borderRadius: '50%',
  },
  loadingText: {
    color: 'rgba(255,255,255,0.45)',
    fontSize: '14px',
  },
  resultCard: {
    background: 'rgba(17,24,39,0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '20px',
    marginBottom: '16px',
    transition: 'border-color 0.2s',
  },
  resultTitle: {
    fontSize: '16px',
    fontWeight: 600,
    color: '#fff',
    margin: '0 0 16px',
    lineHeight: 1.4,
  },
  resultBody: {
    display: 'flex',
    gap: '16px',
  },
  thumbnail: {
    width: '220px',
    height: '140px',
    objectFit: 'cover',
    borderRadius: '10px',
    flexShrink: 0,
  },
  matchesList: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
    maxHeight: '160px',
    overflowY: 'auto',
    paddingRight: '4px',
  },
  matchLink: {
    display: 'flex',
    gap: '10px',
    padding: '8px 10px',
    borderRadius: '8px',
    background: 'rgba(255,255,255,0.03)',
    textDecoration: 'none',
    transition: 'background 0.15s',
    alignItems: 'flex-start',
  },
  matchTime: {
    fontSize: '12px',
    fontWeight: 600,
    color: '#478BE0',
    fontFamily: 'monospace',
    whiteSpace: 'nowrap',
    minWidth: '65px',
    paddingTop: '1px',
  },
  matchText: {
    fontSize: '13px',
    color: 'rgba(255,255,255,0.6)',
    lineHeight: 1.4,
  },
  resultActions: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    marginTop: '14px',
    paddingTop: '14px',
    borderTop: '1px solid rgba(255,255,255,0.05)',
  },
  mergeLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    fontSize: '12.5px',
    color: 'rgba(255,255,255,0.5)',
    cursor: 'pointer',
  },
  checkbox: {
    width: '16px',
    height: '16px',
    accentColor: '#478BE0',
  },
  summaryBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '6px 14px',
    background: 'rgba(255,255,255,0.05)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '8px',
    color: 'rgba(255,255,255,0.6)',
    fontSize: '12.5px',
    fontWeight: 500,
    cursor: 'pointer',
    fontFamily: 'inherit',
    transition: 'all 0.2s',
  },
  summaryWrap: {
    marginTop: '12px',
    padding: '14px 16px',
    background: 'rgba(71,139,224,0.05)',
    border: '1px solid rgba(71,139,224,0.1)',
    borderRadius: '10px',
  },
  summaryText: {
    fontSize: '13.5px',
    lineHeight: 1.6,
    color: 'rgba(255,255,255,0.6)',
    margin: 0,
    fontStyle: 'italic',
  },
  bottomBar: {
    display: 'flex',
    justifyContent: 'center',
    marginTop: '8px',
    marginBottom: '8px',
  },
  primaryBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '13px 28px',
    background: 'linear-gradient(135deg, #478BE0, #2F61A0)',
    color: '#fff',
    border: 'none',
    borderRadius: '12px',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
    boxShadow: '0 2px 12px rgba(71,139,224,0.3)',
    transition: 'all 0.2s',
  },
  mergeBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '13px 28px',
    background: 'rgba(71,139,224,0.12)',
    border: '1px solid rgba(71,139,224,0.2)',
    color: '#478BE0',
    borderRadius: '12px',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
    transition: 'all 0.2s',
  },
  emptyState: {
    textAlign: 'center',
    padding: '60px 20px',
  },
  emptyText: {
    color: 'rgba(255,255,255,0.3)',
    fontSize: '14px',
    marginTop: '16px',
  },
};

export default SearchByKeywordsPage;
