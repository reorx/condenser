import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

vi.mock('@/lib/api', () => ({
  api: {
    getAppMeta: vi.fn(),
    patchAppMeta: vi.fn(),
    tgStatus: vi.fn().mockResolvedValue({ status: 'authorized', phone: '+1' }),
    listDevices: vi.fn().mockResolvedValue([]),
  },
  errorMessage: (_e: unknown, fallback: string) => fallback,
}));

// jsdom has no matchMedia; ThemeProvider reads the system scheme through it
vi.stubGlobal(
  'matchMedia',
  vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
);

import { api } from '@/lib/api';
import { ThemeProvider } from '@/lib/theme';
import { UnreadIndicatorProvider } from '@/lib/unreadIndicator';

import { SettingsDialog } from './SettingsDialog';

function renderDialog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const ui: ReactNode = (
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <UnreadIndicatorProvider>
          <MemoryRouter>
            <SettingsDialog open onOpenChange={() => {}} />
          </MemoryRouter>
        </UnreadIndicatorProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
  return render(ui);
}

const meta = (languages: string[]) => ({
  schema_version: 12,
  backfill_days: 7,
  forward_channel: null,
  languages,
});

describe('SettingsDialog Telegram section', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAppMeta).mockResolvedValue(meta([]));
  });

  it('shows the phone and a disconnect action when connected', async () => {
    vi.mocked(api.tgStatus).mockResolvedValue({ status: 'authorized', phone: '+8613800000000' });
    renderDialog();

    expect(await screen.findByText('+8613800000000')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /disconnect telegram/i })).toBeInTheDocument();
  });

  // The gate stopped forcing the Telegram login on a multi-source install, so this
  // is the only remaining way in — without it an HN-only install could never
  // connect Telegram at all.
  it('offers the way in when Telegram is not connected', async () => {
    vi.mocked(api.tgStatus).mockResolvedValue({ status: 'unauthorized' });
    renderDialog();

    const link = await screen.findByRole('link', { name: /connect telegram/i });
    expect(link).toHaveAttribute('href', '/connect-telegram');
    expect(screen.queryByRole('button', { name: /disconnect telegram/i })).not.toBeInTheDocument();
  });
});

describe('SettingsDialog 语言 section', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.patchAppMeta).mockResolvedValue(meta(['zh']));
  });

  it('selecting a language PATCHes the whole new list', async () => {
    vi.mocked(api.getAppMeta).mockResolvedValue(meta(['zh']));
    renderDialog();

    await userEvent.click(await screen.findByRole('checkbox', { name: 'English' }));

    await waitFor(() => expect(api.patchAppMeta).toHaveBeenCalledWith({ languages: ['zh', 'en'] }));
  });

  it('deselecting removes only that language', async () => {
    vi.mocked(api.getAppMeta).mockResolvedValue(meta(['zh', 'en']));
    renderDialog();

    await userEvent.click(await screen.findByRole('checkbox', { name: '中文' }));

    await waitFor(() => expect(api.patchAppMeta).toHaveBeenCalledWith({ languages: ['en'] }));
  });

  it('reflects the stored selection', async () => {
    vi.mocked(api.getAppMeta).mockResolvedValue(meta(['ja']));
    renderDialog();

    // findBy + checked waits out the app-meta fetch (all pills start unchecked)
    expect(await screen.findByRole('checkbox', { name: '日本語', checked: true })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '中文' })).toHaveAttribute('aria-checked', 'false');
  });
});
