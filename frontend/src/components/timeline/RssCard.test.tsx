import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';

vi.mock('@/lib/api', () => ({
  api: { rssEntry: vi.fn(), saveRecord: vi.fn(), deleteRecord: vi.fn() },
  errorMessage: (_e: unknown, fallback: string) => fallback,
}));

import { api } from '@/lib/api';
import { ItemDetailPaneProvider, useItemDetailPane } from '@/lib/itemDetailPane';
import { UnreadIndicatorProvider } from '@/lib/unreadIndicator';
import type { RssEntry, TimelineItem } from '@/lib/types';

import { RssCard } from './RssCard';

/** Reads the pane context so a test can see what a card opened. */
function OpenProbe() {
  const { open } = useItemDetailPane();
  return <div data-testid="open-key">{open?.key ?? ''}</div>;
}

function makeEntry(over: Partial<RssEntry> = {}): RssEntry {
  return {
    id: 77,
    guid: 'g1',
    feed_url: 'https://simonwillison.net/atom/everything/',
    feed_title: 'Simon Willison',
    title: 'An entry',
    link: 'https://simonwillison.net/2026/post/',
    author: 'Simon',
    content_excerpt: 'the feed body',
    content_truncated: false,
    summary: null,
    published_at: '2026-08-20T10:00:00Z',
    first_seen_at: '2026-08-20T10:05:00Z',
    sort_at: '2026-08-20T10:00:00Z',
    ...over,
  };
}

function makeItem(over: Partial<RssEntry> = {}, read = true): TimelineItem {
  const rss = makeEntry(over);
  return {
    source: 'rss',
    key: `rss:${rss.id}`,
    datetime: rss.sort_at ?? rss.first_seen_at,
    is_read: read,
    is_saved: false,
    rss,
  };
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <UnreadIndicatorProvider>{ui}</UnreadIndicatorProvider>
    </QueryClientProvider>,
  );
}

describe('RssCard', () => {
  it('marks the three read states: unread = sky dot, pending sync = green dot, read = no dot', () => {
    const unread = wrap(<RssCard item={makeItem({}, false)} />);
    expect(unread.container.querySelector('span.rounded-full')).toHaveClass('bg-sky-500');
    unread.unmount();

    const item = makeItem({}, false);
    const pending = wrap(<RssCard item={item} pendingKeys={new Set([item.key])} />);
    expect(pending.container.querySelector('span.rounded-full')).toHaveClass('bg-emerald-500');
    pending.unmount();

    const read = wrap(<RssCard item={makeItem()} />);
    const readDot = read.container.querySelector('span.rounded-full');
    expect(readDot).not.toHaveClass('bg-sky-500');
    expect(readDot).not.toHaveClass('bg-emerald-500');
  });

  it('names the feed and links the title to the article', () => {
    wrap(<RssCard item={makeItem()} />);
    expect(screen.getByText('Simon Willison')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'An entry' })).toHaveAttribute(
      'href',
      'https://simonwillison.net/2026/post/',
    );
  });

  it('falls back to the feed URL before a fetch has taught us the title', () => {
    // The URL is the key the reader typed, so it is unfamiliar at worst — never
    // meaningless. Scheme dropped: 100 sidebar rows are told apart by host.
    wrap(<RssCard item={makeItem({ feed_title: null })} />);
    expect(screen.getByText('simonwillison.net/atom/everything')).toBeInTheDocument();
  });

  it('shows the summary instead of the excerpt, and says that it is one', () => {
    wrap(<RssCard item={makeItem({ summary: '这篇文章讲了三件事。' })} />);
    expect(screen.getByText('这篇文章讲了三件事。')).toBeInTheDocument();
    expect(screen.getByText('AI 摘要')).toBeInTheDocument();
    // the excerpt is the fallback, not a second paragraph under the summary
    expect(screen.queryByText('the feed body')).toBeNull();
  });

  it('renders the excerpt as plain text when there is no summary', () => {
    // The list payload carries no HTML any more, so there is nothing to sanitize
    // here — what arrives is prose the backend already stripped.
    wrap(<RssCard item={makeItem()} />);
    expect(screen.getByText('the feed body')).toBeInTheDocument();
    expect(screen.queryByText('AI 摘要')).toBeNull();
  });

  it('does not offer 查看全文 for a body that already fits', () => {
    // content_truncated is the server saying "this is the whole thing"; an entry
    // over it would open a pane to reveal nothing new.
    wrap(<RssCard item={makeItem()} />);
    expect(screen.queryByRole('button', { name: '查看全文' })).toBeNull();
  });

  it('opens the detail pane on 查看全文 instead of expanding in place', async () => {
    // The article renders (and gets fetched) in the detail pane only — the iOS
    // arrangement. The card itself never fetches anything.
    wrap(
      <ItemDetailPaneProvider>
        <RssCard item={makeItem({ content_truncated: true })} />
        <OpenProbe />
      </ItemDetailPaneProvider>,
    );
    await userEvent.setup().click(screen.getByRole('button', { name: '查看全文' }));

    expect(screen.getByTestId('open-key')).toHaveTextContent('rss:77');
    expect(api.rssEntry).not.toHaveBeenCalled();
  });

  it('offers 查看全文 under a summary — the pane is the only route to the source text', () => {
    // A summary replaces the excerpt entirely, so without this button an entry
    // with one has no path from the card to what the feed actually said.
    wrap(<RssCard item={makeItem({ summary: '摘要。' })} />);
    expect(screen.getByRole('button', { name: '查看全文' })).toBeInTheDocument();
  });

  it('renders a plain title when the entry has no link', () => {
    wrap(<RssCard item={makeItem({ link: null })} />);
    expect(screen.queryByRole('link', { name: 'An entry' })).toBeNull();
    expect(screen.getByText('An entry')).toBeInTheDocument();
  });

  it('opens entry details from the time', () => {
    wrap(<RssCard item={makeItem()} />);
    expect(screen.getByRole('button', { name: 'Open entry details' })).toBeInTheDocument();
  });
});
