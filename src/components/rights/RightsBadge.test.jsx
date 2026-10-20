import React from 'react';
import { render, screen } from '@testing-library/react';
import RightsBadge from './RightsBadge';

describe('RightsBadge Component', () => {
  test('renders CC BY badge for verified Creative Commons metadata', () => {
    const rights = {
      youtube_license: 'creativeCommon',
      license_identifier: 'CC BY (YouTube)',
      verified_metadata: true,
    };
    render(<RightsBadge rights={rights} />);
    const badge = screen.getByTestId('rights-badge-cc');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Eligible by recorded rights');
    expect(badge).toHaveTextContent('Attribution required');
    expect(badge).toHaveTextContent('CC BY');
  });

  test('renders Standard License badge for verified standard license', () => {
    const rights = {
      youtube_license: 'youtube',
      license_identifier: 'YouTube Standard',
      verified_metadata: true,
    };
    render(<RightsBadge rights={rights} />);
    const badge = screen.getByTestId('rights-badge-standard');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Standard License');
    expect(badge).toHaveTextContent('Copyright restrictions may apply');
    expect(badge).toHaveTextContent('Publication/export not verified');
  });

  test('renders Unverified badge when rights metadata is unverified or null', () => {
    render(<RightsBadge rights={null} />);
    const badge = screen.getByTestId('rights-badge-unverified');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Rights not verified');
  });

  test('never renders "Copyright Safe" or clearance percentages', () => {
    const rights = {
      youtube_license: 'creativeCommon',
      license_identifier: 'CC BY (YouTube)',
      verified_metadata: true,
    };
    const { container } = render(<RightsBadge rights={rights} />);
    expect(container.textContent).not.toMatch(/copyright\s*safe/i);
    expect(container.textContent).not.toMatch(/100%/);
    expect(container.textContent).not.toMatch(/copyright\s*free/i);
  });
});

