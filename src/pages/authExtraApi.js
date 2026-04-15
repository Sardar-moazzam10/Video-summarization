import axios from 'axios';
import { API_BASE_URL } from '../config/api.js';

export const sendVerificationCode = async (email) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/v1/auth/send-verification-code`, { email });
    return response.data;
  } catch (error) {
    console.error('Error sending verification code:', error);
    return { success: false, message: 'Network Error' };
  }
};

export const verifyCode = async (email, code) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/v1/auth/verify-code`, { email, code });
    return response.data;
  } catch (error) {
    console.error('Error verifying code:', error);
    return { success: false, message: 'Network Error' };
  }
};

export const resetPassword = async (email, password) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/v1/auth/reset-password`, { email, password });
    return response.data;
  } catch (error) {
    console.error('Error resetting password:', error);
    return { success: false, message: 'Network Error' };
  }
};
