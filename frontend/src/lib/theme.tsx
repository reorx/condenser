// App theme: light / dark / system (default system). The applied class lives on
// <html>; an inline script in index.html sets it before React mounts (no FOUC).

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

export type Theme = 'light' | 'dark' | 'system';

const STORAGE_KEY = 'condenser-theme';

interface ThemeContextValue {
  theme: Theme; // the user's choice
  resolvedTheme: 'light' | 'dark'; // what's actually applied
  setTheme: (t: Theme) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function systemTheme(): 'light' | 'dark' {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(resolved: 'light' | 'dark'): void {
  document.documentElement.classList.toggle('dark', resolved === 'dark');
}

function readStoredTheme(): Theme {
  const stored = localStorage.getItem(STORAGE_KEY);
  return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system';
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(readStoredTheme);
  const [resolved, setResolved] = useState<'light' | 'dark'>(() => (theme === 'system' ? systemTheme() : theme));

  useEffect(() => {
    const next = theme === 'system' ? systemTheme() : theme;
    setResolved(next);
    applyTheme(next);
    if (theme !== 'system') return;
    // While in system mode, follow OS appearance changes live.
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      const sys = systemTheme();
      setResolved(sys);
      applyTheme(sys);
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [theme]);

  const setTheme = useCallback((t: Theme) => {
    localStorage.setItem(STORAGE_KEY, t);
    setThemeState(t);
  }, []);

  const value = useMemo(() => ({ theme, resolvedTheme: resolved, setTheme }), [theme, resolved, setTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
