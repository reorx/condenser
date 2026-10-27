import { Spinner } from '@/components/Spinner';
import type { FilterNearMisses, FilterPreviewResult as FilterPreviewResultData } from '@/lib/types';

import { FilterPreviewSample } from './FilterPreviewSample';

interface FilterPreviewResultProps {
  scope: 'global' | 'channel';
  isPending: boolean;
  error: string | null;
  result: FilterPreviewResultData | null;
  /** Replaces the keyword input with the near-miss suggestion (e.g. `arc*`). */
  onUseSuggestion: (pattern: string) => void;
}

/** The create-filter preview panel: loading / error / summary + near-miss hint + matched samples. */
export function FilterPreviewResult({ scope, isPending, error, result, onUseSuggestion }: FilterPreviewResultProps) {
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
      {result.near_misses && (
        <NearMissHint nearMisses={result.near_misses} hasMatches={result.matched > 0} onUse={onUseSuggestion} />
      )}
      {result.samples.length > 0 && (
        <ul className="max-h-56 overflow-y-auto rounded-md border divide-y divide-border/50">
          {result.samples.map((s) => (
            <FilterPreviewSample key={`${s.channel_id}-${s.message_id}`} sample={s} />
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

/**
 * The messages a whole-word rule leaves visible because the keyword only sits inside a
 * longer word, with a one-click widened rule. Picking it only rewrites the input: the
 * dialog drops this preview on change, and the reader previews again to see the result.
 * The button is underlined up front because touch screens have no hover to reveal a link.
 */
function NearMissHint({
  nearMisses: { count, core, example, suggestion },
  hasMatches,
  onUse,
}: {
  nearMisses: FilterNearMisses;
  hasMatches: boolean;
  onUse: (pattern: string) => void;
}) {
  // "more" only reads right on top of real matches.
  const one = count === 1;
  const lead = `${count}${hasMatches ? ' more' : ''} ${one ? 'message only contains' : 'messages only contain'}`;
  return (
    <p className="px-1 text-xs text-muted-foreground">
      {lead} "{core}" inside a longer word, like "{example}". {one ? 'It stays' : 'They stay'} visible.{' '}
      <button
        type="button"
        className="font-medium text-primary underline underline-offset-2"
        onClick={() => onUse(suggestion)}
      >
        Use <code className="font-mono">{suggestion}</code>
      </button>
    </p>
  );
}
