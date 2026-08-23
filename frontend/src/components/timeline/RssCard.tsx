// One feed entry: the feed as the header subject, the title as the main act, and a
// body that is the LLM summary when there is one and the article's plain-text
// excerpt when there is not (plan §0.4). Which of the two you are reading is marked,
// because a summary is a machine's paraphrase and a card that hides that is lying
// quietly.
import { memo, useCallback, useState } from 'react';
import { Bookmark } from 'lucide-react';

import { RssGlyph } from '@/components/RssGlyph';
import { Spinner } from '@/components/Spinner';
import { useRssArticle } from '@/hooks/useRssArticle';
import { useSaveToggle } from '@/hooks/useSaveToggle';
import { fullDateLabel, timeLabel } from '@/lib/format';
import { useItemDetailPane } from '@/lib/itemDetailPane';
import { sanitizeHtml } from '@/lib/sanitize';
import { rssFeedLabel } from '@/lib/sources';
import { useUnreadIndicator } from '@/lib/unreadIndicator';
import { cn } from '@/lib/utils';
import type { ReadTarget, RssEntry, TimelineItem } from '@/lib/types';

import { ForwardedBadge } from './ForwardedBadge';

interface Props {
  /** Envelope with `rss` present. */
  item: TimelineItem;
  /** Attach for scroll-past-to-read; omit in the saved/search views. */
  observe?: (el: Element | null, target: ReadTarget) => (() => void) | void;
  /** Keys judged read but awaiting server confirmation (green "syncing" state). */
  pendingKeys?: Set<string>;
}

/** Tailwind for the article HTML once it has been fetched. */
const ARTICLE_PROSE = cn(
  'text-sm leading-relaxed break-words text-foreground/90',
  '[&_a]:break-all [&_a]:underline [&_a]:underline-offset-2 [&_p]:mt-2 [&_p:first-child]:mt-0',
  '[&_pre]:mt-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-muted/50 [&_pre]:p-2 [&_pre]:text-xs',
  // Feed bodies carry full-resolution images, and one 1600px photo makes a card
  // taller than the viewport — the timeline stops being scannable at the first
  // illustrated post. Capped rather than dropped: the picture is part of the post,
  // and the original is one click away. Height only, so the browser keeps the
  // aspect ratio itself.
  '[&_img]:mt-2 [&_img]:max-h-80 [&_img]:max-w-full [&_img]:rounded',
);

/** The entry's body: the list's plain-text excerpt, with the article behind "more".
 *
 * The timeline payload stopped carrying feed bodies on 2026-08-23 — they averaged
 * 13.9KB and topped out at 7.1MB, thirty per page — so what is on the card is the
 * backend's already-stripped excerpt (no markup, nothing to sanitize), and clicking
 * "more" fetches the article from `/api/rss/entries/{id}`. Only used when there is
 * no summary.
 */
function RssBody({ entry }: { entry: RssEntry }) {
  const [expanded, setExpanded] = useState(false);
  const article = useRssArticle(expanded ? entry.id : null);
  const html = article.data?.rss?.content ?? null;
  // "more" is offered on the server's word (`content_truncated`), not on a length
  // guess here: the excerpt is cut server-side, and only that side knows whether
  // anything was left behind. Once the article is in hand the toggle stays, to
  // fold it back up.
  const expandable = entry.content_truncated || expanded;

  return (
    <div className="mt-1">
      {expanded && html ? (
        <div
          className={ARTICLE_PROSE}
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{ __html: sanitizeHtml(html) }}
        />
      ) : (
        <p className={cn('text-sm leading-relaxed break-words text-foreground/90', !expanded && 'line-clamp-5')}>
          {entry.content_excerpt}
        </p>
      )}
      {expandable && (
        <div className="mt-1 flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="text-xs font-medium text-sky-600 hover:underline dark:text-sky-400"
          >
            {expanded ? 'less' : 'more'}
          </button>
          {expanded && article.isPending && <Spinner className="size-3 text-muted-foreground" />}
          {/* A failed expand degrades to the excerpt above rather than blanking the
              body — it is still a true rendering of the entry, just a short one. */}
          {expanded && article.isError && <span className="text-xs text-muted-foreground">正文加载失败</span>}
        </div>
      )}
    </div>
  );
}

