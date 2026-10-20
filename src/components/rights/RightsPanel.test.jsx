import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import RightsPanel from './RightsPanel';
import { authenticatedFetch } from '../../config/api.js';

jest.mock('../../config/api.js', () => ({
  API_BASE_URL: 'http://localhost:8000',
  authenticatedFetch: jest.fn(),
}));

describe('RightsPanel hardening', () => {
  beforeEach(() => {
    authenticatedFetch.mockReset();
  });

  test('fetches once and renders frozen source-level backend truth', async () => {
    authenticatedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        snapshot_origin: 'job_evaluation',
        policy_version: 'rights-v1-fail-closed',
        publication_gate_status: 'manual_review_required',
        gate_warnings: ['Ownership declaration requires review.'],
        sources: [{
          source_id: 'source-a',
          title: 'Source A',
          verification_status: 'user_attested',
          publication_gate_status: 'manual_review_required',
        }],
        attribution_block: null,
      }),
    });

    render(<RightsPanel jobId="job-1" />);
    await waitFor(() => expect(authenticatedFetch).toHaveBeenCalledTimes(1));
    expect(authenticatedFetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/rights/job/job-1/manifest'
    );

    fireEvent.click(screen.getByRole('button', { name: /details/i }));

    expect(await screen.findByText(/frozen at job evaluation/i)).toBeInTheDocument();
    expect(screen.getByText('Source A')).toBeInTheDocument();
    expect(screen.getByText(/Evidence: user attested/i)).toBeInTheDocument();
    expect(screen.getAllByText(/manual review required/i).length).toBeGreaterThan(0);
  });
});

