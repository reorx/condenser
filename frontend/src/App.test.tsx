import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

// jsdom has no matchMedia; ThemeProvider reads the system scheme through it
vi.stubGlobal(
  'matchMedia',
  vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
);

import { ThemeProvider } from '@/lib/theme';
import { UnreadIndicatorProvider } from '@/lib/unreadIndicator';

import App from './App';

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

const TG_UNAUTHORIZED = { status: 'unauthorized' };
const HN_SOURCES = [
  { source: 'hn', subscriptions: [{ channel_id: 'front', name: 'Front Page', enabled: true, unread: 3 }] },
];
const TG_SOURCES = [
  { source: 'telegram', subscriptions: [{ channel_id: 42, name: 'Alpha', enabled: true, unread: 0 }] },
];

const requested: string[] = [];

/** Stubs every endpoint the shell touches; `sources` is the one under test. */
function stubFetch(opts: { tg?: unknown; sources?: unknown | 'pending' }) {
  requested.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const { pathname } = new URL(String(input), 'http://localhost');
      requested.push(pathname);
      if (pathname === '/api/tg/status') return json(opts.tg ?? TG_UNAUTHORIZED);
      if (pathname === '/api/sources') {
        // "pending" models the gap between the two queries: the gate must not
        // decide (and must not flash the wall) before it knows the sources.
        if (opts.sources === 'pending') return new Promise<Response>(() => {});
        return json(opts.sources ?? []);
      }
      if (pathname === '/api/timeline') return json({ items: [], has_more: false });
      return json([]);
    }),
  );
}

function setup(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <ThemeProvider>
      <UnreadIndicatorProvider>
        <QueryClientProvider client={client}>
          <MemoryRouter initialEntries={[path]}>
            <App />
          </MemoryRouter>
        </QueryClientProvider>
      </UnreadIndicatorProvider>
    </ThemeProvider>,
  );
}

const wall = () => screen.queryByText('Connect Telegram');
const shell = () => screen.queryByRole('link', { name: /subscriptions/i });

describe('auth gate — the Telegram login is a wall only for a Telegram-only install', () => {
  it('walls off a fresh install (no subscriptions at all)', async () => {
    stubFetch({ sources: [] });
    setup();

    expect(await screen.findByText('Connect Telegram')).toBeInTheDocument();
  });

  it('walls off an install whose only source is Telegram', async () => {
    stubFetch({ sources: TG_SOURCES });
    setup();

    expect(await screen.findByText('Connect Telegram')).toBeInTheDocument();
  });

  it('lets an HN-only install read, with no Telegram session', async () => {
    stubFetch({ sources: HN_SOURCES });
    setup();

    expect(await screen.findByRole('link', { name: /subscriptions/i })).toBeInTheDocument();
    expect(wall()).not.toBeInTheDocument();
  });

  it('shows neither the wall nor the app while the sources are still loading', async () => {
    stubFetch({ sources: 'pending' });
    setup();

    // the sources request proves tg-status already resolved and the gate consulted
    // it; without this anchor the spinner below is just the tg-status query loading
    await waitFor(() => expect(requested).toContain('/api/sources'));
    expect(screen.getByTestId('full-screen-spinner')).toBeInTheDocument();
    expect(wall()).not.toBeInTheDocument();
    expect(shell()).not.toBeInTheDocument();
  });

  it('keeps /authorize reachable without a Telegram session (device pairing)', async () => {
    stubFetch({ sources: [] });
    setup('/authorize');

    expect(await screen.findByRole('heading', { name: /authorize device/i })).toBeInTheDocument();
    expect(wall()).not.toBeInTheDocument();
  });

  it('offers a way back to the Telegram login once inside the app', async () => {
    stubFetch({ sources: HN_SOURCES });
    setup('/connect-telegram');

    expect(await screen.findByText('Connect Telegram')).toBeInTheDocument();
  });

  it('redirects /connect-telegram home once Telegram is connected', async () => {
    stubFetch({ tg: { status: 'authorized', phone: '+1' }, sources: HN_SOURCES });
    setup('/connect-telegram');

    expect(await screen.findByRole('link', { name: /subscriptions/i })).toBeInTheDocument();
    expect(wall()).not.toBeInTheDocument();
  });
});
