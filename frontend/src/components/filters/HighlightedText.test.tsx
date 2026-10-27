import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';

import { HighlightedText } from './HighlightedText';

function marks(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll('mark')).map((m) => m.textContent ?? '');
}

describe('HighlightedText', () => {
  it('slices by code point, so an emoji before the hit does not shift the mark', () => {
    // 😀 is one code point but two UTF-16 units: [2,5) is "Arc", while a
    // UTF-16 slice would mark " Ar".
    const { container } = render(
      <HighlightedText
        text="😀 Arc archive arc"
        ranges={[
          [2, 5],
          [14, 17],
        ]}
      />,
    );
    expect(marks(container)).toEqual(['Arc', 'arc']);
    expect(container).toHaveTextContent('😀 Arc archive arc');
  });

  it('marks only the server ranges, not every occurrence of the keyword', () => {
    const { container } = render(<HighlightedText text="arc archive" ranges={[[0, 3]]} />);
    expect(marks(container)).toEqual(['arc']);
  });

  it('counts the leading ellipsis of a windowed excerpt as one code point', () => {
    const { container } = render(<HighlightedText text="…see arc here" ranges={[[5, 8]]} />);
    expect(marks(container)).toEqual(['arc']);
  });

  it('renders the plain text when there are no ranges', () => {
    const { container } = render(<HighlightedText text="nothing to mark" ranges={[]} />);
    expect(marks(container)).toEqual([]);
    expect(container).toHaveTextContent('nothing to mark');
  });
});
