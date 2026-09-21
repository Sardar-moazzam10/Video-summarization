import { buildMergeRequest } from './SearchPage';

test('normal Search query is propagated through the existing merge request', () => {
  expect(buildMergeRequest(['a', 'b'], 5, ' Supervised Machine Learning ')).toEqual({
    video_ids: ['a', 'b'],
    target_duration_minutes: 5,
    generate_audio: true,
    generate_video: true,
    query: 'Supervised Machine Learning',
  });
});

test('query remains optional for normal non-keyword merges', () => {
  expect(buildMergeRequest(['a'], 10, '').query).toBeUndefined();
});
