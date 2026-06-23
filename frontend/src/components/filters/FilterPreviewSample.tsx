import { timeLabel } from '@/lib/format';
import type { FilterPreviewSample as FilterPreviewSampleData } from '@/lib/types';

import { HighlightedText } from './HighlightedText';

interface FilterPreviewSampleProps {
  sample: FilterPreviewSampleData;
  /** Keyword to highlight inside the sample text. */
  pattern: string;
}

/** One matched message in the create-filter preview list, with the keyword highlighted. */
export function FilterPreviewSample({ sample, pattern }: FilterPreviewSampleProps) {
  return (
    <li className="min-w-0 px-3 py-2 text-sm">
      <div className="mb-0.5 flex items-center gap-2 text-xs text-muted-foreground">
        <span className="truncate">{sample.channel_title ?? 'Unknown channel'}</span>
        <span>·</span>
        <span className="tabular-nums">{timeLabel(sample.date)}</span>
      </div>
      <HighlightedText text={sample.text} pattern={pattern} />
    </li>
  );
}
