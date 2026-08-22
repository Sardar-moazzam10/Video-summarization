import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import './ChoicePage.css';

const TYPING_PHRASES = [
  'Into 60 Seconds of Insight',
  'Into a Concise Masterclip',
  'Into Actionable Knowledge',
  'Into Minutes of Knowledge',
];

const FEATURES = [
  {
    accent: '#478BE0',
    accentRgb: '71,139,224',
    iconBg: 'rgba(71,139,224,0.12)',
    tag: 'Most Popular',
    title: 'Search by Title',
    desc: 'Find any YouTube video by exact title. Select multiple sources and distill hours of content into one sharp AI brief.',
    path: '/search-by-title',
    cta: 'Search Now',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
      </svg>
    ),
    preview: (
      <div className="cp-preview cp-preview--search">
        <div className="cp-preview-bar">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
          <span>Lex Fridman #401…</span>
        </div>
        <div className="cp-preview-rows">
          {[
            { label: 'Lex Fridman #401', color: 'rgba(71,139,224,0.25)', check: true },
            { label: 'Huberman Lab #312', color: 'rgba(139,92,246,0.25)', check: true },
            { label: 'Tim Ferriss #702', color: 'rgba(16,185,129,0.25)', check: false },
          ].map((r, i) => (
            <div key={i} className="cp-preview-row">
              <div className="cp-preview-row-thumb" style={{ background: r.color }} />
              <span>{r.label}</span>
              {r.check && <span className="cp-preview-check">✓</span>}
            </div>
          ))}
        </div>
      </div>
    ),
  },
  {
    accent: '#8b5cf6',
    accentRgb: '139,92,246',
    iconBg: 'rgba(139,92,246,0.12)',
    tag: 'AI-Curated',
    title: 'Search by Keywords',
    desc: 'Type any topic and let AI surface the most relevant videos. Build a personalized knowledge feed from any domain.',
    path: '/search-by-keywords',
    cta: 'Explore Topics',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>
        <path d="m9 10 2 2 4-4"/>
      </svg>
    ),
    preview: (
      <div className="cp-preview cp-preview--pills">
        {['Machine Learning', 'Productivity', 'Deep Work', 'Neuroscience', 'Startups', 'Finance'].map((t, i) => (
          <div key={i} className={`cp-preview-pill ${i < 2 ? 'active' : ''}`}>{t}</div>
        ))}
      </div>
    ),
  },
  {
    accent: '#10b981',
    accentRgb: '16,185,129',
    iconBg: 'rgba(16,185,129,0.12)',
    tag: 'Curated Feed',
    title: 'Suggested Videos',
    desc: 'Discover trending videos curated by AI across 15+ topics. From tech to spirituality — explore what matters.',
    path: '/suggested-podcasts',
    cta: 'Discover Now',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>
        <circle cx="12" cy="13" r="3"/>
      </svg>
    ),
    preview: (
      <div className="cp-preview cp-preview--discover">
        <div className="cp-preview-topics">
          {['Technology', 'Health', 'Business', 'Science'].map((t, i) => (
            <div key={i} className={`cp-preview-topic ${i === 0 ? 'active' : ''}`}>{t}</div>
          ))}
        </div>
        <div className="cp-preview-video-list">
          {[0, 1].map(i => (
            <div key={i} className="cp-preview-video">
              <div className="cp-preview-video-thumb" style={{ background: `rgba(16,185,129,${i === 0 ? 0.25 : 0.12})` }}>
                <svg width="9" height="9" viewBox="0 0 24 24" fill="currentColor" style={{ color: '#10b981' }}><polygon points="5 3 19 12 5 21 5 3"/></svg>
              </div>
              <div className="cp-preview-video-meta">
                <div className="cp-preview-meta-line" />
                <div className="cp-preview-meta-sub" />
              </div>
            </div>
          ))}
        </div>
      </div>
    ),
  },
  {
    accent: '#f59e0b',
    accentRgb: '245,158,11',
    iconBg: 'rgba(245,158,11,0.12)',
    tag: 'Multilingual',
    title: 'Transcript Viewer',
    desc: 'Extract full searchable transcripts from any YouTube video with smart paragraph breaks in 50+ languages.',
    path: '/transcript-viewer',
    cta: 'Extract Text',
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
      </svg>
    ),
    preview: (
      <div className="cp-preview cp-preview--transcript">
        <div className="cp-preview-url">youtube.com/watch?v=dQw4w9…</div>
        <div className="cp-preview-lines">
          {[100, 85, 92, 70, 88].map((w, i) => (
            <div key={i} className="cp-preview-line" style={{
              width: `${w}%`,
              opacity: i === 2 ? 1 : 0.3,
              background: i === 2 ? 'rgba(245,158,11,0.5)' : undefined,
            }} />
          ))}
        </div>
        <div className="cp-preview-lang">🌐 English · 2,847 words</div>
      </div>
    ),
  },
];

