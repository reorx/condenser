import { AlertTriangle, RefreshCw, Trash2 } from 'lucide-react';

import { RssGlyph } from '@/components/RssGlyph';
import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { relativeLabel } from '@/lib/format';
import { rssFeedLabel } from '@/lib/sources';
import type { RssSubscription } from '@/lib/types';

/** The facts line under a feed's name, Miniflux's "Last check … | Next check …".
 *
 *  `checked_at` is every attempt and `fetched_at` only the successes, so the two
 *  together tell "never worked" (likely a wrong URL) from "worked, then died". A next
 *  check is shown only when the feed has one of its own — a healthy feed is on the
 *  round timer, and printing "in 12 minutes" on 70 rows is noise. `now` is injectable
 *  so the test can pin the wording. */
export function rssFeedStatusParts(sub: RssSubscription, now: Date = new Date()): string[] {
  if (!sub.checked_at && !sub.fetched_at) return ['waiting for the first fetch'];
  const parts: string[] = [];
  const checked = sub.checked_at ?? sub.fetched_at;
  if (checked) parts.push(`last check ${relativeLabel(checked, now)}`);
  if (sub.error_count > 0 && sub.fetched_at) parts.push(`last seen ${relativeLabel(sub.fetched_at, now)}`);
  if (sub.next_attempt_at) parts.push(`next check ${relativeLabel(sub.next_attempt_at, now)}`);
  return parts;
}

/** One feed row on the Subscriptions page: name (URL until a fetch teaches us the
 *  title), fetch state, refresh, pause switch, unsubscribe.
 *
 *  Three states read differently and must not be conflated. `abnormal` (server-decided:
 *  the streak is past the threshold, the feed is backed off toward weekly) is the
 *  yellow row with a badge — the one waiting on the reader. `error_count > 0` below
 *  that is broken and retrying on its own. A `last_error` with a zero count is a
 *  complaint about malformed XML we recovered entries from anyway — a warning, not a
 *  failure. The error line spells the failure out verbatim, because "3 errors" alone
 *  does not say whether to fix the URL or wait for the site. */
export function RssSubscriptionRow({
  sub,
  onToggle,
  onDelete,
  onRefresh,
  busy,
  refreshing,
}: {
  sub: RssSubscription;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
  onRefresh: () => void;
  busy?: boolean;
  refreshing?: boolean;
}) {
  const failing = sub.error_count > 0;
  const warning = !failing && !!sub.last_error;

  return (
    <div
      className={cn(
        'flex items-center gap-3 px-4 py-3 sm:px-5',
        sub.abnormal && 'bg-amber-50 dark:bg-amber-950/25',
      )}
      data-abnormal={sub.abnormal || undefined}
    >
      <RssGlyph className="size-9 shrink-0 rounded-full text-base" />
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium">{rssFeedLabel(sub.url, sub.name)}</span>
          {sub.abnormal ? (
            <span
              className="shrink-0 rounded bg-amber-200/80 px-1.5 py-px text-[10px] font-medium leading-4 text-amber-900 dark:bg-amber-900/60 dark:text-amber-100"
              title="连续失败已超过阈值，轮询已退避（最长一周一次）"
            >
              异常
            </span>
          ) : failing ? (
            <AlertTriangle className="size-3.5 shrink-0 text-destructive" aria-label="Feed is failing" />
          ) : warning ? (
            <AlertTriangle className="size-3.5 shrink-0 text-amber-500" aria-label="Feed reported a warning" />
          ) : null}
        </div>
        <div className="truncate text-xs text-muted-foreground" title={sub.url}>
          {rssFeedStatusParts(sub).join(' · ')}
        </div>
        {sub.last_error && (
          <div
            className={cn(
              'truncate text-xs',
              failing ? 'text-destructive' : 'text-amber-600 dark:text-amber-500',
            )}
            title={sub.last_error}
          >
            {failing && <span className="font-medium">{`${sub.error_count} ${sub.error_count === 1 ? 'error' : 'errors'} – `}</span>}
            {sub.last_error}
          </div>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground"
          aria-label={`Refresh ${sub.url}`}
          title="立即抓取一次（无视退避与暂停）"
          disabled={refreshing}
          onClick={onRefresh}
        >
          {refreshing ? <Spinner className="size-4" /> : <RefreshCw className="size-4" />}
        </Button>
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
