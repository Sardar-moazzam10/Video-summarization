import React, { useState, useRef } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { verifyCode } from './authExtraApi.js';
import './AuthPage.css';

const VerifyCodePage = () => {
  const [digits, setDigits] = useState(['', '', '', '', '', '']);
  const [message, setMessage] = useState('');
  const [isError, setIsError] = useState(false);
  const [loading, setLoading] = useState(false);
  const inputRefs = useRef([]);
  const navigate = useNavigate();

  const handleDigitChange = (index, value) => {
    if (value.length > 1) value = value.slice(-1);
    if (value && !/^\d$/.test(value)) return;

    const newDigits = [...digits];
    newDigits[index] = value;
    setDigits(newDigits);

    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (index, e) => {
    if (e.key === 'Backspace' && !digits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handlePaste = (e) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
    if (pasted.length === 6) {
      setDigits(pasted.split(''));
      inputRefs.current[5]?.focus();
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const code = digits.join('');
    if (code.length !== 6) {
      setMessage('Please enter all 6 digits.');
      setIsError(true);
      return;
    }

    setMessage('');
    setIsError(false);
    setLoading(true);

    try {
      const email = localStorage.getItem('resetEmail');
      const res = await verifyCode(email, code);
      setMessage(res.message || 'Code verified!');
      if (res.success) {
        setIsError(false);
        setTimeout(() => navigate('/reset-password'), 1500);
      } else {
        setIsError(true);
      }
    } catch {
      setMessage('Verification failed. Please try again.');
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

        <h1 className="auth-heading">Verify your code</h1>
        <p className="auth-subheading">
          We sent a 6-digit code to <strong style={{ color: '#478BE0' }}>{localStorage.getItem('resetEmail') || 'your email'}</strong>
        </p>

        <form className="auth-form" onSubmit={handleSubmit}>
          <div style={{
            display: 'flex',
            gap: '10px',
            justifyContent: 'center',
            marginBottom: '8px'
          }}>
            {digits.map((digit, i) => (
              <input
                key={i}
                ref={(el) => (inputRefs.current[i] = el)}
                type="text"
                inputMode="numeric"
                maxLength={1}
                value={digit}
                onChange={(e) => handleDigitChange(i, e.target.value)}
                onKeyDown={(e) => handleKeyDown(i, e)}
                onPaste={i === 0 ? handlePaste : undefined}
                style={{
                  width: '48px',
                  height: '56px',
                  textAlign: 'center',
                  fontSize: '22px',
                  fontWeight: '700',
                  background: 'rgba(255, 255, 255, 0.04)',
                  border: digit ? '1px solid rgba(71, 139, 224, 0.5)' : '1px solid rgba(255, 255, 255, 0.08)',
                  borderRadius: '12px',
                  color: '#fff',
                  outline: 'none',
                  transition: 'all 0.2s',
                  fontFamily: 'inherit',
                  caretColor: '#478BE0',
                }}
                onFocus={(e) => {
                  e.target.style.borderColor = 'rgba(71, 139, 224, 0.5)';
                  e.target.style.boxShadow = '0 0 0 3px rgba(71, 139, 224, 0.1)';
                  e.target.style.background = 'rgba(255, 255, 255, 0.06)';
                }}
                onBlur={(e) => {
                  e.target.style.borderColor = digit ? 'rgba(71, 139, 224, 0.5)' : 'rgba(255, 255, 255, 0.08)';
                  e.target.style.boxShadow = 'none';
                  e.target.style.background = 'rgba(255, 255, 255, 0.04)';
                }}
              />
            ))}
          </div>

          <button type="submit" className="auth-submit" disabled={loading}>
            {loading ? <span className="auth-spinner" /> : 'Verify Code'}
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
          Didn't receive the code? <a href="/forgot-password" className="auth-link">Resend</a>
        </p>
      </motion.div>
    </div>
  );
};

export default VerifyCodePage;
