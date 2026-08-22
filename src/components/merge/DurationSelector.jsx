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
    value: 2,
    label: '2 min',
    icon: '🚀',
    title: 'Express',
    description: 'Fastest — ideal for a live demo',
    targetWords: 300,
    color: 'from-rose-500 to-pink-500',
    bgColor: 'bg-rose-500/10',
    borderColor: 'border-rose-500',
  },
  {
    value: 5,
    label: '5 min',
    icon: '⚡',
    title: 'Quick Scan',
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
    title: 'Brief Summary',
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
    title: 'Full Coverage',
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
    title: 'Deep Dive',
    description: 'Comprehensive analysis',
    targetWords: 2800,
    color: 'from-purple-500 to-pink-500',
    bgColor: 'bg-purple-500/10',
    borderColor: 'border-purple-500',
  },
];

const DurationSelector = ({
  value,
  onChange,
  disabled = false,
  showTitle = true,
  compact = false,
}) => {
  // Look the estimate up from DURATIONS rather than hardcoding it, so adding a
  // profile to the table above is the only edit required.
  const selectedDuration = DURATIONS.find((d) => d.value === value);

  return (
    <div className="w-full">
      {showTitle && (
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-white">
            Output Duration
          </h3>
          <span className="text-sm text-dark-400">
            Choose your summary length
          </span>
        </div>
      )}

      {/* Flex-wrap rather than a fixed column count: the option list is 5 long and
          any grid-cols-N leaves an orphan on the last row. Wrapped rows stay
          centered, and flex-1 lets a full row share the width evenly. */}
      <div className="flex flex-wrap justify-center gap-3">
        {DURATIONS.map((duration) => {
          const isSelected = value === duration.value;

          return (
            <motion.button
              key={duration.value}
              onClick={() => !disabled && onChange(duration.value)}
              disabled={disabled}
              className={`
                relative overflow-hidden rounded-xl p-4 text-left
                transition-all duration-300 ease-out
                border-2 flex-1
                ${compact ? 'basis-32 max-w-[220px]' : 'basis-40 max-w-xs'}
                ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                ${
                  isSelected
                    ? `${duration.borderColor} ${duration.bgColor} shadow-lg`
                    : 'border-dark-700 bg-dark-800/50 hover:border-dark-600 hover:bg-dark-800'
                }
              `}
              whileHover={!disabled ? { scale: 1.02, y: -2 } : {}}
              whileTap={!disabled ? { scale: 0.98 } : {}}
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

                {/* Description */}
                <p
                  className={`text-sm ${
                    isSelected ? 'text-dark-300' : 'text-dark-400'
                  }`}
                >
                  {duration.description}
                </p>

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
