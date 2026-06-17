import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';

export function useFilters(channelId: number, enabled = true) {
  return useQuery({
    queryKey: ['filters', channelId],
    queryFn: () => api.listFilters(channelId),
    enabled,
  });
}

/** Adding/removing a rule makes the backend recompute is_filtered, so the timeline
 *  (and unread counts) must be refetched alongside the filter list. */
function useFilterInvalidation(channelId: number) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ['filters', channelId] });
    qc.invalidateQueries({ queryKey: ['timeline'] });
    qc.invalidateQueries({ queryKey: ['subscriptions'] });
  };
}

export function useAddFilter(channelId: number) {
  const invalidate = useFilterInvalidation(channelId);
  return useMutation({
    mutationFn: (pattern: string) => api.addFilter(channelId, pattern),
    onSuccess: invalidate,
    onError: (e) => toast.error(errorMessage(e, 'Could not add keyword')),
  });
}

export function useDeleteFilter(channelId: number) {
  const invalidate = useFilterInvalidation(channelId);
  return useMutation({
    mutationFn: (filterId: number) => api.deleteFilter(filterId),
    onSuccess: invalidate,
    onError: (e) => toast.error(errorMessage(e, 'Could not remove keyword')),
  });
}
