import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './UserPanelPage.css';

const UserPanelPage = () => {
  const [userData, setUserData] = useState({
    firstName: '',
    lastName: '',
    email: '',
    username: '',
  });
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [showOldPassword, setShowOldPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [message, setMessage] = useState('');

  const username = JSON.parse(localStorage.getItem('user'))?.username;

  useEffect(() => {
    if (username) {
      axios.get(`http://localhost:5000/api/user/${username}`)
        .then(res => setUserData(res.data))
        .catch(() => setMessage('Error fetching user data.'));
    }
  }, [username]);

  const handleChange = (e) => {
    setUserData({ ...userData, [e.target.name]: e.target.value });
  };

  const handleUpdate = () => {
    axios.put(`http://localhost:5000/api/user/update/${username}`, userData)
      .then(res => setMessage(res.data.message))
      .catch(() => setMessage('Update failed.'));
  };

  const handlePasswordUpdate = () => {
    axios.put(`http://localhost:5000/api/user/update-password/${username}`, {
      oldPassword,
      newPassword
    })
      .then(res => setMessage(res.data.message))
      .catch(() => setMessage('Password update failed.'));
  };

  const handleDelete = () => {
    if (window.confirm('Are you sure you want to delete your account?')) {
      axios.delete(`http://localhost:5000/api/user/delete/${username}`)
        .then(res => {
          localStorage.removeItem('user');
          setMessage(res.data.message);
          window.location.href = '/login';
        })
        .catch(() => setMessage('Deletion failed.'));
    }
  };

  return (
    <div className="user-panel-wrapper">
      <div className="user-sidebar">
        <h3>⚙️ Settings</h3>
        <ul>
          <li>Account Info</li>
          <li>History</li>
        </ul>
      </div>

      <div className="user-panel">
        <h2 className="section-title">Account Information</h2>
        <div className="form-section">
          <input name="firstName" value={userData.firstName} onChange={handleChange} placeholder="First Name" />
          <input name="lastName" value={userData.lastName} onChange={handleChange} placeholder="Last Name" />
          <input name="email" value={userData.email} onChange={handleChange} placeholder="Email" />
          <button className="update-btn" onClick={handleUpdate}>Update Information</button>
        </div>

        <h2 className="section-title">Change Password</h2>
        <div className="form-section">
          <div className="password-group">
            <input type={showOldPassword ? 'text' : 'password'} value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} placeholder="Old Password" />
            <button onClick={() => setShowOldPassword(!showOldPassword)}>Show</button>
          </div>
          <div className="password-group">
            <input type={showNewPassword ? 'text' : 'password'} value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="New Password" />
            <button onClick={() => setShowNewPassword(!showNewPassword)}>Show</button>
          </div>
          <button className="update-btn" onClick={handlePasswordUpdate}>Update Password</button>
        </div>

        <div className="delete-section">
          <button onClick={handleDelete}>Delete Account</button>
        </div>

        {message && <p className="message">{message}</p>}
      </div>
    </div>
  );
};

export default UserPanelPage;
