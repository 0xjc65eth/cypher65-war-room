import React from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl } from 'react-native';
import { MetricCard } from '../../components/MetricCard';
import { StatusBadge } from '../../components/StatusBadge';
import { useSnapshot } from '../../hooks/useSnapshot';
import { useAppStore } from '../../store';
import { formatDistance } from 'date-fns';

export const CommandScreen = () => {
  const { snapshot, refreshing, refresh } = useSnapshot();
  const { alerts } = useAppStore();

  const worker = (snapshot?.worker as Record<string, unknown>) || {};
  const pool = (snapshot?.pool as Record<string, unknown>) || {};
  const network = (snapshot?.network as Record<string, unknown>) || {};
  const ts = (snapshot?.ts as number) || 0;

  const hashrate = Number(worker.hashrate) || 0;
  const bestDiff = (worker.bestDifficulty as string) || '—';
  const poolHr = Number(pool.hashrate) || 0;
  const workers = Number(pool.workers) || 0;
  const netDiff = Number(network.difficulty) || 0;
  const height = Number(network.height) || 0;

  return (
    <ScrollView
      style={styles.container}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor="#38bdf8" />}
    >
      <Text style={styles.heading}>Command Center</Text>
      <Text style={styles.updated}>
        {ts ? `Updated ${formatDistance(ts * 1000, Date.now(), { addSuffix: true })}` : 'Waiting for data…'}
      </Text>

      <View style={styles.grid}>
        <MetricCard title="Hashrate" value={hashrate > 0 ? `${(hashrate / 1e12).toFixed(2)} TH/s` : '—'} />
        <MetricCard title="Best Diff" value={bestDiff} />
        <MetricCard title="Pool HR" value={poolHr > 0 ? `${(poolHr / 1e12).toFixed(2)} TH/s` : '—'} />
        <MetricCard title="Workers" value={workers} />
        <MetricCard title="Net Difficulty" value={netDiff > 0 ? netDiff.toExponential(2) : '—'} />
        <MetricCard title="Block Height" value={height || '—'} />
      </View>

      <Text style={styles.sectionTitle}>Recent Alerts</Text>
      {alerts.slice(0, 5).map((alert) => (
        <View key={alert.id} style={styles.alertRow}>
          <StatusBadge status={alert.severity} />
          <Text style={styles.alertText}>{alert.message}</Text>
        </View>
      ))}
      {alerts.length === 0 && <Text style={styles.empty}>No recent alerts</Text>}
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0b0f19',
    padding: 16,
  },
  heading: {
    color: '#f8fafc',
    fontSize: 24,
    fontWeight: '700',
    marginTop: 16,
  },
  updated: {
    color: '#64748b',
    fontSize: 12,
    marginBottom: 16,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 24,
  },
  sectionTitle: {
    color: '#f8fafc',
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 12,
  },
  alertRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#111827',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
    gap: 8,
  },
  alertText: {
    color: '#e2e8f0',
    fontSize: 13,
    flex: 1,
  },
  empty: {
    color: '#64748b',
    fontStyle: 'italic',
  },
});
