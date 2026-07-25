import { useState } from 'react';

import { xAvatarUrl } from '@/lib/api';
import { cn } from '@/lib/utils';

// Same deterministic palette idea as ChannelAvatar, keyed on the handle so an
// author's letter fallback keeps one stable color everywhere.
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

function colorOf(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  return COLORS[Math.abs(h) % COLORS.length];
}

/**
 * An X author's avatar. bird's output carries no avatar URL, so the backend
 * proxies unavatar's X lookup; a miss is a 404 and we draw a colored initial —
 * the same degradation ChannelAvatar uses for unresolvable Telegram peers.
 */
export function XAvatar({
  handle,
  name,
  className,
}: {
  handle: string | null;
  name?: string | null;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const letter = ((name || handle || '#').replace(/^@/, '').trim()[0] ?? '#').toUpperCase();

  if (!handle || failed) {
    return (
      <div
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white',
          colorOf(handle ?? name ?? ''),
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
      src={xAvatarUrl(handle)}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className={cn('size-8 shrink-0 rounded-full bg-muted object-cover', className)}
    />
  );
}
