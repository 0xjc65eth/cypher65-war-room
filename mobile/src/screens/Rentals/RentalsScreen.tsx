import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, FlatList, RefreshControl, ActivityIndicator, TouchableOpacity } from 'react-native';
import { fetchRentals } from '../../api/client';
import { MetricCard } from '../../components/MetricCard';
import type { RentalsData, Rental } from '../../types';
import { theme } from '../../theme';

const fmtSats = (n: number | undefined | null): string => {
  if (n === undefined || n === null) return '—';
  if (n >= 1e8) return `${(n / 1e8).toFixed(4)} BTC`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M sats`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K sats`;
  return `${n} sats`;
};

const fmtDate = (ts: number | undefined | null): string => {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short' });
};

const statusColor = (status?: string): string => {
  const s = (status || '').toLowerCase();
  if (s.includes('active') || s.includes('running') || s.includes('started')) return theme.green.strong;
  if (s.includes('end') || s.includes('close') || s.includes('finish')) return theme.text.tertiary;
  return theme.brand.DEFAULT;
};

const RentalCard = ({ rental }: { rental: Rental }) => {
  const rigName = rental.rig?.name || rental.contract?.id || rental.id;
  const status = rental.status || rental.contract?.status || '—';
  const hr = rental.hashrate ?? rental.contract?.speed_ph ?? null;
  const price = rental.price_per_th ?? rental.contract?.price_sat_per_ph_day ?? null;
  const pl = rental.pl_pct;
  const delivery = rental.delivery_pct;

  return (
    <View style={styles.card}>
      <View style={styles.cardHead}>
        <Text style={styles.provider}>{rental.provider.toUpperCase()}</Text>
        {rental.blacklisted ? <Text style={styles.blacklistBadge}>⛔ BLACKLISTED</Text> : null}
        <Text style={[styles.status, { color: statusColor(status) }]}>{status}</Text>
      </View>
      <Text style={styles.rigName} numberOfLines={1}>{rigName}</Text>
      <View style={styles.grid}>
        <MetricCard title="Hashrate" value={hr ? `${hr} TH/s` : '—'} />
        <MetricCard
          title="Price /TH/h"
          value={price !== null && price !== undefined ? `${Number(price).toFixed(1)} sats` : '—'}
        />
        <MetricCard
          title="Delivery"
          value={delivery !== undefined && delivery !== null ? `${delivery.toFixed(0)}%` : '—'}
        />
        <MetricCard
          title="P/L"
          value={pl !== undefined && pl !== null ? `${pl.toFixed(1)}%` : '—'}
        />
      </View>
      <View style={styles.cardFoot}>
        <Text style={styles.date}>start {fmtDate(rental.started_at)}</Text>
        <Text style={styles.date}>end {fmtDate(rental.ends_at)}</Text>
        <Text style={styles.cost}>{fmtSats(rental.total_cost_sat ?? rental.paid_price_sat)}</Text>
      </View>
    </View>
  );
};

