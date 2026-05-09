import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Divider,
  Grid,
  Group,
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
import { useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import {
  IconBolt,
  IconDatabase,
  IconPlayerPlay,
  IconRefresh,
  IconReload,
  IconSearch,
  IconTrash,
} from '@tabler/icons-react';
import { api } from '../lib/api';
import type { AnyRecord, DashboardData } from '../types/api';
import { asArray, asNumber, formatCount, formatDuration, formatNumber, pick, shortDisplayText, shortText } from '../lib/format';
import { MetricCard } from '../components/MetricCard';
import { VirtualDataTable } from '../components/VirtualDataTable';
import { JsonInspector } from '../components/JsonInspector';
import { ConfigMiniEditor } from '../components/ConfigMiniEditor';
import { FeedbackAlert, type FeedbackState } from '../components/FeedbackAlert';
import { AggregateDetail } from '../components/AggregateDetail';
import { aggregateRowsByDisplay, type DisplayAggregateRow } from '../lib/displayAggregation';
import { ObjectDetail } from '../components/ObjectDetail';
import {
  EmotionRuntimeSummary,
  MemoryRuntimeSummary,
  SensorRuntimeSummary,
  TimeRuntimeSummary,
  TimingSummary,
} from '../components/FriendlySummary';
import { LoadingPanel } from '../components/LoadingPanel';

type DashboardPageProps = {
  onStatusChange?: (status: string) => void;
};

function stateItemsFrom(data: DashboardData | null): AnyRecord[] {
  const snapshot = pick(data, ['state_snapshot', 'state.snapshot', 'state.state_snapshot', 'last_report.final_state.state_snapshot'], {});
  return asArray(snapshot?.top_items || snapshot?.items || snapshot?.state_items);
}

function hdbItemsFrom(data: DashboardData | null): AnyRecord[] {
  const snapshot = pick(data, ['hdb_snapshot', 'hdb.snapshot', 'hdb.hdb_snapshot', 'last_report.final_state.hdb_snapshot'], {});
  return asArray(snapshot?.top_structures || snapshot?.recent_structures || snapshot?.structures || snapshot?.items);
}

function actionNodesFrom(actionRuntime: AnyRecord | null): AnyRecord[] {
  return asArray(actionRuntime?.nodes || actionRuntime?.action_nodes || actionRuntime?.items);
}

function actionExecutorsFrom(actionRuntime: AnyRecord | null): AnyRecord[] {
  return asArray(actionRuntime?.executors_registry || actionRuntime?.executors);
}

function flowStepsFrom(data: DashboardData | null): AnyRecord[] {
  const timing = pick(data, ['last_report.timing.steps_ms', 'last_report.timing', 'timing.steps_ms', 'timing'], {});
  if (!timing || typeof timing !== 'object') return [];
  return Object.entries(timing)
    .filter(([, value]) => typeof value === 'number')
    .map(([key, value]) => ({ key, value }));
}

function latestReportFrom(data: DashboardData | null): AnyRecord {
  return (data?.last_report || data?.report || data || {}) as AnyRecord;
}

function flowStageCardsFrom(report: AnyRecord): AnyRecord[] {
  const timing = report.timing || {};
  const timeOf = (...keys: string[]) => {
    for (const key of keys) {
      const value = timing.steps_ms?.[key] ?? timing[key];
      if (Number.isFinite(Number(value))) return Number(value);
    }
    return undefined;
  };
  const sensor = report.sensor || report.text_sensor || {};
  const maintenance = report.maintenance || report.state_pool_maintenance || {};
  const attention = report.attention || {};
  const structureLevel = report.structure_level?.result || report.structure_level || {};
  const stimulusLevel = report.stimulus_level?.result || report.stimulus_level || {};
  const cache = report.cache_neutralization || report.priority_neutralization || {};
  const merged = report.merged_stimulus || report.full_stimulus || {};
  const stitching = report.cognitive_stitching || {};
  const induction = report.induction || {};
  const memoryFeedback = report.memory_feedback || report.memory_activation?.feedback_result || {};
  const cfs = report.cognitive_feeling || {};
  const innate = report.innate_script?.focus || report.innate_script || {};
  const emotion = report.emotion || {};
  const action = report.action || {};

  return [
    {
      stage: '状态池维护',
      description: '衰减、中和、淘汰、合并与软容量压力。',
      duration_ms: timeOf('maintenance_ms', 'timing_maintenance_ms', 'state_pool_maintenance_ms'),
      main_value: `${formatCount(maintenance.before_summary?.active_item_count)} -> ${formatCount(maintenance.after_summary?.active_item_count)}`,
      sub_value: `衰减 ${formatCount(maintenance.summary?.decayed_item_count)} / 中和 ${formatCount(maintenance.summary?.neutralized_item_count)} / 淘汰 ${formatCount(maintenance.summary?.pruned_item_count)}`,
      detail: maintenance,
    },
    {
      stage: '传感器与外源刺激',
      description: '文本感受器、属性刺激元、回声/残响与刺激组。',
      duration_ms: timeOf('sensor_ms', 'timing_sensor_ms', 'text_sensor_ms'),
      main_value: `SA ${formatCount(sensor.sa_count ?? asArray(sensor.units || sensor.feature_units).length)}`,
      sub_value: `组 ${formatCount(asArray(sensor.groups || sensor.stimulus_groups).length)} / 属性 ${formatCount(sensor.attribute_sa_count)}`,
      detail: sensor,
    },
    {
      stage: '注意力滤波',
      description: 'CAM 候选、聚焦、抑制/增益和注意力能量预算。',
      duration_ms: timeOf('attention_ms', 'timing_attention_ms'),
      main_value: `${formatCount(attention.state_pool_candidate_count)} -> ${formatCount(attention.memory_item_count ?? attention.cam_item_count)}`,
      sub_value: `预算 ${formatNumber(attention.energy_budget ?? attention.attention_energy_budget, 3)} / 净增 ${formatNumber(attention.net_delta_energy ?? attention.attention_net_delta_energy, 3)}`,
      detail: attention,
    },
    {
      stage: '结构级查存一体',
      description: '结构对象进入局部库竞争、命中结构组并生成内源片段。',
      duration_ms: timeOf('structure_level_ms', 'timing_structure_level_ms'),
      main_value: `轮次 ${formatCount(structureLevel.round_count)}`,
      sub_value: `命中 ${formatCount(asArray(structureLevel.matched_group_ids).length)} / 新建 ${formatCount(asArray(structureLevel.new_group_ids).length)}`,
      detail: structureLevel,
    },
    {
      stage: '完整刺激合流',
      description: '外源与内源在刺激流合并，形成刺激级查存输入。',
      duration_ms: timeOf('merge_stimulus_ms', 'timing_merge_stimulus_ms'),
      main_value: shortDisplayText(merged.display_text || merged.grouped_display_text || '空', 28),
      sub_value: `组 ${formatCount(merged.group_count ?? asArray(merged.groups).length)} / 单元 ${formatCount(merged.unit_count ?? merged.feature_unit_count ?? asArray(merged.feature_units).length)} / ER ${formatNumber(merged.total_er, 3)} / EV ${formatNumber(merged.total_ev, 3)}`,
      detail: merged,
    },
    {
      stage: '缓存中和',
      description: '优先用刺激流降低状态池认知压，再交给查存一体。',
      duration_ms: timeOf('cache_neutralization_ms', 'timing_cache_neutralization_ms'),
      main_value: `事件 ${formatCount(asArray(cache.priority_events || cache.events).length)}`,
      sub_value: `ER ${formatNumber(cache.priority_summary?.consumed_er, 3)} / EV ${formatNumber(cache.priority_summary?.consumed_ev, 3)} / 缺口 ${formatNumber(cache.priority_summary?.shortfall_ev ?? cache.priority_summary?.shortfall_er, 3)}`,
      detail: cache,
    },
    {
      stage: '刺激级查存一体',
      description: '按锚点和局部组做刺激级软匹配、切割与存储。',
      duration_ms: timeOf('stimulus_level_ms', 'timing_stimulus_level_ms'),
      main_value: `轮次 ${formatCount(stimulusLevel.round_count)}`,
      sub_value: `命中 ${formatCount(asArray(stimulusLevel.matched_structure_ids).length)} / 新建 ${formatCount(asArray(stimulusLevel.new_structure_ids).length)} / 剩余 ${formatCount(stimulusLevel.remaining_stimulus_sa_count)}`,
      detail: stimulusLevel,
    },
    {
      stage: 'CS 回滚诊断',
      description: '默认 growth 主链下通常关闭；仅用于 residual/CS 对照或旧事件整理诊断。',
      duration_ms: timeOf('cognitive_stitching_ms', 'timing_cognitive_stitching_ms'),
      main_value: `${formatCount(stitching.candidate_count)} / ${formatCount(stitching.action_count)}`,
      sub_value: `诊断动作 ${formatCount(stitching.concat_count)} / 新建 ${formatCount(stitching.created_count)} / 强化 ${formatCount(stitching.reinforced_count)}`,
      detail: stitching,
    },
    {
      stage: '感应赋能与记忆回馈',
      description: 'EV 局部传播、ER 诱发 EV，并处理兼容记忆回馈。',
      duration_ms: timeOf('induction_ms', 'timing_induction_ms', 'memory_feedback_ms', 'timing_memory_feedback_ms'),
      main_value: `ΔEV ${formatNumber(induction.total_delta_ev, 3)}`,
      sub_value: `源 ${formatCount(induction.source_item_count)} / 目标 ${formatCount(induction.target_count)} / 回馈 ${formatCount(memoryFeedback.applied_count)}`,
      detail: { induction, memory_feedback: memoryFeedback },
    },
    {
      stage: 'CFS / IESM',
      description: '认知感受生成、先天规则触发、聚焦/行动/情绪更新。',
      duration_ms: timeOf('cognitive_feeling_ms', 'timing_cognitive_feeling_ms', 'innate_script_ms', 'timing_iesm_ms'),
      main_value: `CFS ${formatCount(asArray(cfs.signals || cfs.cfs_signals).length)}`,
      sub_value: `聚焦 ${formatCount(asArray(innate.focus_directives).length)} / 行动触发 ${formatCount(asArray(innate.action_triggers).length)} / 情绪更新 ${formatCount(Object.keys(innate.emotion_updates || {}).length)}`,
      detail: { cognitive_feeling: cfs, innate_script: innate },
    },
    {
      stage: '情绪与行动',
      description: 'NT 通道调制行动阈值、注意力资源与行动竞争。',
      duration_ms: timeOf('emotion_ms', 'timing_emotion_ms', 'action_ms', 'timing_action_ms'),
      main_value: `行动 ${formatCount(asArray(action.executed_actions).length)}`,
      sub_value: `NT ${formatCount(Object.keys(emotion.nt_state_after || emotion.nt_state_snapshot || {}).length)} / 触发 ${formatCount(asArray(action.triggers).length)}`,
      detail: { emotion, action },
    },
  ].filter((item) => item.detail && Object.keys(item.detail).length > 0);
}

function sensorUnitsFrom(report: AnyRecord): AnyRecord[] {
  const sensor = report.sensor || report.text_sensor || {};
  return asArray(sensor.units || sensor.feature_units || sensor.items);
}

function sensorGroupsFrom(report: AnyRecord): AnyRecord[] {
  const sensor = report.sensor || report.text_sensor || {};
  return asArray(sensor.groups || sensor.stimulus_groups || sensor.packet_groups);
}

function timeRowsFrom(report: AnyRecord): AnyRecord[] {
  const timeSensor = report.time_sensor || {};
  return [
    ...asArray(timeSensor.bucket_updates).map((item) => ({ ...item, row_kind: '时间桶' })),
    ...asArray(timeSensor.memory_rows).map((item) => ({ ...item, row_kind: '时间记忆' })),
    ...asArray(timeSensor.attribute_bindings).map((item) => ({ ...item, row_kind: '属性绑定' })),
    ...asArray(timeSensor.delayed_tasks).map((item) => ({ ...item, row_kind: '延迟任务' })),
  ];
}

function memoryRowsFrom(report: AnyRecord, hdbSnapshot: AnyRecord): AnyRecord[] {
  const activation = report.memory_activation || {};
  const feedback = report.memory_feedback || activation.feedback_result || {};
  const recent = asArray(hdbSnapshot?.recent_memory_activations).map((item) => ({ ...item, row_kind: '最近激活' }));
  const snapshotItems = asArray(activation.snapshot?.items || activation.snapshot?.top_items).map((item) => ({ ...item, row_kind: '激活快照' }));
  const feedbackItems = asArray(feedback.items).map((item) => ({ ...item, row_kind: '回馈' }));
  const seeds = asArray(activation.seed_targets).map((item) => ({ ...item, row_kind: '种子目标' }));
  return [...recent, ...snapshotItems, ...feedbackItems, ...seeds];
}

function recentCycleRowsFrom(data: DashboardData | null): AnyRecord[] {
  return asArray(data?.recent_cycles || data?.cycles || []);
}

function cfsRowsFrom(report: AnyRecord): AnyRecord[] {
  const cfs = report.cognitive_feeling || {};
  const focus = report.innate_script?.focus || {};
  return [
    ...asArray(cfs.signals || cfs.cfs_signals).map((item) => ({ ...item, row_kind: 'CFS 输出' })),
    ...asArray(cfs.attribute_bindings).map((item) => ({ ...item, row_kind: '属性写回' })),
    ...asArray(focus.cfs_signals).map((item) => ({ ...item, row_kind: 'IESM 输入' })),
    ...asArray(focus.focus_directives).map((item) => ({ ...item, row_kind: '聚焦指令' })),
  ];
}

function ntRowsFrom(report: AnyRecord): AnyRecord[] {
  const emotion = report.emotion || {};
  const before = emotion.nt_state_before || {};
  const after = emotion.nt_state_after || emotion.nt_state_snapshot || {};
  const labels = emotion.nt_channel_labels || {};
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after), ...Object.keys(labels)]));
  return keys.map((key) => ({
    channel: key,
    label: labels[key] || emotion.nt_channel_meta?.[key]?.label_zh || key,
    before: before[key],
    after: after[key],
    delta: Number(after[key] ?? 0) - Number(before[key] ?? 0),
  }));
}

