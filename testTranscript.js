import { fetchTranscript } from './src/youtubeTranscript.mjs'; // Adjust path as needed

const testVideoId = 'UF8uR6Z6KLc'; // Replace with a valid YouTube video ID

(async () => {
  try {
    const transcript = await fetchTranscript(testVideoId);
    console.log('Fetched Transcript:', transcript);
  } catch (error) {
    console.error('Error fetching transcript:', error.message);
  }
})();
