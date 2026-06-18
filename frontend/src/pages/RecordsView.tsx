import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Bookmark } from 'lucide-react';

import { AllChannelsHidden, ChannelFilter } from '@/components/ChannelFilter';
import { Spinner } from '@/components/Spinner';
import { MessageCard } from '@/components/timeline/MessageCard';
import { useChannelFilter } from '@/hooks/useChannelFilter';
import { api } from '@/lib/api';
import { channelName, fullDateLabel } from '@/lib/format';
import type { DisplayMessage } from '@/lib/types';

export function RecordsView() {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['records'],
    queryFn: api.listRecords,
  });

  // Same client-side channel filter as the timeline, over the saved messages.
  const nameOf = useCallback((m: DisplayMessage) => channelName(m.channel), []);
  const filter = useChannelFilter(data ?? [], nameOf);
  const showFilter = filter.channels.length > 1;

  return (
    <>
      <div className="flex items-center gap-2 border-b px-4 py-3 sm:px-5">
        <Bookmark className="size-4 text-amber-500" />
        <h1 className="text-base font-semibold tracking-tight">Saved</h1>
        {showFilter && (
          <ChannelFilter
            className="ml-auto"
            channels={filter.channels}
            hidden={filter.hidden}
            onToggle={filter.toggle}
            onClear={filter.clear}
          />
        )}
      </div>

      {isPending && (
        <div className="flex justify-center py-16">
          <Spinner className="size-5 text-muted-foreground" />
        </div>
      )}

      {isError && (
        <div className="flex flex-col items-center gap-3 py-16 text-sm text-muted-foreground">
          <p>Failed to load saved messages.</p>
          <button className="underline" onClick={() => refetch()}>
            Retry
          </button>
        </div>
      )}

      {data && data.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-24 text-center text-muted-foreground">
          <Bookmark className="size-8" />
          <p className="text-sm">Nothing saved yet. Tap the bookmark on a message to keep it.</p>
        </div>
      )}

      {data && data.length > 0 && filter.visible.length === 0 && (
        <AllChannelsHidden icon={Bookmark} onClear={filter.clear} />
      )}

      {filter.visible.length > 0 && (
        <div className="divide-y divide-border/50">
          {filter.visible.map((m) => (
            <div key={`${m.channel_id}:${m.id}`}>
              <div className="px-4 pt-2 text-[11px] text-muted-foreground/70 sm:px-5">{fullDateLabel(m.date)}</div>
              <MessageCard msg={m} channelLabel={channelName(m.channel)} />
            </div>
          ))}
        </div>
      )}
    </>
  );
}
