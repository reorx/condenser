import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { ForwardResult, TimelineItem } from '@/lib/types';

vi.mock('@/lib/api', () => ({
  api: { forwardItem: vi.fn() },
  errorMessage: (_e: unknown, fallback: string) => fallback,
}));
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { toast } from 'sonner';
import { api } from '@/lib/api';
import { ForwardDialog } from './ForwardDialog';

const forwardItem = vi.mocked(api.forwardItem);

function ok(mode: ForwardResult['mode']): ForwardResult {
  return { status: 'ok', mode, link: 'https://t.me/mych/9' };
}

/** Only `source` and `key` matter to the dialog; the payload is irrelevant here. */
function item(source: TimelineItem['source'], key: string): TimelineItem {
  return { source, key, datetime: '2026-06-01T12:00:00Z', is_read: false, is_saved: false };
}

function renderDialog(target: TimelineItem = item('telegram', 'tg:1:2')) {
  const onOpenChange = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ForwardDialog open onOpenChange={onOpenChange} item={target} />
    </QueryClientProvider>,
  );
  return { onOpenChange };
}

describe('ForwardDialog', () => {
  beforeEach(() => {
    forwardItem.mockReset();
    vi.mocked(toast.success).mockReset();
  });

  it('shows the hint copy and both actions', () => {
    renderDialog();
    expect(screen.getByText(/写上自己的看法/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '确认转发' })).toBeInTheDocument();
  });

  it('sends the trimmed comment and closes with a toast on success', async () => {
    forwardItem.mockResolvedValue(ok('quote'));
    const { onOpenChange } = renderDialog();
    const user = userEvent.setup();

    await user.type(screen.getByPlaceholderText(/留空则原样转发/), '值得一读');
    await user.click(screen.getByRole('button', { name: '确认转发' }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(forwardItem).toHaveBeenCalledWith('tg:1:2', '值得一读');
    expect(toast.success).toHaveBeenCalled();
  });

  it('uses a native forward when the comment is left empty', async () => {
    forwardItem.mockResolvedValue(ok('forward'));
    const { onOpenChange } = renderDialog();

    await userEvent.setup().click(screen.getByRole('button', { name: '确认转发' }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(forwardItem).toHaveBeenCalledWith('tg:1:2', undefined);
  });

  it('treats a whitespace-only comment as empty', async () => {
    forwardItem.mockResolvedValue(ok('forward'));
    renderDialog();
    const user = userEvent.setup();

    await user.type(screen.getByPlaceholderText(/留空则原样转发/), '   ');
    await user.click(screen.getByRole('button', { name: '确认转发' }));

    await waitFor(() => expect(forwardItem).toHaveBeenCalledWith('tg:1:2', undefined));
  });

  it('cancel closes without calling the API', async () => {
    const { onOpenChange } = renderDialog();

    await userEvent.setup().click(screen.getByRole('button', { name: '取消' }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(forwardItem).not.toHaveBeenCalled();
  });

  it('forwards a non-TG item by key, with copy that drops the native-forward promise', async () => {
    forwardItem.mockResolvedValue(ok('quote'));
    renderDialog(item('hn', 'hn:101'));
    const user = userEvent.setup();

    // "留空则原样转发" would be a lie: HN has no Telegram original to forward.
    expect(screen.getByPlaceholderText(/留空则只发标题和链接/)).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(/留空则只发标题和链接/), '值得一读');
    await user.click(screen.getByRole('button', { name: '确认转发' }));

    await waitFor(() => expect(forwardItem).toHaveBeenCalledWith('hn:101', '值得一读'));
  });
});
