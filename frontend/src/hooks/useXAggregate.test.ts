import { describe, expect, it } from 'vitest';

import { xAggregateLabel, xAggregateModes } from '@/hooks/useXAggregate';
import { isXSyntheticFeed, xFeedLabel } from '@/lib/sources';

describe('X aggregate modes', () => {
  it('does not offer Following a recommended-only mode', () => {
    // Following is never judged — the verdict exists to filter strangers the
    // algorithm picked — so 'positive' would silently hide the whole feed.
    expect(xAggregateModes('following').map((m) => m.value)).toEqual(['none', 'all']);
    expect(xAggregateModes('foryou').map((m) => m.value)).toEqual(['none', 'positive', 'all']);
  });

  it('falls back to the raw value for a mode it has no label for', () => {
    expect(xAggregateLabel('following', 'positive')).toBe('positive');
    expect(xAggregateLabel('foryou', 'positive')).toBe('只进推荐的');
  });
});

describe('X feed identity', () => {
  it('separates the two whole-timeline feeds from an account', () => {
    expect(isXSyntheticFeed('foryou')).toBe(true);
    expect(isXSyntheticFeed('following')).toBe(true);
    expect(isXSyntheticFeed('novoreorx')).toBe(false);
  });

  it('labels an account by its display name, or its handle until one is learned', () => {
    expect(xFeedLabel('following')).toBe('Following');
    expect(xFeedLabel('novoreorx', 'Reorx')).toBe('Reorx');
    expect(xFeedLabel('novoreorx', null)).toBe('@novoreorx');
  });
});
