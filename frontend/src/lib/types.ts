// Mirrors the backend JSON contract (condenser routers + telememo DisplayMessage).

export type TgStatus = 'unauthorized' | 'awaiting_code' | 'awaiting_2fa' | 'authorized';

export interface MediaItem {
  message_id: number;
  media_type: string | null;
  has_media: boolean;
  /** Pixel dimensions of the media, when known (NULL for historical rows pre-migration). */
  width: number | null;
  height: number | null;
}

export interface ForwardInfo {
  from_channel_id: number | null;
  from_channel_name: string | null;
  from_user_id: number | null;
  from_user_name: string | null;
  from_message_id: number | null;
  original_date: string | null;
  post_author: string | null;
}

export interface ChannelRef {
  id: number;
  title: string | null;
  username: string | null;
}

/** URL link preview (Telegram web page preview) attached to a message. */
export interface WebPagePreview {
  url: string | null;
  display_url: string | null;
  type: string | null;
  site_name: string | null;
  title: string | null;
  description: string | null;
  author: string | null;
  /** When true, the preview image is fetchable via the media proxy for this message id. */
  has_photo: boolean;
}

/** One display unit (album-collapsed). Matches telememo's DisplayMessage; read/saved
 *  flags live on the enclosing TimelineItem envelope since the multi-source API. */
export interface DisplayMessage {
  id: number;
  channel_id: number;
  date: string;
  is_edited: boolean;
  edit_date: string | null;
  sender_id: number | null;
  sender_name: string | null;
  text: string | null;
  is_album: boolean;
  grouped_id: number | null;
  media_items: MediaItem[];
  webpage: WebPagePreview | null;
  is_forwarded: boolean;
  forward_info: ForwardInfo | null;
  views: number | null;
  forwards_count: number | null;
  replies_count: number | null;
  raw_message_ids: number[];
  // present on /api/records payloads only
  channel?: ChannelRef | null;
}

export type Source = 'telegram' | 'hn' | 'x';

/** The `hn` payload of a TimelineItem: one archived Hacker News story. */
export interface HnStory {
  id: number;
  title: string | null;
  url: string | null;
  domain: string | null;
  author: string | null;
  type: string | null;
  text: string | null;
  submitted_at: string | null;
  first_seen_at: string;
  score: number;
  comments_count: number;
  /** Query-time rank within the story's archive day; null on saved records. */
  day_rank: number | null;
  peak_rank: number | null;
  backfilled: boolean;
  /** Ingest-prefetched preview for `url`; null while unfetched / failed / self-post. */
  preview: LinkPreview | null;
}

/** One media attachment on a tweet — bird's shape, passed through verbatim
 *  (photo/video seen in the wild; width/height are always present for photos). */
export interface XMediaItem {
  type: string;
  url?: string | null;
  previewUrl?: string | null;
  videoUrl?: string | null;
  width?: number | null;
  height?: number | null;
  durationMs?: number | null;
}

export interface XMetrics {
  reply_count: number;
  retweet_count: number;
  like_count: number;
}

/** An X long-form post: bird exposes only the title + a ~200-char preview. */
export interface XArticle {
  title?: string | null;
  previewText?: string | null;
}

/** A quoted tweet, embedded at depth 1 inside the quoting tweet. */
export interface XQuote {
  id: string;
  author_handle: string | null;
  author_name: string | null;
  text: string | null;
  created_at: string | null;
  media: XMediaItem[] | null;
  metrics: XMetrics | null;
}

/** The `x` payload of a TimelineItem: one archived tweet, as it appeared in one feed. */
export interface XTweet {
  /** Snowflake id as a string — int64 exceeds JS's safe integer range. */
  id: string;
  author_id: string | null;
  author_handle: string | null;
  author_name: string | null;
  text: string | null;
  /** The tweet's own publish time; null when bird's timestamp failed to parse. */
  created_at: string | null;
  /** When the probe first pushed it — the For You sort key. */
  first_seen_at: string;
  media: XMediaItem[] | null;
  metrics: XMetrics | null;
  quote: XQuote | null;
  /** bird flattens retweets into an 'RT @handle:' text prefix — only the handle survives. */
  rt_of_handle: string | null;
  reply_to_id: string | null;
  article: XArticle | null;
  /** The subscription this appearance belongs to: 'foryou' or a followed handle. */
  feed: string;
  feed_kind: 'home' | 'following' | 'user';
  /** Feedback-driven judgement (plan Phase 4). null = not judged (no labels yet, or
   *  outside For You); 'neutral' = judged and deliberately non-committal. */
  verdict: XVerdict | null;
  verdict_meta: XVerdictMeta | null;
}

