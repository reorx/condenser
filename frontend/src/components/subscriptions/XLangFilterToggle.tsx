import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Languages } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { useAppMeta } from '@/hooks/useAppMeta';
import { api, errorMessage } from '@/lib/api';
import { cn } from '@/lib/utils';

/** PATCH For You's `config.lang_filter` (the global language list lives in Settings). */
export function useSetXLangFilter(feed: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (langFilter: boolean) => api.xSetConfig(feed, { lang_filter: langFilter }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['x-subscriptions'] }),
    onError: (e) => toast.error(errorMessage(e, '没能修改语言过滤开关')),
  });
}

/** For You's 「按全局语言过滤」 toggle, sitting beside `XAggregateMenu`.
 *
 *  The language list itself is a global preference (Settings → 语言); this switch
 *  only says "For You obeys it". Filtering happens at ingest — a tweet outside the
 *  list is never archived — so flipping it changes future pushes, not history.
 *  With the switch on but no languages picked the filter is inert (fail-open),
 *  which is why that state gets a visible hint instead of silently doing nothing. */
export function XLangFilterToggle({ feed, enabled }: { feed: string; enabled: boolean }) {
  const meta = useAppMeta();
  const setFilter = useSetXLangFilter(feed);
  const languages = meta.data?.languages ?? [];
  const needsLanguages = enabled && languages.length === 0;
  const title = enabled
    ? needsLanguages
      ? '按全局语言过滤：开 — 先在设置中选择语言，否则不过滤'
      : `按全局语言过滤：开（${languages.join(', ')}）`
    : '按全局语言过滤：关 — 外语推文照常进入';

  return (
    <Button
      variant="ghost"
      size="sm"
      className={cn(
        'h-8 gap-1 px-2 text-xs',
        enabled ? (needsLanguages ? 'text-amber-600 dark:text-amber-500' : 'text-foreground') : 'text-muted-foreground',
      )}
      disabled={setFilter.isPending}
      aria-pressed={enabled}
      title={title}
      onClick={() => setFilter.mutate(!enabled)}
    >
      <Languages className="size-3.5" />
      {enabled ? (needsLanguages ? '先在设置中选择语言' : '按语言过滤') : '语言过滤关'}
    </Button>
  );
}
