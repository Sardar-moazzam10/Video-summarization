import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import VideoChatPanel from './VideoChatPanel.jsx';
import * as apiModule from '../../config/api.js';

jest.mock('../../config/api.js', () => ({
  API_BASE_URL: 'http://localhost:8000',
  authenticatedFetch: jest.fn(),
}));

describe('VideoChatPanel Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders header and initial empty state', async () => {
    apiModule.authenticatedFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        job_id: 'job-1',
        suggestions: ['What is gradient descent?'],
      }),
    });

    render(<VideoChatPanel mergeId="job-1" onSeek={() => {}} />);

    expect(screen.getByText('Ask VidFusion')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Ask about this video/i)).toBeInTheDocument();

    // Check suggestions appear
    expect(await screen.findByText('What is gradient descent?')).toBeInTheDocument();
  });

  test('submits question and renders assistant answer with clickable citations', async () => {
    apiModule.authenticatedFetch
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'job-1',
          suggestions: [],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          job_id: 'job-1',
          question: 'What is gradient descent?',
          answer: 'Gradient descent minimizes the error.',
          found: true,
          confidence: 'high',
          citations: [
            {
              video_id: 'vid-123',
              video_title: '3Blue1Brown',
              timestamp_seconds: 124.5,
              timestamp_label: '02:04',
              snippet: 'gradient descent minimizes the cost function',
              score: 0.85,
            },
          ],
        }),
      });

    const mockSeek = jest.fn();
    render(<VideoChatPanel mergeId="job-1" onSeek={mockSeek} />);

    const input = screen.getByPlaceholderText(/Ask about this video/i);
    fireEvent.change(input, { target: { value: 'What is gradient descent?' } });

    const sendBtn = screen.getByText('Send');
    fireEvent.click(sendBtn);

    // Verify user message appears
    expect(screen.getByText('What is gradient descent?')).toBeInTheDocument();

    // Verify assistant answer appears
    expect(await screen.findByText('Gradient descent minimizes the error.')).toBeInTheDocument();

    // Verify citation appears
    const timestampBtn = screen.getByText('▶ 02:04');
    expect(timestampBtn).toBeInTheDocument();
    expect(screen.getByText('3Blue1Brown')).toBeInTheDocument();

    // Clicking citation triggers onSeek
    fireEvent.click(timestampBtn);
    expect(mockSeek).toHaveBeenCalledWith(124.5);
  });
});
