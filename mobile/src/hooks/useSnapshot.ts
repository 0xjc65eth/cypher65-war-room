import { useEffect, useCallback, useState } from 'react';
import { fetchSnapshot, fetchAlerts } from '../api/client';
import { useAppStore } from '../store';
import { useBatteryMode } from './useBatteryMode';
import { cacheSnapshot, getCachedSnapshot } from '../services/offline';

export const useSnapshot = () => {
  const { snapshot, setSnapshot, setAlerts } = useAppStore();
  const { schedule, cleanup } = useBatteryMode();
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      const [data, alerts] = await Promise.all([fetchSnapshot(), fetchAlerts()]);
      setSnapshot(data);
      setAlerts(Array.isArray(alerts) ? alerts : []);
      await cacheSnapshot(data);
    } catch (err) {
      const cached = await getCachedSnapshot();
      if (cached) {
        setSnapshot(cached.snapshot);
        setError(`Offline mode — ${(err as Error).message}`);
      } else {
        setError((err as Error).message);
      }
    } finally {
      setRefreshing(false);
    }
  }, [setSnapshot, setAlerts]);

  useEffect(() => {
    refresh();
    schedule(refresh);
    return cleanup;
  }, [refresh, schedule, cleanup]);

  return { snapshot, refreshing, error, refresh };
};
