import express from 'express';
import cors from 'cors';
import fetch from 'node-fetch';
import * as cheerio from 'cheerio';

const app = express();
const PORT = process.env.PROXY_PORT || 8081;

app.use(cors());

app.get('/proxy/:videoId', async (req, res) => {
  const videoId = req.params.videoId;
  const youtubeUrl = `https://www.youtube.com/watch?v=${videoId}`;

  try {
    // Fetch the YouTube page HTML
    const response = await fetch(youtubeUrl);
    const html = await response.text();

    // Load the HTML with Cheerio
    const $ = cheerio.load(html);

    let transcriptUrl = null;

    // Search for the script containing "captionTracks"
    $('script').each((i, el) => {
      const scriptContent = $(el).html();
      if (scriptContent.includes('captionTracks')) {
        console.log('Script Content with captionTracks:', scriptContent); // Debug log
        try {
          const startIndex = scriptContent.indexOf('{"captionTracks":');
          const endIndex = scriptContent.indexOf('}]', startIndex) + 2;
    
          if (startIndex !== -1 && endIndex !== -1) {
            const jsonString = scriptContent.slice(startIndex, endIndex);
            const parsedData = JSON.parse(jsonString);
    
            if (
              parsedData.captionTracks &&
              parsedData.captionTracks.length > 0
            ) {
              transcriptUrl = parsedData.captionTracks[0].baseUrl;
            }
          }
        } catch (error) {
          console.error('Error parsing captionTracks JSON:', error.message);
        }
      }
    });
    

    if (transcriptUrl) {
      // Fetch the transcript from the extracted URL
      const transcriptResponse = await fetch(transcriptUrl);
      const transcriptJson = await transcriptResponse.json();

      // Transform the transcript into a structured format
      const transcriptData = transcriptJson.events
        .filter((event) => event.segs) // Ensure events with text segments
        .map((event) => ({
          text: event.segs.map((seg) => seg.utf8).join(' '),
          start: event.tStartMs / 1000, // Convert to seconds
          duration: event.dDurationMs / 1000, // Convert to seconds
        }));

      res.json(transcriptData); // Return the structured transcript data
    } else {
      res.status(404).json({ error: 'Transcript not found.' });
    }
  } catch (error) {
    console.error('Error in proxy server:', error.message);
    res.status(500).json({ error: error.message });
  }
});

app.listen(PORT, () => {
  console.log(`Proxy server running on http://localhost:${PORT}`);
});
