import ReactECharts from 'echarts-for-react';
import { ActionIcon, Badge, Card, Divider, Group, Modal, Stack, Text, useMantineColorScheme } from '@mantine/core';
import { useMemo } from 'react';
import { useDisclosure } from '@mantine/hooks';
import { IconMaximize } from '@tabler/icons-react';
import type { ChartConfig } from '../data/metricCatalog';
import { chartInfluenceHints, metricDisplayName, metricMeaning } from '../data/metricCatalog';
import type { MetricRow } from '../types/api';
import { asNumber, formatNumber } from '../lib/format';
import { metricSeriesStats, visibleMetricKeys } from '../lib/metricStats';

type MetricChartProps = {
  rows: MetricRow[];
  config: ChartConfig;
  height?: number;
};

const colors = ['#20c997', '#4dabf7', '#ffd43b', '#ff8787', '#b197fc', '#63e6be', '#ffa94d', '#91a7ff'];

export function MetricChart({ rows, config, height = 280 }: MetricChartProps) {
  const [opened, { open, close }] = useDisclosure(false);
  const { colorScheme } = useMantineColorScheme();
  const dark = colorScheme !== 'light';
  const seriesStats = useMemo(
    () => config.keys.map((key) => metricSeriesStats(rows, key)),
    [config.keys, rows],
  );
  const visibleKeys = useMemo(() => visibleMetricKeys(rows, config), [config, rows]);
  const hiddenZeroKeys = seriesStats.filter((stats) => stats.hasAnyValue && stats.allZero && !config.preserveFlatLineKeys?.includes(stats.key));
  const option = useMemo(() => {
    const xData = rows.map((row, index) => row.tick_index ?? row.tick ?? index);
    const textColor = dark ? 'rgba(235, 250, 247, .78)' : 'rgba(25, 45, 52, .76)';
    const axisColor = dark ? 'rgba(235, 250, 247, .58)' : 'rgba(25, 45, 52, .62)';
    const lineColor = dark ? 'rgba(255,255,255,.12)' : 'rgba(18, 52, 62, .12)';
    return {
      backgroundColor: 'transparent',
      color: colors,
      tooltip: {
        trigger: 'axis',
        valueFormatter: (value: unknown) => formatNumber(value, 4),
      },
      legend: {
        top: 0,
        textStyle: { color: textColor },
        type: 'scroll',
      },
      grid: { left: 42, right: 18, top: 54, bottom: 38 },
      dataZoom: rows.length > 20 ? [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 8 }] : [{ type: 'inside' }],
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: xData,
        axisLine: { lineStyle: { color: lineColor } },
        axisLabel: { color: axisColor },
      },
      yAxis: {
        type: 'value',
        scale: true,
        splitLine: { lineStyle: { color: lineColor } },
        axisLabel: { color: axisColor },
      },
      series: visibleKeys.map((key) => ({
        name: metricDisplayName(key),
        type: config.type === 'bar' || config.type === 'bar_grouped' || config.type === 'bar_stacked' ? 'bar' : 'line',
        stack: config.type === 'bar_stacked' ? 'total' : undefined,
        smooth: config.type !== 'bar' && config.type !== 'bar_grouped' && config.type !== 'bar_stacked',
        showSymbol: rows.length < 80,
        symbolSize: 4,
        areaStyle: config.type === 'area' ? { opacity: 0.12 } : undefined,
        data: rows.map((row) => asNumber(row[key], 0)),
      })),
    };
  }, [config, dark, rows, visibleKeys]);

  const hasData = rows.length > 0 && visibleKeys.length > 0;
  const hints = chartInfluenceHints(config);
  const shownStats = seriesStats.filter((stats) => visibleKeys.includes(stats.key));
  const topStats = shownStats.slice(0, 4);
  const body = (
    <>
      {hasData ? (
        <ReactECharts option={option} style={{ height }} notMerge lazyUpdate />
      ) : (
        <div className="empty-chart">当前运行没有这些指标。</div>
      )}
    </>
  );

  return (
    <>
    <Card className="chart-card">
      <Group justify="space-between" align="flex-start" gap="sm" mb="xs">
        <div className="chart-title-block">
          <Text fw={700}>{config.title}</Text>
          <Text size="xs" c="dimmed">
            {config.subtitle ? `${config.subtitle}。` : ''}{config.description}
          </Text>
          {hiddenZeroKeys.length ? (
            <Text size="xs" c="dimmed">
              已自动隐藏 {hiddenZeroKeys.length} 条全 0 曲线，避免旧口径或关闭开关指标干扰阅读。
            </Text>
          ) : null}
        </div>
        <ActionIcon variant="light" onClick={open} aria-label="放大图表">
          <IconMaximize size={16} />
        </ActionIcon>
      </Group>
      {body}
      {topStats.length ? (
        <div className="chart-stats-strip">
          {topStats.map((stats) => (
            <div key={stats.key} className="chart-stat-chip">
              <Text size="xs" fw={700}>{metricDisplayName(stats.key)}</Text>
              <Text size="xs" c="dimmed">
                均 {formatNumber(stats.mean, 3)} / 中 {formatNumber(stats.median, 3)} / 峰 {formatNumber(stats.max, 3)} / 新 {formatNumber(stats.latest, 3)}
              </Text>
            </div>
          ))}
        </div>
      ) : null}
      <Group gap={6} mt="xs" className="chart-metric-tags">
        {visibleKeys.slice(0, 8).map((key) => (
          <Badge key={key} variant="light" size="sm">
            {metricDisplayName(key)}
          </Badge>
        ))}
        {visibleKeys.length > 8 ? <Badge variant="outline" size="sm">+{visibleKeys.length - 8}</Badge> : null}
        {hiddenZeroKeys.length ? <Badge variant="outline" size="sm">已藏 0 线 {hiddenZeroKeys.length}</Badge> : null}
      </Group>
    </Card>
    <Modal opened={opened} onClose={close} title={config.title} size="95vw" classNames={{ content: 'chart-modal-content' }}>
      <Stack>
        <Text size="sm" c="dimmed">
          {config.subtitle ? `${config.subtitle}。` : ''}{config.description}
        </Text>
        {hasData ? (
          <ReactECharts option={option} style={{ height: 560 }} notMerge lazyUpdate />
        ) : (
          <div className="empty-chart">当前运行没有非零数据；全 0 或缺失指标已被隐藏。</div>
        )}
        <Divider />
        <div>
          <Text fw={800} mb={6}>这张图有什么用</Text>
          <Stack gap={4}>
            {hints.map((hint) => (
              <Text key={hint} size="sm" c="dimmed">{hint}</Text>
            ))}
            <Text size="sm" c="dimmed">
              阅读建议：先看“最新值”和“首末变化”判断当前状态，再看平均值/中位数判断长期水平；如果最大值远高于中位数，通常说明存在尖峰或短时异常。
            </Text>
            {hiddenZeroKeys.length ? (
              <Text size="sm" c="dimmed">
                本图隐藏了 {hiddenZeroKeys.length} 条全 0 曲线：{hiddenZeroKeys.map((item) => metricDisplayName(item.key)).join('、')}。这些通常来自旧口径指标、关闭的模块开关或当前数据集未触发的链路。
              </Text>
            ) : null}
          </Stack>
        </div>
        <div>
          <Text fw={800} mb={6}>指标统计</Text>
          <div className="metric-stat-grid">
            {shownStats.map((stats) => (
              <Card key={stats.key} className="metric-explain-card">
                <Text fw={700} size="sm">{metricDisplayName(stats.key)}</Text>
                <Text size="xs" c="dimmed">技术键：{stats.key}</Text>
                <div className="metric-stat-table">
                  <span>平均值</span><strong>{formatNumber(stats.mean, 4)}</strong>
                  <span>中位数</span><strong>{formatNumber(stats.median, 4)}</strong>
                  <span>最大值</span><strong>{formatNumber(stats.max, 4)}</strong>
                  <span>最小值</span><strong>{formatNumber(stats.min, 4)}</strong>
                  <span>最新值</span><strong>{formatNumber(stats.latest, 4)}</strong>
                  <span>非零点</span><strong>{stats.nonZeroCount} / {stats.count}</strong>
                </div>
              </Card>
            ))}
          </div>
        </div>
        <div>
          <Text fw={800} mb={6}>包含指标解释</Text>
          <div className="metric-explain-grid">
            {visibleKeys.map((key) => (
              <Card key={key} className="metric-explain-card">
                <Text fw={700} size="sm">{metricDisplayName(key)}</Text>
                <Text size="xs" c="dimmed">技术键：{key}</Text>
                <Text size="xs" mt={6}>{metricMeaning(key)}</Text>
              </Card>
            ))}
          </div>
        </div>
      </Stack>
    </Modal>
    </>
  );
}
