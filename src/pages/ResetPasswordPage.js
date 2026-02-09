import React, { useState } from 'react';
import './AuthPage.css';
import { resetPassword } from './authExtraApi.js';
import { useNavigate } from 'react-router-dom';

const ResetPasswordPage = () => {
  const [newPassword, setNewPassword] = useState('');
  const [message, setMessage] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    const email = localStorage.getItem('resetEmail');
    const res = await resetPassword(email, newPassword);
    setMessage(res.message);
    if (res.success) {
      navigate('/login');
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-form-section">
        <h2 className="auth-title">Set New Password</h2>
        <form className="auth-form" onSubmit={handleSubmit}>
          <input
            type="password"
            placeholder="Enter new password"
            className="auth-input"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
          />
          <button type="submit" className="auth-button">Reset Password</button>
          {message && <p>{message}</p>}
        </form>
      </div>
      <div className="auth-image-section">
        <img src="/login-illustration.webp" alt="Reset" />
      </div>
    </div>
  );
};

export default ResetPasswordPage;
