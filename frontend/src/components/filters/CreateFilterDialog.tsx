import { useEffect, useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Check, ChevronsUpDown, Globe, Radio, Search } from 'lucide-react';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useCreateFilter } from '@/hooks/useAllFilters';
import { useSubscriptions } from '@/hooks/useSubscriptions';
import { api, errorMessage } from '@/lib/api';
import { channelName, timeLabel } from '@/lib/format';
import type { FilterPreviewResult, Subscription } from '@/lib/types';
import { cn } from '@/lib/utils';

type Scope = 'global' | 'channel';

interface CreateFilterDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateFilterDialog({ open, onOpenChange }: CreateFilterDialogProps) {
  const { data: subs } = useSubscriptions();
  const create = useCreateFilter();

  const [scope, setScope] = useState<Scope>('global');
  const [channelId, setChannelId] = useState<number | null>(null);
  const [pattern, setPattern] = useState('');
  const [preview, setPreview] = useState<FilterPreviewResult | null>(null);

  // Reset state every time the dialog reopens so stale preview / inputs don't linger.
  useEffect(() => {
    if (open) {
      setScope('global');
      setChannelId(null);
      setPattern('');
      setPreview(null);
    }
  }, [open]);

  const effectiveChannelId = scope === 'channel' ? channelId : null;
  const canSubmit = !!pattern.trim() && (scope === 'global' || channelId !== null) && !create.isPending;

  const previewMut = useMutation({
    mutationFn: () => api.previewFilter(pattern.trim(), effectiveChannelId),
    onSuccess: setPreview,
  });

  // Drop in-flight requests too — otherwise a settle could overwrite the cleared state.
  useEffect(() => {
    setPreview(null);
    previewMut.reset();
    // previewMut is a stable mutation object; including it would cause an infinite reset loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, channelId, pattern]);

  function submit() {
    if (!canSubmit) return;
    create.mutate({ pattern: pattern.trim(), channelId: effectiveChannelId }, { onSuccess: () => onOpenChange(false) });
  }

  const submitLabel = preview && preview.matched > 0 ? `Create filter (hides ${preview.matched})` : 'Create filter';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Create filter</DialogTitle>
          <DialogDescription>
            Exclude messages whose text contains the keyword (case-insensitive substring).
          </DialogDescription>
        </DialogHeader>

        {/* min-w-0 keeps long unbreakable text in preview samples (URLs, etc.) from stretching the dialog past max-w-lg. */}
        <div className="min-w-0 space-y-4">
          <div>
            <div className="mb-1.5 text-xs font-medium text-muted-foreground">Scope</div>
            <div className="grid grid-cols-2 gap-2">
              <ScopeOption
                active={scope === 'global'}
                onClick={() => setScope('global')}
                icon={<Globe className="size-4" />}
                title="Global"
                hint="Applies to every channel"
              />
              <ScopeOption
                active={scope === 'channel'}
                onClick={() => setScope('channel')}
                icon={<Radio className="size-4" />}
                title="Single channel"
                hint="Applies to one channel"
              />
            </div>
          </div>

          {scope === 'channel' && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-muted-foreground">Channel</div>
              <ChannelPicker subs={subs ?? []} selected={channelId} onSelect={setChannelId} />
            </div>
          )}

          <div>
            <div className="mb-1.5 text-xs font-medium text-muted-foreground">Keyword</div>
            <div className="flex gap-2">
              <Input
                value={pattern}
                onChange={(e) => setPattern(e.target.value)}
                placeholder="e.g. promo"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    submit();
                  }
                }}
              />
              <Button
                type="button"
                variant="outline"
                disabled={!pattern.trim() || previewMut.isPending || (scope === 'channel' && channelId === null)}
                onClick={() => previewMut.mutate()}
              >
                {previewMut.isPending ? <Spinner /> : 'Preview'}
              </Button>
            </div>
          </div>

          <PreviewResult
            scope={scope}
            isPending={previewMut.isPending}
            error={previewMut.error ? errorMessage(previewMut.error, 'Preview failed') : null}
            result={preview}
            pattern={pattern.trim()}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {create.isPending ? <Spinner /> : submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ScopeOption({
  active,
  onClick,
  icon,
  title,
  hint,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  hint: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex flex-col items-start gap-1 rounded-md border p-3 text-left transition-colors',
        active ? 'border-primary bg-accent/40' : 'border-input hover:bg-accent/30',
      )}
    >
      <div className="flex items-center gap-1.5 text-sm font-medium">
        {icon}
        {title}
      </div>
      <span className="text-xs text-muted-foreground">{hint}</span>
    </button>
  );
}

