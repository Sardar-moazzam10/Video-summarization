import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { resetPassword } from './authExtraApi.js';
import './AuthPage.css';

const ResetPasswordPage = () => {
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [message, setMessage] = useState('');
  const [isError, setIsError] = useState(false);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (newPassword !== confirmPassword) {
      setMessage('Passwords do not match.');
      setIsError(true);
      return;
    }

    if (newPassword.length < 6) {
      setMessage('Password must be at least 6 characters.');
      setIsError(true);
      return;
    }

    setMessage('');
    setIsError(false);
    setLoading(true);

    try {
      const email = localStorage.getItem('resetEmail');
      const res = await resetPassword(email, newPassword);
      setMessage(res.message || 'Password reset successfully!');
      if (res.success) {
        setIsError(false);
        localStorage.removeItem('resetEmail');
        setTimeout(() => navigate('/login'), 2000);
      } else {
        setIsError(true);
      }
    } catch {
      setMessage('Password reset failed. Please try again.');
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

        <h1 className="auth-heading">Set new password</h1>
        <p className="auth-subheading">Create a strong password for your account</p>

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="auth-field">
            <label className="auth-label">New Password</label>
            <div className="auth-input-wrap">
              <svg className="auth-input-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              <input
                type="password"
                placeholder="Enter new password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
              />
            </div>
          </div>

          <div className="auth-field">
            <label className="auth-label">Confirm Password</label>
            <div className="auth-input-wrap">
              <svg className="auth-input-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
              <input
                type="password"
                placeholder="Confirm new password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
            </div>
          </div>

          <button type="submit" className="auth-submit" disabled={loading}>
            {loading ? <span className="auth-spinner" /> : 'Reset Password'}
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
          Back to <a href="/login" className="auth-link">Sign in</a>
        </p>
      </motion.div>
    </div>
  );
};

export default ResetPasswordPage;
