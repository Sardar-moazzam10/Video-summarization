import React from 'react';

/**
 * SourceReuseReport - Displays deterministic source usage metrics.
 * 
 * Shows:
 * - Total summary output duration
 * - Per-source usage seconds, percentage ratio, clip counts, and max continuous interval
 * 
 * Invariants:
 * - No "copyright risk" or "clearance score" terminology.
 * - Purely informative factual statistics.
 */
const SourceReuseReport = ({ report }) => {
  if (!report || !report.sources) {
    return null;
  }

  const sources = Object.values(report.sources);
  if (sources.length === 0) {
    return null;
  }

  const formatSeconds = (sec) => {
    if (!sec || isNaN(sec)) return '0s';
    const m = Math.floor(sec / 60);
    const s = Math.round(sec % 60);
    if (m > 0 && s > 0) return `${m}m ${s}s`;
    if (m > 0) return `${m}m`;
    return `${s}s`;
  };

  return (
    <div className="bg-dark-900/60 rounded-xl p-4 border border-dark-700/80 text-sm">
      <div className="flex items-center justify-between pb-3 border-b border-dark-700">
        <div>
          <h4 className="font-semibold text-white flex items-center gap-2">
            <span>📊</span> Source Usage Report
          </h4>
          <p className="text-xs text-dark-400 mt-0.5">
            Objective metrics derived from highlight clips and verified source durations.
          </p>
        </div>
        <div className="text-right">
          <span className="text-xs text-dark-400 block">Total Summary Reel</span>
          <span className="text-sm font-semibold text-accent-400">
            {formatSeconds(report.total_output_seconds)}
          </span>
        </div>
      </div>

      <div className="mt-3 space-y-3">
        {sources.map((src) => {
          const ratioPercent = src.usage_ratio ? Math.round(src.usage_ratio * 100) : 0;
          return (
            <div
              key={src.video_id}
              className="bg-dark-800/80 p-3 rounded-lg border border-dark-700"
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-mono text-dark-300">
                  Source: <strong className="text-white">{src.video_id}</strong>
                </span>
                <span className="text-xs text-dark-400">
                  {src.clip_count} {src.clip_count === 1 ? 'clip' : 'clips'} selected
                </span>
              </div>

              <div className="grid grid-cols-3 gap-2 text-xs text-dark-300 mt-2">
                <div>
                  <span className="text-dark-500 block">Source Total</span>
                  <span className="font-medium text-dark-200">
                    {formatSeconds(src.source_media_seconds)}
                  </span>
                </div>
                <div>
                  <span className="text-dark-500 block">Selected Time</span>
                  <span className="font-medium text-dark-200">
                    {formatSeconds(src.used_seconds)} ({ratioPercent}%)
                  </span>
                </div>
                <div>
                  <span className="text-dark-500 block">Longest Clip</span>
                  <span className="font-medium text-dark-200">
                    {formatSeconds(src.max_continuous_interval_seconds)}
                  </span>
                </div>
              </div>

              {/* Visual usage progress bar */}
              <div className="w-full bg-dark-700/60 rounded-full h-1.5 mt-2.5 overflow-hidden">
                <div
                  className="bg-gradient-to-r from-accent-500 to-primary-500 h-1.5 rounded-full"
                  style={{ width: `${Math.min(100, Math.max(2, ratioPercent))}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default SourceReuseReport;

