import { useState } from 'react';
import { FileText } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { mediaUrl } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { MediaItem } from '@/lib/types';

interface MediaThumbProps {
  channelId: number;
  item: MediaItem;
  className?: string;
  initialAspect: string;
  /** When true, container aspect always stays at initialAspect (grid cells). */
  lockAspect?: boolean;
  onOpen: () => void;
}

/**
 * A single media thumbnail. Reserves space with the given aspect ratio and shows a
 * skeleton until the image loads, then fades it in. No preview image (audio/doc) falls
 * back to a file chip linking to the proxied file instead of opening the lightbox.
 */
export function MediaThumb({ channelId, item, className, initialAspect, lockAspect, onOpen }: MediaThumbProps) {
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
