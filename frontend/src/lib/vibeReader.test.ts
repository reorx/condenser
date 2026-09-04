// The condenser half of the Vibe Reader link-mode contract (plan 2026-09-02 §1).
// These tests pin the wire shape: any change here means bumping PROTOCOL_VERSION
// on both sides. The bridge is simulated by dispatching MessageEvents on window
// with `source: window`, which is exactly what a content-script bridge's
// `window.postMessage` looks like from the page.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  BRIDGE_NS,
  NO_ARTICLE_HOSTS,
  PAGE_NS,
  PROTOCOL_VERSION,
  announceOpen,
  getSnapshot,
  installLinkDelegate,
  installVibeReader,
  listenToBridge,
  resetForTests,
  sayHello,
  setLink,
  shouldAnnounce,
  subscribe,
} from './vibeReader';

/** What the bridge would post: a MessageEvent from this very window. */
function fromBridge(msg: Record<string, unknown>, over: { source?: unknown; ns?: string } = {}) {
  const data = { ns: over.ns ?? BRIDGE_NS, v: PROTOCOL_VERSION, ...msg };
  const source = 'source' in over ? over.source : window;
  window.dispatchEvent(
    new MessageEvent('message', { data, origin: window.location.origin, source: source as Window | null }),
  );
}

let posted: unknown[];

