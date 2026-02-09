import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import '../admin_pages/AdminPanelStyles.css';

const AdminHistoryPage = () => {
  const [history, setHistory] = useState([]);
  const [filter, setFilter] = useState('all');
  const username = JSON.parse(localStorage.getItem('user'))?.username;
  const navigate = useNavigate();

  useEffect(() => {
    if (!username) return;
    fetch(`http://localhost:5000/api/user-history/${username}`)
      .then(res => res.json())
      .then(data => setHistory(data.reverse()))
      .catch(err => console.error('❌ Failed to fetch history:', err));
  }, [username]);

  const handleClearHistory = async () => {
    const confirm = window.confirm('Are you sure you want to delete all history?');
    if (!confirm) return;

    try {
      const res = await fetch(`http://localhost:5000/api/user-history/delete/${username}`, {
        method: 'DELETE',
      });
      const data = await res.json();
      if (data.success) setHistory([]);
    } catch (err) {
      console.error('❌ Failed to delete history:', err);
    }
  };

  const handleDeleteSingle = async (timestamp) => {
    try {
      await fetch(`http://localhost:5000/api/user-history/delete-one`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, timestamp })
      });
      setHistory(prev => prev.filter(item => item.timestamp !== timestamp));
    } catch (err) {
      console.error('❌ Failed to delete item:', err);
    }
  };

  const handleClick = (item) => {
    if (item.type === 'search') {
      navigate(`/search/${encodeURIComponent(item.query)}`);
    } else if (item.type === 'watch') {
      navigate(`/video-player/${item.videoId}`);
    } else if (item.type === 'transcript-view') {
      navigate(`/transcript-viewer/${item.videoId}`);
    }
  };
  



  const filteredHistory = history.filter(item =>
    filter === 'all' ? true : item.type === filter
  );

  return (
    <div className="admin-panel-wrapper">
      <div className="admin-sidebar">
        <h3>Admin Settings</h3>
        <ul>
          <li onClick={() => navigate('/admin-account-info')}>Account Info</li>
          <li onClick={() => navigate('/admin-security')}>Security</li>
          <li onClick={() => navigate('/admin-history')}>History</li>
          <li onClick={() => navigate('/admin-users')}>Manage Users</li>
        </ul>
      </div>

      <div className="admin-panel">
        <br /><br />
        <h2 className="section-title">Search, Watch & Transcript History</h2>

        <div className="form-section">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              style={{
                backgroundColor: '#111',
                color: '#fff',
                padding: '8px',
                border: '1px solid #333',
                borderRadius: '6px'
              }}
            >
              <option value="all">All</option>
              <option value="search">Search</option>
              <option value="watch">Watch</option>
              <option value="transcript-view">Transcript View</option>
            </select>
            <button className="update-btn" onClick={handleClearHistory}>Clear All History</button>
          </div>

          <ul style={{ marginTop: '20px', paddingLeft: '0' }}>
            {filteredHistory.map((item, index) => (
              <li key={index} style={{
                background: '#2c2c2c',
                padding: '10px',
                borderRadius: '6px',
                marginBottom: '10px',
                listStyle: 'none',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}>
                <div style={{ flex: 1 }}>
                  <strong>
                    {item.type === 'search' && '🔍 Search: '}
                    {item.type === 'watch' && '🎬 Watched: '}
                    {item.type === 'transcript-view' && '📝 Transcript: '}
                  </strong>
                  <span
                    onClick={() => handleClick(item)}
                    style={{ color: '#4da6ff', textDecoration: 'underline', cursor: 'pointer' }}
                  >
                    {item.query || item.title || item.videoId}
                  </span>
                  <div style={{ fontSize: '12px', color: '#999' }}>
                    {new Date(item.timestamp).toLocaleString()}
                  </div>
                </div>
                <button
                  onClick={() => handleDeleteSingle(item.timestamp)}
                  style={{
                    marginLeft: '15px',
                    background: 'none',
                    border: 'none',
                    color: '#ff4d4d',
                    fontSize: '18px',
                    cursor: 'pointer'
                  }}
                >
                  🗑️
                </button>
              </li>
            ))}
            {filteredHistory.length === 0 && <p style={{ color: '#999' }}>No history found for selected type.</p>}
          </ul>
        </div>
      </div>
    </div>
  );
};

export default AdminHistoryPage;
