import { Link2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { useLinkPreviews } from '@/hooks/useLinkPreviews';
import { errorMessage } from '@/lib/api';
import { useLinkPreviewPane } from '@/lib/linkPreviewPane';

import { LinkPreviewCard } from './LinkPreviewCard';

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
 * Right-side slide-out pane showing link previews for the open message. Mounted once
 * (in AppShell) and driven by the LinkPreviewPane context, so it works across views.
 */
export function LinkPreviewPane() {
  const { open, close } = useLinkPreviewPane();
  const query = useLinkPreviews(open);
  const previews = query.data ?? [];

  return (
    <Sheet
      open={!!open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      <SheetContent side="right" className="gap-0 p-0">
        <SheetHeader className="border-b">
          <SheetTitle className="flex items-center gap-2">
            <Link2 className="size-4" /> Link previews
          </SheetTitle>
          <SheetDescription>Previews for the links in this message.</SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {query.isPending ? (
            <>
              <CardSkeleton />
              <CardSkeleton />
            </>
          ) : query.isError ? (
            <div className="flex flex-col items-center gap-3 py-12 text-center text-sm text-muted-foreground">
              <p>{errorMessage(query.error, 'Failed to load previews.')}</p>
              <Button variant="outline" size="sm" onClick={() => query.refetch()}>
                Retry
              </Button>
            </div>
          ) : previews.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">No links found in this message.</p>
          ) : (
            previews.map((p, i) => (
              <LinkPreviewCard key={`${p.url}-${i}`} channelId={open!.channel_id} preview={p} />
            ))
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
