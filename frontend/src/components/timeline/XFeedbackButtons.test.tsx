import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';

vi.mock('@/lib/api', () => ({
  api: {
    setFeedback: vi.fn().mockResolvedValue({ ok: true }),
    clearFeedback: vi.fn().mockResolvedValue({ ok: true }),
  },
}));

import { api } from '@/lib/api';

import { XFeedbackButtons } from './XFeedbackButtons';

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

const up = () => screen.getByLabelText('More like this');
const down = () => screen.getByLabelText('Less like this');

describe('XFeedbackButtons', () => {
  beforeEach(() => vi.clearAllMocks());

  it('starts unlabeled', () => {
    wrap(<XFeedbackButtons itemKey="x:1" feedback={null} />);

    expect(up()).toHaveAttribute('aria-pressed', 'false');
    expect(down()).toHaveAttribute('aria-pressed', 'false');
  });

  it('records an up label', async () => {
    wrap(<XFeedbackButtons itemKey="x:1" feedback={null} />);

    await userEvent.click(up());

    await waitFor(() => expect(api.setFeedback).toHaveBeenCalledWith('x:1', 'up'));
  });

  it('highlights the chosen side', () => {
    wrap(<XFeedbackButtons itemKey="x:1" feedback="down" />);

    expect(down()).toHaveAttribute('aria-pressed', 'true');
    expect(up()).toHaveAttribute('aria-pressed', 'false');
  });

  it('clicking the highlighted side again undoes the label', async () => {
    wrap(<XFeedbackButtons itemKey="x:1" feedback="up" />);

    await userEvent.click(up());

    await waitFor(() => expect(api.clearFeedback).toHaveBeenCalledWith('x:1'));
  });

  it('switching sides is a correction, not a second label', async () => {
    wrap(<XFeedbackButtons itemKey="x:1" feedback="up" />);

    await userEvent.click(down());

    await waitFor(() => expect(api.setFeedback).toHaveBeenCalledWith('x:1', 'down'));
    expect(api.clearFeedback).not.toHaveBeenCalled();
  });
});
