// 🔁 Same imports as before
import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchVideos } from './youtubeApi.js';
import { fetchTranscript, searchKeywordInTranscript } from './youtubeTranscript.mjs';

const SearchByKeywordsPage = () => {
  const [keyword, setKeyword] = useState('');
  const [results, setResults] = useState([]);
  const [expandedSummaries, setExpandedSummaries] = useState({});
  const [selectedVideos, setSelectedVideos] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    const savedKeyword = sessionStorage.getItem('keyword');
    const savedResults = sessionStorage.getItem('results');
    if (savedKeyword && savedResults) {
      setKeyword(savedKeyword);
      setResults(JSON.parse(savedResults));
    }
  }, []);

  const fetchSummary = async (transcriptText) => {
    try {
      const response = await fetch('http://localhost:5001/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: transcriptText }),
      });
      const data = await response.json();
      return data.summary || 'No summary available.';
    } catch (err) {
      console.error('Summary error:', err);
      return 'Summary generation failed.';
    }
  };

  const handleSearch = async () => {
    if (!keyword.trim()) return;
    setResults([]);
    setSelectedVideos([]);

    try {
      const videos = await fetchVideos(keyword);
      const matches = [];

      for (const video of videos) {
        const transcript = await fetchTranscript(video.id.videoId);
        if (transcript) {
          const keywordMatches = searchKeywordInTranscript(transcript, keyword);
          if (keywordMatches.length > 0) {
            const transcriptText = transcript.map((e) => e.text).join(' ');
            const summary = await fetchSummary(transcriptText);
            matches.push({ video, matches: keywordMatches, summary, transcript });
          }
        }
      }

      setResults(matches);
      sessionStorage.setItem('keyword', keyword);
      sessionStorage.setItem('results', JSON.stringify(matches));

      // ✅ Save to search history
      const username = localStorage.getItem('username');
      if (username) {
        await fetch('http://localhost:5000/api/user-history', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username,
            type: 'search',
            data: keyword,
            timestamp: Date.now(),
          }),
        });
      }
    } catch (err) {
      console.error('Search error:', err);
    }
  };

  const toggleSelect = (videoId) => {
    setSelectedVideos((prev) =>
      prev.includes(videoId) ? prev.filter((id) => id !== videoId) : [...prev, videoId]
    );
  };

  const toggleSummary = (index) => {
    setExpandedSummaries((prev) => ({ ...prev, [index]: !prev[index] }));
  };

  const handleOpenMergePreview = () => {
    const selectedResults = results.filter((r) => selectedVideos.includes(r.video.id.videoId));
    if (selectedResults.length < 2) {
      alert('Please select at least 2 videos to merge.');
      return;
    }

    try {
      sessionStorage.setItem('mergePreviewSelectedResults', JSON.stringify(selectedResults));
    } catch (e) {
      console.warn('Could not persist merge preview selection:', e);
    }

    navigate('/merge-preview', { state: { selectedResults } });
  };

  const handleSummarize = () => {
    if (results.length < 3) return alert('At least 3 results are needed to summarize!');
    const topThree = results.slice(0, 3).map((r) => ({
      videoId: r.video.id.videoId,
      timestamps: r.matches.slice(0, 5).map((m) => Math.floor(m.timestamp)),
    }));
    navigate('/summarized-player', { state: { videoData: topThree } });
  };

  const styles = {
    container: {
      padding: '30px 20px',
      fontFamily: 'Inter, Arial',
      minHeight: '100vh',
      background: 'linear-gradient(-45deg, #0F172A, #1E293B)',
      color: '#F8FAFC',
    },
    title: { fontSize: '36px', textAlign: 'center', color: '#0EA5E9' },
    searchBar: { display: 'flex', justifyContent: 'center', gap: '10px', marginBottom: '30px' },
    input: {
      width: '50%',
      padding: '12px',
      borderRadius: '8px',
      backgroundColor: '#1f1f2e',
      color: '#fff',
    },
    button: {
      padding: '12px 24px',
      background: 'linear-gradient(135deg, #0EA5E9, #0284C7)',
      color: '#fff',
      border: 'none',
      borderRadius: '8px',
      fontWeight: 'bold',
      cursor: 'pointer',
    },
    summarizeButton: {
      display: 'block',
      margin: '30px auto',
      padding: '15px 35px',
      fontSize: '18px',
      backgroundColor: '#FF5733',
      color: '#fff',
      borderRadius: '10px',
      cursor: 'pointer',
    },
    card: {
      backgroundColor: '#1E293B',
      borderRadius: '10px',
      padding: '20px',
      width: '85%',
      maxWidth: '1000px',
      margin: '20px auto',
      border: '1px solid #334155',
    },
    cardTitle: { textAlign: 'center', fontSize: '22px', fontWeight: 'bold' },
    cardContent: { display: 'flex', gap: '20px' },
    thumbnail: {
      width: '30%',
      minWidth: '300px',
      height: '200px',
      objectFit: 'cover',
      borderRadius: '8px',
    },
    transcript: {
      flex: 1,
      backgroundColor: '#1f1f2e',
      padding: '15px',
      borderRadius: '8px',
      maxHeight: '200px',
      overflowY: 'auto',
    },
    link: { color: '#38BDF8', textDecoration: 'none' },
    toggleSummaryBtn: {
      backgroundColor: '#444',
      border: 'none',
      padding: '8px 16px',
      borderRadius: '6px',
      color: '#fff',
      marginTop: '10px',
    },
  };

  return (
    <div style={styles.container}>
      <br />
      <h1 style={styles.title}>🔍 Search Videos by Keywords</h1>
      <div style={styles.searchBar}>
        <input
          type="text"
          placeholder="Enter keyword..."
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          style={styles.input}
        />
        <button onClick={handleSearch} style={styles.button}>
          Search
        </button>
      </div>
      {results.map((result, index) => {
        const videoId = result.video.id.videoId;
        return (
          <div key={index} style={styles.card}>
            <h3 style={styles.cardTitle}>{result.video.snippet.title}</h3>
            <div style={styles.cardContent}>
              <img src={result.video.snippet.thumbnails.medium.url} style={styles.thumbnail} alt="thumb" />
              <div style={styles.transcript}>
                <ul>
                  {result.matches.slice(0, 5).map((m, i) => (
                    <li key={i}>
                      <a
                        href={`https://www.youtube.com/watch?v=${videoId}&t=${Math.floor(m.timestamp)}s`}
                        target="_blank"
                        rel="noreferrer"
                        style={styles.link}
                        onClick={() => {
                          const username = localStorage.getItem('username');
                          if (username) {
                            fetch('http://localhost:5000/api/user-history', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({
                                username,
                                type: 'watch',
                                data: videoId,
                                timestamp: Date.now(),
                              }),
                            });
                          }
                        }}
                      >
                        {new Date(m.timestamp * 1000).toISOString().substr(11, 8)} - {m.text}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <label style={{ marginTop: '10px' }}>
              <input type="checkbox" checked={selectedVideos.includes(videoId)} onChange={() => toggleSelect(videoId)} />
              Add to Merge
            </label>
            <button onClick={() => toggleSummary(index)} style={styles.toggleSummaryBtn}>
              {expandedSummaries[index] ? 'Hide Summary ▲' : 'Show Summary ▼'}
            </button>
            {expandedSummaries[index] && (
              <p style={{ fontStyle: 'italic', color: '#ccc', marginTop: '10px' }}>
                <strong>Summary:</strong> {result.summary}
              </p>
            )}
          </div>
        );
      })}
      {results.length >= 3 && (
        <button onClick={handleSummarize} style={styles.summarizeButton}>
          🎬 Best Moments
        </button>
      )}
      {selectedVideos.length >= 2 && (
        <button onClick={handleOpenMergePreview} style={{ ...styles.summarizeButton, backgroundColor: '#28a745' }}>
          🧩 Preview & Merge Videos
        </button>
      )}
    </div>
  );
};

export default SearchByKeywordsPage;
