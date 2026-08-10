import { extractUrls } from './extractUrls';
import { stripTrailingMediaTco, urlEntityMap } from './xUrls';
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
  // 钩子 + FOMO + 「save this 🔖」+ 正文钓在评论区。和「广告营销」分开：那个是卖东西，
  // 这个是钓互动，喂的通道也不同（话术是词汇级的，广告更接近意图）。标签取「博眼球」
  // 而不是直译，读者按的时候不用先在心里翻译一遍；值本身仍是那个超集。
  { value: 'engagement_farming', label: '博眼球' },
  { value: 'author', label: '不喜欢作者' },
];

export const FEEDBACK_REASON_LABELS: Record<ItemFeedbackReason, string> = Object.fromEntries(
  FEEDBACK_REASONS.map((r) => [r.value, r.label]),
) as Record<ItemFeedbackReason, string>;

/** The X feed keys that are not account handles: the algorithmic For You timeline
 *  and the chronological "accounts you follow" one. */
export const X_FORYOU_FEED = 'foryou';
export const X_FOLLOWING_FEED = 'following';

/** Is this one of the two whole-timeline feeds rather than a single account? They
 *  have no avatar, no profile and (unlike an account you chose to subscribe to) a
 *  say in how much of them reaches the aggregate timeline. */
export function isXSyntheticFeed(feed: string): boolean {
  return feed === X_FORYOU_FEED || feed === X_FOLLOWING_FEED;
}

/** Display name for an X feed row (a followed account falls back to its handle). */
export function xFeedLabel(feed: string, name?: string | null): string {
  if (feed === X_FORYOU_FEED) return 'For You';
  if (feed === X_FOLLOWING_FEED) return 'Following';
  return name || `@${feed}`;
}

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
 *  tweet we are already looking at, so the self-link is dropped.
 *
 *  With url entities (v13) each t.co previews as its expanded original — better
 *  metadata, and no t.co redirect to chase. A media self-link is recognized
 *  precisely (a trailing t.co the entities don't know), and the quote's own
 *  permalink by its expanded form carrying the quoted status id. Rows without
 *  entities keep the older trailing-self-link heuristic. */
export function xPreviewUrls(tweet: XTweet): string[] {
  const hasAttachment = (tweet.media?.length ?? 0) > 0 || !!tweet.quote;
  if (tweet.urls) {
    const entities = urlEntityMap(tweet.urls);
    const body = stripTrailingMediaTco(tweet.text ?? '', entities, (tweet.media?.length ?? 0) > 0);
    const out: string[] = [];
    for (const url of extractUrls(body)) {
      const expanded = entities.get(url)?.expanded_url ?? url;
      if (tweet.quote && expanded.includes(`/status/${tweet.quote.id}`)) continue;
      if (!out.includes(expanded)) out.push(expanded);
    }
    return out;
  }
  const urls = extractUrls(tweet.text);
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
