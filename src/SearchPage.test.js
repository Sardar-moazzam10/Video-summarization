import { buildMergeRequest } from './SearchPage';

test('title discovery is explicitly an overall multi-source request', () => {
  expect(buildMergeRequest(['a', 'b'], 5, ' Supervised Machine Learning ')).toEqual({
    video_ids: ['a', 'b'],
    target_duration_minutes: 5,
    generate_audio: false,
    generate_video: true,
    summary_scope: 'overall',
    source_scope: 'multi',
    discovery_query: 'Supervised Machine Learning',
  });
});

test('title discovery single never sends semantic intent', () => {
  const request = buildMergeRequest(['a'], 10, 'Some Video Title');
  expect(request.source_scope).toBe('single');
  expect(request.summary_scope).toBe('overall');
  expect(request.summary_query).toBeUndefined();
  expect(request.query).toBeUndefined();
});
