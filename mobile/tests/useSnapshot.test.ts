import { act, renderHook, waitFor } from '@testing-library/react-native';
import { AppState, type AppStateStatus } from 'react-native';
import { useSnapshot } from '../src/hooks/useSnapshot';
import * as client from '../src/api/client';
import * as offline from '../src/services/offline';
import { useAppStore } from '../src/store';

jest.mock('../src/api/client', () => ({
  fetchSnapshot: jest.fn(),
  fetchAlerts: jest.fn(),
}));

jest.mock('../src/services/offline', () => ({
  cacheSnapshot: jest.fn(),
  getCachedSnapshot: jest.fn(),
}));

jest.useFakeTimers();

describe('useSnapshot', () => {
  let onChange: ((state: AppStateStatus) => void) | undefined;

  beforeEach(() => {
    useAppStore.setState({ snapshot: null, alerts: [], batteryMode: 'balanced' });
    jest.clearAllMocks();
    jest.clearAllTimers();
    Object.defineProperty(AppState, 'currentState', { value: 'active', configurable: true });
    jest.spyOn(AppState, 'addEventListener').mockImplementation((_event, listener) => {
      onChange = listener;
      return { remove: jest.fn() };
    });
    (offline.getCachedSnapshot as jest.Mock).mockResolvedValue(null);
    (offline.cacheSnapshot as jest.Mock).mockResolvedValue(undefined);
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('fetches snapshot and alerts on mount', async () => {
    (client.fetchSnapshot as jest.Mock).mockResolvedValue({ ts: 123, worker: {} });
    (client.fetchAlerts as jest.Mock).mockResolvedValue([{ id: 1, severity: 'CRIT' }]);

    await renderHook(() => useSnapshot());

    await waitFor(() => {
      expect(useAppStore.getState().snapshot).toEqual({ ts: 123, worker: {} });
      expect(useAppStore.getState().alerts).toHaveLength(1);
    });
    expect(offline.cacheSnapshot).toHaveBeenCalledWith({ ts: 123, worker: {} });
  });

  it('treats a non-array alerts payload as empty', async () => {
    (client.fetchSnapshot as jest.Mock).mockResolvedValue({ ts: 1 });
    (client.fetchAlerts as jest.Mock).mockResolvedValue({ not: 'an-array' });
    await renderHook(() => useSnapshot());
    await waitFor(() => {
      expect(useAppStore.getState().snapshot).toEqual({ ts: 1 });
    });
    expect(useAppStore.getState().alerts).toEqual([]);
  });

  it('falls back to the cached snapshot when the network fails', async () => {
    (client.fetchSnapshot as jest.Mock).mockRejectedValue(new Error('network down'));
    (client.fetchAlerts as jest.Mock).mockRejectedValue(new Error('network down'));
    (offline.getCachedSnapshot as jest.Mock).mockResolvedValue({
      snapshot: { ts: 9 },
      ts: 9,
    });
    const { result } = await renderHook(() => useSnapshot());
    await waitFor(() => {
      expect(useAppStore.getState().snapshot).toEqual({ ts: 9 });
    });
    expect(result.current.error).toMatch(/Offline mode/);
  });

  it('surfaces the raw error when there is no cache', async () => {
    (client.fetchSnapshot as jest.Mock).mockRejectedValue(new Error('unreachable'));
    (client.fetchAlerts as jest.Mock).mockRejectedValue(new Error('unreachable'));
    (offline.getCachedSnapshot as jest.Mock).mockResolvedValue(null);
    const { result } = await renderHook(() => useSnapshot());
    await waitFor(() => {
      expect(result.current.error).toBe('unreachable');
    });
    expect(useAppStore.getState().snapshot).toBeNull();
  });

  it('uses lifecycle-aware polling without refetching on battery-mode changes', async () => {
    (client.fetchSnapshot as jest.Mock).mockResolvedValue({ ts: 1 });
    (client.fetchAlerts as jest.Mock).mockResolvedValue([]);
    await renderHook(() => useSnapshot());
    await waitFor(() => expect(useAppStore.getState().snapshot).toEqual({ ts: 1 }));
    expect(client.fetchSnapshot).toHaveBeenCalledTimes(1);

    await act(() => onChange?.('background'));
    await act(() => useAppStore.getState().setBatteryMode('real_time'));
    await act(async () => { await jest.advanceTimersByTimeAsync(120000); });
    expect(client.fetchSnapshot).toHaveBeenCalledTimes(1);
    expect(client.fetchAlerts).toHaveBeenCalledTimes(1);

    (client.fetchSnapshot as jest.Mock).mockResolvedValue({ ts: 2 });
    await act(() => onChange?.('active'));
    await waitFor(() => expect(useAppStore.getState().snapshot).toEqual({ ts: 2 }));
    expect(client.fetchSnapshot).toHaveBeenCalledTimes(2);
    expect(client.fetchAlerts).toHaveBeenCalledTimes(2);
    await act(async () => { await jest.advanceTimersByTimeAsync(15000); });
    expect(client.fetchSnapshot).toHaveBeenCalledTimes(3);
    expect(client.fetchAlerts).toHaveBeenCalledTimes(3);
  });
});
