/**
 * MultiSelectBar - Floating selection bar component
 *
 * Features:
 * - Shows selected video count
 * - Thumbnail previews
 * - Duration selector integration
 * - Merge button with validation
 * - Smooth animations
 * - Mobile responsive (slides up from bottom)
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import DurationSelector from './DurationSelector';

const MultiSelectBar = ({
  selectedVideos = [],
  onRemove,
  onClear,
  onMerge,
  isLoading = false,
}) => {
  const [duration, setDuration] = useState(10);
  const [showDurationPicker, setShowDurationPicker] = useState(false);

  const count = selectedVideos.length;
  const canMerge = count >= 1 && !isLoading;
  const isVisible = count > 0;

  const handleMerge = () => {
    if (canMerge) {
      onMerge(duration);
    }
  };

  const getDurationLabel = () => {
    const labels = {
      5: '5 min • Quick',
      10: '10 min • Brief',
      15: '15 min • Full',
      20: '20 min • Deep',
    };
    return labels[duration] || `${duration} min`;
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
                      <DurationSelector
                        value={duration}
                        onChange={(val) => {
                          setDuration(val);
                          setShowDurationPicker(false);
                        }}
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
                        <p className="text-dark-400 text-xs">selected</p>
                      </div>
                    </motion.div>

                    {/* Video Thumbnails */}
                    <div className="flex-1 flex items-center gap-2 overflow-x-auto py-1 px-2">
                      <AnimatePresence mode="popLayout">
                        {selectedVideos.slice(0, 5).map((video, idx) => (
                          <motion.div
                            key={video.id || idx}
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
                              onClick={() => onRemove(video.id)}
                              className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-error-500 text-white text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-error-600"
                            >
                              ×
                            </button>
                          </motion.div>
                        ))}
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
                              : 'bg-dark-800 border-dark-600 text-dark-300 hover:border-dark-500'
                          }
                        `}
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                      >
                        <span className="text-lg">⏱️</span>
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
                        className={`
                          flex items-center gap-2 px-6 py-3 rounded-xl font-semibold
                          transition-all duration-300
                          ${
                            canMerge
                              ? 'bg-gradient-to-r from-accent-500 to-primary-500 text-white shadow-lg shadow-accent-500/25 hover:shadow-accent-500/40'
                              : 'bg-dark-700 text-dark-400 cursor-not-allowed'
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
