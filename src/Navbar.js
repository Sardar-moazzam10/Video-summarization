import React, { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate, Link } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import './Navbar.css';

const NAV_LINKS = [
  { to: '/', label: 'Home' },
  { to: '/search-by-title', label: 'Search' },
  { to: '/suggested-podcasts', label: 'Discover' },
  { to: '/transcript-viewer', label: 'Transcripts' },
  { to: '/about', label: 'About' },
];

const Navbar = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [showMobileMenu, setShowMobileMenu] = useState(false);
  const [userName, setUserName] = useState('');
  const [userRole, setUserRole] = useState('');
  const dropdownRef = useRef(null);
  const [scrolled, setScrolled] = useState(false);

  const hiddenPages = ['/login', '/signup', '/forgot-password', '/verify-code', '/reset-password'];

  useEffect(() => {
    const userStr = localStorage.getItem('user');
    if (userStr) {
      const u = JSON.parse(userStr);
      setIsLoggedIn(true);
      setUserName(u.username || 'Account');
      setUserRole(u.role || 'user');
    } else {
      setIsLoggedIn(false);
    }
  }, [location]);

  // Close mobile menu on route change
  useEffect(() => { setShowMobileMenu(false); setShowDropdown(false); }, [location.pathname]);

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > 30);
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  // Lock body scroll when mobile menu is open
  useEffect(() => {
    document.body.style.overflow = showMobileMenu ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [showMobileMenu]);

  const handleLogout = () => {
    localStorage.removeItem('user');
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    setIsLoggedIn(false);
    setShowDropdown(false);
    setShowMobileMenu(false);
    navigate('/login');
  };

  const handleManageAccount = () => {
    setShowDropdown(false);
    navigate(userRole === 'admin' ? '/admin-account-info' : '/account-info');
  };

  const isActive = (to) =>
    to === '/' ? location.pathname === '/' : location.pathname.startsWith(to);

  if (hiddenPages.includes(location.pathname)) return null;

  return (
    <>
      <nav className={`nav-bar ${scrolled ? 'nav-scrolled' : ''}`}>
        <div className="nav-inner">
          {/* Logo */}
          <div className="nav-logo" onClick={() => navigate('/')}>
            <img src={`${process.env.PUBLIC_URL}/video_summarizer_icon.png`} alt="VidFusion" className="nav-logo-img" />
            <span className="nav-logo-text">VidFusion</span>
          </div>

          {/* Desktop center links */}
          <div className="nav-links">
            {NAV_LINKS.map((l) => (
              <Link key={l.to} to={l.to} className={`nav-link ${isActive(l.to) ? 'nav-link-active' : ''}`}>
                {l.label}
              </Link>
            ))}
          </div>

          {/* Right actions */}
          <div className="nav-actions">
            {!isLoggedIn ? (
              <>
                <Link to="/login" className="nav-link nav-link--desktop">Log in</Link>
                <Link to="/signup" className="nav-btn-primary nav-btn-primary--desktop">Sign Up</Link>
              </>
            ) : (
              <div className="nav-dropdown-wrap" ref={dropdownRef}>
                <button className="nav-user-btn" onClick={() => setShowDropdown(!showDropdown)}>
                  <div className="nav-avatar">{userName.charAt(0).toUpperCase()}</div>
                  <span className="nav-username">{userName}</span>
                  <motion.svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2" className="nav-chevron" animate={{ rotate: showDropdown ? 180 : 0 }}>
                    <polyline points="6 9 12 15 18 9"/>
                  </motion.svg>
                </button>

                <AnimatePresence>
                  {showDropdown && (
                    <motion.div className="nav-dropdown"
                      initial={{ opacity: 0, y: -8, scale: 0.96 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: -8, scale: 0.96 }}
                      transition={{ duration: 0.15 }}>
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

            {/* Hamburger — mobile only */}
            <button
              className="nav-hamburger"
              onClick={() => setShowMobileMenu(!showMobileMenu)}
              aria-label="Toggle navigation"
            >
              <motion.span animate={{ rotate: showMobileMenu ? 45 : 0, y: showMobileMenu ? 7 : 0 }} />
              <motion.span animate={{ opacity: showMobileMenu ? 0 : 1, scaleX: showMobileMenu ? 0 : 1 }} />
              <motion.span animate={{ rotate: showMobileMenu ? -45 : 0, y: showMobileMenu ? -7 : 0 }} />
            </button>
          </div>
        </div>
      </nav>

      {/* Mobile overlay + drawer */}
      <AnimatePresence>
        {showMobileMenu && (
          <>
            <motion.div
              className="nav-mobile-backdrop"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowMobileMenu(false)}
            />
            <motion.div
              className="nav-mobile-menu"
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'spring', damping: 28, stiffness: 300 }}
            >
              <div className="nav-mobile-header">
                <div className="nav-logo">
                  <img src={`${process.env.PUBLIC_URL}/video_summarizer_icon.png`} alt="VidFusion" className="nav-logo-img" />
                  <span className="nav-logo-text">VidFusion</span>
                </div>
                <button className="nav-mobile-close" onClick={() => setShowMobileMenu(false)}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>

              <div className="nav-mobile-links">
                {NAV_LINKS.map((l) => (
                  <Link key={l.to} to={l.to}
                    className={`nav-mobile-link ${isActive(l.to) ? 'nav-mobile-link--active' : ''}`}
                    onClick={() => setShowMobileMenu(false)}>
                    {l.label}
                  </Link>
                ))}
              </div>

              <div className="nav-mobile-footer">
                {!isLoggedIn ? (
                  <>
                    <Link to="/login" className="nav-mobile-auth-btn nav-mobile-auth-btn--ghost" onClick={() => setShowMobileMenu(false)}>
                      Log in
                    </Link>
                    <Link to="/signup" className="nav-mobile-auth-btn nav-mobile-auth-btn--primary" onClick={() => setShowMobileMenu(false)}>
                      Sign Up
                    </Link>
                  </>
                ) : (
                  <>
                    <div className="nav-mobile-user">
                      <div className="nav-avatar nav-avatar--lg">{userName.charAt(0).toUpperCase()}</div>
                      <div>
                        <p className="nav-mobile-username">{userName}</p>
                        <p className="nav-mobile-role">{userRole}</p>
                      </div>
                    </div>
                    <button className="nav-mobile-auth-btn nav-mobile-auth-btn--ghost" onClick={handleManageAccount}>
                      Manage Account
                    </button>
                    <button className="nav-mobile-auth-btn nav-mobile-auth-btn--danger" onClick={handleLogout}>
                      Log out
                    </button>
                  </>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
};

export default Navbar;
