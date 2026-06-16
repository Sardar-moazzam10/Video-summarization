import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { API_BASE_URL } from './config/api.js';
import './VideoCard.css';

const VideoCard = ({ video, videosList, isSelected = false, onToggleSelectForMerge }) => {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [imgError, setImgError] = useState(false);
  const username = JSON.parse(localStorage.getItem('user'))?.username;

  const snippet = video?.snippet || {};
  const title = snippet?.title || 'Title Not Available';
  const channelTitle = snippet?.channelTitle || '';
  const description = snippet?.description || '';
  const thumbnailUrl =
    (!imgError && (snippet?.thumbnails?.medium?.url || snippet?.thumbnails?.default?.url)) ||
    `https://img.youtube.com/vi/${video?.id?.videoId || video?.id}/mqdefault.jpg`;
  const videoId = video?.id?.videoId || video?.id;

  const saveToHistory = async (type) => {
    if (!username || !videoId) return;
    try {
      await fetch(`${API_BASE_URL}/api/v1/auth/user-history`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('access_token') || ''}`,
        },
        body: JSON.stringify({ username, type, title, videoId, timestamp: new Date().toISOString() }),
      });
    } catch (_) {}
  };

  const handleWatchHere = async () => {
    setLoading(true);
    await saveToHistory('watch');
    setTimeout(() => navigate('/video-player', { state: { video, videosList } }), 300);
  };

  const handleWatchYouTube = async () => {
    await saveToHistory('watch');
    window.open(`https://www.youtube.com/watch?v=${videoId}`, '_blank');
  };

  const handleSelect = () => {
    if (videoId && onToggleSelectForMerge) onToggleSelectForMerge(videoId);
  };

  return (
    <motion.div
      className={`vc-card ${isSelected ? 'vc-card--selected' : ''}`}
      layout
      whileHover={{ y: -4 }}
      transition={{ duration: 0.2 }}
    >
      {/* Thumbnail */}
      <div className="vc-thumb" onClick={onToggleSelectForMerge ? handleSelect : undefined}
           style={{ cursor: onToggleSelectForMerge ? 'pointer' : 'default' }}>
        <img
          src={thumbnailUrl}
          alt={title}
          className="vc-thumb-img"
          onError={() => setImgError(true)}
        />
        {/* Selection overlay */}
        <AnimatePresence>
          {isSelected && (
            <motion.div
              className="vc-select-overlay"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <div className="vc-check">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12"/>
                </svg>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Play icon on hover */}
        <div className="vc-play-hint">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        </div>
      </div>

      {/* Body */}
      <div className="vc-body">
        <h3 className="vc-title" title={title}>{title}</h3>
        {channelTitle && <p className="vc-channel">{channelTitle}</p>}
        {description && (
          <p className="vc-desc">{description.slice(0, 100)}{description.length > 100 ? '…' : ''}</p>
        )}
      </div>

      {/* Footer */}
      <div className="vc-footer">
        {/* Select toggle */}
        {videoId && onToggleSelectForMerge && (
          <button
            className={`vc-select-btn ${isSelected ? 'vc-select-btn--active' : ''}`}
            onClick={handleSelect}
          >
            {isSelected ? (
              <>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                Selected
              </>
            ) : (
              <>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
                Add to Merge
              </>
            )}
          </button>
        )}

        <div className="vc-actions">
          <button className="vc-btn vc-btn--primary" onClick={handleWatchHere} disabled={loading}>
            {loading ? (
              <span className="vc-spinner" />
            ) : (
              <>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                Watch
              </>
            )}
          </button>
          {videoId && (
            <button className="vc-btn vc-btn--ghost" onClick={handleWatchYouTube} title="Open on YouTube">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                <path d="M23.5 6.19a3.02 3.02 0 0 0-2.12-2.14C19.54 3.5 12 3.5 12 3.5s-7.54 0-9.38.55A3.02 3.02 0 0 0 .5 6.19C0 8.04 0 12 0 12s0 3.96.5 5.81a3.02 3.02 0 0 0 2.12 2.14C4.46 20.5 12 20.5 12 20.5s7.54 0 9.38-.55a3.02 3.02 0 0 0 2.12-2.14C24 15.96 24 12 24 12s0-3.96-.5-5.81zM9.75 15.02V8.98L15.5 12l-5.75 3.02z"/>
              </svg>
              YouTube
            </button>
          )}
        </div>
      </div>
    </motion.div>
  );
};

export default VideoCard;
