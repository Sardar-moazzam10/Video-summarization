import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import SearchBar from './SearchBar.js';
import VideoList from './VideoList.js';
import { fetchVideos } from './youtubeApi.js';
import MultiSelectBar from './components/merge/MultiSelectBar.jsx';
import './Background.css';
import { API_BASE_URL } from './config/api.js';

const EXAMPLE_QUERIES = [
  'Lex Fridman Podcast',
  'Andrew Huberman sleep science',
  'Tim Ferriss productivity',
  'How money works explained',
  'Deep work Cal Newport',
  'Morning routine habits',
];

const SearchPage = () => {
  const [videos, setVideos] = useState([]);
  const [noResults, setNoResults] = useState(false);
  const [selectedForMerge, setSelectedForMerge] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const navigate = useNavigate();

  const username = JSON.parse(localStorage.getItem('user'))?.username;
  const token = localStorage.getItem('access_token') || '';

  useEffect(() => {
    const storedVideos = JSON.parse(localStorage.getItem('searchedVideos'));
    if (storedVideos) setVideos(storedVideos);
  }, []);

  const handleSearch = useCallback(async (query) => {
    setSelectedForMerge([]);
    setErrorMsg('');
    setNoResults(false);
    setIsLoading(true);

    try {
      // Unrestricted search — exactly what the user typed, any duration.
      const fetchedVideos = await fetchVideos(query);
      setVideos(fetchedVideos);
      localStorage.setItem('searchedVideos', JSON.stringify(fetchedVideos));
      setNoResults(fetchedVideos.length === 0);

      if (username && query) {
        fetch(`${API_BASE_URL}/api/v1/auth/user-history`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify({ username, type: 'search', query, timestamp: new Date().toISOString() }),
        }).catch(() => {});
      }
    } catch (e) {
      setErrorMsg('Failed to fetch videos. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, [username, token]);

  const handleToggleSelectForMerge = (videoId) => {
    setSelectedForMerge((prev) =>
      prev.includes(videoId) ? prev.filter((id) => id !== videoId) : [...prev, videoId]
    );
  };

  const getSelectedVideoObjects = () =>
    videos
      .filter((v) => selectedForMerge.includes(v.id?.videoId))
      .map((v) => ({
        id: v.id?.videoId,
        title: v.snippet?.title,
        thumbnail: v.snippet?.thumbnails?.medium?.url || v.snippet?.thumbnails?.default?.url,
      }));

  const handleMerge = async (durationMinutes) => {
    if (selectedForMerge.length < 1) {
      setErrorMsg('Please select at least 1 video to summarize.');
      return;
    }
    setErrorMsg('');
    setIsLoading(true);

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
        setErrorMsg(data.detail || 'Server error during summarization. Please retry.');
      }
    } catch {
      setErrorMsg('Connection error. Make sure the backend is running.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRemoveVideo = (videoId) =>
    setSelectedForMerge((prev) => prev.filter((id) => id !== videoId));

  const handleClearSelection = () => setSelectedForMerge([]);

  return (
    <div className="min-h-screen text-white" style={{ background: '#000212' }}>
      {/* Header */}
      <motion.div className="pt-24 pb-8 px-4"
        initial={{ opacity: 0, y: -20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <div className="max-w-3xl mx-auto text-center">
          <motion.div
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium mb-6"
            style={{ background: 'rgba(71,139,224,0.1)', border: '1px solid rgba(71,139,224,0.2)', color: '#478BE0' }}
            initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.1 }}
          >
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#478BE0', display: 'inline-block' }} />
            AI Video Search
          </motion.div>

          <motion.h1
            className="text-4xl md:text-5xl font-bold mb-3"
            style={{ letterSpacing: '-0.03em' }}
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
          >
            Search &amp; Summarize
          </motion.h1>
          <motion.p
            className="text-lg max-w-xl mx-auto"
            style={{ color: 'rgba(255,255,255,0.4)' }}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.25 }}
          >
            Find YouTube videos, select multiple sources, and get an AI-powered unified summary.
          </motion.p>
        </div>
      </motion.div>

      {/* Search bar + mode tip + example chips */}
      <motion.div className="px-4 pb-8"
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>
        <div className="max-w-2xl mx-auto" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <SearchBar onSearch={handleSearch} />

          {/* Mode distinction tip */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 16px', flexWrap: 'wrap', gap: 8,
            background: 'rgba(71,139,224,0.05)',
            border: '1px solid rgba(71,139,224,0.1)',
            borderRadius: 12,
          }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'rgba(255,255,255,0.45)' }}>
              <span>📌</span>
              <span>Searches YouTube by <strong style={{ color: 'rgba(255,255,255,0.65)', fontWeight: 600 }}>video title or topic</strong> — returns full video list</span>
            </span>
            <button
              onClick={() => navigate('/search-by-keywords')}
              style={{
                background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                fontFamily: 'inherit', fontSize: 12, fontWeight: 600, color: '#478BE0',
                display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap',
              }}
            >
              Search inside transcripts
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
            </button>
          </div>

          {/* Example query chips — visible only before any search */}
          {videos.length === 0 && !isLoading && (
            <div>
              <p style={{ fontSize: 11, color: 'rgba(255,255,255,0.25)', marginBottom: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                Popular searches
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {EXAMPLE_QUERIES.map((q) => (
                  <button
                    key={q}
                    onClick={() => handleSearch(q)}
                    style={{
                      padding: '7px 14px',
                      background: 'rgba(255,255,255,0.03)',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: 9999,
                      color: 'rgba(255,255,255,0.5)',
                      fontSize: 12.5,
                      fontWeight: 500,
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                      transition: 'all 0.2s',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = 'rgba(71,139,224,0.1)';
                      e.currentTarget.style.borderColor = 'rgba(71,139,224,0.25)';
                      e.currentTarget.style.color = '#78b9ff';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = 'rgba(255,255,255,0.03)';
                      e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)';
                      e.currentTarget.style.color = 'rgba(255,255,255,0.5)';
                    }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </motion.div>

      {/* Error banner */}
      <AnimatePresence>
        {errorMsg && (
          <motion.div
            className="max-w-2xl mx-auto px-4 mb-6"
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8 }}
          >
            <div style={{
              background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.2)',
              borderRadius: 12,
              padding: '12px 16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
            }}>
              <span style={{ color: '#f87171', fontSize: 13.5, fontWeight: 500 }}>{errorMsg}</span>
              <button onClick={() => setErrorMsg('')}
                style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: 18, lineHeight: 1 }}>
                ×
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Results */}
      <div className="px-4 pb-36">
        {isLoading && !videos.length ? (
          <div className="flex justify-center py-20">
            <motion.div className="w-10 h-10 rounded-full"
              style={{ border: '3px solid rgba(71,139,224,0.2)', borderTopColor: '#478BE0' }}
              animate={{ rotate: 360 }} transition={{ duration: 0.9, repeat: Infinity, ease: 'linear' }} />
          </div>
        ) : noResults ? (
          <motion.div className="text-center py-20" initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }}>
            <div className="text-6xl mb-4">🔍</div>
            <h2 className="text-2xl font-bold mb-2" style={{ color: 'rgba(255,255,255,0.7)' }}>No Videos Found</h2>
            <p style={{ color: 'rgba(255,255,255,0.35)' }}>Try different keywords or search another topic!</p>
          </motion.div>
        ) : videos.length > 0 ? (
          <>
            {/* Results count */}
            <motion.div className="max-w-6xl mx-auto mb-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <p style={{ fontSize: 12.5, color: 'rgba(255,255,255,0.3)', fontWeight: 500 }}>
                {videos.length} video{videos.length !== 1 ? 's' : ''} found — click to select, then summarize
              </p>
            </motion.div>

            {/* Selection info banner */}
            <AnimatePresence>
              {selectedForMerge.length > 0 && (
                <motion.div
                  className="max-w-6xl mx-auto mb-6"
                  initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
                  <div style={{
                    background: 'linear-gradient(135deg, rgba(71,139,224,0.08), rgba(47,97,160,0.08))',
                    border: '1px solid rgba(71,139,224,0.2)',
                    borderRadius: 14,
                    padding: '14px 18px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: 10,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <div style={{
                        width: 32, height: 32, borderRadius: 8,
                        background: 'linear-gradient(135deg,#478BE0,#2F61A0)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 14, fontWeight: 700, color: '#fff',
                      }}>
                        {selectedForMerge.length}
                      </div>
                      <div>
                        <p style={{ margin: 0, fontWeight: 600, color: '#fff', fontSize: 14 }}>
                          {selectedForMerge.length} video{selectedForMerge.length > 1 ? 's' : ''} selected
                        </p>
                        <p style={{ margin: 0, fontSize: 12, color: 'rgba(255,255,255,0.4)' }}>
                          Click any video card to add or remove
                        </p>
                      </div>
                    </div>
                    <button onClick={handleClearSelection}
                      style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.4)', cursor: 'pointer', fontSize: 13, fontFamily: 'inherit' }}>
                      Clear all
                    </button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <VideoList
              videos={videos}
              selectedVideoIds={selectedForMerge}
              onToggleSelectForMerge={handleToggleSelectForMerge}
            />
          </>
        ) : !isLoading ? (
          <motion.div className="text-center py-16" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.4 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 24, maxWidth: 480, margin: '0 auto' }}>
              {[
                { icon: '🔍', step: '01', title: 'Search a topic or title', desc: 'Type any YouTube video title or subject — e.g. "Andrew Huberman sleep"' },
                { icon: '☑️', step: '02', title: 'Select multiple videos', desc: 'Click any result card to add it to your selection (up to 5 sources)' },
                { icon: '⚡', step: '03', title: 'Generate AI summary', desc: 'Get chapters, key takeaways, and a highlight reel in the original voices' },
              ].map((s, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 16, textAlign: 'left', width: '100%' }}>
                  <div style={{
                    width: 40, height: 40, borderRadius: 12, flexShrink: 0,
                    background: 'rgba(71,139,224,0.08)', border: '1px solid rgba(71,139,224,0.15)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18,
                  }}>
                    {s.icon}
                  </div>
                  <div>
                    <p style={{ margin: '0 0 3px', fontSize: 14, fontWeight: 600, color: 'rgba(255,255,255,0.7)' }}>{s.title}</p>
                    <p style={{ margin: 0, fontSize: 13, color: 'rgba(255,255,255,0.32)', lineHeight: 1.5 }}>{s.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </motion.div>
        ) : null}
      </div>

      <MultiSelectBar
        selectedVideos={getSelectedVideoObjects()}
        onRemove={handleRemoveVideo}
        onClear={handleClearSelection}
        onMerge={handleMerge}
        isLoading={isLoading}
      />
    </div>
  );
};

export default SearchPage;
