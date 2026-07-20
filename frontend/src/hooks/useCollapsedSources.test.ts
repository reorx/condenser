import { beforeEach, describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';

import { COLLAPSED_SOURCES_KEY, useCollapsedSources } from './useCollapsedSources';

beforeEach(() => localStorage.clear());

describe('useCollapsedSources', () => {
  it('starts with nothing collapsed', () => {
    const { result } = renderHook(() => useCollapsedSources());
    expect(result.current.collapsed.size).toBe(0);
  });

  it('toggle collapses and expands a source', () => {
    const { result } = renderHook(() => useCollapsedSources());
    act(() => result.current.toggle('hn'));
    expect(result.current.collapsed.has('hn')).toBe(true);
    act(() => result.current.toggle('hn'));
    expect(result.current.collapsed.has('hn')).toBe(false);
  });

  it('persists across mounts via localStorage', () => {
    const first = renderHook(() => useCollapsedSources());
    act(() => first.result.current.toggle('telegram'));
    first.unmount();

    const second = renderHook(() => useCollapsedSources());
    expect(second.result.current.collapsed.has('telegram')).toBe(true);
    expect(JSON.parse(localStorage.getItem(COLLAPSED_SOURCES_KEY)!)).toEqual(['telegram']);
  });

  it('ignores corrupt or non-array stored values', () => {
    localStorage.setItem(COLLAPSED_SOURCES_KEY, '{not json');
    const { result } = renderHook(() => useCollapsedSources());
    expect(result.current.collapsed.size).toBe(0);

    localStorage.setItem(COLLAPSED_SOURCES_KEY, '{"a":1}');
    const again = renderHook(() => useCollapsedSources());
    expect(again.result.current.collapsed.size).toBe(0);
  });
});
