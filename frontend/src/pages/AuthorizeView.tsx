import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { Smartphone } from 'lucide-react';

import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { api, errorMessage } from '@/lib/api';

const CALLBACK = 'condenser://auth';

/**
 * Device-authorization page, cold-loaded by the iOS app inside an
 * ASWebAuthenticationSession: /authorize?device_name=<name>. Sits behind the app
 * cookie gate (AppLogin shows first when locked); confirming mints a device bearer
 * token and hands it back to the app via the condenser:// callback.
 */
export function AuthorizeView() {
  const [params] = useSearchParams();
  const deviceName = params.get('device_name')?.trim() || 'Unnamed device';
  const [done, setDone] = useState(false);

  const authorize = useMutation({
    mutationFn: () => api.createDevice(deviceName),
    onSuccess: ({ token, name }) => {
      setDone(true);
      window.location.href = `${CALLBACK}?token=${encodeURIComponent(token)}&name=${encodeURIComponent(name)}`;
    },
  });

  const deny = () => {
    window.location.href = `${CALLBACK}?error=denied`;
  };

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm text-center">
        <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-muted">
          <Smartphone className="size-6 text-muted-foreground" />
        </div>
        <h1 className="text-xl font-semibold tracking-tight">Authorize device</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{deviceName}</span> is asking for access to your Condenser. It
          will be able to read your timeline and manage read/saved state.
        </p>
        {done ? (
          <p className="mt-6 text-sm text-muted-foreground">Device authorized — you can return to the app.</p>
        ) : (
          <div className="mt-6 space-y-2">
            <Button className="w-full" disabled={authorize.isPending} onClick={() => authorize.mutate()}>
              {authorize.isPending && <Spinner />}
              Authorize
            </Button>
            <Button variant="ghost" className="w-full" disabled={authorize.isPending} onClick={deny}>
              Cancel
            </Button>
            {authorize.isError && (
              <p className="text-sm text-destructive">{errorMessage(authorize.error, 'Authorization failed')}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
