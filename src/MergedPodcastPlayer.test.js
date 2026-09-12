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
import { render, screen, waitFor } from '@testing-library/react';
import axios from 'axios';

jest.mock('axios');
jest.mock('./QualityPanel.js', () => () => <div data-testid="quality-panel-stub" />);

const JOB_ID = 'job-abc123';

jest.mock('react-router-dom', () => ({
  useParams: () => ({ mergeId: JOB_ID }),
  useNavigate: () => jest.fn(),
}));

jest.mock('framer-motion', () => {
  const React = require('react');
  const passthrough = (tag) =>
    React.forwardRef(({ children, initial, animate, transition, ...rest }, ref) =>
      React.createElement(tag, { ...rest, ref }, children)
    );
  return { motion: new Proxy({}, { get: (_, tag) => passthrough(tag) }) };
});

import MergedPodcastPlayer from './MergedPodcastPlayer.js';

const STATUS_URL = `http://localhost:8000/api/v1/merge/${JOB_ID}`;
const RESULT_URL = `${STATUS_URL}/result`;

function mockEndpoints({ status, result }) {
  axios.get.mockImplementation((url) => {
    if (url === STATUS_URL) return Promise.resolve({ data: status });
    if (url === RESULT_URL) return Promise.resolve({ data: result || {} });
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
      expect(axios.get).toHaveBeenCalledWith(STATUS_URL);
    });
    expect(screen.queryByText('Video Highlights')).not.toBeInTheDocument();
    expect(screen.queryByText('Your summary is ready')).not.toBeInTheDocument();
    expect(axios.get).not.toHaveBeenCalledWith(RESULT_URL);
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
    expect(axios.get).toHaveBeenCalledWith(RESULT_URL);
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
