// src/components/VideoCard.js
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './VideoCard.css';

const VideoCard = ({ video, videosList, isSelected = false, onToggleSelectForMerge }) => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const username = JSON.parse(localStorage.getItem('user'))?.username;

  const snippet = video?.snippet || {};
  const title = snippet?.title || 'Title Not Available';
  const description = snippet?.description || 'Description Not Available';
  const thumbnailUrl = snippet?.thumbnails?.medium?.url || '/fallback-thumbnail.jpg';
  const videoId = video?.id?.videoId || video?.id;

  const saveToHistory = async (type) => {
    if (!username || !videoId) return;
    try {
      await fetch('http://localhost:5000/api/user-history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          type,
          title,
          videoId,
          timestamp: new Date().toISOString()
        })
      });
    } catch (err) {
      console.error('❌ History save error:', err);
    }
  };

  const handleWatchHere = async () => {
    setLoading(true);
    await saveToHistory('watch-here');
    setTimeout(() => {
      navigate('/video-player', { state: { video, videosList } });
    }, 400);
  };

  const handleWatchYouTube = async () => {
    await saveToHistory('youtube');
    window.open(`https://www.youtube.com/watch?v=${videoId}`, '_blank');
  };

  const handleCheckboxChange = () => {
    if (!videoId || !onToggleSelectForMerge) return;
    onToggleSelectForMerge(videoId);
  };

  return (
    <div className="video-card" style={styles.card}>
      <img src={thumbnailUrl} alt={title} style={styles.thumbnail} />
      <h3 style={styles.title}>{title}</h3>
      <p style={styles.description}>{description}</p>
      <div style={styles.spacer} />
      <div style={styles.buttonGroup}>
        {videoId && (
          <button onClick={handleWatchYouTube} style={{ ...styles.button, ...styles.youtubeButton }}>
            Watch on YouTube
          </button>
        )}
        <button onClick={handleWatchHere} style={styles.button} disabled={loading}>
          {loading ? 'Loading...' : 'Watch Here'}
        </button>
        {videoId && (
          <label style={{ marginTop: '6px', fontSize: '13px', color: '#ddd' }}>
            <input
              type="checkbox"
              checked={isSelected}
              onChange={handleCheckboxChange}
              style={{ marginRight: '6px' }}
            />
            Select for Merge
          </label>
        )}
      </div>
    </div>
  );
};

const styles = {
  card: {
    backgroundColor: '#2f2f3f',
    borderRadius: '10px',
    width: '300px',
    height: '440px',
    padding: '16px',
    color: '#fff',
    boxShadow: '0 4px 10px rgba(0,0,0,0.5)',
    display: 'flex',
    flexDirection: 'column',
  },
  thumbnail: {
    width: '100%',
    height: '170px',
    objectFit: 'cover',
    borderRadius: '6px',
    marginBottom: '10px',
  },
  title: {
    fontSize: '15px',
    fontWeight: '600',
    marginBottom: '6px',
    overflow: 'hidden',
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
  },
  description: {
    fontSize: '13px',
    color: '#ccc',
    overflow: 'hidden',
    display: '-webkit-box',
    WebkitLineClamp: 3,
    WebkitBoxOrient: 'vertical',
  },
  spacer: {
    flexGrow: 1,
  },
  buttonGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  button: {
    backgroundColor: '#8B5DFF',
    color: '#fff',
    padding: '10px',
    borderRadius: '6px',
    border: 'none',
    cursor: 'pointer',
    fontWeight: '600',
  },
  youtubeButton: {
    backgroundColor: '#FF0000',
  },
};

export default VideoCard;