beforeEach(() => {
  resetForTests();
  posted = [];
  vi.spyOn(window, 'postMessage').mockImplementation((msg: unknown) => {
    posted.push(msg);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

const lastPosted = () => posted[posted.length - 1] as Record<string, unknown>;

describe('bridge presence', () => {
  it('starts unavailable and unlinked', () => {
    expect(getSnapshot()).toEqual({ available: false, linked: false, version: null });
  });

  it('vibe-reader:hello marks the bridge available and mirrors linked', () => {
    const off = listenToBridge();
    fromBridge({ type: 'vibe-reader:hello', linked: true });
    expect(getSnapshot()).toMatchObject({ available: true, linked: true, version: PROTOCOL_VERSION });
    off();
  });

  it('vibe-reader:bye marks the bridge gone (the port dropped: sidepanel closed / extension reloaded)', () => {
    const off = listenToBridge();
    fromBridge({ type: 'vibe-reader:hello', linked: true });
    fromBridge({ type: 'vibe-reader:bye' });
    expect(getSnapshot()).toMatchObject({ available: false, linked: false });
    off();
  });

  it('vibe-reader:link is the only thing that flips linked', () => {
    const off = listenToBridge();
    fromBridge({ type: 'vibe-reader:hello', linked: false });
    fromBridge({ type: 'vibe-reader:link', linked: true });
    expect(getSnapshot().linked).toBe(true);
    fromBridge({ type: 'vibe-reader:link', linked: false });
    expect(getSnapshot().linked).toBe(false);
    off();
  });

  it('a hello at another protocol version is recorded but not treated as available', () => {
    const off = listenToBridge();
    window.dispatchEvent(
      new MessageEvent('message', {
        data: { ns: BRIDGE_NS, v: PROTOCOL_VERSION + 1, type: 'vibe-reader:hello', linked: true },
        source: window,
      }),
    );
    expect(getSnapshot()).toEqual({ available: false, linked: false, version: PROTOCOL_VERSION + 1 });
    off();
  });

  it('notifies subscribers on every change and stops after unsubscribe', () => {
    const off = listenToBridge();
    const listener = vi.fn();
    const unsub = subscribe(listener);
    fromBridge({ type: 'vibe-reader:hello', linked: false });
    expect(listener).toHaveBeenCalledTimes(1);
    unsub();
    fromBridge({ type: 'vibe-reader:link', linked: true });
    expect(listener).toHaveBeenCalledTimes(1);
    off();
  });

  it('stops listening once uninstalled', () => {
    const off = listenToBridge();
    off();
    fromBridge({ type: 'vibe-reader:hello', linked: true });
    expect(getSnapshot().available).toBe(false);
  });
});

describe('origin checks', () => {
  it('ignores a message whose source is not this window', () => {
    const off = listenToBridge();
    fromBridge({ type: 'vibe-reader:hello', linked: true }, { source: null });
    expect(getSnapshot().available).toBe(false);
    off();
  });

  it('ignores a message under another namespace — including our own outbound ones', () => {
    const off = listenToBridge();
    fromBridge({ type: 'vibe-reader:hello', linked: true }, { ns: 'other' });
    fromBridge({ type: 'vibe-reader:hello', linked: true }, { ns: PAGE_NS });
    expect(getSnapshot().available).toBe(false);
    off();
  });

  it('ignores junk data without throwing', () => {
    const off = listenToBridge();
    window.dispatchEvent(new MessageEvent('message', { data: 'a string', source: window }));
    window.dispatchEvent(new MessageEvent('message', { data: null, source: window }));
    window.dispatchEvent(new MessageEvent('message', { data: { ns: BRIDGE_NS }, source: window }));
    expect(getSnapshot().available).toBe(false);
    off();
  });
});

describe('outbound messages', () => {
  it('sayHello posts condenser:hello under the page namespace, to our own origin', () => {
    sayHello();
    expect(lastPosted()).toEqual({ ns: PAGE_NS, v: PROTOCOL_VERSION, type: 'condenser:hello' });
    expect(vi.mocked(window.postMessage).mock.calls[0][1]).toBe(window.location.origin);
  });

  it('installVibeReader says hello on mount (the bridge may already be there)', () => {
    const off = installVibeReader(document);
    expect(posted).toContainEqual({ ns: PAGE_NS, v: PROTOCOL_VERSION, type: 'condenser:hello' });
    off();
  });

  it('setLink requests the switch and does NOT flip linked optimistically — the extension is the truth', () => {
    const off = listenToBridge();
    fromBridge({ type: 'vibe-reader:hello', linked: false });
    setLink(true);
    expect(lastPosted()).toEqual({ ns: PAGE_NS, v: PROTOCOL_VERSION, type: 'condenser:set-link', linked: true });
    expect(getSnapshot().linked).toBe(false);
    fromBridge({ type: 'vibe-reader:link', linked: true });
    expect(getSnapshot().linked).toBe(true);
    off();
  });

  it('announceOpen posts condenser:open only while linked', () => {
    const off = listenToBridge();
    expect(announceOpen({ url: 'https://example.com/a' })).toBe(false);
    expect(posted.find((m) => (m as { type: string }).type === 'condenser:open')).toBeUndefined();

    fromBridge({ type: 'vibe-reader:hello', linked: true });
    expect(announceOpen({ url: 'https://example.com/a', title: 'A' })).toBe(true);
    expect(lastPosted()).toEqual({
      ns: PAGE_NS,
      v: PROTOCOL_VERSION,
      type: 'condenser:open',
      url: 'https://example.com/a',
      title: 'A',
    });
    off();
  });
});

describe('shouldAnnounce', () => {
  it('lets ordinary article URLs through, including HN item pages', () => {
    expect(shouldAnnounce('https://example.com/post')).toBe(true);
    expect(shouldAnnounce('http://blog.example.org/x?y=1')).toBe(true);
    expect(shouldAnnounce('https://news.ycombinator.com/item?id=101')).toBe(true);
  });

  it('skips hosts that carry no article', () => {
    expect(shouldAnnounce('https://x.com/alice/status/1')).toBe(false);
    expect(shouldAnnounce('https://twitter.com/alice/status/1')).toBe(false);
    expect(shouldAnnounce('https://mobile.twitter.com/alice')).toBe(false);
    expect(shouldAnnounce('https://t.me/channel/12')).toBe(false);
    expect(shouldAnnounce('https://news.ycombinator.com/user?id=pg')).toBe(false);
  });

  it('skips non-http schemes and our own origin', () => {
    expect(shouldAnnounce('mailto:a@b.c')).toBe(false);
    expect(shouldAnnounce('javascript:void(0)')).toBe(false);
    expect(shouldAnnounce(`${window.location.origin}/api/preview/image?url=x`)).toBe(false);
    expect(shouldAnnounce('not a url')).toBe(false);
  });

  it('pins the exclusion list', () => {
    expect(NO_ARTICLE_HOSTS).toEqual([
      { host: 'x.com' },
      { host: 'twitter.com' },
      { host: 't.me' },
      { host: 'news.ycombinator.com', path: '/user' },
    ]);
  });
});

describe('link delegate', () => {
  let root: HTMLDivElement;
  let offBridge: () => void;
  let offDelegate: () => void;

  function link(attrs: Record<string, string>, text = 'A story') {
    const a = document.createElement('a');
    for (const [k, v] of Object.entries(attrs)) a.setAttribute(k, v);
    a.textContent = text;
    root.appendChild(a);
    return a;
  }

  const hnLink = () =>
    link({
      href: 'https://example.com/post',
      target: '_blank',
      'data-vr-hn-id': '1',
      'data-vr-title': 'T',
      'data-vr-hn-score': '120',
      'data-vr-hn-comments': '45',
      'data-vr-hn-submitted': '2026-07-19T10:00:00+00:00',
    });

  const opens = () => posted.filter((m) => (m as { type: string }).type === 'condenser:open');

  // jsdom tries (and fails, loudly) to navigate on a real anchor click; swallow it
  // at the window, which runs after the delegate on `root` has seen the event.
  const swallowNavigation = (e: Event) => e.preventDefault();

  beforeEach(() => {
    root = document.createElement('div');
    document.body.appendChild(root);
    offBridge = listenToBridge();
    offDelegate = installLinkDelegate(root);
    window.addEventListener('click', swallowNavigation);
    window.addEventListener('auxclick', swallowNavigation);
    fromBridge({ type: 'vibe-reader:hello', linked: true });
  });

  afterEach(() => {
    window.removeEventListener('click', swallowNavigation);
    window.removeEventListener('auxclick', swallowNavigation);
    offDelegate();
    offBridge();
    root.remove();
  });

  it('announces a clicked _blank link with the HN intent read off its data attributes', () => {
    hnLink().dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    expect(opens()).toHaveLength(1);
    expect(lastPosted()).toEqual({
      ns: PAGE_NS,
      v: PROTOCOL_VERSION,
      type: 'condenser:open',
      url: 'https://example.com/post',
      title: 'T',
      hn: { id: 1, title: 'T', score: 120, comments_count: 45, submitted_at: '2026-07-19T10:00:00+00:00' },
    });
  });

  it('does not stop the browser from opening the tab', () => {
    const a = hnLink();
    // Registered after the delegate on the same node, so it observes the event
    // right after the delegate handled it.
    let preventedAfterDelegate: boolean | null = null;
    root.addEventListener('click', (e) => {
      preventedAfterDelegate = e.defaultPrevented;
    });
    a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    expect(opens()).toHaveLength(1);
    expect(preventedAfterDelegate).toBe(false);
  });

  it('covers a middle click (auxclick, button 1) but not a right click', () => {
    const a = hnLink();
    a.dispatchEvent(new MouseEvent('auxclick', { bubbles: true, cancelable: true, button: 1 }));
    expect(opens()).toHaveLength(1);
    a.dispatchEvent(new MouseEvent('auxclick', { bubbles: true, cancelable: true, button: 2 }));
    expect(opens()).toHaveLength(1);
  });

  it('catches a click on an element nested inside the link', () => {
    const a = hnLink();
    const span = document.createElement('span');
    span.textContent = 'inner';
    a.appendChild(span);
    span.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    expect(opens()).toHaveLength(1);
  });

  it('falls back to the link text for the title and sends no hn without the data attributes', () => {
    link({ href: 'https://example.com/rss', target: '_blank' }, '  An RSS entry  ').dispatchEvent(
      new MouseEvent('click', { bubbles: true, cancelable: true }),
    );
    expect(lastPosted()).toEqual({
      ns: PAGE_NS,
      v: PROTOCOL_VERSION,
      type: 'condenser:open',
      url: 'https://example.com/rss',
      title: 'An RSS entry',
    });
    expect(lastPosted()).not.toHaveProperty('hn');
  });

  it('omits the title when the link has no text and no data-vr-title', () => {
    link({ href: 'https://example.com/img', target: '_blank' }, '').dispatchEvent(
      new MouseEvent('click', { bubbles: true, cancelable: true }),
    );
    expect(lastPosted()).not.toHaveProperty('title');
  });

  it('skips x.com links', () => {
    link({ href: 'https://x.com/a/status/1', target: '_blank' }).dispatchEvent(
      new MouseEvent('click', { bubbles: true, cancelable: true }),
    );
    expect(opens()).toHaveLength(0);
  });

  it('skips links that do not open a new tab', () => {
    link({ href: 'https://example.com/same-tab' }).dispatchEvent(
      new MouseEvent('click', { bubbles: true, cancelable: true }),
    );
    expect(opens()).toHaveLength(0);
  });

  it('skips a click a handler already cancelled — the tab is not going to open', () => {
    const a = hnLink();
    a.addEventListener('click', (e) => e.preventDefault());
    a.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    expect(opens()).toHaveLength(0);
  });

  it('is silent while unlinked, and again after bye', () => {
    fromBridge({ type: 'vibe-reader:link', linked: false });
    hnLink().dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    expect(opens()).toHaveLength(0);

    fromBridge({ type: 'vibe-reader:link', linked: true });
    fromBridge({ type: 'vibe-reader:bye' });
    hnLink().dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    expect(opens()).toHaveLength(0);
  });

  it('stops after uninstall', () => {
    offDelegate();
    offDelegate = () => {};
    hnLink().dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    expect(opens()).toHaveLength(0);
  });
});
