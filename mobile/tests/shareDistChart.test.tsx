import React from 'react';
import { render, screen } from '@testing-library/react-native';
import { ShareDistChart, formatDiff, targetLineX } from '../src/components/ShareDistChart';
import type { ShareDistData } from '../src/types';

const fixture: ShareDistData = {
  labels: ['10M', '20M', '30M', '40M'],
  count: 12,
  target_diff: 7.19e7,
  target_bucket: 2,
  datasets: [
    {
      label: 'Shares',
      data: [3, 5, 2, 1],
      fill: true,
      borderColor: '#10b981',
      backgroundColor: 'rgba(16,185,129,0.1)',
      tension: 0.3,
    },
  ],
};

describe('formatDiff', () => {
  it('formats on the same scale as the web fmt.diff', () => {
    expect(formatDiff(7.19e7)).toBe('71.90 M');
    expect(formatDiff(1.5e12)).toBe('1.50 T');
    expect(formatDiff(2.3e9)).toBe('2.30 G');
    expect(formatDiff(4.2e3)).toBe('4.20 K');
    expect(formatDiff(123)).toBe('123'); // x >= 100 → 0 decimals, like the web
  });

  it('renders a dash for missing/non-finite values', () => {
    expect(formatDiff(null)).toBe('—');
    expect(formatDiff(undefined)).toBe('—');
    expect(formatDiff(0)).toBe('—');
    expect(formatDiff(NaN)).toBe('—');
    expect(formatDiff(Infinity)).toBe('—');
  });
});

describe('targetLineX', () => {
  it('maps the target bucket to its bar center', () => {
    expect(targetLineX(2, 4, 280)).toBeCloseTo(((2 + 0.5) / 4) * 280);
  });

  it('clamps out-of-range buckets into the histogram', () => {
    expect(targetLineX(9, 4, 280)).toBeCloseTo(((3 + 0.5) / 4) * 280);
    expect(targetLineX(-3, 4, 280)).toBeCloseTo(((0 + 0.5) / 4) * 280);
  });

  it('returns null when the target is unknown or the chart is empty', () => {
    expect(targetLineX(null, 4, 280)).toBeNull();
    expect(targetLineX(undefined, 4, 280)).toBeNull();
    expect(targetLineX(2, 0, 280)).toBeNull();
  });
});

describe('ShareDistChart', () => {
  it('renders the target badge and the purple reference line', () => {
    render(<ShareDistChart data={fixture} loading={false} error={null} />);
    expect(screen.getByText('target')).toBeTruthy();
    expect(screen.getByText('71.90 M')).toBeTruthy();
    expect(screen.getByText('12 shares')).toBeTruthy();
    expect(screen.getByTestId('share-dist-target-line')).toBeTruthy();
  });

  it('shows an empty state when the session has no shares', () => {
    render(
      <ShareDistChart
        data={{ labels: [], count: 0, target_diff: null, target_bucket: null, datasets: [] }}
        loading={false}
        error={null}
      />
    );
    expect(screen.getByText(/No shares yet/)).toBeTruthy();
  });

  it('renders no target line when the server sends null target', () => {
    render(
      <ShareDistChart
        data={{ ...fixture, target_diff: null, target_bucket: null }}
        loading={false}
        error={null}
      />
    );
    expect(screen.queryByTestId('share-dist-target-line')).toBeNull();
    expect(screen.getByText('—')).toBeTruthy(); // badge falls back to dash
  });
});
