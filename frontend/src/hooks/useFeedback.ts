import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ItemFeedback, TimelineItem, TimelinePage } from '@/lib/types';

type Verdict = ItemFeedback | null;

/** Both surfaces an X card can appear on: the paged timelines and the saved list. */
function applyFeedback(qc: QueryClient, key: string, feedback: Verdict) {
  qc.setQueriesData<{ pages: TimelinePage[]; pageParams: unknown[] }>({ queryKey: ['timeline'] }, (data) => {
    if (!data) return data;
    return {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((it: TimelineItem) => (it.key === key ? { ...it, feedback } : it)),
      })),
    };
  });
  qc.setQueryData<TimelineItem[]>(['records'], (items) =>
    items?.map((it) => (it.key === key ? { ...it, feedback } : it)),
  );
}

/** The label currently in cache, so a failed write can be put back exactly. */
function currentFeedback(qc: QueryClient, key: string): Verdict {
  const caches = qc.getQueriesData<{ pages: TimelinePage[] }>({ queryKey: ['timeline'] });
  for (const [, data] of caches) {
    for (const page of data?.pages ?? []) {
      const hit = page.items.find((it) => it.key === key);
      if (hit) return hit.feedback ?? null;
    }
  }
  return qc.getQueryData<TimelineItem[]>(['records'])?.find((it) => it.key === key)?.feedback ?? null;
}

/**
 * Label an item up/down, or clear it (`verdict: null` — clicking the highlighted
 * side again). Phase 3 only records the label: nothing is hidden, ranked or
 * filtered by it, so the optimistic update is a pure in-place field swap and no
 * count query needs invalidating.
 */
export function useFeedback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, verdict }: { key: string; verdict: Verdict }) =>
      verdict ? api.setFeedback(key, verdict) : api.clearFeedback(key),
    onMutate: ({ key, verdict }) => {
      const previous = currentFeedback(qc, key);
      applyFeedback(qc, key, verdict);
      return { previous };
    },
    onError: (_e, { key }, ctx) => applyFeedback(qc, key, ctx?.previous ?? null),
  });
}
