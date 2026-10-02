import { act, renderHook } from '@testing-library/react-native';
import { useBatteryMode } from '../src/hooks/useBatteryMode';
import { useAppStore } from '../src/store';

jest.useFakeTimers();

describe('useBatteryMode', () => {
  beforeEach(() => {
    useAppStore.setState({ batteryMode: 'balanced' });
    jest.clearAllTimers();
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
});
