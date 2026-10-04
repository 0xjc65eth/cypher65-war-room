import { act, renderHook } from '@testing-library/react-native';
import { AppState, type AppStateStatus } from 'react-native';
import { useBatteryMode } from '../src/hooks/useBatteryMode';
import { useAppStore } from '../src/store';

jest.useFakeTimers();

describe('useBatteryMode', () => {
  let onChange: ((state: AppStateStatus) => void) | undefined;
  let remove: jest.Mock;

  const changeState = async (state: AppStateStatus) => {
    await act(() => {
      Object.defineProperty(AppState, 'currentState', { value: state, configurable: true });
      onChange?.(state);
    });
  };

  const advance = async (milliseconds: number) => {
    await act(async () => {
      await jest.advanceTimersByTimeAsync(milliseconds);
    });
  };

  beforeEach(() => {
    useAppStore.setState({ batteryMode: 'balanced' });
    jest.clearAllTimers();
    onChange = undefined;
    remove = jest.fn();
    Object.defineProperty(AppState, 'currentState', { value: 'active', configurable: true });
    jest.spyOn(AppState, 'addEventListener').mockImplementation((event, listener) => {
      expect(event).toBe('change');
      onChange = listener;
      return { remove };
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('does not schedule a timer in max_battery (manual only)', async () => {
    useAppStore.setState({ batteryMode: 'max_battery' });
    const cb = jest.fn();
    const { result } = await renderHook(() => useBatteryMode());
    await act(() => {
      result.current.schedule(cb);
    });
    await act(async () => {
      await jest.advanceTimersByTimeAsync(120000);
    });
    expect(cb).not.toHaveBeenCalled();
  });

  it('schedules 60s in balanced and 15s in real_time', async () => {
    const cb = jest.fn();
    const { result, rerender } = await renderHook(() => useBatteryMode());
    await act(() => {
      result.current.schedule(cb);
    });
    await act(async () => {
      await jest.advanceTimersByTimeAsync(59999);
    });
    expect(cb).not.toHaveBeenCalled();
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1);
    });
    expect(cb).toHaveBeenCalledTimes(1);

    await act(() => {
      result.current.setBatteryMode('real_time');
    });
    await rerender();
    const cb2 = jest.fn();
    await act(() => {
      result.current.schedule(cb2);
    });
    await act(async () => {
      await jest.advanceTimersByTimeAsync(15000);
    });
    expect(cb2).toHaveBeenCalledTimes(1);
  });

  it('cleanup clears a running interval', async () => {
    const cb = jest.fn();
    const { result } = await renderHook(() => useBatteryMode());
    await act(() => {
      result.current.schedule(cb);
      result.current.cleanup();
    });
    await act(async () => {
      await jest.advanceTimersByTimeAsync(60000);
    });
    expect(cb).not.toHaveBeenCalled();
  });

  it.each(['background', 'inactive', 'unknown', 'extension', null])(
    'does not start polling with initial state %s',
    async (state) => {
      Object.defineProperty(AppState, 'currentState', { value: state, configurable: true });
      const callback = jest.fn();
      const { result } = await renderHook(() => useBatteryMode());
      await act(() => result.current.schedule(callback));
      await advance(120000);
      expect(callback).not.toHaveBeenCalled();
      await changeState('active');
      expect(callback).toHaveBeenCalledTimes(1);
      await advance(60000);
      expect(callback).toHaveBeenCalledTimes(2);
    }
  );

  it('suspends immediately and catches up once on foreground', async () => {
    const callback = jest.fn();
    const { result } = await renderHook(() => useBatteryMode());
    await act(() => result.current.schedule(callback));
    await advance(59000);
    await changeState('inactive');
    await changeState('background');
    await advance(180000);
    expect(callback).not.toHaveBeenCalled();
    await changeState('active');
    await changeState('active');
    expect(callback).toHaveBeenCalledTimes(1);
    await advance(59999);
    expect(callback).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(callback).toHaveBeenCalledTimes(2);
  });

  it('does not refresh or resume timers in manual-only mode', async () => {
    useAppStore.setState({ batteryMode: 'max_battery' });
    const callback = jest.fn();
    const { result } = await renderHook(() => useBatteryMode());
    await act(() => result.current.schedule(callback));
    await changeState('background');
    await changeState('active');
    await advance(120000);
    expect(callback).not.toHaveBeenCalled();
  });

  it('re-arms mode changes without requiring the caller to schedule again', async () => {
    const callback = jest.fn();
    const { result } = await renderHook(() => useBatteryMode());
    const initialSchedule = result.current.schedule;
    await act(() => result.current.schedule(callback));
    await act(() => result.current.setBatteryMode('real_time'));
    expect(result.current.schedule).toBe(initialSchedule);
    await advance(15000);
    expect(callback).toHaveBeenCalledTimes(1);
    await act(() => result.current.setBatteryMode('max_battery'));
    await advance(120000);
    expect(callback).toHaveBeenCalledTimes(1);
    await act(() => result.current.setBatteryMode('balanced'));
    await advance(60000);
    expect(callback).toHaveBeenCalledTimes(2);
  });

  it('retains mode and latest callback changes while in background', async () => {
    const oldCallback = jest.fn();
    const latest = jest.fn();
    const { result } = await renderHook(() => useBatteryMode());
    await act(() => result.current.schedule(oldCallback));
    await changeState('background');
    await act(() => {
      result.current.setBatteryMode('real_time');
      result.current.schedule(latest);
    });
    await advance(60000);
    expect(oldCallback).not.toHaveBeenCalled();
    expect(latest).not.toHaveBeenCalled();
    await changeState('active');
    await advance(15000);
    expect(latest).toHaveBeenCalledTimes(2);
    expect(oldCallback).not.toHaveBeenCalled();
  });

  it('never overlaps asynchronous scheduled reads and coalesces resume', async () => {
    let resolve!: () => void;
    const pending = new Promise<void>((done) => { resolve = done; });
    const callback = jest.fn().mockReturnValueOnce(pending);
    const { result } = await renderHook(() => useBatteryMode());
    await act(() => result.current.schedule(callback));
    await advance(180000);
    expect(callback).toHaveBeenCalledTimes(1);
    await changeState('background');
    await changeState('active');
    await changeState('inactive');
    await changeState('active');
    expect(callback).toHaveBeenCalledTimes(1);
    await act(async () => resolve());
    expect(callback).toHaveBeenCalledTimes(2);
    await advance(60000);
    expect(callback).toHaveBeenCalledTimes(3);
  });

  it('discards queued resume on cleanup, including late read completion', async () => {
    let resolve!: () => void;
    const callback = jest.fn(() => new Promise<void>((done) => { resolve = done; }));
    const { result } = await renderHook(() => useBatteryMode());
    await act(() => result.current.schedule(callback));
    await advance(60000);
    await changeState('background');
    await changeState('active');
    await act(() => result.current.cleanup());
    await act(async () => resolve());
    await changeState('background');
    await changeState('active');
    await advance(120000);
    expect(callback).toHaveBeenCalledTimes(1);
  });

  it('removes the lifecycle listener and ignores late events after unmount', async () => {
    const callback = jest.fn();
    const { result, unmount } = await renderHook(() => useBatteryMode());
    await act(() => result.current.schedule(callback));
    await unmount();
    expect(remove).toHaveBeenCalledTimes(1);
    await changeState('background');
    await changeState('active');
    await advance(120000);
    expect(callback).not.toHaveBeenCalled();
  });

  it('does not dispatch queued catch-up after unmount with a pending read', async () => {
    let resolve!: () => void;
    const callback = jest.fn(() => new Promise<void>((done) => { resolve = done; }));
    const { result, unmount } = await renderHook(() => useBatteryMode());
    await act(() => result.current.schedule(callback));
    await advance(60000);
    await changeState('background');
    await changeState('active');
    await unmount();
    await act(async () => resolve());
    await advance(120000);
    expect(callback).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledTimes(1);
  });

  it('replaces active timers and does not replay missed background intervals', async () => {
    const oldCallback = jest.fn();
    const latest = jest.fn();
    const { result } = await renderHook(() => useBatteryMode());
    await act(() => result.current.schedule(oldCallback));
    await advance(59000);
    await act(() => result.current.schedule(latest));
    await advance(59000);
    expect(oldCallback).not.toHaveBeenCalled();
    expect(latest).not.toHaveBeenCalled();
    await advance(1000);
    expect(latest).toHaveBeenCalledTimes(1);
    await changeState('background');
    await advance(600000);
    await changeState('active');
    expect(latest).toHaveBeenCalledTimes(2);
  });

  it('recovers scheduling after callback rejection or synchronous throw', async () => {
    const callback = jest.fn()
      .mockRejectedValueOnce(new Error('network timeout'))
      .mockImplementationOnce(() => { throw new Error('read failed'); })
      .mockResolvedValue(undefined);
    const { result } = await renderHook(() => useBatteryMode());
    await act(() => result.current.schedule(callback));
    await advance(180000);
    expect(callback).toHaveBeenCalledTimes(3);
  });
});
