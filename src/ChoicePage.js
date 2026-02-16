import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import './ChoicePage.css';

const features = [
  {
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
    ),
    title: 'Search by Title',
    description: 'Find YouTube videos by exact title and select multiple to merge into a single AI summary.',
    path: '/search-by-title',
    buttonLabel: 'Search Now',
    gradient: 'from-blue-500/20 to-cyan-500/20',
    borderColor: 'border-blue-500/30',
    iconColor: 'text-blue-400',
  },
  {
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/><path d="m9 10 2 2 4-4"/></svg>
    ),
    title: 'Search by Keywords',
    description: 'Use any keywords to discover relevant videos and build your personalized knowledge feed.',
    path: '/search-by-keywords',
    buttonLabel: 'Explore',
    gradient: 'from-violet-500/20 to-purple-500/20',
    borderColor: 'border-violet-500/30',
    iconColor: 'text-violet-400',
  },
  {
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/></svg>
    ),
    title: 'Suggested Videos',
    description: 'AI-curated recommendations based on trending topics and expert-picked content.',
    path: '/suggested-podcasts',
    buttonLabel: 'Discover',
    gradient: 'from-emerald-500/20 to-teal-500/20',
    borderColor: 'border-emerald-500/30',
    iconColor: 'text-emerald-400',
  },
  {
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
    ),
    title: 'Transcript Viewer',
    description: 'Extract full transcripts from any YouTube video with multi-language support.',
    path: '/transcript-viewer',
    buttonLabel: 'Extract',
    gradient: 'from-orange-500/20 to-amber-500/20',
    borderColor: 'border-orange-500/30',
    iconColor: 'text-orange-400',
  },
];

const stats = [
  { value: '100%', label: 'Free Stack' },
  { value: '28+', label: 'AI Voices' },
  { value: '5-20m', label: 'Duration Profiles' },
  { value: 'AI', label: 'Fusion Engine' },
];

const staggerContainer = {
  hidden: {},
  show: { transition: { staggerChildren: 0.1 } },
};

const fadeUp = {
  hidden: { opacity: 0, y: 30 },
  show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] } },
};

const TYPING_PHRASES = [
  'Into 60 Seconds of Insight',
  'Into a Concise Masterclip',
  'Into Actionable Knowledge',
  'Into Minutes of Knowledge',
];

const TERMINAL_LINES = [
  '> Analyzing 3 video transcripts...',
  '> Clustering topics with FAISS vectors',
  '> Generating chapters via Gemini 2.0 Flash',
  '> Synthesizing voice narration (28 voices)',
  '> Extracting highlights with Gemini 3 Pro',
  '> \u2713 Summary ready \u2014 4m 32s highlight reel',
];

const PIPELINE_STAGES = [
  { key: 'transcribing', label: 'Transcribe', icon: '01' },
  { key: 'analyzing',    label: 'Analyze',    icon: '02' },
  { key: 'fusing',       label: 'Fuse',       icon: '03' },
  { key: 'summarizing',  label: 'Summarize',  icon: '04' },
  { key: 'enriching',    label: 'Enrich',     icon: '05' },
  { key: 'voice',        label: 'Voice',      icon: '06' },
  { key: 'video',        label: 'Video',      icon: '07' },
  { key: 'completed',    label: 'Done',       icon: '\u2713' },
];

