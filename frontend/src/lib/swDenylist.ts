// Navigations the service worker must hand to the network instead of answering
// with the precached SPA shell. Imported by vite.config.ts (workbox
// navigateFallbackDenylist) and pinned by swDenylist.test.ts.
//
// - /api/…  the backend, never a client route
// - /p/…    the Purifier's reading proxy (kb/plans/2026-09-07-purifier.md): a
//           document with a `_pt=` ticket to exchange — the Mac Catalyst app opens
//           these in the system browser, exactly where the PWA's worker lives
// - /pa/…   its assets; subresource requests are not navigations, but a shared
//           /pa link opened top-level is
export const NAVIGATE_FALLBACK_DENYLIST: RegExp[] = [/^\/api\//, /^\/pa?(\/|$)/];
