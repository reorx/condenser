import { useEffect, useRef } from 'react';

/**
 * Infinite scroll for a paged list: hang the returned ref on a sentinel div at
 * the list's tail, and the next page loads when it nears the viewport.
 *
 * One hook because the tuning must not drift between the paged views (timeline,
 * search, forwards) — the same rootMargin and the same in-flight guard, or one
 * view starts double-fetching while another prefetches a screen later.
 */
export function useInfiniteScrollSentinel(query: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  fetchNextPage: () => unknown;
}) {
  const sentinel = useRef<HTMLDivElement | null>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query;
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: '600px 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  return sentinel;
}
