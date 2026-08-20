import { describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';

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
    content: '<p>the feed body</p>',
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

  it('shows the summary instead of the body, and says that it is one', () => {
    wrap(<RssCard item={makeItem({ summary: '这篇文章讲了三件事。' })} />);
    expect(screen.getByText('这篇文章讲了三件事。')).toBeInTheDocument();
    expect(screen.getByText('AI 摘要')).toBeInTheDocument();
    // the source body is the fallback, not a second paragraph under the summary
    expect(screen.queryByText('the feed body')).toBeNull();
  });

  it('renders the feed body when there is no summary', () => {
    wrap(<RssCard item={makeItem()} />);
    expect(screen.getByText('the feed body')).toBeInTheDocument();
    expect(screen.queryByText('AI 摘要')).toBeNull();
  });

  it('sanitizes the feed body', () => {
    const { container } = wrap(
      <RssCard item={makeItem({ content: '<p>safe</p><script>window.hacked = true</script>' })} />,
    );
    expect(container.querySelector('script')).toBeNull();
    expect(screen.getByText('safe')).toBeInTheDocument();
  });

  it('collapses a long body behind a more toggle', async () => {
    wrap(<RssCard item={makeItem({ content: `<p>${'word '.repeat(200)}</p>` })} />);
    await userEvent.setup().click(screen.getByRole('button', { name: 'more' }));
    expect(screen.getByRole('button', { name: 'less' })).toBeInTheDocument();
  });

  it('does not clamp a short body wrapped in a lot of markup', () => {
    // The clamp measures text, not tags: a two-sentence post inside nested markup
    // would otherwise grow a "more" button that reveals nothing.
    const wrapped = `<div><div><p><em><strong>short</strong></em></p></div></div>`.repeat(6);
    wrap(<RssCard item={makeItem({ content: wrapped })} />);
    expect(screen.queryByRole('button', { name: 'more' })).toBeNull();
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
