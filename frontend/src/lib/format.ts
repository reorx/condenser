import { format, isToday, isYesterday, parseISO } from 'date-fns';

import type { ChannelRef, Subscription } from './types';

/**
 * Backend datetimes are naive ISO strings that are actually UTC (Telegram is UTC,
 * stored without tz). Append 'Z' so they render correctly in the user's locale.
 */
export function parseDate(s: string | null | undefined): Date | null {
  if (!s) return null;
  const hasTz = /[zZ]$/.test(s) || /[+-]\d\d:?\d\d$/.test(s);
  return parseISO(hasTz ? s : `${s}Z`);
}

export function timeLabel(s: string): string {
  const d = parseDate(s);
  return d ? format(d, 'HH:mm') : '';
}

export function dayLabel(s: string): string {
  const d = parseDate(s);
  if (!d) return '';
  if (isToday(d)) return 'Today';
  if (isYesterday(d)) return 'Yesterday';
  return format(d, 'EEE, MMM d');
}

export function fullDateLabel(s: string): string {
  const d = parseDate(s);
  return d ? format(d, 'MMM d, yyyy · HH:mm') : '';
}

/** ISO day key (YYYY-MM-DD) in UTC, matching the backend's substr(date,1,10). */
export function dayKey(s: string): string {
  return s.slice(0, 10);
}

export function compactNumber(n: number | null | undefined): string {
  if (n == null) return '';
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0).replace(/\.0$/, '')}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
}

export function channelName(c: Pick<Subscription, 'title' | 'username' | 'channel_id'>): string;
export function channelName(c: ChannelRef | null | undefined): string;
export function channelName(
  c: Pick<Subscription, 'title' | 'username' | 'channel_id'> | ChannelRef | null | undefined,
): string {
  if (!c) return 'Unknown channel';
  if (c.title) return c.title;
  if (c.username) return `@${c.username}`;
  const id = 'channel_id' in c ? c.channel_id : c.id;
  return `Channel ${id}`;
}
