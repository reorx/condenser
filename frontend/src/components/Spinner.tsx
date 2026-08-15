import { Loader2 } from 'lucide-react';

import { cn } from '@/lib/utils';

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('size-4 animate-spin', className)} />;
}

export function FullScreenSpinner() {
  return (
    <div className="flex min-h-dvh items-center justify-center" data-testid="full-screen-spinner">
      <Spinner className="size-6 text-muted-foreground" />
    </div>
  );
}
