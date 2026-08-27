import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  TouchableOpacity,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';
import { MetricCard } from '../../components/MetricCard';
import { StatusBadge } from '../../components/StatusBadge';
import { ShareDistChart } from '../../components/ShareDistChart';
import { useSnapshot } from '../../hooks/useSnapshot';
import { useAppStore } from '../../store';
import { fetchShareDist } from '../../api/client';
import type { ShareDistData } from '../../types';
import type { RootTabParamList } from '../../types/navigation';
import { formatDistance } from 'date-fns';
import { theme } from '../../theme';

export const CommandScreen = () => {
  const { snapshot, refreshing, refresh } = useSnapshot();
  const { alerts } = useAppStore();
  const navigation = useNavigation<BottomTabNavigationProp<RootTabParamList>>();

  // Live Mining → Probability parity (P0-1): share-difficulty histogram with
  // the network target overlay + CTA into the Block (probability) tab.
  const [dist, setDist] = useState<ShareDistData | null>(null);
  const [distLoading, setDistLoading] = useState(false);
  const [distError, setDistError] = useState<string | null>(null);

  const loadDist = async () => {
    setDistLoading(true);
    setDistError(null);
    try {
      setDist(await fetchShareDist('1h'));
    } catch (err) {
      setDistError((err as Error).message);
    } finally {
      setDistLoading(false);
    }
  };

  useEffect(() => {
    loadDist();
  }, []);

  const onRefresh = async () => {
    await refresh();
    loadDist();
  };

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
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={theme.brand.DEFAULT} />}
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

      <Text style={styles.sectionTitle}>Share Difficulty</Text>
      <View style={styles.sharePanel}>
        <ShareDistChart data={dist} loading={distLoading} error={distError} />
        <TouchableOpacity
          style={styles.cta}
          onPress={() => navigation.navigate('Block')}
          accessibilityRole="button"
        >
          <Text style={styles.ctaText}>⚡ P(block) → Block Model</Text>
        </TouchableOpacity>
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
    backgroundColor: theme.bg.deep,
    padding: 16,
  },
  heading: {
    color: theme.text.primary,
    fontSize: 24,
    fontWeight: '700',
    marginTop: 16,
  },
  updated: {
    color: theme.text.secondary,
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
    color: theme.text.primary,
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 12,
  },
  alertRow: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: theme.bg.surface,
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
    gap: 8,
  },
  alertText: {
    color: theme.text.faint,
    fontSize: 13,
    flex: 1,
  },
  empty: {
    color: theme.text.secondary,
    fontStyle: 'italic',
  },
  sharePanel: {
    backgroundColor: theme.bg.surface,
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
  },
  cta: {
    borderWidth: 1,
    borderColor: theme.purple,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: 'center',
    marginTop: 10,
  },
  ctaText: {
    color: theme.purple,
    fontSize: 13,
    fontWeight: '700',
  },
});
