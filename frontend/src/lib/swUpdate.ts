// PWA background-update flow. The service worker precaches the app shell, so an
// installed app opens instantly from local cache; meanwhile the browser refetches
// sw.js in the background. When a new build is waiting, we surface a toast and
// only activate + reload after the user confirms — the prompt-mode answer to
// "SW caching must not delay deploys" (the reason d2df229 shipped without one).

export const UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000;

// The slice of vite-plugin-pwa's `registerSW` contract we use, plus the document
// subset we listen on — both injectable for tests (the real module is virtual and
// only exists inside a Vite build).
export interface SWRegistrationLike {
  update(): Promise<unknown>;
}

export interface RegisterSWOptions {
  onNeedRefresh?: () => void;
  onRegisteredSW?: (swUrl: string, registration: SWRegistrationLike | undefined) => void;
}

export type RegisterSW = (options: RegisterSWOptions) => (reloadPage?: boolean) => Promise<void>;

export interface SWDocument {
  visibilityState: string;
  addEventListener(type: 'visibilitychange', cb: () => void): void;
}

export interface SetupUpdatePromptOptions {
  registerSW: RegisterSW;
  /** Show the "new version available" toast; call `confirm` when the user accepts. */
  showUpdateToast: (confirm: () => void) => void;
  doc?: SWDocument;
  checkIntervalMs?: number;
}

export function setupUpdatePrompt({
  registerSW,
  showUpdateToast,
  doc = document,
  checkIntervalMs = UPDATE_CHECK_INTERVAL_MS,
}: SetupUpdatePromptOptions): void {
  let prompted = false;
  const updateSW = registerSW({
    onNeedRefresh() {
      if (prompted) return;
      prompted = true;
      showUpdateToast(() => {
        void updateSW(true);
      });
    },
    onRegisteredSW(_swUrl, registration) {
      if (!registration) return;
      const check = () => {
        registration.update().catch(() => {
          // Offline or a transient server error — the next check will try again.
        });
      };
      setInterval(check, checkIntervalMs);
      // A long-lived PWA window rarely reloads, so "the user opened the app" is
      // usually a visibility change, not a navigation — check on each return.
      doc.addEventListener('visibilitychange', () => {
        if (doc.visibilityState === 'visible') check();
      });
    },
  });
}
