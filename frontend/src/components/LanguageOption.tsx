import { Check } from 'lucide-react';

import { cn } from '@/lib/utils';

interface LanguageOptionProps {
  label: string;
  selected: boolean;
  onToggle: () => void;
}

/** One language checkbox-pill in the Settings 语言 multi-select. */
export function LanguageOption({ label, selected, onToggle }: LanguageOptionProps) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={selected}
      onClick={onToggle}
      className={cn(
        'flex items-center justify-center gap-1.5 rounded-md border py-2 text-xs transition-colors',
        selected ? 'border-primary bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/50',
      )}
    >
      <Check className={cn('size-3.5', selected ? '' : 'invisible')} />
      {label}
    </button>
  );
}
