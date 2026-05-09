import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Divider,
  Grid,
  Group,
  JsonInput,
  NumberInput,
  PasswordInput,
  ScrollArea,
  Select,
  Stack,
  Switch,
  Tabs,
  Text,
  Textarea,
  TextInput,
  ThemeIcon,
  Title,
  Tooltip,
  Modal,
} from '@mantine/core';
import { useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { IconChartLine, IconCopy, IconEdit, IconPlayerPlay, IconPlus, IconPower, IconRefresh, IconRotateClockwise, IconTrash, IconUpload } from '@tabler/icons-react';
import { ApiError, api } from '../lib/api';
import type { AnyRecord, DatasetItem, DatasetRef, ExperimentRunItem, MetricRow } from '../types/api';
import { asArray, asNumber, formatCount, formatDuration, formatNumber, formatPercent, shortDisplayText, shortText } from '../lib/format';
import { MetricCard } from '../components/MetricCard';
import { VirtualDataTable } from '../components/VirtualDataTable';
import { MetricChart } from '../components/MetricChart';
import { chartConfigs, chartSections, metricDisplayName } from '../data/metricCatalog';
import { JsonInspector } from '../components/JsonInspector';
import { FeedbackAlert, type FeedbackState } from '../components/FeedbackAlert';
import { AggregateDetail } from '../components/AggregateDetail';
import { aggregateRowsByDisplay, rowCognitivePressure, type DisplayAggregateRow } from '../lib/displayAggregation';
import { SummaryCard, TimingSummary } from '../components/FriendlySummary';
import { chartHasVisibleData } from '../lib/metricStats';
import { LoadingPanel } from '../components/LoadingPanel';
import { MarkdownReport } from '../components/MarkdownReport';

type ExperimentPageProps = {
  onStatusChange?: (status: string) => void;
};

type DatasetLoadPhase = 'idle' | 'loading' | 'ready' | 'backend_waiting' | 'error';
type LiveTopSortMode = 'total' | 'er' | 'ev';

const METRIC_TARGET_FIELDS = [
  'expected_min',
  'expected_max',
  'ideal',
  'min_std',
  'weight',
  'high_band_threshold',
  'high_band_max_ratio',
  'high_band_soft_p95',
  'high_band_max_run',
] as const;

const EXPERIMENT_PAGE_SETTINGS_KEY = 'ap-next-experiment-page-settings-v1';
const DEFAULT_EXPERIMENT_SETTINGS = {
  selectedDatasetKey: '',
  selectedRunId: '',
  activeJobId: '',
  activeSection: 'overview',
  showDiagnosticCharts: false,
  resetMode: 'clear_all',
  cleanRun: false,
  maxTicks: 80 as number | '',
  runAllTicks: false,
  autoTune: false,
  autoTuneShort: true,
  autoTuneLong: true,
  exportJson: false,
  exportHtml: false,
  timeBasisOverride: '',
  tickIntervalSec: '' as number | '',
  downsampleEvery: 1,
  chartSearch: '',
  liveRefreshMs: 750 as number | '',
  liveTopN: 20 as number | '',
  liveAggregateStateTop: true,
  liveTopSort: 'total' as LiveTopSortMode,
  tickTopN: 5 as number | '',
};

type ExperimentPageSettings = typeof DEFAULT_EXPERIMENT_SETTINGS;

function browserStorageAvailable(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined';
}

function normalizeNumberOrEmpty(value: unknown, fallback: number | ''): number | '' {
  if (value === '' || value === null || value === undefined) return '';
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeLiveTopSortMode(value: unknown): LiveTopSortMode {
  const key = String(value || '').trim().toLowerCase();
  if (key === 'er' || key === 'ev') return key;
  return 'total';
}

function loadExperimentPageSettings(): ExperimentPageSettings {
  if (!browserStorageAvailable()) return { ...DEFAULT_EXPERIMENT_SETTINGS };
  try {
    const raw = window.localStorage.getItem(EXPERIMENT_PAGE_SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_EXPERIMENT_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<ExperimentPageSettings>;
    return {
      ...DEFAULT_EXPERIMENT_SETTINGS,
      selectedDatasetKey: String(parsed.selectedDatasetKey || ''),
      selectedRunId: String(parsed.selectedRunId || ''),
      activeJobId: String(parsed.activeJobId || ''),
      activeSection: String(parsed.activeSection || DEFAULT_EXPERIMENT_SETTINGS.activeSection),
      showDiagnosticCharts: Boolean(parsed.showDiagnosticCharts),
      resetMode: String(parsed.resetMode || DEFAULT_EXPERIMENT_SETTINGS.resetMode),
      cleanRun: Boolean(parsed.cleanRun),
      maxTicks: normalizeNumberOrEmpty(parsed.maxTicks, DEFAULT_EXPERIMENT_SETTINGS.maxTicks),
      runAllTicks: Boolean(parsed.runAllTicks),
      autoTune: Boolean(parsed.autoTune),
      autoTuneShort: parsed.autoTuneShort === undefined ? true : Boolean(parsed.autoTuneShort),
      autoTuneLong: parsed.autoTuneLong === undefined ? true : Boolean(parsed.autoTuneLong),
      exportJson: Boolean(parsed.exportJson),
      exportHtml: Boolean(parsed.exportHtml),
      timeBasisOverride: String(parsed.timeBasisOverride || ''),
      tickIntervalSec: normalizeNumberOrEmpty(parsed.tickIntervalSec, ''),
      downsampleEvery: Math.max(1, Number(parsed.downsampleEvery) || DEFAULT_EXPERIMENT_SETTINGS.downsampleEvery),
      chartSearch: String(parsed.chartSearch || ''),
      liveRefreshMs: normalizeNumberOrEmpty(parsed.liveRefreshMs, DEFAULT_EXPERIMENT_SETTINGS.liveRefreshMs),
      liveTopN: normalizeNumberOrEmpty(parsed.liveTopN, DEFAULT_EXPERIMENT_SETTINGS.liveTopN),
      liveAggregateStateTop: parsed.liveAggregateStateTop === undefined ? true : Boolean(parsed.liveAggregateStateTop),
      liveTopSort: normalizeLiveTopSortMode(parsed.liveTopSort),
      tickTopN: normalizeNumberOrEmpty(parsed.tickTopN, DEFAULT_EXPERIMENT_SETTINGS.tickTopN),
    };
  } catch {
    return { ...DEFAULT_EXPERIMENT_SETTINGS };
  }
}

function saveExperimentPageSettings(settings: ExperimentPageSettings) {
  if (!browserStorageAvailable()) return;
  try {
    window.localStorage.setItem(EXPERIMENT_PAGE_SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Local storage can be unavailable in some embedded browser modes.
  }
}

const diagnosticChartSectionIds: Set<string> = new Set(
  chartSections.filter((section) => section.diagnostic).map((section) => section.id),
);

function isDiagnosticChartConfig(config: { section: string; diagnostic?: boolean }): boolean {
  return Boolean(config.diagnostic) || diagnosticChartSectionIds.has(config.section);
}

function datasetRefOf(item: DatasetItem | null): DatasetRef | null {
  if (!item) return null;
  const ref = item.dataset_ref || item.ref;
  if (ref?.source && ref?.rel_path) return ref as DatasetRef;
  if (item.source && item.rel_path) {
    return { source: String(item.source), rel_path: String(item.rel_path) };
  }
  return null;
}

function datasetKey(ref: DatasetRef | null): string {
  return ref ? `${ref.source}:${ref.rel_path}` : '';
}

function downloadText(filename: string, text: string) {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function normalizeLlmConfig(payload: AnyRecord | null): AnyRecord {
  const cfg = (payload?.config || payload || {}) as AnyRecord;
  return {
    enabled: Boolean(cfg.enabled),
    auto_analyze_on_completion: Boolean(cfg.auto_analyze_on_completion ?? cfg.auto_review_on_completion),
    base_url: String(cfg.base_url || 'https://api.openai.com'),
    api_key: '',
    api_key_masked: String(cfg.api_key_masked || ''),
    model: String(cfg.model || ''),
    temperature: asNumber(cfg.temperature, 0.2),
    max_prompt_chars: asNumber(cfg.max_prompt_chars, 900000),
    timeout_sec: asNumber(cfg.timeout_sec, 240),
    max_completion_tokens: asNumber(cfg.max_completion_tokens, 4096),
  };
}

function llmStageLabel(stage: unknown): string {
  const raw = String(stage || '').trim();
  const labels: Record<string, string> = {
    not_started: '尚未开始',
    queued: '排队中',
    running: '运行中',
    building_prompt: '正在整理运行数据与理论提示',
    calling_llm: '正在请求大模型',
    streaming: '正在接收报告文本',
    completed: '已完成',
    failed: '失败',
  };
  return labels[raw] || raw || '未知';
}

function experimentStageLabel(stage: unknown, status?: unknown): string {
  const raw = String(stage || status || '').trim().toLowerCase();
  const labels: Record<string, string> = {
    queued: '排队中',
    loading_dataset: '读取数据集',
    preparing_manifest: '准备运行清单',
    prepared: '准备初始化运行态',
    waiting_for_app_lock: '等待主循环锁/维护任务',
    capturing_baseline: '读取运行前基线',
    applying_overrides: '应用运行覆盖',
    resetting_runtime: '清理运行态',
    configuring_exports: '配置导出开关',
    configuring_time_sensor: '配置时间感受器',
    running: '运行中',
    running_tick: '执行 tick',
    tick_finished: 'tick 已写入指标',
    idle_consolidation: 'HDB 闲时整理',
    idle_consolidation_cs: 'CS 诊断整理',
    finished: '已结束',
    completed: '已完成',
    stopped_max_ticks: '达到最大 tick',
    cancelling: '正在停止',
    cancelled: '已取消',
    failed: '失败',
  };
  return labels[raw] || String(stage || status || '未知');
}

function jobStatusLabel(job: AnyRecord | null | undefined): string {
  if (!job) return '无任务';
  const label = String(job.stage_label || '').trim();
  if (label) return label;
  if (String(job.job_type || '').includes('experiment')) return experimentStageLabel(job.stage, job.status);
  return experimentStageLabel(job.stage, job.status);
}

function jobIsActive(job: AnyRecord | null | undefined): boolean {
  const status = String(job?.status || '').toLowerCase();
  const stage = String(job?.stage || '').toLowerCase();
  return ['queued', 'running', 'cancelling', 'waiting_for_app_lock'].includes(status) ||
    ['queued', 'running', 'running_tick', 'waiting_for_app_lock'].includes(stage) ||
    Boolean(job?.lock_waiting);
}

function jobProgressText(job: AnyRecord | null | undefined): string {
  if (!job) return '-';
  const done = job.tick_done ?? job.source_tick_done ?? job.processed_count ?? job.executed_tick_done_total ?? 0;
  const planned = job.tick_planned ?? job.batch_limit ?? job.total ?? null;
  if (planned !== null && planned !== undefined && Number(planned) > 0) {
    return `${formatCount(done)} / ${formatCount(planned)}`;
  }
  if (Number(done) > 0) return formatCount(done);
  return '-';
}

function jobTypeLabel(job: AnyRecord | null | undefined): string {
  const raw = String(job?.type_label || job?.job_type || '').trim();
  const labels: Record<string, string> = {
    experiment_run: '数据集运行',
    idle_consolidation: '闲时整理',
    hdb_repair: 'HDB 修复',
    repair: 'HDB 修复',
    llm_review: 'LLM 审查',
    auto_tuner_llm: 'AutoTuner LLM',
  };
  return labels[raw] || raw || '后台任务';
}

function jobTimeText(job: AnyRecord | null | undefined): string {
  const updated = Number(job?.updated_at_ms || job?.finished_at_ms || job?.started_at_ms || job?.created_at_ms || 0);
  return updated > 0 ? new Date(updated).toLocaleTimeString() : '-';
}

function manifestSummaryItems(manifest: AnyRecord | null, latest: MetricRow | null) {
  const root = (manifest || {}) as AnyRecord;
  const latestRow = (latest || {}) as AnyRecord;
  return [
    { label: '运行 ID', value: root.run_id || latestRow.run_id },
    { label: '运行状态', value: root.status || latestRow.status },
    { label: '数据集', value: root.dataset_id || root.dataset_name || root.dataset_ref?.rel_path },
    { label: '已完成 tick', value: root.tick_done ?? root.source_tick_done ?? latestRow.tick },
    { label: '计划 tick', value: root.tick_planned ?? root.planned_ticks },
    { label: '最新总耗时', value: latestRow.timing_total_logic_ms ? `${formatNumber(latestRow.timing_total_logic_ms, 1)} ms` : undefined },
    { label: '状态池对象', value: latestRow.pool_active_item_count ?? latestRow.state_pool_active_item_count },
    { label: '注意力资源', value: latestRow.attention_energy_budget ?? latestRow.attention_budget },
  ];
}

function latestMetricSummaryItems(latest: MetricRow | null) {
  const row = (latest || {}) as AnyRecord;
  return [
    { label: '最新 tick', value: row.tick_index ?? row.tick },
    { label: '状态池对象', value: row.pool_active_item_count ?? row.state_pool_active_item_count },
    { label: '状态池 ER', value: row.pool_total_er },
    { label: '状态池 EV', value: row.pool_total_ev },
    { label: '注意力资源', value: row.attention_energy_budget ?? row.attention_budget },
    { label: '注意力净增', value: row.attention_net_delta_energy },
    { label: 'CS 诊断动作', value: row.cs_action_count },
    { label: '总耗时 ms', value: row.timing_total_logic_ms },
  ];
}

function datasetProtocolSummaryItems(protocol: AnyRecord | null) {
  const root = (protocol || {}) as AnyRecord;
  return [
    { label: '协议版本', value: root.version || root.schema_version },
    { label: '支持格式', value: asArray(root.supported_formats || root.formats).join(' / ') || root.format },
    { label: '必填字段', value: asArray(root.required_fields).join(' / ') },
    { label: '可选字段', value: asArray(root.optional_fields).slice(0, 8).join(' / ') },
    { label: '示例数量', value: asArray(root.examples).length },
    { label: '说明', value: root.description || root.summary || root.note },
  ];
}

function datasetResultSummaryItems(datasetPreview: AnyRecord | null, datasetExpand: AnyRecord | null) {
  const preview = (datasetPreview || {}) as AnyRecord;
  const expand = (datasetExpand || {}) as AnyRecord;
  return [
    { label: '总 tick', value: preview.total_ticks ?? expand.total_ticks },
    { label: '预览 tick', value: asArray(preview.preview_ticks).length },
    { label: '有效文本 tick', value: preview.effective_text_ticks ?? preview.overview?.effective_text_ticks },
    { label: '空 tick', value: preview.empty_ticks ?? preview.overview?.empty_ticks },
    { label: 'episode 数', value: preview.episode_count ?? preview.overview?.episode_count },
    { label: '展开路径', value: expand.output_path || expand.jsonl_path || expand.path },
  ];
}

function llmStatusIsRunning(status: AnyRecord | null): boolean {
  const raw = String(status?.status || status?.stage || '').trim().toLowerCase();
  return ['queued', 'running', 'building_prompt', 'calling_llm', 'streaming'].includes(raw);
}

function llmReviewJobKey(job: AnyRecord | null | undefined, fallback = ''): string {
  const raw = String(job?.job_id || job?.id || '').trim();
  if (raw) return raw;
  const runId = String(job?.run_id || '').trim();
  const created = String(job?.created_at_ms || job?.started_at_ms || job?.finished_at_ms || '').trim();
  const suffix = created || fallback;
  return runId || suffix ? `${runId}:${suffix}` : fallback;
}

function llmReviewJobIsRunning(job: AnyRecord | null | undefined): boolean {
  const raw = String(job?.status || job?.stage || '').trim().toLowerCase();
  return ['queued', 'running', 'building_prompt', 'calling_llm', 'streaming'].includes(raw);
}

function pickLlmReviewJobForRun(jobs: AnyRecord[], runId: string, preferredJobId = ''): AnyRecord | null {
  const rid = String(runId || '').trim();
  const preferred = String(preferredJobId || '').trim();
  if (!rid) return null;
  const sameRun = asArray<AnyRecord>(jobs).filter((job) => String(job.run_id || '').trim() === rid);
  if (preferred) {
    const exact = sameRun.find((job, index) => llmReviewJobKey(job, String(index)) === preferred);
    if (exact) return exact;
  }
  return sameRun.find((job) => llmReviewJobIsRunning(job)) || sameRun[0] || null;
}

function llmReviewJobsFromPayload(payload: unknown): AnyRecord[] {
  return asArray<AnyRecord>((payload as AnyRecord | null)?.jobs || payload);
}

function reviewReportSummaryItems(status: AnyRecord | null, report: AnyRecord | null) {
  return [
    { label: '阶段', value: llmStageLabel(status?.stage || status?.status) },
    { label: '已接收字符', value: status?.received_chars ?? report?.char_count ?? 0 },
    { label: '报告文件大小', value: status?.report_size_bytes ? `${formatCount(status.report_size_bytes)} B` : '-' },
    { label: '来源', value: report?.source || status?.report_source_hint || '-' },
    { label: '错误', value: shortText(status?.error || status?.message || '-', 80) },
  ];
}

function explainAutoTunerUpdate(row: AnyRecord): string {
  const param = String(row.param_id || row.key || row.param || '参数');
  const before = row.old_value ?? row.before;
  const after = row.new_value ?? row.after;
  const reason = String(row.reason || row.rule_id || row.metric_key || '未提供原因');
  return `${param} 从 ${formatNumber(before, 4)} 调到 ${formatNumber(after, 4)}，目标是处理：${reason}`;
}

function explainAutoTunerTrial(row: AnyRecord): string {
  const param = String(row.param_id || '未知参数');
  const direction = String(row.direction || row.mode || '试探');
  const status = String(row.status || row.result || '观察中');
  return `${param} 正在做 ${direction} 方向试验，当前状态：${status}`;
}

function autoTunerJobStatusLabel(status: unknown): string {
  const raw = String(status || '').trim().toLowerCase();
  const map: Record<string, string> = {
    queued: '排队中',
    running: '分析中',
    completed: '已完成',
    failed: '失败',
  };
  return map[raw] || raw || '未知';
}

function autoTunerJobIsRunning(job: AnyRecord | null | undefined): boolean {
  const raw = String(job?.status || '').trim().toLowerCase();
  return raw === 'queued' || raw === 'running';
}

function tunerIssueModeLabel(mode: unknown): string {
  const raw = String(mode || '').trim().toLowerCase();
  const map: Record<string, string> = {
    high: '偏高',
    low: '偏低',
    flatline: '过平',
    ok: '正常',
  };
  return map[raw] || raw || '-';
}

function tunerDirectionLabel(direction: unknown, directionText?: unknown): string {
  if (typeof directionText === 'string' && directionText.trim()) {
    const rawText = directionText.trim().toLowerCase();
    if (rawText === 'increase') return '提高';
    if (rawText === 'decrease') return '降低';
    if (rawText === 'keep') return '保持';
  }
  const n = Number(direction);
  if (n > 0) return '提高';
  if (n < 0) return '降低';
  return '保持/观察';
}

function tunerSourceKindLabel(value: unknown): string {
  const raw = String(value || '').trim();
  const map: Record<string, string> = {
    module_config: '模块配置',
    observatory_config: '观测台配置',
    iesm_rule: 'IESM 规则参数',
  };
  return map[raw] || raw || '-';
}

function ruleIdOf(row: AnyRecord | null | undefined): string {
  return String(row?.rule_id || row?.id || '').trim();
}

function targetKeyOf(row: AnyRecord | null | undefined): string {
  return String(row?.key || row?.metric_key || '').trim();
}

function paramIdOf(row: AnyRecord | null | undefined): string {
  return String(row?.param_id || row?.id || '').trim();
}

function isPlainRecord(value: unknown): value is AnyRecord {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function normalizeNumericDraft(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function compactUndefinedFields<T extends AnyRecord>(value: T): T {
  const next: AnyRecord = {};
  Object.entries(value || {}).forEach(([key, val]) => {
    if (val !== undefined && val !== null && val !== '') next[key] = val;
  });
  return next as T;
}

function boundSummary(value: AnyRecord | null | undefined): string {
  if (!value) return '暂无边界';
  return `${formatNumber(value.min_value, 4)} ~ ${formatNumber(value.max_value, 4)}；单步 ${formatNumber(value.max_step_abs, 4)}；量化 ${formatNumber(value.quantum, 4)}`;
}

function llmSuggestionSummary(item: AnyRecord): string {
  const parsed = (item?.parsed_json || {}) as AnyRecord;
  const summary = String(parsed.summary || '').trim();
  if (summary) return summary;
  const findings = asArray<AnyRecord>(parsed.metric_findings).slice(0, 2);
  if (findings.length) {
    return findings
      .map((row) => `${row.metric_key || '指标'} ${tunerIssueModeLabel(row.status)}：${shortText(row.reason || '-', 24)}`)
      .join('；');
  }
  return '该建议没有提供额外摘要。';
}

function llmSuggestionApplyLabel(item: AnyRecord): string {
  const autoApply = (item?.auto_apply_result || {}) as AnyRecord;
  if (!Object.keys(autoApply).length) return '尚未自动落地，仅作为建议保留。';
  if (autoApply.success === false) return `自动落地失败：${shortText(autoApply.error || autoApply.message || '-', 60)}`;
  if (autoApply.success === true) return `已自动落地；结果：${shortText(autoApply.action || autoApply.message || 'success', 60)}`;
  return shortText(autoApply.message || autoApply.status || '已记录自动处理结果。', 60);
}

function SelectionDetailCard({
  title,
  description,
  bullets,
}: {
  title: string;
  description?: string;
  bullets: string[];
}) {
  const visible = bullets.filter((item) => String(item || '').trim());
  return (
    <Card className="selection-detail-card">
      <Text fw={800}>{title}</Text>
      {description ? (
        <Text size="xs" c="dimmed" mt={4}>
          {description}
        </Text>
      ) : null}
      <div className="selection-detail-list" style={{ marginTop: 10 }}>
        {visible.length ? (
          visible.map((item) => (
            <div key={item} className="selection-detail-bullet">
              <Text size="sm">{item}</Text>
            </div>
          ))
        ) : (
          <Text size="sm" c="dimmed">
            当前还没有可解释的条目。
          </Text>
        )}
      </div>
    </Card>
  );
}

function topItemsOfMetricRow(row: MetricRow | null, key: 'pool_er_top5' | 'pool_ev_top5' | 'pool_cp_top5' | 'attention_top5'): AnyRecord[] {
  return asArray<AnyRecord>(row?.[key]);
}

function structureTopItemsOfMetricRow(row: MetricRow | null, key: 'pool_er_top5' | 'pool_ev_top5' | 'pool_cp_top5'): AnyRecord[] {
  const structureKey = key === 'pool_er_top5'
    ? 'pool_er_structure_top5'
    : key === 'pool_ev_top5'
      ? 'pool_ev_structure_top5'
      : 'pool_cp_structure_top5';
  const structureRows = asArray<AnyRecord>(row?.[structureKey]);
  const sameAsRaw = asNumber(row?.[`${structureKey}_same_as_top5`], 0) > 0;
  return structureRows.length || !sameAsRaw ? structureRows : topItemsOfMetricRow(row, key);
}

function topItemDisplay(item: AnyRecord): string {
  return shortDisplayText(item.display || item.display_text || item.ref_object_id || item.item_id || '-', 38);
}

function topItemProvenance(item: AnyRecord): string {
  return shortDisplayText(
    item.context_summary ||
      item.context_ref_object_id ||
      item.context_owner_structure_id ||
      item.growth_source ||
      item.provenance_owner_structure_id ||
      item.source?.origin_id ||
      '无显式激活链',
    24,
  );
}

function activeMetricsRowFromDashboard(dashboard: AnyRecord | null): MetricRow | null {
  const row =
    dashboard?.active_experiment_latest_metrics ||
    dashboard?.active_experiment?.latest_metrics ||
    dashboard?.active_experiment_job?.latest_metrics_preview ||
    dashboard?.active_experiment?.job?.latest_metrics_preview;
  return row && typeof row === 'object' ? (row as MetricRow) : null;
}

function dashboardExperimentJob(dashboard: AnyRecord | null): AnyRecord | null {
  const row = dashboard?.active_experiment_job || dashboard?.active_experiment?.job;
  return row && typeof row === 'object' ? row : null;
}

function actionKindZh(actionKind: unknown): string {
  const key = String(actionKind || '').trim();
  const map: Record<string, string> = {
    recall: '回忆',
    attention_focus_mode: '注意力聚焦模式',
    attention_diverge_mode: '注意力发散模式',
    weather_stub: '天气动作桩',
    teacher_reward_stub: '教师奖励动作桩',
    teacher_punish_stub: '教师惩罚动作桩',
  };
  return map[key] || key || '未命名行动';
}

function liveRowSortValue(row: AnyRecord, sortBy: LiveTopSortMode): number {
  const er = asNumber(row.aggregate_total_er ?? row.er ?? row.total_er ?? row.energy?.er, 0);
  const ev = asNumber(row.aggregate_total_ev ?? row.ev ?? row.total_ev ?? row.energy?.ev, 0);
  if (sortBy === 'er') return er;
  if (sortBy === 'ev') return ev;
  const explicitTotal =
    row.aggregate_total_energy ??
    row.total_energy ??
    row.energy_total ??
    row.weighted_energy ??
    row.energy?.total ??
    row.strength ??
    row.value ??
    row.elapsed_ms;
  const total = asNumber(explicitTotal, er + ev);
  return Number.isFinite(total) ? total : er + ev;
}

function sortLiveRowsByMode(rows: AnyRecord[], sortBy: LiveTopSortMode): AnyRecord[] {
  return rows.slice().sort((left, right) => {
    const primary = liveRowSortValue(right, sortBy) - liveRowSortValue(left, sortBy);
    if (primary) return primary;
    return liveRowSortValue(right, 'total') - liveRowSortValue(left, 'total');
  });
}

function liveRowsFromDashboard(
  dashboard: AnyRecord | null,
  options: { aggregateStateTop?: boolean; topN?: number; sortBy?: LiveTopSortMode } = {},
): AnyRecord[] {
  const sortBy = options.sortBy || 'total';
  const previewRow = activeMetricsRowFromDashboard(dashboard);
  if (previewRow) {
    return sortLiveRowsByMode(rowsFromMetricRow(previewRow, { topN: options.topN || 20 }), sortBy);
  }
  const report = dashboard?.last_report || dashboard || {};
  const stateRows = asArray(
    dashboard?.display_state_snapshot?.top_items ||
      report.final_state?.state_snapshot?.top_items ||
      dashboard?.state_snapshot?.top_items,
  ).map((item) => ({
    ...item,
    row_kind: '状态池',
  }));
  const displayedStateRows = aggregateRowsByDisplay(stateRows, {
    enabled: options.aggregateStateTop !== false,
    topN: options.topN || 20,
    mode: 'display',
    rowKind: '状态池结构波峰',
    hideAtomicFeatureSa: true,
    sortBy,
  });
  return [
    ...displayedStateRows,
    ...asArray(report.cognitive_stitching?.narrative_top_items || report.cognitive_stitching?.actions).map((item) => ({ ...item, row_kind: 'CS审计' })),
    ...asArray(report.cognitive_feeling?.signals).map((item) => ({ ...item, row_kind: 'CFS' })),
    ...asArray(report.action?.executed_actions).map((item) => ({ ...item, row_kind: '行动' })),
    ...asArray(report.observatory?.auto_tune_log || report.auto_tune_log).map((item) => ({ ...item, row_kind: '调参' })),
  ];
}

function cognitivePressureRowsFromDashboard(
  dashboard: AnyRecord | null,
  options: { aggregateStateTop?: boolean; topN?: number } = {},
): AnyRecord[] {
  const previewRow = activeMetricsRowFromDashboard(dashboard);
  if (previewRow) {
    return cognitivePressureRowsFromMetricRow(previewRow, { topN: options.topN || 20 });
  }
  const report = dashboard?.last_report || dashboard || {};
  const stateRows = asArray(
    dashboard?.display_state_snapshot?.cp_top_items ||
      report.final_state?.state_snapshot?.cp_top_items ||
      dashboard?.state_snapshot?.cp_top_items ||
      dashboard?.display_state_snapshot?.top_items ||
      report.final_state?.state_snapshot?.top_items ||
      dashboard?.state_snapshot?.top_items,
  ).map((item) => ({
    ...item,
    row_kind: '认知压结构波峰',
  }));
  return aggregateRowsByDisplay(stateRows, {
    enabled: options.aggregateStateTop !== false,
    topN: options.topN || 20,
    mode: 'display',
    rowKind: '认知压结构波峰',
    hideAtomicFeatureSa: true,
    sortBy: 'cp',
  });
}

function rowsFromMetricRow(row: MetricRow | null, options: { topN?: number } = {}): AnyRecord[] {
  const topN = Math.max(1, Math.floor(Number(options.topN || 20)));
  const withKind = (items: AnyRecord[], rowKind: string, energyKey: 'er' | 'ev' | 'cp' | 'attention') =>
    items.slice(0, topN).map((item, index) => ({
      ...item,
      row_kind: rowKind,
      rank: item.rank ?? index + 1,
      display: item.display || item.display_text || item.ref_object_id || item.item_id || '-',
      total_energy: item.total_energy ?? item.energy_total ?? (asNumber(item.er ?? item.total_er, 0) + asNumber(item.ev ?? item.total_ev, 0)),
      cp: item.cp ?? item.cp_abs ?? item.cognitive_pressure_abs,
      metric_top_energy_key: energyKey,
    }));
  if (!row) return [];
  const cpRows = structureTopItemsOfMetricRow(row, 'pool_cp_top5');
  return [
    ...withKind(structureTopItemsOfMetricRow(row, 'pool_er_top5'), '指标ER结构Top', 'er'),
    ...withKind(structureTopItemsOfMetricRow(row, 'pool_ev_top5'), '指标EV结构Top', 'ev'),
    ...withKind(cpRows, '指标认知压结构Top', 'cp'),
    ...withKind(topItemsOfMetricRow(row, 'attention_top5'), '指标注意 Top', 'attention'),
  ];
}

function cognitivePressureRowsFromMetricRow(row: MetricRow | null, options: { topN?: number } = {}): AnyRecord[] {
  const topN = Math.max(1, Math.floor(Number(options.topN || 20)));
  return structureTopItemsOfMetricRow(row, 'pool_cp_top5')
    .slice(0, topN)
    .map((item, index) => ({
      ...item,
      row_kind: '指标认知压结构Top',
      rank: item.rank ?? index + 1,
      display: item.display || item.display_text || item.ref_object_id || item.item_id || '-',
      total_energy: item.total_energy ?? item.energy_total ?? (asNumber(item.er ?? item.total_er, 0) + asNumber(item.ev ?? item.total_ev, 0)),
      cp: item.cp ?? item.cp_abs ?? item.cognitive_pressure_abs,
      metric_top_energy_key: 'cp',
    }));
}

function monitorInputInfo(dashboard: AnyRecord | null, row: MetricRow | null, selectedRunIsLive: boolean): AnyRecord {
  const livePreviewRow = selectedRunIsLive ? activeMetricsRowFromDashboard(dashboard) : null;
  const effectiveRow = livePreviewRow || row;
  if (!selectedRunIsLive || livePreviewRow) {
    const text = String(row?.input_text_preview ?? row?.input_text ?? '').trim();
    const previewText = String(effectiveRow?.input_text_preview ?? effectiveRow?.input_queue_tick_text_preview ?? effectiveRow?.input_text ?? text).trim();
    const externalCount = asNumber(effectiveRow?.external_sa_count, 0);
    const empty = effectiveRow ? Boolean(effectiveRow.input_is_empty) : !previewText && externalCount <= 0;
    return {
      is_empty: empty,
      label: empty ? '空 tick' : '外源输入',
      text: previewText,
      external_sa_count: externalCount,
    };
  }
  const report = dashboard?.last_report || {};
  const observatory = report.observatory || dashboard?.meta || {};
  const stimulus = report.stimulus || report.sensor || {};
  const text = String(
    observatory.input_text_preview ??
      observatory.input_text ??
      stimulus.input_text_preview ??
      stimulus.input_text ??
      dashboard?.input_text_preview ??
      dashboard?.input_text ??
      '',
  ).trim();
  const externalCount = asNumber(
    report.external_sa_count ??
      report.sensor?.external_sa_count ??
      observatory.external_sa_count ??
      dashboard?.external_sa_count,
    0,
  );
  const empty = Boolean(
    observatory.input_is_empty ??
      stimulus.input_is_empty ??
      dashboard?.input_is_empty ??
      (!text && externalCount <= 0),
  );
  return {
    is_empty: empty,
    label: empty ? '空 tick' : '外源输入',
    text,
    external_sa_count: externalCount,
  };
}

function timingFromMetricRow(row: MetricRow | null): AnyRecord {
  if (!row) return {};
  const timing: AnyRecord = {};
  Object.entries(row).forEach(([key, value]) => {
    if (key.startsWith('timing_') && Number.isFinite(Number(value))) {
      timing[key] = Number(value);
    }
  });
  return timing;
}

type MetricSummary = {
  key: string;
  count: number;
  mean: number;
  min: number;
  max: number;
  median: number;
  latest: number;
  delta: number;
};

function summarizeMetricWindow(rows: MetricRow[], key: string, windowSize: number): MetricSummary | null {
  const slice = asArray<MetricRow>(rows).slice(-Math.max(1, asNumber(windowSize, 40)));
  const values = slice.map((row) => Number(row?.[key])).filter((value) => Number.isFinite(value));
  if (!values.length) return null;
  const sorted = values.slice().sort((a, b) => a - b);
  const latest = values[values.length - 1];
  return {
    key,
    count: values.length,
    mean: values.reduce((sum, value) => sum + value, 0) / values.length,
    min: sorted[0],
    max: sorted[sorted.length - 1],
    median: sorted[Math.floor(sorted.length / 2)],
    latest,
    delta: latest - values[0],
  };
}

function signedNumber(value: unknown, digits = 3): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return `${n >= 0 ? '+' : ''}${formatNumber(n, digits)}`;
}

function insightValue(summary: MetricSummary | null, ratio = false, digits = 3): string {
  if (!summary) return '-';
  return ratio ? formatPercent(summary.latest, 1) : formatNumber(summary.latest, digits);
}

function insightNote(summary: MetricSummary | null, ratio = false, digits = 3): string {
  if (!summary) return '当前运行记录缺少该指标。';
  const meanText = ratio ? formatPercent(summary.mean, 1) : formatNumber(summary.mean, digits);
  const deltaText = ratio ? signedNumber(summary.delta * 100, 1) + '%' : signedNumber(summary.delta, digits);
  return `窗口均值 ${meanText} | 首末变化 ${deltaText}`;
}

function findMetricTarget(config: AnyRecord | null, metricKey: string): AnyRecord | null {
  const targets = asArray<AnyRecord>(config?.metric_targets || config?.config?.metric_targets);
  return targets.find((item) => String(item?.key || '') === metricKey) || null;
}

function buildMetricInsightBundle(rows: MetricRow[], config: AnyRecord | null, tunerState: AnyRecord | null) {
  const windowSize = Math.max(10, asNumber(config?.config?.long_window_ticks ?? config?.long_window_ticks, 40));
  const summary = {
    contextual: summarizeMetricWindow(rows, 'pool_contextual_item_ratio', windowSize),
    explicitContext: summarizeMetricWindow(rows, 'pool_explicit_context_item_ratio', windowSize),
    residualOrigin: summarizeMetricWindow(rows, 'pool_residual_origin_item_ratio', windowSize),
    hdbSameContentMultiContext: summarizeMetricWindow(rows, 'hdb_same_content_multi_context_ratio', windowSize),
    hdbResidualDiff: summarizeMetricWindow(rows, 'hdb_residual_diff_entry_ratio', windowSize),
    poolEvToEr: summarizeMetricWindow(rows, 'pool_ev_to_er_ratio', windowSize),
    inductionPropagatedEv: summarizeMetricWindow(rows, 'induction_propagated_ev_total', windowSize),
    inductionEvFromEr: summarizeMetricWindow(rows, 'induction_ev_from_er_total', windowSize),
    inductionPropagatedRatio: summarizeMetricWindow(rows, 'induction_propagated_target_ratio', windowSize),
    inductionEvFromErRatio: summarizeMetricWindow(rows, 'induction_ev_from_er_ratio', windowSize),
    csCandidates: summarizeMetricWindow(rows, 'cs_candidate_count', windowSize),
    csActions: summarizeMetricWindow(rows, 'cs_action_count', windowSize),
    csLowScoreRejected: summarizeMetricWindow(rows, 'cs_candidate_rejected_low_score_count', windowSize),
    csComponentRejected: summarizeMetricWindow(rows, 'cs_candidate_rejected_component_limit_count', windowSize),
    csNonPositiveRejected: summarizeMetricWindow(rows, 'cs_candidate_rejected_non_positive_edge_count', windowSize),
    csThresholdMargin: summarizeMetricWindow(rows, 'cs_candidate_threshold_margin_mean', windowSize),
    csReplacement: summarizeMetricWindow(rows, 'cs_candidate_replacement_count', windowSize),
    csKeptExisting: summarizeMetricWindow(rows, 'cs_candidate_kept_existing_count', windowSize),
    csRawAccepted: summarizeMetricWindow(rows, 'cs_candidate_raw_accepted_count', windowSize),
    csCreated: summarizeMetricWindow(rows, 'cs_created_count', windowSize),
    csExtended: summarizeMetricWindow(rows, 'cs_extended_count', windowSize),
    csMerged: summarizeMetricWindow(rows, 'cs_merged_count', windowSize),
    csReinforced: summarizeMetricWindow(rows, 'cs_reinforced_count', windowSize),
    stimulusNewStructures: summarizeMetricWindow(rows, 'stimulus_new_structure_count', windowSize),
    timingTotal: summarizeMetricWindow(rows, 'timing_total_logic_ms', windowSize),
    timingStructure: summarizeMetricWindow(rows, 'timing_structure_level_ms', windowSize),
    timingStimulus: summarizeMetricWindow(rows, 'timing_stimulus_level_ms', windowSize),
    timingCache: summarizeMetricWindow(rows, 'timing_cache_neutralization_ms', windowSize),
    timingMaintenance: summarizeMetricWindow(rows, 'timing_maintenance_ms', windowSize),
    timingAttention: summarizeMetricWindow(rows, 'timing_attention_ms', windowSize),
    timingSensor: summarizeMetricWindow(rows, 'timing_sensor_ms', windowSize),
    timingTimeSensor: summarizeMetricWindow(rows, 'timing_time_sensor_ms', windowSize),
    csTiming: summarizeMetricWindow(rows, 'timing_cognitive_stitching_ms', windowSize),
  };

  const maxPair = (a: unknown, b: unknown) => Math.max(asNumber(a, 0), asNumber(b, 0));
  const sourceSupplyHealthy =
    maxPair(summary.contextual?.mean, summary.contextual?.latest) >= 0.14 &&
    (maxPair(summary.residualOrigin?.mean, summary.residualOrigin?.latest) >= 0.08 ||
      maxPair(summary.hdbResidualDiff?.mean, summary.hdbResidualDiff?.latest) >= 0.22);
  const contextBranchingThin = maxPair(summary.hdbSameContentMultiContext?.mean, summary.hdbSameContentMultiContext?.latest) < 0.03;
  const sourceSupplyThin = !sourceSupplyHealthy || contextBranchingThin;

  const meanCandidates = asNumber(summary.csCandidates?.mean, 0);
  const meanActions = asNumber(summary.csActions?.mean, 0);
  const meanLowScoreRejected = asNumber(summary.csLowScoreRejected?.mean, 0);
  const meanComponentRejected = asNumber(summary.csComponentRejected?.mean, 0);
  const meanNonPositiveRejected = asNumber(summary.csNonPositiveRejected?.mean, 0);
  const meanReplacements = asNumber(summary.csReplacement?.mean, 0);
  const meanKeptExisting = asNumber(summary.csKeptExisting?.mean, 0);
  const meanRawAccepted = asNumber(summary.csRawAccepted?.mean, 0);
  const candidateToActionRatio = meanCandidates > 1e-6 ? meanActions / meanCandidates : 0;
  const competitionPressure = (meanReplacements + meanKeptExisting) / Math.max(1e-6, Math.max(meanCandidates, meanRawAccepted, 1));
  const candidateRichButActionStarved = meanCandidates >= 0.8 && meanActions <= 0.05;
  const lowScoreDominant = meanLowScoreRejected >= 0.5 && meanLowScoreRejected >= meanComponentRejected && meanLowScoreRejected >= meanNonPositiveRejected;
  const componentLimitDominant =
    meanComponentRejected >= 0.5 && meanComponentRejected > meanLowScoreRejected && meanComponentRejected >= meanNonPositiveRejected;
  const nonPositiveEdgeDominant =
    meanNonPositiveRejected >= 0.5 && meanNonPositiveRejected > meanLowScoreRejected && meanNonPositiveRejected >= meanComponentRejected;
  const outputTotal =
    asNumber(summary.csCreated?.mean, 0) +
    asNumber(summary.csExtended?.mean, 0) +
    asNumber(summary.csMerged?.mean, 0) +
    asNumber(summary.csReinforced?.mean, 0);

  const expectedMaxFor = (key: string, fallback: number) => Math.max(fallback, asNumber(findMetricTarget(config, key)?.expected_max, fallback));
  const totalMean = asNumber(summary.timingTotal?.mean, 0);
  const timingGroups = [
    { id: 'hdb', label: 'HDB 主链', mean: asNumber(summary.timingStructure?.mean, 0) + asNumber(summary.timingStimulus?.mean, 0), keys: ['timing_structure_level_ms', 'timing_stimulus_level_ms'] },
    { id: 'state_pool', label: '状态池与中和', mean: asNumber(summary.timingCache?.mean, 0) + asNumber(summary.timingMaintenance?.mean, 0), keys: ['timing_cache_neutralization_ms', 'timing_maintenance_ms'] },
    { id: 'attention', label: '注意力', mean: asNumber(summary.timingAttention?.mean, 0), keys: ['timing_attention_ms'] },
    { id: 'sensor', label: '文本感受器', mean: asNumber(summary.timingSensor?.mean, 0), keys: ['timing_sensor_ms'] },
    { id: 'time_sensor', label: '时间感受器', mean: asNumber(summary.timingTimeSensor?.mean, 0), keys: ['timing_time_sensor_ms'] },
    { id: 'cognitive_stitching', label: 'CS 回滚诊断', mean: asNumber(summary.csTiming?.mean, 0), keys: ['timing_cognitive_stitching_ms'] },
  ].map((group) => {
    const share = totalMean > 0 ? group.mean / totalMean : 0;
    const pressure = group.keys.reduce((best, key) => Math.max(best, group.mean / Math.max(1e-6, expectedMaxFor(key, 1))), 0);
    return { ...group, share, pressure, severity: pressure + share * 0.35 };
  });
  timingGroups.sort((a, b) => b.severity - a.severity || b.share - a.share);
  const dominantTimingGroup = timingGroups[0] && (timingGroups[0].share >= 0.3 || timingGroups[0].pressure >= 0.85) ? timingGroups[0] : null;

  const poolEvToErMean = asNumber(summary.poolEvToEr?.mean, 0);
  const propagatedRatioMean = asNumber(summary.inductionPropagatedRatio?.mean, 0);
  const evFromErRatioMean = asNumber(summary.inductionEvFromErRatio?.mean, 0);
  const energySummary =
    poolEvToErMean < 0.98
      ? propagatedRatioMean < 0.35 && evFromErRatioMean < 0.16
        ? 'EV / ER 诊断比值偏低，局部传播与 ER 诱发两条链都偏弱。'
        : propagatedRatioMean < 0.35
          ? 'EV 偏低更像残差局部传播链偏弱。'
          : evFromErRatioMean < 0.16
            ? 'EV 偏低更像现实证据没有有效诱发新预测。'
            : '传播与诱发仍在工作，更像 EV 留存或状态池保活偏薄。'
      : propagatedRatioMean < 0.35
        ? '感应赋能更偏现实重新诱发，沿局部残差链续写偏弱。'
        : '实虚能量关系没有明显理论违和。';

  const csSummary = lowScoreDominant
    ? 'CS 回滚诊断更像低分淘汰主导，应优先审视最低候选分。'
    : componentLimitDominant
      ? 'CS 回滚诊断更像组分上限主导，应优先审视最大组分数。'
      : nonPositiveEdgeDominant
        ? 'CS 回滚诊断更像非正边主导，不宜误降最低分门槛。'
        : candidateRichButActionStarved
          ? '候选已有但动作稀薄，更像阈值、种子能量或事件成熟门槛偏严。'
          : competitionPressure >= 0.65 && asNumber(summary.csThresholdMargin?.mean, 0) >= 0.18
            ? '同签名竞争偏热且阈值余量不低，应考虑适度收紧。'
            : 'CS 回滚诊断当前没有明显异常。';

  const timingSummary = dominantTimingGroup
    ? `主要耗时热点更像 ${dominantTimingGroup.label}，占总耗时 ${formatPercent(dominantTimingGroup.share, 1)}。`
    : '当前没有识别到特别突出的单一耗时热点。';

  const cards = [
    { label: '状态池来源链占比', summary: summary.contextual, ratio: true, note: '诊断 provenance/legacy context 是否仍显著。' },
    { label: '显式来源占比', summary: summary.explicitContext, ratio: true, note: '用于和广义来源链分开读。' },
    { label: '状态池残差来源占比', summary: summary.residualOrigin, ratio: true, note: '残差链对象是否仍活跃。' },
    { label: '同内容多来源占比', summary: summary.hdbSameContentMultiContext, ratio: true, note: '诊断旧多 context 分流，不代表新版身份。' },
    { label: 'EV / ER 诊断比值', summary: summary.poolEvToEr, note: '仅作诊断，不作硬目标。' },
    { label: '局部传播 EV', summary: summary.inductionPropagatedEv, note: '旧预期沿残差链续写。' },
    { label: 'ER 诱发 EV', summary: summary.inductionEvFromEr, note: '现实证据拉起预测。' },
    { label: 'CS 诊断候选', summary: summary.csCandidates, note: '仅显式开启 residual/CS 对照时重点看。' },
    { label: 'CS 诊断动作', summary: summary.csActions, note: `转化率 ${formatPercent(candidateToActionRatio, 1)}` },
    { label: '低分淘汰', summary: summary.csLowScoreRejected, note: '候选是否卡在分数门槛。' },
    { label: '总逻辑耗时', summary: summary.timingTotal, note: timingSummary },
    { label: '注意力耗时', summary: summary.timingAttention, note: '注意力候选与滤波成本。' },
  ];

  const narratives = [
    {
      title: '来源链与残差供给诊断',
      conclusion: sourceSupplyThin
        ? contextBranchingThin
          ? '诊断来源供给偏薄，且同内容多来源分流不足。'
          : '来源链 / 残差供给偏薄。'
        : '来源链与残差供给总体健康。',
      evidence: [
        `状态池来源链：最新 ${insightValue(summary.contextual, true)}，${insightNote(summary.contextual, true)}`,
        `残差来源：最新 ${insightValue(summary.residualOrigin, true)}，${insightNote(summary.residualOrigin, true)}`,
        `HDB 同内容多来源诊断：${insightValue(summary.hdbSameContentMultiContext, true)}；残差局部链接：${insightValue(summary.hdbResidualDiff, true)}`,
      ],
    },
    {
      title: '实虚能量与感应赋能判断',
      conclusion: energySummary,
      evidence: [
        `EV / ER：最新 ${insightValue(summary.poolEvToEr)}，${insightNote(summary.poolEvToEr)}`,
        `局部传播 EV：均值 ${formatNumber(summary.inductionPropagatedEv?.mean, 3)}；ER 诱发 EV：均值 ${formatNumber(summary.inductionEvFromEr?.mean, 3)}`,
        `局部传播目标占比 ${formatPercent(propagatedRatioMean, 1)}；ER 诱发占比 ${formatPercent(evFromErRatioMean, 1)}`,
      ],
    },
    {
      title: 'CS 回滚转化诊断',
      conclusion: csSummary,
      evidence: [
        `候选均值 ${formatNumber(summary.csCandidates?.mean, 3)}；动作均值 ${formatNumber(summary.csActions?.mean, 3)}；转化率 ${formatPercent(candidateToActionRatio, 1)}`,
        `低分淘汰 ${formatNumber(summary.csLowScoreRejected?.mean, 3)}；组分淘汰 ${formatNumber(summary.csComponentRejected?.mean, 3)}；非正边淘汰 ${formatNumber(summary.csNonPositiveRejected?.mean, 3)}`,
        `阈值余量 ${formatNumber(summary.csThresholdMargin?.mean, 3)}；竞争压力 ${formatNumber(competitionPressure, 3)}；产出总量 ${formatNumber(outputTotal, 3)}`,
      ],
    },
    {
      title: '耗时热点归因判断',
      conclusion: timingSummary,
      evidence: [
        `总逻辑耗时：均值 ${formatNumber(summary.timingTotal?.mean, 1)} ms；最新 ${formatNumber(summary.timingTotal?.latest, 1)} ms`,
        `HDB 主链：${formatNumber(timingGroups.find((g) => g.id === 'hdb')?.mean, 1)} ms；状态池与中和：${formatNumber(timingGroups.find((g) => g.id === 'state_pool')?.mean, 1)} ms`,
        `注意力 ${formatNumber(summary.timingAttention?.mean, 1)} ms；文本感受器 ${formatNumber(summary.timingSensor?.mean, 1)} ms；时间感受器 ${formatNumber(summary.timingTimeSensor?.mean, 1)} ms`,
      ],
    },
  ];

  return { windowSize, cards, narratives, timingGroups, summary, tunerState };
}

export function ExperimentPage({ onStatusChange }: ExperimentPageProps) {
  const savedSettings = useMemo(() => loadExperimentPageSettings(), []);
  const initialActiveSection =
    !savedSettings.showDiagnosticCharts && chartSections.find((section) => section.id === savedSettings.activeSection)?.diagnostic
      ? 'overview'
      : savedSettings.activeSection;
  const [datasets, setDatasets] = useState<DatasetItem[]>([]);
  const [selectedDatasetKey, setSelectedDatasetKey] = useState(savedSettings.selectedDatasetKey);
  const [runs, setRuns] = useState<ExperimentRunItem[]>([]);
  const [selectedRunId, setSelectedRunId] = useState(savedSettings.selectedRunId);
  const [manifest, setManifest] = useState<AnyRecord | null>(null);
  const [metrics, setMetrics] = useState<MetricRow[]>([]);
  const [protocol, setProtocol] = useState<AnyRecord | null>(null);
  const [job, setJob] = useState<AnyRecord | null>(
    savedSettings.activeJobId ? { job_id: savedSettings.activeJobId, status: 'queued', stage_label: '正在恢复任务状态' } : null,
  );
  const [experimentJobs, setExperimentJobs] = useState<AnyRecord[]>([]);
  const [backgroundJobs, setBackgroundJobs] = useState<AnyRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [maxTicks, setMaxTicks] = useState<number | ''>(savedSettings.maxTicks);
  const [runAllTicks, setRunAllTicks] = useState(savedSettings.runAllTicks);
  const [resetMode, setResetMode] = useState(savedSettings.resetMode);
  const [cleanRun, setCleanRun] = useState(savedSettings.cleanRun);
  const [autoTune, setAutoTune] = useState(savedSettings.autoTune);
  const [autoTuneShort, setAutoTuneShort] = useState(savedSettings.autoTuneShort);
  const [autoTuneLong, setAutoTuneLong] = useState(savedSettings.autoTuneLong);
  const [exportJson, setExportJson] = useState(savedSettings.exportJson);
  const [exportHtml, setExportHtml] = useState(savedSettings.exportHtml);
  const [timeBasisOverride, setTimeBasisOverride] = useState(savedSettings.timeBasisOverride);
  const [tickIntervalSec, setTickIntervalSec] = useState<number | ''>(savedSettings.tickIntervalSec);
  const [downsampleEvery, setDownsampleEvery] = useState(savedSettings.downsampleEvery);
  const [chartSearch, setChartSearch] = useState(savedSettings.chartSearch);
  const [liveDashboard, setLiveDashboard] = useState<AnyRecord | null>(null);
  const [livePaused, setLivePaused] = useState(false);
  const [liveRefreshMs, setLiveRefreshMs] = useState<number | ''>(savedSettings.liveRefreshMs);
  const [liveTopN, setLiveTopN] = useState<number | ''>(savedSettings.liveTopN);
  const [liveAggregateStateTop, setLiveAggregateStateTop] = useState(savedSettings.liveAggregateStateTop);
  const [liveTopSort, setLiveTopSort] = useState<LiveTopSortMode>(savedSettings.liveTopSort);
  const [importText, setImportText] = useState('');
  const [importName, setImportName] = useState('');
  const [activeSection, setActiveSection] = useState(initialActiveSection);
  const [showDiagnosticCharts, setShowDiagnosticCharts] = useState(savedSettings.showDiagnosticCharts);
  const [autoTunerState, setAutoTunerState] = useState<AnyRecord | null>(null);
  const [datasetPreview, setDatasetPreview] = useState<AnyRecord | null>(null);
  const [datasetExpand, setDatasetExpand] = useState<AnyRecord | null>(null);
  const [llmConfig, setLlmConfig] = useState<AnyRecord | null>(null);
  const [llmConfigDraft, setLlmConfigDraft] = useState('');
  const [llmConfigForm, setLlmConfigForm] = useState<AnyRecord>({});
  const [llmStatus, setLlmStatus] = useState<AnyRecord | null>(null);
  const [llmReport, setLlmReport] = useState<AnyRecord | null>(null);
  const [llmReportExpanded, setLlmReportExpanded] = useState(false);
  const [llmJobs, setLlmJobs] = useState<AnyRecord[]>([]);
  const [selectedLlmReviewJobKey, setSelectedLlmReviewJobKey] = useState('');
  const [autoTunerConfig, setAutoTunerConfig] = useState<AnyRecord | null>(null);
  const [autoTunerConfigDraft, setAutoTunerConfigDraft] = useState('');
  const [autoTunerCatalog, setAutoTunerCatalog] = useState<AnyRecord | null>(null);
  const [autoTunerRules, setAutoTunerRules] = useState<AnyRecord | null>(null);
  const [autoTunerRulesDraft, setAutoTunerRulesDraft] = useState('');
  const [autoTunerAudit, setAutoTunerAudit] = useState<AnyRecord | null>(null);
  const [rollbackPoints, setRollbackPoints] = useState<AnyRecord[]>([]);
  const [autoTunerLlmConfig, setAutoTunerLlmConfig] = useState<AnyRecord | null>(null);
  const [autoTunerLlmDraft, setAutoTunerLlmDraft] = useState('');
  const [autoTunerLlmForm, setAutoTunerLlmForm] = useState<AnyRecord>({});
  const [autoTunerLlmJobs, setAutoTunerLlmJobs] = useState<AnyRecord[]>([]);
  const [autoTunerPrompt, setAutoTunerPrompt] = useState('');
  const [autoTunerParamSearch, setAutoTunerParamSearch] = useState('');
  const [autoTunerRuleSearch, setAutoTunerRuleSearch] = useState('');
  const [metricTargetEdit, setMetricTargetEdit] = useState<AnyRecord | null>(null);
  const [paramBoundEdit, setParamBoundEdit] = useState<AnyRecord | null>(null);
  const [ruleEdit, setRuleEdit] = useState<AnyRecord | null>(null);
  const [ruleEditMode, setRuleEditMode] = useState<'create' | 'edit'>('create');
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [selectedMetricTick, setSelectedMetricTick] = useState<number | ''>('');
  const [tickTopN, setTickTopN] = useState<number | ''>(savedSettings.tickTopN);
  const [datasetLoadPhase, setDatasetLoadPhase] = useState<DatasetLoadPhase>('loading');
  const [datasetLoadMessage, setDatasetLoadMessage] = useState('');

  const selectedDataset = useMemo(
    () => datasets.find((item) => datasetKey(datasetRefOf(item)) === selectedDatasetKey) || null,
    [datasets, selectedDatasetKey],
  );
  const savedActiveJobId = savedSettings.activeJobId;

  useEffect(() => {
    saveExperimentPageSettings({
      selectedDatasetKey,
      selectedRunId,
      activeJobId: job?.job_id && jobIsActive(job) ? String(job.job_id) : '',
      activeSection,
      showDiagnosticCharts,
      resetMode,
      cleanRun,
      maxTicks,
      runAllTicks,
      autoTune,
      autoTuneShort,
      autoTuneLong,
      exportJson,
      exportHtml,
      timeBasisOverride,
      tickIntervalSec,
      downsampleEvery,
      chartSearch,
      liveRefreshMs,
      liveTopN,
      liveAggregateStateTop,
      liveTopSort,
      tickTopN,
    });
  }, [
    selectedDatasetKey,
    selectedRunId,
    job,
    activeSection,
    showDiagnosticCharts,
    resetMode,
    cleanRun,
    maxTicks,
    runAllTicks,
    autoTune,
    autoTuneShort,
    autoTuneLong,
    exportJson,
    exportHtml,
    timeBasisOverride,
    tickIntervalSec,
    downsampleEvery,
    chartSearch,
    liveRefreshMs,
    liveTopN,
    liveAggregateStateTop,
    liveTopSort,
    tickTopN,
  ]);

  async function refreshDatasets(silent = false) {
    setDatasetLoadPhase('loading');
    setDatasetLoadMessage('');
    if (!silent) setBusy(true);
    try {
      const [datasetPayload, protocolPayload] = await Promise.all([api.datasets(), api.datasetProtocol().catch(() => null)]);
      const items = asArray<DatasetItem>(datasetPayload?.items || datasetPayload?.datasets || datasetPayload);
      setDatasets(items);
      if (!selectedDatasetKey && items.length) setSelectedDatasetKey(datasetKey(datasetRefOf(items[0])));
      setProtocol(protocolPayload as AnyRecord | null);
      setDatasetLoadPhase('ready');
      if (!items.length) {
        setDatasetLoadMessage('数据集列表已加载，但当前目录下还没有可选数据集。');
      }
    } catch (error) {
      setDatasets([]);
      if (error instanceof ApiError && typeof error.status === 'undefined') {
        setDatasetLoadPhase('backend_waiting');
        setDatasetLoadMessage('后端正在打开中，请稍等。看到 “AP Observatory Web UI: http://127.0.0.1:8765/” 后会自动恢复。');
      } else {
        setDatasetLoadPhase('error');
        setDatasetLoadMessage(error instanceof Error ? error.message : '读取数据集失败。');
      }
      throw error;
    } finally {
      if (!silent) setBusy(false);
      if (!silent) setInitialLoading(false);
    }
  }

  async function refreshRuns(silent = false) {
    if (!silent) setBusy(true);
    try {
      const payload = await api.experimentRuns(80);
      const items = asArray<ExperimentRunItem>(payload?.items || payload?.runs || payload);
      setRuns(items);
      const rid = selectedRunId || items[0]?.run_id || '';
      if (rid) await selectRun(rid, true, selectedLlmReviewJobKey);
      onStatusChange?.(`${items.length} runs`);
    } finally {
      if (!silent) setBusy(false);
      if (!silent) setInitialLoading(false);
      if (silent) setInitialLoading(false);
    }
  }

  async function refreshJobQueues() {
    const [experimentPayload, backgroundPayload] = await Promise.all([
      api.experimentJobs().catch(() => null),
      api.backgroundJobs().catch(() => null),
    ]);
    const nextExperimentJobs = asArray<AnyRecord>((experimentPayload as AnyRecord | null)?.jobs || experimentPayload);
    const nextBackgroundJobs = asArray<AnyRecord>((backgroundPayload as AnyRecord | null)?.jobs || backgroundPayload);
    setExperimentJobs(nextExperimentJobs);
    setBackgroundJobs(nextBackgroundJobs);
    setJob((prev) => {
      if (prev?.job_id) {
        const same = nextExperimentJobs.find((item) => String(item.job_id || '') === String(prev.job_id || ''));
        if (same) return same;
        if (jobIsActive(prev)) return null;
      }
      return nextExperimentJobs.find((item) => jobIsActive(item)) || prev;
    });
  }

  async function refreshAutoTuner() {
    const [state, config, catalog, rules, audit, rollback, llmCfg, llmJobsPayload] = await Promise.all([
      api.autoTunerState().catch(() => null),
      api.autoTunerConfig().catch(() => null),
      api.autoTunerCatalog().catch(() => null),
      api.autoTunerRules().catch(() => null),
      api.autoTunerAudit().catch(() => null),
      api.autoTunerRollbackPoints().catch(() => null),
      api.autoTunerLlmConfig().catch(() => null),
      api.autoTunerLlmJobs().catch(() => null),
    ]);
    setAutoTunerState(state as AnyRecord | null);
    setAutoTunerConfig(config as AnyRecord | null);
    setAutoTunerConfigDraft(JSON.stringify((config as AnyRecord | null)?.config || config || {}, null, 2));
    setAutoTunerCatalog(catalog as AnyRecord | null);
    setAutoTunerRules(rules as AnyRecord | null);
    setAutoTunerRulesDraft(JSON.stringify((rules as AnyRecord | null)?.rules || {}, null, 2));
    setAutoTunerAudit(audit as AnyRecord | null);
    setRollbackPoints(asArray((rollback as AnyRecord | null)?.points || rollback));
    setAutoTunerLlmConfig(llmCfg as AnyRecord | null);
    setAutoTunerLlmDraft(JSON.stringify((llmCfg as AnyRecord | null)?.config || llmCfg || {}, null, 2));
    setAutoTunerLlmForm(normalizeLlmConfig(llmCfg as AnyRecord | null));
    setAutoTunerLlmJobs(asArray((llmJobsPayload as AnyRecord | null)?.jobs || llmJobsPayload));
    setInitialLoading(false);
  }

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      await Promise.allSettled([
        refreshDatasets(true),
        refreshRuns(true),
        refreshJobQueues(),
        refreshAutoTuner(),
        refreshLlmConfig(),
      ]);
      if (!cancelled) setInitialLoading(false);
    }
    bootstrap().catch(() => {
      if (!cancelled) setInitialLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (datasetLoadPhase !== 'backend_waiting' && datasetLoadPhase !== 'error') return undefined;
    let cancelled = false;
    const timer = window.setInterval(() => {
      if (cancelled) return;
      refreshDatasets(true).catch(() => undefined);
    }, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [datasetLoadPhase]);

  useEffect(() => {
    if (!savedActiveJobId) return;
    let cancelled = false;
    api.experimentJob(savedActiveJobId)
      .then((next) => {
        if (cancelled || !next) return;
        setJob(next as AnyRecord);
      })
      .catch(() => {
        if (!cancelled) setJob(null);
      });
    return () => {
      cancelled = true;
    };
  }, [savedActiveJobId]);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    async function pollQueues() {
      if (inFlight) return;
      inFlight = true;
      await refreshJobQueues().catch(() => undefined);
      inFlight = false;
    }
    pollQueues().catch(() => undefined);
    const timer = window.setInterval(() => {
      if (!cancelled) pollQueues().catch(() => undefined);
    }, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!job?.job_id) return;
    const timer = window.setInterval(async () => {
      const next = await api.experimentJob(String(job.job_id)).catch(() => null);
      if (next) setJob(next);
      const status = String(next?.status || '');
      if (['completed', 'failed', 'cancelled', 'stopped_max_ticks'].includes(status)) {
        window.clearInterval(timer);
        await refreshRuns(true);
        await refreshJobQueues().catch(() => undefined);
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [job?.job_id]);

  useEffect(() => {
    if (!job?.job_id || String(job.stage_label || '') !== '正在恢复任务状态') return;
    let cancelled = false;
    api.experimentJob(String(job.job_id))
      .then((next) => {
        if (!cancelled && next) setJob(next);
      })
      .catch(() => {
        if (!cancelled) setJob(null);
      });
    return () => {
      cancelled = true;
    };
  }, [job?.job_id, job?.stage_label]);

  useEffect(() => {
    if (!selectedRunId) return undefined;
    if (!llmStatusIsRunning(llmStatus)) return undefined;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      if (cancelled) return;
      const [statusPayload, reportPayload, jobsPayload] = await Promise.all([
        api.llmReviewStatus(selectedRunId).catch(() => null),
        api.llmReviewReport(selectedRunId).catch(() => null),
        api.llmReviewJobs().catch(() => null),
      ]);
      if (cancelled) return;
      if (statusPayload) setLlmStatus(statusPayload as AnyRecord);
      if (reportPayload) setLlmReport(reportPayload as AnyRecord);
      if (jobsPayload) {
        const nextJobs = llmReviewJobsFromPayload(jobsPayload);
        setLlmJobs(nextJobs);
        const picked = pickLlmReviewJobForRun(nextJobs, selectedRunId, selectedLlmReviewJobKey);
        setSelectedLlmReviewJobKey(picked ? llmReviewJobKey(picked) : '');
      }
      if (!llmStatusIsRunning(statusPayload as AnyRecord | null)) {
        window.clearInterval(timer);
      }
    }, 900);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedRunId, selectedLlmReviewJobKey, llmStatus]);

  useEffect(() => {
    const active = autoTunerLlmJobs.find((jobItem) => autoTunerJobIsRunning(jobItem));
    if (!active?.job_id) return undefined;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      if (cancelled) return;
      const jobsPayload = await api.autoTunerLlmJobs().catch(() => null);
      if (cancelled || !jobsPayload) return;
      const nextJobs = asArray((jobsPayload as AnyRecord | null)?.jobs || jobsPayload);
      setAutoTunerLlmJobs(nextJobs);
      if (!nextJobs.some((jobItem) => autoTunerJobIsRunning(jobItem))) {
        window.clearInterval(timer);
        await refreshAutoTuner().catch(() => undefined);
      }
    }, 1200);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [autoTunerLlmJobs]);

  useEffect(() => {
    if (livePaused) return;
    let cancelled = false;
    let inFlight = false;
    let lastTick = asNumber(liveDashboard?.tick_counter ?? liveDashboard?.meta?.tick_counter, -1);
    async function tickLive() {
      if (inFlight) return;
      inFlight = true;
      const payload = await api.experimentLivePreview().catch(() => null);
      inFlight = false;
      if (!cancelled && payload) {
        const nextTick = asNumber((payload as AnyRecord)?.tick_counter ?? (payload as AnyRecord)?.meta?.tick_counter, -1);
        const nextPreviewTick = asNumber(activeMetricsRowFromDashboard(payload as AnyRecord)?.tick_index, -1);
        const lastPreviewTick = asNumber(activeMetricsRowFromDashboard(liveDashboard)?.tick_index, -1);
        const nextJobUpdated = asNumber((payload as AnyRecord)?.active_experiment_job?.updated_at_ms, 0);
        const lastJobUpdated = asNumber(liveDashboard?.active_experiment_job?.updated_at_ms, 0);
        if (nextTick !== lastTick || nextTick < 0 || nextPreviewTick !== lastPreviewTick || nextJobUpdated !== lastJobUpdated) {
          lastTick = nextTick;
          setLiveDashboard(payload as AnyRecord);
        }
      }
    }
    tickLive().catch(() => undefined);
    const timer = window.setInterval(() => tickLive().catch(() => undefined), Math.max(250, Number(liveRefreshMs) || 750));
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job?.latest_metrics_preview, job?.latest_metrics_tick_index, livePaused, liveRefreshMs]);

  async function selectRun(runId: string, silent = false, preferredLlmJobKey = '') {
    if (!runId) return;
    if (!silent) setBusy(true);
    try {
      setSelectedRunId(runId);
      const [manifestPayload, metricPayload, statusPayload, reportPayload, jobsPayload] = await Promise.all([
        api.runManifest(runId).catch(() => null),
        api.runMetrics(runId, downsampleEvery).catch(() => null),
        api.llmReviewStatus(runId).catch(() => null),
        api.llmReviewReport(runId).catch(() => null),
        api.llmReviewJobs().catch(() => null),
      ]);
      if (manifestPayload) {
        setManifest((prev) => ({ ...(prev || {}), ...(manifestPayload as AnyRecord) }));
      } else {
        const relatedJob = experimentJobs.find((item) => String(item.run_id || '') === runId);
        setManifest((prev) => ({
          ...(prev || {}),
          run_id: runId,
          status: relatedJob?.status || 'waiting',
          dataset_id: relatedJob?.dataset_id,
          tick_done: relatedJob?.tick_done,
          tick_planned: relatedJob?.tick_planned,
          background_job: relatedJob || prev?.background_job,
        }));
      }
      const nextMetrics = asArray<MetricRow>(metricPayload?.rows || metricPayload?.items || metricPayload);
      setMetrics(nextMetrics);
      if (nextMetrics.length) {
        const latestTick = nextMetrics[nextMetrics.length - 1]?.tick_index ?? nextMetrics[nextMetrics.length - 1]?.tick;
        setSelectedMetricTick(asNumber(latestTick, 0));
      }
      setLlmStatus(statusPayload as AnyRecord | null);
      setLlmReport(reportPayload as AnyRecord | null);
      const nextJobs = llmReviewJobsFromPayload(jobsPayload);
      setLlmJobs(nextJobs);
      const picked = pickLlmReviewJobForRun(nextJobs, runId, preferredLlmJobKey);
      setSelectedLlmReviewJobKey(picked ? llmReviewJobKey(picked) : '');
    } finally {
      if (!silent) setBusy(false);
    }
  }

  async function startRun() {
    const ref = datasetRefOf(selectedDataset);
    if (!ref) return;
    if (cleanRun) {
      const ok = window.confirm('纯净运行会在启动前清空 HDB、状态池、传感器残响、注意力/行动/时间感受运行态和观测台 tick 计数。确认要先清空所有数据再运行吗？');
      if (!ok) return;
    }
    setBusy(true);
    try {
      const payload = await api.startExperiment(ref, {
        reset_mode: cleanRun ? 'clear_all' : resetMode,
        clean_run: cleanRun,
        export_json: exportJson,
        export_html: exportHtml,
        max_ticks: runAllTicks || maxTicks === '' ? null : Number(maxTicks),
        auto_tune_enabled: autoTune,
        auto_tune_short_term: autoTuneShort,
        auto_tune_long_term: autoTuneLong,
        time_sensor_time_basis: timeBasisOverride.trim() || null,
        tick_interval_sec: tickIntervalSec === '' ? null : Number(tickIntervalSec),
      });
      setJob(payload);
      await refreshJobQueues().catch(() => undefined);
      await refreshRuns(true).catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  async function stopRun() {
    if (!job?.job_id) return;
    setBusy(true);
    try {
      const payload = await api.stopExperiment(String(job.job_id));
      if (payload) setJob(payload as AnyRecord);
      await refreshJobQueues().catch(() => undefined);
      setFeedback({ kind: 'ok', message: '已请求停止当前数据集任务。' });
    } finally {
      setBusy(false);
    }
  }

  async function shutdownProcess() {
    const ok = window.confirm('关闭当前观测台 Web 进程？关闭后页面会断开，需要重新启动 bat 或命令。');
    if (!ok) return;
    setBusy(true);
    try {
      await api.shutdown();
      setFeedback({ kind: 'warn', message: '已请求关闭观测台进程，页面很快会断开。' });
    } finally {
      setBusy(false);
    }
  }

  async function restartProcess() {
    const ok = window.confirm('重启当前观测台 Web 进程？页面会短暂断开，稍后可刷新 /next/。');
    if (!ok) return;
    setBusy(true);
    try {
      await api.restart();
      setFeedback({ kind: 'ok', message: '已请求重启观测台进程，请等待几秒后刷新页面。' });
    } finally {
      setBusy(false);
    }
  }

  async function importDataset() {
    if (!importText.trim()) return;
    setBusy(true);
    try {
      await api.importDataset(importName.trim(), 'yaml', importText);
      setImportText('');
      await refreshDatasets(true);
    } finally {
      setBusy(false);
    }
  }

  async function previewDataset() {
    const ref = datasetRefOf(selectedDataset);
    if (!ref) return;
    setBusy(true);
    try {
      const payload = await api.previewDataset(ref, 48);
      setDatasetPreview(payload);
      setFeedback({ kind: 'ok', message: '数据集预览已加载。' });
    } finally {
      setBusy(false);
    }
  }

  async function expandDataset() {
    const ref = datasetRefOf(selectedDataset);
    if (!ref) return;
    setBusy(true);
    try {
      const payload = await api.expandDataset(ref, 120);
      setDatasetExpand(payload);
      setFeedback({ kind: 'ok', message: '数据集已展开为 JSONL，路径见详情。' });
    } finally {
      setBusy(false);
    }
  }

  async function deleteSelectedRun() {
    if (!selectedRunId) return;
    const ok = window.confirm(`删除运行记录 ${selectedRunId}？该操作会修改本地实验输出。`);
    if (!ok) return;
    setBusy(true);
    try {
      await api.deleteRun(selectedRunId);
      setSelectedRunId('');
      setSelectedLlmReviewJobKey('');
      setManifest(null);
      setMetrics([]);
      setLlmStatus(null);
      setLlmReport(null);
      await refreshRuns(true);
    } finally {
      setBusy(false);
    }
  }

  async function clearAllRuns() {
    if (!runs.length) return;
    const ok = window.confirm(`清空全部 ${runs.length} 条运行记录？该操作会删除本地历史实验输出，且不可撤销。`);
    if (!ok) return;
    setBusy(true);
    try {
      await api.clearRuns();
      setRuns([]);
      setSelectedRunId('');
      setSelectedLlmReviewJobKey('');
      setManifest(null);
      setMetrics([]);
      setLlmStatus(null);
      setLlmReport(null);
      await refreshRuns(true);
    } finally {
      setBusy(false);
    }
  }

  async function refreshLlmConfig() {
    const payload = await api.llmReviewConfig();
    const form = normalizeLlmConfig(payload as AnyRecord | null);
    setLlmConfig(payload);
    setLlmConfigForm(form);
    setLlmConfigDraft(JSON.stringify({ ...(payload?.config || payload || {}), ...form, api_key: '' }, null, 2));
  }

  async function saveLlmConfig() {
    const ok = window.confirm('保存 LLM 审查配置？配置中可能包含服务地址等本地敏感设置。');
    if (!ok) return;
    const base = JSON.parse(llmConfigDraft || '{}');
    const config = {
      ...base,
      ...llmConfigForm,
    };
    if (!String(config.api_key || '').trim()) delete config.api_key;
    const payload = await api.saveLlmReviewConfig(config);
    const form = normalizeLlmConfig(payload as AnyRecord | null);
    setLlmConfig(payload);
    setLlmConfigForm(form);
    setLlmConfigDraft(JSON.stringify({ ...(payload?.config || payload || {}), ...form, api_key: '' }, null, 2));
    setFeedback({ kind: 'ok', message: 'LLM 审查配置已保存。' });
  }

  function patchLlmConfigForm(key: string, value: unknown) {
    setLlmConfigForm((prev) => {
      const next = { ...prev, [key]: value };
      setLlmConfigDraft(JSON.stringify(next, null, 2));
      return next;
    });
  }

  async function startReview(force = false) {
    if (!selectedRunId) return;
    const ok = window.confirm(force ? '强制重新启动大模型审查？' : '启动大模型审查任务？');
    if (!ok) return;
    const payload = await api.startLlmReview(selectedRunId, force);
    const nextJobKey = llmReviewJobKey(payload as AnyRecord);
    if (nextJobKey) setSelectedLlmReviewJobKey(nextJobKey);
    setLlmJobs((prev) => [payload, ...prev]);
    await refreshReview(nextJobKey);
    setFeedback({ kind: 'ok', message: 'LLM 审查任务已提交。' });
  }

  async function refreshReview(preferredLlmJobKey = selectedLlmReviewJobKey) {
    if (!selectedRunId) return;
    const [statusPayload, reportPayload, jobsPayload] = await Promise.all([
      api.llmReviewStatus(selectedRunId).catch(() => null),
      api.llmReviewReport(selectedRunId).catch(() => null),
      api.llmReviewJobs().catch(() => null),
    ]);
    setLlmStatus(statusPayload as AnyRecord | null);
    setLlmReport(reportPayload as AnyRecord | null);
    const nextJobs = llmReviewJobsFromPayload(jobsPayload);
    setLlmJobs(nextJobs);
    const picked = pickLlmReviewJobForRun(nextJobs, selectedRunId, preferredLlmJobKey);
    setSelectedLlmReviewJobKey(picked ? llmReviewJobKey(picked) : '');
  }

  async function copyLlmReport() {
    const text = String(llmReport?.text || '');
    if (!text) return;
    await navigator.clipboard?.writeText(text);
    setFeedback({ kind: 'ok', message: 'LLM 审查报告已复制到剪贴板。' });
  }

  function downloadLlmReport() {
    const text = String(llmReport?.text || '');
    if (!text) return;
    downloadText(`${selectedRunId || 'run'}_llm_review.md`, text);
    setFeedback({ kind: 'ok', message: 'LLM 审查报告已生成下载。' });
  }

  async function saveAutoTunerConfig() {
    const ok = window.confirm('保存 AutoTuner 配置？');
    if (!ok) return;
    const config = JSON.parse(autoTunerConfigDraft || '{}');
    const payload = await api.saveAutoTunerConfig(config);
    setAutoTunerConfig(payload);
    setAutoTunerConfigDraft(JSON.stringify(payload?.config || payload || {}, null, 2));
    setFeedback({ kind: 'ok', message: 'AutoTuner 配置已保存。' });
  }

  function currentAutoTunerConfigDraft(): AnyRecord {
    try {
      const parsed = JSON.parse(autoTunerConfigDraft || '{}');
      return isPlainRecord(parsed) ? parsed : {};
    } catch {
      return { ...((autoTunerConfig?.config || autoTunerConfig || {}) as AnyRecord) };
    }
  }

  async function saveAutoTunerConfigPatch(patch: AnyRecord, successMessage: string) {
    const base = currentAutoTunerConfigDraft();
    const payload = await api.saveAutoTunerConfig({ ...base, ...patch });
    setAutoTunerConfig(payload);
    setAutoTunerConfigDraft(JSON.stringify(payload?.config || payload || {}, null, 2));
    setFeedback({ kind: 'ok', message: successMessage });
    await refreshAutoTuner();
    return payload as AnyRecord;
  }

  async function saveAutoTunerRules() {
    const ok = window.confirm('保存 AutoTuner 规则设置？');
    if (!ok) return;
    const rules = JSON.parse(autoTunerRulesDraft || '{}');
    const payload = await api.saveAutoTunerRules(rules);
    setAutoTunerRules(payload);
    setAutoTunerRulesDraft(JSON.stringify(payload?.rules || payload || {}, null, 2));
    setFeedback({ kind: 'ok', message: 'AutoTuner 规则已保存。' });
  }

  function currentAutoTunerRulesDraft(): AnyRecord {
    try {
      const parsed = JSON.parse(autoTunerRulesDraft || '{}');
      return isPlainRecord(parsed) ? parsed : {};
    } catch {
      return { ...((autoTunerRules?.rules || autoTunerRules || {}) as AnyRecord) };
    }
  }

  async function saveAutoTunerRulesPatch(patch: AnyRecord, successMessage: string) {
    const base = currentAutoTunerRulesDraft();
    const payload = await api.saveAutoTunerRules({ ...base, ...patch });
    setAutoTunerRules(payload);
    setAutoTunerRulesDraft(JSON.stringify(payload?.rules || payload || {}, null, 2));
    setFeedback({ kind: 'ok', message: successMessage });
    await refreshAutoTuner();
    return payload as AnyRecord;
  }

  function patchAutoTunerRulesDraft(updater: (rules: AnyRecord) => AnyRecord) {
    const parsed = JSON.parse(autoTunerRulesDraft || '{}');
    const next = updater(parsed && typeof parsed === 'object' ? parsed : {});
    setAutoTunerRulesDraft(JSON.stringify(next, null, 2));
    setAutoTunerRules((prev) => ({ ...(prev || {}), rules: next }));
  }

  async function saveAutoTunerRuleToggle(ruleId: string, field: 'disabled_rule_ids' | 'protected_rule_ids') {
    if (!ruleId) return;
    const rules = currentAutoTunerRulesDraft();
    const current = new Set(asArray<string>(rules[field]).map(String));
    if (current.has(ruleId)) current.delete(ruleId);
    else current.add(ruleId);
    await saveAutoTunerRulesPatch(
      { [field]: Array.from(current).sort() },
      field === 'disabled_rule_ids' ? '规则启用/禁用状态已保存。' : '规则保护状态已保存。',
    );
  }

  function metricTargetDefaultsMap(): Record<string, AnyRecord> {
    return Object.fromEntries(
      asArray<AnyRecord>(autoTunerConfig?.metric_target_defaults || autoTunerCatalog?.metric_defaults).map((item) => [targetKeyOf(item), item]),
    );
  }

  function metricTargetOverridesMap(): Record<string, AnyRecord> {
    return Object.fromEntries(asArray<AnyRecord>(autoTunerConfig?.metric_target_overrides).map((item) => [targetKeyOf(item), item]));
  }

  function openMetricTargetEditor(row: AnyRecord) {
    const key = targetKeyOf(row);
    const defaults = metricTargetDefaultsMap()[key] || {};
    const override = metricTargetOverridesMap()[key] || {};
    const draft = {
      ...row,
      ...override,
      key,
      __default: defaults,
      __hasOverride: Boolean(Object.keys(override).length),
    };
    setMetricTargetEdit(draft);
    setManifest((prev) => ({ ...(prev || {}), auto_tuner_selected: row }));
  }

  function patchMetricTargetEdit(key: string, value: unknown) {
    setMetricTargetEdit((prev) => ({ ...(prev || {}), [key]: value }));
  }

  async function saveMetricTargetOverride() {
    if (!metricTargetEdit) return;
    const key = targetKeyOf(metricTargetEdit);
    if (!key) {
      setFeedback({ kind: 'warn', message: '指标 key 为空，无法保存。' });
      return;
    }
    const overrides = metricTargetOverridesMap();
    const nextItem: AnyRecord = { key };
    METRIC_TARGET_FIELDS.forEach((field) => {
      if (metricTargetEdit[field] !== undefined && metricTargetEdit[field] !== null && metricTargetEdit[field] !== '') {
        nextItem[field] = field === 'high_band_max_run'
          ? Math.round(normalizeNumericDraft(metricTargetEdit[field], 0))
          : normalizeNumericDraft(metricTargetEdit[field], 0);
      }
    });
    overrides[key] = nextItem;
    await saveAutoTunerConfigPatch({ metric_targets: Object.values(overrides) }, '指标目标覆盖值已保存。');
    setMetricTargetEdit((prev) => prev ? { ...prev, __hasOverride: true } : prev);
  }

  function applyMetricTargetRecommendedToDraft() {
    if (!metricTargetEdit) return;
    const defaults = metricTargetEdit.__default || metricTargetDefaultsMap()[targetKeyOf(metricTargetEdit)] || {};
    setMetricTargetEdit((prev) => ({ ...(prev || {}), ...defaults }));
  }

  async function resetMetricTargetOverride() {
    if (!metricTargetEdit) return;
    const key = targetKeyOf(metricTargetEdit);
    if (!key) return;
    const overrides = metricTargetOverridesMap();
    delete overrides[key];
    await saveAutoTunerConfigPatch({ metric_targets: Object.values(overrides) }, '指标目标已恢复推荐值。');
    const defaults = metricTargetDefaultsMap()[key] || {};
    setMetricTargetEdit((prev) => prev ? { ...prev, ...defaults, __hasOverride: false, __default: defaults } : prev);
  }

  function paramBoundRecommendationsMap(): Record<string, AnyRecord> {
    return {
      ...((autoTunerCatalog?.param_bounds || {}) as AnyRecord),
      ...((autoTunerCatalog?.param_bound_recommendations || {}) as AnyRecord),
    };
  }

  function paramBoundOverridesMap(): Record<string, AnyRecord> {
    return { ...((autoTunerConfig?.param_bounds || {}) as AnyRecord) };
  }

  function effectiveParamBound(paramId: string): AnyRecord | null {
    return paramBoundOverridesMap()[paramId] || paramBoundRecommendationsMap()[paramId] || null;
  }

  function openParamBoundEditor(row: AnyRecord) {
    const pid = paramIdOf(row);
    const recommended = paramBoundRecommendationsMap()[pid] || {};
    const override = paramBoundOverridesMap()[pid] || {};
    const effective = effectiveParamBound(pid) || {};
    setParamBoundEdit({
      param_id: pid,
      ...effective,
      ...override,
      __param: row,
      __recommended: recommended,
      __hasOverride: Boolean(Object.keys(override).length),
    });
    setManifest((prev) => ({ ...(prev || {}), auto_tuner_selected_param: row, param_bounds: effective }));
  }

  function patchParamBoundEdit(key: string, value: unknown) {
    setParamBoundEdit((prev) => ({ ...(prev || {}), [key]: value }));
  }

  async function saveParamBoundOverride() {
    if (!paramBoundEdit) return;
    const pid = String(paramBoundEdit.param_id || '').trim();
    if (!pid) {
      setFeedback({ kind: 'warn', message: '参数 id 为空，无法保存。' });
      return;
    }
    const nextBounds = paramBoundOverridesMap();
    nextBounds[pid] = {
      min_value: normalizeNumericDraft(paramBoundEdit.min_value, 0),
      max_value: normalizeNumericDraft(paramBoundEdit.max_value, 0),
      max_step_abs: normalizeNumericDraft(paramBoundEdit.max_step_abs, 0),
      quantum: normalizeNumericDraft(paramBoundEdit.quantum, 0),
    };
    await saveAutoTunerConfigPatch({ param_bounds: nextBounds }, '参数边界覆盖值已保存。');
    setParamBoundEdit((prev) => prev ? { ...prev, __hasOverride: true } : prev);
  }

  function applyParamRecommendedToDraft() {
    if (!paramBoundEdit) return;
    const recommended = paramBoundEdit.__recommended || paramBoundRecommendationsMap()[String(paramBoundEdit.param_id || '')] || {};
    setParamBoundEdit((prev) => ({ ...(prev || {}), ...recommended }));
  }

  async function resetParamBoundOverride() {
    if (!paramBoundEdit) return;
    const pid = String(paramBoundEdit.param_id || '').trim();
    if (!pid) return;
    const nextBounds = paramBoundOverridesMap();
    delete nextBounds[pid];
    await saveAutoTunerConfigPatch({ param_bounds: nextBounds }, '参数边界已恢复推荐值。');
    const recommended = paramBoundRecommendationsMap()[pid] || {};
    setParamBoundEdit((prev) => prev ? { ...prev, ...recommended, __hasOverride: false, __recommended: recommended } : prev);
  }

  function createRuleDraft(seed?: AnyRecord | null): AnyRecord {
    const selectedMetric = targetKeyOf(selectedTarget) || String(seed?.metric_key || '').trim() || String(asArray<AnyRecord>(metricTargets)[0]?.key || '');
    const selectedPid = paramIdOf(selectedParam) || String(seed?.param_id || '').trim() || String(autoTunerParams[0]?.param_id || '');
    const sourceId = ruleIdOf(seed);
    return {
      id: sourceId && !String(sourceId).startsWith('custom.') ? `custom.copy.${Date.now()}` : sourceId || `custom.ui.${Date.now()}`,
      title: seed?.title ? `自定义：${seed.title}` : '新的自定义调参规则',
      description: seed?.description || '通过前端工作台创建，用于在指定指标偏离时小步调整目标参数。',
      enabled: Boolean(seed?.enabled ?? true),
      metric_key: selectedMetric,
      issue_mode: seed?.issue_mode || 'high',
      param_id: selectedPid,
      direction: Number(seed?.direction || -1) < 0 ? -1 : 1,
      step_scale: normalizeNumericDraft(seed?.step_scale, 0.35),
      min_severity: normalizeNumericDraft(seed?.min_severity, 0.05),
      cooldown_ticks: Math.round(normalizeNumericDraft(seed?.cooldown_ticks, 0)),
      protect_from_llm: Boolean(seed?.protect_from_llm || seed?.protected),
      origin: seed?.origin || 'ui_manual',
      status: seed?.status || 'active',
    };
  }

  function openRuleEditor(row?: AnyRecord | null, mode: 'create' | 'edit' = 'edit') {
    const rid = ruleIdOf(row);
    const isCustom = String(row?.rule_source || row?.source || '').toLowerCase().includes('custom') || String(row?.rule_source || '') === '自定义';
    const draft = mode === 'create' || !isCustom ? createRuleDraft(row || null) : createRuleDraft({ ...row, id: rid });
    if (mode === 'edit' && isCustom) draft.id = rid;
    setRuleEdit(draft);
    setRuleEditMode(mode === 'edit' && isCustom ? 'edit' : 'create');
    if (row) setManifest((prev) => ({ ...(prev || {}), auto_tuner_selected_rule: row }));
  }

  function patchRuleEdit(key: string, value: unknown) {
    setRuleEdit((prev) => ({ ...(prev || {}), [key]: value }));
  }

  async function saveCustomRuleDraft() {
    if (!ruleEdit) return;
    const rid = String(ruleEdit.id || '').trim();
    if (!rid || !String(ruleEdit.metric_key || '').trim() || !String(ruleEdit.param_id || '').trim()) {
      setFeedback({ kind: 'warn', message: '规则 id、目标指标和目标参数都必须填写。' });
      return;
    }
    const rules = currentAutoTunerRulesDraft();
    const existing = asArray<AnyRecord>(rules.custom_rules);
    const nextRule = compactUndefinedFields({
      id: rid,
      title: String(ruleEdit.title || rid),
      description: String(ruleEdit.description || ''),
      enabled: Boolean(ruleEdit.enabled ?? true),
      metric_key: String(ruleEdit.metric_key || '').trim(),
      issue_mode: String(ruleEdit.issue_mode || 'high').trim(),
      param_id: String(ruleEdit.param_id || '').trim(),
      direction: Number(ruleEdit.direction) < 0 ? -1 : 1,
      step_scale: normalizeNumericDraft(ruleEdit.step_scale, 0.35),
      min_severity: normalizeNumericDraft(ruleEdit.min_severity, 0.05),
      cooldown_ticks: Math.round(normalizeNumericDraft(ruleEdit.cooldown_ticks, 0)),
      protect_from_llm: Boolean(ruleEdit.protect_from_llm),
      origin: String(ruleEdit.origin || 'ui_manual'),
      status: String(ruleEdit.status || 'active'),
      source_suggestion_path: ruleEdit.source_suggestion_path,
      applied_at_ms: ruleEdit.applied_at_ms,
      evaluation_runs: ruleEdit.evaluation_runs,
    });
    const withoutSame = existing.filter((item) => String(item.id || '').trim() !== rid);
    await saveAutoTunerRulesPatch({ custom_rules: [...withoutSame, nextRule] }, '自定义调参规则已保存。');
    setRuleEdit(nextRule);
    setRuleEditMode('edit');
  }

  async function deleteCustomRule(ruleId?: string) {
    const rid = String(ruleId || ruleEdit?.id || '').trim();
    if (!rid) return;
    const ok = window.confirm(`删除自定义规则 ${rid}？内建/生成规则不会被删除，只会删除 custom_rules 中的条目。`);
    if (!ok) return;
    const rules = currentAutoTunerRulesDraft();
    const nextCustom = asArray<AnyRecord>(rules.custom_rules).filter((item) => String(item.id || '').trim() !== rid);
    const disabled = asArray<string>(rules.disabled_rule_ids).map(String).filter((id) => id !== rid);
    const protectedIds = asArray<string>(rules.protected_rule_ids).map(String).filter((id) => id !== rid);
    await saveAutoTunerRulesPatch(
      { custom_rules: nextCustom, disabled_rule_ids: disabled, protected_rule_ids: protectedIds },
      '自定义调参规则已删除。',
    );
    if (String(ruleEdit?.id || '') === rid) setRuleEdit(null);
  }

  async function rollbackAutoTuner(pointId: string) {
    const ok = window.confirm(`回滚到 ${pointId}？这会修改本地调参持久化参数。`);
    if (!ok) return;
    const payload = await api.autoTunerRollback(pointId);
    setFeedback({ kind: 'ok', message: '回滚请求已完成，结果见 Inspector。' });
    setManifest((prev) => ({ ...(prev || {}), last_rollback_result: payload }));
    await refreshAutoTuner();
  }

  async function saveAutoTunerLlmConfig() {
    const ok = window.confirm('保存 AutoTuner LLM 配置？配置中可能包含服务地址等本地敏感设置。');
    if (!ok) return;
    const base = JSON.parse(autoTunerLlmDraft || '{}');
    const config = {
      ...base,
      ...autoTunerLlmForm,
    };
    if (!String(config.api_key || '').trim()) delete config.api_key;
    const payload = await api.saveAutoTunerLlmConfig(config);
    setAutoTunerLlmConfig(payload);
    setAutoTunerLlmDraft(JSON.stringify(payload?.config || payload || {}, null, 2));
    setAutoTunerLlmForm(normalizeLlmConfig(payload as AnyRecord | null));
    setFeedback({ kind: 'ok', message: 'AutoTuner LLM 配置已保存。' });
  }

  function patchAutoTunerLlmForm(key: string, value: unknown) {
    setAutoTunerLlmForm((prev) => {
      const next = { ...prev, [key]: value };
      setAutoTunerLlmDraft(JSON.stringify(next, null, 2));
      return next;
    });
  }

  async function startAutoTunerAnalyze() {
    if (!selectedRunId) {
      setFeedback({ kind: 'warn', message: '请先在左侧运行记录中选择一个 run，再启动 AutoTuner 的 LLM 分析。' });
      return;
    }
    const payload = await api.startAutoTunerLlmAnalyze(selectedRunId, autoTunerPrompt, []);
    setAutoTunerLlmJobs((prev) => [payload, ...prev]);
    setFeedback({ kind: 'ok', message: 'AutoTuner LLM 分析任务已提交。' });
  }

  const runColumns = useMemo<ColumnDef<ExperimentRunItem>[]>(
    () => [
      {
        header: 'Run',
        cell: ({ row }) => (
          <div>
            <Text size="sm" fw={700}>{shortText(row.original.run_id || '-', 34)}</Text>
            {row.original.job_id ? <Text size="xs" c="dimmed">任务 {shortText(row.original.job_id, 34)}</Text> : null}
          </div>
        ),
      },
      {
        header: '状态',
        cell: ({ row }) => (
          <div>
            <Badge variant="light">{experimentStageLabel(row.original.job_stage || row.original.status, row.original.status)}</Badge>
            {row.original.job_stage_label ? <Text size="xs" c={row.original.lock_waiting ? 'orange' : 'dimmed'}>{shortText(row.original.job_stage_label, 42)}</Text> : null}
          </div>
        ),
      },
      { header: '数据集', cell: ({ row }) => shortText(row.original.dataset_id || '-', 28) },
      { header: '进度', cell: ({ row }) => `${formatCount(row.original.tick_done ?? row.original.source_tick_done)}/${formatCount(row.original.tick_planned)}` },
    ],
    [],
  );

  const previewColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: 'Tick', cell: ({ row }) => row.original.tick_index ?? '-' },
      { header: 'Episode', cell: ({ row }) => shortText(row.original.episode_id || '-', 28) },
      { header: '输入', cell: ({ row }) => shortText(row.original.input_text || (row.original.input_is_empty ? '<empty>' : ''), 42) },
      { header: '标签', cell: ({ row }) => shortText(asArray(row.original.tags).join(', '), 24) },
    ],
    [],
  );

  const rollbackColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '回滚点', cell: ({ row }) => shortText(row.original.point_id || '-', 34) },
      { header: '原因', cell: ({ row }) => shortText(row.original.reason || '-', 24) },
      { header: '耗时均值', cell: ({ row }) => formatDuration(row.original.summary?.timing_mean) },
      { header: '操作', cell: ({ row }) => <Button size="xs" variant="light" color="red" onClick={() => rollbackAutoTuner(String(row.original.point_id || ''))}>回滚</Button> },
    ],
    [],
  );

  const liveColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '类别', cell: ({ row }) => row.original.row_kind || '-' },
      {
        header: '对象/事件',
        cell: ({ row }) => (
          <div>
            <Text size="sm" fw={700}>
              {shortDisplayText(row.original.aggregate_display || row.original.display || row.original.display_text || row.original.kind || row.original.action_kind || row.original.ref_object_id || row.original.item_id || '-', 44)}
            </Text>
            {row.original.__displayAggregate ? (
              <Text size="xs" c="dimmed">
                聚合 {formatCount(row.original.aggregate_component_count)} 个对象，{formatCount(row.original.aggregate_context_count)} 条激活/审计链
              </Text>
            ) : null}
          </div>
        ),
      },
      { header: 'ER', cell: ({ row }) => formatNumber(row.original.aggregate_total_er ?? row.original.er ?? row.original.total_er ?? row.original.energy?.er, 4) },
      { header: 'EV', cell: ({ row }) => formatNumber(row.original.aggregate_total_ev ?? row.original.ev ?? row.original.total_ev ?? row.original.energy?.ev, 4) },
      { header: '认知压', cell: ({ row }) => formatNumber(row.original.aggregate_total_cp ?? row.original.cp ?? row.original.cp_abs ?? row.original.energy?.cognitive_pressure_abs ?? rowCognitivePressure(row.original), 4) },
      { header: '总能量/强度', cell: ({ row }) => formatNumber(row.original.aggregate_total_energy ?? row.original.total_energy ?? row.original.energy_total ?? row.original.strength ?? row.original.value ?? row.original.elapsed_ms, 4) },
    ],
    [],
  );

  const metricTargetColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      {
        header: '指标',
        cell: ({ row }) => (
          <div>
            <Text size="sm" fw={700}>{shortText(row.original.title || row.original.key || '-', 30)}</Text>
            <Text size="xs" c="dimmed">{shortText(row.original.key || '-', 36)}</Text>
          </div>
        ),
      },
      { header: '分组', cell: ({ row }) => row.original.group || '-' },
      { header: '正常范围', cell: ({ row }) => `${formatNumber(row.original.expected_min, 3)} ~ ${formatNumber(row.original.expected_max, 3)}` },
      { header: '理想值', cell: ({ row }) => formatNumber(row.original.ideal, 3) },
      { header: '权重', cell: ({ row }) => formatNumber(row.original.weight ?? 1, 3) },
      {
        header: '来源',
        cell: ({ row }) => (
          <Badge size="sm" variant="light" color={metricTargetOverridesMap()[targetKeyOf(row.original)] ? 'orange' : 'green'}>
            {metricTargetOverridesMap()[targetKeyOf(row.original)] ? '已覆盖' : '推荐值'}
          </Badge>
        ),
      },
      {
        header: '操作',
        cell: ({ row }) => (
          <Tooltip label="打开右侧快捷编辑">
            <ActionIcon
              size="sm"
              variant="light"
              onClick={(event) => {
                event.stopPropagation();
                openMetricTargetEditor(row.original);
              }}
            >
              <IconEdit size={14} />
            </ActionIcon>
          </Tooltip>
        ),
      },
    ],
    [autoTunerConfig, autoTunerCatalog, metricTargetEdit],
  );

  const paramColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      {
        header: '参数',
        cell: ({ row }) => (
          <div>
            <Text size="sm" fw={700}>{shortText(row.original.param_id || '-', 40)}</Text>
            <Text size="xs" c="dimmed">{shortText(row.original.path || row.original.source_kind || '-', 46)}</Text>
          </div>
        ),
      },
      { header: '模块', cell: ({ row }) => row.original.module || '-' },
      { header: '当前值', cell: ({ row }) => shortText(row.original.value, 18) },
      { header: '可调', cell: ({ row }) => row.original.auto_tune_allowed ? '允许' : '仅观测' },
      {
        header: '边界来源',
        cell: ({ row }) => {
          const pid = paramIdOf(row.original);
          return (
            <div>
              <Badge size="sm" variant="light" color={paramBoundOverridesMap()[pid] ? 'orange' : 'green'}>
                {paramBoundOverridesMap()[pid] ? '用户覆盖' : '推荐值'}
              </Badge>
              <Text size="xs" c="dimmed">{shortText(boundSummary(effectiveParamBound(pid)), 54)}</Text>
            </div>
          );
        },
      },
      { header: '影响指标', cell: ({ row }) => shortText(asArray(row.original.impacts).join(', '), 36) },
      {
        header: '操作',
        cell: ({ row }) => (
          <Tooltip label="编辑边界与回滚推荐值">
            <ActionIcon
              size="sm"
              variant="light"
              onClick={(event) => {
                event.stopPropagation();
                openParamBoundEditor(row.original);
              }}
            >
              <IconEdit size={14} />
            </ActionIcon>
          </Tooltip>
        ),
      },
    ],
    [autoTunerConfig, autoTunerCatalog, paramBoundEdit],
  );

  const tunerRuleColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => {
      const disabled = new Set(asArray<string>((autoTunerRules?.rules || {}).disabled_rule_ids).map(String));
      const protectedRules = new Set(asArray<string>((autoTunerRules?.rules || {}).protected_rule_ids).map(String));
      return [
        { header: '来源', cell: ({ row }) => row.original.rule_source || row.original.source || '-' },
        { header: '规则', cell: ({ row }) => shortText(row.original.title || row.original.rule_id || row.original.id || '-', 42) },
        { header: '指标', cell: ({ row }) => shortText(row.original.metric_key || '-', 24) },
        { header: '参数', cell: ({ row }) => shortText(row.original.param_id || '-', 32) },
        { header: '模式', cell: ({ row }) => tunerIssueModeLabel(row.original.issue_mode) },
        {
          header: '开关',
          cell: ({ row }) => {
            const ruleId = String(row.original.rule_id || row.original.id || '');
            return (
              <Group gap={4}>
                <Button
                  size="xs"
                  variant={disabled.has(ruleId) ? 'filled' : 'light'}
                  color={disabled.has(ruleId) ? 'red' : 'gray'}
                  onClick={(event) => {
                    event.stopPropagation();
                    saveAutoTunerRuleToggle(ruleId, 'disabled_rule_ids');
                  }}
                >
                  {disabled.has(ruleId) ? '已禁用' : '启用'}
                </Button>
                <Button
                  size="xs"
                  variant={protectedRules.has(ruleId) ? 'filled' : 'light'}
                  color={protectedRules.has(ruleId) ? 'yellow' : 'gray'}
                  onClick={(event) => {
                    event.stopPropagation();
                    saveAutoTunerRuleToggle(ruleId, 'protected_rule_ids');
                  }}
                >
                  {protectedRules.has(ruleId) ? '白名单' : '可复审'}
                </Button>
              </Group>
            );
          },
        },
        {
          header: '操作',
          cell: ({ row }) => {
            const ruleId = ruleIdOf(row.original);
            const source = String(row.original.rule_source || row.original.source || '').toLowerCase();
            const isCustom = source.includes('custom') || row.original.rule_source === '自定义';
            return (
              <Group gap={4}>
                <Tooltip label={isCustom ? '编辑自定义规则' : '复制为自定义规则'}>
                  <ActionIcon
                    size="sm"
                    variant="light"
                    onClick={(event) => {
                      event.stopPropagation();
                      openRuleEditor(row.original, isCustom ? 'edit' : 'create');
                    }}
                  >
                    {isCustom ? <IconEdit size={14} /> : <IconCopy size={14} />}
                  </ActionIcon>
                </Tooltip>
                {isCustom ? (
                  <Tooltip label="删除自定义规则">
                    <ActionIcon
                      size="sm"
                      variant="light"
                      color="red"
                      onClick={(event) => {
                        event.stopPropagation();
                        deleteCustomRule(ruleId);
                      }}
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Tooltip>
                ) : null}
              </Group>
            );
          },
        },
      ];
    },
    [autoTunerRules, autoTunerRulesDraft],
  );

  const auditColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '时间', cell: ({ row }) => row.original.ts_ms ? new Date(Number(row.original.ts_ms)).toLocaleTimeString() : '-' },
      { header: '类型', cell: ({ row }) => row.original.kind || row.original.event || row.original.action || '-' },
      { header: '规则/参数', cell: ({ row }) => shortText(row.original.rule_id || row.original.param_id || row.original.target || '-', 34) },
      { header: '结果', cell: ({ row }) => shortText(row.original.result || row.original.status || row.original.reason || row.original.message || '-', 46) },
    ],
    [],
  );

  const tunerUpdateColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '参数', cell: ({ row }) => shortText(row.original.param_id || row.original.key || '-', 36) },
      { header: '旧值', cell: ({ row }) => formatNumber(row.original.old_value ?? row.original.before, 4) },
      { header: '新值', cell: ({ row }) => formatNumber(row.original.new_value ?? row.original.after, 4) },
      { header: '原因', cell: ({ row }) => shortText(row.original.reason || row.original.rule_id || '-', 48) },
    ],
    [],
  );

  const tunerTrialColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '试验', cell: ({ row }) => shortText(row.original.trial_id || row.original.param_id || '-', 36) },
      { header: '参数', cell: ({ row }) => shortText(row.original.param_id || '-', 32) },
      { header: '方向', cell: ({ row }) => row.original.direction || row.original.mode || '-' },
      { header: '状态', cell: ({ row }) => row.original.status || row.original.result || '-' },
    ],
    [],
  );

  const tunerHealthColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '规则', cell: ({ row }) => shortText(row.original.rule_id || '-', 42) },
      { header: '命中', cell: ({ row }) => formatCount(row.original.hit_count) },
      { header: '成功', cell: ({ row }) => formatCount(row.original.success_count) },
      { header: '回滚', cell: ({ row }) => formatCount(row.original.rollback_count) },
      { header: '最近结果', cell: ({ row }) => shortText(row.original.last_result || row.original.status || '-', 24) },
    ],
    [],
  );

  const observationColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '观察项', cell: ({ row }) => shortText(row.original.title || row.original.rule_id || row.original.observation_id || '-', 36) },
      { header: '主指标', cell: ({ row }) => shortText(row.original.metric_key || row.original.baseline_metric_summary?.metric_key || '-', 24) },
      { header: '动作', cell: ({ row }) => row.original.action || row.original.source_kind || '-' },
      { header: '轮数', cell: ({ row }) => formatCount(asArray(row.original.observed_runs).length) },
      {
        header: '最近结论',
        cell: ({ row }) => {
          const latest = asArray<AnyRecord>(row.original.observed_runs).slice(-1)[0] || {};
          const effect = latest.effect || row.original.last_review_result || {};
          return shortText(effect.result || effect.action || row.original.status || '待观察', 18);
        },
      },
    ],
    [],
  );

  const observationHistoryColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '时间', cell: ({ row }) => row.original.resolved_at_ms || row.original.last_review_at_ms || row.original.created_at_ms ? new Date(Number(row.original.resolved_at_ms || row.original.last_review_at_ms || row.original.created_at_ms)).toLocaleString() : '-' },
      { header: '规则', cell: ({ row }) => shortText(row.original.rule_id || row.original.observation_id || '-', 34) },
      { header: '状态', cell: ({ row }) => row.original.status || '-' },
      { header: '动作/理由', cell: ({ row }) => shortText(row.original.last_review_result?.action || row.original.last_review_result?.reason || row.original.reason || '-', 48) },
    ],
    [],
  );

  const observationDecisionColumns = useMemo<ColumnDef<AnyRecord>[]>(
    () => [
      { header: '规则', cell: ({ row }) => shortText(row.original.rule_id || row.original.observation_id || '-', 36) },
      { header: '动作', cell: ({ row }) => row.original.action || '-' },
      { header: '状态', cell: ({ row }) => row.original.status || row.original.result || '-' },
      { header: '理由', cell: ({ row }) => shortText(row.original.reason || row.original.summary || '-', 54) },
    ],
    [],
  );

  const latest = metrics[metrics.length - 1] || {};
  const visibleCharts = chartConfigs.filter((cfg) => {
    const inSection = activeSection === 'all' || cfg.section === activeSection;
    if (!inSection) return false;
    if (!showDiagnosticCharts && isDiagnosticChartConfig(cfg)) return false;
    if (metrics.length && !chartHasVisibleData(metrics, cfg)) return false;
    const keyword = chartSearch.trim().toLowerCase();
    if (!keyword) return true;
    const haystack = [
      cfg.id,
      cfg.title,
      cfg.subtitle,
      cfg.description,
      cfg.keys.join(' '),
      cfg.keys.map(metricDisplayName).join(' '),
    ].join(' ').toLowerCase();
    return haystack.includes(keyword);
  });
  const visibleChartCatalog = showDiagnosticCharts ? chartConfigs : chartConfigs.filter((cfg) => !isDiagnosticChartConfig(cfg));
  const runRowKey = (row: ExperimentRunItem) => String(row.run_id || '');
  const tunerSummary = autoTunerState?.summary || {};
  const tunerState = autoTunerState?.state || {};
  const metricTargets = asArray(autoTunerConfig?.metric_targets || autoTunerConfig?.config?.metric_targets);
  const autoTunerParams = useMemo(() => {
    const keyword = autoTunerParamSearch.trim().toLowerCase();
    return asArray<AnyRecord>(autoTunerCatalog?.params).filter((item) => {
      if (!keyword) return true;
      return [item.param_id, item.module, item.value_type, asArray(item.impacts).join(' '), asArray(item.tags).join(' ')]
        .join(' ')
        .toLowerCase()
        .includes(keyword);
    });
  }, [autoTunerCatalog, autoTunerParamSearch]);
  const autoTunerRulesList = useMemo(() => {
    const catalog = autoTunerRules?.catalog || {};
    const rows: AnyRecord[] = [
      ...asArray<AnyRecord>(catalog.builtin_rules).map((item) => ({ ...item, rule_source: '内建' })),
      ...asArray<AnyRecord>(catalog.custom_rules).map((item) => ({ ...item, rule_source: '自定义' })),
      ...asArray<AnyRecord>(catalog.generated_rules).map((item) => ({ ...item, rule_source: '生成' })),
    ];
    const keyword = autoTunerRuleSearch.trim().toLowerCase();
    return rows.filter((item) => {
      if (!keyword) return true;
      return [item.rule_id, item.id, item.title, item.metric_key, item.param_id, item.issue_mode, item.module, item.rule_source]
        .join(' ')
        .toLowerCase()
        .includes(keyword);
    });
  }, [autoTunerRuleSearch, autoTunerRules]);
  const autoTunerAuditRows = asArray<AnyRecord>(autoTunerAudit?.items || autoTunerAudit);
  const autoTunerRecentUpdates = asArray<AnyRecord>(tunerState.last_applied_updates).slice().reverse();
  const autoTunerActiveTrials = asArray<AnyRecord>(tunerState.active_trials).slice().reverse();
  const autoTunerRuleHealth = Object.entries(tunerState.rule_health || {}).map(([rule_id, value]) => ({ rule_id, ...(value as AnyRecord) }));
  const autoTunerSuggestions = asArray<AnyRecord>(autoTunerState?.recent_llm_suggestions);
  const observationActive = asArray<AnyRecord>(tunerState.rule_observations).slice().reverse();
  const observationHistory = asArray<AnyRecord>(tunerState.observation_history).slice().reverse();
  const lastObservationReview = tunerState.last_observation_review || {};
  const observationDecisions = asArray<AnyRecord>(lastObservationReview.decisions);
  const disabledRuleIds = new Set(asArray<string>((autoTunerRules?.rules || {}).disabled_rule_ids).map(String));
  const protectedRuleIds = new Set(asArray<string>((autoTunerRules?.rules || {}).protected_rule_ids).map(String));
  const rulesSummary = autoTunerRules?.catalog?.summary || {};
  const metricInsightBundle = useMemo(
    () => buildMetricInsightBundle(metrics, autoTunerConfig, autoTunerState),
    [metrics, autoTunerConfig, autoTunerState],
  );
  const selectedMetricRow = useMemo(() => {
    const target = Number(selectedMetricTick);
    if (!Number.isFinite(target)) return metrics[metrics.length - 1] || null;
    return (
      metrics.find((row) => asNumber(row.tick_index ?? row.tick, -1) === target) ||
      metrics[metrics.length - 1] ||
      null
    );
  }, [metrics, selectedMetricTick]);
  const tickTopErItems = useMemo(
    () => structureTopItemsOfMetricRow(selectedMetricRow, 'pool_er_top5').slice(0, Number(tickTopN) || 5),
    [selectedMetricRow, tickTopN],
  );
  const tickTopEvItems = useMemo(
    () => structureTopItemsOfMetricRow(selectedMetricRow, 'pool_ev_top5').slice(0, Number(tickTopN) || 5),
    [selectedMetricRow, tickTopN],
  );
  const tickTopCpItems = useMemo(
    () => structureTopItemsOfMetricRow(selectedMetricRow, 'pool_cp_top5').slice(0, Number(tickTopN) || 5),
    [selectedMetricRow, tickTopN],
  );
  const visibleBackgroundJobs = useMemo(() => {
    const seen = new Set<string>();
    const merged: AnyRecord[] = [
      ...backgroundJobs,
      ...experimentJobs.map((item): AnyRecord => ({
        ...(item as AnyRecord),
        job_type: item.job_type || 'experiment_run',
        type_label: item.type_label || '数据集运行',
      })),
    ];
    return merged.filter((item, index) => {
      const key = String(item.job_type || '') + ':' + String(item.job_id || item.run_id || index);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [backgroundJobs, experimentJobs]);
  const activeBackgroundJobs = useMemo(
    () => visibleBackgroundJobs.filter((item) => jobIsActive(item)),
    [visibleBackgroundJobs],
  );
  const activeExperimentJob = useMemo(() => {
    return experimentJobs.find((item) => jobIsActive(item)) || (jobIsActive(job) ? job : null);
  }, [experimentJobs, job]);
  const liveDashboardWithJob = useMemo(() => {
    if (!activeExperimentJob?.latest_metrics_preview) return liveDashboard;
    const dashboardJob = dashboardExperimentJob(liveDashboard);
    const dashboardPreviewTick = asNumber(activeMetricsRowFromDashboard(liveDashboard)?.tick_index, -1);
    const jobPreviewTick = asNumber(activeExperimentJob.latest_metrics_preview?.tick_index, -1);
    const jobUpdated = asNumber(activeExperimentJob.updated_at_ms, 0);
    const dashboardUpdated = asNumber(dashboardJob?.updated_at_ms, 0);
    const dashboardHasPreview = Boolean(activeMetricsRowFromDashboard(liveDashboard));
    const jobHasPreview = Boolean(activeExperimentJob.latest_metrics_preview);
    if (jobHasPreview && (!dashboardHasPreview || jobPreviewTick >= dashboardPreviewTick || jobUpdated > dashboardUpdated)) {
      return {
        ...(liveDashboard || {}),
        tick_counter: activeExperimentJob.latest_metrics_preview.tick_index ?? liveDashboard?.tick_counter,
        meta: {
          ...(liveDashboard?.meta || {}),
          tick_counter: activeExperimentJob.latest_metrics_preview.tick_index ?? liveDashboard?.meta?.tick_counter,
        },
        active_experiment_job: activeExperimentJob,
        active_experiment_latest_metrics: activeExperimentJob.latest_metrics_preview,
        live_metrics_source: 'experiment_job_poll',
      };
    }
    return liveDashboard;
  }, [activeExperimentJob, liveDashboard]);
  const monitorMetricRow = activeMetricsRowFromDashboard(liveDashboardWithJob);
  const monitorRows = useMemo(
    () => liveRowsFromDashboard(liveDashboardWithJob, {
      aggregateStateTop: liveAggregateStateTop,
      topN: Number(liveTopN) || 20,
      sortBy: liveTopSort,
    }),
    [liveAggregateStateTop, liveDashboardWithJob, liveTopN, liveTopSort],
  );
  const monitorCpRows = useMemo(
    () => cognitivePressureRowsFromDashboard(liveDashboardWithJob, {
      aggregateStateTop: liveAggregateStateTop,
      topN: Number(liveTopN) || 20,
    }),
    [liveAggregateStateTop, liveDashboardWithJob, liveTopN],
  );
  const monitorInput = useMemo(
    () => monitorInputInfo(liveDashboardWithJob, null, true),
    [liveDashboardWithJob],
  );
  const monitorMetricTiming = timingFromMetricRow(monitorMetricRow);
  const monitorTiming = Object.keys(monitorMetricTiming).length
    ? monitorMetricTiming
    : (liveDashboardWithJob?.last_report?.timing || {});
  const monitorMeta = {
    ...(liveDashboardWithJob?.last_report?.observatory || liveDashboardWithJob?.meta || {}),
    tick_counter: monitorMetricRow?.tick_index ?? liveDashboardWithJob?.tick_counter ?? liveDashboardWithJob?.meta?.tick_counter,
    trace_id: monitorMetricRow?.trace_id,
  };
  const monitorTickValue = monitorMetricRow?.tick_index ?? liveDashboardWithJob?.tick_counter ?? liveDashboardWithJob?.meta?.tick_counter;
  const monitorPoolCount = monitorMetricRow?.pool_active_item_count ?? liveDashboardWithJob?.state_snapshot?.summary?.active_item_count;
  const monitorHdbCount = monitorMetricRow?.hdb_structure_count ?? liveDashboardWithJob?.hdb_snapshot?.summary?.structure_count;
  const recentTrialHistory = asArray<AnyRecord>(tunerState.trial_history).slice().reverse().slice(0, 24);
  const selectedParam = (manifest?.auto_tuner_selected_param || null) as AnyRecord | null;
  const selectedRule = (manifest?.auto_tuner_selected_rule || null) as AnyRecord | null;
  const selectedTarget = (manifest?.auto_tuner_selected || null) as AnyRecord | null;
  const selectedSuggestion = (manifest?.auto_tuner_llm_suggestion || null) as AnyRecord | null;
  const selectedTunerJob = (manifest?.auto_tuner_llm_job || null) as AnyRecord | null;
  const selectedBackgroundJob = (manifest?.background_job || null) as AnyRecord | null;
  const metricTargetDefault = metricTargetEdit ? (metricTargetEdit.__default || metricTargetDefaultsMap()[targetKeyOf(metricTargetEdit)] || {}) : {};
  const paramBoundRecommended = paramBoundEdit ? (paramBoundEdit.__recommended || paramBoundRecommendationsMap()[String(paramBoundEdit.param_id || '')] || {}) : {};
  const metricOptions = useMemo(
    () => metricTargets.map((item) => ({ value: String(item.key || ''), label: shortText(`${item.title || item.key} (${item.key})`, 96) })).filter((item) => item.value),
    [metricTargets],
  );
  const paramOptions = useMemo(
    () => autoTunerParams.map((item) => ({ value: String(item.param_id || ''), label: shortText(`${item.param_id} · ${item.module || '-'}`, 96) })).filter((item) => item.value),
    [autoTunerParams],
  );
  const activeAutoTunerJob = useMemo(
    () => autoTunerLlmJobs.find((jobItem) => autoTunerJobIsRunning(jobItem)) || autoTunerLlmJobs[0] || null,
    [autoTunerLlmJobs],
  );
  const datasetSelectData = useMemo(
    () =>
      datasets.map((item) => {
        const ref = datasetRefOf(item);
        return {
          value: datasetKey(ref),
          label: item.title || item.meta?.title || item.dataset_id || item.meta?.dataset_id || ref?.rel_path || 'dataset',
        };
      }),
    [datasets],
  );
  const datasetDescriptionText = useMemo(() => {
    if (datasetLoadPhase === 'backend_waiting') return datasetLoadMessage || '后端正在打开中，请稍等。';
    if (datasetLoadPhase === 'loading') return '数据集读取中，请稍等。';
    if (datasetLoadPhase === 'error') return datasetLoadMessage || '读取数据集失败。';
    if (selectedDataset) {
      return (
        selectedDataset.description ||
        selectedDataset.meta?.description ||
        selectedDataset.experiment_goal ||
        selectedDataset.meta?.experiment_goal ||
        '当前数据集暂无描述。'
      );
    }
    if (!datasetSelectData.length) return datasetLoadMessage || '当前没有可选数据集。';
    return '请选择一个数据集查看说明。';
  }, [datasetLoadMessage, datasetLoadPhase, datasetSelectData.length, selectedDataset]);
  const datasetMetricValue =
    datasetLoadPhase === 'loading' || datasetLoadPhase === 'backend_waiting' ? '读取中' : formatCount(datasets.length);
  const datasetMetricNote =
    datasetLoadPhase === 'backend_waiting'
      ? '后端正在打开中，请稍等'
      : datasetLoadPhase === 'loading'
        ? '正在读取数据集列表'
        : selectedDataset?.dataset_id || selectedDataset?.title || (datasetSelectData.length ? '等待选择' : '当前为空');

  if (initialLoading) {
    return (
      <LoadingPanel
        title="长期实验页面正在加载"
        description="正在读取运行记录、图表指标、调参器状态和审查配置。首次进入如果数据量较大，可能需要更久一些。"
        minHeight={320}
      />
    );
  }

  return (
    <div className="page-grid">
      <section className="page-main">
        <Group justify="space-between" mb="md" align="flex-start">
          <div>
            <Title order={2}>长期实验与论文图表</Title>
            <Text c="dimmed" size="sm">
              数据集、长跑任务、指标图表和自适应调参集中管理。图表使用 ECharts，长表使用虚拟滚动。
            </Text>
          </div>
          <Group gap="xs">
            <Tooltip label="刷新数据">
              <ActionIcon variant="light" loading={busy} onClick={() => Promise.all([refreshDatasets(), refreshRuns(), refreshAutoTuner()])}>
                <IconRefresh size={18} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>

        <Grid mb="md">
          <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
            <MetricCard label="数据集" value={datasetMetricValue} note={datasetMetricNote} />
          </Grid.Col>
          <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
            <Card className="metric-card">
              <Group justify="space-between" align="flex-start" gap="sm">
                <div>
                  <Text size="xs" c="dimmed" fw={700} tt="uppercase">
                    运行记录
                  </Text>
                  <Text className="metric-value">{formatCount(runs.length)}</Text>
                </div>
                <Group gap={6}>
                  <Tooltip label="重启观测台进程">
                    <ActionIcon variant="light" color="orange" loading={busy} onClick={restartProcess}>
                      <IconRotateClockwise size={18} />
                    </ActionIcon>
                  </Tooltip>
                  <Tooltip label="关闭观测台进程">
                    <ActionIcon variant="light" color="red" loading={busy} onClick={shutdownProcess}>
                      <IconPower size={18} />
                    </ActionIcon>
                  </Tooltip>
                  <ThemeIcon variant="light" color="teal" size="lg">
                    <IconChartLine size={18} />
                  </ThemeIcon>
                </Group>
              </Group>
              <Text size="xs" c="dimmed" mt={8}>
                {selectedRunId || '未选择'}
              </Text>
            </Card>
          </Grid.Col>
          <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
            <MetricCard
              label="指标行"
              value={formatCount(metrics.length)}
              note={activeExperimentJob ? `${jobStatusLabel(activeExperimentJob)}；${jobProgressText(activeExperimentJob)}` : `最新 tick ${latest.tick_index ?? '-'}`}
            />
          </Grid.Col>
          <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
            <MetricCard
              label="后台任务"
              value={formatCount(activeBackgroundJobs.length)}
              note={activeBackgroundJobs[0] ? `${jobTypeLabel(activeBackgroundJobs[0])}：${jobStatusLabel(activeBackgroundJobs[0])}` : `最新耗时 ${formatDuration(latest.timing_total_logic_ms)}`}
              tone={activeBackgroundJobs.length ? 'warn' : 'default'}
            />
          </Grid.Col>
        </Grid>

        <Card mb="md">
          <Grid>
            <Grid.Col span={{ base: 12, lg: 5 }}>
              <Select
                label="选择数据集"
                searchable
                disabled={!datasetSelectData.length}
                value={selectedDatasetKey}
                onChange={(value) => setSelectedDatasetKey(value || '')}
                placeholder={
                  datasetLoadPhase === 'backend_waiting'
                    ? '后端正在打开中，请稍等'
                    : datasetLoadPhase === 'loading'
                      ? '数据集读取中'
                      : datasetLoadPhase === 'error'
                        ? '读取失败，请稍后重试'
                        : datasetSelectData.length
                          ? '请选择数据集'
                          : '当前没有可选数据集'
                }
                data={datasetSelectData}
              />
              <Text size="xs" c="dimmed" mt={6}>
                {datasetDescriptionText}
              </Text>
            </Grid.Col>
            <Grid.Col span={{ base: 12, lg: 7 }}>
              <Group align="flex-end">
                <Select
                  label="重置策略"
                  value={cleanRun ? 'clear_all' : resetMode}
                  onChange={(value) => setResetMode(value || 'keep')}
                  disabled={cleanRun}
                  data={[
                    { value: 'keep', label: '保留' },
                    { value: 'clear_runtime', label: '清运行态' },
                    { value: 'clear_all', label: '清全部' },
                  ]}
                  w={140}
                />
                <Switch
                  label="纯净运行"
                  checked={cleanRun}
                  color="red"
                  onChange={(event) => setCleanRun(event.currentTarget.checked)}
                />
                <NumberInput
                  label="最大 tick"
                  value={maxTicks}
                  min={1}
                  max={100000}
                  disabled={runAllTicks}
                  description={runAllTicks ? '当前会忽略最大 tick，直到数据集自然结束。' : '留空或开启右侧开关可跑完整数据集。'}
                  onChange={(v) => setMaxTicks(v === '' ? '' : Number(v))}
                  w={150}
                />
                <Switch
                  label="跑完整数据集"
                  checked={runAllTicks}
                  onChange={(event) => setRunAllTicks(event.currentTarget.checked)}
                />
                <TextInput label="时间基准覆盖" value={timeBasisOverride} onChange={(event) => setTimeBasisOverride(event.currentTarget.value)} placeholder="wall/tick，可留空" w={150} />
                <NumberInput label="tick 秒" value={tickIntervalSec} min={0.001} step={0.1} onChange={(v) => setTickIntervalSec(v === '' ? '' : Number(v))} w={110} />
                <Button loading={busy} leftSection={<IconPlayerPlay size={16} />} onClick={startRun}>
                  启动运行
                </Button>
                {job?.job_id && jobIsActive(job) ? (
                  <Button variant="light" color="red" loading={busy && String(job.status || '') === 'cancelling'} onClick={stopRun}>
                    停止
                  </Button>
                ) : null}
              </Group>
              <Group mt="sm" gap="lg">
                <Switch label="自适应调参" checked={autoTune} onChange={(event) => setAutoTune(event.currentTarget.checked)} />
                <Switch label="短期调参" checked={autoTuneShort} onChange={(event) => setAutoTuneShort(event.currentTarget.checked)} />
                <Switch label="长期调参" checked={autoTuneLong} onChange={(event) => setAutoTuneLong(event.currentTarget.checked)} />
                <Switch label="导出 JSON" checked={exportJson} onChange={(event) => setExportJson(event.currentTarget.checked)} />
                <Switch label="导出 HTML" checked={exportHtml} onChange={(event) => setExportHtml(event.currentTarget.checked)} />
              </Group>
              {cleanRun ? (
                <Text size="xs" c="red" mt={8}>
                  纯净运行会在启动前清空 HDB、状态池、残响、注意力/行动/时间感受运行态、报告缓存和观测台 tick 计数；适合做可复现实验，不适合保留长期学习后的记忆。
                </Text>
              ) : (
                <Text size="xs" c="dimmed" mt={8}>
                  重置策略在第一个 tick 前执行：保留=沿用当前 HDB 和运行态；清运行态=保留 HDB 但清空状态池等运行态；清全部=启动前清 HDB 与运行态。
                </Text>
              )}
              {job ? (
                <Text size="xs" c="dimmed" mt={8}>
                  当前任务：{job.job_id || '-'} / {jobStatusLabel(job)} / 进度 {jobProgressText(job)} / run={job.run_id || '-'}
                  {job.lock_waiting ? ` / 已等待锁 ${formatDuration(job.lock_wait_ms)}` : ''}
                </Text>
              ) : null}
            </Grid.Col>
          </Grid>
        </Card>
        <FeedbackAlert feedback={feedback} />

        <Tabs defaultValue="charts">
          <Tabs.List>
            <Tabs.Tab value="charts">指标图表</Tabs.Tab>
            <Tabs.Tab value="runs">运行记录</Tabs.Tab>
            <Tabs.Tab value="jobs">后台任务</Tabs.Tab>
            <Tabs.Tab value="live">实时监控</Tabs.Tab>
            <Tabs.Tab value="tickInspect">历史 Tick 检视</Tabs.Tab>
            <Tabs.Tab value="datasets">导入/标准</Tabs.Tab>
            <Tabs.Tab value="tuner">AutoTuner</Tabs.Tab>
            <Tabs.Tab value="llm">LLM 审查</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="charts" pt="md">
            <Group mb="md" justify="space-between" align="flex-start">
              <div className="chart-section-strip">
                <Button
                  variant={activeSection === 'all' ? 'filled' : 'light'}
                  size="xs"
                  onClick={() => setActiveSection('all')}
                >
                  全部图表 {formatCount(visibleChartCatalog.length)}
                </Button>
                {chartSections.filter((section) => showDiagnosticCharts || !section.diagnostic).map((section) => (
                  <Button
                    key={section.id}
                    variant={activeSection === section.id ? 'filled' : 'light'}
                    size="xs"
                    onClick={() => setActiveSection(section.id)}
                  >
                    {section.label} {formatCount(visibleChartCatalog.filter((cfg) => cfg.section === section.id).length)}
                  </Button>
                ))}
              </div>
              <Group align="flex-end">
                <TextInput
                  label="图表/指标搜索"
                  value={chartSearch}
                  onChange={(event) => setChartSearch(event.currentTarget.value)}
                  placeholder="例如 注意力 / NT / timing / 状态池"
                  w={220}
                />
                <NumberInput
                  label="降采样 every"
                  value={downsampleEvery}
                  min={1}
                  max={1000}
                  onChange={(value) => setDownsampleEvery(Number(value) || 1)}
                  w={150}
                />
                <Button variant="light" disabled={!selectedRunId} onClick={() => selectRun(selectedRunId)}>
                  重新加载指标
                </Button>
                <Switch
                  label="显示诊断/旧口径"
                  checked={showDiagnosticCharts}
                  onChange={(event) => {
                    const next = event.currentTarget.checked;
                    setShowDiagnosticCharts(next);
                    if (!next && activeSection !== 'all' && chartSections.find((section) => section.id === activeSection)?.diagnostic) {
                      setActiveSection('overview');
                    }
                  }}
                />
              </Group>
            </Group>
            <Card className="insight-card" mb="md">
              <Group justify="space-between" align="flex-start">
                <div>
                  <Text fw={800}>图表目录</Text>
                  <Text size="xs" c="dimmed">
                    当前目录共 {formatCount(visibleChartCatalog.length)} 张图；默认优先展示新版 growth 主口径，CS、MAP 兼容和旧闭环等诊断/回滚图表会折叠。当前 run 会自动隐藏全 0 图表和全 0 曲线。每张图都可点右上角放大，放大后会展示用途、统计值、中文解释和主要影响因素。
                  </Text>
                </div>
                <Badge variant="light">当前显示 {formatCount(visibleCharts.length)}</Badge>
              </Group>
            </Card>
            <Grid>
              {visibleCharts.map((cfg) => (
                <Grid.Col key={cfg.id} span={{ base: 12, xl: 6 }}>
                  <MetricChart rows={metrics} config={cfg} />
                </Grid.Col>
              ))}
            </Grid>
          </Tabs.Panel>

          <Tabs.Panel value="runs" pt="md">
            <VirtualDataTable
              data={runs}
              columns={runColumns}
              height={520}
              getRowKey={runRowKey}
              selectedKey={selectedRunId}
              onRowClick={(row) => selectRun(row.run_id)}
            />
            <Group mt="sm">
              <Button variant="light" onClick={() => refreshRuns()}>
                刷新运行记录
              </Button>
              <Button color="red" variant="light" disabled={!runs.length} onClick={clearAllRuns}>
                清空全部运行记录
              </Button>
              <Button color="red" variant="subtle" disabled={!selectedRunId} onClick={deleteSelectedRun}>
                删除选中运行
              </Button>
            </Group>
          </Tabs.Panel>

          <Tabs.Panel value="jobs" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, lg: 4 }}>
                <Stack>
                  <MetricCard
                    label="活动任务"
                    value={formatCount(activeBackgroundJobs.length)}
                    note="queued/running/等待锁都会显示在这里"
                    tone={activeBackgroundJobs.length ? 'warn' : 'ok'}
                  />
                  <MetricCard
                    label="实验任务"
                    value={formatCount(experimentJobs.length)}
                    note={activeExperimentJob ? `${jobStatusLabel(activeExperimentJob)}；${jobProgressText(activeExperimentJob)}` : '暂无正在运行的数据集任务'}
                  />
                  <Card className="soft-note-card">
                    <Text fw={800} mb="xs">怎么看这块？</Text>
                    <Text size="sm">
                      这里独立轮询后台任务，不等待 Dashboard 主锁。若数据集任务显示“等待主循环锁/维护任务”，说明它已经提交成功，但正在等闲时整理、HDB 修复或其他主循环操作释放锁；释放后 tick 指标会继续写入。
                    </Text>
                  </Card>
                  <Button variant="light" onClick={() => refreshJobQueues()}>
                    刷新任务队列
                  </Button>
                </Stack>
              </Grid.Col>
              <Grid.Col span={{ base: 12, lg: 8 }}>
                <Group justify="space-between" mb="xs">
                  <div>
                    <Text fw={800}>后台任务队列</Text>
                    <Text size="xs" c="dimmed">包含数据集运行、闲时整理、HDB 修复、LLM 审查和 AutoTuner LLM 分析。</Text>
                  </div>
                  <Badge variant="light">{formatCount(visibleBackgroundJobs.length)}</Badge>
                </Group>
                <Stack gap={8}>
                  {visibleBackgroundJobs.length ? visibleBackgroundJobs.slice(0, 24).map((jobItem, index) => {
                    const active = jobIsActive(jobItem);
                    return (
                      <Card
                        key={`${jobItem.job_type || 'job'}:${jobItem.job_id || jobItem.run_id || index}`}
                        className={`insight-card queue-card-clickable ${active ? 'active' : ''}`}
                        onClick={() => {
                          setManifest((prev) => ({ ...(prev || {}), background_job: jobItem }));
                          const rid = String(jobItem.run_id || '').trim();
                          if (rid) {
                            setSelectedRunId(rid);
                            void selectRun(rid, true).then(() => {
                              setManifest((prev) => ({ ...(prev || {}), background_job: jobItem }));
                            });
                          }
                        }}
                      >
                        <Group justify="space-between" align="flex-start">
                          <div>
                            <Text fw={800} size="sm">
                              {jobTypeLabel(jobItem)} · {shortText(jobItem.run_id || jobItem.job_id || '-', 52)}
                            </Text>
                            <Text size="xs" c={jobItem.lock_waiting ? 'orange' : 'dimmed'}>
                              {jobStatusLabel(jobItem)}；进度 {jobProgressText(jobItem)}；更新时间 {jobTimeText(jobItem)}
                              {jobItem.lock_waiting ? `；等待锁 ${formatDuration(jobItem.lock_wait_ms)}` : ''}
                            </Text>
                            {jobItem.dataset_id ? (
                              <Text size="xs" c="dimmed">数据集：{shortText(jobItem.dataset_id, 80)}</Text>
                            ) : null}
                            {jobItem.error ? <Text size="xs" c="red">{shortText(jobItem.error, 140)}</Text> : null}
                          </div>
                          <Badge variant="light" color={active ? 'orange' : undefined}>
                            {experimentStageLabel(jobItem.status, jobItem.status)}
                          </Badge>
                        </Group>
                      </Card>
                    );
                  }) : (
                    <Card className="soft-note-card">
                      <Text size="sm" c="dimmed">暂无后台任务。启动数据集、闲时整理、全局修复或 LLM 审查后会出现在这里。</Text>
                    </Card>
                  )}
                </Stack>
              </Grid.Col>
            </Grid>
          </Tabs.Panel>

          <Tabs.Panel value="live" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, lg: 4 }}>
                <Stack>
                  <MetricCard
                    label="实时 Tick"
                    value={formatCount(monitorTickValue)}
                    note={activeExperimentJob?.lock_waiting ? `数据集任务正在等待锁 ${formatDuration(activeExperimentJob.lock_wait_ms)}` : (livePaused ? '已暂停自动刷新' : `约每 ${formatCount(Number(liveRefreshMs) || 750)} ms 拉取；tick 变化才更新`)}
                  />
                  <MetricCard
                    label="状态池对象"
                    value={formatCount(monitorPoolCount)}
                    note={`HDB ${formatCount(monitorHdbCount)} / 宽候选 ${formatCount(asArray(liveDashboardWithJob?.display_state_snapshot?.top_items).length)} / 聚合 TopN ${formatCount(Number(liveTopN) || 20)}`}
                  />
                  <MetricCard
                    label="本轮输入"
                    value={monitorInput.label}
                    note={monitorInput.is_empty
                      ? `外源 SA ${formatCount(monitorInput.external_sa_count)}；当前 tick 没有外源文本输入`
                      : `${shortDisplayText(monitorInput.text || '有外源刺激输入', 64)}；外源 SA ${formatCount(monitorInput.external_sa_count)}`}
                    tone={monitorInput.is_empty ? 'default' : 'ok'}
                  />
                  <NumberInput
                    label="实时刷新间隔 ms"
                    value={liveRefreshMs}
                    min={250}
                    max={60000}
                    step={250}
                    onChange={(value) => setLiveRefreshMs(value === '' ? '' : Number(value) || 750)}
                  />
                  <NumberInput
                    label="结构波峰 TopN"
                    value={liveTopN}
                    min={1}
                    max={300}
                    onChange={(value) => setLiveTopN(value === '' ? '' : Number(value) || 20)}
                  />
                  <Switch
                    label="结构波峰聚合显示"
                    checked={liveAggregateStateTop}
                    onChange={(event) => setLiveAggregateStateTop(event.currentTarget.checked)}
                  />
                  <Group>
                    <Button variant="light" onClick={() => setLivePaused((v) => !v)}>
                      {livePaused ? '继续刷新' : '暂停刷新'}
                    </Button>
                    <Button
                      variant="light"
                      onClick={async () => {
                        const [jobsPayload, payload] = await Promise.all([
                          api.experimentJobs().catch(() => null),
                          api.experimentLivePreview().catch(() => null),
                        ]);
                        const nextJobs = asArray<AnyRecord>((jobsPayload as AnyRecord | null)?.jobs || jobsPayload);
                        if (nextJobs.length) setExperimentJobs(nextJobs);
                        setLiveDashboard((payload as AnyRecord | null) || {});
                      }}
                    >
                      手动刷新
                    </Button>
                  </Group>
                  <TimingSummary
                    timing={monitorTiming}
                    meta={monitorMeta}
                  />
                  {!monitorRows.length ? (
                    <Card className="soft-note-card">
                      <Text fw={800} mb="xs">实时监控暂时没有可显示内容</Text>
                      <Text size="sm">
                        {activeExperimentJob
                          ? `当前数据集任务处于“${jobStatusLabel(activeExperimentJob)}”，进度 ${jobProgressText(activeExperimentJob)}。实时监控现在读取 runner 内存预览，不会主动抢主循环锁；若仍等待锁，通常是运行循环、维护、修复或结束整理任务仍在占用。`
                          : '当前没有正在运行的数据集任务。实时监控只显示当前运行态，不会读取左侧选中的历史 run。'}
                      </Text>
                    </Card>
                  ) : null}
                </Stack>
              </Grid.Col>
              <Grid.Col span={{ base: 12, lg: 8 }}>
                <Group justify="space-between" mb="xs">
                  <div>
                    <Text fw={800}>实时结构 Top / CS审计 / CFS / 行动 / 调参</Text>
                    <Text size="xs" c="dimmed">
                      状态池行按完整特征做前端结构波峰聚合，默认隐藏纯原子 SA 证据项；点击行查看后端对象、激活/审计链与能量组分。这里不读取历史 run，切换运行记录不会影响实时监控。
                    </Text>
                  </div>
                  <Group gap="xs" align="flex-end">
                    <Select
                      label="排序"
                      value={liveTopSort}
                      onChange={(value) => setLiveTopSort(normalizeLiveTopSortMode(value))}
                      data={[
                        { value: 'total', label: '按总能量降序' },
                        { value: 'er', label: '按 ER 降序' },
                        { value: 'ev', label: '按 EV 降序' },
                      ]}
                      allowDeselect={false}
                      w={180}
                    />
                    <Badge variant="light">{formatCount(monitorRows.length)}</Badge>
                  </Group>
                </Group>
                <VirtualDataTable
                  data={monitorRows}
                  columns={liveColumns}
                  height={540}
                  estimateRowHeight={58}
                  onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), live_selected: row }))}
                />
                <Card className="soft-note-card" mt="md">
                  <Group justify="space-between" mb="xs">
                    <div>
                      <Text fw={800}>认知压 Top（ER/EV 差异波峰）</Text>
                      <Text size="xs" c="dimmed">
                        按完整特征聚合后，以认知压绝对值排序；用于观察“还没被解释/还在拉扯”的结构波峰。
                      </Text>
                    </div>
                    <Badge variant="light">{formatCount(monitorCpRows.length)}</Badge>
                  </Group>
                  <VirtualDataTable
                    data={monitorCpRows}
                    columns={liveColumns}
                    height={360}
                    estimateRowHeight={58}
                    onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), live_selected_cp: row }))}
                  />
                </Card>
              </Grid.Col>
            </Grid>
          </Tabs.Panel>

          <Tabs.Panel value="tickInspect" pt="md">
            <Card className="soft-note-card">
              <Group justify="space-between" mb="xs">
                <div>
                  <Text fw={800}>历史运行 Tick 高能对象</Text>
                  <Text size="xs" c="dimmed">
                    这里只读取当前选中 run 的 metrics 快照，用来回看指定 tick 的 ER / EV / 认知压 Top；不会覆盖实时监控里的当前运行态。
                  </Text>
                </div>
                <Badge variant="light">
                  tick {selectedMetricRow?.tick_index ?? selectedMetricRow?.tick ?? '-'}
                </Badge>
              </Group>
              <Group align="flex-end" mb="sm">
                <TextInput
                  label="选中 run"
                  value={selectedRunId || '未选择'}
                  readOnly
                  w={340}
                />
                <NumberInput
                  label="tick"
                  value={selectedMetricTick}
                  min={0}
                  onChange={(value) => setSelectedMetricTick(value === '' ? '' : Number(value) || 0)}
                  w={110}
                />
                <NumberInput
                  label="TopN"
                  value={tickTopN}
                  min={1}
                  max={5}
                  onChange={(value) => setTickTopN(value === '' ? '' : Number(value) || 5)}
                  w={100}
                />
                <Button variant="light" disabled={!selectedRunId} onClick={() => selectRun(selectedRunId)}>
                  重新加载指标
                </Button>
              </Group>
              {!selectedRunId ? (
                <Text size="sm" c="dimmed">请先在“运行记录”里选择一个 run。</Text>
              ) : null}
              <Grid>
                <Grid.Col span={{ base: 12, md: 4 }}>
                  <Text fw={700} size="sm" mb="xs">ER 结构 Top</Text>
                  <div className="topn-list">
                    {tickTopErItems.length ? tickTopErItems.map((item, index) => (
                      <div key={`er-${index}-${item.display || item.ref_object_id || ''}`} className="topn-item">
                        <Text size="sm" fw={700}>{topItemDisplay(item)}</Text>
                        <Text size="xs" c="dimmed">
                          ER {formatNumber(item.er ?? item.energy?.er ?? item.total_er, 4)} / 激活 {topItemProvenance(item)}
                        </Text>
                      </div>
                    )) : <Text size="xs" c="dimmed">当前 run 还没有该 tick 的 ER Top 记录。</Text>}
                  </div>
                </Grid.Col>
                <Grid.Col span={{ base: 12, md: 4 }}>
                  <Text fw={700} size="sm" mb="xs">EV 结构 Top</Text>
                  <div className="topn-list">
                    {tickTopEvItems.length ? tickTopEvItems.map((item, index) => (
                      <div key={`ev-${index}-${item.display || item.ref_object_id || ''}`} className="topn-item">
                        <Text size="sm" fw={700}>{topItemDisplay(item)}</Text>
                        <Text size="xs" c="dimmed">
                          EV {formatNumber(item.ev ?? item.energy?.ev ?? item.total_ev, 4)} / 激活 {topItemProvenance(item)}
                        </Text>
                      </div>
                    )) : <Text size="xs" c="dimmed">当前 run 还没有该 tick 的 EV Top 记录。</Text>}
                  </div>
                </Grid.Col>
                <Grid.Col span={{ base: 12, md: 4 }}>
                  <Text fw={700} size="sm" mb="xs">认知压 Top</Text>
                  <div className="topn-list">
                    {tickTopCpItems.length ? tickTopCpItems.map((item, index) => (
                      <div key={`cp-${index}-${item.display || item.ref_object_id || ''}`} className="topn-item">
                        <Text size="sm" fw={700}>{topItemDisplay(item)}</Text>
                        <Text size="xs" c="dimmed">
                          CP {formatNumber(item.cp ?? item.cp_abs ?? item.energy?.cognitive_pressure_abs, 4)} / 激活 {topItemProvenance(item)}
                        </Text>
                      </div>
                    )) : <Text size="xs" c="dimmed">当前 run 还没有该 tick 的认知压 Top 记录。</Text>}
                  </div>
                </Grid.Col>
              </Grid>
            </Card>
          </Tabs.Panel>

          <Tabs.Panel value="datasets" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, lg: 6 }}>
                <Card>
                  <Text fw={700} mb="xs">
                    数据集标准
                  </Text>
                  <Group mb="sm">
                    <Button variant="light" onClick={previewDataset}>预览 48 tick</Button>
                    <Button variant="light" onClick={expandDataset}>展开 JSONL</Button>
                  </Group>
                  <SummaryCard
                    title="数据集协议摘要"
                    description="用于确认数据集 YAML/JSONL 需要哪些字段；完整协议放在高级区。"
                    items={datasetProtocolSummaryItems(protocol)}
                    raw={protocol}
                    rawTitle="高级 Dataset Protocol JSON"
                  />
                </Card>
              </Grid.Col>
              <Grid.Col span={{ base: 12, lg: 6 }}>
                <Card>
                  <Text fw={700} mb="xs">
                    导入 YAML 数据集
                  </Text>
                  <TextInput label="文件名" value={importName} onChange={(event) => setImportName(event.currentTarget.value)} placeholder="例如 probe_v2" />
                  <Textarea mt="sm" minRows={12} value={importText} onChange={(event) => setImportText(event.currentTarget.value)} placeholder="粘贴 YAML 内容..." />
                  <Button mt="sm" leftSection={<IconUpload size={16} />} loading={busy} onClick={importDataset}>
                    导入
                  </Button>
                </Card>
              </Grid.Col>
              <Grid.Col span={12}>
                <Card>
                  <Group justify="space-between" mb="sm">
                    <div>
                      <Text fw={800}>数据集预览与展开结果</Text>
                      <Text size="xs" c="dimmed">预览用于确认空 tick、episode、输入文本和标签；展开结果给出导出的 JSONL 路径。</Text>
                    </div>
                    <Badge variant="light">{formatCount(datasetPreview?.total_ticks)} ticks</Badge>
                  </Group>
                  <Grid>
                    <Grid.Col span={{ base: 12, xl: 8 }}>
                      <VirtualDataTable data={asArray(datasetPreview?.preview_ticks)} columns={previewColumns} height={300} />
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, xl: 4 }}>
                      <SummaryCard
                        title="预览/展开摘要"
                        description="快速确认 tick 数、空 tick 和导出路径是否符合预期。"
                        items={datasetResultSummaryItems(datasetPreview, datasetExpand)}
                        raw={datasetExpand || datasetPreview?.overview || datasetPreview}
                        rawTitle="高级 Preview / Expand JSON"
                      />
                    </Grid.Col>
                  </Grid>
                </Card>
              </Grid.Col>
            </Grid>
          </Tabs.Panel>

          <Tabs.Panel value="tuner" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
                <MetricCard
                  label="调参器状态"
                  value={autoTunerConfig?.config?.enabled ?? autoTunerConfig?.enabled ? '启用' : '关闭/未知'}
                  note={`短期 ${autoTunerConfig?.config?.enable_short_term ? '开' : '关'} / 长期 ${autoTunerConfig?.config?.enable_long_term ? '开' : '关'}`}
                />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
                <MetricCard label="参数规模" value={formatCount(tunerSummary.persisted_param_count)} note={`运行时 ${formatCount(tunerSummary.runtime_param_count)} / 目录 ${formatCount(autoTunerCatalog?.summary?.param_count || asArray(autoTunerCatalog?.params).length)}`} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
                <MetricCard label="活跃试验" value={formatCount(tunerSummary.active_trial_count || autoTunerActiveTrials.length)} note={`历史 ${formatCount(tunerSummary.trial_history_count || asArray(tunerState.trial_history).length)}`} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
                <MetricCard label="LLM 候选" value={formatCount(tunerSummary.llm_candidate_rule_count)} note={`固化 ${formatCount(tunerSummary.llm_solidified_rule_count)} / 拒绝 ${formatCount(tunerSummary.llm_rejected_rule_count)}`} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
                <MetricCard label="观察区" value={formatCount(tunerSummary.observation_active_count || observationActive.length)} note={`待复审 ${formatCount(tunerSummary.observation_reviewable_count)} / 历史 ${formatCount(tunerSummary.observation_history_count || observationHistory.length)}`} tone="warn" />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
                <MetricCard
                  label="自动验收"
                  value={(autoTunerConfig?.config?.llm_auto_validation_enabled ?? autoTunerConfig?.llm_auto_validation_enabled) ? '启用' : '关闭'}
                  note={`最近动作 ${formatCount(tunerSummary.last_observation_review_action_count)} / 历史 ${formatCount(tunerSummary.observation_review_history_count)}`}
                />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
                <MetricCard label="规则总量" value={formatCount((rulesSummary.builtin_count || 0) + (rulesSummary.generated_count || 0) + (rulesSummary.custom_count || 0))} note={`禁用 ${formatCount(rulesSummary.disabled_count)} / 白名单 ${formatCount(rulesSummary.protected_count)}`} />
              </Grid.Col>
              <Grid.Col span={{ base: 12, sm: 6, xl: 3 }}>
                <MetricCard label="诊断窗口" value={`${formatCount(metricInsightBundle.windowSize)} tick`} note={metrics.length ? `基于当前 run 的 ${formatCount(metrics.length)} 行指标` : '选择运行记录后启用'} />
              </Grid.Col>

              <Grid.Col span={12}>
                <Tabs defaultValue="targets" className="panel-tabs">
                  <Tabs.List>
                    <Tabs.Tab value="insights">诊断快照</Tabs.Tab>
                    <Tabs.Tab value="targets">指标目标</Tabs.Tab>
                    <Tabs.Tab value="params">参数目录</Tabs.Tab>
                    <Tabs.Tab value="rules">调参规则</Tabs.Tab>
                    <Tabs.Tab value="state">状态/审计</Tabs.Tab>
                    <Tabs.Tab value="observations">观察区</Tabs.Tab>
                    <Tabs.Tab value="llm_tuner">LLM 辅助</Tabs.Tab>
                    <Tabs.Tab value="raw">高级 JSON</Tabs.Tab>
                  </Tabs.List>

                  <Tabs.Panel value="insights" pt="md">
                    <Grid>
                      {metricInsightBundle.cards.map((item) => (
                        <Grid.Col key={item.label} span={{ base: 12, sm: 6, xl: 3 }}>
                          <MetricCard
                            label={item.label}
                            value={insightValue(item.summary, Boolean(item.ratio), 3)}
                            note={`${insightNote(item.summary, Boolean(item.ratio), 3)} | ${item.note}`}
                          />
                        </Grid.Col>
                      ))}
                      <Grid.Col span={{ base: 12, xl: 7 }}>
                        <Stack>
                          {metricInsightBundle.narratives.map((item) => (
                            <Card key={item.title} className="insight-card">
                              <Group justify="space-between" align="flex-start" mb="xs">
                                <Text fw={800}>{item.title}</Text>
                                <Badge variant="light">专项判断</Badge>
                              </Group>
                              <Text size="sm">{item.conclusion}</Text>
                              <Stack gap={4} mt="sm">
                                {item.evidence.map((line) => (
                                  <Text key={line} size="xs" c="dimmed">
                                    {line}
                                  </Text>
                                ))}
                              </Stack>
                            </Card>
                          ))}
                        </Stack>
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, xl: 5 }}>
                        <Text fw={800} mb="xs">耗时热点排序</Text>
                        <VirtualDataTable
                          data={metricInsightBundle.timingGroups}
                          height={330}
                          columns={[
                            { header: '链路', cell: ({ row }) => row.original.label },
                            { header: '均值', cell: ({ row }) => `${formatNumber(row.original.mean, 1)} ms` },
                            { header: '占比', cell: ({ row }) => formatPercent(row.original.share, 1) },
                            { header: '压力', cell: ({ row }) => formatNumber(row.original.pressure, 3) },
                          ]}
                          onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), auto_tuner_timing_group: row }))}
                        />
                        <JsonInspector value={metricInsightBundle.summary} title="诊断窗口原始摘要" maxHeight={260} />
                      </Grid.Col>
                    </Grid>
                  </Tabs.Panel>

                  <Tabs.Panel value="targets" pt="md">
                    <Grid>
                      <Grid.Col span={{ base: 12, xl: 7 }}>
                        <Group justify="space-between" mb="xs">
                          <Text fw={800}>长期指标目标</Text>
                          <Badge variant="light">{formatCount(metricTargets.length)}</Badge>
                        </Group>
                        <VirtualDataTable
                          data={metricTargets}
                          columns={metricTargetColumns}
                          height={430}
                          selectedKey={targetKeyOf(metricTargetEdit || selectedTarget)}
                          getRowKey={(row) => targetKeyOf(row)}
                          onRowClick={openMetricTargetEditor}
                        />
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, xl: 5 }}>
                        <Stack>
                          <Card className="soft-note-card">
                            <Group justify="space-between" align="flex-start" mb="xs">
                              <div>
                                <Text fw={800}>指标目标快捷编辑</Text>
                                <Text size="xs" c="dimmed">
                                  调整正常范围、理想值和权重。保存后会写入 AutoTuner 配置；恢复推荐值会删除该指标的用户覆盖项。
                                </Text>
                              </div>
                              <Badge variant="light" color={metricTargetEdit?.__hasOverride ? 'orange' : 'green'}>
                                {metricTargetEdit?.__hasOverride ? '用户覆盖' : '推荐值'}
                              </Badge>
                            </Group>
                            {metricTargetEdit ? (
                              <Stack gap="xs">
                                <TextInput label="指标 key" value={String(metricTargetEdit.key || '')} readOnly />
                                <Text size="xs" c="dimmed">
                                  推荐默认：正常 {formatNumber(metricTargetDefault.expected_min, 4)} ~ {formatNumber(metricTargetDefault.expected_max, 4)}；理想 {formatNumber(metricTargetDefault.ideal, 4)}；权重 {formatNumber(metricTargetDefault.weight, 4)}
                                </Text>
                                <Grid gutter="xs">
                                  <Grid.Col span={6}>
                                    <NumberInput label="正常下限" value={metricTargetEdit.expected_min} onChange={(value) => patchMetricTargetEdit('expected_min', value)} />
                                  </Grid.Col>
                                  <Grid.Col span={6}>
                                    <NumberInput label="正常上限" value={metricTargetEdit.expected_max} onChange={(value) => patchMetricTargetEdit('expected_max', value)} />
                                  </Grid.Col>
                                  <Grid.Col span={6}>
                                    <NumberInput label="理想值" value={metricTargetEdit.ideal} onChange={(value) => patchMetricTargetEdit('ideal', value)} />
                                  </Grid.Col>
                                  <Grid.Col span={6}>
                                    <NumberInput label="权重" value={metricTargetEdit.weight} min={0} onChange={(value) => patchMetricTargetEdit('weight', value)} />
                                  </Grid.Col>
                                  <Grid.Col span={6}>
                                    <NumberInput label="最小波动 min_std" value={metricTargetEdit.min_std} min={0} onChange={(value) => patchMetricTargetEdit('min_std', value)} />
                                  </Grid.Col>
                                  <Grid.Col span={6}>
                                    <NumberInput label="高位连续上限" value={metricTargetEdit.high_band_max_run ?? ''} min={0} onChange={(value) => patchMetricTargetEdit('high_band_max_run', value)} />
                                  </Grid.Col>
                                  <Grid.Col span={4}>
                                    <NumberInput label="高位阈值" value={metricTargetEdit.high_band_threshold ?? ''} onChange={(value) => patchMetricTargetEdit('high_band_threshold', value)} />
                                  </Grid.Col>
                                  <Grid.Col span={4}>
                                    <NumberInput label="高位占比上限" value={metricTargetEdit.high_band_max_ratio ?? ''} min={0} max={1} onChange={(value) => patchMetricTargetEdit('high_band_max_ratio', value)} />
                                  </Grid.Col>
                                  <Grid.Col span={4}>
                                    <NumberInput label="P95 软上限" value={metricTargetEdit.high_band_soft_p95 ?? ''} onChange={(value) => patchMetricTargetEdit('high_band_soft_p95', value)} />
                                  </Grid.Col>
                                </Grid>
                                <Group gap="xs">
                                  <Button size="xs" onClick={saveMetricTargetOverride}>保存覆盖</Button>
                                  <Button size="xs" variant="light" onClick={applyMetricTargetRecommendedToDraft}>填入推荐值</Button>
                                  <Button size="xs" variant="light" color="red" onClick={resetMetricTargetOverride}>恢复推荐值</Button>
                                </Group>
                              </Stack>
                            ) : (
                              <Text size="sm" c="dimmed">点击左侧任意指标后，可以在这里直接编辑目标范围。</Text>
                            )}
                          </Card>
                          <SelectionDetailCard
                            title="指标目标说明"
                            description="这些目标是 AutoTuner 判断“偏高 / 偏低 / 过平”的长期基线。选中左侧某一行后，右侧会集中解释这一指标的理论用途。"
                            bullets={
                              selectedTarget
                                ? [
                                    `指标名称：${selectedTarget.title || selectedTarget.key || '-'}`,
                                    `所属分组：${selectedTarget.group || '未分组'}`,
                                    `正常范围：${formatNumber(selectedTarget.expected_min, 3)} ~ ${formatNumber(selectedTarget.expected_max, 3)}；理想值 ${formatNumber(selectedTarget.ideal, 3)}`,
                                    `权重：${formatNumber(selectedTarget.weight ?? 1, 3)}；最小波动 ${formatNumber(selectedTarget.min_std ?? 0, 3)}`,
                                    `说明：${selectedTarget.description || '当前指标库未提供额外说明。'}`,
                                  ]
                                : [
                                    '建议先点击左侧某个长期指标目标。',
                                    '右侧会解释这个指标主要是看效率、能量、认知感受还是行动链路。',
                                  ]
                            }
                          />
                          <SummaryCard
                            title="调参器摘要"
                            description="这里是 AutoTuner 当前总体状态的简版摘要。"
                            items={[
                              { label: '持久化参数数', value: tunerSummary.persisted_param_count },
                              { label: '活跃试验数', value: tunerSummary.active_trial_count },
                              { label: 'LLM 候选数', value: tunerSummary.llm_candidate_rule_count },
                              { label: '观察区活跃数', value: tunerSummary.observation_active_count },
                            ]}
                            raw={autoTunerState?.summary || {}}
                            rawTitle="高级调参器摘要 JSON"
                          />
                        </Stack>
                      </Grid.Col>
                    </Grid>
                  </Tabs.Panel>

                  <Tabs.Panel value="params" pt="md">
                    <Grid>
                      <Grid.Col span={{ base: 12, xl: 8 }}>
                        <Group mb="sm" justify="space-between">
                          <TextInput
                            placeholder="搜索参数 id / 模块 / 标签 / 影响指标"
                            value={autoTunerParamSearch}
                            onChange={(event) => setAutoTunerParamSearch(event.currentTarget.value)}
                            style={{ flex: 1 }}
                          />
                          <Badge variant="light">{formatCount(autoTunerParams.length)} / {formatCount(asArray(autoTunerCatalog?.params).length)}</Badge>
                        </Group>
                        <VirtualDataTable
                          data={autoTunerParams}
                          columns={paramColumns}
                          height={560}
                          selectedKey={String(paramBoundEdit?.param_id || selectedParam?.param_id || '')}
                          getRowKey={(row) => paramIdOf(row)}
                          onRowClick={openParamBoundEditor}
                        />
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, xl: 4 }}>
                        <Card className="soft-note-card">
                          <Text fw={800} mb="xs">参数目录怎么读</Text>
                          <Text size="sm">
                            这里列的是“允许或观察中的调参参数”。`当前值` 是最近加载到调参器视图里的值，`可调` 表示 AutoTuner 是否允许主动改它，`影响指标` 用来提示它主要服务哪类问题。
                          </Text>
                          <Text size="xs" c="dimmed" mt="sm">
                            若这里看起来“像空的”，通常不是后端没数据，而是你当前筛选词过窄，或者还没选择 run 去对照这些参数和指标的关系。
                          </Text>
                        </Card>
                        <Card mt="sm" className="soft-note-card">
                          <Group justify="space-between" align="flex-start" mb="xs">
                            <div>
                              <Text fw={800}>参数边界快捷编辑</Text>
                              <Text size="xs" c="dimmed">
                                边界决定 AutoTuner 每次最多能推多远。推荐值来自目录推断和系统安全阈，用户覆盖只写入本地配置。
                              </Text>
                            </div>
                            <Badge variant="light" color={paramBoundEdit?.__hasOverride ? 'orange' : 'green'}>
                              {paramBoundEdit?.__hasOverride ? '用户覆盖' : '推荐值'}
                            </Badge>
                          </Group>
                          {paramBoundEdit ? (
                            <Stack gap="xs">
                              <TextInput label="参数 id" value={String(paramBoundEdit.param_id || '')} readOnly />
                              <Text size="xs" c="dimmed">
                                推荐默认：{boundSummary(paramBoundRecommended)}
                              </Text>
                              <Grid gutter="xs">
                                <Grid.Col span={6}>
                                  <NumberInput label="最小值" value={paramBoundEdit.min_value} onChange={(value) => patchParamBoundEdit('min_value', value)} />
                                </Grid.Col>
                                <Grid.Col span={6}>
                                  <NumberInput label="最大值" value={paramBoundEdit.max_value} onChange={(value) => patchParamBoundEdit('max_value', value)} />
                                </Grid.Col>
                                <Grid.Col span={6}>
                                  <NumberInput label="单步上限" value={paramBoundEdit.max_step_abs} min={0} onChange={(value) => patchParamBoundEdit('max_step_abs', value)} />
                                </Grid.Col>
                                <Grid.Col span={6}>
                                  <NumberInput label="量化步长" value={paramBoundEdit.quantum} min={0} onChange={(value) => patchParamBoundEdit('quantum', value)} />
                                </Grid.Col>
                              </Grid>
                              <Group gap="xs">
                                <Button size="xs" onClick={saveParamBoundOverride}>保存覆盖</Button>
                                <Button size="xs" variant="light" onClick={applyParamRecommendedToDraft}>填入推荐值</Button>
                                <Button size="xs" variant="light" color="red" onClick={resetParamBoundOverride}>恢复推荐值</Button>
                              </Group>
                            </Stack>
                          ) : (
                            <Text size="sm" c="dimmed">点击左侧参数行后，可以直接编辑边界并一键回滚推荐值。</Text>
                          )}
                        </Card>
                        <Card mt="sm">
                          <Text fw={800} mb="xs">参数边界 / 推荐阅读</Text>
                          <Text size="xs" c="dimmed">
                            目录 {formatCount(autoTunerCatalog?.summary?.param_count)} 项；允许自动调参 {formatCount(autoTunerCatalog?.summary?.auto_tune_allowed_count)} 项。
                          </Text>
                          <Text size="xs" c="dimmed" mt="sm">
                            当前参数边界来自猜测边界与配置边界合并结果，主要用于防止大幅越界，而不是替代理论判断。
                          </Text>
                          <SummaryCard
                            title="当前选中参数"
                            description="点击左侧参数行后，这里会把它翻译成可读说明，而不是只显示技术键。"
                            items={[
                              { label: '参数', value: selectedParam?.param_id },
                              { label: '来源', value: tunerSourceKindLabel(selectedParam?.source_kind) },
                              { label: '模块', value: selectedParam?.module },
                              { label: '当前值', value: selectedParam?.value },
                              { label: '默认/建议起点', value: autoTunerCatalog?.param_defaults?.[selectedParam?.param_id || ''] },
                              {
                                label: '边界',
                                value: selectedParam ? `${formatNumber(effectiveParamBound(paramIdOf(selectedParam))?.min_value, 4)} ~ ${formatNumber(effectiveParamBound(paramIdOf(selectedParam))?.max_value, 4)}` : undefined,
                                note: selectedParam ? `单步上限 ${formatNumber(effectiveParamBound(paramIdOf(selectedParam))?.max_step_abs, 4)} / 量化 ${formatNumber(effectiveParamBound(paramIdOf(selectedParam))?.quantum, 4)}` : undefined,
                              },
                            ]}
                            raw={selectedParam ? { param: selectedParam, bounds: effectiveParamBound(paramIdOf(selectedParam)), override: paramBoundOverridesMap()[paramIdOf(selectedParam)] } : autoTunerCatalog?.summary || {}}
                            rawTitle="高级参数详情 JSON"
                          />
                          <SelectionDetailCard
                            title="参数用途解释"
                            bullets={
                              selectedParam
                                ? [
                                    `影响指标：${asArray(selectedParam.impacts).join('、') || '当前没有影响指标标签。'}`,
                                    `标签：${asArray(selectedParam.tags).join('、') || '无标签'}`,
                                    `路径：${selectedParam.path || selectedParam.param_id}`,
                                    `可自动调参：${selectedParam.auto_tune_allowed ? '允许，调参器可主动试探。' : '仅观测，默认不主动改动。'}`,
                                    `备注：${selectedParam.note || '当前参数目录没有额外备注。'}`,
                                  ]
                                : [
                                    '建议先点击左侧某个参数行。',
                                    '这里会解释它来自哪个模块、主要影响哪些指标，以及是否允许自动调参。',
                                  ]
                            }
                          />
                        </Card>
                      </Grid.Col>
                    </Grid>
                  </Tabs.Panel>

                  <Tabs.Panel value="rules" pt="md">
                    <Group mb="sm" justify="space-between">
                      <TextInput
                        placeholder="搜索规则 / 指标 / 参数 / 模块"
                        value={autoTunerRuleSearch}
                        onChange={(event) => setAutoTunerRuleSearch(event.currentTarget.value)}
                        style={{ flex: 1 }}
                      />
                      <Button
                        size="xs"
                        variant="light"
                        leftSection={<IconPlus size={14} />}
                        onClick={() => openRuleEditor(null, 'create')}
                      >
                        新建自定义规则
                      </Button>
                      <Badge variant="light">{formatCount(autoTunerRulesList.length)}</Badge>
                    </Group>
                    <Grid>
                      <Grid.Col span={{ base: 12, xl: 8 }}>
                        <VirtualDataTable
                          data={autoTunerRulesList}
                          columns={tunerRuleColumns}
                          height={470}
                          selectedKey={String(ruleEdit?.id || selectedRule?.rule_id || selectedRule?.id || '')}
                          getRowKey={(row) => ruleIdOf(row)}
                          onRowClick={(row) => openRuleEditor(row, 'edit')}
                        />
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, xl: 4 }}>
                        <Card className="soft-note-card">
                          <Text fw={800} mb="xs">规则目录说明</Text>
                          <Text size="sm">
                            `内建` 是系统自带的稳定调参规则，`自定义` 是人工加入的规则，`生成` 则是近期自动生成或派生出的规则。禁用/白名单在这里只改变调参器行为，不会直接删除规则。
                          </Text>
                        </Card>
                        <Card mt="sm" className="soft-note-card">
                          <Group justify="space-between" align="flex-start" mb="xs">
                            <div>
                              <Text fw={800}>自定义规则编辑器</Text>
                              <Text size="xs" c="dimmed">
                                内建/生成规则不能直接改写；点击它们会复制为自定义草稿。自定义规则保存后进入 custom_rules。
                              </Text>
                            </div>
                            <Badge variant="light">{ruleEditMode === 'edit' ? '编辑' : '新建/复制'}</Badge>
                          </Group>
                          {ruleEdit ? (
                            <Stack gap="xs">
                              <TextInput label="规则 id" value={String(ruleEdit.id || '')} onChange={(event) => patchRuleEdit('id', event.currentTarget.value)} />
                              <TextInput label="中文标题" value={String(ruleEdit.title || '')} onChange={(event) => patchRuleEdit('title', event.currentTarget.value)} />
                              <Textarea label="说明 / 调参原因" value={String(ruleEdit.description || '')} minRows={2} onChange={(event) => patchRuleEdit('description', event.currentTarget.value)} />
                              <Select
                                label="目标指标"
                                searchable
                                data={metricOptions}
                                value={String(ruleEdit.metric_key || '') || null}
                                onChange={(value) => patchRuleEdit('metric_key', value || '')}
                              />
                              <Select
                                label="目标参数"
                                searchable
                                data={paramOptions}
                                value={String(ruleEdit.param_id || '') || null}
                                onChange={(value) => patchRuleEdit('param_id', value || '')}
                              />
                              <Grid gutter="xs">
                                <Grid.Col span={6}>
                                  <Select
                                    label="问题模式"
                                    data={[
                                      { value: 'high', label: '偏高：指标超过正常上限' },
                                      { value: 'low', label: '偏低：指标低于正常下限' },
                                      { value: 'flatline', label: '过平：变化太少' },
                                    ]}
                                    value={String(ruleEdit.issue_mode || 'high')}
                                    onChange={(value) => patchRuleEdit('issue_mode', value || 'high')}
                                  />
                                </Grid.Col>
                                <Grid.Col span={6}>
                                  <Select
                                    label="调整方向"
                                    data={[
                                      { value: '1', label: '提高目标参数' },
                                      { value: '-1', label: '降低目标参数' },
                                    ]}
                                    value={String(Number(ruleEdit.direction) < 0 ? -1 : 1)}
                                    onChange={(value) => patchRuleEdit('direction', Number(value || -1))}
                                  />
                                </Grid.Col>
                                <Grid.Col span={4}>
                                  <NumberInput label="步长比例" value={ruleEdit.step_scale} min={0.05} max={1} onChange={(value) => patchRuleEdit('step_scale', value)} />
                                </Grid.Col>
                                <Grid.Col span={4}>
                                  <NumberInput label="最低严重度" value={ruleEdit.min_severity} min={0} max={1} onChange={(value) => patchRuleEdit('min_severity', value)} />
                                </Grid.Col>
                                <Grid.Col span={4}>
                                  <NumberInput label="冷却 tick" value={ruleEdit.cooldown_ticks} min={0} onChange={(value) => patchRuleEdit('cooldown_ticks', value)} />
                                </Grid.Col>
                              </Grid>
                              <Group gap="lg">
                                <Switch label="规则启用" checked={Boolean(ruleEdit.enabled)} onChange={(event) => patchRuleEdit('enabled', event.currentTarget.checked)} />
                                <Switch label="保护免受 LLM 自动改动" checked={Boolean(ruleEdit.protect_from_llm)} onChange={(event) => patchRuleEdit('protect_from_llm', event.currentTarget.checked)} />
                              </Group>
                              <Group gap="xs">
                                <Button size="xs" onClick={saveCustomRuleDraft}>保存自定义规则</Button>
                                <Button size="xs" variant="light" leftSection={<IconPlus size={14} />} onClick={() => openRuleEditor(null, 'create')}>新建空规则</Button>
                                {ruleEditMode === 'edit' ? (
                                  <Button size="xs" variant="light" color="red" leftSection={<IconTrash size={14} />} onClick={() => deleteCustomRule(String(ruleEdit.id || ''))}>删除</Button>
                                ) : null}
                              </Group>
                            </Stack>
                          ) : (
                            <Text size="sm" c="dimmed">点击左侧规则，或点“新建自定义规则”，这里会出现可编辑表单。</Text>
                          )}
                        </Card>
                        <SummaryCard
                          title="当前选中规则"
                          description="点击左侧规则行后，这里会解释它在调参链路中的职责。"
                          items={[
                            { label: '规则', value: selectedRule?.title || selectedRule?.rule_id || selectedRule?.id },
                            { label: '来源', value: selectedRule?.rule_source || selectedRule?.source },
                            { label: '目标指标', value: selectedRule?.metric_key },
                            { label: '目标参数', value: selectedRule?.param_id },
                            { label: '问题模式', value: tunerIssueModeLabel(selectedRule?.issue_mode) },
                            { label: '方向', value: tunerDirectionLabel(selectedRule?.direction) },
                          ]}
                          raw={selectedRule || autoTunerRules?.catalog?.summary || {}}
                          rawTitle="高级规则详情 JSON"
                        />
                        <SelectionDetailCard
                          title="规则解释"
                          bullets={
                            selectedRule
                              ? [
                                  `触发条件：当 ${selectedRule.metric_key || '目标指标'} ${tunerIssueModeLabel(selectedRule.issue_mode)} 时，倾向于${tunerDirectionLabel(selectedRule.direction)} ${selectedRule.param_id || '相关参数'}。`,
                                  `规则来源：${selectedRule.rule_source || selectedRule.source || '未标记'}；标题：${selectedRule.title || selectedRule.rule_id || selectedRule.id || '-'}`,
                                  `禁用状态：${disabledRuleIds.has(String(selectedRule.rule_id || selectedRule.id || '')) ? '已禁用，调参器不会执行它。' : '启用中。'}`,
                                  `白名单状态：${protectedRuleIds.has(String(selectedRule.rule_id || selectedRule.id || '')) ? '已列入白名单/保护，不建议被 LLM 轻易改动。' : '可复审。'}`,
                                  `补充说明：${selectedRule.description || '当前规则目录未提供额外说明。'}`,
                                ]
                              : [
                                  '建议先点击左侧某条规则。',
                                  '右侧会说明它针对哪个指标、会改哪个参数，以及目前是不是被禁用或保护。',
                                ]
                          }
                        />
                        <Card mt="sm">
                          <Group justify="space-between" mb="sm">
                            <div>
                              <Text fw={800}>规则高级 JSON</Text>
                              <Text size="xs" c="dimmed">常规增删改查建议用上方表单；这里保留给批量编辑和排错。</Text>
                            </div>
                            <Button size="xs" variant="light" onClick={saveAutoTunerRules}>保存规则</Button>
                          </Group>
                          <JsonInput value={autoTunerRulesDraft} onChange={setAutoTunerRulesDraft} autosize minRows={7} maxRows={12} validationError="JSON 格式不正确" />
                        </Card>
                      </Grid.Col>
                    </Grid>
                  </Tabs.Panel>

                  <Tabs.Panel value="state" pt="md">
                    <Grid>
                      <Grid.Col span={{ base: 12, xl: 6 }}>
                        <Text fw={800} mb="xs">最近参数动作</Text>
                        <VirtualDataTable data={autoTunerRecentUpdates} columns={tunerUpdateColumns} height={230} onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), auto_tuner_recent_update: row }))} />
                        <Card mt="sm" className="soft-note-card">
                          <Text fw={800} mb="xs">最近动作解释</Text>
                          {autoTunerRecentUpdates.length ? autoTunerRecentUpdates.slice(0, 3).map((row, index) => (
                            <Text key={`update-${index}`} size="xs" c="dimmed" mt={index ? 6 : 0}>
                              {explainAutoTunerUpdate(row)}
                            </Text>
                          )) : <Text size="xs" c="dimmed">当前还没有近期调参动作。</Text>}
                        </Card>
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, xl: 6 }}>
                        <Text fw={800} mb="xs">当前活跃试验</Text>
                        <VirtualDataTable data={autoTunerActiveTrials} columns={tunerTrialColumns} height={230} onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), auto_tuner_active_trial: row }))} />
                        <Card mt="sm" className="soft-note-card">
                          <Text fw={800} mb="xs">活跃试验解释</Text>
                          {autoTunerActiveTrials.length ? autoTunerActiveTrials.slice(0, 3).map((row, index) => (
                            <Text key={`trial-${index}`} size="xs" c="dimmed" mt={index ? 6 : 0}>
                              {explainAutoTunerTrial(row)}
                            </Text>
                          )) : <Text size="xs" c="dimmed">当前没有正在观察的活跃试验。</Text>}
                        </Card>
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, xl: 6 }}>
                        <Text fw={800} mb="xs">规则健康度</Text>
                        <VirtualDataTable data={autoTunerRuleHealth} columns={tunerHealthColumns} height={300} onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), auto_tuner_rule_health: row }))} />
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, xl: 6 }}>
                        <Text fw={800} mb="xs">审计日志</Text>
                        <VirtualDataTable data={autoTunerAuditRows} columns={auditColumns} height={300} onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), auto_tuner_audit: row }))} />
                      </Grid.Col>
                      <Grid.Col span={12}>
                        <Text fw={800} mb="xs">回滚点</Text>
                        <VirtualDataTable data={rollbackPoints} columns={rollbackColumns} height={300} />
                      </Grid.Col>
                      <Grid.Col span={12}>
                        <Text fw={800} mb="xs">近期长期试验记录</Text>
                        <VirtualDataTable data={recentTrialHistory} columns={tunerTrialColumns} height={260} onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), auto_tuner_trial_history: row }))} />
                        <Text size="xs" c="dimmed" mt="sm">
                          这里保留近期的短期/长期调参试验痕迹。若你想判断某次调参是“为了降耗时”还是“为了拉回能量分布”，先点中对应行，再看右侧检视面板里的原因、方向和关联规则。
                        </Text>
                      </Grid.Col>
                    </Grid>
                  </Tabs.Panel>

                  <Tabs.Panel value="observations" pt="md">
                    <Grid>
                      <Grid.Col span={{ base: 12, xl: 5 }}>
                        <Card>
                          <Group justify="space-between" align="flex-start" mb="xs">
                            <div>
                              <Text fw={800}>观察区概况</Text>
                              <Text size="xs" c="dimmed">
                                LLM 建议不会直接永久固化，先在这里累计“生效前 / 生效后”证据，再进入自动验收。
                              </Text>
                            </div>
                            <Badge variant="light">{formatCount(observationActive.length)} 活跃</Badge>
                          </Group>
                          <Stack gap={6}>
                            <Text size="sm">
                              当前可复审 {formatCount(tunerSummary.observation_reviewable_count)} 条，历史归档 {formatCount(observationHistory.length)} 条。
                            </Text>
                            <Text size="xs" c="dimmed">
                              最小观察轮数 {formatCount(autoTunerConfig?.config?.llm_auto_validation_min_runs)}；单次最多复审 {formatCount(autoTunerConfig?.config?.llm_auto_validation_max_observations_per_review)} 条。
                            </Text>
                            <Text size="xs" c="dimmed">
                              最近复审：{lastObservationReview.review_id || '暂无'} {lastObservationReview.reviewed_at_ms ? `/ ${new Date(Number(lastObservationReview.reviewed_at_ms)).toLocaleString()}` : ''}
                            </Text>
                          </Stack>
                        </Card>
                        <Card mt="sm">
                          <Group justify="space-between" mb="xs">
                            <Text fw={800}>最近自动验收决策</Text>
                            <Badge variant="light">{formatCount(observationDecisions.length)}</Badge>
                          </Group>
                          <VirtualDataTable
                            data={observationDecisions}
                            columns={observationDecisionColumns}
                            height={240}
                            onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), auto_tuner_observation_decision: row }))}
                          />
                        </Card>
                        <JsonInspector value={lastObservationReview} title="最近验收原始记录" maxHeight={260} />
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, xl: 7 }}>
                        <Text fw={800} mb="xs">活跃观察项</Text>
                        <VirtualDataTable
                          data={observationActive}
                          columns={observationColumns}
                          height={300}
                          onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), auto_tuner_observation: row }))}
                        />
                        <Text fw={800} mt="md" mb="xs">观察区历史</Text>
                        <VirtualDataTable
                          data={observationHistory}
                          columns={observationHistoryColumns}
                          height={300}
                          onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), auto_tuner_observation_history: row }))}
                        />
                      </Grid.Col>
                    </Grid>
                  </Tabs.Panel>

                  <Tabs.Panel value="llm_tuner" pt="md">
                    <Grid>
                      <Grid.Col span={{ base: 12, xl: 5 }}>
                        <Card>
                          <Group justify="space-between" mb="sm">
                            <Text fw={800}>AutoTuner LLM 配置</Text>
                            <Group gap="xs">
                              <Badge variant="light">{autoTunerLlmConfig?.source === 'llm_review_fallback' ? '沿用主审查配置' : '独立配置'}</Badge>
                              <Button size="xs" variant="light" onClick={saveAutoTunerLlmConfig}>保存</Button>
                            </Group>
                          </Group>
                          <Text size="xs" c="dimmed" mb="sm">
                            这里建议与左侧“大模型审查”使用相同的服务地址、模型与超时思路；不同的是这里更偏向“给出调参建议”，而不是审查运行结果。
                          </Text>
                          <Grid>
                            <Grid.Col span={{ base: 12, sm: 6 }}>
                              <Switch
                                label="启用 LLM 辅助"
                                checked={Boolean(autoTunerLlmForm.enabled)}
                                onChange={(event) => patchAutoTunerLlmForm('enabled', event.currentTarget.checked)}
                              />
                            </Grid.Col>
                            <Grid.Col span={{ base: 12, sm: 6 }}>
                              <Switch
                                label="运行完成后自动分析"
                                checked={Boolean(autoTunerLlmForm.auto_analyze_on_completion)}
                                onChange={(event) => patchAutoTunerLlmForm('auto_analyze_on_completion', event.currentTarget.checked)}
                              />
                            </Grid.Col>
                            <Grid.Col span={12}>
                              <TextInput
                                label="服务地址 Base URL"
                                value={String(autoTunerLlmForm.base_url || '')}
                                onChange={(event) => patchAutoTunerLlmForm('base_url', event.currentTarget.value)}
                                placeholder="https://api.openai.com"
                              />
                            </Grid.Col>
                            <Grid.Col span={{ base: 12, sm: 7 }}>
                              <PasswordInput
                                label="API Key"
                                description={autoTunerLlmForm.api_key_masked ? `已保存：${autoTunerLlmForm.api_key_masked}` : '留空表示保留已保存密钥。'}
                                value={String(autoTunerLlmForm.api_key || '')}
                                onChange={(event) => patchAutoTunerLlmForm('api_key', event.currentTarget.value)}
                                placeholder="sk-..."
                              />
                            </Grid.Col>
                            <Grid.Col span={{ base: 12, sm: 5 }}>
                              <TextInput
                                label="模型名称"
                                value={String(autoTunerLlmForm.model || '')}
                                onChange={(event) => patchAutoTunerLlmForm('model', event.currentTarget.value)}
                                placeholder="gpt-5.2 / 本地模型名"
                              />
                            </Grid.Col>
                            <Grid.Col span={{ base: 12, sm: 4 }}>
                              <NumberInput
                                label="温度"
                                value={Number(autoTunerLlmForm.temperature ?? 0.2)}
                                min={0}
                                max={2}
                                step={0.1}
                                onChange={(value) => patchAutoTunerLlmForm('temperature', Number(value) || 0)}
                              />
                            </Grid.Col>
                            <Grid.Col span={{ base: 12, sm: 4 }}>
                              <NumberInput
                                label="提示词最大字符"
                                value={Number(autoTunerLlmForm.max_prompt_chars ?? 900000)}
                                min={1000}
                                step={10000}
                                onChange={(value) => patchAutoTunerLlmForm('max_prompt_chars', Number(value) || 900000)}
                              />
                            </Grid.Col>
                            <Grid.Col span={{ base: 12, sm: 4 }}>
                              <NumberInput
                                label="超时秒数"
                                value={Number(autoTunerLlmForm.timeout_sec ?? 240)}
                                min={10}
                                step={10}
                                onChange={(value) => patchAutoTunerLlmForm('timeout_sec', Number(value) || 240)}
                              />
                            </Grid.Col>
                          </Grid>
                          <JsonInput mt="sm" value={autoTunerLlmDraft} onChange={setAutoTunerLlmDraft} autosize minRows={4} maxRows={8} validationError="JSON 格式不正确" label="高级 JSON 覆盖" />
                        </Card>
                        <Card mt="sm">
                          <Text fw={800} mb="sm">LLM 分析</Text>
                          <Textarea minRows={5} value={autoTunerPrompt} onChange={(event) => setAutoTunerPrompt(event.currentTarget.value)} placeholder="可选：告诉 LLM 重点分析哪些指标或疑点。" />
                          <Group mt="sm">
                            <Button variant="light" disabled={!selectedRunId} onClick={startAutoTunerAnalyze}>启动分析</Button>
                            <Button variant="subtle" onClick={refreshAutoTuner}>刷新任务</Button>
                          </Group>
                          <Text size="xs" c="dimmed" mt="sm">
                            建议写清楚“想解决什么问题、怀疑哪条链路、希望保持哪些效果不变”，这样生成的调参建议更容易直接落地。
                          </Text>
                        </Card>
                        <SummaryCard
                          title="当前任务状态"
                          description="这里专门追踪最近一次 AutoTuner LLM 分析任务。"
                          items={[
                            { label: '状态', value: autoTunerJobStatusLabel(activeAutoTunerJob?.status) },
                            { label: '关联运行', value: activeAutoTunerJob?.run_id || selectedRunId || '-' },
                            { label: '模型', value: activeAutoTunerJob?.config?.model || autoTunerLlmForm.model || '-' },
                            { label: '关注指标', value: asArray(activeAutoTunerJob?.focus_metrics).join(' / ') || '-' },
                            { label: '错误', value: activeAutoTunerJob?.error || '-' },
                          ]}
                          raw={activeAutoTunerJob}
                          rawTitle="高级 AutoTuner LLM Job JSON"
                        />
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, xl: 7 }}>
                        <Text fw={800} mb="xs">近期 LLM 建议</Text>
                        <VirtualDataTable
                          data={autoTunerSuggestions}
                          columns={[
                            { header: '运行', cell: ({ row }) => shortText(row.original.run_id || '-', 24) },
                            { header: '时间', cell: ({ row }) => row.original.created_at_ms ? new Date(Number(row.original.created_at_ms)).toLocaleString() : '-' },
                            { header: '摘要', cell: ({ row }) => shortText(llmSuggestionSummary(row.original), 60) },
                            { header: '指标/建议', cell: ({ row }) => `${formatCount(row.original.counts?.metric_findings)} / ${formatCount(row.original.counts?.experiments)}` },
                          ]}
                          height={260}
                          onRowClick={(row) => setManifest((prev) => ({ ...(prev || {}), auto_tuner_llm_suggestion: row }))}
                        />
                        <SelectionDetailCard
                          title="选中建议解释"
                          description="点击上方建议后，这里会集中展示它准备改什么、为什么改。"
                          bullets={
                            selectedSuggestion
                              ? [
                                  `摘要：${llmSuggestionSummary(selectedSuggestion)}`,
                                  `指标发现：${asArray(selectedSuggestion?.parsed_json?.metric_findings).map((item) => `${item.metric_key || '指标'} ${tunerIssueModeLabel(item.status)}`).join('；') || '无'}`,
                                  `建议试验：${asArray(selectedSuggestion?.parsed_json?.suggested_experiments).map((item) => `${item.param_id || '参数'} -> ${tunerDirectionLabel(item.direction, item.direction_text)} (${tunerIssueModeLabel(item.issue_mode)})`).join('；') || '无'}`,
                                  `建议规则改动：${asArray(selectedSuggestion?.parsed_json?.suggested_rule_changes).map((item) => `${item.rule_id || 'custom_rule'} ${item.action || '-'}`).join('；') || '无'}`,
                                  `自动落地结果：${llmSuggestionApplyLabel(selectedSuggestion)}`,
                                ]
                              : [
                                  '建议先点击上方某条 LLM 建议。',
                                  '右侧会说明这次建议看到什么异常、建议试什么参数、有没有建议改规则。',
                                ]
                          }
                        />
                        <Card mt="sm" className="soft-note-card">
                          <Text fw={800} mb="xs">LLM 任务队列</Text>
                          <Text size="xs" c="dimmed" mb="sm">
                            这里保留最近的 AutoTuner LLM 任务。点击任意任务，会在右侧检视面板中显示详细结果。
                          </Text>
                          <Stack gap={6}>
                            {autoTunerLlmJobs.length ? autoTunerLlmJobs.slice(0, 8).map((jobItem, index) => (
                              <Card
                                key={String(jobItem.job_id || index)}
                                className={`insight-card queue-card-clickable ${selectedTunerJob?.job_id === jobItem.job_id ? 'active' : ''}`}
                                onClick={() => setManifest((prev) => ({ ...(prev || {}), auto_tuner_llm_job: jobItem }))}
                              >
                                <Group justify="space-between" align="flex-start">
                                  <div>
                                    <Text fw={700} size="sm">{shortText(jobItem.run_id || jobItem.job_id || 'AutoTuner LLM 任务', 48)}</Text>
                                    <Text size="xs" c="dimmed">
                                      {autoTunerJobStatusLabel(jobItem.status)}；模型 {jobItem.config?.model || autoTunerLlmForm.model || '-'}
                                    </Text>
                                  </div>
                                  <Badge variant="light">{autoTunerJobStatusLabel(jobItem.status)}</Badge>
                                </Group>
                                {jobItem.error ? (
                                  <Text size="xs" c="red" mt={6}>{shortText(jobItem.error, 120)}</Text>
                                ) : null}
                              </Card>
                            )) : (
                              <Text size="sm" c="dimmed">暂无 AutoTuner LLM 任务。</Text>
                            )}
                          </Stack>
                        </Card>
                      </Grid.Col>
                    </Grid>
                  </Tabs.Panel>

                  <Tabs.Panel value="raw" pt="md">
                    <Grid>
                      <Grid.Col span={{ base: 12, xl: 6 }}>
                        <Card>
                          <Group justify="space-between" mb="sm">
                            <Text fw={800}>基础配置 JSON</Text>
                            <Button size="xs" variant="light" onClick={saveAutoTunerConfig}>保存配置</Button>
                          </Group>
                          <JsonInput value={autoTunerConfigDraft} onChange={setAutoTunerConfigDraft} autosize minRows={12} maxRows={20} validationError="JSON 格式不正确" />
                        </Card>
                      </Grid.Col>
                      <Grid.Col span={{ base: 12, xl: 6 }}>
                        <JsonInspector value={autoTunerState} title="AutoTuner State Raw" maxHeight={500} />
                      </Grid.Col>
                    </Grid>
                  </Tabs.Panel>
                </Tabs>
              </Grid.Col>
            </Grid>
          </Tabs.Panel>

          <Tabs.Panel value="llm" pt="md">
            <Grid>
              <Grid.Col span={{ base: 12, xl: 5 }}>
                <Card>
                  <Group justify="space-between" mb="sm">
                    <div>
                      <Text fw={800}>大模型审查配置</Text>
                      <Text size="xs" c="dimmed">对当前运行记录生成结构化审查报告。</Text>
                    </div>
                    <Button size="xs" variant="light" onClick={refreshLlmConfig}>刷新</Button>
                  </Group>
                  <Grid>
                    <Grid.Col span={{ base: 12, sm: 6 }}>
                      <Switch
                        label="启用审查"
                        checked={Boolean(llmConfigForm.enabled)}
                        onChange={(event) => patchLlmConfigForm('enabled', event.currentTarget.checked)}
                      />
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 6 }}>
                      <Switch
                        label="运行完成后自动审查"
                        checked={Boolean(llmConfigForm.auto_analyze_on_completion)}
                        onChange={(event) => patchLlmConfigForm('auto_analyze_on_completion', event.currentTarget.checked)}
                      />
                    </Grid.Col>
                    <Grid.Col span={12}>
                      <TextInput
                        label="服务地址 Base URL"
                        description="兼容 OpenAI 风格接口；本地代理或第三方服务也填这里。"
                        value={String(llmConfigForm.base_url || '')}
                        onChange={(event) => patchLlmConfigForm('base_url', event.currentTarget.value)}
                        placeholder="https://api.openai.com"
                      />
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 7 }}>
                      <PasswordInput
                        label="API Key"
                        description={llmConfigForm.api_key_masked ? `已保存：${llmConfigForm.api_key_masked}` : '留空表示不修改已保存密钥。'}
                        value={String(llmConfigForm.api_key || '')}
                        onChange={(event) => patchLlmConfigForm('api_key', event.currentTarget.value)}
                        placeholder="sk-..."
                      />
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 5 }}>
                      <TextInput
                        label="模型名称"
                        value={String(llmConfigForm.model || '')}
                        onChange={(event) => patchLlmConfigForm('model', event.currentTarget.value)}
                        placeholder="gpt-5.2 / gpt-4.1 / 本地模型名"
                      />
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 4 }}>
                      <NumberInput
                        label="温度"
                        value={Number(llmConfigForm.temperature ?? 0.2)}
                        min={0}
                        max={2}
                        step={0.1}
                        onChange={(value) => patchLlmConfigForm('temperature', Number(value) || 0)}
                      />
                    </Grid.Col>
                    <Grid.Col span={{ base: 12, sm: 4 }}>
                      <NumberInput
                        label="提示词最大字符"
                        value={Number(llmConfigForm.max_prompt_chars ?? 900000)}
                        min={1000}
                        step={10000}
                        onChange={(value) => patchLlmConfigForm('max_prompt_chars', Number(value) || 900000)}
                      />
                    </Grid.Col>
                  <Grid.Col span={{ base: 12, sm: 4 }}>
                    <NumberInput
                      label="超时秒数"
                        value={Number(llmConfigForm.timeout_sec ?? 240)}
                        min={10}
                        step={10}
                        onChange={(value) => patchLlmConfigForm('timeout_sec', Number(value) || 240)}
                      />
                    </Grid.Col>
                  </Grid>
                  <Group mt="sm">
                    <Button onClick={saveLlmConfig}>保存配置</Button>
                    <Button variant="light" disabled={!selectedRunId} onClick={() => startReview(false)}>启动审查</Button>
                    <Button variant="subtle" disabled={!selectedRunId} onClick={() => startReview(true)}>强制重审</Button>
                    <Button variant="light" disabled={!selectedRunId} onClick={() => refreshReview()}>刷新状态</Button>
                  </Group>
                  <Text size="xs" c="dimmed" mt="sm">
                    运行中的审查会自动轮询 `status + report`，所以报告文本会边生成边显示，不必等到最终完成。
                  </Text>
                  <JsonInput mt="sm" value={llmConfigDraft} onChange={setLlmConfigDraft} autosize minRows={4} maxRows={8} validationError="JSON 格式不正确" label="高级 JSON 覆盖" />
                </Card>
                <Card mt="sm">
                  <Group justify="space-between" mb="xs">
                    <Text fw={800}>审查状态</Text>
                    <Badge variant="light">{llmStageLabel(llmStatus?.stage || llmStatus?.status)}</Badge>
                  </Group>
                  <div className="friendly-detail-grid">
                    <div className="friendly-detail-item">
                      <Text size="xs" c="dimmed">当前运行</Text>
                      <Text fw={700}>{shortText(selectedRunId || '尚未选择运行记录', 46)}</Text>
                    </div>
                    <div className="friendly-detail-item">
                      <Text size="xs" c="dimmed">报告状态</Text>
                      <Text fw={700}>{llmReport?.exists ? '已生成' : '未生成'}</Text>
                    </div>
                    <div className="friendly-detail-item">
                      <Text size="xs" c="dimmed">任务数</Text>
                      <Text fw={700}>{formatCount(llmJobs.length)}</Text>
                    </div>
                    <div className="friendly-detail-item">
                      <Text size="xs" c="dimmed">最近错误</Text>
                      <Text fw={700}>{shortText(llmStatus?.error || llmStatus?.message || '-', 60)}</Text>
                    </div>
                  </div>
                  <SummaryCard
                    title="流式审查进度"
                    description="这里专门追踪流式字符接收、阶段、报告来源和错误信息，方便判断当前是在排队、请求模型，还是已经开始持续写报告。"
                    items={reviewReportSummaryItems(llmStatus, llmReport)}
                    raw={llmStatus}
                    rawTitle="高级审查状态 JSON"
                  />
                </Card>
              </Grid.Col>
              <Grid.Col span={{ base: 12, xl: 7 }}>
                <Card>
                  <Group justify="space-between" mb="sm">
                    <Text fw={800}>审查报告</Text>
                    <Group gap="xs">
                      <Badge variant="light">{llmReport?.exists ? '已生成' : '未生成'}</Badge>
                      <Button size="xs" variant="light" disabled={!llmReport?.text} onClick={copyLlmReport}>
                        复制
                      </Button>
                      <Button size="xs" variant="light" disabled={!llmReport?.text} onClick={() => setLlmReportExpanded(true)}>
                        放大阅读
                      </Button>
                      <Button size="xs" variant="light" disabled={!llmReport?.text} onClick={downloadLlmReport}>
                        下载
                      </Button>
                    </Group>
                  </Group>
                  <ScrollArea.Autosize mah={620}>
                    <MarkdownReport
                      text={String(llmReport?.text || '')}
                      emptyText="当前运行还没有 LLM 审查报告。"
                    />
                  </ScrollArea.Autosize>
                  <Divider my="sm" />
                  <Group justify="space-between" mb="xs">
                    <Text fw={800}>审查任务队列</Text>
                    <Text size="xs" c="dimmed">点击任意任务可切换到对应 run；高亮按具体审查任务区分。</Text>
                  </Group>
                  <Stack gap={6}>
                    {llmJobs.length ? llmJobs.slice(0, 8).map((jobItem, index) => {
                      const jobKey = llmReviewJobKey(jobItem, String(index));
                      const isSelectedJob = jobKey === selectedLlmReviewJobKey;
                      return (
                        <Card
                          key={String(jobItem.job_id || jobItem.id || index)}
                          className={`insight-card queue-card-clickable ${isSelectedJob ? 'active' : ''}`}
                          onClick={() => {
                            const rid = String(jobItem.run_id || '').trim();
                            setSelectedLlmReviewJobKey(jobKey);
                            if (rid) {
                              void selectRun(rid, false, jobKey);
                            }
                          }}
                        >
                          <Group justify="space-between" align="flex-start">
                            <div>
                              <Text fw={700} size="sm">{shortText(jobItem.run_id || jobItem.job_id || jobItem.id || '审查任务', 52)}</Text>
                              <Text size="xs" c="dimmed">
                                阶段 {llmStageLabel(jobItem.stage || jobItem.status)}；模型 {jobItem.model || llmConfigForm.model || '-'}
                              </Text>
                              <Text size="xs" c="dimmed">
                                已接收 {formatCount(jobItem.received_chars || 0)} 字符；任务 {shortText(jobKey || '-', 42)}
                              </Text>
                            </div>
                            <Badge variant="light">{llmStageLabel(jobItem.status || jobItem.stage)}</Badge>
                          </Group>
                          {jobItem.message || jobItem.error ? (
                            <Text size="xs" mt={6} c={jobItem.error ? 'red' : 'dimmed'}>
                              {shortText(jobItem.error || jobItem.message, 160)}
                            </Text>
                          ) : null}
                        </Card>
                      );
                    }) : (
                      <Text size="sm" c="dimmed">暂无审查任务。启动审查后这里会实时显示队列和阶段。</Text>
                    )}
                  </Stack>
                </Card>
              </Grid.Col>
            </Grid>
          </Tabs.Panel>
        </Tabs>
      </section>

      <Modal
        opened={llmReportExpanded}
        onClose={() => setLlmReportExpanded(false)}
        title="LLM 审查报告"
        size="95vw"
        centered
        scrollAreaComponent={ScrollArea.Autosize}
      >
        <ScrollArea.Autosize mah="calc(100vh - 140px)">
          <MarkdownReport
            text={String(llmReport?.text || '')}
            emptyText="当前运行还没有 LLM 审查报告。"
            className="markdown-report-expanded"
          />
        </ScrollArea.Autosize>
      </Modal>

      <aside className="page-inspector">
        <Card className="sticky-inspector">
          <Text fw={800}>运行检视面板</Text>
          <Text size="xs" c="dimmed" mb="sm">
            当前选中运行的 manifest、最新指标，以及你在 AutoTuner / 实时监控里点中的对象详情。
          </Text>
          <ScrollArea.Autosize mah="calc(100vh - 150px)">
            <Stack>
              {selectedParam ? (
                <SelectionDetailCard
                  title="参数详情"
                  description="来自参数目录的选中项。"
                  bullets={[
                    `参数：${selectedParam.param_id || '-'}`,
                    `来源：${tunerSourceKindLabel(selectedParam.source_kind)} / 模块 ${selectedParam.module || '-'}`,
                    `当前值：${selectedParam.value}；可自动调参：${selectedParam.auto_tune_allowed ? '允许' : '仅观测'}`,
                    `影响指标：${asArray(selectedParam.impacts).join('、') || '无'}`,
                    `标签：${asArray(selectedParam.tags).join('、') || '无标签'}`,
                    `说明：${selectedParam.note || '当前没有额外备注。'}`,
                  ]}
                />
              ) : null}
              {selectedRule ? (
                <SelectionDetailCard
                  title="规则详情"
                  description="来自调参规则目录的选中项。"
                  bullets={[
                    `规则：${selectedRule.title || selectedRule.rule_id || selectedRule.id || '-'}`,
                    `来源：${selectedRule.rule_source || selectedRule.source || '-'}`,
                    `针对指标：${selectedRule.metric_key || '-'}；问题模式：${tunerIssueModeLabel(selectedRule.issue_mode)}`,
                    `目标参数：${selectedRule.param_id || '-'}；方向：${tunerDirectionLabel(selectedRule.direction)}`,
                    `禁用：${disabledRuleIds.has(String(selectedRule.rule_id || selectedRule.id || '')) ? '是' : '否'}；白名单：${protectedRuleIds.has(String(selectedRule.rule_id || selectedRule.id || '')) ? '是' : '否'}`,
                    `说明：${selectedRule.description || '当前规则目录没有补充说明。'}`,
                  ]}
                />
              ) : null}
              {selectedSuggestion ? (
                <SelectionDetailCard
                  title="LLM 建议详情"
                  description="来自 AutoTuner LLM 建议列表。"
                  bullets={[
                    `运行：${selectedSuggestion.run_id || '-'} / 时间：${selectedSuggestion.created_at_ms ? new Date(Number(selectedSuggestion.created_at_ms)).toLocaleString() : '-'}`,
                    `摘要：${llmSuggestionSummary(selectedSuggestion)}`,
                    `指标发现数：${formatCount(selectedSuggestion.counts?.metric_findings)}；建议试验数：${formatCount(selectedSuggestion.counts?.experiments)}；规则改动数：${formatCount(selectedSuggestion.counts?.rule_changes)}`,
                    `自动落地：${llmSuggestionApplyLabel(selectedSuggestion)}`,
                    `报告摘录：${shortText(selectedSuggestion.report_excerpt || '无', 220)}`,
                  ]}
                />
              ) : null}
              {selectedTunerJob ? (
                <SelectionDetailCard
                  title="AutoTuner LLM 任务详情"
                  description="来自 AutoTuner LLM 任务队列。"
                  bullets={[
                    `状态：${autoTunerJobStatusLabel(selectedTunerJob.status)}`,
                    `关联运行：${selectedTunerJob.run_id || '-'}`,
                    `模型：${selectedTunerJob.config?.model || autoTunerLlmForm.model || '-'}`,
                    `研究者补充：${shortText(selectedTunerJob.user_prompt || '无', 180)}`,
                    `结果：${shortText(selectedTunerJob.result?.error || selectedTunerJob.result?.message || selectedTunerJob.error || '暂无异常', 180)}`,
                  ]}
                />
              ) : null}
              {selectedBackgroundJob ? (
                <SummaryCard
                  title="后台任务详情"
                  description="来自后台任务队列。用于判断数据集是否在排队、等待主循环锁，或被维护任务阻塞。"
                  items={[
                    { label: '任务类型', value: jobTypeLabel(selectedBackgroundJob) },
                    { label: '阶段', value: jobStatusLabel(selectedBackgroundJob) },
                    { label: '进度', value: jobProgressText(selectedBackgroundJob) },
                    { label: '等待锁', value: selectedBackgroundJob.lock_waiting ? formatDuration(selectedBackgroundJob.lock_wait_ms) : '否' },
                    { label: '关联运行', value: selectedBackgroundJob.run_id || '-' },
                    { label: '错误', value: selectedBackgroundJob.error || '-' },
                  ]}
                  raw={selectedBackgroundJob}
                  rawTitle="高级后台任务 JSON"
                />
              ) : null}
              {(manifest?.live_selected as DisplayAggregateRow | undefined)?.__displayAggregate ? (
                <AggregateDetail value={manifest?.live_selected} title="结构波峰聚合详情" maxHeight={320} />
              ) : (
                <SummaryCard
                  title="运行清单摘要"
                  description="当前选中运行的基础信息与最新关键指标；完整 manifest 保留在高级区。"
                  items={manifestSummaryItems(manifest, latest)}
                  raw={manifest}
                  rawTitle="高级 Manifest JSON"
                />
              )}
              <SummaryCard
                title="最新指标行摘要"
                description="用于快速确认当前 run 的最后一行指标是否仍在正常范围。"
                items={latestMetricSummaryItems(latest)}
                raw={latest}
                rawTitle="高级 Latest Metric Row JSON"
              />
            </Stack>
          </ScrollArea.Autosize>
        </Card>
      </aside>
    </div>
  );
}
