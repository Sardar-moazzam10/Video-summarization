/**
 * DurationSelector - Professional duration picker component
 *
 * Features:
 * - Visual duration picker, one card per entry in DURATIONS
 * - Animated selection
 * - Descriptions for each option
 * - Accessibility support
 * - Mobile responsive
 */

import React from 'react';
import { motion } from 'framer-motion';

// targetWords mirrors DURATION_PROFILES in backend/services/duration_profiles.py.
// Keep the two in sync — this drives the "Estimated output" label only; the
// backend remains the source of truth for what is actually generated.
const DURATIONS = [
  {
    value: 5,
    label: '5 min',
    icon: '⚡',
    title: 'Quick Highlights',
    description: 'Key highlights only',
    targetWords: 750,
    color: 'from-amber-500 to-orange-500',
    bgColor: 'bg-amber-500/10',
    borderColor: 'border-amber-500',
  },
  {
    value: 10,
    label: '10 min',
    icon: '📝',
    title: 'Key Concepts',
    description: 'Main ideas with context',
    targetWords: 1500,
    color: 'from-emerald-500 to-teal-500',
    bgColor: 'bg-emerald-500/10',
    borderColor: 'border-emerald-500',
  },
  {
    value: 15,
    label: '15 min',
    icon: '📚',
    title: 'Balanced Summary',
    description: 'Complete with examples',
    targetWords: 2200,
    color: 'from-blue-500 to-cyan-500',
    bgColor: 'bg-blue-500/10',
    borderColor: 'border-blue-500',
  },
  {
    value: 20,
    label: '20 min',
    icon: '🎓',
    title: 'Detailed Summary',
    description: 'Comprehensive analysis',
    targetWords: 2800,
    color: 'from-purple-500 to-pink-500',
    bgColor: 'bg-purple-500/10',
    borderColor: 'border-purple-500',
  },
  {
    value: 30,
    label: '30 min',
    icon: '🏛️',
    title: 'Comprehensive Summary',
    description: 'Longest — fullest coverage of the source',
    targetWords: 4200,
    color: 'from-indigo-500 to-violet-500',
    bgColor: 'bg-indigo-500/10',
    borderColor: 'border-indigo-500',
  },
];

