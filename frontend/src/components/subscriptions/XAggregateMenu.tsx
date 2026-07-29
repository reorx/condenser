import { Check, ChevronDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { X_AGGREGATE_MODES, useSetXAggregate, xAggregateLabel } from '@/hooks/useXAggregate';
import type { XAggregateMode } from '@/lib/types';

/** How much of For You joins the aggregate timeline (`HnDisplayModeMenu`'s sibling).
 *
 *  For You alone is a firehose, which is why it was kept out of the main timeline
 *  entirely. Filtering by the verdict changes that: only the recommended tweets
 *  come through, which is a fifth more reading rather than a flood. A setting and
 *  not a constant, because the right answer tracks how good the classifier is —
 *  and that moves with every label. */
export function XAggregateMenu({ mode }: { mode: XAggregateMode }) {
  const setMode = useSetXAggregate();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1 px-2 text-xs text-muted-foreground"
          disabled={setMode.isPending}
          title="For You 有多少并入主时间线"
        >
          {xAggregateLabel(mode)}
          <ChevronDown className="size-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-w-72">
        <DropdownMenuLabel className="text-xs text-muted-foreground">并入主时间线</DropdownMenuLabel>
        {X_AGGREGATE_MODES.map((m) => (
          <DropdownMenuItem
            key={m.value}
            className="items-start"
            onSelect={() => m.value !== mode && setMode.mutate(m.value)}
          >
            <Check className={m.value === mode ? 'mt-0.5 size-4' : 'mt-0.5 size-4 opacity-0'} />
            <span className="flex flex-col gap-0.5">
              <span>{m.label}</span>
              <span className="text-xs text-muted-foreground">{m.hint}</span>
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
