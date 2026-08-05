import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';

import { api } from '@/lib/api';
import type { TimelinePage } from '@/lib/types';

import { useScrollToRead } from './useScrollToRead';

vi.mock('@/lib/api', () => ({
  api: { markRead: vi.fn() },
}));

const markRead = vi.mocked(api.markRead);

// --- IntersectionObserver mock: capture the callback, fire entries manually ---

interface FakeEntry {
  target: Element;
  isIntersecting: boolean;
  boundingClientRect: { top: number; bottom: number };
  rootBounds: { top: number; bottom: number } | null;
}

let ioCallback: ((entries: FakeEntry[]) => void) | null = null;
const observed = new Set<Element>();

class FakeIntersectionObserver {
  constructor(cb: (entries: FakeEntry[]) => void) {
    ioCallback = cb;
  }
  observe(el: Element) {
    observed.add(el);
  }
  unobserve(el: Element) {
    observed.delete(el);
  }
  disconnect() {
    observed.clear();
  }
}

function fire(entries: FakeEntry[]) {
  act(() => ioCallback?.(entries));
}

/** An element whose getBoundingClientRect reports the given bottom edge. */
function elementWithBottom(bottom: number): HTMLElement {
  const el = document.createElement('article');
  el.getBoundingClientRect = () =>
    ({ top: bottom - 100, bottom, left: 0, right: 0, width: 0, height: 100, x: 0, y: 0 }) as DOMRect;
  return el;
}

function entry(target: Element, bottom: number, viewportBottom = 800): FakeEntry {
  return {
    target,
    isIntersecting: bottom > 0 && bottom - 100 < viewportBottom,
    boundingClientRect: { top: bottom - 100, bottom },
    rootBounds: { top: 0, bottom: viewportBottom },
  };
}

/** Arm the tracker: a genuine user scroll (scrollY > 0). */
function userScroll(y = 120) {
  act(() => {
    Object.defineProperty(window, 'scrollY', { value: y, configurable: true });
    window.dispatchEvent(new Event('scroll'));
  });
}

function makeQc(): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const page: TimelinePage = {
    items: [
      { source: 'telegram', key: 'tg:1:10', datetime: '2026-08-05T00:00:00Z', is_read: false, is_saved: false },
      { source: 'telegram', key: 'tg:1:11', datetime: '2026-08-05T00:01:00Z', is_read: false, is_saved: false },
    ],
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
  qc.setQueryData(['timeline', 'all'], { pages: [page], pageParams: [null] });
  return qc;
}

let qc: QueryClient;

function setup(viewKey = 'view-a') {
  qc = makeQc();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return renderHook(({ vk }) => useScrollToRead(vk), { wrapper, initialProps: { vk: viewKey } });
}

function cachedItem(key: string) {
  const data = qc.getQueryData<{ pages: TimelinePage[] }>(['timeline', 'all']);
  return data!.pages[0].items.find((it) => it.key === key)!;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver);
  Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
  Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
  markRead.mockReset();
  markRead.mockResolvedValue({ ok: true });
  ioCallback = null;
  observed.clear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('useScrollToRead: read-line judgement', () => {
  it('queues an item once its bottom edge passes the viewport bottom (still visible)', () => {
    const { result } = setup();
    const el = elementWithBottom(700);
    act(() => void result.current.observe(el, { key: 'tg:1:10', channelId: 1 }));

    userScroll();
    // Fully visible: bottom (700) <= viewport bottom (800) — the new read line.
    fire([entry(el, 700)]);

    expect(result.current.pendingKeys.has('tg:1:10')).toBe(true);
  });

  it('does not queue an item whose bottom edge is still below the viewport', () => {
    const { result } = setup();
    const el = elementWithBottom(900);
    act(() => void result.current.observe(el, { key: 'tg:1:10', channelId: 1 }));

    userScroll();
    fire([entry(el, 900)]);

    expect(result.current.pendingKeys.has('tg:1:10')).toBe(false);
  });

  it('still covers the old condition: scrolled fully above the viewport top', () => {
    const { result } = setup();
    const el = elementWithBottom(-50);
    act(() => void result.current.observe(el, { key: 'tg:1:10', channelId: 1 }));

    userScroll();
    fire([entry(el, -50)]);

    expect(result.current.pendingKeys.has('tg:1:10')).toBe(true);
  });

  it('ignores crossings until the user scrolls (armed gate)', () => {
    const { result } = setup();
    const el = elementWithBottom(700);
    act(() => void result.current.observe(el, { key: 'tg:1:10', channelId: 1 }));

    fire([entry(el, 700)]);

    expect(result.current.pendingKeys.size).toBe(0);
  });

  it('sweeps already-visible observed elements the moment the tracker arms', () => {
    // IO fires no callback for elements with no intersection *change*, so the
    // first-screen items must be caught by a manual scan when arming.
    const { result } = setup();
    const visible = elementWithBottom(400);
    const below = elementWithBottom(1200);
    act(() => {
      result.current.observe(visible, { key: 'tg:1:10', channelId: 1 });
      result.current.observe(below, { key: 'tg:1:11', channelId: 1 });
    });

    userScroll();

    expect(result.current.pendingKeys.has('tg:1:10')).toBe(true);
    expect(result.current.pendingKeys.has('tg:1:11')).toBe(false);
  });

  it('disarm() re-gates marking until the next user scroll', () => {
    const { result } = setup();
    userScroll();
    act(() => result.current.disarm());

    const el = elementWithBottom(700);
    act(() => void result.current.observe(el, { key: 'tg:1:10', channelId: 1 }));
    fire([entry(el, 700)]);

    expect(result.current.pendingKeys.size).toBe(0);
  });
});

describe('useScrollToRead: sync lifecycle', () => {
  function queueOne(result: { current: ReturnType<typeof useScrollToRead> }, key = 'tg:1:10') {
    const el = elementWithBottom(700);
    act(() => void result.current.observe(el, { key, channelId: 1 }));
    userScroll();
    fire([entry(el, 700)]);
  }

  it('flushes after the debounce and clears pending only on server success', async () => {
    const { result } = setup();
    queueOne(result);
    expect(cachedItem('tg:1:10').is_read).toBe(false);

    await act(() => vi.advanceTimersByTimeAsync(700));

    expect(markRead).toHaveBeenCalledWith(['tg:1:10']);
    expect(result.current.pendingKeys.has('tg:1:10')).toBe(false);
    // The optimistic cache flip happens on confirmation, not on send.
    expect(cachedItem('tg:1:10').is_read).toBe(true);
  });

  it('keeps the key pending on failure and retries with backoff until it lands', async () => {
    markRead.mockRejectedValueOnce(new Error('offline'));
    const { result } = setup();
    queueOne(result);

    await act(() => vi.advanceTimersByTimeAsync(700));

    expect(result.current.pendingKeys.has('tg:1:10')).toBe(true);
    expect(cachedItem('tg:1:10').is_read).toBe(false);

    // Backoff: debounce * 5 later the queue retries and succeeds.
    await act(() => vi.advanceTimersByTimeAsync(3500));

    expect(markRead).toHaveBeenCalledTimes(2);
    expect(result.current.pendingKeys.has('tg:1:10')).toBe(false);
    expect(cachedItem('tg:1:10').is_read).toBe(true);
  });
});
