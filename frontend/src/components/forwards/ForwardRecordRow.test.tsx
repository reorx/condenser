import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';

import { UnreadIndicatorProvider } from '@/lib/unreadIndicator';
import type { ForwardRecordEntry, HnStory, TimelineItem } from '@/lib/types';

import { ForwardRecordRow } from './ForwardRecordRow';

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return { ...actual, api: { ...actual.api, deleteForward: vi.fn().mockResolvedValue({ ok: true }) } };
});

function makeItem(): TimelineItem {
  const hn: HnStory = {
    id: 101,
    title: 'A story',
    url: 'https://example.com/post',
    domain: 'example.com',
    author: 'alice',
    type: 'story',
    text: null,
    submitted_at: '2026-08-20T10:00:00+00:00',
    first_seen_at: '2026-08-20T12:00:00+00:00',
    qualified_at: '2026-08-20T12:30:00+00:00',
    score: 120,
    comments_count: 45,
    day_rank: 3,
    peak_rank: 1,
    backfilled: false,
    preview: null,
    summary: null,
  };
  return { source: 'hn', key: 'hn:101', datetime: hn.first_seen_at, is_read: true, is_saved: false, hn };
}

function makeEntry(over: Partial<ForwardRecordEntry['record']> = {}, item: TimelineItem | null = makeItem()) {
  return {
    record: {
      id: 7,
      key: 'hn:101',
      source: 'hn' as const,
      comment: '值得一读',
      mode: 'quote' as const,
      target: '@mychannel',
      message_id: 999,
      link: 'https://t.me/mychannel/999',
      created_at: '2026-08-23T03:44:59Z',
      ...over,
    },
    item,
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

describe('ForwardRecordRow', () => {
  it('renders the comment above the item, not inside the card', () => {
    // The comment belongs to the *record*: the same item can be forwarded twice
    // with two different comments, so it cannot live on the card.
    wrap(<ForwardRecordRow entry={makeEntry()} />);
    expect(screen.getByText('值得一读')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'A story' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '在 Telegram 里打开这条消息' })).toHaveAttribute(
      'href',
      'https://t.me/mychannel/999',
    );
  });

  it('says so when there was no comment, rather than showing an empty line', () => {
    wrap(<ForwardRecordRow entry={makeEntry({ comment: null, mode: 'forward' })} />);
    expect(screen.getByText('原样转发，没有写评论')).toBeInTheDocument();
  });

  it('still renders the record when the item has no snapshot', () => {
    // A native TG forward reads no archive row, so it can publish a message we
    // never stored. The comment and the link are the record's real body anyway.
    wrap(<ForwardRecordRow entry={makeEntry({ comment: 'hi' }, null)} />);
    expect(screen.getByText('hi')).toBeInTheDocument();
    expect(screen.getByText('转发时没有留下条目快照，只保留了这条记录。')).toBeInTheDocument();
  });

  it('warns that deleting the record leaves the published message alone', async () => {
    wrap(<ForwardRecordRow entry={makeEntry()} />);
    await userEvent.click(screen.getByRole('button', { name: '删除这条记录' }));
    expect(screen.getByText(/频道里已经发出去的那条消息不会被撤回/)).toBeInTheDocument();
  });
});
