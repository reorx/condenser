import { useMemo } from 'react';
import { Calendar as CalendarIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useTimelineDays } from '@/hooks/useTimelineDays';
import { dayKeyLabel, fromDayKey, toDayKey } from '@/lib/format';
import type { Source } from '@/lib/types';
import { cn } from '@/lib/utils';

interface CalendarPopoverProps {
  channelId: number | null;
  date: string | null;
  onSelect: (date: string | null) => void;
  /** Scope the day counts to one source (the /s/:source views). */
  source?: Source | null;
  /** Scope further to one feed of a multi-feed source (the /s/x/:feed views). */
  feed?: string | null;
}

export function CalendarPopover({ channelId, date, onSelect, source, feed }: CalendarPopoverProps) {
  const { data: days } = useTimelineDays(channelId, true, source ?? null, feed ?? null);
  const daySet = useMemo(() => new Set((days ?? []).map((d) => d.date)), [days]);

  const selected = date ? fromDayKey(date) : undefined;
  const defaultMonth = selected ?? (days && days[0] ? fromDayKey(days[0].date) : undefined);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant={date ? 'default' : 'ghost'}
          size="icon"
          className={cn('size-8', !date && 'text-muted-foreground')}
          title={date ? `Filtered to ${dayKeyLabel(date)}` : 'Filter by date'}
        >
          <CalendarIcon className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="end">
        <Calendar
          mode="single"
          selected={selected}
          defaultMonth={defaultMonth}
          onSelect={(d) => onSelect(d ? toDayKey(d) : null)}
          disabled={(d) => !daySet.has(toDayKey(d))}
        />
        {date && (
          <div className="border-t p-2">
            <Button variant="ghost" size="sm" className="w-full" onClick={() => onSelect(null)}>
              Clear date
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
