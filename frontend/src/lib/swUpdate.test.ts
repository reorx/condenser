import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { setupUpdatePrompt, UPDATE_CHECK_INTERVAL_MS, type RegisterSWOptions, type SWDocument } from './swUpdate';

function makeHarness({ registration }: { registration?: { update: () => Promise<void> } | undefined } = {}) {
  const listeners: Array<() => void> = [];
  const doc: SWDocument & { visibilityState: string } = {
    visibilityState: 'visible',
    addEventListener: (_type, cb) => listeners.push(cb),
  };
  const updateSW = vi.fn(() => Promise.resolve());
  let captured: RegisterSWOptions | undefined;
  const registerSW = vi.fn((options: RegisterSWOptions) => {
    captured = options;
    return updateSW;
  });
  const showUpdateToast = vi.fn<(confirm: () => void) => void>();

  setupUpdatePrompt({ registerSW, showUpdateToast, doc });
  if (registration !== null) {
    captured?.onRegisteredSW?.('/sw.js', registration);
  }

  return {
    options: captured!,
    updateSW,
    showUpdateToast,
    setVisibility(state: string) {
      doc.visibilityState = state;
      for (const cb of listeners) cb();
    },
  };
}

describe('setupUpdatePrompt', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows the update toast when a new version is waiting', () => {
    const h = makeHarness();
    h.options.onNeedRefresh?.();
    expect(h.showUpdateToast).toHaveBeenCalledTimes(1);
  });

  it('activates the new version and reloads when the user confirms', () => {
    const h = makeHarness();
    h.options.onNeedRefresh?.();
    const confirm = h.showUpdateToast.mock.calls[0][0];
    confirm();
    expect(h.updateSW).toHaveBeenCalledWith(true);
  });

  it('prompts only once even if the worker reports twice', () => {
    const h = makeHarness();
    h.options.onNeedRefresh?.();
    h.options.onNeedRefresh?.();
    expect(h.showUpdateToast).toHaveBeenCalledTimes(1);
  });

  it('checks for updates periodically in the background', async () => {
    const update = vi.fn(() => Promise.resolve());
    makeHarness({ registration: { update } });
    expect(update).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(UPDATE_CHECK_INTERVAL_MS);
    expect(update).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(UPDATE_CHECK_INTERVAL_MS);
    expect(update).toHaveBeenCalledTimes(2);
  });

  it('checks for updates when the window becomes visible again', () => {
    const update = vi.fn(() => Promise.resolve());
    const h = makeHarness({ registration: { update } });
    h.setVisibility('hidden');
    expect(update).not.toHaveBeenCalled();
    h.setVisibility('visible');
    expect(update).toHaveBeenCalledTimes(1);
  });

  it('survives a failing update check (e.g. offline)', async () => {
    const update = vi.fn(() => Promise.reject(new Error('offline')));
    const h = makeHarness({ registration: { update } });
    h.setVisibility('visible');
    await vi.advanceTimersByTimeAsync(0);
    expect(update).toHaveBeenCalled();
  });

  it('tolerates a browser that yields no registration', () => {
    const h = makeHarness({ registration: undefined });
    expect(() => h.setVisibility('visible')).not.toThrow();
  });
});
