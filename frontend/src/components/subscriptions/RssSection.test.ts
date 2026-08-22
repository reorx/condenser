import { describe, expect, it } from 'vitest';

import { rssRefetchInterval } from '@/components/subscriptions/RssSection';
import type { RssSubscription } from '@/lib/types';

function sub(url: string, over: Partial<RssSubscription> = {}): RssSubscription {
  return {
    url,
    name: null,
    enabled: true,
    site_url: null,
    fetched_at: null,
    last_error: null,
    error_count: 0,
    ...over,
  };
}

const OK = { fetched_at: '2026-08-22 06:19:34' };
const BROKEN = { last_error: 'HTTP 404', error_count: 2 };

describe('rss subscription poll interval', () => {
  it('polls fast while a freshly imported feed has no verdict yet', () => {
    expect(rssRefetchInterval([sub('https://a.example/feed'), sub('https://b.example/feed')])).toBe(5_000);
  });

  it('slows down once every running feed has one — including the failed ones', () => {
    // The reproduction: a permanently failing feed never gets a `fetched_at`
    // (record_rss_feed_error deliberately leaves it alone, so a stale feed stays
    // visible as stale), so "some feed lacks fetched_at" never ended and the page
    // polled every 5s for as long as it was open.
    expect(rssRefetchInterval([sub('https://a.example/feed', OK), sub('https://b.example/feed', BROKEN)])).toBe(60_000);
  });

  it('slows down when every feed has been fetched', () => {
    expect(rssRefetchInterval([sub('https://a.example/feed', OK), sub('https://b.example/feed', OK)])).toBe(60_000);
  });

  it('ignores a paused feed that was never fetched', () => {
    // Paused before its first round: no fetch, no error, and no round is coming —
    // the same never-ending poll through a second door.
    expect(rssRefetchInterval([sub('https://a.example/feed', { enabled: false })])).toBe(60_000);
  });
});
