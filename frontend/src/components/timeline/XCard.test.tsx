import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return { ...actual, api: { ...actual.api, xTweet: vi.fn() } };
});

import { api } from '@/lib/api';
import { ItemDetailPaneProvider, useItemDetailPane } from '@/lib/itemDetailPane';
import { UnreadIndicatorProvider } from '@/lib/unreadIndicator';
import type { TimelineItem, XTweet } from '@/lib/types';

import { XCard } from './XCard';

function makeTweet(over: Partial<XTweet> = {}): XTweet {
  return {
    id: '2080526422410752155',
    author_id: '1511658122149961730',
    author_handle: 'NiallxYoung',
    author_name: 'Niall Young',
    text: 'a tweet about things',
    created_at: '2026-07-24T05:32:08Z',
    first_seen_at: '2026-07-24T09:00:00Z',
    media: null,
    metrics: { reply_count: 16, retweet_count: 5, like_count: 1820 },
    quote: null,
    rt_of_handle: null,
    reply_to_id: null,
    article: null,
    feed: 'foryou',
    feed_kind: 'home',
    verdict: null,
    verdict_meta: null,
    ...over,
  };
}

function makeItem(over: Partial<XTweet> = {}, read = true): TimelineItem {
  const x = makeTweet(over);
  return {
    source: 'x',
    key: `x:${x.id}`,
    datetime: x.feed_kind === 'home' ? x.first_seen_at : (x.created_at ?? x.first_seen_at),
    is_read: read,
    is_saved: false,
    x,
  };
}

/** Reads the pane context so a test can see what a card opened. */
function OpenProbe() {
  const { open } = useItemDetailPane();
  return <div data-testid="open-key">{open?.key ?? ''}</div>;
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <UnreadIndicatorProvider>{ui}</UnreadIndicatorProvider>
    </QueryClientProvider>,
  );
}

