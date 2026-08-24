// The detail pane's body section: the item's own text, rendered annotatable —
// the web counterpart of iOS's four detail sheets growing highlights. What counts
// as "the body" per source mirrors iOS's choices exactly: TG = the message text,
// HN = the self-post text (an external-link story has none), X = the derived
// display text (`xBodyText` — the same derivation the card prints, so quotes made
// here relocate there and on iOS), RSS = the full article, fetched lazily. The AI
// summary and quoted tweets are other people's / a machine's words — deliberately
// not annotatable, matching iOS (the fallback is the item-level note).
import { Spinner } from '@/components/Spinner';
import { AnnotatedText } from '@/components/annotations/AnnotatedText';
import { useRssArticle } from '@/hooks/useRssArticle';
import type { useItemAnnotations } from '@/hooks/useItemAnnotations';
import { linkify } from '@/lib/linkify';
import { sanitizeHtml } from '@/lib/sanitize';
import { xBodyText } from '@/lib/xUrls';
import type { TimelineItem } from '@/lib/types';
import { cn } from '@/lib/utils';

type AnnotationsModel = ReturnType<typeof useItemAnnotations>;

interface Props {
  item: TimelineItem;
  annotations: AnnotationsModel;
}

/** Tailwind for sanitized article/self-post HTML (moved here from `RssCard` when
 *  the article moved into the pane). */
const ARTICLE_PROSE = cn(
  'text-sm leading-relaxed break-words text-foreground/90',
  '[&_a]:break-all [&_a]:underline [&_a]:underline-offset-2 [&_p]:mt-2 [&_p:first-child]:mt-0',
  '[&_pre]:mt-2 [&_pre]:overflow-x-auto [&_pre]:rounded [&_pre]:bg-muted/50 [&_pre]:p-2 [&_pre]:text-xs',
  // Feed bodies carry full-resolution images; capped rather than dropped — the
  // original is one click away. Height only, so the aspect ratio keeps itself.
  '[&_img]:mt-2 [&_img]:max-h-80 [&_img]:max-w-full [&_img]:rounded',
);

const PLAIN_PROSE = 'text-sm leading-relaxed break-words whitespace-pre-wrap text-foreground/90';

/** The RSS body: AI summary (when there is one) above the lazily fetched article.
 *  A saved snapshot already carries the article inline; otherwise it comes from
 *  `GET /api/rss/entries/{id}` on open. While it is not in hand the excerpt keeps
 *  the section honest — and highlighting stays off, because a quote made against
 *  the excerpt would need relocating against different text (iOS disables the
 *  fallback state the same way). */
function RssDetailBody({ item, annotations }: Props) {
  const entry = item.rss!;
  const hasInline = entry.content != null;
  const article = useRssArticle(hasInline ? null : entry.id);
  const html = entry.content ?? article.data?.rss?.content ?? null;
  const loading = !hasInline && article.isPending;

  return (
    <div>
      {entry.summary && (
        <div className="mb-3 rounded-md border-l-2 border-indigo-400/70 bg-indigo-500/5 px-3 py-2">
          <p className="text-sm leading-relaxed break-words text-foreground/90">{entry.summary}</p>
          <span className="mt-1 inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
            AI 摘要
          </span>
        </div>
      )}
      {html ? (
        <AnnotatedText
          annotations={annotations.annotations}
          onCreate={annotations.add}
          onSetComment={annotations.setComment}
          onDelete={annotations.remove}
        >
          <div
            className={ARTICLE_PROSE}
            // eslint-disable-next-line react/no-danger
            dangerouslySetInnerHTML={{ __html: sanitizeHtml(html) }}
          />
        </AnnotatedText>
      ) : (
        <>
          {entry.content_excerpt && <p className={PLAIN_PROSE}>{entry.content_excerpt}</p>}
          {loading ? (
            <div className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Spinner className="size-3" />
              正在加载全文…
            </div>
          ) : (
            // A failed fetch keeps the excerpt — still a true rendering of the
            // entry, just a short one.
            article.isError && <p className="mt-2 text-xs text-muted-foreground">正文加载失败</p>
          )}
        </>
      )}
    </div>
  );
}

/**
 * Source-dispatched body for the pane. Renders nothing when the item has no body
 * text *and* nothing was ever highlighted on it; with annotations but no body
 * (the text was derived away), the annotated layer still mounts so the orphan
 * list can say so instead of the highlights silently vanishing.
 */
export function ItemDetailBody({ item, annotations }: Props) {
  if (item.rss) {
    return (
      <div className="border-b px-4 py-3">
        <RssDetailBody item={item} annotations={annotations} />
      </div>
    );
  }

  const msg = item.telegram;
  const hn = item.hn;
  const tweet = item.x;
  const xText = tweet ? xBodyText(tweet) : null;
  const content = msg?.text ? (
    <div className={PLAIN_PROSE}>{linkify(msg.text)}</div>
  ) : hn?.text ? (
    <div
      className={ARTICLE_PROSE}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: sanitizeHtml(hn.text) }}
    />
  ) : tweet && xText ? (
    <div className={PLAIN_PROSE}>{linkify(xText, tweet.urls)}</div>
  ) : null;

  if (!content && annotations.annotations.length === 0) return null;
  return (
    <div className="border-b px-4 py-3">
      <AnnotatedText
        annotations={annotations.annotations}
        onCreate={annotations.add}
        onSetComment={annotations.setComment}
        onDelete={annotations.remove}
      >
        {content}
      </AnnotatedText>
    </div>
  );
}
