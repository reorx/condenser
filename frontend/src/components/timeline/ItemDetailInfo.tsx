// The full-info block at the top of the item detail pane: a label/value list of
// everything known about the item (channel/author, timestamps, ranks, ids).
import { type ReactNode } from 'react';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { HnGlyph } from '@/components/HnGlyph';
import { channelName, fullDateLabel } from '@/lib/format';
import { hnCommentsUrl } from '@/lib/sources';
import type { Subscription, TimelineItem } from '@/lib/types';

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 text-sm">
      <dt className="w-16 shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 flex-1 break-words text-foreground/90">{children}</dd>
    </div>
  );
}

interface Props {
  item: TimelineItem;
  /** The item's TG subscription row, when one is loaded (resolves the channel name). */
  sub?: Subscription | null;
}

/** Source-dispatched detail list for the open item. */
export function ItemDetailInfo({ item, sub }: Props) {
  const msg = item.telegram;
  const hn = item.hn;

  if (msg) {
    const fwd = msg.forward_info;
    const fwdName = fwd?.from_channel_name || fwd?.from_user_name || fwd?.post_author || null;
    const title = sub ? channelName(sub) : channelName(msg.channel);
    return (
      <dl className="space-y-1.5">
        <DetailRow label="频道">
          <span className="inline-flex items-center gap-1.5">
            <ChannelAvatar channelId={msg.channel_id} name={title} className="size-4 text-[8px]" />
            <span>{title}</span>
            {sub?.username && <span className="text-muted-foreground">@{sub.username}</span>}
          </span>
        </DetailRow>
        {msg.sender_name && <DetailRow label="作者">{msg.sender_name}</DetailRow>}
        <DetailRow label="发布时间">{fullDateLabel(msg.date)}</DetailRow>
        {msg.is_edited && msg.edit_date && <DetailRow label="编辑时间">{fullDateLabel(msg.edit_date)}</DetailRow>}
        {msg.is_forwarded && (
          <DetailRow label="转发自">
            {fwdName ?? '未知来源'}
            {fwd?.original_date && <span className="text-muted-foreground"> · {fullDateLabel(fwd.original_date)}</span>}
          </DetailRow>
        )}
        {msg.media_items.length > 0 && <DetailRow label="媒体">{msg.media_items.length} 项</DetailRow>}
        <DetailRow label="条目 ID">{item.key}</DetailRow>
      </dl>
    );
  }

  if (!hn) return null;
  return (
    <dl className="space-y-1.5">
      <DetailRow label="来源">
        <span className="inline-flex items-center gap-1.5">
          <HnGlyph className="size-4 text-[8px]" />
          <span>Hacker News</span>
          {hn.type === 'job' && <span className="text-muted-foreground">(招聘)</span>}
        </span>
      </DetailRow>
      {hn.author && <DetailRow label="作者">{hn.author}</DetailRow>}
      {hn.submitted_at && <DetailRow label="提交时间">{fullDateLabel(hn.submitted_at)}</DetailRow>}
      <DetailRow label="上榜时间">{fullDateLabel(hn.first_seen_at)}</DetailRow>
      <DetailRow label="热度">
        {hn.score} 分 ·{' '}
        <a href={hnCommentsUrl(hn.id)} target="_blank" rel="noreferrer" className="hover:underline">
          {hn.comments_count} 条评论
        </a>
      </DetailRow>
      {(hn.day_rank != null || hn.peak_rank != null) && (
        <DetailRow label="排名">
          {hn.day_rank != null && <span>当日 #{hn.day_rank}</span>}
          {hn.day_rank != null && hn.peak_rank != null && <span aria-hidden> · </span>}
          {hn.peak_rank != null && <span>首页峰值 #{hn.peak_rank}</span>}
        </DetailRow>
      )}
      {hn.domain && <DetailRow label="域名">{hn.domain}</DetailRow>}
      <DetailRow label="条目 ID">{item.key}</DetailRow>
    </dl>
  );
}
