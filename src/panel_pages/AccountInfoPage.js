import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import './PanelStyles.css';

const sidebarLinks = [
  { path: '/account-info', label: 'Account Info', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg> },
  { path: '/security', label: 'Security', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> },
  { path: '/history', label: 'History', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> },
];

const AccountInfoPage = () => {
  const [userData, setUserData] = useState({});
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState('');
  const [msgType, setMsgType] = useState('success');
  const username = JSON.parse(localStorage.getItem('user'))?.username;
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (username) {
      fetch(`http://localhost:8000/api/v1/auth/user/${username}`)
        .then(res => res.json())
        .then(data => setUserData(data))
        .catch(() => { setMessage('Failed to load user data.'); setMsgType('error'); });
    }
  }, [username]);

  const handleUpdate = () => {
    fetch(`http://localhost:8000/api/v1/auth/user/update/${username}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(userData)
    })
      .then(res => res.json())
      .then(data => {
        setMessage(data.message || 'Updated successfully');
        setMsgType('success');
        if (userData.username && userData.username !== username) {
          const currentUser = JSON.parse(localStorage.getItem('user'));
          currentUser.username = userData.username;
          localStorage.setItem('user', JSON.stringify(currentUser));
          window.location.reload();
        }
      })
      .catch(() => { setMessage('Update failed.'); setMsgType('error'); });
  };

  const handleDelete = () => {
    if (window.confirm('Are you sure you want to delete your account? This action cannot be undone.')) {
      fetch(`http://localhost:8000/api/v1/auth/user/delete/${username}`, {
        method: 'DELETE'
      })
        .then(res => res.json())
        .then(data => {
          localStorage.removeItem('user');
          localStorage.removeItem('access_token');
          localStorage.removeItem('refresh_token');
          setMessage(data.message);
          window.location.href = '/login';
        })
        .catch(() => { setMessage('Account deletion failed.'); setMsgType('error'); });
    }
  };

  return (
    <div className="panel-page">
      <div className="panel-bg-gradient" />

      <div className="panel-layout">
        {/* Sidebar */}
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

        {/* Main Content */}
        <main className="panel-main">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <h1 className="panel-heading">Account Information</h1>
            <p className="panel-subheading">Update your personal details</p>

            <div className="panel-card">
              <div className="panel-form-grid">
                <div className="panel-field">
                  <label className="panel-label">First Name</label>
                  <input
                    className="panel-input"
                    value={userData.firstName || ''}
                    onChange={(e) => setUserData({ ...userData, firstName: e.target.value })}
                    placeholder="First Name"
                  />
                </div>
                <div className="panel-field">
                  <label className="panel-label">Last Name</label>
                  <input
                    className="panel-input"
                    value={userData.lastName || ''}
                    onChange={(e) => setUserData({ ...userData, lastName: e.target.value })}
                    placeholder="Last Name"
                  />
                </div>
                <div className="panel-field">
                  <label className="panel-label">Username</label>
                  <input
                    className="panel-input"
                    value={userData.username || ''}
                    onChange={(e) => setUserData({ ...userData, username: e.target.value })}
                    placeholder="Username"
                  />
                </div>
                <div className="panel-field">
                  <label className="panel-label">Email</label>
                  <input
                    className="panel-input"
                    value={userData.email || ''}
                    onChange={(e) => setUserData({ ...userData, email: e.target.value })}
                    placeholder="Email"
                  />
                </div>
              </div>

              <button className="panel-btn-primary" onClick={handleUpdate}>
                Save Changes
              </button>

              {message && (
                <div className={`panel-message ${msgType === 'error' ? 'panel-message-error' : 'panel-message-success'}`}>
                  {message}
                </div>
              )}
            </div>

            {/* Danger Zone */}
            <div className="panel-card panel-card-danger">
              <h3 className="panel-danger-title">Danger Zone</h3>
              <p className="panel-danger-desc">Once you delete your account, there is no going back.</p>

              <select
                className="panel-select"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              >
                <option value="">Reason for leaving (optional)</option>
                <option value="privacy">Privacy concerns</option>
                <option value="not-useful">Not useful for me</option>
                <option value="temporary">Temporary account</option>
                <option value="other">Other</option>
              </select>

              <button className="panel-btn-danger" onClick={handleDelete}>
                Delete My Account
              </button>
            </div>
          </motion.div>
        </main>
      </div>
    </div>
  );
};

export default AccountInfoPage;
