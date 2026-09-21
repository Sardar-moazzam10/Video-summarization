import assert from 'assert';
import {
  normalizeText,
  stemWord,
  searchKeywordInTranscript,
  fetchTranscript
} from '../src/youtubeTranscript.mjs';

console.log('--- Running Keyword Matcher Tests ---');

// Test Case 1: Exact keyword match
{
  const transcript = [
    { start: 0.0, duration: 3.5, text: "Welcome back to the channel." },
    { start: 3.5, duration: 4.0, text: "Today we will study gradient descent in depth." },
    { start: 7.5, duration: 3.0, text: "Let's begin with loss functions." }
  ];

  const results = searchKeywordInTranscript(transcript, "gradient descent");
  assert.strictEqual(results.length, 1, "Should find 1 match for gradient descent");
  assert.strictEqual(results[0].start, 3.5, "Match timestamp should be 3.5");
  assert.strictEqual(results[0].isExact, true, "Should be exact match");
  console.log('✓ Test Case 1 (Exact Match): Passed');
}

// Test Case 2: Split phrase across caption boundaries (Sliding Window)
{
  const transcript = [
    { start: 10.0, duration: 2.0, text: "Let's take a look at the support" },
    { start: 12.0, duration: 2.5, text: "vector machine algorithm and how it works." },
    { start: 14.5, duration: 3.0, text: "It creates an optimal hyperplane." }
  ];

  const results = searchKeywordInTranscript(transcript, "support vector machine");
  assert.strictEqual(results.length, 1, "Should find 1 match split across 2 lines");
  assert.strictEqual(results[0].start, 10.0, "Start timestamp should be start of first segment (10.0)");
  assert.strictEqual(results[0].isExact, true, "Cross-boundary exact phrase match should have isExact=true");
  assert(results[0].text.includes("support") && results[0].text.includes("vector machine"), "Text should contain merged phrase");
  console.log('✓ Test Case 2 (Cross-Boundary Split Phrase): Passed');
}

// Test Case 3: Plural / Singular variations
{
  const transcript = [
    { start: 20.0, duration: 3.0, text: "Deep neural networks are composed of many layers." },
    { start: 23.0, duration: 3.0, text: "Each neural network learns different representations." }
  ];

  // Search singular "neural network" when transcript has plural "neural networks"
  const results1 = searchKeywordInTranscript(transcript, "neural network");
  assert.strictEqual(results1.length, 2, "Should find both singular and plural");
  // The first one is plural in transcript, searched singular -> stemmed match or exact substring match
  // In this case 'neural network' is a substring of 'neural networks' (exact=true)
  
  // Now search plural "neural networks" when segment 2 only has singular "neural network"
  const results2 = searchKeywordInTranscript(transcript, "neural networks");
  assert.strictEqual(results2.length, 2, "Should match both segments");
  const segment2Match = results2.find(r => r.start === 23.0);
  assert(segment2Match, "Should find match at 23.0");
  assert.strictEqual(segment2Match.isExact, false, "Singular segment with plural query should have isExact=false");
  console.log('✓ Test Case 3 (Plural/Singular Stemming): Passed');
}

// Test Case 4: No-caption result (fast-fail)
{
  // When fetchTranscript receives 404, it returns empty array immediately
  // Mock global fetch for this test
  const originalFetch = global.fetch;
  global.fetch = async (url) => {
    return {
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({ detail: 'No captions found' })
    };
  };

  const res = await fetchTranscript('no_caption_vid_123', { allowWhisper: false });
  assert.deepStrictEqual(res, [], "Should return empty array fast on 404 without errors");
  console.log('✓ Test Case 4 (Fast-fail on no-caption video): Passed');

  global.fetch = originalFetch;
}

// Test Case 5: Expired auth (401) and backend down (Network error) error surfacing
{
  // Test 401 error surfacing
  const originalFetch = global.fetch;
  global.fetch = async () => {
    return {
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      json: async () => ({ detail: 'Token expired' })
    };
  };

  let caught401 = false;
  try {
    await fetchTranscript('vid_auth_test', { allowWhisper: false });
  } catch (err) {
    caught401 = true;
    assert.strictEqual(err.status, 401);
    assert(err.message.includes('Authentication expired') || err.message.includes('log in again'));
  }
  assert.strictEqual(caught401, true, "Should surface 401 auth error");

  // Test network error surfacing
  global.fetch = async () => {
    throw new TypeError('Failed to fetch');
  };

  let caughtNetwork = false;
  try {
    await fetchTranscript('vid_net_test', { allowWhisper: false });
  } catch (err) {
    caughtNetwork = true;
    assert.strictEqual(err.isNetworkError, true);
    assert(err.message.includes('Backend server is unreachable'));
  }
  assert.strictEqual(caughtNetwork, true, "Should surface network unreachable error");

  global.fetch = originalFetch;
  console.log('✓ Test Case 5 (Auth 401 & Network Error Surfacing): Passed');
}

console.log('\nAll 5 Client & Transcript Test Cases Passed Successfully!');
// Test Case 6: Multi-concept query ("linear regression and logistic regression")
{
  const transcript = [
    { start: 5.0, duration: 4.0, text: "In this module, we introduce linear regression models." },
    { start: 25.0, duration: 4.0, text: "Later on, we will explore logistic regression for classification." },
    { start: 60.0, duration: 3.0, text: "Both methods are fundamental machine learning tools." }
  ];

  const results = searchKeywordInTranscript(transcript, "linear regression and logistic regression");
  assert.strictEqual(results.length, 2, "Should find 2 matches for separate concepts in the query");
  assert.strictEqual(results[0].start, 5.0, "First match should be linear regression at 5.0");
  assert.strictEqual(results[1].start, 25.0, "Second match should be logistic regression at 25.0");
  assert(results[0].text.includes("linear regression"), "Match 1 contains linear regression");
  assert(results[1].text.includes("logistic regression"), "Match 2 contains logistic regression");
  assert(results[0].contextText.length > results[0].text.length, "Should include surrounding context");
  console.log('✓ Test Case 6 (Multi-Concept Query: "X and Y"): Passed');
}

// Test Case 7: Region deduplication of close moments
{
  const transcript = [
    { start: 10.0, duration: 2.0, text: "Gradient descent optimizes the objective function." },
    { start: 12.0, duration: 2.0, text: "Stochastic gradient descent operates on mini batches." },
    { start: 40.0, duration: 3.0, text: "Now let us observe the final gradient descent loss." }
  ];

  const results = searchKeywordInTranscript(transcript, "gradient descent and stochastic gradient descent");
  // 10.0 and 12.0 are within 2.0s of each other (overlapping region) -> deduplicated to single entry
  const momentsNearStart = results.filter(r => r.start <= 15.0);
  assert.strictEqual(momentsNearStart.length, 1, "Should deduplicate overlapping matches from the same region");
  console.log('✓ Test Case 7 (Region Deduplication): Passed');
}

console.log('\nAll 7 Client & Transcript Test Cases Passed Successfully!');

