import { cn } from '@/lib/utils';

/** The X mark in its black square, HnGlyph/TgGlyph's size-pair; used by the
 *  Subscriptions tab bar and the X subscription rows. */
export function XGlyph({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'flex size-5 items-center justify-center rounded bg-foreground text-background dark:bg-foreground',
        className,
      )}
    >
      <svg viewBox="0 0 24 24" fill="currentColor" className="size-[62%]">
        <path d="M18.9 1.6h3.5l-7.7 8.8L23.7 22h-7l-5.6-7.2L4.8 22H1.3l8.2-9.4L.7 1.6h7.2l5 6.6zm-1.2 18.3h1.9L6.9 3.6H4.8z" />
      </svg>
    </span>
  );
}
