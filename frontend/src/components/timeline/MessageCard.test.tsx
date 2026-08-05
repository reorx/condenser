import { beforeEach, describe, expect, it } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactNode } from 'react';

import { UnreadIndicatorProvider } from '@/lib/unreadIndicator';
import type { DisplayMessage, TimelineItem } from '@/lib/types';

import { MessageCard } from './MessageCard';

function makeMessage(over: Partial<DisplayMessage> = {}): DisplayMessage {
  return {
    id: 10,
    channel_id: 1,
    grouped_id: null,
    date: '2026-08-05T08:00:00+00:00',
    edit_date: null,
    text: 'hello there',
    has_media: false,
    media_type: null,
    media_items: [],
    webpage: null,
    is_forwarded: false,
    forward_info: null,
    post_author: null,
    ...over,
  } as DisplayMessage;
}

function makeItem(read = true): TimelineItem {
  const msg = makeMessage();
  return {
    source: 'telegram',
    key: `tg:${msg.channel_id}:${msg.id}`,
    datetime: msg.date,
    is_read: read,
    is_saved: false,
    telegram: msg,
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

describe('MessageCard read-state indicator', () => {
  beforeEach(() => {
    localStorage.removeItem('condenser-unread-indicator');
  });

  it('marks the three read states: unread = sky dot, pending sync = green dot, read = no dot', () => {
    const unread = wrap(<MessageCard item={makeItem(false)} channelLabel="Chan" />);
    expect(unread.container.querySelector('span.rounded-full')).toHaveClass('bg-sky-500');
    unread.unmount();

    const item = makeItem(false);
    const pending = wrap(<MessageCard item={item} channelLabel="Chan" pendingKeys={new Set([item.key])} />);
    const pendingDot = pending.container.querySelector('span.rounded-full');
    expect(pendingDot).toHaveClass('bg-emerald-500');
    expect(pendingDot).not.toHaveClass('bg-sky-500');
    pending.unmount();

    const read = wrap(<MessageCard item={makeItem()} channelLabel="Chan" />);
    const readDot = read.container.querySelector('span.rounded-full');
    expect(readDot).not.toHaveClass('bg-sky-500');
    expect(readDot).not.toHaveClass('bg-emerald-500');
  });

  it('divider mode mirrors the same three states on the bottom border', () => {
    localStorage.setItem('condenser-unread-indicator', 'divider');

    const unread = wrap(<MessageCard item={makeItem(false)} channelLabel="Chan" />);
    expect(unread.container.querySelector('article')).toHaveClass('border-sky-500');
    unread.unmount();

    const item = makeItem(false);
    const pending = wrap(<MessageCard item={item} channelLabel="Chan" pendingKeys={new Set([item.key])} />);
    const pendingCard = pending.container.querySelector('article');
    expect(pendingCard).toHaveClass('border-emerald-500');
    expect(pendingCard).not.toHaveClass('border-sky-500');
    pending.unmount();

    const read = wrap(<MessageCard item={makeItem()} channelLabel="Chan" />);
    const readCard = read.container.querySelector('article');
    expect(readCard).not.toHaveClass('border-sky-500');
    expect(readCard).not.toHaveClass('border-emerald-500');
  });
});
