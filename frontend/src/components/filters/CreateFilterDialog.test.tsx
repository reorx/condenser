import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { FilterPreviewResult } from '@/lib/types';

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>();
  return {
    ...actual,
    api: { listSubscriptions: vi.fn(), previewFilter: vi.fn(), createFilter: vi.fn() },
  };
});
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

import { toast } from 'sonner';
import { api, ApiError } from '@/lib/api';
import { CreateFilterDialog } from './CreateFilterDialog';

const previewFilter = vi.mocked(api.previewFilter);
const createFilter = vi.mocked(api.createFilter);

const ARC_PREVIEW: FilterPreviewResult = {
  scanned: 1000,
  matched: 0,
  samples: [],
  near_misses: { count: 10, core: 'arc', example: 'archives', suggestion: 'arc*' },
};

function renderDialog() {
  const onOpenChange = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <CreateFilterDialog open onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  );
  return { onOpenChange, user: userEvent.setup(), keyword: screen.getByRole('textbox') as HTMLInputElement };
}

describe('CreateFilterDialog', () => {
  beforeEach(() => {
    vi.mocked(api.listSubscriptions).mockResolvedValue([]);
    previewFilter.mockReset();
    createFilter.mockReset();
    vi.mocked(toast.error).mockReset();
  });

  it('describes whole-word matching and the * widener', () => {
    renderDialog();
    expect(screen.getByText(/match whole words only/)).toBeInTheDocument();
    expect(screen.getByText(/arc\* also hides archive/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText('e.g. promo, arc*, 广告')).toBeInTheDocument();
  });

  it('swaps the keyword for the suggestion and waits for a fresh preview', async () => {
    previewFilter.mockResolvedValue(ARC_PREVIEW);
    const { user, keyword } = renderDialog();

    await user.type(keyword, 'arc');
    await user.click(screen.getByRole('button', { name: 'Preview' }));
    await user.click(await screen.findByRole('button', { name: 'Use arc*' }));

    expect(keyword).toHaveValue('arc*');
    // The old preview described `arc`; it must not linger next to `arc*`.
    expect(screen.queryByText(/inside a longer word/)).not.toBeInTheDocument();
    expect(previewFilter).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: 'Preview' }));
    expect(previewFilter).toHaveBeenLastCalledWith('arc*', null);
  });

  it('shows the empty-keyword error when previewing a bare *', async () => {
    previewFilter.mockRejectedValue(new ApiError(422, 'Keyword is empty — * alone matches nothing'));
    const { user, keyword } = renderDialog();

    await user.type(keyword, '*');
    await user.click(screen.getByRole('button', { name: 'Preview' }));

    expect(await screen.findByText('Keyword is empty — * alone matches nothing')).toBeInTheDocument();
  });

  it('keeps the dialog open and reports the empty keyword when creating a bare *', async () => {
    createFilter.mockRejectedValue(new ApiError(422, 'Keyword is empty — * alone matches nothing'));
    const { user, keyword, onOpenChange } = renderDialog();

    await user.type(keyword, '*');
    await user.click(screen.getByRole('button', { name: 'Create filter' }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Keyword is empty — * alone matches nothing'));
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });
});
