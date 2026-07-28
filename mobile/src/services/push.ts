import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { Platform } from 'react-native';
import { registerPushToken } from '../api/client';
import type { PushPreferences } from '../types';

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

export const registerForPushNotifications = async (): Promise<PushPreferences | null> => {
  const granted = await requestPushPermissions();
  if (!granted) {
    return null;
  }

  const token = await getPushToken();
  if (!token) {
    return null;
  }

  const preferences: PushPreferences = {
    token,
    platform: Platform.OS === 'ios' ? 'ios' : 'android',
    categories: { ...DEFAULT_PUSH_CATEGORIES },
  };

  await registerPushToken(preferences);
  return preferences;
};

export const updatePushCategories = async (
  token: string,
  categories: Record<string, boolean>
): Promise<PushPreferences | null> => {
  const preferences: PushPreferences = {
    token,
    platform: Platform.OS === 'ios' ? 'ios' : 'android',
    categories,
  };
  await registerPushToken(preferences);
  return preferences;
};

export const configureNotificationHandler = () => {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
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
