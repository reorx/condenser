import { useMemo, useState } from 'react';
import { Globe, Plus, Trash2 } from 'lucide-react';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { CreateFilterDialog } from '@/components/filters/CreateFilterDialog';
import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { useAllFilters, useDeleteFilter } from '@/hooks/useAllFilters';
import type { KeywordFilter } from '@/lib/types';

interface FilterGroup {
  key: string;
  channelId: number | null;
  title: string;
  filters: KeywordFilter[];
}

function groupFilters(filters: KeywordFilter[]): FilterGroup[] {
  const buckets = new Map<string, FilterGroup>();
  for (const f of filters) {
    const key = f.channel_id === null ? 'global' : `c:${f.channel_id}`;
    let group = buckets.get(key);
    if (!group) {
      group = {
        key,
        channelId: f.channel_id,
        title: f.channel_id === null ? 'Global' : (f.channel_title ?? 'Unknown channel'),
        filters: [],
      };
      buckets.set(key, group);
    }
    group.filters.push(f);
  }
  // Global first, then alphabetical by channel title.
  const groups = [...buckets.values()];
  groups.sort((a, b) => {
    if (a.channelId === null) return -1;
    if (b.channelId === null) return 1;
    return a.title.localeCompare(b.title);
  });
  return groups;
}

export function FiltersView() {
  const { data: filters, isPending } = useAllFilters();
  const [createOpen, setCreateOpen] = useState(false);
  // Track pending deletes per id so concurrent clicks each show their own spinner.
  const [deletingIds, setDeletingIds] = useState<Set<number>>(new Set());
  const del = useDeleteFilter({
    onMutate: (id) => setDeletingIds((prev) => new Set(prev).add(id)),
    onSettled: (_d, _e, id) =>
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      }),
  });

  const groups = useMemo(() => groupFilters(filters ?? []), [filters]);

  return (
    <>
      <div className="flex items-start justify-between gap-3 border-b px-4 py-3 sm:px-5">
        <div>
          <h1 className="text-base font-semibold tracking-tight">Filters</h1>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Exclude messages by keyword — globally or per channel (case-insensitive substring).
          </p>
        </div>
        <Button size="sm" className="shrink-0" onClick={() => setCreateOpen(true)}>
          <Plus className="size-4" />
          Create filter
        </Button>
      </div>

      {isPending ? (
        <div className="flex justify-center py-16">
          <Spinner className="size-5 text-muted-foreground" />
        </div>
      ) : groups.length === 0 ? (
        <div className="px-4 py-16 text-center text-sm text-muted-foreground">
          <p>No filters yet.</p>
          <p className="mt-1 text-xs">
            Click <span className="font-medium">Create filter</span> to hide messages matching a keyword.
          </p>
        </div>
      ) : (
        <div className="divide-y divide-border/50">
          {groups.map((g) => (
            <FilterGroupSection key={g.key} group={g} onDelete={(id) => del.mutate(id)} deletingIds={deletingIds} />
          ))}
        </div>
      )}

      <CreateFilterDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  );
}

function FilterGroupSection({
  group,
  onDelete,
  deletingIds,
}: {
  group: FilterGroup;
  onDelete: (id: number) => void;
  deletingIds: Set<number>;
}) {
  return (
    <section className="px-4 py-3 sm:px-5">
      <header className="mb-2 flex items-center gap-2 text-sm">
        {group.channelId === null ? (
          <span className="flex size-6 items-center justify-center rounded-full bg-muted text-muted-foreground">
            <Globe className="size-3.5" />
          </span>
        ) : (
          <ChannelAvatar channelId={group.channelId} name={group.title} className="size-6 text-[10px]" />
        )}
        <span className="font-medium">{group.title}</span>
        <span className="text-xs text-muted-foreground">
          {group.filters.length} {group.filters.length === 1 ? 'keyword' : 'keywords'}
        </span>
      </header>
      <ul className="flex flex-wrap gap-1.5">
        {group.filters.map((f) => (
          <li key={f.id} className="group flex items-center gap-1 rounded-full bg-muted/60 py-1 pr-1 pl-2.5 text-sm">
            <span className="max-w-[20rem] truncate">{f.pattern}</span>
            <Button
              variant="ghost"
              size="icon"
              className="size-6 text-muted-foreground hover:text-destructive"
              disabled={deletingIds.has(f.id)}
              onClick={() => onDelete(f.id)}
              aria-label={`Remove keyword ${f.pattern}`}
            >
              {deletingIds.has(f.id) ? <Spinner className="size-3" /> : <Trash2 className="size-3.5" />}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
