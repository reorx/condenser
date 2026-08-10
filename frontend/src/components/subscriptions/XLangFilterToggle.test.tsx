import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';

vi.mock('@/lib/api', () => ({
  api: {
    getAppMeta: vi.fn(),
    xSetConfig: vi.fn().mockResolvedValue({}),
  },
  errorMessage: (_e: unknown, fallback: string) => fallback,
}));

import { api } from '@/lib/api';

import { XLangFilterToggle } from './XLangFilterToggle';

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const meta = (languages: string[]) => ({
  schema_version: 12,
  backfill_days: 7,
  forward_channel: null,
  languages,
});

describe('XLangFilterToggle', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAppMeta).mockResolvedValue(meta(['zh', 'en']));
  });

  it('turns the filter on through the subscription config', async () => {
    wrap(<XLangFilterToggle feed="foryou" enabled={false} />);

    await userEvent.click(screen.getByText('语言过滤关'));

    await waitFor(() => expect(api.xSetConfig).toHaveBeenCalledWith('foryou', { lang_filter: true }));
  });

  it('turns the filter off the same way', async () => {
    wrap(<XLangFilterToggle feed="foryou" enabled={true} />);

    // findBy: until app-meta resolves the button shows the pick-languages hint
    await userEvent.click(await screen.findByText('按语言过滤'));

    await waitFor(() => expect(api.xSetConfig).toHaveBeenCalledWith('foryou', { lang_filter: false }));
  });

  it('warns when the switch is on but no global languages are picked', async () => {
    // fail-open: the filter is inert in this state, and silence would read as
    // "working" — the button itself says what to do about it
    vi.mocked(api.getAppMeta).mockResolvedValue(meta([]));

    wrap(<XLangFilterToggle feed="foryou" enabled={true} />);

    expect(await screen.findByText('先在设置中选择语言')).toBeInTheDocument();
  });
});
