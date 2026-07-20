import { useCallback, useState } from 'react';

import type { Source } from '@/lib/types';

export const COLLAPSED_SOURCES_KEY = 'condenser-sidebar-collapsed';

function load(): Set<Source> {
  try {
    const raw = localStorage.getItem(COLLAPSED_SOURCES_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? (parsed as Source[]) : []);
  } catch {
    return new Set();
  }
}

/** Which sidebar source groups are collapsed, persisted in localStorage. */
export function useCollapsedSources() {
  const [collapsed, setCollapsed] = useState<Set<Source>>(load);

  const toggle = useCallback((source: Source) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(source)) next.delete(source);
      else next.add(source);
      localStorage.setItem(COLLAPSED_SOURCES_KEY, JSON.stringify([...next]));
      return next;
    });
  }, []);

  return { collapsed, toggle };
}
