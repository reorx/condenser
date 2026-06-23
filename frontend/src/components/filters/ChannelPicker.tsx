import { useMemo, useState } from 'react';
import { ChevronsUpDown, Search } from 'lucide-react';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { channelName } from '@/lib/format';
import type { Subscription } from '@/lib/types';

import { ChannelPickerOption } from './ChannelPickerOption';

interface ChannelPickerProps {
  subs: Subscription[];
  selected: number | null;
  onSelect: (id: number) => void;
}

/** Searchable dropdown for picking a single channel to scope a filter to. */
export function ChannelPicker({ subs, selected, onSelect }: ChannelPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');

  const enabled = useMemo(() => subs.filter((s) => s.enabled), [subs]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return enabled;
    return enabled.filter(
      (c) => (c.title ?? '').toLowerCase().includes(q) || (c.username ?? '').toLowerCase().includes(q),
    );
  }, [enabled, search]);

  const selectedSub = selected != null ? enabled.find((s) => s.channel_id === selected) : undefined;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" className="w-full justify-between font-normal">
          {selectedSub ? (
            <span className="flex items-center gap-2">
              <ChannelAvatar
                channelId={selectedSub.channel_id}
                name={channelName(selectedSub)}
                className="size-5 text-[10px]"
              />
              <span className="truncate">{channelName(selectedSub)}</span>
            </span>
          ) : (
            <span className="text-muted-foreground">Select a channel…</span>
          )}
          <ChevronsUpDown className="size-4 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[--radix-popover-trigger-width] p-0"
        align="start"
        onOpenAutoFocus={(e) => {
          // Keep focus on the search input we render below.
          e.preventDefault();
        }}
      >
        <div className="border-b p-2">
          <div className="relative">
            <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search channels…"
              className="pl-8"
            />
          </div>
        </div>
        <div className="max-h-64 overflow-y-auto p-1">
          {filtered.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No channels match.</p>
          ) : (
            filtered.map((s) => (
              <ChannelPickerOption
                key={s.channel_id}
                sub={s}
                selected={s.channel_id === selected}
                onSelect={(id) => {
                  onSelect(id);
                  setOpen(false);
                }}
              />
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
