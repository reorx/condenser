import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

beforeEach(() => {
  vi.clearAllMocks();
});

vi.mock('@/lib/api', () => ({
  api: { rssEntry: vi.fn() },
  errorMessage: (_e: unknown, fallback: string) => fallback,
}));

import { api } from '@/lib/api';
import type { ItemAnnotation, RssEntry, TimelineItem } from '@/lib/types';

import { ItemDetailBody } from './ItemDetailBody';

const noopAnnotations = {
  annotations: [] as ItemAnnotation[],
  add: vi.fn(),
  remove: vi.fn(),
  setComment: vi.fn(),
};

function rssItem(over: Partial<RssEntry> = {}): TimelineItem {
  const rss: RssEntry = {
    id: 9,
    guid: null,
    feed_url: 'https://feed.example/atom',
    feed_title: 'Feed',
    title: 'Entry',
    link: 'https://feed.example/post',
    author: null,
    content_excerpt: 'the excerpt',
    content_truncated: true,
    summary: null,
    published_at: null,
    first_seen_at: '2026-08-20T10:00:00Z',
    sort_at: '2026-08-20T10:00:00Z',
    ...over,
  };
  return { source: 'rss', key: 'rss:9', datetime: '2026-08-20T10:00:00Z', is_read: true, is_saved: false, rss };
}

function wrap(item: TimelineItem, annotations = noopAnnotations) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ItemDetailBody item={item} annotations={annotations} />
    </QueryClientProvider>,
  );
}

describe('ItemDetailBody (RSS)', () => {
  it('fetches the article on mount and renders it sanitized', async () => {
    const full = rssItem();
    vi.mocked(api.rssEntry).mockResolvedValue({
      ...full,
      rss: { ...full.rss!, content: '<p>whole article</p><script>window.x = 1</script>' },
    });
    const { container } = wrap(rssItem());

    expect(await screen.findByText('whole article')).toBeInTheDocument();
    expect(api.rssEntry).toHaveBeenCalledWith(9);
    expect(container.querySelector('script')).toBeNull();
  });

  it('keeps the excerpt while loading and after a failed fetch', async () => {
    vi.mocked(api.rssEntry).mockRejectedValue(new Error('offline'));
    wrap(rssItem());
    // The excerpt keeps the section honest the whole way.
    expect(screen.getByText('the excerpt')).toBeInTheDocument();
    expect(await screen.findByText('正文加载失败')).toBeInTheDocument();
    expect(screen.getByText('the excerpt')).toBeInTheDocument();
  });

  it('uses an inline article from a saved snapshot without fetching', () => {
    wrap(rssItem({ content: '<p>snapshot body</p>' }));
    expect(screen.getByText('snapshot body')).toBeInTheDocument();
    expect(api.rssEntry).not.toHaveBeenCalled();
  });

  it('marks the AI summary as machine words above the article', async () => {
    wrap(rssItem({ summary: '三句话摘要。', content: '<p>body</p>' }));
    expect(screen.getByText('三句话摘要。')).toBeInTheDocument();
    expect(screen.getByText('AI 摘要')).toBeInTheDocument();
  });
});

describe('ItemDetailBody (other sources)', () => {
  it('renders a Telegram message text', () => {
    const item = {
      source: 'telegram',
      key: 'tg:1:2',
      datetime: '2026-08-20T10:00:00Z',
      is_read: true,
      is_saved: false,
      telegram: { id: 2, channel_id: 1, text: 'tg 正文' },
    } as unknown as TimelineItem;
    wrap(item);
    expect(screen.getByText('tg 正文')).toBeInTheDocument();
  });

  it('renders nothing for a body-less item with no annotations', () => {
    const item = {
      source: 'hn',
      key: 'hn:3',
      datetime: '2026-08-20T10:00:00Z',
      is_read: true,
      is_saved: false,
      hn: { id: 3, text: null },
    } as unknown as TimelineItem;
    const { container } = wrap(item);
    expect(container).toBeEmptyDOMElement();
  });

  it('still lists highlights as orphans when the body text is gone', () => {
    const item = {
      source: 'hn',
      key: 'hn:3',
      datetime: '2026-08-20T10:00:00Z',
      is_read: true,
      is_saved: false,
      hn: { id: 3, text: null },
    } as unknown as TimelineItem;
    const orphan: ItemAnnotation = {
      id: 1,
      quote: '曾经画过的话',
      prefix: '',
      suffix: '',
      block: null,
      comment: '当时的想法',
      created_at: null,
    };
    wrap(item, { ...noopAnnotations, annotations: [orphan] });
    expect(screen.getByText('失效的高亮（原文已变，引文保留）')).toBeInTheDocument();
    expect(screen.getByText('曾经画过的话')).toBeInTheDocument();
    expect(screen.getByText('当时的想法')).toBeInTheDocument();
  });
});
