import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import type { TimelineItem } from '@/lib/types';

import { ForwardedBadge } from './ForwardedBadge';

function item(over: Partial<TimelineItem> = {}): TimelineItem {
  return {
    source: 'hn',
    key: 'hn:101',
    datetime: '2026-08-20T12:00:00Z',
    is_read: false,
    is_saved: false,
    ...over,
  };
}

describe('ForwardedBadge', () => {
  it('shows only when I forwarded the item myself', () => {
    const { container, rerender } = render(<ForwardedBadge item={item()} />);
    expect(container).toBeEmptyDOMElement();

    rerender(<ForwardedBadge item={item({ forwarded_by_me: true })} />);
    expect(screen.getByLabelText('已转发到我的频道')).toBeInTheDocument();
  });

  it('ignores telegram.is_forwarded, which points the other way', () => {
    // `telegram.is_forwarded` means "this post was forwarded *into* the channel
    // I read". Badging that would tell the reader they published something they
    // only received — the exact confusion the field name avoids.
    const { container } = render(
      <ForwardedBadge
        item={item({ source: 'telegram', telegram: { is_forwarded: true } as never, forwarded_by_me: false })}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
