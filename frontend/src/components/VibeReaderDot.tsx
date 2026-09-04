// A 6px dot at the sidebar's foot that says whether the Vibe Reader extension is
// listening (plan 2026-09-02 §2.2): green = linked, grey = bridge present but the
// link is off, nothing at all when there is no bridge. The title spells it out.
import { useVibeReader } from '@/hooks/useVibeReader';
import { cn } from '@/lib/utils';

export function VibeReaderDot({ className }: { className?: string }) {
  const { available, linked } = useVibeReader();
  if (!available) return null;
  return (
    <span
      role="status"
      title={linked ? 'Vibe Reader 联动已开启' : 'Vibe Reader 已连接，联动未开启'}
      aria-label={linked ? 'Vibe Reader 联动已开启' : 'Vibe Reader 已连接，联动未开启'}
      className={cn('inline-block size-1.5 rounded-full', linked ? 'bg-emerald-500' : 'bg-muted-foreground/40', className)}
    />
  );
}
