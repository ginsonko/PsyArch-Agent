import { Badge, Card, Divider, Group, Stack, Text } from '@mantine/core';
import type { ColumnDef } from '@tanstack/react-table';
import type { AnyRecord } from '../types/api';
import { asArray, formatCount, formatNumber, shortDisplayText, shortText } from '../lib/format';
import { JsonInspector } from './JsonInspector';
import { VirtualDataTable } from './VirtualDataTable';

type ObjectDetailProps = {
  value: AnyRecord | null | undefined;
  title?: string;
  maxHeight?: number;
};

function payloadOf(value: AnyRecord | null | undefined): AnyRecord {
  if (!value || typeof value !== 'object') return {};
  return (value.data || value) as AnyRecord;
}

function primaryOf(payload: AnyRecord): AnyRecord {
  if (!payload || typeof payload !== 'object') return {};
  return (payload.structure || payload.group || payload.item || payload.snapshot || payload) as AnyRecord;
}

function displayOf(value: AnyRecord): string {
  const nestedStructure = value.structure && typeof value.structure === 'object' ? value.structure : null;
  const nestedGroup = value.group && typeof value.group === 'object' ? value.group : null;
  const targetStats = value.target_structure_stats && typeof value.target_structure_stats === 'object' ? value.target_structure_stats : null;
  return shortDisplayText(
    value.target_display_text ||
      value.residual_display_text ||
      value.display ||
      value.display_text ||
      value.content_display ||
      value.grouped_display_text ||
      value.title ||
      nestedStructure?.display ||
      nestedStructure?.display_text ||
      nestedStructure?.structure?.display_text ||
      nestedGroup?.display ||
      targetStats?.display ||
      targetStats?.display_text ||
      value.structure_id ||
      value.group_id ||
      value.target_id ||
      value.item_id ||
      value.ref_object_id ||
      value.id ||
      '未选择对象',
    9999,
  );
}

function idOf(value: AnyRecord): string {
  const nestedStructure = value.structure && typeof value.structure === 'object' ? value.structure : null;
  const nestedGroup = value.group && typeof value.group === 'object' ? value.group : null;
  return String(
    value.structure_id ||
      value.group_id ||
      value.target_id ||
      value.item_id ||
      value.ref_object_id ||
      value.memory_id ||
      value.id ||
      nestedStructure?.id ||
      nestedStructure?.structure_id ||
      nestedGroup?.id ||
      nestedGroup?.group_id ||
      '-',
  );
}

function typeOf(value: AnyRecord): string {
  if (value.target_id) return '残差项';
  if (value.group_id && value.required_structures) return '结构组索引';
  return String(value.ref_object_type || value.object_type || value.type || value.sub_type || value.row_kind || '-');
}

function provenanceOf(value: AnyRecord): string {
  return String(
    value.context_summary ||
      value.context_text ||
      value.context_id ||
      value.context_ref_object_id ||
      value.context_owner_structure_id ||
      value.growth_source ||
      value.provenance_owner_structure_id ||
      value.owner_structure_id ||
      value.structure_db_id ||
      value.source?.context_ref_object_id ||
      value.source?.origin_id ||
      '无显式来源',
  );
}

function weightOf(value: AnyRecord): unknown {
  return (
    value.base_weight ??
    value.weight ??
    value.group_stats?.base_weight ??
    value.stats?.base_weight ??
    value.total_energy ??
    value.energy ??
    value.ratio ??
    value.score
  );
}

function structureDbOf(payload: AnyRecord, primary: AnyRecord): AnyRecord {
  return (payload.structure_db || primary.structure_db || {}) as AnyRecord;
}

function collectGenericChildren(payload: AnyRecord, primary: AnyRecord): AnyRecord[] {
  const candidates = [
    payload.database_items,
    payload.db_items,
    payload.entries,
    payload.residual_entries,
    payload.children,
    payload.members,
    payload.items,
    payload.recent_structures,
    payload.recent_groups,
    payload.recent_episodic,
    payload.recent_memory_activations,
    primary.database_items,
    primary.db_items,
    primary.entries,
    primary.children,
    primary.members,
    primary.items,
  ];
  for (const candidate of candidates) {
    const rows = asArray<AnyRecord>(candidate);
    if (rows.length) return rows;
  }
  return [];
}

