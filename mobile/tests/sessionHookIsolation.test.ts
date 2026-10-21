import { act, cleanup, renderHook, waitFor } from '@testing-library/react-native';
import { AxiosError, AxiosHeaders } from 'axios';
import * as client from '../src/api/client';
import { useCommands } from '../src/hooks/useCommands';
import { useFleet } from '../src/hooks/useFleet';
import { useSnapshot } from '../src/hooks/useSnapshot';
import * as offline from '../src/services/offline';
import { useAppStore } from '../src/store';
import type { Alert, Device, FleetSummary } from '../src/types';

// Keep the real store, hooks, session checks and polling lifecycle. Only the
// external API and cache boundaries return controlled synthetic fixture data.
jest.mock('../src/api/client', () => ({
  fetchSnapshot: jest.fn(),
  fetchAlerts: jest.fn(),
  fetchDevices: jest.fn(),
  fetchFleetSummary: jest.fn(),
  fetchDevice: jest.fn(),
  refreshDevice: jest.fn(),
  sendDeviceCommand: jest.fn(),
  requestDeviceCommandConfirmation: jest.fn(),
  fetchCommandHistory: jest.fn(),
  fetchDeviceCommandStatus: jest.fn(),
}));
jest.mock('../src/services/offline', () => ({
  cacheSnapshot: jest.fn(),
  getCachedSnapshot: jest.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

const deviceA: Device = {
  id: 'fixture-device-a', name: 'Private A', model: 'fixture',
  manufacturer: 'fixture', ip_address: '192.0.2.1', status: 'ONLINE',
  last_seen: 1, current_telemetry: null,
};
const deviceB: Device = { ...deviceA, id: 'fixture-device-b', name: 'Private B' };
const summaryA: FleetSummary = {
  total: 1, total_hashrate: 100, devices_with_recent_telemetry: 1,
  status_counts: { ONLINE: 1, OFFLINE: 0, WARNING: 0, CRITICAL: 0, UNKNOWN: 0 },
};
const summaryB: FleetSummary = { ...summaryA, total_hashrate: 200 };
const snapshotA = { privateMarker: 'fixture-snapshot-a' };
const snapshotB = { privateMarker: 'fixture-snapshot-b' };
const alertsB: Alert[] = [{ id: 2, ts: 2, severity: 'WARN', category: 'fixture', message: 'Private B' }];
const pendingOperation = {
  success: true, operation_id: 'fixture-operation-a', reconciliation: { state: 'pending' },
};
const verifiedOperation = {
  success: true, phase: 'verified', reconciliation: { state: 'confirmed' },
  audit: { state: 'recorded' },
};

function selectB() {
  // A newly rendered B hook may legitimately refetch. Its synthetic response
  // belongs to B; only already-started A promises retain A fixture payloads.
  jest.mocked(client.fetchSnapshot).mockResolvedValue(snapshotB);
  jest.mocked(client.fetchAlerts).mockResolvedValue(alertsB);
  jest.mocked(client.fetchDevices).mockResolvedValue({ devices: [deviceB], summary: summaryB });
  jest.mocked(client.fetchFleetSummary).mockResolvedValue(summaryB);
  useAppStore.getState().setToken('fixture-session-b');
  useAppStore.setState({ devices: [deviceB], fleetSummary: summaryB, snapshot: snapshotB, alerts: alertsB });
}

beforeEach(() => {
  jest.clearAllMocks();
  // Preserve the native lifecycle stubs installed by jest-expo. Reset only
  // the two boundaries owned by this suite, not AppState's remove callback.
  for (const boundary of [
    client.fetchSnapshot, client.fetchAlerts, client.fetchDevices,
    client.fetchFleetSummary, client.fetchDevice, client.refreshDevice,
    client.sendDeviceCommand, client.requestDeviceCommandConfirmation,
    client.fetchCommandHistory, client.fetchDeviceCommandStatus,
    offline.cacheSnapshot, offline.getCachedSnapshot,
  ]) jest.mocked(boundary).mockReset();
  useAppStore.setState(useAppStore.getInitialState(), true);
  useAppStore.getState().setToken('fixture-session-a');
  useAppStore.getState().setBatteryMode('max_battery');
  jest.mocked(client.fetchSnapshot).mockResolvedValue(snapshotA);
  jest.mocked(client.fetchAlerts).mockResolvedValue([]);
  jest.mocked(client.fetchDevices).mockResolvedValue({ devices: [deviceA], summary: summaryA });
  jest.mocked(client.fetchFleetSummary).mockResolvedValue(summaryA);
  jest.mocked(client.fetchDevice).mockResolvedValue({ success: true, device: deviceA });
  jest.mocked(client.refreshDevice).mockResolvedValue({ success: true, device: deviceA });
  jest.mocked(client.sendDeviceCommand).mockResolvedValue({ success: true, dry_run: true });
  jest.mocked(client.requestDeviceCommandConfirmation).mockResolvedValue({ confirmation_token: 'fixture-confirmation-a' });
  jest.mocked(client.fetchCommandHistory).mockResolvedValue([{ privateMarker: 'fixture-history-a' }]);
  jest.mocked(client.fetchDeviceCommandStatus).mockResolvedValue(verifiedOperation);
  jest.mocked(offline.cacheSnapshot).mockResolvedValue(undefined);
  jest.mocked(offline.getCachedSnapshot).mockResolvedValue(null);
});

afterEach(async () => {
  await cleanup();
  jest.clearAllTimers();
  jest.useRealTimers();
});

describe('snapshot hook session isolation', () => {
  it('rejects an A render callback invoked in B before React cleanup', async () => {
    const { result } = await renderHook(() => useSnapshot());
    await waitFor(() => expect(useAppStore.getState().snapshot).toEqual(snapshotA));
    const refreshA = result.current.refresh;
    jest.clearAllMocks();
    let request!: Promise<unknown>;
    await act(() => {
      selectB();
      request = refreshA().catch(() => undefined);
      // Assert synchronously, before React can render B or run cleanup.
      expect(client.fetchSnapshot).not.toHaveBeenCalled();
      expect(client.fetchAlerts).not.toHaveBeenCalled();
    });
    await act(async () => { await request; });
  });

  it.each(['B', 'same-token-after-logout'] as const)(
    'discards late A success and never caches it for %s', async (next) => {
      const snapshot = deferred<Record<string, unknown>>();
      const alerts = deferred<Alert[]>();
      jest.mocked(client.fetchSnapshot).mockReturnValueOnce(snapshot.promise);
      jest.mocked(client.fetchAlerts).mockReturnValueOnce(alerts.promise);
      await renderHook(() => useSnapshot());
      await act(async () => {
        if (next === 'same-token-after-logout') {
          jest.mocked(client.fetchSnapshot).mockResolvedValue(snapshotB);
          jest.mocked(client.fetchAlerts).mockResolvedValue(alertsB);
          useAppStore.getState().logout();
          useAppStore.getState().setToken('fixture-session-a');
          useAppStore.setState({ snapshot: snapshotB, alerts: alertsB });
        } else selectB();
        snapshot.resolve(snapshotA);
        alerts.resolve([{ ...alertsB[0], id: 1, message: 'Private A' }]);
      });
      expect(useAppStore.getState().snapshot).toEqual(snapshotB);
      expect(useAppStore.getState().alerts).toEqual(alertsB);
      expect(jest.mocked(offline.cacheSnapshot).mock.calls.map(([data]) => data))
        .not.toContainEqual(snapshotA);
    }
  );

  it('discards an A cache read completing after B is selected', async () => {
    const read = deferred<{ snapshot: Record<string, unknown>; ts: number } | null>();
    jest.mocked(client.fetchSnapshot).mockRejectedValueOnce(new Error('fixture network down'));
    jest.mocked(offline.getCachedSnapshot).mockReturnValueOnce(read.promise);
    await renderHook(() => useSnapshot());
    await waitFor(() => expect(offline.getCachedSnapshot).toHaveBeenCalledTimes(1));
    await act(async () => {
      selectB();
      read.resolve({ snapshot: snapshotA, ts: 1 });
    });
    expect(useAppStore.getState().snapshot).toEqual(snapshotB);
    expect(useAppStore.getState().alerts).toEqual(alertsB);
  });

  it('does not enter cache fallback when an A network failure arrives in B', async () => {
    const snapshot = deferred<Record<string, unknown>>();
    jest.mocked(client.fetchSnapshot).mockReturnValueOnce(snapshot.promise);
    await renderHook(() => useSnapshot());
    await act(async () => {
      selectB();
      snapshot.reject(new Error('fixture late network failure'));
    });
    expect(offline.getCachedSnapshot).not.toHaveBeenCalled();
    expect(useAppStore.getState().snapshot).toEqual(snapshotB);
  });

  it.each([401, 403])('never treats HTTP %s as permission to restore offline data', async (status) => {
    const error = new AxiosError('fixture authorization rejection', 'ERR_BAD_REQUEST', undefined, undefined, {
      status, statusText: 'fixture', data: {}, headers: {}, config: { headers: new AxiosHeaders() },
    });
    jest.mocked(client.fetchSnapshot).mockRejectedValueOnce(error);
    jest.mocked(offline.getCachedSnapshot).mockResolvedValue({ snapshot: snapshotA, ts: 1 });
    await renderHook(() => useSnapshot());
    await act(async () => {});
    expect(offline.getCachedSnapshot).not.toHaveBeenCalled();
    expect(useAppStore.getState().snapshot).toBeNull();
  });
});

describe('fleet hook session isolation', () => {
  it.each(['load', 'refresh', 'getDevice'] as const)(
    'rejects an A %s callback invoked in B before React cleanup', async (method) => {
      const { result } = await renderHook(() => useFleet());
      await waitFor(() => expect(useAppStore.getState().devices).toEqual([deviceA]));
      const viewA = result.current;
      jest.clearAllMocks();
      let request!: Promise<unknown>;
      await act(() => {
        selectB();
        request = (method === 'load' ? viewA.load() : viewA[method](deviceA.id)).catch(() => undefined);
        expect(client.fetchDevices).not.toHaveBeenCalled();
        expect(client.fetchFleetSummary).not.toHaveBeenCalled();
        expect(client.refreshDevice).not.toHaveBeenCalled();
        expect(client.fetchDevice).not.toHaveBeenCalled();
      });
      await act(async () => { await request; });
    }
  );

  it('does not publish late A devices and summary into B', async () => {
    const devices = deferred<{ devices: Device[]; summary: FleetSummary }>();
    const summary = deferred<FleetSummary>();
    jest.mocked(client.fetchDevices).mockReturnValueOnce(devices.promise);
    jest.mocked(client.fetchFleetSummary).mockReturnValueOnce(summary.promise);
    await renderHook(() => useFleet());
    await act(async () => {
      selectB();
      devices.resolve({ devices: [deviceA], summary: summaryA });
      summary.resolve(summaryA);
    });
    expect(useAppStore.getState().devices).toEqual([deviceB]);
    expect(useAppStore.getState().fleetSummary).toEqual(summaryB);
  });

  it('does not overwrite B devices or return success for a late A refresh', async () => {
    const reply = deferred<{ success: boolean; device: Device }>();
    jest.mocked(client.refreshDevice).mockReturnValueOnce(reply.promise);
    const { result } = await renderHook(() => useFleet());
    await waitFor(() => expect(useAppStore.getState().devices).toEqual([deviceA]));
    let request!: ReturnType<typeof result.current.refresh>;
    await act(() => { request = result.current.refresh(deviceA.id); });
    let response: Awaited<typeof request> | undefined;
    await act(async () => {
      selectB();
      reply.resolve({ success: true, device: { ...deviceA, name: 'Updated private A' } });
      response = await request;
    });
    expect(useAppStore.getState().devices).toEqual([deviceB]);
    expect(response?.success).toBe(false);
  });

  it('does not return a private A device read that completes in B', async () => {
    const reply = deferred<{ success: boolean; device: Device }>();
    jest.mocked(client.fetchDevice).mockReturnValueOnce(reply.promise);
    const { result } = await renderHook(() => useFleet());
    let request!: ReturnType<typeof result.current.getDevice>;
    await act(() => { request = result.current.getDevice(deviceA.id); });
    let response: Device | null = null;
    await act(async () => {
      selectB();
      reply.resolve({ success: true, device: deviceA });
      response = await request;
    });
    expect(response).toBeNull();
    expect(useAppStore.getState().devices).toEqual([deviceB]);
  });
});

describe('command hook session isolation', () => {
  it('rejects an A command callback invoked in B before React cleanup', async () => {
    const { result } = await renderHook(() => useCommands(deviceA.id));
    const sendA = result.current.sendCommand;
    let request!: Promise<unknown>;
    await act(() => {
      selectB();
      request = sendA('restart', {}, 'CONFIRM RESTART').catch(() => undefined);
      expect(client.requestDeviceCommandConfirmation).not.toHaveBeenCalled();
      expect(client.sendDeviceCommand).not.toHaveBeenCalled();
    });
    await act(async () => { await request; });
  });

  it('rejects an A history callback invoked in B before React cleanup', async () => {
    const { result } = await renderHook(() => useCommands(deviceA.id));
    const historyA = result.current.getHistory;
    let request!: Promise<unknown>;
    await act(() => {
      selectB();
      request = historyA().catch(() => undefined);
      expect(client.fetchCommandHistory).not.toHaveBeenCalled();
    });
    await act(async () => { await request; });
  });

  it('does not dispatch a command after an A confirmation completes in B', async () => {
    const confirmation = deferred<{ confirmation_token: string }>();
    jest.mocked(client.requestDeviceCommandConfirmation).mockReturnValueOnce(confirmation.promise);
    const { result } = await renderHook(() => useCommands(deviceA.id));
    let request!: ReturnType<typeof result.current.sendCommand>;
    await act(() => { request = result.current.sendCommand('restart', {}, 'CONFIRM RESTART'); });
    let response: Awaited<typeof request> | undefined;
    await act(async () => {
      selectB();
      confirmation.resolve({ confirmation_token: 'fixture-confirmation-a' });
      response = await request;
    });
    expect(client.sendDeviceCommand).not.toHaveBeenCalled();
    expect(response?.success).toBe(false);
  });

  it('does not publish a late A ACK or start reconciliation in B', async () => {
    const reply = deferred<typeof pendingOperation>();
    jest.mocked(client.sendDeviceCommand).mockReturnValueOnce(reply.promise);
    const { result } = await renderHook(() => useCommands(deviceA.id));
    let request!: ReturnType<typeof result.current.sendCommand>;
    await act(() => { request = result.current.sendCommand('restart'); });
    let response: Awaited<typeof request> | undefined;
    await act(async () => {
      selectB();
      reply.resolve(pendingOperation);
      response = await request;
    });
    expect(client.fetchDeviceCommandStatus).not.toHaveBeenCalled();
    expect(result.current.operationId).toBeNull();
    expect(result.current.auditRecorded).toBe(false);
    expect(response?.success).toBe(false);
  });

  it('does not return private A history completing in B', async () => {
    const history = deferred<{ privateMarker: string }[]>();
    jest.mocked(client.fetchCommandHistory).mockReturnValueOnce(history.promise);
    const { result } = await renderHook(() => useCommands(deviceA.id));
    let request!: ReturnType<typeof result.current.getHistory>;
    await act(() => { request = result.current.getHistory(); });
    let response: unknown;
    await act(async () => {
      selectB();
      history.resolve([{ privateMarker: 'fixture-history-a' }]);
      response = await request;
    });
    expect(response).toEqual([]);
  });

  it('does not publish late A verification and audit evidence in B', async () => {
    const status = deferred<typeof verifiedOperation>();
    jest.mocked(client.sendDeviceCommand).mockResolvedValueOnce(pendingOperation);
    jest.mocked(client.fetchDeviceCommandStatus).mockReturnValueOnce(status.promise);
    const { result } = await renderHook(() => useCommands(deviceA.id));
    await act(async () => { await result.current.sendCommand('restart'); });
    expect(client.fetchDeviceCommandStatus).toHaveBeenCalledTimes(1);
    await act(async () => {
      selectB();
      status.resolve(verifiedOperation);
    });
    expect(result.current.phase).not.toBe('verified');
    expect(result.current.auditRecorded).toBe(false);
  });

  it.each(['pending', 'transient-error'] as const)(
    'does not dispatch another A reconciliation request after B enters during %s wait', async (state) => {
      jest.useFakeTimers();
      jest.mocked(client.sendDeviceCommand).mockResolvedValueOnce(pendingOperation);
      if (state === 'pending') {
        jest.mocked(client.fetchDeviceCommandStatus).mockResolvedValueOnce({ phase: 'reconnecting', reconciliation: { state: 'pending' } });
      } else {
        jest.mocked(client.fetchDeviceCommandStatus).mockRejectedValueOnce(new Error('fixture transient network failure'));
      }
      const { result } = await renderHook(() => useCommands(deviceA.id));
      await act(async () => { await result.current.sendCommand('restart'); });
      expect(client.fetchDeviceCommandStatus).toHaveBeenCalledTimes(1);
      await act(async () => {
        selectB();
        await jest.advanceTimersByTimeAsync(2000);
      });
      expect(client.fetchDeviceCommandStatus).toHaveBeenCalledTimes(1);
    }
  );
});
