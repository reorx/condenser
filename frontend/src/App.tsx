import { Route, Routes, useLocation } from 'react-router-dom';

import { FullScreenSpinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { useTgStatus } from '@/hooks/useTgStatus';
import { ApiError } from '@/lib/api';
import { AppShell } from '@/pages/AppShell';
import { AppLogin } from '@/pages/AppLogin';
import { AuthorizeView } from '@/pages/AuthorizeView';
import { FiltersView } from '@/pages/FiltersView';
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
  const location = useLocation();

  if (isError) {
    if (error instanceof ApiError && error.status === 401) return <AppLogin />;
    return <ErrorScreen message="Cannot reach the server." onRetry={() => refetch()} />;
  }
  if (isPending || !data) return <FullScreenSpinner />;
  // Device authorization only needs the cookie session, not a Telegram login.
  if (location.pathname === '/authorize') return <AuthorizeView />;
  if (data.status !== 'authorized') return <TgLogin status={data.status} />;

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<TimelineView />} />
        <Route path="/c/:channelId" element={<TimelineView />} />
        <Route path="/s/:source" element={<TimelineView />} />
        {/* One feed inside a multi-feed source (X: For You / a followed account) */}
        <Route path="/s/:source/:feed" element={<TimelineView />} />
        <Route path="/saved" element={<RecordsView />} />
        <Route path="/search" element={<SearchView />} />
        <Route path="/filters" element={<FiltersView />} />
        <Route path="/subscriptions" element={<SubscriptionsView />} />
        <Route path="*" element={<TimelineView />} />
      </Route>
    </Routes>
  );
}
