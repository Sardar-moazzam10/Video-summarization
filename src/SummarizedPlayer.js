import React, { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import YouTube from 'react-youtube';
import './SummarizedPlayer.css'; // 👉 We’ll create this new CSS file

const SummarizedPlayer = () => {
  const location = useLocation();
  const { videoData } = location.state || {};
  const [currentVideoIndex, setCurrentVideoIndex] = useState(0);
  const [player, setPlayer] = useState(null);

  if (!videoData || videoData.length === 0) {
    return <h2>No videos to summarize</h2>;
  }

  const handleReady = (event) => {
    setPlayer(event.target);
  };

  const jumpToTimestamp = (timestamp) => {
    if (player) {
      player.seekTo(timestamp, true);
    }
  };

  return (
    <div className="summary-wrapper">
      <h1 className="summary-title">Best Podcast Moments 🎬</h1>
      <YouTube
        videoId={videoData[currentVideoIndex].videoId}
        opts={{ width: '800', height: '450', playerVars: { autoplay: 1 } }}
        onReady={handleReady}
      />
      <div className="video-switch-buttons">
        {videoData.map((_, index) => (
          <button
            key={index}
            className={`video-btn ${index === currentVideoIndex ? 'active' : ''}`}
            onClick={() => setCurrentVideoIndex(index)}
          >
            🎥 Video {index + 1}
          </button>
        ))}
      </div>

      <h3 className="moment-title">Jump to Best Moments:</h3>
      <div className="timestamp-buttons">
        {videoData[currentVideoIndex].timestamps.map((timestamp, i) => (
          <button
            key={i}
            onClick={() => jumpToTimestamp(timestamp)}
            className="timestamp-btn"
          >
            {new Date(timestamp * 1000).toISOString().substr(11, 8)}
          </button>
        ))}
      </div>
    </div>
  );
};

export default SummarizedPlayer;
