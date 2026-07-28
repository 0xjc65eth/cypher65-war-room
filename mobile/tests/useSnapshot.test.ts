import { renderHook, waitFor } from '@testing-library/react-native';
import { useSnapshot } from '../src/hooks/useSnapshot';
import * as client from '../src/api/client';
import { useAppStore } from '../src/store';

jest.mock('../src/api/client', () => ({
  fetchSnapshot: jest.fn(),
  fetchAlerts: jest.fn(),
}));

jest.useFakeTimers();

describe('useSnapshot', () => {
  beforeEach(() => {
    useAppStore.setState({ snapshot: null, alerts: [] });
    jest.clearAllMocks();
  });

  it('fetches snapshot and alerts on mount', async () => {
    (client.fetchSnapshot as jest.Mock).mockResolvedValue({ ts: 123, worker: {} });
    (client.fetchAlerts as jest.Mock).mockResolvedValue([{ id: 1, severity: 'CRIT' }]);

    renderHook(() => useSnapshot());

    await waitFor(() => {
      expect(useAppStore.getState().snapshot).toEqual({ ts: 123, worker: {} });
      expect(useAppStore.getState().alerts).toHaveLength(1);
    });
  });
});