function executedActionRowsFrom(report: AnyRecord): AnyRecord[] {
  const action = report.action || {};
  return [
    ...asArray(action.executed_actions).map((item) => ({ ...item, row_kind: '已执行' })),
    ...asArray(action.triggers).map((item) => ({ ...item, row_kind: '触发' })),
    ...asArray(action.focus_directives_out).map((item) => ({ ...item, row_kind: '聚焦输出' })),
    ...asArray(action.recall_requests_out).map((item) => ({ ...item, row_kind: '回忆请求' })),
  ];
}

function actionKindLabel(value: AnyRecord): string {
  const key = String(value.action_kind || value.kind || value.action_id || '').trim();
  const map: Record<string, string> = {
    attention_focus_mode: '注意力聚焦模式',
    attention_diverge_mode: '注意力发散模式',
    recall: '回忆',
    dissonance: '违和感',
    correctness: '正确感',
    expectation: '期待',
    pressure: '压力',
    complexity: '繁简感受',
    weather_stub: '天气动作桩',
    teacher_reward_stub: '教师奖励动作桩',
    teacher_punish_stub: '教师惩罚动作桩',
  };
  return map[key] || key || '未命名行动';
}

function actionKindDescription(value: AnyRecord): string {
  const key = String(value.action_kind || value.kind || value.action_id || '').trim();
  const map: Record<string, string> = {
    attention_focus_mode: '让注意力更收束，把更多有限注意资源分给少数高优先对象。',
    attention_diverge_mode: '让注意力更发散，扩大候选范围，避免长期死盯单一对象。',
    recall: '触发回忆接口，把相关记忆重新带回当前运行态竞争。',
    weather_stub: '实验用天气行动桩，用于验证行动学习、教师反馈与奖惩联动链路。',
    teacher_reward_stub: '实验用奖励反馈桩，模拟外部教师给出正反馈。',
    teacher_punish_stub: '实验用惩罚反馈桩，模拟外部教师给出负反馈。',
  };
  return map[key] || String(value.description || value.title || '当前没有额外解释。');
}

function rowIdentity(row: AnyRecord): string {
  return String(
    row.aggregate_key ||
      row.item_id ||
      row.ref_object_id ||
      row.structure_id ||
      row.group_id ||
      row.action_id ||
      row.id ||
      row.display ||
      '',
  );
}

