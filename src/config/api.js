/**
 * API Configuration - Central source of truth
 */

// Backend API base URL
export const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// API Endpoints
export const API = {
  // Auth
  LOGIN: `${API_BASE_URL}/api/v1/auth/login`,
  SIGNUP: `${API_BASE_URL}/api/v1/auth/signup`,
  REFRESH: `${API_BASE_URL}/api/v1/auth/refresh`,

  // User
  USER: (username) => `${API_BASE_URL}/api/v1/auth/user/${username}`,
  USERS: `${API_BASE_URL}/api/v1/auth/users`,
  UPDATE_USER: (username) => `${API_BASE_URL}/api/v1/auth/user/update/${username}`,
  UPDATE_PASSWORD: (username) => `${API_BASE_URL}/api/v1/auth/user/update-password/${username}`,
  DELETE_USER: (username) => `${API_BASE_URL}/api/v1/auth/user/delete/${username}`,

  // History
  USER_HISTORY: (username) => `${API_BASE_URL}/api/v1/auth/user-history/${username}`,
  USER_HISTORY_ADD: `${API_BASE_URL}/api/v1/auth/user-history`,
  USER_HISTORY_DELETE: (username) => `${API_BASE_URL}/api/v1/auth/user-history/delete/${username}`,
  USER_HISTORY_DELETE_ONE: `${API_BASE_URL}/api/v1/auth/user-history/delete-one`,

  // Transcript
  TRANSCRIPT: (videoId) => `${API_BASE_URL}/api/v1/transcript/${videoId}`,

  // Merge
  MERGE: `${API_BASE_URL}/api/v1/merge`,
  MERGE_STATUS: (jobId) => `${API_BASE_URL}/api/v1/merge/${jobId}`,
  MERGE_RESULT: (jobId) => `${API_BASE_URL}/api/v1/merge/${jobId}/result`,
  MERGE_AUDIO: (jobId) => `${API_BASE_URL}/api/v1/merge/${jobId}/audio`,
  MERGE_PROFILES: `${API_BASE_URL}/api/v1/merge/profiles`,
};

export default API;
