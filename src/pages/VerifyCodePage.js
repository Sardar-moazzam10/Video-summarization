import React, { useState } from 'react';
import './AuthPage.css';
import { verifyCode } from './authExtraApi.js';
import { useNavigate } from 'react-router-dom';

const VerifyCodePage = () => {
  const [code, setCode] = useState('');
  const [message, setMessage] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    const email = localStorage.getItem('resetEmail');
    const res = await verifyCode(email, code);
    setMessage(res.message);
    if (res.success) {
      navigate('/reset-password');
    }
  };

  return (
    <div className="auth-container">
      <div className="auth-form-section">
        <h2 className="auth-title">Verify Code</h2>
        <form className="auth-form" onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="Enter 6-digit code"
            className="auth-input"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
          />
          <button type="submit" className="auth-button">Verify</button>
          {message && <p>{message}</p>}
        </form>
      </div>
      <div className="auth-image-section">
        <img src="/login-illustration.webp" alt="Verify" />
      </div>
    </div>
  );
};

export default VerifyCodePage;
