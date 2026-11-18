import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { ErrorBoundary } from './components/ErrorBoundary';
import { queryClient, AuthProvider } from './state';
import { BrandProvider } from './state/brand/BrandProvider';
import { router } from './router';
import { installProjectFetch } from './state/project/viewProject';
import './index.css';

// Before anything renders: tag Ruth API requests with the viewed project
// (?project=...), so the first requests after a reload are already right.
installProjectFetch();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrandProvider>
          <AuthProvider>
            <RouterProvider router={router} />
          </AuthProvider>
        </BrandProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>
);
