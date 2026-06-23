import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Globe, Radio } from 'lucide-react';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useCreateFilter } from '@/hooks/useAllFilters';
import { useSubscriptions } from '@/hooks/useSubscriptions';
import { api, errorMessage } from '@/lib/api';
import type { FilterPreviewResult as FilterPreviewResultData } from '@/lib/types';

import { ChannelPicker } from './ChannelPicker';
import { FilterPreviewResult } from './FilterPreviewResult';
import { ScopeOption } from './ScopeOption';

type Scope = 'global' | 'channel';

interface CreateFilterDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateFilterDialog({ open, onOpenChange }: CreateFilterDialogProps) {
  const { data: subs } = useSubscriptions();
  const create = useCreateFilter();

  const [scope, setScope] = useState<Scope>('global');
  const [channelId, setChannelId] = useState<number | null>(null);
  const [pattern, setPattern] = useState('');
  const [preview, setPreview] = useState<FilterPreviewResultData | null>(null);

  // Reset state every time the dialog reopens so stale preview / inputs don't linger.
  useEffect(() => {
    if (open) {
      setScope('global');
      setChannelId(null);
      setPattern('');
      setPreview(null);
    }
  }, [open]);

  const effectiveChannelId = scope === 'channel' ? channelId : null;
  const canSubmit = !!pattern.trim() && (scope === 'global' || channelId !== null) && !create.isPending;

  const previewMut = useMutation({
    mutationFn: () => api.previewFilter(pattern.trim(), effectiveChannelId),
    onSuccess: setPreview,
  });

  // Drop in-flight requests too — otherwise a settle could overwrite the cleared state.
  useEffect(() => {
    setPreview(null);
    previewMut.reset();
    // previewMut is a stable mutation object; including it would cause an infinite reset loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, channelId, pattern]);

  function submit() {
    if (!canSubmit) return;
    create.mutate({ pattern: pattern.trim(), channelId: effectiveChannelId }, { onSuccess: () => onOpenChange(false) });
  }

  const submitLabel = preview && preview.matched > 0 ? `Create filter (hides ${preview.matched})` : 'Create filter';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Create filter</DialogTitle>
          <DialogDescription>
            Exclude messages whose text contains the keyword (case-insensitive substring).
          </DialogDescription>
        </DialogHeader>

        {/* min-w-0 keeps long unbreakable text in preview samples (URLs, etc.) from stretching the dialog past max-w-lg. */}
        <div className="min-w-0 space-y-4">
          <div>
            <div className="mb-1.5 text-xs font-medium text-muted-foreground">Scope</div>
            <div className="grid grid-cols-2 gap-2">
              <ScopeOption
                active={scope === 'global'}
                onClick={() => setScope('global')}
                icon={<Globe className="size-4" />}
                title="Global"
                hint="Applies to every channel"
              />
              <ScopeOption
                active={scope === 'channel'}
                onClick={() => setScope('channel')}
                icon={<Radio className="size-4" />}
                title="Single channel"
                hint="Applies to one channel"
              />
            </div>
          </div>

          {scope === 'channel' && (
            <div>
              <div className="mb-1.5 text-xs font-medium text-muted-foreground">Channel</div>
              <ChannelPicker subs={subs ?? []} selected={channelId} onSelect={setChannelId} />
            </div>
          )}

          <div>
            <div className="mb-1.5 text-xs font-medium text-muted-foreground">Keyword</div>
            <div className="flex gap-2">
              <Input
                value={pattern}
                onChange={(e) => setPattern(e.target.value)}
                placeholder="e.g. promo"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    submit();
                  }
                }}
              />
              <Button
                type="button"
                variant="outline"
                disabled={!pattern.trim() || previewMut.isPending || (scope === 'channel' && channelId === null)}
                onClick={() => previewMut.mutate()}
              >
                {previewMut.isPending ? <Spinner /> : 'Preview'}
              </Button>
            </div>
          </div>

          <FilterPreviewResult
            scope={scope}
            isPending={previewMut.isPending}
            error={previewMut.error ? errorMessage(previewMut.error, 'Preview failed') : null}
            result={preview}
            pattern={pattern.trim()}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {create.isPending ? <Spinner /> : submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
