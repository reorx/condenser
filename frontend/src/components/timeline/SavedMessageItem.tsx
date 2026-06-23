import { MessageCard } from '@/components/timeline/MessageCard';
import { channelName, fullDateLabel } from '@/lib/format';
import type { DisplayMessage } from '@/lib/types';

/** A saved message in the Saved view: a full date line above the message card. */
export function SavedMessageItem({ msg }: { msg: DisplayMessage }) {
  return (
    <div>
      <div className="px-4 pt-2 text-[11px] text-muted-foreground/70 sm:px-5">{fullDateLabel(msg.date)}</div>
      <MessageCard msg={msg} channelLabel={channelName(msg.channel)} />
    </div>
  );
}
