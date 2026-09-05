// The condenser half of the Vibe Reader link mode (plan 2026-09-02 §1 + §2).
//
// The extension's sidepanel injects a content-script *bridge* into any tab whose
// page carries `<meta name="application-name" content="condenser">`. Page and
// bridge talk over `window.postMessage` on our own origin; the page only ever
// listens for messages that come from this very window under the bridge's
// namespace, and the bridge does the mirror-image check. There is no heartbeat:
// the bridge's existence *is* "the sidepanel is open" — its port dies with the
// panel and the bridge tells us so (`bye`).
//
// Two rules the store enforces, both user decisions (plan §0):
//   - the link switch has one source of truth, the extension. `setLink` only
//     *asks*; `linked` flips when `vibe-reader:link` says so, never before.
//   - only a click condenser explicitly announced (`condenser:open`) gets the
//     extension's attention and the reader's money. Nothing is announced while
//     unlinked, nothing is prefetched on hover.
//
// The message shapes below are the contract's copy on this side; the extension
// keeps its own (`vibe-reader-hn/kb/plans/2026-09-02-condenser-link-mode-multi-session.md`).
// Both are pinned by tests. Changing either means bumping PROTOCOL_VERSION.
import { useMemo, useSyncExternalStore } from 'react';

import type { HnStory } from '@/lib/types';

export const PROTOCOL_VERSION = 1;
/** Namespace of everything the page sends. */
export const PAGE_NS = 'condenser';
/** Namespace of everything the bridge sends. */
export const BRIDGE_NS = 'vibe-reader';

/** What a story card knows that spares the extension an Algolia search. */
export interface HnIntent {
  id: number;
  title: string;
  score: number;
  comments_count: number;
  submitted_at: string | null;
}

/** "The reader just opened this in a new tab." */
export interface OpenIntent {
  url: string;
  title?: string;
  hn?: HnIntent;
}

export type VibeReaderStatusState = 'queued' | 'extracting' | 'generating' | 'done' | 'error';
const STATUS_STATES: ReadonlySet<string> = new Set<VibeReaderStatusState>([
  'queued',
  'extracting',
  'generating',
  'done',
  'error',
]);

/** Where the extension stands on one page the reader opened from here (Phase D). */
export interface VibeReaderStatus {
  /** The url as announced (the extension echoes our `condenser:open`). */
  url: string;
  state: VibeReaderStatusState;
  /** What is being / was generated (`summary`, `discussion`, …) when the extension said. */
  modes?: string[];
  /** Arrival order; a card with several links shows the one touched last. */
  seq: number;
}

type PageMessage =
  | { ns: typeof PAGE_NS; v: number; type: 'condenser:hello' }
  | { ns: typeof PAGE_NS; v: number; type: 'condenser:set-link'; linked: boolean }
  | ({ ns: typeof PAGE_NS; v: number; type: 'condenser:open' } & OpenIntent);

type BridgeMessage =
  | { ns: typeof BRIDGE_NS; v: number; type: 'vibe-reader:hello'; linked: boolean }
  | { ns: typeof BRIDGE_NS; v: number; type: 'vibe-reader:link'; linked: boolean }
  | { ns: typeof BRIDGE_NS; v: number; type: 'vibe-reader:bye' }
  // Phase D (plan §5): per-URL progress, shown as a badge on the card's time line.
  | {
      ns: typeof BRIDGE_NS;
      v: number;
      type: 'vibe-reader:status';
      url: string;
      state: VibeReaderStatusState;
      modes?: string[];
    };

export interface VibeReaderState {
  /** A bridge at our protocol version is present (the sidepanel is open). */
  available: boolean;
  /** The extension's switch, mirrored. Meaningless while unavailable (always false). */
  linked: boolean;
  /** The protocol version the last hello carried; null before any. Differs from
   *  ours ⟹ available stays false, so Settings can say "version mismatch". */
  version: number | null;
  /** Per-page progress the extension reported, keyed by `canonicalUrl`. Never
   *  persisted and never in React Query: a reload starts blank (plan §5), and
   *  `bye` empties it — a spinner for a sidepanel that closed would spin forever. */
  statuses: ReadonlyMap<string, VibeReaderStatus>;
}

const NO_STATUSES: ReadonlyMap<string, VibeReaderStatus> = new Map();
const INITIAL: VibeReaderState = { available: false, linked: false, version: null, statuses: NO_STATUSES };
let statusSeq = 0;

let state: VibeReaderState = INITIAL;
const listeners = new Set<() => void>();

function setState(next: Partial<VibeReaderState>) {
  state = { ...state, ...next };
  for (const l of listeners) l();
}

