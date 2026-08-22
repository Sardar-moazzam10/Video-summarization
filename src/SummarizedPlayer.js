import React, { useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import YouTube from 'react-youtube';
import './SummarizedPlayer.css';

/**
 * SummarizedPlayer — instant transcript keyword mentions.
 *
 * These timestamps are literal caption matches produced client-side by
 * searchKeywordInTranscript (youtubeTranscript.mjs); no model ranks them. The
 * AI-generated podcast lives in MergedPodcastPlayer (/merged-player/:mergeId).
 *
 * Expected router state:
 *   videoData: [{ videoId, title?, timestamps: [{ time, text }] }]
 *   keyword:   string (optional — used to highlight the matched term)
 */

const formatTime = (seconds) => new Date(seconds * 1000).toISOString().slice(11, 19);

/**
 * Normalise a video's timestamp list into moment objects.
 *
 * The current producer (handleSummarize in SearchByKeywordsPage) sends
 * { time, text }. A bare number array means the router state predates that
 * change — React Router keeps location.state in history.state, so an old tab or
 * a refresh replays the old shape. Re-running the search repairs it.
 */
const toMoments = (timestamps = []) => {
  const legacy = timestamps.some((entry) => typeof entry === 'number');
  if (legacy && process.env.NODE_ENV !== 'production') {
    console.warn(
      '[SummarizedPlayer] Received timestamps as bare numbers — this navigation ' +
        'predates the { time, text } payload. Re-run the keyword search and press ' +
        '"Best Moments" again to load transcript snippets.'
    );
  }

  return timestamps.map((entry, index) =>
    typeof entry === 'number'
      ? { index, time: entry, text: '', legacy: true }
      : {
          index,
          // `timestamp` is the field name used by searchKeywordInTranscript,
          // accepted here so a raw match object also works.
          time: Math.floor(entry?.time ?? entry?.timestamp ?? 0),
          text: entry?.text || '',
          legacy: false,
        }
  );
};

const escapeRegExp = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Wrap occurrences of `term` in <mark> so the match is visible in the snippet. */
const highlightTerm = (text, term) => {
  if (!term) return text;
  const parts = text.split(new RegExp(`(${escapeRegExp(term)})`, 'gi'));
  return parts.map((part, i) =>
    part.toLowerCase() === term.toLowerCase() ? (
      <mark key={i} className="snippet-mark">{part}</mark>
    ) : (
      <React.Fragment key={i}>{part}</React.Fragment>
    )
  );
};

const SummarizedPlayer = () => {
  const location = useLocation();
  const { videoData, keyword } = location.state || {};

  const [currentVideoIndex, setCurrentVideoIndex] = useState(0);
  const [player, setPlayer] = useState(null);
  // Committed by click — persists until another mention is chosen.
  const [activeSnippet, setActiveSnippet] = useState(null);
  // Transient preview on hover/focus; never overwrites the committed snippet.
  const [hoveredSnippet, setHoveredSnippet] = useState(null);

  const currentVideo = videoData?.[currentVideoIndex];
  const moments = useMemo(() => toMoments(currentVideo?.timestamps), [currentVideo]);

  // Hover wins while the pointer is over a button, then falls back to the click.
  const displayedSnippet = hoveredSnippet || activeSnippet;

  if (!videoData || videoData.length === 0) {
    return (
      <div className="summary-wrapper">
        <h2 className="summary-title">No mentions to show</h2>
        <p className="summary-subtitle">
          Run a keyword search first, then choose “Best Moments”.
        </p>
      </div>
    );
  }

  const handleReady = (event) => setPlayer(event.target);

  const handleSelectVideo = (index) => {
    setCurrentVideoIndex(index);
    setActiveSnippet(null);
    setHoveredSnippet(null);
  };

  const handleMomentClick = (moment) => {
    setActiveSnippet(moment);
    if (player) {
      player.seekTo(moment.time, true);
      player.playVideo?.();
    }
  };

  return (
    <div className="summary-wrapper">
      <h1 className="summary-title">Instant Keyword Mentions 🎬</h1>
      <p className="summary-subtitle">
        Exact points where {keyword ? <strong>“{keyword}”</strong> : 'your keyword'} is
        spoken — matched directly against the transcript, so it is instant and literal.
        These are not AI-selected highlights.
      </p>

      {/* Fluid 16:9 shell — the CSS pins the iframe to the wrapper, so the
          player scales instead of overflowing narrow viewports. */}
      <div className="player-shell">
        <YouTube
          videoId={currentVideo.videoId}
          opts={{ width: '100%', height: '100%', playerVars: { autoplay: 1 } }}
          className="player-frame"
          iframeClassName="player-frame"
          onReady={handleReady}
        />
      </div>

      {/* Always rendered so hovering a timestamp never shifts the layout. */}
      <div
        className={`snippet-card ${displayedSnippet ? 'is-filled' : ''}`}
        aria-live="polite"
      >
        {displayedSnippet ? (
          <>
            <div className="snippet-head">
              <span className="snippet-time">{formatTime(displayedSnippet.time)}</span>
              <span className="snippet-label">Transcript</span>
            </div>
            <p className="snippet-text">
              {displayedSnippet.text ? (
                <>“{highlightTerm(displayedSnippet.text, keyword)}”</>
              ) : (
                <span className="snippet-placeholder">
                  {displayedSnippet.legacy
                    ? 'This page was opened before snippets were added — re-run the search and press “Best Moments” again to load the transcript text.'
                    : 'No transcript line was captured for this mention.'}
                </span>
              )}
            </p>
          </>
        ) : (
          <p className="snippet-placeholder">
            Hover or tap a timestamp below to read exactly what is said at that moment.
          </p>
        )}
      </div>

      <div className="video-switch-buttons">
        {videoData.map((video, index) => (
          <button
            key={video.videoId ?? index}
            className={`video-btn ${index === currentVideoIndex ? 'active' : ''}`}
            onClick={() => handleSelectVideo(index)}
            title={video.title}
          >
            🎥 Video {index + 1}
          </button>
        ))}
      </div>

      <h3 className="moment-title">
        Jump to a Mention
        <span className="mention-count">
          {moments.length} match{moments.length !== 1 ? 'es' : ''}
        </span>
      </h3>

      <div className="timestamp-buttons">
        {moments.map((moment) => (
          <button
            key={moment.index}
            className={`timestamp-btn ${
              activeSnippet?.index === moment.index ? 'active' : ''
            }`}
            onClick={() => handleMomentClick(moment)}
            onMouseEnter={() => setHoveredSnippet(moment)}
            onMouseLeave={() => setHoveredSnippet(null)}
            onFocus={() => setHoveredSnippet(moment)}
            onBlur={() => setHoveredSnippet(null)}
            title={moment.text}
          >
            {formatTime(moment.time)}
          </button>
        ))}
      </div>
    </div>
  );
};

export default SummarizedPlayer;
