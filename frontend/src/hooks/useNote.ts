import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { findItem, patchItem } from '@/lib/itemCaches';

/**
 * Set/overwrite an item's note (schema v18). Whole-text overwrite semantics: ''
 * clears, which is also the delete — no separate endpoint. Optimistic in-place
 * swap across every item cache (useFeedback's arrangement), rolled back from the
 * pre-click value. `['records']` is invalidated because a first note creates the
 * saved-items row (unsaved) and clearing the last writing drops it — the Saved
 * view's list membership can change either way.
 */
export function useNote() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, note }: { key: string; note: string }) => api.setNote(key, note),
    onMutate: ({ key, note }) => {
      const previous = findItem(qc, key)?.note ?? null;
      patchItem(qc, key, { note: note || null });
      return { previous };
    },
    onError: (_e, { key }, ctx) => patchItem(qc, key, { note: ctx?.previous ?? null }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['records'] }),
  });
}
