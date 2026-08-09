import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { findItem, patchItem } from '@/lib/itemCaches';
import type { ItemFeedback, ItemFeedbackReason } from '@/lib/types';

type Verdict = ItemFeedback | null;
type Reason = ItemFeedbackReason | null;
/** The label is both halves at once — the reason belongs to the verdict it explains,
 *  so they are cached, rolled back and cleared together. */
type Label = { feedback: Verdict; feedback_reason: Reason };

const CLEARED: Label = { feedback: null, feedback_reason: null };

/** The label currently on screen, so a failed write can be put back exactly. */
function currentLabel(qc: ReturnType<typeof useQueryClient>, key: string): Label {
  const item = findItem(qc, key);
  return { feedback: item?.feedback ?? null, feedback_reason: item?.feedback_reason ?? null };
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
      patchItem(qc, key, { feedback: verdict, feedback_reason: verdict ? reason : null });
      return { previous };
    },
    onError: (_e, { key }, ctx) => patchItem(qc, key, ctx?.previous ?? CLEARED),
  });
}
