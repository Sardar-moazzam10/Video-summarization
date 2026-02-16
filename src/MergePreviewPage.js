import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

const MergePreviewPage = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const fromState = location.state?.selectedResults || [];
  const fromStorage = (() => {
    try {
      const raw = sessionStorage.getItem('mergePreviewSelectedResults');
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  })();

  const initialResults = fromState.length ? fromState : fromStorage;
  const [selectedResults] = useState(initialResults);
  const [targetDuration, setTargetDuration] = useState('300'); // seconds
  const [selectedStyle, setSelectedStyle] = useState('educational');
  const [generateVideo, setGenerateVideo] = useState(true);
  const [highlightDuration, setHighlightDuration] = useState('120');

  const handleBack = () => {
    navigate(-1);
  };

  const handleConfirmMerge = async () => {
    if (!selectedResults || selectedResults.length < 2) {
      alert('Please select at least 2 videos to merge from the search page first.');
      return;
    }

    const selectedSegments = selectedResults
      .map((r) => {
        const videoId = r.video?.id?.videoId;
        if (!videoId || !Array.isArray(r.matches) || r.matches.length === 0) return null;

        const matchTimestamps = r.matches.slice(0, 3).map((m) => Math.floor(m.timestamp));
        if (matchTimestamps.length === 0) return null;

        const start = matchTimestamps[0];
        const end = matchTimestamps[matchTimestamps.length - 1] + 30;
        return { videoId, start, end };
      })
      .filter(Boolean);

    if (selectedSegments.length < 2) {
      alert('Not enough valid segments to merge. Please go back and select other videos.');
      return;
    }

    try {
      const res = await fetch('http://localhost:8000/api/v1/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_ids: selectedSegments.map(s => s.videoId),
          target_duration_minutes: Math.round(parseInt(targetDuration, 10) / 60),
          generate_audio: true,
          style: selectedStyle,
          generate_video: generateVideo,
          highlight_duration_seconds: parseInt(highlightDuration, 10),
        }),
      });
      const data = await res.json();
      if (data.job_id) {
        navigate(`/merged-player/${data.job_id}`);
      } else {
        alert('Server error during merge.');
      }
    } catch (err) {
      console.error('Merge failed:', err);
      alert('Server error during merge.');
    }
  };

  if (!selectedResults || selectedResults.length === 0) {
    return (
      <div style={styles.container}>
        <h2 style={styles.title}>Merge Preview</h2>
        <p style={styles.info}>No videos selected. Go back to the keyword search page and add videos to merge.</p>
        <button onClick={handleBack} style={styles.button}>⬅ Back</button>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <br />
      <h1 style={styles.title}>🧩 Merge Preview – Important Moments</h1>
      <p style={styles.subtitle}>
        Review the highlighted moments and summaries for each selected video before merging them into one combined podcast.
      </p>

      {selectedResults.map((result, index) => {
        const videoId = result.video?.id?.videoId;
        const thumb = result.video?.snippet?.thumbnails?.medium?.url;
        const title = result.video?.snippet?.title;
        const matches = Array.isArray(result.matches) ? result.matches.slice(0, 5) : [];

        return (
          <div key={index} style={styles.card}>
            <h3 style={styles.cardTitle}>{title}</h3>
            <div style={styles.cardContent}>
              <img src={thumb} alt={title} style={styles.thumbnail} />
              <div style={styles.details}>
                <h4 style={styles.sectionTitle}>Top Moments</h4>
                {matches.length === 0 ? (
                  <p style={styles.muted}>No keyword matches found for this video.</p>
                ) : (
                  <ul style={styles.list}>
                    {matches.map((m, i) => (
                      <li key={i} style={styles.listItem}>
                        <span style={styles.timestamp}>
                          {new Date(m.timestamp * 1000).toISOString().substr(11, 8)}
                        </span>
                        <span style={styles.text}>{m.text}</span>
                      </li>
                    ))}
                  </ul>
                )}

                {result.summary && (
                  <>
                    <h4 style={styles.sectionTitle}>AI Summary</h4>
                    <p style={styles.summaryText}>{result.summary}</p>
                  </>
                )}

                {videoId && (
                  <a
                    href={`https://www.youtube.com/watch?v=${videoId}`}
                    target="_blank"
                    rel="noreferrer"
                    style={styles.link}
                  >
                    Watch full episode on YouTube ↗
                  </a>
                )}
              </div>
            </div>
          </div>
        );
      })}

      <div style={styles.actions}>
        <div style={styles.durationSelector}>
          <label style={styles.durationLabel}>Duration:</label>
          <select
            value={targetDuration}
            onChange={(e) => setTargetDuration(e.target.value)}
            style={styles.select}
          >
            <option value="300">5 minutes</option>
            <option value="600">10 minutes</option>
            <option value="900">15 minutes</option>
            <option value="1200">20 minutes</option>
          </select>
        </div>
        <div style={styles.durationSelector}>
          <label style={styles.durationLabel}>Style:</label>
          <select
            value={selectedStyle}
            onChange={(e) => setSelectedStyle(e.target.value)}
            style={styles.select}
          >
            <option value="educational">Educational</option>
            <option value="casual">Casual / Podcast</option>
            <option value="executive">Executive Briefing</option>
            <option value="beginner">Beginner Friendly</option>
            <option value="detailed">Detailed Analysis</option>
          </select>
        </div>
        <div style={styles.videoToggle}>
          <label style={styles.checkboxLabel}>
            <input
              type="checkbox"
              checked={generateVideo}
              onChange={(e) => setGenerateVideo(e.target.checked)}
              style={styles.checkbox}
            />
            Video Highlights
          </label>
          {generateVideo && (
            <select
              value={highlightDuration}
              onChange={(e) => setHighlightDuration(e.target.value)}
              style={styles.select}
            >
              <option value="60">1 min</option>
              <option value="120">2 min</option>
              <option value="180">3 min</option>
              <option value="300">5 min</option>
            </select>
          )}
        </div>
        <button onClick={handleBack} style={{ ...styles.button, backgroundColor: '#444' }}>
          ⬅ Back to Search
        </button>
        <button onClick={handleConfirmMerge} style={{ ...styles.button, backgroundColor: '#28a745' }}>
          {generateVideo ? '🎬 Merge with Video Highlights' : '🎧 Merge & Play Combined Podcast'}
        </button>
      </div>
    </div>
  );
};

