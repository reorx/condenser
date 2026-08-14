import { Check, ChevronDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  HN_DISPLAY_MODES,
  HN_MAX_PEAK_RANKS,
  HN_MIN_SCORES,
  hnModeLabel,
  hnRulesSummary,
  useSetHnFeedRules,
  type HnFeedRules,
} from '@/hooks/useHnFeedRules';
import type { HnFeedConfig } from '@/lib/types';

/** Which HN stories reach the timeline: the day quota plus the two floors that
 *  keep an unformed day from admitting anything with a pulse (see `useHnFeedRules`).
 *
 *  One trigger rather than three, because the header has to fit on a phone — and
 *  because the day quota is the knob you actually change while the floors are set
 *  once. The trigger keeps showing the quota; the tooltip names all three. */
export function HnFeedRulesMenu({ rules }: { rules: HnFeedRules }) {
  const setRules = useSetHnFeedRules();
  const patch = (key: keyof HnFeedConfig, value: unknown, current: unknown) =>
    value !== current && setRules.mutate({ [key]: value } as Partial<HnFeedConfig>);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1 px-2 text-xs text-muted-foreground"
          disabled={setRules.isPending}
          title={hnRulesSummary(rules)}
        >
          {hnModeLabel(rules.mode)}
          <ChevronDown className="size-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel className="text-xs text-muted-foreground">Stories per day</DropdownMenuLabel>
        {HN_DISPLAY_MODES.map((m) => (
          <RuleOption
            key={m.value}
            label={m.label}
            selected={m.value === rules.mode}
            onSelect={() => patch('display_mode', m.value, rules.mode)}
          />
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs text-muted-foreground">Minimum score</DropdownMenuLabel>
        {HN_MIN_SCORES.map((s) => (
          <RuleOption
            key={s.value}
            label={s.label}
            selected={s.value === rules.minScore}
            onSelect={() => patch('min_score', s.value, rules.minScore)}
          />
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs text-muted-foreground">Front-page peak rank</DropdownMenuLabel>
        {HN_MAX_PEAK_RANKS.map((r) => (
          <RuleOption
            key={r.value}
            label={r.label}
            selected={r.value === rules.maxPeakRank}
            onSelect={() => patch('max_peak_rank', r.value, rules.maxPeakRank)}
          />
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function RuleOption({ label, selected, onSelect }: { label: string; selected: boolean; onSelect: () => void }) {
  return (
    <DropdownMenuItem onSelect={onSelect}>
      <Check className={selected ? 'size-4' : 'size-4 opacity-0'} />
      {label}
    </DropdownMenuItem>
  );
}
