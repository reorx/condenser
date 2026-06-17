import { useState } from 'react';

import { mediaUrl } from '@/lib/api';
import type { WebPagePreview as WebPagePreviewData } from '@/lib/types';

/** Hostname for the accent line when the preview has no site_name. */
function hostOf(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url.startsWith('http') ? url : `https://${url}`).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

/**
 * Telegram-style link preview card. The preview image (when `has_photo`) is streamed
 * by the existing media proxy for this message id — Telethon resolves the webpage photo.
 */
export function WebPagePreview({
  channelId,
  messageId,
  webpage,
}: {
  channelId: number;
  messageId: number;
  webpage: WebPagePreviewData;
}) {
  const [imgFailed, setImgFailed] = useState(false);
  if (!webpage.url) return null;

  const source = webpage.site_name || webpage.author || hostOf(webpage.display_url || webpage.url);
  const showImage = webpage.has_photo && !imgFailed;
  const hasText = webpage.title || webpage.description;

  return (
    <a
      href={webpage.url}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="mt-2 flex gap-3 overflow-hidden rounded-lg border border-l-[3px] border-l-sky-500 bg-muted/30 p-3 transition-colors hover:bg-muted/60"
    >
      {showImage && (
        <img
          src={mediaUrl(channelId, messageId, true)}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setImgFailed(true)}
          className="size-16 shrink-0 rounded-md bg-muted object-cover sm:size-20"
        />
      )}
      <div className="min-w-0 flex-1">
        {source && <div className="truncate text-xs font-medium text-sky-600 dark:text-sky-400">{source}</div>}
        {webpage.title && (
          <div className="mt-0.5 line-clamp-2 text-sm font-medium break-words text-foreground">{webpage.title}</div>
        )}
        {webpage.description && (
          <div className="mt-0.5 line-clamp-3 text-xs leading-snug break-words text-muted-foreground">
            {webpage.description}
          </div>
        )}
        {!hasText && (
          <div className="mt-0.5 truncate text-xs text-muted-foreground">{webpage.display_url || webpage.url}</div>
        )}
      </div>
    </a>
  );
}
