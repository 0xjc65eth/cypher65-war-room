import { useEffect, useCallback, useState } from 'react';
import { fetchSnapshot, fetchAlerts } from '../api/client';
import { useAppStore } from '../store';
import { useBatteryMode } from './useBatteryMode';
import { cacheSnapshot, getCachedSnapshot } from '../services/offline';
import { useSessionScope } from './useSessionScope';

const accessDenied = (error: unknown): boolean => {
  if (!error || typeof error !== 'object' || !('response' in error)) return false;
  const response = error.response;
  return !!response && typeof response === 'object' && 'status' in response &&
    (response.status === 401 || response.status === 403);
};

/**
 * Poll and restore owner-bound observations, never using cache after 401/403.
 * @example const { snapshot, refresh } = useSnapshot();
 */
export const useSnapshot = () => {
  const { snapshot, setSnapshot, setAlerts } = useAppStore();
  const { schedule, cleanup } = useBatteryMode();
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scope = useSessionScope();

  const refresh = useCallback(async () => {
    if (!scope.isActive()) return;
    setRefreshing(true);
    setError(null);
    try {
      const [data, alerts] = await Promise.all([fetchSnapshot(), fetchAlerts()]);
      if (!scope.isActive()) return;
      setSnapshot(data);
      setAlerts(Array.isArray(alerts) ? alerts : []);
      await cacheSnapshot(data, scope.lease);
    } catch (err) {
      if (!scope.isActive()) return;
      if (accessDenied(err)) {
        setError('Acesso não autorizado. Entre novamente.');
        return;
      }
      const cached = await getCachedSnapshot(scope.lease);
      if (!scope.isActive()) return;
      if (cached) {
        setSnapshot(cached.snapshot);
        setError(`Modo offline — ${(err as Error).message}`);
      } else {
        setError((err as Error).message);
      }
    } finally {
      if (scope.isActive()) setRefreshing(false);
    }
  }, [setSnapshot, setAlerts, scope]);

  useEffect(() => {
    refresh();
    schedule(refresh);
    return cleanup;
  }, [refresh, schedule, cleanup]);

  return { snapshot, refreshing, error, refresh };
};
