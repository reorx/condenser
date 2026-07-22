import { useState } from 'react';
import { ExternalLink, Forward, Link2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { useAppMeta } from '@/hooks/useAppMeta';
import { useLinkPreviews, useUrlPreview } from '@/hooks/useLinkPreviews';
import { useSubscriptions } from '@/hooks/useSubscriptions';
import { errorMessage } from '@/lib/api';
import { tgMessageUrl } from '@/lib/format';
import { hnCommentsUrl } from '@/lib/sources';
import { useLinkPreviewPane } from '@/lib/linkPreviewPane';

import { ForwardDialog } from './ForwardDialog';
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
 * Right-side slide-out pane showing link previews for the open item — a Telegram
 * message's links or an HN story's URL. Mounted once (in AppShell) and driven by
 * the LinkPreviewPane context, so it works across views.
 */
export function LinkPreviewPane() {
  const { open, close } = useLinkPreviewPane();
  const msgRef = open?.source === 'telegram' ? { channel_id: open.channel_id, message_id: open.message_id } : null;
  const story = open?.source === 'hn' ? open.story : null;

  const messageQuery = useLinkPreviews(msgRef);
  // The story's ingest-prefetched preview renders instantly; fetch live only without one.
  const urlQuery = useUrlPreview(story && !story.preview ? story.url : null);
  const query = story ? urlQuery : messageQuery;
  const previews = story
    ? story.preview
      ? [story.preview]
      : urlQuery.data
        ? [urlQuery.data]
        : []
    : (messageQuery.data ?? []);
  // Self-posts (no URL) and prefetched stories never fetch; don't show their skeleton forever.
  const pending = query.isPending && !(story && (!story.url || story.preview));

  const subs = useSubscriptions();
  const username = msgRef ? subs.data?.find((s) => s.channel_id === msgRef.channel_id)?.username : null;

  const meta = useAppMeta();
  const [forwardOpen, setForwardOpen] = useState(false);

  return (
    <Sheet
      open={!!open}
      onOpenChange={(next) => {
        if (!next) {
          close();
          setForwardOpen(false);
        }
      }}
    >
      <SheetContent side="right" className="gap-0 p-0">
        <SheetHeader className="border-b">
          <SheetTitle className="flex items-center gap-2">
            <Link2 className="size-4" /> Link previews
          </SheetTitle>
          <SheetDescription>
            {story ? 'Preview of the story link.' : 'Previews for the links in this message.'}
          </SheetDescription>
        </SheetHeader>

        {msgRef && (
          <div className="flex items-center gap-3 border-b px-4 py-3">
            <div className="min-w-0 flex-1">
              <MessageStatsRow msgRef={msgRef} />
            </div>
            <Button
              variant="outline"
              size="sm"
              className="shrink-0"
              onClick={() => {
                if (!meta.data?.forward_channel) {
                  toast.info('Set a forward target channel in Settings first.');
                  return;
                }
                setForwardOpen(true);
              }}
            >
              <Forward className="size-4" />
              Forward
            </Button>
          </div>
        )}

        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {pending ? (
            <>
              <CardSkeleton />
              {!story && <CardSkeleton />}
            </>
          ) : query.isError ? (
            <div className="flex flex-col items-center gap-3 py-12 text-center text-sm text-muted-foreground">
              <p>{errorMessage(query.error, 'Failed to load previews.')}</p>
              <Button variant="outline" size="sm" onClick={() => query.refetch()}>
                Retry
              </Button>
            </div>
          ) : previews.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              {story ? 'A self-post — the discussion is the content.' : 'No links found in this message.'}
            </p>
          ) : (
            previews.map((p, i) => <LinkPreviewCard key={`${p.url}-${i}`} channelId={msgRef?.channel_id} preview={p} />)
          )}
        </div>

        {open && (
          <div className="border-t p-4">
            <a
              href={story ? hnCommentsUrl(story.id) : tgMessageUrl(msgRef!.channel_id, msgRef!.message_id, username)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              <ExternalLink className="size-4" />
              {story ? 'Open comments on Hacker News' : 'Open original in Telegram'}
            </a>
          </div>
        )}

        {msgRef && <ForwardDialog open={forwardOpen} onOpenChange={setForwardOpen} msgRef={msgRef} />}
      </SheetContent>
    </Sheet>
  );
}
