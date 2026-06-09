import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Bookmark, Hash, Inbox, LogOut, Plus, Settings, Sparkles } from 'lucide-react';
import { NavLink } from 'react-router-dom';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useSubscriptions } from '@/hooks/useSubscriptions';
import { api, ApiError } from '@/lib/api';
import { channelName } from '@/lib/format';
import { queryClient, TG_STATUS_KEY } from '@/lib/queryClient';
import { cn } from '@/lib/utils';

function navClass({ isActive }: { isActive: boolean }) {
  return cn(
    'flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors',
    isActive ? 'bg-accent text-accent-foreground font-medium' : 'text-muted-foreground hover:bg-accent/60',
  );
}

function UnreadBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="ml-auto rounded-full bg-muted px-1.5 text-[11px] tabular-nums text-muted-foreground">
      {count > 999 ? '999+' : count}
    </span>
  );
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const qc = useQueryClient();
  const { data: subs } = useSubscriptions();
  const [handle, setHandle] = useState('');
  const totalUnread = (subs ?? []).reduce((n, s) => n + (s.enabled ? s.unread : 0), 0);

  const add = useMutation({
    mutationFn: () => api.addSubscription(handle.trim()),
    onSuccess: () => {
      setHandle('');
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['timeline'] });
    },
  });

  const logout = useMutation({
    mutationFn: () => api.logout(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TG_STATUS_KEY }),
  });

  const enabledSubs = (subs ?? []).filter((s) => s.enabled);

  return (
    <div className="flex h-full flex-col gap-4 p-3">
      <div className="flex items-center gap-2 px-1.5 pt-1">
        <Sparkles className="size-5 text-amber-500" />
        <span className="font-semibold tracking-tight">Condenser</span>
      </div>

      <nav className="flex flex-col gap-0.5">
        <NavLink to="/" end className={navClass} onClick={onNavigate}>
          <Inbox className="size-4" />
          All
        </NavLink>
        <NavLink to="/?unread=1" className={navClass} onClick={onNavigate}>
          <Sparkles className="size-4" />
          Unread
          <UnreadBadge count={totalUnread} />
        </NavLink>
        <NavLink to="/saved" className={navClass} onClick={onNavigate}>
          <Bookmark className="size-4" />
          Saved
        </NavLink>
        <NavLink to="/subscriptions" className={navClass} onClick={onNavigate}>
          <Settings className="size-4" />
          Manage channels
        </NavLink>
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="px-2.5 pb-1 text-[11px] font-medium tracking-wide text-muted-foreground/70 uppercase">
          Channels
        </div>
        <div className="flex flex-col gap-0.5">
          {enabledSubs.map((s) => (
            <NavLink key={s.channel_id} to={`/c/${s.channel_id}`} className={navClass} onClick={onNavigate}>
              <Hash className="size-4 shrink-0" />
              <span className="truncate">{channelName(s)}</span>
              <UnreadBadge count={s.unread} />
            </NavLink>
          ))}
          {enabledSubs.length === 0 && <p className="px-2.5 py-1 text-xs text-muted-foreground/70">No channels yet.</p>}
        </div>
      </div>

      <form
        className="space-y-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          if (handle.trim()) add.mutate();
        }}
      >
        <div className="flex gap-1.5">
          <Input
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            placeholder="@channel or t.me/…"
            className="h-8 text-sm"
            aria-invalid={!!add.error}
          />
          <Button type="submit" size="icon" className="size-8 shrink-0" disabled={!handle.trim() || add.isPending}>
            {add.isPending ? <Spinner /> : <Plus />}
          </Button>
        </div>
        {add.error && (
          <p className="text-xs text-destructive">
            {add.error instanceof ApiError ? add.error.message : 'Could not subscribe'}
          </p>
        )}
        {add.isSuccess && <p className="text-xs text-muted-foreground">Subscribed — backfilling…</p>}
      </form>

      <Button variant="ghost" size="sm" className="justify-start text-muted-foreground" onClick={() => logout.mutate()}>
        <LogOut className="size-4" />
        Lock app
      </Button>
    </div>
  );
}
