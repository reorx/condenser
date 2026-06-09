import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { ArrowRight } from 'lucide-react';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { api, ApiError } from '@/lib/api';
import { queryClient, TG_STATUS_KEY } from '@/lib/queryClient';
import type { TgStatus } from '@/lib/types';

function setStatus(status: TgStatus) {
  queryClient.setQueryData(TG_STATUS_KEY, { status });
}

function errMsg(error: unknown): string | null {
  if (error instanceof ApiError) return error.message;
  if (error) return 'Something went wrong';
  return null;
}

const STEP_META: Record<Exclude<TgStatus, 'authorized'>, { title: string; hint: string }> = {
  unauthorized: { title: 'Connect Telegram', hint: 'Sign in with your Telegram account to start reading.' },
  awaiting_code: { title: 'Enter the code', hint: 'Telegram sent a login code to your app or SMS.' },
  awaiting_2fa: { title: 'Two-step password', hint: 'Your account is protected with a 2FA password.' },
};

export function TgLogin({ status }: { status: Exclude<TgStatus, 'authorized'> }) {
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');

  const sendCode = useMutation({
    mutationFn: () => api.tgSendCode(phone.trim()),
    onSuccess: (r) => setStatus(r.status),
  });
  const signIn = useMutation({
    mutationFn: () => api.tgSignIn(code.trim()),
    onSuccess: (r) => setStatus(r.status),
  });
  const signIn2fa = useMutation({
    mutationFn: () => api.tgSignIn2fa(password),
    onSuccess: (r) => setStatus(r.status),
  });

  const meta = STEP_META[status];
  const busy = sendCode.isPending || signIn.isPending || signIn2fa.isPending;

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <h1 className="text-xl font-semibold tracking-tight">{meta.title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{meta.hint}</p>
        </div>

        {status === 'unauthorized' && (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (phone.trim()) sendCode.mutate();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="phone">Phone number</Label>
              <Input
                id="phone"
                autoFocus
                inputMode="tel"
                placeholder="+1 555 123 4567"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                aria-invalid={!!sendCode.error}
              />
            </div>
            {errMsg(sendCode.error) && <p className="text-sm text-destructive">{errMsg(sendCode.error)}</p>}
            <Button type="submit" className="w-full" disabled={!phone.trim() || busy}>
              {sendCode.isPending ? <Spinner /> : <ArrowRight />}
              Send code
            </Button>
          </form>
        )}

        {status === 'awaiting_code' && (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (code.trim()) signIn.mutate();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="code">Login code</Label>
              <Input
                id="code"
                autoFocus
                inputMode="numeric"
                autoComplete="one-time-code"
                placeholder="12345"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                aria-invalid={!!signIn.error}
              />
            </div>
            {errMsg(signIn.error) && <p className="text-sm text-destructive">{errMsg(signIn.error)}</p>}
            <Button type="submit" className="w-full" disabled={!code.trim() || busy}>
              {signIn.isPending && <Spinner />}
              Verify
            </Button>
          </form>
        )}

        {status === 'awaiting_2fa' && (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (password) signIn2fa.mutate();
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="tfa">2FA password</Label>
              <Input
                id="tfa"
                type="password"
                autoFocus
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-invalid={!!signIn2fa.error}
              />
            </div>
            {errMsg(signIn2fa.error) && <p className="text-sm text-destructive">{errMsg(signIn2fa.error)}</p>}
            <Button type="submit" className="w-full" disabled={!password || busy}>
              {signIn2fa.isPending && <Spinner />}
              Sign in
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
