import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { theme } from '../theme';

type StatusBadgeProps = {
  status: 'ONLINE' | 'OFFLINE' | 'WARNING' | 'CRITICAL' | 'CRIT' | 'WARN' | 'GOLD' | 'SUCCESS' | 'INFO';
  label?: string;
};

const statusColors: Record<string, { bg: string; text: string }> = {
  ONLINE: { bg: theme.bg.green, text: theme.green.DEFAULT },
  OFFLINE: { bg: theme.bg.red, text: theme.red.DEFAULT },
  WARNING: { bg: theme.bg.amber, text: theme.amber.DEFAULT },
  WARN: { bg: theme.bg.amber, text: theme.amber.DEFAULT },
  CRITICAL: { bg: theme.bg.red, text: theme.red.DEFAULT },
  CRIT: { bg: theme.bg.red, text: theme.red.DEFAULT },
  GOLD: { bg: theme.bg.amberDeep, text: theme.amber.soft },
  SUCCESS: { bg: theme.bg.green, text: theme.green.DEFAULT },
  INFO: { bg: theme.bg.brandDeep, text: theme.brand.DEFAULT },
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
