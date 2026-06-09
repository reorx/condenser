import { Hash } from 'lucide-react';

import { Spinner } from '@/components/Spinner';
import { useSubscriptions } from '@/hooks/useSubscriptions';
import { channelName } from '@/lib/format';

export function SubscriptionsView() {
  const { data: subs, isPending } = useSubscriptions();

  return (
    <>
      <div className="border-b px-4 py-3 sm:px-5">
        <h1 className="text-base font-semibold tracking-tight">Manage channels</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Add channels from the sidebar. Enable/disable, keyword filters &amp; delete arrive next.
        </p>
      </div>

      {isPending ? (
        <div className="flex justify-center py-16">
          <Spinner className="size-5 text-muted-foreground" />
        </div>
      ) : (
        <ul className="divide-y divide-border/50">
          {(subs ?? []).map((s) => (
            <li key={s.channel_id} className="flex items-center gap-3 px-4 py-3 sm:px-5">
              <Hash className="size-4 shrink-0 text-muted-foreground" />
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{channelName(s)}</div>
                {s.username && <div className="truncate text-xs text-muted-foreground">@{s.username}</div>}
              </div>
              <div className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
                {!s.backfill_done && <span className="text-amber-500">backfilling…</span>}
                <span
                  className={
                    s.enabled
                      ? 'rounded-full bg-emerald-500/15 px-2 py-0.5 text-emerald-600 dark:text-emerald-400'
                      : 'rounded-full bg-muted px-2 py-0.5'
                  }
                >
                  {s.enabled ? 'active' : 'paused'}
                </span>
              </div>
            </li>
          ))}
          {(subs ?? []).length === 0 && (
            <li className="px-4 py-16 text-center text-sm text-muted-foreground">No channels yet.</li>
          )}
        </ul>
      )}
    </>
  );
}
