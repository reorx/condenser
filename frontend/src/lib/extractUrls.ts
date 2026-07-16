// Single source of truth for URL matching, shared by `linkify` (rendering) and the
// link-preview pane (which URLs to preview) so the two can never drift.
export const URL_RE = /(https?:\/\/[^\s<]+|www\.[^\s<]+)/gi;
// Trailing punctuation that is almost never part of the URL itself.
export const TRAILING = /[.,;:!?)\]}'"]+$/;

/** Strip trailing punctuation and upgrade a bare `www.` link to an absolute https URL. */
export function cleanUrl(raw: string): string {
  const url = raw.replace(TRAILING, '');
  return url.toLowerCase().startsWith('www.') ? `https://${url}` : url;
}

/** Every URL in `text`, de-duplicated (by cleaned form), order preserved. */
export function extractUrls(text: string | null | undefined): string[] {
  if (!text) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  URL_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = URL_RE.exec(text)) !== null) {
    const url = cleanUrl(m[0]);
    if (!seen.has(url)) {
      seen.add(url);
      out.push(url);
    }
  }
  return out;
}

/** Loose equality for "is this the same link" checks (ignores scheme/www/trailing slash). */
export function sameUrl(a: string, b: string): boolean {
  const loose = (u: string) =>
    u
      .trim()
      .toLowerCase()
      .replace(/^https?:\/\//, '')
      .replace(/^www\./, '')
      .replace(/\/+$/, '');
  return loose(a) === loose(b);
}
