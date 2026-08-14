import { Check, ChevronDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useSetXAggregate, xAggregateLabel, xAggregateModes } from '@/hooks/useXAggregate';
import { xFeedLabel } from '@/lib/sources';
import type { XAggregateMode } from '@/lib/types';

/** How much of a synthetic X feed joins the aggregate timeline (`HnFeedRulesMenu`'s
 *  sibling).
 *
 *  For You alone is a firehose, which is why it was kept out of the main timeline
 *  entirely. Filtering by the verdict changes that: only the recommended tweets
 *  come through, which is a fifth more reading rather than a flood. A setting and
 *  not a constant, because the right answer tracks how good the classifier is —
 *  and that moves with every label. Following gets the same control with a shorter
 *  option list (it is never judged, so there is nothing to recommend). */
export function XAggregateMenu({ feed, mode }: { feed: string; mode: XAggregateMode }) {
  const setMode = useSetXAggregate(feed);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1 px-2 text-xs text-muted-foreground"
          disabled={setMode.isPending}
          title={`${xFeedLabel(feed)} 有多少并入主时间线`}
        >
          {xAggregateLabel(feed, mode)}
          <ChevronDown className="size-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-w-72">
        <DropdownMenuLabel className="text-xs text-muted-foreground">并入主时间线</DropdownMenuLabel>
        {xAggregateModes(feed).map((m) => (
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
