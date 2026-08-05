import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { type QueryClient, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ReadTarget, SourceGroup, Subscription, TimelineItem, TimelinePage } from '@/lib/types';

/** Flip is_read in every cached timeline page + drop unread counts (server-confirmed). */
function applyReadConfirmed(qc: QueryClient, targets: ReadTarget[]) {
  const seen = new Set(targets.map((t) => t.key));
  const perChannel = new Map<number, number>();
  let hnCount = 0;
  for (const t of targets) {
    if (t.channelId != null) perChannel.set(t.channelId, (perChannel.get(t.channelId) ?? 0) + 1);
    else hnCount += 1;
  }

  qc.setQueriesData<{ pages: TimelinePage[]; pageParams: unknown[] }>({ queryKey: ['timeline'] }, (data) => {
    if (!data) return data;
    return {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items.map((it: TimelineItem) => (!it.is_read && seen.has(it.key) ? { ...it, is_read: true } : it)),
      })),
    };
  });

  qc.setQueryData<Subscription[]>(['subscriptions'], (subs) =>
    subs?.map((s) =>
      perChannel.has(s.channel_id) ? { ...s, unread: Math.max(0, s.unread - perChannel.get(s.channel_id)!) } : s,
    ),
  );

  // The aggregate-view header sums /api/sources: drop TG counts per channel and
  // HN (channelId == null, v1 = the single 'front' feed) by the read count.
  qc.setQueryData<SourceGroup[]>(['sources'], (groups) =>
    groups?.map((g) => ({
      ...g,
      subscriptions: g.subscriptions.map((s) => {
        const drop =
          g.source === 'hn' ? hnCount : typeof s.channel_id === 'number' ? (perChannel.get(s.channel_id) ?? 0) : 0;
        return drop ? { ...s, unread: Math.max(0, s.unread - drop) } : s;
      }),
    })),
  );
}

const DEBOUNCE_MS = 700;
/** Failed batches retry at debounce * 5 (mirrors the iOS ReadReporter backoff). */
const RETRY_MS = DEBOUNCE_MS * 5;

/** Long cards outgrow the viewport, so their bottom-edge crossing never lands on a
 *  ratio-0/1 boundary; a dense threshold ladder keeps the callback firing while any
 *  slice of the card moves. */
const THRESHOLDS = Array.from({ length: 21 }, (_, i) => i * 0.05);

export interface ScrollToRead {
  /** Attach to each unread card; returns a ref cleanup. */
  observe: (el: Element | null, target: ReadTarget) => (() => void) | void;
  /** Keys judged read but not yet confirmed by the server (green-dot state). */
  pendingKeys: Set<string>;
  /** Re-gate marking (list refresh / jump-to-top) until the user scrolls again. */
  disarm: () => void;
}

/**
 * "Scroll past = read" (spec D2). A card counts as read once the user has scrolled
 * in this view (armed) AND its bottom edge is at or above the viewport bottom —
 * i.e. fully seen, not necessarily scrolled away. Queued keys show as `pendingKeys`
 * (the green "syncing" dot) until POST /api/read confirms; the cache flip + badge
 * math run only on confirmation, and a failed batch stays pending and retries with
 * backoff, so a lit green dot is the visible "sync is stuck" signal.
 *
 * `viewKey` identifies the current channel/filter view. When it changes (switching
 * channel, toggling All/Unread, picking a date) the scroll jumps back to the top and
 * the read tracker is *re-armed*: nothing is marked read until the user actively
 * scrolls again, so landing on a new view never mass-marks its top messages read.
 */
