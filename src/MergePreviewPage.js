import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { API_BASE_URL } from './config/api.js';
import DurationSelector from './components/merge/DurationSelector.jsx';

/**
 * MergePreviewPage — confirmation + configuration gate for POST /api/v1/merge.
 *
 * This page CONFIGURES a merge job; it does not curate one. MergeJobCreate
 * (backend/models/job.py) accepts `video_ids` plus output settings only — there
 * is no request field for user-supplied segment boundaries. Highlight selection
 * happens server-side in the fusion engine, so offering a per-moment picker here
 * would promise control the API cannot accept.
 */

// `style` values accepted by MergeJobCreate. Labels/hints are presentational.
const STYLES = [
  { value: 'educational', label: 'Educational', hint: 'Structured and explanatory' },
  { value: 'casual', label: 'Casual', hint: 'Conversational podcast tone' },
  { value: 'executive', label: 'Executive', hint: 'Tight, decision-focused' },
  { value: 'beginner', label: 'Beginner', hint: 'Plain language, no jargon' },
  { value: 'detailed', label: 'Detailed', hint: 'Full depth and nuance' },
];

// Seconds — mirrors highlight_duration_seconds (backend bounds: ge=30, le=1200).
const HIGHLIGHT_LENGTHS = [
  { value: 60, label: '1 min' },
  { value: 120, label: '2 min' },
  { value: 180, label: '3 min' },
  { value: 300, label: '5 min' },
];

// MergeJobCreate declares video_ids with max_length=10.
const MAX_VIDEOS = 10;

/** Shared pill control — used for Style and Highlight length. */
const Pill = ({ selected, disabled, onClick, children }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    className={`
      rounded-xl border-2 px-4 py-2.5 text-left transition-all duration-200
      ${disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}
      ${
        selected
          ? 'border-brand-500 bg-brand-500/10 text-white shadow-lg'
          : 'border-dark-700 bg-dark-800/50 text-dark-300 hover:border-dark-600 hover:bg-dark-800'
      }
    `}
  >
    {children}
  </button>
);

