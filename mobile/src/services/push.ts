import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { Platform } from 'react-native';
import { registerPushToken } from '../api/client';
import type { PushPreferences } from '../types';
import { captureSession, isCurrentSession, type SessionLease } from './sessionLease';

export const DEFAULT_PUSH_CATEGORIES: Record<string, boolean> = {
  temperature: true,
  hashrate_drop: true,
  worker_offline: true,
  device_offline: true,
  best_diff_bump: true,
  new_block: true,
};

export const requestPushPermissions = async (): Promise<boolean> => {
  if (!Device.isDevice) {
    return false;
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  return finalStatus === 'granted';
};

export const getPushToken = async (): Promise<string | null> => {
  if (!Device.isDevice) {
    return null;
  }

  const token = (await Notifications.getExpoPushTokenAsync()).data;
  return token;
};

/**
 * Register only for the account that began the permission/token workflow.
 * @example await registerForPushNotifications(captureSession());
 */
export const registerForPushNotifications = async (
  lease: SessionLease = captureSession()
): Promise<PushPreferences | null> => {
  if (!lease.token || !isCurrentSession(lease)) return null;
  const granted = await requestPushPermissions();
  if (!granted || !isCurrentSession(lease)) {
    return null;
  }

  const token = await getPushToken();
  if (!token || !isCurrentSession(lease)) {
    return null;
  }

  const preferences: PushPreferences = {
    token,
    platform: Platform.OS === 'ios' ? 'ios' : 'android',
    categories: { ...DEFAULT_PUSH_CATEGORIES },
  };

  await registerPushToken(preferences);
  return isCurrentSession(lease) ? preferences : null;
};

/**
 * Keep delayed preference updates bound to their original session.
 * @example await updatePushCategories(pushToken, categories, captureSession());
 */
export const updatePushCategories = async (
  token: string,
  categories: Record<string, boolean>,
  lease: SessionLease = captureSession()
): Promise<PushPreferences | null> => {
  if (!lease.token || !isCurrentSession(lease)) return null;
  const preferences: PushPreferences = {
    token,
    platform: Platform.OS === 'ios' ? 'ios' : 'android',
    categories,
  };
  await registerPushToken(preferences);
  return isCurrentSession(lease) ? preferences : null;
};

export const configureNotificationHandler = () => {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: true,
    }),
  });
};

export const addNotificationReceivedListener = (
  callback: (notification: Notifications.Notification) => void
) => {
  return Notifications.addNotificationReceivedListener(callback);
};

export const addNotificationResponseListener = (
  callback: (response: Notifications.NotificationResponse) => void
) => {
  return Notifications.addNotificationResponseReceivedListener(callback);
};
