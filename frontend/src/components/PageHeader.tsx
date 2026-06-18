import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

interface PageHeaderProps {
  /** Leading glyph: a category icon wrapped in `IconBadge`, or a `ChannelAvatar`. */
  icon: ReactNode;
  title: string;
  /** Small line under the title, e.g. "626 unread". Omitted when there's nothing to show. */
  meta?: ReactNode;
  /** Right-aligned, icon-only action buttons. */
  actions?: ReactNode;
}

/**
 * Unified top bar for the reading views: leading icon + title (with optional
 * count line) on the left, icon-only actions pinned right. Matches the
 * sidebar's identity for the current route.
 */
export function PageHeader({ icon, title, meta, actions }: PageHeaderProps) {
  return (
    <div className="flex items-center gap-3 border-b px-4 py-3 sm:px-5">
      <div className="shrink-0">{icon}</div>
      <div className="min-w-0">
        <h1 className="truncate text-base leading-tight font-semibold tracking-tight">{title}</h1>
        {meta != null && meta !== '' && <div className="mt-0.5 text-xs text-muted-foreground">{meta}</div>}
      </div>
      {actions && <div className="ml-auto flex shrink-0 items-center gap-0.5">{actions}</div>}
    </div>
  );
}

/** A category glyph in a muted circle, matching ChannelAvatar's footprint. */
export function IconBadge({ icon: Icon, className }: { icon: ReactNode; className?: string }) {
  return (
    <span
      className={cn('flex size-9 items-center justify-center rounded-full bg-muted text-muted-foreground', className)}
    >
      {Icon}
    </span>
  );
}
