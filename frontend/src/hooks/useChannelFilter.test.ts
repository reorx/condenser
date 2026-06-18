import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { useChannelFilter } from './useChannelFilter';

interface Item {
  channel_id: number;
  label: string;
}

const nameOf = (m: Item) => m.label;

// channel 1 -> 3 msgs, channel 2 -> 2 msgs, channel 3 -> 1 msg
const items: Item[] = [
  { channel_id: 1, label: 'Alpha' },
  { channel_id: 2, label: 'Bravo' },
  { channel_id: 1, label: 'Alpha' },
  { channel_id: 3, label: 'Charlie' },
  { channel_id: 1, label: 'Alpha' },
  { channel_id: 2, label: 'Bravo' },
];

describe('useChannelFilter', () => {
  it('summarizes the rendered channels with message counts, sorted by count desc', () => {
    const { result } = renderHook(() => useChannelFilter(items, nameOf));

    expect(result.current.channels).toEqual([
      { id: 1, name: 'Alpha', count: 3 },
      { id: 2, name: 'Bravo', count: 2 },
      { id: 3, name: 'Charlie', count: 1 },
    ]);
  });

  it('breaks count ties by channel name ascending', () => {
    const tied: Item[] = [
      { channel_id: 9, label: 'Zeta' },
      { channel_id: 4, label: 'Apple' },
    ];
    const { result } = renderHook(() => useChannelFilter(tied, nameOf));

    expect(result.current.channels.map((c) => c.name)).toEqual(['Apple', 'Zeta']);
  });

  it('shows every item visible when nothing is hidden', () => {
    const { result } = renderHook(() => useChannelFilter(items, nameOf));

    expect(result.current.hidden.size).toBe(0);
    expect(result.current.visible).toHaveLength(items.length);
  });

  it('toggling a channel hides its messages but keeps it in the channel summary', () => {
    const { result } = renderHook(() => useChannelFilter(items, nameOf));

    act(() => result.current.toggle(1));

    expect(result.current.hidden.has(1)).toBe(true);
    expect(result.current.visible).toHaveLength(3); // channels 2 (2) + 3 (1)
    expect(result.current.visible.every((m) => m.channel_id !== 1)).toBe(true);
    // The summary still lists channel 1 so it can be toggled back on.
    expect(result.current.channels.map((c) => c.id)).toContain(1);
  });

  it('toggling the same channel twice restores its messages', () => {
    const { result } = renderHook(() => useChannelFilter(items, nameOf));

    act(() => result.current.toggle(1));
    act(() => result.current.toggle(1));

    expect(result.current.hidden.size).toBe(0);
    expect(result.current.visible).toHaveLength(items.length);
  });

  it('clear() un-hides every channel at once', () => {
    const { result } = renderHook(() => useChannelFilter(items, nameOf));

    act(() => result.current.toggle(1));
    act(() => result.current.toggle(2));
    expect(result.current.visible).toHaveLength(1);

    act(() => result.current.clear());

    expect(result.current.hidden.size).toBe(0);
    expect(result.current.visible).toHaveLength(items.length);
  });
});
