import axios from 'axios';

const API_KEY = process.env.REACT_APP_YOUTUBE_API_KEY;
const BASE_URL = 'https://www.googleapis.com/youtube/v3';

// Fetch videos based on the search query
export const fetchVideos = async (searchQuery, videoDuration = 'long') => {
  try {
    const response = await axios.get(`${BASE_URL}/search`, {
      params: {
        part: 'snippet',
        q: `${searchQuery} podcast`, // Include "podcast" in the query for specificity
        type: 'video',
        videoDuration, // Fetch videos of specified duration
        maxResults: 20, // Limit results to 10
        key: API_KEY,
      },
    });

    // Further filter results on the client side
    const relevantVideos = response.data.items.filter((video) => {
      const title = video.snippet.title.toLowerCase();
      const description = video.snippet.description.toLowerCase();
      const queryLower = searchQuery.toLowerCase();

      // Check if the query is in the title or description
      return title.includes(queryLower) || description.includes(queryLower);
    });

    return relevantVideos;
  } catch (error) {
    console.error('Error fetching videos:', error);
    return [];
  }
};