const STEPS = [
  {
    num: '01', color: '#478BE0', colorRgb: '71,139,224',
    title: 'Search & Select',
    desc: 'Find YouTube videos by title or keyword. Pick 1–5 sources to combine.',
    icon: <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>,
  },
  {
    num: '02', color: '#8b5cf6', colorRgb: '139,92,246',
    title: 'AI Fusion',
    desc: 'Ollama + FAISS clusters topics, removes duplicates, and weaves a unified narrative.',
    icon: <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48 2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48 2.83-2.83"/></svg>,
  },
  {
    num: '03', color: '#10b981', colorRgb: '16,185,129',
    title: 'Listen & Learn',
    desc: 'Get a rich summary with the speakers\' own audio, BART chapters, and highlights.',
    icon: <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>,
  },
];

const STAT_ITEMS = [
  { value: '100%', label: 'Free Stack',  icon: '⚡' },
  { value: '100%', label: 'Real Audio',  icon: '🎙' },
  { value: '15+',  label: 'Topics',      icon: '📚' },
  { value: '7',    label: 'AI Stages',   icon: '🤖' },
];

const TECH_STACK = ['Whisper ASR', 'FAISS Vectors', 'Ollama LLM', 'SBERT Ranking', 'BART Model'];

const fadeUp = {
  hidden: { opacity: 0, y: 28 },
  show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] } },
};

const staggerContainer = {
  hidden: {},
  show: { transition: { staggerChildren: 0.1 } },
};

