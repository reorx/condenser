import { useInfiniteQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { SearchPage, SearchSort, SearchStatus, Source } from '@/lib/types';

export const SEARCH_PAGE_SIZE = 20;

/**
 * The search scope as the URL carries it: a source and, optionally, one of its
 * subscriptions. Two fields rather than the API's three (`source` /
 * `channel_id` / `feed`) because the picker is built from `GET /api/sources`,
 * where a subscription is just "a row under a source" whatever its id type is.
 */
export interface SearchScope {
  source?: Source | null;
  /** A TG channel id, an X feed key or an RSS feed URL, as a string; null = the whole source. */
  sub?: string | null;
}

export interface SearchQueryParams extends SearchScope {
  q: string;
  status?: SearchStatus | null;
  sort?: SearchSort;
}

/** Scope -> the API's own parameters. HN has a single feed, so its subscription
 *  row adds nothing the source filter does not already say. A `feed` always travels
 *  with its source: the two feed-keyed sources key on different things (an X handle,
 *  an RSS feed URL), so the server cannot read one without the other. */
export function scopeParams(scope: SearchScope) {
  const { source, sub } = scope;
  if (!sub || !source) return { source: source ?? null, channel_id: null, feed: null };
  if (source === 'telegram') return { source, channel_id: Number(sub), feed: null };
  if (source === 'x' || source === 'rss') return { source, channel_id: null, feed: sub };
  return { source, channel_id: null, feed: null };
}

/**
 * The search results, paged by offset. Idle until the query has content: an
 * empty box must not fire a request per keystroke of deleting, and the view
 * shows a prompt rather than "no results" for a question nobody asked.
 */
export function useSearch({ q, source, sub, status, sort = 'recent' }: SearchQueryParams) {
  const query = q.trim();
  return useInfiniteQuery({
    queryKey: ['search', { q: query, source: source ?? null, sub: sub ?? null, status: status ?? null, sort }],
    queryFn: ({ pageParam }) =>
      api.search({
        q: query,
        ...scopeParams({ source, sub }),
        status,
        sort,
        offset: pageParam,
        limit: SEARCH_PAGE_SIZE,
      }),
    initialPageParam: 0,
    // Every page but the last is full, so the count of loaded pages *is* the offset.
    getNextPageParam: (last: SearchPage, pages) => (last.has_more ? pages.length * SEARCH_PAGE_SIZE : undefined),
    enabled: query.length > 0,
  });
}

export type SearchQuery = ReturnType<typeof useSearch>;
