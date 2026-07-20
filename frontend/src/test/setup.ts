import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// RTL auto-cleanup relies on a global afterEach; we don't enable vitest globals,
// so wire it up explicitly.
afterEach(() => {
  cleanup();
});

// jsdom 29 delegates localStorage to Node's WebStorage, which is inert under
// vitest (no --localstorage-file → no clear/getItem methods). Substitute a
// plain in-memory Storage so hooks that persist state are testable.
class MemoryStorage implements Storage {
  private map = new Map<string, string>();
  get length() {
    return this.map.size;
  }
  clear() {
    this.map.clear();
  }
  getItem(key: string) {
    return this.map.has(key) ? this.map.get(key)! : null;
  }
  key(index: number) {
    return [...this.map.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.map.delete(key);
  }
  setItem(key: string, value: string) {
    this.map.set(key, String(value));
  }
}
if (typeof window.localStorage?.clear !== 'function') {
  const storage = new MemoryStorage();
  Object.defineProperty(window, 'localStorage', { value: storage, writable: true });
  Object.defineProperty(globalThis, 'localStorage', { value: storage, writable: true });
}

// jsdom is missing a few DOM APIs that Radix UI (Popover/Popper) reaches for.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
