// src/pages/SearchPage.js
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import SearchBar from './SearchBar.js';
import VideoList from './VideoList.js';
import { fetchVideos } from './youtubeApi.js';
import './Background.css';

const SearchPage = () => {
  const [videos, setVideos] = useState([]);
  const [noResults, setNoResults] = useState(false);
  const [selectedForMerge, setSelectedForMerge] = useState([]);
  const [mergeDuration, setMergeDuration] = useState('300'); // seconds
  const navigate = useNavigate();

  const username = JSON.parse(localStorage.getItem('user'))?.username;

  useEffect(() => {
    const storedVideos = JSON.parse(localStorage.getItem('searchedVideos'));
    if (storedVideos) {
      setVideos(storedVideos);
    }
  }, []);

  const handleSearch = async (searchQuery) => {
    setSelectedForMerge([]);
    const fetchedVideos = await fetchVideos(searchQuery);
    setVideos(fetchedVideos);
    localStorage.setItem('searchedVideos', JSON.stringify(fetchedVideos));
    setNoResults(fetchedVideos.length === 0);

    // ✅ Save search query to MongoDB
    if (username && searchQuery) {
      try {
        await fetch('http://localhost:5000/api/user-history', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username,
            type: 'search',
            query: searchQuery,
            timestamp: new Date().toISOString(),
          }),
        });
      } catch (error) {
        console.warn('❌ Failed to save search history:', error.message);
      }
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
    } catch (error) {
      console.error('❌ Merge error:', error);
      alert('Server error during merge.');
    }
  };

  return (
    <div style={styles.container}>
      <br></br>
      <br></br>
      <div style={styles.header}>
        <h1 style={styles.title}>🎬 Discover Videos by Title</h1>
        <p style={styles.subtitle}>
          Enter a topic or keyword to explore relevant videos instantly!
        </p>
      </div>
      <SearchBar onSearch={handleSearch} />
      {noResults ? (
        <div style={styles.noResults}>
          <h2>😔 Oops! No Videos Found</h2>
          <p>Try using different keywords or explore other topics!</p>
        </div>
      ) : (
        <>
          <VideoList
            videos={videos}
            selectedVideoIds={selectedForMerge}
            onToggleSelectForMerge={handleToggleSelectForMerge}
          />
          {videos.length > 0 && (
            <div style={styles.mergeBar}>
              <span style={styles.mergeLabel}>
                Select at least 2 videos, then choose total output length:
              </span>
              <select
                value={mergeDuration}
                onChange={(e) => setMergeDuration(e.target.value)}
                style={styles.select}
              >
                <option value="300">5 minutes total</option>
                <option value="600">10 minutes total</option>
                <option value="900">15 minutes total</option>
              </select>
              <button onClick={handleMergeSelected} style={styles.mergeButton}>
                🧩 Merge & Summarize Selected
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
};

const styles = {
  container: {
    padding: '20px',
    minHeight: '100vh',
    color: '#fff',
  },
  header: {
    textAlign: 'center',
    marginBottom: '20px',
  },
  title: {
    fontSize: '36px',
    fontWeight: 'bold',
    color: '#0EA5E9',
  },
  subtitle: {
    fontSize: '18px',
    marginTop: '10px',
  },
  noResults: {
    textAlign: 'center',
    marginTop: '50px',
    color: '#ccc',
  },
  mergeBar: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '10px',
    marginTop: '20px',
  },
  mergeLabel: {
    fontSize: '14px',
  },
  select: {
    padding: '8px 10px',
    borderRadius: '6px',
    border: '1px solid #555',
    backgroundColor: '#1f1f2e',
    color: '#fff',
  },
  mergeButton: {
    padding: '10px 18px',
    backgroundColor: '#28a745',
    border: 'none',
    borderRadius: '6px',
    color: '#fff',
    fontWeight: 'bold',
    cursor: 'pointer',
  },
};

export default SearchPage;
