import type { Source, SourceSub } from './types';

const LABELS: Record<Source, string> = {
  telegram: 'Telegram',
  hn: 'Hacker News',
};

export function isSource(v: string | undefined | null): v is Source {
  return v === 'telegram' || v === 'hn';
}

/** Display name for a source group (sidebar headers, /s/:source view titles). */
export function sourceLabel(source: Source): string {
  return LABELS[source];
}

/** The HN discussion page for a story (comments URLs are client-assembled). */
export function hnCommentsUrl(storyId: number): string {
  return `https://news.ycombinator.com/item?id=${storyId}`;
}

/** Display name for a /api/sources subscription row (`name` is already
 *  COALESCE(sub.name, source-side title) server-side). */
export function sourceSubLabel(sub: SourceSub): string {
  if (sub.name) return sub.name;
  if (sub.username) return `@${sub.username}`;
  return typeof sub.channel_id === 'number' ? `Channel ${sub.channel_id}` : String(sub.channel_id);
}
