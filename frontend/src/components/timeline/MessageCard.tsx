import { memo, useCallback } from 'react';
import { Bookmark, Forward, Pencil } from 'lucide-react';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { useSaveToggle } from '@/hooks/useSaveToggle';
import { timeLabel } from '@/lib/format';
import { linkify } from '@/lib/linkify';
import { useUnreadIndicator } from '@/lib/unreadIndicator';
import { cn } from '@/lib/utils';
import type { DisplayMessage, MsgRef } from '@/lib/types';

import { MessageMedia } from './MessageMedia';
import { WebPagePreview } from './WebPagePreview';

interface Props {
  msg: DisplayMessage;
  channelLabel: string;
  /** Attach for scroll-past-to-read; omit in the saved view. Returns a ref cleanup. */
  observe?: (el: Element | null, ref: MsgRef) => (() => void) | void;
}

function forwardSourceName(msg: DisplayMessage): string | null {
  if (!msg.is_forwarded) return null;
  const f = msg.forward_info;
  return f?.from_channel_name || f?.from_user_name || f?.post_author || null;
}

function MessageCardImpl({ msg, channelLabel, observe }: Props) {
  const save = useSaveToggle();
  const { mode } = useUnreadIndicator();
  const ref: MsgRef = { channel_id: msg.channel_id, message_id: msg.id };
  const fwdName = forwardSourceName(msg);

  const attach = useCallback(
    (el: HTMLElement | null) => {
      if (observe && el && !msg.is_read) return observe(el, ref);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [observe, msg.is_read, msg.channel_id, msg.id],
  );

  // Text + media + webpage; reused inside the forward box or rendered bare otherwise.
  const body = (
    <>
      {msg.text && (
        <div className="mt-1 text-sm leading-relaxed whitespace-pre-wrap break-words">{linkify(msg.text)}</div>
      )}
      <MessageMedia channelId={msg.channel_id} items={msg.media_items} />
      {msg.webpage && <WebPagePreview channelId={msg.channel_id} messageId={msg.id} webpage={msg.webpage} />}
    </>
  );

  return (
    <article
      ref={attach}
      data-read={msg.is_read ? '' : undefined}
      className={cn(
        'group relative border-b px-4 py-3 transition-colors duration-500 sm:px-5',
        mode === 'divider' && !msg.is_read ? 'border-sky-500 dark:border-sky-400' : 'border-border/50',
      )}
    >
      <header className="flex items-center gap-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          {/* Unread marker (dot mode): a sky dot before the avatar; fades to transparent
              once the message is read. Rendered only in dot mode so divider mode has no slot. */}
          {mode === 'dot' && (
            <span
              aria-hidden
              className={cn(
                'size-2 shrink-0 rounded-full transition-colors duration-500',
                !msg.is_read && 'bg-sky-500 dark:bg-sky-400',
              )}
            />
          )}
          <ChannelAvatar channelId={msg.channel_id} name={channelLabel} className="size-5 text-[10px]" />
          <span className="font-medium text-foreground/80">{channelLabel}</span>
        </div>
        <span aria-hidden>·</span>
        <time>{timeLabel(msg.date)}</time>
        {msg.is_edited && (
          <span className="inline-flex items-center gap-0.5" title="Edited">
            <Pencil className="size-3" />
          </span>
        )}
        <button
          type="button"
          onClick={() => save.mutate({ ref, saved: !msg.is_saved })}
          aria-label={msg.is_saved ? 'Remove from saved' : 'Save'}
          aria-pressed={msg.is_saved}
          className={cn(
            'ml-auto rounded p-1 transition-colors hover:bg-accent hover:text-accent-foreground',
            msg.is_saved ? 'text-amber-500' : 'text-muted-foreground',
          )}
        >
          <Bookmark className={cn('size-4', msg.is_saved && 'fill-current')} />
        </button>
      </header>

      {msg.is_forwarded ? (
        <>
          <div className="mt-1 inline-flex items-center gap-1 text-xs text-muted-foreground/80">
            <Forward className="size-3" />
            Forwarded
          </div>
          <div className="mt-1 ml-8 rounded-lg border bg-muted/30 p-3">
            {fwdName && <div className="text-xs font-medium text-foreground/80">{fwdName}</div>}
            {body}
          </div>
        </>
      ) : (
        body
      )}
    </article>
  );
}

export const MessageCard = memo(MessageCardImpl);
