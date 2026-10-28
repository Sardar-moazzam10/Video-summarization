import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { API_BASE_URL, authenticatedFetch } from '../../config/api.js';
import ReelPreviewModal from './ReelPreviewModal.jsx';

export default function ReelStudioCard({ mergeId }) {
  const [candidates, setCandidates] = useState([]);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [audioMode, setAudioMode] = useState('original'); // 'original' or 'voiceover'
  const [voiceLang, setVoiceLang] = useState('en');       // 'en', 'ur', 'hi'
  const [isRendering, setIsRendering] = useState(false);
  const [renderedReel, setRenderedReel] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [error, setError] = useState('');

  // Fetch candidate moments on mount
  useEffect(() => {
    let alive = true;
    if (!mergeId) return;

    const fetchCandidates = async () => {
      try {
        const res = await authenticatedFetch(`${API_BASE_URL}/api/v1/reel/${mergeId}/candidates`);
        if (res.ok) {
          const data = await res.json();
          if (alive && data.candidates && data.candidates.length > 0) {
            setCandidates(data.candidates);
          }
        }
      } catch (e) {
        // Gracefully ignore network errors if endpoint is unavailable or in mock test
      }
    };

    fetchCandidates();
    return () => { alive = false; };
  }, [mergeId]);

  if (!candidates || candidates.length === 0) {
    return null; // Gracefully omit if no candidates exist
  }

  const handleRender = async () => {
    setIsRendering(true);
    setError('');
    try {
      const res = await authenticatedFetch(`${API_BASE_URL}/api/v1/reel/${mergeId}/render`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          candidate_idx: selectedIdx,
          audio_mode: audioMode,
          voice_language: voiceLang,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to render 9:16 reel');
      }

      const data = await res.json();
      setRenderedReel(data);
      setModalOpen(true);
    } catch (err) {
      console.error('Reel generation error:', err);
      setError(err.message || 'Error rendering reel. Please try again.');
    } finally {
      setIsRendering(false);
    }
  };

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.28 }}
        style={{
          background: 'linear-gradient(135deg, rgba(168, 85, 247, 0.08) 0%, rgba(99, 102, 241, 0.04) 100%)',
          border: '1px solid rgba(168, 85, 247, 0.25)',
          borderRadius: '20px',
          padding: '24px',
          marginBottom: '24px',
          boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.3)',
        }}
      >
        {/* Title & Tagline */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
          <span style={{ fontSize: '1.4rem' }}>📱</span>
          <h3 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, color: '#f8fafc' }}>
            VidFusion Shorts &amp; Reels Studio
          </h3>
          <span style={{
            fontSize: '0.7rem',
            fontWeight: 700,
            padding: '2px 8px',
            borderRadius: '999px',
            background: 'rgba(168, 85, 247, 0.2)',
            color: '#c084fc',
            border: '1px solid rgba(168, 85, 247, 0.4)',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}>
            9:16 Vertical
          </span>
        </div>
        <p style={{ margin: '0 0 20px 0', fontSize: '0.9rem', color: '#94a3b8' }}>
          Transform key insights into a viral 9:16 vertical short ready for YouTube Shorts, Instagram Reels &amp; TikTok.
        </p>

        {/* Step 1: Candidate Moments */}
        <div style={{ marginBottom: '20px' }}>
          <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: '#e2e8f0', marginBottom: '10px' }}>
            1. Select a Highlight Moment:
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '10px' }}>
            {candidates.map((cand, idx) => {
              const isSelected = selectedIdx === idx;
              return (
                <div
                  key={cand.id}
                  onClick={() => setSelectedIdx(idx)}
                  style={{
                    padding: '12px 14px',
                    borderRadius: '12px',
                    background: isSelected ? 'rgba(168, 85, 247, 0.16)' : 'rgba(255, 255, 255, 0.03)',
                    border: isSelected ? '1.5px solid #a855f7' : '1px solid rgba(255, 255, 255, 0.08)',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <span style={{ fontSize: '0.85rem', fontWeight: 700, color: isSelected ? '#e9d5ff' : '#f1f5f9' }}>
                      {cand.title}
                    </span>
                    <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', background: 'rgba(255,255,255,0.06)', padding: '2px 6px', borderRadius: '4px' }}>
                      {Math.round(cand.duration_seconds)}s
                    </span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: cand.is_cc_by ? '#4ade80' : '#c084fc', fontWeight: 500 }}>
                    {cand.license_label}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Step 2: Audio Mode Selection */}
        <div style={{ marginBottom: '20px' }}>
          <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 600, color: '#e2e8f0', marginBottom: '10px' }}>
            2. Choose Audio Track:
          </label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
            <button
              type="button"
              onClick={() => setAudioMode('original')}
              style={{
                flex: '1 1 200px',
                padding: '10px 16px',
                borderRadius: '12px',
                background: audioMode === 'original' ? 'rgba(59, 130, 246, 0.2)' : 'rgba(255, 255, 255, 0.04)',
                border: audioMode === 'original' ? '1.5px solid #3b82f6' : '1px solid rgba(255, 255, 255, 0.1)',
                color: audioMode === 'original' ? '#93c5fd' : '#cbd5e1',
                fontWeight: 600,
                fontSize: '0.85rem',
                cursor: 'pointer',
                textAlign: 'left',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              <span style={{ fontSize: '1.1rem' }}>🔊</span>
              <div>
                <div>Original Speaker Audio</div>
                <div style={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: 400 }}>Natural speaker voice from clip</div>
              </div>
            </button>

            <button
              type="button"
              onClick={() => setAudioMode('voiceover')}
              style={{
                flex: '1 1 200px',
                padding: '10px 16px',
                borderRadius: '12px',
                background: audioMode === 'voiceover' ? 'rgba(168, 85, 247, 0.2)' : 'rgba(255, 255, 255, 0.04)',
                border: audioMode === 'voiceover' ? '1.5px solid #a855f7' : '1px solid rgba(255, 255, 255, 0.1)',
                color: audioMode === 'voiceover' ? '#e9d5ff' : '#cbd5e1',
                fontWeight: 600,
                fontSize: '0.85rem',
                cursor: 'pointer',
                textAlign: 'left',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              <span style={{ fontSize: '1.1rem' }}>🎙️</span>
              <div>
                <div>AI Narrator Voiceover</div>
                <div style={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: 400 }}>Studio summary narration (Fair-Use)</div>
              </div>
            </button>
          </div>

          {/* Voice Language Selector (when voiceover is chosen) */}
          {audioMode === 'voiceover' && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              style={{ marginTop: '12px', padding: '12px 14px', borderRadius: '10px', background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(255,255,255,0.06)' }}
            >
              <span style={{ fontSize: '0.8rem', color: '#cbd5e1', fontWeight: 500, marginRight: '10px' }}>
                Narrator Voice &amp; Language:
              </span>
              <select
                value={voiceLang}
                onChange={(e) => setVoiceLang(e.target.value)}
                style={{
                  background: '#1e293b',
                  color: '#f8fafc',
                  border: '1px solid #475569',
                  borderRadius: '6px',
                  padding: '6px 10px',
                  fontSize: '0.8rem',
                  outline: 'none',
                }}
              >
                <option value="en">🇺🇸 English (Guy Studio Neural)</option>
                <option value="ur">🇵🇰 Urdu (Uzma Natural Neural)</option>
                <option value="hi">🇮🇳 Hindi (Swara Natural Neural)</option>
              </select>
            </motion.div>
          )}
        </div>

        {/* Error notification */}
        {error && (
          <div style={{ marginBottom: '16px', padding: '10px', borderRadius: '8px', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid rgba(239, 68, 68, 0.3)', color: '#fca5a5', fontSize: '0.85rem' }}>
            {error}
          </div>
        )}

        {/* Action Button */}
        <button
          onClick={handleRender}
          disabled={isRendering}
          style={{
            padding: '12px 24px',
            borderRadius: '12px',
            background: isRendering ? 'rgba(168, 85, 247, 0.5)' : 'linear-gradient(135deg, #a855f7 0%, #6366f1 100%)',
            color: '#fff',
            fontWeight: 700,
            fontSize: '0.95rem',
            border: 'none',
            cursor: isRendering ? 'not-allowed' : 'pointer',
            boxShadow: '0 4px 14px rgba(168, 85, 247, 0.35)',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <span>{isRendering ? '⚙️' : '🎬'}</span>
          <span>{isRendering ? 'Rendering 9:16 Vertical Reel (~4s)...' : 'Generate 9:16 Vertical Reel'}</span>
        </button>
      </motion.div>

      {/* 9:16 Smartphone Mockup Modal */}
      <ReelPreviewModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        reelData={renderedReel}
        API_BASE_URL={API_BASE_URL}
      />
    </>
  );
}
