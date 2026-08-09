import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { invalidateItemLists, removeItem } from '@/lib/itemCaches';

function invalidateCounts(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: ['sources'] });
  qc.invalidateQueries({ queryKey: ['subscriptions'] });
  qc.invalidateQueries({ queryKey: ['timeline-days'] });
}

/** Hide an item from the timeline for good (server-enforced, so iOS stops seeing it too). */
export function useHideItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => api.hideItem(key),
    onMutate: (key) => removeItem(qc, key),
    // The optimistic removal can't be restored positionally; refetch instead.
    onError: () => invalidateItemLists(qc),
    onSettled: () => invalidateCounts(qc),
  });
}

/** Undo a hide (the toast's 撤销 action); refetches so the item reappears in place. */
export function useUnhideItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) => api.unhideItem(key),
    onSettled: () => {
      invalidateItemLists(qc);
      invalidateCounts(qc);
    },
  });
}
