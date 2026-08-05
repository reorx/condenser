import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { toast } from 'sonner';
import { registerSW } from 'virtual:pwa-register';

import App from './App';
import './index.css';
import { Toaster } from './components/ui/sonner';
import { initPwaWindow } from './lib/pwa';
import { setupUpdatePrompt } from './lib/swUpdate';
import { queryClient } from './lib/queryClient';
import { ThemeProvider } from './lib/theme';
import { UnreadIndicatorProvider } from './lib/unreadIndicator';

// react-grab: lets coding agents grab a UI element's source context (hover + ⌘/Ctrl+C).
// Dev-only dynamic import so it's tree-shaken out of the production bundle.
if (import.meta.env.DEV) {
  import('react-grab');
}

// Installed as a desktop PWA → snap the window to a phone-sized column.
initPwaWindow();

// Background update flow: the SW-cached shell renders first, a new build found
// in the background raises a persistent toast, and confirming reloads onto the
// new version. No-op in dev (the SW is only generated for production builds).
setupUpdatePrompt({
  registerSW,
  showUpdateToast: (confirm) => {
    toast('发现新版本', {
      description: '点击更新以加载最新版本',
      duration: Infinity,
      action: { label: '更新', onClick: confirm },
    });
  },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <UnreadIndicatorProvider>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
            <Toaster />
          </BrowserRouter>
        </QueryClientProvider>
      </UnreadIndicatorProvider>
    </ThemeProvider>
  </StrictMode>,
);
