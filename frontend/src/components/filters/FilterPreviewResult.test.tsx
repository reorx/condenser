import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { FilterPreviewResult as FilterPreviewResultData } from '@/lib/types';

import { FilterPreviewResult } from './FilterPreviewResult';

function result(over: Partial<FilterPreviewResultData> = {}): FilterPreviewResultData {
  return { scanned: 1000, matched: 0, samples: [], near_misses: null, ...over };
}

const NEAR_MISS = { count: 76, core: 'arc', example: 'archives', suggestion: 'arc*' };

function renderResult(data: FilterPreviewResultData, onUseSuggestion = vi.fn()) {
  render(
    <FilterPreviewResult
      scope="global"
      isPending={false}
      error={null}
      result={data}
      onUseSuggestion={onUseSuggestion}
    />,
  );
  return { onUseSuggestion };
}

describe('FilterPreviewResult', () => {
  it('shows the near-miss count, core keyword, example word and suggestion', () => {
    renderResult(result({ matched: 2, near_misses: NEAR_MISS }));
    expect(
      screen.getByText(
        /76 more messages only contain "arc" inside a longer word, like "archives"\. They stay visible\./,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Use arc*' })).toBeInTheDocument();
  });

  it('hands the suggestion to onUseSuggestion when clicked', async () => {
    const { onUseSuggestion } = renderResult(result({ matched: 2, near_misses: NEAR_MISS }));
    await userEvent.setup().click(screen.getByRole('button', { name: 'Use arc*' }));
    expect(onUseSuggestion).toHaveBeenCalledWith('arc*');
  });

  it('still shows the near-miss line when nothing matches strictly', () => {
    renderResult(result({ near_misses: { count: 10, core: 'arc', example: 'research', suggestion: '*arc*' } }));
    expect(screen.getByText(/No matches in the last 1000 messages/)).toBeInTheDocument();
    // "more" only makes sense on top of real matches.
    expect(screen.getByText(/^10 messages only contain "arc"/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Use *arc*' })).toBeInTheDocument();
  });

  it('uses the singular for a single near miss', () => {
    renderResult(result({ matched: 3, near_misses: { ...NEAR_MISS, count: 1 } }));
    expect(screen.getByText(/^1 more message only contains "arc"/)).toBeInTheDocument();
  });

  it('omits the near-miss line when the server returns null', () => {
    renderResult(result({ matched: 2 }));
    expect(screen.queryByText(/inside a longer word/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Use / })).not.toBeInTheDocument();
  });

  it('highlights each sample from its server ranges', () => {
    const { container } = render(
      <FilterPreviewResult
        scope="global"
        isPending={false}
        error={null}
        onUseSuggestion={vi.fn()}
        result={result({
          matched: 1,
          samples: [
            {
              channel_id: 1,
              message_id: 2,
              channel_title: 'Chan',
              date: '2026-10-25 08:00:00',
              text: '拥抱 AI 的 Arc 浏览器 archive',
              highlights: [[8, 11]],
            },
          ],
        })}
      />,
    );
    expect(Array.from(container.querySelectorAll('mark')).map((m) => m.textContent)).toEqual(['Arc']);
  });
});
