import React, { useState, useEffect } from 'react';
import { API_BASE_URL, authenticatedFetch } from '../../config/api.js';
import SourceReuseReport from './SourceReuseReport.jsx';

/**
 * RightsPanel - Result view panel for source rights, attribution, and publication guidance.
 *
 * Distinguishes private study summary export (unrestricted) from public publication.
 */
const RightsPanel = ({ jobId, initialGateStatus = 'manual_review_required' }) => {
  const [manifest, setManifest] = useState(null);
  const [loading, setLoading] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!jobId) return;

    let isMounted = true;
    setLoading(true);

    authenticatedFetch(`${API_BASE_URL}/api/v1/rights/job/${jobId}/manifest`)
      .then((res) => {
        if (!res.ok) throw new Error('Could not fetch rights manifest');
        return res.json();
      })
      .then((data) => {
        if (isMounted) setManifest(data);
      })
      .catch((err) => {
        console.warn('[RightsPanel] Manifest fetch failed:', err);
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [jobId]);

  const gateStatus = manifest?.publication_gate_status || initialGateStatus;
  const rawWarnings = manifest?.gate_warnings || [];
  const warnings = Array.from(
    new Set(rawWarnings.map((w) => (typeof w === 'string' ? w.trim() : '')).filter(Boolean))
  );
  const attributionBlock = manifest?.attribution_block;

  const handleCopyAttribution = () => {
    if (!attributionBlock) return;
    navigator.clipboard.writeText(attributionBlock);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getGateBadge = () => {
    switch (gateStatus) {
      case 'eligible_by_recorded_rights':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-950/60 text-emerald-300 border border-emerald-500/40">
            <span>✓</span> Public Publication: Eligible by Recorded Rights
          </span>
        );
      case 'manual_review_required':
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-950/60 text-amber-300 border border-amber-500/40">
            <span>⚠️</span> Public Publication: Manual Review Required
          </span>
        );
      case 'restricted_by_product_policy':
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-dark-800 text-dark-300 border border-dark-600">
            <span>🔒</span> Public Publication: Restricted by Product Policy
          </span>
        );
    }
  };

  return (
    <div className="bg-dark-900/80 rounded-2xl border border-dark-700/80 p-5 mt-6 shadow-xl">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-dark-700">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-dark-800 flex items-center justify-center text-lg border border-dark-600">
            ⚖️
          </div>
          <div>
            <h3 className="font-semibold text-white text-base">
              Rights & Publication Guidance
            </h3>
            <p className="text-xs text-dark-400 mt-0.5">
              Source provenance, attribution metadata, and publication policy status.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {getGateBadge()}
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1.5 text-dark-400 hover:text-white hover:bg-dark-800 rounded-lg transition-colors text-xs font-medium"
            title={isExpanded ? 'Collapse section' : 'Expand section'}
          >
            {isExpanded ? '▲ Hide' : '▼ Details'}
          </button>
        </div>
      </div>

      {/* Primary Study Notice */}
      <div className="mt-3 p-2.5 rounded-xl bg-dark-800/60 border border-dark-700 text-xs text-dark-300 flex items-start gap-2">
        <span className="text-sm">ℹ️</span>
        <div>
          <strong className="text-dark-200">Private Study & Analysis:</strong>{' '}
          Generated TXT/PDF notes remain available. Standard License reels may be privately
          previewed in-app, but source video/audio download, public media export, publication,
          and redistribution remain blocked unless recorded rights make the job eligible.
        </div>
      </div>

      {/* Expandable Details */}
      {isExpanded && (
        <div className="mt-4 space-y-4 pt-2">
          {/* Gate Warnings */}
          {warnings.length > 0 && (
            <div className="bg-amber-950/20 border border-amber-600/30 rounded-xl p-3 text-xs text-amber-200 space-y-1">
              <span className="font-semibold block text-amber-300">Policy Notes:</span>
              <ul className="list-disc list-inside space-y-0.5">
                {warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {manifest?.snapshot_origin && (
            <p className="text-[11px] text-dark-400">
              Evidence snapshot: {manifest.snapshot_origin === 'job_evaluation'
                ? `frozen at job evaluation (${manifest.policy_version || 'policy version unavailable'})`
                : 'reconstructed for legacy inspection only'}
            </p>
          )}

          {manifest?.sources?.length > 0 && (
            <div className="space-y-2">
              <span className="text-xs font-semibold text-white">Source Rights</span>
              {manifest.sources.map((source) => (
                <div key={source.source_id} className="rounded-lg border border-dark-700 bg-dark-800/70 p-3 text-xs">
                  <div className="font-medium text-dark-100">
                    {source.title || source.source_id}
                  </div>
                  <div className="mt-1 text-dark-400">
                    Evidence: {(source.verification_status || 'unverified').replaceAll('_', ' ')}
                    {' · '}Status: {(source.publication_gate_status || 'restricted_by_product_policy').replaceAll('_', ' ')}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Attribution Box */}
          {attributionBlock && (
            <div className="bg-dark-800/80 rounded-xl p-3 border border-dark-700 text-xs">
              <div className="flex items-center justify-between mb-1.5">
                <span className="font-semibold text-white">Attribution Notice:</span>
                <button
                  type="button"
                  onClick={handleCopyAttribution}
                  className="px-2 py-1 rounded bg-dark-700 hover:bg-dark-600 text-dark-200 text-xs font-medium transition-colors"
                >
                  {copied ? '✓ Copied!' : 'Copy Attribution'}
                </button>
              </div>
              <pre className="p-2 rounded bg-dark-900/90 text-dark-300 font-mono text-[11px] whitespace-pre-wrap overflow-x-auto border border-dark-700">
                {attributionBlock}
              </pre>
            </div>
          )}

          {/* Objective Source Usage Report */}
          {manifest?.source_reuse_report && (
            <SourceReuseReport report={manifest.source_reuse_report} />
          )}

          {loading && (
            <p className="text-xs text-dark-400 italic">Updating rights metadata...</p>
          )}
        </div>
      )}
    </div>
  );
};

export default RightsPanel;

