import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { ForwardResult } from '@/lib/types';

vi.mock('@/lib/api', () => ({
  api: { forwardMessage: vi.fn() },
  errorMessage: (_e: unknown, fallback: string) => fallback,
}));
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { toast } from 'sonner';
import { api } from '@/lib/api';
import { ForwardDialog } from './ForwardDialog';

const forwardMessage = vi.mocked(api.forwardMessage);

function ok(mode: ForwardResult['mode']): ForwardResult {
  return { status: 'ok', mode, link: 'https://t.me/mych/9' };
}

function renderDialog() {
  const onOpenChange = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ForwardDialog open onOpenChange={onOpenChange} msgRef={{ channel_id: 1, message_id: 2 }} />
    </QueryClientProvider>,
  );
  return { onOpenChange };
}

describe('ForwardDialog', () => {
  beforeEach(() => {
    forwardMessage.mockReset();
    vi.mocked(toast.success).mockReset();
  });

  it('shows the hint copy and both actions', () => {
    renderDialog();
    expect(screen.getByText(/写上自己的看法/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '确认转发' })).toBeInTheDocument();
  });

  it('sends the trimmed comment and closes with a toast on success', async () => {
    forwardMessage.mockResolvedValue(ok('quote'));
    const { onOpenChange } = renderDialog();
    const user = userEvent.setup();

    await user.type(screen.getByPlaceholderText(/留空则原样转发/), '值得一读');
    await user.click(screen.getByRole('button', { name: '确认转发' }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(forwardMessage).toHaveBeenCalledWith(1, 2, '值得一读');
    expect(toast.success).toHaveBeenCalled();
  });

  it('uses a native forward when the comment is left empty', async () => {
    forwardMessage.mockResolvedValue(ok('forward'));
    const { onOpenChange } = renderDialog();

    await userEvent.setup().click(screen.getByRole('button', { name: '确认转发' }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(forwardMessage).toHaveBeenCalledWith(1, 2, undefined);
  });

  it('treats a whitespace-only comment as empty', async () => {
    forwardMessage.mockResolvedValue(ok('forward'));
    renderDialog();
    const user = userEvent.setup();

    await user.type(screen.getByPlaceholderText(/留空则原样转发/), '   ');
    await user.click(screen.getByRole('button', { name: '确认转发' }));

    await waitFor(() => expect(forwardMessage).toHaveBeenCalledWith(1, 2, undefined));
  });

  it('cancel closes without calling the API', async () => {
    const { onOpenChange } = renderDialog();

    await userEvent.setup().click(screen.getByRole('button', { name: '取消' }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(forwardMessage).not.toHaveBeenCalled();
  });
});
