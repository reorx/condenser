// Dev-only component preview / playbook. Renders real components with mock data so we can
// screenshot and verify visual changes without a logged-in backend. Add cases as needed.
import { useEffect } from 'react';

import { ItemDetailPane } from '@/components/timeline/ItemDetailPane';
import { LinkPreviewCard } from '@/components/timeline/LinkPreviewCard';
import { TimelineDayGroup } from '@/components/timeline/TimelineDayGroup';
import { XVerdictDetail } from '@/components/timeline/XVerdictDetail';
import { ItemDetailPaneProvider } from '@/lib/itemDetailPane';
import { useTheme } from '@/lib/theme';
import { useUnreadIndicator } from '@/lib/unreadIndicator';
import { listenToBridge } from '@/lib/vibeReader';
import type { XVerdictMeta } from '@/lib/types';

import { CHANNEL_ID, channelLabels, dayItems, samplePreviews } from './mocks';

// The ensemble meta shape (plan v2 step 4) — mirrors a real vote-v1 row.
const ensembleMeta: XVerdictMeta = {
  score: -0.0005,
  neighbors: [
    { tweet_id: '2081638972724564013', distance: 0.09, label: 'down', handle: 'vikingmute' },
    { tweet_id: '2081476700379197583', distance: 0.45, label: 'up', handle: 'Leechael' },
  ],
  channels: {
    b: { verdict: 'neutral', score: -0.0005 },
    c: { verdict: 'negative', score: -0.32, driver: 'promo_cta', flags: [['promo_cta', -0.32]] },
    d: {
      verdict: 'negative',
      score: -0.45,
      tokens: [
        ['直接', -2.23],
        ['node', -1.42],
        ['👉', -1.42],
        ['无需', -1.13],
      ],
    },
  },
  model: 'text-embedding-v4@256',
  algo: 'vote-v1',
};

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
  // The Vibe Reader bridge listener `AppShell` normally installs, so the gallery can
  // show the status badges too: post `{ns:'vibe-reader', v:1, type:'vibe-reader:hello',
  // linked:true}` and then `vibe-reader:status` messages from the console / eval.
  useEffect(() => listenToBridge(), []);
  return (
    <ItemDetailPaneProvider>
      <div className="min-h-dvh bg-background text-foreground">
        <Toolbar />
        <div className="mx-auto max-w-2xl md:border-x md:border-border">
          <TimelineDayGroup items={dayItems} labels={channelLabels} />
        </div>

        {/* XVerdictDetail — the pane's 判定 row with the ensemble's channels block. */}
        <div className="mx-auto mt-6 max-w-md space-y-3 border-t px-4 py-4 text-sm">
          <p className="text-xs font-semibold text-muted-foreground">XVerdictDetail (ensemble)</p>
          <XVerdictDetail verdict="negative" meta={ensembleMeta} />
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
