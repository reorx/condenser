import { Globe } from 'lucide-react';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import type { KeywordFilter } from '@/lib/types';

import { FilterKeywordChip } from './FilterKeywordChip';

export interface FilterGroup {
  key: string;
  channelId: number | null;
  title: string;
  filters: KeywordFilter[];
}

interface FilterGroupSectionProps {
  group: FilterGroup;
  onDelete: (id: number) => void;
  /** Ids whose delete request is currently in flight. */
  deletingIds: Set<number>;
}

/** One scope section on the Filters page: a header (Global / channel) + its keyword chips. */
export function FilterGroupSection({ group, onDelete, deletingIds }: FilterGroupSectionProps) {
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
          <FilterKeywordChip key={f.id} filter={f} deleting={deletingIds.has(f.id)} onDelete={onDelete} />
        ))}
      </ul>
    </section>
  );
}
