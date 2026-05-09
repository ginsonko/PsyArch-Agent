import { Badge, Card, Group, Progress, Stack, Text } from '@mantine/core';
import type { ColumnDef } from '@tanstack/react-table';
import type { AnyRecord } from '../types/api';
import { formatNumber, shortDisplayText, shortText } from '../lib/format';
import { rowContextLabel, rowEnergy, rowObjectId, rowObjectType, type DisplayAggregateRow } from '../lib/displayAggregation';
import { VirtualDataTable } from './VirtualDataTable';
import { JsonInspector } from './JsonInspector';

type AggregateDetailProps = {
  value: AnyRecord | null | undefined;
  title?: string;
  maxHeight?: number;
};

function isAggregate(value: AnyRecord | null | undefined): value is DisplayAggregateRow {
  return Boolean(value && value.__displayAggregate && Array.isArray(value.aggregate_components));
}

const componentColumns: ColumnDef<AnyRecord>[] = [
  {
    header: '原始对象',
    cell: ({ row }) => (
      <div>
        <Text size="sm" fw={700}>
          {shortDisplayText(row.original.component_display || row.original.display || row.original.display_text || rowObjectId(row.original), 42)}
        </Text>
        <Text size="xs" c="dimmed">
          运行态组分，正式结构身份以完整特征解析为准
        </Text>
      </div>
    ),
  },
  {
    header: 'ID / 类型',
    cell: ({ row }) => `${shortText(row.original.component_object_id || rowObjectId(row.original) || '-', 22)} / ${row.original.component_object_type || rowObjectType(row.original)}`,
  },
  {
    header: '激活/审计链',
    cell: ({ row }) => shortDisplayText(row.original.component_context || rowContextLabel(row.original), 42),
  },
  {
    header: 'ER',
    cell: ({ row }) => formatNumber(row.original.component_er ?? rowEnergy(row.original).er, 4),
  },
  {
    header: 'EV',
    cell: ({ row }) => formatNumber(row.original.component_ev ?? rowEnergy(row.original).ev, 4),
  },
  {
    header: '总能量',
    cell: ({ row }) => formatNumber(row.original.component_total_energy ?? rowEnergy(row.original).total, 4),
  },
  {
    header: '占比',
    cell: ({ row }) => {
      const share = Number(row.original.component_energy_share || 0);
      return (
        <div className="aggregate-share-cell">
          <Text size="xs" fw={700}>{formatNumber(share * 100, 2)}%</Text>
          <Progress value={Math.max(0, Math.min(100, share * 100))} size="xs" radius="xs" />
        </div>
      );
    },
  },
];

export function AggregateDetail({ value, title = '聚合对象详情', maxHeight = 260 }: AggregateDetailProps) {
  if (!isAggregate(value)) {
    return <JsonInspector value={value || {}} title={title} maxHeight={maxHeight} />;
  }

  return (
    <Card className="aggregate-detail-card">
      <Group justify="space-between" align="flex-start" mb="sm">
        <div>
          <Text fw={800}>{title}</Text>
          <Text size="xs" c="dimmed">
            前端显示聚合只汇总可见特征内容，不改变后端状态池、HDB 或对象 id；下方组分用于查看激活/审计链与能量来源差异。
          </Text>
        </div>
        <Badge variant="light">{value.aggregate_component_count} 个组分</Badge>
      </Group>
      <div className="friendly-detail-grid">
        <div className="friendly-detail-item">
          <Text size="xs" c="dimmed">显示特征</Text>
          <Text fw={700}>{shortDisplayText(value.aggregate_display, 80)}</Text>
        </div>
        <div className="friendly-detail-item">
          <Text size="xs" c="dimmed">聚合 ER / EV</Text>
          <Text fw={700}>{formatNumber(value.aggregate_total_er, 4)} / {formatNumber(value.aggregate_total_ev, 4)}</Text>
        </div>
        <div className="friendly-detail-item">
          <Text size="xs" c="dimmed">聚合总能量</Text>
          <Text fw={700}>{formatNumber(value.aggregate_total_energy, 4)}</Text>
        </div>
        <div className="friendly-detail-item">
          <Text size="xs" c="dimmed">激活链数量</Text>
          <Text fw={700}>{value.aggregate_context_count}</Text>
        </div>
      </div>
      <Stack gap={6} mt="sm">
        <Text size="xs" c="dimmed">
          主要激活链：{shortDisplayText(value.aggregate_context_summary, 160)}
        </Text>
        <Text size="xs" c="dimmed">
          原始对象：{shortText(value.aggregate_ref_summary, 160)}
        </Text>
        <Text size="xs" c="dimmed">
          {value.aggregate_note || '这是观察层汇总，不会写回运行态。'}
        </Text>
      </Stack>
      <Text fw={800} mt="md" mb="xs">组分明细</Text>
      <VirtualDataTable
        data={value.aggregate_components}
        columns={componentColumns}
        height={Math.min(maxHeight, 360)}
        estimateRowHeight={58}
        getRowKey={(row, index) => `${row.component_object_id || rowObjectId(row) || 'component'}:${index}`}
      />
      <JsonInspector value={value} title="高级原始数据" maxHeight={220} />
    </Card>
  );
}
