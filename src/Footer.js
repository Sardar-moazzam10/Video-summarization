import React from 'react';
import { useNavigate } from 'react-router-dom';

const Footer = () => {
  const navigate = useNavigate();

  return (
    <footer style={styles.footer}>
      <div style={styles.inner}>
        <div style={styles.top}>
          {/* Brand */}
          <div style={styles.brand}>
            <div style={styles.logoRow}>
              <div style={styles.logoIcon}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polygon points="5 3 19 12 5 21 5 3" fill="rgba(71,139,224,0.3)" stroke="#478BE0"/>
                </svg>
              </div>
              <span style={styles.logoText}>VideoAI</span>
            </div>
            <p style={styles.tagline}>Transform hours of video into minutes of knowledge. Powered by AI.</p>
          </div>

          {/* Links */}
          <div style={styles.linksGroup}>
            <div style={styles.linkCol}>
              <h4 style={styles.linkTitle}>Product</h4>
              <button style={styles.linkBtn} onClick={() => navigate('/search-by-title')}>Search Videos</button>
              <button style={styles.linkBtn} onClick={() => navigate('/transcript-viewer')}>Transcripts</button>
              <button style={styles.linkBtn} onClick={() => navigate('/suggested-podcasts')}>Suggestions</button>
            </div>
            <div style={styles.linkCol}>
              <h4 style={styles.linkTitle}>Company</h4>
              <button style={styles.linkBtn} onClick={() => navigate('/about')}>About</button>
              <button style={styles.linkBtn} onClick={() => navigate('/contact')}>Contact</button>
            </div>
          </div>
        </div>

        <div style={styles.divider} />

        <div style={styles.bottom}>
          <span style={styles.copyright}>2025 VideoAI. All rights reserved.</span>
          <span style={styles.version}>v2.0</span>
        </div>
      </div>
    </footer>
  );
};

const styles = {
  footer: {
    borderTop: '1px solid rgba(255, 255, 255, 0.06)',
    background: 'rgba(0, 2, 18, 0.8)',
    padding: '48px 0 24px',
    fontFamily: "'Inter', system-ui, sans-serif",
  },
  inner: {
    maxWidth: '1200px',
    margin: '0 auto',
    padding: '0 24px',
  },
  top: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '60px',
    flexWrap: 'wrap',
  },
  brand: {
    maxWidth: '280px',
  },
  logoRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '12px',
  },
  logoIcon: {
    width: '30px',
    height: '30px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'rgba(71, 139, 224, 0.1)',
    borderRadius: '8px',
  },
  logoText: {
    fontSize: '15px',
    fontWeight: 700,
    color: '#fff',
  },
  tagline: {
    fontSize: '13.5px',
    lineHeight: 1.6,
    color: 'rgba(255, 255, 255, 0.35)',
    margin: 0,
  },
  linksGroup: {
    display: 'flex',
    gap: '60px',
  },
  linkCol: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  linkTitle: {
    fontSize: '13px',
    fontWeight: 600,
    color: 'rgba(255, 255, 255, 0.6)',
    margin: '0 0 8px',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  linkBtn: {
    background: 'none',
    border: 'none',
    color: 'rgba(255, 255, 255, 0.4)',
    fontSize: '13.5px',
    cursor: 'pointer',
    padding: '3px 0',
    textAlign: 'left',
    transition: 'color 0.2s',
    fontFamily: 'inherit',
  },
  divider: {
    height: '1px',
    background: 'rgba(255, 255, 255, 0.06)',
    margin: '32px 0 20px',
  },
  bottom: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  copyright: {
    fontSize: '12.5px',
    color: 'rgba(255, 255, 255, 0.25)',
  },
  version: {
    fontSize: '12px',
    color: 'rgba(255, 255, 255, 0.2)',
    padding: '3px 8px',
    background: 'rgba(255, 255, 255, 0.04)',
    borderRadius: '6px',
  },
};

export default Footer;
