import { useEffect, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Circle, Lock, LogIn, LogOut, Minus, Monitor, Moon, Phone, Puzzle, Sun } from 'lucide-react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { ConfirmDialog } from '@/components/ConfirmDialog';
import { DeviceList } from '@/components/DeviceList';
import { LanguageOption } from '@/components/LanguageOption';
import { SegmentedOption } from '@/components/SegmentedOption';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { useAppMeta, useSetForwardChannel, useSetLanguages } from '@/hooks/useAppMeta';
import { useTgStatus } from '@/hooks/useTgStatus';
import { useVibeReader } from '@/hooks/useVibeReader';
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

/** Offered languages (primary subtags). The backend accepts any 2-3 letter code,
 *  so growing this list is a constant edit, not a schema change. */
const LANGUAGE_OPTIONS: { value: string; label: string }[] = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
];

/** The one line that tells "no extension" from "extension, link off" from
 *  "extension at a protocol version we don't speak". */
function vibeReaderStatusText(s: { available: boolean; linked: boolean; version: number | null }): string {
  if (s.available) return s.linked ? '已连接 · 联动开启' : '已连接 · 联动关闭';
  if (s.version != null) return `已连接 · 协议版本不匹配 (v${s.version})`;
  return '未检测到扩展';
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-xs font-medium tracking-wide text-muted-foreground/70 uppercase">{children}</div>;
}

export function SettingsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { data: status } = useTgStatus();
  const tgConnected = status?.status === 'authorized';
  const { theme, setTheme } = useTheme();
  const { mode: unreadMode, setMode: setUnreadMode } = useUnreadIndicator();
  const [confirmTgLogout, setConfirmTgLogout] = useState(false);

  const vibe = useVibeReader();

  const meta = useAppMeta();
  const setForward = useSetForwardChannel();
  const setLanguages = useSetLanguages();
  const languages = meta.data?.languages ?? [];
  const toggleLanguage = (code: string) =>
    setLanguages.mutate(languages.includes(code) ? languages.filter((c) => c !== code) : [...languages, code]);
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
            <span>{tgConnected ? (status?.phone ?? 'Connected') : 'Not connected'}</span>
          </div>
          {/* Reachable only on a multi-source install: the gate no longer walls
              those off, so this is the one entry left to the Telegram login. */}
          {tgConnected ? (
            <Button
              variant="outline"
              size="sm"
              className="w-full justify-start text-destructive hover:text-destructive"
              onClick={() => setConfirmTgLogout(true)}
            >
              <LogOut className="size-4" />
              Disconnect Telegram
            </Button>
          ) : (
            <Button variant="outline" size="sm" className="w-full justify-start" asChild>
              <Link to="/connect-telegram" onClick={() => onOpenChange(false)}>
                <LogIn className="size-4" />
                Connect Telegram
              </Link>
            </Button>
          )}
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
          <SectionLabel>语言</SectionLabel>
          <div className="grid grid-cols-4 gap-1.5">
            {LANGUAGE_OPTIONS.map((opt) => (
              <LanguageOption
                key={opt.value}
                label={opt.label}
                selected={languages.includes(opt.value)}
                onToggle={() => toggleLanguage(opt.value)}
              />
            ))}
          </div>
          <p className="text-xs text-muted-foreground">全局语言偏好；X For You 开启「按语言过滤」后只保留所选语言。</p>
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
          <SectionLabel>Vibe Reader</SectionLabel>
          {/* The switch mirrors the extension's own; flipping it only *asks* (the
              answer comes back as vibe-reader:link), so no optimistic state here.
              Disabled without a bridge: there is nobody to ask. */}
          <div className="flex items-center gap-2 text-sm">
            <Puzzle className="size-4 text-muted-foreground" />
            <span className="flex-1">{vibeReaderStatusText(vibe)}</span>
            <Switch
              aria-label="Vibe Reader 联动"
              checked={vibe.linked}
              disabled={!vibe.available}
              onCheckedChange={(v) => vibe.setLink(v)}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            开启后，从这里点开的链接会在 Vibe Reader 侧栏自动生成摘要。开关的状态由扩展保存。
          </p>
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
