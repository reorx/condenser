import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

import type { HnStory } from './types';

/** What the details/link-preview pane is showing: a Telegram message's links, or
 *  one Hacker News story (its URL preview + a comments-page footer link). */
export type PaneTarget =
  | { source: 'telegram'; channel_id: number; message_id: number }
  | { source: 'hn'; story: HnStory };

interface LinkPreviewPaneValue {
  /** The item whose previews are currently open, or null. */
  open: PaneTarget | null;
  openPane: (target: PaneTarget) => void;
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
  const [open, setOpen] = useState<PaneTarget | null>(null);
  const value = useMemo<LinkPreviewPaneValue>(() => ({ open, openPane: setOpen, close: () => setOpen(null) }), [open]);
  return <LinkPreviewPaneContext.Provider value={value}>{children}</LinkPreviewPaneContext.Provider>;
}

export function useLinkPreviewPane(): LinkPreviewPaneValue {
  return useContext(LinkPreviewPaneContext);
}
