import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';
import type { HnDisplayMode, HnFeedConfig, SourceGroup } from '@/lib/types';

/** Which stories reach the timeline. Three independent knobs on one config blob:
 *
 *  - `mode` — how many of a day's top stories are shown. A *relative* bar, and it
 *    does not exist at the start of a UTC day: nine rows in the partition make
 *    "top 10" mean "everything", and UTC midnight is 08:00 Beijing.
 *  - `minScore` — the absolute floor for exactly that window. A mature day cuts
 *    at 243-476 points, so it never binds there.
 *  - `maxPeakRank` — the best front-page position the story ever reached, aimed at
 *    the second-chance-pool repost. **Off by default**: measured on production it
 *    only ever caught stories the score floor had already taken, plus three of the
 *    archive's biggest hits, because peak_rank is the best rank we *sampled* and a
 *    story whose peak falls in a sampling gap is recorded on its way down.
 *
 *  Defaults mirror `condenser/sources/hn.py`, which is the authority — the two
 *  only meet on a subscription row that predates the floors, where the server
 *  fills them in and the menu must show the same thing.
 */
export type HnFeedRules = {
  mode: HnDisplayMode;
  minScore: number; // 0 = off
  maxPeakRank: number; // 0 = off
};

type Option<T> = { value: T; label: string };

export const HN_DISPLAY_MODES: Option<HnDisplayMode>[] = [
  { value: 'top10', label: 'Top 10' },
  { value: 'top20', label: 'Top 20' },
  { value: 'half', label: 'Top half' },
  { value: 'all', label: 'All' },
];

export const HN_MIN_SCORES: Option<number>[] = [
  { value: 0, label: 'No minimum' },
  { value: 30, label: '≥ 30' },
  { value: 50, label: '≥ 50' },
  { value: 100, label: '≥ 100' },
  { value: 150, label: '≥ 150' },
];

export const HN_MAX_PEAK_RANKS: Option<number>[] = [
  { value: 0, label: 'Any rank' },
  { value: 10, label: '#10 or better' },
  { value: 20, label: '#20 or better' },
  { value: 30, label: '#30 or better' },
];

const DEFAULTS: HnFeedRules = { mode: 'top20', minScore: 50, maxPeakRank: 0 };

function asMode(v: unknown): HnDisplayMode {
  return typeof v === 'string' && HN_DISPLAY_MODES.some((m) => m.value === v) ? (v as HnDisplayMode) : DEFAULTS.mode;
}

/** A stored floor, or its default. An absent key means "written before the floor
 *  existed" and must read as armed; only an explicit 0 turns one off. */
function asFloor(v: unknown, fallback: number): number {
  return typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : fallback;
}

export function hnFeedRules(config: HnFeedConfig | Record<string, unknown> | null | undefined): HnFeedRules {
  return {
    mode: asMode(config?.display_mode),
    minScore: asFloor(config?.min_score, DEFAULTS.minScore),
    maxPeakRank: asFloor(config?.max_peak_rank, DEFAULTS.maxPeakRank),
  };
}

/** The front feed's rules from the /api/sources cache. */
export function hnFeedRulesOf(sources: SourceGroup[] | undefined): HnFeedRules {
  const front = sources?.find((g) => g.source === 'hn')?.subscriptions.find((s) => s.channel_id === 'front');
  return hnFeedRules(front?.config);
}

function labelOf<T>(options: Option<T>[], value: T): string {
  return options.find((o) => o.value === value)?.label ?? String(value);
}

export function hnModeLabel(mode: HnDisplayMode): string {
  return labelOf(HN_DISPLAY_MODES, mode);
}

/** One line naming all three rules — the trigger shows only the day quota, so
 *  this is where the floors stay visible without costing header width. */
export function hnRulesSummary(rules: HnFeedRules): string {
  const parts = [`${hnModeLabel(rules.mode).toLowerCase()} a day`];
  if (rules.minScore > 0) parts.push(`score ≥ ${rules.minScore}`);
  if (rules.maxPeakRank > 0) parts.push(`peaked at #${rules.maxPeakRank} or better`);
  return `Which stories reach the timeline: ${parts.join(' · ')}`;
}

/** PATCH one rule. The server merges into the stored config, so sending a single
 *  key is what keeps the other two — and the admitted set is computed query-time,
 *  so the timeline, the calendar and both unread badges must all refetch. */
export function useSetHnFeedRules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<HnFeedConfig>) => api.hnSetConfig(patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sources'] });
      qc.invalidateQueries({ queryKey: ['timeline'] });
      qc.invalidateQueries({ queryKey: ['timeline-days'] });
      qc.invalidateQueries({ queryKey: ['hn-status'] });
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not change the story rules')),
  });
}
