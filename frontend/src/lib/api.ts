// Typed fetch client for the condenser JSON API. Auth is a signed HttpOnly cookie
// issued by /api/auth/login; the dev Vite proxy keeps it same-origin.

import type {
  DayCount,
  DisplayMessage,
  FilterPreviewResult,
  JoinedChannel,
  KeywordFilter,
  MsgRef,
  Subscription,
  TgStatus,
  TimelineNew,
  TimelinePage,
  TimelineParams,
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
        }),
    ),
  timelineDays: (channelId?: number | null) =>
    request<DayCount[]>('/api/timeline/days' + qs({ channel_id: channelId })),
  timelineNew: (after: string, channelId?: number | null, limit = 100) =>
    request<TimelineNew>('/api/timeline/new' + qs({ after, channel_id: channelId, limit })),

  markRead: (items: MsgRef[]) => post<{ ok: true }>('/api/read', { items }),
  markReadBulk: (body: { channel_id?: number | null; before_date?: string | null }) =>
    post<{ ok: true }>('/api/read/bulk', body),

  // ---- records (saved) ----
  listRecords: () => request<DisplayMessage[]>('/api/records'),
  saveRecord: (ref: MsgRef) => post<{ ok: true }>('/api/records', ref),
  deleteRecord: (ref: MsgRef) => del<{ ok: true }>(`/api/records/${ref.channel_id}/${ref.message_id}`),
};

/** URL for the media proxy; `thumb` requests the small preview. */
export function mediaUrl(channelId: number, messageId: number, thumb = false): string {
  return `/api/media/${channelId}/${messageId}${thumb ? '?thumb=1' : ''}`;
}

/** URL for a channel's avatar proxy; 404/503 lets the UI fall back to a letter. */
export function channelAvatarUrl(channelId: number): string {
  return `/api/channels/${channelId}/avatar`;
}
