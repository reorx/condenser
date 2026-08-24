import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api, errorMessage } from '@/lib/api';
import { invalidateItemLists } from '@/lib/itemCaches';
import type { ForwardRecordPage } from '@/lib/types';

export const FORWARDS_PAGE_SIZE = 30;

/**
 * The forward log, paged by offset — `useSearch`'s shape, and for the same
 * reason: this is an archive being browsed, not a queue being drained, so the
 * drift a cursor exists to prevent costs nothing here.
 */
export function useForwards() {
  return useInfiniteQuery({
    queryKey: ['forwards'],
    queryFn: ({ pageParam }) => api.listForwards(FORWARDS_PAGE_SIZE, pageParam),
    initialPageParam: 0,
    // Every page but the last is full, so the count of loaded pages *is* the offset.
    getNextPageParam: (last: ForwardRecordPage, pages) =>
      last.has_more ? pages.length * FORWARDS_PAGE_SIZE : undefined,
  });
}

export type ForwardsQuery = ReturnType<typeof useForwards>;

/**
 * Forget one record. Not optimistic: this is a delete of the reader's own
 * writing, so it is worth showing the server actually agreed before the row
 * leaves the screen.
 *
 * The item's `forwarded_by_me` badge is **not** patched back off here — a
 * second record of the same item may still exist, and only the server knows.
 * Getting it wrong locally would tell the reader they never forwarded something
 * they did — so instead every item list is invalidated and the server restates
 * the flag (staleTime alone would leave a dead badge lit for its 30s).
 */
export function useDeleteForward() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteForward(id),
    onSuccess: () => {
      invalidateItemLists(qc);
      toast.success('已删除转发记录，频道里的消息还在');
    },
    onError: (e) => toast.error(errorMessage(e, '删除失败')),
  });
}
