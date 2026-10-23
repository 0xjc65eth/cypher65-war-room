import { useEffect, useState, useCallback } from 'react';
import { fetchDevices, fetchDevice, refreshDevice, fetchFleetSummary } from '../api/client';
import { useAppStore } from '../store';
import type { Device } from '../types';
import { useSessionScope } from './useSessionScope';

/**
 * Read fleet data only while this render's session and mount remain active.
 * @example const { devices, refresh } = useFleet();
 */
export const useFleet = () => {
  const { devices, setDevices, fleetSummary, setFleetSummary } = useAppStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scope = useSessionScope();

  const load = useCallback(async () => {
    if (!scope.isActive()) return;
    setLoading(true);
    setError(null);
    try {
      const [devicesData, summaryData] = await Promise.all([fetchDevices(), fetchFleetSummary()]);
      if (!scope.isActive()) return;
      setDevices(devicesData.devices);
      setFleetSummary(summaryData);
    } catch (err) {
      if (scope.isActive()) setError((err as Error).message);
    } finally {
      if (scope.isActive()) setLoading(false);
    }
  }, [setDevices, setFleetSummary, scope]);

  const refresh = useCallback(
    async (deviceId: string) => {
      if (!scope.isActive()) return { success: false, error: 'A sessão mudou. Entre novamente.' };
      try {
        const result = await refreshDevice(deviceId);
        if (!scope.isActive()) return { success: false, error: 'A sessão mudou. Entre novamente.' };
        if (result.success) {
          useAppStore.getState().updateDevice(result.device);
        }
        return result;
      } catch (err) {
        return { success: false, error: scope.isActive() ? (err as Error).message : 'A sessão mudou. Entre novamente.' };
      }
    },
    [scope]
  );

  const getDevice = useCallback(async (deviceId: string): Promise<Device | null> => {
    if (!scope.isActive()) return null;
    try {
      const result = await fetchDevice(deviceId);
      return scope.isActive() ? result.device ?? null : null;
    } catch (err) {
      if (scope.isActive()) setError((err as Error).message);
      return null;
    }
  }, [scope]);

  useEffect(() => {
    load();
  }, [load]);

  return { devices, fleetSummary, loading, error, load, refresh, getDevice };
};
