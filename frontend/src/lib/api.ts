// Typed fetch client for the condenser JSON API. Auth is a signed HttpOnly cookie
// issued by /api/auth/login; the dev Vite proxy keeps it same-origin.

import type {
  AppMeta,
  DayCount,
  Device,
  FilterPreviewResult,
  ForwardResult,
  HnStatus,
  ItemFeedback,
  ItemFeedbackReason,
  JoinedChannel,
  KeywordFilter,
  LinkPreview,
  MessageStats,
  SearchPage,
  SearchParams,
  Source,
  SourceGroup,
  Subscription,
  TgStatus,
  TimelineItem,
  TimelineNew,
  TimelinePage,
  TimelineParams,
  XStatus,
  XSubscription,
} from './types';

/** Result of a batch subscribe (POST /api/subscriptions/batch). */
export interface BatchSubscribeResult {
  added: { channel_id: number; title: string | null; username: string | null }[];
  failed: { channel_id: number; error: string }[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

/** Human-readable message for a caught error, falling back when it isn't an ApiError. */
export function errorMessage(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

type Json = unknown;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get('content-type') ?? '';
  if (!ct.includes('application/json')) return undefined as T;
  return (await res.json()) as T;
}

function post<T>(path: string, body?: Json): Promise<T> {
  return request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
}

function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' });
}

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export const api = {
  // ---- app auth ----
  login: (password: string) => post<{ ok: true }>('/api/auth/login', { password }),
  logout: () => post<{ ok: true }>('/api/auth/logout'),

  // ---- devices (client bearer tokens; cookie-authed management) ----
  // The raw token appears in this response only — hand it to the device, never store it.
  createDevice: (name: string) => post<{ id: number; name: string; token: string }>('/api/auth/device', { name }),
  listDevices: () => request<Device[]>('/api/auth/devices'),
  deleteDevice: (deviceId: number) => del<{ ok: true }>(`/api/auth/devices/${deviceId}`),

  // ---- telegram step-login ----
  tgStatus: () => request<{ status: TgStatus; phone?: string | null }>('/api/tg/status'),
  tgSendCode: (phone: string) => post<{ status: TgStatus }>('/api/tg/send-code', { phone }),
  tgSignIn: (code: string) => post<{ status: TgStatus; result: string }>('/api/tg/sign-in', { code }),
  tgSignIn2fa: (password: string) => post<{ status: TgStatus; result: string }>('/api/tg/sign-in-2fa', { password }),
  tgLogout: () => post<{ status: TgStatus }>('/api/tg/logout'),
  // The account's joined broadcast channels; `refresh` bypasses the backend TTL cache.
  tgDialogs: (refresh = false) => request<JoinedChannel[]>('/api/tg/dialogs' + qs({ refresh: refresh || undefined })),
  // Manual content refresh: all enabled channels (background) or one channel (sync, returns new count).
  tgRefreshAll: () => post<{ status: string; channels: number }>('/api/tg/refresh'),
  tgRefreshChannel: (channelId: number) => post<{ status: string; new: number }>(`/api/tg/refresh/${channelId}`),
  // Page further back into one channel's history (older than the oldest stored message).
  tgFetchOlder: (channelId: number, count = 200) =>
    post<{ status: string; fetched: number }>(`/api/tg/fetch-older/${channelId}` + qs({ count })),
  // Destructive: wipe one channel's cached messages + read state, then re-sync from scratch.
  tgResetChannel: (channelId: number) =>
    post<{ status: string; deleted: number; fetched: number }>(`/api/tg/reset/${channelId}`),

  // ---- subscriptions ----
  listSubscriptions: () => request<Subscription[]>('/api/subscriptions'),
  addSubscription: (handle: string) =>
    post<{ channel_id: number; title: string | null; username: string | null }>('/api/subscriptions', {
      handle,
    }),
  addSubscriptionsBatch: (channelIds: number[]) =>
    post<BatchSubscribeResult>('/api/subscriptions/batch', { channel_ids: channelIds }),
  setSubscriptionEnabled: (channelId: number, enabled: boolean) =>
    request<{ ok: true }>(`/api/subscriptions/${channelId}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
  deleteSubscription: (channelId: number) => del<{ ok: true }>(`/api/subscriptions/${channelId}`),

  // ---- hacker news source (Phase 1 minimal management; full /api/sources arrives in Phase 2) ----
  hnStatus: () => request<HnStatus>('/api/hn/status'),
  hnSubscribe: () =>
    post<{ source: 'hn'; channel_id: string; name: string; enabled: boolean }>('/api/sources/hn/subscriptions', {
      channel_id: 'front',
    }),
  hnSetEnabled: (enabled: boolean) =>
    request<{ ok: true }>('/api/sources/hn/subscriptions/front', {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
  hnUnsubscribe: () => del<{ ok: true }>('/api/sources/hn/subscriptions/front'),
  // Front-feed display config (e.g. {display_mode: 'top10'}); merged server-side as the whole config.
  hnSetConfig: (config: Record<string, unknown>) =>
    request<{ ok: true }>('/api/sources/hn/subscriptions/front', {
      method: 'PATCH',
      body: JSON.stringify({ config }),
    }),

  // ---- x source (Phase 1 management; the data itself is pushed by the local probe) ----
  xStatus: () => request<XStatus>('/api/x/status'),
  listXSubscriptions: () => request<XSubscription[]>('/api/sources/x/subscriptions'),
  // channel_id: 'foryou' or a handle ('@name' / 'name'); the server normalizes it.
  xSubscribe: (channelId: string) => post<XSubscription>('/api/sources/x/subscriptions', { channel_id: channelId }),
  xSetEnabled: (channelId: string, enabled: boolean) =>
    request<XSubscription>(`/api/sources/x/subscriptions/${channelId}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
  // config is merged server-side, so a partial patch can't drop the learned handle/user_id
  xSetConfig: (channelId: string, config: Record<string, unknown>) =>
    request<XSubscription>(`/api/sources/x/subscriptions/${channelId}`, {
      method: 'PATCH',
      body: JSON.stringify({ config }),
    }),
  xUnsubscribe: (channelId: string) => del<{ ok: true }>(`/api/sources/x/subscriptions/${channelId}`),

  // ---- sources (two-level source -> subscriptions listing, Phase 2) ----
  listSources: () => request<SourceGroup[]>('/api/sources'),

  // ---- keyword filters ----
  // Global + per-channel listing (channel_id=null = global).
  listAllFilters: () => request<KeywordFilter[]>('/api/filters'),
  createFilter: (pattern: string, channelId: number | null) =>
    post<KeywordFilter>('/api/filters', { pattern, channel_id: channelId }),
  deleteFilter: (filterId: number) => del<{ ok: true }>(`/api/filters/${filterId}`),
  // Dry-run the same matcher against the last N messages so the user sees what a new rule would hide.
  previewFilter: (pattern: string, channelId: number | null) =>
    post<FilterPreviewResult>('/api/filters/preview', { pattern, channel_id: channelId }),

  // ---- timeline / reading ----
  timeline: (params: TimelineParams) =>
    request<TimelinePage>(
      '/api/timeline' +
        qs({
          cursor: params.cursor,
          limit: params.limit,
          channel_id: params.channel_id,
          date: params.date,
          unread_only: params.unread_only,
          source: params.source,
          feed: params.feed,
        }),
    ),
  timelineDays: (channelId?: number | null, source?: Source | null, feed?: string | null) =>
    request<DayCount[]>('/api/timeline/days' + qs({ channel_id: channelId, source, feed })),
  timelineNew: (
    after: string,
    channelId?: number | null,
    limit = 100,
    unreadOnly = false,
    source?: Source | null,
    feed?: string | null,
  ) =>
    request<TimelineNew>(
      '/api/timeline/new' +
        qs({ after, channel_id: channelId, limit, unread_only: unreadOnly || undefined, source, feed }),
    ),

  // ---- full-text search ----
  // Offset paging rather than a cursor: search browses an archive instead of
  // draining a queue, so the drift a cursor exists to prevent doesn't matter here.
  search: (params: SearchParams) =>
    request<SearchPage>(
      '/api/search' +
        qs({
          q: params.q,
          source: params.source,
          channel_id: params.channel_id,
          feed: params.feed,
          status: params.status,
          sort: params.sort,
          offset: params.offset,
          limit: params.limit,
        }),
    ),

  markRead: (keys: string[]) => post<{ ok: true }>('/api/read', { keys }),

  // ---- hidden items (never show in any timeline again; server-enforced for all clients) ----
  hideItem: (key: string) => post<{ ok: true }>('/api/hidden', { key }),
  unhideItem: (key: string) => del<{ ok: true }>(`/api/hidden/${encodeURIComponent(key)}`),

  // ---- feedback (up/down labels; only recorded, nothing is filtered by them yet) ----
  // A call states the *whole* label: sending no reason clears a stored one, which is
  // what makes correcting a down-with-reason into an up drop the stale attribute.
  setFeedback: (key: string, verdict: ItemFeedback, reason: ItemFeedbackReason | null = null) =>
    post<{ ok: true }>('/api/feedback', { key, verdict, reason }),
  clearFeedback: (key: string) => del<{ ok: true }>(`/api/feedback/${encodeURIComponent(key)}`),

  markReadBulk: (body: {
    channel_id?: number | null;
    before_date?: string | null;
    source?: Source | null;
    feed?: string | null;
  }) => post<{ ok: true }>('/api/read/bulk', body),

  // ---- message actions (live Telegram reads/writes) ----
  // Views/forwards/reactions, read live from Telegram each time (never cached server-side).
  messageStats: (channelId: number, messageId: number) =>
    request<MessageStats>(`/api/messages/${channelId}/${messageId}/stats`),
  // Republish any item into the configured forward channel. A TG item forwards natively
  // (or quotes its t.me link); the other sources are rendered into a message server-side.
  forwardItem: (key: string, comment?: string) =>
    post<ForwardResult>('/api/forward', { key, comment: comment ?? null }),

  // ---- app meta (runtime settings) ----
  getAppMeta: () => request<AppMeta>('/api/app/meta'),
  patchAppMeta: (patch: Partial<Pick<AppMeta, 'backfill_days' | 'forward_channel'>>) =>
    request<AppMeta>('/api/app/meta', { method: 'PATCH', body: JSON.stringify(patch) }),

  // ---- link previews ----
  // Previews for every URL in a message (album-aware; Telegram's preview folded in as a bonus).
  messagePreviews: (channelId: number, messageId: number) =>
    request<LinkPreview[]>(`/api/messages/${channelId}/${messageId}/previews`),
  // Generic single-URL preview (reusable for future feed types).
  urlPreview: (url: string) => request<LinkPreview>('/api/preview' + qs({ url })),

  // ---- records (saved) ----
  listRecords: () => request<TimelineItem[]>('/api/records'),
  saveRecord: (key: string) => post<{ ok: true }>('/api/records', { key }),
  deleteRecord: (key: string) => del<{ ok: true }>(`/api/records/${encodeURIComponent(key)}`),
};

/** URL for the media proxy; `thumb` requests the small preview. */
export function mediaUrl(channelId: number, messageId: number, thumb = false): string {
  return `/api/media/${channelId}/${messageId}${thumb ? '?thumb=1' : ''}`;
}

/** URL for a channel's avatar proxy; 404/503 lets the UI fall back to a letter. */
export function channelAvatarUrl(channelId: number): string {
  return `/api/channels/${channelId}/avatar`;
}

/** Proxy a preview's thumbnail through the backend (private + hotlink-proof). */
export function previewImageUrl(originUrl: string): string {
  return `/api/preview/image?url=${encodeURIComponent(originUrl)}`;
}

/** X author avatar proxy (bird carries no avatar URL); 404 = draw a letter instead. */
export function xAvatarUrl(handle: string): string {
  return `/api/x/avatar/${encodeURIComponent(handle)}`;
}