export type XVerdict = 'positive' | 'neutral' | 'negative';

/** One labeled tweet that voted on a verdict — the evidence behind the badge. */
export interface XVerdictNeighbor {
  tweet_id: string;
  /** Cosine distance: 0 = identical, 1 = unrelated. */
  distance: number;
  label: 'up' | 'down' | 'save';
  /** The neighbour's author, denormalized at judge time so the evidence reads as
   *  "like that post of @x's you marked down" without a second lookup. */
  handle?: string | null;
}

/** One channel's vote inside the ensemble meta (plan v2 step 4): its verdict at its
 *  own thresholds, its score on its own scale, and channel-specific evidence.
 *  Channel B carries no evidence here — its neighbours stay at the meta's top level
 *  (the pre-ensemble shape shipped clients decode). */
export interface XVerdictChannel {
  verdict: XVerdict | null;
  score: number;
  /** Step 5b: this channel scored into the archive but was not allowed to vote, so
   *  it could be measured on real traffic without badging anyone. An *abstaining*
   *  channel is absent from the block entirely — that is the difference. */
  shadow?: boolean;
  /** Channel C: the flag that decided, plus every sufficiently observed flag's score. */
  driver?: string;
  flags?: [string, number][];
  /** Channel D: the strongest evidence tokens with their log-odds. */
  tokens?: [string, number][];
  /** Channel A: the account and its record with you — the most readable evidence
   *  any channel produces, and the only one that needs no metric to interpret. */
  handle?: string;
  up?: number;
  down?: number;
}

/** Why the verdict came out the way it did. `reason` marks the two "did not judge"
 *  outcomes: too far from anything labeled, or no text to judge — both about the
 *  topic channel, which the top-level fields describe. */
export interface XVerdictMeta {
  score?: number;
  neighbors?: XVerdictNeighbor[];
  reason?: 'out_of_domain' | 'no_text';
  /** Present when more than channel B voted (algo 'vote-v1'): key -> that channel's
   *  vote. Only channels that actually spoke appear — abstention is absence. */
  channels?: Record<string, XVerdictChannel>;
  /** The embedding identity the score is comparable within, e.g. 'text-embedding-v4@256'. */
  model?: string;
  algo?: string;
}

/** The reader's own up/down label on an item (plan Phase 3) — the training signal
 *  Phase 4's verdict classifier learns from. Stored source-generically, exposed on
 *  X envelopes only until another source grows the buttons. */
export type ItemFeedback = 'up' | 'down';

/** The one-tap chip behind a thumbs-down: *which attribute* earned it. A bare down
 *  labels the whole tweet, but the cause is usually one of these — and a single
 *  embedding averages them all into one point, so "I hate this tone" reads as "I
 *  hate this topic". Closed taxonomy; each value aims at a different channel of the
 *  planned model (kb/notes/2026-07-24-x-verdict-multi-channel-discussion.md). */
export type ItemFeedbackReason = 'topic' | 'promo' | 'ai_slop' | 'engagement_farming' | 'author';

/** Multi-source item envelope: exactly one of `telegram` / `hn` / `x` is present. */
export interface TimelineItem {
  source: Source;
  /** Global item id, e.g. 'tg:123:45' / 'hn:678' / 'x:208…' — the read/save API currency. */
  key: string;
  /** Sort timestamp (ISO8601 UTC): TG = message time, HN = first front-page sighting,
   *  X = the tweet's time in a followed feed / the first sighting in For You. */
  datetime: string;
  is_read: boolean;
  is_saved: boolean;
  /** Absent on sources that don't expose feedback yet; null = unlabeled. */
  feedback?: ItemFeedback | null;
  /** The label's reason chip; null = the reader skipped it (a valid, lossless label). */
  feedback_reason?: ItemFeedbackReason | null;
  telegram?: DisplayMessage;
  hn?: HnStory;
  x?: XTweet;
}

/** What scroll-to-read reports: the item key plus its TG channel (for badge math). */
export interface ReadTarget {
  key: string;
  channelId: number | null;
}

/**
 * Unified, source-agnostic link preview from the backend (GET /api/preview and
 * /api/messages/{cid}/{mid}/previews). `source` is 'telegram' when the backend fell
 * back to Telegram's bonus preview; `tg_image_message_id`, when set, means the image
 * is available via the media proxy for that Telegram message. `error` is set in-band
 * when the fetch failed (the URL is still returned).
 */
