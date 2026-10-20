import { buildKeywordMergeRequest } from './SearchByKeywordsPage';

test.each([
  [['a'], 'single'],
  [['a', 'b'], 'multi'],
])('keyword request declares semantic intent for %s source mode', (videoIds, sourceScope) => {
  const request = buildKeywordMergeRequest(videoIds, 5, ' machine learning ');
  expect(request.summary_scope).toBe('keyword');
  expect(request.source_scope).toBe(sourceScope);
  expect(request.summary_query).toBe('machine learning');
  expect(request.selected_keywords).toEqual(['machine learning']);
  expect(request.discovery_query).toBeUndefined();
  expect(request.query).toBeUndefined();
});
