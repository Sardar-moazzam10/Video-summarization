import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import '../admin_pages/AdminPanelStyles.css';

const AdminSecurityPage = () => {
  const navigate = useNavigate();
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [showOld, setShowOld] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [message, setMessage] = useState('');
  const username = JSON.parse(localStorage.getItem('user'))?.username;

  const handleUpdate = () => {
    fetch(`http://localhost:5000/api/user/update-password/${username}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ oldPassword, newPassword }),
    })
      .then(res => res.json())
      .then(data => setMessage(data.message))
      .catch(() => setMessage('Password update failed.'));
  };

  return (
    <div className="user-panel-wrapper">
      {/* Sidebar */}
      <div className="admin-sidebar">
        <h3>Admin Settings</h3>
        <ul>
          <li onClick={() => navigate('/admin-account-info')}>Account Info</li>
          <li onClick={() => navigate('/admin-security')}>Security</li>
          <li onClick={() => navigate('/admin-history')}>History</li>
          <li onClick={() => navigate('/admin-users')}>Manage Users</li>
        </ul>
      </div>

      {/* Main Panel */}
      <div className="admin-panel">
        <br /><br />
        <h2 className="section-title">Change Password</h2>

        <div className="form-section password-group">
          <input
            type={showOld ? 'text' : 'password'}
            placeholder="Old Password"
            value={oldPassword}
            onChange={(e) => setOldPassword(e.target.value)}
          />
          <button onClick={() => setShowOld(!showOld)}>
            {showOld ? 'Hide' : 'Show'}
          </button>
        </div>

        <div className="form-section password-group">
          <input
            type={showNew ? 'text' : 'password'}
            placeholder="New Password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
          />
          <button onClick={() => setShowNew(!showNew)}>
            {showNew ? 'Hide' : 'Show'}
          </button>
        </div>

        <button className="update-btn" onClick={handleUpdate}>Update Password</button>

        <div style={{ marginTop: '30px', textAlign: 'center' }}>
          <button
            onClick={() => navigate('/forgot-password')}
            className="update-btn"
            style={{ backgroundColor: '#444' }}
          >
            Forgot Password?
          </button>
        </div>

        {message && <p className="message">{message}</p>}
      </div>
    </div>
  );
};

export default AdminSecurityPage;
