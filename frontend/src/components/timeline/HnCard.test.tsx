import { afterEach, describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';

import { UnreadIndicatorProvider } from '@/lib/unreadIndicator';
import { BRIDGE_NS, PROTOCOL_VERSION, listenToBridge, resetForTests } from '@/lib/vibeReader';
import type { HnStory, LinkPreview, TimelineItem } from '@/lib/types';

import { HnCard } from './HnCard';

function makeStory(over: Partial<HnStory> = {}): HnStory {
  return {
    id: 101,
    title: 'A story',
    url: 'https://example.com/post',
    domain: 'example.com',
    author: 'alice',
    type: 'story',
    text: null,
    submitted_at: '2026-07-19T10:00:00+00:00',
    first_seen_at: '2026-07-19T12:00:00+00:00',
    qualified_at: '2026-07-19T12:30:00+00:00',
    score: 120,
    comments_count: 45,
    day_rank: 3,
    peak_rank: 1,
    backfilled: false,
    preview: null,
    summary: null,
    ...over,
  };
}

function makePreview(over: Partial<LinkPreview> = {}): LinkPreview {
  return {
    url: 'https://example.com/post',
    title: 'Og title',
    description: 'Og description',
    image: null,
    site_name: 'Example Site',
    source: 'fetched',
    tg_image_message_id: null,
    error: null,
    ...over,
  };
}

function makeItem(over: Partial<HnStory> = {}, read = true): TimelineItem {
  const hn = makeStory(over);
  return {
    source: 'hn',
    key: `hn:${hn.id}`,
    datetime: hn.first_seen_at,
    is_read: read,
    is_saved: false,
    hn,
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

describe('HnCard', () => {
  it('marks the three read states: unread = sky dot, pending sync = green dot, read = no dot', () => {
    const unread = wrap(<HnCard item={makeItem({}, false)} />);
    expect(unread.container.querySelector('span.rounded-full')).toHaveClass('bg-sky-500');
    unread.unmount();

    const item = makeItem({}, false);
    const pending = wrap(<HnCard item={item} pendingKeys={new Set([item.key])} />);
    const pendingDot = pending.container.querySelector('span.rounded-full');
    expect(pendingDot).toHaveClass('bg-emerald-500');
    expect(pendingDot).not.toHaveClass('bg-sky-500');
    pending.unmount();

    const read = wrap(<HnCard item={makeItem()} />);
    const readDot = read.container.querySelector('span.rounded-full');
    expect(readDot).not.toHaveClass('bg-sky-500');
    expect(readDot).not.toHaveClass('bg-emerald-500');
  });

  it('links the title to the story URL and shows meta with the day rank', () => {
    wrap(<HnCard item={makeItem()} />);
    const title = screen.getByRole('link', { name: 'A story' });
    expect(title).toHaveAttribute('href', 'https://example.com/post');
    expect(screen.getByText('#3')).toBeInTheDocument();
    expect(screen.getByText('120 points')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '45 comments' })).toHaveAttribute(
      'href',
      'https://news.ycombinator.com/item?id=101',
    );
  });

  it('marks job posts and mutes their meta', () => {
    wrap(<HnCard item={makeItem({ type: 'job', comments_count: 0, score: 1 })} />);
    expect(screen.getByText('Job')).toBeInTheDocument();
  });

  it('points a self-post title at the comments page and renders its text', () => {
    wrap(<HnCard item={makeItem({ url: null, domain: null, text: '<p>Ask HN <i>body</i></p>' })} />);
    expect(screen.getByRole('link', { name: 'A story' })).toHaveAttribute(
      'href',
      'https://news.ycombinator.com/item?id=101',
    );
    expect(screen.getByText('body')).toBeInTheDocument();
  });

  it('collapses long self-post text behind a more toggle', async () => {
    const long = `<p>${'word '.repeat(200)}</p>`;
    wrap(<HnCard item={makeItem({ url: null, text: long })} />);
    const toggle = screen.getByRole('button', { name: 'more' });
    await userEvent.setup().click(toggle);
    expect(screen.getByRole('button', { name: 'less' })).toBeInTheDocument();
  });

  it('sanitizes self-post HTML', () => {
    const { container } = wrap(
      <HnCard item={makeItem({ url: null, text: '<p>safe</p><script>window.hacked = true</script>' })} />,
    );
    expect(container.querySelector('script')).toBeNull();
    expect(screen.getByText('safe')).toBeInTheDocument();
  });

  it('shows the submitted time and opens story details from it', () => {
    wrap(<HnCard item={makeItem()} />);
    expect(screen.getByRole('button', { name: 'Open story details' })).toBeInTheDocument();
  });

  it('embeds the prefetched link preview card', () => {
    wrap(<HnCard item={makeItem({ preview: makePreview() })} />);
    expect(screen.getByText('Og title')).toBeInTheDocument();
    expect(screen.getByText('Og description')).toBeInTheDocument();
    expect(screen.getByText('Example Site')).toBeInTheDocument();
  });

  it('renders no preview card when the preview is missing', () => {
    wrap(<HnCard item={makeItem()} />);
    expect(screen.queryByText('Og title')).toBeNull();
  });

  it('renders no preview card when the preview has no content', () => {
    wrap(<HnCard item={makeItem({ preview: makePreview({ title: null, description: null, image: null }) })} />);
    expect(screen.queryByText('Example Site')).toBeNull();
  });

  it('shows the AI summary under the title, and says that it is one', () => {
    wrap(<HnCard item={makeItem({ summary: '这篇文章讲了三件事。讨论主要在争论第二件。' })} />);
    expect(screen.getByText('这篇文章讲了三件事。讨论主要在争论第二件。')).toBeInTheDocument();
    expect(screen.getByText('AI 摘要')).toBeInTheDocument();
    // Under the title, above the meta line: the reader decides from it whether to open.
    const title = screen.getByRole('link', { name: 'A story' });
    const summary = screen.getByText('这篇文章讲了三件事。讨论主要在争论第二件。');
    const meta = screen.getByText('120 points');
    expect(title.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(summary.compareDocumentPosition(meta) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows no summary block without one', () => {
    wrap(<HnCard item={makeItem()} />);
    expect(screen.queryByText('AI 摘要')).toBeNull();
  });

  it('drops the preview description under a summary — same information twice', () => {
    wrap(<HnCard item={makeItem({ summary: '摘要。', preview: makePreview() })} />);
    expect(screen.getByText('Og title')).toBeInTheDocument();
    expect(screen.getByText('Example Site')).toBeInTheDocument();
    expect(screen.queryByText('Og description')).toBeNull();
  });

  it('renders no preview card under a summary when the description was all it had', () => {
    wrap(<HnCard item={makeItem({ summary: '摘要。', preview: makePreview({ title: null, image: null }) })} />);
    expect(screen.queryByText('Example Site')).toBeNull();
    expect(screen.queryByText('Og description')).toBeNull();
  });

  // Plan 2026-09-02 §2.3: the Vibe Reader delegate (AppShell) reads the story off
  // the anchor, so the extension can open the thread without an Algolia search.
  it('tags the title and comments links with the story for the Vibe Reader delegate', () => {
    wrap(<HnCard item={makeItem()} />);
    for (const link of [screen.getByRole('link', { name: 'A story' }), screen.getByRole('link', { name: '45 comments' })]) {
      expect(link).toHaveAttribute('data-vr-hn-id', '101');
      expect(link).toHaveAttribute('data-vr-title', 'A story');
      expect(link).toHaveAttribute('data-vr-hn-score', '120');
      expect(link).toHaveAttribute('data-vr-hn-comments', '45');
      expect(link).toHaveAttribute('data-vr-hn-submitted', '2026-07-19T10:00:00+00:00');
    }
  });

  // Plan 2026-09-02 §5 (Phase D): the extension reports per-URL progress back and
  // the card's time line shows it — for the article and the thread alike.
  describe('Vibe Reader status badge', () => {
    afterEach(() => resetForTests());

    function fromBridge(msg: Record<string, unknown>) {
      act(() => {
        window.dispatchEvent(
          new MessageEvent('message', {
            data: { ns: BRIDGE_NS, v: PROTOCOL_VERSION, ...msg },
            origin: window.location.origin,
            source: window,
          }),
        );
      });
    }

    it('lights up on the time line for the story url and for the comments url', () => {
      const off = listenToBridge();
      try {
        wrap(<HnCard item={makeItem()} />);
        fromBridge({ type: 'vibe-reader:hello', linked: true });
        expect(screen.queryByLabelText(/^Vibe Reader/)).toBeNull();

        fromBridge({ type: 'vibe-reader:status', url: 'https://example.com/post', state: 'generating' });
        expect(screen.getByLabelText('Vibe Reader 正在生成')).toBeInTheDocument();

        fromBridge({ type: 'vibe-reader:status', url: 'https://news.ycombinator.com/item?id=101', state: 'done' });
        expect(screen.getByLabelText('Vibe Reader 已就绪')).toBeInTheDocument();
      } finally {
        off();
      }
    });
  });
});
