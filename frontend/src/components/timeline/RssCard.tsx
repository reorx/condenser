// One feed entry: the feed as the header subject, the title as the main act, and a
// body that is the LLM summary when there is one and the article's plain-text
// excerpt when there is not (plan §0.4). Which of the two you are reading is marked,
// because a summary is a machine's paraphrase and a card that hides that is lying
// quietly.
//
// The full article does NOT expand in place (2026-08-24): 「查看全文」 opens the
// item detail pane, which fetches and renders it — the iOS arrangement (detail =
// the sheet, card = the scan surface), and the pane is also where highlighting
// lives, so there is exactly one rendering of the article to annotate.
import { memo, useCallback, useMemo } from 'react';
import { Bookmark } from 'lucide-react';

import { RssGlyph } from '@/components/RssGlyph';
import { useSaveToggle } from '@/hooks/useSaveToggle';
import { fullDateLabel, timeLabel } from '@/lib/format';
import { useItemDetailPane } from '@/lib/itemDetailPane';
import { rssFeedLabel } from '@/lib/sources';
import { useUnreadIndicator } from '@/lib/unreadIndicator';
import { cn } from '@/lib/utils';
import type { ReadTarget, TimelineItem } from '@/lib/types';

import { AnnotationBadge } from './AnnotationBadge';
import { ForwardedBadge } from './ForwardedBadge';
import { VibeReaderBadge } from './VibeReaderBadge';

interface Props {
  /** Envelope with `rss` present. */
  item: TimelineItem;
  /** Attach for scroll-past-to-read; omit in the saved/search views. */
  observe?: (el: Element | null, target: ReadTarget) => (() => void) | void;
  /** Keys judged read but awaiting server confirmation (green "syncing" state). */
  pendingKeys?: Set<string>;
}

function RssCardImpl({ item, observe, pendingKeys }: Props) {
  const rss = item.rss!;
  const save = useSaveToggle();
  const vrUrls = useMemo(() => (rss.link ? [rss.link] : []), [rss.link]);
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
  // 「查看全文」 is offered on the server's word (`content_truncated`) when the card
  // shows the excerpt; a summary hides the excerpt entirely, so with one the entry
  // to the source text is always offered.
  const hasMore = rss.summary ? true : rss.content_truncated;

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
        <AnnotationBadge item={item} />
        <VibeReaderBadge urls={vrUrls} />
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
        rss.content_excerpt && (
          <p className="mt-1 line-clamp-5 text-sm leading-relaxed break-words text-foreground/90">
            {rss.content_excerpt}
          </p>
        )
      )}

      {hasMore && (
        <div className="mt-1">
          <button
            type="button"
            onClick={() => openPane(item)}
            className="text-xs font-medium text-sky-600 hover:underline dark:text-sky-400"
          >
            查看全文
          </button>
        </div>
      )}

      {rss.author && <div className="mt-1 truncate text-xs text-muted-foreground">{rss.author}</div>}
    </article>
  );
}

export const RssCard = memo(RssCardImpl);
