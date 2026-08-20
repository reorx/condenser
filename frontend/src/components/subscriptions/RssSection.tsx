import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api, errorMessage } from '@/lib/api';
import { fullDateLabel } from '@/lib/format';
import type { RssStatus, RssSubscription } from '@/lib/types';

import { RssSubscriptionRow } from './RssSubscriptionRow';

/** The RSS tab on the Subscriptions page: add a feed by URL, bulk-import an OPML
 *  export, pause or drop a feed, and see whether polling is actually running.
 *
 *  The OPML file is read **in the browser** and posted as text — the server parses
 *  the same string a manual add would produce a URL from, so an import cannot create
 *  a subscription that typing one could not. */
export function RssSection() {
  const qc = useQueryClient();
  const { data: status } = useQuery({ queryKey: ['rss-status'], queryFn: api.rssStatus, refetchInterval: 60_000 });
  // Both queries poll: a round finishes seconds after an import and minutes after
  // that on its own schedule, and the fetch state each row shows (title, last fetch,
  // error streak) is written by that round. Without this the rows sit on "waiting for
  // the first fetch" until the reader reloads — which reads as a feed that never ran.
  //
  // Fast while any feed has never been fetched, slow once they all have: right after
  // an import that is the whole list and the answer arrives within seconds, and the
  // condition ends itself — a feed only lacks `fetched_at` until its first round.
  const { data: subs, isPending } = useQuery({
    queryKey: ['rss-subscriptions'],
    queryFn: api.listRssSubscriptions,
    refetchInterval: (query) => ((query.state.data ?? []).some((s) => !s.fetched_at) ? 5_000 : 60_000),
  });
  const [url, setUrl] = useState('');
  const [pendingDelete, setPendingDelete] = useState<RssSubscription | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['rss-status'] });
    qc.invalidateQueries({ queryKey: ['rss-subscriptions'] });
    // the sidebar, the /s/rss view and the aggregate all render from these
    qc.invalidateQueries({ queryKey: ['sources'] });
    qc.invalidateQueries({ queryKey: ['timeline'] });
  };
  const subscribe = useMutation({
    mutationFn: api.rssSubscribe,
    onSuccess: (sub) => {
      setUrl('');
      toast.success(`已订阅 ${sub.name ?? sub.url} —— 马上抓一轮`);
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e, '订阅失败')),
  });
  const importOpml = useMutation({
    mutationFn: api.rssImportOpml,
    onSuccess: (r) => {
      // All three counts, always: "added 40" alone hides that 12 were unusable.
      toast.success(`导入完成：新增 ${r.added} 个，已有 ${r.skipped_existing} 个，无法识别 ${r.invalid} 个`);
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e, 'OPML 导入失败')),
  });
  const setEnabled = useMutation({
    mutationFn: ({ url: feedUrl, enabled }: { url: string; enabled: boolean }) => api.rssSetEnabled(feedUrl, enabled),
    onError: (e) => toast.error(errorMessage(e, '更新失败')),
    onSettled: invalidate,
  });
  const unsubscribe = useMutation({
    mutationFn: api.rssUnsubscribe,
    onSuccess: () => toast.success('已退订 —— 已存档的条目保留'),
    onError: (e) => toast.error(errorMessage(e, '退订失败')),
    onSettled: invalidate,
  });

  const disabled = !status?.source_enabled;

  async function onPickFile(file: File | undefined) {
    if (!file) return;
    importOpml.mutate(await file.text());
    // Let the same file be picked again after a failed import.
    if (fileInput.current) fileInput.current.value = '';
  }

  return (
    <section>
      <div className="space-y-3 border-b px-4 py-3 sm:px-5">
        <p className="text-xs text-muted-foreground">
          标准 RSS / Atom 订阅，服务端按 <span className="font-medium">条件请求</span> 定时轮询（多数轮次是
          304，所以上百个 feed 也很便宜）。 首次订阅时超过一周的旧文章直接归档为已读，只有一周内的进未读。
        </p>
        {disabled && (
          <p className="text-xs text-destructive">
            服务端已禁用 RSS 信源（CONDENSER_RSS_ENABLED=false），订阅与轮询都不会运行。
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (url.trim()) subscribe.mutate(url.trim());
            }}
          >
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/feed.xml"
              className="h-8 w-64"
              disabled={disabled}
              aria-label="Feed URL"
            />
            <Button type="submit" variant="outline" size="sm" disabled={!url.trim() || disabled}>
              {subscribe.isPending ? <Spinner className="size-4" /> : <Plus className="size-4" />}
              Add feed
            </Button>
          </form>
          <Button
            variant="outline"
            size="sm"
            disabled={disabled || importOpml.isPending}
            onClick={() => fileInput.current?.click()}
          >
            {importOpml.isPending ? <Spinner className="size-4" /> : <Upload className="size-4" />}
            Import OPML
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept=".opml,.xml,text/xml,application/xml"
            className="hidden"
            onChange={(e) => void onPickFile(e.target.files?.[0])}
          />
        </div>
      </div>

      {isPending ? (
        <div className="flex justify-center py-8">
          <Spinner className="size-5 text-muted-foreground" />
        </div>
      ) : (subs ?? []).length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground sm:px-5">还没有 RSS 订阅。</p>
      ) : (
        <div className="divide-y">
          {(subs ?? []).map((sub) => (
            <RssSubscriptionRow
              key={sub.url}
              sub={sub}
              busy={setEnabled.isPending}
              onToggle={(enabled) => setEnabled.mutate({ url: sub.url, enabled })}
              onDelete={() => setPendingDelete(sub)}
            />
          ))}
        </div>
      )}

      {status && <RssStatusLine status={status} />}

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        title="Unsubscribe from this feed?"
        description="停止轮询，已存档的条目保留。重新订阅会从上次的位置续抓，不会重下已有的窗口。"
        destructive
        confirmLabel="Unsubscribe"
        pending={unsubscribe.isPending}
        onConfirm={() =>
          pendingDelete && unsubscribe.mutate(pendingDelete.url, { onSuccess: () => setPendingDelete(null) })
        }
      />
    </section>
  );
}

/** One-line polling summary: archive size, last round, and how many feeds are broken. */
function RssStatusLine({ status }: { status: RssStatus }) {
  const parts: string[] = [`${status.feeds_enabled}/${status.feeds_total} feeds`, `${status.entries_total} archived`];
  if (status.last_poll_at) parts.push(`polled ${fullDateLabel(status.last_poll_at)}`);
  else parts.push('not polled yet');
  if (status.last_round) parts.push(`+${status.last_round.new_entries} last round`);
  return (
    <div className="border-t px-4 py-3 text-xs text-muted-foreground sm:px-5">
      {parts.join(' · ')}
      {status.feeds_error > 0 && <span className="text-destructive"> · {status.feeds_error} feeds failing</span>}
      {status.last_error && <span className="text-destructive"> · {status.last_error}</span>}
    </div>
  );
}
