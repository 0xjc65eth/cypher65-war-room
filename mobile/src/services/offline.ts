import AsyncStorage from '@react-native-async-storage/async-storage';
import { CryptoDigestAlgorithm, digestStringAsync } from 'expo-crypto';
import Constants from 'expo-constants';
import { resolveMobileEnvironment } from '../config/environment';
import { captureSession, isCurrentSession, type SessionLease } from './sessionLease';

const environment = resolveMobileEnvironment(Constants.expoConfig?.extra, __DEV__);
const namespace = `${environment.environment}:${environment.apiBaseUrl}`;
const VERSION = 2;
const LEGACY_KEYS = ['cypher65_offline_cache', 'cypher65_action_queue'];
let storageTail: Promise<unknown> = Promise.resolve();

function serialize<T>(operation: () => Promise<T>): Promise<T> {
  const result = storageTail.then(operation);
  storageTail = result.catch(() => undefined);
  return result;
}

async function ownerFor(lease: SessionLease): Promise<string | null> {
  if (!lease.token || !isCurrentSession(lease)) return null;
  const owner = await digestStringAsync(CryptoDigestAlgorithm.SHA256,
    JSON.stringify([VERSION, namespace, lease.token]));
  return isCurrentSession(lease) && /^[a-f0-9]{64}$/.test(owner) ? owner : null;
}

const keyFor = (kind: string, owner: string) => `cypher65_${kind}_v${VERSION}_${owner}`;

/**
 * Queue removal before digesting so an old cleanup cannot overtake a new write.
 * Unlike reads, cleanup deliberately accepts an expired, captured owner lease.
 * @example const old = captureSession(); logout(); await clearSessionCache(old);
 */
export function clearSessionCache(lease: SessionLease): Promise<void> {
  return serialize(async () => {
    for (const key of LEGACY_KEYS) await AsyncStorage.removeItem(key);
    if (!lease.token) return;
    const owner = await digestStringAsync(CryptoDigestAlgorithm.SHA256,
      JSON.stringify([VERSION, namespace, lease.token]));
    if (!/^[a-f0-9]{64}$/.test(owner)) return;
    await AsyncStorage.removeItem(keyFor('offline', owner));
    await AsyncStorage.removeItem(keyFor('actions', owner));
  }).catch(() => undefined);
}
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);

async function readOwned(kind: string, owner: string): Promise<unknown> {
  // Legacy records cannot be assigned to an authenticated owner safely.
  for (const key of LEGACY_KEYS) await AsyncStorage.removeItem(key);
  const raw = await AsyncStorage.getItem(keyFor(kind, owner));
  if (!raw) return null;
  const value: unknown = JSON.parse(raw);
  return record(value) && value.version === VERSION && value.owner === owner ? value.data : null;
}

export interface QueuedAction {
  id: string;
  endpoint: string;
  method: 'GET' | 'POST';
  payload?: Record<string, unknown>;
  createdAt: number;
  retries: number;
}

interface CachedSnapshot {
  snapshot: Record<string, unknown>;
  ts: number;
}

const validSnapshot = (value: unknown): value is CachedSnapshot =>
  record(value) && record(value.snapshot) && typeof value.ts === 'number' &&
  Number.isFinite(value.ts) && value.ts >= 0 && value.ts <= Date.now();

function safePayload(value: unknown, depth = 0): boolean {
  if (depth > 8) return false;
  if (value === null || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value === 'string') return value.length <= 4096;
  if (Array.isArray(value)) return value.length <= 100 && value.every((v) => safePayload(v, depth + 1));
  return record(value) && Object.entries(value).every(([key, item]) =>
    !/token|secret|password|authorization|cookie|credential|confirmation|api[_-]?key|private[_-]?key|mnemonic|seed[_-]?phrase/i.test(key) &&
    safePayload(item, depth + 1));
}

