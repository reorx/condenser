import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';
import type { HnDisplayMode, SourceGroup } from '@/lib/types';

export const HN_DISPLAY_MODES: { value: HnDisplayMode; label: string }[] = [
  { value: 'top10', label: 'Top 10' },
  { value: 'top20', label: 'Top 20' },
  { value: 'half', label: 'Top half' },
  { value: 'all', label: 'All' },
];

const DEFAULT_MODE: HnDisplayMode = 'top20';

/** Short label for a mode value (dropdown trigger text). */
export function hnDisplayModeLabel(mode: HnDisplayMode): string {
  return HN_DISPLAY_MODES.find((m) => m.value === mode)?.label ?? mode;
}

/** Coerce a stored config value to a known mode (backend default: top20). */
export function asHnDisplayMode(v: unknown): HnDisplayMode {
  return typeof v === 'string' && HN_DISPLAY_MODES.some((m) => m.value === v) ? (v as HnDisplayMode) : DEFAULT_MODE;
}

/** The front feed's display mode from the /api/sources cache. */
export function hnDisplayModeOf(sources: SourceGroup[] | undefined): HnDisplayMode {
  const front = sources?.find((g) => g.source === 'hn')?.subscriptions.find((s) => s.channel_id === 'front');
  return asHnDisplayMode(front?.config?.display_mode);
}

/** PATCH the front feed's display mode; the visible top-N set (and unread counts)
 *  are query-time on the backend, so everything derived must refetch. */
export function useSetHnDisplayMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mode: HnDisplayMode) => api.hnSetConfig({ display_mode: mode }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sources'] });
      qc.invalidateQueries({ queryKey: ['timeline'] });
      qc.invalidateQueries({ queryKey: ['timeline-days'] });
      qc.invalidateQueries({ queryKey: ['hn-status'] });
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not change the display mode')),
  });
}
