import { useState } from 'react';

import { cn } from '@/lib/utils';
import type { MediaItem } from '@/lib/types';

import { Lightbox } from './Lightbox';
import { MediaThumb } from './MediaThumb';

// Telegram represents video/gif/audio/files all as "document"; "webpage" is a link
// preview, not real media, so we never render it. Everything else with media gets a
// thumbnail attempt that falls back to a file chip if no preview image exists.
function isRenderable(item: MediaItem): boolean {
  return item.has_media && item.media_type !== 'webpage' && item.media_type != null;
}

const SINGLE_FALLBACK_ASPECT = '4 / 3';
const GRID_ASPECT = '1 / 1';

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
        <MediaThumb
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
          <MediaThumb
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
