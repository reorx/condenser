// The full-info block at the top of the item detail pane: a label/value list of
// everything known about the item (channel/author, timestamps, ranks, ids).
import { type ReactNode } from 'react';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { HnGlyph } from '@/components/HnGlyph';
import { XAvatar } from '@/components/XAvatar';
import { channelName, compactNumber, fullDateLabel } from '@/lib/format';
import { hnCommentsUrl, xProfileUrl, X_FORYOU_FEED } from '@/lib/sources';
import type { Subscription, TimelineItem } from '@/lib/types';

import { XVerdictDetail } from './XVerdictDetail';

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
  const tweet = item.x;

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

  if (tweet) {
    const m = tweet.metrics;
    return (
      <dl className="space-y-1.5">
        <DetailRow label="作者">
          <span className="inline-flex items-center gap-1.5">
            <XAvatar handle={tweet.author_handle} name={tweet.author_name} className="size-4 text-[8px]" />
            <span>{tweet.author_name ?? '未知'}</span>
            {tweet.author_handle && (
              <a
                href={xProfileUrl(tweet.author_handle)}
                target="_blank"
                rel="noreferrer"
                className="text-muted-foreground hover:underline"
              >
                @{tweet.author_handle}
              </a>
            )}
          </span>
        </DetailRow>
        <DetailRow label="信息源">
          {tweet.feed === X_FORYOU_FEED ? 'X · For You（算法推荐）' : `X · @${tweet.feed}`}
        </DetailRow>
        {tweet.created_at && <DetailRow label="发布时间">{fullDateLabel(tweet.created_at)}</DetailRow>}
        {/* For You sorts on this, so it is the position you actually see it at. */}
        <DetailRow label="抓取时间">{fullDateLabel(tweet.first_seen_at)}</DetailRow>
        {m && (
          <DetailRow label="互动">
            {compactNumber(m.like_count)} 赞 · {compactNumber(m.retweet_count)} 转推 · {compactNumber(m.reply_count)}{' '}
            回复
          </DetailRow>
        )}
        {tweet.rt_of_handle && <DetailRow label="转推自">@{tweet.rt_of_handle}</DetailRow>}
        {tweet.quote && <DetailRow label="引用">@{tweet.quote.author_handle ?? '未知'}</DetailRow>}
        {tweet.reply_to_id && <DetailRow label="回复">该推文是一条回复</DetailRow>}
        {tweet.media && tweet.media.length > 0 && <DetailRow label="媒体">{tweet.media.length} 项</DetailRow>}
        {/* The reader's own label (Phase 3) — shown as a fact here; the card owns the buttons. */}
        {item.feedback && <DetailRow label="反馈">{item.feedback === 'up' ? '赞' : '踩'}</DetailRow>}
        {tweet.verdict && (
          <DetailRow label="判定">
            <XVerdictDetail verdict={tweet.verdict} meta={tweet.verdict_meta} />
          </DetailRow>
        )}
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
