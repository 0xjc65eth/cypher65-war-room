import { useEffect, useState, type PropsWithChildren } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useAppStore } from '../store';

/**
 * One query cache per keyed session subtree. Clear synchronously on identity
 * change; cancellation is best effort, never proof a remote action was undone.
 * @example <SessionBoundary key={revision}>{children}</SessionBoundary>
 */
export function SessionBoundary({ children }: PropsWithChildren) {
  const [client] = useState(() => new QueryClient());
  useEffect(() => {
    const clear = () => {
      void client.cancelQueries().catch(() => undefined);
      client.clear();
    };
    const unsubscribe = useAppStore.subscribe((state, previous) => {
      if (state.authRevision !== previous.authRevision) clear();
    });
    return () => { unsubscribe(); clear(); };
  }, [client]);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
