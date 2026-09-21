/**
 * MultiSelectBar - Floating selection bar component with shared duration validation
 *
 * Features:
 * - Shows selected video count
 * - Thumbnail previews
 * - Duration selector integration
 * - Merge button with validation
 * - Smooth animations
 * - Mobile responsive (slides up from bottom)
 * - Shared duration validation across all entry points
 * - Fail-closed duration verification (validating, valid, too_short, verification_failed)
 * - Auto-adjustment of duration on video removal/addition with notice
 * - Race-condition safe with AbortController and request sequencing
 */

import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import DurationSelector from './DurationSelector';
import { API, authenticatedFetch } from '../../config/api';

const getVideoId = (v) => {
  if (!v) return '';
  if (typeof v === 'string') return v;
  return v.id?.videoId || v.videoId || v.id || '';
};

// Module-level cache so probed durations persist across selection toggles
const PROBED_DURATIONS_CACHE = new Map();

const MultiSelectBar = ({
  selectedVideos = [],
  onRemove,
  onClear,
  onMerge,
  isLoading = false,
}) => {
  const [duration, setDuration] = useState(10);
  const [showDurationPicker, setShowDurationPicker] = useState(false);
  const [validationStatus, setValidationStatus] = useState('idle'); // 'idle' | 'validating' | 'valid' | 'too_short' | 'verification_failed'
  const [allowedDurations, setAllowedDurations] = useState(null);
  const [combinedDurationLabel, setCombinedDurationLabel] = useState('');
  const [durationNotice, setDurationNotice] = useState(null);

  useEffect(() => {
    if (!showDurationPicker) return;
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        setShowDurationPicker(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showDurationPicker]);

  const requestSeqRef = useRef(0);

  const count = selectedVideos.length;
  const isVisible = count > 0;

  // Deduplicate unique video IDs
  const uniqueVideoIds = Array.from(
    new Set(selectedVideos.map(getVideoId).filter(Boolean))
  );

  useEffect(() => {
    if (uniqueVideoIds.length === 0) {
      setValidationStatus('idle');
      setAllowedDurations(null);
      setCombinedDurationLabel('');
      setDurationNotice(null);
      setDuration(null);
      return;
    }

    const currentSeq = ++requestSeqRef.current;
    const abortController = new AbortController();

    // Fast path: check if all unique IDs are already cached
    const allCached = uniqueVideoIds.every((id) => PROBED_DURATIONS_CACHE.has(id));

    if (allCached) {
      const cachedDurations = uniqueVideoIds.map((id) => PROBED_DURATIONS_CACHE.get(id));
      const anyFailed = cachedDurations.some((d) => d === null || d === undefined);

      if (anyFailed) {
        setValidationStatus('verification_failed');
        setAllowedDurations([]);
        setCombinedDurationLabel('');
        setDuration(null);
        return;
      }

      const totalSeconds = cachedDurations.reduce((a, b) => a + b, 0);
      // Strict rule: requested_minutes * 60 < totalSeconds
      const allowed = [5, 10, 15, 20, 30].filter((m) => m * 60 < totalSeconds);

      const m = Math.floor(totalSeconds / 60);
      const s = Math.round(totalSeconds % 60);
      const label = m && s ? `${m}m ${s}s` : m ? `${m}m` : `${s}s`;

      setCombinedDurationLabel(label);
      setAllowedDurations(allowed);
      const newStatus = allowed.length > 0 ? 'valid' : 'too_short';
      setValidationStatus(newStatus);

      setDuration((current) => {
        if (allowed.length === 0) return null;
        if (current && allowed.includes(current)) return current;
        const fallback = allowed.includes(10) ? 10 : allowed[allowed.length - 1];
        if (current && current !== fallback) {
          setDurationNotice(`Adjusted duration from ${current}m to ${fallback}m based on source length.`);
        }
        return fallback;
      });
      return;
    }

    // Network path
    setValidationStatus('validating');

    (async () => {
      try {
        const res = await authenticatedFetch(API.MERGE_VIDEO_DURATIONS(uniqueVideoIds), {
          signal: abortController.signal,
        });

        if (currentSeq !== requestSeqRef.current) return;

        if (!res.ok) {
          setValidationStatus('verification_failed');
          setAllowedDurations([]);
          setDuration(null);
          return;
        }

        const data = await res.json();
        if (currentSeq !== requestSeqRef.current) return;

        // Cache resolved items
        if (data.durations && typeof data.durations === 'object') {
          Object.entries(data.durations).forEach(([vid, d]) => {
            PROBED_DURATIONS_CACHE.set(vid, d);
          });
        }

        if (data.status === 'verification_failed') {
          setValidationStatus('verification_failed');
          setAllowedDurations([]);
          setCombinedDurationLabel('');
          setDuration(null);
        } else if (data.status === 'too_short') {
          setValidationStatus('too_short');
          setAllowedDurations([]);
          setCombinedDurationLabel(data.combined_duration_label || '');
          setDuration(null);
        } else if (data.status === 'valid' && Array.isArray(data.allowed_durations)) {
          setValidationStatus('valid');
          setAllowedDurations(data.allowed_durations);
          setCombinedDurationLabel(data.combined_duration_label || '');

          setDuration((current) => {
            if (data.allowed_durations.length === 0) return null;
            if (current && data.allowed_durations.includes(current)) return current;
            const fallback = data.allowed_durations.includes(10)
              ? 10
              : data.allowed_durations[data.allowed_durations.length - 1];
            if (current && current !== fallback) {
              setDurationNotice(`Adjusted duration from ${current}m to ${fallback}m based on source length.`);
            }
            return fallback;
          });
        }
      } catch (err) {
        if (abortController.signal.aborted || currentSeq !== requestSeqRef.current) return;
        setValidationStatus('verification_failed');
        setAllowedDurations([]);
        setDuration(null);
      }
    })();

    return () => {
      abortController.abort();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uniqueVideoIds.join(',')]);

  // Strict canMerge gating
  const canMerge =
    count >= 1 &&
    !isLoading &&
    validationStatus === 'valid' &&
    duration !== null &&
    Array.isArray(allowedDurations) &&
    allowedDurations.includes(duration);

  const handleMerge = () => {
    if (canMerge) {
      onMerge(duration);
    }
  };

  const getDurationLabel = () => {
    if (validationStatus === 'validating') return 'Verifying...';
    if (validationStatus === 'too_short') return 'Too Short';
    if (validationStatus === 'verification_failed') return 'Unverified';
    const labels = {
      5: '5 min • Quick',
      10: '10 min • Brief',
      15: '15 min • Full',
      20: '20 min • Detailed',
      30: '30 min • Comprehensive',
    };
    return duration ? (labels[duration] || `${duration} min`) : 'Pick Duration';
  };

  const getButtonTooltip = () => {
    if (validationStatus === 'validating') return 'Verifying video duration...';
    if (validationStatus === 'too_short') {
      return combinedDurationLabel
        ? `Source is only ${combinedDurationLabel}. A 5-minute summary requires more than 5 minutes of source content.`
        : 'A 5-minute summary requires more than 5 minutes of source content.';
    }
    if (validationStatus === 'verification_failed') {
      return 'Could not verify duration for all selected videos';
    }
    if (!duration) return 'Please choose an output duration';
    return undefined;
  };

  return (
    <AnimatePresence>
      {isVisible && (
        <>
          {/* Backdrop for duration picker */}
          {showDurationPicker && (
            <motion.div
              className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowDurationPicker(false)}
            />
          )}

          {/* Main Bar */}
          <motion.div
            className="fixed bottom-0 left-0 right-0 z-50 p-4"
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
          >
            <div className="max-w-4xl mx-auto">
              <div className="bg-dark-900/95 backdrop-blur-xl rounded-2xl border border-dark-700 shadow-2xl overflow-hidden">
                {/* Duration Picker Panel (Expandable) */}
                <AnimatePresence>
                  {showDurationPicker && (
                    <motion.div
                      className="p-4 border-b border-dark-700"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.2 }}
                    >
                      {durationNotice && (
                        <div className="mb-3 p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs text-amber-300 flex items-center justify-between">
                          <span>ℹ️ {durationNotice}</span>
                          <button
                            type="button"
                            onClick={() => setDurationNotice(null)}
                            className="text-amber-400 hover:text-white font-bold ml-2 text-sm"
                          >
                            ×
                          </button>
                        </div>
                      )}
                      <DurationSelector
                        value={duration}
                        onChange={(val) => {
                          setDuration(val);
                          setDurationNotice(null);
                          setShowDurationPicker(false);
                        }}
                        allowedDurations={allowedDurations}
                        sourceDurationLabel={combinedDurationLabel}
                        validationStatus={validationStatus}
                        compact
                      />
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* Main Content */}
                <div className="p-4">
                  <div className="flex items-center gap-4">
                    {/* Selection Count Badge */}
                    <motion.div
                      className="flex items-center gap-2"
                      layout
                    >
                      <motion.div
                        className="relative"
                        key={count}
                        initial={{ scale: 0.5 }}
                        animate={{ scale: 1 }}
                        transition={{ type: 'spring', stiffness: 500 }}
                      >
                        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-accent-500 to-primary-500 flex items-center justify-center">
                          <span className="text-xl font-bold text-white">
                            {count}
                          </span>
                        </div>
                        {/* Pulse animation */}
                        <motion.div
                          className="absolute inset-0 rounded-xl bg-accent-500"
                          initial={{ scale: 1, opacity: 0.5 }}
                          animate={{ scale: 1.5, opacity: 0 }}
                          transition={{ duration: 1, repeat: Infinity }}
                        />
                      </motion.div>
                      <div className="hidden sm:block">
                        <p className="text-white font-medium">
                          {count === 1 ? '1 video' : `${count} videos`}
                        </p>
                        <p className="text-dark-400 text-xs">
                          {combinedDurationLabel ? combinedDurationLabel : 'selected'}
                        </p>
                      </div>
                    </motion.div>

                    {/* Video Thumbnails */}
                    <div className="flex-1 flex items-center gap-2 overflow-x-auto py-1 px-2">
                      <AnimatePresence mode="popLayout">
                        {selectedVideos.slice(0, 5).map((video, idx) => {
                          const id = getVideoId(video);
                          return (
                            <motion.div
                              key={`${id || 'video'}-${idx}`}
                              className="relative group flex-shrink-0"
                              initial={{ scale: 0, opacity: 0 }}
                              animate={{ scale: 1, opacity: 1 }}
                              exit={{ scale: 0, opacity: 0 }}
                              layout
                            >
                              <img
                                src={video.thumbnail || '/placeholder-video.jpg'}
                                alt={video.title || 'Video'}
                                className="w-16 h-10 object-cover rounded-lg border-2 border-dark-600 group-hover:border-accent-500 transition-colors"
                              />
                              {/* Remove Button */}
                              <button
                                onClick={() => onRemove(id || video.id)}
                                className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-error-500 text-white text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-error-600"
                              >
                                ×
                              </button>
                            </motion.div>
                          );
                        })}
                      </AnimatePresence>
                      {count > 5 && (
                        <span className="text-dark-400 text-sm flex-shrink-0">
                          +{count - 5} more
                        </span>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2">
                      {/* Duration Toggle Button */}
                      <motion.button
                        onClick={() => setShowDurationPicker(!showDurationPicker)}
                        className={`
                          hidden sm:flex items-center gap-2 px-4 py-2 rounded-xl
                          border transition-all
                          ${
                            showDurationPicker
                              ? 'bg-accent-500/20 border-accent-500 text-accent-400'
                              : validationStatus === 'too_short'
                              ? 'bg-amber-500/10 border-amber-500/30 text-amber-300 hover:border-amber-400'
                              : validationStatus === 'verification_failed'
                              ? 'bg-red-500/10 border-red-500/30 text-red-300 hover:border-red-400'
                              : 'bg-dark-800 border-dark-600 text-dark-300 hover:border-dark-500'
                          }
                        `}
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        title="Click to change summary output duration"
                      >
                        <span className="text-lg">
                          {validationStatus === 'too_short'
                            ? '⚠️'
                            : validationStatus === 'verification_failed'
                            ? '❌'
                            : '⏱️'}
                        </span>
                        <span className="text-sm font-medium">
                          {getDurationLabel()}
                        </span>
                        <motion.svg
                          className="w-4 h-4"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          animate={{ rotate: showDurationPicker ? 180 : 0 }}
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 9l-7 7-7-7"
                          />
                        </motion.svg>
                      </motion.button>

                      {/* Clear Button */}
                      <motion.button
                        onClick={onClear}
                        className="p-2 rounded-xl bg-dark-800 border border-dark-600 text-dark-400 hover:text-white hover:border-dark-500 transition-colors"
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        disabled={isLoading}
                        title="Clear selection"
                      >
                        <svg
                          className="w-5 h-5"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                          />
                        </svg>
                      </motion.button>

                      {/* Merge Button */}
                      <motion.button
                        onClick={handleMerge}
                        disabled={!canMerge}
                        title={getButtonTooltip()}
                        data-testid="multiselectbar-submit-btn"
                        className={`
                          flex items-center gap-2 px-6 py-3 rounded-xl font-semibold
                          transition-all duration-300
                          ${
                            canMerge
                              ? 'bg-gradient-to-r from-accent-500 to-primary-500 text-white shadow-lg shadow-accent-500/25 hover:shadow-accent-500/40 cursor-pointer'
                              : 'bg-dark-700 text-dark-400 cursor-not-allowed opacity-60'
                          }
                        `}
                        whileHover={canMerge ? { scale: 1.02 } : {}}
                        whileTap={canMerge ? { scale: 0.98 } : {}}
                      >
                        {isLoading ? (
                          <>
                            <motion.div
                              className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full"
                              animate={{ rotate: 360 }}
                              transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                            />
                            <span>Processing...</span>
                          </>
                        ) : validationStatus === 'validating' ? (
                          <>
                            <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                            <span>Checking...</span>
                          </>
                        ) : (
                          <>
                            <span>🚀</span>
                            <span>
                              {count === 1 ? 'Summarize' : `Merge ${count} Videos`}
                            </span>
                          </>
                        )}
                      </motion.button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
};

export default MultiSelectBar;
