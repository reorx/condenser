import { describe, expect, it } from 'vitest';

import { NAVIGATE_FALLBACK_DENYLIST } from './swDenylist';

const denied = (path: string) => NAVIGATE_FALLBACK_DENYLIST.some((re) => re.test(path));

describe('service worker navigateFallbackDenylist', () => {
  it('passes API calls through to the backend', () => {
    expect(denied('/api/health')).toBe(true);
    expect(denied('/api/timeline?limit=1')).toBe(true);
  });

  it('never serves the SPA shell for purifier documents and assets', () => {
    // Review 2026-09-07 #5: the Mac Catalyst app hands /p/... to the system browser,
    // which has the installed PWA's service worker; workbox answered with index.html
    // and the ticket exchange never reached the backend.
    expect(denied('/p/news.ycombinator.com/item?id=1&_pt=abc')).toBe(true);
    expect(denied('/p/blog.example')).toBe(true);
    expect(denied('/pa/cdn.example/news.css')).toBe(true);
  });

  it('keeps client routes on the SPA shell', () => {
    for (const path of ['/', '/saved', '/forwards', '/authorize', '/pending', '/parts/1', '/s/x/foryou']) {
      expect(denied(path), path).toBe(false);
    }
  });
});
