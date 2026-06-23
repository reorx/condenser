import { Check } from 'lucide-react';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { channelName } from '@/lib/format';
import type { Subscription } from '@/lib/types';
import { cn } from '@/lib/utils';

interface ChannelPickerOptionProps {
  sub: Subscription;
  selected: boolean;
  /** Called with the channel id; the picker also closes its popover on select. */
  onSelect: (id: number) => void;
}

/** One channel row inside the create-filter channel picker. */
export function ChannelPickerOption({ sub, selected, onSelect }: ChannelPickerOptionProps) {
  return (
    <button
      type="button"
      onClick={() => onSelect(sub.channel_id)}
      className={cn(
        'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent',
        selected && 'bg-accent',
      )}
    >
      <ChannelAvatar channelId={sub.channel_id} name={channelName(sub)} className="size-5 text-[10px]" />
      <span className="truncate">{channelName(sub)}</span>
      {selected && <Check className="ml-auto size-4 text-primary" />}
    </button>
  );
}