const DurationSelector = ({
  value,
  onChange,
  disabled = false,
  showTitle = true,
  compact = false,
  // Durations the source material can actually produce. null = not resolved
  // yet, so nothing is disabled and the picker behaves exactly as before.
  // The backend computes this from real media duration and re-checks it on
  // submit — this only saves the user a round trip and explains why.
  allowedDurations = null,
  sourceDurationLabel = '',
  validationStatus = null,
  validationMessage = '',
}) => {
  // Look the estimate up from DURATIONS rather than hardcoding it, so adding a
  // profile to the table above is the only edit required.
  // Derive status if not explicitly provided
  const status = validationStatus || (
    allowedDurations === null
      ? 'idle'
      : allowedDurations.length === 0
      ? 'too_short'
      : 'valid'
  );

  const selectedDuration = DURATIONS.find((d) => d.value === value);

  // Strict eligibility: must be an array and contain the minutes
  const isAllowed = (minutes) =>
    Array.isArray(allowedDurations) && allowedDurations.includes(minutes);

  const getReason = () => {
    if (status === 'validating') return 'Verifying length...';
    if (status === 'verification_failed') return 'Length unverified';
    if (sourceDurationLabel) return `Video is only ${sourceDurationLabel}`;
    return 'Longer than the source video';
  };

  return (
    <div className="w-full">
      {showTitle && (
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold text-white">
            Output Duration
          </h3>
          <span className="text-sm text-dark-400">
            Choose your summary length
          </span>
        </div>
      )}

      {/* Validation Status Banners */}
      {status === 'validating' && (
        <div className="flex items-center gap-2 mb-3 text-xs text-cyan-400" data-testid="duration-validating-banner">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-cyan-400 border-t-transparent inline-block" />
          <span>Verifying video length...</span>
        </div>
      )}

      {status === 'too_short' && (
        <div className="mb-3 rounded-lg bg-amber-500/10 border border-amber-500/30 p-2.5 text-xs text-amber-400 flex items-center gap-2" data-testid="duration-too-short-banner">
          <span>⚠️</span>
          <span>
            {validationMessage || (sourceDurationLabel
              ? `Selected video is only ${sourceDurationLabel}. A 5-minute summary requires more than 5 minutes of source content.`
              : 'A 5-minute summary requires more than 5 minutes of source content.')}
          </span>
        </div>
      )}

      {status === 'verification_failed' && (
        <div className="mb-3 rounded-lg bg-red-500/10 border border-red-500/30 p-2.5 text-xs text-red-400 flex items-center gap-2" data-testid="duration-failed-banner">
          <span>❌</span>
          <span>{validationMessage || 'Could not verify duration for all selected videos. Summarization is disabled.'}</span>
        </div>
      )}

      {status === 'valid' && sourceDurationLabel && (
        <div className="flex items-center gap-2 mb-3 text-xs text-dark-300" data-testid="duration-valid-info">
          <span className="font-medium text-white">Source length:</span>
          <span className="px-2 py-0.5 rounded bg-dark-700 text-cyan-300 font-mono">{sourceDurationLabel}</span>
          <span className="text-dark-400">(Summaries must be shorter than source)</span>
        </div>
      )}

      {/* Flex-wrap rather than a fixed column count: the option list is 5 long and
          any grid-cols-N leaves an orphan on the last row. Wrapped rows stay
          centered, and flex-1 lets a full row share the width evenly. */}
      <div className="flex flex-wrap justify-center gap-3">
        {DURATIONS.map((duration) => {
          const allowed = isAllowed(duration.value);
          const isSelected = value === duration.value && allowed;
          const isDisabled = disabled || !allowed;

          return (
            <motion.button
              key={duration.value}
              onClick={() => !isDisabled && onChange(duration.value)}
              disabled={isDisabled}
              aria-disabled={isDisabled}
              title={!allowed ? getReason() : undefined}
              data-testid={`duration-option-${duration.value}`}
              className={`
                relative overflow-hidden rounded-xl p-4 text-left
                transition-all duration-300 ease-out
                border-2 flex-1
                ${compact ? 'basis-32 max-w-[220px]' : 'basis-40 max-w-xs'}
                ${isDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                ${
                  isSelected
                    ? `${duration.borderColor} ${duration.bgColor} shadow-lg`
                    : 'border-dark-700 bg-dark-800/50 hover:border-dark-600 hover:bg-dark-800'
                }
              `}
              whileHover={!isDisabled ? { scale: 1.02, y: -2 } : {}}
              whileTap={!isDisabled ? { scale: 0.98 } : {}}
              layout
            >
              {/* Gradient Background on Selection */}
              {isSelected && (
                <motion.div
                  className={`absolute inset-0 bg-gradient-to-br ${duration.color} opacity-10`}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 0.1 }}
                  transition={{ duration: 0.3 }}
                />
              )}

              {/* Content */}
              <div className="relative z-10">
                {/* Icon & Label */}
                <div className="flex items-center justify-between mb-2">
                  <span className="text-2xl">{duration.icon}</span>
                  <span
                    className={`
                      text-xs font-bold px-2 py-1 rounded-full
                      ${isSelected ? `bg-gradient-to-r ${duration.color} text-white` : 'bg-dark-700 text-dark-300'}
                    `}
                  >
                    {duration.label}
                  </span>
                </div>

                {/* Title */}
                <h4
                  className={`font-semibold mb-1 ${
                    isSelected ? 'text-white' : 'text-dark-200'
                  }`}
                >
                  {duration.title}
                </h4>

                {/* Description, or why this option cannot be used */}
                {allowed ? (
                  <p
                    className={`text-sm ${
                      isSelected ? 'text-dark-300' : 'text-dark-400'
                    }`}
                  >
                    {duration.description}
                  </p>
                ) : (
                  <p className="text-sm text-amber-500/90" data-testid={`duration-reason-${duration.value}`}>
                    {getReason()}
                  </p>
                )}

                {/* Selection Indicator */}
                {isSelected && (
                  <motion.div
                    className={`absolute top-2 right-2 w-6 h-6 rounded-full bg-gradient-to-r ${duration.color} flex items-center justify-center`}
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                  >
                    <svg
                      className="w-4 h-4 text-white"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={3}
                        d="M5 13l4 4L19 7"
                      />
                    </svg>
                  </motion.div>
                )}
              </div>
            </motion.button>
          );
        })}
      </div>

      {/* Estimated Output Info */}
      {value && (
        <motion.div
          className="mt-4 p-3 rounded-lg bg-dark-800/50 border border-dark-700"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <div className="flex items-center justify-between text-sm">
            <span className="text-dark-400">Estimated output:</span>
            <span className="text-white font-medium">
              ~{selectedDuration?.targetWords?.toLocaleString() ?? '—'} words
            </span>
          </div>
        </motion.div>
      )}
    </div>
  );
};

export default DurationSelector;
