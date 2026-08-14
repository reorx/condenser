import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';

vi.mock('@/lib/api', () => ({
  api: { hnSetConfig: vi.fn().mockResolvedValue({}) },
  errorMessage: (_e: unknown, fallback: string) => fallback,
}));

import { api } from '@/lib/api';
import { hnFeedRules } from '@/hooks/useHnFeedRules';

import { HnFeedRulesMenu } from './HnFeedRulesMenu';

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('hnFeedRules', () => {
  it('fills in the server defaults for a config written before the floors existed', () => {
    // production's row is `{display_mode: 'top10'}` — the score floor must read as
    // armed there, or the menu would show "off" for a filter that is running
    expect(hnFeedRules({ display_mode: 'top10' })).toEqual({ mode: 'top10', minScore: 50, maxPeakRank: 0 });
  });

  it('keeps an explicit value, which is the only way a floor differs from its default', () => {
    expect(hnFeedRules({ min_score: 0, max_peak_rank: 20 })).toEqual({
      mode: 'top20',
      minScore: 0,
      maxPeakRank: 20,
    });
  });

  it('falls back to the defaults for junk, never to off', () => {
    expect(hnFeedRules({ display_mode: 'weekly', min_score: 'fifty', max_peak_rank: null })).toEqual({
      mode: 'top20',
      minScore: 50,
      maxPeakRank: 0,
    });
    expect(hnFeedRules(null)).toEqual({ mode: 'top20', minScore: 50, maxPeakRank: 0 });
  });
});

describe('HnFeedRulesMenu', () => {
  const rules = { mode: 'top10' as const, minScore: 50, maxPeakRank: 0 };

  beforeEach(() => vi.clearAllMocks());

  const open = () => userEvent.click(screen.getByRole('button', { name: /Top 10/ }));

  it('shows the day quota on the trigger and all three rules inside', async () => {
    wrap(<HnFeedRulesMenu rules={rules} />);
    await open();

    expect(screen.getByText('Let in per day')).toBeInTheDocument();
    expect(screen.getByText('Minimum score')).toBeInTheDocument();
    expect(screen.getByText('Front-page peak rank')).toBeInTheDocument();
  });

  it('patches one key at a time so the server merge keeps the other two', async () => {
    wrap(<HnFeedRulesMenu rules={rules} />);
    await open();
    await userEvent.click(screen.getByRole('menuitem', { name: '≥ 100' }));

    await waitFor(() => expect(api.hnSetConfig).toHaveBeenCalledWith({ min_score: 100 }));
    expect(api.hnSetConfig).toHaveBeenCalledTimes(1);
  });

  it('offers arming the peak-rank gate, which ships off', async () => {
    wrap(<HnFeedRulesMenu rules={rules} />);
    await open();
    await userEvent.click(screen.getByRole('menuitem', { name: '#20 or better' }));

    await waitFor(() => expect(api.hnSetConfig).toHaveBeenCalledWith({ max_peak_rank: 20 }));
  });

  it('does not write when the already-selected value is picked', async () => {
    wrap(<HnFeedRulesMenu rules={rules} />);
    await open();
    await userEvent.click(screen.getByRole('menuitem', { name: 'Top 10' }));

    expect(api.hnSetConfig).not.toHaveBeenCalled();
  });
});
