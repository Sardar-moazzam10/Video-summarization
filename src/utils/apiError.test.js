/**
 * FastAPI error bodies must always reduce to a renderable string.
 *
 * Regression test for a real crash: the SUMMARY_DURATION_EXCEEDS_VIDEO
 * validation error returns `detail` as an OBJECT, and four pages did
 * `setError(data.detail || '…')`, putting that object into React state.
 * React then threw "Objects are not valid as a React child (found: object
 * with keys {error_code, message, source_duration_seconds, ...})" and the
 * whole page went blank instead of showing the perfectly good message the
 * server had sent.
 */

import { extractErrorMessage, extractErrorDetail } from './apiError.js';

describe('extractErrorMessage', () => {
  test('plain string detail passes through', () => {
    expect(extractErrorMessage({ detail: 'Job not found' })).toBe('Job not found');
  });

  test('structured object detail yields its human message, never the object', () => {
    const body = {
      detail: {
        error_code: 'SUMMARY_DURATION_EXCEEDS_VIDEO',
        message: 'This video is only 5m 20s long. Please choose 5 minutes or less.',
        source_duration_seconds: 320.0,
        requested_duration_minutes: 10,
        max_allowed_minutes: 5,
        allowed_durations: [5],
      },
    };
    const out = extractErrorMessage(body);
    expect(typeof out).toBe('string');
    expect(out).toBe('This video is only 5m 20s long. Please choose 5 minutes or less.');
  });

  test("FastAPI's validation array is joined, not rendered raw", () => {
    const body = {
      detail: [
        { loc: ['body', 'target_duration_minutes'], msg: 'Input should be >= 5', type: 'greater_than_equal' },
        { loc: ['body', 'video_ids'], msg: 'Field required', type: 'missing' },
      ],
    };
    const out = extractErrorMessage(body);
    expect(typeof out).toBe('string');
    expect(out).toBe('Input should be >= 5. Field required');
  });

  test.each([
    ['empty body', {}],
    ['null body', null],
    ['undefined body', undefined],
    ['object detail with no message', { detail: { error_code: 'X' } }],
    ['empty string detail', { detail: '   ' }],
    ['empty array detail', { detail: [] }],
  ])('%s falls back to the supplied default', (_label, body) => {
    expect(extractErrorMessage(body, 'fallback')).toBe('fallback');
  });

  test('always returns a string for any shape', () => {
    const shapes = [
      { detail: 'x' },
      { detail: { message: 'y' } },
      { detail: [{ msg: 'z' }] },
      { detail: { error_code: 'X' } },
      { detail: 123 },
      {},
      null,
    ];
    shapes.forEach((body) => {
      expect(typeof extractErrorMessage(body)).toBe('string');
    });
  });
});

describe('extractErrorDetail', () => {
  test('returns the payload so callers can act on error_code', () => {
    const detail = { error_code: 'SUMMARY_DURATION_EXCEEDS_VIDEO', allowed_durations: [5] };
    expect(extractErrorDetail({ detail })).toEqual(detail);
  });

  test('returns null for string and validation-array errors', () => {
    expect(extractErrorDetail({ detail: 'nope' })).toBeNull();
    expect(extractErrorDetail({ detail: [{ msg: 'nope' }] })).toBeNull();
    expect(extractErrorDetail({})).toBeNull();
  });
});
