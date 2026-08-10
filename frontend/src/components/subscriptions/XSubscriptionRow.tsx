import { Trash2 } from 'lucide-react';

import { XAggregateMenu } from '@/components/subscriptions/XAggregateMenu';
import { XLangFilterToggle } from '@/components/subscriptions/XLangFilterToggle';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { XGlyph } from '@/components/XGlyph';
import { fullDateLabel } from '@/lib/format';
import { isXSyntheticFeed, X_FORYOU_FEED, xFeedLabel } from '@/lib/sources';
import type { XPushCount, XSubscription } from '@/lib/types';

/** One X feed row on the Subscriptions page: For You, Following or a followed
 *  account — archive size + last probe push, pause switch, unsubscribe. */
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
  // Following only, and worth showing: these are the two things X pads the feed
  // with, and a count of 0 where you expected some means a filter stopped working.
  if (push?.filtered_ads) parts.push(`${push.filtered_ads} 条广告已滤除`);
  if (push?.filtered_old) parts.push(`${push.filtered_old} 条超期（只存档）`);
  // For You only: the global-language ingest filter's work on the last push.
  if (push?.filtered_lang) parts.push(`${push.filtered_lang} 条外语已滤除`);

  return (
    <div className="flex items-center gap-3 px-4 py-3 sm:px-5">
      <XGlyph className="size-9 shrink-0 rounded-full" />
      <div className="min-w-0">
        <div className="truncate text-sm font-medium">
          {xFeedLabel(sub.channel_id, sub.name)}
          {/* the handle only earns its own chip once a real display name is known
              (learned from the first push) — otherwise it would render twice */}
          {sub.kind === 'user' && sub.name && (
            <span className="ml-1.5 text-xs text-muted-foreground">@{sub.channel_id}</span>
          )}
        </div>
        <div className="truncate text-xs text-muted-foreground">{parts.join(' · ')}</div>
      </div>
      <div className="ml-auto flex items-center gap-2">
        {/* For You only: language-filter the algorithm's picks — a followed account
            posting in another language was still chosen by the reader */}
        {sub.channel_id === X_FORYOU_FEED && sub.enabled && (
          <XLangFilterToggle feed={sub.channel_id} enabled={sub.lang_filter} />
        )}
        {/* only the synthetic feeds have a choice to make: a followed account is one
            you already picked, so it is always in the aggregate */}
        {isXSyntheticFeed(sub.channel_id) && sub.enabled && (
          <XAggregateMenu feed={sub.channel_id} mode={sub.aggregate} />
        )}
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
