import {
  formatCompressionMetric,
  resolveTopicsList,
  formatTopicsCount,
} from './resultMetrics.js';

describe('formatCompressionMetric contract', () => {
  test('handles normal valid values', () => {
    // 1,000 words out of 10,000 words = 10%
    expect(formatCompressionMetric(0.1, 10000, 1000)).toBe('10%');
    expect(formatCompressionMetric(0.254, 1000, 254)).toBe('25%');
    expect(formatCompressionMetric(0.5, 200, 100)).toBe('50%');
  });

  test('clamps output > input to 100% (never 1000% or 7100%)', () => {
    // Historical bug: output_words > total_source_words produced ratio > 1.0 (e.g. 71.0 -> 7100%)
    expect(formatCompressionMetric(71.0, 2, 142)).toBe('100%');
    expect(formatCompressionMetric(1.5, 100, 150)).toBe('100%');
    expect(formatCompressionMetric(10.0, 10, 100)).toBe('100%');
  });

  test('handles zero input gracefully returning unavailable "—"', () => {
    expect(formatCompressionMetric(0.0, 0, 0)).toBe('—');
    expect(formatCompressionMetric(0.0, 0, 100)).toBe('—');
    expect(formatCompressionMetric(0.0, 100, 0)).toBe('—');
  });

  test('handles missing or invalid metadata gracefully returning unavailable "—"', () => {
    expect(formatCompressionMetric(null, null, null)).toBe('—');
    expect(formatCompressionMetric(undefined, undefined, undefined)).toBe('—');
    expect(formatCompressionMetric(NaN, 100, 50)).toBe('—');
    expect(formatCompressionMetric(0.2, null, 50)).toBe('—');
    expect(formatCompressionMetric(0.2, 100, null)).toBe('—');
  });

  test('clamps negative values to 0%', () => {
    expect(formatCompressionMetric(-0.5, 100, 10)).toBe('0%');
  });
});

describe('resolveTopicsList contract', () => {
  test('uses topics_found when present and valid', () => {
    const topics = ['Neural Networks', 'Backpropagation'];
    const concepts = [{ name: 'Deep Learning' }];
    expect(resolveTopicsList(topics, concepts)).toEqual(['Neural Networks', 'Backpropagation']);
  });

  test('falls back to concepts when topics_found is empty or missing', () => {
    const concepts = [
      { name: 'Quantum Computing' },
      { name: 'Superposition' },
      'Entanglement',
    ];
    expect(resolveTopicsList([], concepts)).toEqual([
      'Quantum Computing',
      'Superposition',
      'Entanglement',
    ]);
    expect(resolveTopicsList(null, concepts)).toEqual([
      'Quantum Computing',
      'Superposition',
      'Entanglement',
    ]);
  });

  test('returns empty array when neither topics_found nor concepts are available', () => {
    expect(resolveTopicsList([], [])).toEqual([]);
    expect(resolveTopicsList(null, null)).toEqual([]);
    expect(resolveTopicsList(['', '   '], [{}, { name: '  ' }])).toEqual([]);
  });

  test('deduplicates concept names', () => {
    const concepts = [
      { name: 'Attention' },
      { name: 'Attention' },
      'Transformer',
    ];
    expect(resolveTopicsList([], concepts)).toEqual(['Attention', 'Transformer']);
  });
});

describe('formatTopicsCount contract', () => {
  test('returns count number when topics exist', () => {
    expect(formatTopicsCount(['AI', 'ML'], [])).toBe(2);
    expect(formatTopicsCount([], [{ name: 'Robotics' }, { name: 'Control' }])).toBe(2);
  });

  test('returns neutral "—" instead of misleading 0 when no topics exist', () => {
    expect(formatTopicsCount([], [])).toBe('—');
    expect(formatTopicsCount(null, null)).toBe('—');
    expect(formatTopicsCount(undefined, undefined)).toBe('—');
  });
});
