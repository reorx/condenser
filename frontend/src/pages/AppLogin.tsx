import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { api, ApiError } from '@/lib/api';
import { queryClient, TG_STATUS_KEY } from '@/lib/queryClient';

export function AppLogin() {
  const [password, setPassword] = useState('');

  const login = useMutation({
    mutationFn: () => api.login(password),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: TG_STATUS_KEY }),
  });

  const error =
    login.error instanceof ApiError
      ? login.error.status === 401
        ? 'Incorrect password'
        : login.error.message
      : login.error
        ? 'Something went wrong'
        : null;

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Condenser</h1>
          <p className="mt-1 text-sm text-muted-foreground">Your Telegram channels, one timeline.</p>
        </div>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (password) login.mutate();
          }}
        >
          <Input
            type="password"
            autoFocus
            autoComplete="current-password"
            placeholder="App password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!error}
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" className="w-full" disabled={!password || login.isPending}>
            {login.isPending && <Spinner />}
            Unlock
          </Button>
        </form>
      </div>
    </div>
  );
}
