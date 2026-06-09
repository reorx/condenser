import { type QueryClient, useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { DisplayMessage, MsgRef, TimelinePage } from '@/lib/types';

function setSavedOptimistic(qc: QueryClient, ref: MsgRef, saved: boolean) {
  qc.setQueriesData<{ pages: TimelinePage[]; pageParams: unknown[] }>({ queryKey: ['timeline'] }, (data) => {
    if (!data) return data;
    return {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((m: DisplayMessage) =>
          m.channel_id === ref.channel_id && m.id === ref.message_id ? { ...m, is_saved: saved } : m,
        ),
      })),
    };
  });
}

export function useSaveToggle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ref, saved }: { ref: MsgRef; saved: boolean }) =>
      saved ? api.saveRecord(ref) : api.deleteRecord(ref),
    onMutate: ({ ref, saved }) => setSavedOptimistic(qc, ref, saved),
    onError: (_e, { ref, saved }) => setSavedOptimistic(qc, ref, !saved),
    onSettled: () => qc.invalidateQueries({ queryKey: ['records'] }),
  });
}
