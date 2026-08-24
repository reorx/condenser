import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Highlighter, MessageSquareText, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import type { HighlightContext } from '@/hooks/useItemAnnotations';
import { locateAnnotation, selectionContext } from '@/lib/annotate';
import { errorMessage } from '@/lib/api';
import { buildTextIndex, offsetFromPoint, rangeFromOffsets, selectionOffsets, type TextIndex } from '@/lib/domText';
import type { ItemAnnotation } from '@/lib/types';
import { cn } from '@/lib/utils';

import { AnnotationCommentDialog } from './AnnotationCommentDialog';
import { AnnotationOrphans } from './AnnotationOrphans';

/** The CSS Custom Highlight registry name — styled by `::highlight(...)` rules in
 *  `index.css`. One static name is enough: the detail pane mounts at most one
 *  annotatable body at a time. */
const HIGHLIGHT_NAME = 'condenser-annotation';

const supportsHighlights = typeof CSS !== 'undefined' && 'highlights' in CSS;

interface Props {
  annotations: ItemAnnotation[];
  /** Persist one new highlight; rejects on failure (toasted here). */
  onCreate: (context: HighlightContext) => Promise<void>;
  /** Persist a highlight's whole comment (null clears); rejects on failure. */
  onSetComment: (id: number, comment: string | null) => Promise<void>;
  /** Remove one highlight (comment included); rejects on failure. */
  onDelete: (id: number) => Promise<void>;
  /** The rendered body text (React children or a sanitized-HTML div). */
  children: ReactNode;
}

interface Located {
  annotation: ItemAnnotation;
  loc: { start: number; end: number } | null;
}

/**
 * The annotatable body: renders its children untouched, then works on the DOM —
 * a flat text index over the rendered nodes, quote relocation (`lib/annotate.ts`),
 * highlight painting via the CSS Custom Highlight API (never mutating nodes React
 * owns), a floating 「高亮」 button on selection (the web's stand-in for iOS's
 * edit-menu entry), and a 评论/删除 menu on clicking a painted highlight
 * (shortest-range-wins hit-testing, iOS's rule for overlaps). Orphans — quotes
 * the text no longer contains — are listed below the body, never dropped.
 *
 * On a browser without the Highlight API the layer degrades: creating still
 * works and orphans still list, but located highlights are not painted (and so
 * not clickable). Acceptable — every evergreen browser has shipped the API.
 */