function ChannelPicker({
  subs,
  selected,
  onSelect,
}: {
  subs: Subscription[];
  selected: number | null;
  onSelect: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');

  const enabled = useMemo(() => subs.filter((s) => s.enabled), [subs]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return enabled;
    return enabled.filter(
      (c) => (c.title ?? '').toLowerCase().includes(q) || (c.username ?? '').toLowerCase().includes(q),
    );
  }, [enabled, search]);

  const selectedSub = selected != null ? enabled.find((s) => s.channel_id === selected) : undefined;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" className="w-full justify-between font-normal">
          {selectedSub ? (
            <span className="flex items-center gap-2">
              <ChannelAvatar
                channelId={selectedSub.channel_id}
                name={channelName(selectedSub)}
                className="size-5 text-[10px]"
              />
              <span className="truncate">{channelName(selectedSub)}</span>
            </span>
          ) : (
            <span className="text-muted-foreground">Select a channel…</span>
          )}
          <ChevronsUpDown className="size-4 opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        className="w-[--radix-popover-trigger-width] p-0"
        align="start"
        onOpenAutoFocus={(e) => {
          // Keep focus on the search input we render below.
          e.preventDefault();
        }}
      >
        <div className="border-b p-2">
          <div className="relative">
            <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search channels…"
              className="pl-8"
            />
          </div>
        </div>
        <div className="max-h-64 overflow-y-auto p-1">
          {filtered.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No channels match.</p>
          ) : (
            filtered.map((s) => {
              const isSelected = s.channel_id === selected;
              return (
                <button
                  key={s.channel_id}
                  type="button"
                  onClick={() => {
                    onSelect(s.channel_id);
                    setOpen(false);
                  }}
                  className={cn(
                    'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent',
                    isSelected && 'bg-accent',
                  )}
                >
                  <ChannelAvatar channelId={s.channel_id} name={channelName(s)} className="size-5 text-[10px]" />
                  <span className="truncate">{channelName(s)}</span>
                  {isSelected && <Check className="ml-auto size-4 text-primary" />}
                </button>
              );
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

function PreviewResult({
  scope,
  isPending,
  error,
  result,
  pattern,
}: {
  scope: Scope;
  isPending: boolean;
  error: string | null;
  result: FilterPreviewResult | null;
  pattern: string;
}) {
  if (isPending) {
    return (
      <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-3 text-sm text-muted-foreground">
        <Spinner className="size-4" />
        Scanning recent messages…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-3 text-sm text-destructive">
        {error}
      </div>
    );
  }
  if (!result) return null;

  if (result.scanned === 0) {
    return (
      <div className="rounded-md border bg-muted/40 px-3 py-3 text-sm text-muted-foreground">
        Nothing to scan yet — no cached messages for this scope.
      </div>
    );
  }

  const where = scope === 'global' ? 'across all channels' : 'in this channel';
  const summary =
    result.matched === 0
      ? `No matches in the last ${result.scanned} messages ${where}.`
      : `Will hide ${result.matched} of the last ${result.scanned} messages ${where}.`;

  return (
    <div className="space-y-2">
      <div className="rounded-md border bg-muted/40 px-3 py-2 text-sm">{summary}</div>
      {result.samples.length > 0 && (
        <ul className="max-h-56 overflow-y-auto rounded-md border divide-y divide-border/50">
          {result.samples.map((s) => (
            <li key={`${s.channel_id}-${s.message_id}`} className="min-w-0 px-3 py-2 text-sm">
              <div className="mb-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                <span className="truncate">{s.channel_title ?? 'Unknown channel'}</span>
                <span>·</span>
                <span className="tabular-nums">{timeLabel(s.date)}</span>
              </div>
              <HighlightedText text={s.text} pattern={pattern} />
            </li>
          ))}
        </ul>
      )}
      {result.matched > result.samples.length && (
        <p className="text-xs text-muted-foreground">
          Showing {result.samples.length} of {result.matched} matches.
        </p>
      )}
    </div>
  );
}

function HighlightedText({ text, pattern }: { text: string; pattern: string }) {
  if (!pattern) return <span>{text}</span>;
  const lowered = text.toLowerCase();
  const needle = pattern.toLowerCase();
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  while (cursor < text.length) {
    const hit = lowered.indexOf(needle, cursor);
    if (hit === -1) {
      parts.push(<span key={key++}>{text.slice(cursor)}</span>);
      break;
    }
    if (hit > cursor) parts.push(<span key={key++}>{text.slice(cursor, hit)}</span>);
    parts.push(
      <mark key={key++} className="rounded bg-amber-300/60 px-0.5 text-foreground dark:bg-amber-500/40">
        {text.slice(hit, hit + needle.length)}
      </mark>,
    );
    cursor = hit + needle.length;
  }
  // `overflow-wrap: anywhere` breaks long URLs that `break-words` won't.
  return <span className="block [overflow-wrap:anywhere]">{parts}</span>;
}
