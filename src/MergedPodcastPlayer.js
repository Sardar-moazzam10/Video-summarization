import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import { API_BASE_URL, authenticatedFetch } from './config/api.js';
import { extractErrorMessage } from './utils/apiError.js';
import { getStepStatus, monotonicPercent, nextVisitedStages } from './utils/progressState.js';
import QualityPanel from './QualityPanel.js';
import RightsPanel from './components/rights/RightsPanel.jsx';
import VideoChatPanel from './components/chat/VideoChatPanel.jsx';
import { formatCompressionMetric, formatTopicsCount, resolveTopicsList } from './utils/resultMetrics.js';

const LANGUAGE_NAMES = { hi: "Hindi", en: "English", ar: "Arabic", zh: "Chinese", es: "Spanish", fr: "French" };
const displayLanguage = (code) => LANGUAGE_NAMES[code] || code || "unsupported";

const STAGES = [
  { key: 'transcribing', label: 'Transcribing', icon: '01' },
  { key: 'analyzing', label: 'Analyzing', icon: '02' },
  { key: 'fusing', label: 'Selecting', icon: '03' },
  { key: 'generating_video', label: 'Video Gen', icon: '04' },
  { key: 'video_ready', label: 'Video Ready', icon: '05' },
  { key: 'summarizing', label: 'Summarizing', icon: '06' },
  { key: 'enriching', label: 'AI Enriching', icon: '07' },
  { key: 'generating_voice', label: 'Voice Gen', icon: '08' },
];

