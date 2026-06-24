import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';

import '../index.css';
import { queryClient } from '@/lib/queryClient';
import { ThemeProvider } from '@/lib/theme';
import { UnreadIndicatorProvider } from '@/lib/unreadIndicator';

import { PreviewApp } from './PreviewApp';

// Dev-only preview harness. Mirrors the providers MessageCard needs (query client for
// useSaveToggle, unread-indicator + theme contexts); no router/auth gate.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <UnreadIndicatorProvider>
        <QueryClientProvider client={queryClient}>
          <PreviewApp />
        </QueryClientProvider>
      </UnreadIndicatorProvider>
    </ThemeProvider>
  </StrictMode>,
);
