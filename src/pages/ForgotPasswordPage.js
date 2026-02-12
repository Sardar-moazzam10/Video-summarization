import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { sendVerificationCode } from './authExtraApi.js';
import './AuthPage.css';

const ForgotPasswordPage = () => {
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [isError, setIsError] = useState(false);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage('');
    setIsError(false);
    setLoading(true);

    try {
      const res = await sendVerificationCode(email);
      setMessage(res.message || 'Verification code sent!');
      if (res.success) {
        setIsError(false);
        localStorage.setItem('resetEmail', email);
        setTimeout(() => navigate('/verify-code'), 1500);
      } else {
        setIsError(true);
      }
    } catch {
      setMessage('Failed to send verification code.');
      setIsError(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-bg-gradient" />
      <div className="auth-bg-grid" />

      <motion.div
        className="auth-card"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <div className="auth-logo" onClick={() => navigate('/')}>
          <img
            src={`${process.env.PUBLIC_URL}/video_summarizer_icon.png`}
            alt="VideoAI"
            className="auth-logo-img"
          />
          <span className="auth-logo-text">VideoAI</span>
        </div>

        <h1 className="auth-heading">Forgot password?</h1>
        <p className="auth-subheading">Enter your email and we'll send you a verification code</p>

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="auth-field">
            <label className="auth-label">Email Address</label>
            <div className="auth-input-wrap">
              <svg className="auth-input-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
              <input
                type="email"
                placeholder="Enter your registered email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
          </div>

          <button type="submit" className="auth-submit" disabled={loading}>
            {loading ? <span className="auth-spinner" /> : 'Send Verification Code'}
          </button>

          {message && (
            <motion.div
              className={`auth-message ${isError ? 'auth-message-error' : 'auth-message-success'}`}
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
            >
              {message}
            </motion.div>
          )}
        </form>

        <p className="auth-footer-text">
          Remember your password? <a href="/login" className="auth-link">Sign in</a>
        </p>
      </motion.div>
    </div>
  );
};

export default ForgotPasswordPage;
