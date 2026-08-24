// The DOM half of highlighting: a flat view of a container's rendered text with
// maps between UTF-16 offsets and (text node, offset) positions. `annotate.ts`
// works on the flat string (so it can stay a pure, cross-platform-tested port);
// this module turns its answers back into DOM Ranges — and selections/clicks back
// into flat offsets. It deliberately never mutates the DOM: highlights render via
// the CSS Custom Highlight API, so React keeps sole ownership of the nodes.

/** A container's text nodes in document order, with each node's start offset in
 *  the concatenated text. `text` is what `locateAnnotation` searches. */
export interface TextIndex {
  root: HTMLElement;
  text: string;
  nodes: { node: Text; start: number }[];
}

export function buildTextIndex(root: HTMLElement): TextIndex {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: { node: Text; start: number }[] = [];
  let text = '';
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n as Text;
    nodes.push({ node: t, start: text.length });
    text += t.data;
  }
  return { root, text, nodes };
}

/** The (node, offset) position of a flat offset; clamps to the last node's end. */
function domPos(index: TextIndex, offset: number): { node: Text; offset: number } | null {
  const { nodes } = index;
  if (nodes.length === 0) return null;
  for (let i = nodes.length - 1; i >= 0; i -= 1) {
    if (offset >= nodes[i].start) {
      const node = nodes[i].node;
      return { node, offset: Math.min(offset - nodes[i].start, node.data.length) };
    }
  }
  return { node: nodes[0].node, offset: 0 };
}

/** A live Range over [start, end) of the flat text, or null when out of reach. */
export function rangeFromOffsets(index: TextIndex, start: number, end: number): Range | null {
  const from = domPos(index, start);
  const to = domPos(index, end);
  if (!from || !to) return null;
  const range = document.createRange();
  range.setStart(from.node, from.offset);
  range.setEnd(to.node, to.offset);
  return range;
}

/** The flat offset of a (node, offset) DOM position; null when the node is not
 *  part of the index (outside the container, or an element position). */
export function offsetFromDomPos(index: TextIndex, node: Node, nodeOffset: number): number | null {
  if (node.nodeType === Node.TEXT_NODE) {
    const entry = index.nodes.find((e) => e.node === node);
    return entry ? entry.start + nodeOffset : null;
  }
  // Element position (e.g. a selection boundary between nodes): resolve to the
  // start of the first indexed text node at/after the child boundary.
  if (node.nodeType === Node.ELEMENT_NODE && index.root.contains(node)) {
    const children = node.childNodes;
    for (let i = nodeOffset; i < children.length; i += 1) {
      const entry = index.nodes.find((e) => children[i].contains(e.node));
      if (entry) return entry.start;
    }
    return index.text.length;
  }
  return null;
}

/** The current selection as flat offsets into the index, or null when there is no
 *  non-collapsed selection fully inside the container. */
export function selectionOffsets(index: TextIndex): { start: number; end: number } | null {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  if (!index.root.contains(range.startContainer) || !index.root.contains(range.endContainer)) return null;
  const start = offsetFromDomPos(index, range.startContainer, range.startOffset);
  const end = offsetFromDomPos(index, range.endContainer, range.endOffset);
  if (start === null || end === null || start >= end) return null;
  return { start, end };
}

/** The flat offset under a client point (for hit-testing a click on a highlight);
 *  null where the platform API is missing or the point misses the indexed text. */
export function offsetFromPoint(index: TextIndex, x: number, y: number): number | null {
  // Two vendor shapes for the same question; Firefox has the spec'd one.
  const doc = document as Document & {
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
    caretRangeFromPoint?: (x: number, y: number) => Range | null;
  };
  if (doc.caretPositionFromPoint) {
    const pos = doc.caretPositionFromPoint(x, y);
    return pos ? offsetFromDomPos(index, pos.offsetNode, pos.offset) : null;
  }
  if (doc.caretRangeFromPoint) {
    const range = doc.caretRangeFromPoint(x, y);
    return range ? offsetFromDomPos(index, range.startContainer, range.startOffset) : null;
  }
  return null;
}
