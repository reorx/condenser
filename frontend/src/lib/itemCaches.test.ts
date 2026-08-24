import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import { findItem, invalidateItemLists, patchItem, removeItem } from './itemCaches';
import type { ForwardRecordEntry, TimelineItem } from './types';

function item(key: string, over: Partial<TimelineItem> = {}): TimelineItem {
  return { source: 'hn', key, datetime: '2026-08-23T10:00:00Z', is_read: false, is_saved: false, ...over };
}

function entry(id: number, it: TimelineItem | null): ForwardRecordEntry {
  return {
    record: {
      id,
      key: it?.key ?? 'tg:5:100',
      source: it?.source ?? 'telegram',
      comment: null,
      mode: 'forward',
      target: '@mychannel',
      message_id: 999,
      link: 'https://t.me/mychannel/999',
      created_at: '2026-08-23T10:00:00Z',
    },
    item: it,
  };
}

/** Every cache shape at once, with 'hn:1' present in all of them and 'hn:9'
 *  living only inside the forward log's entry-shaped pages. */
function seeded() {
  const qc = new QueryClient();
  qc.setQueryData(['timeline', 'all'], { pages: [{ items: [item('hn:1'), item('hn:2')] }], pageParams: [null] });
  qc.setQueryData(['search', 'q'], { pages: [{ items: [item('hn:1')] }], pageParams: [0] });
  qc.setQueryData(['records'], [item('hn:1')]);
  qc.setQueryData(['forwards'], {
    pages: [{ items: [entry(1, item('hn:1')), entry(2, null), entry(3, item('hn:9'))] }],
    pageParams: [0],
  });
  return qc;
}

const forwardEntries = (qc: QueryClient) =>
  (qc.getQueryData(['forwards']) as { pages: { items: ForwardRecordEntry[] }[] }).pages[0].items;

describe('patchItem', () => {
  it('reaches the forward log too — its pages hold {record, item} entries, not bare items', () => {
    // The bug this pins: /forwards rendered fully interactive cards, but the
    // save/feedback patch never reached its cache — so a bookmark clicked there
    // saved server-side and the icon never filled, and the second click sent
    // "save" again instead of unsave.
    const qc = seeded();
    patchItem(qc, 'hn:1', { is_saved: true });

    const [hit, snapshotless, other] = forwardEntries(qc);
    expect(hit.item?.is_saved).toBe(true);
    expect(snapshotless.item).toBeNull();
    expect(other.item?.is_saved).toBe(false);
  });

  it('still patches every item-shaped cache', () => {
    const qc = seeded();
    patchItem(qc, 'hn:1', { is_saved: true });

    const timeline = qc.getQueryData(['timeline', 'all']) as { pages: { items: TimelineItem[] }[] };
    expect(timeline.pages[0].items.map((it) => it.is_saved)).toEqual([true, false]);
    const search = qc.getQueryData(['search', 'q']) as { pages: { items: TimelineItem[] }[] };
    expect(search.pages[0].items[0].is_saved).toBe(true);
    expect((qc.getQueryData(['records']) as TimelineItem[])[0].is_saved).toBe(true);
  });
});

describe('findItem', () => {
  it('returns the copy only the forward log holds, so a rollback restores the real pre-click state', () => {
    const qc = seeded();
    expect(findItem(qc, 'hn:9')?.key).toBe('hn:9');
  });
});

describe('removeItem', () => {
  it('drops the item from the reading lists but not from the two archives', () => {
    const qc = seeded();
    removeItem(qc, 'hn:1');

    const timeline = qc.getQueryData(['timeline', 'all']) as { pages: { items: TimelineItem[] }[] };
    expect(timeline.pages[0].items.map((it) => it.key)).toEqual(['hn:2']);
    const search = qc.getQueryData(['search', 'q']) as { pages: { items: TimelineItem[] }[] };
    expect(search.pages[0].items).toEqual([]);
    // hiding is about the reading queue; a bookmark and a publish record are the
    // reader's own assets and stay
    expect((qc.getQueryData(['records']) as TimelineItem[]).length).toBe(1);
    expect(forwardEntries(qc).length).toBe(3);
  });
});

describe('invalidateItemLists', () => {
  it('marks every list that can hold an item stale, the forward log included', () => {
    // What un-lights a deleted record's forwarded_by_me badge within staleTime.
    const qc = seeded();
    invalidateItemLists(qc);

    for (const key of [['timeline', 'all'], ['search', 'q'], ['records'], ['forwards']]) {
      expect(qc.getQueryState(key)?.isInvalidated, key.join('/')).toBe(true);
    }
  });
});
