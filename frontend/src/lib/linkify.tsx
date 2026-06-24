import type { ReactNode } from 'react';

import { TRAILING, URL_RE } from './extractUrls';

// v1 renders plain text + clickable URLs only (no rich entities — the backend
// does not persist Telegram message entities yet; see spec D3 note). The URL regex
// is shared with `extractUrls` so what we linkify matches what the preview pane fetches.

export function linkify(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  URL_RE.lastIndex = 0;
  let i = 0;
  while ((m = URL_RE.exec(text)) !== null) {
    const start = m.index;
    let url = m[0];
    let trailing = '';
    const trail = url.match(TRAILING);
    if (trail) {
      trailing = trail[0];
      url = url.slice(0, -trailing.length);
    }
    if (start > last) out.push(text.slice(last, start));
    const href = url.startsWith('www.') ? `https://${url}` : url;
    out.push(
      <a key={`l${i++}`} href={href} target="_blank" rel="noopener noreferrer nofollow" className="msg-link">
        {url}
      </a>,
    );
    if (trailing) out.push(trailing);
    last = start + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
