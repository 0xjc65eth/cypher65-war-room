import AsyncStorage from '@react-native-async-storage/async-storage';

const OFFLINE_CACHE_KEY = 'cypher65_offline_cache';
const ACTION_QUEUE_KEY = 'cypher65_action_queue';

export interface QueuedAction {
  id: string;
  endpoint: string;
  method: 'GET' | 'POST';
  payload?: Record<string, unknown>;
  createdAt: number;
  retries: number;
}

export const cacheSnapshot = async (snapshot: Record<string, unknown>): Promise<void> => {
  try {
    await AsyncStorage.setItem(OFFLINE_CACHE_KEY, JSON.stringify({ snapshot, ts: Date.now() }));
  } catch {
    // silently ignore cache errors
  }
};

export const getCachedSnapshot = async (): Promise<{ snapshot: Record<string, unknown>; ts: number } | null> => {
  try {
    const raw = await AsyncStorage.getItem(OFFLINE_CACHE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
};

export const queueAction = async (action: Omit<QueuedAction, 'id' | 'retries'>): Promise<void> => {
  try {
    const queue = await getActionQueue();
    const newAction: QueuedAction = {
      ...action,
      id: `${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
      retries: 0,
    };
    queue.push(newAction);
    await AsyncStorage.setItem(ACTION_QUEUE_KEY, JSON.stringify(queue));
  } catch {
    // ignore
  }
};

export const getActionQueue = async (): Promise<QueuedAction[]> => {
  try {
    const raw = await AsyncStorage.getItem(ACTION_QUEUE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
};

export const clearActionQueue = async (): Promise<void> => {
  try {
    await AsyncStorage.removeItem(ACTION_QUEUE_KEY);
  } catch {
    // ignore
  }
};
