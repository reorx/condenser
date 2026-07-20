import { NavLink } from 'react-router-dom';

import { HnGlyph } from '@/components/HnGlyph';
import { navLinkClass } from '@/components/SidebarChannelLink';
import { UnreadBadge } from '@/components/UnreadBadge';

interface SidebarHnFeedLinkProps {
  label: string;
  unread: number;
  onNavigate?: () => void;
}

/** A subscribed Hacker News feed link inside the sidebar's Hacker News group.
 *  v1 has a single feed ('front'), so it routes to the source view. */
export function SidebarHnFeedLink({ label, unread, onNavigate }: SidebarHnFeedLinkProps) {
  return (
    <NavLink to="/s/hn" className={navLinkClass} onClick={onNavigate}>
      <HnGlyph />
      <span className="truncate">{label}</span>
      <UnreadBadge count={unread} />
    </NavLink>
  );
}
