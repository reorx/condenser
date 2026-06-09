import { useParams, useSearchParams } from 'react-router-dom';

import { Timeline } from '@/components/timeline/Timeline';
import { Button } from '@/components/ui/button';
import { useSubscriptions } from '@/hooks/useSubscriptions';
import { channelName } from '@/lib/format';

export function TimelineView() {
  const { channelId } = useParams();
  const [sp, setSp] = useSearchParams();
  const cid = channelId ? Number(channelId) : undefined;
  const unreadOnly = sp.get('unread') === '1';
  const { data: subs } = useSubscriptions();

  const sub = cid != null ? subs?.find((s) => s.channel_id === cid) : undefined;
  const title = cid != null ? (sub ? channelName(sub) : `Channel ${cid}`) : unreadOnly ? 'Unread' : 'All';

  function toggleUnread() {
    setSp(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (unreadOnly) next.delete('unread');
        else next.set('unread', '1');
        return next;
      },
      { replace: true },
    );
  }

  return (
    <>
      <div className="flex items-center gap-2 border-b px-4 py-3 sm:px-5">
        <h1 className="text-base font-semibold tracking-tight">{title}</h1>
        <Button size="sm" variant={unreadOnly ? 'default' : 'outline'} className="ml-auto h-7" onClick={toggleUnread}>
          Unread only
        </Button>
      </div>
      <Timeline channelId={cid} unreadOnly={unreadOnly} />
    </>
  );
}
