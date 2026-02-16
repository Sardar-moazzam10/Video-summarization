import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import axios from 'axios';

const STAGES = [
  { key: 'transcribing', label: 'Transcribing', icon: '01' },
  { key: 'analyzing', label: 'Analyzing', icon: '02' },
  { key: 'fusing', label: 'Fusing', icon: '03' },
  { key: 'summarizing', label: 'Summarizing', icon: '04' },
  { key: 'enriching', label: 'AI Enriching', icon: '05' },
  { key: 'generating_voice', label: 'Voice Gen', icon: '06' },
  { key: 'generating_video', label: 'Video Gen', icon: '07' },
];

const MergedPodcastPlayer = () => {
  const { mergeId } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState('pending');
  const [stage, setStage] = useState('Initializing...');
  const [progressPercent, setProgressPercent] = useState(0);
  const [summary, setSummary] = useState('');
  const [audioUrl, setAudioUrl] = useState('');
  const [metadata, setMetadata] = useState(null);
  const [richOutput, setRichOutput] = useState(null);
  const [videoUrl, setVideoUrl] = useState('');
  const [chatQuestion, setChatQuestion] = useState('');
  const [chatAnswer, setChatAnswer] = useState(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [error, setError] = useState('');
  const pollIntervalRef = useRef(null);
  const lastStatusRef = useRef('');

  const getPollInterval = (status) => {
    switch (status) {
      case 'transcribing': return 5000;
      case 'analyzing': return 2000;
      case 'fusing': return 3000;
      case 'summarizing': return 3000;
      case 'enriching': return 3000;
      case 'generating_voice': return 4000;
      case 'generating_video': return 5000;
      default: return 3000;
    }
  };

  const fetchStatus = async () => {
    try {
      const res = await axios.get(`http://localhost:8000/api/v1/merge/${mergeId}`);
      const currentStatus = res.data.status;
      setStatus(currentStatus);
      setStage(res.data.stage_message || 'Processing...');
      setProgressPercent(res.data.progress_percent || 0);

      if (currentStatus === 'completed') {
        const resultRes = await axios.get(`http://localhost:8000/api/v1/merge/${mergeId}/result`);
        setSummary(resultRes.data.summary_text || '');
        setMetadata(resultRes.data.metadata || null);
        setRichOutput(resultRes.data.rich_output || null);
        if (resultRes.data.audio_url) {
          setAudioUrl(`http://localhost:8000${resultRes.data.audio_url}`);
        }
        if (resultRes.data.video_url) {
          setVideoUrl(`http://localhost:8000${resultRes.data.video_url}`);
        }
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      } else if (currentStatus === 'error') {
        setError(res.data.error || 'An unknown error occurred.');
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      } else {
        if (lastStatusRef.current !== currentStatus) {
          clearInterval(pollIntervalRef.current);
          const pollInterval = getPollInterval(currentStatus);
          pollIntervalRef.current = setInterval(fetchStatus, pollInterval);
          lastStatusRef.current = currentStatus;
        }
      }
    } catch (err) {
      console.error("Polling error:", err);
      setError('Connection to merge server failed.');
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  useEffect(() => {
    // Try SSE for real-time progress, fall back to polling on error
    let eventSource = null;
    try {
      eventSource = new EventSource(
        `http://localhost:8000/api/v1/merge/${mergeId}/stream`
      );

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.error) {
            setError(data.error);
            eventSource.close();
            return;
          }
          setStatus(data.status);
          setStage(data.stage_message || 'Processing...');
          setProgressPercent(data.progress_percent || 0);

          if (data.status === 'completed') {
            axios.get(`http://localhost:8000/api/v1/merge/${mergeId}/result`)
              .then(res => {
                setSummary(res.data.summary_text || '');
                setMetadata(res.data.metadata || null);
                setRichOutput(res.data.rich_output || null);
                if (res.data.audio_url) {
                  setAudioUrl(`http://localhost:8000${res.data.audio_url}`);
                }
                if (res.data.video_url) {
                  setVideoUrl(`http://localhost:8000${res.data.video_url}`);
                }
              });
            eventSource.close();
          } else if (data.status === 'error') {
            setError(data.stage_message || 'An unknown error occurred.');
            eventSource.close();
          }
        } catch (parseErr) {
          console.error('SSE parse error:', parseErr);
        }
      };

      eventSource.onerror = () => {
        // SSE failed — fall back to polling
        eventSource.close();
        eventSource = null;
        fetchStatus();
        pollIntervalRef.current = setInterval(fetchStatus, 3000);
      };
    } catch (sseErr) {
      // SSE not supported — use polling
      fetchStatus();
      pollIntervalRef.current = setInterval(fetchStatus, 5000);
    }

    return () => {
      if (eventSource) eventSource.close();
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mergeId]);

  const handleBack = () => navigate('/search-by-title');

  const getStepStatus = (stepName) => {
    const statusOrder = ['pending', 'transcribing', 'analyzing', 'fusing', 'summarizing', 'enriching', 'generating_voice', 'generating_video', 'completed'];
    const currentIdx = statusOrder.indexOf(status);
    const stepIdx = statusOrder.indexOf(stepName);
    if (stepIdx < currentIdx) return 'complete';
    if (stepIdx === currentIdx) return 'active';
    return 'pending';
  };

  const isProcessing = ['pending', 'transcribing', 'analyzing', 'fusing', 'summarizing', 'enriching', 'generating_voice', 'generating_video'].includes(status);

  const handleChat = async () => {
    if (!chatQuestion.trim()) return;
    setChatLoading(true);
    setChatAnswer(null);
    try {
      const res = await axios.post('http://localhost:8000/api/v1/chat', {
        question: chatQuestion.trim(),
        top_k: 5,
      });
      setChatAnswer(res.data);
    } catch (err) {
      console.error('Chat error:', err);
      setChatAnswer({ answer: 'Failed to get an answer. Please try again.', sources: [] });
    } finally {
      setChatLoading(false);
    }
  };

  return (
    <div style={styles.page}>
      {/* Background Effects */}
      <div style={styles.bgGradient} />
      <div style={styles.bgGrid} />

      <div style={styles.container}>
        {/* Header */}
        <motion.div
          style={styles.header}
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <button style={styles.backLink} onClick={handleBack}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg>
            Back to Search
          </button>
          <h1 style={styles.title}>AI Video Summarizer</h1>
          <p style={styles.subtitle}>
            {isProcessing ? 'Processing your videos...' : status === 'completed' ? 'Your summary is ready' : 'Something went wrong'}
          </p>
        </motion.div>

        {/* Processing State */}
        {isProcessing && (
          <motion.div
            style={styles.processingCard}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
          >
            {/* Progress Ring */}
            <div style={styles.ringContainer}>
              <svg width="140" height="140" viewBox="0 0 140 140" style={{ transform: 'rotate(-90deg)' }}>
                <circle cx="70" cy="70" r="60" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8" />
                <circle
                  cx="70" cy="70" r="60" fill="none"
                  stroke="#478BE0"
                  strokeWidth="8"
                  strokeLinecap="round"
                  strokeDasharray={`${2 * Math.PI * 60}`}
                  strokeDashoffset={`${2 * Math.PI * 60 * (1 - progressPercent / 100)}`}
                  style={{ transition: 'stroke-dashoffset 0.5s ease' }}
                />
              </svg>
              <div style={styles.ringLabel}>
                <span style={styles.ringPercent}>{progressPercent}%</span>
              </div>
            </div>

            <p style={styles.stageMessage}>{stage}</p>

            {/* Steps */}
            <div style={styles.stepsRow}>
              {STAGES.map((s, i) => {
                const stepStatus = getStepStatus(s.key);
                return (
                  <div key={i} style={styles.step}>
                    <div style={{
                      ...styles.stepDot,
                      background: stepStatus === 'complete' ? '#22c55e'
                        : stepStatus === 'active' ? '#478BE0'
                        : 'rgba(255,255,255,0.1)',
                      boxShadow: stepStatus === 'active' ? '0 0 12px rgba(71,139,224,0.4)' : 'none',
                    }}>
                      {stepStatus === 'complete' ? (
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                      ) : (
                        <span style={{ fontSize: '10px', fontWeight: 700, color: stepStatus === 'active' ? '#fff' : 'rgba(255,255,255,0.3)' }}>{s.icon}</span>
                      )}
                    </div>
                    <span style={{
                      ...styles.stepLabel,
                      color: stepStatus === 'active' ? '#fff'
                        : stepStatus === 'complete' ? 'rgba(255,255,255,0.5)'
                        : 'rgba(255,255,255,0.25)',
                    }}>{s.label}</span>
                  </div>
                );
              })}
            </div>
          </motion.div>
        )}

        {/* Completed State */}
        {status === 'completed' && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.1 }}
          >
            {/* Stats Grid */}
            {metadata && (
              <div style={styles.statsGrid}>
                {[
                  { label: 'Topics Found', value: metadata.topics_found?.length || 0, color: '#478BE0' },
                  { label: 'Compression', value: `${((metadata.compression_ratio || 0) * 100).toFixed(0)}%`, color: '#22c55e' },
                  { label: 'Output Words', value: metadata.output_words || 0, color: '#a855f7' },
                  { label: 'Videos Merged', value: metadata.video_count || '-', color: '#f59e0b' },
                ].map((stat, i) => (
                  <motion.div
                    key={i}
                    style={styles.statCard}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.1 + i * 0.05 }}
                  >
                    <span style={{ ...styles.statValue, color: stat.color }}>{stat.value}</span>
                    <span style={styles.statLabel}>{stat.label}</span>
                  </motion.div>
                ))}
              </div>
            )}

            {/* Audio Player */}
            {audioUrl && (
              <motion.div
                style={styles.audioCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
              >
                <div style={styles.audioHeader}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#478BE0" strokeWidth="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
                  <span style={styles.audioTitle}>AI Voice Narration</span>
                </div>
                <audio controls style={styles.audioPlayer}>
                  <source src={audioUrl} type="audio/mpeg" />
                </audio>
              </motion.div>
            )}

            {/* Video Player */}
            {videoUrl && (
              <motion.div
                style={styles.videoCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.22 }}
              >
                <div style={styles.audioHeader}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#a855f7" strokeWidth="2"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
                  <span style={styles.audioTitle}>Video Highlights</span>
                </div>
                <video
                  controls
                  style={styles.videoPlayer}
                  poster=""
                >
                  <source src={videoUrl} type="video/mp4" />
                  Your browser does not support the video tag.
                </video>
              </motion.div>
            )}

            {/* TL;DR */}
            {richOutput?.tldr && (
              <motion.div
                style={styles.tldrCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.25 }}
              >
                <h3 style={styles.sectionTitle}>TL;DR</h3>
                <p style={styles.tldrText}>{richOutput.tldr}</p>
              </motion.div>
            )}

            {/* Summary */}
            <motion.div
              style={styles.summaryCard}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            >
              <h3 style={styles.sectionTitle}>AI Summary</h3>
              <p style={styles.summaryText}>{summary}</p>
            </motion.div>

            {/* Key Takeaways */}
            {richOutput?.key_takeaways?.length > 0 && (
              <motion.div
                style={styles.richCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.35 }}
              >
                <h3 style={styles.sectionTitle}>Key Takeaways</h3>
                <ul style={styles.takeawayList}>
                  {richOutput.key_takeaways.map((item, idx) => (
                    <li key={idx} style={styles.takeawayItem}>
                      <span style={styles.takeawayIcon}>&#10003;</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </motion.div>
            )}

            {/* Chapters */}
            {richOutput?.chapters?.length > 0 && (
              <motion.div
                style={styles.richCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.4 }}
              >
                <h3 style={styles.sectionTitle}>Chapters</h3>
                <div style={styles.chaptersList}>
                  {richOutput.chapters.map((ch, idx) => (
                    <div key={idx} style={styles.chapterItem}>
                      <div style={styles.chapterNumber}>{String(idx + 1).padStart(2, '0')}</div>
                      <div style={styles.chapterContent}>
                        <h4 style={styles.chapterTitle}>{ch.title}</h4>
                        <p style={styles.chapterText}>{ch.text}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}

            {/* Best Quotes */}
            {richOutput?.best_quotes?.length > 0 && (
              <motion.div
                style={styles.richCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.45 }}
              >
                <h3 style={styles.sectionTitle}>Best Quotes</h3>
                <div style={styles.quotesList}>
                  {richOutput.best_quotes.map((q, idx) => (
                    <div key={idx} style={styles.quoteItem}>
                      <p style={styles.quoteText}>"{q.text}"</p>
                      {q.speaker && <span style={styles.quoteSpeaker}>— {q.speaker}</span>}
                    </div>
                  ))}
                </div>
              </motion.div>
            )}

            {/* Who Should Watch / Who Can Skip */}
            {(richOutput?.who_should_watch || richOutput?.who_can_skip) && (
              <motion.div
                style={styles.whoGrid}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5 }}
              >
                {richOutput.who_should_watch && (
                  <div style={styles.whoCard}>
                    <h4 style={{ ...styles.whoTitle, color: '#22c55e' }}>Who Should Watch</h4>
                    <p style={styles.whoText}>{richOutput.who_should_watch}</p>
                  </div>
                )}
                {richOutput.who_can_skip && (
                  <div style={styles.whoCard}>
                    <h4 style={{ ...styles.whoTitle, color: '#f59e0b' }}>Who Can Skip</h4>
                    <p style={styles.whoText}>{richOutput.who_can_skip}</p>
                  </div>
                )}
              </motion.div>
            )}

            {/* Action Steps */}
            {richOutput?.action_steps?.length > 0 && (
              <motion.div
                style={styles.richCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.55 }}
              >
                <h3 style={styles.sectionTitle}>Action Steps</h3>
                <ol style={styles.actionStepsList}>
                  {richOutput.action_steps.map((step, idx) => (
                    <li key={idx} style={styles.actionStepItem}>{step}</li>
                  ))}
                </ol>
              </motion.div>
            )}

            {/* Topics */}
            {metadata?.topics_found?.length > 0 && (
              <motion.div
                style={styles.topicsCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.6 }}
              >
                <h3 style={styles.sectionTitle}>Key Topics</h3>
                <div style={styles.topicsWrap}>
                  {metadata.topics_found.slice(0, 10).map((topic, idx) => (
                    <span key={idx} style={styles.topicTag}>{topic}</span>
                  ))}
                </div>
              </motion.div>
            )}

            {/* Chat with Video */}
            <motion.div
              style={styles.chatCard}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.62 }}
            >
              <h3 style={styles.sectionTitle}>Chat with Video</h3>
              <p style={styles.chatSubtext}>Ask questions about the video content</p>
              <div style={styles.chatInputRow}>
                <input
                  type="text"
                  value={chatQuestion}
                  onChange={(e) => setChatQuestion(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleChat()}
                  placeholder="e.g. What are the main arguments discussed?"
                  style={styles.chatInput}
                  disabled={chatLoading}
                />
                <button
                  onClick={handleChat}
                  disabled={chatLoading || !chatQuestion.trim()}
                  style={{
                    ...styles.chatBtn,
                    opacity: chatLoading || !chatQuestion.trim() ? 0.5 : 1,
                  }}
                >
                  {chatLoading ? 'Thinking...' : 'Ask'}
                </button>
              </div>
              {chatAnswer && (
                <div style={styles.chatAnswerBox}>
                  <p style={styles.chatAnswerText}>{chatAnswer.answer}</p>
                  {chatAnswer.sources?.length > 0 && (
                    <div style={styles.chatSources}>
                      <span style={styles.chatSourcesLabel}>Sources:</span>
                      {chatAnswer.sources.map((src, i) => (
                        <span key={i} style={styles.chatSourceTag}>
                          {src.video_title || `Segment ${i + 1}`}
                          {src.timestamp != null && ` @ ${Math.floor(src.timestamp)}s`}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </motion.div>

            {/* Export Buttons */}
            <motion.div
              style={styles.exportRow}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.65 }}
            >
              <button
                style={styles.exportBtn}
                onClick={() => {
                  const text = [
                    richOutput?.tldr ? `TL;DR: ${richOutput.tldr}\n` : '',
                    `SUMMARY:\n${summary}\n`,
                    richOutput?.key_takeaways?.length ? `KEY TAKEAWAYS:\n${richOutput.key_takeaways.map((t, i) => `${i + 1}. ${t}`).join('\n')}\n` : '',
                    richOutput?.chapters?.length ? `CHAPTERS:\n${richOutput.chapters.map((c, i) => `${i + 1}. ${c.title}\n${c.text}`).join('\n\n')}\n` : '',
                    richOutput?.action_steps?.length ? `ACTION STEPS:\n${richOutput.action_steps.map((s, i) => `${i + 1}. ${s}`).join('\n')}\n` : '',
                  ].filter(Boolean).join('\n');
                  navigator.clipboard.writeText(text);
                  alert('Copied to clipboard!');
                }}
              >
                Copy Text
              </button>
              <button
                style={styles.exportBtn}
                onClick={() => {
                  const text = [
                    richOutput?.tldr ? `TL;DR: ${richOutput.tldr}\n` : '',
                    `SUMMARY:\n${summary}\n`,
                    richOutput?.key_takeaways?.length ? `KEY TAKEAWAYS:\n${richOutput.key_takeaways.map((t, i) => `${i + 1}. ${t}`).join('\n')}\n` : '',
                    richOutput?.chapters?.length ? `CHAPTERS:\n${richOutput.chapters.map((c, i) => `${i + 1}. ${c.title}\n${c.text}`).join('\n\n')}\n` : '',
                    richOutput?.action_steps?.length ? `ACTION STEPS:\n${richOutput.action_steps.map((s, i) => `${i + 1}. ${s}`).join('\n')}\n` : '',
                  ].filter(Boolean).join('\n');
                  const blob = new Blob([text], { type: 'text/plain' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = `summary_${mergeId}.txt`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}
              >
                Download TXT
              </button>
            </motion.div>

            {/* Action */}
            <motion.div
              style={styles.actionRow}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.7 }}
            >
              <button style={styles.btnPrimary} onClick={handleBack}>
                Create Another Summary
              </button>
            </motion.div>
          </motion.div>
        )}

        {/* Error State */}
        {status === 'error' && (
          <motion.div
            style={styles.errorCard}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
          >
            <div style={styles.errorIcon}>
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
            </div>
            <h3 style={styles.errorTitle}>Processing Failed</h3>
            <p style={styles.errorText}>{error}</p>
            <button style={styles.btnPrimary} onClick={handleBack}>Try Again</button>
          </motion.div>
        )}
      </div>
    </div>
  );
};

const styles = {
  page: {
    minHeight: '100vh',
    background: '#000212',
    color: '#fff',
    fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
    position: 'relative',
    overflow: 'hidden',
  },
  bgGradient: {
    position: 'absolute',
    inset: 0,
    background: 'radial-gradient(ellipse 60% 40% at 50% 20%, rgba(71, 139, 224, 0.06), transparent 70%)',
    pointerEvents: 'none',
  },
  bgGrid: {
    position: 'absolute',
    inset: 0,
    backgroundImage: 'linear-gradient(rgba(71,139,224,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(71,139,224,0.02) 1px, transparent 1px)',
    backgroundSize: '60px 60px',
    maskImage: 'radial-gradient(ellipse 70% 60% at 50% 50%, black, transparent)',
    pointerEvents: 'none',
  },
  container: {
    position: 'relative',
    zIndex: 1,
    maxWidth: '800px',
    margin: '0 auto',
    padding: '100px 24px 80px',
  },
  header: {
    textAlign: 'center',
    marginBottom: '40px',
  },
  backLink: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    background: 'none',
    border: 'none',
    color: 'rgba(255,255,255,0.4)',
    fontSize: '13px',
    fontWeight: 500,
    cursor: 'pointer',
    marginBottom: '20px',
    transition: 'color 0.2s',
    fontFamily: 'inherit',
  },
  title: {
    fontSize: '2.2rem',
    fontWeight: 800,
    letterSpacing: '-0.03em',
    margin: '0 0 8px',
    background: 'linear-gradient(135deg, #478BE0 0%, #8ecaff 100%)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    backgroundClip: 'text',
  },
  subtitle: {
    fontSize: '1rem',
    color: 'rgba(255,255,255,0.4)',
    margin: 0,
  },
  processingCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '20px',
    padding: '48px 32px',
    textAlign: 'center',
  },
  ringContainer: {
    position: 'relative',
    width: '140px',
    height: '140px',
    margin: '0 auto 24px',
  },
  ringLabel: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  ringPercent: {
    fontSize: '2rem',
    fontWeight: 800,
    color: '#fff',
  },
  stageMessage: {
    fontSize: '1rem',
    color: 'rgba(255,255,255,0.6)',
    marginBottom: '32px',
  },
  stepsRow: {
    display: 'flex',
    justifyContent: 'center',
    gap: '24px',
    flexWrap: 'wrap',
  },
  step: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '8px',
  },
  stepDot: {
    width: '32px',
    height: '32px',
    borderRadius: '10px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'all 0.3s',
  },
  stepLabel: {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    transition: 'color 0.3s',
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: '12px',
    marginBottom: '20px',
  },
  statCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '14px',
    padding: '20px 16px',
    textAlign: 'center',
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
  },
  statValue: {
    fontSize: '1.5rem',
    fontWeight: 800,
  },
  statLabel: {
    fontSize: '0.75rem',
    color: 'rgba(255,255,255,0.4)',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  audioCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '20px 24px',
    marginBottom: '20px',
  },
  audioHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    marginBottom: '14px',
  },
  audioTitle: {
    fontSize: '0.9rem',
    fontWeight: 600,
    color: '#fff',
  },
  audioPlayer: {
    width: '100%',
    borderRadius: '8px',
    outline: 'none',
  },
  summaryCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '28px',
    marginBottom: '20px',
  },
  sectionTitle: {
    fontSize: '1rem',
    fontWeight: 700,
    color: '#fff',
    margin: '0 0 16px',
    letterSpacing: '-0.01em',
  },
  summaryText: {
    fontSize: '0.95rem',
    lineHeight: 1.8,
    color: 'rgba(255,255,255,0.65)',
    margin: 0,
    whiteSpace: 'pre-wrap',
  },
  topicsCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '24px',
    marginBottom: '20px',
  },
  topicsWrap: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '8px',
  },
  topicTag: {
    padding: '6px 14px',
    background: 'rgba(71, 139, 224, 0.1)',
    border: '1px solid rgba(71, 139, 224, 0.15)',
    borderRadius: '9999px',
    fontSize: '13px',
    color: '#58adff',
    fontWeight: 500,
  },
  actionRow: {
    textAlign: 'center',
    paddingTop: '16px',
  },
  btnPrimary: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '8px',
    padding: '14px 28px',
    background: 'linear-gradient(135deg, #478BE0, #2F61A0)',
    color: '#fff',
    fontSize: '15px',
    fontWeight: 600,
    border: 'none',
    borderRadius: '12px',
    cursor: 'pointer',
    boxShadow: '0 4px 20px rgba(71,139,224,0.3)',
    transition: 'all 0.2s',
    fontFamily: 'inherit',
  },
  errorCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(239, 68, 68, 0.2)',
    borderRadius: '20px',
    padding: '48px 32px',
    textAlign: 'center',
  },
  errorIcon: {
    marginBottom: '16px',
  },
  errorTitle: {
    fontSize: '1.25rem',
    fontWeight: 700,
    color: '#fff',
    margin: '0 0 8px',
  },
  errorText: {
    fontSize: '0.9rem',
    color: 'rgba(255,255,255,0.5)',
    marginBottom: '24px',
  },
  // ===== Rich Output Styles =====
  tldrCard: {
    background: 'linear-gradient(135deg, rgba(71,139,224,0.12), rgba(71,139,224,0.04))',
    border: '1px solid rgba(71,139,224,0.2)',
    borderRadius: '16px',
    padding: '24px 28px',
    marginBottom: '20px',
  },
  tldrText: {
    fontSize: '1.1rem',
    fontWeight: 600,
    lineHeight: 1.6,
    color: '#8ecaff',
    margin: 0,
  },
  richCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '24px 28px',
    marginBottom: '20px',
  },
  takeawayList: {
    listStyle: 'none',
    padding: 0,
    margin: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  takeawayItem: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '12px',
    fontSize: '0.93rem',
    lineHeight: 1.6,
    color: 'rgba(255,255,255,0.7)',
  },
  takeawayIcon: {
    color: '#22c55e',
    fontWeight: 700,
    fontSize: '1rem',
    flexShrink: 0,
    marginTop: '2px',
  },
  chaptersList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  chapterItem: {
    display: 'flex',
    gap: '16px',
    alignItems: 'flex-start',
  },
  chapterNumber: {
    fontSize: '0.75rem',
    fontWeight: 800,
    color: '#478BE0',
    background: 'rgba(71,139,224,0.1)',
    border: '1px solid rgba(71,139,224,0.15)',
    borderRadius: '8px',
    width: '32px',
    height: '32px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  chapterContent: {
    flex: 1,
  },
  chapterTitle: {
    fontSize: '0.95rem',
    fontWeight: 700,
    color: '#fff',
    margin: '0 0 4px',
  },
  chapterText: {
    fontSize: '0.88rem',
    lineHeight: 1.6,
    color: 'rgba(255,255,255,0.55)',
    margin: 0,
  },
  quotesList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '14px',
  },
  quoteItem: {
    borderLeft: '3px solid #a855f7',
    paddingLeft: '16px',
  },
  quoteText: {
    fontSize: '0.93rem',
    lineHeight: 1.6,
    color: 'rgba(255,255,255,0.7)',
    fontStyle: 'italic',
    margin: '0 0 4px',
  },
  quoteSpeaker: {
    fontSize: '0.8rem',
    color: 'rgba(255,255,255,0.4)',
    fontWeight: 500,
  },
  whoGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '12px',
    marginBottom: '20px',
  },
  whoCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '14px',
    padding: '20px',
  },
  whoTitle: {
    fontSize: '0.85rem',
    fontWeight: 700,
    margin: '0 0 8px',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  whoText: {
    fontSize: '0.88rem',
    lineHeight: 1.6,
    color: 'rgba(255,255,255,0.6)',
    margin: 0,
  },
  actionStepsList: {
    padding: '0 0 0 20px',
    margin: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  },
  actionStepItem: {
    fontSize: '0.93rem',
    lineHeight: 1.6,
    color: 'rgba(255,255,255,0.7)',
  },
  exportRow: {
    display: 'flex',
    justifyContent: 'center',
    gap: '12px',
    marginBottom: '20px',
  },
  exportBtn: {
    padding: '10px 20px',
    background: 'rgba(255,255,255,0.06)',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: '10px',
    color: 'rgba(255,255,255,0.7)',
    fontSize: '13px',
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'all 0.2s',
    fontFamily: 'inherit',
  },
  // ===== Video Player Styles =====
  videoCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(168, 85, 247, 0.15)',
    borderRadius: '16px',
    padding: '20px 24px',
    marginBottom: '20px',
  },
  videoPlayer: {
    width: '100%',
    borderRadius: '10px',
    outline: 'none',
    backgroundColor: '#000',
    maxHeight: '450px',
  },
  // ===== Chat Styles =====
  chatCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '24px 28px',
    marginBottom: '20px',
  },
  chatSubtext: {
    fontSize: '0.85rem',
    color: 'rgba(255,255,255,0.35)',
    margin: '-8px 0 16px',
  },
  chatInputRow: {
    display: 'flex',
    gap: '10px',
  },
  chatInput: {
    flex: 1,
    padding: '12px 16px',
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: '10px',
    color: '#fff',
    fontSize: '14px',
    fontFamily: 'inherit',
    outline: 'none',
  },
  chatBtn: {
    padding: '12px 24px',
    background: 'linear-gradient(135deg, #478BE0, #2F61A0)',
    color: '#fff',
    fontSize: '14px',
    fontWeight: 600,
    border: 'none',
    borderRadius: '10px',
    cursor: 'pointer',
    fontFamily: 'inherit',
    whiteSpace: 'nowrap',
  },
  chatAnswerBox: {
    marginTop: '16px',
    padding: '16px 20px',
    background: 'rgba(71,139,224,0.06)',
    border: '1px solid rgba(71,139,224,0.12)',
    borderRadius: '12px',
  },
  chatAnswerText: {
    fontSize: '0.93rem',
    lineHeight: 1.7,
    color: 'rgba(255,255,255,0.75)',
    margin: 0,
  },
  chatSources: {
    marginTop: '12px',
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: '6px',
  },
  chatSourcesLabel: {
    fontSize: '0.75rem',
    color: 'rgba(255,255,255,0.35)',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  chatSourceTag: {
    padding: '3px 10px',
    background: 'rgba(71,139,224,0.1)',
    border: '1px solid rgba(71,139,224,0.15)',
    borderRadius: '9999px',
    fontSize: '11px',
    color: '#58adff',
    fontWeight: 500,
  },
};

export default MergedPodcastPlayer;
