export const fetchTranscript = async (videoId) => {
    try {
      const response = await fetch(`http://localhost:8000/api/v1/transcript?videoId=${videoId}`);
      if (!response.ok) {
        throw new Error(`Error: ${response.status}`);
      }
      const data = await response.json();
      // Backend returns { transcript: [...], source, cached } — unwrap it
      return Array.isArray(data) ? data : data?.transcript || [];
    } catch (error) {
      console.error('Error fetching transcript:', error.message);
      return []; // Return an empty array in case of an error
    }
  };
  