import { describe, expect, it } from 'vitest';

import { extractUrls, messageHasPreviewableLinks, sameUrl } from './extractUrls';
import type { DisplayMessage, WebPagePreview } from './types';

function msg(over: Partial<DisplayMessage>): DisplayMessage {
  return {
    id: 1,
    channel_id: 1,
    date: '2026-06-23T00:00:00+00:00',
    is_edited: false,
    edit_date: null,
    sender_id: null,
    sender_name: null,
    text: null,
    is_album: false,
    grouped_id: null,
    media_items: [],
    webpage: null,
    is_forwarded: false,
    forward_info: null,
    views: null,
    forwards_count: null,
    replies_count: null,
    raw_message_ids: [1],
    ...over,
  };
}

const wp = (over: Partial<WebPagePreview>): WebPagePreview => ({
  url: null,
  display_url: null,
  type: null,
  site_name: null,
  title: null,
  description: null,
  author: null,
  has_photo: false,
  ...over,
});

describe('extractUrls', () => {
  it('strips trailing punctuation, upgrades www., and de-dupes preserving order', () => {
    expect(extractUrls('see https://a.com/x. and https://a.com/x again, plus www.b.org!')).toEqual([
      'https://a.com/x',
      'https://www.b.org',
    ]);
  });

  it('returns [] for empty/null text', () => {
    expect(extractUrls(null)).toEqual([]);
    expect(extractUrls('no links here')).toEqual([]);
  });
});

describe('sameUrl', () => {
  it('ignores scheme, www, and trailing slash', () => {
    expect(sameUrl('https://www.example.com/a/', 'http://example.com/a')).toBe(true);
    expect(sameUrl('https://example.com/a', 'https://example.com/b')).toBe(false);
  });
});

describe('messageHasPreviewableLinks', () => {
  it('is false when there are no URLs', () => {
    expect(messageHasPreviewableLinks(msg({ text: 'plain text' }))).toBe(false);
  });

  it('is true when there is a URL and no useful inline Telegram preview', () => {
    expect(messageHasPreviewableLinks(msg({ text: 'check https://news.com/post' }))).toBe(true);
  });

  it('is false when the only URL is already covered by the inline Telegram preview', () => {
    expect(
      messageHasPreviewableLinks(
        msg({ text: 'read https://news.com/post', webpage: wp({ url: 'https://news.com/post', title: 'Post' }) }),
      ),
    ).toBe(false);
  });

  it('is true when there are extra URLs beyond the inline preview', () => {
    expect(
      messageHasPreviewableLinks(
        msg({
          text: 'read https://news.com/post and https://other.com/x',
          webpage: wp({ url: 'https://news.com/post', title: 'Post' }),
        }),
      ),
    ).toBe(true);
  });
});
