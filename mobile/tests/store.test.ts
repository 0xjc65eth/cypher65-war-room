import { useAppStore } from '../src/store';

describe('App store', () => {
  beforeEach(() => {
    useAppStore.setState({
      auth: { token: null, isAuthenticated: false },
      devices: [],
      alerts: [],
      snapshot: null,
    });
  });

  it('updates auth token', () => {
    useAppStore.getState().setToken('abc123');
    expect(useAppStore.getState().auth.token).toBe('abc123');
    expect(useAppStore.getState().auth.isAuthenticated).toBe(true);
  });

  it('updates battery mode', () => {
    useAppStore.getState().setBatteryMode('real_time');
    expect(useAppStore.getState().batteryMode).toBe('real_time');
  });

  it('updates devices and supports partial update', () => {
    const device = {
      id: 'd1',
      name: 'Test Miner',
      model: 'Bitaxe',
      manufacturer: 'Bitaxe',
      ip_address: '192.168.1.1',
      status: 'ONLINE',
      last_seen: 0,
      current_telemetry: null,
    } as any;

    useAppStore.getState().setDevices([device]);
    expect(useAppStore.getState().devices).toHaveLength(1);

    useAppStore.getState().updateDevice({ ...device, name: 'Updated Miner' });
    expect(useAppStore.getState().devices[0].name).toBe('Updated Miner');
  });
});
