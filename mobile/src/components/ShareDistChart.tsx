import React from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import Svg, { Rect, Line } from 'react-native-svg';
import type { ShareDistData } from '../types';

// Live Mining → Probability parity (P0-1): the share-difficulty histogram with
// the network target rendered as a solid purple reference line + target badge.
// Mirrors the web dashboard (`_applyShareDistTarget` + annotation plugin):
// the server already sends `target_diff` / `target_bucket` (null when
// unavailable) — this component only draws them, never fabricates data.

const TARGET_COLOR = '#a855f7';
const BAR_COLOR = '#10b981';
const VIEW_W = 280;
const CHART_HEIGHT = 120;

// Human difficulty formatting — EXACT parity with the web badge:
// static/app.js `fmt._diffFromNum` (units ['',K,M,G,T,P,E], toFixed 2 unless
// x >= 100 → 0, space before the unit). The '—' fallback for null/0 mirrors
// the web badge's `data.target_diff ? ... : 'target —'` branch.
export function formatDiff(v: number | null | undefined): string {
  if (v === null || v === undefined || !isFinite(v) || v === 0) return '—';
  const units = ['', 'K', 'M', 'G', 'T', 'P', 'E'];
  let i = 0;
  let x = Math.abs(v);
  while (x >= 1000 && i < units.length - 1) {
    x /= 1000;
    i++;
  }
  return `${x.toFixed(x >= 100 ? 0 : 2)} ${units[i]}`.trim();
}

// X position (viewBox units) of the target line — bucket center, clamped to
// the histogram. Pure + exported for unit tests.
export function targetLineX(
  bucket: number | null | undefined,
  nBuckets: number,
  width: number
): number | null {
  if (bucket === null || bucket === undefined || nBuckets <= 0) return null;
  if (!isFinite(width) || width <= 0) return null;
  const b = Math.max(0, Math.min(nBuckets - 1, bucket));
  return ((b + 0.5) / nBuckets) * width;
}

interface Props {
  data: ShareDistData | null;
  loading: boolean;
  error: string | null;
}

export const ShareDistChart = ({ data, loading, error }: Props) => {
  const values = data?.datasets?.[0]?.data ?? [];
  const labels = data?.labels ?? [];
  const n = labels.length;
  const max = values.length ? Math.max(...values) : 0;

  if (loading && !data) {
    return <ActivityIndicator color="#38bdf8" style={styles.loading} />;
  }
  if (error && !data) {
    return <Text style={styles.empty}>{error}</Text>;
  }
  if (!data || n === 0) {
    return <Text style={styles.empty}>No shares yet this session — keep hashing.</Text>;
  }

  const barW = VIEW_W / n;
  const targetX = targetLineX(data.target_bucket, n, VIEW_W);

  return (
    <View>
      <View style={styles.badgeRow}>
        <Text style={styles.badgeLabel}>target</Text>
        <Text style={styles.badgeValue}>{formatDiff(data.target_diff)}</Text>
        {data.count != null && (
          <Text style={styles.badgeCount}>{data.count} shares</Text>
        )}
      </View>
      <Svg width="100%" height={CHART_HEIGHT} viewBox={`0 0 ${VIEW_W} ${CHART_HEIGHT}`}>
        {values.map((v, i) => {
          const h = max > 0 ? (v / max) * (CHART_HEIGHT - 10) : 2;
          return (
            <Rect
              key={i}
              x={i * barW + 1}
              y={CHART_HEIGHT - h}
              width={Math.max(2, barW - 2)}
              height={h}
              fill={BAR_COLOR}
              opacity={0.85}
              rx={1}
            />
          );
        })}
        {targetX !== null && (
          <Line
            testID="share-dist-target-line"
            x1={targetX}
            y1={2}
            x2={targetX}
            y2={CHART_HEIGHT - 2}
            stroke={TARGET_COLOR}
            strokeWidth={1.5}
          />
        )}
      </Svg>
    </View>
  );
};

const styles = StyleSheet.create({
  loading: {
    marginVertical: 16,
  },
  empty: {
    color: '#64748b',
    fontStyle: 'italic',
    paddingVertical: 12,
  },
  badgeRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 8,
  },
  badgeLabel: {
    color: '#64748b',
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: 0.08,
  },
  badgeValue: {
    color: TARGET_COLOR,
    fontSize: 13,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  badgeCount: {
    color: '#64748b',
    fontSize: 11,
    marginLeft: 'auto',
  },
});
