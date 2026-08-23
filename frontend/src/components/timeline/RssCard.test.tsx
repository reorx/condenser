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
import { UnreadIndicatorProvider } from '@/lib/unreadIndicator';
import type { RssEntry, TimelineItem } from '@/lib/types';

import { RssCard } from './RssCard';

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

/** What GET /api/rss/entries/{id} answers: the same envelope, plus the article. */
function articleItem(content: string): TimelineItem {
  const item = makeItem({ content_truncated: true });
  return { ...item, rss: { ...item.rss!, content } };
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

  it('does not offer "more" for a body that already fits', () => {
    // content_truncated is the server saying "this is the whole thing"; a toggle
    // over it would fetch an article to reveal nothing.
    wrap(<RssCard item={makeItem()} />);
    expect(screen.queryByRole('button', { name: 'more' })).toBeNull();
  });

  it('fetches the article on "more" and renders it sanitized', async () => {
    vi.mocked(api.rssEntry).mockResolvedValue(
      articleItem('<p>the whole article</p><script>window.hacked = true</script>'),
    );
    const { container } = wrap(<RssCard item={makeItem({ content_truncated: true })} />);
    // nothing is fetched until the reader asks: that is the point of the split
    expect(api.rssEntry).not.toHaveBeenCalled();

    await userEvent.setup().click(screen.getByRole('button', { name: 'more' }));

    expect(api.rssEntry).toHaveBeenCalledWith(77);
    expect(await screen.findByText('the whole article')).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
    expect(screen.getByRole('button', { name: 'less' })).toBeInTheDocument();
  });

  it('keeps showing the excerpt when the article cannot be fetched', async () => {
    // A failed expand degrades to what the card already had, rather than blanking
    // the body — the excerpt is still a true (if short) rendering of the entry.
    vi.mocked(api.rssEntry).mockRejectedValue(new Error('offline'));
    wrap(<RssCard item={makeItem({ content_truncated: true })} />);
    await userEvent.setup().click(screen.getByRole('button', { name: 'more' }));

    expect(await screen.findByText('正文加载失败')).toBeInTheDocument();
    expect(screen.getByText('the feed body')).toBeInTheDocument();
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
