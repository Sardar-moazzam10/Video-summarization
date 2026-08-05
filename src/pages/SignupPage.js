import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import './AuthPage.css';
import { API_BASE_URL } from '../config/api.js';

const EyeIcon = ({ open }) =>
  open ? (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
    </svg>
  ) : (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
      <line x1="1" y1="1" x2="23" y2="23"/>
    </svg>
  );

/* Password strength helper */
const getStrength = (pwd) => {
  let score = 0;
  if (!pwd) return { score: 0, label: '', color: '' };
  if (pwd.length >= 8) score++;
  if (pwd.length >= 12) score++;
  if (/[A-Z]/.test(pwd)) score++;
  if (/[0-9]/.test(pwd)) score++;
  if (/[^A-Za-z0-9]/.test(pwd)) score++;
  if (score <= 1) return { score, label: 'Weak', color: '#ef4444' };
  if (score <= 2) return { score, label: 'Fair', color: '#f59e0b' };
  if (score <= 3) return { score, label: 'Good', color: '#3b82f6' };
  return { score, label: 'Strong', color: '#22c55e' };
};

const SignupPage = () => {
  const [formData, setFormData] = useState({
    name: '', email: '', password: '', role: 'user',
  });
  const [showPassword, setShowPassword] = useState(false);
  const [message, setMessage] = useState('');
  const [isError, setIsError] = useState(false);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleChange = (e) =>
    setFormData((prev) => ({ ...prev, [e.target.name]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setMessage('');
    setIsError(false);

    if (formData.password.length < 6) {
      setMessage('Password must be at least 6 characters.');
      setIsError(true);
      return;
    }

    setLoading(true);
    try {
      const response = await axios.post(`${API_BASE_URL}/api/v1/auth/signup`, formData);
      if (response.data.success) {
        setMessage('Account created! Redirecting to login…');
        setIsError(false);
        setTimeout(() => navigate('/login'), 1800);
      } else {
        setMessage(response.data.message || 'Signup failed.');
        setIsError(true);
      }
    } catch (err) {
      setMessage(err.response?.data?.detail || 'Signup failed. Please try again.');
      setIsError(true);
    } finally {
      setLoading(false);
    }
  };

  const strength = getStrength(formData.password);

  return (
    <div className="auth-page">
      <div className="auth-bg-gradient" />
      <div className="auth-bg-grid" />

      <motion.div className="auth-card"
        initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>

        <div className="auth-logo" onClick={() => navigate('/')}>
          <img src={`${process.env.PUBLIC_URL}/video_summarizer_icon.png`} alt="VidFusion" className="auth-logo-img" />
          <span className="auth-logo-text">VidFusion</span>
        </div>

        <h1 className="auth-heading">Create your account</h1>
        <p className="auth-subheading">Start summarizing videos for free</p>

        <form className="auth-form" onSubmit={handleSubmit}>
          {/* Full name (optional) */}
          <div className="auth-field">
            <label className="auth-label">Full Name <span className="auth-optional">(optional)</span></label>
            <div className="auth-input-wrap">
              <svg className="auth-input-icon" width="18" height="18" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
              </svg>
              <input type="text" name="name" placeholder="John Doe"
                value={formData.name} onChange={handleChange} />
            </div>
          </div>

          {/* Email */}
          <div className="auth-field">
            <label className="auth-label">Email</label>
            <div className="auth-input-wrap">
              <svg className="auth-input-icon" width="18" height="18" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2">
                <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
                <polyline points="22,6 12,13 2,6"/>
              </svg>
              <input type="email" name="email" placeholder="john@example.com"
                value={formData.email} onChange={handleChange} required />
            </div>
          </div>

          {/* Password with eye toggle + strength meter */}
          <div className="auth-field">
            <label className="auth-label">Password</label>
            <div className="auth-input-wrap">
              <svg className="auth-input-icon" width="18" height="18" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              </svg>
              <input
                type={showPassword ? 'text' : 'password'}
                name="password"
                placeholder="Create a strong password"
                value={formData.password}
                onChange={handleChange}
                required
              />
              {/* 👁 Eye toggle */}
              <button
                type="button"
                className="auth-eye-btn"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex={-1}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                <EyeIcon open={showPassword} />
              </button>
            </div>

            {/* Strength meter */}
            {formData.password && (
              <motion.div className="auth-strength" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                <div className="auth-strength-bars">
                  {[1, 2, 3, 4].map((i) => (
                    <div
                      key={i}
                      className="auth-strength-bar"
                      style={{
                        background: i <= strength.score
                          ? strength.color
                          : 'rgba(255,255,255,0.08)',
                        transition: 'background 0.3s',
                      }}
                    />
                  ))}
                </div>
                <span className="auth-strength-label" style={{ color: strength.color }}>
                  {strength.label}
                </span>
              </motion.div>
            )}
          </div>

          <button type="submit" className="auth-submit" disabled={loading}>
            {loading ? <span className="auth-spinner" /> : 'Create Account'}
          </button>

          {message && (
            <motion.div
              className={`auth-message ${isError ? 'auth-message-error' : 'auth-message-success'}`}
              initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }}>
              {message}
            </motion.div>
          )}
        </form>

        <p className="auth-footer-text">
          Already have an account?{' '}
          <Link to="/login" className="auth-link">Sign in</Link>
        </p>
      </motion.div>
    </div>
  );
};

export default SignupPage;
