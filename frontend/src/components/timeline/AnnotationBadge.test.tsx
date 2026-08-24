import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import type { ItemAnnotation, TimelineItem } from '@/lib/types';

import { AnnotationBadge } from './AnnotationBadge';

function makeItem(over: Partial<TimelineItem> = {}): TimelineItem {
  return { source: 'rss', key: 'rss:1', datetime: '2026-08-20T10:00:00Z', is_read: true, is_saved: false, ...over };
}

const highlight: ItemAnnotation = {
  id: 1,
  quote: 'q',
  prefix: '',
  suffix: '',
  block: null,
  comment: null,
  created_at: null,
};

describe('AnnotationBadge', () => {
  it('renders nothing when the reader wrote nothing on the item', () => {
    const { container } = render(<AnnotationBadge item={makeItem()} />);
    expect(container).toBeEmptyDOMElement();
    // '' is a cleared note, not a note.
    const cleared = render(<AnnotationBadge item={makeItem({ note: '', annotations: [] })} />);
    expect(cleared.container).toBeEmptyDOMElement();
  });

  it('marks an item carrying a note or a highlight', () => {
    render(<AnnotationBadge item={makeItem({ note: '想法' })} />);
    expect(screen.getByLabelText('有评论或高亮')).toBeInTheDocument();
    render(<AnnotationBadge item={makeItem({ annotations: [highlight] })} />);
    expect(screen.getAllByLabelText('有评论或高亮')).toHaveLength(2);
  });
});
