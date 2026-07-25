import { XAvatar } from '@/components/XAvatar';
import { timeLabel } from '@/lib/format';
import { linkify } from '@/lib/linkify';
import { xTweetUrl } from '@/lib/sources';
import type { XQuote } from '@/lib/types';

import { XMedia } from './XMedia';

/** The quoted tweet embedded inside a quote tweet — a bordered, muted sub-card,
 *  visually the same language as MessageCard's forward box. bird gives us the full
 *  quoted object at depth 1, so it renders with its own author, text and media. */
export function XQuoteCard({ quote }: { quote: XQuote }) {
  return (
    <a
      href={xTweetUrl(quote.id, quote.author_handle)}
      target="_blank"
      rel="noreferrer"
      className="mt-2 block rounded-lg border bg-muted/30 p-3 transition-colors hover:bg-muted/50"
    >
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <XAvatar handle={quote.author_handle} name={quote.author_name} className="size-4 text-[8px]" />
        {quote.author_name && <span className="truncate font-medium text-foreground/80">{quote.author_name}</span>}
        {quote.author_handle && <span className="truncate">@{quote.author_handle}</span>}
        {quote.created_at && (
          <>
            <span aria-hidden>·</span>
            <time>{timeLabel(quote.created_at)}</time>
          </>
        )}
      </div>
      {quote.text && (
        <p className="mt-1 text-sm leading-relaxed whitespace-pre-wrap text-foreground/90">{linkify(quote.text)}</p>
      )}
      {quote.media && quote.media.length > 0 && <XMedia items={quote.media} />}
    </a>
  );
}
