import { useMemo } from 'react';
import { SearchX } from 'lucide-react';

import { Spinner } from '@/components/Spinner';
import { DatedItemRow } from '@/components/timeline/DatedItemRow';
import { Button } from '@/components/ui/button';
import { useInfiniteScrollSentinel } from '@/hooks/useInfiniteScrollSentinel';
import type { SearchQuery } from '@/hooks/useSearch';
import { ApiError } from '@/lib/api';

/**
 * The result list: flat and dated, never grouped by day.
 *
 * Deliberately **not** wired to scroll-to-read. Searching is going through an
 * archive, not working a queue, and scrolling past a five-year-old message
 * looking for a different one is not reading it. Everything else a card offers —
 * save, hide, feedback, the detail pane — works exactly as it does elsewhere.
 */
export function SearchResults({ query }: { query: SearchQuery }) {
  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);

  const sentinel = useInfiniteScrollSentinel(query);

  if (query.isPending) {
    return (
      <div className="flex justify-center py-16">
        <Spinner className="size-5 text-muted-foreground" />
      </div>
    );
  }

  if (query.isError) {
    // 422 is not a failure: the box holds only punctuation or emoji, which carry
    // no token to look for. Saying so beats a red "search failed".
    const unsearchable = query.error instanceof ApiError && query.error.status === 422;
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-sm text-muted-foreground">
        <p>{unsearchable ? 'Nothing searchable in that query.' : 'Search failed.'}</p>
        {!unsearchable && (
          <Button variant="outline" size="sm" onClick={() => query.refetch()}>
            Retry
          </Button>
        )}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-24 text-center text-muted-foreground">
        <SearchX className="size-8" />
        <p className="text-sm">No matches. Try fewer words, or widen the filters.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="divide-y divide-border/50">
        {items.map((it) => (
          <DatedItemRow key={it.key} item={it} />
        ))}
      </div>
      <div ref={sentinel} />
      {query.isFetchingNextPage && (
        <div className="flex justify-center py-6">
          <Spinner className="text-muted-foreground" />
        </div>
      )}
      {!query.hasNextPage && <p className="py-8 text-center text-xs text-muted-foreground">End of results</p>}
    </div>
  );
}
