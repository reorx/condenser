import { useState } from 'react';
import { FileText } from 'lucide-react';

import { mediaUrl } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { MediaItem } from '@/lib/types';

// Telegram represents video/gif/audio/files all as "document"; "webpage" is a link
// preview, not real media, so we never render it. Everything else with media gets a
// thumbnail attempt that falls back to a file chip if no preview image exists.
function isRenderable(item: MediaItem): boolean {
  return item.has_media && item.media_type !== 'webpage' && item.media_type != null;
}

function Thumb({ channelId, item, className }: { channelId: number; item: MediaItem; className?: string }) {
  const [failed, setFailed] = useState(false);
  const full = mediaUrl(channelId, item.message_id);

  if (failed) {
    return (
      <a
        href={full}
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          'flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground hover:bg-muted',
          className,
        )}
      >
        <FileText className="size-4 shrink-0" />
        <span className="truncate">{item.media_type ?? 'file'}</span>
      </a>
    );
  }

  return (
    <a href={full} target="_blank" rel="noopener noreferrer" className={cn('block overflow-hidden', className)}>
      <img
        src={mediaUrl(channelId, item.message_id, true)}
        alt=""
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className="h-full w-full bg-muted object-cover"
      />
    </a>
  );
}

export function MessageMedia({ channelId, items }: { channelId: number; items: MediaItem[] }) {
  const media = items.filter(isRenderable);
  if (media.length === 0) return null;

  if (media.length === 1) {
    return (
      <div className="mt-2 overflow-hidden rounded-lg border">
        <Thumb channelId={channelId} item={media[0]} className="max-h-[28rem] w-auto" />
      </div>
    );
  }

  return (
    <div
      className={cn(
        'mt-2 grid gap-1 overflow-hidden rounded-lg border',
        media.length === 2 ? 'grid-cols-2' : 'grid-cols-3',
      )}
    >
      {media.map((item) => (
        <Thumb key={item.message_id} channelId={channelId} item={item} className="aspect-square" />
      ))}
    </div>
  );
}
