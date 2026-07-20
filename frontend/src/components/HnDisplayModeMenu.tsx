import { Check, ChevronDown } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { HN_DISPLAY_MODES, hnDisplayModeLabel, useSetHnDisplayMode } from '@/hooks/useHnDisplayMode';
import type { HnDisplayMode } from '@/lib/types';

/** Top-N display-mode switcher in the /s/hn header: how many of each archive
 *  day's top stories are visible (top10 / top20 / half / all). */
export function HnDisplayModeMenu({ mode }: { mode: HnDisplayMode }) {
  const setMode = useSetHnDisplayMode();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1 px-2 text-xs text-muted-foreground"
          disabled={setMode.isPending}
          title="How many of each day's top stories to show"
        >
          {hnDisplayModeLabel(mode)}
          <ChevronDown className="size-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel className="text-xs text-muted-foreground">Stories per day</DropdownMenuLabel>
        {HN_DISPLAY_MODES.map((m) => (
          <DropdownMenuItem key={m.value} onSelect={() => m.value !== mode && setMode.mutate(m.value)}>
            <Check className={m.value === mode ? 'size-4' : 'size-4 opacity-0'} />
            {m.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
