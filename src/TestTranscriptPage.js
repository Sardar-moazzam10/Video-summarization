import React, { useState } from 'react';
import { fetchTranscript } from './youtubeTranscript.mjs'; // Import fetchTranscript function

const TestTranscriptPage = () => {
  const [videoId, setVideoId] = useState('UF8uR6Z6KLc'); // Default Video ID for testing
  const [transcript, setTranscript] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Fetch and display transcript
  const handleFetchTranscript = async () => {
    setError('');
    setLoading(true);
    setTranscript([]);

    try {
      console.log(`Fetching transcript for video ID: ${videoId}`);
      const fetchedTranscript = await fetchTranscript(videoId);
      console.log('Transcript fetched:', fetchedTranscript);

      if (fetchedTranscript) {
        setTranscript(fetchedTranscript); // Update state with transcript
      } else {
        setError('No transcript available for this video.');
      }
    } catch (err) {
      console.error('Error fetching transcript:', err);
      setError('Something went wrong. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.container}>
      <h1 style={styles.title}>Test YouTube Transcript</h1>
      <div style={styles.inputContainer}>
        <input
          type="text"
          placeholder="Enter Video ID"
          value={videoId}
          onChange={(e) => setVideoId(e.target.value)}
          style={styles.input}
        />
        <button onClick={handleFetchTranscript} style={styles.button}>
          Fetch Transcript
        </button>
      </div>
      {loading && <p>Loading...</p>}
      {error && <p style={styles.error}>{error}</p>}
      <div style={styles.transcript}>
        {transcript.map((entry, index) => (
          <div key={index} style={styles.transcriptEntry}>
            <p>
              <strong>{new Date(entry.start * 1000).toISOString().substr(11, 8)}:</strong>{' '}
              {entry.text}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
};

const styles = {
  container: {
    padding: '20px',
    fontFamily: 'Arial, sans-serif',
  },
  title: {
    fontSize: '24px',
    textAlign: 'center',
    marginBottom: '20px',
  },
  inputContainer: {
    display: 'flex',
    justifyContent: 'center',
    marginBottom: '20px',
  },
  input: {
    width: '50%',
    padding: '10px',
    borderRadius: '5px',
    border: '1px solid #ccc',
  },
  button: {
    marginLeft: '10px',
    padding: '10px 20px',
    backgroundColor: '#8B5DFF', // Theme color
    color: '#fff',
    border: 'none',
    borderRadius: '5px',
    cursor: 'pointer',
  },
  error: {
    color: 'red',
    textAlign: 'center',
    marginTop: '10px',
  },
  transcript: {
    marginTop: '20px',
    maxHeight: '400px',
    overflowY: 'auto',
    border: '1px solid #ddd',
    borderRadius: '5px',
    padding: '10px',
  },
  transcriptEntry: {
    marginBottom: '10px',
  },
};

export default TestTranscriptPage;
