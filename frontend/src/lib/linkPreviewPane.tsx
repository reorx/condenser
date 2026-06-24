import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

import type { MsgRef } from './types';

interface LinkPreviewPaneValue {
  /** The message whose previews are currently open, or null. */
  open: MsgRef | null;
  openPane: (ref: MsgRef) => void;
  close: () => void;
}

// Default is a no-op so components using the context (e.g. MessageCard) still render
// outside a provider — notably the dev preview harness, which has no pane mounted.
const LinkPreviewPaneContext = createContext<LinkPreviewPaneValue>({
  open: null,
  openPane: () => {},
  close: () => {},
});

export function LinkPreviewPaneProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<MsgRef | null>(null);
  const value = useMemo<LinkPreviewPaneValue>(
    () => ({ open, openPane: setOpen, close: () => setOpen(null) }),
    [open],
  );
  return <LinkPreviewPaneContext.Provider value={value}>{children}</LinkPreviewPaneContext.Provider>;
}

export function useLinkPreviewPane(): LinkPreviewPaneValue {
  return useContext(LinkPreviewPaneContext);
}
