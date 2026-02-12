import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';

const VideoPlayerPage = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { video, videosList } = location.state || {};

  if (!video) {
    return (
      <div style={styles.page}>
        <div style={styles.bgGrid} />
        <div style={styles.emptyWrap}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="rgba(71,139,224,0.3)" strokeWidth="1.5">
            <polygon points="5 3 19 12 5 21 5 3"/>
          </svg>
          <p style={styles.emptyText}>No video selected</p>
          <button onClick={() => navigate('/')} style={styles.backBtn}>Go Home</button>
        </div>
      </div>
    );
  }

  const videoId = video.id?.videoId || video.id;

  return (
    <div style={styles.page}>
      <div style={styles.bgGrid} />
      <div style={styles.bgGlow} />

      <div style={styles.container}>
        {/* Main player */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          style={styles.playerCard}
        >
          <div style={styles.iframeWrap}>
            <iframe
              src={`https://www.youtube.com/embed/${videoId}`}
              title="Video Player"
              frameBorder="0"
              allow="autoplay; encrypted-media"
              allowFullScreen
              style={styles.iframe}
            />
          </div>
          {video.snippet?.title && (
            <div style={styles.playerInfo}>
              <h2 style={styles.playerTitle}>{video.snippet.title}</h2>
              {video.snippet?.channelTitle && (
                <span style={styles.channelName}>{video.snippet.channelTitle}</span>
              )}
            </div>
          )}
        </motion.div>

        {/* More videos */}
        {videosList && videosList.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.15 }}
          >
            <div style={styles.sectionHeader}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#478BE0" strokeWidth="2">
                <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/>
              </svg>
              <h3 style={styles.sectionTitle}>More on this Topic</h3>
            </div>

            <div style={styles.grid}>
              {videosList.map((vid, i) => {
                const snippet = vid.snippet;
                const id = vid.id?.videoId || vid.id;
                return (
                  <motion.div
                    key={id}
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3, delay: 0.2 + i * 0.05 }}
                    style={styles.videoCard}
                    onClick={() => navigate('/video-player', { state: { video: vid, videosList } })}
                  >
                    <div style={styles.thumbWrap}>
                      <img
                        src={snippet?.thumbnails?.medium?.url || ''}
                        alt={snippet?.title}
                        style={styles.thumbnail}
                      />
                      <div style={styles.playOverlay}>
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="white" stroke="none">
                          <polygon points="5 3 19 12 5 21 5 3"/>
                        </svg>
                      </div>
                    </div>
                    <div style={styles.cardInfo}>
                      <p style={styles.cardTitle}>{snippet?.title}</p>
                      {snippet?.channelTitle && (
                        <span style={styles.cardChannel}>{snippet.channelTitle}</span>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </div>
          </motion.div>
        )}
      </div>
    </div>
  );
};

const styles = {
  page: {
    background: '#000212',
    minHeight: '100vh',
    position: 'relative',
    overflow: 'hidden',
  },
  bgGrid: {
    position: 'absolute',
    inset: 0,
    backgroundImage: 'linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)',
    backgroundSize: '60px 60px',
    mask: 'radial-gradient(ellipse at 50% 0%, black 0%, transparent 70%)',
    WebkitMask: 'radial-gradient(ellipse at 50% 0%, black 0%, transparent 70%)',
    pointerEvents: 'none',
  },
  bgGlow: {
    position: 'absolute',
    top: '-10%',
    left: '50%',
    transform: 'translateX(-50%)',
    width: '900px',
    height: '400px',
    background: 'radial-gradient(ellipse, rgba(71,139,224,0.06) 0%, transparent 70%)',
    pointerEvents: 'none',
  },
  container: {
    position: 'relative',
    zIndex: 1,
    maxWidth: '1000px',
    margin: '0 auto',
    padding: '100px 20px 60px',
  },
  emptyWrap: {
    position: 'relative',
    zIndex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '100vh',
    gap: '12px',
  },
  emptyText: {
    color: 'rgba(255,255,255,0.4)',
    fontSize: '15px',
  },
  backBtn: {
    padding: '10px 24px',
    background: 'linear-gradient(135deg, #478BE0, #2F61A0)',
    color: '#fff',
    border: 'none',
    borderRadius: '12px',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
  },
  playerCard: {
    background: 'rgba(17,24,39,0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    overflow: 'hidden',
    marginBottom: '40px',
  },
  iframeWrap: {
    position: 'relative',
    paddingTop: '56.25%',
    width: '100%',
  },
  iframe: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    border: 'none',
  },
  playerInfo: {
    padding: '20px 24px',
  },
  playerTitle: {
    fontSize: '18px',
    fontWeight: 600,
    color: '#fff',
    margin: '0 0 6px',
    lineHeight: 1.4,
  },
  channelName: {
    fontSize: '13px',
    color: 'rgba(255,255,255,0.4)',
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    marginBottom: '20px',
  },
  sectionTitle: {
    fontSize: '18px',
    fontWeight: 600,
    color: '#fff',
    margin: 0,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
    gap: '16px',
  },
  videoCard: {
    background: 'rgba(17,24,39,0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '14px',
    overflow: 'hidden',
    cursor: 'pointer',
    transition: 'all 0.2s',
  },
  thumbWrap: {
    position: 'relative',
    width: '100%',
    paddingTop: '56.25%',
    overflow: 'hidden',
  },
  thumbnail: {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    objectFit: 'cover',
  },
  playOverlay: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'rgba(0,0,0,0.3)',
    opacity: 0,
    transition: 'opacity 0.2s',
  },
  cardInfo: {
    padding: '14px 16px',
  },
  cardTitle: {
    fontSize: '14px',
    fontWeight: 500,
    color: '#fff',
    margin: '0 0 6px',
    lineHeight: 1.4,
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
  },
  cardChannel: {
    fontSize: '12px',
    color: 'rgba(255,255,255,0.35)',
  },
};

export default VideoPlayerPage;
