// The Phase D badge (plan 2026-09-02 §5): the Vibe Reader extension's progress on
// the pages a card links to, painted on the time line beside `ForwardedBadge`. The
// bridge is simulated the way `vibeReader.test.ts` does it — a MessageEvent from
// this very window under the bridge's namespace.
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act, render, screen } from '@testing-library/react';

import { BRIDGE_NS, PROTOCOL_VERSION, listenToBridge, resetForTests } from '@/lib/vibeReader';

import { VibeReaderBadge } from './VibeReaderBadge';

function fromBridge(msg: Record<string, unknown>) {
  act(() => {
    window.dispatchEvent(
      new MessageEvent('message', {
        data: { ns: BRIDGE_NS, v: PROTOCOL_VERSION, ...msg },
        origin: window.location.origin,
        source: window,
      }),
    );
  });
}

const URL = 'https://example.com/post';
let off: () => void = () => {};

beforeEach(() => {
  resetForTests();
  off = listenToBridge();
  fromBridge({ type: 'vibe-reader:hello', linked: true });
});

afterEach(() => off());

describe('VibeReaderBadge', () => {
  it('renders nothing while the extension has said nothing about the page', () => {
    const { container } = render(<VibeReaderBadge urls={[URL]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('spins through queued / extracting / generating, naming the step', () => {
    const { container } = render(<VibeReaderBadge urls={[URL]} />);
    fromBridge({ type: 'vibe-reader:status', url: URL, state: 'queued' });
    expect(screen.getByLabelText('Vibe Reader 排队中')).toBeInTheDocument();
    expect(container.querySelector('.animate-spin')).not.toBeNull();

    fromBridge({ type: 'vibe-reader:status', url: URL, state: 'extracting' });
    expect(screen.getByLabelText('Vibe Reader 正在提取正文')).toBeInTheDocument();

    fromBridge({ type: 'vibe-reader:status', url: URL, state: 'generating' });
    expect(screen.getByLabelText('Vibe Reader 正在生成')).toBeInTheDocument();
    expect(container.querySelector('.animate-spin')).not.toBeNull();
  });

  it('shows the lightning once done, with the modes when the extension named them', () => {
    const { container } = render(<VibeReaderBadge urls={[URL]} />);
    fromBridge({ type: 'vibe-reader:status', url: URL, state: 'done', modes: ['summary', 'discussion'] });
    expect(screen.getByLabelText('Vibe Reader 已就绪 · summary, discussion')).toBeInTheDocument();
    expect(container.querySelector('.animate-spin')).toBeNull();

    fromBridge({ type: 'vibe-reader:status', url: URL, state: 'done' });
    expect(screen.getByLabelText('Vibe Reader 已就绪')).toBeInTheDocument();
  });

  it('names an error and stops spinning', () => {
    const { container } = render(<VibeReaderBadge urls={[URL]} />);
    fromBridge({ type: 'vibe-reader:status', url: URL, state: 'generating' });
    fromBridge({ type: 'vibe-reader:status', url: URL, state: 'error' });
    expect(screen.getByLabelText('Vibe Reader 生成失败')).toBeInTheDocument();
    expect(container.querySelector('.animate-spin')).toBeNull();
  });

  it('follows whichever of the card\'s links the reader touched last', () => {
    const comments = 'https://news.ycombinator.com/item?id=1';
    render(<VibeReaderBadge urls={[URL, comments]} />);
    fromBridge({ type: 'vibe-reader:status', url: URL, state: 'done' });
    fromBridge({ type: 'vibe-reader:status', url: comments, state: 'extracting' });
    expect(screen.getByLabelText('Vibe Reader 正在提取正文')).toBeInTheDocument();
  });

  it('disappears when the sidepanel closes', () => {
    const { container } = render(<VibeReaderBadge urls={[URL]} />);
    fromBridge({ type: 'vibe-reader:status', url: URL, state: 'generating' });
    fromBridge({ type: 'vibe-reader:bye' });
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for a card without links', () => {
    fromBridge({ type: 'vibe-reader:status', url: URL, state: 'done' });
    const { container } = render(<VibeReaderBadge urls={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
