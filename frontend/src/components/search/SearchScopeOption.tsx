import type { ReactNode } from 'react';
import { Check } from 'lucide-react';

import { DropdownMenuItem } from '@/components/ui/dropdown-menu';
import { cn } from '@/lib/utils';

interface SearchScopeOptionProps {
  label: string;
  /** Source mark or subscription avatar — whatever identifies this row visually. */
  icon: ReactNode;
  active: boolean;
  /** Set on a subscription row, so the two levels read as a tree in a flat menu. */
  indent?: boolean;
  onSelect: () => void;
}

/** One row inside `SearchScopeMenu`: check + glyph + name. */
export function SearchScopeOption({ label, icon, active, indent, onSelect }: SearchScopeOptionProps) {
  return (
    <DropdownMenuItem onSelect={onSelect} className={cn(indent && 'pl-6')}>
      <Check className={active ? 'size-4' : 'size-4 opacity-0'} />
      {icon}
      <span className="truncate">{label}</span>
    </DropdownMenuItem>
  );
}
