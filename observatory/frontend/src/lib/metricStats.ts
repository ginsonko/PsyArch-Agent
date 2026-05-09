import type { ChartConfig } from '../data/metricCatalog';
import type { MetricRow } from '../types/api';

export type MetricSeriesStats = {
  key: string;
  values: number[];
  count: number;
  nonZeroCount: number;
  mean: number;
  median: number;
  min: number;
  max: number;
  latest: number;
  first: number;
  delta: number;
  allZero: boolean;
  hasAnyValue: boolean;
};

function numericValues(rows: MetricRow[], key: string): number[] {
  return rows
    .map((row) => {
      const value = row?.[key];
      if (value === undefined || value === null || value === '') return null;
      const numberValue = Number(value);
      return Number.isFinite(numberValue) ? numberValue : null;
    })
    .filter((value): value is number => value !== null);
}

export function metricSeriesStats(rows: MetricRow[], key: string): MetricSeriesStats {
  const values = numericValues(rows, key);
  const sorted = values.slice().sort((a, b) => a - b);
  const count = values.length;
  const latest = count ? values[count - 1] : 0;
  const first = count ? values[0] : 0;
  const nonZeroCount = values.filter((value) => Math.abs(value) > 1e-12).length;
  return {
    key,
    values,
    count,
    nonZeroCount,
    mean: count ? values.reduce((sum, value) => sum + value, 0) / count : 0,
    median: count ? sorted[Math.floor(count / 2)] : 0,
    min: count ? sorted[0] : 0,
    max: count ? sorted[count - 1] : 0,
    latest,
    first,
    delta: latest - first,
    allZero: count > 0 && nonZeroCount === 0,
    hasAnyValue: count > 0,
  };
}

export function visibleMetricKeys(rows: MetricRow[], config: ChartConfig): string[] {
  return config.keys.filter((key) => {
    const stats = metricSeriesStats(rows, key);
    if (!stats.hasAnyValue) return false;
    if (stats.allZero && !config.preserveFlatLineKeys?.includes(key)) return false;
    return true;
  });
}

export function chartHasVisibleData(rows: MetricRow[], config: ChartConfig): boolean {
  return visibleMetricKeys(rows, config).length > 0;
}

