import { act, renderHook } from '@testing-library/react-native';
import { useBatteryMode } from '../src/hooks/useBatteryMode';
import { useAppStore } from '../src/store';

jest.useFakeTimers();

describe('useBatteryMode', () => {
  beforeEach(() => {
    useAppStore.setState({ batteryMode: 'balanced' });
    jest.clearAllTimers();
  });

  it('does not schedule a timer in max_battery (manual only)', () => {
    useAppStore.setState({ batteryMode: 'max_battery' });
    const cb = jest.fn();
    const { result } = renderHook(() => useBatteryMode());
    act(() => {
      result.current.schedule(cb);
    });
    act(() => {
      jest.advanceTimersByTime(120000);
    });
    expect(cb).not.toHaveBeenCalled();
  });

  it('schedules 60s in balanced and 15s in real_time', () => {
    const cb = jest.fn();
    const { result, rerender } = renderHook(() => useBatteryMode());
    act(() => {
      result.current.schedule(cb);
    });
    act(() => {
      jest.advanceTimersByTime(59999);
    });
    expect(cb).not.toHaveBeenCalled();
    act(() => {
      jest.advanceTimersByTime(1);
    });
    expect(cb).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.setBatteryMode('real_time');
    });
    rerender();
    const cb2 = jest.fn();
    act(() => {
      result.current.schedule(cb2);
    });
    act(() => {
      jest.advanceTimersByTime(15000);
    });
    expect(cb2).toHaveBeenCalledTimes(1);
  });

  it('cleanup clears a running interval', () => {
    const cb = jest.fn();
    const { result } = renderHook(() => useBatteryMode());
    act(() => {
      result.current.schedule(cb);
      result.current.cleanup();
    });
    act(() => {
      jest.advanceTimersByTime(60000);
    });
    expect(cb).not.toHaveBeenCalled();
  });
});
