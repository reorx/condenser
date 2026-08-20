import { NavLink } from 'react-router-dom';

import { navLinkClass } from '@/components/SidebarChannelLink';
import { RssGlyph } from '@/components/RssGlyph';
import { UnreadBadge } from '@/components/UnreadBadge';

interface SidebarRssFeedLinkProps {
  /** The feed key — this source's is the feed URL. */
  feed: string;
  label: string;
  unread: number;
  onNavigate?: () => void;
}

/** One feed link in the sidebar's RSS group, routing to /s/rss/:feed.
 *
 *  The feed key is a URL, so it is percent-encoded into the path: that leaves no
 *  literal slash, which is what lets it occupy a single route segment. Ugly in the
 *  address bar and exactly right everywhere else — the URL *is* the key this source
 *  is built on (the reader typed it), and inventing a second id for the sake of a
 *  prettier route would mean keeping the two in sync forever. */
export function SidebarRssFeedLink({ feed, label, unread, onNavigate }: SidebarRssFeedLinkProps) {
  return (
    <NavLink to={`/s/rss/${encodeURIComponent(feed)}`} className={navLinkClass} onClick={onNavigate}>
      <RssGlyph />
      <span className="truncate">{label}</span>
      <UnreadBadge count={unread} />
    </NavLink>
  );
}
