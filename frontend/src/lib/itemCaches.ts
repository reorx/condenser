import type { QueryClient } from '@tanstack/react-query';

import type { TimelineItem } from './types';

/**
 * The three caches that hold item envelopes: the paged timelines, the paged
 * search results, and the flat saved list.
 *
 * They are listed in one place because a mutation on an item has to reach all of
 * them — the same card can be on screen in two of them at once (search a word,
 * open the saved view), and patching only the timeline is how one card ends up
 * showing a filled bookmark while its twin shows an empty one.
 */
const PAGED_KEYS = [['timeline'], ['search']] as const;
const SAVED_KEY = ['records'] as const;

type Paged = { pages: { items: TimelineItem[] }[]; pageParams: unknown[] };

/** Apply a field patch to one item wherever it is cached. */
export function patchItem(qc: QueryClient, key: string, patch: Partial<TimelineItem>): void {
  for (const queryKey of PAGED_KEYS) {
    qc.setQueriesData<Paged>({ queryKey }, (data) =>
      data
        ? {
            ...data,
            pages: data.pages.map((page) => ({
              ...page,
              items: page.items.map((it) => (it.key === key ? { ...it, ...patch } : it)),
            })),
          }
        : data,
    );
  }
  qc.setQueryData<TimelineItem[]>(SAVED_KEY, (items) =>
    items?.map((it) => (it.key === key ? { ...it, ...patch } : it)),
  );
}

/**
 * Drop one item from the **paged** lists (the optimistic hide).
 *
 * Deliberately not from the saved list: hiding is about the reading queue, and a
 * saved record is a user asset the backend keeps for hidden items too. So a saved
 * item hidden from search stays in Saved — which is the intended behavior, not an
 * oversight, and is why this does not simply mirror `patchItem`.
 */
export function removeItem(qc: QueryClient, key: string): void {
  for (const queryKey of PAGED_KEYS) {
    qc.setQueriesData<Paged>({ queryKey }, (data) =>
      data
        ? { ...data, pages: data.pages.map((page) => ({ ...page, items: page.items.filter((it) => it.key !== key) })) }
        : data,
    );
  }
}

/** The cached copy of an item, so a failed write can be rolled back to exactly
 *  what was on screen before the click rather than to a guessed default. */
export function findItem(qc: QueryClient, key: string): TimelineItem | undefined {
  for (const queryKey of PAGED_KEYS) {
    for (const [, data] of qc.getQueriesData<Paged>({ queryKey })) {
      for (const page of data?.pages ?? []) {
        const hit = page.items.find((it) => it.key === key);
        if (hit) return hit;
      }
    }
  }
  return qc.getQueryData<TimelineItem[]>(SAVED_KEY)?.find((it) => it.key === key);
}

/** Every list that can hold an item — for the invalidations a hide/unhide needs,
 *  where an optimistic patch cannot restore position. */
export function invalidateItemLists(qc: QueryClient): void {
  for (const queryKey of PAGED_KEYS) qc.invalidateQueries({ queryKey });
}
