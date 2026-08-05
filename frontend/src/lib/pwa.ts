// PWA window bootstrap: when the app runs as an installed desktop app
// (display-mode: standalone), snap the window down to a phone-sized viewport —
// the app's layout is mobile-first and reads best in a narrow column. Chromium
// permits window.resizeTo() in standalone PWA windows (single-tab app windows),
// where a regular tab would ignore it.

export const PHONE_WINDOW_WIDTH = 420;
export const PHONE_WINDOW_HEIGHT = 920;

// The subset of `window` we touch, injectable for tests (jsdom has no real
// matchMedia/resizeTo).
export interface PwaWindow {
  matchMedia(query: string): { matches: boolean };
  outerWidth: number;
  screen: { availHeight: number };
  resizeTo(width: number, height: number): void;
}

export function isStandaloneDisplayMode(win: PwaWindow): boolean {
  return win.matchMedia('(display-mode: standalone)').matches;
}

/**
 * Resize the installed-app window to phone size. Returns whether a resize was
 * issued. Windows at or below phone width are left alone — the user may have
 * sized it deliberately, and re-widening a narrowed window would fight them.
 */
export function initPwaWindow(win: PwaWindow = window): boolean {
  if (!isStandaloneDisplayMode(win)) return false;
  if (win.outerWidth <= PHONE_WINDOW_WIDTH) return false;
  const height = Math.min(PHONE_WINDOW_HEIGHT, win.screen.availHeight);
  try {
    win.resizeTo(PHONE_WINDOW_WIDTH, height);
  } catch {
    return false;
  }
  return true;
}
