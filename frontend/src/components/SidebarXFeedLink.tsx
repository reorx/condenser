import { NavLink } from 'react-router-dom';

import { navLinkClass } from '@/components/SidebarChannelLink';
import { UnreadBadge } from '@/components/UnreadBadge';
import { XAvatar } from '@/components/XAvatar';
import { XGlyph } from '@/components/XGlyph';
import { X_FORYOU_FEED } from '@/lib/sources';

interface SidebarXFeedLinkProps {
  /** The feed key: 'foryou' or a followed account's handle. */
  feed: string;
  label: string;
  unread: number;
  onNavigate?: () => void;
}

/** One X feed link in the sidebar. Unlike Hacker News (a single feed), X has many,
 *  so each row routes to its own /s/x/:feed view; For You is not part of the
 *  aggregate timeline, which makes this its only entry point. */
export function SidebarXFeedLink({ feed, label, unread, onNavigate }: SidebarXFeedLinkProps) {
  const isForYou = feed === X_FORYOU_FEED;
  return (
    <NavLink to={`/s/x/${feed}`} className={navLinkClass} onClick={onNavigate}>
      {isForYou ? <XGlyph /> : <XAvatar handle={feed} name={label} className="size-5 text-[10px]" />}
      <span className="truncate">{label}</span>
      <UnreadBadge count={unread} />
    </NavLink>
  );
}
