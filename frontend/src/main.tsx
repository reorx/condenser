import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';

import App from './App';
import './index.css';
import { Toaster } from './components/ui/sonner';
import { queryClient } from './lib/queryClient';
import { ThemeProvider } from './lib/theme';
import { UnreadIndicatorProvider } from './lib/unreadIndicator';

// react-grab: lets coding agents grab a UI element's source context (hover + ⌘/Ctrl+C).
// Dev-only dynamic import so it's tree-shaken out of the production bundle.
if (import.meta.env.DEV) {
  import('react-grab');
}

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
