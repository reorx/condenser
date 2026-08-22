import { describe, expect, it } from 'vitest';

import type { TimelineItem } from '@/lib/types';

import { itemInSweep } from './useBulkRead';

// Only the fields the sweep reads; the rest of the envelope is irrelevant here.
function item(over: Record<string, unknown>): TimelineItem {
  return { datetime: '2026-08-20T10:00:00', ...over } as unknown as TimelineItem;
}

const RSS_FEED = 'https://a.example.com/feed.xml';
const rssItem = item({ source: 'rss', rss: { feed_url: RSS_FEED } });
const xItem = item({ source: 'x', x: { feed: 'foryou' } });
const tgItem = item({ source: 'telegram', telegram: { channel_id: 7 } });

describe('itemInSweep', () => {
  it('matches RSS items by feed URL in a feed-scoped sweep', () => {
    // The /s/rss/:feed "mark all read": server burns the feed's entries, so the
    // optimistic sweep must flip the same cards — not just zero the badge.
    const args = { source: 'rss' as const, feed: RSS_FEED };
    expect(itemInSweep(args, rssItem)).toBe(true);
    expect(itemInSweep(args, item({ source: 'rss', rss: { feed_url: 'https://other.example.com/f' } }))).toBe(false);
    expect(itemInSweep(args, xItem)).toBe(false);
  });

  it('matches X items by feed key in a feed-scoped sweep', () => {
    const args = { source: 'x' as const, feed: 'foryou' };
    expect(itemInSweep(args, xItem)).toBe(true);
    expect(itemInSweep(args, item({ source: 'x', x: { feed: 'following' } }))).toBe(false);
  });

  it('scopes by channel and by date', () => {
    expect(itemInSweep({ channel_id: 7 }, tgItem)).toBe(true);
    expect(itemInSweep({ channel_id: 8 }, tgItem)).toBe(false);
    expect(itemInSweep({ before_date: '2026-08-21' }, rssItem)).toBe(true);
    expect(itemInSweep({ before_date: '2026-08-20' }, rssItem)).toBe(false);
  });

  it('an unscoped sweep covers everything', () => {
    for (const it_ of [rssItem, xItem, tgItem]) expect(itemInSweep({}, it_)).toBe(true);
  });
});
