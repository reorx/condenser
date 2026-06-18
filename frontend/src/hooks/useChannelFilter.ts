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
 * Client-side channel filter over already-rendered messages. Derives the channel
 * list + counts from `items`, and tracks a hidden set so callers can drop those
 * channels from view. `nameOf` resolves a display name from an item (pass a
 * memoized callback — Timeline reads the labels map, Saved uses the embedded channel).
 */
export function useChannelFilter<T extends { channel_id: number }>(
  items: T[],
  nameOf: (item: T) => string,
): ChannelFilter<T> {
  const [hidden, setHidden] = useState<Set<number>>(() => new Set());

  const channels = useMemo<ChannelSummary[]>(() => {
    const byId = new Map<number, ChannelSummary>();
    for (const item of items) {
      const existing = byId.get(item.channel_id);
      if (existing) existing.count += 1;
      else byId.set(item.channel_id, { id: item.channel_id, name: nameOf(item), count: 1 });
    }
    return [...byId.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }, [items, nameOf]);

  const visible = useMemo(
    () => (hidden.size ? items.filter((i) => !hidden.has(i.channel_id)) : items),
    [items, hidden],
  );

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
