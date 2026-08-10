import { describe, expect, it } from 'vitest';

import { linkify } from './linkify';
import { xPreviewUrls } from './sources';
import { stripTrailingMediaTco, urlEntityMap } from './xUrls';
import type { XTweet, XUrlEntity } from './types';

const ENTITY: XUrlEntity = {
  url: 'https://t.co/qzYxwreb9x',
  expanded_url: 'https://haotianzheng.com/?t=202607291001',
  display_url: 'haotianzheng.com/?t=202607291001',
  indices: [0, 23],
};

function tweet(over: Partial<XTweet>): XTweet {
  return {
    id: '1',
    author_id: null,
    author_handle: 'alice',
    author_name: 'Alice',
    text: null,
    created_at: null,
    first_seen_at: '2026-07-24T09:00:00Z',
    media: null,
    metrics: null,
    quote: null,
    rt_of_handle: null,
    reply_to_id: null,
    article: null,
    urls: null,
    feed: 'foryou',
    feed_kind: 'home',
    verdict: null,
    verdict_meta: null,
    ...over,
  };
}

describe('linkify with url entities', () => {
  it('renders a matching t.co with display_url as anchor text and expanded_url as href', () => {
    const nodes = linkify('read https://t.co/qzYxwreb9x now', [ENTITY]);
    const anchor = nodes.find((n) => typeof n === 'object' && n !== null && 'props' in n) as React.ReactElement<{
      href: string;
      children: string;
    }>;
    expect(anchor.props.href).toBe('https://haotianzheng.com/?t=202607291001');
    expect(anchor.props.children).toBe('haotianzheng.com/?t=202607291001');
  });

  it('keeps an unmatched t.co verbatim (old rows, un-upgraded probe)', () => {
    const nodes = linkify('read https://t.co/other now', [ENTITY]);
    const anchor = nodes.find((n) => typeof n === 'object' && n !== null && 'props' in n) as React.ReactElement<{
      href: string;
      children: string;
    }>;
    expect(anchor.props.href).toBe('https://t.co/other');
    expect(anchor.props.children).toBe('https://t.co/other');
  });

  it('falls back per entity when expansion fields are missing', () => {
    const bare: XUrlEntity = { url: 'https://t.co/x', expanded_url: null, display_url: null, indices: null };
    const nodes = linkify('https://t.co/x', [bare]);
    const anchor = nodes[0] as React.ReactElement<{ href: string; children: string }>;
    expect(anchor.props.href).toBe('https://t.co/x');
    expect(anchor.props.children).toBe('https://t.co/x');
  });

  it('matches a t.co even with trailing punctuation in the text', () => {
    const nodes = linkify('see https://t.co/qzYxwreb9x.', [ENTITY]);
    const anchor = nodes.find((n) => typeof n === 'object' && n !== null && 'props' in n) as React.ReactElement<{
      href: string;
    }>;
    expect(anchor.props.href).toBe('https://haotianzheng.com/?t=202607291001');
  });
});

describe('stripTrailingMediaTco', () => {
  const map = urlEntityMap([ENTITY]);

  it('hides a trailing t.co that is not a url entity when the tweet has media', () => {
    expect(stripTrailingMediaTco('nice photo https://t.co/mediaXYZ', map, true)).toBe('nice photo');
  });

  it('keeps a trailing t.co that IS a url entity (a real outbound link)', () => {
    const text = 'read https://t.co/qzYxwreb9x';
    expect(stripTrailingMediaTco(text, map, true)).toBe(text);
  });

  it('keeps a trailing t.co when the tweet has no media', () => {
    const text = 'bare link https://t.co/mediaXYZ';
    expect(stripTrailingMediaTco(text, map, false)).toBe(text);
  });

  it('only ever strips at the very end of the text', () => {
    const text = 'https://t.co/mediaXYZ then words';
    expect(stripTrailingMediaTco(text, map, true)).toBe(text);
  });

  it('treats missing url entities as an empty set (old rows strip too)', () => {
    // a trailing t.co beside media is the media's self-link whether or not the
    // row carries entities — X's own UI never shows it
    expect(stripTrailingMediaTco('old https://t.co/x', urlEntityMap(null), true)).toBe('old');
  });
});

describe('xPreviewUrls with url entities', () => {
  it('previews the expanded original, not the t.co', () => {
    const t = tweet({ text: 'read https://t.co/qzYxwreb9x', urls: [ENTITY] });
    expect(xPreviewUrls(t)).toEqual(['https://haotianzheng.com/?t=202607291001']);
  });

  it('drops the trailing media self-link but keeps real links', () => {
    const t = tweet({
      text: 'read https://t.co/qzYxwreb9x https://t.co/mediaXYZ',
      urls: [ENTITY],
      media: [{ type: 'photo' }],
    });
    expect(xPreviewUrls(t)).toEqual(['https://haotianzheng.com/?t=202607291001']);
  });

  it('drops the expanded link that points at the embedded quote', () => {
    const quoteLink: XUrlEntity = {
      url: 'https://t.co/qq',
      expanded_url: 'https://x.com/bob/status/42',
      display_url: 'x.com/bob/status/42',
      indices: null,
    };
    const t = tweet({
      text: 'so true https://t.co/qq',
      urls: [quoteLink],
      quote: {
        id: '42',
        author_handle: 'bob',
        author_name: 'Bob',
        text: 'quoted',
        created_at: null,
        media: null,
        metrics: null,
        urls: null,
      },
    });
    expect(xPreviewUrls(t)).toEqual([]);
  });

  it('keeps the legacy trailing-self-link heuristic for rows without urls', () => {
    const t = tweet({ text: 'photo https://t.co/self', urls: null, media: [{ type: 'photo' }] });
    expect(xPreviewUrls(t)).toEqual([]);
    const t2 = tweet({ text: 'link https://example.com https://t.co/self', urls: null, media: [{ type: 'photo' }] });
    expect(xPreviewUrls(t2)).toEqual(['https://example.com']);
  });
});
