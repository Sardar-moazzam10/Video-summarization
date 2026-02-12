/**
 * VideoCard - Enhanced video card component
 *
 * Features:
 * - Beautiful hover effects
 * - Selection state with visual feedback
 * - Duration badge
 * - Channel info
 * - Action buttons
 * - Accessibility support
 */

import React from 'react';
import { motion } from 'framer-motion';

const VideoCard = ({
  video,
  isSelected = false,
  onSelect,
  onWatch,
  onTranscript,
  showActions = true,
  compact = false,
}) => {
  const {
    id,
    title,
    thumbnail,
    channelTitle,
    duration,
    viewCount,
    publishedAt,
  } = video;

  // Format view count
  const formatViews = (count) => {
    if (!count) return null;
    if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M views`;
    if (count >= 1000) return `${(count / 1000).toFixed(1)}K views`;
    return `${count} views`;
  };

  // Format date
  const formatDate = (dateStr) => {
    if (!dateStr) return null;
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now - date;
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    if (days < 1) return 'Today';
    if (days < 7) return `${days}d ago`;
    if (days < 30) return `${Math.floor(days / 7)}w ago`;
    if (days < 365) return `${Math.floor(days / 30)}mo ago`;
    return `${Math.floor(days / 365)}y ago`;
  };

  return (
    <motion.div
      className={`
        group relative rounded-2xl overflow-hidden
        bg-dark-800/50 border-2 transition-all duration-300
        ${
          isSelected
            ? 'border-accent-500 bg-accent-500/10 ring-2 ring-accent-500/20'
            : 'border-dark-700 hover:border-dark-600 hover:bg-dark-800'
        }
        ${compact ? 'p-2' : 'p-0'}
      `}
      whileHover={{ y: -4 }}
      layout
    >
      {/* Selection Overlay */}
      {isSelected && (
        <motion.div
          className="absolute inset-0 bg-gradient-to-br from-accent-500/10 to-transparent pointer-events-none z-10"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        />
      )}

      {/* Thumbnail Container */}
      <div className="relative aspect-video overflow-hidden">
        <img
          src={thumbnail || `https://img.youtube.com/vi/${id}/mqdefault.jpg`}
          alt={title}
          className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
          loading="lazy"
        />

        {/* Duration Badge */}
        {duration && (
          <div className="absolute bottom-2 right-2 px-2 py-1 rounded-md bg-black/80 text-white text-xs font-medium">
            {duration}
          </div>
        )}

        {/* Selection Checkbox */}
        <motion.button
          onClick={() => onSelect && onSelect(video)}
          className={`
            absolute top-2 left-2 w-8 h-8 rounded-lg
            flex items-center justify-center
            transition-all duration-200
            ${
              isSelected
                ? 'bg-accent-500 text-white'
                : 'bg-black/60 text-white/70 opacity-0 group-hover:opacity-100 hover:bg-black/80'
            }
          `}
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.9 }}
        >
          {isSelected ? (
            <svg
              className="w-5 h-5"
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
          ) : (
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
                d="M12 4v16m8-8H4"
              />
            </svg>
          )}
        </motion.button>

        {/* Hover Play Button */}
        <motion.button
          onClick={() => onWatch && onWatch(video)}
          className="absolute inset-0 flex items-center justify-center bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity"
          whileHover={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
        >
          <motion.div
            className="w-16 h-16 rounded-full bg-white/90 flex items-center justify-center"
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.95 }}
          >
            <svg
              className="w-8 h-8 text-dark-900 ml-1"
              fill="currentColor"
              viewBox="0 0 24 24"
            >
              <path d="M8 5v14l11-7z" />
            </svg>
          </motion.div>
        </motion.button>
      </div>

      {/* Content */}
      <div className={`p-4 ${compact ? 'p-3' : 'p-4'}`}>
        {/* Title */}
        <h3
          className={`
            font-semibold text-white line-clamp-2 mb-2
            group-hover:text-accent-400 transition-colors
            ${compact ? 'text-sm' : 'text-base'}
          `}
          title={title}
        >
          {title}
        </h3>

        {/* Channel & Meta */}
        <div className="flex items-center gap-2 text-dark-400 text-sm mb-3">
          <span className="truncate">{channelTitle || 'Unknown Channel'}</span>
          {(viewCount || publishedAt) && (
            <>
              <span>•</span>
              <span className="whitespace-nowrap">
                {formatViews(viewCount) || formatDate(publishedAt)}
              </span>
            </>
          )}
        </div>

        {/* Action Buttons */}
        {showActions && (
          <div className="flex items-center gap-2">
            <motion.button
              onClick={() => onSelect && onSelect(video)}
              className={`
                flex-1 py-2 px-3 rounded-lg text-sm font-medium
                transition-all duration-200
                ${
                  isSelected
                    ? 'bg-accent-500 text-white'
                    : 'bg-dark-700 text-dark-300 hover:bg-dark-600 hover:text-white'
                }
              `}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
            >
              {isSelected ? '✓ Selected' : '+ Select'}
            </motion.button>

            <motion.button
              onClick={() => onTranscript && onTranscript(video)}
              className="p-2 rounded-lg bg-dark-700 text-dark-400 hover:bg-dark-600 hover:text-white transition-colors"
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              title="View Transcript"
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
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
            </motion.button>
          </div>
        )}
      </div>

      {/* Selection Indicator Ring */}
      {isSelected && (
        <motion.div
          className="absolute top-2 right-2 z-20"
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ type: 'spring', stiffness: 500 }}
        >
          <div className="w-8 h-8 rounded-full bg-accent-500 flex items-center justify-center shadow-lg shadow-accent-500/50">
            <svg
              className="w-5 h-5 text-white"
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
          </div>
        </motion.div>
      )}
    </motion.div>
  );
};

export default VideoCard;
