import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, FlatList, RefreshControl, ActivityIndicator } from 'react-native';
import { fetchHashrateMarket, compareOffers } from '../../api/client';
import { MetricCard } from '../../components/MetricCard';
import type { MarketOffer } from '../../types';
import { theme } from '../../theme';

export const MarketScreen = () => {
  const [offers, setOffers] = useState<MarketOffer[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [marketData, compareData] = await Promise.all([
        fetchHashrateMarket(),
        compareOffers(['braiins', 'mrr']),
      ]);
      const all = [...marketData.offers, ...compareData.offers];
      all.sort((a, b) => (b.metrics?.score ?? 0) - (a.metrics?.score ?? 0));
      setOffers(all);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const renderItem = ({ item }: { item: MarketOffer }) => (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.provider}>{item.provider}</Text>
        <Text style={styles.score}>score {item.metrics?.score?.toFixed(2) ?? '—'}</Text>
      </View>
      <View style={styles.grid}>
        <MetricCard title="Hashrate" value={`${item.hashrate} TH/s`} />
        <MetricCard
          title="Price /TH/day"
          value={`${(item.price_per_th_day * 1e6).toFixed(2)} sats`}
        />
        <MetricCard
          title="Daily Cost"
          value={`${(item.metrics?.daily_cost_btc ?? 0).toFixed(6)} BTC`}
        />
        <MetricCard
          title="Daily Rev"
          value={`${(item.metrics?.daily_revenue_btc ?? 0).toFixed(6)} BTC`}
        />
      </View>
    </View>
  );

  return (
    <FlatList
      style={styles.container}
      data={offers}
      keyExtractor={(item) => item.id}
      renderItem={renderItem}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.brand.DEFAULT} />}
      ListHeaderComponent={<Text style={styles.heading}>Hashrate Market</Text>}
      ListEmptyComponent={
        loading ? (
          <ActivityIndicator color={theme.brand.DEFAULT} style={styles.loader} />
        ) : (
          <Text style={styles.empty}>{error || 'No offers available'}</Text>
        )
      }
    />
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
    marginBottom: 12,
  },
  card: {
    backgroundColor: theme.bg.surface,
    borderRadius: 8,
    padding: 12,
    marginVertical: 6,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  provider: {
    color: theme.text.primary,
    fontSize: 16,
    fontWeight: '700',
    textTransform: 'uppercase',
  },
  score: {
    color: theme.brand.DEFAULT,
    fontSize: 12,
    fontWeight: '600',
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  loader: {
    marginTop: 24,
  },
  empty: {
    color: theme.text.secondary,
    textAlign: 'center',
    marginTop: 24,
    fontStyle: 'italic',
  },
});
