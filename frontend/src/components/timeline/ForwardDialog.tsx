import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { api, errorMessage } from '@/lib/api';
import type { MsgRef } from '@/lib/types';

interface ForwardDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  msgRef: MsgRef;
}

/** 转发到 app_meta.forward_channel 配置的频道：评论非空 → 文字 + t.me 链接引用的新消息，
 *  留空 → 原生 forward。App 其余 UI 为英文，此处发布动作面向用户自己的中文频道，特意保留中文文案。 */
export function ForwardDialog({ open, onOpenChange, msgRef }: ForwardDialogProps) {
  const [comment, setComment] = useState('');

  const forward = useMutation({
    mutationFn: () => api.forwardMessage(msgRef.channel_id, msgRef.message_id, comment.trim() || undefined),
    onSuccess: (res) => {
      setComment('');
      onOpenChange(false);
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
          <DialogDescription>写上自己的看法会通过文字 + 链接引用的形式发布新消息。</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="留空则原样转发…"
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
