import React from 'react';

/**
 * RightsBadge - Minimal non-misleading license badge for video cards.
 *
 * Rules:
 * - CC BY (blue) for verified Creative Commons.
 * - Standard License (gray) for verified YouTube Standard License.
 * - Unverified (subtle neutral) when rights data is unverified or absent.
 * - NEVER says "Copyright Safe" or shows clearance percentages.
 */
const RightsBadge = ({ rights, className = '' }) => {
  if (!rights) {
    return (
      <span
        data-testid="rights-badge-unverified"
        className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-dark-700/80 text-dark-300 border border-dark-600 ${className}`}
        title="Rights not verified with YouTube API"
      >
        Rights not verified
      </span>
    );
  }

  const { youtube_license, license_identifier, verified_metadata } = rights;

  if (verified_metadata && (youtube_license === 'creativeCommon' || license_identifier?.includes('CC BY'))) {
    return (
      <span
        data-testid="rights-badge-cc"
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-blue-900/60 text-blue-300 border border-blue-500/40 ${className}`}
        title="Verified Creative Commons Attribution (CC BY) on YouTube"
      >
        <span>⚖️</span>
        <span className="flex flex-col leading-tight">
          <span>CC BY</span>
          <span className="text-[10px] font-normal">Eligible by recorded rights · Attribution required</span>
        </span>
      </span>
    );
  }

  if (verified_metadata && youtube_license === 'youtube') {
    return (
      <span
        data-testid="rights-badge-standard"
        className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-dark-800 text-dark-400 border border-dark-600 ${className}`}
        title="Standard YouTube License — public redistribution restricted without explicit grant"
      >
        <span className="flex flex-col leading-tight">
          <span>Standard License</span>
          <span className="text-[10px] font-normal">Copyright restrictions may apply</span>
          <span className="text-[10px] font-normal">Playback/summary allowed · Publication/export not verified</span>
        </span>
      </span>
    );
  }

  return (
    <span
      data-testid="rights-badge-unverified"
      className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-dark-700/80 text-dark-300 border border-dark-600 ${className}`}
      title="Rights not verified"
    >
      Rights not verified
    </span>
  );
};

export default RightsBadge;

