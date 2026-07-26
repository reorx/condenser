import { extractUrls } from './extractUrls';
import type { ItemFeedbackReason, Source, SourceSub, XTweet } from './types';

const LABELS: Record<Source, string> = {
  telegram: 'Telegram',
  hn: 'Hacker News',
  x: 'X',
};

/** The down-reason chips, in the order they are offered. Shared by the card that asks
 *  and the detail pane that reports the answer back, so the two can never drift. */
export const FEEDBACK_REASONS: { value: ItemFeedbackReason; label: string }[] = [
  { value: 'topic', label: '不感兴趣' },
  { value: 'promo', label: '广告营销' },
  { value: 'ai_slop', label: 'AI Slop' },
  { value: 'author', label: '不喜欢作者' },
];

export const FEEDBACK_REASON_LABELS: Record<ItemFeedbackReason, string> = Object.fromEntries(
  FEEDBACK_REASONS.map((r) => [r.value, r.label]),
) as Record<ItemFeedbackReason, string>;

/** The X algorithmic feed's subscription key (a followed account's key is its handle). */
export const X_FORYOU_FEED = 'foryou';

export function isSource(v: string | undefined | null): v is Source {
  return v === 'telegram' || v === 'hn' || v === 'x';
}

/** Display name for a source group (sidebar headers, /s/:source view titles). */
export function sourceLabel(source: Source): string {
  return LABELS[source];
}

/** The HN discussion page for a story (comments URLs are client-assembled). */
export function hnCommentsUrl(storyId: number): string {
  return `https://news.ycombinator.com/item?id=${storyId}`;
}

/** A tweet's permalink. X accepts any handle in the path, so an unknown author
 *  still resolves via the placeholder ('i' is X's own canonical stand-in). */
export function xTweetUrl(tweetId: string, handle?: string | null): string {
  return `https://x.com/${handle || 'i'}/status/${tweetId}`;
}

export function xProfileUrl(handle: string): string {
  return `https://x.com/${handle}`;
}

/** URLs from a tweet worth previewing. X appends a t.co link to the text for its own
 *  attachments (photos, video, the quoted tweet) — previewing that just renders the
 *  tweet we are already looking at, so the trailing self-link is dropped. */
export function xPreviewUrls(tweet: XTweet): string[] {
  const urls = extractUrls(tweet.text);
  const hasAttachment = (tweet.media?.length ?? 0) > 0 || !!tweet.quote;
  if (hasAttachment && urls.length > 0 && /^https?:\/\/t\.co\//i.test(urls[urls.length - 1])) {
    return urls.slice(0, -1);
  }
  return urls;
}

/** Display name for a /api/sources subscription row (`name` is already
 *  COALESCE(sub.name, source-side title) server-side). */
export function sourceSubLabel(sub: SourceSub): string {
  if (sub.name) return sub.name;
  if (sub.username) return `@${sub.username}`;
  return typeof sub.channel_id === 'number' ? `Channel ${sub.channel_id}` : String(sub.channel_id);
}