export function useScrollToRead(viewKey: string): ScrollToRead {
  const qc = useQueryClient();
  const pending = useRef(new Map<string, ReadTarget>());
  const timer = useRef<number | undefined>(undefined);
  const elToRef = useRef(new Map<Element, ReadTarget>());
  const obsRef = useRef<IntersectionObserver | null>(null);
  // Gate: only mark-as-read once the user has manually scrolled in the current view.
  const armed = useRef(false);
  const [pendingKeys, setPendingKeys] = useState<Set<string>>(() => new Set());

  const flush = useCallback(() => {
    const targets = [...pending.current.values()];
    pending.current.clear();
    if (!targets.length) return;
    void api
      .markRead(targets.map((t) => t.key))
      .then(() => {
        applyReadConfirmed(qc, targets);
        setPendingKeys((prev) => {
          const next = new Set(prev);
          for (const t of targets) next.delete(t.key);
          return next;
        });
        // Reconcile /api/sources once the server has the reads (the HN visible set
        // is query-time, so the local decrement can drift slightly).
        void qc.invalidateQueries({ queryKey: ['sources'] });
      })
      .catch(() => {
        // Keep the batch pending (green dots stay lit) and retry with backoff;
        // keys enqueued meanwhile ride along on the next flush.
        for (const t of targets) if (!pending.current.has(t.key)) pending.current.set(t.key, t);
        if (timer.current) window.clearTimeout(timer.current);
        timer.current = window.setTimeout(flush, RETRY_MS);
      });
  }, [qc]);

  const enqueue = useCallback(
    (target: ReadTarget) => {
      pending.current.set(target.key, target);
      setPendingKeys((prev) => (prev.has(target.key) ? prev : new Set(prev).add(target.key)));
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(flush, DEBOUNCE_MS);
    },
    [flush],
  );

  const markElement = useCallback(
    (el: Element) => {
      const target = elToRef.current.get(el);
      if (!target) return;
      enqueue(target);
      obsRef.current?.unobserve(el);
      elToRef.current.delete(el);
    },
    [enqueue],
  );

  const observer = useMemo(() => {
    if (typeof IntersectionObserver === 'undefined') return null;
    return new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const readLine = e.rootBounds?.bottom ?? window.innerHeight;
          // Bottom edge at/above the viewport bottom => the card has been fully
          // seen (covers the old fully-scrolled-above case for free).
          if (e.boundingClientRect.bottom <= readLine) {
            // Suppressed until the user actively scrolls this view; leave the
            // element observed so it re-fires once they do (see `armed`).
            if (!armed.current) continue;
            markElement(e.target);
          }
        }
      },
      { threshold: THRESHOLDS },
    );
  }, [markElement]);

  obsRef.current = observer;

  useEffect(() => {
    return () => {
      observer?.disconnect();
      flush();
    };
  }, [observer, flush]);

  // Arm the tracker on the first genuine user scroll. The programmatic jump-to-top
  // on a view switch lands at scrollY 0, so it never counts as a manual scroll.
  // Arming sweeps the already-observed elements once by hand: IO never re-fires for
  // an element whose intersection didn't change, so the first screen's fully-visible
  // cards would otherwise stay unmarked until they scrolled fully out.
  useEffect(() => {
    const onScroll = () => {
      if (armed.current || window.scrollY <= 0) return;
      armed.current = true;
      for (const el of [...elToRef.current.keys()]) {
        if (el.getBoundingClientRect().bottom <= window.innerHeight) markElement(el);
      }
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, [markElement]);

  const disarm = useCallback(() => {
    armed.current = false;
  }, []);

  // View switch: flush the previous view's reads, jump to the top, and disarm so
  // nothing is marked read until the user scrolls again. Layout effect runs before
  // paint to avoid a flash of the new view at the old scroll offset.
  useLayoutEffect(() => {
    flush();
    armed.current = false;
    window.scrollTo(0, 0);
  }, [viewKey, flush]);

  const observe = useCallback(
    (el: Element | null, target: ReadTarget) => {
      if (!el || !observer) return;
      elToRef.current.set(el, target);
      observer.observe(el);
      return () => {
        observer.unobserve(el);
        elToRef.current.delete(el);
      };
    },
    [observer],
  );

  return useMemo(() => ({ observe, pendingKeys, disarm }), [observe, pendingKeys, disarm]);
}
