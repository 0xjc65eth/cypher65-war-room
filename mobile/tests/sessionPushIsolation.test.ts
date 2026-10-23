import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import { registerPushToken } from '../src/api/client';
import { captureSession } from '../src/services/sessionLease';
import { DEFAULT_PUSH_CATEGORIES, registerForPushNotifications, updatePushCategories } from '../src/services/push';
import { useAppStore } from '../src/store';

jest.mock('expo-notifications', () => ({
  getPermissionsAsync: jest.fn(), requestPermissionsAsync: jest.fn(),
  getExpoPushTokenAsync: jest.fn(), setNotificationHandler: jest.fn(),
  addNotificationReceivedListener: jest.fn(), addNotificationResponseReceivedListener: jest.fn(),
}));
jest.mock('expo-device', () => ({ isDevice: true }));
jest.mock('../src/api/client', () => ({ registerPushToken: jest.fn() }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

const granted: Notifications.NotificationPermissionsStatus = {
  status: 'granted' as Notifications.NotificationPermissionsStatus['status'],
  granted: true, canAskAgain: true, expires: 'never',
};
const denied: Notifications.NotificationPermissionsStatus = {
  ...granted, status: 'denied' as Notifications.NotificationPermissionsStatus['status'], granted: false,
};
const token: Notifications.ExpoPushToken = { type: 'expo', data: 'ExponentPushToken[fixture-device]' };

beforeEach(() => {
  jest.clearAllMocks();
  for (const boundary of [
    Notifications.getPermissionsAsync, Notifications.requestPermissionsAsync,
    Notifications.getExpoPushTokenAsync, registerPushToken,
  ]) jest.mocked(boundary).mockReset();
  useAppStore.setState(useAppStore.getInitialState(), true);
  useAppStore.getState().setToken('fixture-session-a');
  jest.mocked(Notifications.getPermissionsAsync).mockResolvedValue(granted);
  jest.mocked(Notifications.requestPermissionsAsync).mockResolvedValue(granted);
  jest.mocked(Notifications.getExpoPushTokenAsync).mockResolvedValue(token);
  jest.mocked(registerPushToken).mockResolvedValue({ success: true });
});

describe('push workflow session ownership', () => {
  it('does not start permission, token or registration work anonymously', async () => {
    useAppStore.getState().logout();
    expect(await registerForPushNotifications()).toBeNull();
    expect(await updatePushCategories(token.data, { temperature: false })).toBeNull();
    expect(Notifications.getPermissionsAsync).not.toHaveBeenCalled();
    expect(Notifications.requestPermissionsAsync).not.toHaveBeenCalled();
    expect(Notifications.getExpoPushTokenAsync).not.toHaveBeenCalled();
    expect(registerPushToken).not.toHaveBeenCalled();
  });

  it('rejects an explicitly captured A lease before doing any work in B', async () => {
    const leaseA = captureSession();
    useAppStore.getState().setToken('fixture-session-b');
    expect(await registerForPushNotifications(leaseA)).toBeNull();
    expect(await updatePushCategories(token.data, { temperature: false }, leaseA)).toBeNull();
    expect(Notifications.getPermissionsAsync).not.toHaveBeenCalled();
    expect(registerPushToken).not.toHaveBeenCalled();
  });

  it('does not obtain or register a token after an A permission read completes in B', async () => {
    const permissions = deferred<Notifications.NotificationPermissionsStatus>();
    jest.mocked(Notifications.getPermissionsAsync).mockReturnValueOnce(permissions.promise);
    const request = registerForPushNotifications();
    useAppStore.getState().setToken('fixture-session-b');
    permissions.resolve(granted);
    expect(await request).toBeNull();
    expect(Notifications.getExpoPushTokenAsync).not.toHaveBeenCalled();
    expect(registerPushToken).not.toHaveBeenCalled();
  });

  it('does not obtain or register a token after an A permission prompt completes in B', async () => {
    const permissions = deferred<Notifications.NotificationPermissionsStatus>();
    const started = deferred<void>();
    jest.mocked(Notifications.getPermissionsAsync).mockResolvedValueOnce(denied);
    jest.mocked(Notifications.requestPermissionsAsync).mockImplementationOnce(() => {
      started.resolve();
      return permissions.promise;
    });
    const request = registerForPushNotifications();
    await started.promise;
    useAppStore.getState().setToken('fixture-session-b');
    permissions.resolve(granted);
    expect(await request).toBeNull();
    expect(Notifications.getExpoPushTokenAsync).not.toHaveBeenCalled();
    expect(registerPushToken).not.toHaveBeenCalled();
  });

  it.each(['B', 'same-token-after-logout'] as const)(
    'does not register an A token that completes in %s', async (next) => {
      const nativeToken = deferred<Notifications.ExpoPushToken>();
      const started = deferred<void>();
      jest.mocked(Notifications.getExpoPushTokenAsync).mockImplementationOnce(() => {
        started.resolve();
        return nativeToken.promise;
      });
      const request = registerForPushNotifications();
      await started.promise;
      if (next === 'same-token-after-logout') {
        useAppStore.getState().logout();
        useAppStore.getState().setToken('fixture-session-a');
      } else useAppStore.getState().setToken('fixture-session-b');
      nativeToken.resolve(token);
      expect(await request).toBeNull();
      expect(registerPushToken).not.toHaveBeenCalled();
    }
  );

  it('registers the current fixture owner and preserves its preferences', async () => {
    let ownerAtDispatch: string | null = null;
    jest.mocked(registerPushToken).mockImplementationOnce(async () => {
      ownerAtDispatch = useAppStore.getState().auth.token;
      return { success: true };
    });
    const preferences = await registerForPushNotifications();
    expect(ownerAtDispatch).toBe('fixture-session-a');
    expect(preferences).toEqual({
      token: token.data, platform: Platform.OS === 'ios' ? 'ios' : 'android',
      categories: DEFAULT_PUSH_CATEGORIES,
    });
    expect(registerPushToken).toHaveBeenCalledTimes(1);
    expect(registerPushToken).toHaveBeenCalledWith(preferences);
  });

  it('does not publish an A registration response into B', async () => {
    const response = deferred<{ success: boolean }>();
    const started = deferred<void>();
    jest.mocked(registerPushToken).mockImplementationOnce(() => {
      started.resolve();
      return response.promise;
    });
    const request = registerForPushNotifications();
    await started.promise;
    useAppStore.getState().setToken('fixture-session-b');
    response.resolve({ success: true });
    expect(await request).toBeNull();
    expect(registerPushToken).toHaveBeenCalledTimes(1);
    expect(useAppStore.getState().auth.token).toBe('fixture-session-b');
  });

  it('updates current-owner categories but suppresses a reply arriving after logout', async () => {
    const categories = { ...DEFAULT_PUSH_CATEGORIES, temperature: false };
    expect((await updatePushCategories(token.data, categories))?.categories).toEqual(categories);
    const response = deferred<{ success: boolean }>();
    jest.mocked(registerPushToken).mockReturnValueOnce(response.promise);
    const request = updatePushCategories(token.data, categories);
    useAppStore.getState().logout();
    response.resolve({ success: true });
    expect(await request).toBeNull();
    expect(useAppStore.getState().auth.token).toBeNull();
  });

  it('does not proceed when the current owner denies permissions', async () => {
    jest.mocked(Notifications.getPermissionsAsync).mockResolvedValueOnce(denied);
    jest.mocked(Notifications.requestPermissionsAsync).mockResolvedValueOnce(denied);
    expect(await registerForPushNotifications()).toBeNull();
    expect(Notifications.getExpoPushTokenAsync).not.toHaveBeenCalled();
    expect(registerPushToken).not.toHaveBeenCalled();
  });
});
