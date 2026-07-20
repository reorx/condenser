import { cn } from '@/lib/utils';

/** The Hacker News "Y" mark in its orange square; size/typography via className.
 *  Shared by the HN timeline card, the sidebar feed row, and the /s/hn header. */
export function HnGlyph({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'flex size-5 items-center justify-center rounded bg-orange-500 text-[10px] font-bold text-white',
        className,
      )}
    >
      Y
    </span>
  );
}
