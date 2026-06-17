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

    // Filter: at least one word from the query must appear in title or description
    const queryWords = searchQuery.toLowerCase().split(/\s+/).filter(w => w.length > 2);
    const relevantVideos = response.data.items.filter((video) => {
      const title = video.snippet.title.toLowerCase();
      const description = video.snippet.description.toLowerCase();
      return queryWords.some(word => title.includes(word) || description.includes(word));
    });

    return relevantVideos;
  } catch (error) {
    console.error('Error fetching videos:', error);
    return [];
  }
};


