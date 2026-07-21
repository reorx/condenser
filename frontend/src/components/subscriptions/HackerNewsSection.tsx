import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { ConfirmDialog } from '@/components/ConfirmDialog';
import { HnDisplayModeMenu } from '@/components/HnDisplayModeMenu';
import { HnGlyph } from '@/components/HnGlyph';
import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { asHnDisplayMode } from '@/hooks/useHnDisplayMode';
import { api, errorMessage } from '@/lib/api';
import { fullDateLabel } from '@/lib/format';
import type { HnStatus } from '@/lib/types';

/** The Hacker News block on the Subscriptions page: Front Page subscribe/unsubscribe,
 * sampling pause switch, display-mode (top N) config, and sampling/backfill status. */
export function HackerNewsSection() {
  const qc = useQueryClient();
  const { data: status, isPending } = useQuery({
    queryKey: ['hn-status'],
    queryFn: api.hnStatus,
    // sampling/backfill progress keeps moving server-side; keep the numbers fresh
    refetchInterval: 60_000,
  });
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['hn-status'] });
    // the sidebar + /s/hn view render from these
    qc.invalidateQueries({ queryKey: ['sources'] });
    qc.invalidateQueries({ queryKey: ['timeline'] });
  };
  const subscribe = useMutation({
    mutationFn: api.hnSubscribe,
    onSuccess: () => {
      toast.success('Hacker News Front Page subscribed — sampling starts now');
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not subscribe')),
  });
  const setEnabled = useMutation({
    mutationFn: api.hnSetEnabled,
    onError: (e) => toast.error(errorMessage(e, 'Could not update')),
    onSettled: invalidate,
  });
  const unsubscribe = useMutation({
    mutationFn: api.hnUnsubscribe,
    onSuccess: () => toast.success('Unsubscribed — archived stories are kept'),
    onError: (e) => toast.error(errorMessage(e, 'Could not unsubscribe')),
    onSettled: invalidate,
  });
  const [confirmOpen, setConfirmOpen] = useState(false);

  return (
    <section>
      <div className="flex items-start justify-between gap-3 px-4 py-3 sm:px-5">
        <div>
          <p className="text-xs text-muted-foreground">
            每日首页 story 采样存档 —— 订阅后才开始采集，官方 API 无历史，订阅一天才有一天的数据。
          </p>
          {status && !status.source_enabled && (
            <p className="mt-1 text-xs text-destructive">
              服务端已禁用 HN 信源（CONDENSER_HN_ENABLED=false），采样不会运行。
            </p>
          )}
        </div>
        {status && !status.subscribed && (
          <Button
            variant="outline"
            size="sm"
            className="shrink-0"
            disabled={subscribe.isPending || !status.source_enabled}
            onClick={() => subscribe.mutate()}
          >
            {subscribe.isPending ? <Spinner className="size-4" /> : <Plus className="size-4" />}
            Add Front Page
          </Button>
        )}
      </div>

      {isPending ? (
        <div className="flex justify-center py-8">
          <Spinner className="size-5 text-muted-foreground" />
        </div>
      ) : status?.subscribed ? (
        <div className="flex items-center gap-3 px-4 py-3 sm:px-5">
          <HnGlyph className="size-9 shrink-0 rounded-full text-base" />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">Front Page</div>
            <HnStatusLine status={status} />
          </div>
          <div className="ml-auto flex items-center gap-2">
            <HnDisplayModeMenu mode={asHnDisplayMode(status.config?.display_mode)} />
            <Switch
              checked={status.enabled}
              onCheckedChange={(enabled) => setEnabled.mutate(enabled)}
              aria-label={status.enabled ? 'Pause sampling' : 'Resume sampling'}
            />
            <Button
              variant="ghost"
              size="icon"
              className="size-8 text-muted-foreground hover:text-destructive"
              aria-label="Unsubscribe Hacker News"
              onClick={() => setConfirmOpen(true)}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Unsubscribe from Hacker News?"
        description="采样停止，已存档的 story 保留。重新订阅即可恢复采集。"
        destructive
        confirmLabel="Unsubscribe"
        pending={unsubscribe.isPending}
        onConfirm={() => unsubscribe.mutate(undefined, { onSuccess: () => setConfirmOpen(false) })}
      />
    </section>
  );
}

/** One-line sampling summary under the feed name (archive size, last poll, backfill/error state). */
function HnStatusLine({ status }: { status: HnStatus }) {
  const parts: string[] = [`${status.stories_total} archived`, `${status.stories_today} today`];
  if (status.last_poll_at) parts.push(`sampled ${fullDateLabel(status.last_poll_at)}`);
  if (status.backfill_pending_days.length > 0)
    parts.push(`backfill pending: ${status.backfill_pending_days.length} days`);
  return (
    <div className="truncate text-xs text-muted-foreground">
      {parts.join(' · ')}
      {status.last_error && <span className="text-destructive"> · {status.last_error}</span>}
    </div>
  );
}
