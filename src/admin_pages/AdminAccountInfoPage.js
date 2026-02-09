import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import '../admin_pages/AdminPanelStyles.css';

const AdminAccountInfoPage = () => {
  const [userData, setUserData] = useState({});
  const [reason, setReason] = useState('');
  const [message, setMessage] = useState('');
  const username = JSON.parse(localStorage.getItem('user'))?.username;
  const navigate = useNavigate();

  useEffect(() => {
    if (username) {
      fetch(`http://localhost:5000/api/user/${username}`)
        .then(res => res.json())
        .then(data => setUserData(data))
        .catch(() => setMessage('Failed to load user data.'));
    }
  }, [username]);

const handleUpdate = () => {
  fetch(`http://localhost:5000/api/user/update/${username}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(userData)
  })
    .then(res => res.json())
    .then(data => {
      setMessage(data.message);
      // ✅ If username changed, update localStorage
      if (data.newUsername && data.newUsername !== username) {
        const currentUser = JSON.parse(localStorage.getItem('user'));
        currentUser.username = data.newUsername;
        localStorage.setItem('user', JSON.stringify(currentUser));
        // Optionally reload to reflect in Navbar
        window.location.reload();
      }
    })
    .catch(() => setMessage('Update failed.'));
};


  const handleDelete = () => {
    if (window.confirm('Are you sure you want to delete your account?')) {
      fetch(`http://localhost:5000/api/user/delete/${username}`, {
        method: 'DELETE'
      })
        .then(res => res.json())
        .then(data => {
          localStorage.removeItem('user');
          setMessage(data.message);
          window.location.href = '/login';
        })
        .catch(() => setMessage('Account deletion failed.'));
    }
  };

  return (
    <div className="admin-panel-wrapper">
      {/* Sidebar */}
      <div className="admin-sidebar">
        <h3>{userData.firstName} {userData.lastName}</h3>
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
        <h2 className="section-title">Admin Account Information</h2>
       <div className="form-section">
  <label>First Name</label>
  <input
    name="firstName"
    placeholder="First Name"
    value={userData.firstName || ''}
    onChange={(e) => setUserData({ ...userData, firstName: e.target.value })}
  />

  <label>Last Name</label>
  <input
    name="lastName"
    placeholder="Last Name"
    value={userData.lastName || ''}
    onChange={(e) => setUserData({ ...userData, lastName: e.target.value })}
  />

  <label>Username</label>
  <input
    name="username"
    placeholder="Username"
    value={userData.username || ''}
    onChange={(e) => setUserData({ ...userData, username: e.target.value })}
  />

  <label>Email</label>
  <input
    name="email"
    placeholder="Email"
    value={userData.email || ''}
    onChange={(e) => setUserData({ ...userData, email: e.target.value })}
  />

 <button
  onClick={handleUpdate}
  style={{
    backgroundColor: '#0C0950',
    color: '#fff',
    fontSize: '13px',
    padding: '8px 14px',
    border: 'none',
    borderRadius: '4px',
    fontWeight: 'bold',
    cursor: 'pointer',
    width: 'fit-content',
    marginTop: '10px',
    textAlign: 'left'
  }}
>
  Update Info
</button>
</div>


        <h2 className="section-title">Delete Account</h2>
        <div className="delete-section">
          <select
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ marginBottom: '15px' }}
          >
            <option value="">Reason for leaving (optional)</option>
            <option value="privacy">Privacy concerns</option>
            <option value="not-useful">Not useful</option>
            <option value="temporary">Just temporary</option>
            <option value="other">Other</option>
          </select>
          <br></br>
                        <button
                onClick={handleDelete}
                style={{
                  backgroundColor: '#ff4d4d',
                  color: '#fff',
                  fontSize: '13px',
                  padding: '8px 14px',
                  border: 'none',
                  borderRadius: '4px',
                  fontWeight: 'bold',
                  cursor: 'pointer',
                  width: 'fit-content',
                  textAlign: 'left'
                }}
              >
                Delete My Account
              </button>

        </div>

        {message && <p className="message">{message}</p>}
      </div>
    </div>
  );
};

export default AdminAccountInfoPage;
