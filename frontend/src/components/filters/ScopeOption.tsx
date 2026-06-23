import { cn } from '@/lib/utils';

interface ScopeOptionProps {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  hint: string;
}

/** A selectable scope card (Global / Single channel) in the create-filter dialog. */
export function ScopeOption({ active, onClick, icon, title, hint }: ScopeOptionProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex flex-col items-start gap-1 rounded-md border p-3 text-left transition-colors',
        active ? 'border-primary bg-accent/40' : 'border-input hover:bg-accent/30',
      )}
    >
      <div className="flex items-center gap-1.5 text-sm font-medium">
        {icon}
        {title}
      </div>
      <span className="text-xs text-muted-foreground">{hint}</span>
    </button>
  );
}
