import { useState } from 'react';

import { cn } from '@/lib/utils';
import type { XMediaItem } from '@/lib/types';

import { XLightbox } from './XLightbox';
import { XMediaThumb } from './XMediaThumb';

const SINGLE_FALLBACK_ASPECT = '4 / 3';
const GRID_ASPECT = '1 / 1';

/** A tweet's media: one image at its natural aspect, or a 2/3-column grid of squares. */
export function XMedia({ items, className }: { items: XMediaItem[]; className?: string }) {
  const media = items.filter((m) => m.previewUrl || m.url);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  if (media.length === 0) return null;

  const singleAspect =
    media.length === 1 && media[0].width && media[0].height
      ? `${media[0].width} / ${media[0].height}`
      : SINGLE_FALLBACK_ASPECT;

  return (
    <>
      {media.length === 1 ? (
        <div className={cn('mt-2 overflow-hidden rounded-lg border', className)}>
          <XMediaThumb
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
            className,
          )}
        >
          {media.map((item, i) => (
            <XMediaThumb
              key={item.url ?? item.previewUrl ?? i}
              item={item}
              initialAspect={GRID_ASPECT}
              lockAspect
              onOpen={() => setLightboxIndex(i)}
            />
          ))}
        </div>
      )}
      {lightboxIndex !== null && (
        <XLightbox
          items={media}
          index={lightboxIndex}
          onIndexChange={setLightboxIndex}
          onClose={() => setLightboxIndex(null)}
        />
      )}
    </>
  );
}
