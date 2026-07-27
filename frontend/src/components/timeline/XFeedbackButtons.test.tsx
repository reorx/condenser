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
import { FEEDBACK_REASONS, FEEDBACK_REASON_LABELS } from '@/lib/sources';

import { XFeedbackButtons } from './XFeedbackButtons';

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const utils = render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
  // The label is a prop: in the app the optimistic cache update pushes the new one
  // back down. Tests that span two clicks have to replay that, or the second click
  // is judged against a stale label.
  return {
    ...utils,
    rerenderIn: (next: ReactNode) => utils.rerender(<QueryClientProvider client={qc}>{next}</QueryClientProvider>),
  };
}

const up = () => screen.getByLabelText('More like this');
const down = () => screen.getByLabelText('Less like this');
const reasonRow = () => screen.queryByText('为什么？');

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

    await waitFor(() => expect(api.setFeedback).toHaveBeenCalledWith('x:1', 'up', null));
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

    await waitFor(() => expect(api.setFeedback).toHaveBeenCalledWith('x:1', 'down', null));
    expect(api.clearFeedback).not.toHaveBeenCalled();
  });

  // --- the reason chips (credit assignment) ---------------------------------
  // A bare down says "not this tweet"; the chip says which attribute earned it,
  // which is what lets a later model route the label instead of averaging it.

  it('asks why right after a down', async () => {
    wrap(<XFeedbackButtons itemKey="x:1" feedback={null} />);
    expect(reasonRow()).not.toBeInTheDocument();

    await userEvent.click(down());

    expect(reasonRow()).toBeInTheDocument();
    // Derived, not spelled out: a chip added to the taxonomy but not offered here
    // is a value the backend accepts and the reader can never produce.
    for (const { label } of FEEDBACK_REASONS) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('offers 博眼球 — bait is not the same complaint as an advertisement', async () => {
    // Added 2026-07-27. The influencer-thread pattern (hook, FOMO, "save this 🔖",
    // the payoff parked in the replies) is what a reader actually meets on For You,
    // and folding it into 广告营销 would make the two indistinguishable in the
    // training set even though they feed different channels.
    wrap(<XFeedbackButtons itemKey="x:1" feedback={null} />);
    await userEvent.click(down());

    // Through the label constant, not the string: the wording is cosmetic and has
    // already changed once (钓互动 → 博眼球, 2026-07-27); the value mapping is the contract.
    await userEvent.click(screen.getByRole('button', { name: FEEDBACK_REASON_LABELS.engagement_farming }));

    await waitFor(() => expect(api.setFeedback).toHaveBeenLastCalledWith('x:1', 'down', 'engagement_farming'));
  });

  it('does not ask why on an up — the chips are the negative taxonomy', async () => {
    wrap(<XFeedbackButtons itemKey="x:1" feedback={null} />);

    await userEvent.click(up());

    expect(reasonRow()).not.toBeInTheDocument();
  });

  it('a chip re-sends the whole label, verdict included', async () => {
    wrap(<XFeedbackButtons itemKey="x:1" feedback={null} />);
    await userEvent.click(down());

    await userEvent.click(screen.getByRole('button', { name: 'AI Slop' }));

    await waitFor(() => expect(api.setFeedback).toHaveBeenLastCalledWith('x:1', 'down', 'ai_slop'));
  });

  it('collapses once a chip is picked', async () => {
    wrap(<XFeedbackButtons itemKey="x:1" feedback={null} />);
    await userEvent.click(down());

    await userEvent.click(screen.getByRole('button', { name: '不感兴趣' }));

    await waitFor(() => expect(reasonRow()).not.toBeInTheDocument());
  });

  it('is skippable: dismissing keeps the down and sends no reason', async () => {
    wrap(<XFeedbackButtons itemKey="x:1" feedback={null} />);
    await userEvent.click(down());

    await userEvent.click(screen.getByLabelText('跳过'));

    expect(reasonRow()).not.toBeInTheDocument();
    expect(api.setFeedback).toHaveBeenCalledTimes(1);
    expect(api.setFeedback).toHaveBeenCalledWith('x:1', 'down', null);
  });

  it('undoing the down takes the question away with it', async () => {
    const { rerenderIn } = wrap(<XFeedbackButtons itemKey="x:1" feedback={null} />);
    await userEvent.click(down());
    expect(reasonRow()).toBeInTheDocument();
    rerenderIn(<XFeedbackButtons itemKey="x:1" feedback="down" />); // the label lands

    await userEvent.click(down()); // clicking the lit thumb = undo

    await waitFor(() => expect(api.clearFeedback).toHaveBeenCalledWith('x:1'));
    expect(reasonRow()).not.toBeInTheDocument();
  });

  it('switching from down to up closes the question too', async () => {
    const { rerenderIn } = wrap(<XFeedbackButtons itemKey="x:1" feedback={null} />);
    await userEvent.click(down());
    rerenderIn(<XFeedbackButtons itemKey="x:1" feedback="down" />);

    await userEvent.click(up());

    await waitFor(() => expect(api.setFeedback).toHaveBeenLastCalledWith('x:1', 'up', null));
    expect(reasonRow()).not.toBeInTheDocument();
  });

  it('never nags a tweet that is merely already labeled', () => {
    // The row answers *this* click; it is not a state of the card. An already
    // down-voted tweet scrolling back into view must not re-ask on every render.
    wrap(<XFeedbackButtons itemKey="x:1" feedback="down" />);

    expect(reasonRow()).not.toBeInTheDocument();
  });
});
