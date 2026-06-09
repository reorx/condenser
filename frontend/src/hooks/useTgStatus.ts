import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { TG_STATUS_KEY } from '@/lib/queryClient';

/** Drives the whole auth gate: a 401 here means "not app-authed". */
export function useTgStatus() {
  return useQuery({
    queryKey: TG_STATUS_KEY,
    queryFn: api.tgStatus,
    staleTime: 5_000,
  });
}
