import { Filter, type LucideIcon } from 'lucide-react';

import { ChannelFilterOption } from '@/components/ChannelFilterOption';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { ChannelSummary } from '@/hooks/useChannelFilter';
import { cn } from '@/lib/utils';

interface ChannelFilterProps {
  channels: ChannelSummary[];
  hidden: Set<number>;
  onToggle: (id: number) => void;
  onClear: () => void;
  /** Extra classes for the trigger button (e.g. `ml-auto` in a title bar). */
  className?: string;
}

/**
 * Dropdown over the currently-rendered channels: each row is an avatar + name +
 * message count, and clicking it toggles that channel's visibility. A hidden
 * channel's avatar dims (opacity) to signal the off state.
 */
export function ChannelFilter({ channels, hidden, onToggle, onClear, className }: ChannelFilterProps) {
  const hiddenCount = hidden.size;
  const active = hiddenCount > 0;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          aria-label={active ? `Filter channels, ${hiddenCount} hidden` : 'Filter channels'}
          className={cn(
            'h-6 gap-1 px-1.5 text-xs font-medium',
            active ? 'text-foreground' : 'text-muted-foreground',
            className,
          )}
        >
          <Filter className="size-3.5" />
          {active && <span className="tabular-nums">{hiddenCount}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-60 p-1">
        <div className="max-h-80 space-y-0.5 overflow-y-auto">
          {channels.map((c) => (
            <ChannelFilterOption key={c.id} channel={c} off={hidden.has(c.id)} onToggle={onToggle} />
          ))}
        </div>
        {active && (
          <div className="mt-1 border-t pt-1">
            <Button variant="ghost" size="sm" className="h-7 w-full justify-center text-xs" onClick={onClear}>
              Show all
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

/** Empty state shown when every channel in the current view is toggled off. */
export function AllChannelsHidden({ icon: Icon, onClear }: { icon: LucideIcon; onClear: () => void }) {
  return (
    <div className="flex flex-col items-center gap-2 py-24 text-center text-muted-foreground">
      <Icon className="size-8" />
      <p className="text-sm">
        All channels are hidden by the filter.{' '}
        <button type="button" className="underline" onClick={onClear}>
          Show all
        </button>
      </p>
    </div>
  );
}
