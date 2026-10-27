/**
 * Renders `text` with the given hit ranges wrapped in <mark>. The ranges come from the
 * server's matcher as `[start, end)` code-point offsets, so this never re-implements
 * matching: JS and Python disagree on Unicode classes, and a second matcher here would
 * mark words the rule does not hide. Slicing goes through `Array.from` because
 * `String.slice` counts UTF-16 units and an emoji before a hit would shift the mark.
 */
export function HighlightedText({ text, ranges }: { text: string; ranges: [number, number][] }) {
  const chars = Array.from(text);
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  for (const [start, end] of ranges) {
    // The server sends sorted, disjoint ranges; clamping just keeps a bad one from repeating text.
    const from = Math.max(start, cursor);
    const to = Math.min(end, chars.length);
    if (to <= from) continue;
    if (from > cursor) parts.push(<span key={key++}>{chars.slice(cursor, from).join('')}</span>);
    parts.push(
      <mark key={key++} className="rounded bg-amber-300/60 px-0.5 text-foreground dark:bg-amber-500/40">
        {chars.slice(from, to).join('')}
      </mark>,
    );
    cursor = to;
  }
  if (cursor < chars.length) parts.push(<span key={key++}>{chars.slice(cursor).join('')}</span>);
  // `overflow-wrap: anywhere` breaks long URLs that `break-words` won't.
  return <span className="block [overflow-wrap:anywhere]">{parts}</span>;
}
