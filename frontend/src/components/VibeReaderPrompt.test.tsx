// The "Vibe Reader detected — link up?" toast (plan 2026-09-02 §2.2). Rendered
// against the real sonner Toaster so the actions are the buttons a reader clicks.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Toaster } from 'sonner';

import { BRIDGE_NS, PAGE_NS, PROTOCOL_VERSION, listenToBridge, resetForTests } from '@/lib/vibeReader';

import { VIBE_READER_PROMPT_KEY, VibeReaderPrompt } from './VibeReaderPrompt';

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

let posted: unknown[];
let offBridge: () => void;

beforeEach(() => {
  localStorage.clear();
  resetForTests();
  posted = [];
  vi.spyOn(window, 'postMessage').mockImplementation((msg: unknown) => {
    posted.push(msg);
  });
  offBridge = listenToBridge();
});

afterEach(() => {
  offBridge();
  vi.restoreAllMocks();
});

function renderPrompt() {
  return render(
    <>
      <VibeReaderPrompt />
      <Toaster />
    </>,
  );
}

describe('VibeReaderPrompt', () => {
  it('shows nothing until the bridge says hello', () => {
    renderPrompt();
    expect(screen.queryByText('检测到 Vibe Reader')).toBeNull();
  });

  it('prompts on the first hello when the link is off', async () => {
    renderPrompt();
    fromBridge({ type: 'vibe-reader:hello', linked: false });
    expect(await screen.findByText('检测到 Vibe Reader')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开启' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '不再提示' })).toBeInTheDocument();
  });

  it('开启 asks the extension to link — the toast does not flip the state itself', async () => {
    renderPrompt();
    fromBridge({ type: 'vibe-reader:hello', linked: false });
    await userEvent.click(await screen.findByRole('button', { name: '开启' }));
    expect(posted).toContainEqual({ ns: PAGE_NS, v: PROTOCOL_VERSION, type: 'condenser:set-link', linked: true });
    expect(localStorage.getItem(VIBE_READER_PROMPT_KEY)).toBeNull();
  });

  it('不再提示 remembers the dismissal, and a fresh mount no longer prompts', async () => {
    const first = renderPrompt();
    fromBridge({ type: 'vibe-reader:hello', linked: false });
    await userEvent.click(await screen.findByRole('button', { name: '不再提示' }));
    expect(localStorage.getItem(VIBE_READER_PROMPT_KEY)).toBe('dismissed');
    expect(posted.find((m) => (m as { type: string }).type === 'condenser:set-link')).toBeUndefined();
    first.unmount();

    resetForTests();
    renderPrompt();
    fromBridge({ type: 'vibe-reader:hello', linked: false });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.queryByText('检测到 Vibe Reader')).toBeNull();
  });

  it('does not prompt when the extension reports the link already on', async () => {
    renderPrompt();
    fromBridge({ type: 'vibe-reader:hello', linked: true });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.queryByText('检测到 Vibe Reader')).toBeNull();
  });

  it('prompts once per page load even if the bridge reconnects', async () => {
    renderPrompt();
    fromBridge({ type: 'vibe-reader:hello', linked: false });
    await screen.findByText('检测到 Vibe Reader');
    fromBridge({ type: 'vibe-reader:bye' });
    fromBridge({ type: 'vibe-reader:hello', linked: false });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getAllByText('检测到 Vibe Reader')).toHaveLength(1);
  });
});
