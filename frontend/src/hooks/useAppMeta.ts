import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';

/** Runtime app settings (GET /api/app/meta): schema version, backfill window, forward channel. */
export function useAppMeta() {
  return useQuery({
    queryKey: ['app-meta'],
    queryFn: () => api.getAppMeta(),
    staleTime: 60_000,
  });
}

/** Save the forward target channel; '' clears it (reads back as null). */
export function useSetForwardChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (forwardChannel: string) => api.patchAppMeta({ forward_channel: forwardChannel }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['app-meta'] }),
    onError: (e) => toast.error(errorMessage(e, 'Could not save forward channel')),
  });
}

/** Save the global language whitelist; [] clears it (= filter nothing). */
export function useSetLanguages() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (languages: string[]) => api.patchAppMeta({ languages }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['app-meta'] }),
    onError: (e) => toast.error(errorMessage(e, 'Could not save languages')),
  });
}
