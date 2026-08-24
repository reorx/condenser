import type { QueryClient } from '@tanstack/react-query';

import type { ForwardRecordEntry, TimelineItem } from './types';

/**
 * The caches that hold item envelopes: the paged timelines, the paged search
 * results, the flat saved list — and the forward log, whose pages hold
 * `{record, item}` entries wrapping the same envelopes.
 *
 * They are listed in one place because a mutation on an item has to reach all of
 * them — the same card can be on screen in two of them at once (search a word,
 * open the saved view), and patching only the timeline is how one card ends up
 * showing a filled bookmark while its twin shows an empty one.
 */
const PAGED_KEYS = [['timeline'], ['search']] as const;
const SAVED_KEY = ['records'] as const;
// Entry-shaped, not item-shaped — handled by its own accessors below, never by
// appending it to PAGED_KEYS (that would patch nothing and read as covered).
const FORWARDS_KEY = ['forwards'] as const;

type Paged = { pages: { items: TimelineItem[] }[]; pageParams: unknown[] };
type ForwardsPaged = { pages: { items: ForwardRecordEntry[] }[]; pageParams: unknown[] };

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
  qc.setQueriesData<ForwardsPaged>({ queryKey: FORWARDS_KEY }, (data) =>
    data
      ? {
          ...data,
          pages: data.pages.map((page) => ({
            ...page,
            items: page.items.map((entry) =>
              entry.item?.key === key ? { ...entry, item: { ...entry.item, ...patch } } : entry,
            ),
          })),
        }
      : data,
  );
}

/**
 * Drop one item from the **paged reading lists** (the optimistic hide).
 *
 * Deliberately not from the saved list or the forward log: hiding is about the
 * reading queue, and both of those are archives of the reader's own acts (a
 * bookmark, a publish) that the backend keeps for hidden items too. So a saved
 * item hidden from search stays in Saved, and a forwarded one keeps its row in
 * /forwards — intended behavior, not an oversight, and why this does not simply
 * mirror `patchItem`.
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
  const saved = qc.getQueryData<TimelineItem[]>(SAVED_KEY)?.find((it) => it.key === key);
  if (saved) return saved;
  for (const [, data] of qc.getQueriesData<ForwardsPaged>({ queryKey: FORWARDS_KEY })) {
    for (const page of data?.pages ?? []) {
      const hit = page.items.find((entry) => entry.item?.key === key);
      if (hit?.item) return hit.item;
    }
  }
  return undefined;
}

/** Every list that can hold an item — for the invalidations a hide/unhide or a
 *  deleted forward record needs, where an optimistic patch cannot do the job. */
export function invalidateItemLists(qc: QueryClient): void {
  for (const queryKey of PAGED_KEYS) qc.invalidateQueries({ queryKey });
  qc.invalidateQueries({ queryKey: SAVED_KEY });
  qc.invalidateQueries({ queryKey: FORWARDS_KEY });
}
