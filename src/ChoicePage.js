import React from 'react';
import { useNavigate } from 'react-router-dom';
import './ChoicePage.css';

const cardData = [
  {
    title: 'Search by Title',
    description: 'Find episodes by exact title',
    image: '/terrific_titles.webp',
    path: '/search-by-title',
    buttonLabel: 'Search Now',
  },
  {
    title: 'Search by Keywords',
    description: 'Use any keywords to search',
    image: '/Keyword-Research.png',
    path: '/search-by-keywords',
    buttonLabel: 'Go Keywords',
  },
  {
    title: 'Suggested Videos',
    description: 'Expert recommendations',
    image: '/cowomen-UUPpu2sYV6E-unsplash.jpg',
    path: '/suggested-podcasts',
    buttonLabel: 'Discover',
  },
  {
    title: 'Transcript Viewer',
    description: 'Extract and view transcripts',
    image: '/annie-spratt-askpr0s66Rg-unsplash.jpg',
    path: '/transcript-viewer',
    buttonLabel: 'Extract Now',
  },
];

const ChoicePage = () => {
  const navigate = useNavigate();

  return (
    <div className="choice-page">
      {/* --- HERO SECTION WITH FIXED BACKGROUND --- */}
      <div className="glow-hero">
        <p className="glow-subtitle">YOUR SMART VIDEO AI COMPANION</p>
        <h1 className="glow-title">Find. Watch. Understand.</h1>
        <p className="glow-desc">Dive into a universe of video intelligence with AI-powered discovery tools.</p>
        <div className="glow-buttons">
          <button className="glow-primary" onClick={() => navigate('/search-by-title')}>
            Start Exploring
          </button>
          <button className="glow-secondary" onClick={() => navigate('/transcript-viewer')}>
            View Transcripts
          </button>
        </div>
      </div>

      {/* --- CHOICE CARDS --- */}
      <h1 className="choice-title">Our Exclusive Range of Services</h1>
      <p className="choice-subtitle">Find your favorite videos easily! Choose how you want to search:</p>
      <div className="card-container">
        {cardData.map((card, index) => (
          <div className="choice-card" key={index}>
            <div
              className="card-image"
              style={{ backgroundImage: `url(${card.image})` }}
            />
            <div className="card-content">
              <h3>{card.title}</h3>
              <p>{card.description}</p>
            </div>
            <div className="card-button-hover">
              <button onClick={() => navigate(card.path)}>{card.buttonLabel}</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default ChoicePage;
