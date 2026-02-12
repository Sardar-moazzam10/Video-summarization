import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import './PanelStyles.css';

const sidebarLinks = [
  { path: '/account-info', label: 'Account Info', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg> },
  { path: '/security', label: 'Security', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> },
  { path: '/history', label: 'History', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> },
];

const filterTabs = [
  { value: 'all', label: 'All', icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg> },
  { value: 'search', label: 'Searches', icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg> },
  { value: 'watch', label: 'Watched', icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> },
  { value: 'transcript-view', label: 'Transcripts', icon: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> },
];

const typeConfig = {
  search: { color: '#478BE0', bg: 'rgba(71, 139, 224, 0.1)', border: 'rgba(71, 139, 224, 0.2)', label: 'Search', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg> },
  watch: { color: '#a78bfa', bg: 'rgba(167, 139, 250, 0.1)', border: 'rgba(167, 139, 250, 0.2)', label: 'Watched', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> },
  'transcript-view': { color: '#34d399', bg: 'rgba(52, 211, 153, 0.1)', border: 'rgba(52, 211, 153, 0.2)', label: 'Transcript', icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg> },
};

function timeAgo(dateStr) {
  const now = new Date();
  const date = new Date(dateStr);
  const diff = Math.floor((now - date) / 1000);
  if (diff < 60) return 'Just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

const HistoryPage = () => {
  const [history, setHistory] = useState([]);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const user = JSON.parse(localStorage.getItem('user'));
  const username = user?.username;
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (!username) { setLoading(false); return; }
    fetch(`http://localhost:8000/api/v1/auth/user-history/${username}`)
      .then(res => res.json())
      .then(data => { setHistory(data.reverse()); setLoading(false); })
      .catch(() => setLoading(false));
  }, [username]);

  const handleClearHistory = async () => {
    if (!window.confirm('Are you sure you want to delete all history?')) return;
    try {
      const res = await fetch(`http://localhost:8000/api/v1/auth/user-history/delete/${username}`, { method: 'DELETE' });
      const data = await res.json();
      if (data.success) setHistory([]);
    } catch (err) {
      console.error('Failed to delete history:', err);
    }
  };

  const handleDeleteSingle = async (e, timestamp) => {
    e.stopPropagation();
    try {
      await fetch('http://localhost:8000/api/v1/auth/user-history/delete-one', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, timestamp })
      });
      setHistory(prev => prev.filter(item => item.timestamp !== timestamp));
    } catch (err) {
      console.error('Failed to delete item:', err);
    }
  };

  const handleClick = (item) => {
    if (item.type === 'search') {
      navigate('/search-by-title', { state: { query: item.query } });
    } else if (item.type === 'watch') {
      navigate(`/video-player/${encodeURIComponent(item.videoId)}`);
    } else if (item.type === 'transcript-view') {
      navigate(`/transcript-viewer/${encodeURIComponent(item.videoId)}`);
    }
  };

  const filteredHistory = history.filter(item =>
    filter === 'all' ? true : item.type === filter
  );

  const counts = {
    all: history.length,
    search: history.filter(i => i.type === 'search').length,
    watch: history.filter(i => i.type === 'watch').length,
    'transcript-view': history.filter(i => i.type === 'transcript-view').length,
  };

  return (
    <div className="panel-page">
      <div className="panel-bg-gradient" />

      <div className="panel-layout">
        {/* Sidebar */}
        <aside className="panel-sidebar">
          <div className="panel-sidebar-header">
            <div className="panel-sidebar-avatar">
              {(user?.firstName || 'U').charAt(0).toUpperCase()}
            </div>
            <div className="panel-sidebar-info">
              <p className="panel-sidebar-name">{user?.firstName} {user?.lastName}</p>
              <p className="panel-sidebar-email">{user?.email}</p>
            </div>
          </div>

          <nav className="panel-sidebar-nav">
            {sidebarLinks.map((link) => (
              <button
                key={link.path}
                className={`panel-sidebar-link ${location.pathname === link.path ? 'panel-sidebar-link-active' : ''}`}
                onClick={() => navigate(link.path)}
              >
                {link.icon}
                {link.label}
              </button>
            ))}
          </nav>
        </aside>

        {/* Main Content */}
        <main className="panel-main" style={{ maxWidth: '800px' }}>
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <h1 className="panel-heading">Activity History</h1>
            <p className="panel-subheading">Your searches, watched videos, and transcript views</p>

            {/* Filter Tabs + Clear Button */}
            <div style={styles.toolbar}>
              <div style={styles.filterTabs}>
                {filterTabs.map((tab) => (
                  <button
                    key={tab.value}
                    onClick={() => setFilter(tab.value)}
                    style={{
                      ...styles.filterTab,
                      ...(filter === tab.value ? styles.filterTabActive : {}),
                    }}
                  >
                    {tab.icon}
                    {tab.label}
                    {counts[tab.value] > 0 && (
                      <span style={{
                        ...styles.countBadge,
                        ...(filter === tab.value ? styles.countBadgeActive : {}),
                      }}>
                        {counts[tab.value]}
                      </span>
                    )}
                  </button>
                ))}
              </div>

              {history.length > 0 && (
                <button onClick={handleClearHistory} style={styles.clearBtn}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                  Clear All
                </button>
              )}
            </div>

            {/* Loading State */}
            {loading && (
              <div style={styles.emptyWrap}>
                <motion.div
                  animate={{ rotate: 360 }}
                  transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                  style={styles.spinner}
                />
              </div>
            )}

            {/* History List */}
            {!loading && (
              <div style={styles.historyList}>
                <AnimatePresence mode="popLayout">
                  {filteredHistory.map((item, index) => {
                    const config = typeConfig[item.type] || typeConfig.search;
                    const displayText = item.title || item.query || item.videoId || 'Unknown';

                    return (
                      <motion.div
                        key={item.timestamp + index}
                        layout
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, x: -20 }}
                        transition={{ duration: 0.2, delay: index * 0.03 }}
                        onClick={() => handleClick(item)}
                        style={styles.historyCard}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.borderColor = config.border;
                          e.currentTarget.style.background = 'rgba(255, 255, 255, 0.04)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.06)';
                          e.currentTarget.style.background = 'rgba(17, 24, 39, 0.5)';
                        }}
                      >
                        {/* Type Icon */}
                        <div style={{ ...styles.typeIcon, background: config.bg, color: config.color }}>
                          {config.icon}
                        </div>

                        {/* Content */}
                        <div style={styles.cardContent}>
                          <div style={styles.cardHeader}>
                            <span style={{ ...styles.typeBadge, background: config.bg, color: config.color, border: `1px solid ${config.border}` }}>
                              {config.label}
                            </span>
                            <span style={styles.timeAgo}>{timeAgo(item.timestamp)}</span>
                          </div>
                          <p style={styles.cardTitle}>{displayText}</p>
                          {item.videoId && item.type !== 'search' && (
                            <p style={styles.cardMeta}>ID: {item.videoId}</p>
                          )}
                        </div>

                        {/* Delete Button */}
                        <button
                          onClick={(e) => handleDeleteSingle(e, item.timestamp)}
                          style={styles.deleteBtn}
                          onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(239, 68, 68, 0.15)'; e.currentTarget.style.color = '#f87171'; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'rgba(255,255,255,0.25)'; }}
                        >
                          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                          </svg>
                        </button>
                      </motion.div>
                    );
                  })}
                </AnimatePresence>

                {/* Empty State */}
                {filteredHistory.length === 0 && !loading && (
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    style={styles.emptyWrap}
                  >
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="rgba(71,139,224,0.25)" strokeWidth="1.5">
                      <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                    </svg>
                    <p style={styles.emptyTitle}>
                      {filter === 'all' ? 'No activity yet' : `No ${filterTabs.find(t => t.value === filter)?.label.toLowerCase() || ''} history`}
                    </p>
                    <p style={styles.emptyDesc}>
                      {filter === 'all'
                        ? 'Start searching, watching videos, or viewing transcripts to build your history.'
                        : 'Items will appear here as you use this feature.'}
                    </p>
                  </motion.div>
                )}
              </div>
            )}
          </motion.div>
        </main>
      </div>
    </div>
  );
};