const validAction = (value: unknown): value is QueuedAction =>
  record(value) && typeof value.id === 'string' && value.id.length > 0 &&
  typeof value.endpoint === 'string' && /^\/[a-zA-Z0-9/_-]+$/.test(value.endpoint) &&
  (value.method === 'GET' || value.method === 'POST') &&
  typeof value.createdAt === 'number' && Number.isFinite(value.createdAt) && value.createdAt >= 0 &&
  typeof value.retries === 'number' && Number.isSafeInteger(value.retries) && value.retries >= 0 &&
  (value.payload === undefined || (record(value.payload) && safePayload(value.payload)));

/**
 * Cache only for the captured authenticated owner; never serialize the lease.
 * @example await cacheSnapshot(snapshot, captureSession());
 */
export async function cacheSnapshot(
  snapshot: Record<string, unknown>, lease: SessionLease = captureSession()
): Promise<void> {
  try {
    if (!safePayload(snapshot)) return;
    const owner = await ownerFor(lease);
    if (!owner) return;
    await serialize(async () => {
      if (!isCurrentSession(lease)) return;
      const serialized = JSON.stringify({
        version: VERSION, owner, data: { snapshot, ts: Date.now() },
      });
      if (lease.token && serialized.includes(lease.token)) return;
      await AsyncStorage.setItem(keyFor('offline', owner), serialized);
      if (!isCurrentSession(lease)) await AsyncStorage.removeItem(keyFor('offline', owner));
    });
  } catch {
    // A cache failure is not authority to publish data or change authentication.
  }
}

/**
 * Restore this owner's cache, including relaunch with the same stored token.
 * @example const cached = await getCachedSnapshot(captureSession());
 */
export async function getCachedSnapshot(
  lease: SessionLease = captureSession()
): Promise<CachedSnapshot | null> {
  try {
    const owner = await ownerFor(lease);
    if (!owner) return null;
    return await serialize(async () => {
      if (!isCurrentSession(lease)) return null;
      const value = await readOwned('offline', owner);
      return isCurrentSession(lease) && validSnapshot(value) ? value : null;
    });
  } catch {
    return null;
  }
}

/**
 * Serialize the complete owner-bound queue transaction, not only its write.
 * This stores intent only; it neither executes nor authorizes device commands.
 * @example await queueAction({ endpoint: '/fixture/read', method: 'GET', createdAt: Date.now() });
 */
export async function queueAction(
  action: Omit<QueuedAction, 'id' | 'retries'>, lease: SessionLease = captureSession()
): Promise<void> {
  try {
    const owner = await ownerFor(lease);
    if (!owner) return;
    await serialize(async () => {
      if (!isCurrentSession(lease)) return;
      const stored = await readOwned('actions', owner);
      if (!isCurrentSession(lease)) return;
      const queue = Array.isArray(stored) && stored.every(validAction) ? stored : [];
      const next = { ...action, id: `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`, retries: 0 };
      if (!validAction(next)) return;
      queue.push(next);
      const serialized = JSON.stringify({ version: VERSION, owner, data: queue });
      if (lease.token && serialized.includes(lease.token)) return;
      await AsyncStorage.setItem(keyFor('actions', owner), serialized);
      if (!isCurrentSession(lease)) await AsyncStorage.removeItem(keyFor('actions', owner));
    });
  } catch {
    // Offline queuing is best effort, never execution authority.
  }
}

/**
 * Read validated queued work for this owner, without executing it.
 * @example const pending = await getActionQueue(captureSession());
 */
export async function getActionQueue(lease: SessionLease = captureSession()): Promise<QueuedAction[]> {
  try {
    const owner = await ownerFor(lease);
    if (!owner) return [];
    return await serialize(async () => {
      if (!isCurrentSession(lease)) return [];
      const value = await readOwned('actions', owner);
      return isCurrentSession(lease) && Array.isArray(value) && value.every(validAction) ? value : [];
    });
  } catch {
    return [];
  }
}

/**
 * Clear only the captured owner's queue, after all prior transactions.
 * @example await clearActionQueue(captureSession());
 */
export async function clearActionQueue(lease: SessionLease = captureSession()): Promise<void> {
  const owner = await ownerFor(lease).catch(() => null);
  if (owner) await serialize(() => AsyncStorage.removeItem(keyFor('actions', owner))).catch(() => undefined);
}
