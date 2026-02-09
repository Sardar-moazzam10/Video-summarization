import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import './Background.css'; // Import background

const VideoPlayerPage = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const { video, videosList } = location.state || {};

  if (!video) {
    return <div>No video selected.</div>;
  }

  const videoId = video.id?.videoId || video.id;

  return (
    <div style={styles.container}>
  <br></br><br></br><br></br><br></br>

      <div style={styles.mainVideoContainer}>
        <iframe
          width="900"
          height="500"
          src={`https://www.youtube.com/embed/${videoId}`}
          title="Podcast Video Player"
          frameBorder="0"
          allow="autoplay; encrypted-media"
          allowFullScreen
          style={styles.iframe}
        ></iframe>
      </div>

      <h2 style={styles.moreHeading}>🎥 More on this Topic</h2>
      <div style={styles.moreContainer}>
        {videosList.map((vid) => {
          const snippet = vid.snippet;
          const id = vid.id?.videoId || vid.id;
          return (
            <div key={id} style={styles.moreItem} onClick={() => navigate('/video-player', { state: { video: vid, videosList } })}>
              <img
                src={snippet?.thumbnails?.medium?.url || ''}
                alt={snippet?.title}
                style={styles.moreThumbnail}
              />
              <p style={styles.moreTitle}>{snippet?.title}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const styles = {
  container: {
    padding: '20px',
    minHeight: '100vh',
    color: '#fff',
  },
  backButton: {
    backgroundColor: '#4F46E5',
    color: 'white',
    border: 'none',
    padding: '10px 20px',
    borderRadius: '6px',
    cursor: 'pointer',
    fontWeight: 'bold',
    marginBottom: '20px',
  },
  
  mainVideoContainer: {
    display: 'flex',
    justifyContent: 'center',
    marginBottom: '30px',
  },
  iframe: {
    borderRadius: '10px',
    maxWidth: '100%',
  },
  moreHeading: {
    fontSize: '24px',
    marginBottom: '20px',
    color: '#8B5DFF',
    textAlign: 'center',
  },
  moreContainer: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))',
    gap: '20px',
    justifyContent: 'center',
    padding: '0 10%',
  },
  moreItem: {
    cursor: 'pointer',
    textAlign: 'center',
    backgroundColor: '#222',
    padding: '10px',
    borderRadius: '10px',
  },
  moreThumbnail: {
    width: '100%',
    height: '150px',
    objectFit: 'cover',
    borderRadius: '8px',
  },
  moreTitle: {
    marginTop: '10px',
    fontSize: '14px',
    color: '#ccc',
  },
};

export default VideoPlayerPage;
