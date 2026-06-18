import { useState } from 'react';
import { FileText } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
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

const SINGLE_FALLBACK_ASPECT = '4 / 3';
const GRID_ASPECT = '1 / 1';

function Thumb({
  channelId,
  item,
  className,
  initialAspect,
  /** When true, container aspect always stays at initialAspect (grid cells). */
  lockAspect,
  onOpen,
}: {
  channelId: number;
  item: MediaItem;
  className?: string;
  initialAspect: string;
  lockAspect?: boolean;
  onOpen: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [aspect, setAspect] = useState<string>(initialAspect);

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
    <button
      type="button"
      onClick={onOpen}
      style={{ aspectRatio: aspect }}
      className={cn(
        // max-h caps portrait thumbs (object-cover then crops); full image lives in the Lightbox.
        'relative block w-full cursor-zoom-in overflow-hidden',
        'transition-[aspect-ratio] duration-300 ease-out',
        className,
      )}
    >
      {!loaded && <Skeleton className="absolute inset-0 rounded-none" />}
      <img
        src={mediaUrl(channelId, item.message_id, true)}
        alt=""
        loading="lazy"
        decoding="async"
        onLoad={(e) => {
          const img = e.currentTarget;
          // Override the placeholder aspect with the natural one ONLY when:
          //  - the caller didn't lock it (grid cells stay square), AND
          //  - we didn't already get exact dimensions from the API.
          // For new rows with API dimensions, the inline aspect already matches.
          if (!lockAspect && (!item.width || !item.height)) {
            if (img.naturalWidth > 0 && img.naturalHeight > 0) {
              setAspect(`${img.naturalWidth} / ${img.naturalHeight}`);
            }
          }
          setLoaded(true);
        }}
        onError={() => setFailed(true)}
        className={cn(
          'absolute inset-0 h-full w-full object-cover',
          'transition-opacity duration-300 ease-out',
          loaded ? 'opacity-100' : 'opacity-0',
        )}
      />
    </button>
  );
}

export function MessageMedia({ channelId, items }: { channelId: number; items: MediaItem[] }) {
  const media = items.filter(isRenderable);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  if (media.length === 0) return null;

  const singleAspect =
    media.length === 1 && media[0].width && media[0].height
      ? `${media[0].width} / ${media[0].height}`
      : SINGLE_FALLBACK_ASPECT;

  const grid =
    media.length === 1 ? (
      <div className="mt-2 overflow-hidden rounded-lg border">
        <Thumb
          channelId={channelId}
          item={media[0]}
          initialAspect={singleAspect}
          className="max-h-[28rem]"
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
            initialAspect={GRID_ASPECT}
            lockAspect
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
