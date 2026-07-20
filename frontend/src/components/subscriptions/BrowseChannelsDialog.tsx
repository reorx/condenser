import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw, Search } from 'lucide-react';
import { toast } from 'sonner';

import { Spinner } from '@/components/Spinner';
import { BrowseChannelRow } from '@/components/subscriptions/BrowseChannelRow';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { api, errorMessage } from '@/lib/api';
import type { JoinedChannel } from '@/lib/types';

interface BrowseChannelsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function BrowseChannelsDialog({ open, onOpenChange }: BrowseChannelsDialogProps) {
  const qc = useQueryClient();
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const { data: channels, isPending } = useQuery({
    queryKey: ['joined-channels'],
    queryFn: () => api.tgDialogs(),
    enabled: open,
    staleTime: 5 * 60 * 1000, // mirrors the backend dialogs TTL; iter_dialogs is slow
  });

  const refresh = useMutation({
    mutationFn: () => api.tgDialogs(true),
    onSuccess: (data) => {
      qc.setQueryData(['joined-channels'], data);
      setSelected(new Set());
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not refresh channels')),
  });

  const add = useMutation({
    mutationFn: (ids: number[]) => api.addSubscriptionsBatch(ids),
    onSuccess: (res) => {
      // Optimistically flip the added channels to subscribed in the cached list.
      const addedIds = new Set(res.added.map((c) => c.channel_id));
      qc.setQueryData<JoinedChannel[]>(['joined-channels'], (list) =>
        (list ?? []).map((c) => (addedIds.has(c.channel_id) ? { ...c, subscribed: true } : c)),
      );
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['sources'] });
      qc.invalidateQueries({ queryKey: ['timeline'] });
      // Drop the added channels from the selection; keep any failures selected for retry.
      setSelected((prev) => new Set([...prev].filter((id) => !addedIds.has(id))));
      if (res.added.length) {
        toast.success(`Subscribed to ${res.added.length} channel${res.added.length > 1 ? 's' : ''} — backfilling…`);
      }
      if (res.failed.length) {
        toast.error(`${res.failed.length} channel${res.failed.length > 1 ? 's' : ''} could not be added`);
      } else if (res.added.length) {
        onOpenChange(false);
      }
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not subscribe')),
  });

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return channels ?? [];
    return (channels ?? []).filter(
      (c) => (c.title ?? '').toLowerCase().includes(q) || (c.username ?? '').toLowerCase().includes(q),
    );
  }, [channels, search]);

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Browse my channels</DialogTitle>
          <DialogDescription>
            Pick from the channels your Telegram account already follows, newest activity first.
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search channels…"
              className="pl-8"
            />
          </div>
          <Button
            variant="outline"
            size="icon"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
            aria-label="Refresh channel list"
          >
            {refresh.isPending ? <Spinner /> : <RefreshCw />}
          </Button>
        </div>

        <div className="max-h-[55vh] min-h-32 overflow-y-auto">
          {isPending ? (
            <div className="flex justify-center py-10">
              <Spinner className="size-5 text-muted-foreground" />
            </div>
          ) : filtered.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              {(channels ?? []).length === 0 ? 'No channels found on your account.' : 'No channels match your search.'}
            </p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {filtered.map((c) => (
                <BrowseChannelRow
                  key={c.channel_id}
                  channel={c}
                  selected={selected.has(c.channel_id)}
                  onToggle={toggle}
                />
              ))}
            </ul>
          )}
        </div>

        <Button
          className="w-full"
          disabled={selected.size === 0 || add.isPending}
          onClick={() => add.mutate([...selected])}
        >
          {add.isPending ? (
            <Spinner />
          ) : selected.size > 0 ? (
            `Add ${selected.size} ${selected.size === 1 ? 'channel' : 'channels'}`
          ) : (
            'Add channels'
          )}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
