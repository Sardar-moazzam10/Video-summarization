import React, { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import './Navbar.css';

const Navbar = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [userName, setUserName] = useState('');
  const dropdownRef = useRef(null);
  const [scrolled, setScrolled] = useState(false);

  const hiddenPages = ['/login', '/signup', '/forgot-password', '/verify-code', '/reset-password'];

  useEffect(() => {
    const userStr = localStorage.getItem('user');
    if (userStr) {
      const parsedUser = JSON.parse(userStr);
      setIsLoggedIn(true);
      setUserName(parsedUser.username || 'Account');
    } else {
      setIsLoggedIn(false);
    }
  }, [location]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 30);
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('user');
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    setIsLoggedIn(false);
    setShowDropdown(false);
    navigate('/login');
  };

  const handleManageAccount = () => {
    const user = JSON.parse(localStorage.getItem('user'));
    setShowDropdown(false);
    if (user?.role === 'admin') {
      navigate('/admin-account-info');
    } else {
      navigate('/account-info');
    }
  };

  if (hiddenPages.includes(location.pathname)) return null;

  return (
    <nav className={`nav-bar ${scrolled ? 'nav-scrolled' : ''}`}>
      <div className="nav-inner">
        {/* Logo */}
        <div className="nav-logo" onClick={() => navigate('/')}>
          <img
            src={`${process.env.PUBLIC_URL}/video_summarizer_icon.png`}
            alt="VideoAI"
            className="nav-logo-img"
          />
          <span className="nav-logo-text">VideoAI</span>
        </div>

        {/* Center Links */}
        <div className="nav-links">
          <button
            className={`nav-link ${location.pathname === '/' ? 'nav-link-active' : ''}`}
            onClick={() => navigate('/')}
          >
            Home
          </button>
          <button
            className={`nav-link ${location.pathname === '/search-by-title' ? 'nav-link-active' : ''}`}
            onClick={() => navigate('/search-by-title')}
          >
            Search
          </button>
          <button
            className={`nav-link ${location.pathname === '/transcript-viewer' ? 'nav-link-active' : ''}`}
            onClick={() => navigate('/transcript-viewer')}
          >
            Transcripts
          </button>
          <button
            className={`nav-link ${location.pathname === '/about' ? 'nav-link-active' : ''}`}
            onClick={() => navigate('/about')}
          >
            About
          </button>
        </div>

        {/* Right Actions */}
        <div className="nav-actions">
          {!isLoggedIn ? (
            <>
              <button className="nav-link" onClick={() => navigate('/login')}>
                Log in
              </button>
              <button className="nav-btn-primary" onClick={() => navigate('/signup')}>
                Sign Up
              </button>
            </>
          ) : (
            <div className="nav-dropdown-wrap" ref={dropdownRef}>
              <button
                className="nav-user-btn"
                onClick={() => setShowDropdown(!showDropdown)}
              >
                <div className="nav-avatar">
                  {userName.charAt(0).toUpperCase()}
                </div>
                <span className="nav-username">{userName}</span>
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className={`nav-chevron ${showDropdown ? 'nav-chevron-open' : ''}`}
                >
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </button>

              <AnimatePresence>
                {showDropdown && (
                  <motion.div
                    className="nav-dropdown"
                    initial={{ opacity: 0, y: -8, scale: 0.96 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -8, scale: 0.96 }}
                    transition={{ duration: 0.15 }}
                  >
                    <button className="nav-dropdown-item" onClick={handleManageAccount}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                      Manage Account
                    </button>
                    <button className="nav-dropdown-item" onClick={() => { setShowDropdown(false); navigate('/history'); }}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                      History
                    </button>
                    <div className="nav-dropdown-divider" />
                    <button className="nav-dropdown-item nav-dropdown-danger" onClick={handleLogout}>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                      Log out
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
