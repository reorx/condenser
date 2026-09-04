import { setLink, useVibeReaderState, type VibeReaderState } from '@/lib/vibeReader';

/** The Vibe Reader bridge state (mirrored from the extension) + the one request
 *  the page can make of it. `setLink` asks; `linked` answers, later. */
export function useVibeReader(): VibeReaderState & { setLink: (linked: boolean) => void } {
  const state = useVibeReaderState();
  return { ...state, setLink };
}