const styles = {
  container: {
    padding: '30px 20px',
    minHeight: '100vh',
    background: 'linear-gradient(-45deg, #0a0a23, #1a1a2e)',
    color: '#fff',
    fontFamily: 'Arial, sans-serif',
  },
  title: {
    fontSize: '32px',
    textAlign: 'center',
    color: '#8B5DFF',
    marginBottom: '10px',
  },
  subtitle: {
    textAlign: 'center',
    marginBottom: '30px',
    color: '#ccc',
  },
  info: {
    textAlign: 'center',
    marginBottom: '20px',
  },
  card: {
    backgroundColor: '#2f2f3f',
    borderRadius: '12px',
    padding: '20px',
    maxWidth: '1000px',
    margin: '0 auto 25px auto',
  },
  cardTitle: {
    fontSize: '20px',
    fontWeight: 'bold',
    marginBottom: '12px',
  },
  cardContent: {
    display: 'flex',
    gap: '20px',
    flexWrap: 'wrap',
  },
  thumbnail: {
    width: '280px',
    height: '170px',
    objectFit: 'cover',
    borderRadius: '8px',
  },
  details: {
    flex: 1,
    minWidth: '260px',
  },
  sectionTitle: {
    fontSize: '16px',
    marginBottom: '6px',
    color: '#ffd580',
  },
  muted: {
    color: '#aaa',
    fontStyle: 'italic',
  },
  list: {
    listStyle: 'none',
    padding: 0,
    margin: '0 0 10px 0',
  },
  listItem: {
    marginBottom: '6px',
  },
  timestamp: {
    display: 'inline-block',
    minWidth: '80px',
    fontWeight: 'bold',
    color: '#8B5DFF',
    marginRight: '6px',
  },
  text: {
    color: '#eee',
    fontSize: '14px',
  },
  summaryText: {
    marginTop: '4px',
    marginBottom: '8px',
    color: '#ddd',
    fontSize: '14px',
  },
  link: {
    display: 'inline-block',
    marginTop: '4px',
    fontSize: '13px',
    color: '#8B5DFF',
    textDecoration: 'none',
  },
  actions: {
    marginTop: '30px',
    display: 'flex',
    justifyContent: 'center',
    gap: '12px',
  },
  button: {
    padding: '10px 18px',
    borderRadius: '8px',
    border: 'none',
    cursor: 'pointer',
    color: '#fff',
    fontWeight: 'bold',
  },
  durationSelector: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginRight: '20px',
  },
  durationLabel: {
    fontSize: '14px',
    color: '#ccc',
  },
  select: {
    padding: '8px 12px',
    borderRadius: '6px',
    border: '1px solid #555',
    backgroundColor: '#1f1f2e',
    color: '#fff',
    fontSize: '14px',
  },
  videoToggle: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginRight: '20px',
  },
  checkboxLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    fontSize: '14px',
    color: '#ccc',
    cursor: 'pointer',
  },
  checkbox: {
    width: '16px',
    height: '16px',
    accentColor: '#8B5DFF',
    cursor: 'pointer',
  },
};

export default MergePreviewPage;





