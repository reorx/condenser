import type { LucideIcon } from 'lucide-react';

import { cn } from '@/lib/utils';

interface SegmentedOptionProps {
  icon: LucideIcon;
  label: string;
  active: boolean;
  onClick: () => void;
}

/** A single button in a segmented control (icon over label); `active` highlights it. */
export function SegmentedOption({ icon: Icon, label, active, onClick }: SegmentedOptionProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'flex flex-col items-center gap-1.5 rounded-md border py-2.5 text-xs transition-colors',
        active ? 'border-primary bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50',
      )}
    >
      <Icon className="size-4" />
      {label}
    </button>
  );
}
