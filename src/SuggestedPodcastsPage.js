import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
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
  const [selectedForMerge, setSelectedForMerge] = useState([]);
  const [mergeDuration, setMergeDuration] = useState('300');

  useEffect(() => {
    if (location.state?.topic) {
      handleTopicClick(location.state.topic);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state?.topic]);

  const handleTopicClick = async (topic) => {
    setSelectedTopic(topic);
    setLoading(true);
    setError('');
    setVideos([]);
    setSelectedForMerge([]);

    try {
      const fetchedVideos = await fetchVideos(topic);
      setVideos(fetchedVideos.length > 0 ? fetchedVideos : []);
      if (fetchedVideos.length === 0) {
        setError(`No videos found for "${topic}". Try another topic!`);
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
      const res = await fetch('http://localhost:8000/api/v1/merge', {
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
    <div className="suggested-page">
      <div className="suggested-bg-grid" />
      <div className="suggested-bg-glow" />

      <div className="suggested-container">
        {/* Header */}
        <motion.div
          className="suggested-header"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <div className="suggested-icon-wrap">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#478BE0" strokeWidth="2">
              <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
            </svg>
          </div>
          <h1 className="suggested-title">Discover Videos</h1>
          <p className="suggested-subtitle">Click a topic below to explore relevant videos</p>
        </motion.div>

        {/* Topic pills */}
        <motion.div
          className="suggested-topics"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1 }}
        >
          {suggestedTopics.map((topic, index) => (
            <button
              key={index}
              className={`suggested-topic-btn ${selectedTopic === topic ? 'active' : ''}`}
              onClick={() => handleTopicClick(topic)}
            >
              {topic}
            </button>
          ))}
        </motion.div>

        {/* Loading */}
        {loading && (
          <div className="suggested-loading">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
              style={{
                display: 'inline-block',
                width: 20,
                height: 20,
                border: '2px solid rgba(71,139,224,0.2)',
                borderTopColor: '#478BE0',
                borderRadius: '50%',
                marginRight: 10,
                verticalAlign: 'middle',
              }}
            />
            Loading videos...
          </div>
        )}

        {/* Error */}
        {error && <p className="suggested-error">{error}</p>}

        {/* Video grid */}
        {videos.length > 0 && (
          <div className="suggested-grid">
            {videos.map((video, index) => {
              const videoId = video.id?.videoId || video.id;
              return (
                <motion.div
                  key={index}
                  className="suggested-card"
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: 0.1 + index * 0.04 }}
                >
                  <div className="suggested-card-thumb">
                    <img
                      src={video.snippet.thumbnails.medium.url}
                      alt={video.snippet.title}
                    />
                  </div>
                  <div className="suggested-card-body">
                    <h3 className="suggested-card-title">{video.snippet.title}</h3>
                    <p className="suggested-card-desc">
                      {video.snippet.description.substring(0, 100)}...
                    </p>
                    <label className="suggested-merge-label">
                      <input
                        type="checkbox"
                        checked={selectedForMerge.includes(videoId)}
                        onChange={() => handleToggleSelectForMerge(videoId)}
                      />
                      Select for merge
                    </label>
                    <div className="suggested-card-btns">
                      <button
                        className="suggested-btn-watch"
                        onClick={() => handleWatchHere(video)}
                      >
                        Watch Here
                      </button>
                      <a
                        href={`https://www.youtube.com/watch?v=${video.id.videoId}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="suggested-btn-yt"
                      >
                        YouTube
                      </a>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}

        {/* Merge bar */}
        {videos.length > 0 && (
          <motion.div
            className="suggested-merge-bar"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.4 }}
          >
            <span className="suggested-merge-text">
              {selectedForMerge.length} selected &mdash; Choose output length:
            </span>
            <select
              className="suggested-merge-select"
              value={mergeDuration}
              onChange={(e) => setMergeDuration(e.target.value)}
            >
              <option value="300">5 minutes</option>
              <option value="600">10 minutes</option>
              <option value="900">15 minutes</option>
            </select>
            <button
              className="suggested-merge-btn"
              onClick={handleMergeSelected}
              disabled={selectedForMerge.length < 2}
              style={{ opacity: selectedForMerge.length < 2 ? 0.5 : 1 }}
            >
              Merge Selected
            </button>
          </motion.div>
        )}
      </div>
    </div>
  );
};

export default SuggestedPage;
