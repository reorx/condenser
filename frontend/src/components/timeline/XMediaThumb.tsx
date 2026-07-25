import { useState } from 'react';
import { Play } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { previewImageUrl } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { XMediaItem } from '@/lib/types';

interface XMediaThumbProps {
  item: XMediaItem;
  className?: string;
  initialAspect: string;
  /** Grid cells keep their square aspect regardless of the natural one. */
  lockAspect?: boolean;
  onOpen: () => void;
}

/** One tweet media thumbnail: reserves space via aspect-ratio, skeleton until load,
 *  then fades in — the same treatment as Telegram's `MediaThumb`. Images go through
 *  the backend image proxy so reading a tweet never pings X from the reader's IP. */
export function XMediaThumb({ item, className, initialAspect, lockAspect, onOpen }: XMediaThumbProps) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [aspect, setAspect] = useState(initialAspect);
  const src = item.previewUrl ?? item.url;
  const isVideo = item.type !== 'photo';

  if (!src || failed) return null;

  return (
    <button
      type="button"
      onClick={onOpen}
      style={{ aspectRatio: aspect }}
      className={cn(
        'relative block w-full cursor-zoom-in overflow-hidden',
        'transition-[aspect-ratio] duration-300 ease-out',
        className,
      )}
    >
      {!loaded && <Skeleton className="absolute inset-0 rounded-none" />}
      <img
        src={previewImageUrl(src)}
        alt=""
        loading="lazy"
        decoding="async"
        onLoad={(e) => {
          const img = e.currentTarget;
          if (!lockAspect && (!item.width || !item.height) && img.naturalWidth > 0 && img.naturalHeight > 0) {
            setAspect(`${img.naturalWidth} / ${img.naturalHeight}`);
          }
          setLoaded(true);
        }}
        onError={() => setFailed(true)}
        className={cn(
          'absolute inset-0 h-full w-full object-cover transition-opacity duration-300 ease-out',
          loaded ? 'opacity-100' : 'opacity-0',
        )}
      />
      {isVideo && (
        <span className="absolute inset-0 flex items-center justify-center" aria-hidden>
          <span className="flex size-11 items-center justify-center rounded-full bg-black/55 text-white">
            <Play className="size-5 fill-current" />
          </span>
        </span>
      )}
    </button>
  );
}
