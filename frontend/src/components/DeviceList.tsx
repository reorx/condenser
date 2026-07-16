import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { formatDistanceToNow } from 'date-fns';
import { Smartphone, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { ConfirmDialog } from '@/components/ConfirmDialog';
import { Spinner } from '@/components/Spinner';
import { Button } from '@/components/ui/button';
import { api, errorMessage } from '@/lib/api';
import { parseDate } from '@/lib/format';
import { queryClient } from '@/lib/queryClient';
import type { Device } from '@/lib/types';

function lastSeenLabel(device: Device): string {
  const d = parseDate(device.last_seen_at);
  return d ? `Active ${formatDistanceToNow(d, { addSuffix: true })}` : 'Never used';
}

function DeviceRow({ device, onRevoke }: { device: Device; onRevoke: (device: Device) => void }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <Smartphone className="size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="truncate">{device.name}</div>
        <div className="text-xs text-muted-foreground">{lastSeenLabel(device)}</div>
      </div>
      <Button
        variant="ghost"
        size="icon"
        className="size-7 text-muted-foreground hover:text-destructive"
        title="Revoke device"
        onClick={() => onRevoke(device)}
      >
        <Trash2 className="size-4" />
      </Button>
    </div>
  );
}

/** Authorized devices (bearer-token clients) with revocation; shown in SettingsDialog. */
export function DeviceList() {
  const [revoking, setRevoking] = useState<Device | null>(null);
  const devices = useQuery({ queryKey: ['devices'], queryFn: api.listDevices });

  const revoke = useMutation({
    mutationFn: (device: Device) => api.deleteDevice(device.id),
    onSuccess: () => {
      setRevoking(null);
      queryClient.invalidateQueries({ queryKey: ['devices'] });
    },
    onError: (e) => toast.error(errorMessage(e, 'Failed to revoke device')),
  });

  if (devices.isPending) return <Spinner />;
  if (devices.isError || devices.data.length === 0) {
    return <p className="text-sm text-muted-foreground">No authorized devices.</p>;
  }

  return (
    <div className="space-y-2">
      {devices.data.map((d) => (
        <DeviceRow key={d.id} device={d} onRevoke={setRevoking} />
      ))}
      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(o) => !o && setRevoking(null)}
        title={`Revoke ${revoking?.name ?? 'device'}?`}
        description="The device's token stops working immediately; it will need to authorize again."
        destructive
        confirmLabel="Revoke"
        pending={revoke.isPending}
        onConfirm={() => revoking && revoke.mutate(revoking)}
      />
    </div>
  );
}
