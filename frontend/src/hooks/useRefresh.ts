import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';

/** Synchronously re-pull one channel's recent window, then surface fetched count + refresh views. */
export function useRefreshChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (channelId: number) => api.tgRefreshChannel(channelId),
    onSuccess: (res) => {
      toast.success(res.new > 0 ? `Fetched ${res.new} new ${res.new === 1 ? 'post' : 'posts'}` : 'Up to date');
      qc.invalidateQueries({ queryKey: ['timeline'] });
      qc.invalidateQueries({ queryKey: ['timeline-days'] });
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['sources'] });
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not refresh channel')),
  });
}

/** Page further back into one channel's history, then refresh the views that show it. */
export function useFetchOlder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, count }: { channelId: number; count?: number }) => api.tgFetchOlder(channelId, count),
    onSuccess: (res) => {
      toast.success(
        res.fetched > 0
          ? `Fetched ${res.fetched} older ${res.fetched === 1 ? 'post' : 'posts'}`
          : 'No older posts to fetch',
      );
      qc.invalidateQueries({ queryKey: ['timeline'] });
      qc.invalidateQueries({ queryKey: ['timeline-days'] });
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['sources'] });
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not fetch older posts')),
  });
}

/** Destructive: wipe one channel's cached messages + read state, then re-sync from scratch. */
export function useResetChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (channelId: number) => api.tgResetChannel(channelId),
    onSuccess: (res) => {
      toast.success(`Reset done — re-synced ${res.fetched} ${res.fetched === 1 ? 'post' : 'posts'}`);
      qc.invalidateQueries({ queryKey: ['timeline'] });
      qc.invalidateQueries({ queryKey: ['timeline-days'] });
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['sources'] });
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not reset channel')),
  });
}

/** Kick off a background re-pull across all enabled channels; results surface via the new-content poll. */
export function useRefreshAll() {
  return useMutation({
    mutationFn: () => api.tgRefreshAll(),
    onSuccess: (res) =>
      toast.success(
        `Refreshing ${res.channels} ${res.channels === 1 ? 'channel' : 'channels'} in the background — new posts appear shortly`,
      ),
    onError: (e) => toast.error(errorMessage(e, 'Could not start refresh')),
  });
}