const ChoicePage = () => {
  const navigate = useNavigate();

  // Typing animation state
  const [displayText, setDisplayText] = useState('');
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    const currentPhrase = TYPING_PHRASES[phraseIndex];
    let timeout;

    if (!isDeleting) {
      if (displayText.length < currentPhrase.length) {
        timeout = setTimeout(() => {
          setDisplayText(currentPhrase.slice(0, displayText.length + 1));
        }, 80);
      } else {
        timeout = setTimeout(() => setIsDeleting(true), 2000);
      }
    } else {
      if (displayText.length > 0) {
        timeout = setTimeout(() => {
          setDisplayText(displayText.slice(0, -1));
        }, 40);
      } else {
        timeout = setTimeout(() => {
          setIsDeleting(false);
          setPhraseIndex((prev) => (prev + 1) % TYPING_PHRASES.length);
        }, 500);
      }
    }

    return () => clearTimeout(timeout);
  }, [displayText, phraseIndex, isDeleting]);

  // Terminal cycling state
  const [terminalIndex, setTerminalIndex] = useState(0);

  useEffect(() => {
    const isLastLine = terminalIndex === TERMINAL_LINES.length - 1;
    const delay = isLastLine ? 3000 : 2000;
    const timer = setTimeout(() => {
      setTerminalIndex((prev) => (prev + 1) % TERMINAL_LINES.length);
    }, delay);
    return () => clearTimeout(timer);
  }, [terminalIndex]);

  // Pipeline animation state
  const [activeStage, setActiveStage] = useState(0);

  useEffect(() => {
    const isCompleted = activeStage === PIPELINE_STAGES.length - 1;
    const delay = isCompleted ? 2500 : 1500;
    const timer = setTimeout(() => {
      setActiveStage((prev) => (prev + 1) % PIPELINE_STAGES.length);
    }, delay);
    return () => clearTimeout(timer);
  }, [activeStage]);

  return (
    <div className="choice-page">
      {/* Hero Section */}
      <section className="hero-section">
        {/* Decorative grid */}
        <div className="hero-grid" />

        <motion.div
          className="hero-content"
          variants={staggerContainer}
          initial="hidden"
          animate="show"
        >
          <motion.div variants={fadeUp} className="hero-badge">
            <span className="badge-dot" />
            AI-Powered Video Intelligence
          </motion.div>

          <motion.h1 variants={fadeUp} className="hero-title">
            Transform Hours of Video
            <br />
            <span className="hero-title-gradient">
              {displayText}
              <span className="typing-cursor" />
            </span>
          </motion.h1>

          <motion.p variants={fadeUp} className="hero-description">
            Search YouTube videos, merge multiple sources with AI fusion,
            and get concise summaries with natural voice narration.
            All powered by a 100% free technology stack.
          </motion.p>

          <motion.div variants={fadeUp} className="hero-actions">
            <button
              className="btn-primary-hero"
              onClick={() => navigate('/search-by-title')}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              Start Summarizing
            </button>
            <button
              className="btn-secondary-hero"
              onClick={() => navigate('/transcript-viewer')}
            >
              View Transcripts
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
            </button>
          </motion.div>

          {/* Stats bar */}
          <motion.div variants={fadeUp} className="stats-bar">
            {stats.map((stat, i) => (
              <div key={i} className="stat-item">
                <span className="stat-value">{stat.value}</span>
                <span className="stat-label">{stat.label}</span>
              </div>
            ))}
          </motion.div>
        </motion.div>

        {/* Hero visual */}
        <motion.div
          className="hero-visual"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.5, duration: 0.8 }}
        >
          <div className="visual-card">
            <div className="visual-header">
              <div className="visual-dots">
                <span /><span /><span />
              </div>
              <span className="visual-title-bar">AI Video Summarizer</span>
            </div>
            <div className="power-box-content">
              {/* Selected videos */}
              <motion.div
                className="power-thumbnails"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.6, duration: 0.5 }}
              >
                <div className="power-thumb power-thumb--blue">
                  <svg className="power-thumb-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                  <span className="power-thumb-label">Video 1</span>
                  <div className="power-thumb-check">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                  </div>
                </div>
                <div className="power-thumb power-thumb--violet">
                  <svg className="power-thumb-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                  <span className="power-thumb-label">Video 2</span>
                  <div className="power-thumb-check">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                  </div>
                </div>
                <div className="power-thumb power-thumb--emerald">
                  <svg className="power-thumb-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                  <span className="power-thumb-label">Video 3</span>
                  <div className="power-thumb-check">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                  </div>
                </div>
              </motion.div>

              {/* Duration selector */}
              <motion.div
                className="power-duration"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.85, duration: 0.4 }}
              >
                <svg className="power-duration-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                <span className="power-duration-label">Duration:</span>
                <span className="power-duration-value">10 min</span>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
              </motion.div>

              {/* Processing Pipeline */}
              <motion.div
                className="power-pipeline"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 1.0, duration: 0.5 }}
              >
                {PIPELINE_STAGES.map((stage, i) => {
                  const status = i < activeStage ? 'complete'
                               : i === activeStage ? 'active'
                               : 'pending';
                  return (
                    <React.Fragment key={stage.key}>
                      <div className={`pipeline-stage pipeline-stage--${status}`}>
                        <div className="pipeline-dot">
                          {status === 'complete' ? (
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                          ) : (
                            <span className="pipeline-dot-text">{stage.icon}</span>
                          )}
                        </div>
                        <span className="pipeline-label">{stage.label}</span>
                      </div>
                      {i < PIPELINE_STAGES.length - 1 && (
                        <div className={`pipeline-connector pipeline-connector--${i < activeStage ? 'complete' : 'pending'}`} />
                      )}
                    </React.Fragment>
                  );
                })}
              </motion.div>

              {/* Output — one cohesive video */}
              <motion.div
                className={`power-output ${activeStage === PIPELINE_STAGES.length - 1 ? 'power-output--done' : ''}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 1.4, duration: 0.5 }}
              >
                <div className="power-output-header">
                  <div className="power-output-dot" />
                  <span className="power-output-label">1 Cohesive Video</span>
                  <span className="power-output-time">10:00</span>
                </div>
                <div className="power-mini-waveform">
                  {Array.from({ length: 24 }).map((_, i) => (
                    <motion.div
                      key={i}
                      className="power-mini-bar"
                      animate={{
                        height: [3, 8 + Math.random() * 12, 3],
                      }}
                      transition={{
                        duration: 1 + Math.random() * 0.5,
                        repeat: Infinity,
                        delay: i * 0.04,
                        ease: 'easeInOut',
                      }}
                    />
                  ))}
                </div>
                <div className="power-pills">
                  <span className="power-pill">Chapters</span>
                  <span className="power-pill">Key Takeaways</span>
                  <span className="power-pill">Narration</span>
                  <span className="power-pill">Highlights</span>
                </div>
              </motion.div>
            </div>

            {/* Live Terminal */}
            <div className="power-terminal">
              <span className="power-terminal-line" key={terminalIndex}>
                {TERMINAL_LINES[terminalIndex]}
              </span>
            </div>
          </div>
        </motion.div>
      </section>

      {/* Features Section */}
      <section className="features-section">
        <motion.div
          className="features-header"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
        >
          <h2 className="features-title">Everything You Need</h2>
          <p className="features-subtitle">
            Powerful tools to search, extract, merge and listen to video content — all in one place.
          </p>
        </motion.div>

        <motion.div
          className="features-grid"
          variants={staggerContainer}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true }}
        >
          {features.map((feature, index) => (
            <motion.div
              key={index}
              variants={fadeUp}
              className={`feature-card ${feature.borderColor}`}
              onClick={() => navigate(feature.path)}
            >
              <div className={`feature-icon ${feature.iconColor}`}>
                {feature.icon}
              </div>
              <h3 className="feature-title">{feature.title}</h3>
              <p className="feature-description">{feature.description}</p>
              <div className="feature-action">
                <span>{feature.buttonLabel}</span>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* How It Works Section */}
      <section className="how-section">
        <motion.div
          className="how-header"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
        >
          <h2 className="features-title">How It Works</h2>
          <p className="features-subtitle">Three simple steps to transform video into knowledge</p>
        </motion.div>

        <motion.div
          className="steps-container"
          variants={staggerContainer}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true }}
        >
          {[
            {
              step: '01',
              title: 'Search & Select',
              desc: 'Find YouTube videos and select up to 5 to merge together.',
              icon: <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>,
            },
            {
              step: '02',
              title: 'AI Fusion',
              desc: 'Our engine clusters topics, removes duplicates, and creates a unified narrative.',
              icon: <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48 2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48 2.83-2.83"/></svg>,
            },
            {
              step: '03',
              title: 'Listen & Learn',
              desc: 'Get a text summary with optional voice narration in 28+ natural voices.',
              icon: <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>,
            },
          ].map((item, i) => (
            <motion.div key={i} variants={fadeUp} className="step-card">
              <div className="step-number">{item.step}</div>
              <div className="step-icon">{item.icon}</div>
              <h3 className="step-title">{item.title}</h3>
              <p className="step-desc">{item.desc}</p>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* CTA Section */}
      <section className="cta-section">
        <motion.div
          className="cta-content"
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
        >
          <h2 className="cta-title">
            Ready to Transform Your<br />
            <span className="hero-title-gradient">Video Experience?</span>
          </h2>
          <p className="cta-desc">
            Start summarizing YouTube videos with AI — completely free.
          </p>
          <button
            className="btn-primary-hero"
            onClick={() => navigate('/search-by-title')}
          >
            Get Started Free
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
          </button>
        </motion.div>
      </section>
    </div>
  );
};

export default ChoicePage;
