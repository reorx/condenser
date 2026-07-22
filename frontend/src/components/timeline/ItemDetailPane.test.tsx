import { useEffect } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { TimelineItem, TimelinePage } from '@/lib/types';

vi.mock('@/lib/api', () => ({
  api: {
    messagePreviews: vi.fn().mockResolvedValue([]),
    urlPreview: vi.fn().mockResolvedValue(null),
    messageStats: vi.fn().mockResolvedValue({ views: null, forwards: null, reactions: [] }),
    listSubscriptions: vi
      .fn()
      .mockResolvedValue([
        { channel_id: 1, enabled: true, backfill_done: true, title: 'Tech', username: 'tech', unread: 0 },
      ]),
    getAppMeta: vi.fn().mockResolvedValue({ schema_version: 6, backfill_days: 7, forward_channel: null }),
    hideItem: vi.fn().mockResolvedValue({ ok: true }),
    unhideItem: vi.fn().mockResolvedValue({ ok: true }),
  },
  errorMessage: (_e: unknown, fallback: string) => fallback,
  channelAvatarUrl: (id: number) => `/api/channels/${id}/avatar`,
  mediaUrl: () => '/media',
  previewImageUrl: (u: string) => u,
}));
vi.mock('sonner', () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

import { toast } from 'sonner';
import { api } from '@/lib/api';
import { ItemDetailPaneProvider, useItemDetailPane } from '@/lib/itemDetailPane';
import { ItemDetailPane } from './ItemDetailPane';

const tgItem: TimelineItem = {
  source: 'telegram',
  key: 'tg:1:10',
  datetime: '2026-06-01T12:01:00Z',
  is_read: false,
  is_saved: false,
  telegram: {
    id: 10,
    channel_id: 1,
    date: '2026-06-01T12:01:00+00:00',
    is_edited: false,
    edit_date: null,
    sender_id: null,
    sender_name: null,
    text: 'hello world',
    is_album: false,
    grouped_id: null,
    media_items: [],
    webpage: null,
    is_forwarded: false,
    forward_info: null,
    views: null,
    forwards_count: null,
    replies_count: null,
    raw_message_ids: [10],
  },
};

const hnItem: TimelineItem = {
  source: 'hn',
  key: 'hn:101',
  datetime: '2026-06-01T12:05:00Z',
  is_read: false,
  is_saved: false,
  hn: {
    id: 101,
    title: 'A story',
    url: 'https://ex.com/101',
    domain: 'ex.com',
    author: 'alice',
    type: 'story',
    text: null,
    submitted_at: '2026-06-01T11:00:00Z',
    first_seen_at: '2026-06-01T12:05:00Z',
    score: 42,
    comments_count: 7,
    day_rank: 1,
    peak_rank: 3,
    backfilled: false,
    preview: {
      url: 'https://ex.com/101',
      title: 'Og title',
      description: null,
      image: null,
      site_name: null,
      source: 'fetched',
      tg_image_message_id: null,
      error: null,
    },
  },
};

function Opener({ item }: { item: TimelineItem }) {
  const { openPane } = useItemDetailPane();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => openPane(item), []);
  return null;
}

function renderPane(item: TimelineItem) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const page: TimelinePage = { items: [tgItem, hnItem], next_cursor: null, end_cursor: null, head_cursor: null };
  qc.setQueryData(['timeline', 'all'], { pages: [page], pageParams: [null] });
  render(
    <QueryClientProvider client={qc}>
      <ItemDetailPaneProvider>
        <Opener item={item} />
        <ItemDetailPane />
      </ItemDetailPaneProvider>
    </QueryClientProvider>,
  );
  return qc;
}

describe('ItemDetailPane', () => {
  beforeEach(() => {
    vi.mocked(api.hideItem).mockClear();
    vi.mocked(toast).mockClear();
  });

  it('renders the 条目详情 title and the TG item info', async () => {
    renderPane(tgItem);
    expect(screen.getByText('条目详情')).toBeInTheDocument();
    // channel resolved from subscriptions
    expect(await screen.findByText('Tech')).toBeInTheDocument();
    // full publish time is shown
    expect(screen.getByText(/Jun 1, 2026/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '隐藏' })).toBeInTheDocument();
  });

  it('hide posts the key, drops the item from timeline caches, closes, and offers undo', async () => {
    const qc = renderPane(tgItem);
    await userEvent.setup().click(screen.getByRole('button', { name: '隐藏' }));

    await waitFor(() => expect(api.hideItem).toHaveBeenCalledWith('tg:1:10'));
    const cached = qc.getQueryData<{ pages: TimelinePage[] }>(['timeline', 'all'])!;
    expect(cached.pages[0].items.map((it) => it.key)).toEqual(['hn:101']);
    await waitFor(() => expect(screen.queryByText('条目详情')).not.toBeInTheDocument());
    expect(toast).toHaveBeenCalledWith('已隐藏', expect.objectContaining({ action: expect.anything() }));
  });

  it('renders HN story details and hides by story key', async () => {
    renderPane(hnItem);
    expect(screen.getByText('alice')).toBeInTheDocument();
    expect(screen.getByText(/42/)).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: '隐藏' }));
    await waitFor(() => expect(api.hideItem).toHaveBeenCalledWith('hn:101'));
  });
});
