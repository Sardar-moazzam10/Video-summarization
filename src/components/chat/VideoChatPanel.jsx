import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { API_BASE_URL, authenticatedFetch } from '../../config/api.js';

const SafeAnimatePresence = AnimatePresence || (({ children }) => <>{children}</>);

export default function VideoChatPanel({ mergeId, onSeek }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [isExpanded, setIsExpanded] = useState(true);
  const messagesEndRef = useRef(null);

  // Fetch dynamic suggestions on mount
  useEffect(() => {
    let alive = true;
    if (!mergeId) return;

    const fetchSuggestions = async () => {
      try {
        const res = await authenticatedFetch(`${API_BASE_URL}/api/v1/chat/${mergeId}/suggestions`);
        if (res.ok) {
          const data = await res.json();
          if (alive && data.suggestions) {
            setSuggestions(data.suggestions);
          }
        }
      } catch (_) {
        // Fallback default suggestions
        if (alive) {
          setSuggestions([
            'What is the core conclusion of this video?',
            'Where are the practical examples or formulas explained?',
            'What are the key points of debate or disagreement?',
          ]);
        }
      }
    };

    fetchSuggestions();
    return () => { alive = false; };
  }, [mergeId]);

  useEffect(() => {
    if (messages.length > 0 && typeof messagesEndRef.current?.scrollIntoView === 'function') {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, loading]);

  const handleSend = async (queryText) => {
    const textToSend = (queryText || input).trim();
    if (!textToSend || loading) return;

    const userMessage = {
      id: Date.now(),
      sender: 'user',
      text: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);

    try {
      const res = await authenticatedFetch(`${API_BASE_URL}/api/v1/chat/${mergeId}/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: textToSend }),
      });

      if (!res.ok) {
        throw new Error('Failed to get answer');
      }

      const data = await res.json();
      const botMessage = {
        id: Date.now() + 1,
        sender: 'assistant',
        text: data.answer,
        citations: data.citations || [],
        found: data.found,
        confidence: data.confidence,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };

      setMessages((prev) => [...prev, botMessage]);
    } catch (err) {
      const errorMessage = {
        id: Date.now() + 1,
        sender: 'assistant',
        text: 'Sorry, I encountered an error while searching the video evidence. Please try again.',
        citations: [],
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <motion.div
      style={styles.card}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.35 }}
    >
      {/* Header */}
      <div style={styles.header} onClick={() => setIsExpanded(!isExpanded)}>
        <div style={styles.headerTitleWrap}>
          <span style={styles.headerIcon}>💬</span>
          <div>
            <h3 style={styles.title}>Ask VidFusion</h3>
            <p style={styles.subtitle}>Chat with your merged video transcripts • Grounded in evidence with timestamp citations</p>
          </div>
        </div>
        <button
          style={styles.toggleBtn}
          type="button"
          aria-label={isExpanded ? 'Collapse chat' : 'Expand chat'}
        >
          {isExpanded ? '▲' : '▼'}
        </button>
      </div>

      <SafeAnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
          >
            {/* Suggestions */}
            {suggestions.length > 0 && messages.length === 0 && (
              <div style={styles.suggestionsWrap}>
                <div style={styles.suggestionsLabel}>💡 Suggested questions:</div>
                <div style={styles.suggestionsList}>
                  {suggestions.slice(0, 3).map((s, idx) => (
                    <button
                      key={idx}
                      style={styles.suggestionPill}
                      onClick={() => handleSend(s)}
                      disabled={loading}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Chat Thread */}
            <div style={styles.chatArea}>
              {messages.length === 0 ? (
                <div style={styles.emptyState}>
                  <p>Ask any question about concepts, quotes, or formulas from this video.</p>
                  <p style={{ fontSize: '12px', color: 'rgba(255,255,255,0.4)', marginTop: '4px' }}>
                    VidFusion will find the exact spoken evidence and provide clickable timestamp links.
                  </p>
                </div>
              ) : (
                messages.map((m) => (
                  <div
                    key={m.id}
                    style={{
                      ...styles.messageRow,
                      justifyContent: m.sender === 'user' ? 'flex-end' : 'flex-start',
                    }}
                  >
                    <div
                      style={{
                        ...styles.bubble,
                        background: m.sender === 'user'
                          ? 'linear-gradient(135deg, #2563eb, #1d4ed8)'
                          : 'rgba(30, 41, 59, 0.85)',
                        border: m.sender === 'user'
                          ? '1px solid rgba(96, 165, 250, 0.4)'
                          : '1px solid rgba(255, 255, 255, 0.08)',
                        alignSelf: m.sender === 'user' ? 'flex-end' : 'flex-start',
                      }}
                    >
                      <div style={styles.messageText}>{m.text}</div>

                      {/* Citations */}
                      {m.citations && m.citations.length > 0 && (
                        <div style={styles.citationsContainer}>
                          <div style={styles.citationsTitle}>📍 Video Citations:</div>
                          <div style={styles.citationsList}>
                            {m.citations.map((c, i) => (
                              <div key={i} style={styles.citationBadge}>
                                <button
                                  type="button"
                                  style={styles.timestampBtn}
                                  onClick={() => onSeek && onSeek(c.timestamp_seconds)}
                                  title={`Seek video to ${c.timestamp_label}`}
                                >
                                  ▶ {c.timestamp_label}
                                </button>
                                <span style={styles.citationVideo}>{c.video_title}</span>
                                {c.video_id && (
                                  <a
                                    href={`https://www.youtube.com/watch?v=${c.video_id}&t=${Math.floor(c.timestamp_seconds)}s`}
                                    target="_blank"
                                    rel="noreferrer"
                                    style={styles.ytLink}
                                    title="Open on YouTube"
                                  >
                                    ↗
                                  </a>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      <div style={styles.timeBadge}>{m.timestamp}</div>
                    </div>
                  </div>
                ))
              )}

              {loading && (
                <div style={styles.loadingRow}>
                  <div style={styles.loadingBubble}>
                    <span style={styles.dotPulse}></span>
                    <span>Scanning video evidence…</span>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input Form */}
            <div style={styles.inputArea}>
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about this video (e.g. 'How is learning rate calculated?')..."
                style={styles.textInput}
                disabled={loading}
              />
              <button
                type="button"
                onClick={() => handleSend()}
                disabled={!input.trim() || loading}
                style={{
                  ...styles.sendBtn,
                  opacity: (!input.trim() || loading) ? 0.5 : 1,
                  cursor: (!input.trim() || loading) ? 'not-allowed' : 'pointer',
                }}
              >
                Send
              </button>
            </div>
          </motion.div>
        )}
      </SafeAnimatePresence>
    </motion.div>
  );
}

