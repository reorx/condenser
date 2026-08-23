import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api';

/** A feed entry's article body, fetched only once the reader asks for it.
 *
 * The timeline carries a ~500-character excerpt per entry instead of the article
 * (13.9KB average in production, 7.1MB at the tail), so expanding one is a
 * request. Pass null to keep it idle — the card does that until "more" is clicked.
 *
 * Cached without a stale clock: a feed entry is a published document and does not
 * change under us, so collapsing and re-expanding must not re-fetch it.
 */
export function useRssArticle(id: number | null) {
  return useQuery({
    queryKey: ['rss-article', id],
    queryFn: () => api.rssEntry(id!),
    enabled: id !== null,
    staleTime: Infinity,
  });
}
