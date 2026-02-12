import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import './PanelStyles.css';

const sidebarLinks = [
  { path: '/account-info', label: 'Account Info', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg> },
  { path: '/security', label: 'Security', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> },
  { path: '/history', label: 'History', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> },
];

const SecurityPage = () => {
  const [userData, setUserData] = useState({});
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showOld, setShowOld] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [message, setMessage] = useState('');
  const [msgType, setMsgType] = useState('success');
  const navigate = useNavigate();
  const location = useLocation();
  const username = JSON.parse(localStorage.getItem('user'))?.username;

  useEffect(() => {
    if (username) {
      fetch(`http://localhost:8000/api/v1/auth/user/${username}`)
        .then(res => res.json())
        .then(data => setUserData(data))
        .catch(() => {});
    }
  }, [username]);

  const handleUpdate = () => {
    if (!oldPassword || !newPassword) {
      setMessage('Please fill in both fields.');
      setMsgType('error');
      return;
    }
    if (newPassword.length < 6) {
      setMessage('New password must be at least 6 characters.');
      setMsgType('error');
      return;
    }
    if (newPassword !== confirmPassword) {
      setMessage('New passwords do not match.');
      setMsgType('error');
      return;
    }

    fetch(`http://localhost:8000/api/v1/auth/user/update-password/${username}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ oldPassword, newPassword }),
    })
      .then(res => res.json())
      .then(data => {
        setMessage(data.message || 'Password updated successfully');
        setMsgType(data.success === false ? 'error' : 'success');
        if (data.success !== false) {
          setOldPassword('');
          setNewPassword('');
          setConfirmPassword('');
        }
      })
      .catch(() => { setMessage('Password update failed.'); setMsgType('error'); });
  };

  return (
    <div className="panel-page">
      <div className="panel-bg-gradient" />

      <div className="panel-layout">
        <aside className="panel-sidebar">
          <div className="panel-sidebar-header">
            <div className="panel-sidebar-avatar">
              {(userData.firstName || 'U').charAt(0).toUpperCase()}
            </div>
            <div className="panel-sidebar-info">
              <p className="panel-sidebar-name">{userData.firstName} {userData.lastName}</p>
              <p className="panel-sidebar-email">{userData.email}</p>
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

        <main className="panel-main">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <h1 className="panel-heading">Security</h1>
            <p className="panel-subheading">Manage your password and account security</p>

            <div className="panel-card">
              <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#fff', margin: '0 0 20px' }}>Change Password</h3>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '24px' }}>
                <div className="panel-field">
                  <label className="panel-label">Current Password</label>
                  <div style={{ position: 'relative' }}>
                    <input
                      className="panel-input"
                      type={showOld ? 'text' : 'password'}
                      placeholder="Enter current password"
                      value={oldPassword}
                      onChange={(e) => setOldPassword(e.target.value)}
                    />
                    <button
                      type="button"
                      onClick={() => setShowOld(!showOld)}
                      style={{
                        position: 'absolute',
                        right: '12px',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        background: 'none',
                        border: 'none',
                        color: 'rgba(255,255,255,0.4)',
                        cursor: 'pointer',
                        fontSize: '13px',
                        fontFamily: 'inherit',
                      }}
                    >
                      {showOld ? 'Hide' : 'Show'}
                    </button>
                  </div>
                </div>

                <div className="panel-field">
                  <label className="panel-label">New Password</label>
                  <div style={{ position: 'relative' }}>
                    <input
                      className="panel-input"
                      type={showNew ? 'text' : 'password'}
                      placeholder="Enter new password"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                    />
                    <button
                      type="button"
                      onClick={() => setShowNew(!showNew)}
                      style={{
                        position: 'absolute',
                        right: '12px',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        background: 'none',
                        border: 'none',
                        color: 'rgba(255,255,255,0.4)',
                        cursor: 'pointer',
                        fontSize: '13px',
                        fontFamily: 'inherit',
                      }}
                    >
                      {showNew ? 'Hide' : 'Show'}
                    </button>
                  </div>
                </div>

                <div className="panel-field">
                  <label className="panel-label">Confirm New Password</label>
                  <input
                    className="panel-input"
                    type="password"
                    placeholder="Confirm new password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                  />
                </div>
              </div>

              <button className="panel-btn-primary" onClick={handleUpdate}>
                Update Password
              </button>

              {message && (
                <div className={`panel-message ${msgType === 'error' ? 'panel-message-error' : 'panel-message-success'}`}>
                  {message}
                </div>
              )}
            </div>

            <div className="panel-card" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
              <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'rgba(255,255,255,0.7)', margin: '0 0 8px' }}>Forgot your password?</h3>
              <p style={{ fontSize: '0.85rem', color: 'rgba(255,255,255,0.35)', margin: '0 0 16px' }}>
                If you can't remember your current password, you can reset it via email verification.
              </p>
              <button
                className="panel-btn-primary"
                onClick={() => navigate('/forgot-password')}
                style={{ background: 'rgba(255,255,255,0.06)', boxShadow: 'none' }}
              >
                Reset via Email
              </button>
            </div>
          </motion.div>
        </main>
      </div>
    </div>
  );
};

export default SecurityPage;
