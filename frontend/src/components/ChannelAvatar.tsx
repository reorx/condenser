import { useState } from 'react';

import { channelAvatarUrl } from '@/lib/api';
import { cn } from '@/lib/utils';

// Deterministic palette so a channel's letter fallback keeps a stable color.
const COLORS = [
  'bg-rose-500',
  'bg-orange-500',
  'bg-amber-500',
  'bg-emerald-500',
  'bg-teal-500',
  'bg-sky-500',
  'bg-indigo-500',
  'bg-violet-500',
  'bg-fuchsia-500',
];

/**
 * Telegram channel avatar via the proxy, falling back to a colored initial.
 *
 * `letterOnly` renders just the initial without hitting the proxy — use it in long
 * lists (e.g. the channel browser) so we don't fire one avatar download per row.
 */
export function ChannelAvatar({
  channelId,
  name,
  className,
  letterOnly = false,
}: {
  channelId: number;
  name: string;
  className?: string;
  letterOnly?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const letter = (name.replace(/^@/, '').trim()[0] ?? '#').toUpperCase();
  const color = COLORS[Math.abs(channelId) % COLORS.length];

  if (failed || letterOnly) {
    return (
      <div
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white',
          color,
          className,
        )}
        aria-hidden
      >
        {letter}
      </div>
    );
  }

  return (
    <img
      src={channelAvatarUrl(channelId)}
      alt=""
      onError={() => setFailed(true)}
      className={cn('size-8 shrink-0 rounded-full bg-muted object-cover', className)}
    />
  );
}
