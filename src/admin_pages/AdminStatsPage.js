import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import './AdminPanelStyles.css';
import { API_BASE_URL } from '../config/api.js';

const sidebarLinks = [
  { path: '/admin-account-info', label: 'Account Info', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg> },
  { path: '/admin-security', label: 'Security', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> },
  { path: '/admin-history', label: 'History', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> },
  { path: '/admin-stats', label: 'Platform Stats', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg> },
  { path: '/admin-users', label: 'Manage Users', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg> },
];

const authHeaders = () => ({
  'Content-Type': 'application/json',
  'Authorization': `Bearer ${localStorage.getItem('access_token') || ''}`,
});

const StatCard = ({ label, value, sub, color, icon }) => (
  <motion.div
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    style={{
      background: 'rgba(255,255,255,0.04)',
      border: '1px solid rgba(255,255,255,0.08)',
      borderRadius: '16px',
      padding: '24px',
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
      flex: '1 1 180px',
      minWidth: '160px',
    }}
  >
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
      <span style={{ color, opacity: 0.9 }}>{icon}</span>
      <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.45)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
    </div>
    <span style={{ fontSize: '2.2rem', fontWeight: 700, color: '#fff', lineHeight: 1 }}>{value ?? '—'}</span>
    {sub && <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.35)' }}>{sub}</span>}
  </motion.div>
);

const AdminStatsPage = () => {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [userData, setUserData] = useState({});
  const navigate = useNavigate();
  const location = useLocation();
  const username = JSON.parse(localStorage.getItem('user'))?.username;

  useEffect(() => {
    if (username) {
      fetch(`${API_BASE_URL}/api/v1/auth/user/${username}`, { headers: authHeaders() })
        .then(r => r.json()).then(setUserData).catch(() => {});
    }

    fetch(`${API_BASE_URL}/api/v1/auth/admin/stats`, { headers: authHeaders() })
      .then(r => {
        if (!r.ok) throw new Error('Failed to load stats');
        return r.json();
      })
      .then(data => { setStats(data); setLoading(false); })
      .catch(() => { setError('Could not load platform stats.'); setLoading(false); });
  }, [username]);

  return (
    <div className="admin-page">
      <div className="admin-bg-gradient" />
      <div className="admin-layout">

        {/* Sidebar */}
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

        {/* Main */}
        <main className="admin-main">
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
            <h1 className="admin-heading">Platform Stats</h1>
            <p className="admin-subheading">Overview of platform activity — individual user data is private</p>

            {loading && (
              <div style={{ color: 'rgba(255,255,255,0.4)', padding: '40px 0', textAlign: 'center' }}>Loading stats...</div>
            )}

            {error && (
              <div className="admin-message admin-message-error">{error}</div>
            )}

            {stats && !loading && (
              <>
                {/* Users section */}
                <div style={{ marginBottom: '32px' }}>
                  <h2 style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: '16px' }}>
                    Users
                  </h2>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px' }}>
                    <StatCard
                      label="Total Users"
                      value={stats.users.total}
                      color="#60a5fa"
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>}
                    />
                    <StatCard
                      label="Active Accounts"
                      value={stats.users.active}
                      sub="Not deactivated"
                      color="#34d399"
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>}
                    />
                    <StatCard
                      label="Inactive"
                      value={stats.users.inactive}
                      sub="Deactivated by admin"
                      color="#f87171"
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>}
                    />
                    <StatCard
                      label="Active Today"
                      value={stats.users.active_today}
                      sub="Unique users with activity"
                      color="#a78bfa"
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>}
                    />
                    <StatCard
                      label="New This Week"
                      value={stats.users.new_this_week}
                      color="#fbbf24"
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>}
                    />
                    <StatCard
                      label="Admins"
                      value={stats.users.admins}
                      color="#f472b6"
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>}
                    />
                  </div>
                </div>

                {/* Activity section */}
                <div>
                  <h2 style={{ fontSize: '13px', fontWeight: 600, color: 'rgba(255,255,255,0.4)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: '16px' }}>
                    Platform Activity (All Time)
                  </h2>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px' }}>
                    <StatCard
                      label="Total Actions"
                      value={stats.activity.total_actions}
                      color="#60a5fa"
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>}
                    />
                    <StatCard
                      label="Searches"
                      value={stats.activity.total_searches}
                      color="#0EA5E9"
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>}
                    />
                    <StatCard
                      label="Videos Watched"
                      value={stats.activity.total_watches}
                      color="#a78bfa"
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="5 3 19 12 5 21 5 3"/></svg>}
                    />
                    <StatCard
                      label="Merges Done"
                      value={stats.activity.total_merges}
                      color="#34d399"
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>}
                    />
                    <StatCard
                      label="Transcripts Viewed"
                      value={stats.activity.total_transcripts}
                      color="#fbbf24"
                      icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>}
                    />
                  </div>
                </div>

                {/* Privacy note */}
                <div style={{
                  marginTop: '32px', padding: '14px 18px',
                  background: 'rgba(96,165,250,0.06)',
                  border: '1px solid rgba(96,165,250,0.15)',
                  borderRadius: '12px',
                  fontSize: '13px', color: 'rgba(255,255,255,0.45)',
                  display: 'flex', alignItems: 'center', gap: '10px'
                }}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" strokeWidth="2">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                  </svg>
                  Individual user search history, watched videos, and personal activity are private and not accessible to admins.
                </div>
              </>
            )}
          </motion.div>
        </main>
      </div>
    </div>
  );
};

export default AdminStatsPage;

