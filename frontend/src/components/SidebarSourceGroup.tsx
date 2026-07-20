import { ChevronDown } from 'lucide-react';
import { NavLink } from 'react-router-dom';

import { SidebarChannelLink } from '@/components/SidebarChannelLink';
import { SidebarHnFeedLink } from '@/components/SidebarHnFeedLink';
import { UnreadBadge } from '@/components/UnreadBadge';
import { sourceLabel, sourceSubLabel } from '@/lib/sources';
import type { SourceGroup } from '@/lib/types';
import { cn } from '@/lib/utils';

interface SidebarSourceGroupProps {
  group: SourceGroup;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onNavigate?: () => void;
}

/** One collapsible source section in the sidebar: a header row (chevron toggle +
 *  label linking to the /s/:source view) over the source's enabled subscriptions. */
export function SidebarSourceGroup({ group, collapsed, onToggleCollapsed, onNavigate }: SidebarSourceGroupProps) {
  const enabled = group.subscriptions.filter((s) => s.enabled);
  const unread = enabled.reduce((n, s) => n + s.unread, 0);

  return (
    <div>
      <div className="flex items-center gap-0.5 px-1 pb-1">
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-expanded={!collapsed}
          aria-label={`${collapsed ? 'Expand' : 'Collapse'} ${sourceLabel(group.source)}`}
          className="rounded p-0.5 text-muted-foreground/70 transition-colors hover:bg-accent/60 hover:text-foreground"
        >
          <ChevronDown className={cn('size-3.5 transition-transform', collapsed && '-rotate-90')} />
        </button>
        <NavLink
          to={`/s/${group.source}`}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'rounded px-1 text-[11px] font-medium tracking-wide uppercase transition-colors hover:text-foreground',
              isActive ? 'text-foreground' : 'text-muted-foreground/70',
            )
          }
        >
          {sourceLabel(group.source)}
        </NavLink>
        {collapsed && <UnreadBadge count={unread} />}
      </div>
      {!collapsed && (
        <div className="flex flex-col gap-0.5">
          {enabled.map((s) =>
            group.source === 'telegram' && typeof s.channel_id === 'number' ? (
              <SidebarChannelLink
                key={s.channel_id}
                channelId={s.channel_id}
                label={sourceSubLabel(s)}
                unread={s.unread}
                onNavigate={onNavigate}
              />
            ) : (
              <SidebarHnFeedLink
                key={s.channel_id}
                label={sourceSubLabel(s)}
                unread={s.unread}
                onNavigate={onNavigate}
              />
            ),
          )}
          {enabled.length === 0 && <p className="px-2.5 py-1 text-xs text-muted-foreground/70">Nothing enabled.</p>}
        </div>
      )}
    </div>
  );
}
