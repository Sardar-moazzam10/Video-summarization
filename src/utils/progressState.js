/**
 * Canonical order of pipeline stages in the video-first architecture:
 * TRANSCRIBING -> ANALYZING -> FUSING/SELECTING -> VIDEO GENERATION -> VIDEO_READY -> SUMMARIZING -> ENRICHMENT -> GENERATING_VOICE -> COMPLETED
 */
export const PIPELINE_STAGES = [
  'transcribing',
  'analyzing',
  'fusing',
  'generating_video',
  'video_ready',
  'summarizing',
  'enriching',
  'generating_voice',
];

export const TERMINAL_STATUSES = ['completed', 'partial_success'];

/**
 * Returns the updated visited-stages set for a newly-arrived status.
 * Monotonically accumulates stages — once a stage index in PIPELINE_STAGES is reached,
 * all prior stages are automatically marked visited.
 * Returns the SAME set reference when nothing changed.
 */
export function nextVisitedStages(visitedStages, status) {
  if (!status) return visitedStages;

  const next = new Set(visitedStages);
  let changed = false;

  if (TERMINAL_STATUSES.includes(status)) {
    for (const stage of PIPELINE_STAGES) {
      if (!next.has(stage)) {
        next.add(stage);
        changed = true;
      }
    }
  } else {
    const SHARED_STAGES = ['transcribing', 'analyzing', 'fusing'];
    const VIDEO_STAGES = ['generating_video', 'video_ready'];
    const TEXT_STAGES = ['summarizing', 'enriching', 'generating_voice'];

    let stagesToMark = [];
    if (TEXT_STAGES.includes(status)) {
      const textIdx = TEXT_STAGES.indexOf(status);
      stagesToMark = [...SHARED_STAGES, ...TEXT_STAGES.slice(0, textIdx + 1)];
    } else if (VIDEO_STAGES.includes(status)) {
      const vidIdx = VIDEO_STAGES.indexOf(status);
      stagesToMark = [...SHARED_STAGES, ...VIDEO_STAGES.slice(0, vidIdx + 1)];
    } else if (SHARED_STAGES.includes(status)) {
      const sharedIdx = SHARED_STAGES.indexOf(status);
      stagesToMark = SHARED_STAGES.slice(0, sharedIdx + 1);
    } else {
      stagesToMark = [status];
    }

    for (const stage of stagesToMark) {
      if (!next.has(stage)) {
        next.add(stage);
        changed = true;
      }
    }
  }

  return changed ? next : visitedStages;
}

/**
 * Derives step status for UI indicators:
 * 'complete' — step has finished or job reached a stage past it
 * 'active'   — this step is currently executing
 * 'pending'  — step has not been reached yet
 */
export function getStepStatus(stepName, status, visitedStages) {
  if (TERMINAL_STATUSES.includes(status)) return 'complete';

  const hasVideoReady = visitedStages.has('video_ready') || status === 'video_ready';
  const videoReadyIdx = PIPELINE_STAGES.indexOf('video_ready');
  const stepIdx = PIPELINE_STAGES.indexOf(stepName);

  // If video_ready has been reached, all video-pipeline stages up to video_ready are complete
  if (hasVideoReady && stepIdx !== -1 && stepIdx <= videoReadyIdx) {
    return 'complete';
  }

  if (stepName === status) {
    return 'active';
  }

  if (visitedStages.has(stepName)) {
    const currentIdx = PIPELINE_STAGES.indexOf(status);
    if (currentIdx !== -1 && stepIdx !== -1 && currentIdx > stepIdx) {
      return 'complete';
    }
    if (stepIdx !== -1 && currentIdx === -1) {
      return 'complete';
    }
    return 'complete';
  }

  return 'pending';
}

/**
 * Clamps a newly-received percentage so the displayed number can never drop
 * below the highest value already shown.
 */
export function monotonicPercent(prevMax, incomingPercent) {
  const incoming = Number.isFinite(incomingPercent) ? incomingPercent : 0;
  return Math.max(prevMax, incoming);
}

