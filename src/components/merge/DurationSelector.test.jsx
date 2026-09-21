/**
 * Duration eligibility in the picker.
 *
 * A 5m20s source was offering 10/15/20/30-minute summaries as if they were
 * available. Options the source cannot produce must be disabled and must say
 * why — while staying a convenience only: the backend re-checks on submit, so
 * these assertions are about what the user is told, not about enforcement.
 * Core invariant: requested_summary_duration < total_unique_selected_source_duration
 * Strict inequality and fail-closed validation.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import DurationSelector from './DurationSelector.jsx';

const ALL = [5, 10, 15, 20, 30];

describe('DurationSelector eligibility', () => {
  test('renders exactly the five supported durations', () => {
    render(<DurationSelector value={10} onChange={() => {}} />);
    ALL.forEach((m) => {
      expect(screen.getByTestId(`duration-option-${m}`)).toBeInTheDocument();
    });
    expect(screen.queryByTestId('duration-option-2')).not.toBeInTheDocument();
  });

  test('options are disabled while duration is unresolved (null / fail-closed)', () => {
    render(<DurationSelector value={10} onChange={() => {}} allowedDurations={null} />);
    ALL.forEach((m) => {
      expect(screen.getByTestId(`duration-option-${m}`)).toBeDisabled();
    });
  });

  test('a 5m20s source enables only 5 and disables the rest with a reason', () => {
    render(
      <DurationSelector
        value={5}
        onChange={() => {}}
        allowedDurations={[5]}
        sourceDurationLabel="5m 20s"
      />
    );

    expect(screen.getByTestId('duration-option-5')).not.toBeDisabled();
    [10, 15, 20, 30].forEach((m) => {
      expect(screen.getByTestId(`duration-option-${m}`)).toBeDisabled();
      expect(screen.getByTestId(`duration-reason-${m}`)).toHaveTextContent(
        'Video is only 5m 20s'
      );
    });
  });

  test('a disabled option cannot be selected', () => {
    const onChange = jest.fn();
    render(
      <DurationSelector
        value={5}
        onChange={onChange}
        allowedDurations={[5]}
        sourceDurationLabel="5m 20s"
      />
    );

    fireEvent.click(screen.getByTestId('duration-option-10'));
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('duration-option-5'));
    expect(onChange).toHaveBeenCalledWith(5);
  });

  test('enables only allowed presets in allowedDurations', () => {
    render(
      <DurationSelector
        value={10}
        onChange={() => {}}
        allowedDurations={[5, 10]}
        sourceDurationLabel="10m 01s"
      />
    );
    expect(screen.getByTestId('duration-option-5')).not.toBeDisabled();
    expect(screen.getByTestId('duration-option-10')).not.toBeDisabled();
    expect(screen.getByTestId('duration-option-15')).toBeDisabled();
  });

  test('a source <= 5m disables all options and shows too_short banner with exact 5:00 wording', () => {
    render(
      <DurationSelector
        value={null}
        onChange={() => {}}
        allowedDurations={[]}
        sourceDurationLabel="5m 00s"
        validationStatus="too_short"
      />
    );
    ALL.forEach((m) => {
      expect(screen.getByTestId(`duration-option-${m}`)).toBeDisabled();
    });
    const banner = screen.getByTestId('duration-too-short-banner');
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent('A 5-minute summary requires more than 5 minutes of source content.');
  });

  test('shows validating banner when validationStatus is validating', () => {
    render(
      <DurationSelector
        value={null}
        onChange={() => {}}
        allowedDurations={null}
        validationStatus="validating"
      />
    );
    expect(screen.getByTestId('duration-validating-banner')).toBeInTheDocument();
    ALL.forEach((m) => {
      expect(screen.getByTestId(`duration-option-${m}`)).toBeDisabled();
    });
  });

  test('shows failure banner when validationStatus is verification_failed', () => {
    render(
      <DurationSelector
        value={null}
        onChange={() => {}}
        allowedDurations={[]}
        validationStatus="verification_failed"
      />
    );
    expect(screen.getByTestId('duration-failed-banner')).toBeInTheDocument();
    ALL.forEach((m) => {
      expect(screen.getByTestId(`duration-option-${m}`)).toBeDisabled();
    });
  });

  test('falls back to a generic reason when the length label is missing', () => {
    render(
      <DurationSelector value={5} onChange={() => {}} allowedDurations={[5]} />
    );
    expect(screen.getByTestId('duration-reason-10')).toHaveTextContent(
      'Longer than the source video'
    );
  });
});
