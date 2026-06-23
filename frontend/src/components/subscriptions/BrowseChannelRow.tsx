import { Check } from 'lucide-react';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { channelName } from '@/lib/format';
import type { JoinedChannel } from '@/lib/types';
import { cn } from '@/lib/utils';

interface BrowseChannelRowProps {
  channel: JoinedChannel;
  selected: boolean;
  onToggle: (id: number) => void;
}

/** A selectable channel row in the "Browse my channels" dialog. */
export function BrowseChannelRow({ channel, selected, onToggle }: BrowseChannelRowProps) {
  return (
    <li>
      <button
        type="button"
        disabled={channel.subscribed}
        onClick={() => onToggle(channel.channel_id)}
        className={cn(
          'flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors',
          channel.subscribed ? 'cursor-default opacity-60' : 'hover:bg-accent/60',
          selected && 'bg-accent',
        )}
      >
        <ChannelAvatar channelId={channel.channel_id} name={channelName(channel)} className="size-8" letterOnly />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{channelName(channel)}</div>
          {channel.username && <div className="truncate text-xs text-muted-foreground">@{channel.username}</div>}
        </div>
        {channel.unread > 0 && (
          <span
            className="shrink-0 rounded-full bg-muted px-1.5 text-[11px] tabular-nums text-muted-foreground"
            title={`${channel.unread} unread on Telegram`}
          >
            {channel.unread > 999 ? '999+' : channel.unread}
          </span>
        )}
        {channel.subscribed ? (
          <span className="shrink-0 text-xs text-muted-foreground">Added</span>
        ) : (
          <span
            className={cn(
              'flex size-5 shrink-0 items-center justify-center rounded border transition-colors',
              selected ? 'border-primary bg-primary text-primary-foreground' : 'border-input',
            )}
            aria-hidden
          >
            {selected && <Check className="size-3.5" />}
          </span>
        )}
      </button>
    </li>
  );
}
