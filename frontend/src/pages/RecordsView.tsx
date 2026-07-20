import { useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Bookmark } from 'lucide-react';

import { AllChannelsHidden, ChannelFilter } from '@/components/ChannelFilter';
import { IconBadge, PageHeader } from '@/components/PageHeader';
import { Spinner } from '@/components/Spinner';
import { SavedMessageItem } from '@/components/timeline/SavedMessageItem';
import { useChannelFilter } from '@/hooks/useChannelFilter';
import { api } from '@/lib/api';
import { channelName } from '@/lib/format';
import type { TimelineItem } from '@/lib/types';

export function RecordsView() {
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['records'],
    queryFn: api.listRecords,
  });

  // Same client-side channel filter as the timeline, over the saved items.
  const channelOf = useCallback((it: TimelineItem) => it.telegram?.channel_id ?? null, []);
  const nameOf = useCallback((it: TimelineItem) => channelName(it.telegram?.channel), []);
  const filter = useChannelFilter(data ?? [], channelOf, nameOf);
  const showFilter = filter.channels.length > 1;

  return (
    <>
      <PageHeader
        icon={<IconBadge icon={<Bookmark className="size-5 text-amber-500" />} />}
        title="Saved"
        actions={
          showFilter && (
            <ChannelFilter
              className="h-8 px-2"
              channels={filter.channels}
              hidden={filter.hidden}
              onToggle={filter.toggle}
              onClear={filter.clear}
            />
          )
        }
      />

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
          {filter.visible.map((it) => (
            <SavedMessageItem key={it.key} item={it} />
          ))}
        </div>
      )}
    </>
  );
}
