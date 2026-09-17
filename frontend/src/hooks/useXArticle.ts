import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

/** A long-form tweet with its article body, fetched when the detail pane opens it.
 *
 * `useRssArticle`'s sibling, with one difference in the clock: an RSS entry's body
 * is there from the moment the entry is, but an X article's can arrive later — the
 * probe reads it with the tweet, and a read that failed is retried next round — so
 * an answer *without* a body is only true for now and must not be cached forever.
 * An answer with one is final (a published tweet does not change under us). Pass
 * null to keep it idle.
 */
export function useXArticle(id: string | null) {
  return useQuery({
    queryKey: ['x-article', id],
    queryFn: () => api.xTweet(id!),
    enabled: id !== null,
    staleTime: (query) => (query.state.data?.x?.article?.content_html ? Infinity : 0),
  });
}
