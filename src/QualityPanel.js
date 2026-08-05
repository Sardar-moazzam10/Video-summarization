import React, { useEffect, useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import { API_BASE_URL } from './config/api.js';

/**
 * Quality scorecard panel — shows TWO separate scores for a completed job:
 *
 *   Summary score (Check A): is the AI summary a faithful summary of the
 *       original video?  (summary vs original transcript)
 *   Video score (Check B): do the generated highlight clips represent the
 *       summary?  (clip transcripts vs summary) — expected to be high.
 *
 * Fast scores (keyword + SBERT) load automatically (llm=false, <1s).
 * The "Run detailed analysis" button re-runs WITH the Ollama judge
 * (llm=true, 30-90s) and replaces the scores with the richer, judged ones.
 */

function scoreColor(score) {
  if (score === null || score === undefined) return '#6b7280';
  if (score >= 75) return '#22c55e';   // green  — good
  if (score >= 55) return '#f59e0b';   // amber  — fair
  return '#ef4444';                    // red    — weak
}

function ScoreDial({ label, sublabel, score }) {
  const color = scoreColor(score);
  const display = score === null || score === undefined ? '–' : `${Math.round(score)}%`;
  const pct = score === null || score === undefined ? 0 : score;
  const r = 34;
  const circ = 2 * Math.PI * r;

  return (
    <div style={dialStyles.wrap}>
      <div style={dialStyles.ringBox}>
        <svg width="90" height="90" viewBox="0 0 90 90" style={{ transform: 'rotate(-90deg)' }}>
          <circle cx="45" cy="45" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="7" />
          <circle
            cx="45" cy="45" r={r} fill="none"
            stroke={color} strokeWidth="7" strokeLinecap="round"
            strokeDasharray={`${circ}`}
            strokeDashoffset={`${circ * (1 - pct / 100)}`}
            style={{ transition: 'stroke-dashoffset 0.6s ease, stroke 0.4s ease' }}
          />
        </svg>
        <span style={{ ...dialStyles.value, color }}>{display}</span>
      </div>
      <span style={dialStyles.label}>{label}</span>
      <span style={dialStyles.sub}>{sublabel}</span>
    </div>
  );
}

function DetailList({ title, items }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ marginTop: 10 }}>
      <span style={panelStyles.detailTitle}>{title}</span>
      <ul style={panelStyles.detailUl}>
        {items.slice(0, 5).map((it, i) => (
          <li key={i} style={panelStyles.detailLi}>
            {typeof it === 'string' ? it : (it.text || JSON.stringify(it))}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function QualityPanel({ mergeId, delay = 0.18 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [judging, setJudging] = useState(false);
  const [error, setError] = useState('');

  const fetchScores = useCallback(async (withLlm) => {
    const url = `${API_BASE_URL}/api/v1/merge/${mergeId}/evaluate?llm=${withLlm ? 'true' : 'false'}`;
    const res = await fetch(url);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Evaluation failed (${res.status})`);
    }
    return res.json();
  }, [mergeId]);

  // Fast scores on mount
  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchScores(false)
      .then((d) => { if (alive) { setData(d); setError(''); } })
      .catch((e) => { if (alive) setError(e.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [fetchScores]);

  // Full scores on button click (with Ollama judge)
  const runDetailed = async () => {
    setJudging(true);
    setError('');
    try {
      const d = await fetchScores(true);
      setData(d);
    } catch (e) {
      setError(e.message);
    } finally {
      setJudging(false);
    }
  };

  if (loading) {
    return (
      <motion.div style={panelStyles.card} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay }}>
        <div style={panelStyles.header}>
          <span style={panelStyles.title}>Quality Check</span>
        </div>
        <p style={panelStyles.muted}>Measuring summary & video quality…</p>
      </motion.div>
    );
  }

  if (error && !data) {
    return (
      <motion.div style={panelStyles.card} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay }}>
        <div style={panelStyles.header}><span style={panelStyles.title}>Quality Check</span></div>
        <p style={{ ...panelStyles.muted, color: '#f59e0b' }}>Could not evaluate: {error}</p>
      </motion.div>
    );
  }

  const a = data.check_a || {};
  const b = data.check_b || {};
  const aLlm = a.llm_judge || {};
  const bLlm = b.llm_judge || {};

  return (
    <motion.div style={panelStyles.card} initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay }}>
      <div style={panelStyles.header}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="2">
          <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
        </svg>
        <span style={panelStyles.title}>Quality Check</span>
        <span style={panelStyles.badgeMode}>{data.llm_used ? 'Detailed (LLM judged)' : 'Fast'}</span>
      </div>

      <p style={panelStyles.intro}>
        Verifies that the summary captures the real video — and that the generated video matches the summary.
        No guessing: scores compare against the original transcript.
      </p>

      <div style={panelStyles.dials}>
        <ScoreDial
          label="AI Summary"
          sublabel="matches the original video"
          score={data.summary_score}
        />
        <ScoreDial
          label="Video"
          sublabel="matches the summary"
          score={data.video_score}
        />
      </div>

      {/* Per-score verdicts */}
      <div style={panelStyles.verdicts}>
        {a.verdict && <p style={panelStyles.verdict}><b style={{ color: scoreColor(data.summary_score) }}>Summary:</b> {a.verdict}</p>}
        {b.verdict && <p style={panelStyles.verdict}><b style={{ color: scoreColor(data.video_score) }}>Video:</b> {b.verdict}</p>}
      </div>

      {/* Detailed findings only appear after the LLM judge runs */}
      {data.llm_used && (
        <div style={panelStyles.details}>
          <DetailList title="Possibly guessed / unsupported in summary" items={aLlm.hallucinations} />
          <DetailList title="Important points the summary missed" items={aLlm.missing_key_points} />
          <DetailList title="Summary points missing from the video" items={bLlm.summary_points_missing_from_clips} />
        </div>
      )}

      {!data.llm_used && (
        <button
          style={{ ...panelStyles.button, opacity: judging ? 0.6 : 1, cursor: judging ? 'wait' : 'pointer' }}
          onClick={runDetailed}
          disabled={judging}
        >
          {judging ? 'Analyzing with local AI… (~30–90s)' : 'Run detailed analysis (LLM judge)'}
        </button>
      )}
      {error && data && <p style={{ ...panelStyles.muted, color: '#f59e0b', marginTop: 8 }}>{error}</p>}
    </motion.div>
  );
}

const dialStyles = {
  wrap: { display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1, minWidth: 120 },
  ringBox: { position: 'relative', width: 90, height: 90, display: 'flex', alignItems: 'center', justifyContent: 'center' },
  value: { position: 'absolute', fontSize: 20, fontWeight: 800 },
  label: { marginTop: 8, fontSize: 14, fontWeight: 700, color: '#fff' },
  sub: { fontSize: 11, color: 'rgba(255,255,255,0.45)', textAlign: 'center' },
};

const panelStyles = {
  card: {
    background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
    borderRadius: 16, padding: 22, marginBottom: 20,
  },
  header: { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 },
  title: { fontSize: 16, fontWeight: 700, color: '#fff' },
  badgeMode: {
    marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,0.6)',
    background: 'rgba(255,255,255,0.06)', padding: '3px 8px', borderRadius: 20,
  },
  intro: { fontSize: 12.5, color: 'rgba(255,255,255,0.5)', margin: '0 0 16px', lineHeight: 1.5 },
  dials: { display: 'flex', gap: 16, justifyContent: 'center', flexWrap: 'wrap' },
  verdicts: { marginTop: 16 },
  verdict: { fontSize: 12.5, color: 'rgba(255,255,255,0.7)', margin: '4px 0', lineHeight: 1.45 },
  details: { marginTop: 8, borderTop: '1px solid rgba(255,255,255,0.07)', paddingTop: 8 },
  detailTitle: { fontSize: 12, fontWeight: 700, color: 'rgba(255,255,255,0.75)' },
  detailUl: { margin: '4px 0 0', paddingLeft: 18 },
  detailLi: { fontSize: 12, color: 'rgba(255,255,255,0.55)', margin: '2px 0', lineHeight: 1.4 },
  button: {
    marginTop: 18, width: '100%', padding: '11px 16px', borderRadius: 10, border: 'none',
    background: 'linear-gradient(135deg, #478BE0, #a855f7)', color: '#fff',
    fontSize: 13.5, fontWeight: 600,
  },
  muted: { fontSize: 13, color: 'rgba(255,255,255,0.5)', margin: 0 },
};
