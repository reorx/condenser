// t.co expansion (schema v13): the pure logic behind rendering a tweet's rewritten
// links as their originals. Replacement is by exact t.co string — a t.co is a
// globally unique token, while the entities' `indices` are offsets into X's raw
// text and misalign once the RT prefix or an article title is stripped.
import type { XTweet, XUrlEntity } from './types';

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

/** The text to print as the tweet body, or null when there is nothing left to print.
 *  Two upstream quirks are absorbed here: retweets arrive only as an 'RT @orig: …'
 *  prefix (bird flattens them — the prefix becomes the caption instead), and a
 *  long-form post's `text` *is* its article title, which the article card already
 *  shows. A trailing t.co the url entities don't know stands for the media shown
 *  right below (X's own UI hides it too).
 *
 *  Shared by `XCard` and the detail pane's annotatable body — one derivation, so a
 *  highlight quoted from either surface relocates on the other (and on iOS, whose
 *  `xDisplayedText` mirrors these rules). */
export function xBodyText(tweet: XTweet): string | null {
  if (!tweet.text) return null;
  let text = tweet.rt_of_handle ? tweet.text.replace(/^RT @[A-Za-z0-9_]{1,15}:\s*/, '') : tweet.text;
  if (tweet.article?.title && tweet.article.title.trim() === text.trim()) return null;
  // urls null (old rows / a tweet with no outbound links) counts as an empty set:
  // a trailing t.co beside media is the media's self-link either way.
  text = stripTrailingMediaTco(text, urlEntityMap(tweet.urls), (tweet.media?.length ?? 0) > 0);
  return text || null;
}
