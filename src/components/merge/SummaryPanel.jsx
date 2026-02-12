/**
 * SummaryPanel - Display fusion results with metadata
 *
 * Features:
 * - Summary text display
 * - Fusion statistics
 * - Topic tags
 * - Conflict notes
 * - Copy & download options
 * - Audio player integration
 */

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const SummaryPanel = ({
  summaryText = '',
  metadata = {},
  audioUrl = null,
  onDownload,
  onCopy,
  isLoading = false,
}) => {
  const [copied, setCopied] = useState(false);
  const [expandedSection, setExpandedSection] = useState('summary');

  const {
    topics = [],
    conflicts = [],
    compression_ratio = 0,
    output_words = 0,
    total_source_words = 0,
    processing_time_seconds = 0,
    videos_processed = 0,
  } = metadata;

  const handleCopy = async () => {
    if (onCopy) {
      await onCopy();
    } else {
      await navigator.clipboard.writeText(summaryText);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const formatNumber = (num) => {
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  const stats = [
    {
      label: 'Videos',
      value: videos_processed,
      icon: '🎬',
      color: 'from-blue-500 to-cyan-500',
    },
    {
      label: 'Words',
      value: formatNumber(output_words),
      icon: '📝',
      color: 'from-emerald-500 to-teal-500',
    },
    {
      label: 'Compression',
      value: `${Math.round(compression_ratio * 100)}%`,
      icon: '📊',
      color: 'from-purple-500 to-pink-500',
    },
    {
      label: 'Time',
      value: `${Math.round(processing_time_seconds)}s`,
      icon: '⏱️',
      color: 'from-amber-500 to-orange-500',
    },
  ];

  return (
    <div className="w-full max-w-4xl mx-auto space-y-6">
      {/* Header with Stats */}
      <motion.div
        className="p-6 rounded-2xl bg-gradient-to-br from-dark-800 to-dark-900 border border-dark-700"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-accent-500 to-primary-500 flex items-center justify-center text-2xl">
              🧠
            </div>
            <div>
              <h2 className="text-xl font-bold text-white">AI Summary</h2>
              <p className="text-dark-400 text-sm">
                Powered by Fusion Engine
              </p>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-2">
            <motion.button
              onClick={handleCopy}
              className={`
                flex items-center gap-2 px-4 py-2 rounded-lg
                transition-all duration-200
                ${
                  copied
                    ? 'bg-success-500/20 text-success-400 border border-success-500/30'
                    : 'bg-dark-700 text-dark-300 hover:text-white border border-dark-600'
                }
              `}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              {copied ? (
                <>
                  <span>✓</span>
                  <span>Copied!</span>
                </>
              ) : (
                <>
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                    />
                  </svg>
                  <span>Copy</span>
                </>
              )}
            </motion.button>

            {onDownload && (
              <motion.button
                onClick={onDownload}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-accent-500/20 text-accent-400 border border-accent-500/30 hover:bg-accent-500/30 transition-colors"
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
              >
                <svg
                  className="w-4 h-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                  />
                </svg>
                <span>Download</span>
              </motion.button>
            )}
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-4 gap-4">
          {stats.map((stat, idx) => (
            <motion.div
              key={stat.label}
              className="text-center p-3 rounded-xl bg-dark-800/50"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: idx * 0.1 }}
            >
              <div className="text-2xl mb-1">{stat.icon}</div>
              <div
                className={`text-xl font-bold bg-gradient-to-r ${stat.color} bg-clip-text text-transparent`}
              >
                {stat.value}
              </div>
              <div className="text-xs text-dark-400">{stat.label}</div>
            </motion.div>
          ))}
        </div>
      </motion.div>

      {/* Topics */}
      {topics.length > 0 && (
        <motion.div
          className="flex flex-wrap gap-2"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
        >
          <span className="text-dark-400 text-sm mr-2">Topics covered:</span>
          {topics.map((topic, idx) => (
            <span
              key={idx}
              className="px-3 py-1 rounded-full text-sm bg-dark-800 text-dark-300 border border-dark-700"
            >
              {topic}
            </span>
          ))}
        </motion.div>
      )}

      {/* Audio Player */}
      {audioUrl && (
        <motion.div
          className="p-4 rounded-xl bg-dark-800/50 border border-dark-700"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="text-xl">🔊</span>
            <span className="text-white font-medium">Listen to Summary</span>
          </div>
          <audio
            src={audioUrl}
            controls
            className="w-full rounded-lg"
            style={{
              filter: 'invert(1)',
            }}
          />
        </motion.div>
      )}

      {/* Summary Text */}
      <motion.div
        className="p-6 rounded-2xl bg-dark-800/30 border border-dark-700"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
      >
        <div className="prose prose-invert max-w-none">
          {summaryText.split('\n\n').map((paragraph, idx) => (
            <motion.p
              key={idx}
              className="text-dark-200 leading-relaxed mb-4 last:mb-0"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.5 + idx * 0.1 }}
            >
              {paragraph}
            </motion.p>
          ))}
        </div>
      </motion.div>

      {/* Conflicts Note */}
      {conflicts.length > 0 && (
        <motion.div
          className="p-4 rounded-xl bg-warning-500/10 border border-warning-500/30"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
        >
          <div className="flex items-start gap-3">
            <span className="text-xl">⚠️</span>
            <div>
              <h4 className="text-warning-400 font-medium mb-2">
                Differing Perspectives Detected
              </h4>
              <ul className="text-dark-300 text-sm space-y-1">
                {conflicts.map((conflict, idx) => (
                  <li key={idx}>• {conflict.topic}</li>
                ))}
              </ul>
            </div>
          </div>
        </motion.div>
      )}
    </div>
  );
};

export default SummaryPanel;
