import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ItemFeedback, ItemFeedbackReason, TimelineItem, TimelinePage } from '@/lib/types';

type Verdict = ItemFeedback | null;
type Reason = ItemFeedbackReason | null;
/** The label is both halves at once — the reason belongs to the verdict it explains,
 *  so they are cached, rolled back and cleared together. */
type Label = { feedback: Verdict; feedback_reason: Reason };

/** Both surfaces an X card can appear on: the paged timelines and the saved list. */
function applyFeedback(qc: QueryClient, key: string, label: Label) {
  qc.setQueriesData<{ pages: TimelinePage[]; pageParams: unknown[] }>({ queryKey: ['timeline'] }, (data) => {
    if (!data) return data;
    return {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((it: TimelineItem) => (it.key === key ? { ...it, ...label } : it)),
      })),
    };
  });
  qc.setQueryData<TimelineItem[]>(['records'], (items) =>
    items?.map((it) => (it.key === key ? { ...it, ...label } : it)),
  );
}

/** The label currently in cache, so a failed write can be put back exactly. */
function currentLabel(qc: QueryClient, key: string): Label {
  const caches = qc.getQueriesData<{ pages: TimelinePage[] }>({ queryKey: ['timeline'] });
  for (const [, data] of caches) {
    for (const page of data?.pages ?? []) {
      const hit = page.items.find((it) => it.key === key);
      if (hit) return { feedback: hit.feedback ?? null, feedback_reason: hit.feedback_reason ?? null };
    }
  }
  const saved = qc.getQueryData<TimelineItem[]>(['records'])?.find((it) => it.key === key);
  return { feedback: saved?.feedback ?? null, feedback_reason: saved?.feedback_reason ?? null };
}

/**
 * Label an item up/down with an optional reason chip, or clear it (`verdict: null` —
 * clicking the highlighted side again). Phase 3 only records the label: nothing is
 * hidden, ranked or filtered by it, so the optimistic update is a pure in-place field
 * swap and no count query needs invalidating.
 */
export function useFeedback() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, verdict, reason = null }: { key: string; verdict: Verdict; reason?: Reason }) =>
      verdict ? api.setFeedback(key, verdict, reason) : api.clearFeedback(key),
    onMutate: ({ key, verdict, reason = null }) => {
      const previous = currentLabel(qc, key);
      applyFeedback(qc, key, { feedback: verdict, feedback_reason: verdict ? reason : null });
      return { previous };
    },
    onError: (_e, { key }, ctx) => applyFeedback(qc, key, ctx?.previous ?? { feedback: null, feedback_reason: null }),
  });
}
