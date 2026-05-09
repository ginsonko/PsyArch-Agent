import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Divider,
  Drawer,
  Grid,
  Group,
  JsonInput,
  Loader,
  NumberInput,
  ScrollArea,
  Select,
  Stack,
  Switch,
  Tabs,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
} from '@mantine/core';
import Editor from '@monaco-editor/react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from 'reactflow';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  IconCopy,
  IconGitBranch,
  IconPlayerPlay,
  IconPlus,
  IconRefresh,
  IconTrash,
} from '@tabler/icons-react';
import { api } from '../lib/api';
import type { AnyRecord } from '../types/api';
import { asArray, formatCount, jsonPretty, shortText } from '../lib/format';
import { JsonInspector } from '../components/JsonInspector';
import { FeedbackAlert, type FeedbackState } from '../components/FeedbackAlert';
import { LoadingPanel } from '../components/LoadingPanel';

const EMPTY_RULE_DOC: AnyRecord = {
  rules_schema_version: '1.0',
  rules_version: '0.0',
  enabled: true,
  defaults: {},
  rules: [],
};

type RuleFilter = 'all' | 'enabled' | 'disabled';
type GraphNodeKind = 'root' | 'condition' | 'action';
type GraphNodeData = { label: string; kind: GraphNodeKind; nodeType: string; config: unknown };

const NONE_VALUE = '__none__';

const CONDITION_NODE_TYPE_OPTIONS = [
  { value: 'cfs', label: '认知感受 CFS' },
  { value: 'state_window', label: '状态窗口' },
  { value: 'timer', label: '定时器' },
  { value: 'metric', label: '运行指标' },
];

const ACTION_NODE_TYPE_OPTIONS = [
  { value: 'cfs_emit', label: '认知感受生成 cfs_emit' },
  { value: 'focus', label: '注意力聚焦' },
  { value: 'emit_script', label: '触发脚本记录' },
  { value: 'emotion_update', label: '情绪递质更新' },
  { value: 'action_trigger', label: '行动触发' },
  { value: 'pool_energy', label: '对状态池对象赋能 ER/EV' },
  { value: 'pool_bind_attribute', label: '绑定属性刺激元' },
  { value: 'delay', label: '延时动作 delay' },
  { value: 'branch', label: '分支动作 branch' },
  { value: 'log', label: '审计日志' },
];

const NT_CHANNEL_OPTIONS = [
  { value: 'DA', label: '多巴胺 DA' },
  { value: 'ADR', label: '肾上腺素 ADR' },
  { value: 'OXY', label: '催产素 OXY' },
  { value: 'SER', label: '血清素 SER' },
  { value: 'END', label: '内啡肽 END' },
  { value: 'COR', label: '皮质醇 COR' },
  { value: 'NOV', label: '新奇/探索 NOV' },
  { value: 'FOC', label: '聚焦 FOC' },
];

const COMPARE_OPTIONS = [
  { value: 'exists', label: 'exists：存在即可' },
  { value: 'changed', label: 'changed：发生变化' },
  { value: '>=', label: '>= 大于等于' },
  { value: '>', label: '> 大于' },
  { value: '<=', label: '<= 小于等于' },
  { value: '<', label: '< 小于' },
  { value: '==', label: '== 等于' },
  { value: '!=', label: '!= 不等于' },
  { value: 'between', label: 'between：区间内' },
];

const METRIC_MODE_OPTIONS = [
  { value: 'state', label: '状态 state：当前值' },
  { value: 'prev_state', label: '上一 tick prev_state' },
  { value: 'delta', label: '变化量 delta：近 1 tick' },
  { value: 'avg_rate', label: '变化率 avg_rate：近 N tick 平均' },
];

const MATCH_POLICY_OPTIONS = [
  { value: 'all', label: 'all：全部命中' },
  { value: 'any', label: 'any：任一命中' },
  { value: 'strongest', label: 'strongest：最强命中' },
  { value: 'first', label: 'first：第一个命中' },
];

const SELECTOR_MODE_OPTIONS = [
  { value: 'all', label: '全部对象 all' },
  { value: 'specific_ref', label: '特定认知对象 specific_ref' },
  { value: 'specific_item', label: '特定状态池条目 specific_item' },
  { value: 'contains_text', label: '包含文本/特征 contains_text' },
  { value: 'top_n', label: '能量 Top-N top_n' },
];

const REF_OBJECT_TYPE_OPTIONS = [
  { value: NONE_VALUE, label: '不限制类型' },
  { value: 'sa', label: '基础刺激元 SA' },
  { value: 'st', label: '结构对象 ST' },
  { value: 'em', label: '记忆片段 EM' },
  { value: 'cfs_signal', label: '认知感受信号 CFS' },
  { value: 'action_node', label: '行动节点 Action Node' },
];

const DEFAULT_METRIC_PRESETS = [
  { preset: 'got_er', metric: 'item.er', mode: 'delta', label_zh: '获得实能量（ER 变化量）', group_zh: '对象能量（Item Energy）' },
  { preset: 'got_ev', metric: 'item.ev', mode: 'delta', label_zh: '获得虚能量（EV 变化量）', group_zh: '对象能量（Item Energy）' },
  { preset: 'got_total_energy', metric: 'item.total_energy', mode: 'delta', label_zh: '获得总能量（ER+EV 变化量）', group_zh: '对象能量（Item Energy）' },
  { preset: 'cp_abs_state', metric: 'item.cp_abs', mode: 'state', label_zh: '认知压大小状态（|CP|）', group_zh: '对象能量（Item Energy）' },
  { preset: 'fatigue_state', metric: 'item.fatigue', mode: 'state', label_zh: '疲劳度状态（Fatigue）', group_zh: '对象能量（Item Energy）' },
  { preset: 'reward_state', metric: 'emotion.rwd', mode: 'state', label_zh: '奖励信号状态（RWD 当前值）', group_zh: '奖励/惩罚（Rwd/Pun）' },
  { preset: 'reward_rate', metric: 'emotion.rwd', mode: 'avg_rate', window_ticks: 4, label_zh: '奖励信号变化率（RWD 近 N tick 平均）', group_zh: '奖励/惩罚（Rwd/Pun）' },
  { preset: 'punish_state', metric: 'emotion.pun', mode: 'state', label_zh: '惩罚信号状态（PUN 当前值）', group_zh: '奖励/惩罚（Rwd/Pun）' },
  { preset: 'nt_state', metric: 'emotion.nt.{channel}', mode: 'state', needs_channel: true, label_zh: '情绪递质状态（NT，需填写 channel）', group_zh: '情绪递质（NT）' },
  { preset: 'stimulus_match_score', metric: 'retrieval.stimulus.best_match_score', mode: 'state', label_zh: '查存一体匹配分数（刺激级）', group_zh: '查存一体（Retrieval）' },
];

function csvToList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function listToCsv(value: unknown): string {
  return csvToList(value).join(', ');
}

function toText(value: unknown, fallback = ''): string {
  if (value === undefined || value === null) return fallback;
  return String(value);
}

function toNumberOrText(value: string): string | number {
  const raw = String(value ?? '').trim();
  if (!raw) return '';
  if (raw.includes('{{{') || raw.includes('{{')) return raw;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : raw;
}

function metricPresetOptions(catalog: AnyRecord[] | undefined | null) {
  const presets = (asArray<AnyRecord>(catalog).length ? asArray<AnyRecord>(catalog) : DEFAULT_METRIC_PRESETS)
    .filter((item) => item && typeof item === 'object')
    .map((item) => ({
      group: String(item.group_zh || '其他指标'),
      value: String(item.preset || ''),
      label: `${String(item.label_zh || item.preset || '')}${item.preset ? ` (${item.preset})` : ''}`,
      metric: String(item.metric || ''),
      mode: String(item.mode || ''),
      window_ticks: Number(item.window_ticks || 0),
      needs_channel: Boolean(item.needs_channel),
    }))
    .filter((item) => item.value);
  return [
    { value: NONE_VALUE, label: '手动填写 metric 路径' },
    ...presets.sort((a, b) => `${a.group}:${a.label}`.localeCompare(`${b.group}:${b.label}`, 'zh-Hans')).map((item) => ({
      value: item.value,
      label: `${item.group} / ${item.label}`,
    })),
  ];
}

function findMetricPreset(catalog: AnyRecord[] | undefined | null, preset: unknown): AnyRecord | null {
  const key = String(preset || '').trim();
  if (!key) return null;
  return (asArray<AnyRecord>(catalog).length ? asArray<AnyRecord>(catalog) : DEFAULT_METRIC_PRESETS).find((item) => String(item?.preset || '') === key) || null;
}

function selectedMetricPresetNeedsChannel(catalog: AnyRecord[] | undefined | null, preset: unknown): boolean {
  const item = findMetricPreset(catalog, preset);
  return Boolean(item?.needs_channel || String(item?.metric || '').includes('{channel}'));
}

function selectValueOrNone(value: unknown): string {
  const text = String(value ?? '').trim();
  return text || NONE_VALUE;
}

function noneToEmpty(value: string | null | undefined): string {
  return !value || value === NONE_VALUE ? '' : value;
}

function graphNodeInnerConfig(node: Node<GraphNodeData> | null | undefined): AnyRecord {
  if (!node?.data?.config || typeof node.data.config !== 'object') return {};
  const config = node.data.config as AnyRecord;
  if (node.data.kind === 'root') return config;
  const type = String(node.data.nodeType || Object.keys(config)[0] || '');
  const inner = config[type];
  return inner && typeof inner === 'object' ? (inner as AnyRecord) : {};
}

function graphNodeTypeOptions(kind: GraphNodeKind) {
  if (kind === 'condition') return CONDITION_NODE_TYPE_OPTIONS;
  if (kind === 'action') return ACTION_NODE_TYPE_OPTIONS;
  return [
    { value: 'all', label: 'all：全部条件同时满足' },
    { value: 'any', label: 'any：任一条件满足' },
  ];
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value ?? null)) as T;
}

function ensureRuleDoc(value: unknown): AnyRecord {
  const doc = value && typeof value === 'object' ? clone(value as AnyRecord) : clone(EMPTY_RULE_DOC);
  if (!Array.isArray(doc.rules)) doc.rules = [];
  if (!doc.defaults || typeof doc.defaults !== 'object') doc.defaults = {};
  if (doc.enabled === undefined) doc.enabled = true;
  if (!doc.rules_schema_version) doc.rules_schema_version = '1.0';
  if (!doc.rules_version) doc.rules_version = '0.0';
  return doc;
}

function parseRuleBundle(payload: AnyRecord | null): { doc: AnyRecord; yaml: string } {
  const doc = ensureRuleDoc(payload?.normalized_doc || payload?.doc || (payload?.rules ? payload : null));
  const yaml = String(payload?.file_yaml || payload?.normalized_yaml || payload?.yaml || jsonPretty(doc));
  return { doc, yaml };
}

function ruleIdSet(doc: AnyRecord): Set<string> {
  return new Set(asArray<AnyRecord>(doc.rules).map((rule) => String(rule?.id || '')).filter(Boolean));
}

function nextRuleId(doc: AnyRecord, prefix: string): string {
  const ids = ruleIdSet(doc);
  let n = 1;
  while (ids.has(`${prefix}_${String(n).padStart(2, '0')}`)) n += 1;
  return `${prefix}_${String(n).padStart(2, '0')}`;
}

function summarizeWhen(whenExpr: unknown): string {
  if (!whenExpr || typeof whenExpr !== 'object') return '-';
  const expr = whenExpr as AnyRecord;
  const key = Object.keys(expr)[0];
  const value = expr[key];
  if (key === 'all' || key === 'any') return `${key}(${asArray(value).map(summarizeWhen).join(' / ') || '-'})`;
  if (key === 'not') return `not(${summarizeWhen(value)})`;
  if (key === 'cfs') {
    return `CFS ${asArray(value?.kinds).join(',') || '*'} >= ${value?.min_strength ?? '-'}`;
  }
  if (key === 'state_window') {
    return `状态窗口 stage=${value?.stage ?? 'any'} rise>=${value?.fast_cp_rise_min ?? 0} drop>=${value?.fast_cp_drop_min ?? 0}`;
  }
  if (key === 'timer') {
    return `定时器 every=${value?.every_n_ticks ?? '-'} at=${value?.at_tick ?? '-'}`;
  }
  if (key === 'metric') {
    const name = value?.preset || value?.metric || value?.channel || 'metric';
    return `指标 ${name} ${value?.op || '>='} ${value?.value ?? '-'}`;
  }
  return key || '-';
}

