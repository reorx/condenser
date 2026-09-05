import { Loader2, Zap, ZapOff } from 'lucide-react';

import { useVibeReaderStatus, type VibeReaderStatusState } from '@/lib/vibeReader';

/**
 * 「Vibe Reader 对这条的深读进行到哪了」的角标（plan 2026-09-02 §5，Phase D），画在
 * 四张卡片的时间那一行，`ForwardedBadge` / `AnnotationBadge` 的第三个兄弟。
 *
 * 数据来自扩展经桥回传的 `vibe-reader:status`，按 URL 存在 `lib/vibeReader` 的 store 里：
 * 不落库、不进 React Query，刷新页面即丢，sidepanel 关掉（`bye`）即清。一张卡片给出它
 * 全部可点开的链接（HN 是文章 + 讨论两条），显示的是读者最后点过的那条的状态。
 *
 * 转圈 = 排队 / 提取 / 生成中；闪电 = 就绪（切到那个 tab 就有摘要）；闪电划掉 = 失败。
 * 只是记号不是按钮：结果在扩展的 sidepanel 里，这里点了也没处可去。提示文案用
 * native `title`，理由同 `ForwardedBadge`。
 */
export function VibeReaderBadge({ urls }: { urls: readonly string[] }) {
  const status = useVibeReaderStatus(urls);
  if (!status) return null;
  const label = describe(status.state, status.modes);
  const spinning = status.state === 'queued' || status.state === 'extracting' || status.state === 'generating';
  const Icon = spinning ? Loader2 : status.state === 'done' ? Zap : ZapOff;
  return (
    <span
      title={label}
      aria-label={label}
      className={
        status.state === 'done'
          ? 'inline-flex shrink-0 items-center text-violet-500/80 dark:text-violet-400/80'
          : status.state === 'error'
            ? 'inline-flex shrink-0 items-center text-rose-500/70 dark:text-rose-400/70'
            : 'inline-flex shrink-0 items-center text-muted-foreground/80'
      }
    >
      <Icon className={spinning ? 'size-3.5 animate-spin' : 'size-3.5'} />
    </span>
  );
}

function describe(state: VibeReaderStatusState, modes?: string[]): string {
  switch (state) {
    case 'queued':
      return 'Vibe Reader 排队中';
    case 'extracting':
      return 'Vibe Reader 正在提取正文';
    case 'generating':
      return 'Vibe Reader 正在生成';
    case 'done':
      return modes && modes.length > 0 ? `Vibe Reader 已就绪 · ${modes.join(', ')}` : 'Vibe Reader 已就绪';
    case 'error':
      return 'Vibe Reader 生成失败';
  }
}
