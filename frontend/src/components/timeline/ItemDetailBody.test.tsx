import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

beforeEach(() => {
  vi.clearAllMocks();
});

vi.mock('@/lib/api', () => ({
  api: { rssEntry: vi.fn(), xTweet: vi.fn() },
  errorMessage: (_e: unknown, fallback: string) => fallback,
  previewImageUrl: (url: string) => `/api/preview/image?url=${encodeURIComponent(url)}`,
}));

import { api } from '@/lib/api';
import type { ItemAnnotation, RssEntry, TimelineItem, XArticle, XTweet } from '@/lib/types';

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

function xArticleItem(article: XArticle): TimelineItem {
  const x = {
    id: '2099707280845332534',
    author_handle: 'xiaoerzhan',
    author_name: 'Xiaoer',
    // bird sets a long-form post's `text` to its article title
    text: article.title,
    created_at: '2026-09-15T03:50:01Z',
    first_seen_at: '2026-09-15T04:00:00Z',
    media: null,
    metrics: null,
    quote: null,
    rt_of_handle: null,
    reply_to_id: null,
    urls: null,
    article,
    feed: 'following',
    feed_kind: 'following',
    verdict: null,
    verdict_meta: null,
  } as XTweet;
  return { source: 'x', key: `x:${x.id}`, datetime: x.created_at!, is_read: true, is_saved: false, x };
}

const ARTICLE = { title: '如何接上全球收款', previewText: '我做了个 Mac 工具。' };
const BODY_HTML =
  '<figure><img src="https://pbs.twimg.com/media/C.jpg" width="1600" height="900" alt="" /></figure>' +
  '<h2>第一件事</h2><p>全文第一段。</p><script>window.x = 1</script>';

describe('ItemDetailBody (X article)', () => {
  it('fetches the body on open and renders it sanitized, with images through the proxy', async () => {
    const list = xArticleItem({ ...ARTICLE, has_content: true });
    vi.mocked(api.xTweet).mockResolvedValue({
      ...list,
      x: { ...list.x!, article: { ...ARTICLE, has_content: true, content_html: BODY_HTML } },
    });
    const { container } = wrap(list);

    expect(await screen.findByText('全文第一段。')).toBeInTheDocument();
    expect(api.xTweet).toHaveBeenCalledWith('2099707280845332534');
    expect(screen.getByRole('heading', { name: '第一件事' })).toBeInTheDocument();
    expect(screen.getByText('如何接上全球收款')).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
    const img = container.querySelector('img')!;
    expect(img.getAttribute('src')).toBe(
      `/api/preview/image?url=${encodeURIComponent('https://pbs.twimg.com/media/C.jpg')}`,
    );
    // the preview was a stand-in for the body, not part of it
    expect(screen.queryByText('我做了个 Mac 工具。')).toBeNull();
  });

  it('keeps the preview while loading and after a failed fetch, without a toast', async () => {
    vi.mocked(api.xTweet).mockRejectedValue(new Error('offline'));
    wrap(xArticleItem({ ...ARTICLE, has_content: true }));
    expect(screen.getByText('我做了个 Mac 工具。')).toBeInTheDocument();
    expect(screen.getByText('正在加载全文…')).toBeInTheDocument();
    expect(await screen.findByText('正文加载失败')).toBeInTheDocument();
    expect(screen.getByText('我做了个 Mac 工具。')).toBeInTheDocument();
  });

  it('uses the body a saved snapshot carries without fetching', () => {
    wrap(xArticleItem({ ...ARTICLE, has_content: true, content_html: '<p>snapshot body</p>' }));
    expect(screen.getByText('snapshot body')).toBeInTheDocument();
    expect(api.xTweet).not.toHaveBeenCalled();
  });

  it('with no body on the server, keeps the preview and says the body was not fetched', async () => {
    const list = xArticleItem({ ...ARTICLE, has_content: false });
    vi.mocked(api.xTweet).mockResolvedValue({
      ...list,
      x: { ...list.x!, article: { ...ARTICLE, has_content: false, content_html: null } },
    });
    wrap(list);
    expect(screen.getByText('我做了个 Mac 工具。')).toBeInTheDocument();
    expect(screen.queryByText('正在加载全文…')).toBeNull();
    // it still asks — a failed read is retried by the next probe round
    await vi.waitFor(() => expect(api.xTweet).toHaveBeenCalled());
    expect(await screen.findByText('未获取到 article 正文')).toBeInTheDocument();
    // not a request error: that one has its own line
    expect(screen.queryByText('正文加载失败')).toBeNull();
    expect(screen.getByText('我做了个 Mac 工具。')).toBeInTheDocument();
  });

  it('does not claim the body is missing before the answer is in', () => {
    vi.mocked(api.xTweet).mockReturnValue(new Promise(() => {}));
    wrap(xArticleItem({ ...ARTICLE, has_content: false }));
    expect(screen.queryByText('未获取到 article 正文')).toBeNull();
  });

  it('picks up a body that arrived after the list was loaded', async () => {
    const list = xArticleItem({ ...ARTICLE, has_content: false });
    vi.mocked(api.xTweet).mockResolvedValue({
      ...list,
      x: { ...list.x!, article: { ...ARTICLE, has_content: true, content_html: '<p>late body</p>' } },
    });
    wrap(list);
    expect(await screen.findByText('late body')).toBeInTheDocument();
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
