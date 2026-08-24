import { useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import { patchItem } from '@/lib/itemCaches';
import type { ItemAnnotation, TimelineItem } from '@/lib/types';

/** What a new highlight stores (W3C TextQuoteSelector shape; `lib/annotate.ts`
 *  builds it from the selection). */
export interface HighlightContext {
  quote: string;
  prefix: string;
  suffix: string;
}

/**
 * The detail pane's annotation model — the web sibling of iOS's
 * `ItemAnnotationsModel`. The pane's context holds the envelope captured at click
 * time, so `annotations` on it is a snapshot; this hook mirrors its own writes in
 * local state keyed on the item **object** (the `savedOverride` arrangement: a new
 * cache object on reopen drops the override on identity), while `patchItem`
 * carries every write to the item caches so the card badge tracks live.
 *
 * `add` is deliberately not optimistic: the server assigns the annotation id (the
 * edit/delete handle), so there is nothing coherent to render until it answers —
 * iOS awaits the same way. Remove/comment are optimistic with whole-list rollback.
 * `['records']` is invalidated on membership-changing writes (first highlight
 * creates the row, deleting the last may drop it).
 */
export function useItemAnnotations(item: TimelineItem | null) {
  const qc = useQueryClient();
  const [override, setOverride] = useState<{ item: TimelineItem; annotations: ItemAnnotation[] } | null>(null);
  const annotations = (override?.item === item ? override.annotations : item?.annotations) ?? [];

  const write = useCallback(
    (target: TimelineItem, next: ItemAnnotation[]) => {
      setOverride({ item: target, annotations: next });
      patchItem(qc, target.key, { annotations: next.length ? next : null });
    },
    [qc],
  );

  const add = useCallback(
    async (context: HighlightContext) => {
      if (!item) return;
      const res = await api.addAnnotation({ key: item.key, ...context, block: null });
      write(item, [...annotations, res.annotation]);
      void qc.invalidateQueries({ queryKey: ['records'] });
    },
    [item, annotations, write, qc],
  );

  const remove = useCallback(
    async (id: number) => {
      if (!item) return;
      const before = annotations;
      write(
        item,
        annotations.filter((a) => a.id !== id),
      );
      try {
        await api.deleteAnnotation(item.key, id);
      } catch (e) {
        write(item, before);
        throw e;
      }
      void qc.invalidateQueries({ queryKey: ['records'] });
    },
    [item, annotations, write, qc],
  );

  const setComment = useCallback(
    async (id: number, comment: string | null) => {
      if (!item) return;
      const before = annotations;
      write(
        item,
        annotations.map((a) => (a.id === id ? { ...a, comment } : a)),
      );
      try {
        await api.setAnnotationComment(item.key, id, comment);
      } catch (e) {
        write(item, before);
        throw e;
      }
    },
    [item, annotations, write],
  );

  return { annotations, add, remove, setComment };
}
