import React, { useState } from 'react';
import './AuthPage.css';
import { sendVerificationCode, verifyCode, resetPassword } from './authExtraApi.js'; // ✅ Corrected path

import { useNavigate } from 'react-router-dom';

const ForgotPasswordPage = () => {
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    const res = await sendVerificationCode(email);
    setMessage(res.message);
    if (res.success) {
      localStorage.setItem('resetEmail', email);
      navigate('/verify-code'); // This should route to a page you create for code input
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-form-section">
        <h2 className="auth-title">Forgot Password</h2>
        <form className="auth-form" onSubmit={handleSubmit}>
          <input
            type="email"
            placeholder="Enter your registered email"
            className="auth-input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
          <button type="submit" className="auth-button">Send Verification Code</button>
          {message && <p className="auth-footer" style={{ color: 'green', marginTop: '10px' }}>{message}</p>}
        </form>
      </div>
      <div className="auth-image-section">
        <img src="/login-illustration.webp" alt="Forgot Illustration" />
      </div>
    </div>
  );
};

export default ForgotPasswordPage;
