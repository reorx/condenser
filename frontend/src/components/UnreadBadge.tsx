/** Right-aligned pill showing an unread count; renders nothing when the count is 0. */
export function UnreadBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="ml-auto rounded-full bg-muted px-1.5 text-[11px] tabular-nums text-muted-foreground">
      {count > 999 ? '999+' : count}
    </span>
  );
}
