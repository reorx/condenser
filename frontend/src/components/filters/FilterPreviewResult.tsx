import { Spinner } from '@/components/Spinner';
import type { FilterPreviewResult as FilterPreviewResultData } from '@/lib/types';

import { FilterPreviewSample } from './FilterPreviewSample';

interface FilterPreviewResultProps {
  scope: 'global' | 'channel';
  isPending: boolean;
  error: string | null;
  result: FilterPreviewResultData | null;
  pattern: string;
}

/** The create-filter preview panel: loading / error / summary + matched samples. */
export function FilterPreviewResult({ scope, isPending, error, result, pattern }: FilterPreviewResultProps) {
  if (isPending) {
    return (
      <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-3 text-sm text-muted-foreground">
        <Spinner className="size-4" />
        Scanning recent messages…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-3 text-sm text-destructive">
        {error}
      </div>
    );
  }
  if (!result) return null;

  if (result.scanned === 0) {
    return (
      <div className="rounded-md border bg-muted/40 px-3 py-3 text-sm text-muted-foreground">
        Nothing to scan yet — no cached messages for this scope.
      </div>
    );
  }

  const where = scope === 'global' ? 'across all channels' : 'in this channel';
  const summary =
    result.matched === 0
      ? `No matches in the last ${result.scanned} messages ${where}.`
      : `Will hide ${result.matched} of the last ${result.scanned} messages ${where}.`;

  return (
    <div className="space-y-2">
      <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm">{summary}</div>
      {result.samples.length > 0 && (
        <ul className="max-h-56 overflow-y-auto rounded-md border divide-y divide-border/50">
          {result.samples.map((s) => (
            <FilterPreviewSample key={`${s.channel_id}-${s.message_id}`} sample={s} pattern={pattern} />
          ))}
        </ul>
      )}
      {result.matched > result.samples.length && (
        <p className="text-xs text-muted-foreground">
          Showing {result.samples.length} of {result.matched} matches.
        </p>
      )}
    </div>
  );
}