export interface LinkPreview {
  url: string;
  title: string | null;
  description: string | null;
  image: string | null;
  site_name: string | null;
  source: 'fetched' | 'telegram';
  tg_image_message_id: number | null;
  error: string | null;
}

export interface Subscription {
  channel_id: number;
  enabled: boolean;
  backfill_done: boolean;
  title: string | null;
  username: string | null;
  unread: number;
}

/** One subscription row inside a GET /api/sources group; `channel_id` is a
 *  TG channel id (number) or a source-local feed key (string, e.g. HN 'front'). */
export interface SourceSub {
  channel_id: number | string;
  name: string | null;
  username: string | null;
  enabled: boolean;
  /** Unread in this subscription's own view. */
  unread: number;
  /** Its contribution to the aggregate All/Unread badge — the same number except
   *  for X's For You, where the aggregate only admits what the verdict let in. */
  aggregate_unread: number;
  config: Record<string, unknown> | null;
}

/** GET /api/sources — sources that have at least one subscription. */
export interface SourceGroup {
  source: Source;
  subscriptions: SourceSub[];
}

/** GET /api/hn/status — Hacker News source sampling + backfill state. */
export interface HnStatus {
  subscribed: boolean;
  enabled: boolean;
  /** Server-side master switch (CONDENSER_HN_ENABLED); false = no sampling loop exists. */
  source_enabled: boolean;
  config: { display_mode?: string } | null;
  last_poll_at: string | null;
  last_error: string | null;
  stories_total: number;
  stories_today: number;
  /** Days (YYYY-MM-DD) still waiting for the hckrnews history backfill. */
  backfill_pending_days: string[];
}

/** One X subscription, from GET /api/sources/x/subscriptions.
 *  `channel_id` is 'foryou' (the algorithmic feed), 'following' (the chronological
 *  accounts-you-follow timeline) or a followed account's lowercased handle;
 *  `user_id` is the rename-stable numeric id, learned from the first probe push. */
/** How much of a synthetic feed reaches the main timeline. For You is a firehose,
 *  so its middle setting is "only what the verdict recommends"; Following is never
 *  judged, so it only has none/all. */
export type XAggregateMode = 'none' | 'positive' | 'all';

export interface XSubscription {
  source: 'x';
  channel_id: string;
  kind: 'home' | 'following' | 'user';
  handle: string | null;
  user_id: string | null;
  name: string | null;
  enabled: boolean;
  /** Per-feed fetch-count override handed to the probe; null = the server default. */
  n: number | null;
  /** How much of this feed joins the aggregate timeline. Settable on For You and
   *  Following; a followed account is always 'all' (subscribing *is* the setting). */
  aggregate: XAggregateMode;
  added_at: string | null;
  /** Archived appearances of tweets in this feed. */
  tweets: number;
}

/** Per-feed summary of the last probe push (GET /api/x/status → last_push_counts). */
export interface XPushCount {
  at: string;
  received: number;
  stored: number;
  new_tweets: number;
  new_items: number;
  parse_errors: number;
  /** Following only: entries dropped as injected ads (author not in the follow list)
   *  and entries archived without a feed row because they fell outside the age window
   *  (X pads the feed with a thread's own ancestors). */
  filtered_ads: number;
  filtered_old: number;
}

export interface XStatus {
  /** Server-side master switch (CONDENSER_X_ENABLED); false = subscribe/ingest are refused. */
  source_enabled: boolean;
  subscribed: boolean;
  tweets_total: number;
  feed_items_total: number;
  /** Null until the local probe has pushed at least once. */
  last_push_at: string | null;
  last_push_counts: Record<string, XPushCount>;
  parse_errors: number;
  verdict: XVerdictStatus;
}

/** The For You verdict's own health (plan Phase 4): can it run, has the cold-start
 *  gate opened, and how much labeling is still needed before it does. */
export interface XVerdictStatus {
  enabled: boolean;
  /** The "not for you" half. Off since the 2026-07-27 backtest found it no better
   *  than guessing, so a fully trained verdict still shows no negative badges. */
  negative_enabled: boolean;
  embedding_configured: boolean;
  index_available: boolean;
  /** True once both label floors are met; until then everything stays unjudged. */
  ready: boolean;
  positives: number;
  negatives: number;
  needs_positive: number;
  needs_negative: number;
  /** Vectors in the KNN index, and vectors stored overall. */
  indexed: number;
  embedded: number;
  judged: { positive: number; neutral: number; negative: number };
  model: string;
  algo: string;
  last_run_at: string | null;
}

