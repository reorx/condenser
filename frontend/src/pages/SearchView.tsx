import { useEffect, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';

import { IconBadge, PageHeader } from '@/components/PageHeader';
import { SearchFilters } from '@/components/search/SearchFilters';
import { SearchResults } from '@/components/search/SearchResults';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { type SearchScope, useSearch } from '@/hooks/useSearch';
import { isSource } from '@/lib/sources';
import type { SearchSort, SearchStatus } from '@/lib/types';

/** Typing pause before a query is sent. Long enough that a word is finished,
 *  short enough that it still feels like it is answering as you type. */
const DEBOUNCE_MS = 300;

function isStatus(v: string | null): v is SearchStatus {
  return v === 'unread' || v === 'saved';
}

export function SearchView() {
  const [sp, setSp] = useSearchParams();
  const committed = sp.get('q') ?? '';
  // Each param is bound before it is narrowed: a type predicate only narrows a
  // *reference*, so `isSource(sp.get('source')) ? sp.get('source') : …` type-checks
  // as `string | null` and fails the build.
  const rawSource = sp.get('source');
  const rawStatus = sp.get('status');
  const scope: SearchScope = { source: isSource(rawSource) ? rawSource : null, sub: sp.get('sub') };
  const status: SearchStatus | null = isStatus(rawStatus) ? rawStatus : null;
  const sort: SearchSort = sp.get('sort') === 'relevance' ? 'relevance' : 'recent';

  // The box is local state; the URL is the committed query. Keeping them apart is
  // what lets typing stay instant while history gets one entry per search rather
  // than one per keystroke — and `replace` means Back leaves the page, not the word.
  const [draft, setDraft] = useState(committed);
  // A `q` that changed without us typing (a link into /search, history restore) is
  // an instruction, not a stale draft: adopt it, or the debounce below would write
  // the old word back 300ms later and silently undo the navigation.
  const typed = useRef(committed);
  useEffect(() => {
    if (committed !== typed.current) {
      typed.current = committed;
      setDraft(committed);
    }
  }, [committed]);
  useEffect(() => {
    if (draft === committed) return;
    const timer = setTimeout(() => {
      typed.current = draft;
      patch((p) => (draft ? p.set('q', draft) : p.delete('q')));
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft, committed]);

  const query = useSearch({ q: committed, ...scope, status, sort });
  const total = query.data?.pages[0]?.total ?? 0;

  function patch(mutate: (p: URLSearchParams) => void) {
    setSp(
      (prev) => {
        const next = new URLSearchParams(prev);
        mutate(next);
        return next;
      },
      { replace: true },
    );
  }

  function setScope(next: SearchScope) {
    patch((p) => {
      next.source ? p.set('source', next.source) : p.delete('source');
      next.sub ? p.set('sub', next.sub) : p.delete('sub');
    });
  }

  return (
    <>
      <PageHeader
        icon={<IconBadge icon={<Search className="size-5" />} />}
        title="Search"
        meta={committed && query.isSuccess ? `${total.toLocaleString()} result${total === 1 ? '' : 's'}` : undefined}
      />

      <div className="relative border-b px-3 py-2 sm:px-4">
        <Search className="pointer-events-none absolute top-1/2 left-6 size-4 -translate-y-1/2 text-muted-foreground sm:left-7" />
        <Input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Search everything you've archived…"
          aria-label="Search"
          className="h-10 pr-9 pl-9"
        />
        {draft && (
          <Button
            variant="ghost"
            size="icon"
            className="absolute top-1/2 right-5 size-7 -translate-y-1/2 text-muted-foreground sm:right-6"
            onClick={() => setDraft('')}
            aria-label="Clear search"
          >
            <X className="size-4" />
          </Button>
        )}
      </div>

      <SearchFilters
        scope={scope}
        status={status}
        sort={sort}
        onScope={setScope}
        onStatus={(s) => patch((p) => (s ? p.set('status', s) : p.delete('status')))}
        onSort={(s) => patch((p) => (s === 'recent' ? p.delete('sort') : p.set('sort', s)))}
      />

      {committed ? (
        <SearchResults query={query} />
      ) : (
        <div className="flex flex-col items-center gap-2 py-24 text-center text-muted-foreground">
          <Search className="size-8" />
          <p className="text-sm">
            Search across Telegram, Hacker News and X — including what the timeline no longer shows.
          </p>
        </div>
      )}
    </>
  );
}
