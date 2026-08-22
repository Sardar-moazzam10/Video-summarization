import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { fetchVideos } from './youtubeApi.js';
import VideoList from './VideoList.js';
import MultiSelectBar from './components/merge/MultiSelectBar.jsx';
import './SuggestedPage.css';
import { API_BASE_URL } from './config/api.js';

const suggestedTopics = [
  'Technology', 'Entertainment', 'Health', 'Business', 'Sports',
  'History', 'Education', 'Science', 'Politics', 'Music',
  'Gaming', 'Motivation', 'Self-Improvement', 'Marketing', 'Spirituality',
];

const TOPIC_ICONS = {
  Technology: '💻', Entertainment: '🎬', Health: '💪', Business: '📈',
  Sports: '⚽', History: '📜', Education: '🎓', Science: '🔬',
  Politics: '🏛️', Music: '🎵', Gaming: '🎮', Motivation: '🔥',
  'Self-Improvement': '🌱', Marketing: '📢', Spirituality: '✨',
};

const SuggestedPodcastsPage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const token = localStorage.getItem('access_token') || '';

  const [selectedTopic, setSelectedTopic] = useState('');
  const [videos, setVideos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedForMerge, setSelectedForMerge] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [customTopic, setCustomTopic] = useState('');

  const handleTopicClick = useCallback(async (topic) => {
    setSelectedTopic(topic);
    setLoading(true);
    setError('');
    setVideos([]);
    setSelectedForMerge([]);

    try {
      // Preset topic buttons keep the original podcast/long-form behaviour.
      const fetchedVideos = await fetchVideos(topic, { appendPodcast: true, duration: 'long' });
      if (fetchedVideos.length === 0) {
        setError(`No videos found for "${topic}". Try another topic.`);
      }
      setVideos(fetchedVideos);
    } catch {
      setError('Failed to fetch videos. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (location.state?.topic) handleTopicClick(location.state.topic);
  }, [location.state?.topic, handleTopicClick]);

  const handleToggleSelect = (videoId) => {
    setSelectedForMerge((prev) =>
      prev.includes(videoId) ? prev.filter((id) => id !== videoId) : [...prev, videoId]
    );
  };

  const getSelectedVideoObjects = () =>
    videos
      .filter((v) => selectedForMerge.includes(v.id?.videoId || v.id))
      .map((v) => ({
        id: v.id?.videoId || v.id,
        title: v.snippet?.title,
        thumbnail: v.snippet?.thumbnails?.medium?.url || v.snippet?.thumbnails?.default?.url,
      }));

  const handleMerge = async (durationMinutes) => {
    if (selectedForMerge.length < 1) return;
    setIsSubmitting(true);

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/merge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          video_ids: selectedForMerge,
          target_duration_minutes: durationMinutes,
          generate_audio: true,
          generate_video: true,
        }),
      });
      const data = await res.json();
      if (data.job_id) {
        navigate(`/merged-player/${data.job_id}`);
      } else {
        setError(data.detail || 'Server error. Please retry.');
      }
    } catch {
      setError('Connection error. Make sure the backend is running.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRemoveVideo = (videoId) =>
    setSelectedForMerge((prev) => prev.filter((id) => id !== videoId));

  const handleClearSelection = () => setSelectedForMerge([]);

  return (
    <div className="suggested-page">
      <div className="suggested-bg-grid" />
      <div className="suggested-bg-glow" />

      <div className="suggested-container" style={{ paddingBottom: selectedForMerge.length > 0 ? 120 : 60 }}>
        {/* Header */}
        <motion.div className="suggested-header"
          initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
          <div className="suggested-icon-wrap">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#478BE0" strokeWidth="2">
              <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
            </svg>
          </div>
          <h1 className="suggested-title">Discover Videos</h1>
          <p className="suggested-subtitle">Pick a topic → select videos → get an AI-powered summary in minutes</p>

          {/* 3-step flow hint */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 0, marginTop: 18,
            background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)',
            borderRadius: 12, overflow: 'hidden',
          }}>
            {[
              { icon: '🏷️', label: 'Pick topic' },
              { icon: '☑️', label: 'Select videos' },
              { icon: '⚡', label: 'Get AI summary' },
            ].map((s, i) => (
              <React.Fragment key={i}>
                <div style={{ padding: '9px 16px', display: 'flex', alignItems: 'center', gap: 7 }}>
                  <span style={{ fontSize: 15 }}>{s.icon}</span>
                  <span style={{ fontSize: 12, fontWeight: 500, color: 'rgba(255,255,255,0.45)' }}>{s.label}</span>
                </div>
                {i < 2 && <div style={{ width: 1, background: 'rgba(255,255,255,0.07)', alignSelf: 'stretch' }} />}
              </React.Fragment>
            ))}
          </div>
        </motion.div>

        {/* Topic pills with icons */}
        <motion.div className="suggested-topics"
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          {suggestedTopics.map((topic) => (
            <button
              key={topic}
              className={`suggested-topic-btn ${selectedTopic === topic ? 'active' : ''}`}
              onClick={() => handleTopicClick(topic)}
            >
              <span style={{ fontSize: 14, marginRight: 5 }}>{TOPIC_ICONS[topic]}</span>
              {topic}
            </button>
          ))}
        </motion.div>

        {/* Custom topic search */}
        <motion.div
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.18 }}
          style={{ marginBottom: 28 }}
        >
          <div style={{
            display: 'flex', gap: 8, maxWidth: 480, margin: '0 auto',
            padding: '6px 6px 6px 14px',
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 12, transition: 'border-color 0.2s',
          }}>
            <svg style={{ color: 'rgba(255,255,255,0.25)', flexShrink: 0, alignSelf: 'center' }} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
            </svg>
            <input
              type="text"
              placeholder="Search any topic not listed above..."
              value={customTopic}
              onChange={(e) => setCustomTopic(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && customTopic.trim()) {
                  handleTopicClick(customTopic.trim());
                  setCustomTopic('');
                }
              }}
              style={{
                flex: 1, background: 'none', border: 'none', outline: 'none',
                color: '#fff', fontSize: 13.5, fontFamily: 'inherit', minWidth: 0,
              }}
            />
            <button
              onClick={() => {
                if (customTopic.trim()) {
                  handleTopicClick(customTopic.trim());
                  setCustomTopic('');
                }
              }}
              style={{
                padding: '8px 16px', background: 'linear-gradient(135deg, #478BE0, #2F61A0)',
                border: 'none', borderRadius: 8, color: '#fff', fontSize: 13, fontWeight: 600,
                cursor: 'pointer', fontFamily: 'inherit', flexShrink: 0,
              }}
            >
              Search
            </button>
          </div>
        </motion.div>

        {/* Loading */}
        {loading && (
          <div className="suggested-loading">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 0.9, repeat: Infinity, ease: 'linear' }}
              style={{ display: 'inline-block', width: 20, height: 20,
                border: '2px solid rgba(71,139,224,0.2)', borderTopColor: '#478BE0',
                borderRadius: '50%', marginRight: 10, verticalAlign: 'middle' }}
            />
            Loading videos for <strong style={{ color: '#fff' }}>{selectedTopic}</strong>…
          </div>
        )}

        {/* Error */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              style={{
                background: 'rgba(239,68,68,0.08)',
                border: '1px solid rgba(239,68,68,0.2)',
                borderRadius: 12, padding: '12px 16px', margin: '0 0 16px',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
              }}>
              <span style={{ color: '#f87171', fontSize: 13.5 }}>{error}</span>
              <button onClick={() => setError('')}
                style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: 18 }}>
                ×
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Selection info pill */}
        <AnimatePresence>
          {selectedForMerge.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
              style={{
                background: 'linear-gradient(135deg, rgba(71,139,224,0.08), rgba(47,97,160,0.08))',
                border: '1px solid rgba(71,139,224,0.2)',
                borderRadius: 14, padding: '12px 18px',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                marginBottom: 20, gap: 12, flexWrap: 'wrap',
              }}>
              <span style={{ color: '#fff', fontSize: 13.5, fontWeight: 500 }}>
                <span style={{
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  width: 24, height: 24, borderRadius: 6, background: '#478BE0',
                  fontSize: 12, fontWeight: 700, marginRight: 8,
                }}>{selectedForMerge.length}</span>
                {selectedForMerge.length} video{selectedForMerge.length !== 1 ? 's' : ''} selected for summary
              </span>
              <button onClick={handleClearSelection}
                style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: 13, fontFamily: 'inherit' }}>
                Clear all
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Video grid */}
        {!loading && videos.length > 0 && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
              <p style={{ margin: 0, fontSize: 13, color: 'rgba(255,255,255,0.35)', fontWeight: 500 }}>
                {videos.length} videos found for <strong style={{ color: 'rgba(255,255,255,0.6)' }}>{selectedTopic}</strong>
              </p>
              <span style={{
                fontSize: 11.5, color: 'rgba(255,255,255,0.3)', fontWeight: 500,
                padding: '4px 10px', borderRadius: 9999,
                background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)',
              }}>
                Click a card to select · then hit Summarize
              </span>
            </div>
          <VideoList
            videos={videos}
            selectedVideoIds={selectedForMerge}
            onToggleSelectForMerge={handleToggleSelect}
          />
          </>
        )}

        {/* Empty state */}
        {!loading && !selectedTopic && (
          <motion.div className="text-center py-12"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }}>
            <div style={{ fontSize: 44, marginBottom: 14 }}>✨</div>
            <p style={{ color: 'rgba(255,255,255,0.55)', fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
              Pick a topic to get started
            </p>
            <p style={{ color: 'rgba(255,255,255,0.3)', fontSize: 13.5, maxWidth: 360, margin: '0 auto', lineHeight: 1.6 }}>
              Select any category above or type a custom topic — we'll fetch relevant YouTube videos instantly. Select the ones you like and get a single AI-generated summary.
            </p>
          </motion.div>
        )}
      </div>

      {/* Floating MultiSelectBar */}
      <MultiSelectBar
        selectedVideos={getSelectedVideoObjects()}
        onRemove={handleRemoveVideo}
        onClear={handleClearSelection}
        onMerge={handleMerge}
        isLoading={isSubmitting}
      />
    </div>
  );
};

export default SuggestedPodcastsPage;
