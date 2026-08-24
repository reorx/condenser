import { useState } from 'react';
import { ExternalLink, Repeat2, Trash2 } from 'lucide-react';

import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DatedItemRow } from '@/components/timeline/DatedItemRow';
import { useDeleteForward } from '@/hooks/useForwards';
import { fullDateLabel } from '@/lib/format';
import type { ForwardRecordEntry } from '@/lib/types';

/**
 * 一条转发记录：**这次转发的元信息在上，被转发的条目在下**。
 *
 * 评论是「记录」的属性，不是「条目」的属性 —— 同一篇文章可以被转两次、写两段不同的话 ——
 * 所以它画在条目外面，而不是塞进卡片里。上半部分是我做的事，下半部分是我读的东西。
 *
 * `item` 为 null 时只渲染上半部分：那是一条转发时源表里就没有行的记录（TG 原生转发不读
 * 归档），评论和链接仍然在，而那才是记录的主体。
 */
export function ForwardRecordRow({ entry }: { entry: ForwardRecordEntry }) {
  const { record, item } = entry;
  const [confirmOpen, setConfirmOpen] = useState(false);
  const remove = useDeleteForward();

  return (
    <div className="py-1">
      <div className="flex items-start gap-2 px-4 pt-2 sm:px-5">
        <Repeat2 className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 text-[11px] text-muted-foreground/80">
            <time>{fullDateLabel(record.created_at)}</time>
            <span aria-hidden>·</span>
            {/* 转发当时配置的频道 —— 目标改过之后，旧记录仍然指着它真正去过的地方。 */}
            <span>{record.target}</span>
          </div>
          {record.comment ? (
            <p className="mt-1 text-sm leading-relaxed whitespace-pre-wrap break-words text-foreground/90">
              {record.comment}
            </p>
          ) : (
            <p className="mt-1 text-sm text-muted-foreground/70 italic">原样转发，没有写评论</p>
          )}
        </div>
        <a
          href={record.link}
          target="_blank"
          rel="noreferrer"
          title="在 Telegram 里打开这条消息"
          aria-label="在 Telegram 里打开这条消息"
          className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <ExternalLink className="size-4" />
        </a>
        <button
          type="button"
          onClick={() => setConfirmOpen(true)}
          title="删除这条记录"
          aria-label="删除这条记录"
          className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-destructive"
        >
          <Trash2 className="size-4" />
        </button>
      </div>

      {item ? (
        <DatedItemRow item={item} />
      ) : (
        <p className="px-4 py-3 text-xs text-muted-foreground/70 sm:px-5">转发时没有留下条目快照，只保留了这条记录。</p>
      )}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="删除转发记录？"
        description="只删除本地这条记录，频道里已经发出去的那条消息不会被撤回。"
        confirmLabel="删除记录"
        destructive
        pending={remove.isPending}
        onConfirm={() => {
          remove.mutate(record.id, { onSettled: () => setConfirmOpen(false) });
        }}
      />
    </div>
  );
}
