import AsyncStorage from '@react-native-async-storage/async-storage';
import { useAppStore } from '../src/store';
import { cacheSnapshot, getCachedSnapshot, queueAction, getActionQueue } from '../src/services/offline';

describe('private offline session boundary', () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
    useAppStore.setState(useAppStore.getInitialState(), true);
  });

  it('never returns A snapshot to B, including offline after logout', async () => {
    useAppStore.getState().setToken('fixture-account-a');
    await cacheSnapshot({ privateMarker: 'snapshot-a' });
    expect((await getCachedSnapshot())?.snapshot).toEqual({ privateMarker: 'snapshot-a' });
    useAppStore.getState().logout();
    useAppStore.getState().setToken('fixture-account-b');
    expect(await getCachedSnapshot()).toBeNull();
  });

  it('never exposes a previous account action queue to another account', async () => {
    useAppStore.getState().setToken('fixture-account-a');
    await queueAction({ endpoint: '/fixture/read-only', method: 'GET', createdAt: 1 });
    expect(await getActionQueue()).toHaveLength(1);
    useAppStore.getState().logout();
    useAppStore.getState().setToken('fixture-account-b');
    expect(await getActionQueue()).toEqual([]);
  });

  it('never restores legacy unowned cache into a new account', async () => {
    await AsyncStorage.setItem('cypher65_offline_cache', JSON.stringify({
      snapshot: { privateMarker: 'legacy-a' }, ts: Date.now(),
    }));
    useAppStore.getState().setToken('fixture-account-b');
    expect(await getCachedSnapshot()).toBeNull();
  });

  it('never returns private offline data without an authenticated owner', async () => {
    useAppStore.getState().setToken('fixture-account-a');
    await cacheSnapshot({ privateMarker: 'snapshot-a' });
    useAppStore.getState().logout();
    expect(await getCachedSnapshot()).toBeNull();
  });

  it.each(['access_token', 'password', 'api_key', 'privateKey', 'seed_phrase'])(
    'never persists a snapshot containing a credential field %s', async (field) => {
      useAppStore.getState().setToken('fixture-account-a');
      await cacheSnapshot({ telemetry: { [field]: 'synthetic-sensitive-value' } });
      expect(await getCachedSnapshot()).toBeNull();
    }
  );

  it('keeps raw auth credentials out of storage payloads and owner keys', async () => {
    const token = 'fixture-account-a-raw-credential';
    useAppStore.getState().setToken(token);
    jest.mocked(AsyncStorage.setItem).mockClear();
    await cacheSnapshot({ source: token });
    await queueAction({ endpoint: '/fixture/read', method: 'GET', createdAt: 1, payload: { source: token } });
    expect(AsyncStorage.setItem).not.toHaveBeenCalled();
    await cacheSnapshot({ hashrate: 1 });
    const writes = jest.mocked(AsyncStorage.setItem).mock.calls;
    expect(writes.length).toBeGreaterThan(0);
    expect(JSON.stringify(writes)).not.toContain(token);
  });
});
