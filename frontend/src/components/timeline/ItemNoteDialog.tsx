import { useEffect, useState } from 'react';
import { Forward } from 'lucide-react';
import { toast } from 'sonner';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { useNote } from '@/hooks/useNote';
import { errorMessage } from '@/lib/api';
import type { TimelineItem } from '@/lib/types';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  item: TimelineItem;
  /** The note currently on the item (the pane's live view of it). */
  note: string;
  /** Mirror the saved value into the pane's local state. */
  onSaved: (note: string) => void;
  /** Chain into the forward dialog with the note prefilled — called only after
   *  the save landed. */
  onForward: (note: string) => void;
}

/**
 * 条目评论编辑框（iOS `ItemNoteSheet` 的对应物）。覆盖语义：每次保存整段文字，清空保存
 * 即删除 —— 没有单独的删除按钮。「保存并转发」先把评论落库、成功后才带着它打开转发弹窗：
 * 打了字只进了 Telegram 没进笔记的惊讶感必须避免（转发弹窗里再改只影响发出的消息）。
 */
export function ItemNoteDialog({ open, onOpenChange, item, note, onSaved, onForward }: Props) {
  const [text, setText] = useState('');
  const save = useNote();

  // Seed from the live note each time the dialog opens.
  useEffect(() => {
    if (open) setText(note);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const submit = (thenForward: boolean) => {
    const value = text.trim();
    save.mutate(
      { key: item.key, note: value },
      {
        onSuccess: () => {
          onSaved(value);
          if (thenForward) onForward(value);
          else onOpenChange(false);
        },
        // 错误按语义分：清空保存是在删除。
        onError: (e) => toast.error(errorMessage(e, value ? '保存失败，请重试' : '删除失败，请重试')),
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (save.isPending) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>条目评论</DialogTitle>
          <DialogDescription>写给自己的看法，保存在这条内容上。</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={note ? '清空保存 = 删除评论' : '对这条内容写点什么…'}
            autoFocus
            className="min-h-28"
          />
          <div className="flex items-center justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={save.isPending}>
              取消
            </Button>
            <Button
              variant="outline"
              onClick={() => submit(true)}
              // 空评论没有可预填的东西 —— 直接用转发按钮即可。
              disabled={save.isPending || !text.trim()}
              title="先保存评论，再带着它打开转发"
            >
              <Forward className="size-4" />
              保存并转发
            </Button>
            <Button onClick={() => submit(false)} disabled={save.isPending}>
              {save.isPending ? <Spinner /> : '保存'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
