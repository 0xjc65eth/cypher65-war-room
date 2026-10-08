import { useCallback, useEffect, useRef } from 'react';
import { AppState, type AppStateStatus } from 'react-native';
import { useAppStore } from '../store';
import type { BatteryMode } from '../types';

const POLL_INTERVALS: Record<BatteryMode, number | null> = {
  max_battery: null, // manual only
  balanced: 60000,
  real_time: 15000,
};

type PollCallback = () => void | Promise<void>;

/**
 * Schedule read-only refreshes while the app is active, with one coalesced
 * foreground catch-up and no overlapping scheduled callbacks.
 * Callbacks own their error presentation; already-started reads are not aborted.
 * @example
 * const { schedule, cleanup } = useBatteryMode();
 * useEffect(() => { schedule(refreshSnapshot); return cleanup; }, [schedule, cleanup]);
 */
export const useBatteryMode = () => {
  const { batteryMode, setBatteryMode } = useAppStore();

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const callbackRef = useRef<PollCallback | null>(null);
  const periodRef = useRef(POLL_INTERVALS[batteryMode]);
  const stateRef = useRef<AppStateStatus | null>(AppState.currentState);
  const mountedRef = useRef(false);
  const runningRef = useRef(false);
  const resumeRef = useRef(false);

  const stopTimer = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const run = useCallback(async function invoke(): Promise<void> {
    if (
      !mountedRef.current ||
      stateRef.current !== 'active' ||
      periodRef.current === null ||
      !callbackRef.current ||
      runningRef.current
    ) {
      return;
    }
    resumeRef.current = false;
    runningRef.current = true;
    try {
      await callbackRef.current();
    } catch {
      // Refresh callbacks surface their own errors; a failed read must not
      // become an unhandled timer rejection or permanently stop scheduling.
    } finally {
      runningRef.current = false;
      if (resumeRef.current) {
        resumeRef.current = false;
        void invoke();
      }
    }
  }, []);

  const arm = useCallback(() => {
    stopTimer();
    const period = periodRef.current;
    if (mountedRef.current && stateRef.current === 'active' && callbackRef.current && period) {
      intervalRef.current = setInterval(() => void run(), period);
    }
  }, [run, stopTimer]);

  const schedule = useCallback(
    (callback: PollCallback) => {
      callbackRef.current = callback;
      resumeRef.current = false;
      arm();
    },
    [arm]
  );

  const cleanup = useCallback(() => {
    callbackRef.current = null;
    resumeRef.current = false;
    stopTimer();
  }, [stopTimer]);

  useEffect(() => {
    mountedRef.current = true;
    stateRef.current = AppState.currentState;
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (!mountedRef.current) return;
      const previousState = stateRef.current;
      stateRef.current = nextState;
      if (nextState !== 'active') {
        resumeRef.current = false;
        stopTimer();
      } else if (previousState !== 'active') {
        arm();
        if (callbackRef.current && periodRef.current !== null) {
          if (runningRef.current) resumeRef.current = true;
          else void run();
        }
      }
    });
    return () => {
      mountedRef.current = false;
      cleanup();
      subscription.remove();
    };
  }, [arm, cleanup, run, stopTimer]);

  useEffect(() => {
    periodRef.current = POLL_INTERVALS[batteryMode];
    resumeRef.current = false;
    arm();
  }, [arm, batteryMode]);

  return { batteryMode, setBatteryMode, schedule, cleanup };
};
