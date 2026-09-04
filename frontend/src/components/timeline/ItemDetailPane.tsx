import { useState } from 'react';
import { Bookmark, ExternalLink, EyeOff, Forward, Info, MessageSquare } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { useAppMeta } from '@/hooks/useAppMeta';
import { useHideItem, useUnhideItem } from '@/hooks/useHideItem';
import { useItemAnnotations } from '@/hooks/useItemAnnotations';
import { useLinkPreviews, useUrlPreview } from '@/hooks/useLinkPreviews';
import { useSaveToggle } from '@/hooks/useSaveToggle';
import { useSubscriptions } from '@/hooks/useSubscriptions';
import { errorMessage } from '@/lib/api';
import { tgMessageUrl } from '@/lib/format';
import { useItemDetailPane } from '@/lib/itemDetailPane';
import { hnCommentsUrl, xPreviewUrls, xTweetUrl } from '@/lib/sources';
import { hnLinkAttrs } from '@/lib/vibeReader';
import type { TimelineItem } from '@/lib/types';
import { cn } from '@/lib/utils';

import { ForwardDialog } from './ForwardDialog';
import { ItemDetailBody } from './ItemDetailBody';
import { ItemDetailInfo } from './ItemDetailInfo';
import { ItemNoteDialog } from './ItemNoteDialog';
import { LinkPreviewCard } from './LinkPreviewCard';
import { MessageStatsRow } from './MessageStatsRow';

function CardSkeleton() {
  return (
    <div className="flex gap-3 rounded-lg border p-3">
      <Skeleton className="size-16 shrink-0 rounded-md sm:size-20" />
      <div className="flex-1 space-y-2 py-1">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-3 w-full" />
      </div>
    </div>
  );
}

/**
 * Right-side item detail pane: full info block on top, the item's actions right under
 * it (save + note + forward, every source; live TG stats share the row), then the
 * scrollable middle — the annotatable body (`ItemDetailBody`; RSS fetches its full
 * article here) followed by link previews — and original link + hide at the bottom.
 * Mounted once (in AppShell) and driven by the ItemDetailPane context, so it works
 * across views.
 */
