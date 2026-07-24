import { Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { XGlyph } from '@/components/XGlyph';
import { fullDateLabel } from '@/lib/format';
import type { XPushCount, XSubscription } from '@/lib/types';

/** One X feed row on the Subscriptions page: For You or a followed account —
 *  archive size + last probe push, pause switch, unsubscribe. */
export function XSubscriptionRow({
  sub,
  push,
  onToggle,
  onDelete,
  busy,
}: {
  sub: XSubscription;
  push?: XPushCount;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
  busy?: boolean;
}) {
  const parts: string[] = [`${sub.tweets} archived`];
  if (push) parts.push(`pushed ${fullDateLabel(push.at)}`);
  else parts.push('waiting for the first probe push');
  if (push?.parse_errors) parts.push(`${push.parse_errors} parse errors`);

  return (
    <div className="flex items-center gap-3 px-4 py-3 sm:px-5">
      <XGlyph className="size-9 shrink-0 rounded-full" />
      <div className="min-w-0">
        <div className="truncate text-sm font-medium">
          {sub.kind === 'home' ? 'For You' : sub.name || `@${sub.channel_id}`}
          {/* the handle only earns its own chip once a real display name is known
              (learned from the first push) — otherwise it would render twice */}
          {sub.kind === 'user' && sub.name && (
            <span className="ml-1.5 text-xs text-muted-foreground">@{sub.channel_id}</span>
          )}
        </div>
        <div className="truncate text-xs text-muted-foreground">{parts.join(' · ')}</div>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <Switch
          checked={sub.enabled}
          disabled={busy}
          onCheckedChange={onToggle}
          aria-label={sub.enabled ? 'Pause this feed' : 'Resume this feed'}
        />
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-destructive"
          aria-label={`Unsubscribe ${sub.channel_id}`}
          onClick={onDelete}
        >
          <Trash2 className="size-4" />
        </Button>
      </div>
    </div>
  );
}
