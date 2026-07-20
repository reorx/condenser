import type { UseMutationOptions } from '@tanstack/react-query';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';

export function useAllFilters() {
  return useQuery({
    queryKey: ['filters-all'],
    queryFn: () => api.listAllFilters(),
  });
}

/** Adding/removing a rule recomputes is_filtered server-side, so timeline +
 *  subscription counts must refetch alongside the filter list. */
function useFilterInvalidation() {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ['filters-all'] });
    qc.invalidateQueries({ queryKey: ['timeline'] });
    qc.invalidateQueries({ queryKey: ['subscriptions'] });
    qc.invalidateQueries({ queryKey: ['sources'] });
  };
}

export function useCreateFilter() {
  const invalidate = useFilterInvalidation();
  return useMutation({
    mutationFn: ({ pattern, channelId }: { pattern: string; channelId: number | null }) =>
      api.createFilter(pattern, channelId),
    onSuccess: invalidate,
    onError: (e) => toast.error(errorMessage(e, 'Could not create filter')),
  });
}

type DeleteOptions = Pick<UseMutationOptions<{ ok: true }, Error, number>, 'onMutate' | 'onSettled'>;

export function useDeleteFilter(options: DeleteOptions = {}) {
  const invalidate = useFilterInvalidation();
  return useMutation({
    mutationFn: (filterId: number) => api.deleteFilter(filterId),
    onSuccess: invalidate,
    onError: (e) => toast.error(errorMessage(e, 'Could not remove filter')),
    ...options,
  });
}
