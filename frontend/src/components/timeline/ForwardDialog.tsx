import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { api, errorMessage } from '@/lib/api';
import { patchItem } from '@/lib/itemCaches';
import type { TimelineItem } from '@/lib/types';

interface ForwardDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  item: TimelineItem;
}

/** 转发到 app_meta.forward_channel 配置的频道。Telegram 条目：评论非空 → 文字 + t.me 链接
 *  的新消息，留空 → 原生 forward。其他信源没有「原生转发」这回事，服务端把标题和链接渲染成
 *  一条新消息，留空就是只发这条，不加评论。 */
export function ForwardDialog({ open, onOpenChange, item }: ForwardDialogProps) {
  const [comment, setComment] = useState('');
  const isTelegram = item.source === 'telegram';
  const qc = useQueryClient();

  const forward = useMutation({
    mutationFn: () => api.forwardItem(item.key, comment.trim() || undefined),
    onSuccess: (res) => {
      setComment('');
      onOpenChange(false);
      // 服务端已经落了一行记录（schema v17）：角标立刻亮，转发列表下次打开是新的。
      // 这个 patch 只会把 false 改成 true，所以不需要回滚 —— 发送已经成功了。
      patchItem(qc, item.key, { forwarded_by_me: true });
      void qc.invalidateQueries({ queryKey: ['forwards'] });
      toast.success(res.mode === 'quote' ? '已发布带评论的新消息' : '已转发到你的频道', {
        action: { label: '打开', onClick: () => window.open(res.link, '_blank') },
      });
    },
    onError: (e) => toast.error(errorMessage(e, '转发失败')),
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setComment('');
          forward.reset();
        }
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>转发到我的频道</DialogTitle>
          <DialogDescription>
            {isTelegram
              ? '写上自己的看法会通过文字 + 链接引用的形式发布新消息。'
              : '写上自己的看法会和标题、链接一起发布成一条新消息。'}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder={isTelegram ? '留空则原样转发…' : '留空则只发标题和链接…'}
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={forward.isPending}>
              取消
            </Button>
            <Button onClick={() => forward.mutate()} disabled={forward.isPending}>
              {forward.isPending ? <Spinner /> : '确认转发'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
