import axios from 'axios';
import { sendVerificationCode, verifyCode, resetPassword } from './authExtraApi.js';

jest.mock('axios');

describe('authExtraApi', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  describe('verifyCode', () => {
    test('returns response data on success', async () => {
      axios.post.mockResolvedValueOnce({
        data: { success: true, message: 'Code verified', reset_token: 'tok-123' },
      });

      const res = await verifyCode('test@example.com', '123456');
      expect(res).toEqual({ success: true, message: 'Code verified', reset_token: 'tok-123' });
    });

    test('extracts backend error message on 400 rejection', async () => {
      axios.post.mockRejectedValueOnce({
        response: {
          status: 400,
          data: { detail: 'Invalid or expired code' },
        },
      });

      const res = await verifyCode('test@example.com', '123456');
      expect(res).toEqual({
        success: false,
        message: 'Invalid or expired code',
      });
    });

    test('returns network error when server cannot be reached', async () => {
      axios.post.mockRejectedValueOnce(new Error('Network error'));

      const res = await verifyCode('test@example.com', '123456');
      expect(res).toEqual({
        success: false,
        message: 'Network error. Please check your connection and try again.',
      });
    });
  });

  describe('sendVerificationCode', () => {
    test('returns response data on success', async () => {
      axios.post.mockResolvedValueOnce({
        data: { success: true, message: 'Code sent' },
      });

      const res = await sendVerificationCode('test@example.com');
      expect(res).toEqual({ success: true, message: 'Code sent' });
    });

    test('extracts backend error message on failure', async () => {
      axios.post.mockRejectedValueOnce({
        response: {
          status: 422,
          data: { detail: 'Email format invalid' },
        },
      });

      const res = await sendVerificationCode('invalid');
      expect(res).toEqual({
        success: false,
        message: 'Email format invalid',
      });
    });

    test('returns network error when server unreachable', async () => {
      axios.post.mockRejectedValueOnce(new Error('Network error'));

      const res = await sendVerificationCode('test@example.com');
      expect(res).toEqual({
        success: false,
        message: 'Network error. Please check your connection and try again.',
      });
    });
  });

  describe('resetPassword', () => {
    test('returns response data on success', async () => {
      axios.post.mockResolvedValueOnce({
        data: { success: true, message: 'Password reset successfully' },
      });

      const res = await resetPassword('tok-123', 'newSecret123');
      expect(res).toEqual({ success: true, message: 'Password reset successfully' });
    });

    test('extracts backend error message on rejection', async () => {
      axios.post.mockRejectedValueOnce({
        response: {
          status: 400,
          data: { detail: 'Password must be at least 8 characters' },
        },
      });

      const res = await resetPassword('tok-123', 'short');
      expect(res).toEqual({
        success: false,
        message: 'Password must be at least 8 characters',
      });
    });
  });
});

