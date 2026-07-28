import { useEffect, useState, useCallback } from 'react';
import { fetchDevices, fetchDevice, refreshDevice, fetchFleetSummary } from '../api/client';
import { useAppStore } from '../store';
import type { Device } from '../types';

export const useFleet = () => {
  const { devices, setDevices, fleetSummary, setFleetSummary } = useAppStore();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [devicesData, summaryData] = await Promise.all([fetchDevices(), fetchFleetSummary()]);
      setDevices(devicesData.devices);
      setFleetSummary(summaryData);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [setDevices, setFleetSummary]);

  const refresh = useCallback(
    async (deviceId: string) => {
      try {
        const result = await refreshDevice(deviceId);
        if (result.success) {
          setDevices(devices.map((d) => (d.id === deviceId ? result.device : d)));
        }
        return result;
      } catch (err) {
        return { success: false, error: (err as Error).message };
      }
    },
    [devices, setDevices]
  );

  const getDevice = useCallback(async (deviceId: string): Promise<Device | null> => {
    try {
      const result = await fetchDevice(deviceId);
      return result.device ?? null;
    } catch (err) {
      setError((err as Error).message);
      return null;
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { devices, fleetSummary, loading, error, load, refresh, getDevice };
};
