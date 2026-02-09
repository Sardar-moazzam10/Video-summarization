import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { fetchVideos } from './youtubeApi.js';
import './SuggestedPage.css';

const suggestedTopics = [
  'Technology', 'Entertainment', 'Health', 'Business', 'Sports',
  'History', 'Education', 'Science', 'Politics', 'Music',
  'Gaming', 'Motivation', 'Self-Improvement', 'Marketing', 'Spirituality'
];

const SuggestedPage = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const [selectedTopic, setSelectedTopic] = useState('');
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [animate, setAnimate] = useState(false);
  const [selectedForMerge, setSelectedForMerge] = useState([]);
  const [mergeDuration, setMergeDuration] = useState('300'); // seconds

  // Handle redirect with topic from another component like Footer
  useEffect(() => {
    if (location.state?.topic) {
      handleTopicClick(location.state.topic);
    }
  }, [location.state?.topic]);

  const handleTopicClick = async (topic) => {
    setSelectedTopic(topic);
    setLoading(true);
    setError('');
    setVideos([]);
    setSelectedForMerge([]);
    setAnimate(false);

    try {
      const fetchedVideos = await fetchVideos(topic);
      setVideos(fetchedVideos.length > 0 ? fetchedVideos : []);
      if (fetchedVideos.length === 0) {
        setError(`No videos found for "${topic}". Try another topic!`);
      } else {
        setTimeout(() => setAnimate(true), 100);
      }
    } catch (err) {
      setError('Failed to fetch videos. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleSelectForMerge = (videoId) => {
    setSelectedForMerge((prev) =>
      prev.includes(videoId) ? prev.filter((id) => id !== videoId) : [...prev, videoId]
    );
  };

  const handleMergeSelected = async () => {
    if (selectedForMerge.length < 2) {
      alert('Please select at least 2 videos to merge.');
      return;
    }

    try {
      const res = await fetch('http://localhost:5002/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          selectedSegments: selectedForMerge.map((id) => ({ videoId: id })),
          targetDuration: parseInt(mergeDuration, 10) || 300,
        }),
      });
      const data = await res.json();
      if (data.mergeId) {
        navigate(`/merged-player/${data.mergeId}`);
      } else {
        alert('Server error during merge.');
      }
    } catch (err) {
      console.error('Merge failed:', err);
      alert('Server error during merge.');
    }
  };

  const handleWatchHere = (video) => {
    navigate('/video-player', { state: { video, videosList: videos } });
  };

  return (
    <div className="suggested-container">
      <br></br>
      <br></br>
      <h1 className="suggested-title">🔥 Discover Suggested Videos</h1>
      <p className="suggested-subtitle">Click a topic below to explore relevant videos.</p>

      <div className="topics-container">
        {suggestedTopics.map((topic, index) => (
          <button
            key={index}
            className={`topic-button ${selectedTopic === topic ? 'active' : ''}`}
            onClick={() => handleTopicClick(topic)}
          >
            {topic}
          </button>
        ))}
      </div>

      {loading && <div className="loading">Loading...</div>}
      {error && <p className="error">{error}</p>}

      <div className={`videos-container ${animate ? 'slide-in' : ''}`}>
        {videos.map((video, index) => {
          const videoId = video.id?.videoId || video.id;
          return (
            <div key={index} className="video-card">
              <img
                src={video.snippet.thumbnails.medium.url}
                alt={video.snippet.title}
                className="video-thumbnail"
              />
              <div className="video-info">
                <h3 className="video-title">{video.snippet.title}</h3>
                <p className="video-description">
                  {video.snippet.description.substring(0, 100)}...
                </p>
                <label style={{ display: 'block', marginTop: '8px', fontSize: '13px', color: '#eee' }}>
                  <input
                    type="checkbox"
                    checked={selectedForMerge.includes(videoId)}
                    onChange={() => handleToggleSelectForMerge(videoId)}
                    style={{ marginRight: '6px' }}
                  />
                  Select for Merge
                </label>
                <div className="button-group">
                  <a
                    href={`https://www.youtube.com/watch?v=${video.id.videoId}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="watch-youtube-button"
                  >
                    Watch on YouTube
                  </a>
                  <button
                    onClick={() => handleWatchHere(video)}
                    className="watch-here-button"
                  >
                    Watch Here
                  </button>
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {videos.length > 0 && (
        <div style={{ marginTop: '20px', textAlign: 'center' }}>
          <span style={{ fontSize: '14px', marginRight: '8px' }}>
            Select at least 2 videos, then choose total output length:
          </span>
          <select
            value={mergeDuration}
            onChange={(e) => setMergeDuration(e.target.value)}
            style={{
              padding: '8px 10px',
              borderRadius: '6px',
              border: '1px solid #555',
              backgroundColor: '#1f1f2e',
              color: '#fff',
              marginRight: '8px',
            }}
          >
            <option value="300">5 minutes total</option>
            <option value="600">10 minutes total</option>
            <option value="900">15 minutes total</option>
          </select>
          <button
            onClick={handleMergeSelected}
            style={{
              padding: '10px 18px',
              backgroundColor: '#28a745',
              border: 'none',
              borderRadius: '6px',
              color: '#fff',
              fontWeight: 'bold',
              cursor: 'pointer',
            }}
          >
            🧩 Merge Selected
          </button>
        </div>
      )}
    </div>
  );
};

export default SuggestedPage;