export function DashboardPage({ onStatusChange }: DashboardPageProps) {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [stateSnapshotWide, setStateSnapshotWide] = useState<AnyRecord | null>(null);
  const [actionRuntime, setActionRuntime] = useState<AnyRecord | null>(null);
  const [configBundle, setConfigBundle] = useState<AnyRecord | null>(null);
  const [selected, setSelected] = useState<AnyRecord | null>(null);
  const [selectedKey, setSelectedKey] = useState('');
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  const [maintenanceTarget, setMaintenanceTarget] = useState('');
  const [repairJobId, setRepairJobId] = useState('');
  const [idleMode, setIdleMode] = useState<'light' | 'full'>('light');
  const [idleBatchLimit, setIdleBatchLimit] = useState<number | ''>(256);
  const [idleMaxCsEvents, setIdleMaxCsEvents] = useState<number | ''>(128);
  const [maintenanceJobs, setMaintenanceJobs] = useState<AnyRecord[]>([]);
  const [actionStopMode, setActionStopMode] = useState('action_kind');
  const [actionStopValue, setActionStopValue] = useState('');
  const [actionStopHoldTicks, setActionStopHoldTicks] = useState(2);
  const [actionStopReason, setActionStopReason] = useState('manual_stop');
  const [pipelineDraft, setPipelineDraft] = useState({
    enable_cognitive_stitching: false,
    enable_structure_level_retrieval_storage: false,
    enable_goal_b_char_sa_string_mode: false,
    enable_energy_balance: false,
    enable_delayed_tasks: false,
  });
  const [busy, setBusy] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);
  const [inputText, setInputText] = useState('');
  const [tickCount, setTickCount] = useState(1);
  const [queryMode, setQueryMode] = useState<'structure' | 'group' | 'episodic'>('structure');
  const [queryValue, setQueryValue] = useState('');
  const [aggregateStateTop, setAggregateStateTop] = useState(true);
  const [stateTopN, setStateTopN] = useState<number | ''>(20);
  const [refreshMs, setRefreshMs] = useState<number | ''>(750);
  const [autoRefresh, setAutoRefresh] = useState(true);

  async function refresh(silent = false) {
    if (!silent) setBusy(true);
    try {
      const [dash, runtime, stateWide] = await Promise.all([
        api.dashboard(false),
        api.actionRuntime().catch(() => null),
        api.state(260).catch(() => null),
      ]);
      setDashboard(dash);
      setStateSnapshotWide((stateWide as AnyRecord | null)?.snapshot || null);
      setActionRuntime(runtime as AnyRecord | null);
      if (dash?.module_configs) setConfigBundle(dash.module_configs);
      onStatusChange?.(`tick ${dash?.tick_counter ?? dash?.meta?.tick_counter ?? '-'}`);
    } finally {
      if (!silent) setBusy(false);
      if (!silent) setInitialLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    refresh(true)
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setInitialLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const timer = window.setInterval(() => refresh(true).catch(() => undefined), Math.max(250, Number(refreshMs) || 750));
    return () => window.clearInterval(timer);
  }, [autoRefresh, refreshMs]);

  async function refreshMaintenanceJobs() {
    const payload = await api.maintenanceJobs();
    setMaintenanceJobs(asArray(payload?.jobs || payload?.items || payload));
  }

  useEffect(() => {
    refreshMaintenanceJobs().catch(() => undefined);
    const timer = window.setInterval(() => refreshMaintenanceJobs().catch(() => undefined), Math.max(750, Math.min(5000, Number(refreshMs) || 1000)));
    return () => window.clearInterval(timer);
  }, [refreshMs]);

  const stateItems = useMemo(() => asArray(stateSnapshotWide?.top_items).length ? asArray(stateSnapshotWide?.top_items) : stateItemsFrom(dashboard), [dashboard, stateSnapshotWide]);
  const displayedStateItems = useMemo(
    () => aggregateRowsByDisplay(stateItems, {
      enabled: aggregateStateTop,
      topN: Number(stateTopN) || 20,
      mode: 'display',
      rowKind: '状态池结构波峰',
      hideAtomicFeatureSa: true,
    }),
    [aggregateStateTop, stateItems, stateTopN],
  );
  const hdbItems = useMemo(() => hdbItemsFrom(dashboard), [dashboard]);
  const actionNodes = useMemo(() => actionNodesFrom(actionRuntime), [actionRuntime]);
  const actionExecutors = useMemo(() => actionExecutorsFrom(actionRuntime), [actionRuntime]);
  const flowSteps = useMemo(() => flowStepsFrom(dashboard), [dashboard]);

  const summary = pick(dashboard, ['state_snapshot.summary', 'state.snapshot.summary', 'state.state_snapshot.summary', 'last_report.final_state.state_snapshot.summary'], {});
  const hdbSummary = pick(dashboard, ['hdb_snapshot.summary', 'hdb.snapshot.summary', 'hdb.hdb_snapshot.summary', 'last_report.final_state.hdb_snapshot.summary'], {});
  const lastReport = latestReportFrom(dashboard);
  const hdbSnapshot = dashboard?.hdb_snapshot || {};
  const repairJobs = maintenanceJobs.length ? maintenanceJobs : asArray(hdbSnapshot?.repair_jobs);
  const hdbIssues = asArray(hdbSnapshot?.issues || hdbSnapshot?.recent_issues);
  const sensorUnits = useMemo(() => sensorUnitsFrom(lastReport), [lastReport]);
  const sensorGroups = useMemo(() => sensorGroupsFrom(lastReport), [lastReport]);
  const timeRows = useMemo(() => timeRowsFrom(lastReport), [lastReport]);
  const memoryRows = useMemo(() => memoryRowsFrom(lastReport, hdbSnapshot), [lastReport, hdbSnapshot]);
  const recentCycles = useMemo(() => recentCycleRowsFrom(dashboard), [dashboard]);
  const cfsRows = useMemo(() => cfsRowsFrom(lastReport), [lastReport]);
  const ntRows = useMemo(() => ntRowsFrom(lastReport), [lastReport]);
  const executedActionRows = useMemo(() => executedActionRowsFrom(lastReport), [lastReport]);
  const flowStageCards = useMemo(() => flowStageCardsFrom(lastReport), [lastReport]);

  useEffect(() => {
    const configs = dashboard?.module_configs || configBundle || {};
    const observatory = configs?.observatory?.effective || {};
    const energyBalance = configs?.energy_balance?.effective || {};
    const timeSensor = configs?.time_sensor?.effective || {};
    setPipelineDraft({
      enable_cognitive_stitching: Boolean(observatory.enable_cognitive_stitching),
      enable_structure_level_retrieval_storage: Boolean(observatory.enable_structure_level_retrieval_storage),
      enable_goal_b_char_sa_string_mode: Boolean(observatory.enable_goal_b_char_sa_string_mode),
      enable_energy_balance: Boolean(energyBalance.enabled),
      enable_delayed_tasks: Boolean(timeSensor.enable_delayed_tasks),
    });
  }, [dashboard, configBundle]);

  const stateColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      {
        header: '对象',
        cell: ({ row }) => (
          <div>
            <Text size="sm" fw={700}>
              {shortDisplayText(row.original.aggregate_display || row.original.display || row.original.ref_object_id || row.original.item_id, 34)}
            </Text>
            {row.original.__displayAggregate ? (
              <Text size="xs" c="dimmed">
                显示聚合：{formatCount(row.original.aggregate_component_count)} 个后端对象，按内容汇总
              </Text>
            ) : null}
          </div>
        ),
      },
      {
        header: '类型',
        cell: ({ row }) => row.original.__displayAggregate ? '显示聚合' : row.original.ref_object_type || row.original.object_type || '-',
      },
      { header: 'ER', cell: ({ row }) => formatNumber(row.original.aggregate_total_er ?? row.original.er ?? row.original.energy?.er, 4) },
      { header: 'EV', cell: ({ row }) => formatNumber(row.original.aggregate_total_ev ?? row.original.ev ?? row.original.energy?.ev, 4) },
      {
        header: '组分/激活',
        cell: ({ row }) => row.original.__displayAggregate
          ? `${formatCount(row.original.aggregate_component_count)} / ${shortDisplayText(row.original.aggregate_context_summary, 24)}`
          : shortDisplayText(row.original.context_summary || row.original.context_ref_object_id || row.original.growth_source || '-', 24),
      },
      { header: 'CP', cell: ({ row }) => formatNumber(row.original.cp_abs ?? row.original.energy?.cognitive_pressure_abs, 4) },
    ],
    [],
  );

  const hdbColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '结构', cell: ({ row }) => shortDisplayText(row.original.display || row.original.display_text || row.original.id, 38) },
      { header: '类型', cell: ({ row }) => row.original.object_type || row.original.sub_type || '-' },
      { header: '权重', cell: ({ row }) => formatNumber(row.original.weight ?? row.original.base_weight, 4) },
      { header: '激活审计', cell: ({ row }) => shortDisplayText(row.original.context_summary || row.original.context_id || row.original.growth_source || '-', 24) },
    ],
    [],
  );

  const actionColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      {
        header: '行动',
        cell: ({ row }) => (
          <div>
            <Text size="sm" fw={700}>
              {actionKindLabel(row.original)}
            </Text>
            <Text size="xs" c="dimmed">
              {shortText(String(row.original.action_kind || row.original.kind || row.original.action_id || '-'), 40)}
            </Text>
          </div>
        ),
      },
      { header: '驱动力', cell: ({ row }) => formatNumber(row.original.drive ?? row.original.current_drive, 4) },
      { header: '阈值', cell: ({ row }) => formatNumber(row.original.threshold ?? row.original.effective_threshold, 4) },
      { header: '状态', cell: ({ row }) => row.original.status || row.original.phase || '-' },
      { header: '作用解释', cell: ({ row }) => shortText(actionKindDescription(row.original), 42) },
    ],
    [],
  );

  const executorColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      {
        header: '行动器',
        cell: ({ row }) => (
          <div>
            <Text size="sm" fw={700}>{actionKindLabel(row.original)}</Text>
            <Text size="xs" c="dimmed">{shortText(String(row.original.action_kind || row.original.kind || '-'), 36)}</Text>
          </div>
        ),
      },
      { header: '状态', cell: ({ row }) => row.original.enabled === false ? '停用' : '启用' },
      { header: '描述', cell: ({ row }) => shortText(actionKindDescription(row.original), 42) },
    ],
    [],
  );

  const repairColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '任务', cell: ({ row }) => shortText(row.original.repair_job_id || row.original.job_id || '-', 30) },
      {
        header: '类型/状态',
        cell: ({ row }) => (
          <div>
            <Text size="sm" fw={700}>{row.original.scope || row.original.job_type || '维护任务'}</Text>
            <Text size="xs" c="dimmed">{row.original.status || '-'}</Text>
          </div>
        ),
      },
      { header: '目标', cell: ({ row }) => row.original.target_id || row.original.target || '全局' },
      {
        header: '进度',
        cell: ({ row }) => {
          const total = Number(row.original.issue_count || row.original.batch_limit || row.original.request?.batch_limit || 0);
          const processed = Number(row.original.processed_count || 0);
          const changed = Number(row.original.repaired_count || 0);
          const suffix = total > 0 ? ` / ${formatCount(total)}` : '';
          return `已扫 ${formatCount(processed)}${suffix}，更新 ${formatCount(changed)}`;
        },
      },
      { header: '错误', cell: ({ row }) => shortText(row.original.error || '-', 32) },
    ],
    [],
  );

  const issueColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '类型', cell: ({ row }) => row.original.type || row.original.kind || '-' },
      { header: '目标', cell: ({ row }) => shortText(row.original.target_id || '-', 28) },
      { header: '消息', cell: ({ row }) => shortText(row.original.message || row.original.reason || '-', 52) },
    ],
    [],
  );

  const sensorUnitColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: 'SA / 文本', cell: ({ row }) => shortDisplayText(row.original.display || row.original.text || row.original.value || row.original.sa_id || row.original.id, 36) },
      { header: '类型', cell: ({ row }) => row.original.sa_type || row.original.type || row.original.kind || '-' },
      { header: 'ER', cell: ({ row }) => formatNumber(row.original.er ?? row.original.energy?.er ?? row.original.stimulus_er, 4) },
      { header: 'EV', cell: ({ row }) => formatNumber(row.original.ev ?? row.original.energy?.ev ?? row.original.stimulus_ev, 4) },
      { header: '来源', cell: ({ row }) => shortText(row.original.source || row.original.origin || row.original.modality || '-', 18) },
    ],
    [],
  );

  const sensorGroupColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '组', cell: ({ row }) => shortDisplayText(row.original.display || row.original.text || row.original.group_text || row.original.group_id || '-', 42) },
      { header: '模式', cell: ({ row }) => row.original.mode || row.original.sequence_mode || row.original.group_type || '-' },
      { header: '数量', cell: ({ row }) => formatCount(row.original.unit_count ?? row.original.sa_count ?? asArray(row.original.units).length) },
      { header: 'ext', cell: ({ row }) => shortText(row.original.ext?.internal_merge_mode || row.original.ext?.source || row.original.source || '-', 24) },
    ],
    [],
  );

  const timeColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '类别', cell: ({ row }) => row.original.row_kind || '-' },
      { header: '对象', cell: ({ row }) => shortDisplayText(row.original.display || row.original.bucket_label || row.original.target_display || row.original.ref_object_id || row.original.task_id || '-', 42) },
      { header: '时间', cell: ({ row }) => row.original.time_basis || row.original.interval_label || row.original.delay_ticks || row.original.target_tick || '-' },
      { header: 'ER', cell: ({ row }) => formatNumber(row.original.er ?? row.original.energy_er ?? row.original.total_er, 4) },
      { header: 'EV', cell: ({ row }) => formatNumber(row.original.ev ?? row.original.energy_ev ?? row.original.total_ev, 4) },
    ],
    [],
  );

  const memoryColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '类别', cell: ({ row }) => row.original.row_kind || '-' },
      { header: '记忆/目标', cell: ({ row }) => shortDisplayText(row.original.display || row.original.memory_id || row.original.target_id || row.original.ref_object_id || '-', 42) },
      { header: '能量', cell: ({ row }) => formatNumber(row.original.energy ?? row.original.assigned_energy ?? row.original.feedback_energy ?? row.original.total_energy, 4) },
      { header: 'ER', cell: ({ row }) => formatNumber(row.original.er ?? row.original.total_er ?? row.original.feedback_er, 4) },
      { header: 'EV', cell: ({ row }) => formatNumber(row.original.ev ?? row.original.total_ev ?? row.original.feedback_ev, 4) },
    ],
    [],
  );

  const cycleColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: 'Tick', cell: ({ row }) => row.original.tick_counter ?? row.original.tick_id ?? '-' },
      { header: 'Trace', cell: ({ row }) => shortText(row.original.trace_id || '-', 32) },
      { header: '输入', cell: ({ row }) => shortText(row.original.input_text || row.original.input || '-', 40) },
      { header: '耗时', cell: ({ row }) => formatDuration(row.original.total_logic_ms ?? row.original.elapsed_ms ?? row.original.timing?.total_logic_ms) },
      { header: '状态', cell: ({ row }) => row.original.status || row.original.result || '-' },
    ],
    [],
  );

  const cfsColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '类别', cell: ({ row }) => row.original.row_kind || '-' },
      {
        header: '感受/动作',
        cell: ({ row }) => actionKindLabel(row.original) || row.original.kind || row.original.attribute_name || '-',
      },
      { header: '强度', cell: ({ row }) => formatNumber(row.original.strength ?? row.original.value ?? row.original.match_value, 4) },
      { header: '目标', cell: ({ row }) => shortText(row.original.target?.display || row.original.target_display || row.original.ref_object_id || row.original.target_ref_object_id || '-', 42) },
      { header: '规则', cell: ({ row }) => shortText(row.original.rule_title || row.original.rule_id || row.original.reason || '-', 38) },
    ],
    [],
  );

  const ntColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '通道', cell: ({ row }) => `${row.original.channel || '-'} ${row.original.label || ''}` },
      { header: 'Before', cell: ({ row }) => formatNumber(row.original.before, 4) },
      { header: 'After', cell: ({ row }) => formatNumber(row.original.after, 4) },
      { header: 'Delta', cell: ({ row }) => formatNumber(row.original.delta, 4) },
    ],
    [],
  );

  if (initialLoading) {
    return (
      <LoadingPanel
        title="实时观测台正在加载"
        description="正在读取最新 tick、状态池、HDB、行动节点和运行配置。"
        minHeight={320}
      />
    );
  }

  async function runCycle() {
    setBusy(true);
    try {
      const result = await api.runCycle(inputText);
      setDashboard((result as AnyRecord) || dashboard);
      setInputText('');
      await refresh(true);
    } finally {
      setBusy(false);
    }
  }

  async function runTicks() {
    setBusy(true);
    try {
      await api.runTicks(Math.max(1, Number(tickCount) || 1));
      await refresh(true);
    } finally {
      setBusy(false);
    }
  }

  async function query() {
    const value = queryValue.trim();
    setBusy(true);
    try {
      if (queryMode === 'structure') setSelected(await api.queryStructure(value));
      if (queryMode === 'group') setSelected(await api.queryGroup(value));
      if (queryMode === 'episodic') setSelected(await api.episodic(Number(value) || 20));
    } finally {
      setBusy(false);
    }
  }

  async function inspectHdbRow(row: AnyRecord) {
    setSelectedKey(rowIdentity(row));
    setSelected(row);
    const structureId =
      row.structure_id ||
      row.ref_object_id ||
      (String(row.object_type || row.ref_object_type || '').toLowerCase() === 'st' ? row.id : '') ||
      (String(row.id || '').startsWith('st_') ? row.id : '');
    const groupId =
      row.group_id ||
      (String(row.object_type || row.ref_object_type || '').toLowerCase() === 'sg' ? row.id : '') ||
      (String(row.id || '').startsWith('sg_') ? row.id : '');
    try {
      if (structureId) {
        setSelected((await api.queryStructure(String(structureId))) as AnyRecord);
        return;
      }
      if (groupId) {
        setSelected((await api.queryGroup(String(groupId))) as AnyRecord);
      }
    } catch (error) {
      setFeedback({ kind: 'warn', message: error instanceof Error ? error.message : String(error) });
    }
  }

  async function confirmedReset(label: string, action: () => Promise<unknown>) {
    const ok = window.confirm(`${label} 会修改本地观测台数据，是否继续？`);
    if (!ok) return;
    setBusy(true);
    try {
      await action();
      setSelected(null);
      setSelectedKey('');
      await refresh(true);
    } finally {
      setBusy(false);
    }
  }

  async function loadConfig() {
    setBusy(true);
    try {
      const bundle = await api.config();
      setConfigBundle(bundle);
      setFeedback({ kind: 'ok', message: '配置已刷新。' });
    } finally {
      setBusy(false);
    }
  }

  async function saveConfigModule(moduleName: string, values: AnyRecord) {
    if (!Object.keys(values).length) {
      setFeedback({ kind: 'info', message: '没有检测到配置改动。' });
      return;
    }
    const ok = window.confirm(`保存 ${moduleName} 的配置改动并热加载？`);
    if (!ok) return;
    setBusy(true);
    try {
      const result = await api.saveConfig(moduleName, values);
      setSelected(result);
      await api.reload().catch(() => null);
      await refresh(true);
      await loadConfig();
      setFeedback({ kind: 'ok', message: `${moduleName} 配置已保存并尝试热加载。` });
    } finally {
      setBusy(false);
    }
  }

  async function applyPipelineSwitches() {
    const ok = window.confirm('应用流程阶段开关会写入本地配置并热加载，是否继续？');
    if (!ok) return;
    setBusy(true);
    try {
      await api.saveConfig('observatory', {
        enable_cognitive_stitching: pipelineDraft.enable_cognitive_stitching,
        enable_structure_level_retrieval_storage: pipelineDraft.enable_structure_level_retrieval_storage,
        enable_goal_b_char_sa_string_mode: pipelineDraft.enable_goal_b_char_sa_string_mode,
      });
      await api.saveConfig('cognitive_stitching', { enabled: pipelineDraft.enable_cognitive_stitching }).catch(() => null);
      await api.saveConfig('energy_balance', { enabled: pipelineDraft.enable_energy_balance }).catch(() => null);
      await api.saveConfig('time_sensor', { enable_delayed_tasks: pipelineDraft.enable_delayed_tasks }).catch(() => null);
      await api.reload().catch(() => null);
      await refresh(true);
      setFeedback({ kind: 'ok', message: '流程阶段开关已保存并热加载。' });
    } finally {
      setBusy(false);
    }
  }

  async function runMaintenance(kind: 'check' | 'repair' | 'repair_all' | 'idle' | 'stop_repair') {
    setBusy(true);
    try {
      let result: unknown = null;
      if (kind === 'check') result = await api.checkHdb(maintenanceTarget.trim() || null);
      if (kind === 'repair') {
        if (!maintenanceTarget.trim()) throw new Error('请先填写修复目标 ID。');
        result = await api.repairHdb(maintenanceTarget.trim());
      }
      if (kind === 'repair_all') {
        if (!window.confirm('启动全局快速修复？该操作可能占用一段时间。')) return;
        result = await api.repairAllHdb();
      }
      if (kind === 'idle') {
        const fullMode = idleMode === 'full';
        if (fullMode && !window.confirm('完整闲时整理会扫描全部结构 DB 并重建指针索引，建议只在暂停实验后执行。继续吗？')) return;
        result = await api.idleConsolidate(true, {
          rebuild_pointer_index: fullMode,
          apply_soft_limits: true,
          batch_limit: fullMode ? null : Number(idleBatchLimit) || 256,
          max_cs_events: fullMode ? null : Number(idleMaxCsEvents) || 128,
          reason: fullMode ? 'web_manual_full_idle_consolidation' : 'web_manual_light_idle_consolidation',
        });
      }
      if (kind === 'stop_repair') {
        if (!repairJobId.trim()) throw new Error('请先填写修复任务 ID。');
        result = await api.stopRepair(repairJobId.trim());
      }
      setSelected(result as AnyRecord);
      await refreshMaintenanceJobs().catch(() => undefined);
      if (kind === 'check' || kind === 'repair') {
        await refresh(true).catch(() => undefined);
      }
      const resultRecord = result as AnyRecord;
      const dataRecord = (resultRecord?.data || resultRecord || {}) as AnyRecord;
      const jobId = dataRecord?.job_id || dataRecord?.repair_job_id || resultRecord?.job_id || resultRecord?.repair_job_id;
      setFeedback({ kind: 'ok', message: jobId ? `维护任务已提交：${jobId}。右侧“活动维护任务”会实时刷新进度。` : '维护操作已完成/已入队，结果已放入 Inspector。' });
    } catch (error) {
      setFeedback({ kind: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function stopActionNodes(all = false) {
    const mode = all ? 'all' : actionStopMode;
    const value = all ? null : actionStopValue.trim();
    if (!all && !value) {
      setFeedback({ kind: 'warn', message: '请先填写要停止的行动节点或行动器类型。' });
      return;
    }
    const ok = window.confirm(all ? '停止全部行动节点？' : `停止 ${mode}=${value}？`);
    if (!ok) return;
    setBusy(true);
    try {
      const result = await api.actionStop({
        mode,
        value,
        hold_ticks: actionStopHoldTicks,
        reason: actionStopReason,
      });
      setSelected(result);
      await refresh(true);
      setFeedback({ kind: 'ok', message: '行动停止请求已提交。' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-grid">
      <section className="page-main">
        <Group justify="space-between" mb="md" align="flex-start">
          <div>
            <Title order={2}>实时观测台</Title>
            <Text c="dimmed" size="sm">
              运行控制、状态池、HDB、行动节点与流程耗时集中在同一研究面板。
            </Text>
          </div>
          <Group gap="xs">
            <NumberInput
              label="刷新间隔 ms"
              value={refreshMs}
              min={250}
              max={60000}
              step={250}
              w={135}
              onChange={(value) => setRefreshMs(value === '' ? '' : Number(value) || 750)}
            />
            <Switch
              label="自动刷新"
              checked={autoRefresh}
              onChange={(event) => setAutoRefresh(event.currentTarget.checked)}
            />
            <Tooltip label="刷新快照">
              <ActionIcon variant="light" loading={busy} onClick={() => refresh()}>
                <IconRefresh size={18} />
              </ActionIcon>
            </Tooltip>
            <Button leftSection={<IconReload size={16} />} variant="light" onClick={() => api.reload().then(() => refresh())}>
              热加载
            </Button>
          </Group>
        </Group>

        <Grid mb="md">
          <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
            <MetricCard label="Tick" value={formatCount(dashboard?.tick_counter ?? dashboard?.meta?.tick_counter)} note="当前观测台循环计数" icon={<IconBolt size={18} />} tone="ok" />
          </Grid.Col>
          <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
            <MetricCard label="状态池对象" value={formatCount(summary?.active_item_count ?? stateItems.length)} note="活跃运行态对象" />
          </Grid.Col>
          <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
            <MetricCard label="HDB 结构" value={formatCount(hdbSummary?.structure_count ?? hdbItems.length)} note="长期结构规模" icon={<IconDatabase size={18} />} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
            <MetricCard label="最近耗时" value={formatDuration(pick(lastReport, ['timing.total_logic_ms', 'timing.total_ms'], 0))} note="主循环逻辑耗时" />
          </Grid.Col>
        </Grid>

        <Card mb="md" className="control-card">
          <Grid>
            <Grid.Col span={{ base: 12, lg: 7 }}>
              <Textarea
                label="文本输入"
                placeholder="输入文本后执行完整循环"
                minRows={4}
                value={inputText}
                onChange={(event) => setInputText(event.currentTarget.value)}
              />
              <Group mt="sm">
                <Button leftSection={<IconPlayerPlay size={16} />} loading={busy} onClick={runCycle}>
                  执行完整循环
                </Button>
                <NumberInput label="空 Tick 数" value={tickCount} min={1} max={999} onChange={(value) => setTickCount(Number(value) || 1)} w={140} />
                <Button variant="light" loading={busy} onClick={runTicks}>
                  执行 Tick
                </Button>
              </Group>
            </Grid.Col>
            <Grid.Col span={{ base: 12, lg: 5 }}>
              <Text fw={700} mb="xs">
                重置、维护与检视
              </Text>
              <Group gap="xs" mb="md">
                <Button
                  color="red"
                  variant="light"
                  leftSection={<IconTrash size={16} />}
                  onClick={() => confirmedReset('清空运行态', api.clearRuntime)}
                >
                  清运行态
                </Button>
                <Button color="red" variant="subtle" onClick={() => confirmedReset('清空 HDB', api.clearHdb)}>
                  清 HDB
                </Button>
                <Button color="red" variant="filled" onClick={() => confirmedReset('清空全部', api.clearAll)}>
                  清空全部
                </Button>
              </Group>
              <Group align="flex-end" gap="xs">
                <Select
                  label="查询类型"
                  value={queryMode}
                  onChange={(value) => setQueryMode((value as any) || 'structure')}
                  data={[
                    { value: 'structure', label: '结构 ST' },
                    { value: 'group', label: '结构组 SG' },
                    { value: 'episodic', label: '情节记忆 EM' },
                  ]}
                  w={140}
                />
                <TextInput label="ID / limit" value={queryValue} onChange={(event) => setQueryValue(event.currentTarget.value)} style={{ flex: 1 }} />
                <ActionIcon size={36} variant="light" onClick={query}>
                  <IconSearch size={18} />
                </ActionIcon>
              </Group>
            </Grid.Col>
          </Grid>
        </Card>
        <FeedbackAlert feedback={feedback} />

        <Tabs defaultValue="state" className="panel-tabs">
          <Tabs.List>
            <Tabs.Tab value="state">状态池 Top</Tabs.Tab>
            <Tabs.Tab value="hdb">HDB Top</Tabs.Tab>
            <Tabs.Tab value="sensor">传感器</Tabs.Tab>
            <Tabs.Tab value="time">时间感受</Tabs.Tab>
            <Tabs.Tab value="memory">记忆激活</Tabs.Tab>
            <Tabs.Tab value="cfs">认知/情绪</Tabs.Tab>
            <Tabs.Tab value="actions">行动节点</Tabs.Tab>
            <Tabs.Tab value="flow">流程耗时</Tabs.Tab>
            <Tabs.Tab value="cycles">最近循环</Tabs.Tab>
            <Tabs.Tab value="maintenance">维护/修复</Tabs.Tab>
            <Tabs.Tab value="pipeline">流程开关</Tabs.Tab>
            <Tabs.Tab value="settings">配置</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="state" pt="md">
            <Group justify="space-between" mb="sm" align="flex-end">
              <div>
                <Text fw={800}>状态池结构波峰显示</Text>
                <Text size="xs" c="dimmed">
                  聚合显示只在前端把相同特征内容汇总为一个波峰；默认隐藏纯原子 SA 证据项，让结构主榜更贴近 growth 口径。后端对象、激活/审计元数据和 id 不会被合并。
                </Text>
              </div>
              <Group gap="sm" align="flex-end">
                <Switch
                  label="按特征内容聚合"
                  checked={aggregateStateTop}
                  onChange={(event) => setAggregateStateTop(event.currentTarget.checked)}
                />
                <NumberInput
                  label="显示 TopN"
                  value={stateTopN}
                  min={1}
                  max={300}
                  onChange={(value) => setStateTopN(value === '' ? '' : Number(value) || 20)}
                  w={130}
                />
                <Badge variant="light">
                  {formatCount(displayedStateItems.length)} / 候选 {formatCount(stateItems.length)}
                </Badge>
              </Group>
            </Group>
            <VirtualDataTable
              data={displayedStateItems}
              columns={stateColumns}
              height={460}
              estimateRowHeight={58}
              getRowKey={rowIdentity}
              selectedKey={selectedKey}
              onRowClick={(row) => {
                setSelectedKey(rowIdentity(row));
                setSelected(row as AnyRecord);
              }}
            />
          </Tabs.Panel>
          <Tabs.Panel value="hdb" pt="md">
            <VirtualDataTable
              data={hdbItems}
              columns={hdbColumns}
              height={460}
              getRowKey={rowIdentity}
              selectedKey={selectedKey}
              onRowClick={inspectHdbRow}
            />
          </Tabs.Panel>
          <Tabs.Panel value="sensor" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, lg: 4 }}>
                <Stack>
                  <MetricCard label="传感器模式" value={lastReport.sensor?.mode || lastReport.sensor?.tokenizer_backend || '-'} note={`SA ${formatCount(lastReport.sensor?.sa_count)} / 属性 ${formatCount(lastReport.sensor?.attribute_sa_count)}`} />
                  <MetricCard label="输入队列" value={formatCount(lastReport.input_queue?.queued_count ?? lastReport.input_queue?.input_count)} note={shortText(lastReport.sensor?.input_text || lastReport.sensor?.normalized_text || '-', 80)} />
                  <SensorRuntimeSummary value={lastReport.sensor?.fatigue_summary || lastReport.sensor?.echo_decay_summary || {}} />
                </Stack>
              </Grid.Col>
              <Grid.Col span={{ base: 12, lg: 8 }}>
                <Stack>
                  <div>
                    <Group justify="space-between" mb="xs">
                      <Text fw={800}>刺激单元</Text>
                      <Badge variant="light">{formatCount(sensorUnits.length)}</Badge>
                    </Group>
                    <VirtualDataTable data={sensorUnits} columns={sensorUnitColumns} height={260} onRowClick={(row) => setSelected(row)} />
                  </div>
                  <div>
                    <Group justify="space-between" mb="xs">
                      <Text fw={800}>刺激组 / 合流组</Text>
                      <Badge variant="light">{formatCount(sensorGroups.length)}</Badge>
                    </Group>
                    <VirtualDataTable data={sensorGroups} columns={sensorGroupColumns} height={260} onRowClick={(row) => setSelected(row)} />
                  </div>
                </Stack>
              </Grid.Col>
            </Grid>
          </Tabs.Panel>
          <Tabs.Panel value="time" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, lg: 4 }}>
                <Stack>
                  <MetricCard label="时间基准" value={lastReport.time_sensor?.time_basis || dashboard?.time_sensor_runtime?.time_basis || '-'} note={`tick ${lastReport.time_sensor?.tick_index ?? lastReport.tick_counter ?? '-'}`} />
                  <MetricCard label="时间桶/绑定" value={`${formatCount(asArray(lastReport.time_sensor?.bucket_updates).length)} / ${formatCount(asArray(lastReport.time_sensor?.attribute_bindings).length)}`} note={`延迟任务 ${formatCount(asArray(lastReport.time_sensor?.delayed_tasks).length)}`} />
                  <TimeRuntimeSummary value={dashboard?.time_sensor_runtime || lastReport.time_sensor || {}} />
                </Stack>
              </Grid.Col>
              <Grid.Col span={{ base: 12, lg: 8 }}>
                <VirtualDataTable data={timeRows} columns={timeColumns} height={540} onRowClick={(row) => setSelected(row)} />
              </Grid.Col>
            </Grid>
          </Tabs.Panel>
          <Tabs.Panel value="memory" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, lg: 4 }}>
                <Stack>
                  <MetricCard label="记忆激活路径" value={lastReport.memory_activation?.path_mode || '-'} note={`专用池 ${lastReport.memory_activation?.dedicated_memory_pool_enabled ? '启用' : '关闭/未用'}`} />
                  <MetricCard label="记忆回馈" value={formatCount(lastReport.memory_feedback?.applied_count)} note={`ER ${formatNumber(lastReport.memory_feedback?.total_feedback_er, 3)} / EV ${formatNumber(lastReport.memory_feedback?.total_feedback_ev, 3)}`} />
                  <MemoryRuntimeSummary value={lastReport.memory_activation?.maintenance || lastReport.memory_feedback || {}} />
                </Stack>
              </Grid.Col>
              <Grid.Col span={{ base: 12, lg: 8 }}>
                <VirtualDataTable data={memoryRows} columns={memoryColumns} height={540} onRowClick={(row) => setSelected(row)} />
              </Grid.Col>
            </Grid>
          </Tabs.Panel>
          <Tabs.Panel value="cfs" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, xl: 7 }}>
                <Card mb="sm" className="soft-note-card">
                  <Text fw={800} mb="xs">认知/情绪页在看什么？</Text>
                  <Text size="sm">
                    这里把四类运行态线索放在一张桌子上：`CFS 输出` 是认知感受器直接生成的感受，`属性写回` 是把感受绑定回对象，`IESM 输入` 是先天规则真正读到的候选，`聚焦指令` 则是 IESM 最终发给注意力模块的偏置结果。
                  </Text>
                  <Text size="xs" c="dimmed" mt="sm">
                    读法上建议先看左表里“CFS 输出”和“聚焦指令”的数量，再点具体行去右侧检视面板确认：究竟是某个对象真的触发了感受，还是只是规则前段看到了候选但没形成最终偏置。
                  </Text>
                </Card>
                <Group justify="space-between" mb="xs">
                  <div>
                    <Text fw={800}>认知感受 / IESM 聚焦</Text>
                    <Text size="xs" c="dimmed">
                      这里混合展示四类东西：CFS 直接输出、属性回写、IESM 读取到的输入，以及最终发出的聚焦指令。点击任意一行，右侧会显示它当前携带的对象信息。
                    </Text>
                  </div>
                  <Badge variant="light">{formatCount(cfsRows.length)}</Badge>
                </Group>
                <Group gap="xs" mb="sm">
                  {['CFS 输出', '属性写回', 'IESM 输入', '聚焦指令'].map((kind) => (
                    <Badge key={kind} variant="light">
                      {kind} {formatCount(cfsRows.filter((row) => String(row.row_kind || '') === kind).length)}
                    </Badge>
                  ))}
                </Group>
                <VirtualDataTable data={cfsRows} columns={cfsColumns} height={520} onRowClick={(row) => setSelected(row)} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, xl: 5 }}>
                <Stack>
                  <div>
                    <Group justify="space-between" mb="xs">
                      <Text fw={800}>NT 通道变化</Text>
                      <Badge variant="light">{formatCount(ntRows.length)}</Badge>
                    </Group>
                    <VirtualDataTable data={ntRows} columns={ntColumns} height={260} onRowClick={(row) => setSelected(row)} />
                  </div>
                  <EmotionRuntimeSummary value={lastReport.emotion?.modulation || lastReport.emotion || {}} />
                </Stack>
              </Grid.Col>
            </Grid>
          </Tabs.Panel>
          <Tabs.Panel value="actions" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, xl: 7 }}>
                <Card mb="sm" className="soft-note-card">
                  <Text fw={800} mb="xs">为什么会看到很多“注意力聚焦模式”对象？</Text>
                  <Text size="sm">
                    这里列的是运行态里的行动节点，不是行动器种类目录。同一种行动器可以在不同激活链、不同触发链或不同节点 ID 下同时存在，所以你会看到多个“注意力聚焦模式”对象。
                  </Text>
                </Card>
                <VirtualDataTable
                  data={actionNodes}
                  columns={actionColumns}
                  height={420}
                  getRowKey={rowIdentity}
                  selectedKey={selectedKey}
                  onRowClick={(row) => {
                    setSelectedKey(rowIdentity(row));
                    setSelected(row);
                  }}
                />
              </Grid.Col>
              <Grid.Col span={{ base: 12, xl: 5 }}>
                <Card>
                  <Text fw={800}>行动停止接口</Text>
                  <Text size="xs" c="dimmed" mb="sm">
                    对齐旧前端 Stop/Cancel：清零 drive，并在 hold_ticks 内门控执行。
                  </Text>
                  <Group align="flex-end">
                    <Select
                      label="模式"
                      value={actionStopMode}
                      onChange={(value) => {
                        setActionStopMode(value || 'action_kind');
                        setActionStopValue('');
                      }}
                      data={[
                        { value: 'action_kind', label: '行动器类型' },
                        { value: 'action_id', label: '行动节点 ID' },
                      ]}
                      w={150}
                    />
                    <TextInput
                      label="目标"
                      value={actionStopValue}
                      onChange={(event) => setActionStopValue(event.currentTarget.value)}
                      placeholder={actionStopMode === 'action_id' ? 'action_id' : 'action_kind'}
                      style={{ flex: 1 }}
                    />
                    <NumberInput label="hold" value={actionStopHoldTicks} min={0} max={10000} onChange={(v) => setActionStopHoldTicks(Number(v) || 0)} w={110} />
                  </Group>
                  <TextInput mt="sm" label="原因" value={actionStopReason} onChange={(event) => setActionStopReason(event.currentTarget.value)} />
                  <Group mt="sm">
                    <Button color="red" variant="light" onClick={() => stopActionNodes(false)}>
                      停止目标
                    </Button>
                    <Button color="red" variant="subtle" onClick={() => stopActionNodes(true)}>
                      停止全部
                    </Button>
                  </Group>
                </Card>
              </Grid.Col>
              <Grid.Col span={12}>
                <Text fw={800} mb="xs">
                  本轮行动事件
                </Text>
                <VirtualDataTable data={executedActionRows} columns={cfsColumns} height={240} onRowClick={(row) => setSelected(row)} />
              </Grid.Col>
              <Grid.Col span={12}>
                <Text fw={800} mb="xs">
                  行动器注册表
                </Text>
                <VirtualDataTable data={actionExecutors} columns={executorColumns} height={240} />
              </Grid.Col>
            </Grid>
          </Tabs.Panel>
          <Tabs.Panel value="flow" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, xl: 8 }}>
                <Grid>
                  {flowStageCards.map((stage) => (
                    <Grid.Col key={stage.stage} span={{ base: 12, md: 6 }}>
                      <Card className="flow-stage-card" onClick={() => setSelected(stage.detail)}>
                        <Group justify="space-between" align="flex-start" mb="xs">
                          <div>
                            <Text fw={800}>{stage.stage}</Text>
                            <Text size="xs" c="dimmed">
                              {stage.description}
                            </Text>
                          </div>
                          <Badge variant="light">{stage.duration_ms === undefined ? '-' : formatDuration(stage.duration_ms)}</Badge>
                        </Group>
                        <Text className="flow-stage-value">{stage.main_value}</Text>
                        <Text size="xs" c="dimmed" mt={6}>
                          {stage.sub_value}
                        </Text>
                      </Card>
                    </Grid.Col>
                  ))}
                </Grid>
              </Grid.Col>
              <Grid.Col span={{ base: 12, xl: 4 }}>
                <Stack>
                  <Card>
                    <Text fw={800} mb="xs">流程耗时明细</Text>
                    <Grid>
                      {flowSteps.map((step) => (
                        <Grid.Col key={step.key} span={{ base: 12, sm: 6, xl: 12 }}>
                          <MetricCard label={String(step.key)} value={formatDuration(step.value)} />
                        </Grid.Col>
                      ))}
                    </Grid>
                  </Card>
                  <TimingSummary timing={lastReport.timing || {}} meta={lastReport.observatory || lastReport.meta || {}} />
                </Stack>
              </Grid.Col>
              {!flowStageCards.length ? (
                <Grid.Col span={12}>
                  <Card>
                    <Text c="dimmed">执行一次循环后，这里会显示完整流程阶段。</Text>
                  </Card>
                </Grid.Col>
              ) : null}
            </Grid>
          </Tabs.Panel>
          <Tabs.Panel value="cycles" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, lg: 8 }}>
                <VirtualDataTable data={recentCycles} columns={cycleColumns} height={520} onRowClick={(row) => setSelected(row)} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, lg: 4 }}>
                <TimingSummary timing={lastReport.timing || {}} meta={lastReport.observatory || lastReport.meta || {}} />
              </Grid.Col>
            </Grid>
          </Tabs.Panel>
          <Tabs.Panel value="maintenance" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, lg: 5 }}>
                <Card>
                  <Text fw={800}>HDB 自检、修复与闲时巩固</Text>
                  <Text size="xs" c="dimmed" mb="sm">
                    迁移旧观测台的 check / repair / repair_all / idle_consolidate / stop_repair。
                  </Text>
                  <TextInput label="目标 ID" value={maintenanceTarget} onChange={(event) => setMaintenanceTarget(event.currentTarget.value)} placeholder="例如 st_000012，可留空自检全局" />
                  <TextInput mt="sm" label="修复任务 ID" value={repairJobId} onChange={(event) => setRepairJobId(event.currentTarget.value)} placeholder="例如 repair_job_0003" />
                  <Divider my="sm" />
                  <Text fw={700} size="sm">手动闲时整理</Text>
                  <Text size="xs" c="dimmed" mb="xs">
                    轻量模式只整理最近一批结构 DB 与 CS 诊断事件，适合运行间隙；完整模式会扫描全部结构 DB 并重建指针索引，建议暂停实验后手动执行。
                  </Text>
                  <Group grow align="flex-end">
                    <Select
                      label="整理模式"
                      value={idleMode}
                      onChange={(value) => setIdleMode(value === 'full' ? 'full' : 'light')}
                      data={[
                        { value: 'light', label: '轻量批次整理' },
                        { value: 'full', label: '完整全库整理' },
                      ]}
                    />
                    <NumberInput
                      label="结构 DB 批量"
                      min={16}
                      max={5000}
                      disabled={idleMode === 'full'}
                      value={idleBatchLimit}
                      onChange={(value) => setIdleBatchLimit(value === '' ? '' : Number(value) || 256)}
                    />
                    <NumberInput
                      label="CS事件批量"
                      min={0}
                      max={5000}
                      disabled={idleMode === 'full'}
                      value={idleMaxCsEvents}
                      onChange={(value) => setIdleMaxCsEvents(value === '' ? '' : Number(value) || 128)}
                    />
                  </Group>
                  <Group mt="sm">
                    <Button variant="light" onClick={() => runMaintenance('check')}>执行自检</Button>
                    <Button variant="light" onClick={() => runMaintenance('repair')}>局部修复</Button>
                    <Button variant="light" onClick={() => runMaintenance('repair_all')}>全局快速修复</Button>
                    <Button variant="light" leftSection={<IconDatabase size={16} />} onClick={() => runMaintenance('idle')}>启动手动闲时整理</Button>
                    <Button color="red" variant="subtle" onClick={() => runMaintenance('stop_repair')}>停止修复</Button>
                  </Group>
                </Card>
              </Grid.Col>
              <Grid.Col span={{ base: 12, lg: 7 }}>
                <Stack>
                  <div>
                    <Text fw={800} mb="xs">活动维护任务</Text>
                    <Text size="xs" c="dimmed" mb="xs">
                      独立轮询维护任务状态，不等待主 Dashboard 锁；全局修复和闲时整理提交后可在这里看到 queued/running/completed、扫描量和更新量。
                    </Text>
                    <VirtualDataTable data={repairJobs} columns={repairColumns} height={220} onRowClick={(row) => setSelected(row)} />
                  </div>
                  <div>
                    <Text fw={800} mb="xs">HDB 异常项</Text>
                    <VirtualDataTable data={hdbIssues} columns={issueColumns} height={220} onRowClick={(row) => setSelected(row)} />
                  </div>
                </Stack>
              </Grid.Col>
            </Grid>
          </Tabs.Panel>
          <Tabs.Panel value="pipeline" pt="md">
            <Card>
              <Text fw={800}>流程阶段开关</Text>
              <Text size="xs" c="dimmed" mb="md">
                使用当前 effective 值初始化。保存会同步观测台主开关，并尽量同步相关模块文件值。
              </Text>
              <Grid>
                {[
                  ['enable_cognitive_stitching', 'CS 回滚诊断'],
                  ['enable_structure_level_retrieval_storage', '结构级查存一体'],
                  ['enable_goal_b_char_sa_string_mode', '字符串方案'],
                  ['enable_energy_balance', '能量平衡控制器（EBC）'],
                  ['enable_delayed_tasks', '时间感受器延迟任务'],
                ].map(([key, label]) => (
                  <Grid.Col key={key} span={{ base: 12, sm: 6, lg: 4 }}>
                    <Switch
                      label={label}
                      checked={Boolean((pipelineDraft as AnyRecord)[key])}
                      onChange={(event) => setPipelineDraft((prev) => ({ ...prev, [key]: event.currentTarget.checked }))}
                    />
                  </Grid.Col>
                ))}
              </Grid>
              <Group mt="md">
                <Button onClick={applyPipelineSwitches}>应用并热加载</Button>
                <Button variant="light" onClick={() => refresh(true)}>重置为当前生效值</Button>
              </Group>
            </Card>
          </Tabs.Panel>
          <Tabs.Panel value="settings" pt="md">
            <Card mb="sm" className="soft-note-card">
              <Text fw={800} mb="xs">配置页使用说明</Text>
              <Text size="sm">
                这里优先展示模块的生效值与中文注释。若你手工调整了某些关键阈值，但同时启用了自适应调参器，最好也同步检查对应的调参规则、参数边界与长期目标，否则运行中可能很快被调参器拉回另一套范围。
              </Text>
            </Card>
            <Group mb="sm">
              <Button variant="light" onClick={loadConfig}>刷新配置包</Button>
            </Group>
            <ConfigMiniEditor bundle={configBundle || dashboard?.module_configs || null} onSave={saveConfigModule} />
          </Tabs.Panel>
        </Tabs>
      </section>

      <aside className="page-inspector">
        <Card className="sticky-inspector">
          <Group justify="space-between" mb="sm">
            <div>
              <Text fw={800}>对象检视面板</Text>
              <Text size="xs" c="dimmed">
                点击状态池、HDB 或行动行可固定查看对象详情；查询结果也会显示在这里。
              </Text>
            </div>
            <Badge variant="light">详情</Badge>
          </Group>
          <Divider mb="sm" />
          <ScrollArea.Autosize mah="calc(100vh - 180px)">
            <Stack gap="sm">
              {selected && (selected as DisplayAggregateRow).__displayAggregate ? (
                <AggregateDetail value={selected} title="状态池显示聚合详情" maxHeight={340} />
              ) : selected ? (
                <ObjectDetail value={selected} title="查询结果" maxHeight={620} />
              ) : (
                <Card className="soft-note-card">
                  <Text fw={800} mb="xs">
                    等待选择对象
                  </Text>
                  <Text size="sm">
                    右侧检视面板默认不再首屏展开整份最近报告，避免大对象详情把页面拖慢或直接黑屏。
                  </Text>
                  <Text size="xs" c="dimmed" mt="sm">
                    现在建议从状态池、HDB、行动、CFS、时间或最近循环表中点击一行，再在这里查看该对象的结构库、残差表、激活/审计元数据和运行态细节。
                  </Text>
                </Card>
              )}
            </Stack>
          </ScrollArea.Autosize>
        </Card>
      </aside>
    </div>
  );
}
