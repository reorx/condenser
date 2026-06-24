import { useState } from 'react';
import { LinkIcon } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { mediaUrl, previewImageUrl } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { LinkPreview } from '@/lib/types';

/** Hostname for the accent line / fallback when the preview has no site_name. */
function hostOf(url: string): string {
  try {
    return new URL(url.startsWith('http') ? url : `https://${url}`).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

/**
 * One link preview in the pane. Image is served through the backend proxy (private,
 * hotlink-proof); when our fetch found no image but Telegram had one, fall back to the
 * media proxy for that Telegram message (`tg_image_message_id`).
 */
export function LinkPreviewCard({ channelId, preview }: { channelId: number; preview: LinkPreview }) {
  const [imgFailed, setImgFailed] = useState(false);
  const [imgLoaded, setImgLoaded] = useState(false);

  const imageSrc = preview.image
    ? previewImageUrl(preview.image)
    : preview.tg_image_message_id != null
      ? mediaUrl(channelId, preview.tg_image_message_id, true)
      : null;
  const showImage = !!imageSrc && !imgFailed;
  const host = hostOf(preview.url);
  const source = preview.site_name || host;
  const hasText = preview.title || preview.description;

  return (
    <a
      href={preview.url}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="flex gap-3 overflow-hidden rounded-lg border border-l-[3px] border-l-sky-500 bg-muted/30 p-3 transition-colors hover:bg-muted/60"
    >
      {showImage && (
        <div className="relative size-16 shrink-0 overflow-hidden rounded-md sm:size-20">
          {!imgLoaded && <Skeleton className="absolute inset-0 rounded-md" />}
          <img
            src={imageSrc}
            alt=""
            loading="lazy"
            decoding="async"
            onLoad={() => setImgLoaded(true)}
            onError={() => setImgFailed(true)}
            className={cn(
              'absolute inset-0 h-full w-full object-cover transition-opacity duration-300 ease-out',
              imgLoaded ? 'opacity-100' : 'opacity-0',
            )}
          />
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 truncate text-xs font-medium text-sky-600 dark:text-sky-400">
          <LinkIcon className="size-3 shrink-0" />
          <span className="truncate">{source}</span>
        </div>
        {preview.title && (
          <div className="mt-0.5 line-clamp-2 text-sm font-medium break-words text-foreground">{preview.title}</div>
        )}
        {preview.description && (
          <div className="mt-0.5 line-clamp-3 text-xs leading-snug break-words text-muted-foreground">
            {preview.description}
          </div>
        )}
        {!hasText && (
          <div className="mt-0.5 truncate text-xs text-muted-foreground">
            {preview.error ? "Couldn't load a preview for this link." : preview.url}
          </div>
        )}
      </div>
    </a>
  );
}
