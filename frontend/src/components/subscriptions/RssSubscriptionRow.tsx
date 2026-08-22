import { AlertTriangle, Trash2 } from 'lucide-react';

import { RssGlyph } from '@/components/RssGlyph';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { fullDateLabel } from '@/lib/format';
import { rssFeedLabel } from '@/lib/sources';
import type { RssSubscription } from '@/lib/types';

/** One feed row on the Subscriptions page: name (URL until a fetch teaches us the
 *  title), fetch state, pause switch, unsubscribe.
 *
 *  The status line's job is to explain a feed that has gone quiet. Two states read
 *  differently and must not be conflated: `error_count > 0` is broken and retrying,
 *  while a `last_error` with a zero count is a complaint about malformed XML we
 *  recovered entries from anyway — a warning, not a failure. */
export function RssSubscriptionRow({
  sub,
  onToggle,
  onDelete,
  busy,
}: {
  sub: RssSubscription;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
  busy?: boolean;
}) {
  const failing = sub.error_count > 0;
  const parts: string[] = [];
  if (sub.fetched_at) parts.push(`fetched ${fullDateLabel(sub.fetched_at)}`);
  else parts.push('waiting for the first fetch');
  if (failing) parts.push(`${sub.error_count} consecutive failures`);

  return (
    <div className="flex items-center gap-3 px-4 py-3 sm:px-5">
      <RssGlyph className="size-9 shrink-0 rounded-full text-base" />
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium">{rssFeedLabel(sub.url, sub.name)}</span>
          {sub.last_error && (
            <AlertTriangle
              className={failing ? 'size-3.5 shrink-0 text-destructive' : 'size-3.5 shrink-0 text-amber-500'}
              aria-label={failing ? 'Feed is failing' : 'Feed reported a warning'}
            />
          )}
        </div>
        <div className="truncate text-xs text-muted-foreground" title={sub.url}>
          {parts.join(' · ')}
          {sub.last_error && (
            <span
              className={failing ? 'text-destructive' : 'text-amber-600 dark:text-amber-500'}
              title={sub.last_error}
            >
              {' '}
              · {sub.last_error}
            </span>
          )}
        </div>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <Switch
          checked={sub.enabled}
          disabled={busy}
          onCheckedChange={onToggle}
          aria-label={sub.enabled ? 'Pause this feed' : 'Resume this feed'}
        />
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-destructive"
          aria-label={`Unsubscribe ${sub.url}`}
          onClick={onDelete}
        >
          <Trash2 className="size-4" />
        </Button>
      </div>
    </div>
  );
}
