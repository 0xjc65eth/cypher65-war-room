jest.mock('expo-notifications', () => ({
  setNotificationHandler: jest.fn(),
  getPermissionsAsync: jest.fn(),
  requestPermissionsAsync: jest.fn(),
  getExpoPushTokenAsync: jest.fn(),
  addNotificationReceivedListener: jest.fn(),
  addNotificationResponseReceivedListener: jest.fn(),
}));

jest.mock('expo-device', () => ({
  isDevice: true,
}));

jest.mock('../src/api/client', () => ({
  registerPushToken: jest.fn(),
}));

import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import {
  configureNotificationHandler,
  DEFAULT_PUSH_CATEGORIES,
  requestPushPermissions,
  getPushToken,
  updatePushCategories,
  addNotificationReceivedListener,
  addNotificationResponseListener,
} from '../src/services/push';
import { registerPushToken } from '../src/api/client';

describe('push notification handler', () => {
  it('declares the complete Expo SDK 57 foreground presentation behavior', async () => {
    configureNotificationHandler();

    expect(Notifications.setNotificationHandler).toHaveBeenCalledTimes(1);
    const handler = (Notifications.setNotificationHandler as jest.Mock).mock.calls[0][0];

    await expect(handler.handleNotification()).resolves.toEqual({
      shouldShowAlert: true,
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: true,
    });
  });

  it('refuses push registration on a simulator and returns a token on a device', async () => {
    (Device as { isDevice: boolean }).isDevice = false;
    await expect(requestPushPermissions()).resolves.toBe(false);
    await expect(getPushToken()).resolves.toBeNull();

    (Device as { isDevice: boolean }).isDevice = true;
    (Notifications.getPermissionsAsync as jest.Mock).mockResolvedValue({ status: 'granted' });
    (Notifications.getExpoPushTokenAsync as jest.Mock).mockResolvedValue({ data: 'ExponentPushToken[x]' });
    await expect(requestPushPermissions()).resolves.toBe(true);
    await expect(getPushToken()).resolves.toBe('ExponentPushToken[x]');
  });

  it('updates categories through the register endpoint and wires listeners', async () => {
    (registerPushToken as jest.Mock).mockResolvedValue(undefined);
    const prefs = await updatePushCategories('tok', { ...DEFAULT_PUSH_CATEGORIES, temperature: false });
    expect(prefs?.token).toBe('tok');
    expect(prefs?.categories.temperature).toBe(false);
    expect(registerPushToken).toHaveBeenCalled();

    const received = jest.fn();
    const response = jest.fn();
    addNotificationReceivedListener(received);
    addNotificationResponseListener(response);
    expect(Notifications.addNotificationReceivedListener).toHaveBeenCalledWith(received);
    expect(Notifications.addNotificationResponseReceivedListener).toHaveBeenCalledWith(response);
  });
});