export function getSnapshot(): VibeReaderState {
  return state;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useVibeReaderState(): VibeReaderState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** Test seam: back to the never-met-a-bridge state. */
export function resetForTests() {
  state = INITIAL;
  statusSeq = 0;
  listeners.clear();
}

// ---------------------------------------------------------------------------
// Per-page status (Phase D)

/** The form both sides' urls are compared in. The extension echoes the `a.href`
 *  we announced, which the browser had already normalized (`https://x.com` →
 *  `https://x.com/`); a card looks up with the raw payload url. `new URL().href`
 *  is that same normalization. Null when the string is not a url at all. */
export function canonicalUrl(url: string): string | null {
  try {
    return new URL(url).href;
  } catch {
    return null;
  }
}

/** The status of the link the reader touched last among `urls`, or null. Returns
 *  the stored object itself, so an unchanged answer is the same reference and
 *  `useSyncExternalStore` bails out of the re-render. */
export function statusFor(urls: readonly string[]): VibeReaderStatus | null {
  let best: VibeReaderStatus | null = null;
  for (const url of urls) {
    const key = canonicalUrl(url);
    const status = key ? state.statuses.get(key) : undefined;
    if (status && (!best || status.seq > best.seq)) best = status;
  }
  return best;
}

/** What the extension last said about any of a card's links; null = nothing. */
export function useVibeReaderStatus(urls: readonly string[]): VibeReaderStatus | null {
  // A fresh array every render is the norm (cards build it from the payload); the
  // store answers by reference, so the subscription stays cheap either way.
  const getStatus = useMemo(() => () => statusFor(urls), [urls]);
  return useSyncExternalStore(subscribe, getStatus, getStatus);
}

function recordStatus(msg: Extract<BridgeMessage, { type: 'vibe-reader:status' }>) {
  if (typeof msg.url !== 'string' || !STATUS_STATES.has(msg.state)) return;
  const key = canonicalUrl(msg.url);
  if (!key) return;
  const statuses = new Map(state.statuses);
  const status: VibeReaderStatus = { url: msg.url, state: msg.state, seq: ++statusSeq };
  if (Array.isArray(msg.modes)) status.modes = msg.modes.filter((m): m is string => typeof m === 'string');
  statuses.set(key, status);
  setState({ statuses });
}

// ---------------------------------------------------------------------------
// Outbound

function post(msg: PageMessage) {
  window.postMessage(msg, window.location.origin);
}

/** "I'm here" — sent on mount. Whoever is ready second finds the other. */
export function sayHello() {
  post({ ns: PAGE_NS, v: PROTOCOL_VERSION, type: 'condenser:hello' });
}

/** Ask the extension to flip the link. The answer arrives as `vibe-reader:link`. */
export function setLink(linked: boolean) {
  post({ ns: PAGE_NS, v: PROTOCOL_VERSION, type: 'condenser:set-link', linked });
}

/** Tell the extension a tab is opening. Returns whether anything was sent. */
export function announceOpen(intent: OpenIntent): boolean {
  if (!state.available || !state.linked) return false;
  post({ ns: PAGE_NS, v: PROTOCOL_VERSION, type: 'condenser:open', ...intent });
  return true;
}

// ---------------------------------------------------------------------------
// Inbound

function isBridgeMessage(data: unknown): data is BridgeMessage {
  return (
    typeof data === 'object' &&
    data !== null &&
    (data as { ns?: unknown }).ns === BRIDGE_NS &&
    typeof (data as { type?: unknown }).type === 'string'
  );
}

function onBridgeMessage(msg: BridgeMessage) {
  switch (msg.type) {
    case 'vibe-reader:hello': {
      const ours = msg.v === PROTOCOL_VERSION;
      setState({ available: ours, linked: ours && !!msg.linked, version: msg.v });
      return;
    }
    case 'vibe-reader:link':
      if (state.available) setState({ linked: !!msg.linked });
      return;
    case 'vibe-reader:bye':
      // Everything here described the bridge that just left: the link is a
      // property of the connection (nobody to announce to; the next hello restates
      // the switch), and so is the version — a leftover one read as "protocol
      // mismatch" in Settings once the sidepanel closed (2026-09-04 walkthrough).
      setState(INITIAL);
      return;
    case 'vibe-reader:status':
      // Only a bridge we accepted gets to paint badges; a foreign-version one
      // never said a hello we honored.
      if (state.available) recordStatus(msg);
      return;
  }
}

/** Listen for the bridge on this window. Returns the uninstaller. */
export function listenToBridge(): () => void {
  const handler = (event: MessageEvent) => {
    // Same window only: a bridge is a content script, so its postMessage looks
    // like our own. Anything from an iframe or another window is not it.
    if (event.source !== window) return;
    if (!isBridgeMessage(event.data)) return;
    onBridgeMessage(event.data);
  };
  window.addEventListener('message', handler);
  return () => window.removeEventListener('message', handler);
}

// ---------------------------------------------------------------------------
// Which links to announce

/** Hosts (any subdomain) that carry nothing worth extracting; an optional path
 *  prefix narrows it — HN *item* pages are announced (the extension reads the
 *  thread), HN *user* pages are not. */
export const NO_ARTICLE_HOSTS: ReadonlyArray<{ host: string; path?: string }> = [
  { host: 'x.com' },
  { host: 'twitter.com' },
  { host: 't.me' },
  { host: 'news.ycombinator.com', path: '/user' },
];

function hostMatches(hostname: string, host: string) {
  return hostname === host || hostname.endsWith(`.${host}`);
}

export function shouldAnnounce(href: string): boolean {
  let url: URL;
  try {
    url = new URL(href, window.location.href);
  } catch {
    return false;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
  // Our own proxies (media, avatars, preview images) are not articles.
  if (url.origin === window.location.origin) return false;
  return !NO_ARTICLE_HOSTS.some(
    (rule) => hostMatches(url.hostname, rule.host) && (!rule.path || url.pathname.startsWith(rule.path)),
  );
}

// ---------------------------------------------------------------------------
// Click delegate

/** The `data-vr-*` attributes a story's links carry so the delegate can hand the
 *  extension an `HnIntent` (plan §2.3). Spread onto the anchor; the title comes
 *  from here too, since the comments link's own text is "45 comments". */
export function hnLinkAttrs(hn: HnStory): Record<`data-vr-${string}`, string> {
  const attrs: Record<`data-vr-${string}`, string> = {
    'data-vr-hn-id': String(hn.id),
    'data-vr-hn-score': String(hn.score),
    'data-vr-hn-comments': String(hn.comments_count),
    'data-vr-hn-submitted': hn.submitted_at ?? '',
  };
  // A story without a title (a dead/deleted one) leaves the delegate to the link text.
  if (hn.title) attrs['data-vr-title'] = hn.title;
  return attrs;
}

function intentFromAnchor(a: HTMLAnchorElement): OpenIntent {
  const title = a.dataset.vrTitle ?? a.textContent?.trim();
  const intent: OpenIntent = { url: a.href };
  if (title) intent.title = title;
  const hnId = a.dataset.vrHnId;
  if (hnId != null) {
    intent.hn = {
      id: Number(hnId),
      title: title ?? '',
      score: Number(a.dataset.vrHnScore ?? 0),
      comments_count: Number(a.dataset.vrHnComments ?? 0),
      submitted_at: a.dataset.vrHnSubmitted || null,
    };
  }
  return intent;
}

/** A new-tab link the reader is opening, or null if this event is not that. */
function newTabAnchor(event: MouseEvent): HTMLAnchorElement | null {
  // A cancelled click opens nothing, so there is nothing to announce.
  if (event.defaultPrevented) return null;
  // auxclick fires for the middle button (new tab) and the right button (menu).
  if (event.type === 'auxclick' && event.button !== 1) return null;
  const target = event.target;
  if (!(target instanceof Element)) return null;
  const a = target.closest('a[href]');
  if (!(a instanceof HTMLAnchorElement) || a.target !== '_blank') return null;
  return a;
}

/** One listener on `root` (the document) covers every card, every source,
 *  every future surface: `condenser:open` for each new-tab http(s) link the
 *  reader clicks, with the HN intent when the anchor carries `data-vr-hn-*`.
 *  Never `preventDefault`s — the browser opens the tab as it always did. */
export function installLinkDelegate(root: Document | Element): () => void {
  const handler = (event: Event) => {
    const a = newTabAnchor(event as MouseEvent);
    if (!a || !shouldAnnounce(a.href)) return;
    announceOpen(intentFromAnchor(a));
  };
  root.addEventListener('click', handler);
  root.addEventListener('auxclick', handler);
  return () => {
    root.removeEventListener('click', handler);
    root.removeEventListener('auxclick', handler);
  };
}

/** Everything the app shell needs: listen, delegate, say hello. Returns the uninstaller. */
export function installVibeReader(root: Document | Element = document): () => void {
  const offBridge = listenToBridge();
  const offDelegate = installLinkDelegate(root);
  sayHello();
  return () => {
    offDelegate();
    offBridge();
  };
}