function RssCardImpl({ item, observe, pendingKeys }: Props) {
  const rss = item.rss!;
  const save = useSaveToggle();
  const { mode } = useUnreadIndicator();
  const { open, openPane } = useItemDetailPane();

  const attach = useCallback(
    (el: HTMLElement | null) => {
      if (observe && el && !item.is_read) return observe(el, { key: item.key, channelId: null });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [observe, item.is_read, item.key],
  );

  const feedName = rssFeedLabel(rss.feed_url, rss.feed_title);
  const isActive = open?.key === item.key;
  // Three read states: pending (judged read, sync unconfirmed) > unread > read.
  const isPending = pendingKeys?.has(item.key) ?? false;
  // The declared time is what the card shows; the sort position can differ when the
  // feed's own timestamp was missing or implausible, so the tooltip names both.
  const shown = rss.published_at ?? item.datetime;
  const timeTitle =
    rss.published_at && rss.published_at !== item.datetime
      ? `${fullDateLabel(rss.published_at)} · 时间线位置 ${fullDateLabel(item.datetime)}`
      : fullDateLabel(item.datetime);

  return (
    <article
      ref={attach}
      data-read={item.is_read ? '' : undefined}
      className={cn(
        'group relative border-b px-4 py-3 transition-colors duration-500 sm:px-5',
        mode !== 'divider'
          ? 'border-border/50'
          : isPending
            ? 'border-emerald-500 dark:border-emerald-400'
            : !item.is_read
              ? 'border-sky-500 dark:border-sky-400'
              : 'border-border/50',
        isActive && 'bg-muted/40',
      )}
    >
      <header className="flex items-center gap-2 text-xs text-muted-foreground">
        <div className="relative flex min-w-0 items-center gap-2">
          {mode === 'dot' && (
            <span
              aria-hidden
              className={cn(
                'absolute top-1/2 right-full mr-1.5 size-2 -translate-y-1/2 rounded-full transition-colors duration-500',
                isPending ? 'bg-emerald-500 dark:bg-emerald-400' : !item.is_read && 'bg-sky-500 dark:bg-sky-400',
              )}
            />
          )}
          <RssGlyph />
          <span className="truncate font-medium text-foreground/80">{feedName}</span>
        </div>
        <span aria-hidden>·</span>
        {/* Details-pane entry on the time, as on every other card. */}
        <button
          type="button"
          onClick={() => openPane(item)}
          title={timeTitle}
          aria-label="Open entry details"
          className="shrink-0 cursor-pointer rounded underline-offset-2 transition-colors hover:text-foreground hover:underline"
        >
          <time>{timeLabel(shown)}</time>
        </button>
        <ForwardedBadge item={item} />
        <button
          type="button"
          onClick={() => save.mutate({ key: item.key, saved: !item.is_saved })}
          aria-label={item.is_saved ? 'Remove from saved' : 'Save'}
          aria-pressed={item.is_saved}
          className={cn(
            'ml-auto shrink-0 rounded p-1 transition-colors hover:bg-accent hover:text-accent-foreground',
            item.is_saved ? 'text-amber-500' : 'text-muted-foreground',
          )}
        >
          <Bookmark className={cn('size-4', item.is_saved && 'fill-current')} />
        </button>
      </header>

      {rss.link ? (
        <a
          href={rss.link}
          target="_blank"
          rel="noreferrer"
          className="mt-1 block text-sm leading-relaxed font-medium break-words hover:underline"
        >
          {rss.title || rss.link}
        </a>
      ) : (
        // A feed that carries the whole post and nothing to point at.
        <p className="mt-1 text-sm leading-relaxed font-medium break-words">{rss.title || '(untitled)'}</p>
      )}

      {rss.summary ? (
        <div className="mt-1.5">
          <p className="text-sm leading-relaxed break-words text-foreground/90">{rss.summary}</p>
          <span className="mt-1 inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            AI 摘要
          </span>
        </div>
      ) : (
        rss.content_excerpt && <RssBody entry={rss} />
      )}

      {rss.author && <div className="mt-1 truncate text-xs text-muted-foreground">{rss.author}</div>}
    </article>
  );
}

export const RssCard = memo(RssCardImpl);
