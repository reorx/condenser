import { useState } from 'react';
import { FileText } from 'lucide-react';

import { mediaUrl } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { MediaItem } from '@/lib/types';

import { Lightbox } from './Lightbox';

// Telegram represents video/gif/audio/files all as "document"; "webpage" is a link
// preview, not real media, so we never render it. Everything else with media gets a
// thumbnail attempt that falls back to a file chip if no preview image exists.
function isRenderable(item: MediaItem): boolean {
  return item.has_media && item.media_type !== 'webpage' && item.media_type != null;
}

function Thumb({
  channelId,
  item,
  className,
  onOpen,
}: {
  channelId: number;
  item: MediaItem;
  className?: string;
  onOpen: () => void;
}) {
  const [failed, setFailed] = useState(false);

  // No preview image (audio/doc) -> a chip linking to the proxied file, not the lightbox.
  if (failed) {
    return (
      <a
        href={mediaUrl(channelId, item.message_id)}
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
    <button type="button" onClick={onOpen} className={cn('block cursor-zoom-in overflow-hidden', className)}>
      <img
        src={mediaUrl(channelId, item.message_id, true)}
        alt=""
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
        className="h-full w-full bg-muted object-cover"
      />
    </button>
  );
}

export function MessageMedia({ channelId, items }: { channelId: number; items: MediaItem[] }) {
  const media = items.filter(isRenderable);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  if (media.length === 0) return null;

  const grid =
    media.length === 1 ? (
      <div className="mt-2 overflow-hidden rounded-lg border">
        <Thumb
          channelId={channelId}
          item={media[0]}
          className="max-h-[28rem] w-auto"
          onOpen={() => setLightboxIndex(0)}
        />
      </div>
    ) : (
      <div
        className={cn(
          'mt-2 grid gap-1 overflow-hidden rounded-lg border',
          media.length === 2 ? 'grid-cols-2' : 'grid-cols-3',
        )}
      >
        {media.map((item, i) => (
          <Thumb
            key={item.message_id}
            channelId={channelId}
            item={item}
            className="aspect-square"
            onOpen={() => setLightboxIndex(i)}
          />
        ))}
      </div>
    );

  return (
    <>
      {grid}
      {lightboxIndex !== null && (
        <Lightbox
          channelId={channelId}
          items={media}
          index={lightboxIndex}
          onIndexChange={setLightboxIndex}
          onClose={() => setLightboxIndex(null)}
        />
      )}
    </>
  );
}
