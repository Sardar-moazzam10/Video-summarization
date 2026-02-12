/**
 * ProgressTracker - Professional multi-stage progress component
 *
 * Features:
 * - Stage-based progress visualization
 * - Animated transitions
 * - ETA display
 * - Error state handling
 * - Responsive design
 */

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const STAGES = [
  {
    id: 'pending',
    label: 'Preparing',
    icon: '⏳',
    description: 'Setting up the merge process',
  },
  {
    id: 'transcribing',
    label: 'Transcribing',
    icon: '🎤',
    description: 'Extracting audio from videos',
  },
  {
    id: 'analyzing',
    label: 'Analyzing',
    icon: '🔍',
    description: 'Understanding content structure',
  },
  {
    id: 'fusing',
    label: 'Fusing',
    icon: '🧩',
    description: 'Combining knowledge intelligently',
  },
  {
    id: 'summarizing',
    label: 'Summarizing',
    icon: '🧠',
    description: 'Creating coherent narrative',
  },
  {
    id: 'generating_voice',
    label: 'Voice',
    icon: '🔊',
    description: 'Generating natural audio',
  },
  {
    id: 'completed',
    label: 'Complete',
    icon: '✅',
    description: 'Your summary is ready!',
  },
];

const ProgressTracker = ({
  status = 'pending',
  progressPercent = 0,
  stageMessage = '',
  estimatedSeconds = null,
  error = null,
}) => {
  const currentStageIndex = STAGES.findIndex((s) => s.id === status);
  const currentStage = STAGES[currentStageIndex] || STAGES[0];

  // Format ETA
  const formatEta = (seconds) => {
    if (!seconds || seconds < 0) return null;
    if (seconds < 60) return `${Math.ceil(seconds)}s remaining`;
    return `${Math.ceil(seconds / 60)}m remaining`;
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      {/* Main Progress Bar */}
      <div className="relative mb-8">
        {/* Background Track */}
        <div className="h-3 bg-dark-800 rounded-full overflow-hidden">
          {/* Progress Fill */}
          <motion.div
            className={`h-full rounded-full ${
              error
                ? 'bg-gradient-to-r from-error-500 to-error-600'
                : status === 'completed'
                ? 'bg-gradient-to-r from-success-500 to-emerald-400'
                : 'bg-gradient-to-r from-accent-500 to-primary-500'
            }`}
            initial={{ width: 0 }}
            animate={{ width: `${progressPercent}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
        </div>

        {/* Percentage Label */}
        <motion.div
          className="absolute -top-8 transform -translate-x-1/2"
          style={{ left: `${progressPercent}%` }}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <span className="text-sm font-bold text-white bg-dark-800 px-2 py-1 rounded-md">
            {progressPercent}%
          </span>
        </motion.div>
      </div>

      {/* Stage Indicators */}
      <div className="flex justify-between mb-8 overflow-x-auto pb-2">
        {STAGES.map((stage, idx) => {
          const isComplete = idx < currentStageIndex;
          const isCurrent = idx === currentStageIndex;
          const isPending = idx > currentStageIndex;

          return (
            <motion.div
              key={stage.id}
              className={`
                flex flex-col items-center min-w-[80px]
                ${isPending ? 'opacity-40' : 'opacity-100'}
              `}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: isPending ? 0.4 : 1, y: 0 }}
              transition={{ delay: idx * 0.1 }}
            >
              {/* Icon Circle */}
              <motion.div
                className={`
                  w-12 h-12 rounded-full flex items-center justify-center text-xl
                  ${
                    isComplete
                      ? 'bg-success-500/20 text-success-400'
                      : isCurrent
                      ? 'bg-accent-500/20 text-accent-400 ring-2 ring-accent-500'
                      : 'bg-dark-800 text-dark-400'
                  }
                `}
                whileHover={{ scale: 1.1 }}
                animate={
                  isCurrent
                    ? {
                        boxShadow: [
                          '0 0 0 0 rgba(168, 85, 247, 0.4)',
                          '0 0 0 10px rgba(168, 85, 247, 0)',
                        ],
                      }
                    : {}
                }
                transition={
                  isCurrent
                    ? { duration: 1.5, repeat: Infinity }
                    : { duration: 0.2 }
                }
              >
                {isComplete ? '✓' : stage.icon}
              </motion.div>

              {/* Label */}
              <span
                className={`
                  mt-2 text-xs font-medium text-center
                  ${isCurrent ? 'text-accent-400' : isComplete ? 'text-success-400' : 'text-dark-400'}
                `}
              >
                {stage.label}
              </span>

              {/* Connector Line */}
              {idx < STAGES.length - 1 && (
                <div
                  className={`
                    absolute top-6 left-[calc(50%+24px)] w-[calc(100%-48px)] h-0.5
                    ${isComplete ? 'bg-success-500' : 'bg-dark-700'}
                  `}
                  style={{ display: 'none' }} // Hidden on mobile
                />
              )}
            </motion.div>
          );
        })}
      </div>

      {/* Current Status Card */}
      <AnimatePresence mode="wait">
        <motion.div
          key={status}
          className={`
            p-6 rounded-2xl border
            ${
              error
                ? 'bg-error-500/10 border-error-500/30'
                : status === 'completed'
                ? 'bg-success-500/10 border-success-500/30'
                : 'bg-dark-800/50 border-dark-700'
            }
          `}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -20 }}
          transition={{ duration: 0.3 }}
        >
          <div className="flex items-start gap-4">
            {/* Status Icon */}
            <motion.div
              className={`
                w-14 h-14 rounded-xl flex items-center justify-center text-3xl
                ${
                  error
                    ? 'bg-error-500/20'
                    : status === 'completed'
                    ? 'bg-success-500/20'
                    : 'bg-accent-500/20'
                }
              `}
              animate={
                !error && status !== 'completed'
                  ? { rotate: [0, 5, -5, 0] }
                  : {}
              }
              transition={{ duration: 2, repeat: Infinity }}
            >
              {error ? '❌' : currentStage.icon}
            </motion.div>

            {/* Status Text */}
            <div className="flex-1">
              <h3
                className={`
                  text-lg font-semibold mb-1
                  ${
                    error
                      ? 'text-error-400'
                      : status === 'completed'
                      ? 'text-success-400'
                      : 'text-white'
                  }
                `}
              >
                {error ? 'Error Occurred' : currentStage.label}
              </h3>
              <p className="text-dark-400 text-sm">
                {error || stageMessage || currentStage.description}
              </p>
            </div>

            {/* ETA */}
            {estimatedSeconds && !error && status !== 'completed' && (
              <div className="text-right">
                <span className="text-xs text-dark-400">ETA</span>
                <p className="text-accent-400 font-medium">
                  {formatEta(estimatedSeconds)}
                </p>
              </div>
            )}
          </div>

          {/* Additional Info for Completed */}
          {status === 'completed' && (
            <motion.div
              className="mt-4 pt-4 border-t border-success-500/20"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.3 }}
            >
              <p className="text-success-400 text-sm text-center">
                🎉 Your AI-powered summary is ready to view!
              </p>
            </motion.div>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
};

export default ProgressTracker;
