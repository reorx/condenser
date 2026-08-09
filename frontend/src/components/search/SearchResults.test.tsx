import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSearch } from '@/hooks/useSearch';
import { UnreadIndicatorProvider } from '@/lib/unreadIndicator';
import type { TimelineItem } from '@/lib/types';

import { SearchResults } from './SearchResults';

/**
 * Searching is not reading, so the result list must never mark anything read:
 * hunting for one message means flying past dozens of others, and none of them
 * was seen in the sense the timeline's read line means.
 *
 * Today that holds by an *absence* — `DatedItemRow` takes no `observe`, so the
 * cards register with no observer — which is one prop away from being lost. This
 * pins the behaviour instead of the shape: an unread result on screen, a genuine
 * user scroll (the gate that arms `useScrollToRead`), every observed element
 * reporting itself above the read line, and still nothing reaches POST /api/read.
 */

const posted: string[] = [];

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

function unreadItem(): TimelineItem {
  return {
    source: 'telegram',
    key: 'tg:1:10',
    datetime: '2026-08-05T08:00:00+00:00',
    is_read: false,
    is_saved: false,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    telegram: {
      id: 10,
      channel_id: 1,
      grouped_id: null,
      date: '2026-08-05T08:00:00+00:00',
      edit_date: null,
      text: 'a needle in the archive',
      has_media: false,
      media_type: null,
      media_items: [],
      webpage: null,
      is_forwarded: false,
      forward_info: null,
      post_author: null,
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
    } as any,
  };
}

function stubFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost');
    if (init?.method === 'POST') posted.push(url.pathname);
    if (url.pathname === '/api/search') {
      return json({ items: [unreadItem()], total: 1, has_more: false });
    }
    return json({ ok: true });
  });
}

// --- IntersectionObserver: record every observer, fire entries on demand ---

interface FakeEntry {
  target: Element;
  isIntersecting: boolean;
  boundingClientRect: { top: number; bottom: number };
  rootBounds: { top: number; bottom: number } | null;
}

const observers: { cb: (entries: FakeEntry[]) => void; elements: Set<Element> }[] = [];

class FakeIntersectionObserver {
  private entry: { cb: (entries: FakeEntry[]) => void; elements: Set<Element> };
  constructor(cb: (entries: FakeEntry[]) => void) {
    this.entry = { cb, elements: new Set() };
    observers.push(this.entry);
  }
  observe(el: Element) {
    this.entry.elements.add(el);
  }
  unobserve(el: Element) {
    this.entry.elements.delete(el);
  }
  disconnect() {
    this.entry.elements.clear();
  }
}

/** Every observed element reports its bottom edge above the viewport bottom —
 *  the crossing the timeline reads as "fully seen". */
function crossReadLine() {
  for (const o of observers) {
    const entries = [...o.elements].map((target) => ({
      target,
      isIntersecting: true,
      boundingClientRect: { top: 0, bottom: 200 },
      rootBounds: { top: 0, bottom: 800 },
    }));
    if (entries.length) act(() => o.cb(entries));
  }
}

function Harness() {
  const query = useSearch({ q: 'needle' });
  return <SearchResults query={query} />;
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <UnreadIndicatorProvider>{ui}</UnreadIndicatorProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  posted.length = 0;
  observers.length = 0;
  vi.stubGlobal('fetch', stubFetch());
  vi.stubGlobal('IntersectionObserver', FakeIntersectionObserver);
  Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
  Object.defineProperty(window, 'scrollY', { value: 0, configurable: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('SearchResults', () => {
  it('never marks a result read, however far it is scrolled past', async () => {
    wrap(<Harness />);
    const card = await screen.findByText('a needle in the archive');

    // The scroll-to-read gate arms on a real user scroll; do exactly that, then
    // put every observed element above the read line.
    vi.useFakeTimers();
    act(() => {
      Object.defineProperty(window, 'scrollY', { value: 400, configurable: true });
      window.dispatchEvent(new Event('scroll'));
    });
    crossReadLine();
    await act(() => vi.advanceTimersByTimeAsync(5000));

    expect(posted).not.toContain('/api/read');
    // And the card is still unread: the sky dot, not the read state.
    expect(card.closest('article, div')).toBeTruthy();
    expect(document.querySelector('span.bg-sky-500')).toBeTruthy();
  });
});
