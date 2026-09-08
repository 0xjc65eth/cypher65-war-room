import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  cacheSnapshot,
  getCachedSnapshot,
  queueAction,
  getActionQueue,
  clearActionQueue,
  type QueuedAction,
} from '../src/services/offline';

describe('offline cache and action queue', () => {
  beforeEach(async () => {
    await AsyncStorage.clear();
  });

  it('round-trips a snapshot and returns null when empty or corrupt', async () => {
    expect(await getCachedSnapshot()).toBeNull();
    await cacheSnapshot({ hashrate: 1 });
    const cached = await getCachedSnapshot();
    expect(cached?.snapshot).toEqual({ hashrate: 1 });
    expect(typeof cached?.ts).toBe('number');

    (AsyncStorage.getItem as jest.Mock).mockResolvedValueOnce('{');
    expect(await getCachedSnapshot()).toBeNull();
  });

  it('queues actions with generated ids and clears the queue', async () => {
    await queueAction({
      endpoint: '/devices/d1/restart',
      method: 'POST',
      payload: { dry_run: true },
      createdAt: 1,
    });
    const queued: QueuedAction[] = await getActionQueue();
    expect(queued).toHaveLength(1);
    expect(queued[0].endpoint).toBe('/devices/d1/restart');
    expect(queued[0].retries).toBe(0);
    expect(queued[0].id).toEqual(expect.any(String));

    await clearActionQueue();
    expect(await getActionQueue()).toEqual([]);
  });

  it('returns an empty queue when storage is missing or invalid', async () => {
    expect(await getActionQueue()).toEqual([]);
    (AsyncStorage.getItem as jest.Mock).mockResolvedValueOnce('not-json');
    expect(await getActionQueue()).toEqual([]);
  });
});
