import { useCallback, useMemo, useState } from 'react';

export interface ChannelSummary {
  id: number;
  name: string;
  count: number;
}

export interface ChannelFilter<T> {
  /** Channels present in the loaded items, with message counts (sorted count desc, name asc). */
  channels: ChannelSummary[];
  /** Channel ids the user has toggled off. */
  hidden: Set<number>;
  /** `items` minus every hidden channel. */
  visible: T[];
  toggle: (id: number) => void;
  clear: () => void;
}

/**
 * Client-side channel filter over already-rendered items. Derives the channel
 * list + counts from `items`, and tracks a hidden set so callers can drop those
 * channels from view. `channelOf` resolves an item's TG channel id (null = not
 * channel-scoped, e.g. an HN story — always visible); `nameOf` resolves a display
 * name (pass memoized callbacks — Timeline reads the labels map, Saved uses the
 * embedded channel).
 */
export function useChannelFilter<T>(
  items: T[],
  channelOf: (item: T) => number | null,
  nameOf: (item: T) => string,
): ChannelFilter<T> {
  const [hidden, setHidden] = useState<Set<number>>(() => new Set());

  const channels = useMemo<ChannelSummary[]>(() => {
    const byId = new Map<number, ChannelSummary>();
    for (const item of items) {
      const cid = channelOf(item);
      if (cid == null) continue;
      const existing = byId.get(cid);
      if (existing) existing.count += 1;
      else byId.set(cid, { id: cid, name: nameOf(item), count: 1 });
    }
    return [...byId.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }, [items, channelOf, nameOf]);

  const visible = useMemo(() => {
    if (!hidden.size) return items;
    return items.filter((i) => {
      const cid = channelOf(i);
      return cid == null || !hidden.has(cid);
    });
  }, [items, hidden, channelOf]);

  const toggle = useCallback((id: number) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const clear = useCallback(() => setHidden(new Set()), []);

  return { channels, hidden, visible, toggle, clear };
}
