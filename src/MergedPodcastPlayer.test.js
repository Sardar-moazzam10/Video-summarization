/**
 * Video-first pipeline: the player must treat `video_ready` as a usable
 * result state (video visible immediately, summary sections showing a
 * loading state) without ever presenting a pending summary as a finished
 * one, and `completed`/`partial_success` must keep rendering full results
 * exactly as before.
 *
 * jsdom has no EventSource, so `new EventSource(...)` throws inside the
 * component's try/catch and it falls back to its polling path immediately
 * — real network calls are replaced by mocking `axios.get`.
 */

import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

jest.mock('axios');
jest.mock('./QualityPanel.js', () => () => <div data-testid="quality-panel-stub" />);
jest.mock('./components/rights/RightsPanel.jsx', () => () => <div data-testid="rights-panel-stub" />);

const JOB_ID = 'job-abc123';

jest.mock('react-router-dom', () => ({
  useParams: () => ({ mergeId: JOB_ID }),
  useNavigate: () => jest.fn(),
  useLocation: () => ({ state: {} }),
}));

jest.mock('framer-motion', () => {
  const React = require('react');
  const passthrough = (tag) =>
    React.forwardRef(({ children, initial, animate, transition, ...rest }, ref) =>
      React.createElement(tag, { ...rest, ref }, children)
    );
  return { motion: new Proxy({}, { get: (_, tag) => passthrough(tag) }) };
});

jest.mock('./config/api.js', () => ({
  API_BASE_URL: 'http://localhost:8000',
  authenticatedFetch: jest.fn(),
}));

import { authenticatedFetch } from './config/api.js';
import MergedPodcastPlayer from './MergedPodcastPlayer.js';

const STATUS_URL = `http://localhost:8000/api/v1/merge/${JOB_ID}`;
const RESULT_URL = `${STATUS_URL}/result`;

function mockEndpoints({ status, result }) {
  authenticatedFetch.mockImplementation((url) => {
    if (url === STATUS_URL) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(status),
      });
    }
    if (url === RESULT_URL) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(result || {}),
      });
    }
    return Promise.reject(new Error(`Unexpected URL in test: ${url}`));
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
});