export function ItemDetailPane() {
  const { open, close } = useItemDetailPane();
  const msg = open?.telegram ?? null;
  const story = open?.hn ?? null;
  const tweet = open?.x ?? null;
  const entry = open?.rss ?? null;
  const msgRef = msg ? { channel_id: msg.channel_id, message_id: msg.id } : null;

  const messageQuery = useLinkPreviews(msgRef);
  // Single-URL sources: the story's own link (unless ingest already prefetched a
  // preview) or the tweet's first outbound link. Null = nothing to fetch.
  const singleUrl = story
    ? story.preview
      ? null
      : story.url
    : tweet
      ? (xPreviewUrls(tweet)[0] ?? null)
      : entry
        ? entry.link
        : null;
  const urlQuery = useUrlPreview(singleUrl);
  const query = msg ? messageQuery : urlQuery;
  const previews = msg
    ? (messageQuery.data ?? [])
    : story?.preview
      ? [story.preview]
      : urlQuery.data
        ? [urlQuery.data]
        : [];
  // Nothing to fetch (self-post, prefetched story, link-less tweet) — no endless skeleton.
  const pending = msg ? messageQuery.isPending : !!singleUrl && urlQuery.isPending;

  const subs = useSubscriptions();
  const sub = msgRef ? subs.data?.find((s) => s.channel_id === msgRef.channel_id) : null;

  const meta = useAppMeta();
  const [forwardOpen, setForwardOpen] = useState(false);
  // Prefill for ForwardDialog when opened through the note dialog's 保存并转发
  // chain; a plain 转发 click clears it first.
  const [forwardComment, setForwardComment] = useState<string | undefined>(undefined);
  const [noteOpen, setNoteOpen] = useState(false);

  const hide = useHideItem();
  const unhide = useUnhideItem();

  // The pane's annotation model (highlights); local-state mirror + cache patches.
  const annotations = useItemAnnotations(open);

  // The item's note, with the savedOverride arrangement below: the envelope is a
  // click-time snapshot, so a save from this pane mirrors itself here, keyed on
  // the envelope object so a reopen with a fresh cache object drops the override.
  const [noteOverride, setNoteOverride] = useState<{ item: TimelineItem; note: string } | null>(null);
  const currentNote = noteOverride?.item === open ? noteOverride.note : (open?.note ?? '');

  // The context holds the envelope captured at click time, so `is_saved` is a snapshot.
  // While the pane is open the only writer is the button below, so mirroring its own
  // mutation here is exactly right — but the pane is mounted for the app's lifetime, so
  // the override has to expire with the session. It is tied to the envelope **object**,
  // not its key: an out-of-band unsave (every card has its own bookmark) replaces the
  // cached item, so reopening hands over a different object and the override is dropped
  // on identity. Same object = nothing changed = the override is still the truth.
  const save = useSaveToggle();
  const [savedOverride, setSavedOverride] = useState<{ item: TimelineItem; saved: boolean } | null>(null);
  const isSaved = savedOverride?.item === open ? savedOverride.saved : (open?.is_saved ?? false);

  const toggleSaved = () => {
    if (!open) return;
    const item = open;
    const next = !isSaved;
    setSavedOverride({ item, saved: next });
    save.mutate(
      { key: item.key, saved: next },
      {
        onError: (e) => {
          setSavedOverride({ item, saved: !next });
          toast.error(errorMessage(e, next ? '收藏失败' : '取消收藏失败'));
        },
      },
    );
  };

  const hideOpenItem = () => {
    if (!open) return;
    const key = open.key;
    hide.mutate(key, {
      onError: (e) => toast.error(errorMessage(e, '隐藏失败')),
    });
    close();
    setForwardOpen(false);
    toast('已隐藏', {
      description: '该条目不会再出现在时间线中。',
      action: { label: '撤销', onClick: () => unhide.mutate(key) },
    });
  };

  return (
    <Sheet
      open={!!open}
      onOpenChange={(next) => {
        if (!next) {
          close();
          setForwardOpen(false);
          setForwardComment(undefined);
          setNoteOpen(false);
        }
      }}
    >
      {/* Wider than the sheet default (28rem): since the RSS article moved in
          here, the pane is a reading surface, not just an info block. */}
      <SheetContent side="right" className="gap-0 p-0 sm:max-w-xl">
        <SheetHeader className="border-b">
          <SheetTitle className="flex items-center gap-2">
            <Info className="size-4" /> 条目详情
          </SheetTitle>
          <SheetDescription>
            {story
              ? '该 Hacker News 条目的完整信息。'
              : tweet
                ? '该推文的完整信息。'
                : entry
                  ? '该文章的完整信息。'
                  : '该消息的完整信息。'}
          </SheetDescription>
        </SheetHeader>

        {open && (
          <div className="border-b px-4 py-3">
            <ItemDetailInfo item={open} sub={sub} />
          </div>
        )}

        {open && (
          <div className="flex items-center gap-2 border-b px-4 py-3">
            {/* Live engagement numbers exist for Telegram only; the actions are source-generic. */}
            <div className="min-w-0 flex-1">{msgRef && <MessageStatsRow msgRef={msgRef} />}</div>
            <Button
              variant="outline"
              size="sm"
              className={cn('shrink-0', isSaved && 'text-amber-500 hover:text-amber-500')}
              onClick={toggleSaved}
            >
              <Bookmark className={cn('size-4', isSaved && 'fill-current')} />
              {isSaved ? '已收藏' : '收藏'}
            </Button>
            {/* iOS 的动作行顺序：收藏、评论、转发。有评论时按钮转靛蓝实心。 */}
            <Button
              variant="outline"
              size="sm"
              className={cn('shrink-0', currentNote && 'text-indigo-500 hover:text-indigo-500')}
              onClick={() => setNoteOpen(true)}
            >
              <MessageSquare className={cn('size-4', currentNote && 'fill-current')} />
              评论
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="shrink-0"
              onClick={() => {
                if (!meta.data?.forward_channel) {
                  toast.info('请先在设置中配置转发的目标频道。');
                  return;
                }
                setForwardComment(undefined);
                setForwardOpen(true);
              }}
            >
              <Forward className="size-4" />
              转发
            </Button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          {/* 正文区：可高亮的条目文本（RSS 在这里加载全文）。 */}
          {open && <ItemDetailBody item={open} annotations={annotations} />}

          <div className="space-y-3 p-4">
            <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">链接预览</p>
            {pending ? (
              <>
                <CardSkeleton />
                {/* A Telegram message can carry several links; the single-URL sources
                  never show two placeholders for one card that is coming. */}
                {!story && !entry && <CardSkeleton />}
              </>
            ) : query.isError ? (
              <div className="flex flex-col items-center gap-3 py-8 text-center text-sm text-muted-foreground">
                <p>{errorMessage(query.error, '链接预览加载失败。')}</p>
                <Button variant="outline" size="sm" onClick={() => query.refetch()}>
                  重试
                </Button>
              </div>
            ) : previews.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                {story
                  ? '自荐帖，无外部链接 — 讨论即内容。'
                  : tweet
                    ? '该推文没有外部链接。'
                    : entry
                      ? '该条目没有原文链接。'
                      : '消息中没有链接。'}
              </p>
            ) : (
              previews.map((p, i) => (
                <LinkPreviewCard key={`${p.url}-${i}`} channelId={msgRef?.channel_id} preview={p} />
              ))
            )}
          </div>
        </div>

        {open && (
          <div className="flex items-center justify-between gap-3 border-t p-4">
            <a
              href={
                story
                  ? hnCommentsUrl(story.id)
                  : tweet
                    ? xTweetUrl(tweet.id, tweet.author_handle)
                    : entry
                      ? (entry.link ?? entry.feed_url)
                      : tgMessageUrl(msgRef!.channel_id, msgRef!.message_id, sub?.username)
              }
              target="_blank"
              rel="noopener noreferrer"
              {...(story ? hnLinkAttrs(story) : {})}
              className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              <ExternalLink className="size-4" />
              {story
                ? 'Open comments on Hacker News'
                : tweet
                  ? 'Open original on X'
                  : entry
                    ? 'Open original article'
                    : 'Open original in Telegram'}
            </a>
            <Button
              variant="outline"
              size="sm"
              className="shrink-0 text-muted-foreground hover:text-destructive"
              title="从时间线中永久隐藏该条目（所有客户端生效）"
              onClick={hideOpenItem}
            >
              <EyeOff className="size-4" />
              隐藏
            </Button>
          </div>
        )}

        {open && (
          <ForwardDialog open={forwardOpen} onOpenChange={setForwardOpen} item={open} initialComment={forwardComment} />
        )}
        {open && (
          <ItemNoteDialog
            open={noteOpen}
            onOpenChange={setNoteOpen}
            item={open}
            note={currentNote}
            onSaved={(note) => setNoteOverride({ item: open, note })}
            onForward={(note) => {
              // 评论已落库；带着它进转发弹窗（在那边再改只影响发出的消息）。
              setNoteOpen(false);
              if (!meta.data?.forward_channel) {
                toast.info('评论已保存。转发需要先在设置中配置目标频道。');
                return;
              }
              setForwardComment(note);
              setForwardOpen(true);
            }}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}