const MergedPodcastPlayer = () => {
  const { mergeId } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState('pending');
  const [stage, setStage] = useState('Initializing...');
  const [progressPercent, setProgressPercent] = useState(0);
  // Stages ever seen, so a step badge never regresses to "pending" once shown
  // — see utils/progressState.js for the rewind bug this fixes.
  const [visitedStages, setVisitedStages] = useState(() => new Set());
  const [summary, setSummary] = useState('');
  const [audioUrl, setAudioUrl] = useState('');
  const [metadata, setMetadata] = useState(null);
  const [richOutput, setRichOutput] = useState(null);
  const [videoUrl, setVideoUrl] = useState('');
  const [chatQuestion, setChatQuestion] = useState('');
  const [chatAnswer, setChatAnswer] = useState(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [error, setError] = useState('');
  const [warning, setWarning] = useState('');
  const [videoId, setVideoId] = useState('');
  const [videoIds, setVideoIds] = useState([]);
  const [isCompiling, setIsCompiling] = useState(false);
  const [compileError, setCompileError] = useState('');
  const location = useLocation();
  const [jobQuery, setJobQuery] = useState(location.state?.query || '');
  // This job's own settings, echoed back by /result. Carried into the
  // highlight-reel job so it reproduces THIS summary instead of a new one.
  const [jobSettings, setJobSettings] = useState({});
  // Full result payload from /result, used to read summary_unavailable and
  // other fields that the status endpoint (/merge/{id}) does not carry.
  const [resultData, setResultData] = useState(null);
  const [videoComponent, setVideoComponent] = useState(null);
  const [textComponent, setTextComponent] = useState(null);
  const pollTimeoutRef = useRef(null);
  const pollGenerationRef = useRef(0);
  const pollAbortRef = useRef(null);
  const videoFetchedRef = useRef(false);
  const historySavedRef = useRef(false);
  const videoRef = useRef(null);

  const handleSeekToTimestamp = (seconds) => {
    if (videoRef.current) {
      videoRef.current.currentTime = seconds;
      videoRef.current.play().catch(() => {});
      videoRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  };

  const getPollInterval = (status) => {
    switch (status) {
      case 'transcribing': return 5000;
      case 'analyzing': return 2000;
      case 'fusing': return 3000;
      case 'summarizing': return 3000;
      case 'enriching': return 3000;
      case 'generating_voice': return 4000;
      case 'generating_video': return 5000;
      case 'video_ready': return 2000;
      default: return 3000;
    }
  };

  const fetchStatus = async (generation, signal) => {
    try {
      const res = await authenticatedFetch(`${API_BASE_URL}/api/v1/merge/${mergeId}`, { signal });
      if (pollGenerationRef.current !== generation) return;
      if (!res.ok) throw new Error(`Status request failed (${res.status})`);
      const statusData = await res.json();
      if (pollGenerationRef.current !== generation) return;
      const currentStatus = statusData.status;
      setVideoComponent(statusData.video_component || null);
      setTextComponent(statusData.text_component || null);
      if (statusData.query) {
        setJobQuery((prev) => prev || statusData.query);
      }
      setStatus(currentStatus);
      setStage(statusData.stage_message || 'Processing...');
      setVisitedStages((prev) => nextVisitedStages(prev, currentStatus));
      setProgressPercent((prev) => monotonicPercent(prev, statusData.progress_percent || 0));

      const componentReady = ['ready', 'failed'].includes(statusData.video_component?.status)
        || ['ready', 'failed'].includes(statusData.text_component?.status);
      if (currentStatus === 'completed' || currentStatus === 'partial_success' || componentReady) {
        const resultRes = await authenticatedFetch(`${API_BASE_URL}/api/v1/merge/${mergeId}/result`);
        if (!resultRes.ok) throw new Error(`Result request failed (${resultRes.status})`);
        const result = await resultRes.json();
        if (result.query) {
          setJobQuery(result.query);
        }
        setSummary(result.summary_text || '');
        setMetadata(result.metadata || null);
        setRichOutput(result.rich_output || null);
        setVideoId(result.highlight_segments?.[0]?.video_id || result.video_ids?.[0] || '');
        setVideoIds(result.video_ids || []);
        setJobSettings({
          target_duration_minutes: result.target_duration_minutes,
          style: result.rich_output?.style_applied,
        });
        setResultData(result);
        setVideoComponent(result.video_component || statusData.video_component || null);
        setTextComponent(result.text_component || statusData.text_component || null);
        setWarning(result.warning || statusData.warning || '');
        if (result.audio_url) {
          setAudioUrl(`${API_BASE_URL}${result.audio_url}`);
        }
        if (result.video_url) {
          setVideoUrl(`${API_BASE_URL}${result.video_url}`);
        }
        if (currentStatus === 'completed' || currentStatus === 'partial_success') {
          saveToHistory(result);
        }
        if (currentStatus !== 'completed' && currentStatus !== 'partial_success') {
          const pollInterval = getPollInterval(currentStatus);
          pollTimeoutRef.current = setTimeout(() => fetchStatus(generation, signal), pollInterval);
        }
      } else if (currentStatus === 'error') {
        setError(statusData.error || 'An unknown error occurred.');
      } else {
        if ((currentStatus === 'video_ready' || Boolean(statusData.has_video_ready) || ['summarizing', 'enriching', 'generating_voice'].includes(currentStatus)) && !videoFetchedRef.current) {
          authenticatedFetch(`${API_BASE_URL}/api/v1/merge/${mergeId}/result`)
            .then(async (videoRes) => {
              if (!videoRes.ok) throw new Error(`Result request failed (${videoRes.status})`);
              const videoResult = await videoRes.json();
              if (videoResult.query) {
                setJobQuery((prev) => prev || videoResult.query);
              }
              setResultData(videoResult);
              if (videoResult.video_url) {
                setVideoUrl(`${API_BASE_URL}${videoResult.video_url}`);
                // Do not mark the media fetch as complete until the renderer
                // has actually persisted a playable URL. Text processing can
                // reach `summarizing` before FFmpeg finishes, so polling must
                // keep retrying meanwhile.
                videoFetchedRef.current = true;
              }
              setVideoId(videoResult.highlight_segments?.[0]?.video_id || videoResult.video_ids?.[0] || '');
              setVideoIds(videoResult.video_ids || []);
              if (videoResult.summary_text) setSummary(videoResult.summary_text);
              if (videoResult.rich_output) setRichOutput(videoResult.rich_output);
              if (videoResult.metadata && Object.keys(videoResult.metadata).length > 0) setMetadata(videoResult.metadata);
              if (videoResult.audio_url) setAudioUrl(`${API_BASE_URL}${videoResult.audio_url}`);
            })
            .catch(() => {});
        }
        const pollInterval = getPollInterval(currentStatus);
        pollTimeoutRef.current = setTimeout(() => fetchStatus(generation, signal), pollInterval);
      }
    } catch (err) {
      if (pollGenerationRef.current !== generation) return;
      console.error("Polling error:", err);
      setError('Connection to merge server failed.');
    }
  };

  useEffect(() => {
    // EventSource cannot attach a Bearer header. Authenticated polling keeps
    // progress private and adapts its interval to the current pipeline stage.
    const generation = pollGenerationRef.current + 1;
    pollGenerationRef.current = generation;
    videoFetchedRef.current = false;
    const controller = new AbortController();
    pollAbortRef.current = controller;
    pollTimeoutRef.current = setTimeout(
      () => fetchStatus(generation, controller.signal),
      0
    );

    return () => {
      pollGenerationRef.current += 1;
      controller.abort();
      if (pollAbortRef.current === controller) pollAbortRef.current = null;
      if (pollTimeoutRef.current) {
        clearTimeout(pollTimeoutRef.current);
        pollTimeoutRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mergeId]);

  const handleBack = () => {
    if (location.state?.from) {
      navigate(location.state.from);
    } else if (jobQuery) {
      navigate('/search-by-keywords');
    } else {
      navigate('/search-by-title');
    }
  };

  const getCurrentStepStatus = (stepName) => getStepStatus(stepName, status, visitedStages);

  const knownComponents = [videoComponent, textComponent].filter(Boolean);
  const componentsTerminal = knownComponents.length > 0 && knownComponents
    .every((item) => ['ready', 'failed', 'cancelled', 'not_requested'].includes(item.status));
  const isFinal = status === 'completed' || status === 'partial_success' || componentsTerminal;
  const hasVideoReady = Boolean(videoUrl) || videoComponent?.status === 'ready'
    || status === 'video_ready' || visitedStages.has('video_ready');
  const hasTextReady = textComponent?.status === 'ready' || Boolean(summary);
  const isProcessing = !hasVideoReady && !hasTextReady && !isFinal && status !== 'error';
  const summaryPending = !isFinal && !hasTextReady && hasVideoReady && (
    textComponent
      ? ['queued', 'running'].includes(textComponent.status)
      : (status !== 'error')
  );
  const previewOnly = resultData?.preview_allowed === true && resultData?.download_allowed !== true;
  const downloadAllowed = resultData?.download_allowed === true;
  const copySummaryAllowed = resultData?.copy_summary_allowed === true;
  const txtExportAllowed = resultData?.txt_export_allowed === true;
  const pdfExportAllowed = resultData?.pdf_export_allowed === true;
  const showResults = isFinal || summaryPending || hasVideoReady || hasTextReady;

  const saveToHistory = (resultData) => {
    if (historySavedRef.current) return;
    const username = JSON.parse(localStorage.getItem('user'))?.username;
    if (!username) return;
    historySavedRef.current = true;
    const vids = resultData.video_ids || [];
    const baseTitle = resultData.rich_output?.tldr
      ? resultData.rich_output.tldr.slice(0, 80)
      : `Merged summary (${vids.length} video${vids.length !== 1 ? 's' : ''})`;
    const title = resultData.query ? `[Keyword: ${resultData.query}] ${baseTitle}` : baseTitle;
    authenticatedFetch(`${API_BASE_URL}/api/v1/auth/user-history`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        type: 'merge',
        jobId: mergeId,
        title,
        videoCount: vids.length,
        timestamp: new Date().toISOString(),
      }),
    }).catch(() => {});
  };

  const downloadProtectedExport = async (format = 'pdf') => {
    try {
      const res = await authenticatedFetch(
        `${API_BASE_URL}/api/v1/merge/${mergeId}/export?format=${format}`
      );
      if (!res.ok) throw new Error('Download failed');
      const blobUrl = URL.createObjectURL(await res.blob());
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = `summary_${mergeId}.${format === 'pdf' ? 'pdf' : 'txt'}`;
      link.click();
      URL.revokeObjectURL(blobUrl);
    } catch {
      setError('Could not download the PDF. Please sign in again and retry.');
    }
  };

  const handleChat = async () => {
    if (!chatQuestion.trim()) return;
    setChatLoading(true);
    setChatAnswer(null);
    try {
      const res = await authenticatedFetch(`${API_BASE_URL}/api/v1/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        question: chatQuestion.trim(),
        top_k: 5,
        ...(videoIds.length > 0 && { video_ids: videoIds }),
        }),
      });
      if (!res.ok) throw new Error(`Chat request failed (${res.status})`);
      setChatAnswer(await res.json());
    } catch (err) {
      console.error('Chat error:', err);
      const errMsg = extractErrorMessage(
        err.response?.data, 'Failed to get an answer. Please try again.'
      );
      setChatAnswer({ answer: errMsg, sources: [] });
    } finally {
      setChatLoading(false);
    }
  };

  /**
   * Re-run THIS job with generate_video enabled, to get a highlight reel.
   *
   * Every setting is carried over from the current job, so the summarizer —
   * which is deterministic (do_sample=False) — reproduces the same summary
   * rather than an unrelated one. The old POST to /transcript/compile was
   * removed: MergeJobCreate has no field for segment boundaries, so its
   * response could never be forwarded and was discarded on arrival.
   */
  const handleAutoCompile = async () => {
    // All sources, not just the first — a 3-video summary gets a 3-video reel.
    const sourceIds = videoIds.length > 0 ? videoIds : (videoId ? [videoId] : []);
    if (sourceIds.length === 0) {
      setCompileError('No video ID found. Please re-process the video.');
      return;
    }
    setIsCompiling(true);
    setCompileError('');
    try {
      const mergeRes = await authenticatedFetch(`${API_BASE_URL}/api/v1/merge`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        video_ids: sourceIds,
        generate_video: true,
        generate_audio: false,
        highlight_duration_seconds: 120,
        // Fall back to the previous hardcoded values only if /result omitted them.
        target_duration_minutes: jobSettings.target_duration_minutes || 5,
        style: jobSettings.style || 'educational',
        ...(jobQuery ? { query: jobQuery } : {}),
        }),
      });
      if (!mergeRes.ok) throw new Error(`Merge request failed (${mergeRes.status})`);
      const mergeData = await mergeRes.json();
      if (mergeData.job_id) {
        window.open(`/merged-player/${mergeData.job_id}`, '_blank');
      }
    } catch (err) {
      console.error('Highlight reel request failed:', err);
      setCompileError(extractErrorMessage(
        err.response?.data, 'Could not generate highlights. Please try again.'
      ));
    } finally {
      setIsCompiling(false);
    }
  };

  return (
    <div style={styles.page}>
      {/* Background Effects */}
      <div style={styles.bgGradient} />
      <div style={styles.bgGrid} />

      <div style={styles.container}>
        {/* Header */}
        <motion.div
          style={styles.header}
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <button style={styles.backLink} onClick={handleBack}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg>
            Back to Search
          </button>
          <h1 style={styles.title}>VidFusion</h1>
          {jobQuery && (
            <div style={styles.topicBadge}>
              <span style={styles.topicBadgeLabel}>Topic:</span>
              <span style={styles.topicBadgeQuery}>"{jobQuery}"</span>
            </div>
          )}
          <p style={styles.subtitle}>
            {status === 'queued'
              ? 'Job queued — worker will pick it up in a moment...'
              : isProcessing
              ? (warning
                  ? `Summary unavailable for this language — generating highlight video…`
                  : 'Processing your videos...')
              : summaryPending
              ? (warning || 'Highlight video ready — generating AI summary...')
              : isFinal
              ? (resultData?.summary_unavailable
                  ? 'Summary unavailable — unsupported transcript language'
                  : 'Your summary is ready')
              : 'Something went wrong'}
          </p>
        </motion.div>

        {/* Processing State */}
        {isProcessing && (
          <motion.div
            style={styles.processingCard}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
          >
            {/* Queue Position Banner */}
            {status === 'queued' && (
              <div
                style={{
                  maxWidth: '460px',
                  margin: '0 auto 20px',
                  padding: '10px 16px',
                  background: 'linear-gradient(135deg, rgba(37, 99, 235, 0.18) 0%, rgba(59, 130, 246, 0.1) 100%)',
                  border: '1px solid rgba(96, 165, 250, 0.45)',
                  borderRadius: '10px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  boxShadow: '0 4px 14px rgba(37, 99, 235, 0.15)',
                }}
              >
                <div style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: '#60a5fa',
                  boxShadow: '0 0 8px #60a5fa',
                  flexShrink: 0,
                }} />
                <div style={{ textAlign: 'left' }}>
                  <div style={{ color: '#ffffff', fontSize: '13px', fontWeight: 600 }}>
                    Job Queued in Worker Pool
                  </div>
                  <div style={{ color: '#93c5fd', fontSize: '11px', marginTop: '1px' }}>
                    Your request is queued safely. Dedicated background worker is picking it up.
                  </div>
                </div>
              </div>
            )}

            {/* Progress Ring */}
            <div style={styles.ringContainer}>
              <svg width="140" height="140" viewBox="0 0 140 140" style={{ transform: 'rotate(-90deg)' }}>
                <circle cx="70" cy="70" r="60" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8" />
                <circle
                  cx="70" cy="70" r="60" fill="none"
                  stroke="#478BE0"
                  strokeWidth="8"
                  strokeLinecap="round"
                  strokeDasharray={`${2 * Math.PI * 60}`}
                  strokeDashoffset={`${2 * Math.PI * 60 * (1 - progressPercent / 100)}`}
                  style={{ transition: 'stroke-dashoffset 0.5s ease' }}
                />
              </svg>
              <div style={styles.ringLabel}>
                <span style={styles.ringPercent}>{progressPercent}%</span>
              </div>
            </div>

            <p style={styles.stageMessage}>{status === 'queued' ? 'Queued in background worker pool...' : stage}</p>

            {/* Steps */}
            <div style={styles.stepsRow}>
              {STAGES.slice(0, 5).map((s, i) => {
                const stepStatus = getCurrentStepStatus(s.key);
                return (
                  <div key={i} style={styles.step}>
                    <div style={{
                      ...styles.stepDot,
                      background: stepStatus === 'complete' ? '#22c55e'
                        : stepStatus === 'active' ? '#478BE0'
                        : 'rgba(255,255,255,0.1)',
                      boxShadow: stepStatus === 'active' ? '0 0 12px rgba(71,139,224,0.4)' : 'none',
                    }}>
                      {stepStatus === 'complete' ? (
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                      ) : (
                        <span style={{ fontSize: '10px', fontWeight: 700, color: stepStatus === 'active' ? '#fff' : 'rgba(255,255,255,0.3)' }}>{s.icon}</span>
                      )}
                    </div>
                    <span style={{
                      ...styles.stepLabel,
                      color: stepStatus === 'active' ? '#fff'
                        : stepStatus === 'complete' ? 'rgba(255,255,255,0.5)'
                        : 'rgba(255,255,255,0.25)',
                    }}>{s.label}</span>
                  </div>
                );
              })}
            </div>
          </motion.div>
        )}

        {/* Completed / Video-Ready State */}
        {showResults && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.1 }}
          >
            {/* Stats Grid */}
            {metadata && (() => {
              const topicsDisplay = formatTopicsCount(metadata.topics_found, resultData?.concepts);
              const compressionDisplay = formatCompressionMetric(
                metadata.compression_ratio,
                metadata.total_source_words,
                metadata.output_words
              );
              return (
                <div style={styles.statsGrid}>
                  {[
                    { label: 'Topics Found', value: topicsDisplay, color: '#478BE0' },
                    { label: 'Text Retained', value: compressionDisplay, color: '#22c55e' },
                    { label: 'Output Words', value: resultData?.summary_unavailable ? '—' : (metadata.output_words ?? '—'), color: '#a855f7' },
                    { label: videoUrl ? 'Videos Merged' : 'Sources Processed', value: metadata.video_count || '-', color: '#f59e0b' },
                  ].map((stat, i) => (
                    <motion.div
                      key={i}
                      style={styles.statCard}
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.1 + i * 0.05 }}
                    >
                      <span style={{ ...styles.statValue, color: stat.color }}>{stat.value}</span>
                      <span style={styles.statLabel}>{stat.label}</span>
                    </motion.div>
                  ))}
                </div>
              );
            })()}

            {/* Quality Check — two scores: summary vs video, and video vs summary.
                Needs a finished summary; the /evaluate endpoint returns
                { unavailable: true } for language-abort jobs, so we skip it
                and show a clear notice instead. */}
            {isFinal && !resultData?.summary_unavailable && (
              <QualityPanel mergeId={mergeId} delay={0.18} />
            )}
            {isFinal && resultData?.summary_unavailable && (
              <motion.div
                style={{
                  ...styles.tldrCard,
                  borderColor: 'rgba(245,158,11,0.2)',
                  background: 'rgba(245,158,11,0.04)',
                }}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.18 }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                  <span style={{ fontSize: 15, fontWeight: 700, color: '#f59e0b' }}>Quality Check Unavailable</span>
                </div>
                <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.6)', margin: 0, lineHeight: 1.5 }}>
                  Quality evaluation requires a written summary. No summary was generated
                  because the transcript language ({displayLanguage(resultData.detected_language)}) is not
                  supported. VidFusion currently supports English-language summarization.
                </p>
              </motion.div>
            )}

            {/* Rights, Attribution & Publication Guidance */}
            {isFinal && (
              <RightsPanel
                jobId={mergeId}
                initialGateStatus={resultData?.publication_gate_status}
              />
            )}

            {/* Audio Player */}
            {audioUrl && (
              <motion.div
                style={styles.audioCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
              >
                <div style={styles.audioHeader}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#478BE0" strokeWidth="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
                  <span style={styles.audioTitle}>Summary Audio</span>
                </div>
                <audio controls style={styles.audioPlayer}>
                  <source src={audioUrl} type="audio/mpeg" />
                </audio>
              </motion.div>
            )}

            {warning && (
              <motion.div
                style={styles.warningCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.21 }}
              >
                <div style={styles.warningIcon}>!</div>
                <div style={styles.warningBody}>
                  <h3 style={styles.warningTitle}>Video Warning</h3>
                  <p style={styles.warningText}>{warning}</p>
                </div>
              </motion.div>
            )}

            {resultData?.selected_keywords?.length > 0 && (() => {
              const structuredCoverage = resultData?.structured_text_output?.keyword_coverage || [];
              const coverageByKeyword = new Map(
                structuredCoverage.map((item) => [item.keyword, item.status])
              );
              const covered = new Set(
                (resultData.highlight_segments || []).flatMap((clip) => clip.keyword_matches || [])
              );
              return (
                <motion.div style={styles.tldrCard} data-testid="keyword-coverage"
                  initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
                  <h3 style={styles.sectionTitle}>Requested topic coverage</h3>
                  {resultData.selected_keywords.map((keyword) => {
                    const coverage = coverageByKeyword.get(keyword)
                      || (covered.has(keyword) ? 'supported' : 'unsupported');
                    return (
                      <p key={keyword} style={styles.tldrText}>
                        {coverage === 'supported' ? '✓' : coverage === 'partial' ? '◐' : '○'}{' '}
                        {keyword}: {coverage === 'supported'
                          ? 'supported by selected source evidence'
                          : coverage === 'partial'
                          ? 'partially supported by selected source evidence'
                          : 'no meaningful supporting evidence found'}
                      </p>
                    );
                  })}
                </motion.div>
              );
            })()}

            {/* Video Player */}
            {videoUrl && (
              <motion.div
                style={styles.videoCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.22 }}
              >
                <div style={styles.audioHeader}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#a855f7" strokeWidth="2"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
                  <span style={styles.audioTitle}>Video Highlights</span>
                </div>
                {previewOnly && (
                  <div role="alert" style={{
                    marginBottom: 14,
                    padding: '12px 14px',
                    borderRadius: 10,
                    color: '#fcd34d',
                    background: 'rgba(245, 158, 11, 0.10)',
                    border: '1px solid rgba(245, 158, 11, 0.35)',
                  }}>
                    <strong>Private Preview Only.</strong>{' '}
                    Rights for reuse/publication are not verified. Do not publish or redistribute without permission.
                  </div>
                )}
                <video
                  ref={videoRef}
                  key={videoUrl}
                  src={videoUrl}
                  controls
                  playsInline
                  preload="metadata"
                  style={styles.videoPlayer}
                  poster=""
                >
                  <source src={videoUrl} type="video/mp4" />
                  Your browser does not support the video tag.
                </video>
              </motion.div>
            )}

            {/* Summary generating — shown while video is ready but the text
                pipeline is still running */}
            {summaryPending && (
              <motion.div
                style={styles.tldrCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.25 }}
              >
                <h3 style={styles.sectionTitle}>Generating Summary</h3>
                <p style={{ ...styles.tldrText, fontSize: '0.95rem', marginBottom: '24px' }}>
                  AI summary, TL;DR, key takeaways and chapters are being generated —
                  this page will update automatically.
                </p>
                <div style={styles.stepsRow}>
                  {STAGES.slice(5).map((s, i) => {
                    const stepStatus = getCurrentStepStatus(s.key);
                    return (
                      <div key={i} style={styles.step}>
                        <div style={{
                          ...styles.stepDot,
                          background: stepStatus === 'complete' ? '#22c55e'
                            : stepStatus === 'active' ? '#478BE0'
                            : 'rgba(255,255,255,0.1)',
                          boxShadow: stepStatus === 'active' ? '0 0 12px rgba(71,139,224,0.4)' : 'none',
                        }}>
                          {stepStatus === 'complete' ? (
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                          ) : (
                            <span style={{ fontSize: '10px', fontWeight: 700, color: stepStatus === 'active' ? '#fff' : 'rgba(255,255,255,0.3)' }}>{s.icon}</span>
                          )}
                        </div>
                        <span style={{
                          ...styles.stepLabel,
                          color: stepStatus === 'active' ? '#fff'
                            : stepStatus === 'complete' ? 'rgba(255,255,255,0.5)'
                            : 'rgba(255,255,255,0.25)',
                        }}>{s.label}</span>
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            )}

            {/* TL;DR */}
            {richOutput?.tldr && (
              <motion.div
                style={styles.tldrCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.25 }}
              >
                <h3 style={styles.sectionTitle}>TL;DR</h3>
                <p style={styles.tldrText}>{richOutput.tldr}</p>
              </motion.div>
            )}

            {/* Summary */}
            <motion.div
              style={styles.summaryCard}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            >
              <h3 style={styles.sectionTitle}>AI Summary</h3>
              {summaryPending ? (
                <p style={{ ...styles.summaryText, fontStyle: 'italic', opacity: 0.6 }}>
                  Generating AI summary…
                </p>
              ) : resultData?.summary_unavailable ? (
                <p style={{ ...styles.summaryText, fontStyle: 'italic', color: 'rgba(245,158,11,0.85)' }}>
                  {displayLanguage(resultData.detected_language)} transcript detected, but an English transcript could not be generated.
                </p>
              ) : resultData?.structured_text_output?.summary?.length > 0 ? (
                resultData.structured_text_output.summary.map((paragraph, index) => (
                  <p key={index} style={styles.summaryText}>{paragraph.text}</p>
                ))
              ) : (
                <p style={styles.summaryText}>{summary}</p>
              )}
            </motion.div>

            {/* Key Takeaways */}
            {richOutput?.key_takeaways?.length > 0 && (
              <motion.div
                style={styles.richCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.35 }}
              >
                <h3 style={styles.sectionTitle}>
                  {resultData?.content_type === 'narrative' ? 'Key Events' : 'Key Takeaways'}
                </h3>
                <ul style={styles.takeawayList}>
                  {richOutput.key_takeaways.map((item, idx) => (
                    <li key={idx} style={styles.takeawayItem}>
                      <span style={styles.takeawayIcon}>&#10003;</span>
                      <span style={styles.takeawayText}>{item}</span>
                    </li>
                  ))}
                </ul>
              </motion.div>
            )}

            {/* Chapters */}
            {richOutput?.chapters?.length > 0 && (
              <motion.div
                style={styles.richCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.4 }}
              >
                <h3 style={styles.sectionTitle}>Chapters</h3>
                <div style={styles.chaptersList}>
                  {richOutput.chapters.map((ch, idx) => {
                    const hasTimestamp = ch.timestamp_seconds !== undefined && ch.timestamp_seconds !== null;
                    return (
                      <div
                        key={idx}
                        style={{
                          ...styles.chapterItem,
                          cursor: hasTimestamp ? 'pointer' : 'default',
                          padding: '10px 12px',
                          borderRadius: '8px',
                          transition: 'background 0.2s ease',
                        }}
                        className={hasTimestamp ? 'hover:bg-white/5' : ''}
                        onClick={() => {
                          if (hasTimestamp) {
                            handleSeekToTimestamp(ch.timestamp_seconds);
                          }
                        }}
                        title={hasTimestamp ? `Jump to ${ch.timestamp_label || 'chapter'}` : ''}
                      >
                        <div style={styles.chapterNumber}>{String(idx + 1).padStart(2, '0')}</div>
                        <div style={styles.chapterContent}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                            <h4 style={styles.chapterTitle}>{ch.title}</h4>
                            {ch.timestamp_label && (
                              <span style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '4px',
                                padding: '2px 8px',
                                borderRadius: '9999px',
                                fontSize: '0.72rem',
                                fontWeight: 600,
                                background: 'rgba(59, 130, 246, 0.15)',
                                color: '#60a5fa',
                                border: '1px solid rgba(59, 130, 246, 0.3)',
                              }}>
                                ▶ {ch.timestamp_label}
                              </span>
                            )}
                          </div>
                          <p style={styles.chapterText}>{ch.text}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </motion.div>
            )}

            {/* Best Quotes */}
            {richOutput?.best_quotes?.length > 0 && (
              <motion.div
                style={styles.richCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.45 }}
              >
                <h3 style={styles.sectionTitle}>Best Quotes</h3>
                <div style={styles.quotesList}>
                  {richOutput.best_quotes.map((q, idx) => (
                    <div key={idx} style={styles.quoteItem}>
                      <p style={styles.quoteText}>"{q.text}"</p>
                      {q.speaker && <span style={styles.quoteSpeaker}>— {q.speaker}</span>}
                    </div>
                  ))}
                </div>
              </motion.div>
            )}

            {/* Who Should Watch / Who Can Skip */}
            {(richOutput?.who_should_watch || richOutput?.who_can_skip) && (
              <motion.div
                style={styles.whoGrid}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.5 }}
              >
                {richOutput.who_should_watch && (
                  <div style={styles.whoCard}>
                    <h4 style={{ ...styles.whoTitle, color: '#22c55e' }}>Who Should Watch</h4>
                    <p style={styles.whoText}>{richOutput.who_should_watch}</p>
                  </div>
                )}
                {richOutput.who_can_skip && (
                  <div style={styles.whoCard}>
                    <h4 style={{ ...styles.whoTitle, color: '#f59e0b' }}>Who Can Skip</h4>
                    <p style={styles.whoText}>{richOutput.who_can_skip}</p>
                  </div>
                )}
              </motion.div>
            )}

            {/* Action Steps */}
            {richOutput?.action_steps?.length > 0 && (
              <motion.div
                style={styles.richCard}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.55 }}
              >
                <h3 style={styles.sectionTitle}>Action Steps</h3>
                <ol style={styles.actionStepsList}>
                  {richOutput.action_steps.map((step, idx) => (
                    <li key={idx} style={styles.actionStepItem}>{step}</li>
                  ))}
                </ol>
              </motion.div>
            )}

            {/* Topics */}
            {(() => {
              const resolvedTopics = resolveTopicsList(metadata?.topics_found, resultData?.concepts);
              if (resolvedTopics.length === 0) return null;
              return (
                <motion.div
                  style={styles.topicsCard}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.6 }}
                >
                  <h3 style={styles.sectionTitle}>Key Topics</h3>
                  <div style={styles.topicsWrap}>
                    {resolvedTopics.slice(0, 10).map((topic, idx) => (
                      <span key={idx} style={styles.topicTag}>{topic}</span>
                    ))}
                  </div>
                </motion.div>
              );
            })()}

            {/* Interactive Video Chat & Q&A */}
            <VideoChatPanel mergeId={mergeId} onSeek={handleSeekToTimestamp} />

            {/* Export Buttons — need a finished summary; hidden while it's
                still generating (video_ready). */}
            {!summaryPending && (copySummaryAllowed || txtExportAllowed || pdfExportAllowed || downloadAllowed) && (
              <motion.div
                style={styles.exportRow}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.65 }}
              >
                {copySummaryAllowed && (
                <button
                  style={styles.exportBtn}
                  onClick={() => {
                    const text = [
                      richOutput?.tldr ? `TL;DR: ${richOutput.tldr}\n` : '',
                      `SUMMARY:\n${summary}\n`,
                      richOutput?.key_takeaways?.length
                        ? `${resultData?.content_type === 'narrative' ? 'KEY EVENTS' : 'KEY TAKEAWAYS'}:\n${richOutput.key_takeaways.map((t, i) => `${i + 1}. ${t}`).join('\n')}\n`
                        : '',
                      richOutput?.chapters?.length ? `CHAPTERS:\n${richOutput.chapters.map((c, i) => `${i + 1}. ${c.title}\n${c.text}`).join('\n\n')}\n` : '',
                      richOutput?.action_steps?.length ? `ACTION STEPS:\n${richOutput.action_steps.map((s, i) => `${i + 1}. ${s}`).join('\n')}\n` : '',
                    ].filter(Boolean).join('\n');
                    navigator.clipboard.writeText(text);
                    alert('Copied to clipboard!');
                  }}
                >
                  Copy Text
                </button>
                )}
                {txtExportAllowed && (
                  <button style={styles.exportBtn} onClick={() => downloadProtectedExport('text')}>
                    Download TXT
                  </button>
                )}
                {pdfExportAllowed && (
                <button
                  style={{ ...styles.exportBtn, background: 'linear-gradient(135deg, rgba(239,68,68,0.15), rgba(239,68,68,0.05))', borderColor: 'rgba(239,68,68,0.3)' }}
                  onClick={() => downloadProtectedExport('pdf')}
                >
                  Download PDF
                </button>
                )}
                {downloadAllowed && resultData?.video_download_url && (
                  <button
                    style={{ ...styles.exportBtn, background: 'linear-gradient(135deg, rgba(71,139,224,0.15), rgba(71,139,224,0.05))', borderColor: 'rgba(71,139,224,0.3)' }}
                    onClick={() => window.open(`${API_BASE_URL}${resultData.video_download_url}`, '_blank', 'noopener,noreferrer')}
                  >
                    Download Video
                  </button>
                )}
                {downloadAllowed && resultData?.audio_download_url && (
                  <button
                    style={{ ...styles.exportBtn, background: 'linear-gradient(135deg, rgba(71,139,224,0.15), rgba(71,139,224,0.05))', borderColor: 'rgba(71,139,224,0.3)' }}
                    onClick={() => window.open(`${API_BASE_URL}${resultData.audio_download_url}`, '_blank', 'noopener,noreferrer')}
                  >
                    Download Audio
                  </button>
                )}
              </motion.div>
            )}

            {/* Action */}
            <motion.div
              style={styles.actionRow}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.7 }}
            >
              <button style={styles.btnPrimary} onClick={handleBack}>
                Create Another Summary
              </button>
              {/* Only offered when this job has no video yet — with one, the
                  button would just re-do work the page is already showing. */}
              {!videoUrl && (
                <button
                  style={{
                    ...styles.btnPrimary,
                    background: isCompiling
                      ? 'rgba(168, 85, 247, 0.3)'
                      : 'linear-gradient(135deg, #a855f7, #7c3aed)',
                    boxShadow: '0 4px 20px rgba(168,85,247,0.3)',
                    opacity: isCompiling ? 0.7 : 1,
                    cursor: isCompiling ? 'not-allowed' : 'pointer',
                  }}
                  onClick={handleAutoCompile}
                  disabled={isCompiling}
                  title={`Generate a video highlight reel from ${videoIds.length || 1} source video${videoIds.length > 1 ? 's' : ''}`}
                >
                  {isCompiling ? 'Generating...' : 'Generate Video Highlights'}
                </button>
              )}
            </motion.div>
            {compileError && (
              <p style={{ color: '#ef4444', fontSize: '13px', textAlign: 'center', marginTop: '8px' }}>
                {compileError}
              </p>
            )}
          </motion.div>
        )}

        {/* Error State */}
        {status === 'error' && (
          <motion.div
            style={styles.errorCard}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
          >
            <div style={styles.errorIcon}>
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
            </div>
            <h3 style={styles.errorTitle}>Processing Failed</h3>
            <p style={styles.errorText}>{error}</p>
            <button style={styles.btnPrimary} onClick={handleBack}>Try Again</button>
          </motion.div>
        )}
      </div>
    </div>
  );
};

const styles = {
  page: {
    minHeight: '100vh',
    background: '#000212',
    color: '#fff',
    fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
    position: 'relative',
    overflow: 'hidden',
  },
  bgGradient: {
    position: 'absolute',
    inset: 0,
    background: 'radial-gradient(ellipse 60% 40% at 50% 20%, rgba(71, 139, 224, 0.06), transparent 70%)',
    pointerEvents: 'none',
  },
  bgGrid: {
    position: 'absolute',
    inset: 0,
    backgroundImage: 'linear-gradient(rgba(71,139,224,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(71,139,224,0.02) 1px, transparent 1px)',
    backgroundSize: '60px 60px',
    maskImage: 'radial-gradient(ellipse 70% 60% at 50% 50%, black, transparent)',
    pointerEvents: 'none',
  },
  container: {
    position: 'relative',
    zIndex: 1,
    maxWidth: '800px',
    margin: '0 auto',
    padding: '100px 24px 80px',
  },
  header: {
    textAlign: 'center',
    marginBottom: '40px',
  },
  backLink: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    background: 'none',
    border: 'none',
    color: 'rgba(255,255,255,0.4)',
    fontSize: '13px',
    fontWeight: 500,
    cursor: 'pointer',
    marginBottom: '20px',
    transition: 'color 0.2s',
    fontFamily: 'inherit',
  },
  title: {
    fontSize: '2.2rem',
    fontWeight: 800,
    letterSpacing: '-0.03em',
    margin: '0 0 8px',
    background: 'linear-gradient(135deg, #478BE0 0%, #8ecaff 100%)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    backgroundClip: 'text',
  },
  topicBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '6px',
    backgroundColor: 'rgba(59, 130, 246, 0.12)',
    border: '1px solid rgba(59, 130, 246, 0.3)',
    borderRadius: '20px',
    padding: '4px 14px',
    margin: '0 auto 12px',
    fontSize: '0.85rem',
  },
  topicBadgeLabel: {
    color: 'rgba(255, 255, 255, 0.5)',
    fontWeight: 500,
  },
  topicBadgeQuery: {
    color: '#60A5FA',
    fontWeight: 600,
  },
  subtitle: {
    fontSize: '1rem',
    color: 'rgba(255,255,255,0.4)',
    margin: 0,
  },
  processingCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '20px',
    padding: '48px 32px',
    textAlign: 'center',
  },
  ringContainer: {
    position: 'relative',
    width: '140px',
    height: '140px',
    margin: '0 auto 24px',
  },
  ringLabel: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  ringPercent: {
    fontSize: '2rem',
    fontWeight: 800,
    color: '#fff',
  },
  stageMessage: {
    fontSize: '1rem',
    color: 'rgba(255,255,255,0.6)',
    marginBottom: '32px',
  },
  stepsRow: {
    display: 'flex',
    justifyContent: 'center',
    gap: '24px',
    flexWrap: 'wrap',
  },
  step: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '8px',
  },
  stepDot: {
    width: '32px',
    height: '32px',
    borderRadius: '10px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    transition: 'all 0.3s',
  },
  stepLabel: {
    fontSize: '11px',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    transition: 'color 0.3s',
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
    gap: '12px',
    marginBottom: '20px',
  },
  statCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '14px',
    padding: '20px 16px',
    textAlign: 'center',
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
  },
  statValue: {
    fontSize: '1.5rem',
    fontWeight: 800,
  },
  statLabel: {
    fontSize: '0.75rem',
    color: 'rgba(255,255,255,0.4)',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  audioCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '20px 24px',
    marginBottom: '20px',
  },
  audioHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    marginBottom: '14px',
  },
  audioTitle: {
    fontSize: '0.9rem',
    fontWeight: 600,
    color: '#fff',
  },
  audioPlayer: {
    width: '100%',
    borderRadius: '8px',
    outline: 'none',
  },
  warningCard: {
    background: 'rgba(245, 158, 11, 0.1)',
    border: '1px solid rgba(245, 158, 11, 0.28)',
    borderRadius: '16px',
    padding: '18px 20px',
    marginBottom: '20px',
    display: 'flex',
    gap: '12px',
    alignItems: 'flex-start',
  },
  warningIcon: {
    width: '26px',
    height: '26px',
    borderRadius: '999px',
    background: 'rgba(245, 158, 11, 0.18)',
    color: '#fbbf24',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontWeight: 800,
    flexShrink: 0,
  },
  warningBody: {
    flex: 1,
    minWidth: 0,
  },
  warningTitle: {
    fontSize: '0.95rem',
    fontWeight: 700,
    color: '#fde68a',
    margin: '0 0 4px',
  },
  warningText: {
    fontSize: '0.9rem',
    lineHeight: 1.6,
    color: '#fef3c7',
    margin: 0,
    overflowWrap: 'break-word',
    wordBreak: 'break-word',
  },
  summaryCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '28px',
    marginBottom: '20px',
  },
  sectionTitle: {
    fontSize: '1rem',
    fontWeight: 700,
    color: '#fff',
    margin: '0 0 16px',
    letterSpacing: '-0.01em',
  },
  summaryText: {
    fontSize: '0.95rem',
    lineHeight: 1.8,
    color: 'rgba(255,255,255,0.65)',
    margin: 0,
    whiteSpace: 'pre-wrap',
  },
  topicsCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '24px',
    marginBottom: '20px',
  },
  topicsWrap: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '8px',
  },
  topicTag: {
    padding: '6px 14px',
    background: 'rgba(71, 139, 224, 0.1)',
    border: '1px solid rgba(71, 139, 224, 0.15)',
    borderRadius: '9999px',
    fontSize: '13px',
    color: '#58adff',
    fontWeight: 500,
  },
  actionRow: {
    textAlign: 'center',
    paddingTop: '16px',
  },
  btnPrimary: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '8px',
    padding: '14px 28px',
    background: 'linear-gradient(135deg, #478BE0, #2F61A0)',
    color: '#fff',
    fontSize: '15px',
    fontWeight: 600,
    border: 'none',
    borderRadius: '12px',
    cursor: 'pointer',
    boxShadow: '0 4px 20px rgba(71,139,224,0.3)',
    transition: 'all 0.2s',
    fontFamily: 'inherit',
  },
  errorCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(239, 68, 68, 0.2)',
    borderRadius: '20px',
    padding: '48px 32px',
    textAlign: 'center',
  },
  errorIcon: {
    marginBottom: '16px',
  },
  errorTitle: {
    fontSize: '1.25rem',
    fontWeight: 700,
    color: '#fff',
    margin: '0 0 8px',
  },
  errorText: {
    fontSize: '0.9rem',
    color: 'rgba(255,255,255,0.5)',
    marginBottom: '24px',
  },
  // ===== Rich Output Styles =====
  tldrCard: {
    background: 'linear-gradient(135deg, rgba(71,139,224,0.12), rgba(71,139,224,0.04))',
    border: '1px solid rgba(71,139,224,0.2)',
    borderRadius: '16px',
    padding: '24px 28px',
    marginBottom: '20px',
  },
  tldrText: {
    fontSize: '1.1rem',
    fontWeight: 600,
    lineHeight: 1.6,
    color: '#8ecaff',
    margin: 0,
  },
  richCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '24px 28px',
    marginBottom: '20px',
  },
  takeawayList: {
    listStyle: 'none',
    padding: 0,
    margin: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  takeawayItem: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '12px',
    fontSize: '0.93rem',
    lineHeight: 1.6,
    color: 'rgba(255,255,255,0.7)',
  },
  takeawayIcon: {
    color: '#22c55e',
    fontWeight: 700,
    fontSize: '1rem',
    flexShrink: 0,
    marginTop: '2px',
  },
  takeawayText: {
    flex: 1,
    minWidth: 0,
    overflowWrap: 'break-word',
    wordBreak: 'break-word',
  },
  chaptersList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  chapterItem: {
    display: 'flex',
    gap: '16px',
    alignItems: 'flex-start',
  },
  chapterNumber: {
    fontSize: '0.75rem',
    fontWeight: 800,
    color: '#478BE0',
    background: 'rgba(71,139,224,0.1)',
    border: '1px solid rgba(71,139,224,0.15)',
    borderRadius: '8px',
    width: '32px',
    height: '32px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  chapterContent: {
    flex: 1,
  },
  chapterTitle: {
    fontSize: '0.95rem',
    fontWeight: 700,
    color: '#fff',
    margin: '0 0 4px',
  },
  chapterText: {
    fontSize: '0.88rem',
    lineHeight: 1.6,
    color: 'rgba(255,255,255,0.55)',
    margin: 0,
  },
  quotesList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '14px',
  },
  quoteItem: {
    borderLeft: '3px solid #a855f7',
    paddingLeft: '16px',
  },
  quoteText: {
    fontSize: '0.93rem',
    lineHeight: 1.6,
    color: 'rgba(255,255,255,0.7)',
    fontStyle: 'italic',
    margin: '0 0 4px',
  },
  quoteSpeaker: {
    fontSize: '0.8rem',
    color: 'rgba(255,255,255,0.4)',
    fontWeight: 500,
  },
  whoGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
    gap: '12px',
    marginBottom: '20px',
  },
  whoCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '14px',
    padding: '20px',
  },
  whoTitle: {
    fontSize: '0.85rem',
    fontWeight: 700,
    margin: '0 0 8px',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  whoText: {
    fontSize: '0.88rem',
    lineHeight: 1.6,
    color: 'rgba(255,255,255,0.6)',
    margin: 0,
  },
  actionStepsList: {
    padding: '0 0 0 20px',
    margin: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  },
  actionStepItem: {
    fontSize: '0.93rem',
    lineHeight: 1.6,
    color: 'rgba(255,255,255,0.7)',
  },
  exportRow: {
    display: 'flex',
    justifyContent: 'center',
    gap: '12px',
    marginBottom: '20px',
  },
  exportBtn: {
    padding: '10px 20px',
    background: 'rgba(255,255,255,0.06)',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: '10px',
    color: 'rgba(255,255,255,0.7)',
    fontSize: '13px',
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'all 0.2s',
    fontFamily: 'inherit',
  },
  // ===== Video Player Styles =====
  videoCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(168, 85, 247, 0.15)',
    borderRadius: '16px',
    padding: '20px 24px',
    marginBottom: '20px',
  },
  videoPlayer: {
    width: '100%',
    borderRadius: '10px',
    outline: 'none',
    backgroundColor: '#000',
    maxHeight: '450px',
  },
  // ===== Chat Styles =====
  chatCard: {
    background: 'rgba(17, 24, 39, 0.5)',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '16px',
    padding: '24px 28px',
    marginBottom: '20px',
  },
  chatSubtext: {
    fontSize: '0.85rem',
    color: 'rgba(255,255,255,0.35)',
    margin: '-8px 0 16px',
  },
  chatInputRow: {
    display: 'flex',
    gap: '10px',
  },
  chatInput: {
    flex: 1,
    padding: '12px 16px',
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid rgba(255,255,255,0.1)',
    borderRadius: '10px',
    color: '#fff',
    fontSize: '14px',
    fontFamily: 'inherit',
    outline: 'none',
  },
  chatBtn: {
    padding: '12px 24px',
    background: 'linear-gradient(135deg, #478BE0, #2F61A0)',
    color: '#fff',
    fontSize: '14px',
    fontWeight: 600,
    border: 'none',
    borderRadius: '10px',
    cursor: 'pointer',
    fontFamily: 'inherit',
    whiteSpace: 'nowrap',
  },
  chatAnswerBox: {
    marginTop: '16px',
    padding: '16px 20px',
    background: 'rgba(71,139,224,0.06)',
    border: '1px solid rgba(71,139,224,0.12)',
    borderRadius: '12px',
  },
  chatAnswerText: {
    fontSize: '0.93rem',
    lineHeight: 1.7,
    color: 'rgba(255,255,255,0.75)',
    margin: 0,
  },
  chatSources: {
    marginTop: '12px',
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: '6px',
  },
  chatSourcesLabel: {
    fontSize: '0.75rem',
    color: 'rgba(255,255,255,0.35)',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  chatSourceTag: {
    padding: '3px 10px',
    background: 'rgba(71,139,224,0.1)',
    border: '1px solid rgba(71,139,224,0.15)',
    borderRadius: '9999px',
    fontSize: '11px',
    color: '#58adff',
    fontWeight: 500,
  },
};

export default MergedPodcastPlayer;
