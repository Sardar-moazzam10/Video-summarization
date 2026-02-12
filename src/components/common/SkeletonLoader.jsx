/**
 * SkeletonLoader - Professional loading skeleton components
 *
 * Features:
 * - Multiple skeleton types
 * - Shimmer animation
 * - Customizable sizing
 * - Dark theme optimized
 */

import React from 'react';
import { motion } from 'framer-motion';

// Base skeleton with shimmer
const SkeletonBase = ({ className = '', children }) => (
  <div
    className={`
      relative overflow-hidden
      bg-dark-800 rounded-lg
      before:absolute before:inset-0
      before:bg-gradient-to-r before:from-transparent before:via-dark-700/50 before:to-transparent
      before:animate-shimmer
      ${className}
    `}
    style={{
      backgroundSize: '200% 100%',
    }}
  >
    {children}
  </div>
);

// Text skeleton
export const SkeletonText = ({ lines = 1, className = '' }) => (
  <div className={`space-y-2 ${className}`}>
    {Array.from({ length: lines }).map((_, i) => (
      <SkeletonBase
        key={i}
        className={`h-4 ${i === lines - 1 ? 'w-3/4' : 'w-full'}`}
      />
    ))}
  </div>
);

// Avatar skeleton
export const SkeletonAvatar = ({ size = 'md', className = '' }) => {
  const sizes = {
    sm: 'w-8 h-8',
    md: 'w-12 h-12',
    lg: 'w-16 h-16',
    xl: 'w-24 h-24',
  };

  return (
    <SkeletonBase className={`${sizes[size]} rounded-full ${className}`} />
  );
};

// Video card skeleton
export const SkeletonVideoCard = ({ compact = false }) => (
  <div
    className={`
      rounded-2xl overflow-hidden bg-dark-800/50 border border-dark-700
      ${compact ? 'p-2' : ''}
    `}
  >
    {/* Thumbnail */}
    <SkeletonBase className="aspect-video w-full" />

    {/* Content */}
    <div className={compact ? 'p-3' : 'p-4'}>
      {/* Title */}
      <SkeletonText lines={2} className="mb-3" />

      {/* Meta */}
      <div className="flex items-center gap-2 mb-3">
        <SkeletonBase className="h-3 w-24" />
        <SkeletonBase className="h-3 w-16" />
      </div>

      {/* Buttons */}
      <div className="flex gap-2">
        <SkeletonBase className="h-10 flex-1 rounded-lg" />
        <SkeletonBase className="h-10 w-10 rounded-lg" />
      </div>
    </div>
  </div>
);

// Video grid skeleton
export const SkeletonVideoGrid = ({ count = 6, columns = 3 }) => (
  <div
    className={`grid gap-6 grid-cols-1 sm:grid-cols-2 lg:grid-cols-${columns}`}
  >
    {Array.from({ length: count }).map((_, i) => (
      <motion.div
        key={i}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: i * 0.1 }}
      >
        <SkeletonVideoCard />
      </motion.div>
    ))}
  </div>
);

// Summary panel skeleton
export const SkeletonSummary = () => (
  <div className="space-y-6">
    {/* Header */}
    <div className="flex items-center gap-4">
      <SkeletonBase className="w-16 h-16 rounded-xl" />
      <div className="flex-1">
        <SkeletonBase className="h-6 w-48 mb-2" />
        <SkeletonBase className="h-4 w-32" />
      </div>
    </div>

    {/* Stats */}
    <div className="grid grid-cols-4 gap-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="text-center">
          <SkeletonBase className="h-8 w-16 mx-auto mb-2" />
          <SkeletonBase className="h-3 w-20 mx-auto" />
        </div>
      ))}
    </div>

    {/* Content */}
    <div className="space-y-4">
      <SkeletonText lines={4} />
      <SkeletonText lines={3} />
      <SkeletonText lines={4} />
    </div>
  </div>
);

// Progress skeleton
export const SkeletonProgress = () => (
  <div className="space-y-6">
    {/* Progress bar */}
    <SkeletonBase className="h-3 w-full rounded-full" />

    {/* Stages */}
    <div className="flex justify-between">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex flex-col items-center gap-2">
          <SkeletonBase className="w-12 h-12 rounded-full" />
          <SkeletonBase className="h-3 w-16" />
        </div>
      ))}
    </div>

    {/* Status card */}
    <div className="p-6 rounded-2xl bg-dark-800/50 border border-dark-700">
      <div className="flex items-start gap-4">
        <SkeletonBase className="w-14 h-14 rounded-xl" />
        <div className="flex-1">
          <SkeletonBase className="h-5 w-32 mb-2" />
          <SkeletonBase className="h-4 w-48" />
        </div>
      </div>
    </div>
  </div>
);

// Search bar skeleton
export const SkeletonSearchBar = () => (
  <div className="flex gap-3">
    <SkeletonBase className="flex-1 h-14 rounded-xl" />
    <SkeletonBase className="w-32 h-14 rounded-xl" />
  </div>
);

// Default export with all variants
const SkeletonLoader = {
  Base: SkeletonBase,
  Text: SkeletonText,
  Avatar: SkeletonAvatar,
  VideoCard: SkeletonVideoCard,
  VideoGrid: SkeletonVideoGrid,
  Summary: SkeletonSummary,
  Progress: SkeletonProgress,
  SearchBar: SkeletonSearchBar,
};

export default SkeletonLoader;
