import { useEffect, useState } from 'react';
import { Menu, Sparkles, X } from 'lucide-react';
import { Outlet, useLocation } from 'react-router-dom';

import { Sidebar } from '@/components/Sidebar';
import { ItemDetailPane } from '@/components/timeline/ItemDetailPane';
import { Button } from '@/components/ui/button';
import { VibeReaderPrompt } from '@/components/VibeReaderPrompt';
import { ItemDetailPaneProvider } from '@/lib/itemDetailPane';
import { installVibeReader } from '@/lib/vibeReader';

export function AppShell() {
  const [open, setOpen] = useState(false);
  const location = useLocation();

  // Close the mobile drawer on navigation.
  useEffect(() => setOpen(false), [location.pathname, location.search]);

  // Vibe Reader link mode: listen for the extension's bridge, delegate every
  // new-tab link click on the document to it, and say hello (the bridge may have
  // been injected before React mounted — both sides greet, whoever is second finds
  // the other). One listener here covers every card on every route.
  useEffect(() => installVibeReader(document), []);

  return (
    <ItemDetailPaneProvider>
      <div className="min-h-dvh bg-background">
        {/* Mobile top bar */}
        <div className="sticky top-0 z-30 flex h-12 items-center gap-2 border-b bg-background/90 px-3 backdrop-blur md:hidden">
          <Button variant="ghost" size="icon" className="size-8" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu />
          </Button>
          <Sparkles className="size-4 text-amber-500" />
          <span className="font-semibold">Condenser</span>
        </div>

        {/* Desktop sidebar */}
        <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r bg-sidebar md:block">
          <Sidebar />
        </aside>

        {/* Mobile drawer */}
        {open && (
          <div className="fixed inset-0 z-40 md:hidden">
            <div className="absolute inset-0 bg-black/50" onClick={() => setOpen(false)} />
            <div className="absolute inset-y-0 left-0 w-72 max-w-[85%] border-r bg-sidebar shadow-xl">
              <Button
                variant="ghost"
                size="icon"
                className="absolute top-2 right-2 size-8"
                onClick={() => setOpen(false)}
                aria-label="Close menu"
              >
                <X />
              </Button>
              <Sidebar onNavigate={() => setOpen(false)} />
            </div>
          </div>
        )}

        <main className="md:pl-64">
          <div className="mx-auto min-h-dvh max-w-2xl md:border-x md:border-border">
            <Outlet />
          </div>
        </main>
      </div>
      <ItemDetailPane />
      <VibeReaderPrompt />
    </ItemDetailPaneProvider>
  );
}
