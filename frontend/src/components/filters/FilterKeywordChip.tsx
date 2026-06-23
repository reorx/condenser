import { Trash2 } from 'lucide-react';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import type { KeywordFilter } from '@/lib/types';

interface FilterKeywordChipProps {
  filter: KeywordFilter;
  /** True while this keyword's delete request is in flight (shows a spinner). */
  deleting: boolean;
  onDelete: (id: number) => void;
}

/** A single keyword filter rendered as a removable pill. */
export function FilterKeywordChip({ filter, deleting, onDelete }: FilterKeywordChipProps) {
  return (
    <li className="group flex items-center gap-1 rounded-full bg-muted/60 py-1 pr-1 pl-2.5 text-sm">
      <span className="max-w-[20rem] truncate">{filter.pattern}</span>
      <Button
        variant="ghost"
        size="icon"
        className="size-6 text-muted-foreground hover:text-destructive"
        disabled={deleting}
        onClick={() => onDelete(filter.id)}
        aria-label={`Remove keyword ${filter.pattern}`}
      >
        {deleting ? <Spinner className="size-3" /> : <Trash2 className="size-3.5" />}
      </Button>
    </li>
  );
}
