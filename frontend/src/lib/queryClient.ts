import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';

import { ApiError } from './api';

export const TG_STATUS_KEY = ['tg-status'] as const;

function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export const queryClient = new QueryClient({
  // A 401 from any *other* query means the app-password cookie expired mid-session:
  // re-run tg-status so the App falls back to the login screen. We must NOT invalidate
  // when tg-status itself 401s — that would refetch-loop the gate forever. Its own 401
  // is the signal the App reads directly to show the login page.
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (isUnauthorized(error) && query.queryKey[0] !== TG_STATUS_KEY[0]) {
        queryClient.invalidateQueries({ queryKey: TG_STATUS_KEY });
      }
    },
  }),
  mutationCache: new MutationCache({
    onError: (error) => {
      if (isUnauthorized(error)) queryClient.invalidateQueries({ queryKey: TG_STATUS_KEY });
    },
  }),
  defaultOptions: {
    queries: {
      retry: false,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
  },
});
