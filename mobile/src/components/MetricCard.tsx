import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

interface MetricCardProps {
  title: string;
  value: string | number;
  subtext?: string;
  accent?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({ title, value, subtext, accent }) => {
  return (
    <View style={styles.card}>
      <Text style={styles.title}>{title}</Text>
      <Text style={[styles.value, accent ? { color: accent } : undefined]}>{value}</Text>
      {subtext ? <Text style={styles.subtext}>{subtext}</Text> : null}
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#111827',
    borderRadius: 8,
    padding: 12,
    minWidth: 100,
    flex: 1,
  },
  title: {
    color: '#94a3b8',
    fontSize: 12,
    marginBottom: 4,
  },
  value: {
    color: '#f8fafc',
    fontSize: 20,
    fontWeight: '700',
  },
  subtext: {
    color: '#64748b',
    fontSize: 11,
    marginTop: 4,
  },
});
