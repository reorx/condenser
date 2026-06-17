import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, X } from 'lucide-react';

import { mediaUrl } from '@/lib/api';
import type { MediaItem } from '@/lib/types';

interface LightboxProps {
  channelId: number;
  items: MediaItem[];
  index: number;
  onIndexChange: (i: number) => void;
  onClose: () => void;
}

/** Full image or video for one item; starts as <img> and falls back to <video>
 *  for documents that turn out to be playable (Telegram lumps video into "document"). */
function LightboxMedia({ channelId, item }: { channelId: number; item: MediaItem }) {
  const [asVideo, setAsVideo] = useState(item.media_type === 'video' || item.media_type === 'gif');
  const src = mediaUrl(channelId, item.message_id);

  if (asVideo) {
    return (
      <video
        src={src}
        controls
        autoPlay
        playsInline
        className="max-h-[90vh] max-w-[92vw] rounded-md"
        onClick={(e) => e.stopPropagation()}
      />
    );
  }
  return (
    <img
      src={src}
      alt=""
      onError={() => setAsVideo(true)}
      className="max-h-[90vh] max-w-[92vw] rounded-md object-contain"
      onClick={(e) => e.stopPropagation()}
    />
  );
}

export function Lightbox({ channelId, items, index, onIndexChange, onClose }: LightboxProps) {
  const count = items.length;
  const item = items[index];

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
      else if (e.key === 'ArrowLeft' && count > 1) onIndexChange((index - 1 + count) % count);
      else if (e.key === 'ArrowRight' && count > 1) onIndexChange((index + 1) % count);
    }
    window.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [index, count, onClose, onIndexChange]);

  if (!item) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/90"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <button
        type="button"
        onClick={onClose}
        className="absolute top-3 right-3 rounded-full p-2 text-white/80 hover:bg-white/10 hover:text-white"
        aria-label="Close"
      >
        <X className="size-5" />
      </button>

      {count > 1 && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onIndexChange((index - 1 + count) % count);
          }}
          className="absolute left-2 rounded-full p-2 text-white/80 hover:bg-white/10 hover:text-white sm:left-4"
          aria-label="Previous"
        >
          <ChevronLeft className="size-7" />
        </button>
      )}

      <LightboxMedia key={item.message_id} channelId={channelId} item={item} />

      {count > 1 && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onIndexChange((index + 1) % count);
          }}
          className="absolute right-2 rounded-full p-2 text-white/80 hover:bg-white/10 hover:text-white sm:right-4"
          aria-label="Next"
        >
          <ChevronRight className="size-7" />
        </button>
      )}

      {count > 1 && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white/90 tabular-nums">
          {index + 1} / {count}
        </div>
      )}
    </div>
  );
}
