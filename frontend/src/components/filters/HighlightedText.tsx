/** Renders `text` with every case-insensitive occurrence of `pattern` wrapped in <mark>. */
export function HighlightedText({ text, pattern }: { text: string; pattern: string }) {
  if (!pattern) return <span>{text}</span>;
  const lowered = text.toLowerCase();
  const needle = pattern.toLowerCase();
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  while (cursor < text.length) {
    const hit = lowered.indexOf(needle, cursor);
    if (hit === -1) {
      parts.push(<span key={key++}>{text.slice(cursor)}</span>);
      break;
    }
    if (hit > cursor) parts.push(<span key={key++}>{text.slice(cursor, hit)}</span>);
    parts.push(
      <mark key={key++} className="rounded bg-amber-300/60 px-0.5 text-foreground dark:bg-amber-500/40">
        {text.slice(hit, hit + needle.length)}
      </mark>,
    );
    cursor = hit + needle.length;
  }
  // `overflow-wrap: anywhere` breaks long URLs that `break-words` won't.
  return <span className="block [overflow-wrap:anywhere]">{parts}</span>;
}