const childColumns: ColumnDef<AnyRecord>[] = [
  { header: '内容/关系', cell: ({ row }) => shortDisplayText(displayOf(row.original), 44) },
  { header: 'ID', cell: ({ row }) => shortText(idOf(row.original), 30) },
  { header: '类型', cell: ({ row }) => typeOf(row.original) },
  { header: '权重/能量', cell: ({ row }) => formatNumber(weightOf(row.original), 4) },
  { header: '来源/备注', cell: ({ row }) => shortDisplayText(provenanceOf(row.original), 36) },
];

const diffColumns: ColumnDef<AnyRecord>[] = [
  { header: '残差对象', cell: ({ row }) => shortDisplayText(displayOf(row.original), 44) },
  { header: '目标 ID', cell: ({ row }) => shortText(row.original.target_id || idOf(row.original), 30) },
  { header: '关系', cell: ({ row }) => shortText(row.original.relation_type || row.original.kind || row.original.ext?.relation_type || '-', 24) },
  { header: '权重', cell: ({ row }) => formatNumber(weightOf(row.original), 4) },
  { header: '签名', cell: ({ row }) => shortText(row.original.target_signature || row.original.content_signature || row.original.semantic_signature || '-', 42) },
];

const groupColumns: ColumnDef<AnyRecord>[] = [
  { header: '结构组', cell: ({ row }) => shortDisplayText(displayOf(row.original), 42) },
  { header: 'Group ID', cell: ({ row }) => shortText(row.original.group_id || idOf(row.original), 30) },
  {
    header: '基础/近因/疲劳',
    cell: ({ row }) =>
      `${formatNumber(row.original.group_stats?.base_weight ?? row.original.base_weight, 3)} / ${formatNumber(row.original.group_stats?.recent_gain, 3)} / ${formatNumber(row.original.group_stats?.fatigue, 3)}`,
  },
  { header: '必要结构', cell: ({ row }) => formatCount(asArray(row.original.required_structures).length || asArray(row.original.required_structure_ids).length) },
  { header: '偏置结构', cell: ({ row }) => formatCount(asArray(row.original.bias_structures).length || asArray(row.original.bias_structure_ids).length) },
];

const refColumns: ColumnDef<AnyRecord>[] = [
  { header: '结构', cell: ({ row }) => shortDisplayText(displayOf(row.original), 44) },
  { header: 'ID', cell: ({ row }) => shortText(idOf(row.original), 30) },
  { header: '类型', cell: ({ row }) => typeOf(row.original) },
  { header: '权重', cell: ({ row }) => formatNumber(weightOf(row.original), 4) },
  { header: '签名', cell: ({ row }) => shortText(row.original.content_signature || row.original.semantic_signature || row.original.signature || '-', 42) },
];

function DetailTable({
  title,
  note,
  rows,
  columns,
  height,
}: {
  title: string;
  note?: string;
  rows: AnyRecord[];
  columns: ColumnDef<AnyRecord>[];
  height: number;
}) {
  if (!rows.length) return null;
  return (
    <div className="object-detail-section">
      <Group justify="space-between" align="flex-start" mt="md" mb="xs">
        <div>
          <Text fw={800}>{title}</Text>
          {note ? (
            <Text size="xs" c="dimmed">
              {note}
            </Text>
          ) : null}
        </div>
        <Badge variant="light">{formatCount(rows.length)}</Badge>
      </Group>
      <VirtualDataTable data={rows} columns={columns} height={height} estimateRowHeight={58} />
    </div>
  );
}

