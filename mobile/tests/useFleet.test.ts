import { renderHook, waitFor, act } from '@testing-library/react-native';
import { useFleet } from '../src/hooks/useFleet';
import * as client from '../src/api/client';
import { useAppStore } from '../src/store';

jest.mock('../src/api/client', () => ({
  fetchDevices: jest.fn(),
  fetchFleetSummary: jest.fn(),
  fetchDevice: jest.fn(),
  refreshDevice: jest.fn(),
}));

describe('useFleet', () => {
  beforeEach(() => {
    useAppStore.setState({
      devices: [],
      fleetSummary: null,
    });
  });

  it('loads devices and fleet summary', async () => {
    const devices = [{ id: 'd1', name: 'Miner 1' }] as any;
    const summary = { total: 1, total_hashrate: 1e12 } as any;

    (client.fetchDevices as jest.Mock).mockResolvedValue({ devices });
    (client.fetchFleetSummary as jest.Mock).mockResolvedValue(summary);

    const { result } = renderHook(() => useFleet());

    await waitFor(() => {
      expect(result.current.devices).toHaveLength(1);
      expect(result.current.fleetSummary).toEqual(summary);
    });
  });

  it('refreshes a device and updates the store', async () => {
    // Isolate this test: the previous test's fetchDevices mock would otherwise
    // resolve with 'Miner 1' and clobber the store. Return the SAME device the
    // store starts with so the hook's initial load() keeps it in place, then
    // the refresh swaps in the updated device.
    const old = { id: 'd1', name: 'Old' } as any;
    (client.fetchDevices as jest.Mock).mockResolvedValue({ devices: [old] });
    (client.fetchFleetSummary as jest.Mock).mockResolvedValue({ total: 1 } as any);
    const updated = { id: 'd1', name: 'Updated' } as any;
    (client.refreshDevice as jest.Mock).mockResolvedValue({ success: true, device: updated });
    useAppStore.setState({ devices: [old] });

    const { result } = renderHook(() => useFleet());

    // Wait for the initial load() to settle so it can't race the refresh.
    await waitFor(() => {
      expect(useAppStore.getState().devices[0].name).toBe('Old');
    });

    await act(async () => {
      await result.current.refresh('d1');
    });

    expect(useAppStore.getState().devices[0].name).toBe('Updated');
  });
});
