import type { LucideIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface SearchFilterChipProps {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  title?: string;
  className?: string;
  onClick: () => void;
}

/** One small icon+label button in the search filter row. Unlike `SegmentedOption`
 *  (a settings-sized card) this is header-scale, so it sits beside the scope menu
 *  without the row growing a second line on a phone. */
export function SearchFilterChip({ icon: Icon, label, active, title, className, onClick }: SearchFilterChipProps) {
  return (
    <Button
      variant={active ? 'secondary' : 'ghost'}
      size="sm"
      aria-pressed={active}
      title={title ?? label}
      onClick={onClick}
      className={cn('h-8 gap-1.5 px-2 text-xs', !active && 'text-muted-foreground', className)}
    >
      <Icon className="size-3.5" />
      {label}
    </Button>
  );
}
