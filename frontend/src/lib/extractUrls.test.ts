import { describe, expect, it } from 'vitest';

import { extractUrls, sameUrl } from './extractUrls';

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
