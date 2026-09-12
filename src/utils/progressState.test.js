/**
 * Unit & regression tests for video-first pipeline state machine.
 */

import { getStepStatus, monotonicPercent, nextVisitedStages, PIPELINE_STAGES, TERMINAL_STATUSES } from './progressState.js';

const VIDEO_FIRST_SEQUENCE = [
  'transcribing',
  'analyzing',
  'fusing',
  'generating_video',
  'video_ready',
  'fusing',      // 74% transcript reconstruction for BART
  'summarizing', // 79-84% BART
  'enriching',   // 85-90% Ollama
  'completed',
];

function replay(sequence) {
  let visited = new Set();
  const statusesAtEachStep = [];
  for (const status of sequence) {
    visited = nextVisitedStages(visited, status);
    statusesAtEachStep.push({ status, visited });
  }
  return statusesAtEachStep;
}

const STEP_KEYS = ['transcribing', 'analyzing', 'fusing', 'generating_video', 'video_ready', 'summarizing', 'enriching', 'generating_voice'];

describe('nextVisitedStages', () => {
  test('accumulates monotonically — prior pipeline stages are automatically included', () => {
    let visited = new Set();
    visited = nextVisitedStages(visited, 'generating_video');
    expect(visited.has('transcribing')).toBe(true);
    expect(visited.has('analyzing')).toBe(true);
    expect(visited.has('fusing')).toBe(true);
    expect(visited.has('generating_video')).toBe(true);
  });

  test('direct jump to video_ready marks all pre-video stages as visited', () => {
    const visited = nextVisitedStages(new Set(), 'video_ready');
    expect(visited.has('transcribing')).toBe(true);
    expect(visited.has('analyzing')).toBe(true);
    expect(visited.has('fusing')).toBe(true);
    expect(visited.has('generating_video')).toBe(true);
    expect(visited.has('video_ready')).toBe(true);
  });

  test('returns the same set reference when nothing changed', () => {
    const visited = nextVisitedStages(new Set(), 'fusing');
    const again = nextVisitedStages(visited, 'fusing');
    expect(again).toBe(visited);
  });

  test('ignores empty/undefined status', () => {
    const visited = new Set(['fusing']);
    expect(nextVisitedStages(visited, undefined)).toBe(visited);
    expect(nextVisitedStages(visited, '')).toBe(visited);
  });
});

describe('getStepStatus — video-first state machine rules', () => {
  test('for VIDEO_READY, all video pipeline stages show complete', () => {
    const visited = nextVisitedStages(new Set(), 'video_ready');
    expect(getStepStatus('transcribing', 'video_ready', visited)).toBe('complete');
    expect(getStepStatus('analyzing', 'video_ready', visited)).toBe('complete');
    expect(getStepStatus('fusing', 'video_ready', visited)).toBe('complete');
    expect(getStepStatus('generating_video', 'video_ready', visited)).toBe('complete');
    expect(getStepStatus('video_ready', 'video_ready', visited)).toBe('complete');
    expect(getStepStatus('summarizing', 'video_ready', visited)).toBe('pending');
    expect(getStepStatus('enriching', 'video_ready', visited)).toBe('pending');
  });

  test('completed video generation stage never becomes pending or re-activates when backend re-fuses for BART', () => {
    const steps = replay(VIDEO_FIRST_SEQUENCE);
    // Index 4: status === 'video_ready'
    const atVideoReady = steps[4];
    expect(getStepStatus('generating_video', atVideoReady.status, atVideoReady.visited)).toBe('complete');

    // Index 5: status flips to 'fusing' at 74%
    const atReFuse = steps[5];
    expect(atReFuse.status).toBe('fusing');
    expect(getStepStatus('generating_video', atReFuse.status, atReFuse.visited)).toBe('complete');
    expect(getStepStatus('video_ready', atReFuse.status, atReFuse.visited)).toBe('complete');
  });

  test('no completed video stage ever regresses to pending during text summarization', () => {
    const steps = replay(VIDEO_FIRST_SEQUENCE);
    const videoStages = ['transcribing', 'analyzing', 'fusing', 'generating_video', 'video_ready'];

    steps.forEach(({ status, visited }) => {
      if (visited.has('video_ready')) {
        videoStages.forEach((key) => {
          expect(getStepStatus(key, status, visited)).toBe('complete');
        });
      }
    });
  });

  test.each(TERMINAL_STATUSES)('every step shows complete once job reaches terminal status "%s"', (terminalStatus) => {
    const visited = nextVisitedStages(new Set(), terminalStatus);
    STEP_KEYS.forEach((key) => {
      expect(getStepStatus(key, terminalStatus, visited)).toBe('complete');
    });
  });
});

describe('monotonicPercent', () => {
  test('never returns less than the previous maximum', () => {
    expect(monotonicPercent(60, 75)).toBe(75);
    expect(monotonicPercent(75, 60)).toBe(75);
  });

  test('treats a non-finite incoming value as 0', () => {
    expect(monotonicPercent(40, undefined)).toBe(40);
    expect(monotonicPercent(40, NaN)).toBe(40);
  });

  test('the real anchor sequence never decreases end to end', () => {
    const realPercentSequence = [5, 30, 35, 45, 50, 55, 65, 70, 74, 79, 84, 90, 100];
    let max = 0;
    let prevDisplayed = 0;
    for (const p of realPercentSequence) {
      max = monotonicPercent(max, p);
      expect(max).toBeGreaterThanOrEqual(prevDisplayed);
      prevDisplayed = max;
    }
    expect(max).toBe(100);
  });
});

