import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { AiSummaryBlock, displaySummary } from './AiSummaryBlock';

describe('AiSummaryBlock', () => {
  it('puts the 「AI 摘要」 label before the summary, inside the same block', () => {
    const { container } = render(<AiSummaryBlock summary="文章讲了三件事。" />);
    const label = screen.getByText('AI 摘要');
    const text = screen.getByText('文章讲了三件事。');
    // The eye meets "a machine wrote this" first, then the words.
    expect(label.compareDocumentPosition(text) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // One block holds both, so the attribution cannot be misread.
    const block = container.firstElementChild!;
    expect(block).toContainElement(label);
    expect(block).toContainElement(text);
  });

  it('renders the trimmed summary', () => {
    render(<AiSummaryBlock summary={'  两句话。\n'} />);
    expect(screen.getByText('两句话。')).toBeInTheDocument();
  });

  it('renders nothing for a missing or whitespace-only summary', () => {
    for (const summary of [null, undefined, '', '  \n ']) {
      const { container, unmount } = render(<AiSummaryBlock summary={summary} />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it('passes the caller its outer margin', () => {
    const { container } = render(<AiSummaryBlock summary="摘要。" className="mt-1.5" />);
    expect(container.firstElementChild).toHaveClass('mt-1.5');
  });
});

describe('displaySummary', () => {
  it('is the trimmed text, or null when nothing is left', () => {
    expect(displaySummary(' 摘要。 ')).toBe('摘要。');
    expect(displaySummary('   ')).toBeNull();
    expect(displaySummary(null)).toBeNull();
    expect(displaySummary(undefined)).toBeNull();
  });
});