const styles = {
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '12px',
    marginBottom: '20px',
    flexWrap: 'wrap',
  },
  filterTabs: {
    display: 'flex',
    gap: '6px',
    flexWrap: 'wrap',
  },
  filterTab: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '7px 14px',
    background: 'rgba(255, 255, 255, 0.04)',
    border: '1px solid rgba(255, 255, 255, 0.08)',
    borderRadius: '9px',
    color: 'rgba(255, 255, 255, 0.5)',
    fontSize: '13px',
    fontWeight: 500,
    cursor: 'pointer',
    fontFamily: 'inherit',
    transition: 'all 0.15s',
  },
  filterTabActive: {
    background: 'rgba(71, 139, 224, 0.12)',
    borderColor: 'rgba(71, 139, 224, 0.3)',
    color: '#fff',
  },
  countBadge: {
    fontSize: '11px',
    fontWeight: 600,
    padding: '1px 6px',
    borderRadius: '6px',
    background: 'rgba(255, 255, 255, 0.08)',
    color: 'rgba(255, 255, 255, 0.4)',
    minWidth: '18px',
    textAlign: 'center',
  },
  countBadgeActive: {
    background: 'rgba(71, 139, 224, 0.2)',
    color: '#478BE0',
  },
  clearBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '7px 14px',
    background: 'rgba(239, 68, 68, 0.08)',
    border: '1px solid rgba(239, 68, 68, 0.15)',
    borderRadius: '9px',
    color: '#f87171',
    fontSize: '13px',
    fontWeight: 500,
    cursor: 'pointer',
    fontFamily: 'inherit',
    transition: 'all 0.15s',
  },
  historyList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  historyCard: {
    display: 'flex',
    alignItems: 'center',
    gap: '14px',
    padding: '14px 16px',
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255, 255, 255, 0.06)',
    borderRadius: '14px',
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  typeIcon: {
    width: '38px',
    height: '38px',
    borderRadius: '10px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  cardContent: {
    flex: 1,
    minWidth: 0,
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '4px',
  },
  typeBadge: {
    fontSize: '11px',
    fontWeight: 600,
    padding: '2px 8px',
    borderRadius: '6px',
    letterSpacing: '0.02em',
  },
  timeAgo: {
    fontSize: '12px',
    color: 'rgba(255, 255, 255, 0.3)',
  },
  cardTitle: {
    fontSize: '14px',
    fontWeight: 500,
    color: '#fff',
    margin: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  cardMeta: {
    fontSize: '12px',
    color: 'rgba(255, 255, 255, 0.25)',
    margin: '2px 0 0',
    fontFamily: 'monospace',
  },
  deleteBtn: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '32px',
    height: '32px',
    borderRadius: '8px',
    border: 'none',
    background: 'transparent',
    color: 'rgba(255, 255, 255, 0.25)',
    cursor: 'pointer',
    flexShrink: 0,
    transition: 'all 0.15s',
  },
  emptyWrap: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '60px 20px',
    textAlign: 'center',
  },
  emptyTitle: {
    fontSize: '16px',
    fontWeight: 600,
    color: 'rgba(255, 255, 255, 0.5)',
    margin: '16px 0 6px',
  },
  emptyDesc: {
    fontSize: '13.5px',
    color: 'rgba(255, 255, 255, 0.3)',
    margin: 0,
    maxWidth: '360px',
    lineHeight: 1.5,
  },
  spinner: {
    width: '24px',
    height: '24px',
    border: '2px solid rgba(71, 139, 224, 0.2)',
    borderTopColor: '#478BE0',
    borderRadius: '50%',
  },
};

export default HistoryPage;
