import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';
import type { XAggregateMode } from '@/lib/types';

/** How much of For You reaches the aggregate timeline.
 *
 *  For You was kept out of the main timeline entirely because it re-samples on
 *  every probe call — a firehose that would bury Telegram and HN. The verdict
 *  changes that arithmetic: only ~13% of arrivals are judged positive, which is
 *  roughly a fifth added to the aggregate rather than a flood. It stays a setting
 *  rather than a constant because the right answer depends on how good the
 *  classifier currently is, and that moves with every label. */
export const X_AGGREGATE_MODES: { value: XAggregateMode; label: string; hint: string }[] = [
  { value: 'none', label: '不进主时间线', hint: '只在 X 视图里看 For You' },
  { value: 'positive', label: '只进推荐的', hint: '判定为「推荐」的推文并入 All / Unread' },
  { value: 'all', label: '全部并入', hint: '整个 For You 并入主时间线' },
];

export function xAggregateLabel(mode: XAggregateMode): string {
  return X_AGGREGATE_MODES.find((m) => m.value === mode)?.label ?? mode;
}

/** PATCH the For You feed's aggregate mode. The admitted set is query-time on the
 *  backend, so the timeline, the calendar and both unread badges all derive from
 *  it and must refetch. */
export function useSetXAggregate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mode: XAggregateMode) => api.xSetConfig('foryou', { aggregate: mode }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sources'] });
      qc.invalidateQueries({ queryKey: ['x-subscriptions'] });
      qc.invalidateQueries({ queryKey: ['timeline'] });
      qc.invalidateQueries({ queryKey: ['timeline-days'] });
    },
    onError: (e) => toast.error(errorMessage(e, '没能修改 For You 的并入方式')),
  });
}
