import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

type StatusBadgeProps = {
  status: 'ONLINE' | 'OFFLINE' | 'WARNING' | 'CRITICAL' | 'CRIT' | 'WARN' | 'GOLD' | 'SUCCESS' | 'INFO';
  label?: string;
};

const statusColors: Record<string, { bg: string; text: string }> = {
  ONLINE: { bg: '#064e3b', text: '#34d399' },
  OFFLINE: { bg: '#7f1d1d', text: '#f87171' },
  WARNING: { bg: '#713f12', text: '#facc15' },
  WARN: { bg: '#713f12', text: '#facc15' },
  CRITICAL: { bg: '#7f1d1d', text: '#f87171' },
  CRIT: { bg: '#7f1d1d', text: '#f87171' },
  GOLD: { bg: '#422006', text: '#fbbf24' },
  SUCCESS: { bg: '#064e3b', text: '#34d399' },
  INFO: { bg: '#0c4a6e', text: '#38bdf8' },
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, label }) => {
  const colors = statusColors[status] || statusColors.INFO;
  return (
    <View style={[styles.badge, { backgroundColor: colors.bg }]}>
      <Text style={[styles.text, { color: colors.text }]}>{label || status}</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 4,
    alignSelf: 'flex-start',
  },
  text: {
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
});
