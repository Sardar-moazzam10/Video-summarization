// src/pages/SearchPage.js - Modern UI with Multi-Select and Duration Intelligence
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import SearchBar from './SearchBar.js';
import VideoList from './VideoList.js';
import { fetchVideos } from './youtubeApi.js';
import MultiSelectBar from './components/merge/MultiSelectBar.jsx';
import './Background.css';

const SearchPage = () => {
  const [videos, setVideos] = useState([]);
  const [noResults, setNoResults] = useState(false);
  const [selectedForMerge, setSelectedForMerge] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();

  const username = JSON.parse(localStorage.getItem('user'))?.username;

  useEffect(() => {
    const storedVideos = JSON.parse(localStorage.getItem('searchedVideos'));
    if (storedVideos) {
      setVideos(storedVideos);
    }
  }, []);

  const handleSearch = async (query) => {
    setSelectedForMerge([]);
    setIsLoading(true);

    try {
      const fetchedVideos = await fetchVideos(query);
      setVideos(fetchedVideos);
      localStorage.setItem('searchedVideos', JSON.stringify(fetchedVideos));
      setNoResults(fetchedVideos.length === 0);

      // Save search query to MongoDB
      if (username && query) {
        try {
          await fetch('http://localhost:8000/api/v1/auth/user-history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              username,
              type: 'search',
              query,
              timestamp: new Date().toISOString(),
            }),
          });
        } catch (error) {
          console.warn('Failed to save search history:', error.message);
        }
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleSelectForMerge = (videoId) => {
    setSelectedForMerge((prev) =>
      prev.includes(videoId)
        ? prev.filter((id) => id !== videoId)
        : [...prev, videoId]
    );
  };

  // Get selected video objects for MultiSelectBar
  const getSelectedVideoObjects = () => {
    return videos
      .filter((video) => selectedForMerge.includes(video.id?.videoId))
      .map((video) => ({
        id: video.id?.videoId,
        title: video.snippet?.title,
        thumbnail: video.snippet?.thumbnails?.medium?.url || video.snippet?.thumbnails?.default?.url,
      }));
  };

  const handleMerge = async (durationMinutes) => {
    if (selectedForMerge.length < 1) {
      alert('Please select at least 1 video to summarize.');
      return;
    }

    setIsLoading(true);

    try {
      const res = await fetch('http://localhost:8000/api/v1/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_ids: selectedForMerge,
          target_duration_minutes: durationMinutes,
          generate_audio: true,
        }),
      });
      const data = await res.json();
      if (data.job_id) {
        navigate(`/merged-player/${data.job_id}`);
      } else {
        alert(data.detail || 'Server error during merge.');
      }
    } catch (error) {
      console.error('Merge error:', error);
      alert('Server error during merge.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRemoveVideo = (videoId) => {
    setSelectedForMerge((prev) => prev.filter((id) => id !== videoId));
  };

  const handleClearSelection = () => {
    setSelectedForMerge([]);
  };

  return (
    <div className="min-h-screen text-white" style={{ background: '#000212' }}>
      {/* Header Section */}
      <motion.div
        className="pt-20 pb-10 px-4"
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
      >
        <div className="max-w-4xl mx-auto text-center">
          <motion.h1
            className="text-4xl md:text-5xl font-bold bg-gradient-to-r from-blue-400 via-blue-300 to-blue-500 bg-clip-text text-transparent mb-4"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.2 }}
          >
            AI Video Summarizer
          </motion.h1>
          <motion.p
            className="text-dark-300 text-lg max-w-2xl mx-auto"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.4 }}
          >
            Search YouTube videos, select multiple sources, and get an AI-powered
            unified summary with intelligent fusion technology.
          </motion.p>
        </div>
      </motion.div>

      {/* Search Section */}
      <motion.div
        className="px-4 pb-8"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <div className="max-w-2xl mx-auto">
          <SearchBar onSearch={handleSearch} />
        </div>
      </motion.div>

      {/* Results Section */}
      <div className="px-4 pb-32">
        {isLoading && !videos.length ? (
          <div className="flex justify-center py-20">
            <motion.div
              className="w-12 h-12 border-4 border-primary-500/30 border-t-primary-500 rounded-full"
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
            />
          </div>
        ) : noResults ? (
          <motion.div
            className="text-center py-20"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
          >
            <div className="text-6xl mb-4">🔍</div>
            <h2 className="text-2xl font-bold text-dark-200 mb-2">No Videos Found</h2>
            <p className="text-dark-400">Try different keywords or explore other topics!</p>
          </motion.div>
        ) : videos.length > 0 ? (
          <>
            {/* Selection Info */}
            {selectedForMerge.length > 0 && (
              <motion.div
                className="max-w-6xl mx-auto mb-6 px-4"
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <div className="bg-gradient-to-r from-accent-500/10 to-primary-500/10 border border-accent-500/30 rounded-xl p-4 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-2xl">✨</span>
                    <div>
                      <p className="font-semibold text-white">
                        {selectedForMerge.length} video{selectedForMerge.length > 1 ? 's' : ''} selected
                      </p>
                      <p className="text-sm text-dark-400">
                        Click videos to add/remove from selection
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={handleClearSelection}
                    className="text-dark-400 hover:text-white transition-colors"
                  >
                    Clear all
                  </button>
                </div>
              </motion.div>
            )}

            {/* Video Grid */}
            <VideoList
              videos={videos}
              selectedVideoIds={selectedForMerge}
              onToggleSelectForMerge={handleToggleSelectForMerge}
            />
          </>
        ) : null}
      </div>

      {/* Multi-Select Bar */}
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
