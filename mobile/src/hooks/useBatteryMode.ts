import { useCallback, useEffect, useRef } from 'react';
import { useAppStore } from '../store';
import type { BatteryMode } from '../types';

const POLL_INTERVALS: Record<BatteryMode, number | null> = {
  max_battery: null, // manual only
  balanced: 60000,
  real_time: 15000,
};

export const useBatteryMode = () => {
  const { batteryMode, setBatteryMode } = useAppStore();

  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const schedule = useCallback(
    (callback: () => void) => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }

      const interval = POLL_INTERVALS[batteryMode];
      if (interval) {
        intervalRef.current = setInterval(callback, interval);
      }
    },
    [batteryMode]
  );

  const cleanup = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    return cleanup;
  }, [cleanup]);

  return { batteryMode, setBatteryMode, schedule, cleanup };
};
