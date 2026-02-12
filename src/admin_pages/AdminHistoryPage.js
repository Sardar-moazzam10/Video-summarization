import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import './AdminPanelStyles.css';

const sidebarLinks = [
  { path: '/admin-account-info', label: 'Account Info', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg> },
  { path: '/admin-security', label: 'Security', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> },
  { path: '/admin-history', label: 'History', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> },
  { path: '/admin-users', label: 'Manage Users', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg> },
];

const filterTabs = [
  { key: 'all', label: 'All', icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/></svg> },
  { key: 'search', label: 'Searches', icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> },
  { key: 'watch', label: 'Watched', icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> },
  { key: 'transcript-view', label: 'Transcripts', icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> },
];

const typeColors = {
  search: '#0EA5E9',
  watch: '#a78bfa',
  'transcript-view': '#34d399',
};

const typeLabels = {
  search: 'Search',
  watch: 'Watch',
  'transcript-view': 'Transcript',
};

const timeAgo = (ts) => {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(ts).toLocaleDateString();
};

const AdminHistoryPage = () => {
  const [history, setHistory] = useState([]);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [userData, setUserData] = useState({});
  const username = JSON.parse(localStorage.getItem('user'))?.username;
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (!username) return;
    Promise.all([
      fetch(`http://localhost:8000/api/v1/auth/user-history/${username}`).then(r => r.json()),
      fetch(`http://localhost:8000/api/v1/auth/user/${username}`).then(r => r.json()),
    ])
      .then(([histData, user]) => {
        setHistory(histData.reverse());
        setUserData(user);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [username]);

  const handleClear = async () => {
    if (!window.confirm('Delete all history?')) return;
    try {
      const res = await fetch(`http://localhost:8000/api/v1/auth/user-history/delete/${username}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) setHistory([]);
    } catch {}
  };

  const handleDeleteOne = async (timestamp, e) => {
    e.stopPropagation();
    try {
      await fetch('http://localhost:8000/api/v1/auth/user-history/delete-one', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, timestamp })
      });
      setHistory(prev => prev.filter(i => i.timestamp !== timestamp));
    } catch {}
  };

  const handleClick = (item) => {
    if (item.type === 'search') navigate(`/search/${encodeURIComponent(item.query)}`);
    else if (item.type === 'watch') navigate(`/video-player/${encodeURIComponent(item.videoId)}`);
    else if (item.type === 'transcript-view') navigate(`/transcript-viewer/${encodeURIComponent(item.videoId)}`);
  };

  const filtered = history.filter(i => filter === 'all' || i.type === filter);

  return (
    <div className="admin-page">
      <div className="admin-bg-gradient" />

      <div className="admin-layout">
        <aside className="admin-sidebar">
          <div className="admin-sidebar-header">
            <div className="admin-sidebar-avatar">
              {(userData.firstName || 'A').charAt(0).toUpperCase()}
            </div>
            <div className="admin-sidebar-info">
              <p className="admin-sidebar-name">{userData.firstName} {userData.lastName}</p>
              <p className="admin-sidebar-role">Admin</p>
            </div>
          </div>

          <nav className="admin-sidebar-nav">
            {sidebarLinks.map((link) => (
              <button
                key={link.path}
                className={`admin-sidebar-link ${location.pathname === link.path ? 'admin-sidebar-link-active' : ''}`}
                onClick={() => navigate(link.path)}
              >
                {link.icon}
                {link.label}
              </button>
            ))}
          </nav>
        </aside>

        <main className="admin-main">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <h1 className="admin-heading">History</h1>
            <p className="admin-subheading">Your recent searches, watches, and transcript views</p>

            <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', flexWrap: 'wrap' }}>
              {filterTabs.map((tab) => {
                const count = tab.key === 'all' ? history.length : history.filter(i => i.type === tab.key).length;
                return (
                  <button
                    key={tab.key}
                    onClick={() => setFilter(tab.key)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: '6px',
                      padding: '8px 14px', borderRadius: '10px', border: 'none',
                      background: filter === tab.key ? 'rgba(14, 165, 233, 0.12)' : 'rgba(255,255,255,0.04)',
                      color: filter === tab.key ? '#fff' : 'rgba(255,255,255,0.5)',
                      fontSize: '13px', fontWeight: 500, cursor: 'pointer',
                      fontFamily: 'inherit', transition: 'all 0.15s',
                    }}
                  >
                    {tab.icon}
                    {tab.label}
                    <span style={{
                      background: filter === tab.key ? 'rgba(14,165,233,0.3)' : 'rgba(255,255,255,0.08)',
                      padding: '1px 7px', borderRadius: '6px', fontSize: '11px',
                    }}>
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>

            {history.length > 0 && (
              <div style={{ marginBottom: '16px' }}>
                <button className="admin-btn-danger admin-btn-sm" onClick={handleClear}>
                  Clear All History
                </button>
              </div>
            )}

            {loading ? (
              <div className="admin-card" style={{ textAlign: 'center', padding: '40px' }}>
                <div style={{
                  width: '32px', height: '32px', border: '3px solid rgba(255,255,255,0.1)',
                  borderTopColor: '#0EA5E9', borderRadius: '50%',
                  animation: 'spin 0.6s linear infinite', margin: '0 auto 12px',
                }} />
                <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: '14px', margin: 0 }}>Loading history...</p>
                <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
              </div>
            ) : filtered.length === 0 ? (
              <div className="admin-card" style={{ textAlign: 'center', padding: '40px' }}>
                <p style={{ color: 'rgba(255,255,255,0.35)', fontSize: '14px', margin: 0 }}>
                  {history.length === 0 ? 'No history yet.' : `No ${filter} history found.`}
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <AnimatePresence>
                  {filtered.map((item, i) => {
                    const color = typeColors[item.type] || '#0EA5E9';
                    return (
                      <motion.div
                        key={item.timestamp + i}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, x: -20 }}
                        transition={{ duration: 0.2 }}
                        onClick={() => handleClick(item)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: '14px',
                          padding: '14px 18px', borderRadius: '12px', cursor: 'pointer',
                          background: 'rgba(17, 24, 39, 0.5)',
                          border: '1px solid rgba(255,255,255,0.06)',
                          transition: 'all 0.15s',
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = `rgba(${color === '#0EA5E9' ? '14,165,233' : color === '#a78bfa' ? '167,139,250' : '52,211,153'}, 0.06)`;
                          e.currentTarget.style.borderColor = `${color}33`;
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = 'rgba(17, 24, 39, 0.5)';
                          e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)';
                        }}
                      >
                        <div style={{
                          width: '36px', height: '36px', borderRadius: '10px', flexShrink: 0,
                          background: `${color}18`, display: 'flex', alignItems: 'center', justifyContent: 'center',
                          color: color,
                        }}>
                          {item.type === 'search' && <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>}
                          {item.type === 'watch' && <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>}
                          {item.type === 'transcript-view' && <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>}
                        </div>

                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '2px' }}>
                            <span style={{
                              fontSize: '11px', fontWeight: 600, color: color, textTransform: 'uppercase',
                              letterSpacing: '0.05em',
                            }}>
                              {typeLabels[item.type]}
                            </span>
                            <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.25)' }}>
                              {timeAgo(item.timestamp)}
                            </span>
                          </div>
                          <p style={{
                            margin: 0, fontSize: '14px', color: '#fff', fontWeight: 500,
                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          }}>
                            {item.query || item.title || item.videoId || 'Untitled'}
                          </p>
                        </div>

                        <button
                          onClick={(e) => handleDeleteOne(item.timestamp, e)}
                          style={{
                            background: 'none', border: 'none', color: 'rgba(255,255,255,0.2)',
                            cursor: 'pointer', padding: '6px', borderRadius: '6px',
                            transition: 'all 0.15s', flexShrink: 0,
                          }}
                          onMouseEnter={(e) => { e.target.style.color = '#ef4444'; e.target.style.background = 'rgba(239,68,68,0.1)'; }}
                          onMouseLeave={(e) => { e.target.style.color = 'rgba(255,255,255,0.2)'; e.target.style.background = 'none'; }}
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                      </motion.div>
                    );
                  })}
                </AnimatePresence>
              </div>
            )}
          </motion.div>
        </main>
      </div>
    </div>
  );
};

export default AdminHistoryPage;