function summarizeThen(thenExpr: unknown): string {
  const actions = asArray<AnyRecord>(thenExpr);
  if (!actions.length) return '-';
  return actions
    .map((action) => {
      const key = Object.keys(action || {})[0];
      if (key === 'log') return 'log';
      if (key === 'cfs_emit') return `cfs_emit:${action.cfs_emit?.kind || '-'}`;
      if (key === 'action_trigger') return `action:${action.action_trigger?.action_kind || action.action_trigger?.action_id || '-'}`;
      if (key === 'emotion_update') return 'emotion_update';
      if (key === 'pool_energy') return `pool_energy ER=${action.pool_energy?.delta_er ?? 0} EV=${action.pool_energy?.delta_ev ?? 0}`;
      if (key === 'pool_bind_attribute') return `bind:${action.pool_bind_attribute?.attribute?.attribute_name || '-'}`;
      if (key === 'delay') return `delay:${action.delay?.ticks ?? 1}tick`;
      if (key === 'branch') return 'branch';
      return key || '-';
    })
    .join(' / ');
}

function ruleTemplate(doc: AnyRecord, kind: 'focus' | 'window' | 'timer'): AnyRecord {
  if (kind === 'window') {
    return {
      id: nextRuleId(doc, 'window_rule'),
      title: '状态窗口 -> 触发记录',
      enabled: true,
      priority: 50,
      cooldown_ticks: 0,
      when: { state_window: { stage: 'any', fast_cp_rise_min: 1 } },
      then: [
        {
          emit_script: {
            script_id: 'innate_state_window_cp_rise',
            script_kind: 'window_trigger',
            priority: 50,
            trigger: 'fast_cp_rise',
          },
        },
      ],
      note: '模板：状态窗口触发 -> 生成触发记录（用于观测/联调）',
    };
  }
  if (kind === 'timer') {
    return {
      id: nextRuleId(doc, 'timer_rule'),
      title: '定时器 -> 日志',
      enabled: true,
      priority: 10,
      cooldown_ticks: 0,
      when: { timer: { every_n_ticks: 1 } },
      then: [{ log: '定时触发' }],
      note: '模板：定时触发 -> 写入审计日志（用于测试；建议调整 every_n_ticks/cooldown_ticks）。',
    };
  }
  return {
    id: nextRuleId(doc, 'focus_rule'),
    title: '认知感受（CFS）-> 聚焦指令',
    enabled: true,
    priority: 60,
    cooldown_ticks: 0,
    when: { cfs: { kinds: ['dissonance', 'surprise', 'pressure', 'expectation'], min_strength: 0.3 } },
    then: [
      {
        focus: {
          from: 'cfs_matches',
          match_policy: 'all',
          ttl_ticks: 2,
          focus_boost: 0.9,
          deduplicate_by: 'target_ref_object_id',
        },
      },
    ],
    note: '模板：核心认知感受（CFS）-> 注意力聚焦（下一 tick 生效）',
  };
}

function ruleNodes(doc: AnyRecord | null, selectedId: string): { nodes: Node[]; edges: Edge[] } {
  const rules = asArray<AnyRecord>(doc?.rules).slice(0, 80);
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  rules.forEach((rule, index) => {
    const ruleId = String(rule.id || index);
    const rootId = `rule-${ruleId}`;
    const x = (index % 4) * 300;
    const y = Math.floor(index / 4) * 190;
    const active = selectedId === ruleId;
    nodes.push({
      id: rootId,
      position: { x, y },
      data: {
        label: `${rule.enabled === false ? '停用' : '启用'} | ${shortText(rule.title || ruleId, 28)}`,
      },
      type: 'default',
      style: {
        width: 230,
        borderColor: active ? '#20c997' : 'rgba(32, 201, 151, 0.45)',
        boxShadow: active ? '0 0 0 2px rgba(32, 201, 151, 0.22)' : undefined,
      },
    });
    const whenId = `${rootId}-when`;
    nodes.push({
      id: whenId,
      position: { x: x - 24, y: y + 76 },
      data: { label: `WHEN ${shortText(summarizeWhen(rule.when), 46)}` },
      style: { width: 270, background: '#10202c' },
    });
    const thenId = `${rootId}-then`;
    nodes.push({
      id: thenId,
      position: { x: x + 24, y: y + 132 },
      data: { label: `THEN ${shortText(summarizeThen(rule.then), 46)}` },
      style: { width: 270, background: '#17232b' },
    });
    edges.push({ id: `${rootId}->${whenId}`, source: rootId, target: whenId, animated: rule.enabled !== false });
    edges.push({ id: `${whenId}->${thenId}`, source: whenId, target: thenId, animated: rule.enabled !== false });
  });
  return { nodes, edges };
}

function unwrapWhenClauses(whenExpr: unknown): { mode: 'all' | 'any'; clauses: AnyRecord[] } {
  if (!whenExpr || typeof whenExpr !== 'object') return { mode: 'all', clauses: [] };
  const expr = whenExpr as AnyRecord;
  if (Array.isArray(expr.all)) return { mode: 'all', clauses: expr.all.filter((item: unknown) => item && typeof item === 'object') as AnyRecord[] };
  if (Array.isArray(expr.any)) return { mode: 'any', clauses: expr.any.filter((item: unknown) => item && typeof item === 'object') as AnyRecord[] };
  return { mode: 'all', clauses: [expr] };
}

function actionTemplate(actionType: string): AnyRecord {
  if (actionType === 'cfs_emit') {
    return {
      cfs_emit: {
        kind: 'dissonance',
        scope: 'object',
        from: 'metric_matches',
        max_signals: 1,
        min_strength: 0.0,
        capture_as: '',
        strength: { from: 'match_value', policy: 'linear_clamp', min: 0.0, max: 1.0, out_min: 0.0, out_max: 1.0 },
      },
    };
  }
  if (actionType === 'focus') {
    return { focus: { from: 'cfs_matches', match_policy: 'all', ttl_ticks: 2, focus_boost: 0.9, deduplicate_by: 'target_ref_object_id' } };
  }
  if (actionType === 'emit_script') {
    return { emit_script: { script_id: 'innate_state_window_cp_rise', script_kind: 'window_trigger', priority: 50, trigger: 'fast_cp_rise' } };
  }
  if (actionType === 'emotion_update') {
    return { emotion_update: { FOC: 0.05 } };
  }
  if (actionType === 'action_trigger') {
    return { action_trigger: { from: 'metric_matches', match_policy: 'strongest', max_triggers: 1, action_kind: 'recall', action_id: 'recall_top_memory', gain: 0.35, threshold: 0.7 } };
  }
  if (actionType === 'pool_energy') {
    return { pool_energy: { selector: { mode: 'all' }, delta_er: 0.0, delta_ev: 0.0, create_if_missing: false, create_ref_object_type: 'sa', create_display: '', reason: '' } };
  }
  if (actionType === 'pool_bind_attribute') {
    return {
      pool_bind_attribute: {
        selector: { mode: 'all' },
        attribute: { attribute_name: '', attribute_value: '', raw: '', display: '', value_type: 'discrete', modality: 'internal', er: 0.0, ev: 0.0 },
        reason: '',
      },
    };
  }
  if (actionType === 'delay') {
    return { delay: { ticks: 2, then: [{ log: '延时触发（示例）' }] } };
  }
  if (actionType === 'branch') {
    return { branch: { when: { metric: { preset: 'reward_state', mode: 'state', op: '>', value: 0 } }, then: [{ log: '满足条件（then）' }], else: [{ log: '不满足（else）' }], on_error: [{ log: '条件报错（on_error）' }] } };
  }
  return { log: '图形规则触发' };
}

function conditionTemplate(conditionType: string): AnyRecord {
  if (conditionType === 'state_window') return { state_window: { stage: 'any', fast_cp_rise_min: 1 } };
  if (conditionType === 'timer') return { timer: { every_n_ticks: 1 } };
  if (conditionType === 'metric') {
    return {
      metric: {
        preset: 'got_er',
        metric: '',
        channel: '',
        mode: 'delta',
        selector: { mode: 'all' },
        op: '>=',
        value: 0,
        window_ticks: 4,
        match_policy: 'any',
        capture_as: '',
        prev_gate: {},
      },
    };
  }
  return { cfs: { kinds: ['dissonance', 'surprise', 'pressure', 'expectation'], min_strength: 0.3 } };
}

function graphFromRule(rule: AnyRecord | null): { nodes: Node<GraphNodeData>[]; edges: Edge[] } {
  const whenModel = unwrapWhenClauses(rule?.when);
  const actions = asArray<AnyRecord>(rule?.then);
  const nodes: Node<GraphNodeData>[] = [
    {
      id: 'root',
      type: 'default',
      position: { x: 360, y: 180 },
      data: { kind: 'root', nodeType: whenModel.mode, config: { mode: whenModel.mode }, label: `条件汇总：${whenModel.mode}` },
      style: { width: 220, borderColor: '#20c997' },
    },
  ];
  const edges: Edge[] = [];
  whenModel.clauses.forEach((clause, index) => {
    const type = Object.keys(clause || {})[0] || 'cfs';
    const id = `cond-${index}`;
    nodes.push({
      id,
      type: 'default',
      position: { x: 40, y: 70 + index * 118 },
      data: { kind: 'condition', nodeType: type, config: clause, label: `条件 ${index + 1}: ${shortText(summarizeWhen(clause), 38)}` },
      style: { width: 270, background: '#10202c' },
    });
    edges.push({ id: `${id}->root`, source: id, target: 'root', animated: true });
  });
  actions.forEach((action, index) => {
    const type = Object.keys(action || {})[0] || 'log';
    const id = `action-${index}`;
    nodes.push({
      id,
      type: 'default',
      position: { x: 690, y: 70 + index * 118 },
      data: { kind: 'action', nodeType: type, config: action, label: `动作 ${index + 1}: ${shortText(summarizeThen([action]), 38)}` },
      style: { width: 270, background: '#17232b' },
    });
    edges.push({ id: `root->${id}`, source: 'root', target: id, animated: true });
  });
  return { nodes, edges };
}

function compileRuleGraph(nodes: Node<GraphNodeData>[], edges: Edge[] = []): { ok: true; when: AnyRecord; then: AnyRecord[] } | { ok: false; message: string } {
  const root = nodes.find((node) => node.id === 'root');
  const mode = String((root?.data?.config as AnyRecord | undefined)?.mode || root?.data?.nodeType || 'all') === 'any' ? 'any' : 'all';
  const edgeBoundConditionIds = new Set(edges.filter((edge) => edge.target === 'root').map((edge) => edge.source));
  const edgeBoundActionIds = new Set(edges.filter((edge) => edge.source === 'root').map((edge) => edge.target));
  const hasCompiledEdges = edgeBoundConditionIds.size > 0 || edgeBoundActionIds.size > 0;
  const conditionNodes = nodes
    .filter((node) => node.data?.kind === 'condition' && (!hasCompiledEdges || edgeBoundConditionIds.has(node.id)))
    .sort((a, b) => a.position.y - b.position.y);
  const actionNodes = nodes
    .filter((node) => node.data?.kind === 'action' && (!hasCompiledEdges || edgeBoundActionIds.has(node.id)))
    .sort((a, b) => a.position.y - b.position.y);
  if (!conditionNodes.length) return { ok: false, message: '图形中至少需要一个条件节点。' };
  if (!actionNodes.length) return { ok: false, message: '图形中至少需要一个动作节点。' };
  const clauses = conditionNodes
    .map((node) => node.data?.config)
    .filter((config): config is AnyRecord => Boolean(config && typeof config === 'object'));
  const actions = actionNodes
    .map((node) => node.data?.config)
    .filter((config): config is AnyRecord => Boolean(config && typeof config === 'object'));
  if (!clauses.length || !actions.length) return { ok: false, message: '条件或动作节点配置为空。' };
  return {
    ok: true,
    when: clauses.length === 1 ? clauses[0] : { [mode]: clauses },
    then: actions,
  };
}

function refreshGraphLabels(nodes: Node<GraphNodeData>[]): Node<GraphNodeData>[] {
  let conditionIndex = 0;
  let actionIndex = 0;
  return nodes.map((node) => {
    if (node.id === 'root') {
      const mode = String((node.data?.config as AnyRecord | undefined)?.mode || node.data?.nodeType || 'all') === 'any' ? 'any' : 'all';
      return { ...node, data: { ...node.data, nodeType: mode, label: `条件汇总：${mode}` } };
    }
    if (node.data?.kind === 'condition') {
      conditionIndex += 1;
      return { ...node, data: { ...node.data, label: `条件 ${conditionIndex}: ${shortText(summarizeWhen(node.data.config), 38)}` } };
    }
    if (node.data?.kind === 'action') {
      actionIndex += 1;
      return { ...node, data: { ...node.data, label: `动作 ${actionIndex}: ${shortText(summarizeThen([node.data.config]), 38)}` } };
    }
    return node;
  });
}

function resultSummary(payload: AnyRecord | null): string {
  if (!payload) return '尚无操作结果。';
  if (payload.valid !== undefined) {
    return `校验 ${payload.valid ? '通过' : '失败'} | 错误 ${asArray(payload.errors).length} | 警告 ${asArray(payload.warnings).length}`;
  }
  if (payload.saved !== undefined) {
    return `保存 ${payload.saved ? '完成' : '失败'} | 规则 ${payload.data?.rule_count ?? payload.rule_count ?? '-'}`;
  }
  if (payload.ok !== undefined) {
    const data = payload.data || {};
    return `模拟 ${payload.ok ? '完成' : '失败'} | 触发规则 ${asArray(data.triggered_rules).length} | 触发脚本 ${asArray(data.triggered_scripts).length}`;
  }
  return payload.message || payload.code || '操作完成。';
}

