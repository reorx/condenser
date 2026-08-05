// A single tweet card: author identity as the subject (For You mixes ~46 different
// authors per 50 tweets, so *who* is the primary orientation cue), the text, media,
// an embedded quote, and the engagement line. The time opens the item-detail pane,
// matching MessageCard / HnCard.
import { memo, useCallback } from 'react';
import { Bookmark, Heart, MessageCircle, Repeat2 } from 'lucide-react';

import { XAvatar } from '@/components/XAvatar';
import { useSaveToggle } from '@/hooks/useSaveToggle';
import { compactNumber, fullDateLabel, timeLabel } from '@/lib/format';
import { useItemDetailPane } from '@/lib/itemDetailPane';
import { linkify } from '@/lib/linkify';
import { xProfileUrl } from '@/lib/sources';
import { useUnreadIndicator } from '@/lib/unreadIndicator';
import { cn } from '@/lib/utils';
import type { ReadTarget, TimelineItem, XTweet } from '@/lib/types';

import { XFeedbackButtons } from './XFeedbackButtons';
import { XMedia } from './XMedia';
import { XQuoteCard } from './XQuoteCard';
import { XVerdictBadge } from './XVerdictBadge';

interface Props {
  /** Envelope with `x` present. */
  item: TimelineItem;
  /** Attach for scroll-past-to-read; omit in the saved view. Returns a ref cleanup. */
  observe?: (el: Element | null, target: ReadTarget) => (() => void) | void;
  /** Keys judged read but awaiting server confirmation (green "syncing" state). */
  pendingKeys?: Set<string>;
}

/** The text to print as the tweet body, or null when there is nothing left to print.
 *  Two upstream quirks are absorbed here: retweets arrive only as an 'RT @orig: …'
 *  prefix (bird flattens them — the prefix becomes the caption instead), and a
 *  long-form post's `text` *is* its article title, which the article card already
 *  shows. */
function bodyText(tweet: XTweet): string | null {
  if (!tweet.text) return null;
  const text = tweet.rt_of_handle ? tweet.text.replace(/^RT @[A-Za-z0-9_]{1,15}:\s*/, '') : tweet.text;
  if (tweet.article?.title && tweet.article.title.trim() === text.trim()) return null;
  return text || null;
}

function MetricChip({ icon, value }: { icon: React.ReactNode; value: number }) {
  return (
    <span className="inline-flex items-center gap-1">
      {icon}
      {compactNumber(value)}
    </span>
  );
}

function XCardImpl({ item, observe, pendingKeys }: Props) {
  const tweet = item.x!;
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

  const isActive = open?.key === item.key;
  // Three read states: pending (judged read, sync unconfirmed) > unread > read.
  const isPending = pendingKeys?.has(item.key) ?? false;
  const name = tweet.author_name || (tweet.author_handle ? `@${tweet.author_handle}` : 'Unknown');
  const shownAt = tweet.created_at ?? item.datetime;
  // For You sorts by the sighting, not the tweet time — say so in the tooltip so a
  // days-old tweet sitting at the top of the feed isn't confusing.
  const timeTitle =
    tweet.feed_kind === 'home'
      ? `${fullDateLabel(shownAt)} · seen ${fullDateLabel(tweet.first_seen_at)}`
      : fullDateLabel(shownAt);
  const body = bodyText(tweet);
  const metrics = tweet.metrics;

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
          <XAvatar handle={tweet.author_handle} name={tweet.author_name} className="size-5 text-[10px]" />
          <span className="truncate font-medium text-foreground/80">{name}</span>
          {tweet.author_handle && tweet.author_name && (
            <a
              href={xProfileUrl(tweet.author_handle)}
              target="_blank"
              rel="noreferrer"
              className="hidden truncate hover:underline sm:inline"
            >
              @{tweet.author_handle}
            </a>
          )}
        </div>
        <span aria-hidden>·</span>
        <button
          type="button"
          onClick={() => openPane(item)}
          title={timeTitle}
          aria-label="Open tweet details"
          className="shrink-0 cursor-pointer rounded underline-offset-2 transition-colors hover:text-foreground hover:underline"
        >
          <time>{timeLabel(shownAt)}</time>
        </button>
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

      {tweet.rt_of_handle && (
        <div className="mt-1 inline-flex items-center gap-1 text-xs text-muted-foreground/80">
          <Repeat2 className="size-3" />
          Retweeted{' '}
          <a href={xProfileUrl(tweet.rt_of_handle)} target="_blank" rel="noreferrer" className="hover:underline">
            @{tweet.rt_of_handle}
          </a>
        </div>
      )}

      {body && <div className="mt-1 text-sm leading-relaxed break-words whitespace-pre-wrap">{linkify(body)}</div>}

      {tweet.article?.title && (
        <div className="mt-2 rounded-lg border bg-muted/30 p-3">
          <div className="text-sm font-medium">{tweet.article.title}</div>
          {tweet.article.previewText && (
            <p className="mt-1 line-clamp-4 text-sm leading-relaxed text-muted-foreground">
              {tweet.article.previewText}
            </p>
          )}
        </div>
      )}

      {tweet.media && tweet.media.length > 0 && <XMedia items={tweet.media} />}
      {tweet.quote && <XQuoteCard quote={tweet.quote} />}

      {/* Footer: the machine's read on the left, the reader's on the right, the
          tweet's own numbers in between. Feedback is always offered, even when
          bird sent no metrics. */}
      <div className="mt-2 flex items-center gap-4 text-xs text-muted-foreground">
        <XVerdictBadge verdict={tweet.verdict} meta={tweet.verdict_meta} onOpen={() => openPane(item)} />
        {metrics && (
          <>
            <MetricChip icon={<Heart className="size-3.5" />} value={metrics.like_count} />
            <MetricChip icon={<Repeat2 className="size-3.5" />} value={metrics.retweet_count} />
            <MetricChip icon={<MessageCircle className="size-3.5" />} value={metrics.reply_count} />
          </>
        )}
        <XFeedbackButtons itemKey={item.key} feedback={item.feedback} className="ml-auto" />
      </div>
    </article>
  );
}

export const XCard = memo(XCardImpl);