const styles = {
  card: {
    background: 'rgba(17, 24, 39, 0.75)',
    border: '1px solid rgba(255, 255, 255, 0.08)',
    borderRadius: '16px',
    padding: '24px',
    marginBottom: '28px',
    backdropFilter: 'blur(12px)',
    boxShadow: '0 8px 32px rgba(0, 0, 0, 0.25)',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    cursor: 'pointer',
    userSelect: 'none',
  },
  headerTitleWrap: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },
  headerIcon: {
    fontSize: '24px',
  },
  title: {
    margin: 0,
    fontSize: '20px',
    fontWeight: 700,
    color: '#ffffff',
    letterSpacing: '-0.01em',
  },
  subtitle: {
    margin: '4px 0 0 0',
    fontSize: '13px',
    color: '#94a3b8',
  },
  toggleBtn: {
    background: 'transparent',
    border: 'none',
    color: '#64748b',
    fontSize: '14px',
    cursor: 'pointer',
    padding: '4px 8px',
  },
  suggestionsWrap: {
    marginTop: '16px',
    paddingTop: '16px',
    borderTop: '1px solid rgba(255, 255, 255, 0.06)',
  },
  suggestionsLabel: {
    fontSize: '12px',
    fontWeight: 600,
    color: '#94a3b8',
    marginBottom: '8px',
  },
  suggestionsList: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '8px',
  },
  suggestionPill: {
    background: 'rgba(59, 130, 246, 0.1)',
    border: '1px solid rgba(59, 130, 246, 0.25)',
    borderRadius: '20px',
    padding: '6px 14px',
    color: '#93c5fd',
    fontSize: '12px',
    cursor: 'pointer',
    textAlign: 'left',
    transition: 'all 0.2s',
  },
  chatArea: {
    marginTop: '16px',
    maxHeight: '340px',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
    paddingRight: '6px',
  },
  emptyState: {
    padding: '24px',
    textAlign: 'center',
    color: '#64748b',
    fontSize: '14px',
    background: 'rgba(255, 255, 255, 0.02)',
    borderRadius: '12px',
    border: '1px dashed rgba(255, 255, 255, 0.08)',
  },
  messageRow: {
    display: 'flex',
    width: '100%',
  },
  bubble: {
    maxWidth: '82%',
    padding: '12px 16px',
    borderRadius: '14px',
    color: '#f8fafc',
    fontSize: '14px',
    lineHeight: 1.55,
  },
  messageText: {
    wordBreak: 'break-word',
  },
  citationsContainer: {
    marginTop: '10px',
    paddingTop: '8px',
    borderTop: '1px solid rgba(255, 255, 255, 0.1)',
  },
  citationsTitle: {
    fontSize: '11px',
    fontWeight: 600,
    color: '#93c5fd',
    marginBottom: '6px',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  },
  citationsList: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '8px',
  },
  citationBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    background: 'rgba(30, 58, 138, 0.45)',
    border: '1px solid rgba(96, 165, 250, 0.3)',
    borderRadius: '6px',
    padding: '3px 8px',
    fontSize: '11px',
  },
  timestampBtn: {
    background: '#2563eb',
    color: '#ffffff',
    border: 'none',
    borderRadius: '4px',
    padding: '2px 6px',
    fontSize: '10px',
    fontWeight: 700,
    cursor: 'pointer',
  },
  citationVideo: {
    color: '#cbd5e1',
    fontWeight: 500,
  },
  ytLink: {
    color: '#93c5fd',
    textDecoration: 'none',
    fontWeight: 700,
    fontSize: '12px',
  },
  timeBadge: {
    fontSize: '10px',
    color: 'rgba(255, 255, 255, 0.4)',
    textAlign: 'right',
    marginTop: '4px',
  },
  loadingRow: {
    display: 'flex',
    justifyContent: 'flex-start',
  },
  loadingBubble: {
    background: 'rgba(30, 41, 59, 0.85)',
    border: '1px solid rgba(255, 255, 255, 0.08)',
    padding: '10px 16px',
    borderRadius: '12px',
    color: '#94a3b8',
    fontSize: '13px',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  dotPulse: {
    width: '6px',
    height: '6px',
    borderRadius: '50%',
    background: '#38bdf8',
  },
  inputArea: {
    display: 'flex',
    gap: '10px',
    marginTop: '16px',
    paddingTop: '16px',
    borderTop: '1px solid rgba(255, 255, 255, 0.08)',
  },
  textInput: {
    flex: 1,
    background: 'rgba(15, 23, 42, 0.7)',
    border: '1px solid rgba(255, 255, 255, 0.12)',
    borderRadius: '10px',
    padding: '12px 16px',
    color: '#ffffff',
    fontSize: '14px',
    outline: 'none',
  },
  sendBtn: {
    background: 'linear-gradient(135deg, #3b82f6, #2563eb)',
    border: 'none',
    borderRadius: '10px',
    padding: '0 22px',
    color: '#ffffff',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
  },
};
