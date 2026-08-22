import { Rss } from 'lucide-react';

import { cn } from '@/lib/utils';

/** The RSS broadcast mark in its amber square, HnGlyph/TgGlyph/XGlyph's size-pair.
 *  A lucide icon rather than a letter because RSS's mark *is* that glyph — it is the
 *  one source whose identity is a shape rather than a wordmark. Used by the timeline
 *  card, the sidebar feed rows, the /s/rss header and the Subscriptions tab bar. */
export function RssGlyph({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn('flex size-5 items-center justify-center rounded bg-amber-500 text-[10px] text-white', className)}
    >
      {/* Sized in em so the icon tracks whatever type scale the caller sets, the way
          HnGlyph's letter does — the two sit side by side in the sidebar and tab bar. */}
      <Rss className="size-[1.2em]" strokeWidth={2.5} />
    </span>
  );
}
