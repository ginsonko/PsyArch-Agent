import type { AnyRecord } from '../types/api';
import { asArray, asNumber, readableApObjectText } from './format';

export type DisplayAggregateRow = AnyRecord & {
  __displayAggregate: true;
  aggregate_key: string;
  aggregate_display: string;
  aggregate_component_count: number;
  aggregate_total_er: number;
  aggregate_total_ev: number;
  aggregate_total_cp: number;
  aggregate_total_energy: number;
  aggregate_context_count: number;
  aggregate_context_summary: string;
  aggregate_ref_summary: string;
  aggregate_note: string;
  aggregate_components: AnyRecord[];
};

export type DisplayAggregateSortBy = 'total' | 'cp' | 'er' | 'ev';

function firstText(row: AnyRecord, paths: string[]): string {
  for (const path of paths) {
    const value = path.split('.').reduce<any>((current, part) => {
      if (!current || typeof current !== 'object') return undefined;
      return current[part];
    }, row);
    const text = String(value ?? '').trim();
    if (text) return text;
  }
  return '';
}

export function rowEnergy(row: AnyRecord): { er: number; ev: number; total: number } {
  const er = asNumber(row.er ?? row.total_er ?? row.energy_er ?? row.energy?.er ?? row.stats?.runtime_er, 0);
  const ev = asNumber(row.ev ?? row.total_ev ?? row.energy_ev ?? row.energy?.ev ?? row.stats?.runtime_ev, 0);
  const explicitTotal = row.total_energy ?? row.energy_total ?? row.weighted_energy ?? row.energy?.total;
  const total = asNumber(explicitTotal, er + ev);
  return { er, ev, total: Number.isFinite(total) ? total : er + ev };
}

export function rowCognitivePressure(row: AnyRecord): number {
  const explicit = row.cp ?? row.cp_abs ?? row.cognitive_pressure_abs ?? row.energy?.cognitive_pressure_abs ?? row.energy?.cp_abs;
  return asNumber(explicit, Math.abs(rowEnergy(row).er - rowEnergy(row).ev));
}

function rowSortValue(row: AnyRecord, sortBy: DisplayAggregateSortBy): number {
  const energy = rowEnergy(row);
  if (sortBy === 'er') return energy.er;
  if (sortBy === 'ev') return energy.ev;
  if (sortBy === 'cp') return rowCognitivePressure(row);
  return energy.total;
}

function aggregateSortValue(row: DisplayAggregateRow, sortBy: DisplayAggregateSortBy): number {
  if (sortBy === 'er') return asNumber(row.aggregate_total_er, 0);
  if (sortBy === 'ev') return asNumber(row.aggregate_total_ev, 0);
  if (sortBy === 'cp') return asNumber(row.aggregate_total_cp, 0);
  return asNumber(row.aggregate_total_energy, 0);
}

export function displayTextOf(row: AnyRecord): string {
  const display = firstText(row, [
    'display',
    'display_text',
    'text',
    'value',
    'label',
    'target_display_text',
    'target_display',
    'structure.display_text',
    'state.display',
  ]);
  if (display) return readableApObjectText(display);
  const signature = firstText(row, [
    'content_signature',
    'semantic_signature',
    'target_signature',
    'signature',
    'structure.content_signature',
  ]);
  if (signature) return readableApObjectText(signature);
  return readableApObjectText(firstText(row, ['ref_object_id', 'item_id', 'id', 'target_id', 'structure_id']) || '未命名对象');
}

export function rowObjectId(row: AnyRecord): string {
  return firstText(row, [
    'ref_object_id',
    'item_id',
    'id',
    'target_id',
    'structure_id',
    'memory_id',
    'action_id',
    'source_item_id',
  ]);
}

export function rowObjectType(row: AnyRecord): string {
  return firstText(row, ['ref_object_type', 'object_type', 'type', 'sub_type', 'row_kind']) || '-';
}

export function isAtomicFeatureSaRow(row: AnyRecord): boolean {
  const objectType = rowObjectType(row).trim().toLowerCase();
  if (objectType !== 'sa') return false;
  let display = displayTextOf(row).trim();
  if (display.startsWith('{') && display.endsWith('}') && display.length >= 2) {
    display = display.slice(1, -1).trim();
  }
  if (!display) return true;
  if (display.includes(':') || display.includes('：') || display.includes('行动节点') || display.includes('时间感受')) {
    return false;
  }
  return Array.from(display).length <= 2;
}

export function rowContextLabel(row: AnyRecord): string {
  const ext = row.ext && typeof row.ext === 'object' ? row.ext : {};
  const source = row.source && typeof row.source === 'object' ? row.source : {};
  const contextId =
    row.context_summary ||
    row.context_id ||
    row.context_ref_object_id ||
    row.context_owner_structure_id ||
    row.context?.owner_id ||
    ext.context_ref_object_id ||
    ext.context_owner_structure_id ||
    ext.owner_structure_id ||
    source.context_ref_object_id ||
    source.context_owner_structure_id ||
    source.origin_id ||
    '';
  const contextType =
    row.context_ref_object_type ||
    row.context_type ||
    row.context?.type ||
    ext.context_ref_object_type ||
    source.context_ref_object_type ||
    '';
  const origin = row.origin || row.source_kind || row.reason || source.origin || ext.relation_type || ext.kind || '';
  const pieces = [
    contextType && contextId ? `${contextType}:${contextId}` : String(contextId || ''),
    String(origin || ''),
  ].filter(Boolean);
  return readableApObjectText(pieces.join(' / ')) || '无显式激活链';
}

