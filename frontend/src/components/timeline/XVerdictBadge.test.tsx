import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { XVerdictMeta } from '@/lib/types';

import { XVerdictBadge } from './XVerdictBadge';

const meta: XVerdictMeta = {
  score: -0.72,
  neighbors: [
    { tweet_id: '11', distance: 0.21, label: 'down' },
    { tweet_id: '12', distance: 0.3, label: 'down' },
    { tweet_id: '13', distance: 0.44, label: 'up' },
  ],
  model: 'text-embedding-v4@256',
  algo: 'knn-v1',
};

describe('XVerdictBadge', () => {
  it('shows nothing for a neutral verdict', () => {
    // neutral is the default answer, not a finding — badging it would put a chip on
    // every card in the feed and mean nothing
    const { container } = render(<XVerdictBadge verdict="neutral" meta={{ score: 0.1 }} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('shows nothing when the tweet was never judged', () => {
    const { container } = render(<XVerdictBadge verdict={null} meta={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('labels a negative verdict without acting on it', () => {
    render(<XVerdictBadge verdict="negative" meta={meta} />);

    expect(screen.getByText('Likely not for you')).toBeInTheDocument();
  });

  it('labels a positive verdict', () => {
    render(<XVerdictBadge verdict="positive" meta={{ score: 0.8, neighbors: [] }} />);

    expect(screen.getByText('Recommended')).toBeInTheDocument();
  });

  it('summarizes the evidence in its tooltip', () => {
    render(<XVerdictBadge verdict="negative" meta={meta} />);

    expect(screen.getByRole('button')).toHaveAttribute(
      'title',
      'Closest labeled tweets: 1 you liked or saved, 2 you marked down · score -0.72',
    );
  });

  it('opens the detail pane, where the full evidence is', async () => {
    const onOpen = vi.fn();
    render(<XVerdictBadge verdict="negative" meta={meta} onOpen={onOpen} />);

    await userEvent.click(screen.getByRole('button'));

    expect(onOpen).toHaveBeenCalled();
  });
});
