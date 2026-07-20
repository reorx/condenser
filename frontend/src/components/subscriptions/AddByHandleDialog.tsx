import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { api, errorMessage } from '@/lib/api';

interface AddByHandleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AddByHandleDialog({ open, onOpenChange }: AddByHandleDialogProps) {
  const qc = useQueryClient();
  const [handle, setHandle] = useState('');

  const add = useMutation({
    mutationFn: () => api.addSubscription(handle.trim()),
    onSuccess: (res) => {
      setHandle('');
      qc.invalidateQueries({ queryKey: ['subscriptions'] });
      qc.invalidateQueries({ queryKey: ['sources'] });
      qc.invalidateQueries({ queryKey: ['timeline'] });
      toast.success(`Subscribed to ${res.title ?? res.username ?? 'channel'} — backfilling…`);
      onOpenChange(false);
    },
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setHandle('');
          add.reset();
        }
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Add by handle</DialogTitle>
          <DialogDescription>Subscribe to a public channel by its @handle or t.me link.</DialogDescription>
        </DialogHeader>

        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (handle.trim()) add.mutate();
          }}
        >
          <Input
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            placeholder="@channel or t.me/…"
            autoFocus
            aria-invalid={!!add.error}
          />
          {add.error && <p className="text-xs text-destructive">{errorMessage(add.error, 'Could not subscribe')}</p>}
          <Button type="submit" className="w-full" disabled={!handle.trim() || add.isPending}>
            {add.isPending ? <Spinner /> : 'Subscribe'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
