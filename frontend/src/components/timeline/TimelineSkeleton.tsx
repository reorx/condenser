function SkeletonRow() {
  return (
    <div className="px-4 py-3 sm:px-5">
      <div className="flex items-center gap-2">
        <div className="h-3 w-24 rounded bg-muted" />
        <div className="h-3 w-10 rounded bg-muted" />
      </div>
      <div className="mt-2 space-y-1.5">
        <div className="h-3 w-full rounded bg-muted" />
        <div className="h-3 w-4/5 rounded bg-muted" />
      </div>
    </div>
  );
}

export function TimelineSkeleton() {
  return (
    <div className="animate-pulse divide-y divide-border/50" aria-hidden>
      {Array.from({ length: 6 }).map((_, i) => (
        <SkeletonRow key={i} />
      ))}
    </div>
  );
}
