import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';

export type FleetStackParamList = {
  FleetList: undefined;
  DeviceDetail: { deviceId: string };
};

export type RootTabParamList = {
  Command: undefined;
  Fleet: undefined;
  Block: undefined;
  Market: undefined;
  AI: undefined;
};

export type RootNavigationProp = BottomTabNavigationProp<RootTabParamList>;
export type FleetNavigationProp = NativeStackNavigationProp<FleetStackParamList>;
