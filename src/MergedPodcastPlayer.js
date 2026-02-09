import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';

const MergedPodcastPlayer = () => {
  const { mergeId } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState('pending');
  const [stage, setStage] = useState('Initializing...');
  const [progressPercent, setProgressPercent] = useState(0);
  const [summary, setSummary] = useState('');
  const [videoUrl, setVideoUrl] = useState('');
  const [error, setError] = useState('');
  const pollIntervalRef = useRef(null);
  const lastStatusRef = useRef('');

  const getPollInterval = (status) => {
    // Adaptive polling: slower for slow stages, faster for quick stages
    switch (status) {
      case 'transcribing':
        return 5000; // 5 seconds for transcription (slow stage)
      case 'summarizing':
        return 3000; // 3 seconds for summarization
      case 'merging':
        return 2000; // 2 seconds for merging
      default:
        return 3000; // Default 3 seconds
    }
  };

  const fetchStatus = async () => {
    try {
      const res = await axios.get(`http://localhost:5002/merge/${mergeId}`);
      const currentStatus = res.data.status;
      setStatus(currentStatus);
      setStage(res.data.stage || res.data.progress || 'Processing...');
      setProgressPercent(res.data.progress_percent || 0);
      setSummary(res.data.summary || '');

      if (currentStatus === 'completed') {
        setVideoUrl(`http://localhost:5002/merge/${mergeId}/file`);
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      } else if (currentStatus === 'error') {
        setError(res.data.error || 'An unknown error occurred.');
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      } else {
        // Update polling interval only if status changed
        if (lastStatusRef.current !== currentStatus) {
          clearInterval(pollIntervalRef.current);
          const pollInterval = getPollInterval(currentStatus);
          pollIntervalRef.current = setInterval(fetchStatus, pollInterval);
          lastStatusRef.current = currentStatus;
        }
      }
    } catch (err) {
      console.error("❌ Polling error:", err);
      setError('Connection to merge server failed.');
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  useEffect(() => {
    fetchStatus();
    // Start with 5 second interval (optimized for transcription)
    pollIntervalRef.current = setInterval(fetchStatus, 5000);
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [mergeId]);

  const handleBack = () => navigate('/search-by-title');

  // Get status icon based on current status
  const getStatusIcon = (currentStatus) => {
    switch (currentStatus) {
      case 'transcribing': return '🎤';
      case 'summarizing': return '🧠';
      case 'merging': return '🎬';
      case 'completed': return '✅';
      case 'error': return '❌';
      default: return '⏳';
    }
  };

  // Check if a step is complete, active, or pending
  const getStepStatus = (stepName) => {
    const statusOrder = ['pending', 'transcribing', 'summarizing', 'merging', 'completed'];
    const currentIdx = statusOrder.indexOf(status);
    const stepIdx = statusOrder.indexOf(stepName);

    if (stepIdx < currentIdx) return 'complete';
    if (stepIdx === currentIdx) return 'active';
    return 'pending';
  };

  const renderLoader = () => (
    <div style={styles.loaderContainer}>
      <div className="spinner" />
      <h3 style={{ color: '#8B5DFF', marginTop: '20px' }}>
        {getStatusIcon(status)} {stage}
      </h3>

      {/* Progress Bar */}
      <div style={styles.progressBarContainer}>
        <div style={{ ...styles.progressBarFill, width: `${progressPercent}%` }} />
      </div>
      <p style={{ color: '#aaa', fontSize: '14px', marginTop: '8px' }}>{progressPercent}% complete</p>

      <p style={{ color: '#aaa', maxWidth: '500px', margin: '15px auto' }}>
        We are transcribing, summarizing, and merging your selected videos into one unified masterpiece.
      </p>

      {/* Enhanced Progress Steps */}
      <div style={styles.progressSteps}>
        <div style={{
          ...styles.step,
          color: getStepStatus('transcribing') === 'active' ? '#8B5DFF' :
            getStepStatus('transcribing') === 'complete' ? '#00d26a' : '#555'
        }}>
          {getStepStatus('transcribing') === 'complete' ? '✓' : '●'} Transcribing
        </div>
        <div style={{
          ...styles.step,
          color: getStepStatus('summarizing') === 'active' ? '#8B5DFF' :
            getStepStatus('summarizing') === 'complete' ? '#00d26a' : '#555'
        }}>
          {getStepStatus('summarizing') === 'complete' ? '✓' : '●'} Summarizing
        </div>
        <div style={{
          ...styles.step,
          color: getStepStatus('merging') === 'active' ? '#8B5DFF' :
            getStepStatus('merging') === 'complete' ? '#00d26a' : '#555'
        }}>
          {getStepStatus('merging') === 'complete' ? '✓' : '●'} Merging
        </div>
      </div>
    </div>
  );

  const renderPlayer = () => (
    <div style={styles.playerSection}>
      <div style={styles.videoWrapper}>
        <video controls autoPlay style={styles.video}>
          <source src={videoUrl} type="video/mp4" />
          Your browser does not support the video tag.
        </video>
      </div>

      <div style={styles.summaryContainer}>
        <h3 style={styles.summaryTitle}>📝 AI Unified Summary</h3>
        <p style={styles.summaryText}>{summary}</p>
      </div>

      <div style={styles.actionRow}>
        <button onClick={handleBack} style={styles.backButton}>⬅ Create Another Summary</button>
      </div>
    </div>
  );

  const renderError = () => (
    <div style={styles.errorContainer}>
      <h2 style={{ color: '#ff4d4d' }}>❌ Merge Failed</h2>
      <p>{error}</p>
      <button onClick={handleBack} style={styles.button}>Back to Search</button>
    </div>
  );

  return (
    <div style={styles.container}>
      <style>
        {`
          .spinner {
            width: 60px;
            height: 60px;
            border: 6px solid #2f2f3f;
            border-top: 6px solid #8B5DFF;
            border-radius: 50%;
            animation: spin 1s linear infinite;
          }
          @keyframes spin {
            to { transform: rotate(360deg); }
          }
        `}
      </style>

      <div style={styles.header}>
        <h1 style={styles.title}>🎙️ Multi-Video AI Summarizer</h1>
        <p style={styles.subtitle}>Unified Intelligence from Multiple Sources</p>
      </div>

      {status === 'completed' && renderPlayer()}
      {['pending', 'transcribing', 'summarizing', 'merging'].includes(status) && renderLoader()}
      {status === 'error' && renderError()}
    </div>
  );
};

const styles = {
  container: {
    padding: '40px 20px',
    minHeight: '100vh',
    background: 'linear-gradient(135deg, #0a0a23 0%, #1a1a2e 100%)',
    color: '#fff',
    fontFamily: '"Segoe UI", Roboto, Helvetica, Arial, sans-serif',
  },
  header: {
    textAlign: 'center',
    marginBottom: '40px',
  },
  title: {
    fontSize: '36px',
    fontWeight: '800',
    color: '#8B5DFF',
    textShadow: '0 0 20px rgba(139, 93, 255, 0.3)',
    margin: 0,
  },
  subtitle: {
    color: '#aaa',
    fontSize: '18px',
    marginTop: '10px',
  },
  loaderContainer: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    marginTop: '60px',
  },
  progressBarContainer: {
    width: '300px',
    height: '8px',
    backgroundColor: '#2f2f3f',
    borderRadius: '4px',
    marginTop: '20px',
    overflow: 'hidden',
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: '#8B5DFF',
    borderRadius: '4px',
    transition: 'width 0.5s ease-out',
  },
  progressSteps: {
    display: 'flex',
    gap: '30px',
    marginTop: '40px',
  },
  step: {
    fontSize: '14px',
    fontWeight: 'bold',
    transition: 'color 0.3s ease',
  },
  playerSection: {
    maxWidth: '1000px',
    margin: '0 auto',
  },
  videoWrapper: {
    background: '#000',
    borderRadius: '16px',
    overflow: 'hidden',
    boxShadow: '0 20px 50px rgba(0,0,0,0.5)',
    border: '1px solid #333',
  },
  video: {
    width: '100%',
    display: 'block',
  },
  summaryContainer: {
    marginTop: '30px',
    background: 'rgba(255, 255, 255, 0.05)',
    padding: '30px',
    borderRadius: '16px',
    backdropFilter: 'blur(10px)',
    border: '1px solid rgba(255,255,255,0.1)',
    textAlign: 'left',
  },
  summaryTitle: {
    color: '#8B5DFF',
    marginTop: 0,
    fontSize: '22px',
    borderBottom: '1px solid #333',
    paddingBottom: '10px',
    marginBottom: '15px',
  },
  summaryText: {
    lineHeight: '1.8',
    fontSize: '17px',
    color: '#eee',
  },
  actionRow: {
    marginTop: '30px',
    textAlign: 'center',
  },
  backButton: {
    backgroundColor: 'transparent',
    color: '#8B5DFF',
    border: '2px solid #8B5DFF',
    padding: '12px 24px',
    borderRadius: '8px',
    cursor: 'pointer',
    fontWeight: 'bold',
    transition: 'all 0.2s ease',
  },
  errorContainer: {
    textAlign: 'center',
    marginTop: '100px',
    background: 'rgba(255,0,0,0.1)',
    padding: '40px',
    borderRadius: '12px',
    border: '1px solid #ff4d4d',
    maxWidth: '600px',
    margin: '100px auto',
  },
  button: {
    marginTop: '20px',
    padding: '10px 20px',
    backgroundColor: '#8B5DFF',
    color: '#fff',
    border: 'none',
    borderRadius: '6px',
    cursor: 'pointer',
  }
};

export default MergedPodcastPlayer;
