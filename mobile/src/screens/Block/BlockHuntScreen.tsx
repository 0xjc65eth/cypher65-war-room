import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, ActivityIndicator } from 'react-native';
import { MetricCard } from '../../components/MetricCard';
import { fetchBlockHunt } from '../../api/client';
import type { BlockHuntData } from '../../types';
import { theme } from '../../theme';

export const BlockHuntScreen = () => {
  const [data, setData] = useState<BlockHuntData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchBlockHunt();
      setData(result);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <ScrollView
      style={styles.container}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.brand.DEFAULT} />}
    >
      <Text style={styles.heading}>Block Hunt</Text>

      {loading && !data && <ActivityIndicator color={theme.brand.DEFAULT} />}
      {error && <Text style={styles.error}>{error}</Text>}

      {data && (
        <>
          <Text style={styles.section}>Network</Text>
          <View style={styles.grid}>
            <MetricCard
              title="Network Hashrate"
              value={`${(data.network_hashrate / 1e18).toFixed(2)} EH/s`}
            />
            <MetricCard
              title="Network Difficulty"
              value={data.network_difficulty > 0 ? data.network_difficulty.toExponential(2) : '—'}
            />
            <MetricCard title="Block Height" value={data.block_height || '—'} />
          </View>

          <Text style={styles.section}>Your Stats</Text>
          <View style={styles.grid}>
            <MetricCard
              title="Your Hashrate"
              value={`${(data.user_hashrate / 1e12).toFixed(2)} TH/s`}
            />
            <MetricCard title="Best Difficulty" value={data.best_difficulty || '—'} />
            <MetricCard
              title="Share of Network"
              value={`${data.user_vs_network_pct.toExponential(2)}%`}
            />
          </View>

          <Text style={styles.section}>Block probability model</Text>
          <View style={styles.grid}>
            <MetricCard title="1 Hour" value={`${(data.probability_1h * 100).toExponential(2)}%`} />
            <MetricCard title="24 Hours" value={`${(data.probability_24h * 100).toExponential(2)}%`} />
            <MetricCard title="7 Days" value={`${(data.probability_7d * 100).toExponential(2)}%`} />
          </View>

          <Text style={styles.section}>Model mean interval</Text>
          <Text style={styles.expected}>{data.expected_time || '—'}</Text>
          <Text style={styles.disclaimer}>
            Statistical mean, not a countdown or guarantee. Source: current worker and network snapshot;
            windows: 1h, 24h and 7d; units: probability and time. Assumes constant hashrate,
            difficulty and independent hashes. Past work does not change the next-hash odds.
          </Text>
        </>
      )}
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
  section: {
    color: theme.text.primary,
    fontSize: 18,
    fontWeight: '600',
    marginTop: 24,
    marginBottom: 12,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  error: {
    color: theme.red.DEFAULT,
    marginVertical: 8,
  },
  expected: {
    color: theme.text.primary,
    fontSize: 16,
    fontWeight: '600',
  },
  disclaimer: {
    color: theme.text.muted,
    fontSize: 12,
    lineHeight: 18,
    marginTop: 8,
    marginBottom: 24,
  },
});
