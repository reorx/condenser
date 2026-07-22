import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

import type { MessageStats } from '@/lib/types';

vi.mock('@/lib/api', () => ({
  api: { messageStats: vi.fn() },
}));

import { api } from '@/lib/api';
import { MessageStatsRow } from './MessageStatsRow';

const messageStats = vi.mocked(api.messageStats);

function makeStats(over: Partial<MessageStats> = {}): MessageStats {
  return {
    views: 1234,
    forwards: 56,
    reactions: [
      { kind: 'emoji', emoji: '👍', document_id: null, count: 12, chosen: false },
      { kind: 'custom', emoji: null, document_id: 5368221678337263242, count: 3, chosen: true },
    ],
    ...over,
  };
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('MessageStatsRow', () => {
  beforeEach(() => {
    messageStats.mockReset();
  });

  it('renders views, forwards and reaction chips', async () => {
    messageStats.mockResolvedValue(makeStats());
    wrap(<MessageStatsRow msgRef={{ channel_id: 1, message_id: 2 }} />);

    expect(await screen.findByText('1.2k')).toBeInTheDocument();
    expect(messageStats).toHaveBeenCalledWith(1, 2);
    expect(screen.getByText('56')).toBeInTheDocument();
    // emoji reaction shows its glyph + count
    expect(screen.getByText('👍')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    // custom emoji degrades to a generic icon + count
    expect(screen.getByLabelText('custom reaction')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('renders nothing when the message carries no stats at all', async () => {
    messageStats.mockResolvedValue(makeStats({ views: null, forwards: null, reactions: [] }));
    const { container } = wrap(<MessageStatsRow msgRef={{ channel_id: 1, message_id: 2 }} />);

    await waitFor(() => expect(messageStats).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing while pending and on error', async () => {
    messageStats.mockRejectedValue(new Error('boom'));
    const { container } = wrap(<MessageStatsRow msgRef={{ channel_id: 1, message_id: 2 }} />);

    expect(container.firstChild).toBeNull();
    await waitFor(() => expect(messageStats).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });
});
