import { NavLink } from 'react-router-dom';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { UnreadBadge } from '@/components/UnreadBadge';
import { channelName } from '@/lib/format';
import type { Subscription } from '@/lib/types';
import { cn } from '@/lib/utils';

/** Shared className for every sidebar nav row (top-level links + channel links). */
export function navLinkClass({ isActive }: { isActive: boolean }) {
  return cn(
    'flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors',
    isActive ? 'bg-accent text-accent-foreground font-medium' : 'text-muted-foreground hover:bg-accent/60',
  );
}

interface SidebarChannelLinkProps {
  sub: Subscription;
  onNavigate?: () => void;
}

/** A single subscribed-channel link in the sidebar's channel list. */
export function SidebarChannelLink({ sub, onNavigate }: SidebarChannelLinkProps) {
  return (
    <NavLink to={`/c/${sub.channel_id}`} className={navLinkClass} onClick={onNavigate}>
      <ChannelAvatar channelId={sub.channel_id} name={channelName(sub)} className="size-5 text-[10px]" />
      <span className="truncate">{channelName(sub)}</span>
      <UnreadBadge count={sub.unread} />
    </NavLink>
  );
}
