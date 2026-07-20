import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { type QueryClient, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ReadTarget, SourceGroup, Subscription, TimelineItem, TimelinePage } from '@/lib/types';

/** Optimistically flip is_read in every cached timeline page + drop unread counts. */
function applyReadOptimistic(qc: QueryClient, targets: ReadTarget[]) {
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

/**
 * "Scroll past = read" (spec D2). Returns an `observe(el, ref)` to attach to each
 * unread message. When a message's bottom scrolls above the viewport top it is
 * queued; the queue flushes (debounced) to POST /api/read with optimistic updates.
 *
 * `viewKey` identifies the current channel/filter view. When it changes (switching
 * channel, toggling All/Unread, picking a date) the scroll jumps back to the top and
 * the read tracker is *re-armed*: nothing is marked read until the user actively
 * scrolls again, so landing on a new view never mass-marks its top messages read.
 */
export function useScrollToRead(viewKey: string) {
  const qc = useQueryClient();
  const pending = useRef(new Map<string, ReadTarget>());
  const timer = useRef<number | undefined>(undefined);
  const elToRef = useRef(new Map<Element, ReadTarget>());
  const obsRef = useRef<IntersectionObserver | null>(null);
  // Gate: only mark-as-read once the user has manually scrolled in the current view.
  const armed = useRef(false);

  const flush = useCallback(() => {
    const targets = [...pending.current.values()];
    pending.current.clear();
    if (!targets.length) return;
    // Reconcile /api/sources once the server has the reads (the HN visible set
    // is query-time, so the optimistic decrement can drift slightly).
    void api
      .markRead(targets.map((t) => t.key))
      .then(() => qc.invalidateQueries({ queryKey: ['sources'] }))
      .catch(() => {});
    applyReadOptimistic(qc, targets);
  }, [qc]);

  const enqueue = useCallback(
    (target: ReadTarget) => {
      pending.current.set(target.key, target);
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(flush, 700);
    },
    [flush],
  );

  const observer = useMemo(() => {
    if (typeof IntersectionObserver === 'undefined') return null;
    return new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const top = e.rootBounds?.top ?? 0;
          // Fully scrolled above the top edge => the user has read past it.
          if (!e.isIntersecting && e.boundingClientRect.bottom <= top) {
            // Suppressed until the user actively scrolls this view; leave the
            // element observed so it re-fires once they do (see `armed`).
            if (!armed.current) continue;
            const target = elToRef.current.get(e.target);
            if (target) {
              enqueue(target);
              obsRef.current?.unobserve(e.target);
              elToRef.current.delete(e.target);
            }
          }
        }
      },
      { threshold: 0 },
    );
  }, [enqueue]);

  obsRef.current = observer;

  useEffect(() => {
    return () => {
      observer?.disconnect();
      flush();
    };
  }, [observer, flush]);

  // Arm the tracker on the first genuine user scroll. The programmatic jump-to-top
  // on a view switch lands at scrollY 0, so it never counts as a manual scroll.
  useEffect(() => {
    const onScroll = () => {
      if (!armed.current && window.scrollY > 0) armed.current = true;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
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

  return observe;
}
