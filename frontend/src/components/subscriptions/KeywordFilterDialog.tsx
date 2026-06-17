import { useState } from 'react';
import { Trash2 } from 'lucide-react';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useAddFilter, useDeleteFilter, useFilters } from '@/hooks/useFilters';

interface KeywordFilterDialogProps {
  channelId: number;
  channelLabel: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function KeywordFilterDialog({ channelId, channelLabel, open, onOpenChange }: KeywordFilterDialogProps) {
  const { data: filters, isPending } = useFilters(channelId, open);
  const addFilter = useAddFilter(channelId);
  const deleteFilter = useDeleteFilter(channelId);
  const [pattern, setPattern] = useState('');

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const p = pattern.trim();
    if (!p) return;
    addFilter.mutate(p, { onSuccess: () => setPattern('') });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Exclude keywords</DialogTitle>
          <DialogDescription>
            Messages from {channelLabel} whose text contains any keyword are hidden (case-insensitive substring).
          </DialogDescription>
        </DialogHeader>

        <form className="flex gap-2" onSubmit={submit}>
          <Input
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            placeholder="e.g. promo"
            aria-invalid={!!addFilter.error}
          />
          <Button type="submit" disabled={!pattern.trim() || addFilter.isPending}>
            {addFilter.isPending ? <Spinner /> : 'Add'}
          </Button>
        </form>

        <div className="max-h-64 overflow-y-auto">
          {isPending ? (
            <div className="flex justify-center py-6">
              <Spinner className="size-4 text-muted-foreground" />
            </div>
          ) : (filters ?? []).length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No keywords yet.</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {(filters ?? []).map((f) => (
                <li key={f.id} className="flex items-center gap-2 rounded-md bg-muted/40 px-2.5 py-1.5 text-sm">
                  <span className="truncate">{f.pattern}</span>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="ml-auto size-7 text-muted-foreground hover:text-destructive"
                    onClick={() => deleteFilter.mutate(f.id)}
                    disabled={deleteFilter.isPending}
                    aria-label={`Remove keyword ${f.pattern}`}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