/** A broadcast channel the logged-in account follows, from GET /api/tg/dialogs. */
export interface JoinedChannel {
  channel_id: number;
  title: string | null;
  username: string | null;
  subscribed: boolean;
  /** Telegram-side unread count for the account (not condenser's read state). */
  unread: number;
}

export interface KeywordFilter {
  id: number;
  channel_id: number | null;
  /** Resolved on /api/filters; absent on per-channel endpoints that already know the channel. */
  channel_title?: string | null;
  pattern: string;
}

export interface FilterPreviewSample {
  channel_id: number;
  message_id: number;
  channel_title: string | null;
  date: string;
  text: string;
}

export interface FilterPreviewResult {
  scanned: number;
  matched: number;
  samples: FilterPreviewSample[];
}

export interface TimelinePage {
  items: TimelineItem[];
  next_cursor: string | null;
  /** Anchor of this page's last unit; present even when next_cursor is null,
   *  so a client can resume paging after fetch-older (iOS pull-up). */
  end_cursor: string | null;
  /** Anchor of the newest unit on this page; used to poll /timeline/new. */
  head_cursor: string | null;
}

export interface TimelineNew {
  count: number;
  items: TimelineItem[];
}

export interface DayCount {
  date: string;
  count: number;
}

/** Full-text search sort: newest first, or FTS5's bm25 relevance. Time is the
 *  default — bigram indexing makes relevance weaker for CJK than it looks. */
export type SearchSort = 'recent' | 'relevance';

/** Narrows results to items in one state; absent = every item in the archive. */
export type SearchStatus = 'unread' | 'saved';

/** GET /api/search — the same envelopes the timeline returns, so results render
 *  with the cards that already exist. `total` counts every hit, not just this page. */
export interface SearchPage {
  items: TimelineItem[];
  total: number;
  has_more: boolean;
}

export interface SearchParams {
  q: string;
  /** Same three scope parameters the timeline takes; channel_id implies telegram. */
  source?: Source | null;
  channel_id?: number | null;
  feed?: string | null;
  status?: SearchStatus | null;
  sort?: SearchSort;
  offset?: number;
  limit?: number;
}

export interface TimelineParams {
  cursor?: string | null;
  limit?: number;
  channel_id?: number | null;
  date?: string | null;
  unread_only?: boolean;
  /** Narrow the query to one source; channel_id already implies telegram. */
  source?: Source | null;
  /** Narrow further inside a multi-feed source (X): one feed key. */
  feed?: string | null;
}

/** HN front-feed display mode: how many of each day's top stories are visible. */
export type HnDisplayMode = 'top10' | 'top20' | 'half' | 'all';

/** A (channel_id, message_id) pair for Telegram-scoped endpoints (media, previews). */
export interface MsgRef {
  channel_id: number;
  message_id: number;
}

/** One reaction bucket on a message (GET /api/messages/{cid}/{mid}/stats). `kind` is the
 *  discriminator: 'emoji' carries a unicode `emoji`, 'custom' a `document_id` (glyph not
 *  resolved — UI degrades to a generic icon), 'other' is the forward-compatible bucket. */
export interface ReactionCount {
  kind: 'emoji' | 'custom' | 'other';
  emoji: string | null;
  document_id: number | null;
  count: number;
  /** The logged-in account reacted with this itself. */
  chosen: boolean;
}

/** Live engagement numbers for one message; null = the channel doesn't carry it. */
export interface MessageStats {
  views: number | null;
  forwards: number | null;
  reactions: ReactionCount[];
}

/** POST /api/messages/{cid}/{mid}/forward — `mode` tells which path ran:
 *  'quote' = new message with comment + t.me link, 'forward' = native forward. */
export interface ForwardResult {
  status: 'ok';
  mode: 'quote' | 'forward';
  /** t.me link of the message that just landed in the target channel. */
  link: string;
}

/** GET /api/app/meta — runtime app settings. */
export interface AppMeta {
  schema_version: number;
  backfill_days: number;
  /** Target channel for "forward to my channel" (@handle / t.me link); null = unset. */
  forward_channel: string | null;
}

/** An authorized client device (bearer token holder); the token itself is never listed. */
export interface Device {
  id: number;
  name: string;
  created_at: string;
  last_seen_at: string | null;
}
