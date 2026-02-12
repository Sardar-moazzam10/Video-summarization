import axios from 'axios';

const BASE_URL = 'http://localhost:8000/api/v1/auth'; // FastAPI backend

// Signup API Call
export const signupUser = async (formData) => {
  try {
    const response = await axios.post(`${BASE_URL}/signup`, formData);
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
    const response = await axios.post(`${BASE_URL}/login`, formData);
    return response.data;
  } catch (error) {
    console.error('Login error:', error);
    return {
      success: false,
      message: error.response?.data?.message || 'Login failed',
    };
  }
};
