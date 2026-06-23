import { ChannelAvatar } from '@/components/ChannelAvatar';
import type { ChannelSummary } from '@/hooks/useChannelFilter';
import { cn } from '@/lib/utils';

interface ChannelFilterOptionProps {
  channel: ChannelSummary;
  /** True when this channel is currently hidden (off-state: dimmed avatar + muted name). */
  off: boolean;
  onToggle: (id: number) => void;
}

/** One row in the channel-filter dropdown: avatar + name + message count, toggles visibility. */
export function ChannelFilterOption({ channel, off, onToggle }: ChannelFilterOptionProps) {
  return (
    <button
      type="button"
      onClick={() => onToggle(channel.id)}
      aria-pressed={!off}
      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent"
    >
      <ChannelAvatar
        channelId={channel.id}
        name={channel.name}
        className={cn('size-6 text-[11px] transition-opacity', off && 'opacity-30')}
      />
      <span className={cn('flex-1 truncate', off && 'text-muted-foreground')}>{channel.name}</span>
      <span className="shrink-0 tabular-nums text-xs text-muted-foreground">{channel.count}</span>
    </button>
  );
}