const ChoicePage = () => {
  const navigate = useNavigate();

  const [displayText, setDisplayText] = useState('');
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    const phrase = TYPING_PHRASES[phraseIndex];
    let t;
    if (!isDeleting) {
      if (displayText.length < phrase.length) {
        t = setTimeout(() => setDisplayText(phrase.slice(0, displayText.length + 1)), 80);
      } else {
        t = setTimeout(() => setIsDeleting(true), 2200);
      }
    } else {
      if (displayText.length > 0) {
        t = setTimeout(() => setDisplayText(displayText.slice(0, -1)), 40);
      } else {
        t = setTimeout(() => { setIsDeleting(false); setPhraseIndex(p => (p + 1) % TYPING_PHRASES.length); }, 500);
      }
    }
    return () => clearTimeout(t);
  }, [displayText, phraseIndex, isDeleting]);

  const [compressionDone, setCompressionDone] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setCompressionDone(d => !d), compressionDone ? 4000 : 5000);
    return () => clearTimeout(t);
  }, [compressionDone]);

  return (
    <div className="cp">
      {/* Ambient orbs */}
      <div className="cp-orb cp-orb--blue" />
      <div className="cp-orb cp-orb--violet" />
      <div className="cp-orb cp-orb--teal" />
      <div className="cp-grid" />

      {/* ── HERO ── */}
      <section className="cp-hero">
        <motion.div className="cp-hero-left" variants={staggerContainer} initial="hidden" animate="show">
          <motion.div variants={fadeUp} className="cp-badge">
            <span className="cp-badge-dot" />
            AI-Powered Video Intelligence
          </motion.div>

          <motion.h1 variants={fadeUp} className="cp-h1">
            Transform Hours of Video
            <span className="cp-h1-gradient">
              <span className="cp-gradient-text">{displayText}</span>
              <span className="cp-cursor" />
            </span>
          </motion.h1>

          <motion.p variants={fadeUp} className="cp-hero-desc">
            Search YouTube videos, merge multiple sources with AI fusion,
            and get concise summaries in the speakers' own voices.
            Powered by Whisper, Ollama, FAISS and BART — 100% free.
          </motion.p>

          <motion.div variants={fadeUp} className="cp-hero-actions">
            <button className="cp-btn-primary" onClick={() => navigate('/search-by-title')}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              Start Summarizing
              <span className="cp-btn-shimmer" />
            </button>
            <button className="cp-btn-ghost" onClick={() => navigate('/transcript-viewer')}>
              View Transcripts
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
            </button>
          </motion.div>

          <motion.div variants={fadeUp} className="cp-stats">
            {STAT_ITEMS.map((s, i) => (
              <div key={i} className="cp-stat">
                <span className="cp-stat-icon">{s.icon}</span>
                <span className="cp-stat-value">{s.value}</span>
                <span className="cp-stat-label">{s.label}</span>
              </div>
            ))}
          </motion.div>
        </motion.div>

        {/* Animated card */}
        <motion.div
          className="cp-hero-right"
          initial={{ opacity: 0, x: 40, scale: 0.96 }}
          animate={{ opacity: 1, x: 0, scale: 1 }}
          transition={{ delay: 0.4, duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
        >
          <div className="cp-visual-card">
            <div className="cp-card-bar">
              <div className="cp-card-dots"><span /><span /><span /></div>
              <span className="cp-card-bar-title">VidFusion</span>
            </div>

            <div className="cp-card-body">
              {/* Input sources */}
              <motion.div
                className="cp-card-sources"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.7 }}
              >
                {[
                  { label: 'Lex Fridman #401',  dur: '2h 15m', color: '#478BE0' },
                  { label: 'Huberman Lab #312', dur: '1h 30m', color: '#8b5cf6' },
                  { label: 'Tim Ferriss #702',  dur: '45m',    color: '#10b981' },
                ].map((v, i) => (
                  <div key={i} className="cp-src-row">
                    <span className="cp-src-dot" style={{ background: v.color, boxShadow: `0 0 6px ${v.color}55` }} />
                    <span className="cp-src-label">{v.label}</span>
                    <span className="cp-src-dur">{v.dur}</span>
                  </div>
                ))}
              </motion.div>

              {/* AI Processing scanning divider */}
              <motion.div
                className="cp-ai-divider"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.9 }}
              >
                <div className="cp-ai-scan-line" />
                <span className="cp-ai-label">AI Processing</span>
                <div className="cp-ai-scan-line cp-ai-scan-line--rev" />
              </motion.div>

              {/* Hero compression metric */}
              <motion.div
                className="cp-transform-hero"
                initial={{ opacity: 0, scale: 0.94 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 1.0, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
              >
                <div className="cp-transform-from">
                  <span className="cp-transform-dur">2h</span>
                  <span className="cp-transform-sub">input</span>
                </div>
                <div className="cp-transform-arrow-wrap">
                  <svg width="44" height="16" viewBox="0 0 44 16" fill="none">
                    <path d="M2 8h36M32 2l8 6-8 6" stroke="#478BE0" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <div className={`cp-transform-to${compressionDone ? ' cp-transform-to--done' : ''}`}>
                  <span className="cp-transform-dur">{compressionDone ? '12 min' : '···'}</span>
                  <span className="cp-transform-sub">summary</span>
                </div>
              </motion.div>

              {/* Saving badge */}
              <div className={`cp-transform-badge${compressionDone ? ' cp-transform-badge--done' : ''}`}>
                {compressionDone ? '⚡ You save 1h 48m' : '⚙ Compressing with AI...'}
              </div>

              {/* Output type pills */}
              <motion.div
                className="cp-card-pills"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 1.4 }}
              >
                {['📍 Chapters', '💡 Key Takeaways', '🎙 Narration', '⭐ Highlights'].map((p, i) => (
                  <span key={i} className="cp-card-pill">{p}</span>
                ))}
              </motion.div>
            </div>
          </div>
        </motion.div>
      </section>

      {/* ── TRUST BAR ── */}
      <motion.section className="cp-trust" initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={{ once: true }}>
        <p className="cp-trust-label">Powered by leading AI models</p>
        <div className="cp-trust-logos">
          {TECH_STACK.map((t, i) => (
            <div key={i} className="cp-trust-logo">
              <span className="cp-trust-dot" />
              {t}
            </div>
          ))}
        </div>
      </motion.section>

      {/* ── FEATURES ── */}
      <section className="cp-features">
        <motion.div className="cp-section-head"
          initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}>
          <span className="cp-eyebrow">Features</span>
          <h2 className="cp-h2">Everything You Need</h2>
          <p className="cp-h2-sub">Powerful tools to search, extract, merge and listen to video content — all in one place.</p>
        </motion.div>

        <motion.div className="cp-features-grid" variants={staggerContainer} initial="hidden" whileInView="show" viewport={{ once: true }}>
          {FEATURES.map((f, i) => (
            <motion.div key={i} variants={fadeUp}
              className="cp-feature-card"
              style={{ '--accent': f.accent, '--accent-rgb': f.accentRgb, '--icon-bg': f.iconBg }}
              onClick={() => navigate(f.path)}
            >
              <div className="cp-fc-top">
                <div className="cp-fc-icon">{f.icon}</div>
                <span className="cp-fc-tag">{f.tag}</span>
              </div>
              <h3 className="cp-fc-title">{f.title}</h3>
              <p className="cp-fc-desc">{f.desc}</p>
              {f.preview}
              <div className="cp-fc-cta">
                <span>{f.cta}</span>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* ── HOW IT WORKS ── */}
      <section className="cp-how">
        <motion.div className="cp-section-head"
          initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}>
          <span className="cp-eyebrow">Process</span>
          <h2 className="cp-h2">How It Works</h2>
          <p className="cp-h2-sub">Three simple steps to turn hours of video into actionable knowledge</p>
        </motion.div>

        <div className="cp-steps">
          {STEPS.map((s, i) => (
            <React.Fragment key={i}>
              <motion.div className="cp-step"
                style={{ '--step-color': s.color, '--step-rgb': s.colorRgb }}
                initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }} transition={{ delay: i * 0.15, duration: 0.6 }}>
                <div className="cp-step-num">{s.num}</div>
                <div className="cp-step-icon" style={{ color: s.color, background: `rgba(${s.colorRgb},0.1)`, border: `1px solid rgba(${s.colorRgb},0.2)` }}>
                  {s.icon}
                </div>
                <h3 className="cp-step-title">{s.title}</h3>
                <p className="cp-step-desc">{s.desc}</p>
              </motion.div>
              {i < STEPS.length - 1 && (
                <div className="cp-step-arrow">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>
                  </svg>
                </div>
              )}
            </React.Fragment>
          ))}
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="cp-cta">
        <div className="cp-cta-orb cp-cta-orb--1" />
        <div className="cp-cta-orb cp-cta-orb--2" />
        <motion.div className="cp-cta-inner"
          initial={{ opacity: 0, y: 32 }} whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }} transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}>
          <div className="cp-cta-badge">Get Started — It's 100% Free</div>
          <h2 className="cp-cta-h2">
            Ready to Transform Your
            <br />
            <span className="cp-gradient-text">Video Experience?</span>
          </h2>
          <p className="cp-cta-desc">Start summarizing YouTube videos with AI — no credit card, no limits.</p>
          <div className="cp-cta-actions">
            <button className="cp-btn-primary" onClick={() => navigate('/search-by-title')}>
              <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
              Get Started Free
              <span className="cp-btn-shimmer" />
            </button>
            <button className="cp-btn-ghost" onClick={() => navigate('/about')}>
              Learn More
            </button>
          </div>
        </motion.div>
      </section>
    </div>
  );
};

export default ChoicePage;
