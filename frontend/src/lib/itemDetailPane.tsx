import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

import type { TimelineItem } from './types';

interface ItemDetailPaneValue {
  /** The item envelope currently open in the detail pane, or null. */
  open: TimelineItem | null;
  openPane: (item: TimelineItem) => void;
  close: () => void;
}

// Default is a no-op so components using the context (e.g. MessageCard) still render
// outside a provider — notably the dev preview harness, which has no pane mounted.
const ItemDetailPaneContext = createContext<ItemDetailPaneValue>({
  open: null,
  openPane: () => {},
  close: () => {},
});

export function ItemDetailPaneProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<TimelineItem | null>(null);
  const value = useMemo<ItemDetailPaneValue>(() => ({ open, openPane: setOpen, close: () => setOpen(null) }), [open]);
  return <ItemDetailPaneContext.Provider value={value}>{children}</ItemDetailPaneContext.Provider>;
}

export function useItemDetailPane(): ItemDetailPaneValue {
  return useContext(ItemDetailPaneContext);
}
