import { Send } from 'lucide-react';

import { cn } from '@/lib/utils';

/** The Telegram paper-plane mark in its blue square; sized to pair with HnGlyph.
 *  Used by the Subscriptions page's source tabs. */
export function TgGlyph({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn('flex size-5 items-center justify-center rounded bg-sky-500 text-white', className)}
    >
      <Send className="size-[60%] -translate-x-px translate-y-px" />
    </span>
  );
}
