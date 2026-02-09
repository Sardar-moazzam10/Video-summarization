import React from 'react';
import './AboutPage.css';

const AboutPage = () => {
  return (
    <div className="about-wrapper">
      <div className="about-content">
        <h1>About Video Summarizer</h1>
        <p>
          <strong>Video Summarizer</strong> is your smart companion for discovering insightful video content, deep-dive discussions, and trending topics. Whether you're curious about technology, politics, spirituality, or self-improvement, Video Summarizer makes it easier to find what matters to you.
        </p>

        <h2>🔍 How It Works</h2>
        <p>
          Our platform allows you to search for videos using simple keywords or specific titles. As you search, Video Summarizer intelligently filters the most relevant results based on the content of their transcripts — not just their titles.
        </p>

        <h2>📄 Keyword Matching & Transcripts</h2>
        <p>
          Unlike typical search tools, Video Summarizer goes deeper. We analyze video transcripts word by word using advanced AI algorithms. This means when you search for a topic, we look inside the actual spoken content of each video to bring you precise results.
        </p>

        <h2>✨ AI-Powered Summaries</h2>
        <p>
          No time to watch an entire video? We've got you. Our system creates short, AI-powered summaries of video content so you can get the key points in seconds — all based on actual spoken content, not just video descriptions.
        </p>

        <h2>🔐 Privacy-First</h2>
        <p>
          We respect your privacy. Your search history is stored securely in your account and is never shared. Only you can see what you searched for or watched. You also have full control to delete it anytime.
        </p>

        <h2>💡 Get Started</h2>
        <p>
          Ready to discover your next favorite video? Just type a keyword, explore the results, and enjoy the power of video discovery — reimagined.
        </p>
      </div>
    </div>
  );
};

export default AboutPage;
