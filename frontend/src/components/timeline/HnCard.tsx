// A Hacker News story card: title as the main act (external link, or the comments
// page for self-posts), score/comments/domain/day-rank meta, sanitized self-post
// text behind a clamp toggle, muted job posts, and the shared details-pane entry
// on the submitted time.
import { memo, useCallback, useState } from 'react';
import { Bookmark } from 'lucide-react';

import { HnGlyph } from '@/components/HnGlyph';
import { useSaveToggle } from '@/hooks/useSaveToggle';
import { fullDateLabel, timeLabel } from '@/lib/format';
import { useItemDetailPane } from '@/lib/itemDetailPane';
import { sanitizeHtml } from '@/lib/sanitize';
import { hnCommentsUrl } from '@/lib/sources';
import { useUnreadIndicator } from '@/lib/unreadIndicator';
import { cn } from '@/lib/utils';
import type { ReadTarget, TimelineItem } from '@/lib/types';

import { LinkPreviewCard } from './LinkPreviewCard';

interface Props {
  /** Envelope with `hn` present. */
  item: TimelineItem;
  /** Attach for scroll-past-to-read; omit in the saved view. Returns a ref cleanup. */
  observe?: (el: Element | null, target: ReadTarget) => (() => void) | void;
  /** Keys judged read but awaiting server confirmation (green "syncing" state). */
  pendingKeys?: Set<string>;
}

/** Self-posts longer than this stay clamped behind a "more" toggle. */
const CLAMP_THRESHOLD = 400;

/** Sanitized self-post body with a deterministic clamp (no layout measuring). */
function HnSelfText({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const clampable = text.length > CLAMP_THRESHOLD;
  return (
    <div className="mt-1">
      <div
        className={cn(
          'text-sm leading-relaxed break-words text-foreground/90',
          '[&_a]:break-all [&_a]:underline [&_a]:underline-offset-2 [&_p]:mt-2 [&_p:first-child]:mt-0',
          '[&_pre]:mt-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-muted/50 [&_pre]:p-2 [&_pre]:text-xs',
          clampable && !expanded && 'line-clamp-5',
        )}
        // eslint-disable-next-line react/no-danger
        dangerouslySetInnerHTML={{ __html: sanitizeHtml(text) }}
      />
      {clampable && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 text-xs font-medium text-sky-600 hover:underline dark:text-sky-400"
        >
          {expanded ? 'less' : 'more'}
        </button>
      )}
    </div>
  );
}

function HnCardImpl({ item, observe, pendingKeys }: Props) {
  const hn = item.hn!;
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

  const commentsUrl = hnCommentsUrl(hn.id);
  const isJob = hn.type === 'job';
  const isActive = open?.key === item.key;
  // Three read states: pending (judged read, sync unconfirmed) > unread > read.
  const isPending = pendingKeys?.has(item.key) ?? false;
  const timeTitle = `${fullDateLabel(hn.submitted_at ?? item.datetime)} · on front page ${fullDateLabel(item.datetime)}`;

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
        <div className="relative flex items-center gap-2">
          {mode === 'dot' && (
            <span
              aria-hidden
              className={cn(
                'absolute top-1/2 right-full mr-1.5 size-2 -translate-y-1/2 rounded-full transition-colors duration-500',
                isPending ? 'bg-emerald-500 dark:bg-emerald-400' : !item.is_read && 'bg-sky-500 dark:bg-sky-400',
              )}
            />
          )}
          <HnGlyph />
          <span className="font-medium text-foreground/80">Hacker News</span>
        </div>
        <span aria-hidden>·</span>
        {/* Details-pane entry, matching MessageCard: the visible time is the story's
            submission time (the sort position is its front-page debut — see title). */}
        <button
          type="button"
          onClick={() => openPane(item)}
          title={timeTitle}
          aria-label="Open story details"
          className="cursor-pointer rounded underline-offset-2 transition-colors hover:text-foreground hover:underline"
        >
          <time>{timeLabel(hn.submitted_at ?? item.datetime)}</time>
        </button>
        {isJob && (
          <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase">Job</span>
        )}
        <button
          type="button"
          onClick={() => save.mutate({ key: item.key, saved: !item.is_saved })}
          aria-label={item.is_saved ? 'Remove from saved' : 'Save'}
          aria-pressed={item.is_saved}
          className={cn(
            'ml-auto rounded p-1 transition-colors hover:bg-accent hover:text-accent-foreground',
            item.is_saved ? 'text-amber-500' : 'text-muted-foreground',
          )}
        >
          <Bookmark className={cn('size-4', item.is_saved && 'fill-current')} />
        </button>
      </header>

      <a
        href={hn.url ?? commentsUrl}
        target="_blank"
        rel="noreferrer"
        className={cn(
          'mt-1 block text-sm leading-relaxed font-medium break-words hover:underline',
          isJob && 'text-muted-foreground',
        )}
      >
        {hn.title}
      </a>

      {!hn.url && hn.text && <HnSelfText text={hn.text} />}

      <div className={cn('mt-1 flex items-center gap-2 text-xs text-muted-foreground', isJob && 'opacity-70')}>
        {hn.day_rank != null && (
          <span title="Which of the day's slots it took" className="font-medium text-orange-600 dark:text-orange-400">
            #{hn.day_rank}
          </span>
        )}
        {!isJob && (
          <>
            <span>{hn.score} points</span>
            <span aria-hidden>·</span>
            <a href={commentsUrl} target="_blank" rel="noreferrer" className="hover:underline">
              {hn.comments_count} comments
            </a>
          </>
        )}
        {hn.domain && (
          <>
            {!isJob && <span aria-hidden>·</span>}
            <span className="truncate">{hn.domain}</span>
          </>
        )}
      </div>

      {hn.url && hn.preview && (hn.preview.title || hn.preview.description || hn.preview.image) && (
        <div className="mt-2">
          <LinkPreviewCard preview={hn.preview} />
        </div>
      )}
    </article>
  );
}

export const HnCard = memo(HnCardImpl);
