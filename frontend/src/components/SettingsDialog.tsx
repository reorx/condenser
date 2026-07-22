import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Circle, Lock, LogOut, Minus, Monitor, Moon, Phone, Sun } from 'lucide-react';
import { toast } from 'sonner';

import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DeviceList } from '@/components/DeviceList';
import { SegmentedOption } from '@/components/SegmentedOption';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useAppMeta, useSetForwardChannel } from '@/hooks/useAppMeta';
import { useTgStatus } from '@/hooks/useTgStatus';
import { api } from '@/lib/api';
import { queryClient, TG_STATUS_KEY } from '@/lib/queryClient';
import { type Theme, useTheme } from '@/lib/theme';
import { type UnreadIndicatorMode, useUnreadIndicator } from '@/lib/unreadIndicator';

const THEME_OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
];

const UNREAD_OPTIONS: { value: UnreadIndicatorMode; label: string; icon: typeof Circle }[] = [
  { value: 'divider', label: 'Divider', icon: Minus },
  { value: 'dot', label: 'Dot', icon: Circle },
];

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-xs font-medium tracking-wide text-muted-foreground/70 uppercase">{children}</div>;
}

export function SettingsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { data: status } = useTgStatus();
  const { theme, setTheme } = useTheme();
  const { mode: unreadMode, setMode: setUnreadMode } = useUnreadIndicator();
  const [confirmTgLogout, setConfirmTgLogout] = useState(false);

  const meta = useAppMeta();
  const setForward = useSetForwardChannel();
  const [forwardChannel, setForwardChannel] = useState('');
  // Sync the input from the server value on load and on every reopen (drops unsaved edits).
  useEffect(() => {
    setForwardChannel(meta.data?.forward_channel ?? '');
  }, [meta.data?.forward_channel, open]);
  const forwardDirty = forwardChannel.trim() !== (meta.data?.forward_channel ?? '');

  const tgLogout = useMutation({
    mutationFn: () => api.tgLogout(),
    onSuccess: () => {
      setConfirmTgLogout(false);
      onOpenChange(false);
      queryClient.invalidateQueries({ queryKey: TG_STATUS_KEY });
    },
  });

  const appLock = useMutation({
    mutationFn: () => api.logout(),
    onSuccess: () => {
      onOpenChange(false);
      queryClient.invalidateQueries({ queryKey: TG_STATUS_KEY });
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>Telegram account and appearance.</DialogDescription>
        </DialogHeader>

        <div className="space-y-2.5">
          <SectionLabel>Telegram</SectionLabel>
          <div className="flex items-center gap-2 text-sm">
            <Phone className="size-4 text-muted-foreground" />
            <span>{status?.phone ?? 'Connected'}</span>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="w-full justify-start text-destructive hover:text-destructive"
            onClick={() => setConfirmTgLogout(true)}
          >
            <LogOut className="size-4" />
            Disconnect Telegram
          </Button>
        </div>

        <div className="space-y-2">
          <SectionLabel>Appearance</SectionLabel>
          <div className="grid grid-cols-3 gap-1.5">
            {THEME_OPTIONS.map((opt) => (
              <SegmentedOption
                key={opt.value}
                icon={opt.icon}
                label={opt.label}
                active={theme === opt.value}
                onClick={() => setTheme(opt.value)}
              />
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <SectionLabel>Unread</SectionLabel>
          <div className="grid grid-cols-2 gap-1.5">
            {UNREAD_OPTIONS.map((opt) => (
              <SegmentedOption
                key={opt.value}
                icon={opt.icon}
                label={opt.label}
                active={unreadMode === opt.value}
                onClick={() => setUnreadMode(opt.value)}
              />
            ))}
          </div>
        </div>

        <div className="space-y-2">
          <SectionLabel>Forward</SectionLabel>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setForward.mutate(forwardChannel.trim(), {
                onSuccess: () => toast.success('Forward channel saved'),
              });
            }}
          >
            <Input
              value={forwardChannel}
              onChange={(e) => setForwardChannel(e.target.value)}
              placeholder="@channel or t.me/… (empty to clear)"
            />
            <Button type="submit" variant="outline" disabled={!forwardDirty || setForward.isPending}>
              Save
            </Button>
          </form>
          <p className="text-xs text-muted-foreground">Target channel for "forward to my channel".</p>
        </div>

        <div className="space-y-2">
          <SectionLabel>Devices</SectionLabel>
          <DeviceList />
        </div>

        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start text-muted-foreground"
          onClick={() => appLock.mutate()}
        >
          <Lock className="size-4" />
          Lock app
        </Button>

        <ConfirmDialog
          open={confirmTgLogout}
          onOpenChange={setConfirmTgLogout}
          title="Disconnect Telegram?"
          description="This logs out your Telegram session — you'll sign in again with a code to read channels. Saved items remain."
          destructive
          confirmLabel="Disconnect"
          pending={tgLogout.isPending}
          onConfirm={() => tgLogout.mutate()}
        />
      </DialogContent>
    </Dialog>
  );
}
