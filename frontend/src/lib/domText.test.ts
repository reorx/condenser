// jsdom covers the index/range math; the point-hit-testing path is guarded live
// (caretRangeFromPoint does not exist here) and exercised in the browser walkthrough.
import { describe, expect, it } from 'vitest';

import { buildTextIndex, offsetFromDomPos, rangeFromOffsets, selectionOffsets } from './domText';

function mount(html: string): HTMLElement {
  const el = document.createElement('div');
  el.innerHTML = html;
  document.body.appendChild(el);
  return el;
}

describe('buildTextIndex', () => {
  it('concatenates text nodes across nested elements in document order', () => {
    const el = mount('<p>one <a>two</a></p><p>three</p>');
    const index = buildTextIndex(el);
    expect(index.text).toBe('one twothree');
    expect(index.nodes.map((n) => n.start)).toEqual([0, 4, 7]);
  });

  it('handles an empty container', () => {
    const index = buildTextIndex(mount(''));
    expect(index.text).toBe('');
    expect(rangeFromOffsets(index, 0, 1)).toBeNull();
  });
});

describe('rangeFromOffsets', () => {
  it('spans element boundaries', () => {
    const el = mount('<p>one <a>two</a></p><p>three</p>');
    const index = buildTextIndex(el);
    const range = rangeFromOffsets(index, 2, 10)!; // 'e twothr'
    expect(range.toString()).toBe('e twothr');
  });

  it('clamps an end past the text to the last node', () => {
    const el = mount('<p>abc</p>');
    const index = buildTextIndex(el);
    expect(rangeFromOffsets(index, 1, 99)!.toString()).toBe('bc');
  });
});

describe('offsetFromDomPos', () => {
  it('maps a text-node position back to the flat offset', () => {
    const el = mount('<p>one <a>two</a></p>');
    const index = buildTextIndex(el);
    const anchorText = el.querySelector('a')!.firstChild as Text;
    expect(offsetFromDomPos(index, anchorText, 1)).toBe(5);
  });

  it('resolves an element boundary to the following text node', () => {
    const el = mount('<p>one </p><p>two</p>');
    const index = buildTextIndex(el);
    // Position "before the second <p>" inside the container element.
    expect(offsetFromDomPos(index, el, 1)).toBe(4);
  });

  it('returns null for a node outside the container', () => {
    const el = mount('<p>in</p>');
    const other = mount('<p>out</p>');
    const index = buildTextIndex(el);
    expect(offsetFromDomPos(index, other.firstChild!.firstChild!, 0)).toBeNull();
  });
});

describe('selectionOffsets', () => {
  it('reads a selection inside the container as flat offsets', () => {
    const el = mount('<p>one <a>two</a></p>');
    const index = buildTextIndex(el);
    const range = rangeFromOffsets(index, 2, 6)!;
    const sel = window.getSelection()!;
    sel.removeAllRanges();
    sel.addRange(range);
    expect(selectionOffsets(index)).toEqual({ start: 2, end: 6 });
    sel.removeAllRanges();
  });

  it('ignores a collapsed or outside selection', () => {
    const el = mount('<p>abc</p>');
    const index = buildTextIndex(el);
    window.getSelection()!.removeAllRanges();
    expect(selectionOffsets(index)).toBeNull();
  });
});
