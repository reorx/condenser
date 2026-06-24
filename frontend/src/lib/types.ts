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

/** One display unit (album-collapsed). Matches telememo's DisplayMessage + condenser flags. */
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
  // condenser-added flags
  is_read?: boolean;
  is_saved?: boolean;
  // present on /api/records only
  channel?: ChannelRef | null;
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
  items: DisplayMessage[];
  next_cursor: string | null;
  /** Anchor of the newest unit on this page; used to poll /timeline/new. */
  head_cursor: string | null;
}

export interface TimelineNew {
  count: number;
  items: DisplayMessage[];
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
}

/** A (channel_id, message_id) pair used for read-marking and saving. */
export interface MsgRef {
  channel_id: number;
  message_id: number;
}
