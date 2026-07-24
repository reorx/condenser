import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { toast } from 'sonner';

import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api, errorMessage } from '@/lib/api';
import { fullDateLabel } from '@/lib/format';
import type { XStatus, XSubscription } from '@/lib/types';

import { XSubscriptionRow } from './XSubscriptionRow';

/** The X tab on the Subscriptions page: subscribe to For You / followed accounts,
 *  pause or drop a feed, and see whether the local probe is actually pushing.
 *
 *  X data can only be read from a logged-in browser session, so unlike TG/HN the
 *  server never fetches: it just tells the probe what these subscriptions are. */
export function XSection() {
  const qc = useQueryClient();
  const { data: status } = useQuery({ queryKey: ['x-status'], queryFn: api.xStatus, refetchInterval: 60_000 });
  const { data: subs, isPending } = useQuery({ queryKey: ['x-subscriptions'], queryFn: api.listXSubscriptions });
  const [handle, setHandle] = useState('');
  const [pendingDelete, setPendingDelete] = useState<XSubscription | null>(null);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['x-status'] });
    qc.invalidateQueries({ queryKey: ['x-subscriptions'] });
  };
  const subscribe = useMutation({
    mutationFn: api.xSubscribe,
    onSuccess: () => {
      setHandle('');
      toast.success('已订阅 —— 本地 probe 下一轮开始抓取');
      invalidate();
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not subscribe')),
  });
  const setEnabled = useMutation({
    mutationFn: ({ channelId, enabled }: { channelId: string; enabled: boolean }) =>
      api.xSetEnabled(channelId, enabled),
    onError: (e) => toast.error(errorMessage(e, 'Could not update')),
    onSettled: invalidate,
  });
  const unsubscribe = useMutation({
    mutationFn: api.xUnsubscribe,
    onSuccess: () => toast.success('已退订 —— 已存档的推文保留'),
    onError: (e) => toast.error(errorMessage(e, 'Could not unsubscribe')),
    onSettled: invalidate,
  });

  const hasForYou = (subs ?? []).some((s) => s.kind === 'home');
  const disabled = !status?.source_enabled;

  return (
    <section>
      <div className="space-y-3 border-b px-4 py-3 sm:px-5">
        <p className="text-xs text-muted-foreground">
          X 数据只存在于本机登录态里 —— 由跑在你电脑上的 <span className="font-medium">probe</span>（bird
          CLI）按这里的订阅抓取并推送到服务端。 订阅 <span className="font-medium">For You</span> 算法流，或按 @handle
          订阅关注的人。
        </p>
        {disabled && (
          <p className="text-xs text-destructive">
            服务端已禁用 X 信源（CONDENSER_X_ENABLED=false），订阅与推送都会被拒绝。
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={hasForYou || disabled || subscribe.isPending}
            onClick={() => subscribe.mutate('foryou')}
          >
            <Plus className="size-4" />
            Add For You
          </Button>
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (handle.trim()) subscribe.mutate(handle.trim());
            }}
          >
            <Input
              value={handle}
              onChange={(e) => setHandle(e.target.value)}
              placeholder="@handle"
              className="h-8 w-40"
              disabled={disabled}
              aria-label="Follow an X account"
            />
            <Button type="submit" variant="outline" size="sm" disabled={!handle.trim() || disabled}>
              {subscribe.isPending ? <Spinner className="size-4" /> : <Plus className="size-4" />}
              Add account
            </Button>
          </form>
        </div>
      </div>

      {isPending ? (
        <div className="flex justify-center py-8">
          <Spinner className="size-5 text-muted-foreground" />
        </div>
      ) : (subs ?? []).length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground sm:px-5">还没有 X 订阅。</p>
      ) : (
        <div className="divide-y">
          {(subs ?? []).map((sub) => (
            <XSubscriptionRow
              key={sub.channel_id}
              sub={sub}
              push={status?.last_push_counts[sub.channel_id]}
              busy={setEnabled.isPending}
              onToggle={(enabled) => setEnabled.mutate({ channelId: sub.channel_id, enabled })}
              onDelete={() => setPendingDelete(sub)}
            />
          ))}
        </div>
      )}

      {status && <XStatusLine status={status} />}

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        title="Unsubscribe from this feed?"
        description="probe 不再抓取这个 feed，已存档的推文保留。重新订阅即可恢复。"
        destructive
        confirmLabel="Unsubscribe"
        pending={unsubscribe.isPending}
        onConfirm={() =>
          pendingDelete && unsubscribe.mutate(pendingDelete.channel_id, { onSuccess: () => setPendingDelete(null) })
        }
      />
    </section>
  );
}

/** Whether the probe is alive at all, plus the archive size — the two things that
 *  tell you a silent feed is the probe's fault and not the server's. */
function XStatusLine({ status }: { status: XStatus }) {
  const parts = [`${status.tweets_total} tweets archived`, `${status.feed_items_total} feed items`];
  parts.push(status.last_push_at ? `last push ${fullDateLabel(status.last_push_at)}` : 'no probe push yet');
  return (
    <div className="border-t px-4 py-3 text-xs text-muted-foreground sm:px-5">
      {parts.join(' · ')}
      {status.parse_errors > 0 && (
        <span className="text-destructive"> · {status.parse_errors} parse errors (bird 输出可能变了)</span>
      )}
    </div>
  );
}
