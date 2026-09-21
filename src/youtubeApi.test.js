import axios from 'axios';
import { fetchVideos } from './youtubeApi.js';

jest.mock('axios');

describe('fetchVideos', () => {
  beforeEach(() => {
    axios.get.mockReset();
  });

  test('returns YouTube results for a successful search', async () => {
    const items = [{ id: { videoId: 'abc123' }, snippet: { title: 'Podcast' } }];
    axios.get.mockResolvedValue({ data: { items } });
    await expect(fetchVideos('podcast')).resolves.toEqual(items);
    expect(axios.get).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/youtube/search',
      expect.objectContaining({
        params: expect.objectContaining({ q: 'podcast', duration: 'any', max_results: 20 }),
      })
    );
  });

  test('does not disguise an API failure as an empty result', async () => {
    axios.get.mockRejectedValue({
      response: {
        data: { error: { message: 'Quota exceeded', errors: [{ reason: 'quotaExceeded' }] } },
      },
    });
    await expect(fetchVideos('podcast')).rejects.toThrow('quota has been reached');
  });

  test('reports network failures', async () => {
    axios.get.mockRejectedValue(new Error('Network Error'));
    await expect(fetchVideos('podcast')).rejects.toThrow('Could not connect to YouTube');
  });
});
