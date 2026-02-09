import React, { useState } from 'react';
import { fetchTranscript } from './api.js';

const TranscriptViewer = () => {
  const [videoId, setVideoId] = useState('');
  const [transcript, setTranscript] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleFetchTranscript = async () => {
    setError('');
    setTranscript([]);
    setLoading(true);

    if (!videoId.trim()) {
      setError('Please enter a valid video ID.');
      setLoading(false);
      return;
    }

    try {
      const response = await fetchTranscript(videoId);

      if (Array.isArray(response) && response.length > 0) {
        setTranscript(response);

        // ✅ Get username from localStorage or fallback to 'guest'
        const loggedInUser = localStorage.getItem('username') || 'guest';

        // ✅ Save transcript-view history
        await fetch('http://localhost:5000/api/user-history', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            username: loggedInUser,
            type: 'transcript-view',
            videoId: videoId,
            timestamp: Date.now(),
          }),
        });

      } else {
        setError('No transcript available.');
      }
    } catch (err) {
      console.error("📛 Transcript fetch error:", err);
      setError('Failed to fetch transcript. ' + err.message);
    }

    setLoading(false);
  };

  const copyTranscript = () => {
    const transcriptText = transcript.map(entry => entry.text).join('\n');
    navigator.clipboard.writeText(transcriptText);
    alert('Transcript copied to clipboard!');
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
    <div style={styles.container}>
      <br />
      <br />
      <h1 style={styles.title}>🎙️ Transcript Viewer</h1>

      <div style={styles.inputContainer}>
        <input
          type="text"
          placeholder="Enter YouTube Video ID"
          value={videoId}
          onChange={(e) => setVideoId(e.target.value)}
          style={styles.input}
        />
      </div>

      <div style={styles.fetchButtonWrapper}>
        <button onClick={handleFetchTranscript} style={styles.button}>
          Fetch Transcript
        </button>
      </div>

      {loading && <div style={styles.loading}>⏳ Loading transcript...</div>}

      {error && <p style={styles.error}>{error}</p>}

      {transcript.length > 0 && (
        <div style={styles.transcriptContainer}>
          <div style={styles.buttonGroup}>
            <button onClick={copyTranscript} style={styles.copyButton}>📋 Copy</button>
            <button onClick={downloadTranscript} style={styles.downloadButton}>⬇️ Download</button>
            <button onClick={downloadTranscriptWithTimestamps} style={styles.downloadButton}>🕒 With Timestamps</button>
          </div>
          <div style={styles.transcript}>
            {transcript.map((entry, index) => (
              <p key={index} style={styles.transcriptEntry}>
                <strong>{new Date(entry.start * 1000).toISOString().substr(11, 8)}:</strong> {entry.text}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

const styles = {
  container: {
    background: 'linear-gradient(-45deg, #0a0a23, #1a1a2e, #0a0a23, #1a1a2e)',
    backgroundSize: '400% 400%',
    animation: 'gradient 20s ease infinite',
    color: '#fff',
    minHeight: '100vh',
    padding: '40px 20px',
    textAlign: 'center',
    fontFamily: 'Arial, sans-serif',
  },
  title: {
    fontSize: '32px',
    marginBottom: '30px',
    color: '#8B5DFF',
  },
  inputContainer: {
    display: 'flex',
    justifyContent: 'center',
    gap: '10px',
    marginBottom: '25px',
    flexWrap: 'wrap',
  },
  input: {
    width: '60%',
    maxWidth: '400px',
    padding: '12px',
    borderRadius: '8px',
    border: '1px solid #aaa',
    fontSize: '16px',
    backgroundColor: '#1e1e2e',
    color: '#fff',
  },
  button: {
    padding: '12px 20px',
    backgroundColor: '#8B5DFF',
    color: '#fff',
    border: 'none',
    borderRadius: '8px',
    fontSize: '16px',
    cursor: 'pointer',
    transition: 'background-color 0.3s ease',
  },
  loading: {
    color: '#aaa',
    fontSize: '16px',
    marginTop: '20px',
  },
  error: {
    color: '#FF4C4C',
    marginBottom: '20px',
    fontSize: '16px',
  },
  transcriptContainer: {
    backgroundColor: '#2e2e3f',
    padding: '20px',
    borderRadius: '12px',
    width: '85%',
    maxWidth: '900px',
    margin: '0 auto',
    boxShadow: '0 0 15px rgba(0,0,0,0.3)',
  },
  buttonGroup: {
    display: 'flex',
    justifyContent: 'center',
    gap: '12px',
    marginBottom: '15px',
    flexWrap: 'wrap',
  },
  copyButton: {
    backgroundColor: '#4CAF50',
    padding: '10px 20px',
    border: 'none',
    borderRadius: '8px',
    color: '#fff',
    cursor: 'pointer',
    fontWeight: 'bold',
    transition: 'transform 0.2s',
  },
  downloadButton: {
    backgroundColor: '#FF9800',
    padding: '10px 20px',
    border: 'none',
    borderRadius: '8px',
    color: '#fff',
    cursor: 'pointer',
    fontWeight: 'bold',
    transition: 'transform 0.2s',
  },
  transcript: {
    textAlign: 'left',
    maxHeight: '300px',
    overflowY: 'auto',
    backgroundColor: '#1e1e2e',
    border: '1px solid #555',
    padding: '15px',
    borderRadius: '8px',
  },
  fetchButtonWrapper: {
    marginTop: '10px',
    marginBottom: '30px',
    display: 'flex',
    justifyContent: 'center',
  },
  transcriptEntry: {
    marginBottom: '12px',
    fontSize: '15px',
    color: '#ddd',
  },
};

export default TranscriptViewer;
