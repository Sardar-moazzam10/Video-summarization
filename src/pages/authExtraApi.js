import axios from 'axios';
import { API_BASE_URL } from '../config/api.js';
import { extractErrorMessage } from '../utils/apiError.js';

const getErrorMessage = (error, fallback) => {
  if (error.response) {
    return extractErrorMessage(error.response.data, fallback);
  }
  return 'Network error. Please check your connection and try again.';
};

export const sendVerificationCode = async (email) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/v1/auth/send-verification-code`, { email });
    return response.data;
  } catch (error) {
    console.error('Error sending verification code:', error);
    return {
      success: false,
      message: getErrorMessage(error, 'Failed to send verification code. Please try again.'),
    };
  }
};

export const verifyCode = async (email, code) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/v1/auth/verify-code`, { email, code });
    return response.data;
  } catch (error) {
    console.error('Error verifying code:', error);
    return {
      success: false,
      message: getErrorMessage(error, 'Invalid or expired verification code.'),
    };
  }
};

export const resetPassword = async (resetToken, password) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/v1/auth/reset-password`, {
      reset_token: resetToken,
      password,
    });
    return response.data;
  } catch (error) {
    console.error('Error resetting password:', error);
    return {
      success: false,
      message: getErrorMessage(error, 'Failed to reset password. Please try again.'),
    };
  }
};
