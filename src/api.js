export const fetchTranscript = async (videoId) => {
    try {
      const response = await fetch(`http://localhost:5001/transcript?videoId=${videoId}`);
      if (!response.ok) {
        throw new Error(`Error: ${response.status}`);
      }
      const transcript = await response.json(); // Parse the JSON response
      return transcript;
    } catch (error) {
      console.error('Error fetching transcript:', error.message);
      return []; // Return an empty array in case of an error
    }
  };
  