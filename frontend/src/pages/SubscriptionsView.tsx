import { useState } from 'react';
import { Search } from 'lucide-react';

import { Spinner } from '@/components/Spinner';
import { BrowseChannelsDialog } from '@/components/subscriptions/BrowseChannelsDialog';
import { SubscriptionRow } from '@/components/subscriptions/SubscriptionRow';
import { Button } from '@/components/ui/button';
import { useSubscriptions } from '@/hooks/useSubscriptions';

export function SubscriptionsView() {
  const { data: subs, isPending } = useSubscriptions();
  const [browseOpen, setBrowseOpen] = useState(false);

  return (
    <>
      <div className="flex items-start justify-between gap-3 border-b px-4 py-3 sm:px-5">
        <div>
          <h1 className="text-base font-semibold tracking-tight">Manage channels</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Toggle to pause syncing, fetch older messages, or unsubscribe. Manage exclude keywords from{' '}
            <span className="font-medium">Filters</span>.
          </p>
        </div>
        <Button variant="outline" size="sm" className="shrink-0" onClick={() => setBrowseOpen(true)}>
          <Search className="size-4" />
          Browse channels
        </Button>
      </div>

      <BrowseChannelsDialog open={browseOpen} onOpenChange={setBrowseOpen} />

      {isPending ? (
        <div className="flex justify-center py-16">
          <Spinner className="size-5 text-muted-foreground" />
        </div>
      ) : (
        <ul className="divide-y divide-border/50">
          {(subs ?? []).map((s) => (
            <SubscriptionRow key={s.channel_id} sub={s} />
          ))}
          {(subs ?? []).length === 0 && (
            <li className="px-4 py-16 text-center text-sm text-muted-foreground">No channels yet.</li>
          )}
        </ul>
      )}
    </>
  );
}
