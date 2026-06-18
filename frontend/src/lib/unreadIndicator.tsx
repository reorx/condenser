// User preference for how unread messages are visually marked:
//   - 'dot': a sky dot sits next to the channel name (default)
//   - 'divider': the bottom border of each unread card turns blue

import { createContext, useCallback, useContext, useMemo, useState } from 'react';

export type UnreadIndicatorMode = 'divider' | 'dot';

const STORAGE_KEY = 'condenser-unread-indicator';

interface UnreadIndicatorContextValue {
  mode: UnreadIndicatorMode;
  setMode: (m: UnreadIndicatorMode) => void;
}

const UnreadIndicatorContext = createContext<UnreadIndicatorContextValue | null>(null);

function readStoredMode(): UnreadIndicatorMode {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === 'dot' || stored === 'divider' ? stored : 'dot';
}

export function UnreadIndicatorProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<UnreadIndicatorMode>(readStoredMode);

  const setMode = useCallback((m: UnreadIndicatorMode) => {
    localStorage.setItem(STORAGE_KEY, m);
    setModeState(m);
  }, []);

  const value = useMemo(() => ({ mode, setMode }), [mode, setMode]);
  return <UnreadIndicatorContext.Provider value={value}>{children}</UnreadIndicatorContext.Provider>;
}

export function useUnreadIndicator(): UnreadIndicatorContextValue {
  const ctx = useContext(UnreadIndicatorContext);
  if (!ctx) throw new Error('useUnreadIndicator must be used within UnreadIndicatorProvider');
  return ctx;
}
