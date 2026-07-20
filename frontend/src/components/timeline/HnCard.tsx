// Minimal Hacker News card (Phase-2 mechanical adaptation): keeps the multi-source
// timeline rendering + scroll-to-read + save working for hn items. The full card
// (self-post text, day-rank badge, job styling, preview-pane entry) is Phase 3.
import { memo, useCallback } from 'react';
import { Bookmark } from 'lucide-react';

import { useSaveToggle } from '@/hooks/useSaveToggle';
import { timeLabel } from '@/lib/format';
import { useUnreadIndicator } from '@/lib/unreadIndicator';
import { cn } from '@/lib/utils';
import type { ReadTarget, TimelineItem } from '@/lib/types';

interface Props {
  /** Envelope with `hn` present. */
  item: TimelineItem;
  /** Attach for scroll-past-to-read; omit in the saved view. Returns a ref cleanup. */
  observe?: (el: Element | null, target: ReadTarget) => (() => void) | void;
}

function HnCardImpl({ item, observe }: Props) {
  const hn = item.hn!;
  const save = useSaveToggle();
  const { mode } = useUnreadIndicator();

  const attach = useCallback(
    (el: HTMLElement | null) => {
      if (observe && el && !item.is_read) return observe(el, { key: item.key, channelId: null });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [observe, item.is_read, item.key],
  );

  const commentsUrl = `https://news.ycombinator.com/item?id=${hn.id}`;

  return (
    <article
      ref={attach}
      data-read={item.is_read ? '' : undefined}
      className={cn(
        'group relative border-b px-4 py-3 transition-colors duration-500 sm:px-5',
        mode === 'divider' && !item.is_read ? 'border-sky-500 dark:border-sky-400' : 'border-border/50',
      )}
    >
      <header className="flex items-center gap-2 text-xs text-muted-foreground">
        <div className="relative flex items-center gap-2">
          {mode === 'dot' && (
            <span
              aria-hidden
              className={cn(
                'absolute top-1/2 right-full mr-1.5 size-2 -translate-y-1/2 rounded-full transition-colors duration-500',
                !item.is_read && 'bg-sky-500 dark:bg-sky-400',
              )}
            />
          )}
          <span className="flex size-5 items-center justify-center rounded bg-orange-500 text-[10px] font-bold text-white">
            Y
          </span>
          <span className="font-medium text-foreground/80">Hacker News</span>
        </div>
        <span aria-hidden>·</span>
        <time>{timeLabel(item.datetime)}</time>
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
        className="mt-1 block text-sm leading-relaxed font-medium break-words hover:underline"
      >
        {hn.title}
      </a>
      <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
        <span>{hn.score} points</span>
        <span aria-hidden>·</span>
        <a href={commentsUrl} target="_blank" rel="noreferrer" className="hover:underline">
          {hn.comments_count} comments
        </a>
        {hn.domain && (
          <>
            <span aria-hidden>·</span>
            <span className="truncate">{hn.domain}</span>
          </>
        )}
      </div>
    </article>
  );
}

export const HnCard = memo(HnCardImpl);
