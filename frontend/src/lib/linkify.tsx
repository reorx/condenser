import type { ReactNode } from 'react';

import { TRAILING, URL_RE } from './extractUrls';
import { urlEntityMap } from './xUrls';
import type { XUrlEntity } from './types';

// v1 renders plain text + clickable URLs only (no rich entities — the backend
// does not persist Telegram message entities yet; see spec D3 note). The URL regex
// is shared with `extractUrls` so what we linkify matches what the preview pane fetches.
//
// `urlEntities` (X only, schema v13) upgrades a matched t.co to its original link:
// anchor text = display_url, href = expanded_url — X's own UI behavior. An
// unmatched t.co (old rows, un-upgraded probe) renders verbatim, per entry.

export function linkify(text: string, urlEntities?: XUrlEntity[] | null): ReactNode[] {
  const entities = urlEntityMap(urlEntities);
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
    const entity = entities.get(url);
    const href = entity?.expanded_url ?? (url.startsWith('www.') ? `https://${url}` : url);
    const label = (entity && (entity.display_url ?? entity.expanded_url)) ?? url;
    out.push(
      <a key={`l${i++}`} href={href} target="_blank" rel="noopener noreferrer nofollow" className="msg-link">
        {label}
      </a>,
    );
    if (trailing) out.push(trailing);
    last = start + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