export function RulesPage() {
  const [bundle, setBundle] = useState<AnyRecord | null>(null);
  const [doc, setDoc] = useState<AnyRecord>(() => clone(EMPTY_RULE_DOC));
  const [yaml, setYaml] = useState('');
  const [result, setResult] = useState<AnyRecord | null>(null);
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  const [selectedId, setSelectedId] = useState('');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<RuleFilter>('all');
  const [ruleDraft, setRuleDraft] = useState('');
  const [graphNodes, setGraphNodes] = useState<Node<GraphNodeData>[]>([]);
  const [graphEdges, setGraphEdges] = useState<Edge[]>([]);
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState('');
  const [graphNodeDraft, setGraphNodeDraft] = useState('');
  const [graphDirty, setGraphDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [graphExpanded, setGraphExpanded] = useState(false);

  const rules = useMemo(() => asArray<AnyRecord>(doc.rules), [doc]);
  const selectedRule = useMemo(
    () => rules.find((rule) => String(rule?.id || '') === selectedId) || rules[0] || null,
    [rules, selectedId],
  );
  const graph = useMemo(() => ruleNodes(doc, selectedRule ? String(selectedRule.id || '') : ''), [doc, selectedRule]);
  const selectedGraphNode = useMemo(
    () => graphNodes.find((item) => item.id === selectedGraphNodeId) || null,
    [graphNodes, selectedGraphNodeId],
  );
  const selectedGraphNodeConfig = useMemo(() => graphNodeInnerConfig(selectedGraphNode), [selectedGraphNode]);

  const filteredRules = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rules.filter((rule) => {
      const enabled = rule.enabled !== false;
      if (filter === 'enabled' && !enabled) return false;
      if (filter === 'disabled' && enabled) return false;
      if (!q) return true;
      const haystack = [
        rule.id,
        rule.title,
        rule.note,
        rule.phase,
        summarizeWhen(rule.when),
        summarizeThen(rule.then),
      ]
        .join('\n')
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [filter, rules, search]);

  useEffect(() => {
    setRuleDraft(selectedRule ? jsonPretty(selectedRule) : '');
  }, [selectedRule?.id]);

  useEffect(() => {
    const nextGraph = graphFromRule(selectedRule);
    setGraphNodes(nextGraph.nodes);
    setGraphEdges(nextGraph.edges);
    setSelectedGraphNodeId('');
    setGraphNodeDraft('');
    setGraphDirty(false);
  }, [selectedRule?.id]);

  useEffect(() => {
    const node = graphNodes.find((item) => item.id === selectedGraphNodeId);
    setGraphNodeDraft(node ? jsonPretty({ node_type: node.data.nodeType, config: node.data.config }) : '');
  }, [graphNodes, selectedGraphNodeId]);

  async function refresh(silent = false) {
    if (!silent) setBusy(true);
    try {
      const payload = await api.innateRules();
      const parsed = parseRuleBundle(payload);
      setBundle(payload);
      setDoc(parsed.doc);
      setYaml(parsed.yaml);
      setResult(null);
      setDirty(false);
      const nextRules = asArray<AnyRecord>(parsed.doc.rules);
      const keep = selectedId && nextRules.some((rule) => String(rule.id || '') === selectedId);
      setSelectedId(keep ? selectedId : String(nextRules[0]?.id || ''));
      if (!silent) {
        setFeedback({
          kind: asArray(payload?.errors).length ? 'error' : 'ok',
          message: `已刷新先天规则：${formatCount(nextRules.length)} 条，错误 ${asArray(payload?.errors).length}，警告 ${asArray(payload?.warnings).length}。`,
        });
      }
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      if (!silent) setBusy(false);
      setInitialLoading(false);
    }
  }

  useEffect(() => {
    refresh(true).catch(() => undefined);
  }, []);

  function updateDoc(mutator: (next: AnyRecord) => void, nextSelectedId?: string) {
    setDoc((current) => {
      const next = ensureRuleDoc(current);
      mutator(next);
      return next;
    });
    if (nextSelectedId !== undefined) setSelectedId(nextSelectedId);
    setDirty(true);
  }

  function updateSelectedRule(mutator: (rule: AnyRecord) => void) {
    if (!selectedRule) return;
    const currentId = String(selectedRule.id || '');
    updateDoc((next) => {
      const idx = asArray<AnyRecord>(next.rules).findIndex((rule) => String(rule.id || '') === currentId);
      if (idx < 0) return;
      mutator(next.rules[idx]);
    });
  }

  function setDocField(field: string, value: unknown) {
    updateDoc((next) => {
      next[field] = value;
    });
  }

  function addTemplate(kind: 'focus' | 'window' | 'timer') {
    const base = ensureRuleDoc(doc);
    const rule = ruleTemplate(base, kind);
    updateDoc((next) => {
      next.rules.push(rule);
    }, String(rule.id));
    setFeedback({ kind: 'ok', message: `已添加模板规则：${rule.title}` });
  }

  function duplicateRule() {
    if (!selectedRule) return;
    const base = ensureRuleDoc(doc);
    const copied = clone(selectedRule);
    copied.id = nextRuleId(base, 'copy_rule');
    copied.title = `${selectedRule.title || selectedRule.id || '未命名规则'}（副本）`;
    updateDoc((next) => {
      const idx = asArray<AnyRecord>(next.rules).findIndex((rule) => String(rule.id || '') === String(selectedRule.id || ''));
      next.rules.splice(idx >= 0 ? idx + 1 : next.rules.length, 0, copied);
    }, String(copied.id));
    setFeedback({ kind: 'ok', message: `已复制规则：${copied.id}` });
  }

  function deleteRule() {
    if (!selectedRule) return;
    const ok = window.confirm(`删除规则 ${selectedRule.id || selectedRule.title || '-'}？草稿保存前不会写入文件。`);
    if (!ok) return;
    const oldId = String(selectedRule.id || '');
    updateDoc((next) => {
      next.rules = asArray<AnyRecord>(next.rules).filter((rule) => String(rule.id || '') !== oldId);
    });
    const remaining = rules.filter((rule) => String(rule.id || '') !== oldId);
    setSelectedId(String(remaining[0]?.id || ''));
    setFeedback({ kind: 'warn', message: `已从草稿删除规则：${oldId}` });
  }

  function applyRuleDraft() {
    if (!selectedRule) return;
    let parsed: AnyRecord;
    try {
      parsed = JSON.parse(ruleDraft || '{}');
    } catch (error) {
      setFeedback({ kind: 'error', message: `规则 JSON 解析失败：${error instanceof Error ? error.message : String(error)}` });
      return;
    }
    const nextId = String(parsed.id || selectedRule.id || '');
    if (!nextId) {
      setFeedback({ kind: 'error', message: '规则必须包含 id。' });
      return;
    }
    const duplicate = rules.some((rule) => String(rule.id || '') === nextId && String(rule.id || '') !== String(selectedRule.id || ''));
    if (duplicate) {
      setFeedback({ kind: 'error', message: `规则 id 已存在：${nextId}` });
      return;
    }
    const oldId = String(selectedRule.id || '');
    updateDoc((next) => {
      const idx = asArray<AnyRecord>(next.rules).findIndex((rule) => String(rule.id || '') === oldId);
      if (idx >= 0) next.rules[idx] = parsed;
    }, nextId);
    setFeedback({ kind: 'ok', message: `已应用规则草稿：${nextId}` });
  }

  const onGraphNodesChange = useCallback((changes: NodeChange[]) => {
    setGraphNodes((nodes) => refreshGraphLabels(applyNodeChanges(changes, nodes) as Node<GraphNodeData>[]));
    if (changes.some((change) => change.type === 'position')) setGraphDirty(true);
  }, []);

  function addGraphNode(kind: 'condition' | 'action', templateType: string) {
    const sameKindCount = graphNodes.filter((node) => node.data?.kind === kind).length;
    const id = `${kind}-${Date.now().toString(36)}-${sameKindCount}`;
    const config = kind === 'condition' ? conditionTemplate(templateType) : actionTemplate(templateType);
    const node: Node<GraphNodeData> = {
      id,
      type: 'default',
      position: kind === 'condition' ? { x: 40, y: 70 + sameKindCount * 118 } : { x: 690, y: 70 + sameKindCount * 118 },
      data: {
        kind,
        nodeType: templateType,
        config,
        label: kind === 'condition' ? `条件: ${shortText(summarizeWhen(config), 38)}` : `动作: ${shortText(summarizeThen([config]), 38)}`,
      },
      style: { width: 270, background: kind === 'condition' ? '#10202c' : '#17232b' },
    };
    setGraphNodes((nodes) => refreshGraphLabels([...nodes, node]));
    setGraphEdges((edges) =>
      kind === 'condition'
        ? [...edges, { id: `${id}->root`, source: id, target: 'root', animated: true }]
        : [...edges, { id: `root->${id}`, source: 'root', target: id, animated: true }],
    );
    setSelectedGraphNodeId(id);
    setGraphDirty(true);
  }

  function deleteSelectedGraphNode() {
    if (!selectedGraphNodeId || selectedGraphNodeId === 'root') return;
    setGraphNodes((nodes) => refreshGraphLabels(nodes.filter((node) => node.id !== selectedGraphNodeId)));
    setGraphEdges((edges) => edges.filter((edge) => edge.source !== selectedGraphNodeId && edge.target !== selectedGraphNodeId));
    setSelectedGraphNodeId('');
    setGraphDirty(true);
  }

  function selectGraphNode(nodeId: string, expand = false) {
    setSelectedGraphNodeId(nodeId);
    if (expand) setGraphExpanded(true);
  }

  function patchGraphNode(nodeId: string, patcher: (node: Node<GraphNodeData>) => Node<GraphNodeData>) {
    setGraphNodes((nodes) =>
      refreshGraphLabels(
        nodes.map((node) => {
          if (node.id !== nodeId) return node;
          return patcher(node);
        }),
      ),
    );
    setGraphDirty(true);
  }

  function setGraphNodeType(nodeId: string, nextType: string) {
    patchGraphNode(nodeId, (node) => {
      if (node.data.kind === 'root') {
        const mode = nextType === 'any' ? 'any' : 'all';
        return { ...node, data: { ...node.data, nodeType: mode, config: { mode } } };
      }
      const nextConfig = node.data.kind === 'condition' ? conditionTemplate(nextType) : actionTemplate(nextType);
      return { ...node, data: { ...node.data, nodeType: nextType, config: nextConfig } };
    });
  }

  function patchGraphNodeConfig(nodeId: string, path: string[], value: unknown) {
    patchGraphNode(nodeId, (node) => {
      const kind = node.data.kind;
      const nodeType = String(node.data.nodeType || '');
      const config = clone((node.data.config && typeof node.data.config === 'object' ? node.data.config : {}) as AnyRecord);
      if (kind === 'root') {
        let cursor = config as AnyRecord;
        path.slice(0, -1).forEach((key) => {
          if (!cursor[key] || typeof cursor[key] !== 'object') cursor[key] = {};
          cursor = cursor[key] as AnyRecord;
        });
        cursor[path[path.length - 1]] = value;
        return { ...node, data: { ...node.data, config } };
      }
      if (!config[nodeType] || typeof config[nodeType] !== 'object') config[nodeType] = {};
      let cursor = config[nodeType] as AnyRecord;
      path.slice(0, -1).forEach((key) => {
        if (!cursor[key] || typeof cursor[key] !== 'object') cursor[key] = {};
        cursor = cursor[key] as AnyRecord;
      });
      cursor[path[path.length - 1]] = value;
      return { ...node, data: { ...node.data, config } };
    });
  }

  function patchGraphNodeConfigMany(nodeId: string, updates: Array<{ path: string[]; value: unknown }>) {
    patchGraphNode(nodeId, (node) => {
      const kind = node.data.kind;
      const nodeType = String(node.data.nodeType || '');
      const config = clone((node.data.config && typeof node.data.config === 'object' ? node.data.config : {}) as AnyRecord);
      updates.forEach((update) => {
        const path = update.path;
        if (!path.length) return;
        let cursor: AnyRecord;
        if (kind === 'root') {
          cursor = config as AnyRecord;
        } else {
          if (!config[nodeType] || typeof config[nodeType] !== 'object') config[nodeType] = {};
          cursor = config[nodeType] as AnyRecord;
        }
        path.slice(0, -1).forEach((key) => {
          if (!cursor[key] || typeof cursor[key] !== 'object') cursor[key] = {};
          cursor = cursor[key] as AnyRecord;
        });
        cursor[path[path.length - 1]] = update.value;
      });
      return { ...node, data: { ...node.data, config } };
    });
  }

  function removeGraphNodeConfigPath(nodeId: string, path: string[]) {
    patchGraphNode(nodeId, (node) => {
      if (!path.length) return node;
      const kind = node.data.kind;
      const nodeType = String(node.data.nodeType || '');
      const config = clone((node.data.config && typeof node.data.config === 'object' ? node.data.config : {}) as AnyRecord);
      let cursor: AnyRecord;
      if (kind === 'root') {
        cursor = config as AnyRecord;
      } else {
        if (!config[nodeType] || typeof config[nodeType] !== 'object') return node;
        cursor = config[nodeType] as AnyRecord;
      }
      for (const key of path.slice(0, -1)) {
        if (!cursor[key] || typeof cursor[key] !== 'object') return node;
        cursor = cursor[key] as AnyRecord;
      }
      delete cursor[path[path.length - 1]];
      return { ...node, data: { ...node.data, config } };
    });
  }

  function setGraphEmotionChannel(nodeId: string, channel: string, value: unknown) {
    patchGraphNode(nodeId, (node) => {
      const config = clone((node.data.config && typeof node.data.config === 'object' ? node.data.config : {}) as AnyRecord);
      const payload = config.emotion_update && typeof config.emotion_update === 'object' ? (config.emotion_update as AnyRecord) : {};
      if (!channel.trim()) return node;
      payload[channel.trim()] = value;
      config.emotion_update = payload;
      return { ...node, data: { ...node.data, config } };
    });
  }

  function removeGraphEmotionChannel(nodeId: string, channel: string) {
    patchGraphNode(nodeId, (node) => {
      const config = clone((node.data.config && typeof node.data.config === 'object' ? node.data.config : {}) as AnyRecord);
      const payload = config.emotion_update && typeof config.emotion_update === 'object' ? (config.emotion_update as AnyRecord) : {};
      delete payload[channel];
      config.emotion_update = payload;
      return { ...node, data: { ...node.data, config } };
    });
  }

  function addGraphEmotionChannel(nodeId: string) {
    const existing = graphNodeInnerConfig(graphNodes.find((node) => node.id === nodeId)) as AnyRecord;
    const used = new Set(Object.keys(existing || {}));
    const channel = ['DA', 'ADR', 'OXY', 'SER', 'END', 'COR', 'NOV', 'FOC'].find((item) => !used.has(item)) || `CH${used.size + 1}`;
    setGraphEmotionChannel(nodeId, channel, 0);
  }

  function renderGraphPalette(compact = false) {
    const buttonSize = compact ? 'xs' : 'sm';
    return (
      <Stack gap={compact ? 6 : 'xs'} className="rule-graph-palette">
        <div>
          <Text fw={800} size="sm">条件 / When</Text>
          <Text size="xs" c="dimmed">条件决定规则何时触发，可以单独触发，也可以由 root 汇总为 all/any。</Text>
        </div>
        <Group gap="xs" wrap="wrap">
          <Button size={buttonSize} variant="light" onClick={() => addGraphNode('condition', 'cfs')}>+ 认知感受 CFS</Button>
          <Button size={buttonSize} variant="light" onClick={() => addGraphNode('condition', 'state_window')}>+ 状态窗口</Button>
          <Button size={buttonSize} variant="light" onClick={() => addGraphNode('condition', 'timer')}>+ 定时器</Button>
          <Button size={buttonSize} variant="light" onClick={() => addGraphNode('condition', 'metric')}>+ 指标条件 metric</Button>
        </Group>
        <Divider my={compact ? 2 : 4} />
        <div>
          <Text fw={800} size="sm">动作 / Then</Text>
          <Text size="xs" c="dimmed">动作是规则触发后的输出，旧版图编辑器支持的动作已迁移到这里。</Text>
        </div>
        <Group gap="xs" wrap="wrap">
          <Button size={buttonSize} variant="subtle" onClick={() => addGraphNode('action', 'cfs_emit')}>+ 认知感受生成</Button>
          <Button size={buttonSize} variant="subtle" onClick={() => addGraphNode('action', 'focus')}>+ 聚焦指令</Button>
          <Button size={buttonSize} variant="subtle" onClick={() => addGraphNode('action', 'emit_script')}>+ 触发记录</Button>
          <Button size={buttonSize} variant="subtle" onClick={() => addGraphNode('action', 'emotion_update')}>+ 情绪更新 NT</Button>
          <Button size={buttonSize} variant="subtle" onClick={() => addGraphNode('action', 'action_trigger')}>+ 行动触发</Button>
          <Button size={buttonSize} variant="subtle" onClick={() => addGraphNode('action', 'pool_energy')}>+ 对对象赋能 ER/EV</Button>
          <Button size={buttonSize} variant="subtle" onClick={() => addGraphNode('action', 'pool_bind_attribute')}>+ 绑定属性</Button>
          <Button size={buttonSize} variant="subtle" onClick={() => addGraphNode('action', 'delay')}>+ 延时</Button>
          <Button size={buttonSize} variant="subtle" onClick={() => addGraphNode('action', 'branch')}>+ 分支</Button>
          <Button size={buttonSize} variant="subtle" onClick={() => addGraphNode('action', 'log')}>+ 日志</Button>
        </Group>
        <Group gap="xs">
          <Button size={buttonSize} color="red" variant="light" disabled={!selectedGraphNodeId || selectedGraphNodeId === 'root'} onClick={deleteSelectedGraphNode}>
            删除当前节点
          </Button>
          <Button size={buttonSize} variant="light" disabled={!selectedGraphNodeId} onClick={applyGraphNodeDraft}>
            应用节点 JSON
          </Button>
        </Group>
      </Stack>
    );
  }

  function renderGraphHowTo() {
    const examples = [
      {
        title: '例 1：对象认知压升高 -> 生成违和感 -> 聚焦该对象',
        steps: '添加“指标条件 metric”，preset 选“获得认知压大小”或“认知压变化率”，capture_as 填 cp；再添加“认知感受生成 cfs_emit”，kind 填 dissonance，from 选 metric_matches；最后添加“聚焦指令 focus”。',
      },
      {
        title: '例 2：奖励信号变化 -> 调高多巴胺/聚焦通道',
        steps: '添加 metric，preset 选“奖励信号变化率 reward_rate”，op 选 >，value 填 0；添加“情绪更新 NT”，加入 DA=0.05 或 FOC=0.03；回写规则后校验草稿。',
      },
      {
        title: '例 3：指标命中对象 -> 触发行动节点',
        steps: 'metric 的 selector 可选 top_n 或 contains_text，capture_as 填 hit；行动触发 action_trigger 的 from 选 metric_matches，params 可填 target_ref_object_id={{{match_ref_object_id}}}, strength={{{match_value}}}。',
      },
    ];
    return (
      <Card className="soft-note-card rule-graph-guide">
        <Group justify="space-between" align="flex-start" mb="xs">
          <div>
            <Text fw={800}>图编辑说明书</Text>
            <Text size="xs" c="dimmed">从“能画出来”到“知道怎么画”：这里保留操作提示和三个最常用的规则构造例子。</Text>
          </div>
          <Badge variant="light">小白向</Badge>
        </Group>
        <Grid>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Text fw={700} size="sm">基础操作</Text>
            <Text size="xs" c="dimmed">
              左侧按钮添加节点；左键选中节点；拖拽节点移动；从节点边缘端口拖到另一个节点端口可以连线；双击或右键节点会进入放大编辑。改完字段后先点“回写规则”，再点“校验草稿/保存草稿”。
            </Text>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Text fw={700} size="sm">连接规则</Text>
            <Text size="xs" c="dimmed">
              条件节点连到 root，动作节点由 root 连出。当前回写时会优先采用实际连到 root 的条件/动作；如果没有手动连线，则按左条件、右动作的布局顺序编译，避免新手误操作后规则为空。
            </Text>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Text fw={700} size="sm">字段思路</Text>
            <Text size="xs" c="dimmed">
              metric 负责“看见什么指标”，capture_as 负责“把数值记成变量”，cfs_emit/focus/emotion/action/pool_* 负责“系统应该怎么反应”。普通字段用中文表单，高级嵌套才用 JSON。
            </Text>
          </Grid.Col>
          {examples.map((item) => (
            <Grid.Col key={item.title} span={{ base: 12, md: 4 }}>
              <Card className="soft-note-card rule-graph-example" p="sm">
                <Text fw={700} size="sm">{item.title}</Text>
                <Text size="xs" c="dimmed" mt={4}>{item.steps}</Text>
              </Card>
            </Grid.Col>
          ))}
        </Grid>
      </Card>
    );
  }

  const onGraphEdgesChange = useCallback((changes: EdgeChange[]) => {
    setGraphEdges((edges) => applyEdgeChanges(changes, edges));
    if (changes.length) setGraphDirty(true);
  }, []);

  const onGraphConnect = useCallback((connection: Connection) => {
    setGraphEdges((edges) => addEdge({ ...connection, animated: true }, edges));
    setGraphDirty(true);
  }, []);

  function applyGraphNodeDraft() {
    if (!selectedGraphNodeId) return;
    let parsed: AnyRecord;
    try {
      parsed = JSON.parse(graphNodeDraft || '{}');
    } catch (error) {
      setFeedback({ kind: 'error', message: `图形节点 JSON 解析失败：${error instanceof Error ? error.message : String(error)}` });
      return;
    }
    setGraphNodes((nodes) =>
      refreshGraphLabels(
        nodes.map((node) => {
          if (node.id !== selectedGraphNodeId) return node;
          const nodeType = String(parsed.node_type || node.data.nodeType || 'custom');
          const config = parsed.config && typeof parsed.config === 'object' ? parsed.config : parsed;
          return { ...node, data: { ...node.data, nodeType, config } };
        }),
      ),
    );
    setGraphDirty(true);
    setFeedback({ kind: 'ok', message: '已应用图形节点草稿。' });
  }

  function applyGraphToRule() {
    if (!selectedRule) return;
    const compiled = compileRuleGraph(graphNodes, graphEdges);
    if (!compiled.ok) {
      setFeedback({ kind: 'error', message: compiled.message });
      return;
    }
    updateSelectedRule((rule) => {
      rule.when = compiled.when;
      rule.then = compiled.then;
      if (!rule.ui || typeof rule.ui !== 'object') rule.ui = {};
      rule.ui.graph_nodes = graphNodes.map((node) => ({
        id: node.id,
        kind: node.data.kind,
        node_type: node.data.nodeType,
        position: node.position,
      }));
      rule.ui.graph_saved_at_ms = Date.now();
    });
    setGraphDirty(false);
    setFeedback({ kind: 'ok', message: '已将图形条件/动作回写到规则草稿。下一步可校验并保存。' });
  }

  async function validateDoc() {
    setBusy(true);
    try {
      const payload = await api.validateInnateRules({ doc });
      setResult(payload);
      if (payload?.yaml_preview || payload?.normalized_yaml) setYaml(String(payload.yaml_preview || payload.normalized_yaml));
      setFeedback({
        kind: payload?.valid ? 'ok' : 'error',
        message: resultSummary(payload),
      });
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function validateYaml(importToDoc = false) {
    setBusy(true);
    try {
      const payload = await api.validateInnateRules({ yaml });
      setResult(payload);
      if (payload?.yaml_preview || payload?.normalized_yaml) setYaml(String(payload.yaml_preview || payload.normalized_yaml));
      if (importToDoc && payload?.valid && payload?.normalized_doc) {
        const normalized = ensureRuleDoc(payload.normalized_doc);
        setDoc(normalized);
        setDirty(true);
        setSelectedId(String(asArray<AnyRecord>(normalized.rules)[0]?.id || ''));
      }
      setFeedback({
        kind: payload?.valid ? 'ok' : 'error',
        message: importToDoc && payload?.valid ? 'YAML 已导入到左侧规则草稿。' : resultSummary(payload),
      });
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function saveDoc() {
    const ok = window.confirm('保存当前规则草稿并热加载 IESM？保存前会由后端再次校验并创建历史备份。');
    if (!ok) return;
    setBusy(true);
    try {
      const payload = await api.saveInnateRules({ doc });
      setResult(payload);
      setFeedback({
        kind: payload?.saved ? 'ok' : 'error',
        message: resultSummary(payload),
      });
      if (payload?.saved) await refresh(true);
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function saveYaml() {
    const ok = window.confirm('按高级 YAML 编辑区保存并热加载？如果左侧草稿未导入 YAML，左侧改动不会包含在这次保存中。');
    if (!ok) return;
    setBusy(true);
    try {
      const payload = await api.saveInnateRules({ yaml });
      setResult(payload);
      setFeedback({
        kind: payload?.saved ? 'ok' : 'error',
        message: resultSummary(payload),
      });
      if (payload?.saved) await refresh(true);
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function reloadRules() {
    setBusy(true);
    try {
      const payload = await api.reloadInnateRules();
      setResult(payload);
      await refresh(true);
      setFeedback({ kind: 'ok', message: '已从规则文件重新加载。' });
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function simulate() {
    setBusy(true);
    try {
      const payload = await api.simulateInnateRules();
      setResult(payload);
      setFeedback({ kind: payload?.ok ? 'ok' : 'warn', message: resultSummary(payload) });
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  function renderGraphNodeEditor(expanded = false) {
    if (!selectedGraphNode) {
      return (
        <Card className="soft-note-card" mt="sm">
          <Text fw={800}>节点属性</Text>
          <Text size="xs" c="dimmed">
            点击图中的条件、汇总或动作节点后，这里会出现中文表单。右键或双击节点会直接打开放大编辑区。
          </Text>
        </Card>
      );
    }

    const node = selectedGraphNode;
    const nodeKind = node.data.kind;
    const nodeType = String(node.data.nodeType || '');
    const config = selectedGraphNodeConfig;
    const nodeTypeOptions = graphNodeTypeOptions(nodeKind);
    const metricOptions = metricPresetOptions(asArray<AnyRecord>(bundle?.metric_presets));
    const metricPreset = findMetricPreset(asArray<AnyRecord>(bundle?.metric_presets), config.preset);
    const metricNeedsChannel = selectedMetricPresetNeedsChannel(asArray<AnyRecord>(bundle?.metric_presets), config.preset);

    const selectorFields = (basePath: string[] = ['selector']) => {
      const selector = basePath.reduce<AnyRecord>((cursor, key) => {
        const next = cursor?.[key];
        return next && typeof next === 'object' ? (next as AnyRecord) : {};
      }, config);
      return (
        <>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Select
              label="目标选择模式"
              description="决定这个条件或动作看哪些状态池对象。"
              value={String(selector.mode || 'all')}
              data={SELECTOR_MODE_OPTIONS}
              onChange={(value) => patchGraphNodeConfig(node.id, [...basePath, 'mode'], value || 'all')}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <TextInput label="ref_object_id" value={toText(selector.ref_object_id)} onChange={(event) => patchGraphNodeConfig(node.id, [...basePath, 'ref_object_id'], event.currentTarget.value)} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Select
              label="ref_object_type"
              value={selectValueOrNone(selector.ref_object_type)}
              data={REF_OBJECT_TYPE_OPTIONS}
              onChange={(value) => patchGraphNodeConfig(node.id, [...basePath, 'ref_object_type'], noneToEmpty(value))}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <TextInput label="item_id" value={toText(selector.item_id)} onChange={(event) => patchGraphNodeConfig(node.id, [...basePath, 'item_id'], event.currentTarget.value)} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <TextInput label="包含文本/特征" value={toText(selector.contains_text)} onChange={(event) => patchGraphNodeConfig(node.id, [...basePath, 'contains_text'], event.currentTarget.value)} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 4 }}>
            <NumberInput label="Top-N 数量" value={selector.top_n === undefined ? '' : Number(selector.top_n)} min={1} step={1} onChange={(value) => patchGraphNodeConfig(node.id, [...basePath, 'top_n'], value === '' ? '' : Number(value))} />
          </Grid.Col>
          <Grid.Col span={{ base: 12 }}>
            <TextInput
              label="ref_object_types 类型过滤"
              description="逗号分隔，例如 st, sa。留空表示不限制。"
              value={listToCsv(selector.ref_object_types)}
              onChange={(event) => patchGraphNodeConfig(node.id, [...basePath, 'ref_object_types'], csvToList(event.currentTarget.value))}
            />
          </Grid.Col>
        </>
      );
    };

    return (
      <Card className="soft-note-card graph-node-editor" mt="sm">
        <Group justify="space-between" align="flex-start" mb="sm">
          <div>
            <Text fw={800}>节点属性</Text>
            <Text size="xs" c="dimmed">
              {nodeKind === 'condition' ? '条件节点' : nodeKind === 'action' ? '动作节点' : '条件汇总节点'} | {node.id}
            </Text>
          </div>
          <Group gap="xs">
            <Badge variant="light">{nodeType || nodeKind}</Badge>
            {node.id !== 'root' ? (
              <Button size="xs" color="red" variant="light" onClick={deleteSelectedGraphNode}>
                删除节点
              </Button>
            ) : null}
          </Group>
        </Group>

        <Grid>
          <Grid.Col span={{ base: 12, md: nodeKind === 'root' ? 12 : 6 }}>
            <Select
              label={nodeKind === 'root' ? '条件汇总模式' : '节点类型'}
              value={nodeKind === 'root' ? String(config.mode || nodeType || 'all') : nodeType}
              data={nodeTypeOptions}
              onChange={(value) => value && setGraphNodeType(node.id, value)}
            />
          </Grid.Col>
          {nodeKind !== 'root' ? (
            <Grid.Col span={{ base: 12, md: 6 }}>
              <TextInput
                label="节点 ID"
                value={node.id}
                readOnly
                description="节点 ID 用于图形编辑器内部连线；规则保存时会写入 ui.graph_nodes。"
              />
            </Grid.Col>
          ) : null}
        </Grid>

        {nodeKind === 'root' ? (
          <Text size="xs" c="dimmed" mt="sm">
            all 表示所有条件同时满足才触发；any 表示任一条件满足即可触发。
          </Text>
        ) : null}

        {nodeKind === 'condition' && nodeType === 'cfs' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12, md: 6 }}>
              <TextInput
                label="认知感受 kinds"
                description="逗号分隔，例如 dissonance, pressure。"
                value={listToCsv(config.kinds)}
                onChange={(event) => patchGraphNodeConfig(node.id, ['kinds'], csvToList(event.currentTarget.value))}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <NumberInput
                label="最小强度"
                value={Number(config.min_strength ?? 0)}
                min={0}
                max={1}
                step={0.05}
                onChange={(value) => patchGraphNodeConfig(node.id, ['min_strength'], Number(value) || 0)}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <NumberInput
                label="最大强度"
                value={config.max_strength === undefined ? '' : Number(config.max_strength)}
                min={0}
                max={1}
                step={0.05}
                onChange={(value) => patchGraphNodeConfig(node.id, ['max_strength'], value === '' ? undefined : Number(value))}
              />
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'condition' && nodeType === 'state_window' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput
                label="阶段 stage"
                value={String(config.stage || 'any')}
                onChange={(event) => patchGraphNodeConfig(node.id, ['stage'], event.currentTarget.value || 'any')}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <NumberInput
                label="CP 快速上升阈值"
                value={Number(config.fast_cp_rise_min ?? 0)}
                step={0.1}
                onChange={(value) => patchGraphNodeConfig(node.id, ['fast_cp_rise_min'], Number(value) || 0)}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <NumberInput
                label="CP 快速下降阈值"
                value={Number(config.fast_cp_drop_min ?? 0)}
                step={0.1}
                onChange={(value) => patchGraphNodeConfig(node.id, ['fast_cp_drop_min'], Number(value) || 0)}
              />
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'condition' && nodeType === 'timer' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12, md: 6 }}>
              <NumberInput
                label="每 N tick 触发"
                value={Number(config.every_n_ticks ?? 1)}
                min={1}
                step={1}
                onChange={(value) => patchGraphNodeConfig(node.id, ['every_n_ticks'], Number(value) || 1)}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <NumberInput
                label="指定 tick"
                value={config.at_tick === undefined ? '' : Number(config.at_tick)}
                min={0}
                step={1}
                onChange={(value) => patchGraphNodeConfig(node.id, ['at_tick'], value === '' ? undefined : Number(value))}
              />
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'condition' && nodeType === 'metric' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12, md: 6 }}>
              <Select
                label="指标预设 preset"
                description={metricPreset ? `${metricPreset.metric || '-'} | 默认 mode=${metricPreset.mode || '-'}` : '推荐优先选择中文指标预设；也可以切到手动 metric。'}
                searchable
                value={selectValueOrNone(config.preset)}
                data={metricOptions}
                onChange={(value) => {
                  const preset = noneToEmpty(value);
                  const item = findMetricPreset(asArray<AnyRecord>(bundle?.metric_presets), preset);
                  patchGraphNodeConfigMany(node.id, [
                    { path: ['preset'], value: preset },
                    { path: ['metric'], value: preset ? '' : String(config.metric || '') },
                    { path: ['mode'], value: item?.mode || config.mode || 'state' },
                    { path: ['window_ticks'], value: item?.window_ticks || config.window_ticks || 4 },
                    { path: ['op'], value: item?.op || config.op || '>=' },
                  ]);
                }}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <TextInput
                label="手动指标路径 metric"
                description="示例：item.er / pool.total_er / emotion.nt.DA / retrieval.stimulus.match_scores"
                value={String(config.metric || '')}
                onChange={(event) => patchGraphNodeConfig(node.id, ['metric'], event.currentTarget.value)}
              />
            </Grid.Col>
            {metricNeedsChannel ? (
              <Grid.Col span={{ base: 12, md: 4 }}>
                <Select
                  label="NT 通道 channel"
                  description="仅 NT 指标需要。可用中文或缩写，保存时由后端归一化。"
                  searchable
                  value={String(config.channel || '')}
                  data={NT_CHANNEL_OPTIONS}
                  onChange={(value) => patchGraphNodeConfig(node.id, ['channel'], value || '')}
                />
              </Grid.Col>
            ) : null}
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select
                label="取值方式 mode"
                value={String(config.mode || metricPreset?.mode || 'state')}
                data={METRIC_MODE_OPTIONS}
                onChange={(value) => patchGraphNodeConfig(node.id, ['mode'], value || 'state')}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select
                label="比较方式"
                value={String(config.op || '>=')}
                data={COMPARE_OPTIONS}
                onChange={(value) => patchGraphNodeConfig(node.id, ['op'], value || '>=')}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput
                label="阈值 value"
                description="可写数值，也可写 {{{变量名}}}。"
                value={toText(config.value)}
                onChange={(event) => patchGraphNodeConfig(node.id, ['value'], toNumberOrText(event.currentTarget.value))}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput
                label="区间最小 min"
                description="op=between 时使用。"
                value={toText(config.min)}
                onChange={(event) => patchGraphNodeConfig(node.id, ['min'], toNumberOrText(event.currentTarget.value))}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput
                label="区间最大 max"
                description="op=between 时使用。"
                value={toText(config.max)}
                onChange={(event) => patchGraphNodeConfig(node.id, ['max'], toNumberOrText(event.currentTarget.value))}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <NumberInput
                label="窗口 tick"
                description="mode=avg_rate 时使用，常用 3~4。"
                value={config.window_ticks === undefined ? '' : Number(config.window_ticks)}
                min={1}
                step={1}
                onChange={(value) => patchGraphNodeConfig(node.id, ['window_ticks'], value === '' ? '' : Number(value))}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select
                label="对象匹配策略"
                description="item.* 指标命中多个对象时如何结算。"
                value={String(config.match_policy || 'any')}
                data={MATCH_POLICY_OPTIONS}
                onChange={(value) => patchGraphNodeConfig(node.id, ['match_policy'], value || 'any')}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput
                label="变量捕获 capture_as"
                description="动作里可用 {{{变量名}}}、{{{变量名_item_id}}} 等引用。"
                value={String(config.capture_as || '')}
                onChange={(event) => patchGraphNodeConfig(node.id, ['capture_as'], event.currentTarget.value)}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <NumberInput
                label="比较容差 epsilon"
                description="等值/不等值比较的容差，一般留默认。"
                value={config.epsilon === undefined ? '' : Number(config.epsilon)}
                min={0}
                step={0.0001}
                onChange={(value) => patchGraphNodeConfig(node.id, ['epsilon'], value === '' ? '' : Number(value))}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12 }}>
              <Divider label="对象选择器 selector" labelPosition="left" />
            </Grid.Col>
            {selectorFields()}
            <Grid.Col span={{ base: 12 }}>
              <Divider label="上一 tick 门控 prev_gate" labelPosition="left" />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <Select
                label="prev_gate 比较符"
                value={selectValueOrNone(config.prev_gate?.op)}
                data={[{ value: NONE_VALUE, label: '不启用' }, ...COMPARE_OPTIONS]}
                onChange={(value) => {
                  const op = noneToEmpty(value);
                  if (!op) removeGraphNodeConfigPath(node.id, ['prev_gate']);
                  else patchGraphNodeConfig(node.id, ['prev_gate', 'op'], op);
                }}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <TextInput label="prev value" value={toText(config.prev_gate?.value)} onChange={(event) => patchGraphNodeConfig(node.id, ['prev_gate', 'value'], toNumberOrText(event.currentTarget.value))} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <TextInput label="prev min" value={toText(config.prev_gate?.min)} onChange={(event) => patchGraphNodeConfig(node.id, ['prev_gate', 'min'], toNumberOrText(event.currentTarget.value))} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <TextInput label="prev max" value={toText(config.prev_gate?.max)} onChange={(event) => patchGraphNodeConfig(node.id, ['prev_gate', 'max'], toNumberOrText(event.currentTarget.value))} />
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'action' && nodeType === 'focus' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select
                label="来源 from"
                value={String(config.from || 'cfs_matches')}
                data={[
                  { value: 'cfs_matches', label: '认知感受命中 cfs_matches' },
                  { value: 'state_window_candidates', label: '状态窗口候选 state_window_candidates' },
                ]}
                onChange={(value) => patchGraphNodeConfig(node.id, ['from'], value || 'cfs_matches')}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <NumberInput label="存活 TTL ticks" value={Number(config.ttl_ticks ?? 2)} min={1} step={1} onChange={(value) => patchGraphNodeConfig(node.id, ['ttl_ticks'], Number(value) || 1)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <NumberInput label="聚焦增益" value={Number(config.focus_boost ?? 0.9)} min={0} step={0.05} onChange={(value) => patchGraphNodeConfig(node.id, ['focus_boost'], Number(value) || 0)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <Select
                label="匹配策略"
                value={String(config.match_policy || 'all')}
                data={MATCH_POLICY_OPTIONS.filter((item) => item.value !== 'any')}
                onChange={(value) => patchGraphNodeConfig(node.id, ['match_policy'], value || 'all')}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <TextInput label="去重字段" value={String(config.deduplicate_by || 'target_ref_object_id')} onChange={(event) => patchGraphNodeConfig(node.id, ['deduplicate_by'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <NumberInput
                label="最多聚焦指令"
                value={config.max_directives === undefined ? '' : Number(config.max_directives)}
                min={1}
                step={1}
                onChange={(value) => patchGraphNodeConfig(node.id, ['max_directives'], value === '' ? '' : Number(value))}
              />
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'action' && nodeType === 'cfs_emit' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput
                label="感受类型 kind"
                description="如 dissonance 违和、correct_event 正确、expectation 期待、pressure 压力。"
                value={String(config.kind || '')}
                onChange={(event) => patchGraphNodeConfig(node.id, ['kind'], event.currentTarget.value)}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select
                label="作用域 scope"
                value={String(config.scope || 'object')}
                data={[
                  { value: 'object', label: '对象级 object' },
                  { value: 'global', label: '全局 global' },
                ]}
                onChange={(value) => patchGraphNodeConfig(node.id, ['scope'], value || 'object')}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select
                label="来源 from"
                value={String(config.from || 'metric_matches')}
                data={[
                  { value: 'metric_matches', label: '指标命中 metric_matches' },
                  { value: 'cfs_matches', label: '认知感受命中 cfs_matches' },
                  { value: 'single', label: '单条 single' },
                ]}
                onChange={(value) => patchGraphNodeConfig(node.id, ['from'], value || 'metric_matches')}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <NumberInput label="最多生成条数" value={config.max_signals === undefined ? '' : Number(config.max_signals)} min={1} step={1} onChange={(value) => patchGraphNodeConfig(node.id, ['max_signals'], value === '' ? '' : Number(value))} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <NumberInput label="最小强度" value={Number(config.min_strength ?? 0)} min={0} max={1} step={0.05} onChange={(value) => patchGraphNodeConfig(node.id, ['min_strength'], Number(value) || 0)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="捕获为变量" value={String(config.capture_as || '')} onChange={(event) => patchGraphNodeConfig(node.id, ['capture_as'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12 }}>
              <Divider label="强度映射 strength" labelPosition="left" />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select
                label="映射策略"
                value={String(config.strength?.policy || 'linear_clamp')}
                data={[
                  { value: 'linear_clamp', label: '线性钳制 linear_clamp' },
                  { value: 'scale_offset', label: '比例偏移 scale_offset' },
                  { value: 'verify_mix', label: '验证混合 verify_mix' },
                ]}
                onChange={(value) => patchGraphNodeConfig(node.id, ['strength', 'policy'], value || 'linear_clamp')}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="strength.from" value={String(config.strength?.from || 'match_value')} onChange={(event) => patchGraphNodeConfig(node.id, ['strength', 'from'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="strength.var" value={String(config.strength?.var || '')} onChange={(event) => patchGraphNodeConfig(node.id, ['strength', 'var'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <NumberInput label="输入 min" value={Number(config.strength?.min ?? 0)} step={0.05} onChange={(value) => patchGraphNodeConfig(node.id, ['strength', 'min'], Number(value) || 0)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <NumberInput label="输入 max" value={Number(config.strength?.max ?? 1)} step={0.05} onChange={(value) => patchGraphNodeConfig(node.id, ['strength', 'max'], Number(value) || 0)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <NumberInput label="输出 out_min" value={Number(config.strength?.out_min ?? 0)} min={0} max={1} step={0.05} onChange={(value) => patchGraphNodeConfig(node.id, ['strength', 'out_min'], Number(value) || 0)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <NumberInput label="输出 out_max" value={Number(config.strength?.out_max ?? 1)} min={0} max={1} step={0.05} onChange={(value) => patchGraphNodeConfig(node.id, ['strength', 'out_max'], Number(value) || 0)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <Switch label="abs 先取绝对值" checked={Boolean(config.strength?.abs)} onChange={(event) => patchGraphNodeConfig(node.id, ['strength', 'abs'], event.currentTarget.checked)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <Switch label="invert 输出 1-x" checked={Boolean(config.strength?.invert)} onChange={(event) => patchGraphNodeConfig(node.id, ['strength', 'invert'], event.currentTarget.checked)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12 }}>
              <Divider label="目标绑定 target" labelPosition="left" />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select
                label="target.from"
                value={String(config.target?.from || 'match')}
                data={[
                  { value: 'match', label: '来自命中对象 match' },
                  { value: 'specific_ref', label: '特定对象 specific_ref' },
                  { value: 'specific_item', label: '特定条目 specific_item' },
                ]}
                onChange={(value) => {
                  if (!value || value === 'match') removeGraphNodeConfigPath(node.id, ['target']);
                  else patchGraphNodeConfig(node.id, ['target', 'from'], value);
                }}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="target.ref_object_id" value={toText(config.target?.ref_object_id)} onChange={(event) => patchGraphNodeConfig(node.id, ['target', 'ref_object_id'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="target.item_id" value={toText(config.target?.item_id)} onChange={(event) => patchGraphNodeConfig(node.id, ['target', 'item_id'], event.currentTarget.value)} />
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'action' && nodeType === 'emit_script' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12, md: 6 }}>
              <TextInput label="脚本 ID" value={String(config.script_id || '')} onChange={(event) => patchGraphNodeConfig(node.id, ['script_id'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <TextInput label="脚本类型" value={String(config.script_kind || '')} onChange={(event) => patchGraphNodeConfig(node.id, ['script_kind'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <TextInput label="触发名 trigger" value={String(config.trigger || '')} onChange={(event) => patchGraphNodeConfig(node.id, ['trigger'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <NumberInput label="优先级" value={Number(config.priority ?? 50)} step={1} onChange={(value) => patchGraphNodeConfig(node.id, ['priority'], Number(value) || 0)} />
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'action' && nodeType === 'action_trigger' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput
                label="行动类型 action_kind"
                description="如 attention_focus 注意力聚焦、recall 回忆、custom 自定义。"
                value={String(config.action_kind || '')}
                onChange={(event) => patchGraphNodeConfig(node.id, ['action_kind'], event.currentTarget.value)}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="行动 ID" value={String(config.action_id || '')} onChange={(event) => patchGraphNodeConfig(node.id, ['action_id'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select
                label="展开来源 from"
                value={selectValueOrNone(config.from)}
                data={[
                  { value: NONE_VALUE, label: '单条触发' },
                  { value: 'metric_matches', label: '指标命中 metric_matches' },
                  { value: 'cfs_matches', label: '认知感受命中 cfs_matches' },
                ]}
                onChange={(value) => patchGraphNodeConfig(node.id, ['from'], noneToEmpty(value))}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="触发阈值 threshold" description="可写数值或 {{{变量名}}}。" value={toText(config.threshold, '0.7')} onChange={(event) => patchGraphNodeConfig(node.id, ['threshold'], toNumberOrText(event.currentTarget.value))} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="驱动力增益 gain" description="可写数值或 {{{match_value}}}。" value={toText(config.gain, '0.35')} onChange={(event) => patchGraphNodeConfig(node.id, ['gain'], toNumberOrText(event.currentTarget.value))} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <NumberInput label="最大触发数" value={Number(config.max_triggers ?? 1)} min={1} step={1} onChange={(value) => patchGraphNodeConfig(node.id, ['max_triggers'], Number(value) || 1)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select label="展开策略" value={String(config.match_policy || 'all')} data={MATCH_POLICY_OPTIONS.filter((item) => item.value !== 'any')} onChange={(value) => patchGraphNodeConfig(node.id, ['match_policy'], value || 'all')} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <NumberInput label="冷却 tick" value={Number(config.cooldown_ticks ?? 0)} min={0} step={1} onChange={(value) => patchGraphNodeConfig(node.id, ['cooldown_ticks'], Number(value) || 0)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12 }}>
              <TextInput
                label="params 参数键值对"
                description="简化输入：key=value，每项用逗号隔开。例 target_ref_object_id={{{match_ref_object_id}}}, strength={{{match_value}}}"
                value={Object.entries((config.params && typeof config.params === 'object' ? config.params : {}) as AnyRecord).map(([key, value]) => `${key}=${value}`).join(', ')}
                onChange={(event) => {
                  const params: AnyRecord = {};
                  event.currentTarget.value.split(',').forEach((part) => {
                    const [rawKey, ...rest] = part.split('=');
                    const key = rawKey.trim();
                    if (!key) return;
                    params[key] = toNumberOrText(rest.join('=').trim());
                  });
                  patchGraphNodeConfig(node.id, ['params'], params);
                }}
              />
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'action' && nodeType === 'emotion_update' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12 }}>
              <Text size="xs" c="dimmed">
                情绪更新支持多通道键值对；通道可用 DA/ADR/OXY/SER/END/COR/NOV/FOC 或中文名，数值可为负，也可写模板。
              </Text>
            </Grid.Col>
            {Object.entries(config).filter(([key]) => !['from', 'match_policy', 'max_updates', 'max_matches', 'channels'].includes(key)).map(([channel, value]) => (
              <Grid.Col span={{ base: 12, md: 6 }} key={channel}>
                <Group align="flex-end" gap="xs" wrap="nowrap">
                  <TextInput
                    label="通道"
                    value={channel}
                    onChange={(event) => {
                      const nextChannel = event.currentTarget.value.trim();
                      removeGraphEmotionChannel(node.id, channel);
                      if (nextChannel) setGraphEmotionChannel(node.id, nextChannel, value);
                    }}
                    style={{ flex: 1 }}
                  />
                  <TextInput
                    label="增量"
                    value={toText(value)}
                    onChange={(event) => setGraphEmotionChannel(node.id, channel, toNumberOrText(event.currentTarget.value))}
                    style={{ flex: 1 }}
                  />
                  <Button size="xs" color="red" variant="light" onClick={() => removeGraphEmotionChannel(node.id, channel)}>
                    移除
                  </Button>
                </Group>
              </Grid.Col>
            ))}
            <Grid.Col span={{ base: 12 }}>
              <Group gap="xs">
                <Button size="xs" variant="light" onClick={() => addGraphEmotionChannel(node.id)}>
                  添加 NT 通道
                </Button>
                <Select
                  label="从命中展开"
                  description="可选：让情绪更新对 metric/cfs 命中结果展开。"
                  value={selectValueOrNone(config.from)}
                  data={[
                    { value: NONE_VALUE, label: '不展开' },
                    { value: 'metric_matches', label: '指标命中 metric_matches' },
                    { value: 'cfs_matches', label: '认知感受命中 cfs_matches' },
                  ]}
                  onChange={(value) => patchGraphNodeConfig(node.id, ['from'], noneToEmpty(value))}
                />
                <Select label="展开策略" value={String(config.match_policy || 'all')} data={MATCH_POLICY_OPTIONS.filter((item) => item.value !== 'any')} onChange={(value) => patchGraphNodeConfig(node.id, ['match_policy'], value || 'all')} />
              </Group>
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'action' && nodeType === 'pool_energy' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12 }}>
              <Text size="xs" c="dimmed">
                对状态池对象注入 ER/EV，最终由观测台安全执行器落地。适合表达先天规则对特定对象的即时能量偏置。
              </Text>
            </Grid.Col>
            {selectorFields()}
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="实能量增量 delta_er" description="可写数值或 {{{变量名}}}，可为负。" value={toText(config.delta_er ?? config.er, '0')} onChange={(event) => patchGraphNodeConfig(node.id, ['delta_er'], toNumberOrText(event.currentTarget.value))} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="虚能量增量 delta_ev" description="可写数值或 {{{变量名}}}，可为负。" value={toText(config.delta_ev ?? config.ev, '0')} onChange={(event) => patchGraphNodeConfig(node.id, ['delta_ev'], toNumberOrText(event.currentTarget.value))} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Switch label="缺失时创建对象" description="仅建议 specific_ref 且正能量时启用。" checked={Boolean(config.create_if_missing)} onChange={(event) => patchGraphNodeConfig(node.id, ['create_if_missing'], event.currentTarget.checked)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select label="创建对象类型" value={String(config.create_ref_object_type || 'sa')} data={REF_OBJECT_TYPE_OPTIONS.filter((item) => item.value !== NONE_VALUE)} onChange={(value) => patchGraphNodeConfig(node.id, ['create_ref_object_type'], value || 'sa')} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="创建展示 create_display" value={toText(config.create_display)} onChange={(event) => patchGraphNodeConfig(node.id, ['create_display'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="原因 reason" value={toText(config.reason)} onChange={(event) => patchGraphNodeConfig(node.id, ['reason'], event.currentTarget.value)} />
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'action' && nodeType === 'pool_bind_attribute' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12 }}>
              <Text size="xs" c="dimmed">
                把属性刺激元绑定到目标对象快照中，适合表达“违和/正确/期待/压力”等感受与对象的锚定关系，通常不单独制造状态池噪音。
              </Text>
            </Grid.Col>
            {selectorFields()}
            <Grid.Col span={{ base: 12 }}>
              <Divider label="属性内容 attribute" labelPosition="left" />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="属性名 attribute_name" value={toText(config.attribute?.attribute_name)} onChange={(event) => patchGraphNodeConfig(node.id, ['attribute', 'attribute_name'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="属性值 attribute_value" value={toText(config.attribute?.attribute_value)} onChange={(event) => patchGraphNodeConfig(node.id, ['attribute', 'attribute_value'], toNumberOrText(event.currentTarget.value))} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="展示文本 display" value={toText(config.attribute?.display)} onChange={(event) => patchGraphNodeConfig(node.id, ['attribute', 'display'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="原始文本 raw" value={toText(config.attribute?.raw)} onChange={(event) => patchGraphNodeConfig(node.id, ['attribute', 'raw'], event.currentTarget.value)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select
                label="值类型 value_type"
                value={String(config.attribute?.value_type || 'discrete')}
                data={[
                  { value: 'discrete', label: '离散 discrete' },
                  { value: 'numerical', label: '数值 numerical' },
                ]}
                onChange={(value) => patchGraphNodeConfig(node.id, ['attribute', 'value_type'], value || 'discrete')}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <Select
                label="模态 modality"
                value={String(config.attribute?.modality || 'internal')}
                data={[
                  { value: 'internal', label: '内部 internal' },
                  { value: 'external', label: '外部 external' },
                ]}
                onChange={(value) => patchGraphNodeConfig(node.id, ['attribute', 'modality'], value || 'internal')}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="属性 ER" value={toText(config.attribute?.er, '0')} onChange={(event) => patchGraphNodeConfig(node.id, ['attribute', 'er'], toNumberOrText(event.currentTarget.value))} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="属性 EV" value={toText(config.attribute?.ev, '0')} onChange={(event) => patchGraphNodeConfig(node.id, ['attribute', 'ev'], toNumberOrText(event.currentTarget.value))} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 4 }}>
              <TextInput label="原因 reason" value={toText(config.reason)} onChange={(event) => patchGraphNodeConfig(node.id, ['reason'], event.currentTarget.value)} />
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'action' && nodeType === 'delay' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12, md: 4 }}>
              <NumberInput label="延时 tick" value={Number(config.ticks ?? 1)} min={1} step={1} onChange={(value) => patchGraphNodeConfig(node.id, ['ticks'], Number(value) || 1)} />
            </Grid.Col>
            <Grid.Col span={{ base: 12 }}>
              <JsonInput
                label="延时后动作 then"
                description="高级子动作列表，格式与规则 then 一致。常用简单延时可保持默认日志，再从 JSON 精修。"
                value={jsonPretty(asArray(config.then))}
                onChange={(value) => {
                  try {
                    const parsed = JSON.parse(value || '[]');
                    patchGraphNodeConfig(node.id, ['then'], Array.isArray(parsed) ? parsed : []);
                  } catch {
                    // Mantine JsonInput already shows validation error; keep last valid graph state.
                  }
                }}
                autosize
                minRows={4}
                maxRows={10}
                validationError="JSON 格式不正确"
              />
            </Grid.Col>
          </Grid>
        ) : null}

        {nodeKind === 'action' && nodeType === 'branch' ? (
          <Grid mt="xs">
            <Grid.Col span={{ base: 12 }}>
              <Text size="xs" c="dimmed">
                分支是“动作内控制流”：先判断 branch.when，满足走 then，不满足走 else，条件报错走 on_error。当前表单给出常用说明，复杂分支可在下方高级 JSON 中编辑。
              </Text>
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 6 }}>
              <Select
                label="分支指标预设"
                searchable
                value={selectValueOrNone(config.when?.metric?.preset)}
                data={metricOptions}
                onChange={(value) => patchGraphNodeConfig(node.id, ['when', 'metric', 'preset'], noneToEmpty(value))}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <Select label="比较符" value={String(config.when?.metric?.op || '>')} data={COMPARE_OPTIONS} onChange={(value) => patchGraphNodeConfig(node.id, ['when', 'metric', 'op'], value || '>')} />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 3 }}>
              <TextInput label="阈值 value" value={toText(config.when?.metric?.value, '0')} onChange={(event) => patchGraphNodeConfig(node.id, ['when', 'metric', 'value'], toNumberOrText(event.currentTarget.value))} />
            </Grid.Col>
            {(['then', 'else', 'on_error'] as const).map((key) => (
              <Grid.Col span={{ base: 12, md: 4 }} key={key}>
                <JsonInput
                  label={`${key} 子动作`}
                  value={jsonPretty(asArray(config[key]))}
                  onChange={(value) => {
                    try {
                      const parsed = JSON.parse(value || '[]');
                      patchGraphNodeConfig(node.id, [key], Array.isArray(parsed) ? parsed : []);
                    } catch {
                      // Keep last valid state.
                    }
                  }}
                  autosize
                  minRows={5}
                  maxRows={9}
                  validationError="JSON 格式不正确"
                />
              </Grid.Col>
            ))}
          </Grid>
        ) : null}

        {nodeKind === 'action' && nodeType === 'log' ? (
          <Textarea
            mt="xs"
            label="日志内容"
            minRows={2}
            value={String((node.data.config as AnyRecord | undefined)?.log || '')}
            onChange={(event) => patchGraphNode(node.id, (current) => ({ ...current, data: { ...current.data, config: { log: event.currentTarget.value } } }))}
          />
        ) : null}

        <Divider my="sm" />
        <Group justify="space-between" align="center">
          <Text size="xs" c="dimmed">
            表单会实时改图形草稿；点“回写规则”才会写入当前规则的 when/then。
          </Text>
          <Button size="xs" variant="light" onClick={() => setGraphExpanded(true)} disabled={expanded}>
            放大编辑
          </Button>
        </Group>
      </Card>
    );
  }

  return (
    <div className="single-page rules-page">
      <Group justify="space-between" mb="md" align="flex-start">
        <div>
          <Title order={2}>先天规则编辑器</Title>
          <Text c="dimmed" size="sm">
            表单化规则草稿、YAML 高级通道、模拟运行和规则关系图集中在同一工作台；旧版前端仍保留在根路径。
          </Text>
        </div>
        <Group gap="xs">
          <Badge variant="light">{initialLoading ? '加载中' : `${formatCount(rules.length)} rules`}</Badge>
          {dirty ? <Badge color="yellow">草稿未保存</Badge> : <Badge color="teal">已同步文件</Badge>}
          <Tooltip label="刷新规则文件">
            <ActionIcon variant="light" loading={busy} onClick={() => refresh()}>
              <IconRefresh size={18} />
            </ActionIcon>
          </Tooltip>
          <Button variant="light" loading={busy} onClick={validateDoc}>
            校验草稿
          </Button>
          <Button loading={busy} onClick={saveDoc}>
            保存草稿
          </Button>
          <Button variant="light" leftSection={<IconPlayerPlay size={16} />} loading={busy} onClick={simulate}>
            模拟
          </Button>
        </Group>
      </Group>

      <FeedbackAlert feedback={feedback} />

      {initialLoading ? (
        <div style={{ marginTop: 16 }}>
          <LoadingPanel
            title="正在加载先天规则"
            description="正在读取 YAML、规范化规则、指标预设和规则关系图。加载完成前不会把 0 rules 当作真实规则数。"
            minHeight={240}
          />
        </div>
      ) : null}

      <Grid mt="md" style={{ opacity: initialLoading ? 0.45 : 1, pointerEvents: initialLoading ? 'none' : undefined }}>
        <Grid.Col span={{ base: 12, xl: 3 }}>
          <Stack>
            <Card className="control-card">
              <Text fw={800}>规则包</Text>
              <Text size="xs" c="dimmed" mb="sm">
                {bundle?.rules_path || '等待加载规则文件。'}
              </Text>
              <Grid>
                <Grid.Col span={6}>
                  <TextInput
                    label="schema"
                    value={String(doc.rules_schema_version || '')}
                    onChange={(event) => setDocField('rules_schema_version', event.currentTarget.value)}
                  />
                </Grid.Col>
                <Grid.Col span={6}>
                  <TextInput
                    label="rules version"
                    value={String(doc.rules_version || '')}
                    onChange={(event) => setDocField('rules_version', event.currentTarget.value)}
                  />
                </Grid.Col>
              </Grid>
              <Switch
                mt="sm"
                label="启用规则包"
                checked={doc.enabled !== false}
                onChange={(event) => setDocField('enabled', event.currentTarget.checked)}
              />
              <Group gap="xs" mt="sm">
                <Badge color={asArray(bundle?.errors).length ? 'red' : 'teal'}>
                  错误 {asArray(bundle?.errors).length}
                </Badge>
                <Badge color={asArray(bundle?.warnings).length ? 'yellow' : 'gray'}>
                  警告 {asArray(bundle?.warnings).length}
                </Badge>
                <Badge color={bundle?.rules_engine_enable ? 'teal' : 'red'}>
                  引擎 {bundle?.rules_engine_enable ? '启用' : '停用'}
                </Badge>
              </Group>
              <Group mt="sm" gap="xs">
                <Button size="xs" variant="light" onClick={reloadRules}>
                  重新加载
                </Button>
                <Button size="xs" variant="subtle" onClick={() => navigator.clipboard?.writeText(yaml)}>
                  复制 YAML
                </Button>
              </Group>
            </Card>

            <Card className="control-card">
              <Text fw={800} mb="sm">
                规则目录
              </Text>
              <TextInput
                placeholder="搜索 id / 标题 / 条件 / 动作"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
              />
              <Select
                mt="sm"
                searchable
                clearable={false}
                label="快速跳转到规则"
                value={selectedRule ? String(selectedRule.id || '') : ''}
                onChange={(value) => setSelectedId(value || '')}
                data={filteredRules.map((rule, index) => {
                  const rid = String(rule.id || `rule_${index + 1}`);
                  return {
                    value: rid,
                    label: `${rule.title || rid} | ${rid}`,
                  };
                })}
              />
              <Select
                mt="sm"
                value={filter}
                onChange={(value) => setFilter((value as RuleFilter) || 'all')}
                data={[
                  { value: 'all', label: '全部规则' },
                  { value: 'enabled', label: '仅启用' },
                  { value: 'disabled', label: '仅停用' },
                ]}
              />
              <Group gap="xs" mt="sm">
                <Button size="xs" leftSection={<IconPlus size={14} />} onClick={() => addTemplate('focus')}>
                  CFS 聚焦
                </Button>
                <Button size="xs" variant="light" onClick={() => addTemplate('window')}>
                  状态窗口
                </Button>
                <Button size="xs" variant="light" onClick={() => addTemplate('timer')}>
                  定时器
                </Button>
              </Group>
              <ScrollArea.Autosize mah="calc(100vh - 430px)" mt="sm">
                <Stack gap="xs">
                  {filteredRules.length ? (
                    filteredRules.map((rule, index) => {
                      const rid = String(rule.id || '');
                      const active = rid === String(selectedRule?.id || '');
                      return (
                        <Card
                          key={rid || `${rule.title || 'rule'}-${index}`}
                          className={`rule-list-item ${active ? 'active' : ''}`}
                          onClick={() => setSelectedId(rid)}
                          p="sm"
                        >
                          <Group justify="space-between" gap="xs">
                            <Text fw={800} size="sm">
                              {shortText(rule.title || rid || '-', 32)}
                            </Text>
                            <Badge color={rule.enabled === false ? 'gray' : 'teal'} variant="light">
                              {rule.enabled === false ? '停用' : '启用'}
                            </Badge>
                          </Group>
                          <Text size="xs" c="dimmed">
                            {rid || '-'} | 优先级 {rule.priority ?? 0}
                          </Text>
                          <Text size="xs" mt={4}>
                            {shortText(summarizeWhen(rule.when), 72)}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {shortText(summarizeThen(rule.then), 72)}
                          </Text>
                        </Card>
                      );
                    })
                  ) : (
                    <Text c="dimmed" size="sm">
                      没有符合筛选条件的规则。
                    </Text>
                  )}
                </Stack>
              </ScrollArea.Autosize>
            </Card>
          </Stack>
        </Grid.Col>

        <Grid.Col span={{ base: 12, xl: 5 }}>
          <Tabs defaultValue="editor" className="panel-tabs">
            <Tabs.List>
              <Tabs.Tab value="editor">规则草稿</Tabs.Tab>
              <Tabs.Tab value="yaml">YAML 高级</Tabs.Tab>
              <Tabs.Tab value="defaults">默认值/预设</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="editor" pt="md">
              {selectedRule ? (
                <Stack>
                  <Card className="editor-card">
                    <Group justify="space-between" align="flex-start" mb="sm">
                      <div>
                        <Text fw={800}>{selectedRule.title || selectedRule.id || '未命名规则'}</Text>
                        <Text size="xs" c="dimmed">
                          {selectedRule.id || '-'} | {summarizeWhen(selectedRule.when)}
                        </Text>
                      </div>
                      <Group gap="xs">
                        <Tooltip label="复制规则">
                          <ActionIcon variant="light" onClick={duplicateRule}>
                            <IconCopy size={16} />
                          </ActionIcon>
                        </Tooltip>
                        <Tooltip label="删除规则">
                          <ActionIcon color="red" variant="light" onClick={deleteRule}>
                            <IconTrash size={16} />
                          </ActionIcon>
                        </Tooltip>
                      </Group>
                    </Group>
                    <Grid>
                      <Grid.Col span={{ base: 12, md: 6 }}>
                        <TextInput
                          label="规则 ID"
                          value={String(selectedRule.id || '')}
                          onChange={(event) => {
                            const oldId = String(selectedRule.id || '');
                            const nextId = event.currentTarget.value;
                            updateDoc((next) => {
                              const idx = asArray<AnyRecord>(next.rules).findIndex((rule) => String(rule.id || '') === oldId);
                              if (idx >= 0) next.rules[idx].id = nextId;
                            }, nextId);
                          }}
                        />
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, md: 6 }}>
                        <TextInput
                          label="标题"
                          value={String(selectedRule.title || '')}
                          onChange={(event) => updateSelectedRule((rule) => { rule.title = event.currentTarget.value; })}
                        />
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, md: 4 }}>
                        <Switch
                          mt={28}
                          label="启用"
                          checked={selectedRule.enabled !== false}
                          onChange={(event) => updateSelectedRule((rule) => { rule.enabled = event.currentTarget.checked; })}
                        />
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, md: 4 }}>
                        <NumberInput
                          label="优先级"
                          value={Number(selectedRule.priority ?? 0)}
                          onChange={(value) => updateSelectedRule((rule) => { rule.priority = Number(value) || 0; })}
                        />
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, md: 4 }}>
                        <NumberInput
                          label="冷却 tick"
                          value={Number(selectedRule.cooldown_ticks ?? 0)}
                          min={0}
                          onChange={(value) => updateSelectedRule((rule) => { rule.cooldown_ticks = Number(value) || 0; })}
                        />
                      </Grid.Col>
                    </Grid>
                    <Textarea
                      mt="sm"
                      label="备注"
                      minRows={2}
                      value={String(selectedRule.note || '')}
                      onChange={(event) => updateSelectedRule((rule) => { rule.note = event.currentTarget.value; })}
                    />
                    <Divider my="sm" />
                    <Text size="xs" c="dimmed">
                      快捷字段会立即改动左侧规则草稿；复杂条件和动作可在下方 JSON 中编辑后点“应用 JSON”。
                    </Text>
                  </Card>

                  <Card className="editor-card">
                    <Group justify="space-between" mb="sm">
                      <Text fw={800}>选中规则 JSON</Text>
                      <Button size="xs" variant="light" onClick={applyRuleDraft}>
                        应用 JSON
                      </Button>
                    </Group>
                    <JsonInput
                      value={ruleDraft}
                      onChange={setRuleDraft}
                      autosize
                      minRows={18}
                      maxRows={28}
                      validationError="JSON 格式不正确"
                      formatOnBlur
                    />
                  </Card>
                </Stack>
              ) : (
                <Card>
                  <Text c="dimmed">请选择或新建一条规则。</Text>
                </Card>
              )}
            </Tabs.Panel>

            <Tabs.Panel value="yaml" pt="md">
              <Card className="editor-card">
                <Group justify="space-between" mb="sm">
                  <div>
                    <Text fw={800}>YAML 文件 / 导入区</Text>
                    <Text size="xs" c="dimmed">
                      校验草稿会刷新这里的规范化 YAML 预览；导入 YAML 会覆盖左侧规则草稿。
                    </Text>
                  </div>
                  <Group gap="xs">
                    <Button size="xs" variant="light" onClick={() => validateYaml(false)}>
                      校验 YAML
                    </Button>
                    <Button size="xs" variant="light" onClick={() => validateYaml(true)}>
                      导入到草稿
                    </Button>
                    <Button size="xs" color="red" variant="subtle" onClick={saveYaml}>
                      按 YAML 保存
                    </Button>
                  </Group>
                </Group>
                <Editor
                  height="calc(100vh - 285px)"
                  defaultLanguage="yaml"
                  theme="vs-dark"
                  value={yaml}
                  onChange={(value) => setYaml(value || '')}
                  options={{ minimap: { enabled: false }, fontSize: 13, wordWrap: 'on', scrollBeyondLastLine: false }}
                />
              </Card>
            </Tabs.Panel>

            <Tabs.Panel value="defaults" pt="md">
              <Stack>
                <JsonInspector value={doc.defaults || {}} title="规则默认值 defaults" maxHeight={260} />
                <JsonInspector value={bundle?.metric_presets || []} title={`指标预设 metric_presets (${formatCount(asArray(bundle?.metric_presets).length)})`} maxHeight={360} />
              </Stack>
            </Tabs.Panel>
          </Tabs>
        </Grid.Col>

        <Grid.Col span={{ base: 12, xl: 4 }}>
          <Stack>
            <Card className="control-card">
              <Group justify="space-between" mb="sm" align="flex-start">
                <div>
                  <Text fw={800}>选中规则图形草稿</Text>
                  <Text size="xs" c="dimmed">
                    左侧为条件，中心为汇总模式，右侧为动作；拖动或编辑节点后点“回写规则”。删除按钮只有选中非 root 节点时才会启用。
                  </Text>
                </div>
                <Group gap="xs">
                  {graphDirty ? <Badge color="yellow">图已改动</Badge> : <Badge color="teal">图已同步</Badge>}
                  <Button size="xs" variant="light" onClick={() => setGraphExpanded(true)}>
                    放大编辑区
                  </Button>
                  <Button size="xs" variant="light" onClick={applyGraphToRule}>
                    回写规则
                  </Button>
                </Group>
              </Group>
              {renderGraphPalette(true)}
              <div className="flow-card rule-editor-flow">
                <ReactFlow
                  nodes={graphNodes}
                  edges={graphEdges}
                  fitView
                  onNodesChange={onGraphNodesChange}
                  onEdgesChange={onGraphEdgesChange}
                  onConnect={onGraphConnect}
                  onNodeClick={(_, node) => selectGraphNode(node.id)}
                  onNodeDoubleClick={(_, node) => selectGraphNode(node.id, true)}
                  onNodeContextMenu={(event, node) => {
                    event.preventDefault();
                    selectGraphNode(node.id, true);
                  }}
                >
                  <MiniMap />
                  <Controls />
                  <Background />
                </ReactFlow>
              </div>
              <Group mt="sm" justify="space-between">
                <Text size="xs" c="dimmed">
                  当前节点：{selectedGraphNodeId || '未选择'}
                </Text>
                <Text size="xs" c="dimmed">
                  左键选择，双击或右键节点可打开放大编辑区；下方表单可直接改常用参数。
                </Text>
              </Group>
              {renderGraphNodeEditor(false)}
              <Divider my="sm" />
              <Text fw={800} size="sm">高级节点 JSON</Text>
              <Text size="xs" c="dimmed">
                常用字段请优先用上面的中文表单；这里保留给复杂嵌套规则和未表单化字段。
              </Text>
              <JsonInput
                mt="xs"
                value={graphNodeDraft}
                onChange={setGraphNodeDraft}
                autosize
                minRows={4}
                maxRows={8}
                validationError="JSON 格式不正确"
                placeholder="点击图中节点后编辑 node_type/config"
              />
              <Group mt="sm">
                <Button size="xs" variant="light" disabled={!selectedGraphNodeId} onClick={applyGraphNodeDraft}>
                  应用节点 JSON
                </Button>
              </Group>
            </Card>

            <Card className="flow-card rules-flow-card">
              <ReactFlow nodes={graph.nodes} edges={graph.edges} fitView>
                <MiniMap />
                <Controls />
                <Background />
              </ReactFlow>
            </Card>
            <Card className="control-card">
              <Group justify="space-between" mb="xs">
                <Text fw={800}>操作结果</Text>
                <Badge variant="light">{result ? 'latest' : 'idle'}</Badge>
              </Group>
              <Text size="sm" c={result ? undefined : 'dimmed'}>
                {resultSummary(result)}
              </Text>
              <Divider my="sm" />
              <JsonInspector value={result || bundle || doc} title={result ? 'Result JSON' : 'Rules Bundle'} maxHeight={360} />
            </Card>
            <Card className="control-card">
              <Group gap="xs" mb="sm">
                <IconGitBranch size={16} />
                <Text fw={800}>迁移对齐</Text>
              </Group>
              <Text size="xs" c="dimmed">
                已覆盖旧前端的刷新、模板新增、表单草稿、YAML 导入/导出、校验、保存热加载、dry-run 模拟和图形规则主路径编辑。复杂规则仍可随时用 JSON/YAML 兜底。
              </Text>
            </Card>
          </Stack>
        </Grid.Col>
      </Grid>

      <Drawer
        opened={graphExpanded}
        onClose={() => setGraphExpanded(false)}
        position="right"
        size="92vw"
        title="图形规则编辑工作台"
      >
        <Stack>
          <Card className="soft-note-card">
            <Group justify="space-between" align="flex-start">
              <div>
                <Text fw={800}>{selectedRule?.title || selectedRule?.id || '未选择规则'}</Text>
                <Text size="xs" c="dimmed">
                  {selectedRule ? `${selectedRule.id || '-'} | ${summarizeWhen(selectedRule.when)}` : '请先在左侧目录选择一条规则。'}
                </Text>
              </div>
              <Group gap="xs">
                {graphDirty ? <Badge color="yellow">图已改动</Badge> : <Badge color="teal">图已同步</Badge>}
                <Button size="xs" variant="light" onClick={applyGraphToRule}>
                  回写规则
                </Button>
              </Group>
            </Group>
          </Card>
          {renderGraphHowTo()}
          <Card className="control-card">
            {renderGraphPalette(false)}
            <Divider my="sm" />
            <div className="flow-card rule-editor-flow rule-editor-flow-expanded">
              <ReactFlow
                nodes={graphNodes}
                edges={graphEdges}
                fitView
                onNodesChange={onGraphNodesChange}
                onEdgesChange={onGraphEdgesChange}
                onConnect={onGraphConnect}
                onNodeClick={(_, node) => selectGraphNode(node.id)}
                onNodeDoubleClick={(_, node) => selectGraphNode(node.id, true)}
                onNodeContextMenu={(event, node) => {
                  event.preventDefault();
                  selectGraphNode(node.id, true);
                }}
              >
                <MiniMap />
                <Controls />
                <Background />
              </ReactFlow>
            </div>
            <Group mt="sm" justify="space-between">
              <Text size="xs" c="dimmed">
                当前节点：{selectedGraphNodeId || '未选择'}
              </Text>
              <Text size="xs" c="dimmed">
                放大模式适合做长链条件和多动作规则；右侧/下方表单改完后回写规则，再做一次“校验草稿”。
              </Text>
            </Group>
            {renderGraphNodeEditor(true)}
            <Divider my="sm" />
            <Text fw={800} size="sm">高级节点 JSON</Text>
            <Text size="xs" c="dimmed">
              复杂字段可在这里精修；普通阈值、增益、通道和行动字段建议用上面的中文表单。
            </Text>
            <JsonInput
              mt="xs"
              value={graphNodeDraft}
              onChange={setGraphNodeDraft}
              autosize
              minRows={6}
              maxRows={12}
              validationError="JSON 格式不正确"
              placeholder="点击图中节点后编辑 node_type/config"
            />
            <Group mt="sm">
              <Button size="xs" variant="light" disabled={!selectedGraphNodeId} onClick={applyGraphNodeDraft}>
                应用节点 JSON
              </Button>
            </Group>
          </Card>
        </Stack>
      </Drawer>
    </div>
  );
}
