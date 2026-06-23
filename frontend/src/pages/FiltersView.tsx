import { useMemo, useState } from 'react';
import { Plus } from 'lucide-react';

import { CreateFilterDialog } from '@/components/filters/CreateFilterDialog';
import { FilterGroupSection, type FilterGroup } from '@/components/filters/FilterGroupSection';
import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { useAllFilters, useDeleteFilter } from '@/hooks/useAllFilters';
import type { KeywordFilter } from '@/lib/types';

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
