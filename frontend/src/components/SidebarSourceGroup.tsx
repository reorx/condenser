import { ChevronDown } from 'lucide-react';
import { NavLink } from 'react-router-dom';

import { SidebarChannelLink } from '@/components/SidebarChannelLink';
import { SidebarHnFeedLink } from '@/components/SidebarHnFeedLink';
import { SidebarRssFeedLink } from '@/components/SidebarRssFeedLink';
import { SidebarXFeedLink } from '@/components/SidebarXFeedLink';
import { UnreadBadge } from '@/components/UnreadBadge';
import { sourceLabel, sourceSubLabel, subRowLabel } from '@/lib/sources';
import type { Source, SourceGroup, SourceSub } from '@/lib/types';
import { cn } from '@/lib/utils';

/** One subscription row, dispatched to its source's own link component. Each source
 *  addresses its subscriptions differently (a channel id, a feed key, a feed URL), so
 *  the row types stay separate and this picks between them. */
function SidebarSubLink({ source, sub, onNavigate }: { source: Source; sub: SourceSub; onNavigate?: () => void }) {
  const feed = String(sub.channel_id);
  if (source === 'telegram' && typeof sub.channel_id === 'number') {
    return (
      <SidebarChannelLink
        channelId={sub.channel_id}
        label={sourceSubLabel(sub)}
        unread={sub.unread}
        onNavigate={onNavigate}
      />
    );
  }
  if (source === 'x') {
    return <SidebarXFeedLink feed={feed} label={sourceSubLabel(sub)} unread={sub.unread} onNavigate={onNavigate} />;
  }
  if (source === 'rss') {
    return <SidebarRssFeedLink feed={feed} label={subRowLabel(source, sub)} unread={sub.unread} onNavigate={onNavigate} />;
  }
  return <SidebarHnFeedLink label={sourceSubLabel(sub)} unread={sub.unread} onNavigate={onNavigate} />;
}

interface SidebarSourceGroupProps {
  group: SourceGroup;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onNavigate?: () => void;
}

/** One collapsible source section in the sidebar: a full-width header row linking to the
 *  /s/:source view, with the collapse chevron pinned to the right edge as its own target. */
export function SidebarSourceGroup({ group, collapsed, onToggleCollapsed, onNavigate }: SidebarSourceGroupProps) {
  const enabled = group.subscriptions.filter((s) => s.enabled);
  const unread = enabled.reduce((n, s) => n + s.unread, 0);

  return (
    <div>
      <div className="flex items-center gap-0.5 pb-1">
        <NavLink
          to={`/s/${group.source}`}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex min-w-0 flex-1 items-center gap-2 rounded-md px-2.5 py-1.5 text-[11px] font-medium tracking-wide uppercase transition-colors hover:bg-accent/60 hover:text-foreground',
              isActive ? 'text-foreground' : 'text-muted-foreground/70',
            )
          }
        >
          <span className="truncate">{sourceLabel(group.source)}</span>
          {collapsed && <UnreadBadge count={unread} />}
        </NavLink>
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-expanded={!collapsed}
          aria-label={`${collapsed ? 'Expand' : 'Collapse'} ${sourceLabel(group.source)}`}
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground/70 transition-colors hover:bg-accent hover:text-foreground"
        >
          <ChevronDown className={cn('size-4 transition-transform', collapsed && '-rotate-90')} />
        </button>
      </div>
      {!collapsed && (
        <div className="flex flex-col gap-0.5">
          {enabled.map((s) => (
            <SidebarSubLink key={String(s.channel_id)} source={group.source} sub={s} onNavigate={onNavigate} />
          ))}
          {enabled.length === 0 && <p className="px-2.5 py-1 text-xs text-muted-foreground/70">Nothing enabled.</p>}
        </div>
      )}
    </div>
  );
}
