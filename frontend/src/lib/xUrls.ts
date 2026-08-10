// t.co expansion (schema v13): the pure logic behind rendering a tweet's rewritten
// links as their originals. Replacement is by exact t.co string — a t.co is a
// globally unique token, while the entities' `indices` are offsets into X's raw
// text and misalign once the RT prefix or an article title is stripped.
import type { XUrlEntity } from './types';

/** t.co → its entity. Accepts null/undefined so callers can pass `tweet.urls` as is. */
export function urlEntityMap(urls: XUrlEntity[] | null | undefined): Map<string, XUrlEntity> {
  return new Map((urls ?? []).map((e) => [e.url, e]));
}

const TRAILING_TCO = /\s*https?:\/\/t\.co\/[A-Za-z0-9]+\s*$/;

/** Hide a trailing t.co that stands for the tweet's own media (X's UI behavior).
 *  Only at the very end of the text, only when the tweet has media, and never for
 *  a t.co the url entities know — that one is a real outbound link. */
export function stripTrailingMediaTco(text: string, entities: Map<string, XUrlEntity>, hasMedia: boolean): string {
  if (!hasMedia) return text;
  const m = text.match(TRAILING_TCO);
  if (!m) return text;
  const tco = m[0].trim();
  if (entities.has(tco)) return text;
  return text.slice(0, m.index).replace(/\s+$/, '');
}
