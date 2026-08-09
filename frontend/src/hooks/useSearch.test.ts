import { describe, expect, it } from 'vitest';

import { scopeParams } from '@/hooks/useSearch';

describe('search scope', () => {
  it('maps a subscription onto whichever parameter its source uses', () => {
    // The picker knows only "a row under a source"; the API takes the timeline's
    // own three scope parameters, and this is the one place that translation lives.
    expect(scopeParams({ source: 'telegram', sub: '12345' })).toEqual({
      source: 'telegram',
      channel_id: 12345,
      feed: null,
    });
    expect(scopeParams({ source: 'x', sub: 'foryou' })).toEqual({ source: 'x', channel_id: null, feed: 'foryou' });
  });

  it('sends only the source when the whole source is selected', () => {
    expect(scopeParams({ source: 'hn' })).toEqual({ source: 'hn', channel_id: null, feed: null });
    // HN has one feed, so its subscription row says nothing the source does not
    expect(scopeParams({ source: 'hn', sub: 'front' })).toEqual({ source: 'hn', channel_id: null, feed: null });
  });

  it('sends nothing at all for "All sources"', () => {
    expect(scopeParams({})).toEqual({ source: null, channel_id: null, feed: null });
    // a stale `sub` with no source cannot narrow anything, and must not be sent
    expect(scopeParams({ sub: '12345' })).toEqual({ source: null, channel_id: null, feed: null });
  });
});
