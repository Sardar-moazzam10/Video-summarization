/**
 * API Configuration - Central source of truth
 */

// Backend API base URL
export const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export const authHeaders = (extra = {}) => {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('access_token') : null;
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
};

export const authenticatedFetch = async (url, options = {}) => {
  const finalUrl = (typeof url === 'string' && url.startsWith('/')) ? `${API_BASE_URL}${url}` : url;
  const response = await fetch(finalUrl, {
    ...options,
    headers: authHeaders(options.headers || {}),
  });

  if (response.status === 401 && typeof window !== 'undefined') {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user');
    localStorage.removeItem('refresh_token');
    if (!window.location.pathname.startsWith('/login')) {
      window.location.href = '/login?expired=1';
    }
  }

  return response;
};

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
  TRANSCRIPT_QUERY: (videoId) => `${API_BASE_URL}/api/v1/transcript?videoId=${videoId}`,
  TRANSCRIPT_COMPILE: `${API_BASE_URL}/api/v1/transcript/compile`,
  SUMMARIZE: `${API_BASE_URL}/api/v1/summarize`,

  // Merge
  MERGE: `${API_BASE_URL}/api/v1/merge`,
  MERGE_STATUS: (jobId) => `${API_BASE_URL}/api/v1/merge/${jobId}`,
  MERGE_RESULT: (jobId) => `${API_BASE_URL}/api/v1/merge/${jobId}/result`,
  MERGE_AUDIO: (jobId) => `${API_BASE_URL}/api/v1/merge/${jobId}/audio`,
  MERGE_STREAM: (jobId) => `${API_BASE_URL}/api/v1/merge/${jobId}/stream`,
  MERGE_EXPORT: (jobId, format) => `${API_BASE_URL}/api/v1/merge/${jobId}/export?format=${format}`,
  MERGE_PROFILES: `${API_BASE_URL}/api/v1/merge/profiles`,
  MERGE_PREFLIGHT: `${API_BASE_URL}/api/v1/merge/preflight`,
  // Real media duration per video, plus which summary lengths it allows.
  MERGE_VIDEO_DURATIONS: (videoIds) =>
    `${API_BASE_URL}/api/v1/merge/video-durations?video_ids=${encodeURIComponent(videoIds.join(','))}`,

  // Chat
  CHAT: `${API_BASE_URL}/api/v1/chat`,
};

export default API;
