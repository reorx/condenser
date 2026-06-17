import { memo, useCallback } from 'react';
import { Bookmark, Eye, Forward, Pencil } from 'lucide-react';

import { useSaveToggle } from '@/hooks/useSaveToggle';
import { compactNumber, timeLabel } from '@/lib/format';
import { linkify } from '@/lib/linkify';
import { cn } from '@/lib/utils';
import type { DisplayMessage, MsgRef } from '@/lib/types';

import { MessageMedia } from './MessageMedia';

interface Props {
  msg: DisplayMessage;
  channelLabel: string;
  /** Attach for scroll-past-to-read; omit in the saved view. Returns a ref cleanup. */
  observe?: (el: Element | null, ref: MsgRef) => (() => void) | void;
  /** Hide the per-row channel name (shown once in the header) in single-channel views. */
  showChannel?: boolean;
}

function forwardSource(msg: DisplayMessage): string | null {
  if (!msg.is_forwarded) return null;
  const f = msg.forward_info;
  const name = f?.from_channel_name || f?.from_user_name || f?.post_author;
  return name ? `Forwarded from ${name}` : 'Forwarded';
}

function MessageCardImpl({ msg, channelLabel, observe, showChannel = true }: Props) {
  const save = useSaveToggle();
  const ref: MsgRef = { channel_id: msg.channel_id, message_id: msg.id };
  const fwd = forwardSource(msg);

  const attach = useCallback(
    (el: HTMLElement | null) => {
      if (observe && el && !msg.is_read) return observe(el, ref);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [observe, msg.is_read, msg.channel_id, msg.id],
  );

  return (
    <article
      ref={attach}
      data-read={msg.is_read ? '' : undefined}
      className={cn(
        'group relative px-4 py-3 transition-opacity sm:px-5',
        msg.is_read && 'opacity-55 hover:opacity-100',
      )}
    >
      <header className="flex items-center gap-2 text-xs text-muted-foreground">
        {showChannel && (
          <>
            <span className="font-medium text-foreground/80">{channelLabel}</span>
            <span aria-hidden>·</span>
          </>
        )}
        <time>{timeLabel(msg.date)}</time>
        {msg.is_edited && (
          <span className="inline-flex items-center gap-0.5" title="Edited">
            <Pencil className="size-3" />
          </span>
        )}
        <div className="ml-auto flex items-center gap-3">
          {msg.views != null && (
            <span className="inline-flex items-center gap-1 tabular-nums">
              <Eye className="size-3.5" />
              {compactNumber(msg.views)}
            </span>
          )}
          <button
            type="button"
            onClick={() => save.mutate({ ref, saved: !msg.is_saved })}
            aria-label={msg.is_saved ? 'Remove from saved' : 'Save'}
            aria-pressed={msg.is_saved}
            className={cn(
              'rounded p-1 transition-colors hover:bg-accent hover:text-accent-foreground',
              msg.is_saved
                ? 'text-amber-500'
                : 'text-muted-foreground opacity-0 focus-visible:opacity-100 group-hover:opacity-100',
            )}
          >
            <Bookmark className={cn('size-4', msg.is_saved && 'fill-current')} />
          </button>
        </div>
      </header>

      {fwd && (
        <div className="mt-1 inline-flex items-center gap-1 text-xs text-muted-foreground/80">
          <Forward className="size-3" />
          {fwd}
        </div>
      )}

      {msg.text && (
        <div className="mt-1 text-sm leading-relaxed whitespace-pre-wrap break-words">{linkify(msg.text)}</div>
      )}

      <MessageMedia channelId={msg.channel_id} items={msg.media_items} />
    </article>
  );
}

export const MessageCard = memo(MessageCardImpl);