describe('XCard', () => {
  it('shows the author, the tweet text and compacted engagement numbers', () => {
    wrap(<XCard item={makeItem()} />);

    expect(screen.getByText('Niall Young')).toBeInTheDocument();
    expect(screen.getByText('@NiallxYoung')).toBeInTheDocument();
    expect(screen.getByText('a tweet about things')).toBeInTheDocument();
    expect(screen.getByText('1.8k')).toBeInTheDocument();
  });

  it("explains For You's sighting-based position in the time tooltip", () => {
    wrap(<XCard item={makeItem()} />);
    expect(screen.getByLabelText('Open tweet details')).toHaveAttribute('title', expect.stringContaining('seen'));
  });

  it('a followed account keeps the plain publish time', () => {
    wrap(<XCard item={makeItem({ feed: 'novoreorx', feed_kind: 'user' })} />);
    expect(screen.getByLabelText('Open tweet details')).not.toHaveAttribute('title', expect.stringContaining('seen'));
  });

  it('renders a retweet as a caption and drops the RT prefix from the body', () => {
    wrap(<XCard item={makeItem({ rt_of_handle: 'colebemis', text: 'RT @colebemis: the original words' })} />);

    expect(screen.getByText('@colebemis')).toBeInTheDocument();
    expect(screen.getByText('the original words')).toBeInTheDocument();
    expect(screen.queryByText(/RT @colebemis:/)).not.toBeInTheDocument();
  });

  it('renders an embedded quote with its own author', () => {
    wrap(
      <XCard
        item={makeItem({
          quote: {
            id: '2080267011654144075',
            author_handle: 'MaxForAI',
            author_name: 'Max For AI',
            text: 'quoted words',
            created_at: '2026-07-23T12:21:19Z',
            media: null,
            metrics: null,
          },
        })}
      />,
    );

    expect(screen.getByText('Max For AI')).toBeInTheDocument();
    expect(screen.getByText('quoted words')).toBeInTheDocument();
  });

  it('offers up/down feedback on every tweet, highlighting the chosen side', () => {
    const item = makeItem();
    wrap(<XCard item={{ ...item, feedback: 'up' }} />);

    expect(screen.getByLabelText('More like this')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Less like this')).toHaveAttribute('aria-pressed', 'false');
  });

  it('keeps the feedback buttons when bird sent no metrics', () => {
    wrap(<XCard item={makeItem({ metrics: null })} />);

    expect(screen.getByLabelText('More like this')).toBeInTheDocument();
  });

  it('marks the three read states: unread = sky dot, pending sync = green dot, read = no dot', () => {
    const unread = wrap(<XCard item={makeItem({}, false)} />);
    expect(unread.container.querySelector('span.rounded-full')).toHaveClass('bg-sky-500');
    unread.unmount();

    const item = makeItem({}, false);
    const pending = wrap(<XCard item={item} pendingKeys={new Set([item.key])} />);
    const pendingDot = pending.container.querySelector('span.rounded-full');
    expect(pendingDot).toHaveClass('bg-emerald-500');
    expect(pendingDot).not.toHaveClass('bg-sky-500');
    pending.unmount();

    const read = wrap(<XCard item={makeItem()} />);
    const readDot = read.container.querySelector('span.rounded-full');
    expect(readDot).not.toHaveClass('bg-sky-500');
    expect(readDot).not.toHaveClass('bg-emerald-500');
  });

  it('renders an X article as a titled card (bird only exposes title + preview text)', () => {
    wrap(
      <XCard
        item={makeItem({
          // bird sets a long-form post's `text` to its article title
          text: 'Superrepos',
          article: { title: 'Superrepos', previewText: 'Different workloads…' },
        })}
      />,
    );

    // the title appears once — inside the article card, not also as the body text
    expect(screen.getByText('Superrepos')).toBeInTheDocument();
    expect(screen.getByText('Different workloads…')).toBeInTheDocument();
    // a payload without the flag (pre-v21) claims nothing either way
    expect(screen.queryByRole('button', { name: '查看全文' })).toBeNull();
    expect(screen.queryByText('未获取到正文')).toBeNull();
  });

  it('says 未获取到正文 when the server has no body, as plain text rather than a button', () => {
    // The probe reads the body with the tweet (plan 2026-09-17), so `has_content:
    // false` is no longer "on its way" but "the probe did not get it" — which the
    // reader should see while scanning, not discover by opening the pane.
    wrap(
      <XCard
        item={makeItem({
          text: 'Superrepos',
          article: { title: 'Superrepos', previewText: 'Different workloads…', has_content: false },
        })}
      />,
    );

    expect(screen.getByText('未获取到正文')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '未获取到正文' })).toBeNull();
    expect(screen.queryByRole('button', { name: '查看全文' })).toBeNull();
  });

  it('says nothing either way when the flag is null (a snapshot saved before the body existed)', () => {
    wrap(
      <XCard
        item={makeItem({
          text: 'Superrepos',
          article: { title: 'Superrepos', previewText: 'Different workloads…', has_content: null },
        })}
      />,
    );
    expect(screen.queryByText('未获取到正文')).toBeNull();
    expect(screen.queryByRole('button', { name: '查看全文' })).toBeNull();
  });

  it('offers 查看全文 once the body exists, and opens the pane instead of expanding', async () => {
    // The body renders in the detail pane only — one rendering to highlight on,
    // RssCard's arrangement. The card itself never fetches it.
    wrap(
      <ItemDetailPaneProvider>
        <XCard
          item={makeItem({
            text: 'Superrepos',
            article: { title: 'Superrepos', previewText: 'Different workloads…', has_content: true },
          })}
        />
        <OpenProbe />
      </ItemDetailPaneProvider>,
    );
    await userEvent.setup().click(screen.getByRole('button', { name: '查看全文' }));

    expect(screen.getByTestId('open-key')).toHaveTextContent('x:2080526422410752155');
    expect(api.xTweet).not.toHaveBeenCalled();
  });
});
