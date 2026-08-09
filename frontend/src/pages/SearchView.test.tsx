import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ItemDetailPaneProvider } from '@/lib/itemDetailPane';
import { SearchView } from '@/pages/SearchView';

const searchCalls: URLSearchParams[] = [];

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
}

/** The two endpoints the page reads: the search itself, and the source tree the
 *  scope menu is built from. */
function stubFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    if (url.pathname === '/api/search') {
      searchCalls.push(url.searchParams);
      return json({ items: [], total: 0, has_more: false });
    }
    if (url.pathname === '/api/sources') {
      return json([
        { source: 'telegram', subscriptions: [{ channel_id: 42, name: 'Alpha', enabled: true, unread: 0 }] },
      ]);
    }
    return json([]);
  });
}

/** Echoes the query string, so "the URL is the state" is testable rather than asserted. */
function LocationProbe() {
  return <div data-testid="location">{useLocation().search}</div>;
}

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/search']}>
        <ItemDetailPaneProvider>
          <Routes>
            <Route path="/search" element={<SearchView />} />
          </Routes>
        </ItemDetailPaneProvider>
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { user: userEvent.setup() };
}

const box = () => screen.getByRole('textbox', { name: /search/i });
const location = () => screen.getByTestId('location').textContent ?? '';
const lastCall = () => searchCalls.at(-1);

/** Type a query and wait for the debounce to commit it. */
async function search(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(box(), text);
  await waitFor(() => expect(searchCalls).toHaveLength(1));
}

beforeEach(() => {
  searchCalls.length = 0;
  vi.stubGlobal('fetch', stubFetch());
});

afterEach(() => vi.unstubAllGlobals());

describe('SearchView', () => {
  it('asks nothing until something is typed, and prompts instead of saying "no results"', async () => {
    setup();
    expect(screen.getByText(/search across telegram/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/no matches/i)).not.toBeInTheDocument());
    expect(searchCalls).toHaveLength(0);
  });

  it('debounces typing into a single committed query in the URL', async () => {
    const { user } = setup();
    await search(user, '模型');

    // one request for the whole word, not one per keystroke
    expect(searchCalls).toHaveLength(1);
    expect(searchCalls[0].get('q')).toBe('模型');
    expect(location()).toContain(`q=${encodeURIComponent('模型')}`);
  });

  it('puts the status and sort filters in the URL and in the request', async () => {
    const { user } = setup();
    await search(user, 'rust');

    await user.click(screen.getByRole('button', { name: 'Unread' }));
    await waitFor(() => expect(lastCall()?.get('status')).toBe('unread'));

    await user.click(screen.getByRole('button', { name: 'Newest' }));
    await waitFor(() => expect(lastCall()?.get('sort')).toBe('relevance'));

    expect(location()).toContain('status=unread');
    expect(location()).toContain('sort=relevance');
  });

  it('omits the defaults from the URL rather than spelling them out', async () => {
    const { user } = setup();
    await search(user, 'rust');

    await user.click(screen.getByRole('button', { name: 'Unread' }));
    await user.click(screen.getByRole('button', { name: 'All' }));
    await user.click(screen.getByRole('button', { name: 'Newest' }));
    await user.click(screen.getByRole('button', { name: 'Relevance' }));

    await waitFor(() => {
      expect(location()).not.toContain('status=');
      expect(location()).not.toContain('sort=');
    });
  });

  it('narrows the scope to one subscription and sends it as that source uses it', async () => {
    const { user } = setup();
    await search(user, 'rust');

    await user.click(screen.getByRole('button', { name: /all sources/i }));
    await user.click(await screen.findByRole('menuitem', { name: /alpha/i }));

    await waitFor(() => {
      expect(lastCall()?.get('source')).toBe('telegram');
      expect(lastCall()?.get('channel_id')).toBe('42');
    });
  });

  it('clears the box back to the prompt', async () => {
    const { user } = setup();
    await search(user, 'rust');

    await user.click(screen.getByRole('button', { name: /clear search/i }));
    await waitFor(() => expect(screen.getByText(/search across telegram/i)).toBeInTheDocument());
  });
});
