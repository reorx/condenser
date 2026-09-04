// "Vibe Reader detected — link up?" (plan 2026-09-02 §2.2). Renders nothing; it
// watches the bridge and raises one sonner toast the first time a bridge shows up
// with the link off. 开启 asks the extension (the switch lives there); 不再提示
// writes a localStorage flag, the only piece of link state condenser keeps.
import { useEffect, useRef } from 'react';
import { toast } from 'sonner';

import { useVibeReader } from '@/hooks/useVibeReader';

export const VIBE_READER_PROMPT_KEY = 'condenser-vibe-reader-prompt';

function isDismissed(): boolean {
  try {
    return localStorage.getItem(VIBE_READER_PROMPT_KEY) === 'dismissed';
  } catch {
    return false;
  }
}

function dismiss() {
  try {
    localStorage.setItem(VIBE_READER_PROMPT_KEY, 'dismissed');
  } catch {
    // Storage unavailable: the prompt just comes back next load.
  }
}

export function VibeReaderPrompt() {
  const { available, linked, setLink } = useVibeReader();
  // Once per page load: the sidepanel closing and reopening is not news.
  const prompted = useRef(false);

  useEffect(() => {
    if (!available || linked || prompted.current || isDismissed()) return;
    prompted.current = true;
    toast('检测到 Vibe Reader', {
      description: '开启联动后，从这里点开的链接会在侧栏自动生成摘要。',
      duration: 15_000,
      action: { label: '开启', onClick: () => setLink(true) },
      cancel: { label: '不再提示', onClick: dismiss },
    });
  }, [available, linked, setLink]);

  return null;
}
