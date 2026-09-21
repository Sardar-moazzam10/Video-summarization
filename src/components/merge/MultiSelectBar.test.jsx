import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import MultiSelectBar from './MultiSelectBar';
import * as apiModule from '../../config/api';

jest.mock('../../config/api', () => ({
  API: {
    MERGE_VIDEO_DURATIONS: (ids) => `http://localhost:8000/api/v1/merge/video-durations?video_ids=${ids.join(',')}`,
  },
  authenticatedFetch: jest.fn(),
}));

describe('MultiSelectBar duration validation & gating', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('deduplicates videos and disables submit while validating', async () => {
    let resolvePromise;
    apiModule.authenticatedFetch.mockImplementation(() => new Promise((resolve) => {
      resolvePromise = resolve;
    }));

    // Pass duplicate videos
    const videos = [
      { id: 'vid1', title: 'Video 1', thumbnail: 'thumb1.jpg' },
      { id: 'vid1', title: 'Video 1 copy', thumbnail: 'thumb1.jpg' },
    ];

    render(<MultiSelectBar selectedVideos={videos} onRemove={() => {}} onClear={() => {}} onMerge={() => {}} />);

    // Count is 2 selected, but API is called with deduplicated 'vid1'
    expect(apiModule.authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining('video_ids=vid1'),
      expect.anything()
    );

    // Button should be disabled during validating
    const submitBtn = screen.getByTestId('multiselectbar-submit-btn');
    expect(submitBtn).toBeDisabled();

    // Finish request with valid duration
    resolvePromise({
      ok: true,
      json: async () => ({
        status: 'valid',
        durations: { vid1: 400.0 },
        combined_duration_seconds: 400.0,
        combined_duration_label: '6m 40s',
        allowed_durations: [5],
      }),
    });

    await waitFor(() => {
      expect(submitBtn).not.toBeDisabled();
    });
  });

  test('fails closed when backend returns verification_failed', async () => {
    apiModule.authenticatedFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'verification_failed',
        unresolved: ['vid_err'],
        allowed_durations: [],
      }),
    });

    const videos = [{ id: 'vid_err', title: 'Bad Video' }];
    render(<MultiSelectBar selectedVideos={videos} onRemove={() => {}} onClear={() => {}} onMerge={() => {}} />);

    const submitBtn = screen.getByTestId('multiselectbar-submit-btn');
    await waitFor(() => {
      expect(submitBtn).toBeDisabled();
      expect(screen.getByText('Unverified')).toBeInTheDocument();
    });
  });

  test('disables submit and shows Too Short when source is < 5m', async () => {
    apiModule.authenticatedFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'too_short',
        combined_duration_seconds: 240.0,
        combined_duration_label: '4m',
        allowed_durations: [],
      }),
    });

    const videos = [{ id: 'vid_short', title: 'Short Video' }];
    render(<MultiSelectBar selectedVideos={videos} onRemove={() => {}} onClear={() => {}} onMerge={() => {}} />);

    const submitBtn = screen.getByTestId('multiselectbar-submit-btn');
    await waitFor(() => {
      expect(submitBtn).toBeDisabled();
      expect(screen.getByText('Too Short')).toBeInTheDocument();
    });
  });

  test('enables submit when valid and triggers onMerge on click', async () => {
    apiModule.authenticatedFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: 'valid',
        durations: { vid_ok: 900.0 },
        combined_duration_seconds: 900.0,
        combined_duration_label: '15m',
        allowed_durations: [5, 10],
      }),
    });

    const onMerge = jest.fn();
    const videos = [{ id: 'vid_ok', title: 'Good Video' }];
    render(<MultiSelectBar selectedVideos={videos} onRemove={() => {}} onClear={() => {}} onMerge={onMerge} />);

    const submitBtn = screen.getByTestId('multiselectbar-submit-btn');
    await waitFor(() => {
      expect(submitBtn).not.toBeDisabled();
    });

    fireEvent.click(submitBtn);
    expect(onMerge).toHaveBeenCalledWith(10); // defaults to 10 if allowed
  });
});

