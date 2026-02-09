import React, { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import './Navbar.css';

const Navbar = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [userName, setUserName] = useState('');
  const dropdownRef = useRef(null);
  const [scrolled, setScrolled] = useState(false);

  const hiddenPages = ['/login', '/signup', '/forgot-password'];

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
    setIsLoggedIn(false);
    navigate('/login');
  };

  const handleManageAccount = () => {
    const user = JSON.parse(localStorage.getItem('user'));
    if (user?.role === 'admin') {
      navigate('/admin-account-info');
    } else {
      navigate('/account-info');
    }
  };

  if (hiddenPages.includes(location.pathname)) return null;

  return (
    <nav className={`refined-navbar ${scrolled ? 'navbar-scrolled' : ''}`}>
      <div className="refined-navbar-inner">
        <span className="refined-navbar-logo" onClick={() => navigate('/')}>
          <img src={`${process.env.PUBLIC_URL}/video_summarizer_logo.png`} alt="Video Summarizer Logo" />
          <span className="logo-text">Video Summarizer</span>
        </span>
        <div className="refined-navbar-links">
          <span className="refined-nav-btn" onClick={() => navigate('/about')}>About</span>
          <span className="refined-nav-btn" onClick={() => navigate('/contact')}>Contact</span>
          {!isLoggedIn ? (
            <>
              <span className="refined-nav-btn" onClick={() => navigate('/login')}>Login</span>
              <span className="refined-nav-btn" onClick={() => navigate('/signup')}>Sign Up</span>
            </>
          ) : (
            <div className="refined-dropdown-wrapper" ref={dropdownRef}>
              <span onClick={() => setShowDropdown(!showDropdown)} className="refined-nav-btn">
                {userName} ▾
              </span>
              {showDropdown && (
                <div className="refined-nav-dropdown">
                  <span onClick={handleManageAccount} className="refined-nav-item">Manage Account</span>
                  <button onClick={handleLogout} className="refined-nav-item logout-btn">
                    Logout
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
