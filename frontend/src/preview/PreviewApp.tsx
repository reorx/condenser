// Dev-only component preview / playbook. Renders real components with mock data so we can
// screenshot and verify visual changes without a logged-in backend. Add cases as needed.
import { ItemDetailPane } from '@/components/timeline/ItemDetailPane';
import { LinkPreviewCard } from '@/components/timeline/LinkPreviewCard';
import { TimelineDayGroup } from '@/components/timeline/TimelineDayGroup';
import { ItemDetailPaneProvider } from '@/lib/itemDetailPane';
import { useTheme } from '@/lib/theme';
import { useUnreadIndicator } from '@/lib/unreadIndicator';

import { CHANNEL_ID, channelLabels, dayItems, samplePreviews } from './mocks';

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
    <ItemDetailPaneProvider>
      <div className="min-h-dvh bg-background text-foreground">
        <Toolbar />
        <div className="mx-auto max-w-2xl md:border-x md:border-border">
          <TimelineDayGroup items={dayItems} labels={channelLabels} />
        </div>

        {/* LinkPreviewCard gallery — the content shown inside the slide-out pane. */}
        <div className="mx-auto mt-6 max-w-md space-y-3 border-t px-4 py-4">
          <p className="text-xs font-semibold text-muted-foreground">LinkPreviewCard (pane content)</p>
          {samplePreviews.map((p, i) => (
            <LinkPreviewCard key={i} channelId={CHANNEL_ID} preview={p} />
          ))}
        </div>
      </div>
      <ItemDetailPane />
    </ItemDetailPaneProvider>
  );
}
