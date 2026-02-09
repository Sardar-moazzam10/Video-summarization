


import axios from "axios";

const API_KEY = import.meta.env.VITE_YOUTUBE_API_KEY;
const BASE_URL = "https://www.googleapis.com/youtube/v3";

// Fetch relevant podcasts based on selected topic
export const fetchSuggestedPodcasts = async (topic) => {
  try {
    const response = await axios.get(`${BASE_URL}/search`, {
      params: {
        part: "snippet",
        q: `${topic} podcast`, // Focus on podcasts
        type: "video",
        maxResults: 10, // Keep this low to avoid API quota issues
        key: API_KEY,
      },
    });

    return response.data.items || [];
  } catch (error) {
    console.error("Error fetching suggested podcasts:", error);
    return [];
  }
};
