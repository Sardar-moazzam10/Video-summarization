import axios from 'axios';
import { API_BASE_URL } from './config/api.js';

// Signup API Call
export const signupUser = async (formData) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/v1/auth/signup`, formData);
    return response.data;
  } catch (error) {
    console.error('Signup error:', error);
    return {
      success: false,
      message: error.response?.data?.message || 'Signup failed',
    };
  }
};

// Login API Call
export const loginUser = async (formData) => {
  try {
    const response = await axios.post(`${API_BASE_URL}/api/v1/auth/login`, formData);
    return response.data;
  } catch (error) {
    console.error('Login error:', error);
    return {
      success: false,
      message: error.response?.data?.message || 'Login failed',
    };
  }
};
