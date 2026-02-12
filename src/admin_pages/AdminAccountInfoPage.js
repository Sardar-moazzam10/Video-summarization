import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import './AdminPanelStyles.css';

const sidebarLinks = [
  { path: '/admin-account-info', label: 'Account Info', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg> },
  { path: '/admin-security', label: 'Security', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg> },
  { path: '/admin-history', label: 'History', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> },
  { path: '/admin-users', label: 'Manage Users', icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg> },
];

const AdminAccountInfoPage = () => {
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
        if (data.newUsername && data.newUsername !== username) {
          const currentUser = JSON.parse(localStorage.getItem('user'));
          currentUser.username = data.newUsername;
          localStorage.setItem('user', JSON.stringify(currentUser));
          window.location.reload();
        }
      })
      .catch(() => { setMessage('Update failed.'); setMsgType('error'); });
  };

  const handleDelete = () => {
    if (window.confirm('Are you sure you want to delete your account? This action cannot be undone.')) {
      fetch(`http://localhost:8000/api/v1/auth/user/delete/${username}`, { method: 'DELETE' })
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
            <h1 className="admin-heading">Account Information</h1>
            <p className="admin-subheading">Update your admin profile details</p>

            <div className="admin-card">
              <div className="admin-form-grid">
                <div className="admin-field">
                  <label className="admin-label">First Name</label>
                  <input
                    className="admin-input"
                    value={userData.firstName || ''}
                    onChange={(e) => setUserData({ ...userData, firstName: e.target.value })}
                    placeholder="First Name"
                  />
                </div>
                <div className="admin-field">
                  <label className="admin-label">Last Name</label>
                  <input
                    className="admin-input"
                    value={userData.lastName || ''}
                    onChange={(e) => setUserData({ ...userData, lastName: e.target.value })}
                    placeholder="Last Name"
                  />
                </div>
                <div className="admin-field">
                  <label className="admin-label">Username</label>
                  <input
                    className="admin-input"
                    value={userData.username || ''}
                    onChange={(e) => setUserData({ ...userData, username: e.target.value })}
                    placeholder="Username"
                  />
                </div>
                <div className="admin-field">
                  <label className="admin-label">Email</label>
                  <input
                    className="admin-input"
                    value={userData.email || ''}
                    onChange={(e) => setUserData({ ...userData, email: e.target.value })}
                    placeholder="Email"
                  />
                </div>
              </div>

              <button className="admin-btn-primary" onClick={handleUpdate}>
                Save Changes
              </button>

              {message && (
                <div className={`admin-message ${msgType === 'error' ? 'admin-message-error' : 'admin-message-success'}`}>
                  {message}
                </div>
              )}
            </div>

            <div className="admin-card admin-card-danger">
              <h3 className="admin-danger-title">Danger Zone</h3>
              <p className="admin-danger-desc">Once you delete your account, there is no going back.</p>

              <select
                className="admin-select"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                style={{ marginBottom: '16px' }}
              >
                <option value="">Reason for leaving (optional)</option>
                <option value="privacy">Privacy concerns</option>
                <option value="not-useful">Not useful for me</option>
                <option value="temporary">Temporary account</option>
                <option value="other">Other</option>
              </select>

              <button className="admin-btn-danger" onClick={handleDelete} style={{ width: '100%' }}>
                Delete My Account
              </button>
            </div>
          </motion.div>
        </main>
      </div>
    </div>
  );
};

export default AdminAccountInfoPage;
