import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { TimelineItem, TimelinePage } from '@/lib/types';

function setSavedOptimistic(qc: QueryClient, key: string, saved: boolean) {
  qc.setQueriesData<{ pages: TimelinePage[]; pageParams: unknown[] }>({ queryKey: ['timeline'] }, (data) => {
    if (!data) return data;
    return {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((it: TimelineItem) => (it.key === key ? { ...it, is_saved: saved } : it)),
      })),
    };
  });
}

export function useSaveToggle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, saved }: { key: string; saved: boolean }) =>
      saved ? api.saveRecord(key) : api.deleteRecord(key),
    onMutate: ({ key, saved }) => setSavedOptimistic(qc, key, saved),
    onError: (_e, { key, saved }) => setSavedOptimistic(qc, key, !saved),
    onSettled: () => qc.invalidateQueries({ queryKey: ['records'] }),
  });
}