const MergePreviewPage = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const fromState = location.state?.selectedResults || [];
  const fromStorage = (() => {
    try {
      const raw = sessionStorage.getItem('mergePreviewSelectedResults');
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  })();

  const initialResults = fromState.length ? fromState : fromStorage;
  const [selectedResults] = useState(initialResults);

  // Minutes — sent verbatim as target_duration_minutes (backend: ge=2, le=20).
  const [targetMinutes, setTargetMinutes] = useState(10);
  const [selectedStyle, setSelectedStyle] = useState('educational');
  const [generateVideo, setGenerateVideo] = useState(true);
  const [highlightSeconds, setHighlightSeconds] = useState(120);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  // De-duplicated, capped at the backend's max_length. Derived, not stored.
  const videoIds = Array.from(
    new Set(selectedResults.map((r) => r.video?.id?.videoId).filter(Boolean))
  );
  const sentVideoIds = videoIds.slice(0, MAX_VIDEOS);
  const droppedCount = videoIds.length - sentVideoIds.length;

  const handleBack = () => navigate(-1);

  const handleConfirmMerge = async () => {
    if (sentVideoIds.length < 1) {
      setErrorMsg('Please go back and select at least one video.');
      return;
    }

    setErrorMsg('');
    setIsSubmitting(true);

    try {
      const token = localStorage.getItem('access_token') || '';
      const res = await fetch(`${API_BASE_URL}/api/v1/merge`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          video_ids: sentVideoIds,
          target_duration_minutes: targetMinutes,
          generate_audio: true,
          generate_video: generateVideo,
          highlight_duration_seconds: highlightSeconds,
          style: selectedStyle,
        }),
      });

      const data = await res.json();
      if (res.ok && data.job_id) {
        navigate(`/merged-player/${data.job_id}`);
      } else {
        setErrorMsg(
          typeof data.detail === 'string'
            ? data.detail
            : 'Server error during merge. Please retry.'
        );
      }
    } catch (err) {
      console.error('Merge failed:', err);
      setErrorMsg('Connection error. Make sure the backend is running.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // pt-28 (112px) clears the fixed 56px navbar (Navbar.css) plus breathing room.
  const pageClasses =
    'min-h-screen bg-surface-base px-5 pb-16 pt-28 text-white';

  if (sentVideoIds.length === 0) {
    return (
      <div className={pageClasses}>
        <div className="mx-auto max-w-md text-center">
          <h1 className="mb-3 text-2xl font-bold">Merge Configuration</h1>
          <p className="mb-6 text-sm text-dark-400">
            No videos selected. Go back to the search page and add at least one video.
          </p>
          <button
            type="button"
            onClick={handleBack}
            className="rounded-xl border border-dark-700 bg-dark-800/50 px-6 py-3 text-sm font-semibold text-dark-200 transition-colors hover:bg-dark-800"
          >
            ← Back
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={pageClasses}>
      <div className="mx-auto max-w-3xl">
        {/* Header */}
        <header className="mb-8 text-center">
          <h1 className="mb-2 text-3xl font-bold tracking-tight">
            Merge Configuration
          </h1>
          <p className="mx-auto max-w-xl text-sm leading-relaxed text-dark-400">
            The summarizer selects its own highlights from the full transcripts. Choose
            the output length, tone, and whether to render a video reel — then start
            the job.
          </p>
        </header>

        {/* Selected videos — confirmation of scope, not a curation surface */}
        <section className="mb-6 rounded-2xl border border-white/5 bg-dark-800/30 p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Selected Videos</h2>
            <span className="rounded-full border border-brand-500/20 bg-brand-500/10 px-3 py-1 text-xs font-bold text-brand-400">
              {sentVideoIds.length} of {MAX_VIDEOS} max
            </span>
          </div>

          <div className="flex flex-col gap-3">
            {selectedResults
              .filter((r) => sentVideoIds.includes(r.video?.id?.videoId))
              .map((result) => {
                const videoId = result.video?.id?.videoId;
                const thumb = result.video?.snippet?.thumbnails?.medium?.url;
                const title = result.video?.snippet?.title;

                return (
                  <div
                    key={videoId}
                    className="flex items-center gap-4 rounded-xl border border-white/5 bg-dark-800/40 p-3"
                  >
                    {thumb && (
                      <img
                        src={thumb}
                        alt=""
                        className="h-16 w-28 flex-shrink-0 rounded-lg object-cover"
                      />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-white">{title}</p>
                      {result.summary && (
                        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-dark-400">
                          {result.summary}
                        </p>
                      )}
                    </div>
                    <a
                      href={`https://www.youtube.com/watch?v=${videoId}`}
                      target="_blank"
                      rel="noreferrer"
                      className="flex-shrink-0 text-xs font-medium text-brand-400 transition-colors hover:text-brand-300"
                    >
                      YouTube ↗
                    </a>
                  </div>
                );
              })}
          </div>

          {droppedCount > 0 && (
            <p className="mt-3 text-xs text-warning-400">
              {droppedCount} extra video{droppedCount !== 1 ? 's' : ''} will not be
              included — the API accepts at most {MAX_VIDEOS}.
            </p>
          )}
        </section>

        {/* Configuration */}
        <section className="mb-6 rounded-2xl border border-white/5 bg-dark-800/30 p-5">
          <DurationSelector
            value={targetMinutes}
            onChange={setTargetMinutes}
            disabled={isSubmitting}
            compact
          />

          <div className="mt-8">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-white">Summary Style</h3>
              <span className="text-sm text-dark-400">Shapes the written summary</span>
            </div>
            <div className="flex flex-wrap gap-3">
              {STYLES.map((style) => (
                <Pill
                  key={style.value}
                  selected={selectedStyle === style.value}
                  disabled={isSubmitting}
                  onClick={() => setSelectedStyle(style.value)}
                >
                  <span className="block text-sm font-semibold">{style.label}</span>
                  <span className="mt-0.5 block text-xs opacity-70">{style.hint}</span>
                </Pill>
              ))}
            </div>
          </div>

          <div className="mt-8 border-t border-dark-700 pt-6">
            <label className="flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                checked={generateVideo}
                onChange={(e) => setGenerateVideo(e.target.checked)}
                disabled={isSubmitting}
                className="h-4 w-4 cursor-pointer accent-brand-500"
              />
              <span className="text-lg font-semibold text-white">Video Highlights</span>
              <span className="text-sm text-dark-400">
                Render a visual reel alongside the audio
              </span>
            </label>

            {generateVideo && (
              <div className="mt-4 flex flex-wrap gap-3">
                {HIGHLIGHT_LENGTHS.map((len) => (
                  <Pill
                    key={len.value}
                    selected={highlightSeconds === len.value}
                    disabled={isSubmitting}
                    onClick={() => setHighlightSeconds(len.value)}
                  >
                    <span className="text-sm font-semibold">{len.label}</span>
                  </Pill>
                ))}
              </div>
            )}
          </div>
        </section>

        {errorMsg && (
          <div
            role="alert"
            className="mb-4 rounded-xl border border-error-500/30 bg-error-500/10 px-4 py-3 text-sm text-error-400"
          >
            {errorMsg}
          </div>
        )}

        {/* Actions */}
        <div className="flex flex-wrap justify-center gap-3">
          <button
            type="button"
            onClick={handleBack}
            disabled={isSubmitting}
            className="rounded-xl border border-dark-700 bg-dark-800/50 px-6 py-3 text-sm font-semibold text-dark-200 transition-colors hover:bg-dark-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            ← Back to Search
          </button>
          <button
            type="button"
            onClick={handleConfirmMerge}
            disabled={isSubmitting}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-br from-brand-500 to-brand-600 px-8 py-3 text-sm font-semibold text-white shadow-lg shadow-brand-500/25 transition-all hover:from-brand-400 hover:to-brand-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSubmitting ? (
              <>
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                Starting job…
              </>
            ) : (
              <>
                {generateVideo ? 'Merge with Video Highlights' : 'Merge & Play Podcast'}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

export default MergePreviewPage;
