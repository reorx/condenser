// Ports the CondenserKit AnnotationsTests cases: the two clients must agree on
// where a stored quote lands, or a highlight made on one platform drifts on the
// other. Same fixtures, same expectations (ios/CondenserKit/Tests/.../AnnotationsTests.swift).
import { describe, expect, it } from 'vitest';

import { hasNotes, locateAnnotation, selectionContext } from './annotate';
import type { ItemAnnotation, TimelineItem } from './types';

function ann(partial: Partial<ItemAnnotation> & { quote: string }): ItemAnnotation {
  return { id: 1, prefix: '', suffix: '', block: null, comment: null, created_at: null, ...partial };
}

describe('locateAnnotation', () => {
  it('finds a unique exact occurrence', () => {
    const loc = locateAnnotation(ann({ quote: 'brown fox' }), ['the quick brown fox jumps']);
    expect(loc).toEqual({ block: 0, start: 10, end: 19 });
  });

  it('disambiguates repeated occurrences by prefix/suffix context', () => {
    const text = 'good code. bad code. good code again.';
    const loc = locateAnnotation(ann({ quote: 'code', prefix: 'bad ', suffix: '. good' }), [text]);
    expect(loc).toEqual({ block: 0, start: 15, end: 19 });
  });

  it('picks the right block when the quote appears in several', () => {
    const blocks = ['alpha shared beta', 'gamma shared delta'];
    const loc = locateAnnotation(ann({ quote: 'shared', prefix: 'gamma ', suffix: ' delta' }), blocks);
    expect(loc?.block).toBe(1);
  });

  it('survives whitespace drift via folded matching', () => {
    // The stored quote has a single space where the rendered text broke the line.
    const loc = locateAnnotation(ann({ quote: 'two words' }), ['before two\n  words after']);
    expect(loc).toEqual({ block: 0, start: 7, end: 18 });
  });

  it('returns null for an orphan (quote no longer in the text)', () => {
    expect(locateAnnotation(ann({ quote: 'vanished' }), ['nothing to see'])).toBeNull();
  });

  it('falls back to full-text search when the block hint is stale', () => {
    const loc = locateAnnotation(ann({ quote: 'needle', block: 7 }), ['hay', 'needle hay']);
    expect(loc).toEqual({ block: 1, start: 0, end: 6 });
  });

  it('lets the block hint break a tie between equal context scores', () => {
    const blocks = ['same text here', 'same text here'];
    const loc = locateAnnotation(ann({ quote: 'same text', block: 1 }), blocks);
    expect(loc?.block).toBe(1);
  });

  it('never lets the block hint outvote the context', () => {
    // Context clearly points at block 0; a stale hint at block 1 must not flip it.
    const blocks = ['alpha shared beta', 'gamma shared delta'];
    const loc = locateAnnotation(ann({ quote: 'shared', prefix: 'alpha ', suffix: ' beta', block: 1 }), blocks);
    expect(loc?.block).toBe(0);
  });

  it('handles empty quotes and empty blocks without ranging out', () => {
    expect(locateAnnotation(ann({ quote: '   ' }), ['text'])).toBeNull();
    expect(locateAnnotation(ann({ quote: 'q' }), [])).toBeNull();
    expect(locateAnnotation(ann({ quote: 'q' }), [''])).toBeNull();
  });
});

describe('selectionContext', () => {
  it('takes ~30 chars of prefix and suffix around the quote', () => {
    const text = 'a'.repeat(50) + 'QUOTE' + 'b'.repeat(50);
    const ctx = selectionContext(text, 50, 55);
    expect(ctx.quote).toBe('QUOTE');
    expect(ctx.prefix).toBe('a'.repeat(30));
    expect(ctx.suffix).toBe('b'.repeat(30));
  });

  it('clamps at the text edges', () => {
    const ctx = selectionContext('abc QUOTE xyz', 4, 9);
    expect(ctx).toEqual({ quote: 'QUOTE', prefix: 'abc ', suffix: ' xyz' });
  });

  it('does not split a surrogate pair at a context edge', () => {
    // The emoji occupies UTF-16 units 21–22; the quote starts at 52, so the naive
    // 30-unit window would start at 22 — the low surrogate.
    const emoji = '😀'; // 2 UTF-16 code units
    const text = 'x'.repeat(21) + emoji + 'y'.repeat(29) + 'QUOTE';
    const ctx = selectionContext(text, 52, 57);
    expect(ctx.quote).toBe('QUOTE');
    // The edge is aligned to a whole code point: the prefix never opens on a lone
    // low surrogate.
    const first = ctx.prefix.charCodeAt(0);
    expect(first >= 0xdc00 && first <= 0xdfff).toBe(false);
  });
});

describe('hasNotes', () => {
  const base = { source: 'rss', key: 'rss:1', datetime: '2026-01-01T00:00:00Z', is_read: false, is_saved: false };
  it('is true for a note or a highlight, false otherwise', () => {
    expect(hasNotes({ ...base, note: 'hi' } as TimelineItem)).toBe(true);
    expect(hasNotes({ ...base, annotations: [ann({ quote: 'q' })] } as TimelineItem)).toBe(true);
    expect(hasNotes({ ...base, note: '', annotations: [] } as TimelineItem)).toBe(false);
    expect(hasNotes({ ...base } as TimelineItem)).toBe(false);
  });
});
