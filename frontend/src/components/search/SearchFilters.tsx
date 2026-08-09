import { ArrowDownWideNarrow, Bookmark, Clock, Inbox, Sparkles } from 'lucide-react';

import { SearchFilterChip } from '@/components/search/SearchFilterChip';
import { SearchScopeMenu } from '@/components/search/SearchScopeMenu';
import type { SearchScope } from '@/hooks/useSearch';
import type { SearchSort, SearchStatus } from '@/lib/types';

interface SearchFiltersProps {
  scope: SearchScope;
  status: SearchStatus | null;
  sort: SearchSort;
  onScope: (scope: SearchScope) => void;
  onStatus: (status: SearchStatus | null) => void;
  onSort: (sort: SearchSort) => void;
}

const STATUSES: { value: SearchStatus | null; label: string; icon: typeof Inbox }[] = [
  { value: null, label: 'All', icon: Inbox },
  { value: 'unread', label: 'Unread', icon: Sparkles },
  { value: 'saved', label: 'Saved', icon: Bookmark },
];

/**
 * The row under the search box: where to look, what state to look for, how to order.
 *
 * All three are in the URL, so a search is a link — which is the point of having a
 * page rather than a popover. Status defaults to `All` deliberately: the timeline
 * defaults to unread because it is a queue, but you search for something you
 * remember reading at least as often as for something you haven't.
 */
export function SearchFilters({ scope, status, sort, onScope, onStatus, onSort }: SearchFiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-1 border-b px-3 py-2 sm:px-4">
      <SearchScopeMenu scope={scope} onChange={onScope} />
      <span className="mx-1 h-4 w-px bg-border" />
      {STATUSES.map((s) => (
        <SearchFilterChip
          key={s.label}
          icon={s.icon}
          label={s.label}
          active={status === s.value}
          onClick={() => onStatus(s.value)}
        />
      ))}
      <SearchFilterChip
        className="ml-auto"
        icon={sort === 'recent' ? Clock : ArrowDownWideNarrow}
        label={sort === 'recent' ? 'Newest' : 'Relevance'}
        // A two-state toggle rather than a menu: with only two orders, a dropdown
        // costs a click to say what the button already says.
        title={
          sort === 'recent' ? 'Sorted newest first — switch to relevance' : 'Sorted by relevance — switch to newest'
        }
        onClick={() => onSort(sort === 'recent' ? 'relevance' : 'recent')}
      />
    </div>
  );
}
