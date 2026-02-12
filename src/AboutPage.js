import React from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import './AboutPage.css';

const features = [
  {
    title: 'Smart Search',
    description: 'Search for videos using simple keywords or specific titles. Our platform filters the most relevant results based on transcript content, not just titles.',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
      </svg>
    ),
  },
  {
    title: 'Deep Transcript Analysis',
    description: 'Unlike typical search tools, we analyze video transcripts word by word using advanced AI. When you search for a topic, we look inside the actual spoken content of each video.',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>
      </svg>
    ),
  },
  {
    title: 'AI-Powered Summaries',
    description: 'No time to watch an entire video? Our system creates concise AI-powered summaries based on actual spoken content, giving you key points in seconds.',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
      </svg>
    ),
  },
  {
    title: 'Multi-Video Fusion',
    description: 'Select multiple videos on any topic and let our AI merge them into one coherent podcast-style summary with unified voice narration.',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/>
      </svg>
    ),
  },
  {
    title: 'Privacy-First',
    description: 'Your search history is stored securely in your account and is never shared. Only you can see what you searched for or watched, with full control to delete anytime.',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
      </svg>
    ),
  },
];

const AboutPage = () => {
  const navigate = useNavigate();

  return (
    <div className="about-page">
      <div className="about-bg-grid" />
      <div className="about-bg-glow" />

      <div className="about-container">
        <motion.div
          className="about-header"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          <div className="about-icon-wrap">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#478BE0" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>
            </svg>
          </div>
          <h1 className="about-title">About VideoAI</h1>
          <p className="about-subtitle">Your smart companion for discovering insightful video content</p>
        </motion.div>

        <div className="about-grid">
          {features.map((feature, i) => (
            <motion.div
              key={i}
              className="about-card"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.1 + i * 0.08 }}
            >
              <div className="about-card-icon">{feature.icon}</div>
              <h3>{feature.title}</h3>
              <p>{feature.description}</p>
            </motion.div>
          ))}
        </div>

        <motion.div
          className="about-cta"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.6 }}
        >
          <p>Ready to discover your next favorite video?</p>
          <button className="about-cta-btn" onClick={() => navigate('/')}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <polygon points="5 3 19 12 5 21 5 3" fill="rgba(255,255,255,0.2)"/>
            </svg>
            Get Started
          </button>
        </motion.div>
      </div>
    </div>
  );
};

export default AboutPage;
