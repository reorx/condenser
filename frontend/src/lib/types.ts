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

export type Source = 'telegram' | 'hn';

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
}

/** Multi-source item envelope: exactly one of `telegram` / `hn` is present. */
export interface TimelineItem {
  source: Source;
  /** Global item id, e.g. 'tg:123:45' / 'hn:678' — the read/save API currency. */
  key: string;
  /** Sort timestamp (ISO8601 UTC): TG = message time, HN = first front-page sighting. */
  datetime: string;
  is_read: boolean;
  is_saved: boolean;
  telegram?: DisplayMessage;
  hn?: HnStory;
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
  unread: number;
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

export interface TimelineParams {
  cursor?: string | null;
  limit?: number;
  channel_id?: number | null;
  date?: string | null;
  unread_only?: boolean;
  /** Narrow the query to one source; channel_id already implies telegram. */
  source?: Source | null;
}

/** HN front-feed display mode: how many of each day's top stories are visible. */
export type HnDisplayMode = 'top10' | 'top20' | 'half' | 'all';

/** A (channel_id, message_id) pair for Telegram-scoped endpoints (media, previews). */
export interface MsgRef {
  channel_id: number;
  message_id: number;
}

/** An authorized client device (bearer token holder); the token itself is never listed. */
export interface Device {
  id: number;
  name: string;
  created_at: string;
  last_seen_at: string | null;
}
