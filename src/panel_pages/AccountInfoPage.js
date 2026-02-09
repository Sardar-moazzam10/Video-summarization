import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import './PanelStyles.css';

const AccountInfoPage = () => {
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

      // ✅ Update localStorage if username was changed
      if (userData.username && userData.username !== username) {
        const currentUser = JSON.parse(localStorage.getItem('user'));
        currentUser.username = userData.username;
        localStorage.setItem('user', JSON.stringify(currentUser));

        // ✅ Reload to reflect changes (like navbar username)
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
    <div className="user-panel-wrapper">
      
      {/* Sidebar */}
      <div className="user-sidebar">
        <h3>{userData.firstName} {userData.lastName}</h3>
        <ul>
          <li onClick={() => navigate('/account-info')}>Account Info</li>
          <li onClick={() => navigate('/security')}>Security</li>
          <li onClick={() => navigate('/history')}>History</li>
        </ul>
      </div>

      {/* Main Panel */}
      <div className="user-panel">
      <br></br>
      <br></br>
        <h2 className="section-title">Account Information</h2>
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

  <button className="update-btn" onClick={handleUpdate}>Update Info</button>
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
          <button onClick={handleDelete}>Delete My Account</button>
        </div>

        {message && <p className="message">{message}</p>}
      </div>
    </div>
  );
};

export default AccountInfoPage;