export function ObjectDetail({ value, title = '对象详情', maxHeight = 420 }: ObjectDetailProps) {
  const payload = payloadOf(value);
  const primary = primaryOf(payload);
  const structureDb = structureDbOf(payload, primary);
  const diffRows = asArray<AnyRecord>(structureDb.diff_table || payload.diff_table || primary.diff_table);
  const groupRows = asArray<AnyRecord>(structureDb.group_table || payload.group_table || primary.group_table);
  const requiredRows = asArray<AnyRecord>(payload.required_structures || primary.required_structures || primary.required_structure_refs);
  const biasRows = asArray<AnyRecord>(payload.bias_structures || primary.bias_structures || primary.bias_structure_refs);
  const rows = collectGenericChildren(payload, primary);
  const attrs = asArray(primary.runtime_bound_attribute_units || primary.bound_attribute_displays || primary.attribute_displays);
  const aliases = asArray(primary.ref_alias_ids || primary.alias_ids);
  const stats = primary.stats || {};
  const pointerInfo = payload.pointer_info || primary.pointer_info || {};
  const hasAdvancedTables = Boolean(diffRows.length || groupRows.length || requiredRows.length || biasRows.length || rows.length);

  return (
    <Card className="object-detail-card">
      <Group justify="space-between" align="flex-start" mb="sm">
        <div>
          <Text fw={800}>{title}</Text>
          <Text size="xs" c="dimmed">
            优先翻译成可观察字段；原始 JSON 仅保留在底部高级审计区。
          </Text>
        </div>
        <Badge variant="light">{typeOf(primary)}</Badge>
      </Group>
      <div className="friendly-detail-grid">
        <div className="friendly-detail-item">
          <Text size="xs" c="dimmed">显示内容</Text>
          <Text fw={700}>{shortDisplayText(displayOf(primary), 90)}</Text>
        </div>
        <div className="friendly-detail-item">
          <Text size="xs" c="dimmed">对象 ID</Text>
          <Text fw={700}>{shortText(idOf(primary), 70)}</Text>
        </div>
        <div className="friendly-detail-item">
          <Text size="xs" c="dimmed">ER / EV / CP</Text>
          <Text fw={700}>
            {formatNumber(primary.er ?? primary.energy?.er ?? stats.runtime_er, 4)} / {formatNumber(primary.ev ?? primary.energy?.ev ?? stats.runtime_ev, 4)} / {formatNumber(primary.cp_abs ?? primary.energy?.cp_abs, 4)}
          </Text>
        </div>
        <div className="friendly-detail-item">
          <Text size="xs" c="dimmed">来源/激活路径</Text>
          <Text fw={700}>{shortDisplayText(provenanceOf(primary), 80)}</Text>
        </div>
        <div className="friendly-detail-item">
          <Text size="xs" c="dimmed">结构数据库</Text>
          <Text fw={700}>{shortText(structureDb.structure_db_id || primary.db_pointer?.structure_db_id || '-', 70)}</Text>
        </div>
        <div className="friendly-detail-item">
          <Text size="xs" c="dimmed">库所有者</Text>
          <Text fw={700}>{shortText(structureDb.owner_structure_id || pointerInfo.owner_structure_id || '-', 70)}</Text>
        </div>
      </div>
      <Stack gap={6} mt="sm">
        {aliases.length ? <Text size="xs" c="dimmed">别名：{shortText(aliases.join(' / '), 180)}</Text> : null}
        {attrs.length ? <Text size="xs" c="dimmed">属性：{shortText(attrs.map((item) => typeof item === 'string' ? item : item.display || item.attribute_name || JSON.stringify(item)).join('；'), 220)}</Text> : null}
        {primary.structure?.content_signature || primary.content_signature || primary.semantic_signature ? (
          <Text size="xs" c="dimmed">签名：{shortText(primary.structure?.content_signature || primary.content_signature || primary.semantic_signature, 220)}</Text>
        ) : null}
        {structureDb.integrity ? (
          <Text size="xs" c="dimmed">数据库完整性：{shortText(JSON.stringify(structureDb.integrity), 180)}</Text>
        ) : null}
      </Stack>
      {hasAdvancedTables ? (
        <Divider my="sm" />
      ) : (
        <Text size="sm" c="dimmed" mt="md">
          当前对象没有可展开的局部数据库表或子项；可以在 HDB 快照中点击结构 ST / 结构组 SG 下钻查看更多。
        </Text>
      )}
      <DetailTable
        title="局部残差表 diff_table"
        note="该结构数据库中可被感应赋能或继续查存的残差对象；这里只做观察展示，不合并后端 ID。"
        rows={diffRows}
        columns={diffColumns}
        height={Math.min(maxHeight, 320)}
      />
      <DetailTable
        title="结构组表 group_table"
        note="结构级查存一体使用的局部结构组索引，包含必要结构与偏置结构引用。"
        rows={groupRows}
        columns={groupColumns}
        height={Math.min(maxHeight, 300)}
      />
      <DetailTable
        title="必要结构 required"
        rows={requiredRows}
        columns={refColumns}
        height={Math.min(maxHeight, 240)}
      />
      <DetailTable
        title="偏置结构 bias"
        rows={biasRows}
        columns={refColumns}
        height={Math.min(maxHeight, 240)}
      />
      <DetailTable
        title="对象子项 / 快照列表"
        rows={rows}
        columns={childColumns}
        height={Math.min(maxHeight, 320)}
      />
      {value ? (
        <details className="advanced-json-details">
          <summary>高级原始数据 JSON</summary>
          <JsonInspector value={value || {}} title="高级原始数据" maxHeight={240} />
        </details>
      ) : null}
    </Card>
  );
}
