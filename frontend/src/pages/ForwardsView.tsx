import { useEffect, useMemo, useRef } from 'react';
import { Repeat2 } from 'lucide-react';

import { ForwardRecordRow } from '@/components/forwards/ForwardRecordRow';
import { IconBadge, PageHeader } from '@/components/PageHeader';
import { Spinner } from '@/components/Spinner';
import { useForwards } from '@/hooks/useForwards';

/**
 * The forward log: which items I published into my own channel, and what I wrote
 * at the time.
 *
 * No channel filter, unlike Saved. This list is ordered by *record* — a row
 * belongs to one act of forwarding rather than to a channel — and its subject is
 * the comment. Chrome stays English like every other view; the row's own copy is
 * Chinese, like `ForwardDialog` and the detail pane it is written next to.
 */
export function ForwardsView() {
  const query = useForwards();
  const entries = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);

  // Infinite scroll: same sentinel + rootMargin as SearchResults.
  const sentinel = useRef<HTMLDivElement | null>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query;
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (es) => {
        if (es[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: '600px 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return (
    <>
      <PageHeader icon={<IconBadge icon={<Repeat2 className="size-5 text-sky-500" />} />} title="Forwards" />

      {query.isPending && (
        <div className="flex justify-center py-16">
          <Spinner className="size-5 text-muted-foreground" />
        </div>
      )}

      {query.isError && (
        <div className="flex flex-col items-center gap-3 py-16 text-sm text-muted-foreground">
          <p>Failed to load forward records.</p>
          <button className="underline" onClick={() => query.refetch()}>
            Retry
          </button>
        </div>
      )}

      {query.data && entries.length === 0 && (
        <div className="flex flex-col items-center gap-2 py-24 text-center text-muted-foreground">
          <Repeat2 className="size-8" />
          <p className="text-sm">Nothing forwarded yet. Use 转发 in an item&apos;s detail pane and it lands here.</p>
        </div>
      )}

      {entries.length > 0 && (
        <div>
          <div className="divide-y divide-border/50">
            {entries.map((entry) => (
              <ForwardRecordRow key={entry.record.id} entry={entry} />
            ))}
          </div>
          <div ref={sentinel} />
          {query.isFetchingNextPage && (
            <div className="flex justify-center py-6">
              <Spinner className="text-muted-foreground" />
            </div>
          )}
          {!query.hasNextPage && <p className="py-8 text-center text-xs text-muted-foreground">End of records</p>}
        </div>
      )}
    </>
  );
}
