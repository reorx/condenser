import { describe, expect, it, vi } from 'vitest';

import { initPwaWindow, PHONE_WINDOW_HEIGHT, PHONE_WINDOW_WIDTH, type PwaWindow } from './pwa';

function makeWindow(overrides: Partial<PwaWindow> & { standalone?: boolean } = {}): PwaWindow {
  const { standalone = true, ...rest } = overrides;
  return {
    matchMedia: (query: string) => ({
      matches: standalone && query === '(display-mode: standalone)',
    }),
    outerWidth: 1440,
    screen: { availHeight: 1080 },
    resizeTo: vi.fn(),
    ...rest,
  };
}

describe('initPwaWindow', () => {
  it('resizes a wide standalone window down to phone size', () => {
    const win = makeWindow();
    expect(initPwaWindow(win)).toBe(true);
    expect(win.resizeTo).toHaveBeenCalledWith(PHONE_WINDOW_WIDTH, PHONE_WINDOW_HEIGHT);
  });

  it('does nothing in a regular browser tab', () => {
    const win = makeWindow({ standalone: false });
    expect(initPwaWindow(win)).toBe(false);
    expect(win.resizeTo).not.toHaveBeenCalled();
  });

  it('leaves an already phone-sized window alone', () => {
    const win = makeWindow({ outerWidth: PHONE_WINDOW_WIDTH });
    expect(initPwaWindow(win)).toBe(false);
    expect(win.resizeTo).not.toHaveBeenCalled();
  });

  it('leaves a window the user made even narrower alone', () => {
    const win = makeWindow({ outerWidth: 360 });
    expect(initPwaWindow(win)).toBe(false);
    expect(win.resizeTo).not.toHaveBeenCalled();
  });

  it('clamps height to the available screen height on short displays', () => {
    const win = makeWindow({ screen: { availHeight: 800 } });
    expect(initPwaWindow(win)).toBe(true);
    expect(win.resizeTo).toHaveBeenCalledWith(PHONE_WINDOW_WIDTH, 800);
  });

  it('survives a window that refuses to resize', () => {
    const win = makeWindow({
      resizeTo: vi.fn(() => {
        throw new Error('blocked');
      }),
    });
    expect(initPwaWindow(win)).toBe(false);
  });
});
