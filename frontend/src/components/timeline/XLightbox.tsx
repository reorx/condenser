import { useEffect } from 'react';
import { ChevronLeft, ChevronRight, ExternalLink, X } from 'lucide-react';

import { previewImageUrl } from '@/lib/api';
import type { XMediaItem } from '@/lib/types';

interface XLightboxProps {
  items: XMediaItem[];
  index: number;
  onIndexChange: (i: number) => void;
  onClose: () => void;
}

/** Fullscreen viewer for a tweet's media. Sibling of the Telegram `Lightbox` rather
 *  than a generalization of it: X media are plain origin URLs (proxied for privacy),
 *  Telegram's are message-scoped proxy paths, and video here is a link out — X's
 *  video URLs are HLS/variant streams we don't play inline (v1). */
export function XLightbox({ items, index, onIndexChange, onClose }: XLightboxProps) {
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
  const src = item.url ?? item.previewUrl;

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

      {src && (
        <img
          key={src}
          src={previewImageUrl(src)}
          alt=""
          className="max-h-[90vh] max-w-[92vw] rounded-md object-contain"
          onClick={(e) => e.stopPropagation()}
        />
      )}

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

      {item.videoUrl && (
        <a
          href={item.videoUrl}
          target="_blank"
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="absolute bottom-14 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-white/10 px-3 py-1.5 text-xs text-white/90 hover:bg-white/20"
        >
          <ExternalLink className="size-3.5" />
          Open video
        </a>
      )}

      {count > 1 && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-black/60 px-2.5 py-1 text-xs text-white/90 tabular-nums">
          {index + 1} / {count}
        </div>
      )}
    </div>
  );
}