function isExplicitContextLabel(label: string): boolean {
  const text = String(label || '').trim();
  return Boolean(text && text !== '无显式来源' && text !== '无显式激活链');
}

function aggregateKey(row: AnyRecord, mode: 'display' | 'signature'): string {
  if (mode === 'signature') {
    const signature = firstText(row, [
      'content_signature',
      'semantic_signature',
      'target_signature',
      'signature',
      'structure.content_signature',
    ]);
    if (signature) return `sig:${signature}`;
  }
  return `display:${displayTextOf(row).trim()}`;
}

export function aggregateRowsByDisplay(
  rows: AnyRecord[],
  options: {
    enabled?: boolean;
    topN?: number;
    mode?: 'display' | 'signature';
    rowKind?: string;
    hideAtomicFeatureSa?: boolean;
    sortBy?: DisplayAggregateSortBy;
  } = {},
): DisplayAggregateRow[] | AnyRecord[] {
  const enabled = options.enabled !== false;
  const topN = Math.max(1, Math.floor(Number(options.topN || 0) || 0));
  const sourceRows = asArray<AnyRecord>(rows).filter((row) => (
    options.hideAtomicFeatureSa ? !isAtomicFeatureSaRow(row) : true
  ));
  if (!enabled) {
    const sortedRaw = sourceRows.slice().sort((a, b) => (
      rowSortValue(b, options.sortBy || 'total') - rowSortValue(a, options.sortBy || 'total')
    ));
    return topN > 0 ? sortedRaw.slice(0, topN) : sortedRaw;
  }

  const buckets = new Map<string, DisplayAggregateRow>();
  for (const row of sourceRows) {
    const key = aggregateKey(row, options.mode || 'display');
    const display = displayTextOf(row);
    const energy = rowEnergy(row);
    const contextLabel = rowContextLabel(row);
    const component = {
      ...row,
      component_display: display,
      component_object_id: rowObjectId(row),
      component_object_type: rowObjectType(row),
      component_context: contextLabel,
      component_er: energy.er,
      component_ev: energy.ev,
      component_cp: rowCognitivePressure(row),
      component_total_energy: energy.total,
    };
    const existing = buckets.get(key);
    if (!existing) {
      buckets.set(key, {
        __displayAggregate: true,
        aggregate_key: key,
        aggregate_display: display,
        display,
        row_kind: options.rowKind || row.row_kind,
        aggregate_component_count: 1,
        aggregate_total_er: energy.er,
        aggregate_total_ev: energy.ev,
        aggregate_total_cp: rowCognitivePressure(row),
        aggregate_total_energy: energy.total,
        aggregate_context_count: isExplicitContextLabel(contextLabel) ? 1 : 0,
        aggregate_context_summary: contextLabel,
        aggregate_ref_summary: rowObjectId(row),
        aggregate_note: '前端显示聚合：仅汇总可见特征内容相同的运行态波峰；正式结构身份仍以完整特征解析为准，后端对象 id、激活/审计元数据与能量组分不会被前端改写。',
        aggregate_components: [component],
      });
      continue;
    }
    existing.aggregate_total_er += energy.er;
    existing.aggregate_total_ev += energy.ev;
    existing.aggregate_total_cp += rowCognitivePressure(row);
    existing.aggregate_total_energy += energy.total;
    existing.aggregate_component_count += 1;
    existing.aggregate_components.push(component);
  }

  const aggregates = Array.from(buckets.values()).map((row) => {
    row.aggregate_components.sort((a, b) => rowEnergy(b).total - rowEnergy(a).total);
    const total = row.aggregate_total_energy || 0;
    row.aggregate_components = row.aggregate_components.map((component) => ({
      ...component,
      component_energy_share: total > 0 ? asNumber(component.component_total_energy, 0) / total : 0,
    }));
    const contexts = Array.from(new Set(row.aggregate_components
      .map((item) => String(item.component_context || ''))
      .filter((label) => isExplicitContextLabel(label))));
    const refs = Array.from(new Set(row.aggregate_components.map((item) => String(item.component_object_id || '')).filter(Boolean)));
    row.aggregate_context_count = contexts.length;
    row.aggregate_context_summary = contexts.slice(0, 3).join(' / ') || '无显式激活链';
    row.aggregate_ref_summary = refs.slice(0, 4).join(' / ') || '-';
    row.er = row.aggregate_total_er;
    row.ev = row.aggregate_total_ev;
    row.cp = row.aggregate_total_cp;
    row.cp_abs = row.aggregate_total_cp;
    row.total_energy = row.aggregate_total_energy;
    row.energy_total = row.aggregate_total_energy;
    row.component_count = row.aggregate_component_count;
    return row;
  });

  aggregates.sort((a, b) => (
    aggregateSortValue(b, options.sortBy || 'total') - aggregateSortValue(a, options.sortBy || 'total')
  ));
  return topN > 0 ? aggregates.slice(0, topN) : aggregates;
}
