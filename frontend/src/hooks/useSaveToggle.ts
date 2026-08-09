import { useMutation, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { patchItem } from '@/lib/itemCaches';

export function useSaveToggle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, saved }: { key: string; saved: boolean }) =>
      saved ? api.saveRecord(key) : api.deleteRecord(key),
    onMutate: ({ key, saved }) => patchItem(qc, key, { is_saved: saved }),
    onError: (_e, { key, saved }) => patchItem(qc, key, { is_saved: !saved }),
    onSettled: () => qc.invalidateQueries({ queryKey: ['records'] }),
  });
}
