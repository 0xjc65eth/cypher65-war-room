import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { StatusBadge } from './StatusBadge';
import type { Device } from '../types';
import { theme } from '../theme';

interface DeviceListItemProps {
  device: Device;
  onPress: (device: Device) => void;
}

export const DeviceListItem: React.FC<DeviceListItemProps> = ({ device, onPress }) => {
  const hashrate = device.current_telemetry?.hashrate ?? 0;
  const temp = device.current_telemetry?.temperature ?? 0;

  return (
    <TouchableOpacity style={styles.row} onPress={() => onPress(device)} activeOpacity={0.7}>
      <View style={styles.header}>
        <Text style={styles.name}>{device.name || device.id}</Text>
        <StatusBadge status={device.status} />
      </View>
      <View style={styles.metrics}>
        <Text style={styles.metric}>{hashrate > 0 ? `${(hashrate / 1e12).toFixed(2)} TH/s` : '—'}</Text>
        <Text style={styles.metric}>{temp > 0 ? `${temp}°C` : '—'}</Text>
        <Text style={styles.ip}>{device.ip_address}</Text>
      </View>
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  row: {
    backgroundColor: theme.bg.surface,
    borderRadius: 8,
    padding: 12,
    marginVertical: 4,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  name: {
    color: theme.text.primary,
    fontSize: 15,
    fontWeight: '600',
  },
  metrics: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  metric: {
    color: theme.text.muted,
    fontSize: 13,
  },
  ip: {
    color: theme.text.secondary,
    fontSize: 12,
  },
});