export const RentalsScreen = () => {
  const [data, setData] = useState<RentalsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'active' | 'history'>('active');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rentals = await fetchRentals();
      setData(rentals);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const mrr = data?.mrr;
  const braiins = data?.braiins;
  const signals = data?.market_signals;

  // Merge active contracts from both providers.
  const activeList: Rental[] = [
    ...(mrr?.active?.map((r) => ({ ...r, provider: 'mrr' as const })) ?? []),
    ...(braiins?.contracts?.map((c) => ({ ...c, provider: 'braiins' as const })) ?? []),
  ];
  const historyList: Rental[] = [
    ...(mrr?.history?.map((r) => ({ ...r, provider: 'mrr' as const })) ?? []),
  ];

  const noCreds = (mrr?.needs_auth && !mrr.active?.length && !mrr.history?.length) ||
    (braiins?.needs_auth && !braiins.contracts?.length);

  const list = tab === 'active' ? activeList : historyList;
  const emptyText = tab === 'active'
    ? (noCreds ? 'Configure MRR / Braiins keys in Settings to see rentals' : 'No active rentals')
    : 'No rental history yet';

  const renderHeader = () => (
    <>
      <Text style={styles.heading}>Rentals Hub</Text>
      {data?.portfolio ? (
        <View style={styles.portfolio}>
          <MetricCard title="Total Spent" value={fmtSats(data.portfolio.total_spent_sat)} />
          <MetricCard
            title="Avg Cost /TH/h"
            value={data.portfolio.weighted_avg_cost_sats_per_thh !== undefined
              ? `${Number(data.portfolio.weighted_avg_cost_sats_per_thh).toFixed(1)} sats` : '—'}
          />
          <MetricCard title="Avg Delivery" value={data.portfolio.avg_delivery_pct !== undefined
            ? `${Number(data.portfolio.avg_delivery_pct).toFixed(0)}%` : '—'} />
          <MetricCard title="Net P/L" value={fmtSats(data.portfolio.total_pl_sat)} />
        </View>
      ) : null}

      {signals?.overpay?.length ? (
        <View style={[styles.signal, styles.signalOverpay]}>
          <Text style={styles.signalTitle}>⚠️ {signals.overpay.length} expensive purchase(s) detected</Text>
          <Text style={styles.signalText} numberOfLines={2}>
            Up to {Math.max(...signals.overpay.map((s) => s.overpay_pct || 0))}% above market at purchase
          </Text>
        </View>
      ) : null}
      {signals?.arbitrage?.length ? (
        <View style={[styles.signal, styles.signalArb]}>
          <Text style={styles.signalTitle}>🏆 ARBITRAGE WINDOW OPEN</Text>
          <Text style={styles.signalText} numberOfLines={2}>{signals.arbitrage[0].message}</Text>
        </View>
      ) : null}

      {noCreds ? (
        <View style={[styles.signal, styles.signalWarn]}>
          <Text style={styles.signalTitle}>🔑 Provider credentials missing</Text>
          <Text style={styles.signalText}>Add your MRR / Braiins API keys in Settings to load rentals.</Text>
        </View>
      ) : null}

      <View style={styles.tabs}>
        <TouchableOpacity
          style={[styles.tab, tab === 'active' && styles.tabActive]}
          onPress={() => setTab('active')}
        >
          <Text style={[styles.tabText, tab === 'active' && styles.tabTextActive]}>ACTIVE ({activeList.length})</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, tab === 'history' && styles.tabActive]}
          onPress={() => setTab('history')}
        >
          <Text style={[styles.tabText, tab === 'history' && styles.tabTextActive]}>HISTORY ({historyList.length})</Text>
        </TouchableOpacity>
      </View>
    </>
  );

  return (
    <FlatList
      style={styles.container}
      data={list}
      keyExtractor={(item, idx) => `${item.provider}-${item.id}-${idx}`}
      renderItem={({ item }) => <RentalCard rental={item} />}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={theme.brand.DEFAULT} />}
      ListHeaderComponent={renderHeader}
      ListEmptyComponent={
        loading ? (
          <ActivityIndicator color={theme.brand.DEFAULT} style={styles.loader} />
        ) : (
          <Text style={styles.empty}>{error || emptyText}</Text>
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
  portfolio: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 10,
  },
  signal: {
    borderRadius: 8,
    padding: 10,
    marginVertical: 4,
  },
  signalOverpay: {
    backgroundColor: 'rgba(255, 23, 68, 0.10)',
    borderColor: 'rgba(255, 23, 68, 0.4)',
    borderWidth: 1,
  },
  signalArb: {
    backgroundColor: 'rgba(255, 215, 0, 0.10)',
    borderColor: 'rgba(255, 215, 0, 0.4)',
    borderWidth: 1,
  },
  signalWarn: {
    backgroundColor: 'rgba(255, 160, 0, 0.08)',
    borderColor: 'rgba(255, 160, 0, 0.35)',
    borderWidth: 1,
  },
  signalTitle: {
    color: theme.text.primary,
    fontSize: 13,
    fontWeight: '700',
    marginBottom: 2,
  },
  signalText: {
    color: theme.text.muted,
    fontSize: 12,
  },
  tabs: {
    flexDirection: 'row',
    gap: 8,
    marginTop: 8,
    marginBottom: 8,
  },
  tab: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 6,
    backgroundColor: theme.bg.overlay,
  },
  tabActive: {
    backgroundColor: theme.bg.brand,
  },
  tabText: {
    color: theme.text.tertiary,
    fontSize: 12,
    fontWeight: '700',
  },
  tabTextActive: {
    color: theme.text.onDeep,
  },
  card: {
    backgroundColor: theme.bg.surface,
    borderRadius: 8,
    padding: 12,
    marginVertical: 6,
  },
  cardHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 6,
  },
  provider: {
    color: theme.brand.DEFAULT,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.05,
  },
  status: {
    fontSize: 11,
    fontWeight: '600',
    textTransform: 'uppercase',
  },
  blacklistBadge: {
    color: theme.red.DEFAULT,
    fontSize: 10,
    fontWeight: '700',
  },
  rigName: {
    color: theme.text.primary,
    fontSize: 14,
    fontWeight: '600',
    marginBottom: 8,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  cardFoot: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 8,
  },
  date: {
    color: theme.text.secondary,
    fontSize: 10,
  },
  cost: {
    color: theme.green.strong,
    fontSize: 11,
    fontWeight: '700',
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
