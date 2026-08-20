import { ChevronDown, Globe } from 'lucide-react';

import { ChannelAvatar } from '@/components/ChannelAvatar';
import { HnGlyph } from '@/components/HnGlyph';
import { RssGlyph } from '@/components/RssGlyph';
import { SearchScopeOption } from '@/components/search/SearchScopeOption';
import { TgGlyph } from '@/components/TgGlyph';
import { XAvatar } from '@/components/XAvatar';
import { XGlyph } from '@/components/XGlyph';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import type { SearchScope } from '@/hooks/useSearch';
import { useSources } from '@/hooks/useSources';
import { isXSyntheticFeed, rssFeedLabel, sourceLabel, sourceSubLabel, subRowLabel } from '@/lib/sources';
import type { Source, SourceGroup, SourceSub } from '@/lib/types';

/** The glyph identifying a whole source, matching the sidebar's marks. */
export function sourceGlyph(source: Source, className = 'size-4 rounded-sm text-[9px]') {
  if (source === 'telegram') return <TgGlyph className={className} />;
  if (source === 'hn') return <HnGlyph className={className} />;
  if (source === 'rss') return <RssGlyph className={className} />;
  return <XGlyph className={className} />;
}

/** The glyph for one subscription row: the real avatar where there is an account
 *  behind it, the source's mark where there isn't (HN's feed, X's For You). */
function subGlyph(source: Source, sub: SourceSub) {
  if (source === 'telegram' && typeof sub.channel_id === 'number') {
    return <ChannelAvatar channelId={sub.channel_id} name={sourceSubLabel(sub)} className="size-4 text-[9px]" />;
  }
  if (source === 'x' && !isXSyntheticFeed(String(sub.channel_id))) {
    return <XAvatar handle={String(sub.channel_id)} name={sourceSubLabel(sub)} className="size-4 text-[9px]" />;
  }
  return sourceGlyph(source);
}

function scopeLabel(scope: SearchScope, groups: SourceGroup[] | undefined): string {
  if (!scope.source) return 'All sources';
  if (!scope.sub) return sourceLabel(scope.source);
  const sub = groups
    ?.find((g) => g.source === scope.source)
    ?.subscriptions.find((s) => String(s.channel_id) === scope.sub);
  // An RSS row's fallback is its URL, which is the key — trimmed to what tells two
  // feeds apart rather than printed whole into a menu trigger.
  if (scope.source === 'rss') return rssFeedLabel(scope.sub, sub?.name);
  return sub ? sourceSubLabel(sub) : scope.sub;
}

interface SearchScopeMenuProps {
  scope: SearchScope;
  onChange: (scope: SearchScope) => void;
}

/**
 * Where to search: everything, one source, or one subscription inside it.
 *
 * Two levels in a single flat menu rather than nested submenus — the whole list
 * is a handful of rows, and a submenu would hide the one channel the reader is
 * reaching for behind a hover. Its data is `GET /api/sources`, the same tree the
 * sidebar draws, so a paused subscription is offered here too: search reads the
 * archive, and pausing a channel does not unread what it already collected.
 */
export function SearchScopeMenu({ scope, onChange }: SearchScopeMenuProps) {
  const { data: groups } = useSources();
  const active = (s: SearchScope) =>
    (s.source ?? null) === (scope.source ?? null) && (s.sub ?? null) === (scope.sub ?? null);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="h-8 gap-1.5 px-2 text-xs" title="Limit the search to one source">
          {scope.source ? sourceGlyph(scope.source) : <Globe className="size-3.5 text-muted-foreground" />}
          <span className="max-w-40 truncate">{scopeLabel(scope, groups)}</span>
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="max-h-[70vh] w-60 overflow-y-auto">
        <SearchScopeOption
          label="All sources"
          icon={<Globe className="size-4" />}
          active={active({})}
          onSelect={() => onChange({})}
        />
        {(groups ?? []).map((group) => (
          <div key={group.source}>
            <DropdownMenuSeparator />
            <SearchScopeOption
              label={sourceLabel(group.source)}
              icon={sourceGlyph(group.source)}
              active={active({ source: group.source })}
              onSelect={() => onChange({ source: group.source })}
            />
            {group.subscriptions.map((sub) => (
              <SearchScopeOption
                key={String(sub.channel_id)}
                label={subRowLabel(group.source, sub)}
                icon={subGlyph(group.source, sub)}
                indent
                active={active({ source: group.source, sub: String(sub.channel_id) })}
                onSelect={() => onChange({ source: group.source, sub: String(sub.channel_id) })}
              />
            ))}
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
