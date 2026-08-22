import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { fetchVideos } from './youtubeApi.js';
import { fetchTranscript, searchKeywordInTranscript } from './youtubeTranscript.mjs';
import { API_BASE_URL } from './config/api.js';
import './VideoCard.css';

// Concrete, spoken-aloud phrases — the kind of thing that shows up in a
// transcript but almost never in a video title.
const EXAMPLE_KEYWORDS = [
  'Neural Networks',
  'Gradient Descent',
  'Climate Change',
  'Inflation rate',
];

// How many videos to fetch transcripts for at once. Transcript fetches can
// fall back to downloading audio and running Whisper locally, which is slow
// and CPU-heavy — high enough to feel fast, low enough not to choke the
// backend if several fallbacks trigger at the same time.
const TRANSCRIPT_CONCURRENCY = 4;

const SearchByKeywordsPage = () => {
  const [keyword, setKeyword] = useState('');
  const [results, setResults] = useState([]);
  const [expandedSummaries, setExpandedSummaries] = useState({});
  const [summaryLoading, setSummaryLoading] = useState({});
  const [selectedVideos, setSelectedVideos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchProgress, setSearchProgress] = useState({ done: 0, total: 0 });
  const navigate = useNavigate();
  const { query: urlQuery } = useParams();
  // Guards against overlapping runSearch calls (double-click, Enter + button
  // click racing, effects re-firing) — without it, two full 20-video batches
  // can fire back to back and trip the backend's own rate limiter.
  const searchInFlightRef = useRef(false);

  useEffect(() => {
    if (urlQuery) {
      const decoded = decodeURIComponent(urlQuery);
      setKeyword(decoded);
      // Will trigger search via the keyword effect below
      return;
    }
    const savedKeyword = sessionStorage.getItem('keyword');
    const savedResults = sessionStorage.getItem('results');
    if (savedKeyword && savedResults) {
      setKeyword(savedKeyword);
      setResults(JSON.parse(savedResults));
    }
  }, [urlQuery]);

  const fetchSummary = async (transcriptText) => {
    try {
      // Route lives under the transcript router; its body field is `text`.
      const response = await fetch(`${API_BASE_URL}/api/v1/transcript/summarize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: transcriptText }),
      });
      // A 404/422 still parses as JSON, so check status before reading `summary`.
      if (!response.ok) {
        console.error('Summary request failed:', response.status, await response.text());
        return 'Summary generation failed.';
      }
      const data = await response.json();
      return data.summary || 'No summary available.';
    } catch (err) {
      console.error('Summary error:', err);
      return 'Summary generation failed.';
    }
  };

  // Auto-run search when navigated from history with a URL query param
  useEffect(() => {
    if (urlQuery) {
      const decoded = decodeURIComponent(urlQuery);
      if (decoded.trim()) {
        runSearch(decoded);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQuery]);

  const runSearch = useCallback(async (searchTerm) => {
    const term = (searchTerm || keyword).trim();
    if (!term) return;
    if (searchInFlightRef.current) return;
    searchInFlightRef.current = true;
    setResults([]);
    setSelectedVideos([]);
    setExpandedSummaries({});
    setSummaryLoading({});
    setLoading(true);

    try {
      // Unrestricted search — exactly what the user typed, any duration.
      const videos = await fetchVideos(term);
      setSearchProgress({ done: 0, total: videos.length });

      const collected = [];

      // Transcript fetches are independent per video and each one can be slow
      // (a missing-captions video falls back to downloading audio and running
      // Whisper locally). Running them one at a time meant a single slow video
      // stalled every result behind it. A small worker pool processes several
      // videos concurrently and pushes each match into the UI as soon as it's
      // found, instead of waiting for all ~20 videos to finish.
      let nextIndex = 0;
      const worker = async () => {
        while (nextIndex < videos.length) {
          const video = videos[nextIndex++];
          try {
            const transcript = await fetchTranscript(video.id?.videoId || video.id);
            if (transcript && transcript.length > 0) {
              const keywordMatches = searchKeywordInTranscript(transcript, term);
              if (keywordMatches.length > 0) {
                const match = { video, matches: keywordMatches, transcript, summary: null };
                collected.push(match);
                setResults((prev) => [...prev, match]);
              }
            }
          } catch (err) {
            console.error('Transcript processing error:', err);
          } finally {
            setSearchProgress((prev) => ({ ...prev, done: prev.done + 1 }));
          }
        }
      };

      const workerCount = Math.min(TRANSCRIPT_CONCURRENCY, videos.length);
      await Promise.all(Array.from({ length: workerCount }, worker));

      sessionStorage.setItem('keyword', term);
      sessionStorage.setItem('results', JSON.stringify(collected));

      const username = JSON.parse(localStorage.getItem('user'))?.username;
      if (username) {
        await fetch(`${API_BASE_URL}/api/v1/auth/user-history`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username,
            type: 'search',
            query: term,
            timestamp: new Date().toISOString(),
          }),
        });
      }
    } catch (err) {
      console.error('Search error:', err);
    } finally {
      setLoading(false);
      searchInFlightRef.current = false;
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSearch = () => runSearch(keyword);

  const toggleSelect = (videoId) => {
    setSelectedVideos((prev) =>
      prev.includes(videoId) ? prev.filter((id) => id !== videoId) : [...prev, videoId]
    );
  };

  const toggleSummary = async (index) => {
    const willExpand = !expandedSummaries[index];
    setExpandedSummaries((prev) => ({ ...prev, [index]: willExpand }));
    if (!willExpand) return;

    // Summary is generated on demand, the first time a card is expanded —
    // not eagerly for every match, since most matches are never opened.
    const result = results[index];
    if (!result || result.summary || summaryLoading[index]) return;

    setSummaryLoading((prev) => ({ ...prev, [index]: true }));
    try {
      const transcriptText = result.transcript.map((e) => e.text).join(' ');
      const summary = await fetchSummary(transcriptText);
      setResults((prev) => {
        const next = prev.map((r, i) => (i === index ? { ...r, summary } : r));
        sessionStorage.setItem('results', JSON.stringify(next));
        return next;
      });
    } finally {
      setSummaryLoading((prev) => ({ ...prev, [index]: false }));
    }
  };

  const handleOpenMergePreview = () => {
    const selectedResults = results.filter((r) => selectedVideos.includes(r.video.id.videoId));
    // Parity with SearchPage / SuggestedPodcastsPage: 1 video summarizes, 2+ merges.
    if (selectedResults.length < 1) {
      alert('Please select at least 1 video to summarize.');
      return;
    }
    try {
      sessionStorage.setItem('mergePreviewSelectedResults', JSON.stringify(selectedResults));
    } catch (e) {
      console.warn('Could not persist merge preview selection:', e);
    }
    navigate('/merge-preview', { state: { selectedResults } });
  };

  const handleSummarize = () => {
    if (results.length < 3) return alert('At least 3 results are needed to summarize!');
    const term = keyword.trim();
    const topThree = results.slice(0, 3).map((r) => ({
      videoId: r.video.id.videoId,
      title: r.video.snippet?.title,
      // Each moment carries the transcript line it was matched on, so the player
      // can show what is actually said instead of a bare timecode.
      timestamps: r.matches.slice(0, 5).map((m) => ({
        time: Math.floor(m.timestamp),
        text: m.text,
      })),
    }));
    navigate('/summarized-player', { state: { videoData: topThree, keyword: term } });
  };

  return (
    <div style={styles.page}>
      <div style={styles.bgGrid} />
      <div style={styles.bgGlow} />

      <div style={styles.container}>
        {/* Hero — explains the page before the user types anything */}
        <motion.header
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-6 text-center"
        >
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-brand-500/20 bg-brand-500/10 px-3.5 py-1.5">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#478BE0" strokeWidth="2.5">
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <span className="text-[11px] font-bold uppercase tracking-[0.09em] text-brand-400">
              Transcript Search
            </span>
          </div>

          <h1 className="mb-3 text-3xl font-bold leading-tight tracking-tight text-white sm:text-4xl">
            Search Inside the Video
          </h1>

          <p className="mx-auto max-w-xl text-[15px] leading-relaxed text-white/45">
            This searches the{' '}
            <strong className="font-semibold text-white/75">actual spoken words</strong> in every
            transcript — not titles, not descriptions. You get the exact timestamps where a topic is
            discussed.
          </p>
        </motion.header>

        {/* Onboarding: what to search, and when to use this page instead of title
            search. Hidden once results exist — it has done its job by then. */}
        {results.length === 0 && !loading && (
          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.08 }}
            className="mb-6 grid gap-3 md:grid-cols-2"
          >
            {/* What to search for */}
            <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-5">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-bold text-white">
                <span className="text-base">🔍</span> What to search for
              </h2>
              <p className="text-[13.5px] leading-relaxed text-white/45">
                Specific technical terms, concepts, or topics — the kind of phrase a creator
                actually says out loud mid-episode.
              </p>

              <p className="mb-2 mt-4 text-[10.5px] font-bold uppercase tracking-[0.08em] text-white/25">
                Tap to try one
              </p>
              <div className="flex flex-wrap gap-2">
                {EXAMPLE_KEYWORDS.map((kw) => (
                  <button
                    key={kw}
                    onClick={() => { setKeyword(kw); runSearch(kw); }}
                    className="rounded-full border border-white/[0.08] bg-white/[0.03] px-3.5 py-1.5 text-[12.5px] font-medium text-white/50 transition-all duration-200 hover:border-accent-400/25 hover:bg-accent-400/10 hover:text-accent-400"
                  >
                    {kw}
                  </button>
                ))}
              </div>
            </div>

            {/* Rule of thumb */}
            <div className="rounded-2xl border border-accent-500/15 bg-accent-500/[0.05] p-5">
              <h2 className="mb-3 flex items-center gap-2 text-sm font-bold text-white">
                <span className="text-base">💡</span> Rule of thumb
              </h2>

              <div className="space-y-3">
                <div className="flex gap-3">
                  <span className="mt-0.5 flex-shrink-0 rounded-md bg-white/[0.06] px-2 py-0.5 text-[10.5px] font-bold uppercase tracking-wide text-white/40">
                    Title
                  </span>
                  <p className="text-[13px] leading-relaxed text-white/50">
                    Finding a specific show or person — e.g.{' '}
                    <span className="font-medium text-white/70">“Lex Fridman”</span>.
                  </p>
                </div>

                <div className="flex gap-3">
                  <span className="mt-0.5 flex-shrink-0 rounded-md bg-accent-500/15 px-2 py-0.5 text-[10.5px] font-bold uppercase tracking-wide text-accent-400">
                    Keyword
                  </span>
                  <p className="text-[13px] leading-relaxed text-white/50">
                    Finding a specific topic discussed{' '}
                    <span className="font-medium text-white/70">deep inside any video</span>,
                    whoever made it.
                  </p>
                </div>
              </div>

              <button
                onClick={() => navigate('/search-by-title')}
                className="mt-4 inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent-400 transition-colors hover:text-accent-300"
              >
                Switch to title search
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M5 12h14" /><path d="m12 5 7 7-7 7" />
                </svg>
              </button>
            </div>
          </motion.section>
        )}

        {/* Search bar */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          style={styles.searchCard}
        >
          <div style={styles.inputRow}>
            <div style={styles.inputWrap}>
              <svg style={styles.inputIcon} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              <input
                type="text"
                placeholder="Try searching 'Support Vector Machine'..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                style={styles.input}
              />
            </div>
            <button onClick={handleSearch} style={styles.searchBtn} disabled={loading}>
              {loading ? <span style={styles.spinner} /> : 'Search'}
            </button>
          </div>

          {/* Example chips now live in the onboarding card above, so they sit
              next to the explanation of what makes a good keyword. */}
          <p className="mb-0 mt-3 text-[12.5px] text-white/25">
            Press Enter to search — we read every transcript, so this takes a moment.
          </p>
        </motion.div>

        {/* Loading */}
        {loading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            style={styles.loadingWrap}
          >
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
              style={styles.loadingSpinner}
            />
            <span style={styles.loadingText}>
              {searchProgress.total > 0
                ? `Checking transcripts... ${searchProgress.done}/${searchProgress.total} videos`
                : 'Searching transcripts... this may take a moment'}
            </span>
          </motion.div>
        )}

        {/* Results — same vc-* card design language as Search & Discover */}
        {results.map((result, index) => {
          const videoId = result.video.id.videoId;
          const title = result.video.snippet.title;
          const channel = result.video.snippet?.channelTitle || '';
          const thumb = result.video.snippet.thumbnails?.medium?.url || result.video.snippet.thumbnails?.default?.url;
          const isSelected = selectedVideos.includes(videoId);

          return (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.1 + index * 0.06 }}
              className={`vc-card kw-card ${isSelected ? 'vc-card--selected' : ''}`}
            >
              <div className="kw-card-main">
                <div className="kw-card-thumb">
                  <img src={thumb} alt={title} />
                </div>
                <div className="vc-body kw-card-content">
                  <div className="kw-card-headrow">
                    <h3 className="vc-title" style={{ WebkitLineClamp: 1 }}>{title}</h3>
                    <span className="kw-match-badge">
                      {result.matches.length} match{result.matches.length !== 1 ? 'es' : ''}
                    </span>
                  </div>
                  {channel && <p className="vc-channel">{channel}</p>}

                  <div className="kw-matches-list">
                    {result.matches.slice(0, 5).map((m, i) => (
                      <a
                        key={i}
                        href={`https://www.youtube.com/watch?v=${videoId}&t=${Math.floor(m.timestamp)}s`}
                        target="_blank"
                        rel="noreferrer"
                        className="kw-match-link"
                        onClick={() => {
                          const username = JSON.parse(localStorage.getItem('user'))?.username;
                          if (username) {
                            fetch(`${API_BASE_URL}/api/v1/auth/user-history`, {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({
                                username,
                                type: 'watch',
                                videoId,
                                title,
                                timestamp: new Date().toISOString(),
                              }),
                            });
                          }
                        }}
                      >
                        <span className="kw-match-time">
                          {new Date(m.timestamp * 1000).toISOString().substr(11, 8)}
                        </span>
                        <span className="kw-match-text">{m.text}</span>
                      </a>
                    ))}
                  </div>
                </div>
              </div>

              {/* Footer — identical vc-* buttons to Search & Discover */}
              <div className="vc-footer">
                <button
                  className={`vc-select-btn ${isSelected ? 'vc-select-btn--active' : ''}`}
                  onClick={() => toggleSelect(videoId)}
                >
                  {isSelected ? (
                    <>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                      Selected
                    </>
                  ) : (
                    <>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/></svg>
                      Add to Merge
                    </>
                  )}
                </button>

                <div className="vc-actions">
                  <button
                    className="vc-btn vc-btn--primary"
                    onClick={() => navigate('/video-player', { state: { video: result.video, videosList: results.map((r) => r.video) } })}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                    Watch
                  </button>
                  <a
                    href={`https://www.youtube.com/watch?v=${videoId}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="vc-btn vc-btn--ghost"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M23.5 6.19a3.02 3.02 0 0 0-2.12-2.14C19.54 3.5 12 3.5 12 3.5s-7.54 0-9.38.55A3.02 3.02 0 0 0 .5 6.19C0 8.04 0 12 0 12s0 3.96.5 5.81a3.02 3.02 0 0 0 2.12 2.14C4.46 20.5 12 20.5 12 20.5s7.54 0 9.38-.55a3.02 3.02 0 0 0 2.12-2.14C24 15.96 24 12 24 12s0-3.96-.5-5.81zM9.75 15.02V8.98L15.5 12l-5.75 3.02z"/>
                    </svg>
                    YouTube
                  </a>
                </div>

                <button onClick={() => toggleSummary(index)} className="kw-summary-toggle" disabled={summaryLoading[index]}>
                  {summaryLoading[index] ? (
                    <span className="kw-summary-spinner" />
                  ) : (
                    expandedSummaries[index] ? 'Hide Summary' : 'Show Summary'
                  )}
                  {!summaryLoading[index] && (
                    <svg
                      width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                      style={{ transform: expandedSummaries[index] ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}
                    >
                      <polyline points="6 9 12 15 18 9"/>
                    </svg>
                  )}
                </button>
              </div>

              {/* Summary */}
              {expandedSummaries[index] && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  className="kw-summary-wrap"
                >
                  <p className="kw-summary-text">
                    {summaryLoading[index]
                      ? 'Generating summary…'
                      : result.summary || 'No summary available.'}
                  </p>
                </motion.div>
              )}
            </motion.div>
          );
        })}

        {/* Bottom action bar — merge takes priority when videos are selected */}
        {selectedVideos.length >= 1 ? (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            style={styles.bottomBar}
          >
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'center' }}>
              <span style={{ fontSize: 12.5, color: 'rgba(255,255,255,0.35)' }}>
                {selectedVideos.length} video{selectedVideos.length !== 1 ? 's' : ''} selected
              </span>
              <button onClick={handleOpenMergePreview} style={styles.mergeBtn}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="2" y="2" width="20" height="20" rx="2.18" ry="2.18"/><line x1="7" y1="2" x2="7" y2="22"/><line x1="17" y1="2" x2="17" y2="22"/><line x1="2" y1="12" x2="22" y2="12"/>
                </svg>
                {selectedVideos.length === 1 ? 'Preview & Summarize' : 'Preview & Merge'}
              </button>
              {results.length >= 3 && (
                <button onClick={handleSummarize} style={styles.primaryBtn}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polygon points="5 3 19 12 5 21 5 3" fill="rgba(255,255,255,0.2)"/>
                  </svg>
                  Best Moments
                </button>
              )}
            </div>
          </motion.div>
        ) : results.length >= 3 ? (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            style={{ ...styles.bottomBar, flexDirection: 'column', gap: 6 }}
          >
            <p style={{ margin: 0, fontSize: 12, color: 'rgba(255,255,255,0.3)' }}>Select a video to summarize, or use auto-select:</p>
            <button onClick={handleSummarize} style={styles.primaryBtn}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polygon points="5 3 19 12 5 21 5 3" fill="rgba(255,255,255,0.2)"/>
              </svg>
              Auto-select Best Moments
            </button>
          </motion.div>
        ) : null}

        {/* Empty state */}
        {!loading && results.length === 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            style={styles.emptyState}
          >
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="rgba(71,139,224,0.25)" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            <p style={styles.emptyText}>Search for a keyword to find matching video transcripts</p>
          </motion.div>
        )}
      </div>

      <style>{`
        .kw-card { max-width: 100%; }
        .kw-card-main {
          display: flex;
          gap: 16px;
          padding: 14px 16px 0;
        }
        .kw-card-thumb {
          position: relative;
          width: 220px;
          flex-shrink: 0;
          border-radius: 10px;
          overflow: hidden;
          aspect-ratio: 16 / 9;
        }
        .kw-card-thumb img {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
        .kw-card-content { flex: 1; min-width: 0; padding: 0; }
        .kw-card-headrow {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 10px;
        }
        .kw-match-badge {
          flex-shrink: 0;
          font-size: 11px;
          font-weight: 700;
          padding: 3px 9px;
          border-radius: 9999px;
          white-space: nowrap;
          background: rgba(139,92,246,0.12);
          border: 1px solid rgba(139,92,246,0.25);
          color: #c084fc;
        }
        .kw-matches-list {
          margin-top: 10px;
          display: flex;
          flex-direction: column;
          gap: 6px;
          max-height: 140px;
          overflow-y: auto;
          padding-right: 4px;
        }
        .kw-match-link {
          display: flex;
          gap: 10px;
          padding: 7px 9px;
          border-radius: 8px;
          background: rgba(255,255,255,0.03);
          text-decoration: none;
          transition: background 0.15s;
          align-items: flex-start;
        }
        .kw-match-link:hover { background: rgba(71,139,224,0.08); }
        .kw-match-time {
          font-size: 11.5px;
          font-weight: 600;
          color: #478BE0;
          font-family: monospace;
          white-space: nowrap;
          min-width: 60px;
          padding-top: 1px;
        }
        .kw-match-text {
          font-size: 12.5px;
          color: rgba(255,255,255,0.6);
          line-height: 1.4;
        }
        .kw-summary-toggle {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 8px 12px;
          background: rgba(255,255,255,0.04);
          border: 1px solid rgba(255,255,255,0.08);
          border-radius: 10px;
          color: rgba(255,255,255,0.55);
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
          font-family: inherit;
          transition: all 0.2s;
          width: 100%;
        }
        .kw-summary-toggle:hover { background: rgba(255,255,255,0.07); color: #fff; }
        .kw-summary-toggle:disabled { cursor: not-allowed; opacity: 0.8; }
        .kw-summary-spinner {
          display: inline-block;
          width: 13px;
          height: 13px;
          border: 2px solid rgba(255,255,255,0.25);
          border-top-color: #fff;
          border-radius: 50%;
          animation: kw-spin 0.65s linear infinite;
        }
        @keyframes kw-spin { to { transform: rotate(360deg); } }
        .kw-summary-wrap {
          margin: 0 16px 16px;
          padding: 14px 16px;
          background: rgba(71,139,224,0.05);
          border: 1px solid rgba(71,139,224,0.1);
          border-radius: 10px;
        }
        .kw-summary-text {
          font-size: 13.5px;
          line-height: 1.6;
          color: rgba(255,255,255,0.6);
          margin: 0;
          font-style: italic;
        }
        @media (max-width: 640px) {
          .kw-card-main { flex-direction: column; }
          .kw-card-thumb { width: 100%; }
        }
      `}</style>
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
    top: '-20%',
    left: '50%',
    transform: 'translateX(-50%)',
    width: '800px',
    height: '400px',
    background: 'radial-gradient(ellipse, rgba(71,139,224,0.08) 0%, transparent 70%)',
    pointerEvents: 'none',
  },
  container: {
    position: 'relative',
    zIndex: 1,
    maxWidth: '900px',
    margin: '0 auto',
    padding: '100px 20px 60px',
  },
  header: {
    textAlign: 'center',
    marginBottom: '32px',
  },
  iconWrap: {
    width: '56px',
    height: '56px',
    borderRadius: '16px',
    background: 'rgba(71,139,224,0.1)',
    border: '1px solid rgba(71,139,224,0.15)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    margin: '0 auto 16px',
  },
  title: {
    fontSize: '32px',
    fontWeight: 700,
    color: '#fff',
    margin: '0 0 8px',
    letterSpacing: '-0.02em',
  },
  subtitle: {
    fontSize: '15px',
    color: 'rgba(255,255,255,0.45)',
    margin: 0,
  },
  searchCard: {
    background: 'rgba(17,24,39,0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '20px',
    marginBottom: '24px',
  },
  inputRow: {
    display: 'flex',
    gap: '12px',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
  inputWrap: {
    flex: 1,
    minWidth: '250px',
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
  },
  inputIcon: {
    position: 'absolute',
    left: '14px',
    color: 'rgba(255,255,255,0.3)',
    pointerEvents: 'none',
  },
  input: {
    width: '100%',
    padding: '12px 14px 12px 42px',
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: '12px',
    color: '#fff',
    fontSize: '14px',
    outline: 'none',
    fontFamily: 'inherit',
    transition: 'border-color 0.2s',
    boxSizing: 'border-box',
  },
  searchBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '12px 28px',
    background: 'linear-gradient(135deg, #478BE0, #2F61A0)',
    color: '#fff',
    border: 'none',
    borderRadius: '12px',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
    whiteSpace: 'nowrap',
    boxShadow: '0 2px 10px rgba(71,139,224,0.25)',
    transition: 'all 0.2s',
  },
  spinner: {
    display: 'inline-block',
    width: '18px',
    height: '18px',
    border: '2px solid rgba(255,255,255,0.3)',
    borderTopColor: '#fff',
    borderRadius: '50%',
    animation: 'spin 0.6s linear infinite',
  },
  loadingWrap: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '12px',
    padding: '32px',
  },
  loadingSpinner: {
    width: '20px',
    height: '20px',
    border: '2px solid rgba(71,139,224,0.2)',
    borderTopColor: '#478BE0',
    borderRadius: '50%',
  },
  loadingText: {
    color: 'rgba(255,255,255,0.45)',
    fontSize: '14px',
  },
  bottomBar: {
    display: 'flex',
    justifyContent: 'center',
    marginTop: '8px',
    marginBottom: '8px',
  },
  primaryBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '13px 28px',
    background: 'linear-gradient(135deg, #478BE0, #2F61A0)',
    color: '#fff',
    border: 'none',
    borderRadius: '12px',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
    boxShadow: '0 2px 12px rgba(71,139,224,0.3)',
    transition: 'all 0.2s',
  },
  mergeBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '13px 28px',
    background: 'rgba(71,139,224,0.12)',
    border: '1px solid rgba(71,139,224,0.2)',
    color: '#478BE0',
    borderRadius: '12px',
    fontSize: '14px',
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
    transition: 'all 0.2s',
  },
  emptyState: {
    textAlign: 'center',
    padding: '60px 20px',
  },
  emptyText: {
    color: 'rgba(255,255,255,0.3)',
    fontSize: '14px',
    marginTop: '16px',
  },
};

export default SearchByKeywordsPage;
