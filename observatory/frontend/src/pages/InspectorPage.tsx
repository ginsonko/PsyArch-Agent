import { Badge, Button, Card, Grid, Group, NumberInput, Select, Stack, Text, TextInput, Title } from '@mantine/core';
import { useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { api } from '../lib/api';
import { asArray, formatCount, formatNumber, shortDisplayText, shortText } from '../lib/format';
import type { AnyRecord } from '../types/api';
import { JsonInspector } from '../components/JsonInspector';
import { VirtualDataTable } from '../components/VirtualDataTable';
import { MetricCard } from '../components/MetricCard';
import { ObjectDetail } from '../components/ObjectDetail';
import { LoadingPanel } from '../components/LoadingPanel';

type InspectorMode = 'structure' | 'group' | 'episodic' | 'state' | 'hdb';

function stateRows(snapshot: AnyRecord | null): AnyRecord[] {
  const root = snapshot?.snapshot || snapshot || {};
  return [
    ...asArray(root.top_items).map((item) => ({ ...item, row_kind: '状态池 Top' })),
    ...asArray(root.er_top_items).map((item) => ({ ...item, row_kind: 'ER Top' })),
    ...asArray(root.ev_top_items).map((item) => ({ ...item, row_kind: 'EV Top' })),
  ];
}

function hdbRows(snapshot: AnyRecord | null): AnyRecord[] {
  const root = snapshot || {};
  return [
    ...asArray(root.recent_structures).map((item) => ({ ...item, row_kind: '结构 ST' })),
    ...asArray(root.recent_groups).map((item) => ({ ...item, row_kind: '结构组 SG' })),
    ...asArray(root.recent_episodic).map((item) => ({ ...item, row_kind: '情节记忆 EM' })),
    ...asArray(root.recent_memory_activations).map((item) => ({ ...item, row_kind: '记忆激活' })),
  ];
}

export function InspectorPage() {
  const [mode, setMode] = useState<InspectorMode>('structure');
  const [value, setValue] = useState('');
  const [limit, setLimit] = useState(20);
  const [result, setResult] = useState<AnyRecord | null>(null);
  const [stateSnapshot, setStateSnapshot] = useState<AnyRecord | null>(null);
  const [hdbSnapshot, setHdbSnapshot] = useState<AnyRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);

  async function refreshSnapshots() {
    const [statePayload, hdbPayload] = await Promise.all([api.state().catch(() => null), api.hdb().catch(() => null)]);
    setStateSnapshot(statePayload as AnyRecord | null);
    setHdbSnapshot(hdbPayload as AnyRecord | null);
  }

  useEffect(() => {
    let cancelled = false;
    refreshSnapshots()
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setInitialLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function run() {
    setBusy(true);
    try {
      if (mode === 'structure') setResult((await api.queryStructure(value.trim())) as AnyRecord);
      if (mode === 'group') setResult((await api.queryGroup(value.trim())) as AnyRecord);
      if (mode === 'episodic') setResult((await api.episodic(limit)) as AnyRecord);
      if (mode === 'state') {
        const payload = (await api.state()) as AnyRecord;
        setStateSnapshot(payload);
        setResult(payload);
      }
      if (mode === 'hdb') {
        const payload = (await api.hdb()) as AnyRecord;
        setHdbSnapshot(payload);
        setResult(payload);
      }
    } finally {
      setBusy(false);
    }
  }

  async function inspectRow(row: AnyRecord) {
    const structureId = row.structure_id || row.ref_object_id;
    const groupId = row.group_id;
    if (row.row_kind === '结构 ST' && structureId) {
      setMode('structure');
      setValue(String(structureId));
      setResult((await api.queryStructure(String(structureId))) as AnyRecord);
      return;
    }
    if (row.row_kind === '结构组 SG' && groupId) {
      setMode('group');
      setValue(String(groupId));
      setResult((await api.queryGroup(String(groupId))) as AnyRecord);
      return;
    }
    setResult(row);
  }

  const stateTableRows = useMemo(() => stateRows(stateSnapshot), [stateSnapshot]);
  const hdbTableRows = useMemo(() => hdbRows(hdbSnapshot), [hdbSnapshot]);
  const stateSummary = stateSnapshot?.snapshot?.summary || stateSnapshot?.summary || {};
  const hdbSummary = hdbSnapshot?.summary || {};

  const stateColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '类别', cell: ({ row }) => row.original.row_kind || '-' },
      { header: '对象', cell: ({ row }) => shortDisplayText(row.original.display || row.original.ref_object_id || row.original.item_id || '-', 42) },
      { header: '类型', cell: ({ row }) => row.original.ref_object_type || row.original.object_type || '-' },
      { header: 'ER', cell: ({ row }) => formatNumber(row.original.er ?? row.original.energy?.er, 4) },
      { header: 'EV', cell: ({ row }) => formatNumber(row.original.ev ?? row.original.energy?.ev, 4) },
      { header: 'CP', cell: ({ row }) => formatNumber(row.original.cp_abs ?? row.original.energy?.cp_abs, 4) },
    ],
    [],
  );

  const hdbColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '类别', cell: ({ row }) => row.original.row_kind || '-' },
      { header: '对象', cell: ({ row }) => shortDisplayText(row.original.display_text || row.original.grouped_display_text || row.original.display || row.original.structure_id || row.original.group_id || row.original.memory_id || '-', 44) },
      { header: 'ID', cell: ({ row }) => shortText(row.original.structure_id || row.original.group_id || row.original.memory_id || row.original.id || '-', 30) },
      { header: '权重/能量', cell: ({ row }) => formatNumber(row.original.base_weight ?? row.original.weight ?? row.original.total_energy ?? row.original.energy, 4) },
      { header: '来源', cell: ({ row }) => shortText(row.original.context_summary || row.original.context_id || row.original.owner_structure_id || row.original.growth_source || '-', 28) },
    ],
    [],
  );

  if (initialLoading) {
    return (
      <LoadingPanel
        title="检视器正在加载"
        description="正在读取状态池快照与 HDB 最近对象，准备可下钻的检查视图。"
        minHeight={320}
      />
    );
  }

  return (
    <div className="single-page">
      <Group justify="space-between" mb="md" align="flex-start">
        <div>
          <Title order={2}>对象检视器</Title>
          <Text c="dimmed" size="sm">
            面向结构、结构组、情节记忆、状态池与 HDB 快照的直接查询入口。支持 Enter 查询与列表点击下钻。
          </Text>
        </div>
        <Button variant="light" loading={busy} onClick={refreshSnapshots}>
          刷新快照
        </Button>
      </Group>

      <Grid mb="md">
        <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
          <MetricCard label="状态池对象" value={formatCount(stateSummary.active_item_count || stateTableRows.length)} note={`高 CP ${formatCount(stateSummary.high_cp_item_count)}`} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
          <MetricCard label="结构 ST" value={formatCount(hdbSummary.structure_count)} note={`最近 ${formatCount(asArray(hdbSnapshot?.recent_structures).length)}`} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
          <MetricCard label="结构组 SG" value={formatCount(hdbSummary.group_count)} note={`最近 ${formatCount(asArray(hdbSnapshot?.recent_groups).length)}`} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
          <MetricCard label="情节记忆 EM" value={formatCount(hdbSummary.episodic_count)} note={`最近 ${formatCount(asArray(hdbSnapshot?.recent_episodic).length)}`} />
        </Grid.Col>
      </Grid>

      <Grid>
        <Grid.Col span={{ base: 12, xl: 4 }}>
          <Stack>
            <Card>
              <Stack>
                <Select
                  label="查询类型"
                  value={mode}
                  onChange={(next) => setMode((next as InspectorMode) || 'structure')}
                  data={[
                    { value: 'structure', label: '结构 ST' },
                    { value: 'group', label: '结构组 SG' },
                    { value: 'episodic', label: '情节记忆 EM' },
                    { value: 'state', label: '状态池快照' },
                    { value: 'hdb', label: 'HDB 快照' },
                  ]}
                />
                {mode === 'episodic' ? (
                  <NumberInput label="limit" value={limit} min={1} max={500} onChange={(v) => setLimit(Number(v) || 20)} onKeyDown={(event) => event.key === 'Enter' && run()} />
                ) : mode === 'structure' || mode === 'group' ? (
                  <TextInput label="对象 ID" value={value} onChange={(event) => setValue(event.currentTarget.value)} onKeyDown={(event) => event.key === 'Enter' && run()} />
                ) : null}
                <Group>
                  <Button loading={busy} onClick={run}>
                    查询
                  </Button>
                  <Badge variant="light">{mode}</Badge>
                </Group>
              </Stack>
            </Card>
            <ObjectDetail value={result} title="查询结果" maxHeight={520} />
          </Stack>
        </Grid.Col>
        <Grid.Col span={{ base: 12, xl: 8 }}>
          <Stack>
            <Card>
              <Group justify="space-between" mb="xs">
                <Text fw={800}>状态池 Top / ER / EV</Text>
                <Badge variant="light">{formatCount(stateTableRows.length)}</Badge>
              </Group>
              <VirtualDataTable data={stateTableRows} columns={stateColumns} height={310} onRowClick={inspectRow} />
            </Card>
            <Card>
              <Group justify="space-between" mb="xs">
                <Text fw={800}>HDB 最近结构 / 结构组 / 情节记忆 / 记忆激活</Text>
                <Badge variant="light">{formatCount(hdbTableRows.length)}</Badge>
              </Group>
              <VirtualDataTable data={hdbTableRows} columns={hdbColumns} height={390} onRowClick={inspectRow} />
            </Card>
          </Stack>
        </Grid.Col>
      </Grid>
    </div>
  );
}
