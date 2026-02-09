import React from 'react';
import { useNavigate } from 'react-router-dom';
import './Footer.css';

const categories = [
  'Technology', 'Entertainment', 'Health', 'Business', 'Sports',
  'History', 'Education', 'Science', 'Politics', 'Music',
  'Gaming', 'Motivation', 'Self-Improvement', 'Marketing', 'Spirituality'
];

const Footer = () => {
  const navigate = useNavigate();

  const handleCategoryClick = (topic) => {
    navigate('/suggested-podcasts', { state: { topic } });
  };

  return (
    <footer className="footer">
      <div className="footer-grid">
        <div>
          <h4>Categories</h4>
          <ul>
            {categories.map((category, index) => (
              <li key={index} onClick={() => handleCategoryClick(category)}>{category}</li>
            ))}
          </ul>
        </div>

        <div>
          <h4>About</h4>
          <ul>
            <li>How It Works</li>
            <li>Our Vision</li>
            <li>Support</li>
          </ul>
        </div>

        <div>
          <h4>Community</h4>
          <ul>
            <li>Content Creators</li>
            <li>Suggest a Topic</li>
            <li>Report Issue</li>
          </ul>
        </div>

        <div>
          <h4>Company</h4>
          <ul>
            <li>Terms of Use</li>
            <li>Privacy Policy</li>
            <li>Careers</li>
          </ul>
        </div>
      </div>

      <div className="footer-bottom">
        <img src={`${process.env.PUBLIC_URL}/video_summarizer_logo.png`} alt="Video Summarizer Logo" className="footer-logo" />
        <span>© Video Summarizer 2025 – All rights reserved</span>
        <button className="version-button" disabled>v1.0.0.1</button>
      </div>
    </footer>
  );
};

export default Footer;