describe('MergedPodcastPlayer — video_ready state', () => {
  const statusResponse = {
    status: 'video_ready',
    progress_percent: 70,
    stage_message: 'Highlight video ready — generating AI summary...',
  };
  const resultResponse = {
    status: 'video_ready',
    summary_pending: true,
    summary_text: null,
    rich_output: null,
    video_url: `/api/v1/merge/${JOB_ID}/video`,
    audio_url: null,
    video_ids: ['abc123'],
    highlight_segments: [{ video_id: 'abc123', start_time: 0, end_time: 30 }],
  };

  test('shows the video as soon as it is available', async () => {
    mockEndpoints({ status: statusResponse, result: resultResponse });
    render(<MergedPodcastPlayer />);

    const video = await screen.findByText('Video Highlights');
    expect(video).toBeInTheDocument();
    const videoEl = document.querySelector('video source');
    expect(videoEl).toHaveAttribute(
      'src',
      `http://localhost:8000/api/v1/merge/${JOB_ID}/video`
    );
  });

  test('does not claim the summary is ready', async () => {
    mockEndpoints({ status: statusResponse, result: resultResponse });
    render(<MergedPodcastPlayer />);

    await screen.findByText('Video Highlights');
    expect(screen.queryByText('Your summary is ready')).not.toBeInTheDocument();
    expect(screen.getAllByText(/generating ai summary/i).length).toBeGreaterThan(0);
  });

  test('shows a loading state for the summary sections instead of empty content', async () => {
    mockEndpoints({ status: statusResponse, result: resultResponse });
    render(<MergedPodcastPlayer />);

    await screen.findByText('Video Highlights');
    expect(screen.getByText('Generating Summary')).toBeInTheDocument();
    expect(screen.getByText(/generating ai summary…/i)).toBeInTheDocument();
    expect(screen.queryByText('Copy Text')).not.toBeInTheDocument();
    expect(screen.queryByText('Download PDF')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quality-panel-stub')).not.toBeInTheDocument();
  });
});

describe('MergedPodcastPlayer — completed state', () => {
  const statusResponse = {
    status: 'completed',
    progress_percent: 100,
    stage_message: 'Your summary is ready!',
  };
  const resultResponse = {
    status: 'completed',
    summary_pending: false,
    summary_text: 'This is the final AI summary.',
    rich_output: {
      tldr: 'Short version of the video.',
      key_takeaways: ['Point one', 'Point two'],
      chapters: [],
      best_quotes: [],
      action_steps: [],
    },
    video_url: `/api/v1/merge/${JOB_ID}/video`,
    audio_url: null,
    preview_allowed: true,
    download_allowed: true,
    copy_summary_allowed: true,
    txt_export_allowed: true,
    pdf_export_allowed: true,
    public_export_allowed: true,
    video_download_url: `/api/v1/merge/${JOB_ID}/video?access=download&token=test`,
    audio_download_url: null,
    video_ids: ['abc123'],
    highlight_segments: [{ video_id: 'abc123', start_time: 0, end_time: 30 }],
    metadata: { topics_found: ['topic'], compression_ratio: 0.2, output_words: 120, video_count: 1 },
  };

  test('shows the full summary, TL;DR and takeaways once BART finishes', async () => {
    mockEndpoints({ status: statusResponse, result: resultResponse });
    render(<MergedPodcastPlayer />);

    expect(await screen.findByText('Your summary is ready')).toBeInTheDocument();
    expect(screen.getByText('This is the final AI summary.')).toBeInTheDocument();
    expect(screen.getByText('Short version of the video.')).toBeInTheDocument();
    expect(screen.getByText('Point one')).toBeInTheDocument();
    expect(screen.queryByText('Generating Summary')).not.toBeInTheDocument();
    expect(screen.queryByText(/generating ai summary/i)).not.toBeInTheDocument();
    expect(screen.getByText('Copy Text')).toBeInTheDocument();
    expect(screen.getByTestId('quality-panel-stub')).toBeInTheDocument();
  });

  test('labels narrative highlights as Key Events without changing the API field', async () => {
    mockEndpoints({
      status: statusResponse,
      result: { ...resultResponse, content_type: 'narrative' },
    });
    render(<MergedPodcastPlayer />);

    expect(await screen.findByText('Key Events')).toBeInTheDocument();
    expect(screen.queryByText('Key Takeaways')).not.toBeInTheDocument();
    expect(screen.getByText('Point one')).toBeInTheDocument();
  });
});

describe('MergedPodcastPlayer — partial_success state (video failed, summary ok)', () => {
  const statusResponse = {
    status: 'partial_success',
    progress_percent: 100,
    stage_message: 'Summary ready, but video highlights were unavailable.',
  };
  const resultResponse = {
    status: 'partial_success',
    summary_pending: false,
    summary_text: 'Text-only summary.',
    rich_output: { tldr: 'TLDR', key_takeaways: [], chapters: [], best_quotes: [], action_steps: [] },
    video_url: null,
    audio_url: null,
    video_ids: ['abc123'],
    highlight_segments: [],
    warning: 'Video selection failed: no highlights found.',
    metadata: {},
  };

  test('still renders the finished summary with no video, and surfaces the warning', async () => {
    mockEndpoints({ status: statusResponse, result: resultResponse });
    render(<MergedPodcastPlayer />);

    expect(await screen.findByText('Your summary is ready')).toBeInTheDocument();
    expect(screen.getByText('Text-only summary.')).toBeInTheDocument();
    expect(screen.queryByText('Video Highlights')).not.toBeInTheDocument();
    expect(screen.getByText(/video selection failed/i)).toBeInTheDocument();
  });
});

describe('MergedPodcastPlayer — mid-pipeline processing states', () => {
  test('does not fetch or show result while still in pre-video stages like transcribing', async () => {
    mockEndpoints({
      status: { status: 'transcribing', progress_percent: 20, stage_message: 'Transcribing video...' },
    });
    render(<MergedPodcastPlayer />);

    await waitFor(() => {
      expect(authenticatedFetch).toHaveBeenCalledWith(
        STATUS_URL,
        expect.objectContaining({ signal: expect.anything() })
      );
    });
    expect(screen.queryByText('Video Highlights')).not.toBeInTheDocument();
    expect(screen.queryByText('Your summary is ready')).not.toBeInTheDocument();
    expect(authenticatedFetch).not.toHaveBeenCalledWith(RESULT_URL);
  });

  test('fetches result and renders video when status is summarizing (post-video-ready)', async () => {
    mockEndpoints({
      status: { status: 'summarizing', progress_percent: 84, stage_message: 'Running BART...' },
      result: {
        status: 'summarizing',
        summary_pending: true,
        video_url: `/api/v1/merge/${JOB_ID}/video`,
        video_ids: ['abc123'],
      },
    });
    render(<MergedPodcastPlayer />);

    const video = await screen.findByText('Video Highlights');
    expect(video).toBeInTheDocument();
    expect(authenticatedFetch).toHaveBeenCalledWith(RESULT_URL);
  });

  test('5. VIDEO_READY -> page refresh still shows video', async () => {
    mockEndpoints({
      status: { status: 'summarizing', progress_percent: 85, stage_message: 'Generating summary...' },
      result: {
        status: 'summarizing',
        summary_pending: true,
        summary_text: null,
        rich_output: null,
        video_url: `/api/v1/merge/${JOB_ID}/video`,
        audio_url: null,
        video_ids: ['abc123'],
        highlight_segments: [{ video_id: 'abc123', start_time: 0, end_time: 30 }],
      },
    });
    render(<MergedPodcastPlayer />);

    const video = await screen.findByText('Video Highlights');
    expect(video).toBeInTheDocument();
  });
});


describe('MergedPodcastPlayer — unsupported-language historical result', () => {
  test('shows truthful unavailable messaging and neutral metrics without playback claims', async () => {
    mockEndpoints({
      status: { status: 'partial_success', progress_percent: 100, stage_message: 'Summary unavailable' },
      result: {
        status: 'partial_success', summary_pending: false, summary_text: null,
        summary_unavailable: true, summary_unavailable_reason: 'UNSUPPORTED_TRANSCRIPT_LANGUAGE',
        detected_language: 'hi', video_url: null, audio_url: null, video_ids: ['hindi_vid'],
        highlight_segments: [],
        metadata: { topics_found: [], compression_ratio: null, output_words: null, video_count: 1 },
        publication_gate_status: 'restricted_by_product_policy',
      },
    });
    render(<MergedPodcastPlayer />);

    expect(await screen.findByText('Summary unavailable — unsupported transcript language')).toBeInTheDocument();
    expect(screen.queryByText('Your summary is ready')).not.toBeInTheDocument();
    expect(screen.getByText(/Hindi transcript detected, but an English transcript could not be generated/i)).toBeInTheDocument();
    expect(screen.getByText('Sources Processed')).toBeInTheDocument();
    expect(screen.queryByText('Videos Merged')).not.toBeInTheDocument();
    expect(screen.getByText('Quality Check Unavailable')).toBeInTheDocument();
    expect(screen.queryByText(/still playable/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Video Highlights')).not.toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(3);
  });
});

describe('MergedPodcastPlayer — polling lifecycle', () => {
  test('keeps at most one status request in flight and stops after unmount', async () => {
    jest.useFakeTimers();
    let calls = 0;
    let inFlight = 0;
    let maxInFlight = 0;

    authenticatedFetch.mockImplementation((url, options = {}) => {
      if (url !== STATUS_URL) {
        return Promise.reject(new Error(`Unexpected URL in test: ${url}`));
      }

      calls += 1;
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);

      return new Promise((resolve, reject) => {
        let settled = false;
        const finish = (callback) => {
          if (settled) return;
          settled = true;
          inFlight -= 1;
          callback();
        };
        const timer = setTimeout(() => finish(() => resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({
            status: 'transcribing',
            progress_percent: 20,
            stage_message: 'Transcribing video...',
          }),
        })), 100);

        options.signal?.addEventListener('abort', () => {
          clearTimeout(timer);
          finish(() => reject(new DOMException('Aborted', 'AbortError')));
        }, { once: true });
      });
    });

    const view = render(
      <React.StrictMode>
        <MergedPodcastPlayer />
      </React.StrictMode>
    );

    for (let index = 0; index < 12; index += 1) {
      await act(async () => {
        jest.advanceTimersByTime(5100);
        await Promise.resolve();
        await Promise.resolve();
      });
    }

    expect(calls).toBeGreaterThanOrEqual(10);
    expect(maxInFlight).toBe(1);

    await act(async () => {
      view.unmount();
    });
    const callsAtUnmount = calls;
    await act(async () => {
      jest.advanceTimersByTime(10000);
      await Promise.resolve();
    });
    expect(calls).toBe(callsAtUnmount);

    jest.useRealTimers();
  });
});

