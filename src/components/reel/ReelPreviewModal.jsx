import React, { useState } from 'react';
import { motion } from 'framer-motion';

export default function ReelPreviewModal({ isOpen, onClose, reelData, API_BASE_URL }) {
  const [copied, setCopied] = useState(false);

  if (!isOpen || !reelData) return null;

  const downloadUrl = `${API_BASE_URL}${reelData.video_url}?download=true`;
  const streamUrl = `${API_BASE_URL}${reelData.video_url}`;

  const hashtags = '#VidFusion #Shorts #Reels #AI #Summary #Knowledge';

  const handleCopyTags = () => {
    navigator.clipboard.writeText(hashtags);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 9999,
        background: 'rgba(0, 0, 0, 0.85)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
      }}
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.9, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.9 }}
        style={{
          background: '#0f172a',
          border: '1px solid rgba(255, 255, 255, 0.12)',
          borderRadius: '24px',
          padding: '24px',
          maxWidth: '460px',
          width: '100%',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 700, color: '#f8fafc' }}>
              📱 9:16 Reel Preview
            </h3>
            <p style={{ margin: '4px 0 0 0', fontSize: '0.8rem', color: '#94a3b8' }}>
              {reelData.candidate?.title || 'Viral Video Short'}
            </p>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'rgba(255, 255, 255, 0.08)',
              border: 'none',
              borderRadius: '50%',
              width: '32px',
              height: '32px',
              color: '#94a3b8',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '14px',
            }}
          >
            ✕
          </button>
        </div>

        {/* License Pill */}
        <div style={{
          width: '100%',
          padding: '8px 12px',
          borderRadius: '8px',
          background: reelData.safe_to_export ? 'rgba(34, 197, 94, 0.12)' : 'rgba(168, 85, 247, 0.12)',
          border: reelData.safe_to_export ? '1px solid rgba(34, 197, 94, 0.3)' : '1px solid rgba(168, 85, 247, 0.3)',
          color: reelData.safe_to_export ? '#4ade80' : '#c084fc',
          fontSize: '0.8rem',
          fontWeight: 600,
          marginBottom: '16px',
          textAlign: 'center',
        }}>
          {reelData.safe_to_export
            ? '⚖️ Creative Commons (CC BY) — 100% Free to Monetize & Publish'
            : (reelData.audio_mode === 'voiceover'
                ? '🛡️ Transformative Commentary Mode — Original audio stripped for Fair-Use'
                : '🔒 Standard License — Private in-app study preview')}
        </div>

        {/* Smartphone Frame (9:16 Mockup) */}
        <div
          style={{
            width: '240px',
            height: '426px',
            background: '#000',
            borderRadius: '32px',
            border: '4px solid #334155',
            boxShadow: '0 0 0 2px rgba(255,255,255,0.1), 0 20px 25px -5px rgba(0,0,0,0.5)',
            position: 'relative',
            overflow: 'hidden',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: '20px',
          }}
        >
          {/* Phone Speaker Notch */}
          <div style={{
            position: 'absolute',
            top: '8px',
            width: '60px',
            height: '4px',
            background: '#334155',
            borderRadius: '4px',
            zIndex: 10,
          }} />

          {/* 9:16 Video Player */}
          <video
            key={streamUrl}
            src={streamUrl}
            controls
            playsInline
            preload="metadata"
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'cover',
            }}
          >
            <source src={streamUrl} type="video/mp4" />
            Your browser does not support video playback.
          </video>
        </div>

        {/* Action Buttons */}
        <div style={{ width: '100%', display: 'flex', gap: '10px' }}>
          <a
            href={downloadUrl}
            download
            style={{
              flex: 1,
              padding: '12px 16px',
              borderRadius: '12px',
              background: 'linear-gradient(135deg, #a855f7 0%, #6366f1 100%)',
              color: '#fff',
              fontWeight: 600,
              fontSize: '0.9rem',
              textAlign: 'center',
              textDecoration: 'none',
              boxShadow: '0 4px 14px rgba(168, 85, 247, 0.4)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
            }}
          >
            <span>⬇️</span> Download Reel
          </a>
          <button
            onClick={handleCopyTags}
            style={{
              padding: '12px 16px',
              borderRadius: '12px',
              background: 'rgba(255, 255, 255, 0.08)',
              border: '1px solid rgba(255, 255, 255, 0.15)',
              color: '#e2e8f0',
              fontWeight: 600,
              fontSize: '0.9rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span>📋</span> {copied ? 'Copied!' : 'Copy Tags'}
          </button>
        </div>
      </motion.div>
    </div>
  );
}

