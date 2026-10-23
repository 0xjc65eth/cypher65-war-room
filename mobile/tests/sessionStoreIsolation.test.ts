import { useAppStore } from '../src/store';
import type { Device, Alert, FleetSummary, BlockHuntData, MarketOffer } from '../src/types';

const privateData = {
  devices: [{ id: 'private-device-a' }] as Device[],
  fleetSummary: { privateMarker: 'summary-a' } as unknown as FleetSummary,
  alerts: [{ id: 'private-alert-a' }] as unknown as Alert[],
  snapshot: { privateMarker: 'snapshot-a' },
  blockHunt: { privateMarker: 'block-a' } as unknown as BlockHuntData,
  marketOffers: [{ privateMarker: 'offer-a' }] as unknown as MarketOffer[],
  aiContext: { privateMarker: 'context-a' },
};

describe('private store session boundary', () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    useAppStore.getState().setToken('fixture-account-a');
    useAppStore.setState({ ...privateData, batteryMode: 'max_battery' });
  });

  it.each(['logout', 'switch', 'expire'] as const)(
    'clears every private field synchronously on %s',
    (operation) => {
      const { logout, setToken } = useAppStore.getState();
      if (operation === 'logout') logout();
      else setToken(operation === 'switch' ? 'fixture-account-b' : null);
      const state = useAppStore.getState();
      expect(state.devices).toEqual([]);
      expect(state.fleetSummary).toBeNull();
      expect(state.alerts).toEqual([]);
      expect(state.snapshot).toBeNull();
      expect(state.blockHunt).toBeNull();
      expect(state.marketOffers).toEqual([]);
      expect(state.aiContext).toEqual({});
      expect(state.batteryMode).toBe('max_battery');
    }
  );

  it('does not discard current private data on same-token hydration', () => {
    useAppStore.getState().setToken('fixture-account-a');
    expect(useAppStore.getState().snapshot).toEqual(privateData.snapshot);
  });

  it('clears values written through every public private-state setter', () => {
    const store = useAppStore.getState();
    store.setDevices(privateData.devices);
    store.updateDevice({ ...privateData.devices[0], name: 'Fixture private name' });
    store.setFleetSummary(privateData.fleetSummary);
    store.setAlerts(privateData.alerts);
    store.setSnapshot(privateData.snapshot);
    store.setBlockHunt(privateData.blockHunt);
    store.setMarketOffers(privateData.marketOffers);
    store.setAiContext(privateData.aiContext);
    store.setPushCategories({ temperature: false });
    store.setBatteryMode('max_battery');
    expect(useAppStore.getState().devices[0].name).toBe('Fixture private name');
    store.logout();
    const state = useAppStore.getState();
    expect(state.devices).toEqual([]);
    expect(state.fleetSummary).toBeNull();
    expect(state.alerts).toEqual([]);
    expect(state.snapshot).toBeNull();
    expect(state.blockHunt).toBeNull();
    expect(state.marketOffers).toEqual([]);
    expect(state.aiContext).toEqual({});
    expect(state.pushCategories.temperature).toBe(true);
    expect(state.batteryMode).toBe('max_battery');
  });
});
