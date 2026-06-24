// Dev-only component preview / playbook. Renders real components with mock data so we can
// screenshot and verify visual changes without a logged-in backend. Add cases as needed.
import { TimelineDayGroup } from '@/components/timeline/TimelineDayGroup';
import { useTheme } from '@/lib/theme';
import { useUnreadIndicator } from '@/lib/unreadIndicator';

import { channelLabels, dayItems } from './mocks';

function Toolbar() {
  const { mode, setMode } = useUnreadIndicator();
  const { resolvedTheme, setTheme } = useTheme();

  return (
    <div className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background/90 px-4 py-2 text-xs backdrop-blur">
      <span className="font-semibold">Preview</span>
      <button
        type="button"
        onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
        className="rounded border px-2 py-1 hover:bg-accent"
      >
        theme: {resolvedTheme}
      </button>
      <button
        type="button"
        onClick={() => setMode(mode === 'dot' ? 'divider' : 'dot')}
        className="rounded border px-2 py-1 hover:bg-accent"
      >
        unread: {mode}
      </button>
    </div>
  );
}

export function PreviewApp() {
  return (
    <div className="min-h-dvh bg-background text-foreground">
      <Toolbar />
      <div className="mx-auto max-w-2xl md:border-x md:border-border">
        <TimelineDayGroup items={dayItems} labels={channelLabels} />
      </div>
    </div>
  );
}
