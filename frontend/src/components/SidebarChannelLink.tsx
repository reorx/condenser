import { NavLink } from 'react-router-dom';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { UnreadBadge } from '@/components/UnreadBadge';
import { cn } from '@/lib/utils';

/** Shared className for every sidebar nav row (top-level links + subscription links). */
export function navLinkClass({ isActive }: { isActive: boolean }) {
  return cn(
    'flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors',
    isActive ? 'bg-accent text-accent-foreground font-medium' : 'text-muted-foreground hover:bg-accent/60',
  );
}

interface SidebarChannelLinkProps {
  channelId: number;
  label: string;
  unread: number;
  onNavigate?: () => void;
}

/** A single subscribed Telegram channel link inside the sidebar's Telegram group. */
export function SidebarChannelLink({ channelId, label, unread, onNavigate }: SidebarChannelLinkProps) {
  return (
    <NavLink to={`/c/${channelId}`} className={navLinkClass} onClick={onNavigate}>
      <ChannelAvatar channelId={channelId} name={label} className="size-5 text-[10px]" />
      <span className="truncate">{label}</span>
      <UnreadBadge count={unread} />
    </NavLink>
  );
}
