import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { fetchTranscript } from './api.js';

const TranscriptViewer = () => {
  const { videoId: urlVideoId } = useParams();
  const [videoId, setVideoId] = useState('');
  const [transcript, setTranscript] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (urlVideoId) {
      const decoded = decodeURIComponent(urlVideoId);
      setVideoId(decoded);
      doFetch(decoded);
    }
  }, [urlVideoId]);

  const doFetch = async (id) => {
    setError('');
    setTranscript([]);
    setLoading(true);

    if (!id.trim()) {
      setError('Please enter a valid video ID.');
      setLoading(false);
      return;
    }

    try {
      const response = await fetchTranscript(id);
      const data = Array.isArray(response) ? response : response?.transcript || [];

      if (Array.isArray(data) && data.length > 0) {
        setTranscript(data);

        const loggedInUser = JSON.parse(localStorage.getItem('user'))?.username;
        if (loggedInUser) {
          await fetch('http://localhost:8000/api/v1/auth/user-history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              username: loggedInUser,
              type: 'transcript-view',
              videoId: id,
              timestamp: new Date().toISOString(),
            }),
          });
        }
      } else {
        setError('No transcript available.');
      }
    } catch (err) {
      console.error("Transcript fetch error:", err);
      setError('Failed to fetch transcript. ' + err.message);
    }

    setLoading(false);
  };

  const handleFetchTranscript = () => doFetch(videoId);

  const copyTranscript = () => {
    const transcriptText = transcript.map(entry => entry.text).join('\n');
    navigator.clipboard.writeText(transcriptText);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const downloadTranscript = () => {
    const transcriptText = transcript.map(entry => entry.text).join('\n');
    const blob = new Blob([transcriptText], { type: 'text/plain' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `transcript_${videoId}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const downloadTranscriptWithTimestamps = () => {
    const transcriptText = transcript
      .map(entry => `${new Date(entry.start * 1000).toISOString().substr(11, 8)} - ${entry.text}`)
      .join('\n');
    const blob = new Blob([transcriptText], { type: 'text/plain' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `transcript_with_timestamps_${videoId}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div style={styles.page}>
      {/* Background effects */}
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
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
              <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
              <line x1="12" y1="19" x2="12" y2="23"/>
              <line x1="8" y1="23" x2="16" y2="23"/>
            </svg>
          </div>
          <h1 style={styles.title}>Transcript Viewer</h1>
          <p style={styles.subtitle}>Extract and download YouTube video transcripts instantly</p>
        </motion.div>

        {/* Search card */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          style={styles.searchCard}
        >
          <div style={styles.inputRow}>
            <div style={styles.inputWrap}>
              <svg style={styles.inputIcon} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              <input
                type="text"
                placeholder="Enter YouTube Video ID or URL"
                value={videoId}
                onChange={(e) => setVideoId(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleFetchTranscript()}
                style={styles.input}
              />
            </div>
            <button onClick={handleFetchTranscript} style={styles.fetchBtn} disabled={loading}>
              {loading ? (
                <span style={styles.spinner} />
              ) : (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                  </svg>
                  Fetch Transcript
                </>
              )}
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
            <div style={styles.loadingDots}>
              {[0, 1, 2].map(i => (
                <motion.div
                  key={i}
                  style={styles.dot}
                  animate={{ y: [0, -8, 0] }}
                  transition={{ duration: 0.6, repeat: Infinity, delay: i * 0.15 }}
                />
              ))}
            </div>
            <span style={styles.loadingText}>Fetching transcript...</span>
          </motion.div>
        )}

        {/* Error */}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            style={styles.errorCard}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            {error}
          </motion.div>
        )}

        {/* Transcript results */}
        {transcript.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            style={styles.resultCard}
          >
            {/* Action bar */}
            <div style={styles.actionBar}>
              <span style={styles.entryCount}>{transcript.length} entries</span>
              <div style={styles.actionBtns}>
                <button onClick={copyTranscript} style={styles.actionBtn}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                  </svg>
                  {copied ? 'Copied!' : 'Copy'}
                </button>
                <button onClick={downloadTranscript} style={styles.actionBtn}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>
                  </svg>
                  Download
                </button>
                <button onClick={downloadTranscriptWithTimestamps} style={styles.actionBtn}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                  </svg>
                  With Timestamps
                </button>
              </div>
            </div>

            {/* Transcript body */}
            <div style={styles.transcriptBody}>
              {transcript.map((entry, index) => (
                <div key={index} style={styles.entry}>
                  <span style={styles.timestamp}>
                    {new Date(entry.start * 1000).toISOString().substr(11, 8)}
                  </span>
                  <span style={styles.entryText}>{entry.text}</span>
                </div>
              ))}
            </div>
          </motion.div>
        )}

        {/* Empty state */}
        {!loading && transcript.length === 0 && !error && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            style={styles.emptyState}
          >
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="rgba(71,139,224,0.3)" strokeWidth="1.5">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
              <polyline points="10 9 9 9 8 9"/>
            </svg>
            <p style={styles.emptyText}>Enter a YouTube video ID to extract its transcript</p>
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
  fetchBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '12px 24px',
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
    padding: '24px',
  },
  loadingDots: {
    display: 'flex',
    gap: '4px',
  },
  dot: {
    width: '6px',
    height: '6px',
    borderRadius: '50%',
    background: '#478BE0',
  },
  loadingText: {
    color: 'rgba(255,255,255,0.45)',
    fontSize: '14px',
  },
  errorCard: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    background: 'rgba(239,68,68,0.08)',
    border: '1px solid rgba(239,68,68,0.15)',
    borderRadius: '12px',
    padding: '14px 18px',
    color: '#ef4444',
    fontSize: '14px',
    marginBottom: '20px',
  },
  resultCard: {
    background: 'rgba(17,24,39,0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    overflow: 'hidden',
  },
  actionBar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '14px 20px',
    borderBottom: '1px solid rgba(255,255,255,0.06)',
    flexWrap: 'wrap',
    gap: '10px',
  },
  entryCount: {
    fontSize: '13px',
    color: 'rgba(255,255,255,0.4)',
    fontWeight: 500,
  },
  actionBtns: {
    display: 'flex',
    gap: '8px',
    flexWrap: 'wrap',
  },
  actionBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '8px 14px',
    background: 'rgba(255,255,255,0.05)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '10px',
    color: 'rgba(255,255,255,0.7)',
    fontSize: '12.5px',
    fontWeight: 500,
    cursor: 'pointer',
    fontFamily: 'inherit',
    transition: 'all 0.2s',
  },
  transcriptBody: {
    maxHeight: '500px',
    overflowY: 'auto',
    padding: '16px 20px',
  },
  entry: {
    display: 'flex',
    gap: '14px',
    padding: '10px 0',
    borderBottom: '1px solid rgba(255,255,255,0.03)',
    alignItems: 'flex-start',
  },
  timestamp: {
    fontSize: '12px',
    fontWeight: 600,
    color: '#478BE0',
    fontFamily: 'monospace',
    whiteSpace: 'nowrap',
    paddingTop: '2px',
    minWidth: '70px',
  },
  entryText: {
    fontSize: '14px',
    color: 'rgba(255,255,255,0.75)',
    lineHeight: 1.6,
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

export default TranscriptViewer;
