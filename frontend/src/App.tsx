import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { FullScreenSpinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { useSources } from '@/hooks/useSources';
import { useTgStatus } from '@/hooks/useTgStatus';
import { ApiError } from '@/lib/api';
import { AppShell } from '@/pages/AppShell';
import { AppLogin } from '@/pages/AppLogin';
import { AuthorizeView } from '@/pages/AuthorizeView';
import { FiltersView } from '@/pages/FiltersView';
import { ForwardsView } from '@/pages/ForwardsView';
import { RecordsView } from '@/pages/RecordsView';
import { SearchView } from '@/pages/SearchView';
import { SubscriptionsView } from '@/pages/SubscriptionsView';
import { TgLogin } from '@/pages/TgLogin';
import { TimelineView } from '@/pages/TimelineView';

function ErrorScreen({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 px-4 text-center">
      <p className="text-sm text-muted-foreground">{message}</p>
      <Button variant="outline" onClick={onRetry}>
        Retry
      </Button>
    </div>
  );
}

export default function App() {
  const { data, error, isError, isPending, refetch } = useTgStatus();
  // Only consulted when Telegram is not connected, so the normal path costs no
  // extra request (the sidebar shares this query key) and a 401 here can't storm
  // the gate while the app password screen is up.
  const sources = useSources({ enabled: !!data && data.status !== 'authorized' });
  const location = useLocation();

  if (isError) {
    if (error instanceof ApiError && error.status === 401) return <AppLogin />;
    return <ErrorScreen message="Cannot reach the server." onRetry={() => refetch()} />;
  }
  if (isPending || !data) return <FullScreenSpinner />;
  // Device authorization only needs the cookie session, not a Telegram login.
  if (location.pathname === '/authorize') return <AuthorizeView />;
  // The Telegram login is a wall only while Telegram is the *only* source this
  // install could read from. Since the app went multi-source, an HN- or X-only
  // install has content to show and a phone-number form in front of it is a lock,
  // not an onboarding step — a demo/review server is exactly that shape. The way
  // back in is Settings → Telegram → /connect-telegram (below).
  if (data.status !== 'authorized' && location.pathname !== '/connect-telegram') {
    // Undecided until the sources land: deciding early flashes the wall at an
    // install that has other sources. A failed request reads as "no other source",
    // which keeps the pre-multi-source behavior as the fallback.
    if (sources.isPending && sources.fetchStatus !== 'idle') return <FullScreenSpinner />;
    if (!(sources.data ?? []).some((group) => group.source !== 'telegram')) {
      return <TgLogin status={data.status} />;
    }
  }

  return (
    <Routes>
      <Route
        path="/connect-telegram"
        element={data.status !== 'authorized' ? <TgLogin status={data.status} /> : <Navigate to="/" replace />}
      />
      <Route element={<AppShell />}>
        <Route path="/" element={<TimelineView />} />
        <Route path="/c/:channelId" element={<TimelineView />} />
        <Route path="/s/:source" element={<TimelineView />} />
        {/* One feed inside a multi-feed source (X: For You / a followed account) */}
        <Route path="/s/:source/:feed" element={<TimelineView />} />
        <Route path="/saved" element={<RecordsView />} />
        <Route path="/forwards" element={<ForwardsView />} />
        <Route path="/search" element={<SearchView />} />
        <Route path="/filters" element={<FiltersView />} />
        <Route path="/subscriptions" element={<SubscriptionsView />} />
        <Route path="*" element={<TimelineView />} />
      </Route>
    </Routes>
  );
}
