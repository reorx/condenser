import { useState } from 'react';
import { AtSign, Search } from 'lucide-react';

import { Spinner } from '@/components/Spinner';
import { AddByHandleDialog } from '@/components/subscriptions/AddByHandleDialog';
import { BrowseChannelsDialog } from '@/components/subscriptions/BrowseChannelsDialog';
import { SubscriptionRow } from '@/components/subscriptions/SubscriptionRow';
import { Button } from '@/components/ui/button';
import { useSubscriptions } from '@/hooks/useSubscriptions';

/** The Telegram tab on the Subscriptions page: browse/add actions + the channel list. */
export function TelegramSection() {
  const { data: subs, isPending } = useSubscriptions();
  const [browseOpen, setBrowseOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);

  return (
    <section>
      <div className="flex items-start justify-between gap-3 px-4 py-3 sm:px-5">
        <p className="text-xs text-muted-foreground">Toggle to pause syncing, fetch older messages, or unsubscribe.</p>
        <div className="flex shrink-0 gap-2">
          <Button variant="outline" size="sm" onClick={() => setBrowseOpen(true)}>
            <Search className="size-4" />
            Browse channels
          </Button>
          <Button variant="outline" size="sm" onClick={() => setAddOpen(true)}>
            <AtSign className="size-4" />
            Add by handle
          </Button>
        </div>
      </div>

      <BrowseChannelsDialog open={browseOpen} onOpenChange={setBrowseOpen} />
      <AddByHandleDialog open={addOpen} onOpenChange={setAddOpen} />

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
    </section>
  );
}
