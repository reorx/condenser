// Quote relocation for highlights (schema v18) — the web port of CondenserKit's
// Annotations.swift, kept behavior-identical so a highlight made on either client
// lands on the same characters on the other.
//
// Why quotes and not offsets: offsets anchor into sand. What is on screen is a
// *derived* text (linkified tweets, HTML stripped to prose, sanitized articles),
// and the derivation can change with any release — a stored offset silently drifts
// onto the wrong words, which is worse than failing. So the quote is the truth:
// relocation is a search for it, with `prefix`/`suffix` disambiguating repeated
// occurrences and whitespace folding absorbing the most common drift (line breaks
// and indentation moving around). No match at all = an orphan, surfaced in the
// detail pane's orphan section rather than silently dropped.

import type { ItemAnnotation, TimelineItem } from './types';

/** Where an annotation's quote sits in the rendered text: block index (0 for
 *  single-block sources) + UTF-16 offsets into that block's string. */
export interface AnnotationLocation {
  block: number;
  start: number;
  end: number;
}

/** How many UTF-16 units of context to store around a new highlight (iOS stores
 *  the same 30; the locate-time comparison window is wider — see CONTEXT_WINDOW). */
export const CONTEXT_CHARS = 30;

/** Locate-time context window: wider than what is stored, so a quote whose stored
 *  context was cut short still matches the front of a longer neighborhood. */
const CONTEXT_WINDOW = 80;

export function foldWhitespace(s: string): string {
  return s.replace(/\s+/g, ' ');
}

/** Every exact occurrence of `needle` in `hay`, advancing one unit at a time so
 *  self-overlapping matches are collected too (mirrors the Swift scan). */
function exactOccurrences(needle: string, hay: string): { start: number; end: number }[] {
  const out: { start: number; end: number }[] = [];
  let from = 0;
  for (;;) {
    const at = hay.indexOf(needle, from);
    if (at === -1) return out;
    out.push({ start: at, end: at + needle.length });
    from = at + 1;
  }
}

/** `hay` with runs of whitespace folded to single spaces, plus the maps back to
 *  the original offsets: `starts[i]`/`ends[i]` bracket folded unit i's source run. */
function fold(hay: string): { text: string; starts: number[]; ends: number[] } {
  let text = '';
  const starts: number[] = [];
  const ends: number[] = [];
  let i = 0;
  while (i < hay.length) {
    if (/\s/.test(hay[i])) {
      let j = i;
      while (j < hay.length && /\s/.test(hay[j])) j += 1;
      text += ' ';
      starts.push(i);
      ends.push(j);
      i = j;
    } else {
      text += hay[i];
      starts.push(i);
      ends.push(i + 1);
      i += 1;
    }
  }
  return { text, starts, ends };
}

/** Occurrences of the whitespace-folded `needle` in `hay`, mapped back to
 *  original-text offsets. The fallback for line-break/indentation drift. */
function foldedOccurrences(needle: string, hay: string): { start: number; end: number }[] {
  const foldedNeedle = foldWhitespace(needle);
  if (!foldedNeedle) return [];
  const folded = fold(hay);
  return exactOccurrences(foldedNeedle, folded.text).map((r) => ({
    start: folded.starts[r.start],
    end: folded.ends[r.end - 1],
  }));
}

function commonPrefixLength(a: string, b: string): number {
  const n = Math.min(a.length, b.length);
  let i = 0;
  while (i < n && a[i] === b[i]) i += 1;
  return i;
}

function commonSuffixLength(a: string, b: string): number {
  const n = Math.min(a.length, b.length);
  let i = 0;
  while (i < n && a[a.length - 1 - i] === b[b.length - 1 - i]) i += 1;
  return i;
}

/**
 * Find where an annotation's quote sits in the rendered text blocks (a
 * single-flow surface passes `[fullText]`). Null = orphan.
 *
 * Exact search first, folded fallback only on zero hits; a lone candidate wins
 * outright. Multiple candidates are scored by how much of the stored prefix
 * aligns backward / suffix forward against an 80-unit neighborhood — doubled, so
 * the `block` hint (+1) can only ever break a context tie, never overrule it.
 */
export function locateAnnotation(annotation: ItemAnnotation, blocks: string[]): AnnotationLocation | null {
  const quote = annotation.quote.trim();
  if (!quote || blocks.length === 0) return null;

  let candidates: AnnotationLocation[] = [];
  blocks.forEach((block, index) => {
    for (const r of exactOccurrences(quote, block)) candidates.push({ block: index, ...r });
  });
  if (candidates.length === 0) {
    blocks.forEach((block, index) => {
      for (const r of foldedOccurrences(quote, block)) candidates.push({ block: index, ...r });
    });
  }
  if (candidates.length === 0) return null;
  if (candidates.length === 1) return candidates[0];

  const prefix = foldWhitespace(annotation.prefix ?? '');
  const suffix = foldWhitespace(annotation.suffix ?? '');
  let best: AnnotationLocation | null = null;
  let bestScore = -1;
  for (const candidate of candidates) {
    const block = blocks[candidate.block];
    const before = foldWhitespace(block.slice(Math.max(0, candidate.start - CONTEXT_WINDOW), candidate.start));
    const after = foldWhitespace(block.slice(candidate.end, candidate.end + CONTEXT_WINDOW));
    let score = 2 * (commonSuffixLength(prefix, before) + commonPrefixLength(suffix, after));
    if (candidate.block === annotation.block) score += 1;
    if (score > bestScore) {
      bestScore = score;
      best = candidate;
    }
  }
  return best;
}

function isLowSurrogate(code: number): boolean {
  return code >= 0xdc00 && code <= 0xdfff;
}

/** Widen a UTF-16 offset outward so it never splits a surrogate pair. */
function alignBoundary(text: string, offset: number, direction: -1 | 1): number {
  let at = offset;
  while (at > 0 && at < text.length && isLowSurrogate(text.charCodeAt(at))) at += direction;
  return at;
}

/** The stored shape of a new highlight: the quote plus ~30 units of surrounding
 *  context, edges aligned to whole code points (iOS aligns to composed character
 *  sequences; a surrogate-safe cut is the part that matters for matching). */
export function selectionContext(
  text: string,
  start: number,
  end: number,
): { quote: string; prefix: string; suffix: string } {
  const prefixStart = alignBoundary(text, Math.max(0, start - CONTEXT_CHARS), -1);
  const suffixEnd = alignBoundary(text, Math.min(text.length, end + CONTEXT_CHARS), 1);
  return {
    quote: text.slice(start, end),
    prefix: text.slice(prefixStart, start),
    suffix: text.slice(end, suffixEnd),
  };
}

/** "The reader wrote on this item" — a note or at least one highlight. Drives the
 *  card badge and the v18 unsave semantics (mirror of Kit's `TimelineItem.hasNotes`). */
export function hasNotes(item: TimelineItem): boolean {
  if (item.note) return true;
  return (item.annotations?.length ?? 0) > 0;
}