export function AnnotatedText({ annotations, onCreate, onSetComment, onDelete, children }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [index, setIndex] = useState<TextIndex | null>(null);
  const [toolbar, setToolbar] = useState<{
    top: number;
    left: number;
    below: boolean;
    context: HighlightContext;
  } | null>(null);
  const [menu, setMenu] = useState<{ top: number; left: number; annotation: ItemAnnotation } | null>(null);
  const [commentTarget, setCommentTarget] = useState<ItemAnnotation | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // Rebuild the text index whenever the rendered nodes changed. Runs every render
  // (children are opaque), but bails to the previous object when nothing moved, so
  // the memos below keep their identity.
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) return;
    const next = buildTextIndex(root);
    setIndex((prev) =>
      prev &&
      prev.text === next.text &&
      prev.nodes.length === next.nodes.length &&
      prev.nodes.every((n, i) => n.node === next.nodes[i].node)
        ? prev
        : next,
    );
  });

  // Relocation is a full-text search per annotation — cached against the exact
  // (text, annotations) pair, the same reason iOS caches per annotation id.
  const located = useMemo<Located[]>(
    () => annotations.map((a) => ({ annotation: a, loc: index ? locateAnnotation(a, [index.text]) : null })),
    [index, annotations],
  );
  // Until the index exists nothing has been searched, so nothing is an orphan yet.
  const orphans = index ? located.filter((l) => !l.loc).map((l) => l.annotation) : [];

  // Paint. Registry cleanup on unmount keeps a closed pane from leaving marks
  // behind on the next thing that renders.
  useEffect(() => {
    if (!supportsHighlights || !index) return;
    const ranges: Range[] = [];
    for (const { loc } of located) {
      if (!loc) continue;
      const range = rangeFromOffsets(index, loc.start, loc.end);
      if (range) ranges.push(range);
    }
    CSS.highlights.set(HIGHLIGHT_NAME, new Highlight(...ranges));
    return () => {
      CSS.highlights.delete(HIGHLIGHT_NAME);
    };
  }, [index, located]);

  // Selection → the floating 「高亮」 button. Deferred a tick: the selection is
  // still settling inside the mouseup/touchend that triggered us.
  const handleSelection = useCallback(() => {
    window.setTimeout(() => {
      const root = ref.current;
      if (!root || !index) return;
      const offsets = selectionOffsets(index);
      if (!offsets) {
        setToolbar(null);
        return;
      }
      const rect = window.getSelection()!.getRangeAt(0).getBoundingClientRect();
      const rootRect = root.getBoundingClientRect();
      // A selection on the first line would put the button past the container's
      // top edge, where the pane's scroll box clips it — flip below instead.
      const below = rect.top - rootRect.top < 40;
      setToolbar({
        top: below ? rect.bottom - rootRect.top : rect.top - rootRect.top,
        left: Math.min(Math.max(rect.left + rect.width / 2 - rootRect.left, 32), rootRect.width - 32),
        below,
        context: selectionContext(index.text, offsets.start, offsets.end),
      });
      setMenu(null);
    }, 0);
  }, [index]);

  // The button outlives the selection only as long as the selection itself does.
  useEffect(() => {
    if (!toolbar) return;
    const onChange = () => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed) setToolbar(null);
    };
    document.addEventListener('selectionchange', onChange);
    return () => document.removeEventListener('selectionchange', onChange);
  }, [toolbar]);

  // The 评论/删除 menu closes on any press outside it.
  useEffect(() => {
    if (!menu) return;
    const onDown = (e: PointerEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(null);
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [menu]);

  const createHighlight = async () => {
    if (!toolbar) return;
    const { context } = toolbar;
    setToolbar(null);
    window.getSelection()?.removeAllRanges();
    try {
      await onCreate(context);
    } catch (e) {
      toast.error(errorMessage(e, '高亮失败，请重试'));
    }
  };

  const deleteHighlight = async (id: number) => {
    setMenu(null);
    try {
      await onDelete(id);
    } catch (e) {
      toast.error(errorMessage(e, '删除失败，请重试'));
    }
  };

  // Click on a painted highlight → the menu. A click that ends a text selection
  // is not a tap (the toolbar owns that moment), and clicks that miss every
  // highlight fall through untouched — links keep working.
  const handleClick = (e: React.MouseEvent) => {
    const root = ref.current;
    if (!root || !index) return;
    const sel = window.getSelection();
    if (sel && !sel.isCollapsed) return;
    const offset = offsetFromPoint(index, e.clientX, e.clientY);
    if (offset === null) return;
    const hits = located.filter((l) => l.loc && l.loc.start <= offset && offset < l.loc.end);
    if (hits.length === 0) {
      setMenu(null);
      return;
    }
    // Overlapping highlights are not merged; the shortest one under the pointer
    // wins, so an inner highlight stays reachable (iOS's rule).
    const target = hits.reduce((a, b) => (a.loc!.end - a.loc!.start <= b.loc!.end - b.loc!.start ? a : b));
    e.preventDefault();
    e.stopPropagation();
    const rootRect = root.getBoundingClientRect();
    setMenu({
      top: e.clientY - rootRect.top,
      left: Math.min(Math.max(e.clientX - rootRect.left, 32), rootRect.width - 72),
      annotation: target.annotation,
    });
  };

  return (
    <div className="relative">
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
      <div ref={ref} onMouseUp={handleSelection} onTouchEnd={handleSelection} onClick={handleClick}>
        {children}
      </div>

      {toolbar && (
        <button
          type="button"
          onClick={createHighlight}
          className={cn(
            'absolute z-10 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-md border bg-popover px-2.5 py-1.5 text-xs font-medium text-popover-foreground shadow-md transition-colors hover:bg-accent',
            !toolbar.below && '-translate-y-full',
          )}
          style={{ top: toolbar.below ? toolbar.top + 6 : toolbar.top - 6, left: toolbar.left }}
        >
          <Highlighter className="size-3.5" />
          高亮
        </button>
      )}

      {menu && (
        <div
          ref={menuRef}
          className="absolute z-10 flex -translate-x-1/2 items-center overflow-hidden rounded-md border bg-popover text-xs font-medium text-popover-foreground shadow-md"
          style={{ top: menu.top + 8, left: menu.left }}
        >
          <button
            type="button"
            onClick={() => {
              setCommentTarget(menu.annotation);
              setMenu(null);
            }}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 transition-colors hover:bg-accent"
          >
            <MessageSquareText className="size-3.5" />
            评论
          </button>
          <button
            type="button"
            onClick={() => deleteHighlight(menu.annotation.id)}
            className="inline-flex items-center gap-1.5 border-l px-2.5 py-1.5 text-destructive transition-colors hover:bg-accent"
          >
            <Trash2 className="size-3.5" />
            删除
          </button>
        </div>
      )}

      <AnnotationOrphans orphans={orphans} onDelete={(id) => void deleteHighlight(id)} />

      <AnnotationCommentDialog
        annotation={commentTarget}
        onClose={() => setCommentTarget(null)}
        onSave={(comment) => onSetComment(commentTarget!.id, comment || null)}
      />
    </div>
  );
}
