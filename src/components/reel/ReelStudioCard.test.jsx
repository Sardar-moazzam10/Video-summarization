import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ReelStudioCard from './ReelStudioCard.jsx';

const mockCandidates = [
  {
    id: 'moment_0',
    index: 0,
    title: 'Top Highlight Moment',
    duration_seconds: 30,
    license_label: '⚖️ CC BY (Safe to Publish)',
    is_cc_by: true,
  },
  {
    id: 'moment_1',
    index: 1,
    title: 'Adding Contact Info',
    duration_seconds: 45,
    license_label: '🔒 Standard License (Fair-Use Transformative)',
    is_cc_by: false,
  },
];

describe('ReelStudioCard Component', () => {
  beforeEach(() => {
    global.fetch = jest.fn((url) => {
      if (url.includes('/candidates')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ candidates: mockCandidates }),
        });
      }
      return Promise.reject(new Error('Unknown url'));
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test('renders candidate moments successfully', async () => {
    render(<ReelStudioCard mergeId="test-job-123" />);

    expect(await screen.findByText('Top Highlight Moment')).toBeInTheDocument();
    expect(screen.getByText('Adding Contact Info')).toBeInTheDocument();
    expect(screen.getByText('VidFusion Shorts & Reels Studio')).toBeInTheDocument();
  });

  test('toggles audio mode between original and voiceover', async () => {
    render(<ReelStudioCard mergeId="test-job-123" />);

    await screen.findByText('Top Highlight Moment');

    const voiceoverBtn = screen.getByText('AI Narrator Voiceover');
    fireEvent.click(voiceoverBtn);

    // Should reveal voice language selector
    expect(screen.getByText('Narrator Voice & Language:')).toBeInTheDocument();
    expect(screen.getByDisplayValue(/English \(Guy Studio Neural\)/i)).toBeInTheDocument();
  });
});

