import { useState } from 'react';
import { Bookmark, Filter, Inbox, Radio, Search, Settings, Sparkles } from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';

import { SettingsDialog } from '@/components/SettingsDialog';
import { navLinkClass, SidebarChannelLink } from '@/components/SidebarChannelLink';
import { BrowseChannelsDialog } from '@/components/subscriptions/BrowseChannelsDialog';
import { UnreadBadge } from '@/components/UnreadBadge';
import { Button } from '@/components/ui/button';
import { useSubscriptions } from '@/hooks/useSubscriptions';

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { data: subs } = useSubscriptions();
  const totalUnread = (subs ?? []).reduce((n, s) => n + (s.enabled ? s.unread : 0), 0);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [browseOpen, setBrowseOpen] = useState(false);
  const location = useLocation();
  // "/" is the Unread home view; "?all=1" flips the aggregate view to All.
  const allActive = location.pathname === '/' && new URLSearchParams(location.search).get('all') === '1';
  const unreadActive = location.pathname === '/' && !allActive;

  const enabledSubs = (subs ?? []).filter((s) => s.enabled);

  return (
    <div className="flex h-full flex-col gap-4 p-3">
      <div className="flex items-center gap-2 px-1.5 pt-1">
        <Sparkles className="size-5 text-amber-500" />
        <span className="font-semibold tracking-tight">Condenser</span>
      </div>

      <nav className="flex flex-col gap-0.5">
        <NavLink to="/" end className={navLinkClass({ isActive: unreadActive })} onClick={onNavigate}>
          <Sparkles className="size-4" />
          Unread
          <UnreadBadge count={totalUnread} />
        </NavLink>
        <NavLink to="/?all=1" className={navLinkClass({ isActive: allActive })} onClick={onNavigate}>
          <Inbox className="size-4" />
          All
        </NavLink>
        <NavLink to="/saved" className={navLinkClass} onClick={onNavigate}>
          <Bookmark className="size-4" />
          Saved
        </NavLink>
        <NavLink to="/filters" className={navLinkClass} onClick={onNavigate}>
          <Filter className="size-4" />
          Filters
        </NavLink>
        <NavLink to="/subscriptions" className={navLinkClass} onClick={onNavigate}>
          <Radio className="size-4" />
          Manage channels
        </NavLink>
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="px-2.5 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground/70 uppercase">
          Channels
        </div>
        <div className="flex flex-col gap-0.5">
          {enabledSubs.map((s) => (
            <SidebarChannelLink key={s.channel_id} sub={s} onNavigate={onNavigate} />
          ))}
          {enabledSubs.length === 0 && <p className="px-2.5 py-1 text-xs text-muted-foreground/70">No channels yet.</p>}
        </div>
      </div>

      <Button variant="outline" size="sm" className="w-full justify-start" onClick={() => setBrowseOpen(true)}>
        <Search className="size-4" />
        Browse my channels
      </Button>

      <Button
        variant="ghost"
        size="sm"
        className="justify-start text-muted-foreground"
        onClick={() => setSettingsOpen(true)}
      >
        <Settings className="size-4" />
        Settings
      </Button>

      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      <BrowseChannelsDialog open={browseOpen} onOpenChange={setBrowseOpen} />
    </div>
  );
}