describe('MergedPodcastPlayer — tiered rights capabilities', () => {
  const completedStatus = {
    status: 'completed', progress_percent: 100, stage_message: 'Your summary is ready!',
  };

  const baseResult = {
    status: 'completed', summary_pending: false,
    summary_text: 'A completed summary.',
    rich_output: { tldr: 'Short summary.', key_takeaways: [], chapters: [] },
    video_ids: ['source'],
    highlight_segments: [{ video_id: 'source', start_time: 0, end_time: 30 }],
    metadata: { topics_found: ['topic'], compression_ratio: 0.2, output_words: 20, video_count: 1 },
  };

  test('Standard License keeps study notes but hides source-media export actions', async () => {
    mockEndpoints({
      status: completedStatus,
      result: {
        ...baseResult,
        publication_gate_status: 'restricted_by_product_policy',
        preview_allowed: true,
        download_allowed: false,
        public_export_allowed: false,
        copy_summary_allowed: true,
        txt_export_allowed: true,
        pdf_export_allowed: true,
        video_url: `/api/v1/merge/${JOB_ID}/video?access=preview&token=preview-token`,
        audio_url: `/api/v1/merge/${JOB_ID}/audio?access=preview&token=audio-preview-token`,
        video_download_url: null,
        audio_download_url: null,
      },
    });
    render(<MergedPodcastPlayer />);

    expect(await screen.findByText('Video Highlights')).toBeInTheDocument();
    expect(screen.getByText('Private Preview Only.')).toBeInTheDocument();
    expect(screen.getByText(/Do not publish or redistribute without permission/i)).toBeInTheDocument();
    expect(document.querySelector('video source')).toHaveAttribute(
      'src', expect.stringContaining('access=preview')
    );
    expect(screen.queryByText('Download Video')).not.toBeInTheDocument();
    expect(screen.queryByText('Download Audio')).not.toBeInTheDocument();
    expect(screen.getByText('Copy Text')).toBeInTheDocument();
    expect(screen.getByText('Download TXT')).toBeInTheDocument();
    expect(screen.getByText('Download PDF')).toBeInTheDocument();
  });

  test('CC BY keeps preview and download/export actions without preview-only warning', async () => {
    mockEndpoints({
      status: completedStatus,
      result: {
        ...baseResult,
        copy_summary_allowed: true,
        txt_export_allowed: true,
        pdf_export_allowed: true,
        publication_gate_status: 'eligible_by_recorded_rights',
        preview_allowed: true,
        download_allowed: true,
        public_export_allowed: true,
        video_url: `/api/v1/merge/${JOB_ID}/video?access=preview&token=preview-token`,
        audio_url: `/api/v1/merge/${JOB_ID}/audio?access=preview&token=audio-preview-token`,
        video_download_url: `/api/v1/merge/${JOB_ID}/video?access=download&token=download-token`,
        audio_download_url: `/api/v1/merge/${JOB_ID}/audio?access=download&token=audio-download-token`,
      },
    });
    render(<MergedPodcastPlayer />);

    expect(await screen.findByText('Video Highlights')).toBeInTheDocument();
    expect(screen.getByText('Download TXT')).toBeInTheDocument();
    expect(screen.queryByText('Private Preview Only.')).not.toBeInTheDocument();
    expect(screen.getByText('Download Video')).toBeInTheDocument();
    expect(screen.getByText('Download Audio')).toBeInTheDocument();
    expect(screen.getByText('Download PDF')).toBeInTheDocument();
    expect(screen.getByText('Copy Text')).toBeInTheDocument();
  });
});
