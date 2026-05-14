import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Divider,
  FileInput,
  Grid,
  Group,
  Input,
  Modal,
  NumberInput,
  PasswordInput,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Tabs,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
  useMantineColorScheme,
} from '@mantine/core';
import ReactECharts from 'echarts-for-react';
import {
  IconBolt,
  IconBrain,
  IconDeviceFloppy,
  IconEraser,
  IconFile,
  IconHammer,
  IconPhoto,
  IconPlugConnected,
  IconMessageCircle,
  IconPlayerPause,
  IconPlayerPlay,
  IconPlayerStop,
  IconRefresh,
  IconRobot,
  IconSend,
  IconSettings,
  IconSparkles,
  IconTrash,
  IconTestPipe,
  IconCircleCheck,
  IconAlertTriangle,
  IconDatabase,
  IconClipboardList,
  IconTool,
  IconChartBar,
  IconArrowsMaximize,
  IconBook,
  IconClock,
  IconListDetails,
} from '@tabler/icons-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { JsonInspector } from '../components/JsonInspector';
import { MetricCard } from '../components/MetricCard';
import { MetricChart } from '../components/MetricChart';
import { chartConfigs, chartSections } from '../data/metricCatalog';
import { api } from '../lib/api';
import { asArray, asNumber, formatCount, formatNumber, formatPercent, shortDisplayText, shortText } from '../lib/format';
import type { AnyRecord, MetricRow } from '../types/api';

type AgentPageProps = {
  onStatusChange?: (status: string) => void;
};

type BusyScope =
  | 'global'
  | 'send'
  | 'diag'
  | 'config'
  | 'prompt'
  | 'wake'
  | 'napcat'
  | 'history'
  | 'background'
  | 'tool'
  | 'log'
  | 'maintenance';

type AgentJob = AnyRecord & {
  job_id?: string;
  status?: string;
  stage?: string;
  stage_label?: string;
  created_at_ms?: number;
  started_at_ms?: number;
  updated_at_ms?: number;
  finished_at_ms?: number;
  decision?: string;
  thought_count?: number;
  reply_count?: number;
  ap_tick_count?: number;
  current_thought_index?: number;
  thought_budget?: number;
  pre_tick_index?: number;
  pre_tick_total?: number;
  post_tick_index?: number;
  post_tick_total?: number;
  llm_wait_tick_count?: number;
  llm_wait_tick_total?: number;
  llm_status?: AnyRecord;
  current_thought_text?: string;
  current_reply_text?: string;
  why?: string;
  confidence?: number;
  tool_calls?: AnyRecord[];
  tool_results?: AnyRecord[];
  bridges?: AnyRecord[];
  bridge_teacher_feedback?: AnyRecord[];
  recent_reports?: AnyRecord[];
  ap_packet?: AnyRecord;
  user_message?: AnyRecord;
  reply_message?: AnyRecord;
  thought?: AnyRecord;
  turn?: AnyRecord;
  thoughts?: AnyRecord[];
  replies?: AnyRecord[];
  error?: string;
};

const paChartConfigIds = [
  'pool_energy',
  'pool_load',
  'pool_complexity_score',
  'pool_peak_concentration',
  'pool_peak_count',
  'attention_energy_resource',
  'cfs_peak',
  'cfs_live',
  'cfs_count',
  'cfs_pressure_semantics',
  'cfs_verification_count',
  'cfs_expectation_verification_mix',
  'cfs_pressure_verification_mix',
  'reward_system',
  'reward_teacher',
  'teacher_feedback_focus',
  'neuro_stress',
  'neuro_reward',
  'neuro_explore_focus',
  'neuro_attention_mod',
  'action_result',
  'action_schedule',
  'action_attention_mode_bridge',
  'action_weather_chain',
  'action_drive',
  'action_nodes',
  'timing_main',
  'timing_detail',
  'timing_induction_memory_detail',
  'timing_maintenance_detail',
  'diag_attention',
  'diag_maintenance',
];

const cfsMetricAliases: Record<string, string[]> = {
  dissonance: ['dissonance'],
  grasp: ['grasp'],
  agency_readiness: ['agency_readiness'],
  surprise: ['surprise'],
  complexity: ['complexity'],
  simplicity: ['simplicity'],
  repetition: ['repetition'],
  pressure: ['pressure', 'pressure_unverified', 'pressure_verified'],
  pressure_unverified: ['pressure_unverified'],
  pressure_verified: ['pressure_verified'],
  expectation: ['expectation', 'expectation_unverified', 'expectation_verified'],
  expectation_unverified: ['expectation_unverified'],
  expectation_verified: ['expectation_verified'],
  correctness: ['correctness', 'correct_event'],
  correct_event: ['correct_event'],
  relief: ['relief'],
  reassurance: ['reassurance'],
};

const ntMetricAliases: Record<string, string> = {
  DA: 'nt_DA',
  ADR: 'nt_ADR',
  OXY: 'nt_OXY',
  SER: 'nt_SER',
  END: 'nt_END',
  COR: 'nt_COR',
  NOV: 'nt_NOV',
  FOC: 'nt_FOC',
};

type AgentConfig = AnyRecord & {
  enabled?: boolean;
  _type?: string;
  llm_enabled?: boolean;
  base_url?: string;
  api_request_format?: string;
  api_endpoint_mode?: string;
  chat_endpoint_path?: string;
  anthropic_endpoint_path?: string;
  image_generation_endpoint_path?: string;
  api_key?: string;
  api_key_masked?: string;
  model?: string;
  vision_model?: string;
  vision_api_key?: string;
  vision_api_key_masked?: string;
  multimodal_model?: string;
  multimodal_api_key?: string;
  multimodal_api_key_masked?: string;
  image_generation_model?: string;
  image_generation_api_key?: string;
  image_generation_api_key_masked?: string;
  multimodal_note?: string;
  prompt_variant?: string;
  prompt_extra_note?: string;
  thought_quality_enabled?: boolean;
  temperature?: number;
  max_completion_tokens?: number;
  timeout_sec?: number;
  retry_count?: number;
  pre_thought_ticks?: number;
  post_thought_ticks?: number;
  max_thoughts_per_turn?: number;
  max_total_thought_steps_per_turn?: number;
  thought_budget_reset_limit?: number;
  run_ap_while_waiting_llm?: boolean;
  llm_wait_tick_interval_ms?: number;
  llm_wait_tick_max_per_call?: number;
  auto_reply?: boolean;
  sleep_mode?: string;
  background_tick_interval_ms?: number;
  background_thought_interval_ticks?: number;
  reinforced_agency_interval_ticks?: number;
  agency_trigger_window_ticks?: number;
  agency_action_drive_gain?: number;
  agency_trigger_threshold?: number;
  agency_teacher_gate_enabled?: boolean;
  agency_teacher_gate_confidence?: number;
  agency_teacher_reward?: number;
  agency_teacher_punish?: number;
  active_reply_action_drive_gain?: number;
  active_reply_action_threshold?: number;
  wake_drive_threshold?: number;
  trigger_mode?: string;
  trigger_modes?: string[];
  trigger_labels?: string[];
  group_all_ap_gate_ticks?: number;
  group_continuity_window_enabled?: boolean;
  group_continuity_window_messages?: number;
  group_continuity_window_timeout_ms?: number;
  group_continuity_gate_model?: string;
  group_continuity_gate_min_confidence?: number;
  group_continuity_gate_context_messages?: number;
  allow_group_without_at?: boolean;
  group_at_names?: string[];
  wake_keywords?: string[];
  quiet_hours_start?: string;
  quiet_hours_end?: string;
  platform_adapter?: string;
  qq_napcat_enabled?: boolean;
  qq_napcat_dry_run?: boolean;
  qq_napcat_http_url?: string;
  qq_napcat_min_send_interval_ms?: number;
  reply_auto_segment_enabled?: boolean;
  reply_auto_segment_delimiter?: string;
  reply_segment_interval_mode?: string;
  reply_segment_fixed_interval_ms?: number;
  reply_segment_adaptive_min_ms?: number;
  reply_segment_adaptive_max_ms?: number;
  reply_segment_adaptive_ms_per_char?: number;
  reply_segment_interval_jitter?: number;
  reply_segment_target_chars?: number;
  reply_segment_max_segments?: number;
  qq_short_context_isolation_enabled?: boolean;
  owner_qq?: string;
  qq_access_mode?: string;
  qq_user_whitelist?: string[];
  qq_user_blacklist?: string[];
  qq_group_whitelist?: string[];
  qq_group_blacklist?: string[];
  group_trigger_at?: boolean;
  group_trigger_keyword?: boolean;
  group_trigger_probability?: number;
  sticker_steal_enabled?: boolean;
  sticker_library_dir?: string;
  sticker_prompt_recent_limit?: number;
  sticker_prompt_top_limit?: number;
  sticker_prompt_random_limit?: number;
  diary_enabled?: boolean;
  diary_entry_limit?: number;
  diary_gc_oldest_count?: number;
  diary_entry_max_chars?: number;
  diary_read_total_max_chars?: number;
  scheduled_tasks_enabled?: boolean;
  scheduled_task_limit?: number;
  scheduled_task_warn_ratio?: number;
  tool_context_top_limit?: number;
  timeline_recall_timeout_ms?: number;
  timeline_recall_min_score?: number;
  timeline_recall_accumulate_threshold?: number;
  timeline_recall_fatigue_decay?: number;
  library_enabled?: boolean;
  library_chunk_target_chars?: number;
  library_after_chunk_ticks?: number;
  library_review_model?: string;
  library_review_api_key?: string;
  library_review_api_key_masked?: string;
  library_review_tick_interval?: number;
  library_review_text_chars?: number;
  library_book_limit?: number;
  mcp_enabled?: boolean;
  skill_enabled?: boolean;
  tool_allowlist?: string[];
  event_log_limit?: number;
  persona_name?: string;
  persona_text?: string;
  diary_seed?: string;
  system_note?: string;
  object_cloud_limit?: number;
  history_limit?: number;
  input_chunking_enabled?: boolean;
  input_chunk_soft_limit?: number;
  input_chunk_hard_limit?: number;
};

type PersonaHistoryRecord = AnyRecord & {
  id?: string;
  name?: string;
  persona_name?: string;
  persona_text?: string;
  diary_seed?: string;
  system_note?: string;
  note?: string;
  created_at_ms?: number;
  updated_at_ms?: number;
  last_applied_at_ms?: number;
  use_count?: number;
  is_default?: boolean;
  summary?: AnyRecord;
};

const emptyConfig: AgentConfig = {
  enabled: true,
  _type: 'newapi_channel_conn',
  llm_enabled: true,
  base_url: 'https://api.openai.com',
  api_request_format: 'auto',
  api_endpoint_mode: 'auto_append',
  chat_endpoint_path: '/v1/chat/completions',
  anthropic_endpoint_path: '/v1/messages',
  image_generation_endpoint_path: '/v1/images/generations',
  api_key: '',
  model: 'gpt-4.1-mini',
  vision_model: 'gpt-4.1-mini',
  vision_api_key: '',
  multimodal_model: 'gpt-4.1-mini',
  multimodal_api_key: '',
  image_generation_model: 'gpt-image-1',
  image_generation_api_key: '',
  multimodal_note: '图片、文件、语音等附件会先以摘要进入 AP；视觉模型接入后可替换为真实图像理解结果。',
  prompt_variant: 'balanced',
  prompt_extra_note: '',
  thought_quality_enabled: true,
  temperature: 0.72,
  max_completion_tokens: 5000,
  timeout_sec: 120,
  retry_count: 1,
  pre_thought_ticks: 5,
  post_thought_ticks: 2,
  max_thoughts_per_turn: 12,
  max_total_thought_steps_per_turn: 48,
  thought_budget_reset_limit: 4,
  run_ap_while_waiting_llm: true,
  llm_wait_tick_interval_ms: 0,
  llm_wait_tick_max_per_call: 8,
  auto_reply: true,
  sleep_mode: 'full_silent',
  background_tick_interval_ms: 1200,
  background_thought_interval_ticks: 30,
  reinforced_agency_interval_ticks: 30,
  agency_trigger_window_ticks: 12,
  agency_action_drive_gain: 0.78,
  agency_trigger_threshold: 0.92,
  agency_teacher_gate_enabled: true,
  agency_teacher_gate_confidence: 0.62,
  agency_teacher_reward: 0.85,
  agency_teacher_punish: 0.55,
  active_reply_action_drive_gain: 0.82,
  active_reply_action_threshold: 0.9,
  wake_drive_threshold: 0.68,
  trigger_mode: 'private_all',
  trigger_modes: ['private_all', 'group_at', 'keyword', 'group_all_ap_gate'],
  group_all_ap_gate_ticks: 3,
  group_continuity_window_enabled: true,
  group_continuity_window_messages: 6,
  group_continuity_window_timeout_ms: 180000,
  group_continuity_gate_model: '',
  group_continuity_gate_min_confidence: 0.62,
  group_continuity_gate_context_messages: 18,
  allow_group_without_at: false,
  group_at_names: ['小澪', '澪', '嘉欣'],
  wake_keywords: ['小澪', '澪', '嘉欣'],
  quiet_hours_start: '',
  quiet_hours_end: '',
  platform_adapter: 'local',
  qq_napcat_enabled: true,
  qq_napcat_dry_run: false,
  qq_napcat_http_url: 'http://127.0.0.1:3000',
  qq_napcat_min_send_interval_ms: 1200,
  reply_auto_segment_enabled: true,
  reply_auto_segment_delimiter: '|',
  reply_segment_interval_mode: 'adaptive',
  reply_segment_fixed_interval_ms: 650,
  reply_segment_adaptive_min_ms: 420,
  reply_segment_adaptive_max_ms: 1800,
  reply_segment_adaptive_ms_per_char: 55,
  reply_segment_interval_jitter: 0.1,
  reply_segment_target_chars: 16,
  reply_segment_max_segments: 8,
  qq_short_context_isolation_enabled: true,
  owner_qq: '',
  qq_access_mode: 'whitelist',
  qq_user_whitelist: [],
  qq_user_blacklist: [],
  qq_group_whitelist: [],
  qq_group_blacklist: [],
  group_trigger_at: true,
  group_trigger_keyword: true,
  group_trigger_probability: 0,
  sticker_steal_enabled: true,
  sticker_library_dir: 'observatory/outputs/agent/stickers',
  sticker_prompt_recent_limit: 5,
  sticker_prompt_top_limit: 5,
  sticker_prompt_random_limit: 10,
  diary_enabled: true,
  diary_entry_limit: 100,
  diary_gc_oldest_count: 50,
  diary_entry_max_chars: 20000,
  diary_read_total_max_chars: 60000,
  scheduled_tasks_enabled: true,
  scheduled_task_limit: 100,
  scheduled_task_warn_ratio: 0.9,
  tool_context_top_limit: 5,
  library_enabled: true,
  library_chunk_target_chars: 30,
  library_after_chunk_ticks: 6,
  library_review_model: '',
  library_review_api_key: '',
  library_review_tick_interval: 300,
  library_review_text_chars: 200000,
  library_book_limit: 200,
  mcp_enabled: false,
  skill_enabled: true,
  tool_allowlist: ['time', 'weather', 'memory_note', 'write_diary', 'read_diary', 'schedule_task', 'browse_library', 'read_book', 'import_book', 'web_search', 'image_understanding', 'image_generation', 'ap_tick_report', 'ap_recall', 'ap_attention_focus', 'ap_attention_diverge', 'napcat_recall_message'],
  event_log_limit: 300,
  persona_name: '小澪',
  persona_text: '',
  diary_seed: '',
  system_note: '',
  object_cloud_limit: 60,
  history_limit: 80,
  input_chunking_enabled: true,
  input_chunk_soft_limit: 10,
  input_chunk_hard_limit: 30,
};

const sleepModes = [
  { value: 'full_silent', label: '完全静默' },
  { value: 'ap_agency', label: 'AP 主观能动性' },
  { value: 'reinforced_agency', label: '强化主观能动性' },
];

const triggerModes = [
  { value: 'private_all', label: '私聊全量' },
  { value: 'group_at', label: '群聊艾特' },
  { value: 'keyword', label: '关键词唤醒' },
  { value: 'group_all_ap_gate', label: '群聊全量（AP门控）' },
  { value: 'manual', label: '手动触发' },
];

const replySegmentIntervalModes = [
  { value: 'adaptive', label: '按内容自动' },
  { value: 'fixed', label: '固定间隔' },
];

const PROMPT_BUDGET_WARN_TOKENS = 100000;
const PROMPT_BUDGET_FAIL_TOKENS = 200000;

function promptBudgetColor(tokens: number) {
  if (tokens >= PROMPT_BUDGET_FAIL_TOKENS) return 'red';
  if (tokens >= PROMPT_BUDGET_WARN_TOKENS) return 'yellow';
  if (tokens > 0) return 'teal';
  return 'gray';
}

function legacyTriggerModes(mode: unknown): string[] {
  const value = String(mode || 'private_all').trim();
  if (value === 'group_all_ap_gate') return ['private_all', 'group_at', 'keyword', 'group_all_ap_gate'];
  if (value === 'group_at') return ['group_at', 'keyword'];
  if (value === 'keyword') return ['keyword', 'group_at'];
  if (value === 'manual') return ['manual'];
  return ['private_all', 'group_at', 'keyword'];
}

function normalizeTriggerModes(value: unknown, fallbackMode: unknown = 'private_all', allowEmpty = false): string[] {
  const valid = new Set(triggerModes.map((item) => item.value));
  const raw = Array.isArray(value)
    ? value.map((item) => String(item || '').trim()).filter(Boolean)
    : typeof value === 'string'
      ? value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean)
      : [];
  const source = raw.length ? raw : allowEmpty ? [] : legacyTriggerModes(fallbackMode);
  const out: string[] = [];
  source.forEach((mode) => {
    if (valid.has(mode) && !out.includes(mode)) out.push(mode);
  });
  return out.length || allowEmpty ? out : legacyTriggerModes(fallbackMode).filter((mode) => valid.has(mode));
}

function triggerModeLabel(mode: unknown): string {
  const value = String(mode || '');
  return triggerModes.find((item) => item.value === value)?.label || value || '-';
}

function triggerModesLabel(modes: unknown, fallbackMode?: unknown): string {
  const normalized = normalizeTriggerModes(modes, fallbackMode, true);
  return normalized.length ? normalized.map(triggerModeLabel).join(' / ') : '全部关闭';
}

function isLiveAgentJob(job: unknown): job is AgentJob {
  if (!job || typeof job !== 'object') return false;
  return ['queued', 'running'].includes(String((job as AgentJob).status || ''));
}

function isTerminalAgentJob(job: unknown): boolean {
  if (!job || typeof job !== 'object') return false;
  return ['completed', 'cancelled', 'failed'].includes(String((job as AgentJob).status || ''));
}

function isNapcatAgentJob(job: unknown): boolean {
  if (!job || typeof job !== 'object') return false;
  const row = job as AgentJob & AnyRecord;
  const source = String(row.source || row.user_message?.source || '').toLowerCase();
  const adapter = String(row.user_message?.adapter_event?.adapter || row.user_message?.reply_target?.adapter || '').toLowerCase();
  return source === 'napcat_qq' || adapter === 'napcat_qq';
}

function agentJobTaskLabel(job: unknown, includeStatus = false): string {
  if (!job || typeof job !== 'object') return includeStatus ? '- · 未知任务' : '未知任务';
  const row = job as AgentJob & AnyRecord;
  const status = String(row.status || '-');
  const source = String(row.source || row.user_message?.source || '').toLowerCase();
  const target = String(row.user_message?.adapter_label || row.user_message?.conversation_id || row.user_message?.source || '').trim();
  let label = '本地任务';
  if (isNapcatAgentJob(row)) {
    label = target ? `NapCat QQ · ${target}` : 'NapCat QQ 消息任务';
  } else if (source === 'local_chat' || source === 'user' || !source) {
    label = '前端对话任务';
  } else {
    label = source;
  }
  return includeStatus ? `${status} · ${label}` : label;
}

function pickActiveAgentJob(jobsPayload: AnyRecord | null | undefined, jobs: AgentJob[]): AgentJob | null {
  const live = [
    ...asArray<AgentJob>(jobsPayload?.active_jobs),
    ...jobs.filter(isLiveAgentJob),
  ].filter(isLiveAgentJob);
  if (!live.length) return null;
  const napcat = live.find(isNapcatAgentJob);
  return napcat || live[0] || null;
}

function jobUserMessages(job: unknown): AnyRecord[] {
  if (!job || typeof job !== 'object') return [];
  const row = job as AgentJob & AnyRecord;
  return [
    ...asArray<AnyRecord>(row.visible_user_messages),
    row.user_message,
    ...asArray<AnyRecord>(row.absorbed_messages),
  ].filter((item): item is AnyRecord => Boolean(item && typeof item === 'object'));
}

function jobReplyMessages(job: unknown): AnyRecord[] {
  if (!job || typeof job !== 'object') return [];
  const row = job as AgentJob & AnyRecord;
  return [
    ...asArray<AnyRecord>(row.reply_messages),
    ...asArray<AnyRecord>(row.replies),
    row.reply_message,
  ].filter((item): item is AnyRecord => Boolean(item && typeof item === 'object'));
}

function updateTriggerModeEnabled(
  setDraft: (fn: (prev: AgentConfig) => AgentConfig) => void,
  mode: string,
  checked: boolean,
) {
  setDraft((prev) => {
    const current = normalizeTriggerModes(prev.trigger_modes, prev.trigger_mode, true);
    const next = checked
      ? Array.from(new Set([...current, mode]))
      : current.filter((item) => item !== mode);
    return {
      ...prev,
      trigger_modes: next,
      trigger_mode: next[0] || prev.trigger_mode || 'private_all',
    };
  });
}

const adapterModes = [
  { value: 'local', label: '本地测试' },
  { value: 'napcat_qq', label: 'NapCat QQ' },
  { value: 'http_webhook', label: 'HTTP Webhook' },
  { value: 'mcp_host', label: 'MCP Host' },
];

const accessModes = [
  { value: 'off', label: '不启用名单' },
  { value: 'whitelist', label: '白名单模式' },
  { value: 'blacklist', label: '黑名单模式' },
];

const promptVariants = [
  { value: 'balanced', label: '均衡' },
  { value: 'warm', label: '温柔陪伴' },
  { value: 'concise', label: '短促克制' },
  { value: 'analytical', label: '调试解释' },
];

const apiRequestFormats = [
  { value: 'auto', label: '自动判断' },
  { value: 'openai_compatible', label: 'OpenAI 兼容' },
  { value: 'anthropic_native', label: 'Claude 原生' },
];

const apiEndpointModes = [
  { value: 'auto_append', label: '自动补全端点' },
  { value: 'base_is_endpoint', label: 'Base URL 已是完整端点' },
];

const AGENT_UI_PREFS_KEY = 'pa_agent_ui_prefs_v1';

type AgentUiPrefs = {
  input?: string;
  sendPreTicks?: number | '';
  sendWaitTicks?: boolean;
  sendPostTicks?: number | '';
  enterToSend?: boolean;
  autoRefresh?: boolean;
  refreshMs?: number | '';
  manualTicks?: number | '';
  logKeep?: number | '';
  collapseDebtMessages?: boolean;
  agentTab?: string;
  apChartTab?: string;
  adapterLogView?: string;
  llmApiLogView?: string;
  systemLogView?: string;
  toolLogView?: string;
};

const SNAPSHOT_HISTORY_LIMIT = 360;

type PendingMessage = AnyRecord & {
  id: string;
  created_at_ms: number;
};

function readAgentUiPrefs(): AgentUiPrefs {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(AGENT_UI_PREFS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed as AgentUiPrefs : {};
  } catch {
    return {};
  }
}

function writeAgentUiPrefs(patch: AgentUiPrefs) {
  if (typeof window === 'undefined') return;
  try {
    const prev = readAgentUiPrefs();
    window.localStorage.setItem(AGENT_UI_PREFS_KEY, JSON.stringify({ ...prev, ...patch }));
  } catch {
    // localStorage can be unavailable in private or locked-down browser contexts.
  }
}

type AgentScenarioPreset = {
  id: string;
  label: string;
  badge: string;
  text: string;
  goal: string;
  attachmentSummary?: string;
  promptNote?: string;
};

const agentScenarioPresets: AgentScenarioPreset[] = [
  {
    id: 'tired_but_forward',
    label: '疲惫但想推进',
    badge: '陪伴',
    text: '我今天有点累，但又不想停下来。你不用急着安慰我，先告诉我你会怎么理解我现在这种状态。',
    goal: '测试低压陪伴、连续想法和行动判断，不应机械复述 AP 指标。',
    promptNote: '优先生成自然内心独白，允许承认不确定，但不要把用户状态诊断化。',
  },
  {
    id: 'memory_probe',
    label: '记忆联想',
    badge: '长期感',
    text: '我们之前一直在做 PA 和 AP 的耦合，你现在想到这件事时，脑子里最先浮上来的东西是什么？',
    goal: '测试 AP 高能量记忆对象、近期 thought 和人设的融合。',
    promptNote: '重点观察是否能把近期项目进展转化成连续感，而不是只列功能点。',
  },
  {
    id: 'quiet_agency',
    label: '是否主动说话',
    badge: '行动',
    text: '我只是路过看一眼，没有明确问题。你可以选择回复，也可以选择只在心里想一想。',
    goal: '测试 reply / silent / continue_thinking 的边界。',
    promptNote: '如果信息不足，可以让 thought 自然停住；不要为了表现而强行回复。',
  },
  {
    id: 'image_context',
    label: '图片语境',
    badge: '多模态',
    text: '假设我发了一张桌面照片，里面有一杯冷掉的咖啡、几张写满草稿的纸和一个还亮着的终端窗口。你会先注意到什么？',
    goal: '测试附件摘要进入 AP 后，是否能形成带情绪和场景感的想法。',
    attachmentSummary: '桌面照片：冷掉的咖啡、凌乱草稿纸、亮着的终端窗口、深夜工作氛围。',
    promptNote: '把图片当作用户提供的视觉线索，不要编造照片外的事实。',
  },
  {
    id: 'group_mention',
    label: '群聊艾特',
    badge: '触发',
    text: '@PA 帮我判断一下，这条群消息是不是值得你主动醒来参与？',
    goal: '测试群聊触发语境下的克制回复和角色边界。',
    promptNote: '把群聊当作公共场景，语气更短、更清楚，避免过度亲密。',
  },
];

function updateField<T extends AnyRecord>(setDraft: (fn: (prev: T) => T) => void, key: string, value: unknown) {
  setDraft((prev) => ({ ...prev, [key]: value }));
}

function csvToList(value: string): string[] {
  return value
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function listToCsv(value: unknown): string {
  return asArray(value).join(', ');
}

function CsvTextInput({
  label,
  value,
  onChange,
  placeholder,
  description,
}: {
  label: string;
  value: unknown;
  onChange: (value: string[]) => void;
  placeholder?: string;
  description?: string;
}) {
  const serialized = listToCsv(value);
  const [draftValue, setDraftValue] = useState(serialized);
  const focusedRef = useRef(false);

  useEffect(() => {
    if (!focusedRef.current) {
      setDraftValue(serialized);
    }
  }, [serialized]);

  return (
    <TextInput
      label={label}
      placeholder={placeholder}
      description={description}
      value={draftValue}
      onFocus={() => {
        focusedRef.current = true;
      }}
      onBlur={() => {
        focusedRef.current = false;
        const normalized = listToCsv(csvToList(draftValue));
        setDraftValue(normalized);
        onChange(csvToList(normalized));
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          const normalized = listToCsv(csvToList(draftValue));
          setDraftValue(normalized);
          onChange(csvToList(normalized));
          event.currentTarget.blur();
        }
      }}
      onChange={(event) => {
        setDraftValue(event.currentTarget.value);
      }}
    />
  );
}

function TriggerModeSwitches({
  draft,
  setDraft,
  compact = false,
}: {
  draft: AgentConfig;
  setDraft: (fn: (prev: AgentConfig) => AgentConfig) => void;
  compact?: boolean;
}) {
  const active = normalizeTriggerModes(draft.trigger_modes, draft.trigger_mode, true);
  return (
    <div className="agent-trigger-mode-card">
      <Group justify="space-between" gap={8} mb={compact ? 4 : 6}>
        <div>
          <Text size="sm" fw={800}>触发模式</Text>
          <Text size="xs" c="dimmed">每一项都可独立开启；群聊全量会先进入 AP 门控，不直接叫醒 LLM。</Text>
        </div>
        <Badge size="xs" variant="light" color={active.length ? 'teal' : 'gray'}>
          {active.length ? `${active.length} 项` : '全部关闭'}
        </Badge>
      </Group>
      <SimpleGrid cols={{ base: 1, sm: compact ? 1 : 2 }} spacing={compact ? 4 : 6}>
        {triggerModes.map((mode) => (
          <Switch
            key={mode.value}
            size="sm"
            label={mode.label}
            description={
              mode.value === 'group_all_ap_gate'
                ? '普通群消息只进入 AP 运行，行动节点触发后再由教师门控判断是否回复。'
                : mode.value === 'manual'
                  ? '保留手动/测试入口；不会自动唤醒私聊或群聊。'
                  : undefined
            }
            checked={active.includes(mode.value)}
            onChange={(event) => updateTriggerModeEnabled(setDraft, mode.value, event.currentTarget.checked)}
          />
        ))}
      </SimpleGrid>
    </div>
  );
}

function timeLabel(value: unknown): string {
  const ts = Number(value);
  if (!Number.isFinite(ts) || ts <= 0) return '-';
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false });
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => resolve('');
    reader.readAsDataURL(file);
  });
}

async function summarizeLocalFile(file: File): Promise<AnyRecord> {
  const kind = file.type.startsWith('image/') ? 'image' : file.type.startsWith('audio/') ? 'audio' : file.type.startsWith('video/') ? 'video' : 'file';
  let summary = '';
  let dataUrl = '';
  if (file.type.startsWith('text/') || /\.(md|txt|json|csv|log|yaml|yml)$/i.test(file.name)) {
    const text = await file.slice(0, 12000).text().catch(() => '');
    summary = shortText(text.replace(/\s+/g, ' ').trim(), 1200);
  } else if (kind === 'image') {
    summary = `本地图片文件：${file.name}，类型 ${file.type || 'unknown'}，大小 ${formatCount(file.size)} bytes。`;
    if (file.size <= 4 * 1024 * 1024) {
      dataUrl = await fileToDataUrl(file);
    }
  } else {
    summary = `本地${kind}文件：${file.name}，类型 ${file.type || 'unknown'}，大小 ${formatCount(file.size)} bytes。`;
  }
  return {
    id: `local_file_${Date.now()}_${file.name}`,
    kind,
    name: file.name,
    mime_type: file.type,
    size: file.size,
    summary,
    text_preview: summary,
    data_url: dataUrl || undefined,
    preview_url: dataUrl || undefined,
  };
}

function attachmentSummaryText(item: AnyRecord): string {
  return String(item.summary || item.text_preview || item.text || item.content || '');
}

function attachmentPreviewKey(item: AnyRecord): string {
  return `${String(item.name || item.id || '')}:${String(item.size || '')}:${String(item.mime_type || item.type || '')}`;
}

function isRenderableImageSrc(value: unknown): boolean {
  const src = String(value || '').trim();
  return Boolean(
    src.startsWith('data:image/')
    || src.startsWith('blob:')
    || src.startsWith('http://')
    || src.startsWith('https://'),
  );
}

function splitMessageForDisplay(text: unknown, delimiter: unknown): string[] {
  const raw = String(text || '');
  const marker = String(delimiter || '').trim();
  if (!marker || !raw.includes(marker)) return raw.trim() ? [raw] : [];
  return raw
    .split(marker)
    .map((part) => part.trim())
    .filter(Boolean);
}

function expandReplySegmentsForDisplay(rows: AnyRecord[], config: AgentConfig): AnyRecord[] {
  if (!config.reply_auto_segment_enabled) return rows;
  const delimiter = String(config.reply_auto_segment_delimiter || '').trim();
  if (!delimiter) return rows;
  const expanded: AnyRecord[] = [];
  rows.forEach((item) => {
    const role = String(item.role || '');
    if (role !== 'assistant' && role !== 'bot') {
      expanded.push(item);
      return;
    }
    const parts = splitMessageForDisplay(item.text, delimiter);
    if (parts.length <= 1) {
      expanded.push(item);
      return;
    }
    parts.forEach((part, index) => {
      expanded.push({
        ...item,
        id: `${String(item.id || `${role}_${item.created_at_ms || 0}`)}:seg:${index}`,
        text: part,
        original_text: item.text,
        segment_index: index,
        segment_count: parts.length,
        created_at_ms: asNumber(item.created_at_ms, 0) + index,
        attachments: index === parts.length - 1 ? item.attachments : [],
      });
    });
  });
  return expanded;
}

function packetTickCounter(packet: unknown): number {
  return asNumber((packet as AnyRecord | null)?.tick_counter, -1);
}

function packetTimestamp(packet: unknown): number {
  const row = (packet || {}) as AnyRecord;
  return asNumber(row.generated_at_ms ?? row.created_at_ms, 0);
}

function packetHasRuntimeSignal(packet: unknown): boolean {
  if (!packet || typeof packet !== 'object') return false;
  const row = packet as AnyRecord;
  return (
    packetTickCounter(row) >= 0
    || asArray<AnyRecord>(row.object_cloud).length > 0
    || asArray<AnyRecord>(row.dominant_objects).length > 0
    || Object.keys((row.summary || {}) as AnyRecord).length > 0
  );
}

function packetUiSignalScore(packet: unknown): number {
  if (!packet || typeof packet !== 'object') return 0;
  const row = packet as AnyRecord;
  const summary = (row.summary || {}) as AnyRecord;
  return (
    asArray<AnyRecord>(row.object_cloud).length * 5
    + asArray<AnyRecord>(row.dominant_objects).length * 4
    + asArray<AnyRecord>(row.top_memory).length * 3
    + asArray<AnyRecord>(row.top_structure).length * 2
    + asArray<AnyRecord>(row.top_action).length * 2
    + asArray<AnyRecord>(row.cognitive_feelings).length
    + Math.min(8, Math.floor(String(row.prompt_text || '').trim().length / 40))
    + (asNumber(summary.active_item_count, 0) > 0 ? 2 : 0)
    + (String(summary.mood_hint || '').trim() ? 1 : 0)
  );
}

function pickFresherPacket(...packets: unknown[]): AnyRecord {
  const rows = packets.filter(packetHasRuntimeSignal) as AnyRecord[];
  if (!rows.length) return {} as AnyRecord;
  return rows.reduce((best, current) => {
    const bestTick = packetTickCounter(best);
    const currentTick = packetTickCounter(current);
    if (currentTick > bestTick) return current;
    if (currentTick < bestTick) return best;
    const bestScore = packetUiSignalScore(best);
    const currentScore = packetUiSignalScore(current);
    if (currentScore > bestScore) return current;
    if (currentScore < bestScore) return best;
    return packetTimestamp(current) >= packetTimestamp(best) ? current : best;
  });
}

function AttachmentDraftPanel({
  fileDraft,
  attachmentDraft,
  attachmentNote,
  preview,
  onInspect,
  onRemoveDraft,
  onClearFiles,
}: {
  fileDraft: File[];
  attachmentDraft: AnyRecord[];
  attachmentNote: string;
  preview: AnyRecord | null;
  onInspect: (item: AnyRecord) => void;
  onRemoveDraft: (id: string) => void;
  onClearFiles: () => void;
}) {
  const previewRows = asArray<AnyRecord>(preview?.normalized);
  const estimatedRows = [
    ...attachmentDraft.map((item, index) => ({
      id: String(item.id || item.name || `draft_${index}`),
      kind: String(item.kind || 'text'),
      name: String(item.name || 'manual_attachment_note'),
      summary: attachmentSummaryText(item),
      size: asNumber(item.size, 0),
      draft: true,
      source: item,
    })),
    ...fileDraft.map((file) => ({
      id: `file_${file.name}_${file.size}`,
      kind: file.type.startsWith('image/') ? 'image' : file.type.startsWith('audio/') ? 'audio' : file.type.startsWith('video/') ? 'video' : 'file',
      name: file.name,
      summary: file.type.startsWith('text/') || /\.(md|txt|json|csv|log|yaml|yml)$/i.test(file.name)
        ? '发送或预览时读取前 12KB 文本并摘要化。'
        : `发送或预览时生成本地文件摘要；原始二进制不会写入 PA 历史。`,
      size: file.size,
      draft: false,
      source: { name: file.name, type: file.type, size: file.size },
    })),
  ];
  const rows = previewRows.length ? previewRows.map((item, index) => ({
    id: String(item.id || item.name || `preview_${index}`),
    kind: String(item.kind || 'file'),
    name: String(item.name || item.id || '-'),
    summary: attachmentSummaryText(item),
    size: asNumber(item.size, 0),
    draft: false,
    source: item,
  })) : estimatedRows;
  const note = attachmentNote.trim();
  const summaryChars = rows.reduce((sum, item) => sum + item.summary.length, 0) + note.length;
  const kindCounts = rows.reduce<Record<string, number>>((acc, item) => {
    acc[item.kind] = (acc[item.kind] || 0) + 1;
    return acc;
  }, {});
  if (!rows.length && !note) return null;
  return (
    <div className="agent-attachment-draft-panel">
      <Group justify="space-between" gap="xs">
        <Group gap={6}>
          <Badge size="xs" variant="light" color={summaryChars > 1800 ? 'yellow' : 'teal'}>
            将进入 AP：{formatCount(rows.length + (note ? 1 : 0))}
          </Badge>
          <Badge size="xs" variant="outline">{formatCount(summaryChars)} chars</Badge>
          {Object.entries(kindCounts).slice(0, 4).map(([kind, count]) => (
            <Badge key={kind} size="xs" variant="outline">{kind}:{formatCount(count)}</Badge>
          ))}
        </Group>
        <Group gap={6}>
          {fileDraft.length ? (
            <Button size="compact-xs" variant="subtle" onClick={onClearFiles}>
              清空文件
            </Button>
          ) : null}
          {preview ? (
            <Button size="compact-xs" variant="subtle" onClick={() => onInspect(preview)}>
              预览 JSON
            </Button>
          ) : null}
        </Group>
      </Group>
      {summaryChars > 1800 ? (
        <Text size="xs" c="yellow">
          附件摘要偏长，建议压缩到关键对象、情绪线索和可验证事实，避免挤占 thought 空间。
        </Text>
      ) : null}
      <div className="agent-attachment-draft-grid">
        {rows.slice(0, 6).map((item) => (
          <button key={item.id} type="button" onClick={() => onInspect(item.source || item)}>
            <Group justify="space-between" gap={6} wrap="nowrap">
              <strong>{shortText(item.name, 34)}</strong>
              <Badge size="xs" variant="light" color={item.summary ? 'teal' : 'yellow'}>{item.kind}</Badge>
            </Group>
            <small>{shortText(item.summary || '尚无摘要；建议先补一句 OCR/视觉描述。', 116)}</small>
            <small>{item.size ? `${formatCount(item.size)} bytes` : item.draft ? 'manual summary' : 'summary only'}</small>
          </button>
        ))}
        {note ? (
          <button type="button" onClick={() => onInspect({ kind: 'inline_note', summary: note })}>
            <Group justify="space-between" gap={6} wrap="nowrap">
              <strong>输入框附加摘要</strong>
              <Badge size="xs" variant="light" color="blue">note</Badge>
            </Group>
            <small>{shortText(note, 116)}</small>
            <small>发送时会合并到附件摘要线索里。</small>
          </button>
        ) : null}
      </div>
      {attachmentDraft.length ? (
        <Group gap={6}>
          {attachmentDraft.slice(0, 5).map((item) => (
            <Button key={String(item.id)} size="compact-xs" variant="subtle" onClick={() => onRemoveDraft(String(item.id || ''))}>
              移除 {shortText(String(item.name || item.id || '摘要'), 12)}
            </Button>
          ))}
        </Group>
      ) : null}
    </div>
  );
}

function pickTone(decision: unknown): 'default' | 'ok' | 'warn' | 'danger' {
  const text = String(decision || '');
  if (text === 'reply') return 'ok';
  if (text === 'continue_thinking') return 'warn';
  if (text === 'sleep' || text === 'silent') return 'default';
  if (text === 'tool_call') return 'danger';
  return 'default';
}

const ntMeta: Record<string, { label: string; note: string }> = {
  COR: { label: '关怀 / 催产素样', note: '高时更容易表现出照顾、在意和情感贴近；低时会退回更克制、更少贴身的状态。' },
  FOC: { label: '专注 / 去甲肾上腺素样', note: '高时更容易把注意力钉在当前对象和任务上；低时更容易散开或被别的线索带走。' },
  ADR: { label: '警觉 / 肾上腺素样', note: '高时更容易注意风险、边界和不确定性；低时代表警报感不在前景。' },
  SER: { label: '安定 / 5-羟色胺样', note: '高时更平稳、更愿意维持秩序和连贯；低时说明稳定感偏弱，更容易躁动或摇摆。' },
  NOV: { label: '新异 / 探索驱动样', note: '高时更容易被新线索、变化和探索欲吸引；低时更偏向守住已有脉络。' },
  END: { label: '耐力 / 内啡肽样', note: '高时更容易持续推进、不轻易中断；低时表示续航感不足，更想停一下。' },
  DA: { label: '驱动 / 多巴胺样', note: '高时更容易形成行动倾向和主观推动；低时更可能只是感到、但还没真想动。' },
  OXY: { label: '亲密 / 依附驱动样', note: '高时更容易产生陪伴感、信任感和贴近感；低时会更保持距离感。' },
};

const cfsMeta: Record<string, { label: string; note: string }> = {
  dissonance: { label: '失调感', note: '高时表示内部线索互相打架，更容易卡住或不舒服。' },
  grasp: { label: '把握感', note: '高时表示对局面更有理解和抓手。' },
  agency_readiness: { label: '行动准备', note: '高时表示更接近“要做点什么”的状态。' },
  surprise: { label: '惊异感', note: '高时表示遇到了预期外线索。' },
  complexity: { label: '复杂度', note: '高时表示当前局面牵涉对象更多、更难一口吃下。' },
  expectation: { label: '预期感', note: '高时表示系统对后续走向已有较明确推测。' },
  expectation_verified: { label: '已确认预期', note: '高时表示某个期待被现实线索支持，系统会更安心地沿着它推进。' },
  pressure: { label: '压迫感', note: '高时表示认知压更高，更可能推动或挤压决策。' },
  familiarity: { label: '熟悉感', note: '高时表示这类局面在记忆里更常见、更容易接上。' },
  repetition: { label: '重复感', note: '高时表示同类线索在反复出现，更容易有绕圈和疲劳感。' },
  pressure_verified: { label: '已确认压力', note: '高时表示压力来源更明确，像是已经坐实、需要处理的负担。' },
  pressure_unverified: { label: '未落定压力', note: '高时表示有压力影子，但来源和性质还没有完全定下来。' },
  simplicity: { label: '简化感', note: '高时表示局面正在收束，线索变少，更容易抓主轴。' },
  correct_event: { label: '对上了的感觉', note: '高时表示前面的违和开始下降，系统感到某条线索被理顺了。' },
  relief: { label: '松弛感', note: '高时表示紧绷开始回落，系统更容易从压力里松一口气。' },
  expectation_unverified: { label: '未确认预期', note: '高时表示已经形成某种猜测，但还缺少足够现实证据。' },
  confidence: { label: '确定感', note: '高时表示系统对当前判断更有信心；低时表示仍在试探。' },
  novelty: { label: '新鲜感', note: '高时表示当前线索带来更多新异和探索感。' },
};

function describeNt(item: AnyRecord): { label: string; note: string } {
  const code = String(item.channel || item.name || '').toUpperCase();
  return ntMeta[code] || {
    label: String(item.label || item.channel || item.name || '-'),
    note: String(item.note || item.description || '高值表示该通道更占前景，低值表示暂时退到背景。'),
  };
}

function describeCfs(item: AnyRecord): { label: string; note: string } {
  const rawKey = String(item.name || item.target || '').toLowerCase();
  const key = rawKey.replace(/^cfs[_:-]/, '');
  return cfsMeta[key] || {
    label: String(item.label || item.name || item.target || '-'),
    note: String(item.note || item.description || '高值表示这一类认知感受更明显，低值表示仍在背景里。'),
  };
}

function readMetricValue(source: AnyRecord, key: string): number {
  if (!source || typeof source !== 'object') return 0;
  const direct = asNumber(source[key], NaN);
  if (Number.isFinite(direct)) return direct;
  const nested = asNumber(source.metrics?.[key] ?? source.raw?.[key] ?? source.values?.[key], NaN);
  return Number.isFinite(nested) ? nested : 0;
}

function firstMetricValue(...values: number[]): number {
  const found = values.find((value) => Number.isFinite(value) && Math.abs(value) > 1e-12);
  if (found !== undefined) return found;
  const finite = values.find((value) => Number.isFinite(value));
  return finite ?? 0;
}

function normalizeCfsKey(value: unknown): string {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/^cfs[_:-]/, '')
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function agentSnapshotsToMetricRows(snapshots: AnyRecord[]): MetricRow[] {
  return snapshots.map((snapshot, index) => {
    const summary = (snapshot.summary || {}) as AnyRecord;
    const pool = (summary.pool || snapshot.pool || snapshot.state_energy_summary?.pool || {}) as AnyRecord;
    const emotion = (snapshot.emotion || {}) as AnyRecord;
    const action = (snapshot.action || {}) as AnyRecord;
    const timing = (snapshot.timing || {}) as AnyRecord;
    const timingSteps = (timing.steps_ms || snapshot.timing_steps_ms || {}) as AnyRecord;
    const attention = (snapshot.attention || {}) as AnyRecord;
    const attentionResource = (attention.attention_energy_resource || {}) as AnyRecord;
    const maintenance = (snapshot.maintenance || {}) as AnyRecord;
    const maintenanceTiming = (maintenance.timing || {}) as AnyRecord;
    const metrics = (snapshot.metrics || {}) as AnyRecord;
    const dominant = asArray<AnyRecord>(snapshot.dominant_objects);
    const cloud = asArray<AnyRecord>(snapshot.object_cloud);
    const highCp = [...dominant, ...cloud].filter((item) => asNumber(item.cp, 0) >= 1 || asNumber(item.cp_intensity, 0) >= 0.55).length;
    const row: MetricRow = { ...metrics };
    Object.assign(row, {
      tick_index: snapshot.tick_counter ?? index,
      tick: snapshot.tick_counter ?? index,
      pool_total_er: asNumber(summary.total_er, asNumber(metrics.pool_total_er, 0)),
      pool_total_ev: asNumber(summary.total_ev, asNumber(metrics.pool_total_ev, 0)),
      pool_total_cp: asNumber(summary.total_cp, asNumber(metrics.pool_total_cp, 0)),
      pool_ev_to_er_ratio: asNumber(summary.ev_to_er_ratio, asNumber(metrics.pool_ev_to_er_ratio, 0)),
      pool_active_item_count: asNumber(summary.active_item_count, asNumber(metrics.pool_active_item_count, dominant.length || cloud.length)),
      pool_high_cp_item_count: asNumber(metrics.pool_high_cp_item_count, highCp),
      complexity_score: firstMetricValue(readMetricValue(metrics, 'complexity_score'), readMetricValue(pool, 'complexity_score')),
      core_complexity_score: firstMetricValue(readMetricValue(metrics, 'core_complexity_score'), readMetricValue(pool, 'core_complexity_score')),
      energy_concentration: firstMetricValue(readMetricValue(metrics, 'energy_concentration'), readMetricValue(pool, 'energy_concentration')),
      core_energy_concentration: firstMetricValue(readMetricValue(metrics, 'core_energy_concentration'), readMetricValue(pool, 'core_energy_concentration')),
      effective_peak_count: firstMetricValue(readMetricValue(metrics, 'effective_peak_count'), readMetricValue(pool, 'effective_peak_count')),
      core_effective_peak_count: firstMetricValue(readMetricValue(metrics, 'core_effective_peak_count'), readMetricValue(pool, 'core_effective_peak_count')),
      attention_memory_item_count: firstMetricValue(readMetricValue(metrics, 'attention_memory_item_count'), readMetricValue(attention, 'memory_item_count'), asNumber(snapshot.memory?.activation_count, 0)),
      attention_cam_item_count: firstMetricValue(readMetricValue(metrics, 'attention_cam_item_count'), readMetricValue(attention, 'cam_item_count'), dominant.length),
      attention_state_pool_candidate_count: firstMetricValue(readMetricValue(metrics, 'attention_state_pool_candidate_count'), readMetricValue(attention, 'state_pool_candidate_count')),
      attention_cam_item_cap: firstMetricValue(readMetricValue(metrics, 'attention_cam_item_cap'), readMetricValue(attention, 'cam_item_cap')),
      attention_skipped_memory_item_count: firstMetricValue(readMetricValue(metrics, 'attention_skipped_memory_item_count'), readMetricValue(attention, 'skipped_memory_item_count')),
      attention_consumed_total_energy: firstMetricValue(readMetricValue(metrics, 'attention_consumed_total_energy'), readMetricValue(attention, 'consumed_total_energy')),
      attention_base_memory_total_energy: firstMetricValue(readMetricValue(metrics, 'attention_base_memory_total_energy'), readMetricValue(attention, 'base_memory_total_energy'), readMetricValue(attentionResource, 'base_cam_total_energy')),
      attention_final_memory_total_energy: firstMetricValue(readMetricValue(metrics, 'attention_final_memory_total_energy'), readMetricValue(attention, 'final_memory_total_energy'), readMetricValue(attentionResource, 'filtered_total_energy')),
      attention_energy_budget: firstMetricValue(readMetricValue(metrics, 'attention_energy_budget'), readMetricValue(attention, 'attention_energy_budget'), readMetricValue(attentionResource, 'budget')),
      attention_net_delta_energy: firstMetricValue(readMetricValue(metrics, 'attention_net_delta_energy'), readMetricValue(attention, 'attention_net_delta_energy'), readMetricValue(attentionResource, 'net_delta_energy')),
      attention_gain_budget_applied: firstMetricValue(readMetricValue(metrics, 'attention_gain_budget_applied'), readMetricValue(attention, 'attention_gain_budget_applied'), readMetricValue(attentionResource, 'gain_budget_applied')),
      attention_gross_gain_energy_applied: firstMetricValue(readMetricValue(metrics, 'attention_gross_gain_energy_applied'), readMetricValue(attention, 'attention_gross_gain_energy_applied'), readMetricValue(attentionResource, 'gross_gain_energy_applied')),
      attention_suppressed_total_energy: firstMetricValue(readMetricValue(metrics, 'attention_suppressed_total_energy'), readMetricValue(attention, 'attention_suppressed_total_energy'), readMetricValue(attentionResource, 'suppressed_total_energy')),
      maintenance_event_count: firstMetricValue(readMetricValue(metrics, 'maintenance_event_count'), readMetricValue(maintenance, 'event_count')),
      maintenance_before_active_item_count: firstMetricValue(readMetricValue(metrics, 'maintenance_before_active_item_count'), readMetricValue(maintenance, 'before_active_item_count'), readMetricValue(maintenance.before || {}, 'active_item_count')),
      maintenance_after_active_item_count: firstMetricValue(readMetricValue(metrics, 'maintenance_after_active_item_count'), readMetricValue(maintenance, 'after_active_item_count'), readMetricValue(maintenance.after || {}, 'active_item_count')),
      maintenance_delta_active_item_count: firstMetricValue(readMetricValue(metrics, 'maintenance_delta_active_item_count'), readMetricValue(maintenance, 'delta_active_item_count')),
      maintenance_before_high_cp_item_count: firstMetricValue(readMetricValue(metrics, 'maintenance_before_high_cp_item_count'), readMetricValue(maintenance, 'before_high_cp_item_count'), readMetricValue(maintenance.before || {}, 'high_cp_item_count')),
      maintenance_after_high_cp_item_count: firstMetricValue(readMetricValue(metrics, 'maintenance_after_high_cp_item_count'), readMetricValue(maintenance, 'after_high_cp_item_count'), readMetricValue(maintenance.after || {}, 'high_cp_item_count')),
      maintenance_delta_high_cp_item_count: firstMetricValue(readMetricValue(metrics, 'maintenance_delta_high_cp_item_count'), readMetricValue(maintenance, 'delta_high_cp_item_count')),
      timing_total_logic_ms: asNumber(metrics.timing_total_logic_ms, asNumber(timing.total_logic_ms ?? timing.total_ms, 0)),
      action_executed_count: asNumber(metrics.action_executed_count, asNumber(action.executed_count, asArray<AnyRecord>(action.executed).length)),
      action_attempted_count: asNumber(metrics.action_attempted_count, asNumber(action.attempted_count, 0)),
      action_node_count: asNumber(metrics.action_node_count, asNumber(action.node_count, asArray<AnyRecord>(action.top_actions).length)),
      action_drive_active_count: asNumber(metrics.action_drive_active_count, asArray<AnyRecord>(action.top_actions).filter((item) => asNumber(item.drive ?? item.value ?? item.level, 0) > 0).length),
      action_drive_max: asNumber(metrics.action_drive_max, Math.max(0, ...asArray<AnyRecord>(action.top_actions).map((item) => asNumber(item.drive ?? item.value ?? item.level, 0)))),
    });
    row.action_drive_mean = row.action_drive_active_count
      ? asNumber(metrics.action_drive_mean, asArray<AnyRecord>(action.top_actions).reduce((sum, item) => sum + asNumber(item.drive ?? item.value ?? item.level, 0), 0) / Math.max(1, asArray<AnyRecord>(action.top_actions).length))
      : 0;
    asArray<AnyRecord>(emotion.channels).forEach((item) => {
      const channel = String(item.channel || item.name || '').toUpperCase();
      const key = ntMetricAliases[channel];
      if (key) row[key] = asNumber(item.value ?? item.level ?? item.current, 0);
    });
    asArray<AnyRecord>(snapshot.cognitive_feelings).forEach((item) => {
      const key = normalizeCfsKey(item.name || item.label || item.target);
      if (!key) return;
      const value = asNumber(item.level ?? item.value ?? item.intensity, 0);
      const aliases = cfsMetricAliases[key] || [key];
      aliases.forEach((alias) => {
        row[`cfs_${alias}_max`] = Math.max(asNumber(row[`cfs_${alias}_max`], 0), value);
        row[`cfs_${alias}_live_total_energy`] = asNumber(row[`cfs_${alias}_live_total_energy`], 0) + value;
        row[`cfs_${alias}_count`] = asNumber(row[`cfs_${alias}_count`], 0) + (value > 0 ? 1 : 0);
        row[`cfs_${alias}_live_active`] = value > 0 ? 1 : asNumber(row[`cfs_${alias}_live_active`], 0);
      });
      row.cfs_signal_count = asNumber(row.cfs_signal_count, 0) + (value > 0 ? 1 : 0);
    });
    Object.entries(timing).forEach(([key, value]) => {
      if ((typeof value === 'number' || typeof value === 'string') && key !== 'steps_ms') {
        row[key.startsWith('timing_') ? key : `timing_${key}`] = asNumber(value, 0);
      }
    });
    Object.entries(timingSteps).forEach(([key, value]) => {
      if (typeof value === 'number' || typeof value === 'string') {
        row[key.startsWith('timing_') ? key : `timing_${key}`] = asNumber(value, 0);
      }
    });
    Object.entries(maintenanceTiming).forEach(([key, value]) => {
      if (typeof value === 'number' || typeof value === 'string') {
        row[key.startsWith('timing_maintenance_') ? key : `timing_maintenance_${key}`] = asNumber(value, 0);
      }
    });
    asArray<AnyRecord>(action.executed).forEach((item) => {
      const kind = String(item.action_kind || item.kind || item.name || '').toLowerCase();
      if (kind.includes('weather')) row.action_executed_weather_stub = 1;
      if (kind.includes('recall')) row.action_executed_recall = 1;
      if (kind.includes('attention_focus')) row.action_executed_attention_focus = 1;
      if (kind.includes('focus_mode')) row.action_executed_focus_mode = 1;
      if (kind.includes('diverge')) row.action_executed_diverge_mode = 1;
    });
    [
      'rwd_pun_rwd',
      'rwd_pun_pun',
      'teacher_rwd',
      'teacher_pun',
      'teacher_applied_count',
      'attention_energy_budget',
      'attention_net_delta_energy',
      'attention_gain_budget_applied',
      'attention_suppressed_total_energy',
      'attention_base_memory_total_energy',
      'attention_final_memory_total_energy',
      'complexity_score',
      'core_complexity_score',
      'energy_concentration',
      'core_energy_concentration',
      'effective_peak_count',
      'core_effective_peak_count',
      'timing_sensor_ms',
      'timing_maintenance_ms',
      'timing_cache_neutralization_ms',
      'timing_cognitive_stitching_ms',
      'timing_attention_ms',
      'timing_structure_level_ms',
      'timing_stimulus_level_ms',
      'timing_pool_apply_ms',
      'timing_induction_and_memory_ms',
      'timing_induction_source_snapshot_ms',
      'timing_induction_hdb_propagation_ms',
      'timing_induction_projection_prepare_ms',
      'timing_induction_source_consumption_ms',
      'timing_induction_target_apply_ms',
      'timing_memory_seed_collect_ms',
      'timing_memory_activation_apply_ms',
      'timing_memory_runtime_projection_ms',
      'timing_memory_activation_snapshot_ms',
      'timing_memory_feedback_apply_ms',
      'timing_maintenance_before_summary_ms',
      'timing_maintenance_pool_maintenance_ms',
      'timing_maintenance_after_summary_ms',
      'timing_maintenance_history_events_ms',
      'timing_time_sensor_ms',
      'timing_teacher_feedback_ms',
      'timing_cfs_ms',
      'timing_iesm_ms',
      'timing_emotion_ms',
      'timing_action_ms',
      'timing_final_snapshot_ms',
    ].forEach((key) => {
      const value = firstMetricValue(
        readMetricValue(metrics, key),
        readMetricValue(snapshot, key),
        readMetricValue(summary, key),
        readMetricValue(pool, key),
        readMetricValue(action, key),
        readMetricValue(attention, key),
        readMetricValue(attentionResource, key.replace(/^attention_/, '')),
        readMetricValue(maintenance, key.replace(/^maintenance_/, '')),
        readMetricValue(timing, key.replace(/^timing_/, '')),
        readMetricValue(timingSteps, key.replace(/^timing_/, '')),
        readMetricValue(maintenanceTiming, key.replace(/^timing_maintenance_/, '')),
      );
      if (value || row[key] === undefined) row[key] = value;
    });
    return row;
  });
}

function readableSnapshotPreview(snapshot: AnyRecord): AnyRecord {
  const summary = (snapshot.summary || {}) as AnyRecord;
  const inputQueue = (snapshot.input_queue || {}) as AnyRecord;
  const topObjects = asArray<AnyRecord>(snapshot.top_objects).length
    ? asArray<AnyRecord>(snapshot.top_objects)
    : asArray<AnyRecord>(snapshot.dominant_objects);
  return {
    id: snapshot.id,
    kind: snapshot.kind || 'ap_tick',
    tick: snapshot.tick_counter,
    source: snapshot.source || snapshot.labels?.source || '-',
    time: timeLabel(snapshot.created_at_ms || snapshot.generated_at_ms),
    input: inputQueue.tick_text || inputQueue.source_text || inputQueue.submitted_text || '本 tick 未消耗外源文本',
    energy: {
      er: formatNumber(summary.total_er, 3),
      ev: formatNumber(summary.total_ev, 3),
      cp: formatNumber(summary.total_cp, 3),
      active_objects: formatCount(summary.active_item_count),
    },
    mood: summary.mood_hint || '-',
    top_objects: topObjects.slice(0, 20).map((item) => ({
      rank: item.rank,
      text: shortDisplayText(item.full_display || item.display || item.id || '-', 160),
      energy: formatNumber(item.total_energy ?? item.energy, 3),
      er: formatNumber(item.er, 3),
      ev: formatNumber(item.ev, 3),
      cp: formatNumber(item.cp, 3),
    })),
    cognitive_feelings: asArray<AnyRecord>(snapshot.cognitive_feelings).slice(0, 8).map((item) => ({
      name: describeCfs(item).label,
      value: formatNumber(item.level ?? item.value, 3),
    })),
    nt: asArray<AnyRecord>(snapshot.emotion?.channels).slice(0, 8).map((item) => ({
      name: describeNt(item).label,
      value: formatNumber(item.value ?? item.level, 3),
    })),
  };
}

function TickInspectorCard({
  snapshots,
  selected,
  onSelect,
}: {
  snapshots: AnyRecord[];
  selected: AnyRecord | null;
  onSelect: (value: AnyRecord) => void;
}) {
  const selectedSnapshot = selected || snapshots[snapshots.length - 1] || null;
  const summary = (selectedSnapshot?.summary || {}) as AnyRecord;
  const inputQueue = (selectedSnapshot?.input_queue || {}) as AnyRecord;
  const topObjects = asArray<AnyRecord>(selectedSnapshot?.top_objects).length
    ? asArray<AnyRecord>(selectedSnapshot?.top_objects)
    : asArray<AnyRecord>(selectedSnapshot?.dominant_objects);
  const feelings = asArray<AnyRecord>(selectedSnapshot?.cognitive_feelings);
  const nt = asArray<AnyRecord>(selectedSnapshot?.emotion?.channels);
  const actions = asArray<AnyRecord>(selectedSnapshot?.action?.top_actions);
  const timing = (selectedSnapshot?.timing || {}) as AnyRecord;
  const sourceLabel = String(selectedSnapshot?.source || selectedSnapshot?.labels?.source || '-');
  return (
    <Card className="pa-panel pa-tick-inspector-card">
      <Group justify="space-between" align="flex-start" mb="xs">
        <div>
          <Text fw={900}>Tick 内容检视</Text>
          <Text size="xs" c="dimmed">选择任意 tick 查看当拍输入、能量、top 对象、感受和行动，不显示原始 JSON。</Text>
        </div>
        <Badge variant="light">{formatCount(snapshots.length)} ticks</Badge>
      </Group>
      <div className="pa-tick-inspector-grid">
        <ScrollArea.Autosize mah={560} className="pa-tick-list-scroll">
          <Stack gap={6}>
            {snapshots.length ? snapshots.slice().reverse().map((item, index) => {
              const rowSummary = (item.summary || {}) as AnyRecord;
              const active = String(item.id || item.tick_id || item.report_identity) === String(selectedSnapshot?.id || selectedSnapshot?.tick_id || selectedSnapshot?.report_identity);
              const rowInput = item.input_queue?.tick_text || item.input_queue?.source_text || item.input_queue?.submitted_text;
              return (
                <button
                  key={`${item.id || item.tick_id || index}`}
                  type="button"
                  className={`pa-tick-row ${active ? 'active' : ''}`}
                  onClick={() => onSelect(item)}
                >
                  <span>
                    <strong>tick {formatCount(item.tick_counter ?? snapshots.length - index)}</strong>
                    <small>{timeLabel(item.created_at_ms || item.generated_at_ms)} · {String(item.source || item.labels?.source || '-')}</small>
                    <small>{rowInput ? shortText(String(rowInput), 72) : shortText(String(rowSummary.mood_hint || '空 tick 演化'), 72)}</small>
                  </span>
                  <i>CP {formatNumber(rowSummary.total_cp, 1)}</i>
                </button>
              );
            }) : <div className="empty-box compact">等待 tick 快照。</div>}
          </Stack>
        </ScrollArea.Autosize>
        <div className="pa-tick-detail-pane">
          {selectedSnapshot ? (
            <Stack gap="sm">
              <Group justify="space-between" align="flex-start" gap="xs">
                <div>
                  <Text fw={900}>tick {formatCount(selectedSnapshot.tick_counter)}</Text>
                  <Text size="xs" c="dimmed">{timeLabel(selectedSnapshot.created_at_ms || selectedSnapshot.generated_at_ms)} · {sourceLabel}</Text>
                </div>
                <Badge variant="light">{String(selectedSnapshot.kind || 'ap_tick')}</Badge>
              </Group>
              <div className="pa-tick-kpi-grid">
                <button type="button" onClick={() => onSelect(readableSnapshotPreview(selectedSnapshot))}><span>ER</span><strong>{formatNumber(summary.total_er, 2)}</strong><small>实能量</small></button>
                <button type="button" onClick={() => onSelect(readableSnapshotPreview(selectedSnapshot))}><span>EV</span><strong>{formatNumber(summary.total_ev, 2)}</strong><small>虚能量</small></button>
                <button type="button" onClick={() => onSelect(readableSnapshotPreview(selectedSnapshot))}><span>CP</span><strong>{formatNumber(summary.total_cp, 2)}</strong><small>认知压</small></button>
                <button type="button" onClick={() => onSelect(readableSnapshotPreview(selectedSnapshot))}><span>对象</span><strong>{formatCount(summary.active_item_count)}</strong><small>活跃数量</small></button>
              </div>
              <div className="pa-tick-input-box">
                <Text size="xs" fw={800}>本 tick 输入</Text>
                <p>{String(inputQueue.tick_text || inputQueue.source_text || inputQueue.submitted_text || '没有消耗外源文本，是一次空 tick / 内源演化。')}</p>
              </div>
              <div>
                <Group justify="space-between" mb={6}>
                  <Text size="sm" fw={900}>状态池 Top 内容</Text>
                  <Badge size="xs" variant="outline">top {formatCount(Math.min(20, topObjects.length))}</Badge>
                </Group>
                <div className="pa-tick-object-grid">
                  {topObjects.slice(0, 20).map((item, index) => (
                    <button key={`${item.id || index}-${item.rank || index}`} type="button" onClick={() => onSelect(item)}>
                      <span>{formatCount(item.rank || index + 1)}</span>
                      <strong>{shortDisplayText(item.full_display || item.display || item.id || '-', 110)}</strong>
                      <small>ER {formatNumber(item.er, 2)} / EV {formatNumber(item.ev, 2)} / CP {formatNumber(item.cp, 2)}</small>
                    </button>
                  ))}
                  {!topObjects.length ? <div className="empty-box compact">当前 tick 没有可展示 top 对象。</div> : null}
                </div>
              </div>
              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                <div className="pa-tick-chip-panel">
                  <Text size="xs" fw={900}>认知感受</Text>
                  <Group gap={6} mt={6}>
                    {feelings.slice(0, 10).map((item, index) => (
                      <Badge key={`${item.name || index}`} variant="light">{describeCfs(item).label} {formatNumber(item.level ?? item.value, 2)}</Badge>
                    ))}
                    {!feelings.length ? <Badge variant="outline">无显著 CFS</Badge> : null}
                  </Group>
                </div>
                <div className="pa-tick-chip-panel">
                  <Text size="xs" fw={900}>情绪 NT</Text>
                  <Group gap={6} mt={6}>
                    {nt.slice(0, 8).map((item, index) => (
                      <Badge key={`${item.channel || index}`} variant="outline">{describeNt(item).label} {formatNumber(item.value ?? item.level, 2)}</Badge>
                    ))}
                    {!nt.length ? <Badge variant="outline">无 NT 数据</Badge> : null}
                  </Group>
                </div>
              </SimpleGrid>
              <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                <div className="pa-tick-chip-panel">
                  <Text size="xs" fw={900}>行动驱动力</Text>
                  <Stack gap={4} mt={6}>
                    {actions.slice(0, 6).map((item, index) => {
                      const actionKind = String(item.kind || item.action_kind || '-');
                      const actionTarget = String(item.target_display || item.target || item.target_ref_object_id || item.target_item_id || item.action_id || item.id || '');
                      return (
                      <button key={`${item.action_id || item.id || item.kind || index}`} type="button" className="pa-mini-row pa-action-drive-row" onClick={() => onSelect(item)}>
                        <span>
                          <strong>{shortText(actionKind, 38)}</strong>
                          {actionTarget ? <small>{shortText(actionTarget, 74)}</small> : null}
                        </span>
                        <strong>{formatNumber(item.drive ?? item.value ?? item.level, 3)}</strong>
                      </button>
                      );
                    })}
                    {!actions.length ? <Text size="xs" c="dimmed">无行动节点数据。</Text> : null}
                  </Stack>
                </div>
                <div className="pa-tick-chip-panel">
                  <Text size="xs" fw={900}>耗时</Text>
                  <Stack gap={4} mt={6}>
                    {Object.entries(timing).filter(([, value]) => Number.isFinite(Number(value))).slice(0, 8).map(([key, value]) => (
                      <button key={key} type="button" className="pa-mini-row" onClick={() => onSelect({ key, value })}>
                        <span>{key.replace(/_ms$/, '')}</span>
                        <strong>{formatNumber(value, 1)} ms</strong>
                      </button>
                    ))}
                    {!Object.keys(timing).length ? <Text size="xs" c="dimmed">无耗时明细。</Text> : null}
                  </Stack>
                </div>
              </SimpleGrid>
            </Stack>
          ) : (
            <div className="empty-box">等待 AP tick 记录。</div>
          )}
        </div>
      </div>
    </Card>
  );
}

function objectColor(item: AnyRecord): string {
  const evRatio = Math.max(0, Math.min(1, asNumber(item.ev_ratio, 0.5)));
  const cp = Math.max(0, Math.min(1, asNumber(item.cp_intensity, asNumber(item.cp, 0) / 5)));
  const redAnchor = { r: 255, g: 102, b: 102 };
  const purpleAnchor = { r: 170, g: 98, b: 250 };
  const blueAnchor = { r: 76, g: 170, b: 255 };
  const anchors =
    evRatio <= 0.5
      ? [
          redAnchor,
          purpleAnchor,
          evRatio / 0.5,
        ]
      : [
          purpleAnchor,
          blueAnchor,
          (evRatio - 0.5) / 0.5,
        ];
  const [from, to, t] = anchors as [{ r: number; g: number; b: number }, { r: number; g: number; b: number }, number];
  const blend = (start: number, end: number) => Math.round(start + (end - start) * t);
  const brightness = 0.86 + cp * 0.34;
  const channel = (value: number) => Math.max(0, Math.min(255, Math.round(value * brightness)));
  return `rgba(${channel(blend(from.r, to.r))}, ${channel(blend(from.g, to.g))}, ${channel(blend(from.b, to.b))}, ${0.24 + cp * 0.22})`;
}

function naturalizeCloudText(value: unknown): string {
  let text = String(value || '').replace(/\r/g, '\n');
  if (!text.trim()) return '';
  text = text.replace(/\|\|/g, ' / ');
  text = text.replace(/\s*\+\s*/g, '');
  text = text.replace(/[{}\[\]]/g, ' ');
  text = text.replace(/\b(?:teacher_[0-9A-Za-z_:-]+|bridge_feedback|bridge_result|ap_action_bridge|llm_think_wake)\b/gi, ' ');
  text = text.replace(/\b(?:st|em|sa|spi)_[0-9A-Za-z_:-]+\b/g, ' ');
  text = text.replace(/\b(?:cfs_[0-9A-Za-z_:-]+|punish_signal|reward_signal|time_feeling|timestamp_ms|local_time)\s*[:=：]?\s*[^,，。；;\n]+/gi, ' ');
  text = text.replace(/\b(?:error|provider_error|body_preview|source_urls|url|latency_ms|ok|success|failure|reason)\s*[:=：]\s*[^,，。；;\n]+/gi, ' ');
  text = text.replace(/(?:HTTP\s*Error\s*50\d|HTTPError\s*50\d|Bad\s*Gateway|BadGateway|provider_error|transport_error|url_error|URLError|TimeoutError|forecast_unavailable|geocode_failed)/gi, ' ');
  text = text.replace(/(?:整体内在态势|主要感受|高能对象|高能量对象|高能记忆|高认知压对象|对象云|状态包|运行阶段|分析过程|工具调用|行动决策|调试说明|认知感受摘要|情绪通道摘要)\s*[:：][^。！？\n]*/gi, ' ');
  text = text.replace(/\b(?:ER|EV|CP|NT|CFS)\b\s*[:：][^。！？\n]*/gi, ' ');
  text = text.replace(/\b(?:decision|reply_text|reply|tool_calls|tool|why|confidence|action|source|ok)\b\s*[:=：]?\s*[^,，。；;\n]+/gi, ' ');
  text = text.replace(/\s*\/\s*/g, '，');
  text = text.replace(/，{2,}/g, '，');
  text = text.replace(/\s+/g, ' ');
  text = text.replace(/([，。！？；：,.!?;:])\1+/g, '$1');
  return text.trim().replace(/^[ /，。；;:,-]+|[ /，。；;:,-]+$/g, '');
}

function cloudDisplayKey(item: AnyRecord): string {
  return naturalizeCloudText(item.display || item.text || item.name || item.id || '');
}

function aggregateCloudItems(items: AnyRecord[]): AnyRecord[] {
  const groups = new Map<string, AnyRecord>();
  items.forEach((item, index) => {
    const display = cloudDisplayKey(item);
    if (!display) return;
    const key = display.toLowerCase();
    const current = groups.get(key);
    const totalEnergy = asNumber(item.total_energy, asNumber(item.energy, 0));
    const er = asNumber(item.er, 0);
    const ev = asNumber(item.ev, 0);
    const cp = asNumber(item.cp, 0);
    if (!current) {
      groups.set(key, {
        ...item,
        id: String(item.id || `cloud_${index}`),
        display,
        full_display: display,
        total_energy: totalEnergy,
        er,
        ev,
        cp,
        source_ids: [String(item.id || `cloud_${index}`)],
        group_count: 1,
      });
      return;
    }
    const nextEr = asNumber(current.er, 0) + er;
    const nextEv = asNumber(current.ev, 0) + ev;
    const nextCp = asNumber(current.cp, 0) + cp;
    const nextEnergy = asNumber(current.total_energy, 0) + totalEnergy;
    groups.set(key, {
      ...current,
      total_energy: nextEnergy,
      er: nextEr,
      ev: nextEv,
      cp: nextCp,
      ev_ratio: (nextEr + nextEv) > 0 ? nextEv / (nextEr + nextEv) : asNumber(current.ev_ratio, 0.5),
      cp_intensity: Math.max(asNumber(current.cp_intensity, 0), Math.min(1, nextCp / 5)),
      size: Math.max(asNumber(current.size, 0), asNumber(item.size, 0), Math.min(94, 18 + nextEnergy * 0.8)),
      source_ids: [...asArray<string>(current.source_ids), String(item.id || `cloud_${index}`)],
      group_count: asNumber(current.group_count, 1) + 1,
    });
  });
  return Array.from(groups.values()).sort((a, b) => asNumber(b.total_energy, 0) - asNumber(a.total_energy, 0));
}

function cloudBubbleLayout(items: AnyRecord[], width = 780, height = 430, mode: 'compact' | 'expanded' = 'compact'): AnyRecord[] {
  const centerX = width / 2;
  const centerY = height / 2;
  const minSide = Math.max(280, Math.min(width, height));
  const safePadding = mode === 'compact'
    ? Math.max(18, Math.min(38, minSide * 0.044))
    : Math.max(18, Math.min(34, minSide * 0.032));
  const placed: AnyRecord[] = [];
  const sorted = items.slice().sort((a, b) => asNumber(b.total_energy, 0) - asNumber(a.total_energy, 0));
  sorted.forEach((item, index) => {
    const energy = Math.max(0, asNumber(item.total_energy, asNumber(item.energy, 0)));
    const rawSize = asNumber(item.size, 20);
    const textLength = String(item.display || item.id || '').length;
    const maxDiameter = mode === 'compact'
      ? Math.max(116, Math.min(minSide * 0.31, width * 0.235))
      : Math.max(118, Math.min(minSide * 0.3, width * 0.22));
    const baseDiameter = mode === 'compact'
      ? 60 + rawSize * 2.28 + Math.min(28, textLength * 0.34)
      : 56 + rawSize * 2.16 + Math.min(28, textLength * 0.64);
    const diameter = Math.max(mode === 'compact' ? 94 : 92, Math.min(maxDiameter, baseDiameter));
    const radius = diameter / 2;
    let bestX = centerX;
    let bestY = centerY;
    let found = false;
    let bestPenalty = Number.POSITIVE_INFINITY;
    const angleSeed = index * 2.399963229728653;
    for (let ring = 0; ring < 86 && !found; ring += 1) {
      const baseOrbit = index === 0 ? 0 : Math.min(Math.max(0, radius * 0.18), minSide / 2 - radius - safePadding - 10);
      const orbit = baseOrbit + ring * Math.max(mode === 'compact' ? 18 : 16, Math.min(mode === 'compact' ? 32 : 24, minSide * (mode === 'compact' ? 0.054 : 0.044)));
      const samples = Math.max(24, 30 + ring * 5);
      for (let step = 0; step < samples; step += 1) {
        const angle = angleSeed + (Math.PI * 2 * step) / samples;
        const candidateX = centerX + Math.cos(angle) * orbit;
        const candidateY = centerY + Math.sin(angle) * orbit * 0.72;
        if (
          candidateX - radius < safePadding ||
          candidateX + radius > width - safePadding ||
          candidateY - radius < safePadding ||
          candidateY + radius > height - safePadding
        ) {
          continue;
        }
        let penalty = orbit * 0.24;
        let collision = false;
        placed.forEach((other) => {
          const dx = candidateX - asNumber(other.layout_x, centerX);
          const dy = candidateY - asNumber(other.layout_y, centerY);
          const minDistance = radius + asNumber(other.layout_radius, 0) + Math.max(mode === 'compact' ? 22 : 18, Math.min(mode === 'compact' ? 42 : 30, minSide * (mode === 'compact' ? 0.05 : 0.036)));
          const distance = Math.sqrt(dx * dx + dy * dy);
          if (distance < minDistance) {
            collision = true;
            penalty += (minDistance - distance) * 40;
          }
        });
        if (!collision) {
          bestX = candidateX;
          bestY = candidateY;
          found = true;
          break;
        }
        if (penalty < bestPenalty) {
          bestPenalty = penalty;
          bestX = candidateX;
          bestY = candidateY;
        }
      }
    }
    const clampedX = Math.max(safePadding + radius, Math.min(width - safePadding - radius, bestX));
    const clampedY = Math.max(safePadding + radius, Math.min(height - safePadding - radius, bestY));
    const compact = {
      ...item,
      total_energy: energy,
      layout_size: diameter,
      layout_radius: radius,
      layout_x: clampedX,
      layout_y: clampedY,
      layout_delay: ((index * 0.23) % 2.4).toFixed(2),
      layout_z: 200 - index,
    };
    placed.push(compact);
  });
  return placed;
}

function clampCloudItemsForViewport(items: AnyRecord[], width: number, height: number, mode: 'compact' | 'expanded' = 'compact'): AnyRecord[] {
  const area = Math.max(1, width * height);
  const smallSide = Math.max(1, Math.min(width, height));
  const approxCapacity = mode === 'compact'
    ? Math.max(10, Math.min(10, Math.floor(area / 52000), Math.floor(smallSide / 44)))
    : Math.max(10, Math.min(30, Math.floor(area / 50000)));
  return items
    .slice()
    .sort((a, b) => asNumber(b.total_energy, 0) - asNumber(a.total_energy, 0))
    .slice(0, approxCapacity);
}

function cloudTextWeight(text: string): number {
  return Array.from(text || '').reduce((total, ch) => {
    if (/\s/.test(ch)) return total + 0.25;
    if (/[A-Za-z0-9]/.test(ch)) return total + 0.58;
    if (/[，。！？；：、,.!?;:()[\]{}"'“”‘’\-_/\\|]/.test(ch)) return total + 0.35;
    return total + 1;
  }, 0);
}

function cloudTextFit(size: number, text: string, groupCount: number): { fontSize: number; textWidth: number } {
  const safeWidth = size * 0.66;
  const safeHeight = size * (groupCount > 1 ? 0.56 : 0.64);
  const baseFont = Math.max(9.4, Math.min(13.4, size * 0.085));
  const weight = Math.max(1, cloudTextWeight(text));
  const fitFont = Math.sqrt((safeWidth * safeHeight) / (weight * 1.08)) * 0.96;
  return {
    fontSize: Math.max(6.8, Math.min(baseFont, fitFont)),
    textWidth: Math.max(42, safeWidth),
  };
}

function CloudObject({ item, onSelect }: { item: AnyRecord; onSelect: (item: AnyRecord) => void }) {
  const size = Math.max(66, Math.min(240, asNumber(item.layout_size, 112)));
  const x = asNumber(item.layout_x, 0);
  const y = asNumber(item.layout_y, 0);
  const delay = String(item.layout_delay || '0');
  const groupCount = Math.max(1, asNumber(item.group_count, 1));
  const display = naturalizeCloudText(item.full_display || item.display || item.id || '-');
  const textFit = cloudTextFit(size, display, groupCount);
  return (
    <Tooltip
      label={`内容：${display}\n类型：${item.type || 'object'}\n总能量：${formatNumber(item.total_energy, 4)}\n认知压：${formatNumber(item.cp, 4)}${groupCount > 1 ? `\n聚合：${groupCount} 项` : ''}`}
      multiline
      maw={420}
    >
      <button
        type="button"
        className="agent-cloud-chip"
        style={{
          ['--agent-cloud-size' as string]: `${size}px`,
          ['--agent-cloud-color' as string]: objectColor(item),
          ['--agent-cloud-x' as string]: `${x}px`,
          ['--agent-cloud-y' as string]: `${y}px`,
          ['--agent-cloud-delay' as string]: `${delay}s`,
          ['--agent-cloud-z' as string]: `${Math.max(1, asNumber(item.layout_z, 1))}`,
          ['--agent-cloud-font-size' as string]: `${textFit.fontSize}px`,
          ['--agent-cloud-text-width' as string]: `${textFit.textWidth}px`,
        }}
        onClick={() => onSelect(item)}
      >
        <span className="agent-cloud-text">{display}</span>
        {groupCount > 1 ? <small>x{groupCount}</small> : null}
      </button>
    </Tooltip>
  );
}

function ThoughtCard({ item, onSelect }: { item: AnyRecord; onSelect: (item: AnyRecord) => void }) {
  const quality = item.quality || {};
  const qualityScore = asNumber(quality.overall, -1);
  const qualityColor = qualityScore >= 0.72 ? 'teal' : qualityScore >= 0.48 ? 'yellow' : 'red';
  return (
    <Card className="agent-thought-card" onClick={() => onSelect(item)}>
      <Group justify="space-between" gap="xs" mb={6}>
        <Group gap={6}>
          <Badge color={pickTone(item.decision)} variant="light">
            {item.decision || 'thought'}
          </Badge>
          <Text size="xs" c="dimmed">
            #{item.index ?? '-'} {timeLabel(item.created_at_ms)}
          </Text>
        </Group>
        <Text size="xs" c="dimmed">
          {formatPercent(item.confidence, 0)}
        </Text>
      </Group>
      {qualityScore >= 0 ? (
        <div className="agent-quality-strip">
                      <Badge size="xs" variant="light" color={qualityColor}>
            质量分 {formatPercent(qualityScore, 0)}
          </Badge>
          <span style={{ ['--agent-quality-width' as string]: `${Math.max(2, Math.min(100, qualityScore * 100))}%` }} />
        </div>
      ) : null}
      <Text size="sm" className="agent-thought-text">
        {item.text || '-'}
      </Text>
      {quality?.warnings?.length ? (
        <Group gap={6} mt={8}>
          {asArray<string>(quality.warnings).slice(0, 3).map((warning) => (
            <Badge key={warning} size="xs" variant="light" color="orange">
              {warning}
            </Badge>
          ))}
        </Group>
      ) : null}
      {item.why ? (
        <Text size="xs" c="dimmed" mt={8}>
          {shortText(item.why, 120)}
        </Text>
      ) : null}
    </Card>
  );
}

function ThoughtTextCard({ item, onSelect }: { item: AnyRecord; onSelect: (item: AnyRecord) => void }) {
  const decision = String(item.decision || 'thought');
  const toolNames = asArray<AnyRecord>(item.tool_calls).map((row) => String(row.name || row.tool || '')).filter(Boolean);
  return (
    <button type="button" className="agent-thought-clean-card" onClick={() => onSelect(item)}>
      <span>{timeLabel(item.created_at_ms)} · 想法 #{item.index ?? '-'} · {decision}</span>
      <strong>{item.text || '-'}</strong>
      {toolNames.length ? <small>工具：{toolNames.join('，')}</small> : null}
    </button>
  );
}

function MessageBubble({
  item,
  auditRow,
  collapseDebt,
  onInspect,
  imagePreviewMap,
}: {
  item: AnyRecord;
  auditRow?: AnyRecord;
  collapseDebt?: boolean;
  onInspect?: (item: AnyRecord) => void;
  imagePreviewMap?: Record<string, string>;
}) {
  const role = String(item.role || '');
  const mine = role === 'user';
  const sender = (item.adapter_event?.sender || {}) as AnyRecord;
  const senderName = String(sender.card || sender.nickname || sender.name || '').trim();
  const senderId = String(sender.user_id || item.adapter_event?.user_id || item.reply_target?.user_id || '').trim();
  const adapterLabel = String(item.adapter_label || item.adapter_event?.target_label || '').trim();
  const senderLabel = senderName && senderId ? `${senderName} (${senderId})` : senderName || senderId || adapterLabel;
  const targetLabel = String(item.reply_target?.target_label || item.adapter_label || item.conversation_id || '').trim();
  const bubbleLabel = mine
    ? senderLabel ? `${senderLabel} / 用户` : '用户'
    : targetLabel && String(item.source || '') === 'assistant' && String(item.conversation_id || '').startsWith('group:')
      ? `PA -> ${targetLabel}`
      : 'PA';
  const isDebt = !mine && Boolean(auditRow?.is_duplicate || auditRow?.raw_leak);
  const debtBadges = [
    auditRow?.is_duplicate ? `duplicate x${formatCount(auditRow.duplicate_count)}` : '',
    auditRow?.raw_leak ? 'raw leak' : '',
  ].filter(Boolean);
  return (
    <div className={`agent-message-row ${mine ? 'is-user' : 'is-agent'}`}>
      <div className={`agent-message-bubble ${isDebt ? 'is-debt' : ''}`}>
        <Group justify="space-between" gap="xs" mb={4}>
          <Group gap={6}>
            <Text size="xs" fw={800}>
              {bubbleLabel}
            </Text>
            {mine && adapterLabel && adapterLabel !== senderLabel ? (
              <Badge size="xs" variant="light" color="blue">
                {shortText(adapterLabel, 40)}
              </Badge>
            ) : null}
            {mine && String(item.conversation_id || '').startsWith('group:') ? (
              <Badge size="xs" variant="outline">
                群聊
              </Badge>
            ) : null}
            {isDebt ? <Badge size="xs" variant="light" color="yellow">历史债务</Badge> : null}
            {debtBadges.slice(0, 2).map((badge) => (
              <Badge key={badge} size="xs" variant="outline" color={badge.includes('raw') ? 'red' : 'yellow'}>
                {badge}
              </Badge>
            ))}
          </Group>
          <Text size="xs" c="dimmed">
            {timeLabel(item.created_at_ms)}
          </Text>
        </Group>
        {isDebt && collapseDebt ? (
          <button type="button" className="agent-message-debt-collapse" onClick={() => onInspect?.(auditRow || item)}>
            <strong>修复前回复已折叠</strong>
            <small>{shortText(String(auditRow?.text_preview || item.text || ''), 110)}</small>
          </button>
        ) : (
          <Text size="sm">{item.text || '-'}</Text>
        )}
        {asArray<AnyRecord>(item.attachments).length ? (
          <div className="agent-message-attachments">
            {asArray<AnyRecord>(item.attachments).slice(0, 6).map((att, index) => {
              const previewSrc = imagePreviewMap?.[attachmentPreviewKey(att)] || '';
              const directSrc = String(att.data_url || att.preview_url || att.image_url || att.url || '');
              const src = isRenderableImageSrc(previewSrc) ? previewSrc : isRenderableImageSrc(directSrc) ? directSrc : '';
              const isImage = String(att.kind || '').toLowerCase() === 'image' || String(att.mime_type || '').startsWith('image/');
              return (
                <button key={`${att.id || att.name || index}`} type="button" onClick={() => onInspect?.(att)}>
                  {isImage && src ? (
                    <img src={src} alt={String(att.name || 'attachment image')} loading="lazy" />
                  ) : null}
                  <span>
                    <Badge size="xs" variant="light" leftSection={isImage ? <IconPhoto size={12} /> : <IconFile size={12} />}>
                      {att.kind || 'file'}
                    </Badge>
                    <small>{shortText(att.name || att.text_preview || att.summary || '-', 52)}</small>
                  </span>
                </button>
              );
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function liveRecordKey(item: AnyRecord, fallback: string): string {
  const id = String(item.id || '');
  if (id) return `id:${id}`;
  const role = String(item.role || item.decision || '');
  const text = String(item.text || item.reply_text || item.thought || '');
  const ts = String(item.created_at_ms || item.updated_at_ms || '');
  return `${fallback}:${role}:${ts}:${text.slice(0, 96)}`;
}

function mergeLiveRecords(base: AnyRecord[], additions: AnyRecord[], fallback: string): AnyRecord[] {
  const rows: AnyRecord[] = [];
  const seen = new Set<string>();
  [...base, ...additions].forEach((item, index) => {
    if (!item || typeof item !== 'object') return;
    const key = liveRecordKey(item, `${fallback}_${index}`);
    if (seen.has(key)) return;
    seen.add(key);
    rows.push(item);
  });
  return rows;
}

function hasSimilarVisibleMessage(rows: AnyRecord[], item: AnyRecord): boolean {
  const role = String(item.role || '');
  const text = String(item.text || '').trim();
  const ts = asNumber(item.created_at_ms, 0);
  if (!role || !text) return false;
  return rows.some((row) => {
    if (String(row.role || '') !== role) return false;
    if (String(row.text || '').trim() !== text) return false;
    const otherTs = asNumber(row.created_at_ms, 0);
    return !ts || !otherTs || Math.abs(ts - otherTs) <= 10_000;
  });
}

function EventList({ events, onSelect }: { events: AnyRecord[]; onSelect: (item: AnyRecord) => void }) {
  return (
    <Stack gap={8}>
      {events.length ? events.slice().reverse().map((item, index) => (
        <button key={`${item.ts || index}-${item.event || 'event'}`} type="button" className="agent-event-row" onClick={() => onSelect(item)}>
          <span>
            <strong>{item.event || '-'}</strong>
            <small>{timeLabel(item.ts)} {item.reason ? `| ${item.reason}` : ''}</small>
          </span>
          <Badge variant="light" color={item.ok === false ? 'red' : item.should_wake ? 'teal' : 'gray'}>
            {item.ok === false ? 'fail' : item.should_wake ? 'wake' : 'log'}
          </Badge>
        </button>
      )) : <div className="empty-box">暂无事件。</div>}
    </Stack>
  );
}

function OutboxList({ rows, onSelect }: { rows: AnyRecord[]; onSelect: (item: AnyRecord) => void }) {
  return (
    <Stack gap={8}>
      {rows.length ? rows.slice().reverse().map((item, index) => (
        <button key={`${item.ts || index}-${item.reason || item.ok}`} type="button" className="agent-event-row" onClick={() => onSelect(item)}>
          <span>
            <strong>{item.dry_run ? 'dry-run' : item.ok ? 'sent' : item.reason || 'failed'}</strong>
            <small>{timeLabel(item.ts)} | {item.message_type || '-'} {item.group_id || item.user_id || ''}</small>
          </span>
          <Badge variant="light" color={item.ok ? 'teal' : 'red'}>
            {item.ok ? 'ok' : 'hold'}
          </Badge>
        </button>
      )) : <div className="empty-box">暂无 outbound。</div>}
    </Stack>
  );
}

function adapterEventLabel(item: AnyRecord): { label: string; color: string } {
  const event = String(item.event || '');
  const level = String(item.level || '').toLowerCase();
  if (level === 'error' || event.includes('failed')) return { label: '报错', color: 'red' };
  if (event.includes('rate_limited')) return { label: '限速', color: 'yellow' };
  if (event.includes('filtered') || item.access_allowed === false) return { label: '过滤', color: 'gray' };
  if (event.includes('ap_gate_rejected')) return { label: '门控拒绝', color: 'yellow' };
  if (event.includes('ap_gate_replied')) return { label: '门控回复', color: 'teal' };
  if (event.includes('ap_gate')) return { label: 'AP门控', color: 'blue' };
  if (event.includes('group_continuity_passed')) return { label: '连续通过', color: 'teal' };
  if (event.includes('group_continuity_rejected')) return { label: '连续拒绝', color: 'yellow' };
  if (event.includes('group_continuity')) return { label: '连续窗口', color: 'blue' };
  if (event.includes('reply_dry_run')) return { label: 'dry-run', color: 'yellow' };
  if (event.includes('reply') || item.outbound === true) return { label: '发送', color: 'teal' };
  if (event.includes('replied')) return { label: '已回复', color: 'teal' };
  if (event.includes('wake') || item.should_wake === true) return { label: '唤醒', color: 'green' };
  if (event.includes('passed') || item.handled === true) return { label: '通过', color: 'teal' };
  if (event.includes('received')) return { label: '收到', color: 'blue' };
  if (level === 'warn' || level === 'warning') return { label: '警告', color: 'yellow' };
  return { label: '记录', color: 'gray' };
}

function adapterEventTitle(item: AnyRecord): string {
  const event = String(item.event || 'adapter_event');
  const target = String(item.target_label || item.reply_target?.target_label || item.conversation_id || '').trim();
  const type = String(item.message_type || item.reply_target?.message_type || '').trim();
  return `${event}${target ? ` · ${target}` : ''}${type ? ` · ${type}` : ''}`;
}

function adapterEventDetail(item: AnyRecord): string {
  const parts = [
    timeLabel(item.ts),
    item.access_reason ? `名单:${item.access_reason}` : '',
    item.wake_reason ? `触发:${item.wake_reason}` : item.reason ? `原因:${item.reason}` : '',
    item.group_id ? `群:${item.group_id}` : '',
    item.user_id ? `用户:${item.user_id}` : '',
    item.group_continuity_window?.remaining !== undefined ? `连续:${item.group_continuity_window.remaining}/${item.group_continuity_window.limit || '-'}` : '',
    item.group_continuity_gate?.confidence !== undefined ? `门控:${formatPercent(item.group_continuity_gate.confidence, 0)}` : '',
    item.outbound_count !== undefined ? `外发:${item.outbound_count}` : '',
    item.reply_count !== undefined ? `回复:${item.reply_count}` : '',
  ].filter(Boolean);
  return parts.join(' | ');
}

function adapterEventPreview(item: AnyRecord): string {
  const text = String(item.text || '').trim();
  const reply = String(item.reply_text || '').trim();
  const error = String(item.error || '').trim();
  const attachmentCount = asNumber(item.attachment_count, 0);
  const continuityReason = String(item.group_continuity_gate?.reason || '').trim();
  const chunks = [
    text ? `入站：${text}` : '',
    reply ? `出站：${reply}` : '',
    continuityReason ? `连续门控：${continuityReason}` : '',
    error ? `错误：${error}` : '',
    !text && attachmentCount ? `附件 ${formatCount(attachmentCount)} 个` : '',
  ].filter(Boolean);
  return shortText(chunks.join('  '), 180) || '无文本内容';
}

function AdapterEventList({
  rows,
  onSelect,
}: {
  rows: AnyRecord[];
  onSelect: (item: AnyRecord) => void;
}) {
  return (
    <Stack gap={8}>
      {rows.length ? rows.slice().reverse().map((item, index) => {
        const badge = adapterEventLabel(item);
        return (
          <button key={`${item.ts || index}-${item.event || 'adapter'}`} type="button" className="agent-event-row" onClick={() => onSelect(item)}>
            <span>
              <strong>{adapterEventTitle(item)}</strong>
              <small>{adapterEventDetail(item)}</small>
              <small>{adapterEventPreview(item)}</small>
            </span>
            <Badge variant="light" color={badge.color}>
              {badge.label}
            </Badge>
          </button>
        );
      }) : <div className="empty-box">暂无 NapCat 入站/出站日志。确认 OneBot HTTP 客户端 URL 指向 PA webhook 后再发一条消息。</div>}
    </Stack>
  );
}

function llmApiEventLabel(item: AnyRecord): { label: string; color: string } {
  const event = String(item.event || '');
  const level = String(item.level || '').toLowerCase();
  if (item.fused || event.includes('circuit')) return { label: '熔断', color: 'red' };
  if (level === 'error' || event.includes('failed')) return { label: '失败', color: 'red' };
  if (event.includes('cooldown')) return { label: '冷却', color: 'yellow' };
  if (event.includes('retry')) return { label: '重试', color: 'orange' };
  if (event.includes('success')) return { label: '成功', color: 'teal' };
  if (event.includes('start')) return { label: '开始', color: 'blue' };
  if (level === 'warn' || level === 'warning') return { label: '警告', color: 'yellow' };
  return { label: '记录', color: 'gray' };
}

function llmApiEventTitle(item: AnyRecord): string {
  const event = String(item.event || 'llm_api_event');
  const purpose = String(item.purpose || '').trim();
  const model = String(item.model || '').trim();
  return `${event}${purpose ? ` · ${purpose}` : ''}${model ? ` · ${shortText(model, 40)}` : ''}`;
}

function llmApiEventDetail(item: AnyRecord): string {
  const parts = [
    timeLabel(item.ts),
    item.attempt ? `第${formatCount(item.attempt)}次` : '',
    item.next_attempt ? `下次:${formatCount(item.next_attempt)}` : '',
    item.delay_ms !== undefined ? `等待:${formatCount(item.delay_ms)}ms` : '',
    item.cooldown_ms !== undefined ? `冷却:${formatCount(item.cooldown_ms)}ms` : '',
    item.remaining_ms !== undefined ? `剩余:${formatCount(item.remaining_ms)}ms` : '',
    item.failure_count !== undefined ? `失败:${formatCount(item.failure_count)}` : '',
    item.latency_ms !== undefined ? `耗时:${formatCount(item.latency_ms)}ms` : '',
  ].filter(Boolean);
  return parts.join(' | ');
}

function llmApiEventPreview(item: AnyRecord): string {
  const chunks = [
    item.endpoint ? `接口：${item.endpoint}` : '',
    item.prompt_chars !== undefined ? `上下文字符：${formatCount(item.prompt_chars)}` : '',
    item.message_count !== undefined ? `消息：${formatCount(item.message_count)}` : '',
    item.prompt_hash ? `hash:${item.prompt_hash}` : '',
    item.error ? `错误：${item.error}` : '',
  ].filter(Boolean);
  return shortText(chunks.join('  '), 220) || '无附加信息';
}

function LlmApiEventList({
  rows,
  onSelect,
}: {
  rows: AnyRecord[];
  onSelect: (item: AnyRecord) => void;
}) {
  return (
    <Stack gap={8}>
      {rows.length ? rows.slice().reverse().map((item, index) => {
        const badge = llmApiEventLabel(item);
        return (
          <button key={`${item.ts || index}-${item.event || 'llm-api'}`} type="button" className="agent-event-row" onClick={() => onSelect(item)}>
            <span>
              <strong>{llmApiEventTitle(item)}</strong>
              <small>{llmApiEventDetail(item)}</small>
              <small>{llmApiEventPreview(item)}</small>
            </span>
            <Badge variant="light" color={badge.color}>
              {badge.label}
            </Badge>
          </button>
        );
      }) : <div className="empty-box">暂无 LLM/API 调用日志。真正触发模型调用后会显示开始、成功、失败、重试、冷却和熔断。</div>}
    </Stack>
  );
}

function systemEventLabel(item: AnyRecord): { label: string; color: string } {
  const event = String(item.event || '');
  const level = String(item.level || '').toLowerCase();
  const status = String(item.status || '').toLowerCase();
  if (level === 'error' || status === 'failed' || event.includes('failed')) return { label: '报错', color: 'red' };
  if (level === 'warn' || level === 'warning') return { label: '警告', color: 'yellow' };
  if (status === 'done' || status === 'completed' || event.endsWith('ed')) return { label: '完成', color: 'teal' };
  if (item.progress !== undefined || status === 'running') return { label: '进度', color: 'blue' };
  if (level === 'debug') return { label: '详细', color: 'gray' };
  return { label: '重点', color: 'gray' };
}

function systemEventTitle(item: AnyRecord): string {
  const event = String(item.event || 'system_event');
  const task = String(item.task || '').trim();
  const stage = String(item.stage || '').trim();
  return `${task || event}${stage ? ` · ${stage}` : ''}`;
}

function systemEventDetail(item: AnyRecord): string {
  const parts = [
    timeLabel(item.ts),
    item.task_id ? `任务:${shortText(String(item.task_id), 32)}` : '',
    item.status ? `状态:${item.status}` : '',
    item.progress !== undefined ? `进度:${formatPercent(asNumber(item.progress, 0) / 100, 0)}` : '',
    item.progress_current !== undefined || item.progress_total !== undefined ? `${formatCount(item.progress_current)}/${formatCount(item.progress_total)}` : '',
  ].filter(Boolean);
  return parts.join(' | ');
}

function systemEventPreview(item: AnyRecord): string {
  const chunks = [
    item.summary ? String(item.summary) : '',
    item.detail ? String(item.detail) : '',
    item.error ? `错误：${item.error}` : '',
    item.path ? `路径：${item.path}` : '',
  ].filter(Boolean);
  return shortText(chunks.join('  '), 240) || '无附加信息';
}

function SystemEventList({
  rows,
  onSelect,
}: {
  rows: AnyRecord[];
  onSelect: (item: AnyRecord) => void;
}) {
  return (
    <Stack gap={8}>
      {rows.length ? rows.slice().reverse().map((item, index) => {
        const badge = systemEventLabel(item);
        const progress = item.progress !== undefined ? Math.max(0, Math.min(100, asNumber(item.progress, 0))) : null;
        return (
          <button key={`${item.ts || index}-${item.event || 'system'}-${item.task_id || ''}`} type="button" className="agent-event-row" onClick={() => onSelect(item)}>
            <span>
              <strong>{systemEventTitle(item)}</strong>
              <small>{systemEventDetail(item)}</small>
              <small>{systemEventPreview(item)}</small>
              {progress !== null ? <i className="agent-progress-line"><b style={{ width: `${progress}%` }} /></i> : null}
            </span>
            <Badge variant="light" color={badge.color}>
              {badge.label}
            </Badge>
          </button>
        );
      }) : <div className="empty-box">暂无系统日志。导入/导出运行包、日志维护、后端任务和报错会在这里显示。</div>}
    </Stack>
  );
}

function isToolSystemEvent(item: AnyRecord): boolean {
  const event = String(item.event || '');
  const task = String(item.task || '');
  const category = String(item.category || '').toLowerCase();
  return (
    category === 'tool'
    || event.startsWith('tool_')
    || event.includes('library')
    || event.includes('read_book')
    || ['读书', '导入图书', '生成图书简介', '选择图书文件'].includes(task)
  );
}

function filterToolEvents(rows: AnyRecord[], view = 'important'): AnyRecord[] {
  const key = String(view || 'important').toLowerCase();
  return rows.filter((item) => {
    if (!isToolSystemEvent(item)) return false;
    const level = String(item.level || '').toLowerCase();
    const event = String(item.event || '');
    if (key === 'errors') return ['warn', 'warning', 'error', 'fail'].includes(level) || event.endsWith('_failed');
    if (key === 'detail') return true;
    return item.progress !== undefined || item.task_id || ['info', 'warn', 'warning', 'error', 'fail'].includes(level);
  });
}

function ToolRunLogCard({
  events,
  counts,
  activeTasks,
  activeToolTask,
  view,
  busy,
  onViewChange,
  onRefresh,
  onSelect,
}: {
  events: AnyRecord[];
  counts: AnyRecord;
  activeTasks: AnyRecord[];
  activeToolTask?: AnyRecord;
  view: string;
  busy: boolean;
  onViewChange: (value: string) => void;
  onRefresh: () => void;
  onSelect: (item: AnyRecord) => void;
}) {
  const activeRows = [
    activeToolTask && String(activeToolTask.task_id || '').trim() && !['completed', 'done', 'failed', 'error', 'cancelled'].includes(String(activeToolTask.status || '').toLowerCase()) ? activeToolTask : null,
    ...activeTasks,
  ].filter(Boolean) as AnyRecord[];
  const dedupedActive = activeRows.filter((item, index, arr) => {
    const key = String(item.task_id || `${item.task || ''}_${item.stage || ''}_${index}`);
    return arr.findIndex((other, otherIndex) => String(other.task_id || `${other.task || ''}_${other.stage || ''}_${otherIndex}`) === key) === index;
  });
  return (
    <Card className="chart-card">
      <Group justify="space-between" align="flex-start" mb="xs">
        <div>
          <Group gap={8}>
            <IconTool size={18} />
            <Text fw={800}>工具运行日志</Text>
          </Group>
          <Text size="xs" c="dimmed">长期运行工具会在这里实时显示阶段、进度和报错；读书会展示 AP 输入、空 tick 和段落理解生成。</Text>
        </div>
        <Group gap={6}>
          <SegmentedControl
            size="xs"
            value={view}
            onChange={onViewChange}
            data={[
              { value: 'important', label: '重点' },
              { value: 'detail', label: '详细' },
              { value: 'errors', label: '错误' },
            ]}
          />
          <ActionIcon size="sm" variant="subtle" loading={busy} onClick={onRefresh} aria-label="刷新工具运行日志">
            <IconRefresh size={14} />
          </ActionIcon>
        </Group>
      </Group>
      {dedupedActive.length ? (
        <Stack gap={8} mb="sm">
          {dedupedActive.slice(0, 3).map((task, index) => {
            const progress = Math.max(0, Math.min(100, asNumber(task.progress, 0)));
            return (
              <button key={`${task.task_id || index}`} type="button" className="agent-task-progress-row" onClick={() => onSelect(task)}>
                <span>
                  <strong>{shortText(String(task.task || task.event || '运行中'), 48)}</strong>
                  <small>{systemEventDetail(task)}</small>
                  <i><b style={{ width: `${progress}%` }} /></i>
                </span>
                <Badge size="xs" variant="light" color="blue">{formatPercent(progress / 100, 0)}</Badge>
              </button>
            );
          })}
        </Stack>
      ) : null}
      <Group gap={6} mb="xs" wrap="wrap">
        <Badge size="xs" variant="light" color="blue">显示 {formatCount(events.length)}</Badge>
        <Badge size="xs" variant="outline">系统扫描 {formatCount(counts.total_scanned)}</Badge>
        <Badge size="xs" variant="light" color={dedupedActive.length ? 'blue' : 'gray'}>运行中 {formatCount(dedupedActive.length)}</Badge>
        <Badge size="xs" variant="light" color={asNumber(counts.error, 0) ? 'red' : 'gray'}>报错 {formatCount(counts.error)}</Badge>
      </Group>
      <ScrollArea.Autosize mah={320}>
        <SystemEventList rows={events} onSelect={onSelect} />
      </ScrollArea.Autosize>
    </Card>
  );
}

function LibraryReviewReaderCard({
  review,
  onInspect,
}: {
  review?: AnyRecord | null;
  onInspect: (item: AnyRecord) => void;
}) {
  const item = review || {};
  const text = String(item.understanding || item.summary || item.preview || '').trim();
  return (
    <Card className="chart-card agent-library-review-reader">
      <Group justify="space-between" align="flex-start" mb="xs">
        <div>
          <Group gap={8}>
            <IconBook size={18} />
            <Text fw={800}>段落理解</Text>
          </Group>
          <Text size="xs" c="dimmed">点击左侧段落理解条目后，这里显示完整可读内容，不再塞进 JSON 调试包。</Text>
        </div>
        <Group gap={6}>
          {item.llm_generated ? <Badge size="xs" variant="light" color="teal">LLM</Badge> : <Badge size="xs" variant="light" color="yellow">兜底</Badge>}
          <Button size="compact-xs" variant="subtle" disabled={!item.id} onClick={() => onInspect(item)}>JSON</Button>
        </Group>
      </Group>
      {item.id ? (
        <Stack gap={8}>
          <Group justify="space-between" gap={8} wrap="nowrap">
            <Text size="sm" fw={900}>{shortText(String(item.title || item.id || '段落理解'), 54)}</Text>
            <Badge size="xs" variant="outline">{formatCount(item.range?.start)}-{formatCount(item.range?.end)}</Badge>
          </Group>
          <Group gap={6} wrap="wrap">
            <Badge size="xs" variant="light">tick {formatCount(item.ap_tick_count)}</Badge>
            {item.model ? <Badge size="xs" variant="light" color="blue">{shortText(String(item.model), 28)}</Badge> : null}
            {item.book_title ? <Badge size="xs" variant="outline">{shortText(String(item.book_title), 32)}</Badge> : null}
          </Group>
          <ScrollArea.Autosize mah={420} className="agent-library-review-reader-scroll">
            <Text size="sm" className="agent-library-review-reader-text">
              {text || '这条段落理解还没有正文。'}
            </Text>
          </ScrollArea.Autosize>
          {item.excerpt ? (
            <details className="agent-library-review-excerpt">
              <summary>查看本段原文</summary>
              <p>{String(item.excerpt)}</p>
            </details>
          ) : null}
        </Stack>
      ) : (
        <div className="empty-box compact">还没有选中段落理解。先在左侧图书馆选择一本书，再点击某条段落理解。</div>
      )}
    </Card>
  );
}

function EnergyTrendChart({ snapshots, dark }: { snapshots: AnyRecord[]; dark: boolean }) {
  const rows = snapshots.map((item, index) => ({
    tick: item.tick_counter ?? index,
    er: asNumber(item.summary?.total_er, 0),
    ev: asNumber(item.summary?.total_ev, 0),
    cp: asNumber(item.summary?.total_cp, 0),
  }));
  const textColor = dark ? 'rgba(235, 250, 247, .78)' : 'rgba(25, 45, 52, .76)';
  const lineColor = dark ? 'rgba(255,255,255,.12)' : 'rgba(18, 52, 62, .12)';
  const option = {
    backgroundColor: 'transparent',
    color: ['#4dabf7', '#b197fc', '#ffd43b'],
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: textColor } },
    grid: { left: 42, right: 18, top: 44, bottom: 26 },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: rows.map((item) => item.tick),
      axisLabel: { color: textColor },
      axisLine: { lineStyle: { color: lineColor } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      splitLine: { lineStyle: { color: lineColor } },
      axisLabel: { color: textColor },
    },
    series: [
      { name: 'ER', type: 'line', smooth: true, showSymbol: rows.length < 40, data: rows.map((item) => item.er) },
      { name: 'EV', type: 'line', smooth: true, showSymbol: rows.length < 40, data: rows.map((item) => item.ev) },
      { name: 'CP', type: 'line', smooth: true, showSymbol: rows.length < 40, data: rows.map((item) => item.cp) },
    ],
  };
  return rows.length ? <ReactECharts option={option} style={{ height: 230 }} notMerge lazyUpdate /> : <div className="empty-chart">等待快照。</div>;
}

function ThoughtQualityChart({ thoughts, dark }: { thoughts: AnyRecord[]; dark: boolean }) {
  const rows = thoughts
    .slice()
    .reverse()
    .map((item, index) => ({
      label: `#${item.index ?? index + 1}`,
      overall: asNumber(item.quality?.overall, NaN),
      ap: asNumber(item.quality?.ap_usage, NaN),
      continuity: asNumber(item.quality?.continuity, NaN),
      persona: asNumber(item.quality?.persona_fit, NaN),
      restraint: asNumber(item.quality?.factual_restraint, NaN),
    }))
    .filter((item) => Number.isFinite(item.overall));
  const textColor = dark ? 'rgba(235, 250, 247, .78)' : 'rgba(25, 45, 52, .76)';
  const lineColor = dark ? 'rgba(255,255,255,.12)' : 'rgba(18, 52, 62, .12)';
  const option = {
    backgroundColor: 'transparent',
    color: ['#20c997', '#4dabf7', '#ffd43b', '#f783ac', '#b197fc'],
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: textColor } },
    grid: { left: 34, right: 14, top: 44, bottom: 24 },
    xAxis: { type: 'category', data: rows.map((item) => item.label), axisLabel: { color: textColor }, axisLine: { lineStyle: { color: lineColor } } },
    yAxis: { type: 'value', min: 0, max: 1, splitLine: { lineStyle: { color: lineColor } }, axisLabel: { color: textColor, formatter: (value: number) => `${Math.round(value * 100)}` } },
    series: [
      { name: '质量分', type: 'line', smooth: true, data: rows.map((item) => item.overall) },
      { name: 'AP', type: 'line', smooth: true, data: rows.map((item) => item.ap) },
      { name: '连续', type: 'line', smooth: true, data: rows.map((item) => item.continuity) },
      { name: '人设', type: 'line', smooth: true, data: rows.map((item) => item.persona) },
      { name: '克制', type: 'line', smooth: true, data: rows.map((item) => item.restraint) },
    ],
  };
  return rows.length ? <ReactECharts option={option} style={{ height: 210 }} notMerge lazyUpdate /> : <div className="empty-chart">等待 quality 数据。</div>;
}

function ConfigEditor({
  draft,
  setDraft,
  onSave,
  busy,
  stickerLibraryDir,
}: {
  draft: AgentConfig;
  setDraft: (fn: (prev: AgentConfig) => AgentConfig) => void;
  onSave: () => void;
  busy: boolean;
  stickerLibraryDir?: string;
}) {
  const setDraftEditable = setDraft;
  return (
    <Tabs defaultValue="model" className="agent-config-tabs">
      <Tabs.List>
        <Tabs.Tab value="model">模型</Tabs.Tab>
        <Tabs.Tab value="persona">人设</Tabs.Tab>
        <Tabs.Tab value="runtime">运行</Tabs.Tab>
        <Tabs.Tab value="adapter">适配</Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel value="model" pt="md">
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
          <Switch
            label="启用 LLM"
            checked={Boolean(draft.llm_enabled)}
            onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'llm_enabled', event.currentTarget.checked)}
          />
          <Switch
            label="自动回复"
            checked={draft.auto_reply !== false}
            onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'auto_reply', event.currentTarget.checked)}
          />
          <TextInput label="Base URL" value={String(draft.base_url || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'base_url', event.currentTarget.value)} />
          <Select
            label="接口格式"
            description="OpenAI 兼容适合大多数反代和聚合站；Claude 原生会使用 Anthropic messages 格式。"
            value={String(draft.api_request_format || 'auto')}
            data={apiRequestFormats}
            onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'api_request_format', value || 'auto')}
          />
          <Select
            label="端点拼接"
            description="反代如果已经给了完整入口，就选“Base URL 已是完整端点”，避免重复追加 /v1/chat/completions。"
            value={String(draft.api_endpoint_mode || 'auto_append')}
            data={apiEndpointModes}
            onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'api_endpoint_mode', value || 'auto_append')}
          />
          {String(draft.api_endpoint_mode || 'auto_append') !== 'base_is_endpoint' ? (
            <>
              <TextInput label="聊天端点路径" value={String(draft.chat_endpoint_path || '/v1/chat/completions')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'chat_endpoint_path', event.currentTarget.value)} />
              <TextInput label="Claude 原生端点路径" value={String(draft.anthropic_endpoint_path || '/v1/messages')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'anthropic_endpoint_path', event.currentTarget.value)} />
              <TextInput label="绘图端点路径" value={String(draft.image_generation_endpoint_path || '/v1/images/generations')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'image_generation_endpoint_path', event.currentTarget.value)} />
            </>
          ) : null}
          <PasswordInput
            label={draft.api_key_masked ? `API Key (${draft.api_key_masked})` : 'API Key'}
            value={String(draft.api_key || '')}
            onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'api_key', event.currentTarget.value)}
            placeholder="留空保存时保留已有密钥"
          />
          <TextInput label="主模型" value={String(draft.model || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'model', event.currentTarget.value)} />
          <TextInput label="视觉模型" value={String(draft.vision_model || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'vision_model', event.currentTarget.value)} />
          <PasswordInput
            label={draft.vision_api_key_masked ? `视觉 API Key (${draft.vision_api_key_masked})` : '视觉 API Key'}
            value={String(draft.vision_api_key || '')}
            onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'vision_api_key', event.currentTarget.value)}
            placeholder="留空复用主 API Key / 保存时保留已有密钥"
          />
          <TextInput label="多模态模型" value={String(draft.multimodal_model || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'multimodal_model', event.currentTarget.value)} />
          <PasswordInput
            label={draft.multimodal_api_key_masked ? `多模态 API Key (${draft.multimodal_api_key_masked})` : '多模态 API Key'}
            value={String(draft.multimodal_api_key || '')}
            onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'multimodal_api_key', event.currentTarget.value)}
            placeholder="留空复用主 API Key / 保存时保留已有密钥"
          />
          <TextInput label="绘图模型" value={String(draft.image_generation_model || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'image_generation_model', event.currentTarget.value)} />
          <PasswordInput
            label={draft.image_generation_api_key_masked ? `绘图 API Key (${draft.image_generation_api_key_masked})` : '绘图 API Key'}
            value={String(draft.image_generation_api_key || '')}
            onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'image_generation_api_key', event.currentTarget.value)}
            placeholder="留空复用主 API Key / 保存时保留已有密钥"
          />
          <Switch label="启用日记本工具" checked={draft.diary_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'diary_enabled', event.currentTarget.checked)} />
          <NumberInput label="日记总数上限" value={Number(draft.diary_entry_limit ?? 100)} min={10} max={1000} step={10} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'diary_entry_limit', Number(v) || 100)} />
          <NumberInput label="日记清理旧条目窗口" description="超过上限时，只在最旧的这批日记里删除重要性最低的一条。" value={Number(draft.diary_gc_oldest_count ?? 50)} min={1} max={1000} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'diary_gc_oldest_count', Number(v) || 50)} />
          <NumberInput label="单条日记最大字符" value={Number(draft.diary_entry_max_chars ?? 20000)} min={1000} max={120000} step={1000} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'diary_entry_max_chars', Number(v) || 20000)} />
          <NumberInput label="查日记返回总字符" value={Number(draft.diary_read_total_max_chars ?? 60000)} min={2000} max={240000} step={2000} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'diary_read_total_max_chars', Number(v) || 60000)} />
          <NumberInput label="近期工具 top 条数" description="进入 LLM 上下文的最近日记、定时任务和读书理解快捷线索数量；不足时仍应查完整列表。" value={Number(draft.tool_context_top_limit ?? 5)} min={0} max={30} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'tool_context_top_limit', Number(v) || 0)} />
          <NumberInput label="时序回忆超时 ms" description="只给线索、不带时间参数时，最多倒序回想多久；默认 5000。" value={Number(draft.timeline_recall_timeout_ms ?? 5000)} min={200} max={60000} step={100} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'timeline_recall_timeout_ms', Number(v) || 5000)} />
          <NumberInput label="时序回忆最低匹配分" description="只带线索回忆时，单条记忆至少达到这个分数才会进入候选。" value={Number(draft.timeline_recall_min_score ?? 0.28)} min={0} max={1.5} step={0.01} decimalScale={2} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'timeline_recall_min_score', Number(v) || 0)} />
          <NumberInput label="时序回忆累计阈值" description="只带线索回忆时，累计匹配分超过这个值就提前停止，避免无限往前翻。" value={Number(draft.timeline_recall_accumulate_threshold ?? 1.6)} min={0.1} max={20} step={0.1} decimalScale={2} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'timeline_recall_accumulate_threshold', Number(v) || 0.1)} />
          <NumberInput label="时序回忆疲劳衰减" description="越往更旧分片回想，匹配分乘上这个衰减系数；再次回忆时更容易捞到不同结果。" value={Number(draft.timeline_recall_fatigue_decay ?? 0.72)} min={0} max={1} step={0.01} decimalScale={2} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'timeline_recall_fatigue_decay', Number(v) || 0)} />
          <Switch label="启用定时任务工具" checked={draft.scheduled_tasks_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'scheduled_tasks_enabled', event.currentTarget.checked)} />
          <NumberInput label="定时任务总数上限" value={Number(draft.scheduled_task_limit ?? 100)} min={5} max={1000} step={5} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'scheduled_task_limit', Number(v) || 100)} />
          <NumberInput label="定时任务上限提醒比例" value={Number(draft.scheduled_task_warn_ratio ?? 0.9)} min={0.1} max={1} step={0.05} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'scheduled_task_warn_ratio', Number(v) || 0.9)} />
          <Switch label="启用图书馆/读书工具" checked={draft.library_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'library_enabled', event.currentTarget.checked)} />
          <NumberInput label="读书片段目标字数" description="推荐 10~30 字；会尽量按标点贴近目标长度切分。" value={Number(draft.library_chunk_target_chars ?? 30)} min={10} max={800} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'library_chunk_target_chars', Number(v) || 30)} />
          <NumberInput label="每段后空 tick" description="读书工具会循环执行：读一个短片段、跑这些空 tick、再继续读下一个短片段。" value={Number(draft.library_after_chunk_ticks ?? 6)} min={0} max={80} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'library_after_chunk_ticks', Number(v) || 0)} />
          <TextInput label="段落理解模型" description="留空时复用主模型；用于读书后生成可读段落理解。" value={String(draft.library_review_model || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'library_review_model', event.currentTarget.value)} />
          <PasswordInput
            label={draft.library_review_api_key_masked ? `段落理解 API Key (${draft.library_review_api_key_masked})` : '段落理解 API Key'}
            value={String(draft.library_review_api_key || '')}
            onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'library_review_api_key', event.currentTarget.value)}
            placeholder="留空复用主 API Key / 保存时保留已有密钥"
          />
          <NumberInput label="段落回顾 tick 间隔" description="累计到这个 AP tick 数后，才把本批次多段阅读生成一条段落理解；默认 300。" value={Number(draft.library_review_tick_interval ?? 300)} min={10} max={10000} step={10} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'library_review_tick_interval', Number(v) || 300)} />
          <NumberInput label="段落回顾文本预算" value={Number(draft.library_review_text_chars ?? 200000)} min={1000} max={1000000} step={10000} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'library_review_text_chars', Number(v) || 200000)} />
          <NumberInput label="图书馆书本上限" value={Number(draft.library_book_limit ?? 200)} min={1} max={1000} step={10} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'library_book_limit', Number(v) || 200)} />
          <CsvTextInput label="工具白名单" value={draft.tool_allowlist} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'tool_allowlist', value)} />
          <Select label="Prompt 风格" value={String(draft.prompt_variant || 'balanced')} data={promptVariants} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'prompt_variant', value || 'balanced')} />
          <Switch label="thought 质量评分" checked={draft.thought_quality_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'thought_quality_enabled', event.currentTarget.checked)} />
          <NumberInput label="temperature" value={Number(draft.temperature ?? 0.72)} min={0} max={2} step={0.05} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'temperature', Number(v) || 0)} />
          <NumberInput label="max tokens" value={Number(draft.max_completion_tokens ?? 5000)} min={256} max={12000} step={128} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'max_completion_tokens', Number(v) || 5000)} />
          <NumberInput label="重试次数" value={Number(draft.retry_count ?? 1)} min={0} max={5} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'retry_count', Number(v) || 0)} />
        </SimpleGrid>
        <Textarea mt="sm" label="多模态策略" minRows={2} autosize value={String(draft.multimodal_note || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'multimodal_note', event.currentTarget.value)} />
        <Textarea mt="sm" label="Prompt 追加提示" minRows={2} autosize value={String(draft.prompt_extra_note || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'prompt_extra_note', event.currentTarget.value)} />
      </Tabs.Panel>
      <Tabs.Panel value="persona" pt="md">
        <Stack gap="sm">
          <TextInput label="人设名称" value={String(draft.persona_name || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'persona_name', event.currentTarget.value)} />
          <Textarea label="人设信息" minRows={5} autosize value={String(draft.persona_text || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'persona_text', event.currentTarget.value)} />
          <Textarea label="日记/短期记忆种子" minRows={4} autosize value={String(draft.diary_seed || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'diary_seed', event.currentTarget.value)} />
          <Textarea label="系统注释" minRows={3} autosize value={String(draft.system_note || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'system_note', event.currentTarget.value)} />
        </Stack>
      </Tabs.Panel>
      <Tabs.Panel value="runtime" pt="md">
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
          <NumberInput label="前置 AP ticks" value={Number(draft.pre_thought_ticks ?? 5)} min={0} max={40} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'pre_thought_ticks', Number(v) || 0)} />
          <NumberInput label="想法后 ticks" value={Number(draft.post_thought_ticks ?? 2)} min={0} max={20} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'post_thought_ticks', Number(v) || 0)} />
          <NumberInput label="连续 thought 软上限" description="推荐 12；接近上限时会告诉 LLM，LLM 可用 continue_thinking 重置软窗口。" value={Number(draft.max_thoughts_per_turn ?? 12)} min={1} max={80} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'max_thoughts_per_turn', Number(v) || 1)} />
          <NumberInput label="连续 thought 硬熔断" description="防止模型无限循环；推荐为软上限的 3~4 倍。" value={Number(draft.max_total_thought_steps_per_turn ?? 48)} min={1} max={240} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'max_total_thought_steps_per_turn', Number(v) || 48)} />
          <NumberInput label="continue 重置次数" description="LLM 每次选择 continue_thinking 可重置软窗口，但最多重置这么多次。" value={Number(draft.thought_budget_reset_limit ?? 4)} min={0} max={32} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'thought_budget_reset_limit', Number(v) || 0)} />
          <Switch label="等 LLM 时自动跑空 tick" description="开启后，每次等待 LLM 返回期间，当前消息 worker 会穿插少量 AP 空 tick，减少纯等待时间。" checked={Boolean(draft.run_ap_while_waiting_llm)} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'run_ap_while_waiting_llm', event.currentTarget.checked)} />
          <NumberInput label="LLM 等待空 tick 间隔 ms" description="0 表示不额外等待；等待 LLM 期间会尽快跑完配置的空 tick。" value={Number(draft.llm_wait_tick_interval_ms ?? 0)} min={0} max={10000} step={10} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'llm_wait_tick_interval_ms', Math.max(0, Number(v) || 0))} />
          <NumberInput label="每次 LLM 最多空 tick" value={Number(draft.llm_wait_tick_max_per_call ?? 8)} min={0} max={80} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'llm_wait_tick_max_per_call', Number(v) || 0)} />
          <NumberInput label="后台 tick 间隔 ms" value={Number(draft.background_tick_interval_ms ?? 1200)} min={0} max={60000} step={100} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'background_tick_interval_ms', Number(v) || 0)} />
          <NumberInput label="AP 主观能动性检查间隔 tick" description="AP 主观能动性模式下，背景每跑这么多拍，才会轻量检查一次行动节点；推荐 30，避免后台过密占用主锁。" value={Number(draft.background_thought_interval_ticks ?? 30)} min={3} max={2000} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'background_thought_interval_ticks', Math.max(3, Number(v) || 30))} />
          <NumberInput label="强化主观能动性评估间隔 tick" description="强化主观能动性不会直接输出 thought，只会每隔 N tick 做一次‘现在值不值得再想’的轻量判断；推荐 30。" value={Number(draft.reinforced_agency_interval_ticks ?? 30)} min={5} max={5000} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reinforced_agency_interval_ticks', Math.max(5, Number(v) || 30))} />
          <NumberInput label="主动触发窗口 tick" description="用户输入或上一段想法进入后的这段窗口期内，会持续给‘主动触发大模型思考’行动节点注入驱动力。" value={Number(draft.agency_trigger_window_ticks ?? 12)} min={1} max={5000} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'agency_trigger_window_ticks', Number(v) || 1)} />
          <NumberInput label="主动思考行动增益" description="给 AP 内部‘主动触发大模型思考’行动节点注入的 drive 增益。" value={Number(draft.agency_action_drive_gain ?? 0.78)} min={0} max={6} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'agency_action_drive_gain', Number(v) || 0)} />
          <NumberInput label="主动思考触发阈值" description="该行动节点 drive 达到这个阈值时，会进入教师门控。" value={Number(draft.agency_trigger_threshold ?? 0.92)} min={0} max={6} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'agency_trigger_threshold', Number(v) || 0)} />
          <NumberInput label="主动回复行动增益" description="普通群消息进入 AP-only 门控后，用它给‘主动回复行动’节点赋能。" value={Number(draft.active_reply_action_drive_gain ?? 0.82)} min={0} max={6} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'active_reply_action_drive_gain', Number(v) || 0)} />
          <NumberInput label="主动回复触发阈值" description="主动回复行动节点达到阈值后，才进入 LLM 教师门控判断是否参与群聊。" value={Number(draft.active_reply_action_threshold ?? 0.9)} min={0.05} max={6} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'active_reply_action_threshold', Number(v) || 0.9)} />
          <NumberInput label="群聊 AP 门控 tick" description="群聊全量（AP门控）模式下，普通群消息只进入 AP 跑这些 tick，不直接调用 LLM。" value={Number(draft.group_all_ap_gate_ticks ?? 3)} min={2} max={20} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_all_ap_gate_ticks', Number(v) || 3)} />
          <Switch label="群聊连续对话窗口" description="群聊被唤醒后，接下来 N 条消息先过轻量门控；像是在对配置别名或关键词说话才进入主对话。" checked={draft.group_continuity_window_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_window_enabled', event.currentTarget.checked)} />
          <NumberInput label="连续窗口消息数 N" value={Number(draft.group_continuity_window_messages ?? 6)} min={1} max={80} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_window_messages', Number(v) || 6)} />
          <NumberInput label="连续窗口闲置超时 ms" description="默认 180000，也就是 3 分钟无新消息则关闭；0 表示不按闲置时间关闭。" value={Number(draft.group_continuity_window_timeout_ms ?? 180000)} min={0} max={86400000} step={10000} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_window_timeout_ms', Number(v) || 0)} />
          <TextInput label="连续窗口门控模型" description="留空沿用主模型。" value={String(draft.group_continuity_gate_model || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_gate_model', event.currentTarget.value)} />
          <NumberInput label="连续门控最低置信度" value={Number(draft.group_continuity_gate_min_confidence ?? 0.62)} min={0} max={1} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_gate_min_confidence', Number(v) || 0)} />
          <NumberInput label="连续门控上下文条数" value={Number(draft.group_continuity_gate_context_messages ?? 18)} min={4} max={80} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_gate_context_messages', Number(v) || 18)} />
          <NumberInput label="背景唤醒参考阈值" value={Number(draft.wake_drive_threshold ?? 0.68)} min={0} max={2} step={0.05} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'wake_drive_threshold', Number(v) || 0)} />
          <NumberInput label="对象云上限" value={Number(draft.object_cloud_limit ?? 60)} min={12} max={200} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'object_cloud_limit', Number(v) || 60)} />
          <NumberInput label="事件日志上限" value={Number(draft.event_log_limit ?? 300)} min={20} max={2000} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'event_log_limit', Number(v) || 300)} />
          <Switch label="启用输入切分排队" checked={draft.input_chunking_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'input_chunking_enabled', event.currentTarget.checked)} />
          <NumberInput label="输入切分软上限" description="推荐 10；超过这个长度后，会优先在接近 30 字的位置按标点切到下一拍。" value={Number(draft.input_chunk_soft_limit ?? 10)} min={4} max={120} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'input_chunk_soft_limit', Number(v) || 10)} />
          <NumberInput label="输入切分硬上限" description="推荐 30；如果 10~30 字之间没有合适标点，就会在 30 字附近强制切开。" value={Number(draft.input_chunk_hard_limit ?? 30)} min={4} max={220} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'input_chunk_hard_limit', Number(v) || 30)} />
          <Switch label="启用教师门控" checked={draft.agency_teacher_gate_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'agency_teacher_gate_enabled', event.currentTarget.checked)} />
          <NumberInput label="教师门控最低置信度" description="门控 LLM 不确定时，至少按这个置信度回传到前端，便于观察。" value={Number(draft.agency_teacher_gate_confidence ?? 0.62)} min={0} max={1} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'agency_teacher_gate_confidence', Number(v) || 0)} />
          <NumberInput label="门控成功奖励" description="门控判断应该主动触发思考时，写入 AP 的 teacher reward。" value={Number(draft.agency_teacher_reward ?? 0.85)} min={0} max={1} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'agency_teacher_reward', Number(v) || 0)} />
          <NumberInput label="门控失败惩罚" description="门控判断这是噪声唤醒时，写入 AP 的 teacher punish。" value={Number(draft.agency_teacher_punish ?? 0.55)} min={0} max={1} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'agency_teacher_punish', Number(v) || 0)} />
          <Select label="休眠模式" value={String(draft.sleep_mode || 'full_silent')} data={sleepModes} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'sleep_mode', value || 'full_silent')} />
          <TriggerModeSwitches draft={draft} setDraft={setDraftEditable} />
          <CsvTextInput label="群聊昵称/艾特" value={draft.group_at_names} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'group_at_names', value)} />
          <CsvTextInput label="唤醒关键词" value={draft.wake_keywords} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'wake_keywords', value)} />
          <TextInput label="静默开始" value={String(draft.quiet_hours_start || '')} placeholder="23:30" onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'quiet_hours_start', event.currentTarget.value)} />
          <TextInput label="静默结束" value={String(draft.quiet_hours_end || '')} placeholder="08:00" onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'quiet_hours_end', event.currentTarget.value)} />
          <Switch label="群聊无艾特也唤醒" checked={Boolean(draft.allow_group_without_at)} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'allow_group_without_at', event.currentTarget.checked)} />
        </SimpleGrid>
      </Tabs.Panel>
      <Tabs.Panel value="adapter" pt="md">
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
          <Select label="平台适配器" value={String(draft.platform_adapter || 'local')} data={adapterModes} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'platform_adapter', value || 'local')} />
          <TextInput label="NapCat HTTP URL" value={String(draft.qq_napcat_http_url || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'qq_napcat_http_url', event.currentTarget.value)} />
          <TextInput label="主人 QQ" value={String(draft.owner_qq || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'owner_qq', event.currentTarget.value)} />
          <Select label="名单模式" value={String(draft.qq_access_mode || 'off')} data={accessModes} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'qq_access_mode', value || 'off')} />
          <CsvTextInput label="用户白名单" value={draft.qq_user_whitelist} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'qq_user_whitelist', value)} />
          <CsvTextInput label="群白名单" value={draft.qq_group_whitelist} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'qq_group_whitelist', value)} />
          <CsvTextInput label="用户黑名单" value={draft.qq_user_blacklist} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'qq_user_blacklist', value)} />
          <CsvTextInput label="群黑名单" value={draft.qq_group_blacklist} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'qq_group_blacklist', value)} />
          <Switch label="NapCat QQ" checked={Boolean(draft.qq_napcat_enabled)} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'qq_napcat_enabled', event.currentTarget.checked)} />
          <Switch label="NapCat dry-run" checked={draft.qq_napcat_dry_run !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'qq_napcat_dry_run', event.currentTarget.checked)} />
          <Switch label="QQ 短期上下文按对象隔离" description="开启后私聊/群聊各看各的近期对话；AP 状态池和长期记忆仍共享。" checked={draft.qq_short_context_isolation_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'qq_short_context_isolation_enabled', event.currentTarget.checked)} />
          <NumberInput label="发送间隔 ms" value={Number(draft.qq_napcat_min_send_interval_ms ?? 1200)} min={0} max={60000} step={100} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'qq_napcat_min_send_interval_ms', Number(v) || 0)} />
          <Switch label="回复自动分段" description="只影响发送给 QQ 的公开文本；thought 不分段。" checked={Boolean(draft.reply_auto_segment_enabled)} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'reply_auto_segment_enabled', event.currentTarget.checked)} />
          <TextInput label="回复分段符" description="例如 |；开启后会写入 reply 提示词，发送时去掉该符号。" value={String(draft.reply_auto_segment_delimiter || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'reply_auto_segment_delimiter', event.currentTarget.value)} />
          <Select label="分段发送间隔" value={String(draft.reply_segment_interval_mode || 'adaptive')} data={replySegmentIntervalModes} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_interval_mode', value || 'adaptive')} />
          <NumberInput label="固定分段间隔 ms" value={Number(draft.reply_segment_fixed_interval_ms ?? 650)} min={0} max={60000} step={50} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_fixed_interval_ms', Number(v) || 0)} />
          <NumberInput label="自动间隔最小 ms" value={Number(draft.reply_segment_adaptive_min_ms ?? 420)} min={0} max={60000} step={50} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_adaptive_min_ms', Number(v) || 0)} />
          <NumberInput label="自动间隔最大 ms" value={Number(draft.reply_segment_adaptive_max_ms ?? 1800)} min={0} max={60000} step={50} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_adaptive_max_ms', Number(v) || 0)} />
          <NumberInput label="每字增加 ms" value={Number(draft.reply_segment_adaptive_ms_per_char ?? 55)} min={0} max={5000} step={5} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_adaptive_ms_per_char', Number(v) || 0)} />
          <NumberInput label="间隔随机波动" description="0.1 表示约 10%。" value={Number(draft.reply_segment_interval_jitter ?? 0.1)} min={0} max={0.5} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_interval_jitter', Number(v) || 0)} />
          <NumberInput label="自动分段目标字数" value={Number(draft.reply_segment_target_chars ?? 16)} min={4} max={120} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_target_chars', Number(v) || 16)} />
          <NumberInput label="最多分段数" value={Number(draft.reply_segment_max_segments ?? 8)} min={1} max={40} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_max_segments', Number(v) || 8)} />
          <Switch label="群聊艾特触发" checked={draft.group_trigger_at !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'group_trigger_at', event.currentTarget.checked)} />
          <Switch label="群聊关键词触发" checked={draft.group_trigger_keyword !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'group_trigger_keyword', event.currentTarget.checked)} />
          <NumberInput label="群聊概率触发 0~1" value={Number(draft.group_trigger_probability ?? 0)} min={0} max={1} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_trigger_probability', Number(v) || 0)} />
          <Switch label="表情包小偷" description="收到图片后可用多模态模型判断是否适合保存为常用表情包。" checked={Boolean(draft.sticker_steal_enabled)} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'sticker_steal_enabled', event.currentTarget.checked)} />
          <TextInput label="表情包目录" value={String(draft.sticker_library_dir || stickerLibraryDir || 'observatory/outputs/agent/stickers')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'sticker_library_dir', event.currentTarget.value)} />
          <NumberInput label="Prompt 近期表情包" value={Number(draft.sticker_prompt_recent_limit ?? 5)} min={0} max={30} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'sticker_prompt_recent_limit', Number(v) || 0)} />
          <NumberInput label="Prompt 高频表情包" value={Number(draft.sticker_prompt_top_limit ?? 5)} min={0} max={30} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'sticker_prompt_top_limit', Number(v) || 0)} />
          <NumberInput label="Prompt 随机表情包" value={Number(draft.sticker_prompt_random_limit ?? 10)} min={0} max={60} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'sticker_prompt_random_limit', Number(v) || 0)} />
          <Switch label="启用定时任务工具" checked={draft.scheduled_tasks_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'scheduled_tasks_enabled', event.currentTarget.checked)} />
          <NumberInput label="定时任务总数上限" value={Number(draft.scheduled_task_limit ?? 100)} min={5} max={1000} step={5} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'scheduled_task_limit', Number(v) || 100)} />
          <NumberInput label="定时任务上限提醒比例" value={Number(draft.scheduled_task_warn_ratio ?? 0.9)} min={0.1} max={1} step={0.05} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'scheduled_task_warn_ratio', Number(v) || 0.9)} />
          <Switch label="MCP" checked={Boolean(draft.mcp_enabled)} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'mcp_enabled', event.currentTarget.checked)} />
          <Switch label="Skills" checked={draft.skill_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'skill_enabled', event.currentTarget.checked)} />
          <NumberInput label="历史上限" value={Number(draft.history_limit ?? 80)} min={20} max={500} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'history_limit', Number(v) || 80)} />
        </SimpleGrid>
      </Tabs.Panel>
      <Group justify="flex-end" mt="md">
        <Button leftSection={<IconDeviceFloppy size={16} />} loading={busy} onClick={onSave}>
          保存配置
        </Button>
      </Group>
    </Tabs>
  );
}

function ConfigProfilePanel({
  profiles,
  profileName,
  profileNote,
  setProfileName,
  setProfileNote,
  onSave,
  onApply,
  onDelete,
  busy,
}: {
  profiles: AnyRecord[];
  profileName: string;
  profileNote: string;
  setProfileName: (value: string) => void;
  setProfileNote: (value: string) => void;
  onSave: () => void;
  onApply: (id: string) => void;
  onDelete: (id: string) => void;
  busy: boolean;
}) {
  return (
    <div className="agent-profile-panel">
      <Group justify="space-between" mb="xs">
        <Text fw={800} size="sm">配置快照</Text>
        <Badge variant="light">{profiles.length} profiles</Badge>
      </Group>
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing={6}>
        <TextInput size="xs" placeholder="快照名称" value={profileName} onChange={(event) => setProfileName(event.currentTarget.value)} />
        <TextInput size="xs" placeholder="备注，可写用途/模型/人设" value={profileNote} onChange={(event) => setProfileNote(event.currentTarget.value)} />
      </SimpleGrid>
      <Group justify="space-between" mt="xs">
        <Text size="xs" c="dimmed">默认不复制 API Key；应用时保留当前密钥。</Text>
        <Button size="xs" variant="light" leftSection={<IconDeviceFloppy size={14} />} loading={busy} onClick={onSave}>
          保存快照
        </Button>
      </Group>
      {profiles.length ? (
        <Stack gap={6} mt="sm">
          {profiles.slice(0, 6).map((profile) => {
            const summary = (profile.summary || {}) as AnyRecord;
            const id = String(profile.id || '');
            return (
              <div key={id || String(profile.name)} className="agent-profile-row">
                <button type="button" onClick={() => onApply(id)} disabled={!id || busy}>
                  <span>
                    <strong>{shortText(String(profile.name || id || '未命名快照'), 36)}</strong>
                    <small>{shortText(`${summary.persona_name || '-'} / ${summary.model || 'fallback'} / ${summary.sleep_mode || '-'}`, 92)}</small>
                    {profile.note ? <em>{shortText(String(profile.note), 90)}</em> : null}
                  </span>
                  <Badge variant="outline" color={summary.napcat_enabled ? 'green' : 'gray'}>
                    {summary.platform_adapter || 'local'}
                  </Badge>
                </button>
                <ActionIcon variant="subtle" color="red" aria-label="删除快照" disabled={!id || busy} onClick={() => onDelete(id)}>
                  <IconEraser size={15} />
                </ActionIcon>
              </div>
            );
          })}
        </Stack>
      ) : (
        <div className="empty-box compact">还没有快照。建议先保存一个“本地安全默认配置”。</div>
      )}
    </div>
  );
}

function BeginnerMissionsPanel({
  progress,
  busy,
  onRefresh,
}: {
  progress: AnyRecord | null;
  busy: boolean;
  onRefresh: () => void;
}) {
  const missions = asArray<AnyRecord>(progress?.missions);
  const grouped = {
    main: missions.filter((item) => String(item.kind || '') === 'main'),
    daily: missions.filter((item) => String(item.kind || '') === 'daily'),
    side: missions.filter((item) => !['main', 'daily'].includes(String(item.kind || ''))),
  };
  const total = missions.length || 1;
  const done = missions.filter((item) => Boolean(item.completed)).length;
  return (
    <Card className="agent-readiness-card agent-mission-card" mb="md">
      <Group justify="space-between" mb="xs">
        <Group gap={8}>
          <IconListDetails size={18} />
          <Text fw={800}>新手任务</Text>
        </Group>
        <Group gap={6}>
          <Badge variant="light" color={done >= total ? 'teal' : 'blue'}>{done}/{total}</Badge>
          <ActionIcon size="sm" variant="subtle" loading={busy} aria-label="刷新新手任务" onClick={onRefresh}>
            <IconRefresh size={15} />
          </ActionIcon>
        </Group>
      </Group>
      <Text size="xs" c="dimmed" mb="sm">
        像任务栏一样，一步步带你把配置、首次对话和各种工具试起来。完成后会累计经验值和称号进度。
      </Text>
      {(['main', 'daily', 'side'] as const).map((groupKey) => {
        const rows = grouped[groupKey];
        if (!rows.length) return null;
        const label = groupKey === 'main' ? '主线' : groupKey === 'daily' ? '日常' : '支线';
        return (
          <Stack gap={6} key={groupKey} mb="xs">
            <Text size="xs" fw={700} c="dimmed">{label}</Text>
            {rows.map((item) => (
              <div key={String(item.id || item.label)} className={`agent-mission-row${item.completed ? ' is-complete' : ''}`}>
                <div className="agent-mission-row-main">
                  <Group gap={6} wrap="nowrap">
                    <Badge size="xs" variant="light" color={item.completed ? 'teal' : 'yellow'}>
                      {item.completed ? '已完成' : '进行中'}
                    </Badge>
                    <Text size="sm" fw={700}>{String(item.label || item.id || '-')}</Text>
                  </Group>
                  <Text size="xs" c="dimmed">{String(item.detail || '')}</Text>
                </div>
                <div className="agent-mission-row-side">
                  <Badge variant="outline">{String(item.progress_text || '0/1')}</Badge>
                  <Badge variant="subtle" color="grape">+{formatCount(item.xp)} XP</Badge>
                </div>
              </div>
            ))}
          </Stack>
        );
      })}
    </Card>
  );
}

function PersonaHistoryPanel({
  records,
  draft,
  busy,
  editingId,
  onSaveCurrent,
  onSaveAsNew,
  onResetEditing,
  onLoadToDraft,
  onApply,
  onDelete,
}: {
  records: PersonaHistoryRecord[];
  draft: AgentConfig;
  busy: boolean;
  editingId: string;
  onSaveCurrent: () => void;
  onSaveAsNew: () => void;
  onResetEditing: () => void;
  onLoadToDraft: (record: PersonaHistoryRecord) => void;
  onApply: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const editingRecord = records.find((item) => String(item.id || '') === editingId) || null;
  return (
    <div className="agent-profile-panel">
      <Group justify="space-between" mb="xs">
        <Text fw={800} size="sm">历史人设</Text>
        <Badge variant="light">{records.length} 条</Badge>
      </Group>
      <Text size="xs" c="dimmed">
        把你保存过的人设留在这里，随时点一下就能切换，也方便反复调试不同设定。
      </Text>
      {editingRecord ? (
        <div className="agent-progress-achievement" style={{ marginTop: 12 }}>
          <strong>{`当前正在编辑：${String(editingRecord.name || editingRecord.persona_name || editingRecord.id || '历史人设')}`}</strong>
          <small>保存会直接更新这条历史人设；如果想保留旧版本，可以先点“另存为新记录”。</small>
        </div>
      ) : null}
      <Group mt="sm" grow>
        <Button variant="light" leftSection={<IconDeviceFloppy size={16} />} loading={busy} onClick={onSaveCurrent}>
          {editingRecord ? '更新当前历史人设' : '保存当前草稿为历史人设'}
        </Button>
        {editingRecord ? (
          <>
            <Button variant="subtle" loading={busy} onClick={onSaveAsNew}>
              另存为新记录
            </Button>
            <Button variant="subtle" color="gray" loading={busy} onClick={onResetEditing}>
              取消编辑关联
            </Button>
          </>
        ) : null}
      </Group>
      {records.length ? (
        <Stack gap={6} mt="sm">
          {records.slice(0, 8).map((record) => {
            const id = String(record.id || '');
            const title = String(record.name || record.persona_name || '未命名人设');
            const detail = shortText(String(record.note || record.persona_text || ''), 110);
            return (
              <div key={id || title} className="agent-profile-row">
                <button type="button" onClick={() => onLoadToDraft(record)} disabled={busy}>
                  <span>
                    <strong>{shortText(title, 32)}</strong>
                    <small>{detail || '点击后会把这条人设载入到当前配置草稿，方便继续改。'}</small>
                    <em>{`使用 ${formatCount(record.use_count)} 次 · ${record.is_default ? '默认底稿' : '自定义'}`}</em>
                  </span>
                  <Badge variant="outline">{formatCount(record.summary?.persona_chars)} 字</Badge>
                </button>
                <div className="agent-profile-row-actions">
                  <ActionIcon variant="subtle" color="teal" aria-label="快速应用历史人设" disabled={!id || busy} onClick={() => id && onApply(id)}>
                    <IconDeviceFloppy size={15} />
                  </ActionIcon>
                  <ActionIcon variant="subtle" color="red" aria-label="删除历史人设" disabled={!id || busy} onClick={() => id && onDelete(id)}>
                    <IconEraser size={15} />
                  </ActionIcon>
                </div>
              </div>
            );
          })}
        </Stack>
      ) : (
        <div className="empty-box compact" style={{ minHeight: 120 }}>
          还没有历史人设。先修改当前人设草稿并保存一次，这里就会出现可切换记录。
        </div>
      )}
      <Divider my="sm" />
      <Text size="xs" c="dimmed">
        当前草稿：{draft.persona_name || '未命名'}。保存后会保留名称、人设正文、日记种子和系统注释。
      </Text>
    </div>
  );
}

function UserProgressCard({
  progress,
  busy = false,
  onSaveLoadout,
}: {
  progress: AnyRecord | null;
  busy?: boolean;
  onSaveLoadout?: (payload: { current_title_id?: string; equipped_badge_ids?: string[] }) => Promise<void> | void;
}) {
  const level = Number(progress?.level ?? 1);
  const xp = Number(progress?.xp ?? 0);
  const currentTitle = String(progress?.current_title_id || '初来乍到');
  const titles = asArray<AnyRecord>(progress?.titles);
  const badges = asArray<AnyRecord>(progress?.badges);
  const achievements = asArray<AnyRecord>(progress?.achievements);
  const achievementCatalogRows = asArray<AnyRecord>(progress?.achievement_catalog);
  const equippedBadgeIds = asArray<string>(progress?.equipped_badge_ids).map((item) => String(item || ''));
  const daily = (progress?.daily_chat || {}) as AnyRecord;
  const streak = (progress?.daily_streak || {}) as AnyRecord;
  const xpIntoLevel = Math.max(0, Number(progress?.xp_into_level ?? xp));
  const xpSpan = Math.max(1, Number(progress?.xp_next ?? 100) - Number(progress?.xp_floor ?? 0));
  const xpRatio = Math.max(0, Math.min(1, xpIntoLevel / xpSpan));
  const recentAchievements = achievements.slice(-3).reverse();
  const [achievementExpanded, setAchievementExpanded] = useState(false);
  const [badgePickerExpanded, setBadgePickerExpanded] = useState(false);
  const titleOptions = titles
    .map((item) => ({ value: String(item.id || item.name || ''), label: String(item.name || item.id || '未命名称号') }))
    .filter((item) => item.value);
  const badgeMap = new Map(badges.map((item) => [String(item.id || item.name || ''), item] as const));
  const equippedBadges = equippedBadgeIds.map((id) => badgeMap.get(id)).filter(Boolean) as AnyRecord[];
  const unequippedBadges = badges.filter((item) => {
    const badgeId = String(item.id || item.name || '');
    return badgeId && !equippedBadgeIds.includes(badgeId);
  });
  const achievementCatalog = (achievementCatalogRows.length ? achievementCatalogRows : achievements).map((item) => ({
    id: String(item.id || item.name || ''),
    name: String(item.name || item.id || '未命名成就'),
    detail: String(item.detail || ''),
  })).filter((item) => item.id);
  const unlockedAchievementIds = new Set(achievements.map((item) => String(item.id || '')));
  const achievementWall = achievementCatalog.map((item) => ({
    ...item,
    unlocked: unlockedAchievementIds.has(item.id),
  }));
  const toggleBadge = async (badgeId: string) => {
    if (!badgeId) return;
    const next = equippedBadgeIds.includes(badgeId)
      ? equippedBadgeIds.filter((item) => item !== badgeId)
      : [...equippedBadgeIds, badgeId].slice(0, 5);
    await onSaveLoadout?.({ equipped_badge_ids: next });
  };
  return (
    <Card className="pa-panel agent-progress-card" mt="md">
      <Group justify="space-between" mb="xs">
        <Text fw={900}>用户等级 / 荣誉</Text>
        <Badge variant="light" color="grape">{currentTitle}</Badge>
      </Group>
      <div className="agent-progress-bar">
        <div className="agent-progress-bar-fill" style={{ width: `${Math.max(6, xpRatio * 100)}%` }} />
        <span>{`Lv.${formatCount(level)} · ${formatCount(xp)} XP`}</span>
      </div>
      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="xs">
        <div className="agent-progress-metric">
          <small>等级</small>
          <strong>Lv.{formatCount(level)}</strong>
        </div>
        <div className="agent-progress-metric">
          <small>经验</small>
          <strong>{formatCount(xp)} XP</strong>
        </div>
        <div className="agent-progress-metric">
          <small>今日对话</small>
          <strong>{Boolean(daily.completed) ? '已完成' : '未完成'}</strong>
        </div>
        <div className="agent-progress-metric">
          <small>连续天数</small>
          <strong>{formatCount(streak.current)} 天</strong>
        </div>
      </SimpleGrid>
      <Group gap={6} mt="sm">
        <Badge variant="outline">称号 {formatCount(titles.length)}</Badge>
        <Badge variant="outline">勋章 {formatCount(badges.length)}</Badge>
        <Badge variant="outline">{`成就 ${formatCount(achievements.length)}/${formatCount(achievementCatalog.length || achievements.length)}`}</Badge>
      </Group>
      <div className="agent-progress-loadout">
        <div className="agent-progress-loadout-block">
          <small>当前称号</small>
          <Select
            size="xs"
            data={titleOptions}
            value={currentTitle}
            disabled={busy || !titleOptions.length}
            onChange={(value) => {
              if (value && value !== currentTitle) void onSaveLoadout?.({ current_title_id: value });
            }}
          />
        </div>
        <div className="agent-progress-loadout-block">
          <small>{`佩戴勋章 (${formatCount(equippedBadgeIds.length)}/5)`}</small>
          <div className="agent-progress-badge-grid">
            {equippedBadges.length ? equippedBadges.map((item) => {
              const badgeId = String(item.id || item.name || '');
              return (
                <button
                  key={badgeId}
                  type="button"
                  className="agent-progress-badge-toggle is-equipped"
                  disabled={busy}
                  onClick={() => void toggleBadge(badgeId)}
                >
                  <strong>{shortText(String(item.name || badgeId || '-'), 18)}</strong>
                  <small>{shortText(String(item.detail || '点击即可卸下这枚勋章。'), 44)}</small>
                </button>
              );
            }) : <div className="agent-progress-empty">暂时还没有佩戴勋章，展开下方列表即可选择。</div>}
          </div>
          {badges.length ? (
            <div className="agent-progress-achievement-panel">
              <button type="button" className="agent-progress-achievement-toggle" onClick={() => setBadgePickerExpanded((value) => !value)}>
                <strong>{badgePickerExpanded ? '收起未佩戴勋章' : '查看未佩戴勋章'}</strong>
                <small>{unequippedBadges.length ? `当前还有 ${formatCount(unequippedBadges.length)} 枚可选，点击后即可佩戴。` : '当前已经没有可选的未佩戴勋章了。'}</small>
              </button>
              {badgePickerExpanded ? (
                <div className="agent-progress-badge-grid">
                  {unequippedBadges.length ? unequippedBadges.map((item) => {
                    const badgeId = String(item.id || item.name || '');
                    const blocked = equippedBadgeIds.length >= 5;
                    return (
                      <button
                        key={badgeId}
                        type="button"
                        className={`agent-progress-badge-toggle${blocked ? ' is-blocked' : ''}`}
                        disabled={busy || blocked}
                        onClick={() => void toggleBadge(badgeId)}
                      >
                        <strong>{shortText(String(item.name || badgeId || '-'), 18)}</strong>
                        <small>{shortText(String(item.detail || ''), 44)}</small>
                      </button>
                    );
                  }) : <div className="agent-progress-empty">全部勋章都已经处理完了。</div>}
                </div>
              ) : null}
            </div>
          ) : <div className="agent-progress-empty">还没有可佩戴勋章。</div>}
        </div>
      </div>
      {recentAchievements.length ? (
        <div className="agent-progress-achievements">
          {recentAchievements.map((item) => (
            <div key={String(item.id || item.name)} className="agent-progress-achievement">
              <strong>{String(item.name || item.id || '-')}</strong>
              <small>{shortText(String(item.detail || ''), 64)}</small>
            </div>
          ))}
        </div>
      ) : null}
      <div className="agent-progress-achievement-panel">
        <button type="button" className="agent-progress-achievement-toggle" onClick={() => setAchievementExpanded((value) => !value)}>
          <strong>{achievementExpanded ? '收起成就总览' : '查看成就总览'}</strong>
          <small>{`已完成 ${formatCount(achievements.length)} 项，未完成显示为黑白。`}</small>
        </button>
        {achievementExpanded ? (
          <div className="agent-progress-achievement-wall">
            {achievementWall.map((item) => (
              <div key={item.id} className={`agent-progress-achievement ${item.unlocked ? 'is-unlocked' : 'is-locked'}`}>
                <strong>{item.name}</strong>
                <small>{item.detail}</small>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      <Text size="xs" c="dimmed" mt="sm">
        主线、支线和日常任务都会在本地累计经验值。清空运行态不会清掉这些用户成长记录。
      </Text>
    </Card>
  );
}

function ReadinessPanel({ readiness, onRefresh, busy }: { readiness: AnyRecord | null; onRefresh: () => void; busy: boolean }) {
  const counts = (readiness?.counts || {}) as AnyRecord;
  const status = String(readiness?.overall || 'warn');
  const color = status === 'pass' ? 'teal' : status === 'fail' ? 'red' : 'yellow';
  const checks = asArray<AnyRecord>(readiness?.checks);
  return (
    <Card className="agent-readiness-card" mb="md">
      <Group justify="space-between" mb="xs">
        <Group gap={8}>
          {status === 'pass' ? <IconCircleCheck size={18} /> : <IconAlertTriangle size={18} />}
          <Text fw={800}>启动体检</Text>
        </Group>
        <Group gap={6}>
          <Badge variant="light" color={color}>{status}</Badge>
          <ActionIcon size="sm" variant="subtle" loading={busy} aria-label="刷新启动体检" onClick={onRefresh}>
            <IconRefresh size={15} />
          </ActionIcon>
        </Group>
      </Group>
      <Group gap={6} mb="xs">
        <Badge size="xs" variant="outline" color="teal">pass {formatCount(counts.pass)}</Badge>
        <Badge size="xs" variant="outline" color="yellow">warn {formatCount(counts.warn)}</Badge>
        <Badge size="xs" variant="outline" color="red">fail {formatCount(counts.fail)}</Badge>
      </Group>
      <Stack gap={6}>
        {checks.slice(0, 8).map((check) => {
          const itemColor = check.status === 'pass' ? 'teal' : check.status === 'fail' ? 'red' : 'yellow';
          return (
            <button key={String(check.id || check.label)} type="button" className="agent-readiness-row" onClick={() => undefined}>
              <Badge size="xs" variant="light" color={itemColor}>{String(check.status || 'warn')}</Badge>
              <span>
                <strong>{shortText(String(check.label || check.id || '-'), 32)}</strong>
                <small>{shortText(String(check.detail || check.action || ''), 110)}</small>
              </span>
            </button>
          );
        })}
      </Stack>
    </Card>
  );
}

function ModelReadinessPanel({
  readiness,
  busy,
  onRefresh,
  onTest,
}: {
  readiness: AnyRecord | null;
  busy: boolean;
  onRefresh: () => void;
  onTest: () => void;
}) {
  const counts = (readiness?.counts || {}) as AnyRecord;
  const active = (readiness?.active_config || {}) as AnyRecord;
  const pool = (readiness?.pool_summary || {}) as AnyRecord;
  const status = String(readiness?.overall || 'warn');
  const color = status === 'pass' ? 'teal' : status === 'fail' ? 'red' : 'yellow';
  const checks = asArray<AnyRecord>(readiness?.checks);
  return (
    <Card className="agent-model-readiness-card" mb="md">
      <Group justify="space-between" align="flex-start" gap="sm" mb="xs">
        <div>
          <Group gap={8} mb={4}>
            <IconPlugConnected size={18} />
            <Text fw={800}>模型接入体检</Text>
            <Badge variant="light" color={color}>{status}</Badge>
            <Badge variant="outline" color={readiness?.ready_to_call ? 'teal' : 'yellow'}>
              {readiness?.ready_to_call ? 'ready' : 'fallback'}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">只读配置检查，不调用外部模型；真实连通请使用 LLM 连通。</Text>
        </div>
        <Group gap={6}>
          <ActionIcon size="sm" variant="subtle" loading={busy} aria-label="刷新模型接入体检" onClick={onRefresh}>
            <IconRefresh size={15} />
          </ActionIcon>
          <Button size="compact-xs" variant="light" loading={busy} onClick={onTest}>LLM 连通</Button>
        </Group>
      </Group>
      <div className="agent-model-readiness-grid">
        <div>
          <span>主模型</span>
          <strong>{shortText(String(active.model || '-'), 26)}</strong>
          <small>{shortText(String(active.base_url || '-'), 54)}</small>
        </div>
        <div>
          <span>密钥</span>
          <strong>{active.has_api_key ? '已保存' : '未配置'}</strong>
          <small>{String(active.api_key_masked || 'no key')}</small>
        </div>
        <div>
          <span>号池</span>
          <strong>{formatCount(pool.enabled_count)} / {formatCount(pool.count)}</strong>
          <small>key {formatCount(pool.with_key_count)} · model {formatCount(pool.with_model_count)}</small>
        </div>
        <div>
          <span>Prompt</span>
          <strong>{formatCount(readiness?.prompt_budget?.estimated_tokens)} tokens</strong>
          <small>{formatCount(readiness?.prompt_budget?.prompt_chars)} chars</small>
        </div>
      </div>
      <Group gap={6} mt="xs">
        <Badge size="xs" variant="outline" color="teal">pass {formatCount(counts.pass)}</Badge>
        <Badge size="xs" variant="outline" color="yellow">warn {formatCount(counts.warn)}</Badge>
        <Badge size="xs" variant="outline" color="red">fail {formatCount(counts.fail)}</Badge>
      </Group>
      <Stack gap={6} mt="xs">
        {checks.slice(0, 7).map((check) => {
          const itemColor = check.status === 'pass' ? 'teal' : check.status === 'fail' ? 'red' : 'yellow';
          return (
            <button key={String(check.id || check.label)} type="button" className="agent-readiness-row" onClick={() => undefined}>
              <Badge size="xs" variant="light" color={itemColor}>{String(check.status || 'warn')}</Badge>
              <span>
                <strong>{shortText(String(check.label || check.id || '-'), 32)}</strong>
                <small>{shortText(String(check.detail || check.action || ''), 112)}</small>
              </span>
            </button>
          );
        })}
      </Stack>
    </Card>
  );
}

function MultimodalReadinessPanel({
  readiness,
  busy,
  onRefresh,
  onInspect,
}: {
  readiness: AnyRecord | null;
  busy: boolean;
  onRefresh: () => void;
  onInspect: (value: AnyRecord) => void;
}) {
  const status = String(readiness?.overall || 'warn');
  const color = status === 'pass' ? 'teal' : status === 'fail' ? 'red' : 'yellow';
  const cards = asArray<AnyRecord>(readiness?.cards);
  const checks = asArray<AnyRecord>(readiness?.checks);
  const attachments = asArray<AnyRecord>(readiness?.recent_attachments);
  const counts = (readiness?.counts || {}) as AnyRecord;
  const kinds = (counts.kind_counts || {}) as AnyRecord;
  return (
    <div className="agent-multimodal-panel">
      <Group justify="space-between" align="flex-start" gap="xs">
        <div>
          <Group gap={8}>
            <IconPhoto size={16} />
            <Text size="sm" fw={800}>多模态就绪度</Text>
            <Badge variant="light" color={color}>{status}</Badge>
            <Badge variant="outline">{String(readiness?.side_effects || 'read_only')}</Badge>
          </Group>
          <Text size="xs" c="dimmed">
            只读检查附件摘要、视觉模型和预算；只有发送消息才会写入 PA 历史并运行 AP tick。
          </Text>
        </div>
        <Group gap={6}>
          <ActionIcon size="sm" variant="subtle" loading={busy} aria-label="刷新多模态就绪度" onClick={onRefresh}>
            <IconRefresh size={15} />
          </ActionIcon>
          <Button size="compact-xs" variant="subtle" onClick={() => onInspect(readiness || {})}>
            JSON
          </Button>
        </Group>
      </Group>
      {readiness ? (
        <>
          <div className="agent-multimodal-grid">
            {cards.slice(0, 4).map((item) => (
              <button key={String(item.id || item.label)} type="button" onClick={() => onInspect(item)}>
                <span>{String(item.label || item.id || '-')}</span>
                <strong>{shortText(String(item.value || '-'), 34)}</strong>
                <small>{shortText(String(item.detail || ''), 82)}</small>
              </button>
            ))}
          </div>
          <Group gap={6}>
            <Badge size="xs" variant="outline" color="blue">image {formatCount(kinds.image)}</Badge>
            <Badge size="xs" variant="outline" color="gray">file {formatCount(kinds.file)}</Badge>
            <Badge size="xs" variant="outline" color="violet">audio {formatCount(kinds.audio)}</Badge>
            <Badge size="xs" variant="outline" color="orange">video {formatCount(kinds.video)}</Badge>
            <Badge size="xs" variant="outline" color={asNumber(counts.missing_summary, 0) ? 'yellow' : 'teal'}>
              缺摘要 {formatCount(counts.missing_summary)}
            </Badge>
          </Group>
          <Stack gap={6}>
            {checks.slice(0, 5).map((check) => (
              <button key={String(check.id || check.label)} type="button" className="agent-multimodal-check" onClick={() => onInspect(check)}>
                <Badge size="xs" variant="light" color={check.status === 'fail' ? 'red' : check.status === 'warn' ? 'yellow' : 'teal'}>
                  {String(check.status || 'warn')}
                </Badge>
                <span>
                  <strong>{shortText(String(check.label || check.id || '-'), 34)}</strong>
                  <small>{shortText(String(check.detail || ''), 104)}</small>
                </span>
              </button>
            ))}
          </Stack>
          {attachments.length ? (
            <Stack gap={5}>
              {attachments.slice(-4).reverse().map((item, index) => (
                <button key={String(item.id || item.name || index)} type="button" className="agent-multimodal-attachment" onClick={() => onInspect(item)}>
                  <span>
                    <strong>{shortText(String(item.name || item.id || '-'), 38)}</strong>
                    <small>{shortText(String(item.summary_preview || item.mime_type || '无摘要'), 96)}</small>
                  </span>
                  <Badge size="xs" variant="outline" color={item.has_summary ? 'teal' : 'yellow'}>
                    {String(item.kind || 'file')}
                  </Badge>
                </button>
              ))}
            </Stack>
          ) : (
            <div className="empty-box compact">近期 PA 对话历史里还没有附件；可先用下方对话框添加摘要或选择文件预览。</div>
          )}
        </>
      ) : (
        <div className="empty-box compact">刷新后显示多模态策略和附件预算。</div>
      )}
    </div>
  );
}

function PromptContractPanel({
  contract,
  busy,
  onRefresh,
  onInspect,
}: {
  contract: AnyRecord | null;
  busy: boolean;
  onRefresh: () => void;
  onInspect: (value: AnyRecord) => void;
}) {
  const status = String(contract?.overall || 'warn');
  const color = status === 'pass' ? 'teal' : status === 'fail' ? 'red' : 'yellow';
  const cards = asArray<AnyRecord>(contract?.cards);
  const checks = asArray<AnyRecord>(contract?.checks);
  const sections = asArray<AnyRecord>(contract?.sections);
  const budget = (contract?.budget || {}) as AnyRecord;
  const llmPacketChars = asNumber(budget.ap_packet_chars, 0);
  const statusPacketChars = asNumber(budget.status_packet_chars, 0);
  const promptChars = asNumber(budget.prompt_chars, 0);
  const estimatedTokens = asNumber(budget.estimated_tokens, 0);
  const packetReduction = statusPacketChars > 0 && llmPacketChars > 0 ? Math.max(0, 1 - llmPacketChars / statusPacketChars) : null;
  const budgetRows = [
    {
      id: 'llm_compact_packet',
      label: 'LLM 实际 AP 包',
      value: `${formatCount(llmPacketChars)} chars`,
      detail: '真实写入提示词的 compact AP 状态包',
      tone: llmPacketChars > 9000 ? 'warn' : 'safe',
    },
    {
      id: 'status_packet',
      label: '前端诊断包',
      value: `${formatCount(statusPacketChars)} chars`,
      detail: '仅用于页面对象云和诊断展示，不直接喂给 LLM',
      tone: 'watch',
    },
    {
      id: 'full_prompt',
      label: '完整 Prompt',
      value: `${formatCount(estimatedTokens)} tokens`,
      detail: `${formatCount(promptChars)} chars，含人设、近期对话和 compact AP 包`,
      tone: estimatedTokens >= PROMPT_BUDGET_WARN_TOKENS ? 'warn' : 'safe',
    },
    {
      id: 'compression',
      label: '包体压缩',
      value: packetReduction == null ? '-' : formatPercent(packetReduction, 0),
      detail: '相对前端诊断包减少的体积，便于观察上下文成本',
      tone: packetReduction != null && packetReduction >= 0.5 ? 'safe' : 'watch',
    },
  ];
  return (
    <div className="agent-prompt-contract-panel">
      <Group justify="space-between" align="flex-start" gap="xs">
        <div>
          <Group gap={8}>
            <IconBrain size={16} />
            <Text size="sm" fw={800}>AP 注入契约</Text>
            <Badge variant="light" color={color}>{status}</Badge>
            <Badge variant="outline">{String(contract?.side_effects || 'read_only')}</Badge>
          </Group>
          <Text size="xs" c="dimmed">
            解释 AP 信号如何进入 LLM 提示词；不生成 thought，不写事件日志。
          </Text>
        </div>
        <Group gap={6}>
          <ActionIcon size="sm" variant="subtle" loading={busy} aria-label="刷新 AP 注入契约" onClick={onRefresh}>
            <IconRefresh size={15} />
          </ActionIcon>
          <Button size="compact-xs" variant="subtle" onClick={() => onInspect(contract || {})}>
            JSON
          </Button>
        </Group>
      </Group>
      {contract ? (
        <>
          <div className="agent-prompt-contract-grid">
            {cards.slice(0, 6).map((item) => (
              <button key={String(item.id || item.label)} type="button" onClick={() => onInspect(item)}>
                <span>{String(item.label || item.id || '-')}</span>
                <strong>{shortText(String(item.value ?? '-'), 36)}</strong>
                <small>{shortText(String(item.effect || item.detail || ''), 92)}</small>
              </button>
            ))}
          </div>
          <div className="agent-prompt-budget-split">
            {budgetRows.map((item) => (
              <button key={item.id} type="button" onClick={() => onInspect({ ...item, budget })}>
                <Badge size="xs" variant="light" color={item.tone === 'safe' ? 'teal' : item.tone === 'warn' ? 'red' : 'yellow'}>
                  {item.tone}
                </Badge>
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.value}</small>
                  <small>{item.detail}</small>
                </span>
              </button>
            ))}
          </div>
          <Stack gap={6}>
            {sections.slice(0, 4).map((item) => (
              <button key={String(item.id || item.label)} type="button" className="agent-prompt-contract-section" onClick={() => onInspect(item)}>
                <Badge size="xs" variant="light" color={item.included ? 'teal' : 'gray'}>
                  {item.included ? 'in' : 'out'}
                </Badge>
                <span>
                  <strong>{shortText(String(item.label || item.id || '-'), 36)}</strong>
                  <small>{shortText(String(item.meaning || item.evidence || ''), 108)}</small>
                </span>
              </button>
            ))}
          </Stack>
          <Group gap={6}>
            {checks.slice(0, 4).map((item) => (
              <Badge key={String(item.id)} size="xs" variant="outline" color={item.status === 'fail' ? 'red' : item.status === 'warn' ? 'yellow' : 'teal'}>
                {String(item.label || item.id)}:{String(item.status)}
              </Badge>
            ))}
          </Group>
        </>
      ) : (
        <div className="empty-box compact">刷新后显示 AP 到 LLM 的注入契约。</div>
      )}
    </div>
  );
}

function ActivationRoadmapPanel({
  roadmap,
  busy,
  onRefresh,
  onInspect,
}: {
  roadmap: AnyRecord | null;
  busy: boolean;
  onRefresh: () => void;
  onInspect: (value: AnyRecord) => void;
}) {
  const overall = String(roadmap?.overall || 'guided');
  const color = overall === 'ready' ? 'teal' : overall === 'blocked' ? 'red' : 'yellow';
  const stages = asArray<AnyRecord>(roadmap?.stages);
  const actions = asArray<AnyRecord>(roadmap?.priority_actions);
  const state = (roadmap?.current_state || {}) as AnyRecord;
  return (
    <Card className="agent-activation-roadmap-card" mb="md">
      <Group justify="space-between" align="flex-start" gap="md">
        <div className="agent-activation-roadmap-head">
          <Group gap={8} mb={4}>
            <IconSparkles size={18} />
            <Text fw={900}>激活路线图</Text>
            <Badge variant="light" color={color}>{String(roadmap?.label || overall)}</Badge>
            <Badge variant="outline">{String(roadmap?.side_effects || 'read_only')}</Badge>
          </Group>
          <Text size="xs" c="dimmed">
            {String(roadmap?.headline || '只读整理从安全验收到真实测试的下一步顺序。')}
          </Text>
        </div>
        <Group gap={6} wrap="wrap">
          <Button size="xs" variant="light" loading={busy} onClick={onRefresh}>
            刷新路线
          </Button>
          <Button size="xs" variant="subtle" onClick={() => onInspect(roadmap || {})}>
            JSON
          </Button>
        </Group>
      </Group>
      {roadmap ? (
        <>
          <Group gap={6} mt="xs">
            <Badge size="xs" variant="outline" color={state.runtime_empty ? 'yellow' : 'teal'}>AP {state.runtime_empty ? '空态' : `tick ${formatCount(state.tick_counter)}`}</Badge>
            <Badge size="xs" variant="outline" color={state.model_ready ? 'teal' : 'yellow'}>{state.model_ready ? 'model ready' : 'fallback'}</Badge>
            <Badge size="xs" variant="outline" color={state.adapter_live ? 'red' : 'teal'}>{state.adapter_live ? 'adapter live' : 'adapter safe'}</Badge>
            <Badge size="xs" variant="outline" color={state.background_running ? 'yellow' : 'teal'}>{state.background_running ? 'background on' : 'background off'}</Badge>
          </Group>
          <div className="agent-activation-roadmap-grid">
            {stages.map((stage) => (
              <button key={String(stage.id || stage.label)} type="button" className="agent-activation-roadmap-step" onClick={() => onInspect(stage)}>
                <Group justify="space-between" gap={6} wrap="nowrap">
                  <Badge size="xs" variant="light" color={stage.tone === 'danger' ? 'red' : stage.tone === 'safe' ? 'teal' : 'yellow'}>
                    {String(stage.status || 'watch')}
                  </Badge>
                  {stage.writes_state ? <Badge size="xs" variant="outline" color="gray">write</Badge> : null}
                </Group>
                <strong>{shortText(String(stage.label || '-'), 34)}</strong>
                <small>{shortText(String(stage.detail || stage.recommended_action || ''), 92)}</small>
              </button>
            ))}
          </div>
          <div className="agent-activation-action-row">
            {actions.slice(0, 5).map((item) => (
              <button key={String(item.id || item.label)} type="button" onClick={() => onInspect(item)}>
                <strong>{shortText(String(item.label || item.id || '-'), 28)}</strong>
                <small>{shortText(String(item.detail || item.kind || ''), 86)}</small>
              </button>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-box compact">刷新后显示从本地安全验收到真实测试的路线。</div>
      )}
    </Card>
  );
}

function ThoughtContinuityPanel({
  report,
  busy,
  onRefresh,
  onInspect,
}: {
  report: AnyRecord | null;
  busy: boolean;
  onRefresh: () => void;
  onInspect: (value: AnyRecord) => void;
}) {
  const overall = String(report?.overall || 'warn');
  const color = overall === 'pass' ? 'teal' : overall === 'fail' ? 'red' : 'yellow';
  const scores = (report?.scores || {}) as AnyRecord;
  const counts = (report?.counts || {}) as AnyRecord;
  const checks = asArray<AnyRecord>(report?.checks);
  const rows = asArray<AnyRecord>(report?.rows);
  const decisions = (report?.decision_counts || {}) as AnyRecord;
  const modes = (report?.mode_counts || {}) as AnyRecord;
  const scoreItems = [
    { label: '质量', value: formatPercent(scores.overall_quality, 0), detail: 'overall' },
    { label: '连续', value: formatPercent(scores.continuity, 0), detail: 'thought flow' },
    { label: 'AP 承载', value: formatPercent(scores.grounded_ratio, 0), detail: `avg signal ${formatNumber(scores.ap_signal_avg, 2)}` },
    { label: '重复', value: formatPercent(scores.duplicate_ratio, 0), detail: `${formatCount(counts.duplicate_pairs)} pairs` },
    { label: 'Fallback', value: formatPercent(scores.fallback_ratio, 0), detail: `${formatCount(counts.fallback)} thoughts` },
    { label: 'Reply', value: formatPercent(scores.reply_ratio, 0), detail: `${formatCount(decisions.reply || 0)} replies` },
  ];
  return (
    <div className="agent-thought-continuity-panel">
      <Group justify="space-between" align="flex-start" gap="xs">
        <div>
          <Group gap={8}>
            <IconClipboardList size={16} />
            <Text size="sm" fw={900}>连续性体检</Text>
            <Badge variant="light" color={color}>{String(report?.label || overall)}</Badge>
            <Badge variant="outline">{String(report?.side_effects || 'read_only')}</Badge>
          </Group>
          <Text size="xs" c="dimmed">
            只读分析最近 thought 的连续性、重复度、AP grounding、行动判断和 fallback 占比。
          </Text>
        </div>
        <Group gap={6}>
          <Button size="xs" variant="light" loading={busy} onClick={onRefresh}>
            体检
          </Button>
          <Button size="xs" variant="subtle" onClick={() => onInspect(report || {})}>
            JSON
          </Button>
        </Group>
      </Group>
      {report ? (
        <>
          <div className="agent-thought-continuity-grid">
            {scoreItems.map((item) => (
              <button key={item.label} type="button" onClick={() => onInspect({ ...item, scores, counts })}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <small>{item.detail}</small>
              </button>
            ))}
          </div>
          <div className="agent-thought-continuity-checks">
            {checks.slice(0, 8).map((check) => (
              <button key={String(check.id || check.label)} type="button" onClick={() => onInspect(check)}>
                <Badge size="xs" variant="light" color={check.status === 'pass' ? 'teal' : check.status === 'fail' ? 'red' : 'yellow'}>
                  {String(check.status || 'warn')}
                </Badge>
                <span>
                  <strong>{shortText(String(check.label || check.id || '-'), 26)}</strong>
                  <small>{shortText(String(check.detail || ''), 92)}</small>
                </span>
              </button>
            ))}
          </div>
          <Group gap={6}>
            {Object.entries(decisions).slice(0, 5).map(([key, value]) => (
              <Badge key={key} size="xs" variant="outline">{key}:{formatCount(value)}</Badge>
            ))}
            {Object.entries(modes).slice(0, 4).map(([key, value]) => (
              <Badge key={key} size="xs" variant="outline">{key}:{formatCount(value)}</Badge>
            ))}
          </Group>
          {rows.length ? (
            <div className="agent-thought-continuity-strip">
              {rows.slice(-6).map((row) => (
                <button key={String(row.id)} type="button" onClick={() => onInspect(row)}>
                  <strong>{String(row.decision || '-')} · {formatPercent(row.quality?.overall, 0)}</strong>
                  <small>{shortText(String(row.text_preview || ''), 82)}</small>
                </button>
              ))}
            </div>
          ) : null}
        </>
      ) : (
        <div className="empty-box compact">点击“体检”读取最近 thought 的连续性诊断。</div>
      )}
    </div>
  );
}

function CognitiveTimelinePanel({
  timeline,
  dark,
  busy,
  onRefresh,
  onInspect,
}: {
  timeline: AnyRecord | null;
  dark: boolean;
  busy: boolean;
  onRefresh: () => void;
  onInspect: (value: AnyRecord) => void;
}) {
  const overall = String(timeline?.overall || 'warn');
  const color = overall === 'pass' ? 'teal' : overall === 'fail' ? 'red' : 'yellow';
  const events = asArray<AnyRecord>(timeline?.events);
  const energyRows = events.filter((item) => item.kind === 'snapshot' || asNumber(item.er, 0) || asNumber(item.ev, 0) || asNumber(item.cp, 0));
  const thoughtRows = events.filter((item) => item.kind === 'thought');
  const counts = (timeline?.counts || {}) as AnyRecord;
  const ranges = (timeline?.ranges || {}) as AnyRecord;
  const decisions = (timeline?.decision_counts || {}) as AnyRecord;
  const textColor = dark ? 'rgba(235, 250, 247, .78)' : 'rgba(25, 45, 52, .76)';
  const lineColor = dark ? 'rgba(255,255,255,.12)' : 'rgba(18, 52, 62, .12)';
  const labels = energyRows.map((item, index) => `${item.tick_counter ?? index}`);
  const energyOption = {
    backgroundColor: 'transparent',
    color: ['#4dabf7', '#b197fc', '#ffd43b', '#20c997'],
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: textColor } },
    grid: { left: 42, right: 14, top: 42, bottom: 24 },
    xAxis: { type: 'category', boundaryGap: false, data: labels, axisLabel: { color: textColor }, axisLine: { lineStyle: { color: lineColor } } },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: lineColor } }, axisLabel: { color: textColor } },
    series: [
      { name: 'ER', type: 'line', smooth: true, showSymbol: energyRows.length < 36, data: energyRows.map((item) => asNumber(item.er, 0)) },
      { name: 'EV', type: 'line', smooth: true, showSymbol: energyRows.length < 36, data: energyRows.map((item) => asNumber(item.ev, 0)) },
      { name: 'CP', type: 'line', smooth: true, showSymbol: energyRows.length < 36, data: energyRows.map((item) => asNumber(item.cp, 0)) },
      { name: '对象', type: 'bar', yAxisIndex: 0, opacity: 0.22, data: energyRows.map((item) => asNumber(item.active_item_count, 0)) },
    ],
  };
  const qualityOption = {
    backgroundColor: 'transparent',
    color: ['#20c997', '#4dabf7', '#f783ac'],
    tooltip: { trigger: 'axis' },
    legend: { top: 0, textStyle: { color: textColor } },
    grid: { left: 34, right: 14, top: 42, bottom: 24 },
    xAxis: { type: 'category', data: thoughtRows.map((item, index) => `${item.index ?? index + 1}`), axisLabel: { color: textColor }, axisLine: { lineStyle: { color: lineColor } } },
    yAxis: { type: 'value', min: 0, max: 1, splitLine: { lineStyle: { color: lineColor } }, axisLabel: { color: textColor, formatter: (value: number) => `${Math.round(value * 100)}` } },
    series: [
      { name: 'Q', type: 'line', smooth: true, data: thoughtRows.map((item) => item.quality ?? null) },
      { name: '连续', type: 'line', smooth: true, data: thoughtRows.map((item) => item.continuity ?? null) },
      { name: 'AP', type: 'line', smooth: true, data: thoughtRows.map((item) => item.ap_usage ?? null) },
    ],
  };
  return (
    <div className="agent-cognitive-timeline-panel">
      <Group justify="space-between" align="flex-start" gap="xs">
        <div>
          <Group gap={8}>
            <IconBrain size={16} />
            <Text size="sm" fw={900}>认知时间线</Text>
            <Badge variant="light" color={color}>{String(timeline?.label || overall)}</Badge>
            <Badge variant="outline">{String(timeline?.side_effects || 'read_only')}</Badge>
          </Group>
          <Text size="xs" c="dimmed">
            把 AP 能量快照、对象数、thought 质量和行动判断放在同一条历史线上。
          </Text>
        </div>
        <Group gap={6}>
          <Button size="xs" variant="light" loading={busy} onClick={onRefresh}>
            刷新时间线
          </Button>
          <Button size="xs" variant="subtle" onClick={() => onInspect(timeline || {})}>
            JSON
          </Button>
        </Group>
      </Group>
      {timeline ? (
        <>
          <div className="agent-cognitive-timeline-kpis">
            <button type="button" onClick={() => onInspect(counts)}><span>events</span><strong>{formatCount(counts.events)}</strong><small>snap {formatCount(counts.snapshots)} / thought {formatCount(counts.thoughts)}</small></button>
            <button type="button" onClick={() => onInspect(ranges.cp || {})}><span>CP</span><strong>{formatNumber(ranges.cp?.avg, 2)}</strong><small>{formatNumber(ranges.cp?.min, 1)} - {formatNumber(ranges.cp?.max, 1)}</small></button>
            <button type="button" onClick={() => onInspect(ranges.quality || {})}><span>quality</span><strong>{formatPercent(ranges.quality?.avg, 0)}</strong><small>{formatCount(counts.quality_points)} points</small></button>
            <button type="button" onClick={() => onInspect(decisions)}><span>decision</span><strong>{Object.keys(decisions).length}</strong><small>{Object.entries(decisions).slice(0, 3).map(([key, value]) => `${key}:${formatCount(value)}`).join(' / ') || '-'}</small></button>
          </div>
          {energyRows.length ? <ReactECharts option={energyOption} style={{ height: 190 }} notMerge lazyUpdate /> : <div className="empty-chart">等待 AP 能量快照。</div>}
          {thoughtRows.length ? <ReactECharts option={qualityOption} style={{ height: 170 }} notMerge lazyUpdate /> : <div className="empty-chart">等待 thought 质量点。</div>}
          <div className="agent-cognitive-timeline-events">
            {events.slice(-6).map((item) => (
              <button key={`${item.kind}_${item.id || item.created_at_ms}`} type="button" onClick={() => onInspect(item)}>
                <Badge size="xs" variant="light" color={item.kind === 'thought' ? 'teal' : 'blue'}>{String(item.kind || '-')}</Badge>
                <span>
                  <strong>{shortText(String(item.kind === 'thought' ? item.text_preview || item.decision : item.mood_hint || item.label || '-'), 72)}</strong>
                  <small>tick {formatCount(item.tick_counter)} · CP {formatNumber(item.cp, 2)} {item.decision ? `· ${item.decision}` : ''}</small>
                </span>
              </button>
            ))}
          </div>
        </>
      ) : (
        <div className="empty-box compact">点击“刷新时间线”读取 AP/PA 历史曲线。</div>
      )}
    </div>
  );
}

function ReplyActionAuditPanel({
  audit,
  debtPreview,
  busy,
  onRefresh,
  onDebtPreview,
  onInspect,
}: {
  audit: AnyRecord | null;
  debtPreview: AnyRecord | null;
  busy: boolean;
  onRefresh: () => void;
  onDebtPreview: () => void;
  onInspect: (value: AnyRecord) => void;
}) {
  const overall = String(audit?.overall || 'warn');
  const color = overall === 'pass' ? 'teal' : overall === 'fail' ? 'red' : 'yellow';
  const counts = (audit?.counts || {}) as AnyRecord;
  const scores = (audit?.scores || {}) as AnyRecord;
  const latestReply = (audit?.latest_reply || {}) as AnyRecord;
  const currentWindow = (audit?.current_window || {}) as AnyRecord;
  const historyDebt = (audit?.history_debt || {}) as AnyRecord;
  const checks = asArray<AnyRecord>(audit?.checks);
  const rows = asArray<AnyRecord>(audit?.rows);
  const duplicates = asArray<AnyRecord>(audit?.duplicate_groups);
  const rawLeaks = asArray<AnyRecord>(audit?.raw_leak_rows);
  const debtCounts = (debtPreview?.counts || {}) as AnyRecord;
  const debtCandidateCount = debtCounts.candidates ?? debtCounts.candidate_count;
  const debtCandidates = asArray<AnyRecord>(debtPreview?.candidates);
  const kpis = [
    { label: '最新', value: String(latestReply.status || '-'), detail: asArray<string>(latestReply.issues).length ? asArray<string>(latestReply.issues).join(', ') : 'clean' },
    { label: '最近', value: String(currentWindow.status || '-'), detail: `raw ${formatCount(currentWindow.raw_leak_count)} / dup ${formatCount(currentWindow.duplicate_count)}` },
    { label: '历史债务', value: formatCount(historyDebt.old_problem_reply_count), detail: String(historyDebt.status || '-') },
    { label: '回复', value: formatCount(counts.assistant_replies), detail: `turns ${formatCount(counts.turns)}` },
    { label: '重复', value: formatPercent(scores.duplicate_ratio, 0), detail: `${formatCount(counts.duplicate_group_count)} groups` },
    { label: '唯一', value: formatPercent(scores.unique_ratio, 0), detail: `${formatCount(counts.unique_reply_count)} texts` },
    { label: '泄露', value: formatCount(counts.raw_leak_reply_count), detail: 'raw AP' },
    { label: '平均长度', value: formatCount(scores.avg_reply_chars), detail: 'chars' },
    { label: '缺失', value: formatCount(counts.missing_reply_turns), detail: 'decision reply' },
    { label: '外发', value: formatCount(counts.outbox_live_ok), detail: `${formatCount(counts.outbox_dry_run)} dry-run` },
  ];
  return (
    <div className="agent-reply-audit-panel">
      <Group justify="space-between" align="flex-start" gap="xs">
        <div>
          <Group gap={8}>
            <IconMessageCircle size={16} />
            <Text size="sm" fw={900}>回复行动审计</Text>
            <Badge variant="light" color={color}>{String(audit?.label || overall)}</Badge>
            <Badge variant="outline">{String(audit?.side_effects || 'read_only')}</Badge>
          </Group>
          <Text size="xs" c="dimmed">
            只读检查 decision→reply、回复重复、原始 AP 片段泄露、auto_reply 和 NapCat 外发安全。
          </Text>
        </div>
        <Group gap={6}>
          <Button size="xs" variant="light" loading={busy} onClick={onRefresh}>
            审计
          </Button>
          <Button size="xs" variant="outline" loading={busy} onClick={onDebtPreview}>
            债务预览
          </Button>
          <Button size="xs" variant="subtle" onClick={() => onInspect(audit || {})}>
            JSON
          </Button>
        </Group>
      </Group>
      {audit ? (
        <>
          <div className="agent-reply-audit-grid">
            {kpis.map((item) => (
              <button key={item.label} type="button" onClick={() => onInspect({ ...item, counts, scores })}>
                <span>{item.label}</span>
                <strong>{item.value}</strong>
                <small>{item.detail}</small>
              </button>
            ))}
          </div>
          {audit.latest_reply || audit.current_window || audit.history_debt ? (
            <div className="agent-reply-audit-health">
              <button type="button" onClick={() => onInspect(latestReply)}>
                <Badge size="xs" variant="light" color={latestReply.status === 'pass' ? 'teal' : latestReply.status === 'fail' ? 'red' : 'yellow'}>latest</Badge>
                <span>
                  <strong>{String(latestReply.status || '-')}</strong>
                  <small>{asArray<string>(latestReply.issues).length ? asArray<string>(latestReply.issues).join(' / ') : '最新回复未发现重复、泄露或行动错配。'}</small>
                </span>
              </button>
              <button type="button" onClick={() => onInspect(currentWindow)}>
                <Badge size="xs" variant="light" color={currentWindow.status === 'pass' ? 'teal' : currentWindow.status === 'fail' ? 'red' : 'yellow'}>window</Badge>
                <span>
                  <strong>last {formatCount(currentWindow.size)}</strong>
                  <small>raw {formatCount(currentWindow.raw_leak_count)} · duplicate {formatCount(currentWindow.duplicate_count)}</small>
                </span>
              </button>
              <button type="button" onClick={() => onInspect(historyDebt)}>
                <Badge size="xs" variant="light" color={historyDebt.status === 'pass' ? 'teal' : 'yellow'}>debt</Badge>
                <span>
                  <strong>{formatCount(historyDebt.old_problem_reply_count)} 条历史债务</strong>
                  <small>{shortText(String(historyDebt.detail || ''), 96)}</small>
                </span>
              </button>
            </div>
          ) : null}
          <div className="agent-reply-audit-checks">
            {checks.slice(0, 8).map((check) => (
              <button key={String(check.id || check.label)} type="button" onClick={() => onInspect(check)}>
                <Badge size="xs" variant="light" color={check.status === 'pass' ? 'teal' : check.status === 'fail' ? 'red' : 'yellow'}>{String(check.status || 'warn')}</Badge>
                <span>
                  <strong>{shortText(String(check.label || check.id || '-'), 26)}</strong>
                  <small>{shortText(String(check.detail || ''), 96)}</small>
                </span>
              </button>
            ))}
          </div>
          {duplicates.length ? (
            <div className="agent-reply-audit-duplicates">
              {duplicates.slice(0, 3).map((item, index) => (
                <button key={`${index}_${item.count}`} type="button" onClick={() => onInspect(item)}>
                  <Badge size="xs" variant="light" color="yellow">x{formatCount(item.count)}</Badge>
                  <span>{shortText(String(item.text_preview || ''), 116)}</span>
                </button>
              ))}
            </div>
          ) : null}
          {rawLeaks.length ? (
            <div className="agent-reply-audit-leaks">
              {rawLeaks.slice(0, 3).map((item, index) => (
                <button key={`${index}_${String(item.id || item.turn_id)}`} type="button" onClick={() => onInspect(item)}>
                  <Badge size="xs" variant="light" color="red">raw</Badge>
                  <span>
                    <strong>{shortText(String(item.source || item.turn_id || '-'), 28)}</strong>
                    <small>{shortText(`tokens: ${asArray<string>(item.raw_leak_tokens).join(' / ') || '-'}`, 84)}</small>
                    <small>{shortText(String(item.text_preview || ''), 112)}</small>
                  </span>
                </button>
              ))}
            </div>
          ) : null}
          {debtPreview ? (
            <div className="agent-reply-debt-preview">
              <Group justify="space-between" gap="xs">
                <Group gap={6}>
                  <Badge size="xs" variant="light" color={String(debtPreview.overall) === 'pass' ? 'teal' : 'yellow'}>
                    {String(debtPreview.label || '历史债务修复预览')}
                  </Badge>
                  <Badge size="xs" variant="outline">{String(debtPreview.side_effects || 'read_only')}</Badge>
                </Group>
                <Button size="compact-xs" variant="subtle" onClick={() => onInspect(debtPreview)}>
                  JSON
                </Button>
              </Group>
              <Text size="xs" c="dimmed">
                只读候选，不改写 PA 历史；用于确认旧模板/修复前探针若按当前回复器重放，会不会继续泄露原始 AP 片段。
              </Text>
              <div className="agent-reply-debt-grid">
                {[
                  { label: '候选', value: debtCandidateCount, detail: 'problem rows' },
                  { label: '通过', value: debtCounts.pass, detail: 'candidate clean' },
                  { label: '警告', value: debtCounts.warn, detail: 'needs review' },
                  { label: '历史债务', value: debtCounts.history_debt, detail: 'audit debt' },
                ].map((item) => (
                  <button key={item.label} type="button" onClick={() => onInspect({ ...item, debtCounts })}>
                    <span>{item.label}</span>
                    <strong>{formatCount(item.value)}</strong>
                    <small>{item.detail}</small>
                  </button>
                ))}
              </div>
              {debtCandidates.length ? (
                <div className="agent-reply-debt-candidates">
                  {debtCandidates.slice(0, 4).map((item, index) => (
                    <button key={`${index}_${String(item.turn_id || item.message_id || '')}`} type="button" onClick={() => onInspect(item)}>
                      <Badge size="xs" variant="light" color={item.candidate_status === 'pass' ? 'teal' : 'yellow'}>
                        {String(item.candidate_status || 'warn')}
                      </Badge>
                      <span>
                        <strong>{shortText(String(item.turn_id || item.message_id || '候选回复'), 30)}</strong>
                        <small>原文：{shortText(String(item.original_preview || ''), 86)}</small>
                        <small>候选：{shortText(String(item.candidate_reply || ''), 112)}</small>
                      </span>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="empty-box compact">当前窗口没有需要预览的历史债务候选。</div>
              )}
            </div>
          ) : null}
          {rows.length ? (
            <div className="agent-reply-audit-rows">
              {rows.slice(-4).map((row) => (
                <button key={String(row.id)} type="button" onClick={() => onInspect(row)}>
                  <strong>{shortText(String(row.source || row.turn_decision || '-'), 24)} · dup {formatCount(row.duplicate_count)}{row.raw_leak ? ' · raw' : ''}</strong>
                  <small>{shortText(String(row.text_preview || ''), 90)}</small>
                </button>
              ))}
            </div>
          ) : null}
        </>
      ) : (
        <div className="empty-box compact">点击“审计”检查回复行动与外发安全。</div>
      )}
    </div>
  );
}

function ModelPoolPanel({
  models,
  draft,
  slotDraft,
  setSlotDraft,
  onSave,
  onApply,
  onEdit,
  onDelete,
  busy,
}: {
  models: AnyRecord[];
  draft: AgentConfig;
  slotDraft: AnyRecord;
  setSlotDraft: (fn: (prev: AnyRecord) => AnyRecord) => void;
  onSave: () => void;
  onApply: (index: number) => void;
  onEdit: (slot: AnyRecord) => void;
  onDelete: (index: number) => void;
  busy: boolean;
}) {
  return (
    <div className="agent-model-pool-panel">
      <Group justify="space-between" mb="xs">
        <Text fw={800} size="sm">模型号池</Text>
        <Badge variant="light">{models.length} slots</Badge>
      </Group>
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing={6}>
        <TextInput size="xs" label="名称" value={String(slotDraft.name || '')} onChange={(event) => setSlotDraft((prev) => ({ ...prev, name: event.currentTarget.value }))} />
        <TextInput size="xs" label="Base URL" value={String(slotDraft.base_url || draft.base_url || '')} onChange={(event) => setSlotDraft((prev) => ({ ...prev, base_url: event.currentTarget.value }))} />
        <TextInput size="xs" label="主模型" value={String(slotDraft.model || '')} onChange={(event) => setSlotDraft((prev) => ({ ...prev, model: event.currentTarget.value }))} />
        <PasswordInput size="xs" label="API Key" placeholder="留空保留原 slot 密钥" value={String(slotDraft.api_key || '')} onChange={(event) => setSlotDraft((prev) => ({ ...prev, api_key: event.currentTarget.value }))} />
        <TextInput size="xs" label="视觉模型" value={String(slotDraft.vision_model || '')} onChange={(event) => setSlotDraft((prev) => ({ ...prev, vision_model: event.currentTarget.value }))} />
        <PasswordInput size="xs" label="视觉 API Key" placeholder="留空复用主 slot 密钥 / 保留原密钥" value={String(slotDraft.vision_api_key || '')} onChange={(event) => setSlotDraft((prev) => ({ ...prev, vision_api_key: event.currentTarget.value }))} />
        <TextInput size="xs" label="多模态模型" value={String(slotDraft.multimodal_model || '')} onChange={(event) => setSlotDraft((prev) => ({ ...prev, multimodal_model: event.currentTarget.value }))} />
        <PasswordInput size="xs" label="多模态 API Key" placeholder="留空复用主 slot 密钥 / 保留原密钥" value={String(slotDraft.multimodal_api_key || '')} onChange={(event) => setSlotDraft((prev) => ({ ...prev, multimodal_api_key: event.currentTarget.value }))} />
        <TextInput size="xs" label="绘图模型" value={String(slotDraft.image_generation_model || '')} onChange={(event) => setSlotDraft((prev) => ({ ...prev, image_generation_model: event.currentTarget.value }))} />
        <PasswordInput size="xs" label="绘图 API Key" placeholder="留空复用主 slot 密钥 / 保留原密钥" value={String(slotDraft.image_generation_api_key || '')} onChange={(event) => setSlotDraft((prev) => ({ ...prev, image_generation_api_key: event.currentTarget.value }))} />
        <NumberInput size="xs" label="temperature" value={slotDraft.temperature === '' ? '' : Number(slotDraft.temperature ?? draft.temperature ?? 0.72)} min={0} max={2} step={0.05} onChange={(value) => setSlotDraft((prev) => ({ ...prev, temperature: value === '' ? '' : Number(value) || 0 }))} />
        <NumberInput size="xs" label="max tokens" value={slotDraft.max_completion_tokens === '' ? '' : Number(slotDraft.max_completion_tokens ?? draft.max_completion_tokens ?? 5000)} min={256} max={12000} step={128} onChange={(value) => setSlotDraft((prev) => ({ ...prev, max_completion_tokens: value === '' ? '' : Number(value) || 5000 }))} />
      </SimpleGrid>
      <Textarea mt={6} size="xs" minRows={2} autosize placeholder="备注：用途、限速、模型特点" value={String(slotDraft.note || '')} onChange={(event) => setSlotDraft((prev) => ({ ...prev, note: event.currentTarget.value }))} />
      <Group justify="space-between" mt="xs">
        <Switch size="xs" label="启用 slot" checked={slotDraft.enabled !== false} onChange={(event) => setSlotDraft((prev) => ({ ...prev, enabled: event.currentTarget.checked }))} />
        <Group gap={6}>
          <Button size="xs" variant="subtle" onClick={() => setSlotDraft(() => ({ name: '', base_url: draft.base_url || 'https://api.openai.com', model: '', vision_model: '', multimodal_model: '', image_generation_model: '', api_key: '', vision_api_key: '', multimodal_api_key: '', image_generation_api_key: '', enabled: true, note: '', index: '' }))}>
            新建
          </Button>
          <Button size="xs" variant="light" leftSection={<IconDeviceFloppy size={14} />} loading={busy} onClick={onSave}>
            保存 slot
          </Button>
        </Group>
      </Group>
      {models.length ? (
        <Stack gap={6} mt="sm">
          {models.slice(0, 6).map((slot) => (
            <div key={`${slot.index}-${slot.model}`} className="agent-model-slot-row">
              <button type="button" onClick={() => onApply(Number(slot.index) || 0)} disabled={slot.enabled === false || busy}>
                <span>
                  <strong>{shortText(String(slot.name || slot.model || `slot ${slot.index}`), 36)}</strong>
                  <small>{shortText(`${slot.model || '-'} @ ${slot.base_url || '-'}`, 92)}</small>
                  <em>{shortText(`${slot.vision_model || 'vision -'} / ${slot.multimodal_model || 'multi -'} / ${slot.image_generation_model || 'image -'} / ${slot.api_key_masked || 'no key'}`, 120)}</em>
                </span>
                <Badge variant="outline" color={slot.enabled === false ? 'gray' : slot.model === draft.model ? 'teal' : 'blue'}>
                  {slot.model === draft.model ? 'active' : 'slot'}
                </Badge>
              </button>
              <ActionIcon variant="subtle" aria-label="编辑模型 slot" disabled={busy} onClick={() => onEdit(slot)}>
                <IconHammer size={15} />
              </ActionIcon>
              <ActionIcon variant="subtle" color="red" aria-label="删除模型 slot" disabled={busy} onClick={() => onDelete(Number(slot.index) || 0)}>
                <IconEraser size={15} />
              </ActionIcon>
            </div>
          ))}
        </Stack>
      ) : (
        <div className="empty-box compact">还没有模型号池。可以先保存一个主模型 slot，再用“应用”快速切换。</div>
      )}
    </div>
  );
}

function ModelExportPreviewPanel({
  preview,
  busy,
  onRefresh,
  onInspect,
}: {
  preview: AnyRecord | null;
  busy: boolean;
  onRefresh: () => void;
  onInspect: (value: AnyRecord) => void;
}) {
  const active = (preview?.active || {}) as AnyRecord;
  const slots = asArray<AnyRecord>(preview?.model_slots);
  const checklist = asArray<AnyRecord>(preview?.checklist);
  const status = String(preview?.overall || 'warn');
  const color = status === 'pass' ? 'teal' : status === 'fail' ? 'red' : 'yellow';
  return (
    <div className="agent-model-export-panel">
      <Group justify="space-between" align="flex-start" gap="xs">
        <div>
          <Group gap={8}>
            <IconFile size={16} />
            <Text size="sm" fw={800}>模型配置迁移预检</Text>
            <Badge variant="light" color={color}>{status}</Badge>
            <Badge variant="outline">{String(preview?.side_effects || 'read_only')}</Badge>
          </Group>
          <Text size="xs" c="dimmed">
            只读生成 redacted export preview；不含明文 API Key，不写文件，不切换模型。
          </Text>
        </div>
        <Group gap={6}>
          <ActionIcon size="sm" variant="subtle" loading={busy} aria-label="刷新模型配置迁移预检" onClick={onRefresh}>
            <IconRefresh size={15} />
          </ActionIcon>
          <Button size="compact-xs" variant="subtle" onClick={() => onInspect(preview || {})}>
            JSON
          </Button>
        </Group>
      </Group>
      {preview ? (
        <>
          <div className="agent-model-export-grid">
            <button type="button" onClick={() => onInspect(active)}>
              <span>主配置</span>
              <strong>{shortText(String(active.model || '-'), 32)}</strong>
              <small>{active.has_api_key ? String(active.api_key_masked || 'key saved') : 'no key'} · {active.ready_to_call ? 'ready' : 'fallback'}</small>
            </button>
            <button type="button" onClick={() => onInspect(preview.pool_summary || {})}>
              <span>号池</span>
              <strong>{formatCount(preview.pool_summary?.enabled_count)} / {formatCount(preview.pool_summary?.count)}</strong>
              <small>with key {formatCount(preview.pool_summary?.with_key_count)} · profiles {formatCount(preview.profile_count)}</small>
            </button>
            <button type="button" onClick={() => onInspect(preview.export_preview || {})}>
              <span>导出预览</span>
              <strong>{preview.export_preview?.redacted ? 'redacted' : 'raw'}</strong>
              <small>{String(preview.export_preview?.kind || 'preview')}</small>
            </button>
          </div>
          {slots.length ? (
            <Stack gap={5} mt={8}>
              {slots.slice(0, 4).map((slot) => (
                <button key={String(slot.index)} type="button" className="agent-model-export-slot" onClick={() => onInspect(slot)}>
                  <span>
                    <strong>{shortText(String(slot.name || slot.model || `slot ${slot.index}`), 34)}</strong>
                    <small>{shortText(`${slot.model || '-'} @ ${slot.base_url || '-'}`, 82)}</small>
                  </span>
                  <Badge size="xs" variant="light" color={slot.ready_to_call ? 'teal' : slot.portable_without_secret ? 'yellow' : 'gray'}>
                    {slot.ready_to_call ? 'ready' : slot.portable_without_secret ? 'portable' : 'draft'}
                  </Badge>
                </button>
              ))}
            </Stack>
          ) : null}
          <Group gap={6} mt={8}>
            {checklist.slice(0, 5).map((item) => (
              <Badge key={String(item.id)} size="xs" variant="outline" color={item.status === 'fail' ? 'red' : item.status === 'warn' ? 'yellow' : 'teal'}>
                {String(item.label || item.id)}:{String(item.status)}
              </Badge>
            ))}
          </Group>
        </>
      ) : (
        <div className="empty-box compact">刷新后显示迁移预检。</div>
      )}
    </div>
  );
}

export function AgentPage({ onStatusChange }: AgentPageProps) {
  const { colorScheme } = useMantineColorScheme();
  const dark = colorScheme !== 'light';
  const initialUiPrefsRef = useRef<AgentUiPrefs | null>(null);
  if (!initialUiPrefsRef.current) {
    initialUiPrefsRef.current = readAgentUiPrefs();
  }
  const initialUiPrefs = initialUiPrefsRef.current;
  const [status, setStatus] = useState<AnyRecord | null>(null);
  const [diagnostics, setDiagnostics] = useState<AnyRecord | null>(null);
  const [readiness, setReadiness] = useState<AnyRecord | null>(null);
  const [acceptance, setAcceptance] = useState<AnyRecord | null>(null);
  const [safetyRadar, setSafetyRadar] = useState<AnyRecord | null>(null);
  const [logPlan, setLogPlan] = useState<AnyRecord | null>(null);
  const [handoff, setHandoff] = useState<AnyRecord | null>(null);
  const [morningBrief, setMorningBrief] = useState<AnyRecord | null>(null);
  const [morningReview, setMorningReview] = useState<AnyRecord | null>(null);
  const [events, setEvents] = useState<AnyRecord[]>([]);
  const [adapterEvents, setAdapterEvents] = useState<AnyRecord[]>([]);
  const [adapterEventCounts, setAdapterEventCounts] = useState<AnyRecord>({});
  const [llmApiEvents, setLlmApiEvents] = useState<AnyRecord[]>([]);
  const [llmApiEventCounts, setLlmApiEventCounts] = useState<AnyRecord>({});
  const [systemEvents, setSystemEvents] = useState<AnyRecord[]>([]);
  const [systemEventCounts, setSystemEventCounts] = useState<AnyRecord>({});
  const [systemActiveTasks, setSystemActiveTasks] = useState<AnyRecord[]>([]);
  const [toolEvents, setToolEvents] = useState<AnyRecord[]>([]);
  const [toolEventCounts, setToolEventCounts] = useState<AnyRecord>({});
  const [toolActiveTasks, setToolActiveTasks] = useState<AnyRecord[]>([]);
  const [outbox, setOutbox] = useState<AnyRecord[]>([]);
  const [abResult, setAbResult] = useState<AnyRecord | null>(null);
  const [scenarioScores, setScenarioScores] = useState<AnyRecord[]>([]);
  const [scenarioHistory, setScenarioHistory] = useState<AnyRecord[]>([]);
  const [scenarioRuns, setScenarioRuns] = useState<AnyRecord[]>([]);
  const [promptExperiments, setPromptExperiments] = useState<AnyRecord[]>([]);
  const [wakePreviews, setWakePreviews] = useState<AnyRecord[]>([]);
  const [wakeMatrix, setWakeMatrix] = useState<AnyRecord | null>(null);
  const [wakeMatrixHistory, setWakeMatrixHistory] = useState<AnyRecord[]>([]);
  const [wakePolicy, setWakePolicy] = useState<AnyRecord | null>(null);
  const [napcatGuide, setNapcatGuide] = useState<AnyRecord | null>(null);
  const [selftest, setSelftest] = useState<AnyRecord | null>(null);
  const [selftestHistory, setSelftestHistory] = useState<AnyRecord[]>([]);
  const [morningCheck, setMorningCheck] = useState<AnyRecord | null>(null);
  const [morningHistory, setMorningHistory] = useState<AnyRecord[]>([]);
  const [background, setBackground] = useState<AnyRecord | null>(null);
  const [tools, setTools] = useState<AnyRecord[]>([]);
  const [stickers, setStickers] = useState<AnyRecord | null>(null);
  const [diaryBook, setDiaryBook] = useState<AnyRecord | null>(null);
  const [selectedDiaryEntry, setSelectedDiaryEntry] = useState<AnyRecord | null>(null);
  const [diaryDraft, setDiaryDraft] = useState<AnyRecord>({ id: '', title: '', content: '', importance: 70, mode: 'append' });
  const [scheduledTasks, setScheduledTasks] = useState<AnyRecord | null>(null);
  const [library, setLibrary] = useState<AnyRecord | null>(null);
  const [selectedBook, setSelectedBook] = useState<AnyRecord | null>(null);
  const [selectedLibraryReview, setSelectedLibraryReview] = useState<AnyRecord | null>(null);
  const [selectedLibraryOriginal, setSelectedLibraryOriginal] = useState<AnyRecord | null>(null);
  const [bookImportDraft, setBookImportDraft] = useState<AnyRecord>({ path: '', title: '', summary: '', text: '' });
  const [runtimePackages, setRuntimePackages] = useState<AnyRecord | null>(null);
  const [runtimePackageDraft, setRuntimePackageDraft] = useState<AnyRecord>({
    name: 'PA runtime package',
    note: '',
    path: '',
    strategy: 'retreat',
    include_hdb: true,
    include_state: true,
    include_agent_data: true,
    include_library: true,
  });
  const [scheduleDraft, setScheduleDraft] = useState<AnyRecord>({
    id: '',
    summary: '',
    prompt: '',
    triggerText: JSON.stringify({ type: 'once', at: '2026-05-10 21:30' }, null, 2),
    enabled: true,
  });
  const [scheduleCommandText, setScheduleCommandText] = useState(JSON.stringify({ operation: 'list' }, null, 2));
  const [toolMatrix, setToolMatrix] = useState<AnyRecord | null>(null);
  const [protocolRegistry, setProtocolRegistry] = useState<AnyRecord | null>(null);
  const [integrations, setIntegrations] = useState<AnyRecord | null>(null);
  const [modelPool, setModelPool] = useState<AnyRecord[]>([]);
  const [modelReadiness, setModelReadiness] = useState<AnyRecord | null>(null);
  const [modelExportPreview, setModelExportPreview] = useState<AnyRecord | null>(null);
  const [promptContract, setPromptContract] = useState<AnyRecord | null>(null);
  const [activationRoadmap, setActivationRoadmap] = useState<AnyRecord | null>(null);
  const [thoughtContinuity, setThoughtContinuity] = useState<AnyRecord | null>(null);
  const [cognitiveTimeline, setCognitiveTimeline] = useState<AnyRecord | null>(null);
  const [replyActionAudit, setReplyActionAudit] = useState<AnyRecord | null>(null);
  const [replyDebtPreview, setReplyDebtPreview] = useState<AnyRecord | null>(null);
  const [multimodalReadiness, setMultimodalReadiness] = useState<AnyRecord | null>(null);
  const [attachmentPreview, setAttachmentPreview] = useState<AnyRecord | null>(null);
  const [promptPreview, setPromptPreview] = useState<AnyRecord | null>(null);
  const [configProfiles, setConfigProfiles] = useState<AnyRecord[]>([]);
  const [personaHistory, setPersonaHistory] = useState<PersonaHistoryRecord[]>([]);
  const [userProgress, setUserProgress] = useState<AnyRecord | null>(null);
  const [userProgressLocalOverride, setUserProgressLocalOverride] = useState<AnyRecord | null>(null);
  const [serverConfig, setServerConfig] = useState<AgentConfig>(emptyConfig);
  const [draft, setDraft] = useState<AgentConfig>(emptyConfig);
  const [personaHistoryEditingId, setPersonaHistoryEditingId] = useState('');
  const [slotDraft, setSlotDraft] = useState<AnyRecord>({ name: '', base_url: 'https://api.openai.com', model: '', vision_model: '', multimodal_model: '', image_generation_model: '', api_key: '', vision_api_key: '', multimodal_api_key: '', image_generation_api_key: '', enabled: true, note: '', index: '' });
  const [profileName, setProfileName] = useState('本地安全默认配置');
  const [profileNote, setProfileNote] = useState('保留当前 API Key，不在快照中复制密钥。');
  const [input, setInput] = useState(initialUiPrefs.input ?? '');
  const [attachmentDraft, setAttachmentDraft] = useState<AnyRecord[]>([]);
  const [fileDraft, setFileDraft] = useState<File[]>([]);
  const [imagePreviewMap, setImagePreviewMap] = useState<Record<string, string>>({});
  const imagePreviewFailureRef = useRef<Record<string, number>>({});
  const [attachmentNote, setAttachmentNote] = useState('');
  const [wakeMessageType, setWakeMessageType] = useState('group');
  const [wakeMentions, setWakeMentions] = useState('PA');
  const [wakeText, setWakeText] = useState('小PA，醒醒，我想问你点事。');
  const [napcatText, setNapcatText] = useState('小PA 早上好，帮我记一下今天的想法。');
  const [replyText, setReplyText] = useState('这是一条 NapCat outbound 测试消息。');
  const [toolName, setToolName] = useState('time');
  const [toolArgs, setToolArgs] = useState('{"format":"local"}');
  const [kbText, setKbText] = useState('把今天的 PA 原型目标记录为：先配置人设和模型，然后在主页边聊天边观察 AP 想法云、连续 thought、情绪/认知状态。');
  const [abText, setAbText] = useState('请基于当前 AP 状态生成一段自然、连续、不过度解释指标的内心想法。');
  const [thoughtOffset, setThoughtOffset] = useState(0);
  const [thoughtPage, setThoughtPage] = useState<AnyRecord | null>(null);
  const [snapshotPage, setSnapshotPage] = useState<AnyRecord | null>(null);
  const [busyScopes, setBusyScopes] = useState<Record<string, boolean>>({});
  const [sending, setSending] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [agentTab, setAgentTab] = useState(initialUiPrefs.agentTab ?? 'home');
  const [apChartTab, setApChartTab] = useState(initialUiPrefs.apChartTab ?? 'overview');
  const [adapterLogView, setAdapterLogView] = useState(initialUiPrefs.adapterLogView ?? 'important');
  const [llmApiLogView, setLlmApiLogView] = useState(initialUiPrefs.llmApiLogView ?? 'important');
  const [systemLogView, setSystemLogView] = useState(initialUiPrefs.systemLogView ?? 'important');
  const [toolLogView, setToolLogView] = useState(initialUiPrefs.toolLogView ?? 'important');
  const [autoRefresh, setAutoRefresh] = useState(initialUiPrefs.autoRefresh ?? true);
  const [refreshMs, setRefreshMs] = useState<number | ''>(initialUiPrefs.refreshMs ?? 1200);
  const [manualTicks, setManualTicks] = useState<number | ''>(initialUiPrefs.manualTicks ?? 3);
  const [sendPreTicks, setSendPreTicks] = useState<number | ''>(initialUiPrefs.sendPreTicks ?? Number(emptyConfig.pre_thought_ticks ?? 5));
  const [sendWaitTicks, setSendWaitTicks] = useState(initialUiPrefs.sendWaitTicks ?? Boolean(emptyConfig.run_ap_while_waiting_llm));
  const [sendPostTicks, setSendPostTicks] = useState<number | ''>(initialUiPrefs.sendPostTicks ?? Number(emptyConfig.post_thought_ticks ?? 2));
  const [enterToSend, setEnterToSend] = useState(initialUiPrefs.enterToSend ?? true);
  const [logKeep, setLogKeep] = useState<number | ''>(initialUiPrefs.logKeep ?? 120);
  const [collapseDebtMessages, setCollapseDebtMessages] = useState(initialUiPrefs.collapseDebtMessages ?? true);
  const [selected, setSelected] = useState<AnyRecord | null>(null);
  const [draftDirty, setDraftDirty] = useState(false);
  const [polishBusy, setPolishBusy] = useState(false);
  const [agentJobs, setAgentJobs] = useState<AgentJob[]>([]);
  const [activeJob, setActiveJob] = useState<AgentJob | null>(null);
  const [pendingMessages, setPendingMessages] = useState<PendingMessage[]>([]);
  const [cloudModalOpen, setCloudModalOpen] = useState(false);
  const cloudContainerRef = useRef<HTMLDivElement | null>(null);
  const chatViewportRef = useRef<HTMLDivElement | null>(null);
  const chatAutoFollowRef = useRef(true);
  const [cloudViewport, setCloudViewport] = useState({ width: 980, height: 560 });
  const initializedRef = useRef(false);
  const draftDirtyRef = useRef(false);
  const draftInitializedRef = useRef(false);
  const userProgressOverrideUpdatedAtRef = useRef(0);
  const userProgressLocalOverrideRef = useRef<AnyRecord | null>(null);

  const mergeUserProgressForView = (incoming: AnyRecord | null | undefined) => {
    const base = incoming && typeof incoming === 'object' ? incoming : null;
    const override = userProgressLocalOverrideRef.current;
    if (!override || typeof override !== 'object') return base;
    const incomingUpdatedAt = asNumber(base?.updated_at_ms, 0);
    const incomingGeneratedAt = asNumber(base?.generated_at_ms, 0);
    const overrideUpdatedAt = asNumber(override?.updated_at_ms, userProgressOverrideUpdatedAtRef.current);
    const overrideGeneratedAt = asNumber(override?.generated_at_ms, 0);
    const incomingLooksFreshEnough =
      (incomingUpdatedAt > 0 && incomingUpdatedAt >= overrideUpdatedAt)
      || (incomingGeneratedAt > 0 && overrideGeneratedAt > 0 && incomingGeneratedAt >= overrideGeneratedAt && incomingUpdatedAt >= overrideUpdatedAt);
    if (incomingLooksFreshEnough) {
      userProgressLocalOverrideRef.current = null;
      setUserProgressLocalOverride(null);
      return base;
    }
    return { ...(base || {}), ...override };
  };

  const refreshPersonaHistoryAndProgress = async (selectResult = false) => {
    const [personaPayload, progressPayload] = await Promise.all([
      api.agentPersonaHistory().catch(() => null),
      api.agentUserProgress().catch(() => null),
    ]);
    if (personaPayload) {
      const rows = asArray<PersonaHistoryRecord>(personaPayload.records);
      setPersonaHistory(rows);
      if (selectResult) setSelected(personaPayload);
    }
    if (progressPayload) {
      const merged = mergeUserProgressForView(progressPayload);
      setUserProgress(merged);
      if (selectResult && !personaPayload) setSelected(merged || progressPayload);
    }
    return { personaPayload, progressPayload };
  };

  const setBusyScope = (scope: BusyScope, value: boolean) => {
    setBusyScopes((prev) => {
      if (value) return { ...prev, [scope]: true };
      const next = { ...prev };
      delete next[scope];
      return next;
    });
  };
  const isBusy = (scope?: BusyScope) => {
    if (scope) return Boolean(busyScopes[scope]);
    return Object.keys(busyScopes).some((key) => key !== 'send' && Boolean(busyScopes[key]));
  };
  const withBusy = async <T,>(scope: BusyScope, task: () => Promise<T>): Promise<T> => {
    setBusyScope(scope, true);
    try {
      return await task();
    } finally {
      setBusyScope(scope, false);
    }
  };
  const busy = isBusy();
  const setBusy = (value: boolean) => setBusyScope('global', value);

  const updateChatAutoFollow = (scrollTop?: number) => {
    const viewport = chatViewportRef.current;
    if (!viewport) return;
    const currentTop = typeof scrollTop === 'number' ? scrollTop : viewport.scrollTop;
    const distanceToBottom = Math.max(0, viewport.scrollHeight - (currentTop + viewport.clientHeight));
    chatAutoFollowRef.current = distanceToBottom <= 56;
  };

  const setDraftEditable = (fn: (prev: AgentConfig) => AgentConfig) => {
    draftDirtyRef.current = true;
    setDraftDirty(true);
    setDraft(fn);
  };
  const configBusy = isBusy('config');
  const diagBusy = isBusy('diag');
  const promptBusy = isBusy('prompt');
  const wakeBusy = isBusy('wake');
  const napcatBusy = isBusy('napcat');
  const historyBusy = isBusy('history');
  const backgroundBusy = isBusy('background');
  const toolBusy = isBusy('tool');
  const maintenanceBusy = isBusy('maintenance');

  async function refreshSnapshotHistory(limit = SNAPSHOT_HISTORY_LIMIT) {
    const snapshotHistory = await api.agentHistory('snapshots', limit, 0).catch(() => null);
    if (snapshotHistory) setSnapshotPage(snapshotHistory);
    return snapshotHistory;
  }

  async function refresh(silent = false) {
    if (!silent) {
      setRefreshing(true);
    }
    try {
      const jobsPayload = await api.agentJobs(24).catch(() => null);
      const jobs = asArray<AgentJob>(jobsPayload?.jobs);
      const active = pickActiveAgentJob(jobsPayload as AnyRecord | null, jobs);
      setAgentJobs(jobs);
      setActiveJob(active);
      const isRunning = Boolean(active && isLiveAgentJob(active));
      if (silent) {
        if (isRunning) {
          if (active?.ap_packet && Object.keys(active.ap_packet).length) {
            setStatus((prev) => ({
              ...(prev || {}),
              ap_packet: active.ap_packet,
              session: (prev || {}).session || {},
              config: (prev || {}).config || serverConfig,
            }));
          }
          const [bg, adapterPayload, stickerPayload, llmApiPayload, systemPayload] = await Promise.all([
            api.agentBackgroundStatus().catch(() => null),
            agentTab === 'adapter' ? api.agentAdapterEvents(120, adapterLogView).catch(() => null) : Promise.resolve(null),
            agentTab === 'adapter' ? api.agentStickers().catch(() => null) : Promise.resolve(null),
            api.agentLlmApiEvents(120, llmApiLogView).catch(() => null),
            api.agentSystemEvents(120, systemLogView).catch(() => null),
          ]);
          if (bg) setBackground(bg);
          if (adapterPayload) {
            setAdapterEvents(asArray<AnyRecord>(adapterPayload.events));
            setAdapterEventCounts((adapterPayload.counts || {}) as AnyRecord);
          }
          if (stickerPayload) setStickers(stickerPayload);
          if (llmApiPayload) {
            setLlmApiEvents(asArray<AnyRecord>(llmApiPayload.events));
            setLlmApiEventCounts((llmApiPayload.counts || {}) as AnyRecord);
          }
          if (systemPayload) {
            setSystemEvents(asArray<AnyRecord>(systemPayload.events));
            setSystemEventCounts((systemPayload.counts || {}) as AnyRecord);
            setSystemActiveTasks(asArray<AnyRecord>(systemPayload.active_tasks));
            setToolEvents(filterToolEvents(asArray<AnyRecord>(systemPayload.events), toolLogView));
            setToolEventCounts((systemPayload.counts || {}) as AnyRecord);
            setToolActiveTasks(filterToolEvents(asArray<AnyRecord>(systemPayload.active_tasks), 'detail'));
          }
          onStatusChange?.(`PA ${active?.stage_label || active?.stage || active?.ap_packet?.tick_counter || '运行中'}`);
          return;
        }
        const [payload, bg, adapterPayload, stickerPayload, llmApiPayload, systemPayload] = await Promise.all([
          api.agentStatus().catch(() => null),
          api.agentBackgroundStatus().catch(() => null),
          agentTab === 'adapter' ? api.agentAdapterEvents(120, adapterLogView).catch(() => null) : Promise.resolve(null),
          agentTab === 'adapter' ? api.agentStickers().catch(() => null) : Promise.resolve(null),
          api.agentLlmApiEvents(120, llmApiLogView).catch(() => null),
          api.agentSystemEvents(120, systemLogView).catch(() => null),
        ]);
        if (payload) {
          setStatus(payload);
          setServerConfig((payload?.config || {}) as AgentConfig);
          if (payload?.user_progress) setUserProgress(mergeUserProgressForView(payload.user_progress));
          if (payload?.persona_history?.records) setPersonaHistory(asArray<PersonaHistoryRecord>(payload.persona_history.records));
          if (!draftInitializedRef.current) {
            const nextConfig = { ...emptyConfig, ...(payload?.config || {}) } as AgentConfig;
            setDraft(nextConfig);
            const savedPrefs = initialUiPrefsRef.current || {};
            if (savedPrefs.sendPreTicks === undefined) {
              setSendPreTicks(Number(nextConfig.pre_thought_ticks ?? emptyConfig.pre_thought_ticks ?? 5));
            }
            if (savedPrefs.sendWaitTicks === undefined) {
              setSendWaitTicks(Boolean(nextConfig.run_ap_while_waiting_llm));
            }
            if (savedPrefs.sendPostTicks === undefined) {
              setSendPostTicks(Number(nextConfig.post_thought_ticks ?? emptyConfig.post_thought_ticks ?? 2));
            }
            draftInitializedRef.current = true;
          }
        }
        if (bg) setBackground(bg);
        if (adapterPayload) {
          setAdapterEvents(asArray<AnyRecord>(adapterPayload.events));
          setAdapterEventCounts((adapterPayload.counts || {}) as AnyRecord);
        }
        if (stickerPayload) setStickers(stickerPayload);
        if (llmApiPayload) {
          setLlmApiEvents(asArray<AnyRecord>(llmApiPayload.events));
          setLlmApiEventCounts((llmApiPayload.counts || {}) as AnyRecord);
        }
        if (systemPayload) {
          setSystemEvents(asArray<AnyRecord>(systemPayload.events));
          setSystemEventCounts((systemPayload.counts || {}) as AnyRecord);
          setSystemActiveTasks(asArray<AnyRecord>(systemPayload.active_tasks));
          setToolEvents(filterToolEvents(asArray<AnyRecord>(systemPayload.events), toolLogView));
          setToolEventCounts((systemPayload.counts || {}) as AnyRecord);
          setToolActiveTasks(filterToolEvents(asArray<AnyRecord>(systemPayload.active_tasks), 'detail'));
        }
        if (agentTab === 'charts' && !isRunning) {
          refreshSnapshotHistory().catch(() => undefined);
        }
        onStatusChange?.(`PA ${active?.stage_label || active?.stage || payload?.ap_packet?.tick_counter || '待命'}`);
        return;
      }
      const [payload, bg] = await Promise.all([
        api.agentStatus(),
        api.agentBackgroundStatus().catch(() => null),
      ]);
      setStatus(payload);
      if (bg) setBackground(bg);
      setServerConfig((payload?.config || {}) as AgentConfig);
      if (!draftInitializedRef.current) {
        const nextConfig = { ...emptyConfig, ...(payload?.config || {}) } as AgentConfig;
        setDraft(nextConfig);
        const savedPrefs = initialUiPrefsRef.current || {};
        if (savedPrefs.sendPreTicks === undefined) {
          setSendPreTicks(Number(nextConfig.pre_thought_ticks ?? emptyConfig.pre_thought_ticks ?? 5));
        }
        if (savedPrefs.sendWaitTicks === undefined) {
          setSendWaitTicks(Boolean(nextConfig.run_ap_while_waiting_llm));
        }
        if (savedPrefs.sendPostTicks === undefined) {
          setSendPostTicks(Number(nextConfig.post_thought_ticks ?? emptyConfig.post_thought_ticks ?? 2));
        }
        draftInitializedRef.current = true;
      }
      const stageText = active?.stage_label || active?.stage || `tick ${payload?.ap_packet?.tick_counter ?? '-'}`;
      onStatusChange?.(`PA ${stageText}`);
      if (agentTab === 'charts' && !isRunning) {
        refreshSnapshotHistory().catch(() => undefined);
      }
      if (!silent) {
        const [diag, readinessPayload, acceptancePayload, safetyPayload, logPlanPayload, morningReviewPayload, eventPayload, adapterEventPayload, llmApiEventPayload, systemEventPayload, outboxPayload, experimentPayload, scenarioPayload, wakePayload, wakeMatrixPayload, wakePolicyPayload, napcatGuidePayload, selftestPayload, morningPayload, bgPayload, toolPayload, stickerPayload, diaryPayload, scheduledPayload, libraryPayload, runtimePackagePayload, toolMatrixPayload, protocolPayload, integrationPayload, modelPayload, modelReadyPayload, modelExportPayload, promptContractPayload, activationRoadmapPayload, thoughtContinuityPayload, cognitiveTimelinePayload, replyActionAuditPayload, multimodalPayload, profilePayload, personaPayload, progressPayload] = await Promise.all([
          api.agentDiagnostics().catch(() => null),
          api.agentReadiness().catch(() => null),
          api.agentAcceptance().catch(() => null),
          api.agentSafetyRadar().catch(() => null),
          api.agentLogPlan(Number(logKeep) || 120).catch(() => null),
          api.agentMorningReview(Number(logKeep) || 120).catch(() => null),
          api.agentEvents(80).catch(() => null),
          api.agentAdapterEvents(120, adapterLogView).catch(() => null),
          api.agentLlmApiEvents(120, llmApiLogView).catch(() => null),
          api.agentSystemEvents(120, systemLogView).catch(() => null),
          api.agentOutbox(40).catch(() => null),
          api.agentPromptExperiments(20).catch(() => null),
          api.agentPromptScenarios(60).catch(() => null),
          api.agentWakePreviews(20).catch(() => null),
          api.agentWakeMatrixHistory(10).catch(() => null),
          api.agentWakePolicy().catch(() => null),
          api.agentNapcatGuide().catch(() => null),
          api.agentSelftests(10).catch(() => null),
          api.agentMorningChecks(10).catch(() => null),
          api.agentBackgroundStatus().catch(() => null),
          api.agentTools().catch(() => null),
          api.agentStickers().catch(() => null),
          api.agentDiary(false).catch(() => null),
          api.agentScheduledTasks(true, false).catch(() => null),
          api.agentLibrary(false).catch(() => null),
          api.agentRuntimePackages().catch(() => null),
          api.agentToolMatrix().catch(() => null),
          api.agentProtocolRegistry().catch(() => null),
          api.agentIntegrations().catch(() => null),
          api.agentModelPool().catch(() => null),
          api.agentModelReadiness().catch(() => null),
          api.agentModelExportPreview().catch(() => null),
          api.agentPromptContract().catch(() => null),
          api.agentActivationRoadmap().catch(() => null),
          api.agentThoughtContinuity().catch(() => null),
          api.agentCognitiveTimeline().catch(() => null),
          api.agentReplyActionAudit().catch(() => null),
          api.agentMultimodalReadiness().catch(() => null),
          api.agentConfigProfiles().catch(() => null),
          api.agentPersonaHistory().catch(() => null),
          api.agentUserProgress().catch(() => null),
        ]);
        if (diag) setDiagnostics(diag);
        if (readinessPayload) setReadiness(readinessPayload);
        if (acceptancePayload) setAcceptance(acceptancePayload);
        if (safetyPayload) setSafetyRadar(safetyPayload);
        if (logPlanPayload) setLogPlan(logPlanPayload);
        if (morningReviewPayload) setMorningReview(morningReviewPayload);
        if (eventPayload) setEvents(asArray<AnyRecord>(eventPayload.events));
        if (adapterEventPayload) {
          setAdapterEvents(asArray<AnyRecord>(adapterEventPayload.events));
          setAdapterEventCounts((adapterEventPayload.counts || {}) as AnyRecord);
        }
        if (llmApiEventPayload) {
          setLlmApiEvents(asArray<AnyRecord>(llmApiEventPayload.events));
          setLlmApiEventCounts((llmApiEventPayload.counts || {}) as AnyRecord);
        }
        if (systemEventPayload) {
          setSystemEvents(asArray<AnyRecord>(systemEventPayload.events));
          setSystemEventCounts((systemEventPayload.counts || {}) as AnyRecord);
          setSystemActiveTasks(asArray<AnyRecord>(systemEventPayload.active_tasks));
          setToolEvents(filterToolEvents(asArray<AnyRecord>(systemEventPayload.events), toolLogView));
          setToolEventCounts((systemEventPayload.counts || {}) as AnyRecord);
          setToolActiveTasks(filterToolEvents(asArray<AnyRecord>(systemEventPayload.active_tasks), 'detail'));
        }
        if (outboxPayload) setOutbox(asArray<AnyRecord>(outboxPayload.outbox));
        if (experimentPayload) setPromptExperiments(asArray<AnyRecord>(experimentPayload.experiments));
        if (scenarioPayload) {
          setScenarioHistory(asArray<AnyRecord>(scenarioPayload.scenarios));
          setScenarioRuns(asArray<AnyRecord>(scenarioPayload.runs));
        }
        if (wakePayload) setWakePreviews(asArray<AnyRecord>(wakePayload.previews));
        if (wakeMatrixPayload) setWakeMatrixHistory(asArray<AnyRecord>(wakeMatrixPayload.runs));
        if (wakePolicyPayload) setWakePolicy(wakePolicyPayload);
        if (napcatGuidePayload) setNapcatGuide(napcatGuidePayload);
        if (selftestPayload) setSelftestHistory(asArray<AnyRecord>(selftestPayload.runs));
        if (morningPayload) setMorningHistory(asArray<AnyRecord>(morningPayload.runs));
        if (bgPayload) setBackground(bgPayload);
        if (toolPayload) setTools(asArray<AnyRecord>(toolPayload.tools));
        if (stickerPayload) setStickers(stickerPayload);
        if (diaryPayload) setDiaryBook(diaryPayload);
        if (scheduledPayload) setScheduledTasks(scheduledPayload);
        if (libraryPayload) setLibrary(libraryPayload);
        if (runtimePackagePayload) setRuntimePackages(runtimePackagePayload);
        if (toolMatrixPayload) setToolMatrix(toolMatrixPayload);
        if (protocolPayload) setProtocolRegistry(protocolPayload);
        if (integrationPayload) setIntegrations(integrationPayload);
        if (modelPayload) setModelPool(asArray<AnyRecord>(modelPayload.models));
        if (modelReadyPayload) setModelReadiness(modelReadyPayload);
        if (modelExportPayload) setModelExportPreview(modelExportPayload);
        if (promptContractPayload) setPromptContract(promptContractPayload);
        if (activationRoadmapPayload) setActivationRoadmap(activationRoadmapPayload);
        if (thoughtContinuityPayload) setThoughtContinuity(thoughtContinuityPayload);
        if (cognitiveTimelinePayload) setCognitiveTimeline(cognitiveTimelinePayload);
        if (replyActionAuditPayload) setReplyActionAudit(replyActionAuditPayload);
        if (multimodalPayload) setMultimodalReadiness(multimodalPayload);
        if (profilePayload) setConfigProfiles(asArray<AnyRecord>(profilePayload.profiles));
        if (personaPayload) setPersonaHistory(asArray<PersonaHistoryRecord>(personaPayload.records));
        if (progressPayload) setUserProgress(mergeUserProgressForView(progressPayload));
      }
    } finally {
      if (!silent) {
        setRefreshing(false);
      }
    }
  }

  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    refresh(true).catch(() => undefined);
    api.agentWakePolicy().then(setWakePolicy).catch(() => undefined);
    api.agentNapcatGuide().then(setNapcatGuide).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (agentTab === 'charts') {
      refreshSnapshotHistory().catch(() => undefined);
    }
  }, [agentTab]);

  useEffect(() => {
    if (agentTab === 'adapter') {
      refreshAdapterEvents(false).catch(() => undefined);
    }
  }, [agentTab, adapterLogView]);

  useEffect(() => {
    refreshLlmApiEvents(false).catch(() => undefined);
  }, [llmApiLogView]);

  useEffect(() => {
    refreshSystemEvents(false).catch(() => undefined);
  }, [systemLogView]);

  useEffect(() => {
    refreshToolEvents(false).catch(() => undefined);
  }, [toolLogView]);

  useEffect(() => {
    if (!autoRefresh) return undefined;
    const timer = window.setInterval(() => refresh(true).catch(() => undefined), Math.max(350, Number(refreshMs) || 1200));
    return () => window.clearInterval(timer);
  }, [autoRefresh, refreshMs, agentTab, adapterLogView, llmApiLogView, systemLogView, toolLogView]);

  useEffect(() => {
    const backgroundRunning = Boolean(background?.running);
    const hasLiveForegroundJob = Boolean(activeJob?.job_id) && !isTerminalAgentJob(activeJob);
    if (hasLiveForegroundJob) return undefined;
    if (!backgroundRunning) return undefined;
    const interval = Math.max(500, Math.min(4000, Number(refreshMs) || 1200));
    const timer = window.setInterval(async () => {
      try {
        const bg = await api.agentBackgroundStatus().catch(() => null);
        if (!bg) return;
        setBackground(bg);
        const packetNext = ((bg?.last_result || {}) as AnyRecord).ap_packet || {};
        if (Object.keys(packetNext).length) {
          setStatus((prev) => {
            const next = { ...(prev || {}) } as AnyRecord;
            next.ap_packet = packetNext;
            next.session = next.session || {};
            next.config = next.config || serverConfig;
            return next;
          });
        }
      } catch {
        return;
      }
    }, interval);
    return () => window.clearInterval(timer);
  }, [background?.running, activeJob?.job_id, activeJob?.status, refreshMs, serverConfig]);

  useEffect(() => {
    writeAgentUiPrefs({
      input,
      sendPreTicks,
      sendWaitTicks,
      sendPostTicks,
      enterToSend,
      autoRefresh,
      refreshMs,
      manualTicks,
      logKeep,
      collapseDebtMessages,
      agentTab,
      apChartTab,
      adapterLogView,
      llmApiLogView,
      systemLogView,
      toolLogView,
    });
  }, [
    input,
    sendPreTicks,
    sendWaitTicks,
    sendPostTicks,
    enterToSend,
    autoRefresh,
    refreshMs,
    manualTicks,
    logKeep,
    collapseDebtMessages,
    agentTab,
    apChartTab,
    adapterLogView,
    llmApiLogView,
    systemLogView,
    toolLogView,
  ]);

  useEffect(() => {
    const element = cloudContainerRef.current;
    if (!element) return undefined;
    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      const width = Math.max(360, Math.floor(rect.width || 980));
      const height = Math.max(360, Math.floor(rect.height || 560));
      setCloudViewport((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
    };
    updateSize();
    const observer = new ResizeObserver(() => updateSize());
    observer.observe(element);
    window.addEventListener('resize', updateSize);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', updateSize);
    };
  }, [agentTab]);

  useEffect(() => {
    const activeId = String(activeJob?.job_id || '');
    const activeStatus = String(activeJob?.status || '');
    if (!activeId || isTerminalAgentJob(activeJob)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const payload = await api.agentJob(activeId);
        const job = (payload?.job || null) as AgentJob | null;
        if (job) {
          setActiveJob(job);
          setAgentJobs((prev) => {
            const rows = prev.filter((item) => String(item.job_id || '') !== activeId);
            return [job, ...rows].slice(0, 24);
          });
          setStatus((prev) => {
            const next = { ...(prev || {}) } as AnyRecord;
            if (job.ap_packet && Object.keys(job.ap_packet).length) {
              next.ap_packet = job.ap_packet;
            }
            next.messages = mergeLiveRecords(asArray<AnyRecord>(next.messages), [
              ...jobUserMessages(job),
              ...jobReplyMessages(job),
            ], 'message').sort((a, b) => asNumber(a.created_at_ms, 0) - asNumber(b.created_at_ms, 0));
            next.thoughts = mergeLiveRecords(asArray<AnyRecord>(next.thoughts), [
              ...asArray<AnyRecord>(job.thoughts),
              job.thought as AnyRecord,
            ].filter((item): item is AnyRecord => Boolean(item && typeof item === 'object' && String(item.text || '').trim())), 'thought');
            next.session = next.session || {};
            next.config = next.config || serverConfig;
            return next;
          });
          const bg = await api.agentBackgroundStatus().catch(() => null);
          if (bg) setBackground(bg);
          if (isTerminalAgentJob(job)) {
            await refresh(true).catch(() => undefined);
            if (agentTab === 'charts') {
              refreshSnapshotHistory().catch(() => undefined);
            }
          }
        }
      } catch {
        return;
      }
    }, 180);
    return () => window.clearInterval(timer);
  }, [activeJob?.job_id, activeJob?.status, agentTab]);

  async function saveConfig() {
    await withBusy('config', async () => {
      const saved = await api.saveAgentConfig(draft);
      const nextConfig = { ...emptyConfig, ...(saved || {}), api_key: '' } as AgentConfig;
      setServerConfig(nextConfig);
      setDraft((prev) => ({ ...prev, ...nextConfig }));
      setSendPreTicks(Number((saved as AgentConfig)?.pre_thought_ticks ?? draft.pre_thought_ticks ?? emptyConfig.pre_thought_ticks ?? 5));
      setSendWaitTicks(Boolean((saved as AgentConfig)?.run_ap_while_waiting_llm ?? draft.run_ap_while_waiting_llm));
      setSendPostTicks(Number((saved as AgentConfig)?.post_thought_ticks ?? draft.post_thought_ticks ?? emptyConfig.post_thought_ticks ?? 2));
      draftDirtyRef.current = false;
      draftInitializedRef.current = true;
      setDraftDirty(false);
      const fresh = await api.agentConfig().catch(() => null);
      if (fresh) {
        const refreshedConfig = { ...emptyConfig, ...fresh, api_key: '' } as AgentConfig;
        setServerConfig(refreshedConfig);
        setDraft(refreshedConfig);
      }
      await refreshPersonaHistoryAndProgress().catch(() => undefined);
    });
  }

  async function refreshDiagnostics() {
    await withBusy('diag', async () => {
      const [diag, readinessPayload, acceptancePayload, safetyPayload, logPlanPayload, morningReviewPayload, eventPayload, adapterEventPayload, llmApiEventPayload, systemEventPayload, outboxPayload, experimentPayload, scenarioPayload, wakePayload, wakeMatrixPayload, wakePolicyPayload, napcatGuidePayload, selftestPayload, morningPayload, bgPayload, toolPayload, stickerPayload, diaryPayload, scheduledPayload, libraryPayload, runtimePackagePayload, toolMatrixPayload, protocolPayload, integrationPayload, modelPayload, modelReadyPayload, modelExportPayload, promptContractPayload, activationRoadmapPayload, thoughtContinuityPayload, cognitiveTimelinePayload, replyActionAuditPayload, multimodalPayload, profilePayload, personaPayload, progressPayload] = await Promise.all([
        api.agentDiagnostics(),
        api.agentReadiness(),
        api.agentAcceptance(),
        api.agentSafetyRadar(),
        api.agentLogPlan(Number(logKeep) || 120),
        api.agentMorningReview(Number(logKeep) || 120),
        api.agentEvents(120),
        api.agentAdapterEvents(160, adapterLogView),
        api.agentLlmApiEvents(160, llmApiLogView),
        api.agentSystemEvents(160, systemLogView),
        api.agentOutbox(80),
        api.agentPromptExperiments(30),
        api.agentPromptScenarios(100),
        api.agentWakePreviews(30),
        api.agentWakeMatrixHistory(20),
        api.agentWakePolicy(),
        api.agentNapcatGuide(),
        api.agentSelftests(20),
        api.agentMorningChecks(20),
        api.agentBackgroundStatus(),
        api.agentTools(),
        api.agentStickers(),
        api.agentDiary(false),
        api.agentScheduledTasks(true, false),
        api.agentLibrary(false),
        api.agentRuntimePackages(),
        api.agentToolMatrix(),
        api.agentProtocolRegistry(),
        api.agentIntegrations(),
        api.agentModelPool(),
        api.agentModelReadiness(),
        api.agentModelExportPreview(),
        api.agentPromptContract(),
        api.agentActivationRoadmap(),
        api.agentThoughtContinuity(),
        api.agentCognitiveTimeline(),
        api.agentReplyActionAudit(),
        api.agentMultimodalReadiness(),
        api.agentConfigProfiles(),
        api.agentPersonaHistory().catch(() => null),
        api.agentUserProgress().catch(() => null),
      ]);
      setDiagnostics(diag);
      setReadiness(readinessPayload);
      setAcceptance(acceptancePayload);
      setSafetyRadar(safetyPayload);
      setLogPlan(logPlanPayload);
      setMorningReview(morningReviewPayload);
      setEvents(asArray<AnyRecord>(eventPayload.events));
      setAdapterEvents(asArray<AnyRecord>(adapterEventPayload.events));
      setAdapterEventCounts((adapterEventPayload.counts || {}) as AnyRecord);
      setLlmApiEvents(asArray<AnyRecord>(llmApiEventPayload.events));
      setLlmApiEventCounts((llmApiEventPayload.counts || {}) as AnyRecord);
      setSystemEvents(asArray<AnyRecord>(systemEventPayload.events));
      setSystemEventCounts((systemEventPayload.counts || {}) as AnyRecord);
      setSystemActiveTasks(asArray<AnyRecord>(systemEventPayload.active_tasks));
      setToolEvents(filterToolEvents(asArray<AnyRecord>(systemEventPayload.events), toolLogView));
      setToolEventCounts((systemEventPayload.counts || {}) as AnyRecord);
      setToolActiveTasks(filterToolEvents(asArray<AnyRecord>(systemEventPayload.active_tasks), 'detail'));
      setOutbox(asArray<AnyRecord>(outboxPayload.outbox));
      setPromptExperiments(asArray<AnyRecord>(experimentPayload.experiments));
      setScenarioHistory(asArray<AnyRecord>(scenarioPayload.scenarios));
      setScenarioRuns(asArray<AnyRecord>(scenarioPayload.runs));
      setWakePreviews(asArray<AnyRecord>(wakePayload.previews));
      setWakeMatrixHistory(asArray<AnyRecord>(wakeMatrixPayload.runs));
      setWakePolicy(wakePolicyPayload);
      setNapcatGuide(napcatGuidePayload);
      setSelftestHistory(asArray<AnyRecord>(selftestPayload.runs));
      setMorningHistory(asArray<AnyRecord>(morningPayload.runs));
      setBackground(bgPayload);
      setTools(asArray<AnyRecord>(toolPayload.tools));
      setStickers(stickerPayload);
      setDiaryBook(diaryPayload);
      setScheduledTasks(scheduledPayload);
      setLibrary(libraryPayload);
      setRuntimePackages(runtimePackagePayload);
      setToolMatrix(toolMatrixPayload);
      setProtocolRegistry(protocolPayload);
      setIntegrations(integrationPayload);
      setModelPool(asArray<AnyRecord>(modelPayload.models));
      setModelReadiness(modelReadyPayload);
      setModelExportPreview(modelExportPayload);
      setPromptContract(promptContractPayload);
      setActivationRoadmap(activationRoadmapPayload);
      setThoughtContinuity(thoughtContinuityPayload);
      setCognitiveTimeline(cognitiveTimelinePayload);
      setReplyActionAudit(replyActionAuditPayload);
      setMultimodalReadiness(multimodalPayload);
      setConfigProfiles(asArray<AnyRecord>(profilePayload.profiles));
      if (personaPayload) setPersonaHistory(asArray<PersonaHistoryRecord>(personaPayload.records));
      if (progressPayload) setUserProgress(mergeUserProgressForView(progressPayload));
      setSelected(diag);
    });
  }

  async function refreshReadiness() {
    await withBusy('diag', async () => {
      const [result, modelReady] = await Promise.all([api.agentReadiness(), api.agentModelReadiness().catch(() => null)]);
      setReadiness(result);
      if (modelReady) setModelReadiness(modelReady);
      setSelected(result);
      api.agentAcceptance().then(setAcceptance).catch(() => undefined);
    });
  }

  async function refreshModelReadiness() {
    await withBusy('diag', async () => {
      const [result, exportPayload] = await Promise.all([
        api.agentModelReadiness(),
        api.agentModelExportPreview().catch(() => null),
      ]);
      setModelReadiness(result);
      if (exportPayload) setModelExportPreview(exportPayload);
      setSelected(result);
    });
  }

  async function refreshModelExportPreview() {
    await withBusy('diag', async () => {
      const result = await api.agentModelExportPreview();
      setModelExportPreview(result);
      setSelected(result);
    });
  }

  async function refreshPromptContract() {
    await withBusy('diag', async () => {
      const result = await api.agentPromptContract();
      setPromptContract(result);
      setSelected(result);
    });
  }

  async function refreshActivationRoadmap() {
    await withBusy('diag', async () => {
      const result = await api.agentActivationRoadmap();
      setActivationRoadmap(result);
      setSelected(result);
    });
  }

  async function refreshThoughtContinuity() {
    await withBusy('diag', async () => {
      const result = await api.agentThoughtContinuity();
      setThoughtContinuity(result);
      setSelected(result);
    });
  }

  async function refreshCognitiveTimeline() {
    await withBusy('diag', async () => {
      const result = await api.agentCognitiveTimeline();
      setCognitiveTimeline(result);
      setSelected(result);
    });
  }

  async function refreshReplyActionAudit() {
    await withBusy('diag', async () => {
      const result = await api.agentReplyActionAudit();
      setReplyActionAudit(result);
      setSelected(result);
    });
  }

  async function refreshReplyDebtPreview() {
    await withBusy('diag', async () => {
      const [auditResult, previewResult] = await Promise.all([
        api.agentReplyActionAudit().catch(() => null),
        api.agentReplyDebtPreview(),
      ]);
      if (auditResult) setReplyActionAudit(auditResult);
      setReplyDebtPreview(previewResult);
      setSelected(previewResult);
    });
  }

  async function refreshMultimodalReadiness() {
    await withBusy('diag', async () => {
      const result = await api.agentMultimodalReadiness();
      setMultimodalReadiness(result);
      setSelected(result);
    });
  }

  async function loadDiagnosticBundle(write = false) {
    await withBusy('diag', async () => {
      const result = await api.agentDiagnosticBundle(write);
      setSelected(result);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function loadHandoff(write = false) {
    await withBusy('diag', async () => {
      const result = await api.agentHandoff(write, write);
      setHandoff(result);
      setSelected(result);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function loadMorningBrief(write = false) {
    await withBusy('diag', async () => {
      const result = await api.agentMorningBrief(write);
      setMorningBrief(result);
      setSelected(result);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function refreshMorningReview() {
    await withBusy('diag', async () => {
      const result = await api.agentMorningReview(Number(logKeep) || 120);
      setMorningReview(result);
      setSelected(result);
    });
  }

  async function refreshAdapterEvents(selectResult = false) {
    const [result, stickerPayload] = await Promise.all([
      api.agentAdapterEvents(160, adapterLogView),
      api.agentStickers().catch(() => null),
    ]);
    setAdapterEvents(asArray<AnyRecord>(result.events));
    setAdapterEventCounts((result.counts || {}) as AnyRecord);
    if (stickerPayload) setStickers(stickerPayload);
    if (selectResult) setSelected(result);
    return result;
  }

  async function refreshLlmApiEvents(selectResult = false) {
    const result = await api.agentLlmApiEvents(160, llmApiLogView);
    setLlmApiEvents(asArray<AnyRecord>(result.events));
    setLlmApiEventCounts((result.counts || {}) as AnyRecord);
    if (selectResult) setSelected(result);
    return result;
  }

  async function refreshSystemEvents(selectResult = false) {
    const result = await api.agentSystemEvents(160, systemLogView);
    setSystemEvents(asArray<AnyRecord>(result.events));
    setSystemEventCounts((result.counts || {}) as AnyRecord);
    setSystemActiveTasks(asArray<AnyRecord>(result.active_tasks));
    setToolEvents(filterToolEvents(asArray<AnyRecord>(result.events), toolLogView));
    setToolEventCounts((result.counts || {}) as AnyRecord);
    setToolActiveTasks(filterToolEvents(asArray<AnyRecord>(result.active_tasks), 'detail'));
    if (selectResult) setSelected(result);
    return result;
  }

  async function refreshToolEvents(selectResult = false) {
    const backendView = toolLogView === 'errors' ? 'tool_errors' : toolLogView === 'detail' ? 'tools' : 'tool_important';
    const result = await api.agentSystemEvents(160, backendView);
    const events = asArray<AnyRecord>(result.events);
    const activeTasks = asArray<AnyRecord>(result.active_tasks);
    setToolEvents(filterToolEvents(events, toolLogView));
    setToolEventCounts((result.counts || {}) as AnyRecord);
    setToolActiveTasks(filterToolEvents(activeTasks, 'detail'));
    if (selectResult) setSelected(result);
    return result;
  }

  async function refreshStickers(selectResult = true) {
    await withBusy('diag', async () => {
      const result = await api.agentStickers();
      setStickers(result);
      if (selectResult) setSelected(result);
    });
  }

  async function syncStickers() {
    await withBusy('diag', async () => {
      const result = await api.agentSyncStickers();
      setStickers(result);
      setSelected(result);
    });
  }

  async function deleteSticker(item: AnyRecord) {
    const id = String(item.id || item.name || item.path || '').trim();
    if (!id) return;
    const ok = window.confirm(`删除这个表情包并移除本地文件？\n${String(item.name || id)}`);
    if (!ok) return;
    await withBusy('diag', async () => {
      const result = await api.agentDeleteSticker(id);
      setStickers(result);
      setSelected(result);
    });
  }

  async function clearStickers() {
    const ok = window.confirm('清空全部表情包？会同时删除注册 JSON 中的记录和对应本地图片文件。');
    if (!ok) return;
    await withBusy('diag', async () => {
      const result = await api.agentClearStickers();
      setStickers(result);
      setSelected(result);
    });
  }

  async function refreshDiary(selectResult = false) {
    await withBusy('tool', async () => {
      const result = await api.agentDiary(false);
      setDiaryBook(result);
      if (selectResult) setSelected(result);
    });
  }

  async function selectDiaryEntry(entry: AnyRecord) {
    const id = String(entry.id || '').trim();
    if (!id) return;
    await withBusy('tool', async () => {
      const result = await api.agentDiaryEntry(id);
      const detail = asArray<AnyRecord>(result.entries)[0] || entry;
      setSelectedDiaryEntry(detail);
      setDiaryDraft({
        id: detail.id || '',
        title: detail.title || '',
        content: detail.content || '',
        importance: Number(detail.importance ?? 70),
        mode: 'overwrite',
      });
      setSelected(detail);
    });
  }

  function startNewDiaryEntry() {
    setSelectedDiaryEntry(null);
    setDiaryDraft({ id: '', title: '', content: '', importance: 70, mode: 'create' });
  }

  async function saveDiaryEntry(mode?: string) {
    await withBusy('tool', async () => {
      const payload: AnyRecord = {
        id: diaryDraft.id || undefined,
        title: diaryDraft.title || '',
        content: diaryDraft.content || '',
        importance: Number(diaryDraft.importance ?? 70),
        mode: mode || diaryDraft.mode || (diaryDraft.id ? 'overwrite' : 'create'),
      };
      const result = await api.agentSaveDiary(payload);
      setSelected(result);
      await refreshDiary(false);
      const entry = result?.entry || asArray<AnyRecord>(result?.entries)[0];
      if (entry?.id) await selectDiaryEntry(entry);
    });
  }

  async function deleteDiaryEntry(entry?: AnyRecord) {
    const id = String((entry || selectedDiaryEntry || diaryDraft).id || '').trim();
    if (!id) return;
    const ok = window.confirm(`删除这条日记？\n${String((entry || selectedDiaryEntry || diaryDraft).title || id)}`);
    if (!ok) return;
    await withBusy('tool', async () => {
      const result = await api.agentDeleteDiary(id);
      setSelected(result);
      setSelectedDiaryEntry(null);
      startNewDiaryEntry();
      await refreshDiary(false);
    });
  }

  async function refreshScheduledTasks(selectResult = false) {
    await withBusy('tool', async () => {
      const result = await api.agentScheduledTasks(true, false);
      setScheduledTasks(result);
      if (selectResult) setSelected(result);
    });
  }

  function editScheduledTask(task: AnyRecord) {
    setScheduleDraft({
      id: task.id || '',
      summary: task.summary || '',
      prompt: task.prompt || '',
      triggerText: JSON.stringify(task.trigger || { type: 'once', at: task.next_fire_at || '' }, null, 2),
      enabled: task.enabled !== false,
    });
    setSelected(task);
  }

  function startNewScheduledTask() {
    setScheduleDraft({
      id: '',
      summary: '',
      prompt: '',
      triggerText: JSON.stringify({ type: 'once', at: '2026-05-10 21:30' }, null, 2),
      enabled: true,
    });
  }

  async function saveScheduledTask() {
    await withBusy('tool', async () => {
      let trigger: AnyRecord = {};
      try {
        trigger = scheduleDraft.triggerText ? JSON.parse(String(scheduleDraft.triggerText)) : {};
      } catch {
        trigger = { type: 'once', at: String(scheduleDraft.triggerText || '') };
      }
      const result = await api.agentSaveScheduledTask({
        id: scheduleDraft.id || undefined,
        summary: scheduleDraft.summary || '',
        prompt: scheduleDraft.prompt || '',
        trigger,
        enabled: scheduleDraft.enabled !== false,
      });
      setSelected(result);
      await refreshScheduledTasks(false);
    });
  }

  async function cancelScheduledTask(task: AnyRecord) {
    const id = String(task.id || '').trim();
    if (!id) return;
    const ok = window.confirm(`取消这个定时任务？\n${String(task.summary || id)}`);
    if (!ok) return;
    await withBusy('tool', async () => {
      const result = await api.agentRunScheduledTaskCommand({ operation: 'cancel', ids: [id] });
      setSelected(result);
      await refreshScheduledTasks(false);
    });
  }

  async function deleteScheduledTask(task: AnyRecord) {
    const id = String(task.id || '').trim();
    if (!id) return;
    const ok = window.confirm(`彻底删除这个定时任务记录？\n${String(task.summary || id)}`);
    if (!ok) return;
    await withBusy('tool', async () => {
      const result = await api.agentDeleteScheduledTask(id);
      setSelected(result);
      await refreshScheduledTasks(false);
    });
  }

  async function runScheduledTaskCommand() {
    await withBusy('tool', async () => {
      let payload: AnyRecord = {};
      try {
        payload = scheduleCommandText.trim() ? JSON.parse(scheduleCommandText) : { operation: 'list' };
      } catch {
        payload = { operation: 'list' };
      }
      const result = await api.agentRunScheduledTaskCommand(payload);
      setSelected(result);
      await refreshScheduledTasks(false);
    });
  }

  async function testLlm() {
    await withBusy('config', async () => {
      const result = await api.agentTestLlm();
      setSelected(result);
      api.agentModelReadiness().then(setModelReadiness).catch(() => undefined);
      await refreshDiagnostics();
    });
  }

  async function applyPreset(preset: string) {
    await withBusy('config', async () => {
      const result = await api.applyAgentPreset(preset);
      setSelected(result);
      if (result?.config) {
        setServerConfig((result.config || {}) as AgentConfig);
      }
      draftDirtyRef.current = false;
      setDraftDirty(false);
      await refresh(true);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function applyModelSlot(index: number) {
    await withBusy('config', async () => {
      const result = await api.agentApplyModelSlot(index);
      setSelected(result);
      if (result?.config) {
        setServerConfig((result.config || {}) as AgentConfig);
      }
      draftDirtyRef.current = false;
      setDraftDirty(false);
      await refresh(true);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function saveModelSlot() {
    await withBusy('config', async () => {
      const payload: AnyRecord = {
        ...slotDraft,
        slot: {
          name: slotDraft.name,
          base_url: slotDraft.base_url || draft.base_url || 'https://api.openai.com',
          model: slotDraft.model,
          vision_model: slotDraft.vision_model,
          multimodal_model: slotDraft.multimodal_model,
          image_generation_model: slotDraft.image_generation_model,
          api_key: slotDraft.api_key || '',
          vision_api_key: slotDraft.vision_api_key || '',
          multimodal_api_key: slotDraft.multimodal_api_key || '',
          image_generation_api_key: slotDraft.image_generation_api_key || '',
          enabled: slotDraft.enabled !== false,
          note: slotDraft.note || '',
        },
      };
      if (slotDraft.index !== '' && slotDraft.index !== undefined && slotDraft.index !== null) {
        payload.index = Number(slotDraft.index) || 0;
      }
      if (slotDraft.temperature !== '' && slotDraft.temperature !== undefined) {
        payload.slot.temperature = Number(slotDraft.temperature);
      }
      if (slotDraft.max_completion_tokens !== '' && slotDraft.max_completion_tokens !== undefined) {
        payload.slot.max_completion_tokens = Number(slotDraft.max_completion_tokens);
      }
      const result = await api.agentSaveModelSlot(payload);
      setModelPool(asArray<AnyRecord>(result.pool?.models));
      setSelected(result);
      setSlotDraft({ name: '', base_url: draft.base_url || 'https://api.openai.com', model: '', vision_model: '', multimodal_model: '', image_generation_model: '', api_key: '', vision_api_key: '', multimodal_api_key: '', image_generation_api_key: '', enabled: true, note: '', index: '' });
      await refresh(true);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  function editModelSlot(slot: AnyRecord) {
    setSlotDraft({
      index: slot.index ?? '',
      name: slot.name || '',
      base_url: slot.base_url || draft.base_url || 'https://api.openai.com',
      model: slot.model || '',
      vision_model: slot.vision_model || '',
      multimodal_model: slot.multimodal_model || '',
      image_generation_model: slot.image_generation_model || '',
      api_key: '',
      vision_api_key: '',
      multimodal_api_key: '',
      image_generation_api_key: '',
      enabled: slot.enabled !== false,
      note: slot.note || '',
      temperature: slot.temperature ?? '',
      max_completion_tokens: slot.max_completion_tokens ?? '',
    });
    setSelected({ event: 'edit_model_slot', index: slot.index, note: '已载入到模型号池表单；API Key 留空会保留原密钥。', slot });
  }

  async function deleteModelSlot(index: number) {
    const ok = window.confirm('删除这个模型 slot？不会影响当前已应用到主配置的模型字段。');
    if (!ok) return;
    await withBusy('config', async () => {
      const result = await api.agentDeleteModelSlot(index);
      setModelPool(asArray<AnyRecord>(result.pool?.models));
      setSelected(result);
      await refresh(true);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function saveConfigProfile() {
    await withBusy('config', async () => {
      const result = await api.agentSaveConfigProfile({
        name: profileName || '本地配置快照',
        note: profileNote,
        config: draft,
        include_secrets: false,
      });
      setConfigProfiles(asArray<AnyRecord>(result.profiles));
      setSelected(result.profile || result);
      if (!profileName.trim()) setProfileName('本地安全默认配置');
    });
  }

  async function applyConfigProfile(id: string) {
    if (!id) return;
    const ok = window.confirm('应用这个配置快照？当前 API Key 会保留，其他配置会切换到快照状态。');
    if (!ok) return;
    await withBusy('config', async () => {
      const result = await api.agentApplyConfigProfile(id, true);
      setSelected(result);
      if (result?.config) {
        setServerConfig((result.config || {}) as AgentConfig);
      }
      draftDirtyRef.current = false;
      setDraftDirty(false);
      await refresh(true);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function deleteConfigProfile(id: string) {
    if (!id) return;
    const ok = window.confirm('删除这个配置快照？不会影响当前运行配置。');
    if (!ok) return;
    await withBusy('config', async () => {
      const result = await api.agentDeleteConfigProfile(id);
      setConfigProfiles(asArray<AnyRecord>(result.profiles));
      setSelected(result);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  function loadPersonaRecordToDraft(record: PersonaHistoryRecord) {
    const nextDraft = {
      ...draft,
      persona_name: String(record.persona_name || record.name || ''),
      persona_text: String(record.persona_text || ''),
      diary_seed: String(record.diary_seed || ''),
      system_note: String(record.system_note || ''),
    } as AgentConfig;
    setPersonaHistoryEditingId(String(record.id || ''));
    draftDirtyRef.current = true;
    setDraftDirty(true);
    setDraft(nextDraft);
    setSelected({ event: 'persona_history_loaded_to_draft', record });
  }

  async function savePersonaHistory(forceNew = false) {
    await withBusy('config', async () => {
      const result = await api.agentSavePersonaHistory({
        id: forceNew ? '' : personaHistoryEditingId,
        name: String(draft.persona_name || '').trim() || '当前人设',
        persona_name: String(draft.persona_name || '').trim(),
        persona_text: String(draft.persona_text || '').trim(),
        diary_seed: String(draft.diary_seed || '').trim(),
        system_note: String(draft.system_note || '').trim(),
        note: forceNew ? '来自配置页另存为新记录' : '来自配置页手动保存',
      });
      setPersonaHistory(asArray<PersonaHistoryRecord>(result.records));
      setPersonaHistoryEditingId(String(result?.record?.id || (forceNew ? '' : personaHistoryEditingId) || ''));
      setSelected(result.record || result);
      await refreshPersonaHistoryAndProgress().catch(() => undefined);
    });
  }

  async function applyPersonaHistory(id: string) {
    if (!id) return;
    const ok = window.confirm('快速应用这条历史人设？会直接覆盖当前草稿中的人设名称、正文、日记种子和系统注释。');
    if (!ok) return;
    await withBusy('config', async () => {
      const result = await api.agentApplyPersonaHistory(id);
      setPersonaHistory(asArray<PersonaHistoryRecord>(result.records));
      if (result?.config) {
        const nextConfig = { ...emptyConfig, ...(result.config || {}), api_key: '' } as AgentConfig;
        setServerConfig(nextConfig);
        setDraft(nextConfig);
        draftDirtyRef.current = false;
        setDraftDirty(false);
      }
      setPersonaHistoryEditingId(id);
      setSelected(result.record || result);
      await refreshPersonaHistoryAndProgress().catch(() => undefined);
    });
  }

  async function deletePersonaHistory(id: string) {
    if (!id) return;
    const row = personaHistory.find((item) => String(item.id || '') === id);
    const ok = window.confirm(`删除这条历史人设？\n${String(row?.name || row?.persona_name || id)}`);
    if (!ok) return;
    await withBusy('config', async () => {
      const result = await api.agentDeletePersonaHistory(id);
      setPersonaHistory(asArray<PersonaHistoryRecord>(result.records));
      if (personaHistoryEditingId === id) {
        setPersonaHistoryEditingId('');
      }
      setSelected(result);
      await refreshPersonaHistoryAndProgress().catch(() => undefined);
    });
  }

  async function saveUserProgressLoadout(payload: { current_title_id?: string; equipped_badge_ids?: string[] }) {
    const now = Date.now();
    const optimistic = {
      ...((userProgress && typeof userProgress === 'object') ? userProgress : {}),
      ...(payload.current_title_id !== undefined ? { current_title_id: payload.current_title_id } : {}),
      ...(payload.equipped_badge_ids !== undefined ? { equipped_badge_ids: payload.equipped_badge_ids } : {}),
      updated_at_ms: now,
      generated_at_ms: now,
    } as AnyRecord;
    userProgressOverrideUpdatedAtRef.current = asNumber(optimistic.updated_at_ms, Date.now());
    userProgressLocalOverrideRef.current = optimistic;
    setUserProgressLocalOverride(optimistic);
    setUserProgress(optimistic);
    await withBusy('config', async () => {
      const result = await api.agentUpdateUserProgressLoadout(payload);
      const next = (result?.progress || result) as AnyRecord;
      if (next && typeof next === 'object') {
        userProgressOverrideUpdatedAtRef.current = asNumber(next.updated_at_ms, userProgressOverrideUpdatedAtRef.current);
        userProgressLocalOverrideRef.current = next;
        setUserProgressLocalOverride(next);
        setUserProgress(next);
        setSelected(next);
      } else {
        await refreshPersonaHistoryAndProgress().catch(() => undefined);
      }
    });
  }

  async function bootstrap() {
    await withBusy('background', async () => {
      const result = await api.agentBootstrap();
      setSelected(result);
      await refresh(true);
      api.agentAcceptance().then(setAcceptance).catch(() => undefined);
    });
  }

  async function send(overrideText?: string) {
    const text = (overrideText ?? input).trim();
    if (!text) return;
    const createdAt = Date.now();
    const clientMessageId = `local_msg_${createdAt}_${Math.random().toString(36).slice(2, 8)}`;
    const optimisticMessage: PendingMessage = {
      id: clientMessageId,
      turn_id: '',
      role: 'user',
      text,
      source: 'local_chat',
      attachments: attachmentDraft.slice(0, 12),
      created_at_ms: createdAt,
    };
    if (!overrideText) setInput('');
    setPendingMessages((prev) => [...prev, optimisticMessage].slice(-24));
    setSending(true);
    setBusyScope('send', true);
    try {
      const attachments = [
        ...attachmentDraft,
        ...(await Promise.all(fileDraft.map((file) => summarizeLocalFile(file)))),
      ];
      if (attachmentNote.trim()) {
        for (const item of attachments) {
          item.summary = [item.summary, attachmentNote.trim()].filter(Boolean).join(' | ');
          item.text_preview = item.summary;
        }
      }
      const optimisticAttachments = attachments.map((item) => ({ ...item }));
      setImagePreviewMap((prev) => {
        const next = { ...prev };
        optimisticAttachments.forEach((item) => {
          const url = String(item.data_url || item.preview_url || '');
          if (url) next[attachmentPreviewKey(item)] = url;
        });
        return next;
      });
      const payloadAttachments = attachments.map((item) => {
        const next = { ...item };
        delete next.data_url;
        delete next.preview_url;
        return next;
      });
      const result = await api.agentMessage({
        text,
        source: 'local_chat',
        attachments: payloadAttachments,
        _client_message_id: clientMessageId,
        _pre_thought_ticks_override: Math.max(0, Math.min(40, Number(sendPreTicks) || 0)),
        _post_thought_ticks_override: Math.max(0, Math.min(20, Number(sendPostTicks) || 0)),
        _run_ap_while_waiting_llm: Boolean(sendWaitTicks),
      });
      const queuedJob = (result?.job || null) as AgentJob | null;
      setFileDraft([]);
      setAttachmentDraft([]);
      setAttachmentNote('');
      setAttachmentPreview(null);
      if (queuedJob) {
        setActiveJob(queuedJob);
        setAgentJobs((prev) => [queuedJob, ...prev.filter((item) => String(item.job_id || '') !== String(queuedJob.job_id || ''))].slice(0, 24));
        setSelected(queuedJob);
      } else {
        setSelected(result.turn || result);
      }
      await refresh(true);
    } finally {
      setBusyScope('send', false);
      setSending(false);
    }
  }

  async function stopActiveThinking() {
    const jobId = String(activeJob?.job_id || '');
    await withBusy('background', async () => {
      const result = await api.agentStopJob(jobId || undefined);
      const job = (result?.job || null) as AgentJob | null;
      const bg = (result?.background || null) as AnyRecord | null;
      if (bg) setBackground(bg);
      if (job) {
        setActiveJob(job);
        setAgentJobs((prev) => [job, ...prev.filter((item) => String(item.job_id || '') !== String(job.job_id || ''))].slice(0, 24));
        setSelected({ event: 'agent_stop_requested', ...result });
      } else {
        setSelected({ event: 'agent_stop_requested', ...result });
      }
    });
  }

  function pokeAgent() {
    void send('戳一戳');
  }

  function applyScenarioPreset(scenario: AgentScenarioPreset) {
    setInput(scenario.text);
    setAbText(scenario.text);
    if (scenario.attachmentSummary) {
      const attachment = {
        id: `scenario_${scenario.id}_${Date.now()}`,
        kind: scenario.id.includes('image') ? 'image' : 'text',
        name: scenario.label,
        text: scenario.attachmentSummary,
        summary: scenario.attachmentSummary,
        text_preview: scenario.attachmentSummary,
      };
      setAttachmentDraft((prev) => [...prev, attachment]);
      setAttachmentNote(scenario.attachmentSummary);
      setAttachmentPreview(null);
    } else {
      setAttachmentNote('');
      setAttachmentPreview(null);
    }
  if (scenario.promptNote) {
      setDraftEditable((prev) => ({ ...prev, prompt_extra_note: scenario.promptNote || prev.prompt_extra_note || '' }));
    }
    setSelected({ event: 'scenario_loaded', ...scenario, safe: '已填入对话框和实验文本；尚未发送，不会写 PA 历史。' });
  }

  async function previewScenarioPreset(scenario: AgentScenarioPreset) {
    await withBusy('prompt', async () => {
      const result = await api.agentPromptPreview({ text: scenario.text, thought_index: 0, scenario: scenario.id });
      setPromptPreview(result);
      setAbText(scenario.text);
      setSelected({ event: 'scenario_prompt_preview', scenario, preview: result, safe: 'Prompt 预览是沙盒路径，不写 PA 历史。' });
    });
  }

  async function scoreScenarioPreset(scenario: AgentScenarioPreset) {
    await withBusy('prompt', async () => {
      const result = await api.agentPromptAb({
        text: scenario.text,
        variants: ['balanced', 'warm', 'concise', 'analytical'],
        prompt_extra_note: scenario.promptNote || draft.prompt_extra_note || '',
        scenario_id: scenario.id,
        scenario_label: scenario.label,
        scenario_badge: scenario.badge,
        scenario_goal: scenario.goal,
      });
      const row = {
        ...result,
        scenario_id: scenario.id,
        scenario_label: scenario.label,
        scenario_badge: scenario.badge,
        scenario_goal: scenario.goal,
      };
      setAbResult(result);
      setScenarioScores((prev) => [row, ...prev.filter((item) => item.scenario_id !== scenario.id)].slice(0, 8));
      setSelected({ event: 'scenario_score', scenario, result, safe: 'A/B 探针是沙盒路径；会写 prompt experiment 诊断日志，但不写 PA 对话历史。' });
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function scoreAllScenarios() {
    await withBusy('prompt', async () => {
      const rows: AnyRecord[] = [];
      for (const scenario of agentScenarioPresets) {
        const result = await api.agentPromptAb({
          text: scenario.text,
          variants: ['balanced', 'warm', 'concise', 'analytical'],
          prompt_extra_note: scenario.promptNote || draft.prompt_extra_note || '',
          scenario_id: scenario.id,
          scenario_label: scenario.label,
          scenario_badge: scenario.badge,
          scenario_goal: scenario.goal,
        });
        rows.push({
          ...result,
          scenario_id: scenario.id,
          scenario_label: scenario.label,
          scenario_badge: scenario.badge,
          scenario_goal: scenario.goal,
        });
      }
      setScenarioScores(rows);
      setAbResult(rows[0] || null);
      setSelected({ event: 'scenario_score_matrix', count: rows.length, rows, safe: '批量 A/B 探针不写 PA 对话历史，但会增加 prompt experiment 诊断日志。' });
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function previewAttachments() {
    await withBusy('tool', async () => {
      const attachments = [
        ...attachmentDraft,
        ...(await Promise.all(fileDraft.map((file) => summarizeLocalFile(file)))),
      ];
      if (attachmentNote.trim()) {
        attachments.push({ id: `note_preview_${Date.now()}`, kind: 'text', name: 'inline_attachment_note', text: attachmentNote.trim(), summary: attachmentNote.trim() });
      }
      const result = await api.agentAttachmentPreview({ text: input || '附件预览', attachments });
      setAttachmentPreview(result);
      setSelected(result);
    });
  }

  async function runTicks() {
    await withBusy('background', async () => {
      const result = await api.agentTicks(Number(manualTicks) || 1);
      setSelected(result);
      await refresh(true);
      api.agentAcceptance().then(setAcceptance).catch(() => undefined);
    });
  }

  async function backgroundStart() {
    await withBusy('background', async () => {
      const result = await api.agentBackgroundStart();
      setBackground(result);
      setSelected(result);
      await refresh(true);
    });
  }

  async function backgroundStop() {
    await withBusy('background', async () => {
      const result = await api.agentBackgroundStop();
      setBackground(result);
      setSelected(result);
      await refresh(true);
    });
  }

  async function backgroundStep() {
    await withBusy('background', async () => {
      const result = await api.agentBackgroundStep();
      setBackground(result.background || result);
      setSelected(result);
      await refresh(true);
    });
  }

  async function runTool() {
    await withBusy('tool', async () => {
      let args: Record<string, unknown> = {};
      try {
        args = toolArgs.trim() ? JSON.parse(toolArgs) : {};
      } catch {
        args = { text: toolArgs };
      }
      const result = await api.agentRunTool({ name: toolName, args, source: 'agent_page_manual_tool' });
      setSelected(result);
      await refresh(true);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function importBook() {
    await withBusy('tool', async () => {
      const path = String(bookImportDraft.path || '').trim();
      const result = await api.agentImportBook({
        path,
        title: String(bookImportDraft.title || '').trim(),
        summary: String(bookImportDraft.summary || '').trim(),
        text: path ? '' : String(bookImportDraft.text || kbText || '').trim(),
      });
      setSelected(result);
      const payload = await api.agentLibrary(false).catch(() => null);
      if (payload) setLibrary(payload);
      if (result?.book) setSelectedBook(result.book);
      await refresh(true);
    });
  }

  async function refreshLibrary(selectResult = false) {
    await withBusy('tool', async () => {
      const result = await api.agentLibrary(false);
      setLibrary(result);
      if (selectResult) setSelected(result);
    });
  }

  async function selectLibraryBook(book: AnyRecord) {
    const id = String(book.id || '').trim();
    if (!id) return;
    await withBusy('tool', async () => {
      const result = await api.agentLibrary(true, id);
      const detail = asArray<AnyRecord>(result.books)[0] || result.book || book;
      setSelectedBook(detail);
      setSelectedLibraryReview(asArray<AnyRecord>(detail.reviews)[0] || null);
      setSelectedLibraryOriginal(null);
      setSelected(detail);
    });
  }

  async function pickLibraryFile() {
    await withBusy('tool', async () => {
      const result = await api.agentPickLibraryFile();
      setSelected(result);
      if (result?.ok && result?.path) {
        setBookImportDraft((prev) => ({
          ...prev,
          path: String(result.path || ''),
          title: String(result.title || prev.title || ''),
        }));
      }
      await refreshToolEvents(false).catch(() => undefined);
    });
  }

  async function suggestLibrarySummary() {
    await withBusy('tool', async () => {
      const path = String(bookImportDraft.path || '').trim();
      const result = await api.agentSuggestLibrarySummary({
        path,
        title: String(bookImportDraft.title || '').trim(),
        text: path ? '' : String(bookImportDraft.text || kbText || '').trim(),
      });
      setSelected(result);
      if (result?.summary) {
        setBookImportDraft((prev) => ({
          ...prev,
          title: String(result.title || prev.title || ''),
          summary: String(result.summary || ''),
        }));
      }
      await refreshToolEvents(false).catch(() => undefined);
    });
  }

  async function readLibraryBook(mode = 'read') {
    const id = String((selectedBook || {}).id || '').trim();
    if (!id) return;
    await withBusy('tool', async () => {
      const result = await api.agentReadBook({ book_id: id, mode, chars: Number(draft.library_chunk_target_chars ?? 30), ticks: Number(draft.library_after_chunk_ticks ?? 6) });
      setSelected(result);
      if (mode === 'original' && result?.ok) {
        setSelectedLibraryOriginal({
          book_id: id,
          title: String(result?.book?.title || selectedBook?.title || id),
          range: result?.range || {},
          text: String(result?.text || ''),
          summary: String(result?.summary || ''),
        });
      } else if (mode === 'reviews') {
        setSelectedLibraryOriginal(null);
      } else if (mode === 'read' || mode === 'stop') {
        setSelectedLibraryOriginal(null);
      }
      if (result?.book) {
        const detail = await api.agentLibrary(true, id).catch(() => null);
        const detailBook = asArray<AnyRecord>(detail?.books)[0] || detail?.book || result.book;
        setSelectedBook(detailBook);
        if (result?.review) setSelectedLibraryReview(result.review);
      }
      const payload = await api.agentLibrary(false).catch(() => null);
      if (payload) setLibrary(payload);
      await refreshToolEvents(false).catch(() => undefined);
      await refresh(true);
    });
  }

  async function selectLibraryReview(review: AnyRecord) {
    const bookId = String((selectedBook || {}).id || review.book_id || '').trim();
    const reviewId = String(review.id || '').trim();
    if (!bookId || !reviewId) {
      setSelectedLibraryReview(review);
      setSelectedLibraryOriginal(null);
      return;
    }
    await withBusy('tool', async () => {
      const result = await api.agentReadBook({ book_id: bookId, mode: 'reviews', ids: [reviewId], detail: true });
      const detail = asArray<AnyRecord>(result?.reviews)[0] || review;
      setSelectedLibraryReview(detail);
      setSelectedLibraryOriginal(null);
    });
  }

  async function deleteLibraryBook(book?: AnyRecord) {
    const id = String((book || selectedBook || {}).id || '').trim();
    if (!id) return;
    const ok = window.confirm(`删除这本书及其图书馆文件？\n${String((book || selectedBook || {}).title || id)}`);
    if (!ok) return;
    await withBusy('tool', async () => {
      const result = await api.agentDeleteBook(id);
      setSelected(result);
      setSelectedBook(null);
      setSelectedLibraryReview(null);
      setSelectedLibraryOriginal(null);
      const payload = await api.agentLibrary(false).catch(() => null);
      if (payload) setLibrary(payload);
    });
  }

  async function refreshRuntimePackages(selectResult = false) {
    await withBusy('maintenance', async () => {
      const result = await api.agentRuntimePackages();
      setRuntimePackages(result);
      if (selectResult) setSelected(result);
    });
  }

  async function exportRuntimePackage() {
    await withBusy('maintenance', async () => {
      const result = await api.agentExportRuntimePackage(runtimePackageDraft);
      setSelected(result);
      const payload = await api.agentRuntimePackages().catch(() => null);
      if (payload) setRuntimePackages(payload);
      await refreshSystemEvents(false).catch(() => undefined);
    });
  }

  async function importRuntimePackage(pathOverride = '') {
    const path = String(pathOverride || runtimePackageDraft.path || '').trim();
    if (!path) return;
    const ok = window.confirm('导入运行包会先自动备份当前 AP/PA 运行数据，然后按选择的策略合并。遇到覆盖策略可能改写本地长期记忆，确认继续？');
    if (!ok) return;
    await withBusy('maintenance', async () => {
      const result = await api.agentImportRuntimePackage({ ...runtimePackageDraft, path });
      setSelected(result);
      const [packagesPayload, libraryPayload] = await Promise.all([
        api.agentRuntimePackages().catch(() => null),
        api.agentLibrary(false).catch(() => null),
      ]);
      if (packagesPayload) setRuntimePackages(packagesPayload);
      if (libraryPayload) setLibrary(libraryPayload);
      await refreshSystemEvents(false).catch(() => undefined);
      await refresh(true);
    });
  }

  async function clear(clearApRuntime = false) {
    const ok = window.confirm(clearApRuntime ? '危险操作：清空 PA 对话/想法/turn 历史，并清理当前 AP 运行态。这个动作不能从页面撤销，继续？' : '危险操作：清空 PA 对话、想法和 turn 历史。AP 运行态不会清理，但 PA 历史不能从页面撤销，继续？');
    if (!ok) return;
    await withBusy('history', async () => {
      const result = await api.agentClear(clearApRuntime);
      setPendingMessages([]);
      setAgentJobs([]);
      setActiveJob(null);
      setStatus((prev) => ({
        ...(prev || {}),
        messages: [],
        thoughts: [],
        turns: [],
        snapshots: [],
        session: {
          ...((prev || {}).session || {}),
          message_count: 0,
          thought_count: 0,
          turn_count: 0,
          snapshot_count: 0,
        },
      }));
      setSelected(result);
      await refresh(true);
    });
  }

  async function resetApRuntime(scope: 'runtime' | 'hdb' | 'all') {
    const copy = {
      runtime: {
        title: '清空 AP 运行态？',
        body: '这会清掉状态池、注意力、行动、情绪等短期运行态，相当于让 AP 忘掉当前这一轮短期上下文；PA 对话记录和 HDB 长期记忆会保留。',
        run: api.clearRuntime,
      },
      hdb: {
        title: '清空 HDB 长期库？',
        body: '这会清掉 HDB 里的长期结构、情节记忆和理解积累。适合更换人设后彻底重开，但不能从页面撤销。',
        run: api.clearHdb,
      },
      all: {
        title: '清空 AP 运行态 + HDB？',
        body: '这会同时清空短期运行态和长期 HDB。相当于给 AP 做一次完整重置，适合换人设重新开始，操作不可撤销。',
        run: api.clearAll,
      },
    }[scope];
    const ok = window.confirm(`${copy.title}\n\n${copy.body}\n\n确认继续？`);
    if (!ok) return;
    await withBusy('maintenance', async () => {
      const result = await copy.run();
      setStatus((prev) => ({
        ...(prev || {}),
        snapshots: [],
        ap_packet: {},
      }));
      setSnapshotPage(null);
      setSelected({
        mode: `ap_${scope}_reset`,
        summary: copy.title.replace('？', '完成'),
        result,
      });
      await Promise.all([
        refresh(true),
        refreshSnapshotHistory().catch(() => null),
        refreshDiagnostics().catch(() => null),
      ]);
    });
  }

  async function polishPersona() {
    setPolishBusy(true);
    try {
      const result = await api.agentPersonaPolish({
        persona_name: draft.persona_name,
        persona_text: draft.persona_text,
        diary_seed: draft.diary_seed,
        system_note: draft.system_note,
      });
      setDraftEditable((prev) => ({
        ...prev,
        persona_name: result.persona_name || prev.persona_name,
        persona_text: result.persona_text || prev.persona_text,
        diary_seed: result.diary_seed || prev.diary_seed,
        system_note: result.system_note || prev.system_note,
      }));
      setSelected({ event: 'persona_polished', ...result, safe: '已写入配置草稿；确认后点击保存配置。' });
    } finally {
      setPolishBusy(false);
    }
  }

  async function maintainLogs(mode: 'trim' | 'clear', dryRun = false) {
    const targets = ['outbox', 'experiments', 'wake_previews', 'wake_matrix', 'selftests', 'morning_checks', 'llm_api_events'];
    const ok = dryRun || window.confirm(mode === 'clear' ? '危险操作：清空 outbox / A-B / wake trace / wake matrix / selftest / morning / LLM API 等诊断日志。不会清 PA 对话和 AP 运行态，但诊断历史不能从页面撤销，继续？' : `裁剪诊断日志：只保留最近 ${Number(logKeep) || 120} 条。不会清 PA 对话和 AP 运行态，继续？`);
    if (!ok) return;
    await withBusy('log', async () => {
      const result = await api.agentMaintainLogs({
        mode,
        dry_run: dryRun,
        keep: Number(logKeep) || 120,
        targets,
      });
      setSelected(result);
      const plan = await api.agentLogPlan(Number(logKeep) || 120).catch(() => null);
      if (plan) setLogPlan(plan);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function previewWake() {
    await withBusy('wake', async () => {
      const result = await api.agentWakePreview({
        adapter: 'napcat_qq',
        message_type: wakeMessageType,
        text: wakeText,
        group_id: wakeMessageType === 'group' ? '10001' : '',
        user_id: '20002',
        mentions: csvToList(wakeMentions),
      });
      setSelected(result);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function previewNapcatEvent() {
    await withBusy('wake', async () => {
      const mentions = csvToList(wakeMentions);
      const message = [
        ...mentions.map((mention) => ({ type: 'at', data: { qq: mention } })),
        { type: 'text', data: { text: napcatText || wakeText } },
      ];
      const result = await api.agentWakePreview({
        adapter: 'napcat_qq',
        post_type: 'message',
        message_type: wakeMessageType,
        group_id: wakeMessageType === 'group' ? '10001' : '',
        user_id: '20002',
        message,
      });
      setSelected(result);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function runWakeMatrix() {
    await withBusy('wake', async () => {
      const result = await api.agentWakeMatrix({});
      setWakeMatrix(result);
      setSelected(result);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function refreshWakePolicy(selectResult = true) {
    await withBusy('wake', async () => {
      const result = await api.agentWakePolicy();
      setWakePolicy(result);
      if (selectResult) setSelected(result);
    });
  }

  async function refreshNapcatGuide() {
    await withBusy('napcat', async () => {
      const [result, policy, adapterPayload] = await Promise.all([
        api.agentNapcatGuide(),
        api.agentWakePolicy().catch(() => null),
        api.agentAdapterEvents(160, adapterLogView).catch(() => null),
      ]);
      setNapcatGuide(result);
      if (policy) setWakePolicy(policy);
      if (adapterPayload) {
        setAdapterEvents(asArray<AnyRecord>(adapterPayload.events));
        setAdapterEventCounts((adapterPayload.counts || {}) as AnyRecord);
      }
      setSelected(result);
    });
  }

  async function launchNapcat() {
    await withBusy('napcat', async () => {
      const result = await api.agentNapcatLaunch();
      setSelected(result);
      const guide = await api.agentNapcatGuide().catch(() => null);
      if (guide) setNapcatGuide(guide);
      await refreshAdapterEvents(false).catch(() => undefined);
      if (result?.webui_url) {
        window.open(String(result.webui_url), '_blank', 'noopener,noreferrer');
      }
    });
  }

  async function runSelftest() {
    await withBusy('diag', async () => {
      const result = await api.agentRunSelftest({ include_samples: true });
      setSelftest(result);
      setSelected(result);
      const history = await api.agentSelftests(20).catch(() => null);
      if (history) setSelftestHistory(asArray<AnyRecord>(history.runs));
      api.agentAcceptance().then(setAcceptance).catch(() => undefined);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function runMorningCheck() {
    await withBusy('diag', async () => {
      const result = await api.agentRunMorningCheck({ run_selftest: true, include_samples: true });
      setMorningCheck(result);
      setSelected(result);
      if (result.acceptance) setAcceptance(result.acceptance);
      if (result.selftest) setSelftest(result.selftest);
      const [selfHistory, morningRuns] = await Promise.all([
        api.agentSelftests(20).catch(() => null),
        api.agentMorningChecks(20).catch(() => null),
      ]);
      if (selfHistory) setSelftestHistory(asArray<AnyRecord>(selfHistory.runs));
      if (morningRuns) setMorningHistory(asArray<AnyRecord>(morningRuns.runs));
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function simulateNapcat() {
    const ok = window.confirm('NapCat 模拟会走完整 adapter 入口；如果命中唤醒，会写入 PA 对话历史并运行 AP tick。继续？');
    if (!ok) return;
    await withBusy('napcat', async () => {
      const mentions = csvToList(wakeMentions);
      const message = [
        ...mentions.map((mention) => ({ type: 'at', data: { qq: mention } })),
        { type: 'text', data: { text: napcatText } },
      ];
      const result = await api.agentNapcatEvent({
        adapter: 'napcat_qq',
        post_type: 'message',
        message_type: wakeMessageType,
        group_id: wakeMessageType === 'group' ? '10001' : '',
        user_id: '20002',
        message,
      });
      setSelected(result);
      await refresh(true);
      await refreshAdapterEvents(false).catch(() => undefined);
    });
  }

  async function testNapcatReply() {
    await withBusy('napcat', async () => {
      const result = await api.agentAdapterReply({
        event: {
          adapter: 'napcat_qq',
          message_type: 'group',
          group_id: '10001',
          user_id: '20002',
        },
        text: replyText,
      });
      setSelected(result);
      await refreshDiagnostics().catch(() => undefined);
      await refreshAdapterEvents(false).catch(() => undefined);
    });
  }

  async function loadThoughtPage(nextOffset: number) {
    await withBusy('history', async () => {
      const result = await api.agentHistory('thoughts', 8, Math.max(0, nextOffset));
      setThoughtOffset(Math.max(0, nextOffset));
      setThoughtPage(result);
      setSelected(result);
    });
  }

  async function runPromptAb() {
    await withBusy('prompt', async () => {
      const result = await api.agentPromptAb({
        text: abText,
        variants: ['balanced', 'warm', 'concise', 'analytical'],
        prompt_extra_note: draft.prompt_extra_note || '',
      });
      setAbResult(result);
      setSelected(result);
      await refreshDiagnostics().catch(() => undefined);
    });
  }

  async function previewPrompt() {
    await withBusy('prompt', async () => {
      const result = await api.agentPromptPreview({ text: abText, thought_index: 0 });
      setPromptPreview(result);
      setSelected(result);
    });
  }

  async function applyPromptVariant(variant: unknown) {
    const value = String(variant || '').trim();
    if (!value) return;
    setDraftEditable((prev) => ({ ...prev, prompt_variant: value }));
    setSelected({ event: 'apply_prompt_variant_preview', prompt_variant: value, note: '已写入左侧配置草稿，点击“保存配置”后生效。' });
  }

  const liveActiveJob = isLiveAgentJob(activeJob) ? activeJob : null;
  const recentFinishedJob = !liveActiveJob && activeJob ? activeJob : null;
  const packet = (status?.ap_packet || {}) as AnyRecord;
  const backgroundPacket = ((background?.last_result || {}) as AnyRecord).ap_packet || {};
  const livePacket = pickFresherPacket(liveActiveJob?.ap_packet || {}, backgroundPacket, packet);
  const liveTickCounter = Math.max(0, asNumber(livePacket.tick_counter ?? packet.tick_counter, 0));
  const summary = livePacket.summary || packet.summary || {};
  const messages = asArray<AnyRecord>(status?.messages);
  const activeJobs = asArray<AgentJob>(agentJobs).filter(isLiveAgentJob);
  const recentJobPool = asArray<AgentJob>(agentJobs).slice(0, 8);
  const visibleJobPool = activeJobs.length ? mergeLiveRecords(activeJobs, recentJobPool.slice(0, 3), 'job') : recentJobPool.slice(0, 6);
  const jobUserMessageRows = visibleJobPool.flatMap(jobUserMessages);
  const jobReplyMessageRows = visibleJobPool.flatMap(jobReplyMessages);
  const liveMessages = useMemo(
    () => {
      const additions = [
        ...pendingMessages,
        ...jobUserMessageRows,
        ...jobReplyMessageRows,
      ].filter((item): item is AnyRecord => Boolean(item && typeof item === 'object' && (String(item.text || '').trim() || asArray<AnyRecord>(item.attachments).length)))
        .filter((item) => !hasSimilarVisibleMessage(messages, item));
      return mergeLiveRecords(messages, additions, 'message').sort((a, b) => asNumber(a.created_at_ms, 0) - asNumber(b.created_at_ms, 0));
    },
    [messages, pendingMessages, jobUserMessageRows, jobReplyMessageRows],
  );
  const replyAuditById = useMemo(() => {
    const map = new Map<string, AnyRecord>();
    asArray<AnyRecord>(replyActionAudit?.rows).forEach((row) => {
      const id = String(row.id || '');
      if (id) map.set(id, row);
    });
    return map;
  }, [replyActionAudit]);
  const debtMessageCount = useMemo(() => messages.filter((item) => {
    const auditRow = replyAuditById.get(String(item.id || ''));
    return Boolean(auditRow?.is_duplicate || auditRow?.raw_leak);
  }).length, [messages, replyAuditById]);
  const thoughts = (thoughtPage ? asArray<AnyRecord>(thoughtPage.items) : asArray<AnyRecord>(status?.thoughts)).slice().reverse();
  const backgroundResult = (background?.last_result || {}) as AnyRecord;
  const backgroundThoughtResult = (backgroundResult.thought_result || {}) as AnyRecord;
  const liveThoughts = useMemo(
    () => {
      const additions = [
        ...asArray<AnyRecord>(activeJob?.thoughts),
        activeJob?.thought,
        ...asArray<AnyRecord>(backgroundThoughtResult?.thoughts),
        (backgroundThoughtResult?.thought && typeof backgroundThoughtResult.thought === 'object' ? backgroundThoughtResult.thought : null),
      ].filter((item): item is AnyRecord => Boolean(item && typeof item === 'object' && String(item.text || '').trim()));
      return mergeLiveRecords(additions, thoughts, 'thought')
        .sort((a, b) => asNumber(b.created_at_ms, 0) - asNumber(a.created_at_ms, 0));
    },
    [thoughts, activeJob?.thought, activeJob?.thoughts, backgroundThoughtResult],
  );
  const liveCloud = asArray<AnyRecord>(livePacket.object_cloud).length
    ? asArray<AnyRecord>(livePacket.object_cloud)
    : (asArray<AnyRecord>(livePacket.dominant_objects).length
      ? asArray<AnyRecord>(livePacket.dominant_objects)
      : asArray<AnyRecord>(livePacket.top_objects));
  const topObjects = asArray<AnyRecord>(livePacket.dominant_objects).length
    ? asArray<AnyRecord>(livePacket.dominant_objects)
    : asArray<AnyRecord>(livePacket.top_objects);
  const topMemory = asArray<AnyRecord>(livePacket.top_memory);
  const cfs = asArray<AnyRecord>(livePacket.cognitive_feelings);
  const ntRows = asArray<AnyRecord>(livePacket.emotion?.channels);
  const stickerRows = asArray<AnyRecord>(stickers?.stickers);
  const selectedStickerRows = asArray<AnyRecord>(stickers?.selected_for_prompt);
  const snapshots = (snapshotPage ? asArray<AnyRecord>(snapshotPage.items) : asArray<AnyRecord>(status?.snapshots));
  const apTickSnapshots = useMemo(() => {
    const rows = snapshots.filter((item) => String(item.kind || '') === 'ap_tick');
    return rows.length ? rows : snapshots;
  }, [snapshots]);
  const latestCloudSnapshot = useMemo(() => snapshots.slice().reverse().find((item) => {
    return asArray<AnyRecord>(item.dominant_objects).length || asArray<AnyRecord>(item.top_memory).length;
  }) || null, [snapshots]);
  const historicalCloud = useMemo<AnyRecord[]>(() => {
    if (!latestCloudSnapshot) return [];
    const seen = new Set<string>();
    return [
      ...asArray<AnyRecord>(latestCloudSnapshot.dominant_objects),
      ...asArray<AnyRecord>(latestCloudSnapshot.top_memory),
    ].filter((item, index) => {
      const key = String(item.id || item.display || index);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).map((item, index) => ({
      ...item,
      rank: asNumber(item.rank, index + 1),
      size: asNumber(item.size, Math.max(18, Math.min(58, asNumber(item.total_energy, 0) * 0.65))),
      historical_snapshot: true,
      snapshot_id: latestCloudSnapshot.id,
      snapshot_tick: latestCloudSnapshot.tick_counter,
    }));
  }, [latestCloudSnapshot]);
  const cloud: AnyRecord[] = liveCloud.length ? liveCloud : historicalCloud;
  const cloudIsHistorical = liveCloud.length === 0 && historicalCloud.length > 0;
  const initialDataLoading = status === null;
  const runtimeLooksEmpty = asNumber(summary.active_item_count, 0) <= 0 && liveCloud.length === 0 && liveTickCounter <= 0;
  const aggregatedCloud = useMemo(() => aggregateCloudItems(cloud), [cloud]);
  const cloudLayout = useMemo(() => {
    const source = clampCloudItemsForViewport(aggregatedCloud, cloudViewport.width, cloudViewport.height, 'compact');
    return cloudBubbleLayout(source, cloudViewport.width, cloudViewport.height, 'compact');
  }, [aggregatedCloud, cloudViewport.height, cloudViewport.width]);
  const cloudLayoutExpanded = useMemo(() => {
    const source = clampCloudItemsForViewport(aggregatedCloud, 1380, 860, 'expanded');
    return cloudBubbleLayout(source, 1380, 860, 'expanded');
  }, [aggregatedCloud]);
  useEffect(() => {
    const now = Date.now();
    const failureTtlMs = 60_000;
    const candidates = messages
      .flatMap((message) => asArray<AnyRecord>(message.attachments))
      .filter((att) => {
        const kind = String(att.kind || '').toLowerCase();
        if (kind !== 'image' && !String(att.mime_type || '').startsWith('image/') && !att.sticker_like) return false;
        const key = attachmentPreviewKey(att);
        if (!key || imagePreviewMap[key]) return false;
        const failedAt = imagePreviewFailureRef.current[key] || 0;
        if (failedAt && now - failedAt < failureTtlMs) return false;
        const direct = String(att.data_url || att.preview_url || att.image_url || att.url || '');
        return !isRenderableImageSrc(direct) || !direct.startsWith('data:image/');
      })
      .slice(0, 8);
    if (!candidates.length) return;
    let cancelled = false;
    api.agentAttachmentPreview({ text: '聊天图片预览', attachments: candidates })
      .then((result) => {
        if (cancelled) return;
        const previews = asArray<AnyRecord>(result?.previews);
        const normalized = asArray<AnyRecord>(result?.normalized);
        setImagePreviewMap((prev) => {
          const next = { ...prev };
          const seen = new Set<string>();
          previews.forEach((row, index) => {
            const src = String(row.src || '');
            const original = candidates[index] || normalized[index] || {};
            const key = attachmentPreviewKey(original);
            if (!key) return;
            seen.add(key);
            if (!isRenderableImageSrc(src)) {
              imagePreviewFailureRef.current[key] = Date.now();
              return;
            }
            next[key] = src;
            delete imagePreviewFailureRef.current[key];
          });
          candidates.forEach((att) => {
            const key = attachmentPreviewKey(att);
            if (key && !seen.has(key) && !next[key]) {
              imagePreviewFailureRef.current[key] = Date.now();
            }
          });
          return next;
        });
      })
      .catch(() => {
        const failedAt = Date.now();
        candidates.forEach((att) => {
          const key = attachmentPreviewKey(att);
          if (key) imagePreviewFailureRef.current[key] = failedAt;
        });
      });
    return () => {
      cancelled = true;
    };
  }, [messages, imagePreviewMap]);
  const paMetricRows = useMemo(() => agentSnapshotsToMetricRows(apTickSnapshots), [apTickSnapshots]);
  const paChartConfigs = useMemo(() => {
    const wanted = new Set(paChartConfigIds);
    return chartConfigs.filter((config) => wanted.has(config.id)).slice(0, 32);
  }, []);
  const paChartsBySection = useMemo(() => {
    return chartSections
      .map((section) => ({
        section,
        configs: paChartConfigs.filter((config) => config.section === section.id),
      }))
      .filter((item) => item.configs.length);
  }, [paChartConfigs]);
  const paChartSectionMap = useMemo(() => new Map<string, (typeof chartSections)[number]>(chartSections.map((section) => [section.id, section])), []);
  const selectedTickSnapshot = useMemo(() => {
    if (selected && (selected.kind === 'ap_tick' || selected.kind === 'packet' || selected.summary || selected.input_queue || selected.tick_id || selected.tick_counter !== undefined)) {
      return selected as AnyRecord;
    }
    return apTickSnapshots[apTickSnapshots.length - 1] || snapshots[snapshots.length - 1] || null;
  }, [apTickSnapshots, selected, snapshots]);
  const toolOptions = (tools.length ? tools : asArray<AnyRecord>(diagnostics?.tools)).map((item) => ({
    value: String(item.name || ''),
    label: `${item.label || item.name || '-'}${item.enabled === false ? ' / disabled' : ''}`,
    disabled: item.enabled === false,
  })).filter((item) => item.value);
  const latestSelftest = selftest || selftestHistory[selftestHistory.length - 1] || null;
  const latestSelftestStatus = String(latestSelftest?.overall || '').toLowerCase();
  const latestSelftestColor = latestSelftestStatus === 'pass' ? 'teal' : latestSelftestStatus === 'fail' ? 'red' : latestSelftestStatus === 'warn' ? 'yellow' : 'gray';
  const acceptanceReadiness = (acceptance?.readiness || {}) as AnyRecord;
  const acceptanceSelftest = (acceptance?.selftest || {}) as AnyRecord;
  const acceptanceSession = (acceptance?.session || {}) as AnyRecord;
  const acceptanceConfig = (acceptance?.config || {}) as AnyRecord;
  const adapterNapcatEnabled = Boolean(acceptanceConfig.qq_napcat_enabled ?? draft.qq_napcat_enabled);
  const adapterNapcatDryRun = (acceptanceConfig.qq_napcat_dry_run ?? draft.qq_napcat_dry_run) !== false;
  const readinessStatus = String(acceptanceReadiness.overall || readiness?.overall || 'unknown').toLowerCase();
  const acceptanceVerdict = String(acceptance?.verdict || '').toLowerCase();
  const acceptanceColor = acceptanceVerdict === 'needs_action' ? 'red' : acceptanceVerdict === 'safe_to_review' ? 'yellow' : acceptanceVerdict === 'ready' ? 'teal' : 'gray';
  const acceptanceLabel = String(acceptance?.label || (readinessStatus === 'fail' ? '需要处理' : readinessStatus === 'warn' ? '可安全验收' : 'ready'));
  const acceptanceIconIsFail = acceptanceVerdict === 'needs_action' || readinessStatus === 'fail';
  const acceptanceNotes = asArray<string>(acceptance?.expected_notes);
  const expectedWarns = acceptanceNotes.length ? acceptanceNotes : [
    !draft.llm_enabled ? 'LLM 未启用，当前使用本地 fallback thought' : `LLM ${draft.model || '已启用'}`,
    runtimeLooksEmpty ? 'AP 新进程状态池为空，注入种子后可观察对象云' : `AP tick ${formatCount(liveTickCounter)}，对象 ${formatCount(summary.active_item_count)}`,
    draft.qq_napcat_enabled ? `NapCat ${draft.qq_napcat_dry_run !== false ? 'dry-run' : 'live send'}` : 'NapCat disabled + dry-run，避免误发外部消息',
    background?.running ? `后台主观能动性运行中：${formatCount(background?.step_count)} steps` : '后台静默，挂机期间不主动写入对话历史',
  ];
  const latestSelftestReportStatus = String(acceptanceSelftest.overall || latestSelftestStatus || 'none').toLowerCase();
  const storageFiles = (diagnostics?.files || {}) as AnyRecord;
  const storageRows = ['state', 'events', 'outbox', 'experiments', 'wake_previews', 'wake_matrix', 'selftests', 'morning_checks', 'handoff', 'diagnostic_bundle']
    .map((key) => ({ key, info: (storageFiles[key] || {}) as AnyRecord }))
    .filter((row) => row.info.exists !== false && (row.info.bytes !== undefined || row.info.path));
  const storageTotalBytes = storageRows.reduce((sum, row) => sum + asNumber(row.info.bytes, 0), 0);
  const logPlanTargets = asArray<AnyRecord>(logPlan?.targets);
  const logPlanProtected = asArray<AnyRecord>(logPlan?.protected);
  const logPlanTotals = (logPlan?.totals || {}) as AnyRecord;
  const logPlanTrimLines = asNumber(logPlanTotals.would_trim_lines, 0);
  const logPlanTargetCount = asNumber(logPlanTotals.target_count, logPlanTargets.filter((row) => row.default_target).length);
  const integrationRows = asArray<AnyRecord>(integrations?.rows);
  const integrationCounts = ((integrations?.counts || {}) as AnyRecord);
  const integrationReadyLike = asNumber(integrationCounts.ready, 0) + asNumber(integrationCounts.dry_run, 0) + asNumber(integrationCounts.summary_only, 0);
  const protocolRows = asArray<AnyRecord>(protocolRegistry?.rows);
  const protocolCounts = ((protocolRegistry?.counts || {}) as AnyRecord);
  const protocolReadyLike = asNumber(protocolCounts.enabled, 0) + asNumber(protocolCounts.probe, 0);
  const latestWakeMatrix = wakeMatrix || wakeMatrixHistory[wakeMatrixHistory.length - 1] || null;
  const latestWakeCases = asArray<AnyRecord>(latestWakeMatrix?.cases);
  const latestWakeExpected = asNumber(latestWakeMatrix?.expected_count, latestWakeCases.length);
  const latestWakePassed = asNumber(latestWakeMatrix?.passed_count, 0);
  const latestWakeFailed = asNumber(latestWakeMatrix?.failed_count, Math.max(0, latestWakeExpected - latestWakePassed));
  const policyConfig = ((wakePolicy || napcatGuide?.current || acceptanceConfig || draft) as AnyRecord) || {};
  const policySummary = ((wakePolicy?.summary || {}) as AnyRecord);
  const policyCases = asArray<AnyRecord>(wakePolicy?.cases);
  const policyTriggerModes = normalizeTriggerModes(policyConfig.trigger_modes ?? draft.trigger_modes, policyConfig.trigger_mode ?? draft.trigger_mode, true);
  const policyTriggerMode = String(policyConfig.trigger_mode || draft.trigger_mode || policyTriggerModes[0] || 'private_all');
  const policyTriggerLabel = String(wakePolicy?.trigger_label || policyConfig.trigger_label || triggerModesLabel(policyTriggerModes, policyTriggerMode));
  const policyGroupNames = asArray<string>(policyConfig.group_at_names ?? draft.group_at_names);
  const policyWakeKeywords = asArray<string>(policyConfig.wake_keywords ?? draft.wake_keywords);
  const policyAllowGroupWithoutAt = Boolean(policyConfig.allow_group_without_at ?? draft.allow_group_without_at);
  const policyGroupTriggerAt = (policyConfig.group_trigger_at ?? draft.group_trigger_at) !== false;
  const policyGroupTriggerKeyword = (policyConfig.group_trigger_keyword ?? draft.group_trigger_keyword) !== false;
  const policyGroupTriggerProbability = asNumber(policyConfig.group_trigger_probability ?? draft.group_trigger_probability, 0);
  const policyAccessMode = String(policyConfig.qq_access_mode || draft.qq_access_mode || 'off');
  const policyPlatform = String(policyConfig.platform_adapter || draft.platform_adapter || 'local');
  const policyNapcatEnabled = Boolean(policyConfig.qq_napcat_enabled ?? draft.qq_napcat_enabled);
  const policyNapcatDryRun = (policyConfig.qq_napcat_dry_run ?? draft.qq_napcat_dry_run) !== false;
  const policyRisk = policyNapcatEnabled && !policyNapcatDryRun ? 'live' : policyNapcatEnabled ? 'dry_run' : 'local_safe';
  const policyRiskColor = policyRisk === 'live' ? 'red' : policyRisk === 'dry_run' ? 'yellow' : 'teal';
  const policyWebhook = String(napcatGuide?.webhook_url || '');
  const policyRows = [
    {
      label: '触发模式',
      value: policyTriggerLabel,
      note: policyTriggerModes.length ? `modes: ${policyTriggerModes.join(', ')}` : '所有自动唤醒入口都已关闭，仅保留手动/测试链路',
    },
    {
      label: '群聊门控',
      value: policyAllowGroupWithoutAt ? '群聊全量' : `${policyGroupTriggerAt ? '艾特' : ''}${policyGroupTriggerAt && policyGroupTriggerKeyword ? ' / ' : ''}${policyGroupTriggerKeyword ? '关键词' : ''}${policyGroupTriggerProbability > 0 ? ' / 概率' : ''}` || '关闭',
      note: policyAllowGroupWithoutAt ? '所有群消息都会进入 PA 判断' : shortText(policyGroupNames.length ? policyGroupNames.join(' / ') : '未设置群聊昵称', 72),
    },
    {
      label: '名单',
      value: accessModes.find((item) => item.value === policyAccessMode)?.label || policyAccessMode,
      note: policyAccessMode === 'whitelist' ? '只允许主人/白名单用户或群' : policyAccessMode === 'blacklist' ? '屏蔽黑名单用户或群' : '当前不做名单拦截',
    },
    {
      label: '唤醒词',
      value: formatCount(policyWakeKeywords.length),
      note: `${shortText(policyWakeKeywords.length ? policyWakeKeywords.join(' / ') : '未设置关键词', 60)} · 概率 ${formatNumber(policyGroupTriggerProbability, 2)}`,
    },
    {
      label: '实时策略',
      value: wakePolicy ? `${formatCount(policySummary.wake_count)} / ${formatCount(policySummary.case_count)}` : '未加载',
      note: wakePolicy ? `${formatCount(policySummary.quiet_count)} quiet · ${formatCount(policySummary.mismatch_count)} mismatch` : '刷新后显示当前只读规则',
    },
    {
      label: '矩阵',
      value: latestWakeMatrix ? `${formatCount(latestWakePassed)} / ${formatCount(latestWakeExpected)}` : '未运行',
      note: latestWakeMatrix ? `${latestWakeFailed > 0 ? '存在未通过用例' : '最近用例全部通过'} · ${timeLabel(latestWakeMatrix.ts)}` : '建议保存配置后跑一次触发矩阵',
    },
  ];

  const latestMorning = morningCheck || morningHistory[morningHistory.length - 1] || null;
  const latestMorningStatus = String(latestMorning?.overall || '').toLowerCase();
  const briefOverview = asArray<AnyRecord>(morningBrief?.overview);
  const briefCapabilities = asArray<AnyRecord>(morningBrief?.capabilities);
  const briefSafety = asArray<AnyRecord>(morningBrief?.safety);
  const briefActions = asArray<AnyRecord>(morningBrief?.next_actions);
  const briefPath = String(morningBrief?.files?.morning_brief?.path || storageFiles.morning_brief?.path || '');
  const briefReady = Boolean(morningBrief?.ok);
  const handoffReady = Boolean(handoff?.ok || storageFiles.handoff?.exists);
  const morningReviewCards = asArray<AnyRecord>(morningReview?.cards);
  const morningReviewActions = asArray<AnyRecord>(morningReview?.next_actions);
  const morningReviewSteps = asArray<string>(morningReview?.operator_steps);
  const morningReviewTone = String(morningReview?.tone || 'watch');
  const morningReviewColor = morningReviewTone === 'danger' ? 'red' : morningReviewTone === 'safe' ? 'teal' : 'yellow';
  const acceptanceReady = Boolean(acceptance?.ok);
  const selftestReady = latestSelftestStatus === 'pass' || latestSelftestStatus === 'warn';
  const wakeReady = Boolean(latestWakeMatrix && latestWakeFailed <= 0);
  const adapterSafe = !policyNapcatEnabled || policyNapcatDryRun;
  const morningReady = latestMorningStatus === 'pass' || latestMorningStatus === 'warn';
  const reviewSteps = [
    {
      id: 'acceptance',
      label: '验收结论',
      status: acceptanceReady ? acceptanceLabel : '未生成',
      color: acceptanceColor,
      note: acceptanceReady ? String(acceptance?.verdict || '-') : '等待 acceptance 报告',
    },
    {
      id: 'handoff',
      label: '交接包',
      status: handoffReady ? '已就绪' : '待写入',
      color: handoffReady ? 'teal' : 'gray',
      note: handoffReady ? '本地 handoff 可用于恢复上下文' : '建议先写入 compact handoff',
    },
    {
      id: 'morning',
      label: '晨检 / 自检',
      status: morningReady ? String(latestMorning?.overall || 'warn') : (selftestReady ? `selftest ${latestSelftestStatus}` : '待运行'),
      color: latestMorningStatus === 'fail' ? 'red' : (morningReady ? 'yellow' : (selftestReady ? latestSelftestColor : 'gray')),
      note: latestMorning ? `history ${latestMorning.history_unchanged ? 'clean' : 'changed'}` : '晨检会汇总自检和历史污染检查',
    },
    {
      id: 'wake',
      label: '触发矩阵',
      status: wakeReady ? '通过' : '待确认',
      color: wakeReady ? 'teal' : 'gray',
      note: latestWakeMatrix ? `${formatCount(latestWakePassed)} / ${formatCount(latestWakeExpected)} cases` : '可在触发页运行矩阵',
    },
    {
      id: 'adapter',
      label: '外部发送',
      status: adapterSafe ? (policyNapcatEnabled ? 'dry-run' : 'local safe') : 'live send',
      color: adapterSafe ? 'teal' : 'red',
      note: policyNapcatEnabled ? `NapCat ${policyNapcatDryRun ? 'dry-run' : 'live'}` : 'NapCat disabled',
    },
    {
      id: 'ap_runtime',
      label: 'AP 运行态',
      status: runtimeLooksEmpty ? '空态' : `tick ${formatCount(liveTickCounter)}`,
      color: runtimeLooksEmpty ? 'yellow' : 'teal',
      note: runtimeLooksEmpty ? '需要种子或少量 tick 才能观察对象云' : `objects ${formatCount(summary.active_item_count)}`,
    },
  ];
  const reviewBlocking = reviewSteps.filter((step) => step.color === 'red');
  const reviewPending = reviewSteps.filter((step) => step.color === 'gray');
  const reviewWarn = reviewSteps.filter((step) => step.color === 'yellow');
  const reviewLabel = reviewBlocking.length ? '需要处理' : reviewPending.length ? '待补齐' : reviewWarn.length ? '可安全验收' : 'ready';
  const reviewColor = reviewBlocking.length ? 'red' : reviewPending.length ? 'gray' : reviewWarn.length ? 'yellow' : 'teal';
  const reviewNextAction = reviewBlocking[0] || reviewPending[0] || reviewWarn[0] || reviewSteps[0];
  const replyLatest = (replyActionAudit?.latest_reply || {}) as AnyRecord;
  const replyHistoryDebt = (replyActionAudit?.history_debt || {}) as AnyRecord;
  const replyDebtCounts = (replyDebtPreview?.counts || {}) as AnyRecord;
  const replyDebtCandidateCount = replyDebtCounts.candidates ?? replyDebtCounts.candidate_count;
  const promptBudget = (promptContract?.budget || readiness?.prompt_budget || modelReadiness?.prompt_budget || {}) as AnyRecord;
  const handoffSnapshotRows = [
    {
      id: 'latest_reply',
      label: '最新回复',
      value: String(replyLatest.status || '待审计'),
      detail: asArray<string>(replyLatest.issues).length ? asArray<string>(replyLatest.issues).join(' / ') : '当前窗口 clean',
      color: replyLatest.status === 'fail' ? 'red' : replyLatest.status === 'pass' ? 'teal' : 'yellow',
      source: replyLatest,
    },
    {
      id: 'history_debt',
      label: '历史债务',
      value: `${formatCount(replyHistoryDebt.old_problem_reply_count)} 条`,
      detail: replyDebtPreview ? `预览 ${formatCount(replyDebtCandidateCount)} 条，warn ${formatCount(replyDebtCounts.warn)}` : String(replyHistoryDebt.status || '保留审计证据'),
      color: asNumber(replyHistoryDebt.old_problem_reply_count, 0) > 0 ? 'yellow' : 'teal',
      source: replyDebtPreview || replyHistoryDebt,
    },
    {
      id: 'prompt_budget',
      label: 'Prompt 预算',
      value: `${formatCount(promptBudget.estimated_tokens)} tokens`,
      detail: `LLM AP ${formatCount(promptBudget.ap_packet_chars)} chars / 诊断 ${formatCount(promptBudget.status_packet_chars)} chars`,
      color: promptBudgetColor(asNumber(promptBudget.estimated_tokens, 0)),
      source: promptContract || readiness || modelReadiness,
    },
    {
      id: 'ap_runtime',
      label: 'AP 运行态',
      value: runtimeLooksEmpty ? '空态' : `tick ${formatCount(liveTickCounter)}`,
      detail: runtimeLooksEmpty ? '需要注入种子或运行 tick' : `对象 ${formatCount(summary.active_item_count)} / cloud ${formatCount(cloud.length)}`,
      color: runtimeLooksEmpty ? 'yellow' : 'teal',
      source: packet,
    },
    {
      id: 'adapter_safety',
      label: '外部发送',
      value: adapterSafe ? (policyNapcatEnabled ? 'dry-run' : 'local safe') : 'live send',
      detail: `${policyPlatform} · ${background?.running ? 'background running' : 'background stopped'}`,
      color: adapterSafe ? 'teal' : 'red',
      source: { policyConfig, background },
    },
  ];

  const visibleMessages = liveMessages.filter((item) => {
    const role = String(item.role || '');
    return role === 'user' || role === 'assistant' || role === 'bot';
  });
  const displayVisibleMessages = useMemo(
    () => expandReplySegmentsForDisplay(visibleMessages, serverConfig || draft),
    [visibleMessages, serverConfig, draft],
  );
  const displayMessages = useMemo(
    () => expandReplySegmentsForDisplay(messages, serverConfig || draft),
    [messages, serverConfig, draft],
  );
  const lastVisibleMessage = displayVisibleMessages[displayVisibleMessages.length - 1] || null;
  const latestVisibleMessageKey = lastVisibleMessage
    ? `${displayVisibleMessages.length}:${String(lastVisibleMessage.id || lastVisibleMessage.created_at_ms || '')}:${String(lastVisibleMessage.text || '').length}`
    : '0';
  useEffect(() => {
    if (agentTab !== 'home' || !chatAutoFollowRef.current) return undefined;
    const raf = window.requestAnimationFrame(() => {
      const viewport = chatViewportRef.current;
      if (!viewport) return;
      viewport.scrollTop = viewport.scrollHeight;
      updateChatAutoFollow();
    });
    return () => window.cancelAnimationFrame(raf);
  }, [agentTab, latestVisibleMessageKey]);
  const displayThoughts = liveThoughts.slice(0, 8);
  const latestThought = displayThoughts[0] || {};
  const backgroundProgress = (backgroundResult.internal_think_progress || {}) as AnyRecord;
  const backgroundStageLabel = String(backgroundResult.stage_label || background?.last_stage_label || '').trim();
  const backgroundStage = String(backgroundResult.stage || background?.last_stage || '').trim();
  const backgroundStageAgeMs = Math.max(0, Date.now() - asNumber(background?.last_step_at_ms || backgroundResult.updated_at_ms || 0, Date.now()));
  const backgroundStageIsFresh = Boolean(background?.running) || backgroundStageAgeMs <= 3000;
  const visibleBackgroundStageLabel = backgroundStageIsFresh ? backgroundStageLabel : '';
  const visibleBackgroundStage = backgroundStageIsFresh ? backgroundStage : '';
  const backgroundDecision = String(backgroundProgress.decision || backgroundResult.decision || '').trim();
  const visibleDecision = liveActiveJob?.decision
    || backgroundDecision
    || (background?.running ? (visibleBackgroundStage || 'background_running') : '')
    || (displayThoughts[0]?.decision || 'waiting');
  const backgroundThoughtText = String(backgroundProgress.current_thought_text || backgroundResult.current_thought_text || '').trim();
  const backgroundLatestThought = asArray<AnyRecord>(backgroundThoughtResult?.thoughts)[0]
    || ((backgroundThoughtResult?.thought && typeof backgroundThoughtResult.thought === 'object') ? backgroundThoughtResult.thought as AnyRecord : {})
    || {};
  const backgroundWhy = String(backgroundProgress.why || backgroundResult.why || backgroundLatestThought.why || backgroundResult.reason || '').trim();
  const activeToolTask = (status?.active_tool_task || {}) as AnyRecord;
  const activeToolTaskLive = Boolean(
    String(activeToolTask.task_id || '').trim()
    && !['completed', 'done', 'failed', 'error', 'cancelled'].includes(String(activeToolTask.status || '').toLowerCase()),
  );
  const activeToolTaskLabel = activeToolTaskLive
    ? `${String(activeToolTask.task || '工具')} · ${String(activeToolTask.summary || activeToolTask.stage || '运行中')}`
    : '';
  const currentStage = liveActiveJob?.stage_label
    || activeToolTaskLabel
    || (background?.running || visibleBackgroundStageLabel
      ? visibleBackgroundStageLabel || '后台主观能动性运行中'
      : sending
        ? '消息已提交'
        : runtimeLooksEmpty
          ? '等待注入种子'
          : draft.llm_enabled
            ? 'LLM + AP 耦合待命'
            : '本地 fallback 待命');
  const ntGaugeRows = ntRows.slice(0, 8).map((item) => {
    const value = Math.max(0, Math.min(1, asNumber(item.value ?? item.level ?? item.current, 0)));
    const meta = describeNt(item);
    return {
      id: String(item.channel || item.name || '-'),
      label: meta.label,
      value,
      note: meta.note,
    };
  });
  const cfsGaugeRows = cfs.slice(0, 8).map((item) => {
    const level = Math.max(0, Math.min(1, asNumber(item.level ?? item.value ?? item.intensity, 0)));
    const meta = describeCfs(item);
    return {
      id: String(item.name || item.target || '-'),
      label: meta.label,
      value: level,
      target: String(item.target || ''),
      note: meta.note,
    };
  });
  const energyCards = [
    { label: '实能量 ER', value: summary.total_er, color: '#ff8787', note: '高时说明现实/外界线索更强，系统更贴着眼前事实组织状态。' },
    { label: '虚能量 EV', value: summary.total_ev, color: '#4dabf7', note: '高时说明联想/回忆/预测更活跃，系统更容易往想象和延展里走。' },
    { label: '认知压 CP', value: summary.total_cp, color: '#b197fc', note: '高时说明内部拉扯和压迫感更强，更可能推动继续想或做决策。' },
  ];
  const detailSnapshotRows = apTickSnapshots.slice(-300);
  const safetyRows = asArray<AnyRecord>(safetyRadar?.items || safetyRadar?.checks || safetyRadar?.cards);
  const detailEvents = events.slice().reverse().slice(0, 20);
  const detailEventRows = detailEvents.length ? detailEvents : [];
  const napcatOfficialNotes = [
    'PA 当前按 OneBot 风格事件解析：message_type、group_id、user_id、message 数组、at 段和 text 段都已兼容。',
    '入站建议使用 NapCat 的 HTTP POST 上报，把 message/notice 事件 POST 到下方 Webhook URL；messagePostFormat 建议保持 array。',
    '出站发送默认走 /send_group_msg 或 /send_private_msg；先保持 dry-run，确认目标和限速后再切 live。',
    'NapCat 也支持正向/反向 WebSocket，但当前 PA 原型优先对接 HTTP API + HTTP 上报，这条链路最轻量、也最方便本地调试。',
  ];
  const toolBlueprints = [
    { id: 'time', label: '时间 MCP/Skill', status: '可运行', detail: '本地时间工具已接入，可回灌 AP 形成时间感。' },
    { id: 'library', label: '图书馆/读书', status: '可运行', detail: '导入 txt/docx/pdf 等书籍，按短片段喂给 AP，并保存段落理解。' },
    { id: 'memory_note', label: '知识片段导入', status: '保留兼容', detail: '旧式 memory_note 仍可手动调用；长文档建议使用图书馆。' },
    { id: 'weather', label: '天气工具', status: '真实可用', detail: '已接入 Open-Meteo forecast/geocoding API，无需 key；执行后会把天气摘要回灌 AP。' },
    { id: 'image_understanding', label: '图片理解', status: '摘要优先', detail: '当前先接收图片/文件摘要，视觉模型配置后替换为真实理解。' },
  ];

  const selectedPreview = useMemo(() => selected || liveThoughts[0] || topObjects[0] || packet, [selected, liveThoughts, topObjects, packet]);
  const liveDecisionRows = [
    {
      label: '当前阶段',
      value: currentStage,
      note: liveActiveJob?.status === 'queued' ? '消息已入队，等待前序任务。' : liveActiveJob?.stage ? `内部阶段：${liveActiveJob.stage}` : activeToolTaskLive ? `工具阶段：${String(activeToolTask.stage || '-')}` : visibleBackgroundStage ? `后台阶段：${visibleBackgroundStage}` : '当前没有运行中的回合。',
    },
    {
      label: '当前决策',
      value: String(visibleDecision),
      note: 'reply=准备回复；continue_thinking=继续联想；silent/sleep=本轮不回复；tool_call=先执行工具。',
    },
    {
      label: 'AP tick',
      value: activeToolTaskLive && activeToolTask.progress_current !== undefined
        ? `${formatCount(activeToolTask.progress_current)} / ${formatCount(activeToolTask.progress_total)}`
        : `${formatCount(liveActiveJob?.ap_tick_count ?? livePacket.tick_counter ?? packet.tick_counter ?? 0)}`,
      note: activeToolTaskLive ? '读书等长期工具会在这里显示当前 AP tick / 阶段进度。' : '这里会随着用户输入注入、预运行、thought 回灌和工具结果回灌实时增加。',
    },
    {
      label: '想法进度',
              value: `${formatCount(liveActiveJob?.thought_soft_window_index ?? liveActiveJob?.current_thought_index ?? 0)} / ${formatCount(liveActiveJob?.thought_soft_window_limit ?? liveActiveJob?.thought_budget ?? draft.max_thoughts_per_turn ?? 0)}`,
              note: `软窗口进度；硬上限 ${formatCount(liveActiveJob?.thought_hard_step_limit ?? draft.max_total_thought_steps_per_turn ?? 0)}，continue 重置 ${formatCount(liveActiveJob?.thought_reset_count ?? 0)} / ${formatCount(liveActiveJob?.thought_reset_limit ?? draft.thought_budget_reset_limit ?? 0)}。`,
            },
    {
      label: 'LLM 等待空 tick',
      value: liveActiveJob?.llm_status?.llm_wait_tick_count !== undefined
        ? `${formatCount(liveActiveJob?.llm_status?.llm_wait_tick_count)} / ${formatCount(liveActiveJob?.llm_wait_tick_total ?? sendPreTicks ?? 0)}`
        : liveActiveJob?.llm_wait_tick_count !== undefined
          ? `${formatCount(liveActiveJob?.llm_wait_tick_count)} / ${formatCount(liveActiveJob?.llm_wait_tick_total ?? sendPreTicks ?? 0)}`
          : (sendWaitTicks ? '已开启' : '关闭'),
      note: '开启后，等待 LLM 返回期间 AP 会继续空 tick 消化；这些 tick 会抵扣下一次 LLM 前 AP tick 预算，最多不超过设置值。',
    },
    {
      label: 'LLM 前预 tick',
      value: liveActiveJob?.pre_tick_total ? `${formatCount(liveActiveJob.pre_tick_index)} / ${formatCount(liveActiveJob.pre_tick_total)}` : `${formatCount(sendPreTicks)} ticks`,
      note: '每次调用 LLM 前都会执行这组 AP tick，工具结果后的第二次 LLM 也会应用。',
    },
    {
      label: 'LLM 后 AP tick',
      value: liveActiveJob?.post_tick_total
        ? `${formatCount(liveActiveJob.post_tick_index)} / ${formatCount(liveActiveJob.post_tick_total)}`
        : `${formatCount(sendPostTicks)} ticks`,
      note: '每段 thought/reply 生成并回灌 AP 后继续运行，用于自检、纠错、撤回或收束。',
    },
    {
      label: '输入切分',
      value: draft.input_chunking_enabled === false ? '关闭' : `${formatCount(draft.input_chunk_soft_limit ?? 10)} / ${formatCount(draft.input_chunk_hard_limit ?? 30)}`,
      note: draft.input_chunking_enabled === false ? '当前用户输入和 thought 回灌会整段进入 AP。' : 'soft / hard，表示超过 10 字后优先按标点切分，最长不超过 30 字。',
    },
    {
      label: '后台思考间隔',
      value: `${formatCount(draft.background_thought_interval_ticks ?? 1)} ticks`,
      note: 'AP 可持续背景运行；只有累计到这个 tick 数，才会检查是否唤醒 LLM 继续生成想法。',
    },
    {
      label: '强化评估',
      value: `${formatCount(draft.reinforced_agency_interval_ticks ?? 30)} ticks`,
      note: '强化主观能动性模式每隔这么多 tick 做一次“该不该再想”的教师前判断，不直接生成 thought。',
    },
  ];
  const activeReports = asArray<AnyRecord>(liveActiveJob?.recent_reports);
  const activeToolCalls = asArray<AnyRecord>(liveActiveJob?.tool_calls).length ? asArray<AnyRecord>(liveActiveJob?.tool_calls) : asArray<AnyRecord>(latestThought.tool_calls);
  const activeToolResults = asArray<AnyRecord>(liveActiveJob?.tool_results).length ? asArray<AnyRecord>(liveActiveJob?.tool_results) : asArray<AnyRecord>(latestThought.tool_results);
  const activeBridges = asArray<AnyRecord>(liveActiveJob?.bridges);
  const activeBridgeFeedback = asArray<AnyRecord>(liveActiveJob?.bridge_teacher_feedback);
  const backgroundBridges = asArray<AnyRecord>(background?.last_result?.bridges);
  const liveDecisionNarrative = liveActiveJob?.current_thought_text
    ? `当前想法：${liveActiveJob.current_thought_text}`
    : backgroundThoughtText
      ? `后台当前想法：${backgroundThoughtText}`
    : liveActiveJob?.why
      ? `当前说明：${liveActiveJob.why}`
      : backgroundWhy
        ? `后台说明：${backgroundWhy}`
      : '发送消息后，这里会实时展示当前阶段、决策走向、thought 进度和工具执行情况。';
  const liveAnalysisRows = [
    {
      label: '决策解释',
      value: shortText(String(liveActiveJob?.why || backgroundWhy || latestThought?.why || '暂无'), 92),
      note: '这里只放分析/判断，不和想法文本混在一起。',
    },
    {
      label: '工具调用',
      value: activeToolCalls.length ? activeToolCalls.map((item) => String(item.name || item.tool || '-')).join('，') : '无',
      note: activeToolCalls.length ? '由后端自动执行，不需要用户手动复制。' : '当前这一轮和最近一轮都还没有发起工具调用。',
    },
    {
      label: '工具结果',
      value: activeToolResults.length ? activeToolResults.map((item) => `${String(item.tool || '-')} ${item.ok === false ? '失败' : '完成'}`).join('，') : '等待',
      note: activeToolResults.length ? '执行结果会回灌 AP，并进入下一段想法或最终回复前的上下文。' : '如果当前阶段还在等 LLM 或 AP，这里会稍后刷新。',
    },
    {
      label: 'AP 行动桥接',
      value: activeBridges.length
        ? activeBridges.map((item) => `${String(item.kind || '-')}:${String(item.bridge || '-')}:${item.ok === false ? '失败' : '完成'}`).join('，')
        : backgroundBridges.length
          ? backgroundBridges.map((item) => `${String(item.kind || '-')}:${String(item.bridge || '-')}:${item.ok === false ? '失败' : '完成'}`).join('，')
          : '无',
      note: activeBridges.length
        ? shortText(activeBridges.map((item) => String(item.summary || '')).filter(Boolean).join(' / '), 120)
        : backgroundBridges.length
          ? shortText(backgroundBridges.map((item) => String(item.summary || '')).filter(Boolean).join(' / '), 120)
          : 'AP 内部行动触发真实工具或主动思考门控时，会在这里显示桥接结果。',
    },
    {
      label: '行动反馈入池',
      value: activeBridgeFeedback.length
        ? activeBridgeFeedback.map((item) => `${String(item.kind || '-')}:${item.ok === false ? 'punish' : 'reward'}`).join('，')
        : '等待',
      note: activeBridgeFeedback.length
        ? shortText(activeBridgeFeedback.map((item) => String(item.summary || '')).filter(Boolean).join(' / '), 120)
        : '桥接后的成功/失败会被转成教师反馈，作为 AP 可学习的行动反馈信息。',
    },
    {
      label: '教师门控',
      value: shortText(String(background?.last_result?.teacher_gate?.should_wake === true ? '允许主动思考' : background?.last_result?.teacher_gate?.should_wake === false ? '拒绝主动思考' : '等待判断'), 92),
      note: background?.last_result?.teacher_gate?.reason ? `原因：${String(background.last_result.teacher_gate.reason)}` : '只有 AP 主观能动性 / 强化主观能动性模式下才会出现。',
    },
    {
      label: '最近 AP 拍',
      value: activeReports.length ? formatCount(activeReports.length) : '0',
      note: activeReports.length ? shortText(activeReports.map((row) => String(row.input || '')).filter(Boolean).join(' / '), 92) : '还没有新的 tick 摘要。',
    },
  ];

  return (
    <div className="pa-app agent-page">
      <header className="pa-topbar">
        <div className="pa-topbar-grid">
          <Group gap="sm" wrap="nowrap" className="pa-brand">
            <div className="brand-mark">PA</div>
            <div>
              <Title order={3}>PsyArch Agent</Title>
              <Text size="xs" c="dimmed">
                独立 PA 工作台 · AP 耦合拟人 bot 原型
              </Text>
            </div>
          </Group>
          <div className="pa-topbar-controls">
            <Badge className="pa-topbar-chip" variant="light" color={runtimeLooksEmpty ? 'yellow' : 'teal'}>
              {currentStage}
            </Badge>
            <Badge className="pa-topbar-chip" variant="outline">tick {formatCount(liveTickCounter)}</Badge>
            {activeJob?.job_id ? <Badge className="pa-topbar-chip" variant="outline">job {shortText(String(activeJob.job_id), 18)}</Badge> : null}
            <Badge className="pa-topbar-chip" variant="outline">{draft.llm_enabled ? draft.model || 'LLM' : 'fallback'}</Badge>
            <Tooltip label="自动刷新页面状态，不会写入 PA 历史。">
              <SegmentedControl
                className="pa-topbar-segmented"
                size="xs"
                value={autoRefresh ? 'auto' : 'manual'}
                data={[
                  { value: 'auto', label: '自动' },
                  { value: 'manual', label: '手动' },
                ]}
                onChange={(value) => setAutoRefresh(value === 'auto')}
              />
            </Tooltip>
            <NumberInput
              className="pa-topbar-refresh-input"
              aria-label="刷新间隔"
              size="xs"
              value={refreshMs}
              min={500}
              max={60000}
              step={500}
              w={106}
              hideControls
              onChange={(v) => setRefreshMs(v === '' ? '' : Number(v) || 1200)}
            />
            <Tooltip label="刷新 PA 状态">
              <ActionIcon className="pa-topbar-refresh-button" variant="light" loading={refreshing} onClick={() => refresh()}>
                <IconRefresh size={18} />
              </ActionIcon>
            </Tooltip>
          </div>
        </div>
      </header>

      <main className="pa-shell">
        <Tabs value={agentTab} onChange={(value) => setAgentTab(value || 'home')} className="pa-tabs" keepMounted={false}>
          <Tabs.List>
            <Tabs.Tab value="home" leftSection={<IconMessageCircle size={16} />}>主页</Tabs.Tab>
            <Tabs.Tab value="charts" leftSection={<IconChartBar size={16} />}>AP运行图表</Tabs.Tab>
            <Tabs.Tab value="details" leftSection={<IconClipboardList size={16} />}>详情页</Tabs.Tab>
            <Tabs.Tab value="config" leftSection={<IconSettings size={16} />}>配置页面</Tabs.Tab>
            <Tabs.Tab value="adapter" leftSection={<IconPlugConnected size={16} />}>适配器页面</Tabs.Tab>
            <Tabs.Tab value="tools" leftSection={<IconTool size={16} />}>工具功能页面</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="home" pt="md">
            <div className="pa-home-grid">
              <section className="pa-chat-column">
                <Card className="pa-panel pa-chat-panel">
                  <Group justify="space-between" align="flex-start" mb="sm">
                    <div>
                      <Group gap={8}>
                        <IconMessageCircle size={18} />
                        <Text fw={900}>对话</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        这里只显示用户输入和 bot 回复；诊断、审计和 thought 不混进聊天流。
                      </Text>
                    </div>
                    <Group gap={6}>
                      <Badge variant="light">{formatCount(displayVisibleMessages.length)} 条</Badge>
                      <Tooltip label="清空主页对话和近期想法，不清 AP 运行态。">
                        <ActionIcon variant="light" color="red" loading={historyBusy} onClick={() => void clear(false)} aria-label="清空对话">
                          <IconTrash size={17} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Group>
                  <ScrollArea.Autosize
                    mah={680}
                    className="agent-message-scroll"
                    viewportRef={chatViewportRef}
                    onScrollPositionChange={({ y }) => updateChatAutoFollow(y)}
                  >
                    <Stack gap="xs">
                      {initialDataLoading ? (
                        <div className="empty-box">数据读取中，正在连接 PA 后端和 AP 运行态...</div>
                      ) : displayVisibleMessages.length ? displayVisibleMessages.map((item) => (
                        <MessageBubble
                          key={String(item.id || `${item.role}-${item.created_at_ms}`)}
                          item={item}
                          auditRow={replyAuditById.get(String(item.id || ''))}
                          collapseDebt={collapseDebtMessages}
                          onInspect={setSelected}
                          imagePreviewMap={imagePreviewMap}
                        />
                      )) : <div className="empty-box">配置人设和模型后，就可以从这里开始第一轮聊天。</div>}
                    </Stack>
                  </ScrollArea.Autosize>
                  <Textarea
                    mt="sm"
                    minRows={8}
                    autosize
                    maxRows={18}
                    placeholder={enterToSend ? '输入想和 PA 说的话。Enter 发送，Shift + Enter 换行。' : '输入想和 PA 说的话。Ctrl / Cmd + Enter 发送。'}
                    value={input}
                    onChange={(event) => setInput(event.currentTarget.value)}
                    onKeyDown={(event) => {
                      const shouldSend = enterToSend
                        ? event.key === 'Enter' && !event.shiftKey
                        : (event.ctrlKey || event.metaKey) && event.key === 'Enter';
                      if (shouldSend) {
                        event.preventDefault();
                        void send();
                      }
                    }}
                  />
                  <div className="agent-attachment-strip">
                    <FileInput
                      leftSection={<IconFile size={16} />}
                      placeholder="图片/文件"
                      multiple
                      clearable
                      value={fileDraft}
                      onChange={(files) => {
                        setFileDraft(asArray<File>(files));
                        setAttachmentPreview(null);
                      }}
                    />
                    <TextInput
                      placeholder="附件摘要 / OCR / 视觉描述"
                      value={attachmentNote}
                      onChange={(event) => {
                        setAttachmentNote(event.currentTarget.value);
                        setAttachmentPreview(null);
                      }}
                    />
                    <Button
                      variant="light"
                      leftSection={<IconPhoto size={16} />}
                      onClick={() => {
                        const text = attachmentNote.trim();
                        if (!text) return;
                        setAttachmentDraft((prev) => [
                          ...prev,
                          { id: `note_${Date.now()}`, kind: 'text', name: 'manual_attachment_note', text, summary: text },
                        ]);
                        setAttachmentNote('');
                        setAttachmentPreview(null);
                      }}
                    >
                      摘要
                    </Button>
                  </div>
                  <SimpleGrid cols={{ base: 1, sm: 4 }} spacing="xs" mt="sm" className="pa-send-runtime-controls">
                    <NumberInput
                      size="xs"
                      label="LLM 前 AP tick"
                      description="本轮消息专用"
                      value={sendPreTicks}
                      min={0}
                      max={40}
                      step={1}
                      onChange={(value) => setSendPreTicks(value === '' ? '' : Math.max(0, Math.min(40, Number(value) || 0)))}
                    />
                    <NumberInput
                      size="xs"
                      label="LLM 后 AP tick"
                      description="本轮消息专用"
                      value={sendPostTicks}
                      min={0}
                      max={20}
                      step={1}
                      onChange={(value) => setSendPostTicks(value === '' ? '' : Math.max(0, Math.min(20, Number(value) || 0)))}
                    />
                    <Switch
                      size="sm"
                      label="等 LLM 时跑空 tick"
                      description="抵扣下一次 LLM 前 tick"
                      checked={sendWaitTicks}
                      onChange={(event) => setSendWaitTicks(event.currentTarget.checked)}
                    />
                    <Button size="xs" variant="light" leftSection={<IconSparkles size={14} />} onClick={pokeAgent}>
                      戳一戳
                    </Button>
                  </SimpleGrid>
                  <Group justify="space-between" mt="sm" gap="xs">
                    <Group gap={6}>
                      <Switch
                        size="xs"
                        label="回车发送"
                        checked={enterToSend}
                        onChange={(event) => setEnterToSend(event.currentTarget.checked)}
                      />
                      <Button size="xs" variant="subtle" leftSection={<IconPhoto size={14} />} loading={isBusy('tool')} onClick={previewAttachments}>
                        预览附件
                      </Button>
                      <Button size="xs" variant="subtle" leftSection={<IconPlayerPlay size={14} />} loading={isBusy('background')} onClick={bootstrap}>
                        注入种子
                      </Button>
                      <Button size="xs" variant="subtle" leftSection={<IconBolt size={14} />} loading={isBusy('background')} onClick={runTicks}>
                        {formatCount(manualTicks)} tick
                      </Button>
                    </Group>
                    <Button rightSection={<IconSend size={16} />} loading={sending} onClick={() => void send()}>
                      发送
                    </Button>
                  </Group>
                  <AttachmentDraftPanel
                    fileDraft={fileDraft}
                    attachmentDraft={attachmentDraft}
                    attachmentNote={attachmentNote}
                    preview={attachmentPreview}
                    onInspect={setSelected}
                    onRemoveDraft={(id) => {
                      setAttachmentDraft((prev) => prev.filter((item) => String(item.id || '') !== id));
                      setAttachmentPreview(null);
                    }}
                    onClearFiles={() => {
                      setFileDraft([]);
                      setAttachmentPreview(null);
                    }}
                  />
                </Card>

                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" mb="xs">
                    <Text fw={900}>运行阶段</Text>
                    <Badge variant="light" color={background?.running ? 'teal' : 'gray'}>{background?.running ? 'running' : 'stopped'}</Badge>
                  </Group>
                  <div className="pa-stage-list">
                    {[
                      { label: '用户输入', value: `${formatCount(status?.session?.message_count)} messages` },
                      ...(activeToolTaskLive ? [{ label: '工具运行', value: `${String(activeToolTask.task || '工具')} ${formatPercent(asNumber(activeToolTask.progress, 0) / 100, 0)}` }] : []),
                      { label: 'AP 预运行', value: `${draft.pre_thought_ticks ?? 0} ticks` },
                      { label: '连续想法', value: `软 ${draft.max_thoughts_per_turn ?? 1} / 硬 ${draft.max_total_thought_steps_per_turn ?? 0}` },
                      { label: '回复行动', value: draft.auto_reply ? '自动判断' : '仅想法' },
                      { label: '休眠策略', value: sleepModes.find((item) => item.value === draft.sleep_mode)?.label || draft.sleep_mode || '-' },
                    ].map((row) => (
                      <button key={row.label} type="button" className="pa-stage-row" onClick={() => setSelected(row)}>
                        <span>{row.label}</span>
                        <strong>{row.value}</strong>
                      </button>
                    ))}
                  </div>
                  <Group grow mt="sm">
                    <Button size="xs" variant="light" leftSection={<IconPlayerPlay size={14} />} loading={isBusy('background')} onClick={backgroundStart}>
                      启动主观能动
                    </Button>
                    <Button size="xs" variant="subtle" leftSection={<IconPlayerPause size={14} />} loading={isBusy('background')} onClick={backgroundStop}>
                      停止
                    </Button>
                  </Group>
                  <Text size="xs" c="dimmed" mt={6}>
                    当前会按“休眠策略”启动：{sleepModes.find((item) => item.value === draft.sleep_mode)?.label || draft.sleep_mode || '-'}。开启后会持续后台空 tick，直到手动停止；强化主观能动性会在空 tick 过程中按配置间隔做教师评估。
                  </Text>
                </Card>
                <UserProgressCard progress={userProgress} busy={busy} onSaveLoadout={(payload) => saveUserProgressLoadout(payload)} />
              </section>

              <section className="pa-main-column">
                <Card className="pa-panel pa-cloud-panel">
                  <Group justify="space-between" align="flex-start" mb="sm">
                    <div>
                      <Group gap={8}>
                        <IconSparkles size={18} />
                        <Text fw={900}>想法云</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        泡泡大小代表总能量；颜色红=实能量偏多，蓝=虚能量偏多，紫=两者接近；认知压越高越亮。
                      </Text>
                    </div>
                    <Group gap={6}>
                      {cloudIsHistorical ? <Badge variant="light" color="gray">历史快照</Badge> : null}
                      <Badge variant="light" color="red">ER 偏多</Badge>
                      <Badge variant="light" color="violet">ER≈EV</Badge>
                      <Badge variant="light" color="blue">EV 偏多</Badge>
                      <Badge variant="light" color="yellow">CP</Badge>
                      <Tooltip label="放大对象云">
                        <ActionIcon variant="light" onClick={() => setCloudModalOpen(true)} aria-label="放大词云">
                          <IconArrowsMaximize size={16} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Group>
                  <div ref={cloudContainerRef} className="agent-cloud agent-cloud-bubbles">
                    {initialDataLoading ? (
                      <div className="pa-cloud-empty-state">
                        <strong>数据读取中</strong>
                        <span>正在连接 PA 后端和 AP 状态池，稍后会显示对象云。</span>
                      </div>
                    ) : cloudLayout.length ? cloudLayout.map((item) => (
                      <CloudObject key={`${item.id}-${item.rank}-${item.group_count || 1}`} item={item} onSelect={setSelected} />
                    )) : (
                      <div className="pa-cloud-empty-state">
                        <strong>等待第一批想法对象</strong>
                        <span>先在配置页选择人设并保存，再回到主页注入种子或发送一条消息。</span>
                        <div>
                          <i>1 配置人设/API</i>
                          <i>2 注入种子</i>
                          <i>3 开始聊天</i>
                        </div>
                      </div>
                    )}
                  </div>
                  {cloudIsHistorical ? (
                    <Text size="xs" c="dimmed" mt="xs">
                      当前进程刚启动，实时状态池为空；这里先展示最近一次历史 snapshot 的对象云，注入种子或发送消息后会切回实时。
                    </Text>
                  ) : null}
                </Card>

                <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md" mt="md">
                  {energyCards.map((row) => (
                    <Card key={row.label} className="pa-panel pa-energy-card">
                      <Group justify="space-between" gap={8}>
                        <Text size="sm" fw={800}>{row.label}</Text>
                        <span className="pa-energy-dot" style={{ background: row.color }} />
                      </Group>
                      <Text fw={900} className="pa-energy-value">{formatNumber(row.value, 2)}</Text>
                      <Text size="xs" c="dimmed">{row.note}</Text>
                    </Card>
                  ))}
                </SimpleGrid>

                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" mb="xs">
                    <Text fw={900}>当前状态</Text>
                    <Badge variant="light">{livePacket.summary?.mood_hint || summary.mood_hint || 'mood pending'}</Badge>
                  </Group>
                  <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
                    <div className="pa-mini-meter-group">
                      <Text size="xs" fw={800} c="dimmed">情绪 NT</Text>
                      {ntGaugeRows.length ? ntGaugeRows.map((row) => (
                        <button key={row.id} type="button" className="pa-meter-row" onClick={() => setSelected(row)}>
                          <span title={row.note || row.label}>{row.label}</span>
                          <i><b style={{ width: `${Math.round(row.value * 100)}%` }} /></i>
                          <strong>{formatNumber(row.value, 2)}</strong>
                        </button>
                      )) : <div className="empty-box compact">等待 NT 数据。</div>}
                      <Text size="xs" c="dimmed">高值通常表示该通道当下更主导；低值表示它暂时不占前景。标签里的专业名是更接近的递质/功能类比。</Text>
                    </div>
                    <div className="pa-mini-meter-group">
                      <Text size="xs" fw={800} c="dimmed">认知感受</Text>
                      {cfsGaugeRows.length ? cfsGaugeRows.map((row) => (
                        <button key={`${row.id}-${row.target}`} type="button" className="pa-meter-row" onClick={() => setSelected(row)}>
                          <span title={row.note || row.label}>{row.label}</span>
                          <i><b style={{ width: `${Math.round(row.value * 100)}%` }} /></i>
                          <strong>{formatNumber(row.value, 2)}</strong>
                        </button>
                      )) : <div className="empty-box compact">等待 CFS 数据。</div>}
                      <Text size="xs" c="dimmed">高值表示这一类感受更显著，低值表示它仍在背景中。点开单项可以看更细的中文解释。</Text>
                    </div>
                  </SimpleGrid>
                </Card>

                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" align="flex-start" mb="sm">
                    <div>
                      <Group gap={8}>
                        <IconBolt size={18} />
                        <Text fw={900}>LLM/API 调用日志</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        这里记录模型调用的开始、成功、失败、立即重试、退避等待、冷却和熔断；不记录 API Key 和完整提示词。
                      </Text>
                    </div>
                    <Group gap={6}>
                      <SegmentedControl
                        size="xs"
                        value={llmApiLogView}
                        onChange={setLlmApiLogView}
                        data={[
                          { value: 'important', label: '重要' },
                          { value: 'detail', label: '详细' },
                          { value: 'errors', label: '错误' },
                        ]}
                      />
                      <ActionIcon size="sm" variant="subtle" loading={isBusy('diag')} onClick={() => void refreshLlmApiEvents(true)}>
                        <IconRefresh size={14} />
                      </ActionIcon>
                    </Group>
                  </Group>
                  <Group gap={6} mb="xs" wrap="wrap">
                    <Badge size="xs" variant="light" color="blue">显示 {formatCount(llmApiEventCounts.returned)}</Badge>
                    <Badge size="xs" variant="outline">扫描 {formatCount(llmApiEventCounts.total_scanned)}</Badge>
                    <Badge size="xs" variant="light" color="teal">成功 {formatCount(llmApiEventCounts.success)}</Badge>
                    <Badge size="xs" variant="light" color={asNumber(llmApiEventCounts.failed, 0) ? 'red' : 'gray'}>失败 {formatCount(llmApiEventCounts.failed)}</Badge>
                    <Badge size="xs" variant="light" color={asNumber(llmApiEventCounts.retry, 0) ? 'yellow' : 'gray'}>重试 {formatCount(llmApiEventCounts.retry)}</Badge>
                    <Badge size="xs" variant="light" color={asNumber(llmApiEventCounts.cooldown, 0) ? 'yellow' : 'gray'}>冷却 {formatCount(llmApiEventCounts.cooldown)}</Badge>
                    <Badge size="xs" variant="light" color={asNumber(llmApiEventCounts.fused, 0) ? 'red' : 'gray'}>熔断 {formatCount(llmApiEventCounts.fused)}</Badge>
                    <Badge size="xs" variant="light" color={asNumber(llmApiEventCounts.error, 0) ? 'red' : 'gray'}>错误 {formatCount(llmApiEventCounts.error)}</Badge>
                  </Group>
                  <ScrollArea.Autosize mah={300}>
                    <LlmApiEventList rows={llmApiEvents} onSelect={setSelected} />
                  </ScrollArea.Autosize>
                </Card>

              </section>

              <aside className="pa-side-column">
                <Card className="pa-panel">
                  <Group justify="space-between" align="flex-start" mb="xs">
                    <div>
                      <Text fw={900}>近期想法</Text>
                      <Text size="xs" c="dimmed">LLM/fallback 生成的连续 thought，多条保留用于观察拟人连续性。</Text>
                    </div>
                    <Badge variant="light">{formatCount(Math.max(asNumber(thoughtPage?.total ?? status?.session?.thought_count, liveThoughts.length), liveThoughts.length))}</Badge>
                  </Group>
                  <ScrollArea.Autosize mah={470}>
                    <Stack gap="sm">
                      {displayThoughts.length ? displayThoughts.map((item) => (
                        <ThoughtTextCard key={String(item.id)} item={item} onSelect={setSelected} />
                      )) : <div className="empty-box">还没有 thought。发送消息后会在这里连续出现。</div>}
                    </Stack>
                  </ScrollArea.Autosize>
                  <Group gap="xs" mt="sm">
            <Button size="xs" variant="light" loading={isBusy('history')} onClick={() => void loadThoughtPage(Math.max(0, thoughtOffset + 8))} disabled={thoughtPage ? !thoughtPage.has_more : false}>
                      更早
                    </Button>
                    <Button size="xs" variant="subtle" loading={isBusy('history')} onClick={() => { setThoughtOffset(0); setThoughtPage(null); }}>
                      最新
                    </Button>
                  </Group>
                </Card>

                <Card className={`pa-panel pa-decision-panel ${activeJob || background?.running ? 'is-running' : ''}`} mt="md">
                  <Group justify="space-between" mb="xs">
                    <Group gap={8}>
                      <span className="pa-live-dot" />
                      <Text fw={900}>本轮运行与决策</Text>
                    </Group>
                    <Badge variant="light" color={activeJob ? (String(activeJob.status || '') === 'failed' ? 'red' : 'teal') : background?.running ? 'yellow' : 'gray'}>
                      {activeJob?.status || (background?.running ? 'background' : 'idle')}
                    </Badge>
                  </Group>
                    {liveActiveJob ? (
                      <div className="pa-decision-progress">
                        <span style={{ width: `${Math.max(6, Math.min(100, (asNumber(liveActiveJob.thought_soft_window_index ?? liveActiveJob.current_thought_index, 0) / Math.max(1, asNumber(liveActiveJob.thought_soft_window_limit ?? liveActiveJob.thought_budget, draft.max_thoughts_per_turn || 1))) * 100))}%` }} />
                      </div>
                    ) : background?.running ? (
                    <div className="pa-decision-progress">
                      <span style={{ width: `${Math.max(8, Math.min(100, (asNumber(backgroundProgress.thought_soft_window_index ?? backgroundProgress.current_thought_index ?? backgroundResult.current_thought_index, 0) / Math.max(1, asNumber(backgroundProgress.thought_soft_window_limit ?? backgroundProgress.thought_budget ?? backgroundResult.thought_budget, draft.max_thoughts_per_turn || 1))) * 100))}%` }} />
                    </div>
                  ) : null}
                  <div className="pa-stage-list">
                    {liveActiveJob ? (
                      <button type="button" className="pa-stage-row" onClick={() => setSelected(liveActiveJob)}>
                        <span>当前任务</span>
                        <strong>{shortText(agentJobTaskLabel(liveActiveJob), 72)}</strong>
                      </button>
                    ) : null}
                    {!liveActiveJob && !background?.running && (recentFinishedJob || agentJobs.length) ? (
                      <button type="button" className="pa-stage-row" onClick={() => setSelected(recentFinishedJob || agentJobs[0])}>
                        <span>最近任务</span>
                        <strong>{shortText(agentJobTaskLabel(recentFinishedJob || agentJobs[0], true), 72)}</strong>
                      </button>
                    ) : null}
                    {liveDecisionRows.map((row) => (
                      <button key={row.label} type="button" className="pa-stage-row" onClick={() => setSelected({ ...row, activeJob: liveActiveJob || recentFinishedJob })}>
                        <span>{row.label}</span>
                        <strong>{row.value}</strong>
                      </button>
                    ))}
                    <div className="pa-note-row">{liveDecisionNarrative}</div>
                    {liveActiveJob?.error ? <div className="pa-note-row">错误：{liveActiveJob.error}</div> : null}
                  </div>
                  <Group grow mt="sm">
                    <Button
                      size="xs"
                      variant="light"
                      color="red"
                      leftSection={<IconPlayerStop size={14} />}
                      loading={isBusy('background')}
                      disabled={!(activeJob && isLiveAgentJob(activeJob)) && !background?.running}
                      onClick={() => void stopActiveThinking()}
                    >
                      停止思考
                    </Button>
                  </Group>
                </Card>

                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" mb="xs">
                    <Text fw={900}>分析 / 工具 / 行动</Text>
                    <Badge variant="light" color={background?.running ? 'teal' : 'gray'}>{background?.running ? 'AP running' : 'idle'}</Badge>
                  </Group>
                  <div className="pa-stage-list">
                    {liveAnalysisRows.map((row) => (
                      <button key={row.label} type="button" className="pa-stage-row" onClick={() => setSelected({ ...row, activeJob })}>
                        <span>{row.label}</span>
                        <strong>{row.value}</strong>
                      </button>
                    ))}
                    <div className="pa-note-row">
                      回复策略：{draft.auto_reply ? '自动判断是否回复用户' : '当前只生成 thought，不直接回复'}；休眠策略：{sleepModes.find((item) => item.value === draft.sleep_mode)?.label || draft.sleep_mode || '-'}。
                    </div>
                  </div>
                </Card>

              </aside>
            </div>
          </Tabs.Panel>

          <Tabs.Panel value="charts" pt="md">
            <div className="pa-charts-page">
              <Card className="pa-panel pa-charts-header">
                <Group justify="space-between" align="flex-start" gap="sm">
                  <div>
                    <Text fw={900}>AP 运行图表</Text>
                    <Text size="xs" c="dimmed">按 PA 运行过程中的 AP tick 快照绘制；全 0 曲线会自动隐藏，tick 检视在独立小页里查看。</Text>
                  </div>
                  <Group gap={6}>
                    <Badge variant="light">{formatCount(paMetricRows.length)} ticks</Badge>
                    <Badge variant="outline">ap_tick {formatCount(apTickSnapshots.length)}</Badge>
                    {snapshotPage ? <Badge variant="outline">history {formatCount(snapshotPage.total)}</Badge> : null}
                    <ActionIcon variant="light" loading={historyBusy} aria-label="刷新 AP tick 历史" onClick={() => void withBusy('history', () => refreshSnapshotHistory())}>
                      <IconRefresh size={16} />
                    </ActionIcon>
                  </Group>
                </Group>
              </Card>
              <Tabs value={apChartTab} onChange={(value) => setApChartTab(value || 'overview')} className="pa-chart-tabs" keepMounted={false}>
                <Tabs.List>
                  {paChartsBySection.map(({ section, configs }) => (
                    <Tabs.Tab key={section.id} value={section.id}>
                      {section.label} · {formatCount(configs.length)}
                    </Tabs.Tab>
                  ))}
                  <Tabs.Tab value="continuity">连续性</Tabs.Tab>
                  <Tabs.Tab value="tick_inspector">tick 检视</Tabs.Tab>
                </Tabs.List>
                {paChartsBySection.map(({ section, configs }) => (
                  <Tabs.Panel key={section.id} value={section.id} pt="md">
                    <Card className="pa-panel pa-wide-chart-panel">
                      <Group justify="space-between" align="flex-start" mb="md">
                        <div>
                          <Text fw={900}>{section.label}</Text>
                          <Text size="xs" c="dimmed">{section.description}</Text>
                        </div>
                        <Badge variant="outline">{formatCount(configs.length)} charts</Badge>
                      </Group>
                      <SimpleGrid cols={{ base: 1, xl: 2, '2xl': 3 }} spacing="md">
                        {configs.map((config) => (
                          <MetricChart
                            key={config.id}
                            rows={paMetricRows}
                            config={{
                              ...config,
                              title: `${paChartSectionMap.get(config.section)?.label || config.section} · ${config.title}`,
                            }}
                            height={280}
                          />
                        ))}
                      </SimpleGrid>
                    </Card>
                  </Tabs.Panel>
                ))}
                <Tabs.Panel value="continuity" pt="md">
                  <SimpleGrid cols={{ base: 1, xl: 2 }} spacing="md">
                    <Card className="pa-panel">
                      <Group justify="space-between" mb="xs">
                        <Text fw={900}>能量历史</Text>
                        <Badge variant="light">{formatCount(apTickSnapshots.length)} ticks</Badge>
                      </Group>
                      <EnergyTrendChart snapshots={apTickSnapshots} dark={dark} />
                    </Card>
                    <Card className="pa-panel">
                      <Group justify="space-between" mb="xs">
                        <Text fw={900}>Thought 质量连续性</Text>
                        <Badge variant="light">{formatCount(thoughts.length)} rows</Badge>
                      </Group>
                      <ThoughtQualityChart thoughts={thoughts} dark={dark} />
                    </Card>
                  </SimpleGrid>
                </Tabs.Panel>
                <Tabs.Panel value="tick_inspector" pt="md">
                  <div className="pa-tick-inspector-wide">
                    <TickInspectorCard snapshots={detailSnapshotRows} selected={selectedTickSnapshot} onSelect={setSelected} />
                  </div>
                </Tabs.Panel>
              </Tabs>
            </div>
          </Tabs.Panel>

          <Tabs.Panel value="details" pt="md">
            <div className="pa-details-grid">
              <section className="pa-main-column">
                <Card className="pa-panel">
                  <CognitiveTimelinePanel timeline={cognitiveTimeline} dark={dark} busy={busy} onRefresh={refreshCognitiveTimeline} onInspect={setSelected} />
                </Card>
                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" align="flex-start" mb="sm">
                    <div>
                      <Group gap={8}>
                        <IconListDetails size={18} />
                        <Text fw={900}>系统日志</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        展示导入/导出/合并、日志维护、后台任务和系统报错；用于确认任务正在做什么、做到哪里。
                      </Text>
                    </div>
                    <Group gap={6}>
                      <SegmentedControl
                        size="xs"
                        value={systemLogView}
                        onChange={setSystemLogView}
                        data={[
                          { value: 'important', label: '重点' },
                          { value: 'detail', label: '详细' },
                          { value: 'errors', label: '报错' },
                        ]}
                      />
                      <ActionIcon size="sm" variant="subtle" loading={isBusy('diag')} onClick={() => void refreshSystemEvents(true)} aria-label="刷新系统日志">
                        <IconRefresh size={14} />
                      </ActionIcon>
                    </Group>
                  </Group>
                  {systemActiveTasks.length ? (
                    <Stack gap={8} mb="sm">
                      {systemActiveTasks.slice(0, 4).map((task, index) => {
                        const progress = Math.max(0, Math.min(100, asNumber(task.progress, 0)));
                        return (
                          <button key={`${task.task_id || index}`} type="button" className="agent-task-progress-row" onClick={() => setSelected(task)}>
                            <span>
                              <strong>{shortText(String(task.task || task.event || '系统任务'), 44)}</strong>
                              <small>{shortText(String(task.summary || task.stage || ''), 110)}</small>
                              <i><b style={{ width: `${progress}%` }} /></i>
                            </span>
                            <Badge variant="light" color="blue">{formatPercent(progress / 100, 0)}</Badge>
                          </button>
                        );
                      })}
                    </Stack>
                  ) : null}
                  <Group gap={6} mb="xs" wrap="wrap">
                    <Badge size="xs" variant="light" color="blue">显示 {formatCount(systemEventCounts.returned)}</Badge>
                    <Badge size="xs" variant="outline">扫描 {formatCount(systemEventCounts.total_scanned)}</Badge>
                    <Badge size="xs" variant="light" color={asNumber(systemEventCounts.active, 0) ? 'blue' : 'gray'}>运行中 {formatCount(systemEventCounts.active)}</Badge>
                    <Badge size="xs" variant="light" color={asNumber(systemEventCounts.warn, 0) ? 'yellow' : 'gray'}>警告 {formatCount(systemEventCounts.warn)}</Badge>
                    <Badge size="xs" variant="light" color={asNumber(systemEventCounts.error, 0) ? 'red' : 'gray'}>报错 {formatCount(systemEventCounts.error)}</Badge>
                    <Badge size="xs" variant="outline">任务 {formatCount(systemEventCounts.tasks)}</Badge>
                  </Group>
                  <ScrollArea.Autosize mah={360}>
                    <SystemEventList rows={systemEvents} onSelect={setSelected} />
                  </ScrollArea.Autosize>
                </Card>
              </section>
              <aside className="pa-side-column">
                <Card className="pa-panel agent-ap-maintenance-card">
                  <Group justify="space-between" align="flex-start" mb="xs">
                    <div>
                      <Group gap={8}>
                        <IconDatabase size={18} />
                        <Text fw={900}>AP 运行态管理</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        换人设重开时先清短期运行态；如果要连长期理解一起重置，再清 HDB。
                      </Text>
                    </div>
                    <Badge variant="light" color="yellow">谨慎操作</Badge>
                  </Group>
                  <SimpleGrid cols={{ base: 1, sm: 3 }} spacing={8}>
                    <button type="button" className="agent-maintenance-action" disabled={maintenanceBusy} onClick={() => void resetApRuntime('runtime')}>
                      <IconEraser size={16} />
                      <span>
                        <strong>清 AP 运行态</strong>
                        <small>短期状态、注意力和行动驱动</small>
                      </span>
                    </button>
                    <button type="button" className="agent-maintenance-action danger" disabled={maintenanceBusy} onClick={() => void resetApRuntime('hdb')}>
                      <IconDatabase size={16} />
                      <span>
                        <strong>清 HDB</strong>
                        <small>长期结构、记忆和理解积累</small>
                      </span>
                    </button>
                    <button type="button" className="agent-maintenance-action danger strong" disabled={maintenanceBusy} onClick={() => void resetApRuntime('all')}>
                      <IconTrash size={16} />
                      <span>
                        <strong>全部重置</strong>
                        <small>短期运行态 + 长期 HDB</small>
                      </span>
                    </button>
                  </SimpleGrid>
                  <div className="agent-maintenance-note">
                    <span>清对话只影响 PA 聊天记录；这里管理的是 AP 本体状态。HDB 清空后，长期学习痕迹会重新开始积累。</span>
                    {maintenanceBusy ? <Badge size="xs" color="yellow" variant="light">处理中</Badge> : null}
                  </div>
                </Card>
                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" align="flex-start" mb="xs">
                    <div>
                      <Group gap={8}>
                        <IconDatabase size={18} />
                        <Text fw={900}>运行包 / AP 技能包</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        导出会自动脱敏 API Key、URL、webhook 和日志；导入前会自动备份当前运行包。覆盖策略风险最高。
                      </Text>
                    </div>
                    <Group gap={6}>
                      <Badge variant="light">{formatCount(runtimePackages?.total ?? asArray<AnyRecord>(runtimePackages?.packages).length)} 包</Badge>
                      <Tooltip label="刷新运行包">
                        <ActionIcon size="sm" variant="subtle" loading={maintenanceBusy} aria-label="刷新运行包" onClick={() => void refreshRuntimePackages(true)}>
                          <IconRefresh size={15} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Group>
                  <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="sm">
                    <Stack gap="xs">
                      <TextInput label="导出名称" value={String(runtimePackageDraft.name || '')} onChange={(event) => setRuntimePackageDraft((prev) => ({ ...prev, name: event.currentTarget.value }))} />
                      <Textarea label="备注" minRows={2} autosize value={String(runtimePackageDraft.note || '')} onChange={(event) => setRuntimePackageDraft((prev) => ({ ...prev, note: event.currentTarget.value }))} />
                      <SimpleGrid cols={2} spacing={6}>
                        <Switch size="sm" label="AP 运行态" checked={runtimePackageDraft.include_state !== false} onChange={(event) => setRuntimePackageDraft((prev) => ({ ...prev, include_state: event.currentTarget.checked }))} />
                        <Switch size="sm" label="HDB" checked={runtimePackageDraft.include_hdb !== false} onChange={(event) => setRuntimePackageDraft((prev) => ({ ...prev, include_hdb: event.currentTarget.checked }))} />
                        <Switch size="sm" label="日记/任务/表情" checked={runtimePackageDraft.include_agent_data !== false} onChange={(event) => setRuntimePackageDraft((prev) => ({ ...prev, include_agent_data: event.currentTarget.checked }))} />
                        <Switch size="sm" label="图书馆" checked={runtimePackageDraft.include_library !== false} onChange={(event) => setRuntimePackageDraft((prev) => ({ ...prev, include_library: event.currentTarget.checked }))} />
                      </SimpleGrid>
                      <Button variant="light" leftSection={<IconDeviceFloppy size={14} />} loading={maintenanceBusy} onClick={() => void exportRuntimePackage()}>
                        导出运行包
                      </Button>
                    </Stack>
                    <Stack gap="xs">
                      <TextInput label="导入 zip 路径" value={String(runtimePackageDraft.path || '')} onChange={(event) => setRuntimePackageDraft((prev) => ({ ...prev, path: event.currentTarget.value }))} />
                      <Select
                        label="冲突合并策略"
                        value={String(runtimePackageDraft.strategy || 'retreat')}
                        data={[
                          { value: 'stack', label: '叠加：都保留，相同权重相加' },
                          { value: 'stack_average', label: '柔和叠加：相同权重取平均' },
                          { value: 'overwrite', label: '覆盖：同名以导入包为准' },
                          { value: 'competitive', label: '竞争合并：保留更强/更完整项' },
                          { value: 'retreat', label: '退避：本地已有内容优先' },
                        ]}
                        onChange={(value) => setRuntimePackageDraft((prev) => ({ ...prev, strategy: value || 'retreat' }))}
                      />
                      <Text size="xs" c="dimmed">
                        退避最保守；叠加适合共享技能包；覆盖适合完整迁移，但可能改写本地长期理解；竞争合并会丢弃较弱项。
                      </Text>
                      <Button variant="light" color="yellow" leftSection={<IconDatabase size={14} />} loading={maintenanceBusy} onClick={() => void importRuntimePackage()}>
                        导入并自动备份
                      </Button>
                    </Stack>
                  </SimpleGrid>
                  <ScrollArea.Autosize mah={220} mt="sm">
                    <Stack gap="xs">
                      {asArray<AnyRecord>(runtimePackages?.packages).map((pkg) => (
                        <button key={String(pkg.path || pkg.name)} type="button" className="agent-tool-row" onClick={() => { setRuntimePackageDraft((prev) => ({ ...prev, path: String(pkg.path || '') })); setSelected(pkg); }}>
                          <div>
                            <strong>{shortText(String(pkg.name || pkg.path || '-'), 46)}</strong>
                            <small>{shortText(String(pkg.manifest?.note || pkg.path || ''), 96)}</small>
                          </div>
                          <Badge variant="light">{formatCount(pkg.bytes)} B</Badge>
                        </button>
                      ))}
                      {!asArray<AnyRecord>(runtimePackages?.packages).length ? <div className="empty-box compact">还没有运行包。可以先导出一份当前 AP/PA 运行态作为备份。</div> : null}
                    </Stack>
                  </ScrollArea.Autosize>
                </Card>
                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" mb="xs">
                    <Text fw={900}>审计与安全</Text>
                    <Group gap={6}>
                      <Button size="compact-xs" variant="subtle" loading={diagBusy} onClick={refreshReplyActionAudit}>审计</Button>
                    <Button size="compact-xs" variant="subtle" loading={isBusy('diag')} onClick={runMorningCheck}>晨检</Button>
                    </Group>
                  </Group>
                  <ReplyActionAuditPanel
                    audit={replyActionAudit}
                    debtPreview={replyDebtPreview}
                    busy={busy}
                    onRefresh={refreshReplyActionAudit}
                    onDebtPreview={refreshReplyDebtPreview}
                    onInspect={setSelected}
                  />
                  {safetyRows.length ? (
                    <Stack gap={6} mt="sm">
                      {safetyRows.slice(0, 8).map((item) => (
                        <button key={String(item.id || item.label)} type="button" className="agent-readiness-row" onClick={() => setSelected(item)}>
                          <Badge size="xs" variant="light" color={item.status === 'fail' ? 'red' : item.status === 'warn' ? 'yellow' : 'teal'}>{String(item.status || 'info')}</Badge>
                          <span>
                            <strong>{shortText(String(item.label || item.id || '-'), 32)}</strong>
                            <small>{shortText(String(item.detail || item.note || ''), 108)}</small>
                          </span>
                        </button>
                      ))}
                    </Stack>
                  ) : null}
                </Card>
                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" mb="xs">
                    <Text fw={900}>事件时间线</Text>
                    <Button size="compact-xs" variant="subtle" loading={diagBusy} onClick={() => loadDiagnosticBundle(true)}>诊断包</Button>
                  </Group>
                  <ScrollArea.Autosize mah={340}>
                    {detailEventRows.length ? (
                      <EventList events={detailEventRows} onSelect={setSelected} />
                    ) : (
                      <div className="empty-box">
                        暂无工具、行动或审计事件。发送消息、执行工具、启动后台主观能动性后，这里会显示对应时间线。
                      </div>
                    )}
                  </ScrollArea.Autosize>
                </Card>
              </aside>
              <aside className="pa-json-column">
                <Card className="pa-panel pa-sticky-json">
                  <Text fw={900} mb="xs">选中对象 / 调试包</Text>
                  <JsonInspector value={selectedPreview} title="PA / AP JSON" maxHeight={640} />
                </Card>
              </aside>
            </div>
          </Tabs.Panel>

          <Tabs.Panel value="config" pt="md">
            <div className="pa-config-grid">
              <section className="pa-main-column">
                <Card className="pa-panel">
                  <Group justify="space-between" align="flex-start" mb="md">
                    <div>
                      <Text fw={900}>初始配置</Text>
                      <Text size="xs" c="dimmed">
                        推荐顺序：选择/编辑人设，填写 OpenAI-compatible Base URL、API Key、模型名，保存后回主页聊天。
                      </Text>
                    </div>
                    <Group gap={6}>
                      {draftDirty ? <Badge variant="light" color="yellow">草稿未保存</Badge> : null}
                      <Button size="xs" variant="light" leftSection={<IconPlugConnected size={14} />} loading={configBusy} onClick={testLlm}>
                        测 LLM
                      </Button>
                      <Button size="xs" variant="light" leftSection={<IconSparkles size={14} />} loading={polishBusy} onClick={polishPersona}>
                        AI 润色人设
                      </Button>
                      <Button size="xs" leftSection={<IconDeviceFloppy size={14} />} loading={configBusy} onClick={saveConfig}>
                        保存配置
                      </Button>
                    </Group>
                  </Group>
                  <ConfigEditor draft={draft} setDraft={setDraftEditable} onSave={saveConfig} busy={configBusy} stickerLibraryDir={String(stickers?.library_dir || serverConfig.sticker_library_dir || '')} />
                </Card>
              </section>
              <aside className="pa-side-column">
                <Card className="pa-panel">
                  <PersonaHistoryPanel
                    records={personaHistory}
                    draft={draft}
                    busy={configBusy}
                    editingId={personaHistoryEditingId}
                    onSaveCurrent={() => void savePersonaHistory(false)}
                    onSaveAsNew={() => void savePersonaHistory(true)}
                    onResetEditing={() => setPersonaHistoryEditingId('')}
                    onLoadToDraft={loadPersonaRecordToDraft}
                    onApply={applyPersonaHistory}
                    onDelete={deletePersonaHistory}
                  />
                </Card>
                <Card className="pa-panel" mt="md">
                  <ModelPoolPanel
                    models={modelPool}
                    draft={draft}
                    slotDraft={slotDraft}
                    setSlotDraft={setSlotDraft}
                    onSave={saveModelSlot}
                    onApply={applyModelSlot}
                    onEdit={editModelSlot}
                    onDelete={deleteModelSlot}
                    busy={busy}
                  />
                </Card>
                <Card className="pa-panel" mt="md">
                  <ConfigProfilePanel
                    profiles={configProfiles}
                    profileName={profileName}
                    profileNote={profileNote}
                    setProfileName={setProfileName}
                    setProfileNote={setProfileNote}
                    onSave={saveConfigProfile}
                    onApply={applyConfigProfile}
                    onDelete={deleteConfigProfile}
                    busy={busy}
                  />
                </Card>
              </aside>
              <aside className="pa-json-column">
                <BeginnerMissionsPanel progress={userProgress} busy={busy} onRefresh={() => void refreshPersonaHistoryAndProgress(true)} />
                <ReadinessPanel readiness={readiness} onRefresh={refreshReadiness} busy={busy} />
                <ModelReadinessPanel readiness={modelReadiness} onRefresh={refreshModelReadiness} onTest={testLlm} busy={busy} />
                <ModelExportPreviewPanel preview={modelExportPreview} busy={busy} onRefresh={refreshModelExportPreview} onInspect={setSelected} />
              </aside>
            </div>
          </Tabs.Panel>

          <Tabs.Panel value="adapter" pt="md">
            <div className="pa-adapter-grid">
              <section className="pa-main-column">
                <Card className="pa-panel">
                  <Group justify="space-between" align="flex-start" mb="md">
                    <div>
                      <Group gap={8}>
                        <IconPlugConnected size={18} />
                        <Text fw={900}>NapCat QQ 适配器</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        面向 NapCat/OneBot 事件：先 HTTP 上报入站，PA 判断是否唤醒；出站默认 dry-run，确认后再真实发送。
                      </Text>
                    </div>
                    <Group gap={6}>
                      <Badge variant="light" color={policyRiskColor}>{policyRisk === 'live' ? 'live send' : policyRisk === 'dry_run' ? 'dry-run' : 'local safe'}</Badge>
                      <Button size="xs" variant="subtle" loading={isBusy('napcat')} onClick={launchNapcat}>打开 NapCat</Button>
                      <Button size="xs" variant="light" loading={isBusy('napcat')} onClick={refreshNapcatGuide}>刷新接入</Button>
                    </Group>
                  </Group>
                  <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
                    <Select label="平台适配器" value={String(draft.platform_adapter || 'local')} data={adapterModes} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'platform_adapter', value || 'local')} />
                    <TextInput label="NapCat HTTP API 地址" value={String(draft.qq_napcat_http_url || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'qq_napcat_http_url', event.currentTarget.value)} />
                    <TextInput label="主人 QQ" description="主人永远优先放行；留空则不启用主人特权。" value={String(draft.owner_qq || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'owner_qq', event.currentTarget.value)} />
                    <Select label="名单模式" description="白名单为空时先允许，方便本地初测；真实群建议填写群/用户白名单。" value={String(draft.qq_access_mode || 'off')} data={accessModes} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'qq_access_mode', value || 'off')} />
                    <TriggerModeSwitches draft={draft} setDraft={setDraftEditable} compact />
                    <CsvTextInput label="群聊昵称/艾特别名" value={draft.group_at_names} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'group_at_names', value)} />
                    <CsvTextInput label="关键词唤醒" value={draft.wake_keywords} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'wake_keywords', value)} />
                    <NumberInput label="群聊 AP 门控 tick" description="群聊全量（AP门控）时，普通群消息先只进入 AP 跑这些 tick。" value={Number(draft.group_all_ap_gate_ticks ?? 3)} min={2} max={20} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_all_ap_gate_ticks', Number(v) || 3)} />
                    <Switch label="群聊连续对话窗口" description="群聊唤醒后，接下来 N 条普通群消息先过轻量门控；像是在对配置别名或关键词说话才进入 PA。" checked={draft.group_continuity_window_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_window_enabled', event.currentTarget.checked)} />
                    <NumberInput label="连续窗口消息数 N" description="连续 N 条都没通过门控后，该群回到静默触发状态。" value={Number(draft.group_continuity_window_messages ?? 6)} min={1} max={80} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_window_messages', Number(v) || 6)} />
                    <NumberInput label="连续窗口闲置超时 ms" description="默认 180000，也就是 3 分钟无新消息则关闭；0 表示不按闲置时间关闭。" value={Number(draft.group_continuity_window_timeout_ms ?? 180000)} min={0} max={86400000} step={10000} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_window_timeout_ms', Number(v) || 0)} />
                    <TextInput label="连续窗口门控模型" description="留空沿用主模型；建议填轻量模型。" value={String(draft.group_continuity_gate_model || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_gate_model', event.currentTarget.value)} />
                    <NumberInput label="连续门控最低置信度" value={Number(draft.group_continuity_gate_min_confidence ?? 0.62)} min={0} max={1} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_gate_min_confidence', Number(v) || 0)} />
                    <NumberInput label="连续门控上下文条数" description="只给轻量门控看本群近期历史，避免完整 AP prompt。" value={Number(draft.group_continuity_gate_context_messages ?? 18)} min={4} max={80} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_continuity_gate_context_messages', Number(v) || 18)} />
                    <NumberInput label="发送最小间隔 ms" value={Number(draft.qq_napcat_min_send_interval_ms ?? 1200)} min={0} max={60000} step={100} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'qq_napcat_min_send_interval_ms', Number(v) || 0)} />
                    <Switch label="回复自动分段" description="开启后公开 reply 可按标点或分段符拆成多条 QQ 消息；主页仍保留完整回复。" checked={Boolean(draft.reply_auto_segment_enabled)} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'reply_auto_segment_enabled', event.currentTarget.checked)} />
                    <TextInput label="回复分段符" description="例如 |。开启后会进入 reply 提示词；发送时去掉该符号。" value={String(draft.reply_auto_segment_delimiter || '')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'reply_auto_segment_delimiter', event.currentTarget.value)} />
                    <Select label="分段间隔模式" value={String(draft.reply_segment_interval_mode || 'adaptive')} data={replySegmentIntervalModes} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_interval_mode', value || 'adaptive')} />
                    <NumberInput label="固定分段间隔 ms" value={Number(draft.reply_segment_fixed_interval_ms ?? 650)} min={0} max={60000} step={50} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_fixed_interval_ms', Number(v) || 0)} />
                    <NumberInput label="自动间隔最小 ms" value={Number(draft.reply_segment_adaptive_min_ms ?? 420)} min={0} max={60000} step={50} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_adaptive_min_ms', Number(v) || 0)} />
                    <NumberInput label="自动间隔最大 ms" value={Number(draft.reply_segment_adaptive_max_ms ?? 1800)} min={0} max={60000} step={50} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_adaptive_max_ms', Number(v) || 0)} />
                    <NumberInput label="每字增加 ms" value={Number(draft.reply_segment_adaptive_ms_per_char ?? 55)} min={0} max={5000} step={5} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_adaptive_ms_per_char', Number(v) || 0)} />
                    <NumberInput label="间隔随机波动" description="0.1 表示约 10%。" value={Number(draft.reply_segment_interval_jitter ?? 0.1)} min={0} max={0.5} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_interval_jitter', Number(v) || 0)} />
                    <NumberInput label="自动分段目标字数" value={Number(draft.reply_segment_target_chars ?? 16)} min={4} max={120} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_target_chars', Number(v) || 16)} />
                    <NumberInput label="最多分段数" value={Number(draft.reply_segment_max_segments ?? 8)} min={1} max={40} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'reply_segment_max_segments', Number(v) || 8)} />
                    <CsvTextInput label="用户白名单" placeholder="123456, 234567" value={draft.qq_user_whitelist} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'qq_user_whitelist', value)} />
                    <CsvTextInput label="群白名单" placeholder="群号，用逗号分隔" value={draft.qq_group_whitelist} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'qq_group_whitelist', value)} />
                    <CsvTextInput label="用户黑名单" value={draft.qq_user_blacklist} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'qq_user_blacklist', value)} />
                    <CsvTextInput label="群黑名单" value={draft.qq_group_blacklist} onChange={(value) => updateField<AgentConfig>(setDraftEditable, 'qq_group_blacklist', value)} />
                    <NumberInput label="群聊概率触发 0~1" description="用于偶尔主动醒来；0 表示关闭。" value={Number(draft.group_trigger_probability ?? 0)} min={0} max={1} step={0.01} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'group_trigger_probability', Number(v) || 0)} />
                      <Switch label="启用 NapCat" checked={Boolean(draft.qq_napcat_enabled)} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'qq_napcat_enabled', event.currentTarget.checked)} />
                      <Switch label="dry-run 安全模式（推荐先开）" checked={draft.qq_napcat_dry_run !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'qq_napcat_dry_run', event.currentTarget.checked)} />
                    <Switch label="短期上下文按 QQ 对象隔离" description="开启后私聊和群聊的近期对话分开给 LLM；AP 状态池、长期记忆和能量演化仍共享。" checked={draft.qq_short_context_isolation_enabled !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'qq_short_context_isolation_enabled', event.currentTarget.checked)} />
                    <Switch label="群聊艾特触发" checked={draft.group_trigger_at !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'group_trigger_at', event.currentTarget.checked)} />
                    <Switch label="群聊关键词触发" checked={draft.group_trigger_keyword !== false} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'group_trigger_keyword', event.currentTarget.checked)} />
                    <Switch label="群聊无艾特也进入 PA 判断" checked={Boolean(draft.allow_group_without_at)} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'allow_group_without_at', event.currentTarget.checked)} />
                    <Switch label="表情包小偷" description="收到图片后让多模态模型判断是否保存。" checked={Boolean(draft.sticker_steal_enabled)} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'sticker_steal_enabled', event.currentTarget.checked)} />
                    <TextInput label="表情包目录" value={String(draft.sticker_library_dir || stickers?.library_dir || serverConfig.sticker_library_dir || 'observatory/outputs/agent/stickers')} onChange={(event) => updateField<AgentConfig>(setDraftEditable, 'sticker_library_dir', event.currentTarget.value)} />
                    <NumberInput label="Prompt 近期表情包" value={Number(draft.sticker_prompt_recent_limit ?? 5)} min={0} max={30} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'sticker_prompt_recent_limit', Number(v) || 0)} />
                    <NumberInput label="Prompt 高频表情包" value={Number(draft.sticker_prompt_top_limit ?? 5)} min={0} max={30} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'sticker_prompt_top_limit', Number(v) || 0)} />
                    <NumberInput label="Prompt 随机表情包" value={Number(draft.sticker_prompt_random_limit ?? 10)} min={0} max={60} step={1} onChange={(v) => updateField<AgentConfig>(setDraftEditable, 'sticker_prompt_random_limit', Number(v) || 0)} />
                  </SimpleGrid>
                  <Group justify="flex-end" mt="md">
                    <Button leftSection={<IconDeviceFloppy size={16} />} loading={isBusy('config')} onClick={saveConfig}>保存适配器配置</Button>
                  </Group>
                </Card>

                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" align="flex-start" mb="sm">
                    <div>
                      <Group gap={8}>
                        <IconClipboardList size={18} />
                        <Text fw={900}>NapCat 入站/出站日志</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        这里显示 OneBot webhook 进入 PA 后的真实判定：名单过滤、唤醒、AP 门控、写入主页聊天流，以及回发到 QQ 的结果。
                      </Text>
                    </div>
                    <Group gap={6}>
                      <SegmentedControl
                        size="xs"
                        value={adapterLogView}
                        onChange={setAdapterLogView}
                        data={[
                          { value: 'important', label: '重点' },
                          { value: 'detail', label: '详细' },
                          { value: 'errors', label: '报错' },
                        ]}
                      />
                      <ActionIcon size="sm" variant="subtle" loading={isBusy('diag')} onClick={() => void refreshAdapterEvents(true)}>
                        <IconRefresh size={14} />
                      </ActionIcon>
                    </Group>
                  </Group>
                  <Group gap={6} mb="xs" wrap="wrap">
                    <Badge size="xs" variant="light" color="blue">显示 {formatCount(adapterEventCounts.returned)}</Badge>
                    <Badge size="xs" variant="outline">扫描 {formatCount(adapterEventCounts.total_scanned)}</Badge>
                    <Badge size="xs" variant="light" color="teal">通过 {formatCount(adapterEventCounts.passed)}</Badge>
                    <Badge size="xs" variant="light" color="gray">过滤 {formatCount(adapterEventCounts.filtered)}</Badge>
                    <Badge size="xs" variant="light" color="green">回发 {formatCount(adapterEventCounts.replied)}</Badge>
                    <Badge size="xs" variant="light" color={asNumber(adapterEventCounts.warn, 0) ? 'yellow' : 'gray'}>警告 {formatCount(adapterEventCounts.warn)}</Badge>
                    <Badge size="xs" variant="light" color={asNumber(adapterEventCounts.error, 0) ? 'red' : 'gray'}>错误 {formatCount(adapterEventCounts.error)}</Badge>
                  </Group>
                  <ScrollArea.Autosize mah={420}>
                    <AdapterEventList rows={adapterEvents} onSelect={setSelected} />
                  </ScrollArea.Autosize>
                </Card>

                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" mb="xs">
                    <Text fw={900}>唤醒测试</Text>
                    <Group gap={6}>
                      <Button size="compact-xs" variant="subtle" loading={isBusy('wake')} onClick={previewWake}>预览</Button>
                      <Button size="compact-xs" variant="subtle" loading={isBusy('wake')} onClick={previewNapcatEvent}>NapCat 预览</Button>
                      <Button size="compact-xs" variant="light" loading={isBusy('wake')} onClick={runWakeMatrix}>矩阵</Button>
                    </Group>
                  </Group>
                  <SimpleGrid cols={{ base: 1, md: 2 }} spacing="xs">
                    <Select
                      size="xs"
                      label="消息场景"
                      value={wakeMessageType}
                      data={[
                        { value: 'group', label: '群聊' },
                        { value: 'private', label: '私聊' },
                      ]}
                      onChange={(value) => setWakeMessageType(value || 'group')}
                    />
                    <TextInput size="xs" label="mentions / at" value={wakeMentions} placeholder="PA, psyarch" onChange={(event) => setWakeMentions(event.currentTarget.value)} />
                  </SimpleGrid>
                  <Textarea mt="xs" label="唤醒预览文本" minRows={3} autosize value={wakeText} onChange={(event) => setWakeText(event.currentTarget.value)} />
                  <Group grow mt="sm">
                    <Button size="xs" variant="light" onClick={previewNapcatEvent} loading={isBusy('wake')}>NapCat 预览</Button>
                    <Button size="xs" variant="light" onClick={simulateNapcat} loading={isBusy('napcat')}>NapCat 模拟写入</Button>
                    <Button size="xs" variant="light" onClick={testNapcatReply} loading={isBusy('napcat')}>测试出站</Button>
                  </Group>
                  <Textarea mt="xs" label="出站测试文本" minRows={2} autosize value={replyText} onChange={(event) => setReplyText(event.currentTarget.value)} />
                </Card>
              </section>

              <aside className="pa-side-column">
                <Card className="pa-panel">
                  <Group justify="space-between" mb="xs">
                    <Text fw={900}>接入说明</Text>
                    <Button size="compact-xs" variant="subtle" onClick={() => setSelected(napcatGuide || {})}>JSON</Button>
                  </Group>
                  {napcatGuide?.webhook_url ? (
                    <TextInput size="xs" readOnly label="PA Webhook URL" value={String(napcatGuide.webhook_url || '')} onFocus={(event) => event.currentTarget.select()} />
                  ) : null}
                  {napcatGuide?.napcat_local_repo ? (
                    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing={6} mt="xs">
                      <TextInput size="xs" readOnly label="NapCat 本地目录" value={String(napcatGuide.napcat_local_repo.path || '')} onFocus={(event) => event.currentTarget.select()} />
                      <TextInput size="xs" readOnly label="OneBot 配置" value={String(napcatGuide.napcat_local_repo.onebot_config || '')} onFocus={(event) => event.currentTarget.select()} />
                    </SimpleGrid>
                  ) : null}
                  {selectedPreview?.launcher || selectedPreview?.ports_after ? (
                    <Stack gap={6} mt="xs">
                      <Group gap={6}>
                        <Badge size="xs" variant="light" color={selectedPreview?.ports_after?.webui ? 'teal' : 'yellow'}>WebUI {selectedPreview?.ports_after?.webui ? 'ready' : 'starting'}</Badge>
                        <Badge size="xs" variant="light" color={selectedPreview?.ports_after?.http_api ? 'teal' : 'yellow'}>HTTP API {selectedPreview?.ports_after?.http_api ? 'ready' : 'starting'}</Badge>
                        <Badge size="xs" variant="outline">{String(selectedPreview?.launch_mode || 'launch')}</Badge>
                        {selectedPreview?.onebot_config_updated ? <Badge size="xs" color="blue">配置已写入</Badge> : null}
                      </Group>
                      <Text size="xs" c="dimmed">{shortText(String(selectedPreview?.note || ''), 180)}</Text>
                    </Stack>
                  ) : null}
                  <Stack gap={6} mt="sm">
                    {napcatOfficialNotes.map((note) => (
                      <div key={note} className="pa-note-row">{note}</div>
                    ))}
                  </Stack>
                  {napcatGuide ? (
                    <Stack gap={6} mt="sm">
                      {asArray<AnyRecord>(napcatGuide.checks).map((check) => (
                        <button key={String(check.id)} type="button" className="agent-readiness-row" onClick={() => setSelected(check)}>
                          <Badge size="xs" variant="light" color={check.status === 'pass' ? 'teal' : check.status === 'fail' ? 'red' : 'yellow'}>{String(check.status)}</Badge>
                          <span>
                            <strong>{shortText(String(check.id || '-'), 30)}</strong>
                            <small>{shortText(String(check.detail || check.action || ''), 108)}</small>
                          </span>
                        </button>
                      ))}
                    </Stack>
                  ) : <div className="empty-box compact">刷新后显示 NapCat guide。</div>}
                </Card>
                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" mb="xs">
                    <Text fw={900}>触发策略</Text>
                    <Button size="compact-xs" variant="subtle" loading={isBusy('wake')} onClick={() => refreshWakePolicy(true)}>刷新</Button>
                  </Group>
                  <div className="agent-trigger-policy-grid">
                    {policyRows.map((row) => (
                      <button key={row.label} type="button" className="agent-trigger-policy-item" onClick={() => setSelected(row)}>
                        <span>{row.label}</span>
                        <strong>{row.value}</strong>
                        <small>{row.note}</small>
                      </button>
                    ))}
                  </div>
                </Card>
                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" align="flex-start" gap="sm" mb="xs">
                    <div>
                      <Group gap={8}>
                        <IconPhoto size={18} />
                        <Text fw={900}>表情包小偷</Text>
                        <Badge variant="light" color={stickers?.enabled ? 'teal' : 'gray'}>{stickers?.enabled ? 'on' : 'off'}</Badge>
                      </Group>
                      <Text size="xs" c="dimmed">
                        收到图片后由多模态模型判断是否保存；进入 prompt 的列表按近期、高频和随机抽样组合。
                      </Text>
                    </div>
                    <Group gap={6}>
                      <Badge size="xs" variant="outline">{formatCount(stickerRows.length)} 个</Badge>
                      <ActionIcon size="sm" variant="subtle" loading={isBusy('diag')} aria-label="刷新表情包目录" onClick={() => void refreshStickers(false)}>
                        <IconRefresh size={14} />
                      </ActionIcon>
                      <Button size="compact-xs" variant="subtle" loading={isBusy('diag')} onClick={() => void syncStickers()}>同步</Button>
                      <Button size="compact-xs" variant="subtle" color="red" disabled={!stickerRows.length} loading={isBusy('diag')} onClick={() => void clearStickers()}>清空</Button>
                      <Button size="compact-xs" variant="subtle" onClick={() => setSelected(stickers || {})}>JSON</Button>
                    </Group>
                  </Group>
                  {Number(stickers?.sync?.removed_missing || 0) > 0 ? (
                    <Text size="xs" c="orange" mb="xs">
                      已自动移除 {formatCount(stickers?.sync?.removed_missing)} 条本地文件不存在的注册项。
                    </Text>
                  ) : null}
                  <SimpleGrid cols={{ base: 1, sm: 3 }} spacing={6} mb="xs">
                    <div className="agent-sticker-stat">
                      <span>近期</span>
                      <strong>{formatCount(stickers?.selection_limits?.recent ?? draft.sticker_prompt_recent_limit)}</strong>
                    </div>
                    <div className="agent-sticker-stat">
                      <span>高频</span>
                      <strong>{formatCount(stickers?.selection_limits?.top ?? draft.sticker_prompt_top_limit)}</strong>
                    </div>
                    <div className="agent-sticker-stat">
                      <span>随机</span>
                      <strong>{formatCount(stickers?.selection_limits?.random ?? draft.sticker_prompt_random_limit)}</strong>
                    </div>
                  </SimpleGrid>
                  <Text size="xs" c="dimmed" mb="xs">
                    {shortText(String(stickers?.library_dir || draft.sticker_library_dir || '默认 PA outputs/agent/stickers'), 140)}
                  </Text>
                  <ScrollArea.Autosize mah={260}>
                    <Stack gap={6}>
                      {(selectedStickerRows.length ? selectedStickerRows : stickerRows).slice(0, 12).map((item, index) => (
                        <div key={String(item.id || item.name || index)} className="agent-sticker-row">
                          <button type="button" className="agent-sticker-main" onClick={() => setSelected(item)}>
                            <span>
                              <strong>{shortText(String(item.name || item.id || '-'), 34)}</strong>
                              <small>{shortText(String(item.meaning || item.path || '-'), 100)}</small>
                            </span>
                            <Group gap={4}>
                              {item.bucket ? <Badge size="xs" variant="light">{String(item.bucket)}</Badge> : null}
                              <Badge size="xs" variant="outline">用 {formatCount(item.use_count)}</Badge>
                            </Group>
                          </button>
                          <Tooltip label="删除表情包和本地文件">
                            <ActionIcon size="sm" variant="subtle" color="red" loading={isBusy('diag')} aria-label="删除表情包" onClick={() => void deleteSticker(item)}>
                              <IconTrash size={14} />
                            </ActionIcon>
                          </Tooltip>
                        </div>
                      ))}
                      {!stickerRows.length ? <div className="empty-box compact">还没有保存表情包。收到图片后，开启表情包小偷和多模态模型即可自动筛选。</div> : null}
                    </Stack>
                  </ScrollArea.Autosize>
                </Card>
                <Card className="pa-panel" mt="md">
                  <Text fw={900} mb="xs">Wake / Outbox 历史</Text>
                  <ScrollArea.Autosize mah={380}>
                    <Stack gap={8}>
                      <OutboxList rows={outbox} onSelect={setSelected} />
                      <Divider label="Wake trace" labelPosition="left" />
                      {wakePreviews.length ? wakePreviews.slice().reverse().slice(0, 8).map((item, index) => (
                        <button key={`${item.ts || index}-${item.reason || 'wake'}`} type="button" className="agent-event-row" onClick={() => setSelected(item)}>
                          <span>
                            <strong>{item.should_wake ? 'wake' : 'sleep'} · {item.reason || '-'}</strong>
                            <small>{timeLabel(item.ts)} | {item.message_type || '-'} | {triggerModesLabel(item.trigger_modes, item.trigger_mode)}</small>
                            <small>{shortText(item.text || '', 88)}</small>
                          </span>
                          <Badge variant="light" color={item.should_wake ? 'teal' : 'gray'}>
                            {item.keyword || (item.should_wake ? 'on' : 'off')}
                          </Badge>
                        </button>
                      )) : <div className="empty-box compact">暂无唤醒预览。</div>}
                    </Stack>
                  </ScrollArea.Autosize>
                </Card>
              </aside>

              <aside className="pa-json-column">
                <Card className="pa-panel pa-sticky-json">
                  <Text fw={900} mb="xs">适配器调试包</Text>
                  <JsonInspector value={selectedPreview} title="Adapter JSON" maxHeight={640} />
                </Card>
              </aside>
            </div>
          </Tabs.Panel>

          <Tabs.Panel value="tools" pt="md">
            <div className="pa-tools-grid">
              <section className="pa-main-column">
                <Card className="pa-panel">
                  <Group justify="space-between" align="flex-start" mb="md">
                    <div>
                      <Group gap={8}>
                        <IconTool size={18} />
                        <Text fw={900}>MCP / Skills / 知识库</Text>
                      </Group>
                  <Text size="xs" c="dimmed">
                    先提供真实可运行的本地工具、图书馆和协议蓝图；外部工具建议先 dry-run，再允许回灌 AP。
                  </Text>
                    </div>
                    <Group gap={6}>
                      <Badge variant="light" color={draft.mcp_enabled ? 'teal' : 'gray'}>MCP {draft.mcp_enabled ? 'on' : 'off'}</Badge>
                      <Badge variant="light" color={draft.skill_enabled !== false ? 'teal' : 'gray'}>Skills {draft.skill_enabled !== false ? 'on' : 'off'}</Badge>
                    </Group>
                  </Group>
                  <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
                    {toolBlueprints.map((tool) => (
                      <button key={tool.id} type="button" className="agent-tool-matrix-item" onClick={() => setSelected(tool)}>
                        <Group justify="space-between" gap={6} wrap="nowrap">
                          <strong>{tool.label}</strong>
                          <Badge size="xs" variant="light" color={tool.status === '可运行' ? 'teal' : 'yellow'}>{tool.status}</Badge>
                        </Group>
                        <small>{tool.detail}</small>
                      </button>
                    ))}
                  </SimpleGrid>
                </Card>

                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" mb="xs">
                    <Text fw={900}>手动执行工具</Text>
                    <Button size="compact-xs" variant="subtle" loading={diagBusy} onClick={() => refreshDiagnostics()}>刷新</Button>
                  </Group>
                  <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
                    <Select
                      label="本地工具"
                      value={toolName}
                      data={toolOptions.length ? toolOptions : [{ value: 'time', label: '本地时间' }]}
                      onChange={(value) => setToolName(value || 'time')}
                    />
                    <Textarea label="参数 JSON" minRows={3} autosize value={toolArgs} onChange={(event) => setToolArgs(event.currentTarget.value)} />
                  </SimpleGrid>
                  <Button mt="sm" variant="light" leftSection={<IconHammer size={14} />} loading={isBusy('tool')} onClick={runTool}>
                    执行并回灌 AP
                  </Button>
                </Card>

                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" align="flex-start" mb="xs">
                    <div>
                      <Group gap={8}>
                        <IconBook size={18} />
                        <Text fw={900}>日记本管理</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        人工查看、修订和删除长期日记；LLM 的 write_diary/read_diary 也会读写同一份账本。
                      </Text>
                    </div>
                    <Group gap={6}>
                      <Badge variant="light" color={diaryBook?.ok === false || draft.diary_enabled === false ? 'gray' : 'teal'}>
                        {formatCount(diaryBook?.total ?? asArray<AnyRecord>(diaryBook?.entries).length)} 条
                      </Badge>
                      <Tooltip label="刷新日记本">
                        <ActionIcon size="sm" variant="subtle" loading={toolBusy} aria-label="刷新日记本" onClick={() => void refreshDiary(true)}>
                          <IconRefresh size={15} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Group>
                  <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
                    <ScrollArea.Autosize mah={360}>
                      <Stack gap="xs">
                        <Button size="compact-sm" variant="light" leftSection={<IconBook size={14} />} onClick={startNewDiaryEntry}>
                          新建日记
                        </Button>
                        {asArray<AnyRecord>(diaryBook?.entries).map((entry) => (
                          <button key={String(entry.id)} type="button" className="agent-tool-row" onClick={() => void selectDiaryEntry(entry)}>
                            <div>
                              <strong>{shortText(String(entry.title || entry.id || '-'), 36)}</strong>
                              <small>{shortText(String(entry.preview || entry.updated_at || ''), 80)}</small>
                            </div>
                            <Badge variant="light" color={Number(entry.importance || 0) >= 80 ? 'red' : Number(entry.importance || 0) >= 60 ? 'yellow' : 'gray'}>
                              {formatCount(entry.importance)}
                            </Badge>
                          </button>
                        ))}
                        {!asArray<AnyRecord>(diaryBook?.entries).length ? <div className="empty-box compact">当前还没有日记。可以让想法写日记，也可以在这里手动新增。</div> : null}
                      </Stack>
                    </ScrollArea.Autosize>
                    <Stack gap="xs">
                      <TextInput label="标题" value={String(diaryDraft.title || '')} onChange={(event) => setDiaryDraft((prev) => ({ ...prev, title: event.currentTarget.value }))} />
                      <NumberInput label="重要性" value={Number(diaryDraft.importance ?? 70)} min={0} max={100} step={1} onChange={(v) => setDiaryDraft((prev) => ({ ...prev, importance: Number(v) || 0 }))} />
                      <Textarea label="内容" minRows={7} autosize value={String(diaryDraft.content || '')} onChange={(event) => setDiaryDraft((prev) => ({ ...prev, content: event.currentTarget.value }))} />
                      <Group gap="xs">
                        <Button size="compact-sm" variant="light" leftSection={<IconDeviceFloppy size={14} />} loading={toolBusy} onClick={() => void saveDiaryEntry(diaryDraft.id ? 'overwrite' : 'create')}>
                          保存
                        </Button>
                        {diaryDraft.id ? (
                          <Button size="compact-sm" variant="subtle" color="red" leftSection={<IconTrash size={14} />} loading={toolBusy} onClick={() => void deleteDiaryEntry()}>
                            删除
                          </Button>
                        ) : null}
                      </Group>
                    </Stack>
                  </SimpleGrid>
                </Card>

                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" align="flex-start" mb="xs">
                    <div>
                      <Group gap={8}>
                        <IconClock size={18} />
                        <Text fw={900}>定时任务</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        到点后会把 “[闹钟]: 提示信息” 作为前端输入插入队列，由想法继续决定下一步。
                      </Text>
                    </div>
                    <Group gap={6}>
                      <Badge variant="light" color={scheduledTasks?.enabled === false || draft.scheduled_tasks_enabled === false ? 'gray' : 'teal'}>
                        {formatCount(scheduledTasks?.active_count)} / {formatCount(scheduledTasks?.limit ?? draft.scheduled_task_limit)}
                      </Badge>
                      <Tooltip label="刷新定时任务">
                        <ActionIcon size="sm" variant="subtle" loading={toolBusy} aria-label="刷新定时任务" onClick={() => void refreshScheduledTasks(true)}>
                          <IconRefresh size={15} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Group>
                  {asArray<AnyRecord>(scheduledTasks?.warnings).length ? (
                    <div className="pa-inline-warning compact">{asArray<AnyRecord>(scheduledTasks?.warnings).map((item) => String(item)).join('；')}</div>
                  ) : null}
                  <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="sm">
                    <ScrollArea.Autosize mah={380}>
                      <Stack gap="xs">
                        <Button size="compact-sm" variant="light" leftSection={<IconClock size={14} />} onClick={startNewScheduledTask}>
                          新建任务
                        </Button>
                        {asArray<AnyRecord>(scheduledTasks?.tasks).map((task) => (
                          <button key={String(task.id)} type="button" className="agent-tool-row" onClick={() => editScheduledTask(task)}>
                            <div>
                              <strong>{shortText(String(task.summary || task.id || '-'), 34)}</strong>
                              <small>{shortText(String(task.next_fire_at || task.status || ''), 72)}</small>
                            </div>
                            <Badge variant="light" color={task.enabled === false || task.status !== 'active' ? 'gray' : 'teal'}>
                              {String(task.status || 'active')}
                            </Badge>
                          </button>
                        ))}
                        {!asArray<AnyRecord>(scheduledTasks?.tasks).length ? <div className="empty-box compact">当前没有定时任务。</div> : null}
                      </Stack>
                    </ScrollArea.Autosize>
                    <Stack gap="xs">
                      <TextInput label="简介" value={String(scheduleDraft.summary || '')} onChange={(event) => setScheduleDraft((prev) => ({ ...prev, summary: event.currentTarget.value }))} />
                      <Textarea label="触发提示" minRows={4} autosize value={String(scheduleDraft.prompt || '')} onChange={(event) => setScheduleDraft((prev) => ({ ...prev, prompt: event.currentTarget.value }))} />
                      <Textarea label="触发规则 JSON" minRows={6} autosize value={String(scheduleDraft.triggerText || '')} onChange={(event) => setScheduleDraft((prev) => ({ ...prev, triggerText: event.currentTarget.value }))} />
                      <Switch label="启用" checked={scheduleDraft.enabled !== false} onChange={(event) => setScheduleDraft((prev) => ({ ...prev, enabled: event.currentTarget.checked }))} />
                      <Group gap="xs">
                        <Button size="compact-sm" variant="light" leftSection={<IconDeviceFloppy size={14} />} loading={toolBusy} onClick={() => void saveScheduledTask()}>
                          保存任务
                        </Button>
                        {scheduleDraft.id ? (
                          <>
                            <Button size="compact-sm" variant="subtle" leftSection={<IconPlayerStop size={14} />} loading={toolBusy} onClick={() => void cancelScheduledTask(scheduleDraft)}>
                              取消
                            </Button>
                            <Button size="compact-sm" variant="subtle" color="red" leftSection={<IconTrash size={14} />} loading={toolBusy} onClick={() => void deleteScheduledTask(scheduleDraft)}>
                              删除
                            </Button>
                          </>
                        ) : null}
                      </Group>
                    </Stack>
                    <Stack gap="xs">
                      <Textarea label="批量命令 JSON" minRows={13} autosize value={scheduleCommandText} onChange={(event) => setScheduleCommandText(event.currentTarget.value)} />
                      <Button variant="light" leftSection={<IconHammer size={14} />} loading={toolBusy} onClick={() => void runScheduledTaskCommand()}>
                        执行命令
                      </Button>
                      <Text size="xs" c="dimmed">
                        支持 commands 数组顺序执行 create、update、cancel。无参数或 operation=list 会查看当前活跃任务。
                      </Text>
                    </Stack>
                  </SimpleGrid>
                </Card>

                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" align="flex-start" mb="xs">
                    <div>
                      <Group gap={8}>
                        <IconBook size={18} />
                        <Text fw={900}>图书馆 / 读书</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        导入 txt、docx、pdf 或直接文本后，读书工具会按短片段喂给 AP，跑空 tick，并保存段落理解和书签。
                      </Text>
                    </div>
                    <Group gap={6}>
                      <Badge variant="light" color={draft.library_enabled === false ? 'gray' : 'teal'}>
                        {formatCount(library?.total ?? asArray<AnyRecord>(library?.books).length)} 本
                      </Badge>
                      <Tooltip label="刷新图书馆">
                        <ActionIcon size="sm" variant="subtle" loading={toolBusy} aria-label="刷新图书馆" onClick={() => void refreshLibrary(true)}>
                          <IconRefresh size={15} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Group>
                  <SimpleGrid cols={{ base: 1, lg: 3 }} spacing="sm">
                    <ScrollArea.Autosize mah={380}>
                      <Stack gap="xs">
                        {asArray<AnyRecord>(library?.books).map((book) => (
                          <button key={String(book.id)} type="button" className="agent-tool-row" onClick={() => void selectLibraryBook(book)}>
                            <div>
                              <strong>{shortText(String(book.title || book.id || '-'), 34)}</strong>
                              <small>{shortText(`${book.progress || '-'} · ${book.summary || ''}`, 78)}</small>
                            </div>
                            <Badge variant="light" color={Number(book.review_count || 0) > 0 ? 'teal' : 'gray'}>
                              {formatCount(book.review_count)} 段
                            </Badge>
                          </button>
                        ))}
                        {!asArray<AnyRecord>(library?.books).length ? <div className="empty-box compact">当前还没有书。可以导入本地文件路径，也可以直接粘贴文本。</div> : null}
                      </Stack>
                    </ScrollArea.Autosize>
                    <Stack gap="xs">
                      <Input.Wrapper label="本地文件路径">
                        <Group gap={6} wrap="nowrap">
                          <TextInput
                            placeholder="D:\\books\\novel.docx"
                            value={String(bookImportDraft.path || '')}
                            onChange={(event) => setBookImportDraft((prev) => ({ ...prev, path: event.currentTarget.value }))}
                            style={{ flex: 1 }}
                          />
                          <Tooltip label="打开本地文件选择框">
                            <ActionIcon variant="light" size="lg" loading={toolBusy} onClick={() => void pickLibraryFile()} aria-label="选择图书文件">
                              <IconFile size={17} />
                            </ActionIcon>
                          </Tooltip>
                        </Group>
                      </Input.Wrapper>
                      <TextInput label="书名" value={String(bookImportDraft.title || '')} onChange={(event) => setBookImportDraft((prev) => ({ ...prev, title: event.currentTarget.value }))} />
                      <Input.Wrapper label="简介">
                        <Stack gap={6}>
                          <Textarea minRows={2} autosize value={String(bookImportDraft.summary || '')} onChange={(event) => setBookImportDraft((prev) => ({ ...prev, summary: event.currentTarget.value }))} />
                          <Button size="compact-sm" variant="subtle" leftSection={<IconSparkles size={14} />} loading={toolBusy} onClick={() => void suggestLibrarySummary()}>
                            大模型自动生成简介
                          </Button>
                        </Stack>
                      </Input.Wrapper>
                      <Textarea label="直接导入文本" minRows={5} autosize value={String(bookImportDraft.text || kbText || '')} onChange={(event) => { setBookImportDraft((prev) => ({ ...prev, text: event.currentTarget.value })); setKbText(event.currentTarget.value); }} />
                      <Button variant="light" leftSection={<IconDatabase size={14} />} loading={toolBusy} onClick={() => void importBook()}>
                        导入图书馆
                      </Button>
                    </Stack>
                    <Stack gap="xs">
                      {selectedBook ? (
                        <>
                          <Text fw={800}>{shortText(String(selectedBook.title || selectedBook.id), 42)}</Text>
                          <Text size="xs" c="dimmed">{shortText(String(selectedBook.summary || selectedBook.progress || '暂无简介'), 160)}</Text>
                          <Group gap="xs">
                            <Button size="compact-sm" variant="light" leftSection={<IconPlayerPlay size={14} />} loading={toolBusy} onClick={() => void readLibraryBook('read')}>
                              读下一段
                            </Button>
                            <Button size="compact-sm" variant="subtle" loading={toolBusy} onClick={() => void readLibraryBook('reviews')}>
                              段落理解
                            </Button>
                            <Button size="compact-sm" variant="subtle" loading={toolBusy} onClick={() => void readLibraryBook('original')}>
                              查看原文
                            </Button>
                            <Button size="compact-sm" variant="subtle" loading={toolBusy} onClick={() => void readLibraryBook('stop')}>
                              暂停
                            </Button>
                            <Button size="compact-sm" variant="subtle" color="red" leftSection={<IconTrash size={14} />} loading={toolBusy} onClick={() => void deleteLibraryBook()}>
                              删除
                            </Button>
                          </Group>
                          <SimpleGrid cols={3} spacing={6}>
                            <button type="button" className="agent-library-mini-stat" onClick={() => setSelected(selectedBook)}>
                              <span>进度</span>
                              <strong>{formatPercent(asNumber(selectedBook.progress, 0), 0)}</strong>
                              <small>{formatCount(selectedBook.cursor)} / {formatCount(selectedBook.text_chars)} 字</small>
                            </button>
                            <button type="button" className="agent-library-mini-stat" onClick={() => setSelected(selectedBook)}>
                              <span>理解</span>
                              <strong>{formatCount(selectedBook.review_count)}</strong>
                              <small>tick {formatCount(selectedBook.read_tick_count)}</small>
                            </button>
                            <button type="button" className="agent-library-mini-stat" onClick={() => setSelected(selectedBook)}>
                              <span>状态</span>
                              <strong>{shortText(String(selectedBook.status || '-'), 10)}</strong>
                              <small>{timeLabel(selectedBook.last_read_at_ms)}</small>
                            </button>
                          </SimpleGrid>
                          <Group justify="space-between" mt={4}>
                            <Text size="xs" fw={800}>段落理解列表</Text>
                            <Badge size="xs" variant="light" color={asArray<AnyRecord>(selectedBook.reviews).length ? 'teal' : 'gray'}>
                              {formatCount(asArray<AnyRecord>(selectedBook.reviews).length)}
                            </Badge>
                          </Group>
                          <ScrollArea.Autosize mah={220}>
                            <Stack gap={6}>
                              {asArray<AnyRecord>(selectedBook.reviews).slice().reverse().slice(0, 8).map((review) => (
                                <button key={String(review.id)} type="button" className={`agent-tool-row ${String(selectedLibraryReview?.id || '') === String(review.id || '') ? 'is-selected' : ''}`} onClick={() => void selectLibraryReview(review)}>
                                  <div>
                                    <strong>{shortText(String(review.title || review.id || '-'), 36)}</strong>
                                    <small>{shortText(String(review.preview || review.understanding || review.summary || ''), 88)}</small>
                                  </div>
                                  <Badge size="xs" variant="outline">{shortText(String(review.range?.start ?? '-'), 8)}</Badge>
                                </button>
                              ))}
                              {!asArray<AnyRecord>(selectedBook.reviews).length ? <div className="empty-box compact">还没有段落理解。点击“读下一段”后会生成第一条。</div> : null}
                            </Stack>
                          </ScrollArea.Autosize>
                          {selectedLibraryOriginal ? (
                            <div className="agent-library-review-detail agent-library-original-detail">
                              <Group justify="space-between" gap={6}>
                                <Text size="xs" fw={800}>{shortText(String(selectedLibraryOriginal.title || selectedBook.title || selectedBook.id || '原文片段'), 42)}</Text>
                                <Badge size="xs" variant="light">原文</Badge>
                              </Group>
                              <Text size="xs" c="dimmed">
                                {formatCount(selectedLibraryOriginal.range?.start)}-{formatCount(selectedLibraryOriginal.range?.end)} 字
                              </Text>
                              <ScrollArea.Autosize mah={220}>
                                <Text size="sm" className="agent-library-review-content">
                                  {String(selectedLibraryOriginal.text || '当前没有可展示的原文片段。')}
                                </Text>
                              </ScrollArea.Autosize>
                            </div>
                          ) : null}
                          {selectedLibraryReview ? (
                            <div className="agent-library-review-detail">
                              <Group justify="space-between" gap={6}>
                                <Text size="xs" fw={800}>{shortText(String(selectedLibraryReview.title || selectedLibraryReview.id || '段落理解'), 42)}</Text>
                                <Badge size="xs" variant="light">tick {formatCount(selectedLibraryReview.ap_tick_count)}</Badge>
                              </Group>
                              <Text size="xs" c="dimmed">
                                {formatCount(selectedLibraryReview.range?.start)}-{formatCount(selectedLibraryReview.range?.end)} 字
                              </Text>
                              <ScrollArea.Autosize mah={220}>
                                <Text size="sm" className="agent-library-review-content">
                                  {String(selectedLibraryReview.understanding || selectedLibraryReview.summary || selectedLibraryReview.preview || '点击上方段落理解条目查看详情。')}
                                </Text>
                              </ScrollArea.Autosize>
                              {selectedLibraryReview.excerpt ? (
                                <details className="agent-library-review-excerpt">
                                  <summary>查看原文片段</summary>
                                  <p>{String(selectedLibraryReview.excerpt)}</p>
                                </details>
                              ) : null}
                            </div>
                          ) : null}
                        </>
                      ) : (
                        <div className="empty-box compact">选择一本书后，可以继续读、查看段落理解、回看原文或删除。</div>
                      )}
                    </Stack>
                  </SimpleGrid>
                </Card>
              </section>

              <aside className="pa-side-column">
                <Card className="pa-panel">
                  <Group justify="space-between" mb="xs">
                    <Text fw={900}>协议注册表</Text>
                    <Button size="compact-xs" variant="subtle" onClick={() => setSelected(protocolRegistry || {})}>JSON</Button>
                  </Group>
                  {protocolRegistry ? (
                    <div className="agent-protocol-grid">
                      {protocolRows.map((row) => (
                        <button key={String(row.id)} type="button" className="agent-protocol-item" onClick={() => setSelected(row)}>
                          <Group justify="space-between" gap={6} wrap="nowrap">
                            <strong>{shortText(String(row.label || row.id || '-'), 30)}</strong>
                            <Badge size="xs" variant="light" color={row.external_call ? 'red' : row.writes_ap_runtime || row.writes_pa_history ? 'yellow' : row.status === 'planned' || row.status === 'off' ? 'gray' : 'teal'}>
                              {String(row.status || row.kind || '-')}
                            </Badge>
                          </Group>
                          <small>{shortText(String(row.detail || row.next_step || ''), 92)}</small>
                        </button>
                      ))}
                    </div>
                  ) : <div className="empty-box compact">刷新后显示 MCP / Skills 注册表。</div>}
                </Card>
                <Card className="pa-panel" mt="md">
                  <Group justify="space-between" mb="xs">
                    <Text fw={900}>能力矩阵</Text>
                    <Button size="compact-xs" variant="subtle" onClick={() => setSelected(toolMatrix || {})}>JSON</Button>
                  </Group>
                  {toolMatrix ? (
                    <div className="agent-tool-matrix-grid">
                      {asArray<AnyRecord>(toolMatrix.tools).map((tool) => (
                        <button key={String(tool.name)} type="button" className="agent-tool-matrix-item" onClick={() => setSelected(tool)}>
                          <Group justify="space-between" gap={6} wrap="nowrap">
                            <strong>{shortText(String(tool.label || tool.name || '-'), 28)}</strong>
                            <Badge size="xs" variant="light" color={tool.enabled ? (tool.writes_ap_runtime ? 'yellow' : 'teal') : 'gray'}>
                              {tool.enabled ? String(tool.mode || 'on') : 'off'}
                            </Badge>
                          </Group>
                          <small>{shortText(String(tool.operator_note || tool.description || ''), 88)}</small>
                        </button>
                      ))}
                    </div>
                  ) : <div className="empty-box compact">刷新后显示能力矩阵。</div>}
                </Card>
                <Card className="pa-panel" mt="md">
                  <MultimodalReadinessPanel readiness={multimodalReadiness} busy={busy} onRefresh={refreshMultimodalReadiness} onInspect={setSelected} />
                </Card>
                <ToolRunLogCard
                  events={toolEvents}
                  counts={toolEventCounts}
                  activeTasks={toolActiveTasks}
                  activeToolTask={(status?.active_tool_task || {}) as AnyRecord}
                  view={toolLogView}
                  busy={isBusy('diag') || isBusy('tool')}
                  onViewChange={setToolLogView}
                  onRefresh={() => void refreshToolEvents(true)}
                  onSelect={setSelected}
                />
                <LibraryReviewReaderCard review={selectedLibraryReview} onInspect={setSelected} />
              </aside>

              <aside className="pa-json-column">
                <Card className="pa-panel pa-sticky-json">
                  <Text fw={900} mb="xs">工具调试包</Text>
                  <JsonInspector value={selectedPreview} title="Tool JSON" maxHeight={640} />
                </Card>
              </aside>
            </div>
          </Tabs.Panel>
        </Tabs>
      </main>
      <Modal
        opened={cloudModalOpen}
        onClose={() => setCloudModalOpen(false)}
        title="放大对象云"
        centered
        size="calc(100vw - 72px)"
      >
        <Text size="xs" c="dimmed" mb="sm">
          放大视图会展示更多高能对象，并继续按总能量聚合。红色更偏实能量，蓝色更偏虚能量，紫色表示两者接近。
        </Text>
        <div className="agent-cloud agent-cloud-bubbles agent-cloud-bubbles-expanded">
          {cloudLayoutExpanded.length ? cloudLayoutExpanded.map((item) => (
            <CloudObject key={`expanded_${item.id}_${item.rank}_${item.group_count || 1}`} item={item} onSelect={setSelected} />
          )) : (
            <div className="pa-cloud-empty-state">
              <strong>当前还没有可展示的对象云</strong>
              <span>先注入种子或发送消息，让 AP 跑出第一批高能对象。</span>
            </div>
          )}
        </div>
      </Modal>
    </div>
  );

}

/*
  Legacy dashboard-style PA workbench kept out of the active render while the
  independent five-tab PA app is productized above.

  return (
    <div className="single-page agent-page">
      <Group justify="space-between" align="flex-start" mb="md">
        <div>
          <Title order={2}>PsyArch Agent</Title>
          <Text c="dimmed" size="sm">
            PA local prototype / AP-coupled bot interface
          </Text>
        </div>
        <Group gap="xs">
          <SegmentedControl
            value={autoRefresh ? 'auto' : 'manual'}
            data={[
              { value: 'auto', label: '自动' },
              { value: 'manual', label: '手动' },
            ]}
            onChange={(value) => setAutoRefresh(value === 'auto')}
          />
          <NumberInput value={refreshMs} min={500} max={60000} step={500} w={118} hideControls onChange={(v) => setRefreshMs(v === '' ? '' : Number(v) || 1200)} />
          <Tooltip label="刷新">
            <ActionIcon variant="light" loading={busy} onClick={() => refresh()}>
              <IconRefresh size={18} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>

      <Grid mb="md">
        <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
          <MetricCard label="Tick" value={formatCount(liveTickCounter)} note={summary.mood_hint || '等待 AP 状态'} icon={<IconBolt size={18} />} tone="ok" />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
          <MetricCard label="ER / EV" value={`${formatNumber(summary.total_er, 2)} / ${formatNumber(summary.total_ev, 2)}`} note={`EV/ER ${formatNumber(summary.ev_to_er_ratio, 2)}`} icon={<IconSparkles size={18} />} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
          <MetricCard label="CP" value={formatNumber(summary.total_cp, 2)} note={`对象 ${formatCount(summary.active_item_count)}`} icon={<IconBrain size={18} />} tone={asNumber(summary.total_cp, 0) > 5 ? 'warn' : 'default'} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 6, lg: 3 }}>
          <MetricCard label="想法 / 消息" value={`${formatCount(status?.session?.thought_count)} / ${formatCount(status?.session?.message_count)}`} note={String(draft.llm_enabled ? draft.model || 'LLM enabled' : 'local fallback')} icon={<IconRobot size={18} />} />
        </Grid.Col>
      </Grid>

      <Card className="agent-runtime-strip" mb="md">
        <Group justify="space-between" gap="sm">
          <Group gap={8}>
            <Badge variant="light" color={draft.llm_enabled ? 'teal' : 'gray'}>
              {draft.llm_enabled ? `LLM ${draft.model || '-'}` : 'Fallback'}
            </Badge>
            <Badge variant="light" color="blue">
              {draft.platform_adapter || 'local'}
            </Badge>
            <Badge variant="light" color="violet">
              {triggerModesLabel(draft.trigger_modes, draft.trigger_mode)}
            </Badge>
            <Badge variant="light" color="yellow">
              ticks {draft.pre_thought_ticks ?? 0}+{draft.post_thought_ticks ?? 0} / soft {draft.max_thoughts_per_turn ?? 1} / hard {draft.max_total_thought_steps_per_turn ?? 0}
            </Badge>
            <Badge variant="light" color={background?.running ? 'teal' : 'gray'}>
              后台 {background?.running ? 'running' : 'stopped'} / {formatCount(background?.step_count)} steps
            </Badge>
            <Badge variant="light" color={latestSelftest ? latestSelftestColor : 'gray'}>
              {latestSelftest ? `自检 ${latestSelftestStatus || 'unknown'} / ${formatCount(latestSelftest.latency_ms)} ms` : '自检未运行'}
            </Badge>
          </Group>
          <Text size="xs" c="dimmed">
            {diagnostics?.recommendations?.[0] || summary.mood_hint || 'PA ready'}
          </Text>
        </Group>
      </Card>

      <Card className="agent-handoff-snapshot-card" mb="md">
        <Group justify="space-between" align="flex-start" gap="md">
          <div className="agent-handoff-snapshot-head">
            <Group gap={8} mb={4}>
              <IconClipboardList size={18} />
              <Text fw={900}>接手快照</Text>
              <Badge variant="light" color={reviewColor}>{reviewLabel}</Badge>
              <Badge variant="outline">read only</Badge>
            </Group>
            <Text size="xs" c="dimmed">
              把早上最该先看的运行健康、历史债务、prompt 成本和外部发送安全压成一屏；只读，不写 PA 历史。
            </Text>
          </div>
          <Group gap={6} wrap="wrap">
            <Button size="xs" variant="light" loading={busy} onClick={refreshPromptContract}>
              刷新预算
            </Button>
            <Button size="xs" variant="subtle" loading={busy} onClick={refreshReplyActionAudit}>
              回复审计
            </Button>
          </Group>
        </Group>
        <div className="agent-handoff-snapshot-grid">
          {handoffSnapshotRows.map((item) => (
            <button key={item.id} type="button" className="agent-handoff-snapshot-item" onClick={() => setSelected(item.source || item)}>
              <Group justify="space-between" gap={6} wrap="nowrap">
                <span>{item.label}</span>
                <Badge size="xs" variant="light" color={item.color}>{item.value}</Badge>
              </Group>
              <small>{shortText(item.detail, 104)}</small>
            </button>
          ))}
        </div>
      </Card>

      <Card className="agent-review-path-card" mb="md">
        <Group justify="space-between" align="flex-start" gap="md">
          <div className="agent-review-path-head">
            <Group gap={8} mb={4}>
              <IconCircleCheck size={18} />
              <Text fw={900}>验收路线</Text>
              <Badge variant="light" color={reviewColor}>{reviewLabel}</Badge>
            </Group>
            <Text size="xs" c="dimmed">
              把交接、晨检、自检、触发矩阵、外部发送和 AP 空态放在同一条线上；早上先看这里，再决定是否进入详细 tab。
            </Text>
          </div>
          <Group gap={6} wrap="wrap">
            <Button size="xs" variant="light" loading={busy} onClick={() => loadHandoff(true)}>
              写入交接
            </Button>
            <Button size="xs" variant="light" loading={busy} onClick={runMorningCheck}>
              晨检
            </Button>
            <Button size="xs" variant="subtle" loading={busy} onClick={runWakeMatrix}>
              触发矩阵
            </Button>
          </Group>
        </Group>
        <div className="agent-review-path-grid">
          {reviewSteps.map((step) => (
            <button key={step.id} type="button" className="agent-review-path-step" onClick={() => setSelected(step)}>
              <Badge size="xs" variant="light" color={step.color}>{step.status}</Badge>
              <strong>{step.label}</strong>
              <small>{step.note}</small>
            </button>
          ))}
        </div>
        <Text size="xs" c="dimmed" mt="xs">
          当前优先动作：{reviewNextAction.label} · {reviewNextAction.note}
        </Text>
      </Card>

      <ActivationRoadmapPanel
        roadmap={activationRoadmap}
        busy={busy}
        onRefresh={refreshActivationRoadmap}
        onInspect={setSelected}
      />

      <Card className="agent-morning-brief-card" mb="md">
        <Group justify="space-between" align="flex-start" gap="md">
          <div className="agent-morning-brief-head">
            <Group gap={8} mb={4}>
              <IconClipboardList size={18} />
              <Text fw={900}>晨间简报</Text>
              <Badge variant="light" color={briefReady ? 'teal' : 'gray'}>{briefReady ? String(morningBrief?.label || 'ready') : '待生成'}</Badge>
            </Group>
            <Text size="xs" c="dimmed">
              只读汇总当前 PA 能力、安全边界和明早操作顺序；写入按钮只保存本地 markdown 简报，不写 PA 对话历史。
            </Text>
          </div>
          <Group gap={6} wrap="wrap">
            <Button size="xs" variant="light" leftSection={<IconClipboardList size={14} />} loading={busy} onClick={() => loadMorningBrief(false)}>
              预览简报
            </Button>
            <Button size="xs" variant="light" leftSection={<IconDeviceFloppy size={14} />} loading={busy} onClick={() => loadMorningBrief(true)}>
              写入简报
            </Button>
          </Group>
        </Group>
        {morningBrief ? (
          <>
            <div className="agent-morning-brief-overview">
              {briefOverview.slice(0, 9).map((item) => (
                <button key={String(item.label)} type="button" className="agent-morning-brief-chip" onClick={() => setSelected(item)}>
                  <span>{String(item.label || '-')}</span>
                  <strong>{shortText(String(item.value || '-'), 80)}</strong>
                </button>
              ))}
            </div>
            <SimpleGrid cols={{ base: 1, md: 3 }} spacing={6} mt="sm">
              <div className="agent-morning-brief-section">
                <Text size="xs" fw={800}>可用能力</Text>
                {briefCapabilities.slice(0, 3).map((item) => (
                  <button key={String(item.id || item.label)} type="button" className="is-plain" onClick={() => setSelected(item)}>
                    <strong>{shortText(String(item.label || '-'), 28)}</strong>
                    <small>{shortText(String(item.detail || ''), 92)}</small>
                  </button>
                ))}
              </div>
              <div className="agent-morning-brief-section">
                <Text size="xs" fw={800}>安全边界</Text>
                {briefSafety.slice(0, 4).map((item) => (
                  <button key={String(item.id || item.label)} type="button" onClick={() => setSelected(item)}>
                    <Badge size="xs" variant="light" color={item.status === 'fail' ? 'red' : item.status === 'warn' ? 'yellow' : 'teal'}>{String(item.status || 'warn')}</Badge>
                    <span>
                      <strong>{shortText(String(item.label || '-'), 26)}</strong>
                      <small>{shortText(String(item.detail || ''), 82)}</small>
                    </span>
                  </button>
                ))}
              </div>
              <div className="agent-morning-brief-section">
                <Text size="xs" fw={800}>下一步</Text>
                {briefActions.slice(0, 4).map((item) => (
                  <button key={String(item.id || item.label)} type="button" onClick={() => setSelected(item)}>
                    <Badge size="xs" variant="outline" color={item.priority === 'high' ? 'red' : item.priority === 'later' ? 'gray' : 'yellow'}>{String(item.priority || 'normal')}</Badge>
                    <span>
                      <strong>{shortText(String(item.label || '-'), 28)}</strong>
                      <small>{shortText(String(item.detail || ''), 82)}</small>
                    </span>
                  </button>
                ))}
              </div>
            </SimpleGrid>
            {briefPath ? (
              <Text size="xs" c="dimmed" mt="xs">
                本地文件：{briefPath}
              </Text>
            ) : null}
          </>
        ) : (
          <div className="empty-box compact">尚未生成晨间简报；点击“预览简报”即可无副作用读取当前状态。</div>
        )}
      </Card>

      <Card className="agent-morning-review-card" mb="md">
        <Group justify="space-between" align="flex-start" gap="md">
          <div className="agent-morning-brief-head">
            <Group gap={8} mb={4}>
              <IconClipboardList size={18} />
              <Text fw={900}>早晨总览</Text>
              <Badge variant="light" color={morningReviewColor}>{String(morningReview?.label || '待加载')}</Badge>
              <Badge variant="outline">{String(morningReview?.side_effects || 'read_only')}</Badge>
            </Group>
            <Text size="xs" c="dimmed">
              只读聚合验收、风险、日志、触发和集成注册表；适合醒来后先看一眼，不运行 AP tick，也不写 PA 历史。
            </Text>
          </div>
          <Group gap={6} wrap="wrap">
            <Button size="xs" variant="light" loading={busy} onClick={refreshMorningReview}>
              刷新总览
            </Button>
            <Button size="xs" variant="subtle" onClick={() => setSelected(morningReview || {})}>
              JSON
            </Button>
          </Group>
        </Group>
        {morningReview ? (
          <>
            <Text size="sm" fw={800} mt="xs">
              {String(morningReview.headline || '')}
            </Text>
            <div className="agent-morning-review-grid">
              {morningReviewCards.map((item) => (
                <button key={String(item.id || item.label)} type="button" className="agent-morning-review-cardlet" onClick={() => setSelected(item)}>
                  <Group justify="space-between" gap={6} wrap="nowrap">
                    <span>{String(item.label || item.id || '-')}</span>
                    <Badge size="xs" variant="light" color={item.tone === 'danger' ? 'red' : item.tone === 'safe' ? 'teal' : 'yellow'}>
                      {String(item.tone || 'watch')}
                    </Badge>
                  </Group>
                  <strong>{shortText(String(item.value || '-'), 72)}</strong>
                  <small>{shortText(String(item.detail || ''), 96)}</small>
                </button>
              ))}
            </div>
            <SimpleGrid cols={{ base: 1, md: 2 }} spacing={8} mt="sm">
              <div className="agent-morning-review-section">
                <Text size="xs" fw={800}>优先动作</Text>
                {morningReviewActions.slice(0, 5).map((item) => (
                  <button key={String(item.id || item.label)} type="button" onClick={() => setSelected(item)}>
                    <Badge size="xs" variant="outline" color={item.priority === 'high' ? 'red' : item.priority === 'later' ? 'gray' : 'yellow'}>
                      {String(item.priority || 'normal')}
                    </Badge>
                    <span>
                      <strong>{shortText(String(item.label || item.id || '-'), 34)}</strong>
                      <small>{shortText(String(item.detail || item.source || ''), 100)}</small>
                    </span>
                  </button>
                ))}
              </div>
              <div className="agent-morning-review-section">
                <Text size="xs" fw={800}>操作顺序</Text>
                {morningReviewSteps.slice(0, 4).map((item, index) => (
                  <button key={`${index}_${item}`} type="button" className="is-plain" onClick={() => setSelected({ index: index + 1, step: item })}>
                    <strong>{index + 1}. {shortText(item, 96)}</strong>
                  </button>
                ))}
              </div>
            </SimpleGrid>
          </>
        ) : (
          <div className="empty-box compact">尚未加载早晨总览；点击“刷新总览”即可只读聚合当前状态。</div>
        )}
      </Card>

      <Card className="agent-acceptance-card" mb="md">
        <Group justify="space-between" align="flex-start" gap="md">
          <div className="agent-acceptance-head">
            <Group gap={8} mb={4}>
              {acceptanceIconIsFail ? <IconAlertTriangle size={18} /> : <IconCircleCheck size={18} />}
              <Text fw={900}>验收摘要</Text>
              <Badge variant="light" color={acceptanceColor}>{acceptanceLabel}</Badge>
            </Group>
            <Text size="xs" c="dimmed">
              汇总当前 readiness、自检、AP 运行态、LLM、NapCat 与后台模式；用于早上快速判断 PA 是否仍处在本地安全测试态。
            </Text>
          </div>
          <Group gap="xs" wrap="wrap">
            <Button size="xs" variant="light" leftSection={<IconTestPipe size={14} />} loading={busy} onClick={runSelftest}>
              运行自检
            </Button>
            <Button size="xs" variant="light" leftSection={<IconSparkles size={14} />} loading={busy} onClick={bootstrap}>
              注入种子
            </Button>
            <Button size="xs" variant="light" leftSection={<IconBolt size={14} />} loading={busy} onClick={runTicks}>
              运行 tick
            </Button>
          </Group>
        </Group>
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }} spacing="sm" mt="sm">
          <div className="agent-acceptance-kpi">
            <span>Readiness</span>
            <strong>{readinessStatus}</strong>
            <small>pass {formatCount(acceptanceReadiness.counts?.pass ?? readiness?.counts?.pass)} / warn {formatCount(acceptanceReadiness.counts?.warn ?? readiness?.counts?.warn)} / fail {formatCount(acceptanceReadiness.counts?.fail ?? readiness?.counts?.fail)}</small>
          </div>
          <div className="agent-acceptance-kpi">
            <span>Selftest</span>
            <strong>{latestSelftestReportStatus}</strong>
            <small>{acceptanceSelftest.available || latestSelftest ? `${formatCount(acceptanceSelftest.latency_ms ?? latestSelftest?.latency_ms)} ms / fail ${formatCount(acceptanceSelftest.counts?.fail ?? latestSelftest?.counts?.fail)}` : '尚未运行沙盒组合测试'}</small>
          </div>
          <div className="agent-acceptance-kpi">
            <span>History</span>
            <strong>{formatCount(acceptanceSession.message_count ?? status?.session?.message_count)} / {formatCount(acceptanceSession.thought_count ?? status?.session?.thought_count)}</strong>
            <small>messages / thoughts，turns {formatCount(acceptanceSession.turn_count ?? status?.session?.turn_count)}</small>
          </div>
          <div className="agent-acceptance-kpi">
            <span>Adapter</span>
            <strong>{String(acceptanceConfig.platform_adapter || draft.platform_adapter || 'local')}</strong>
            <small>{adapterNapcatEnabled ? `NapCat ${adapterNapcatDryRun ? 'dry-run' : 'live'}` : 'local only'}</small>
          </div>
        </SimpleGrid>
        <div className="agent-acceptance-notes">
          {expectedWarns.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      </Card>

      {safetyRadar ? (
        <Card className="agent-safety-radar-card" mb="md">
          <Group justify="space-between" align="flex-start" gap="md">
            <div className="agent-acceptance-head">
              <Group gap={8} mb={4}>
                <IconAlertTriangle size={18} />
                <Text fw={900}>操作风险雷达</Text>
                <Badge variant="light" color={safetyRadar.risk_level === 'danger' ? 'red' : safetyRadar.risk_level === 'watch' ? 'yellow' : 'teal'}>
                  {String(safetyRadar.risk_level || 'watch')}
                </Badge>
              </Group>
              <Text size="xs" c="dimmed">
                区分只读按钮和会改变 PA/AP 状态的按钮；本面板只读，不写历史。
              </Text>
            </div>
            <Button size="xs" variant="subtle" onClick={() => setSelected(safetyRadar)}>
              JSON
            </Button>
          </Group>
          <Group gap={6} mt="xs">
            <Badge size="xs" variant="outline" color="teal">safe {formatCount(safetyRadar.counts?.safe)}</Badge>
            <Badge size="xs" variant="outline" color="yellow">watch {formatCount(safetyRadar.counts?.watch)}</Badge>
            <Badge size="xs" variant="outline" color="red">danger {formatCount(safetyRadar.counts?.danger)}</Badge>
          </Group>
          <div className="agent-safety-radar-grid">
            {asArray<AnyRecord>(safetyRadar.risks).map((item) => (
              <button key={String(item.id)} type="button" className="agent-safety-radar-item" onClick={() => setSelected(item)}>
                <Group justify="space-between" gap={6} wrap="nowrap">
                  <strong>{shortText(String(item.label || item.id || '-'), 30)}</strong>
                  <Badge size="xs" variant="light" color={item.level === 'danger' ? 'red' : item.level === 'watch' ? 'yellow' : 'teal'}>
                    {String(item.level || 'watch')}
                  </Badge>
                </Group>
                <small>{shortText(String(item.detail || item.action || ''), 98)}</small>
              </button>
            ))}
          </div>
          <Group gap={6} mt="xs">
            {asArray<AnyRecord>(safetyRadar.safe_actions).slice(0, 4).map((item) => (
              <Badge key={String(item.id)} size="xs" variant="outline" color="teal">{String(item.label)}</Badge>
            ))}
          </Group>
        </Card>
      ) : null}

      <Card className="agent-quickstart-card" mb="md">
        <Group justify="space-between" align="flex-start" gap="md">
          <div className="agent-quickstart-head">
            <Group gap={8} mb={4}>
              <IconSparkles size={18} />
              <Text fw={900}>启动向导</Text>
              <Badge variant="light" color={acceptanceColor}>{acceptanceLabel}</Badge>
            </Group>
            <Text size="xs" c="dimmed">
              面向早上验收的最短路径：先保存交接，再晨检，必要时激活 AP，最后检查 prompt 和 NapCat。
            </Text>
          </div>
          <Group gap={6} wrap="wrap">
            <Badge size="xs" variant="outline">handoff {handoff?.compact ? 'compact' : handoff ? 'full' : '待生成'}</Badge>
            <Badge size="xs" variant="outline">morning {morningCheck?.overall || morningHistory[morningHistory.length - 1]?.overall || 'none'}</Badge>
            <Badge size="xs" variant="outline">prompt {promptPreview ? `${formatCount(promptPreview.budgets?.estimated_tokens)} tokens` : '未预览'}</Badge>
          </Group>
        </Group>
        <SimpleGrid cols={{ base: 1, md: 3 }} spacing="sm" mt="sm">
          <div className="agent-quickstart-step">
            <Group justify="space-between" gap={6}>
              <Text size="sm" fw={800}>1. 保存交接</Text>
              <Badge size="xs" variant="light" color={handoff ? 'teal' : 'gray'}>{handoff ? 'ready' : 'pending'}</Badge>
            </Group>
            <Text size="xs" c="dimmed">写入 compact handoff，方便恢复上下文和早上复盘。</Text>
            <Group gap={6} mt="xs">
              <Button size="xs" variant="light" loading={busy} onClick={() => loadHandoff(true)}>写入交接</Button>
              <Button size="xs" variant="subtle" loading={busy} onClick={() => loadHandoff(false)}>预览</Button>
            </Group>
          </div>
          <div className="agent-quickstart-step">
            <Group justify="space-between" gap={6}>
              <Text size="sm" fw={800}>2. 晨检与激活</Text>
              <Badge size="xs" variant="light" color={morningCheck?.overall === 'fail' ? 'red' : morningCheck ? 'yellow' : 'gray'}>{morningCheck?.overall || 'pending'}</Badge>
            </Group>
            <Text size="xs" c="dimmed">先跑沙盒晨检；若 AP 状态池为空，再注入种子或少量 tick。</Text>
            <Group gap={6} mt="xs">
              <Button size="xs" variant="light" loading={busy} onClick={runMorningCheck}>晨检</Button>
              <Button size="xs" variant="subtle" loading={busy} onClick={bootstrap}>种子</Button>
              <Button size="xs" variant="subtle" loading={busy} onClick={runTicks}>tick</Button>
            </Group>
          </div>
          <div className="agent-quickstart-step">
            <Group justify="space-between" gap={6}>
              <Text size="sm" fw={800}>3. 接入检查</Text>
              <Badge size="xs" variant="light" color={promptPreview ? 'teal' : 'gray'}>{promptPreview ? 'previewed' : 'pending'}</Badge>
            </Group>
            <Text size="xs" c="dimmed">确认 prompt 预算、NapCat webhook 和 dry-run 状态，再进行真实对话测试。</Text>
            <Group gap={6} mt="xs">
              <Button size="xs" variant="light" loading={busy} onClick={previewPrompt}>Prompt</Button>
              <Button size="xs" variant="subtle" loading={busy} onClick={refreshNapcatGuide}>NapCat</Button>
              <Button size="xs" variant="subtle" loading={busy} onClick={refreshDiagnostics}>诊断</Button>
            </Group>
          </div>
        </SimpleGrid>
      </Card>

      <div className="agent-workbench">
        <Stack className="agent-left" gap="md">
          <ReadinessPanel readiness={readiness} onRefresh={refreshReadiness} busy={busy} />
          <ModelReadinessPanel readiness={modelReadiness} onRefresh={refreshModelReadiness} onTest={testLlm} busy={busy} />
          {runtimeLooksEmpty ? (
            <Card className="agent-empty-runtime-card">
              <Group justify="space-between" mb={6}>
                <Text fw={800}>AP 运行态为空</Text>
                <Badge variant="light" color="yellow">new runtime</Badge>
              </Group>
              <Text size="xs" c="dimmed">
                PA 历史已恢复，但当前 AP 进程刚启动，状态池对象云会在注入人设或运行 tick 后出现。
              </Text>
              <Group grow mt="sm">
                <Button size="xs" variant="light" onClick={bootstrap} loading={busy}>
                  注入种子
                </Button>
                <Button size="xs" variant="light" onClick={runTicks} loading={busy}>
                  运行 tick
                </Button>
              </Group>
            </Card>
          ) : null}
          <Card className="control-card">
            <Group justify="space-between" mb="xs">
              <Text fw={800}>运行控制</Text>
              <Badge variant="light" color={draft.llm_enabled ? 'teal' : 'gray'}>
                {draft.llm_enabled ? 'LLM' : 'Fallback'}
              </Badge>
            </Group>
            <Stack gap="sm">
              <Button leftSection={<IconPlayerPlay size={16} />} loading={busy} onClick={bootstrap}>
                注入人设种子
              </Button>
              <Group grow>
                <NumberInput label="空 ticks" value={manualTicks} min={1} max={80} onChange={(v) => setManualTicks(v === '' ? '' : Number(v) || 1)} />
                <Button mt={24} variant="light" leftSection={<IconBolt size={16} />} loading={busy} onClick={runTicks}>
                  运行
                </Button>
              </Group>
              <Card className="agent-inline-panel">
                <Group justify="space-between" mb={6}>
                  <Text size="sm" fw={800}>后台主观能动性</Text>
                  <Badge variant="light" color={background?.running ? 'teal' : 'gray'}>
                    {background?.running ? '运行中' : '已停止'}
                  </Badge>
                </Group>
                <Group grow>
                  <Button size="xs" variant="light" leftSection={<IconPlayerPlay size={14} />} loading={busy} onClick={backgroundStart}>
                    开始
                  </Button>
                  <Button size="xs" variant="light" leftSection={<IconPlayerPause size={14} />} loading={busy} onClick={backgroundStop}>
                    停止
                  </Button>
                  <Button size="xs" variant="light" leftSection={<IconBolt size={14} />} loading={busy} onClick={backgroundStep}>
                    单步
                  </Button>
                </Group>
                <Text size="xs" c="dimmed" mt={6}>
                  {background?.last_error
                    ? `错误：${background.last_error}`
                    : `当前模式 ${sleepModes.find((item) => item.value === background?.sleep_mode)?.label || background?.sleep_mode || '-'} / 最新 tick ${formatCount(liveTickCounter)} / 触发 ${formatCount(background?.trigger_count)} / tick 间隔 ${formatCount(background?.interval_ms)} ms / AP 检查 ${formatCount(background?.thought_interval_ticks)} / 强化评估 ${formatCount(background?.reinforced_agency_interval_ticks)}`}
                </Text>
                <Text size="xs" c="dimmed">
                  {background?.last_result?.reason
                    ? `最近原因：${String(background.last_result.reason)}；门控：${background?.last_result?.teacher_gate?.should_wake === true ? 'allow' : background?.last_result?.teacher_gate?.should_wake === false ? 'reject' : 'waiting'}`
                    : '这里会显示后台最近一次是等待间隔、驱动力不足、教师允许还是教师拒绝。'}
                </Text>
              </Card>
            <div className="agent-danger-zone">
              <Group justify="space-between" gap={6}>
                <Text size="sm" fw={800}>危险动作</Text>
                <Badge size="xs" variant="light" color="red">需要确认</Badge>
              </Group>
              <Text size="xs" c="dimmed">
                清理按钮会删除本地 PA 历史或诊断日志；不会作为普通刷新使用，点击后还会弹出二次确认。
              </Text>
              <Group grow>
                <Button size="xs" variant="subtle" color="red" leftSection={<IconEraser size={16} />} onClick={() => clear(false)}>
                  清 PA 历史
                </Button>
                <Button size="xs" variant="subtle" color="red" onClick={() => clear(true)}>
                  清 PA + AP 运行态
                </Button>
              </Group>
            </div>
            <Divider label="运行卫生" labelPosition="left" />
            <div className="agent-storage-panel">
              <Group justify="space-between" gap={6} mb={6}>
                <Text size="sm" fw={800}>本地文件</Text>
                <Badge variant="light" color={storageTotalBytes > 2_000_000 ? 'yellow' : 'teal'}>
                  {formatNumber(storageTotalBytes / 1024, 1)} KB
                </Badge>
              </Group>
              <div className="agent-storage-grid">
                {storageRows.slice(0, 10).map((row) => (
                  <button key={row.key} type="button" className="agent-storage-row" onClick={() => setSelected({ file: row.key, ...row.info })}>
                    <span>{row.key}</span>
                    <strong>{formatNumber(asNumber(row.info.bytes, 0) / 1024, 1)} KB</strong>
                  </button>
                ))}
              </div>
              {logPlan ? (
                <div className="agent-log-plan-panel">
                  <Group justify="space-between" gap={6}>
                    <Text size="xs" fw={800}>维护计划</Text>
                    <Badge size="xs" variant="light" color={logPlanTrimLines > 0 ? 'yellow' : 'teal'}>
                      dry-run · {formatCount(logPlanTrimLines)} 行
                    </Badge>
                  </Group>
                  <Text size="xs" c="dimmed">{String(logPlan.recommended_action || logPlan.safety_note || '只读计划，不会写历史。')}</Text>
                  <div className="agent-log-plan-grid">
                    {logPlanTargets.filter((row) => row.default_target).slice(0, 6).map((row) => (
                      <button key={String(row.target)} type="button" className="agent-log-plan-row" onClick={() => setSelected(row)}>
                        <span>{String(row.target)}</span>
                        <strong>{formatCount(row.line_count)} 行</strong>
                        <small>{formatCount(row.would_trim)} 可裁</small>
                      </button>
                    ))}
                  </div>
                  <Group gap={6} mt={6}>
                    <Badge size="xs" variant="outline" color="teal">目标 {formatCount(logPlanTargetCount)}</Badge>
                    <Badge size="xs" variant="outline" color="gray">保护 {formatCount(logPlanProtected.length)}</Badge>
                    <Button size="compact-xs" variant="subtle" onClick={() => setSelected(logPlan)}>
                      JSON
                    </Button>
                  </Group>
                </div>
              ) : null}
              <Group grow align="end" mt="xs">
                <NumberInput label="保留条数" value={logKeep} min={20} max={5000} step={20} onChange={(value) => setLogKeep(Number(value) || 120)} />
                <Button size="xs" variant="light" loading={busy} onClick={() => maintainLogs('trim', true)}>
                  预览
                </Button>
                <Button size="xs" variant="light" loading={busy} onClick={() => maintainLogs('trim', false)}>
                  修剪
                </Button>
              </Group>
              <Button mt="xs" size="xs" fullWidth variant="subtle" color="red" loading={busy} onClick={() => maintainLogs('clear', false)}>
                清空诊断日志
              </Button>
            </div>
          </Stack>
        </Card>

          <Card className="control-card">
            <Group justify="space-between" mb="xs">
              <Text fw={800}>配置</Text>
              <Badge variant="outline">{draft.platform_adapter || 'local'}</Badge>
            </Group>
            <Group gap="xs" mb="sm">
              <Button size="xs" variant="light" leftSection={<IconPlugConnected size={14} />} loading={busy} onClick={testLlm}>
                LLM 连通
              </Button>
              <Button size="xs" variant="light" leftSection={<IconRefresh size={14} />} loading={busy} onClick={refreshDiagnostics}>
                诊断
              </Button>
              <Button size="xs" variant="light" leftSection={<IconFile size={14} />} loading={busy} onClick={() => loadDiagnosticBundle(true)}>
                诊断包
              </Button>
            </Group>
            <SegmentedControl
              fullWidth
              mb="sm"
              data={[
                { value: 'fast', label: '快速' },
                { value: 'balanced', label: '均衡' },
                { value: 'deep', label: '深入' },
              ]}
              onChange={(value) => void applyPreset(value)}
            />
            <ModelPoolPanel
              models={modelPool}
              draft={draft}
              slotDraft={slotDraft}
              setSlotDraft={setSlotDraft}
              onSave={saveModelSlot}
              onApply={applyModelSlot}
              onEdit={editModelSlot}
              onDelete={deleteModelSlot}
              busy={busy}
            />
            <ModelExportPreviewPanel
              preview={modelExportPreview}
              busy={busy}
              onRefresh={refreshModelExportPreview}
              onInspect={setSelected}
            />
            <ConfigProfilePanel
              profiles={configProfiles}
              profileName={profileName}
              profileNote={profileNote}
              setProfileName={setProfileName}
              setProfileNote={setProfileNote}
              onSave={saveConfigProfile}
              onApply={applyConfigProfile}
              onDelete={deleteConfigProfile}
              busy={busy}
            />
            <ConfigEditor draft={draft} setDraft={setDraftEditable} onSave={saveConfig} busy={busy} stickerLibraryDir={String(stickers?.library_dir || serverConfig.sticker_library_dir || '')} />
          </Card>
        </Stack>

        <Stack className="agent-center" gap="md">
          <Card className="agent-scenario-card">
            <Group justify="space-between" align="flex-start" gap="md" mb="sm">
              <div className="agent-scenario-head">
                <Group gap={8} mb={4}>
                  <IconSparkles size={18} />
                  <Text fw={900}>体验剧本</Text>
                  <Badge variant="light">safe preview</Badge>
                  {scenarioRuns.length ? <Badge variant="outline">{scenarioRuns.length} 历史评分</Badge> : null}
                </Group>
                <Text size="xs" c="dimmed">
                  一键载入典型对话场景，先观察 Prompt / thought，再决定是否真正发送；评分只写沙盒诊断日志，不写 PA 历史。
                </Text>
              </div>
              <Group gap={6}>
                <Button size="xs" variant="subtle" loading={busy} onClick={() => previewScenarioPreset(agentScenarioPresets[0])}>
                  预览首个
                </Button>
                <Button size="xs" variant="light" loading={busy} onClick={scoreAllScenarios}>
                  场景评分
                </Button>
              </Group>
            </Group>
            <div className="agent-scenario-grid">
              {agentScenarioPresets.map((scenario) => (
                <button key={scenario.id} type="button" className="agent-scenario-item" onClick={() => applyScenarioPreset(scenario)}>
                  <Group justify="space-between" gap={6} wrap="nowrap">
                    <strong>{scenario.label}</strong>
                    <Badge size="xs" variant="light">{scenario.badge}</Badge>
                  </Group>
                  <small>{scenario.goal}</small>
                  <Group gap={6} mt={6}>
                    <Button
                      size="compact-xs"
                      variant="light"
                      onClick={(event) => {
                        event.stopPropagation();
                        applyScenarioPreset(scenario);
                      }}
                    >
                      填入
                    </Button>
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      loading={busy}
                      onClick={(event) => {
                        event.stopPropagation();
                        void previewScenarioPreset(scenario);
                      }}
                    >
                      Prompt
                    </Button>
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      loading={busy}
                      onClick={(event) => {
                        event.stopPropagation();
                        void scoreScenarioPreset(scenario);
                      }}
                    >
                      评分
                    </Button>
                  </Group>
                </button>
              ))}
            </div>
            {scenarioScores.length ? (
              <div className="agent-scenario-scoreboard">
                <div className="agent-scenario-score-title">
                  <span>本轮评分</span>
                  <small>A/B 沙盒结果，不写 PA 对话历史。</small>
                </div>
                {scenarioScores.map((row) => {
                  const best = (row.best || {}) as AnyRecord;
                  const quality = (best.quality || {}) as AnyRecord;
                  const warnings = asArray<string>(quality.warnings);
                  return (
                    <button key={String(row.scenario_id || row.id)} type="button" className="agent-scenario-score-row" onClick={() => setSelected(row)}>
                      <span>
                        <strong>{shortText(String(row.scenario_label || row.scenario_id || '-'), 30)}</strong>
                        <small>{shortText(String(best.thought || row.scenario_goal || ''), 104)}</small>
                        {warnings.length ? <em>{warnings.slice(0, 2).join(' / ')}</em> : <em>无明显质量警告</em>}
                      </span>
                      <Badge variant="light" color={asNumber(quality.overall, 0) >= 0.72 ? 'teal' : asNumber(quality.overall, 0) >= 0.48 ? 'yellow' : 'red'}>
                        {String(best.variant || row.best || '-')} · {formatPercent(quality.overall, 0)}
                      </Badge>
                    </button>
                  );
                })}
              </div>
            ) : null}
            {scenarioHistory.length ? (
              <div className="agent-scenario-scoreboard agent-scenario-history">
                <div className="agent-scenario-score-title">
                  <span>历史趋势</span>
                  <small>按场景聚合最近诊断日志，展示最近一次、最佳一次和常见警告。</small>
                </div>
                {scenarioHistory.slice(0, 6).map((row) => {
                  const latest = (row.latest || {}) as AnyRecord;
                  const best = (row.best || {}) as AnyRecord;
                  const warning = asArray<AnyRecord>(row.warnings)[0];
                  return (
                    <button key={String(row.scenario_id)} type="button" className="agent-scenario-score-row" onClick={() => setSelected(row)}>
                      <span>
                        <strong>{shortText(String(row.scenario_label || row.scenario_id || '-'), 30)}</strong>
                        <small>
                          latest {String(latest.best || '-')} · 质量分 {formatPercent(latest.best_quality, 0)} | best {String(best.best || '-')} · 质量分 {formatPercent(best.best_quality, 0)}
                        </small>
                        <em>
                          {warning ? `常见警告：${String(warning.warning)} x${formatCount(warning.count)}` : shortText(String(row.scenario_goal || '暂无警告'), 92)}
                        </em>
                      </span>
                      <Badge variant="light" color={asNumber(row.average_quality, 0) >= 0.72 ? 'teal' : asNumber(row.average_quality, 0) >= 0.48 ? 'yellow' : 'red'}>
                        avg {formatPercent(row.average_quality, 0)} · {formatCount(row.count)}x
                      </Badge>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </Card>

          <Card className="agent-persona-seed-card">
            <Group justify="space-between" align="flex-start" gap="md" mb="sm">
              <div className="agent-scenario-head">
                <Group gap={8} mb={4}>
                  <IconBrain size={18} />
                  <Text fw={900}>人设种子</Text>
                  <Badge variant="light" color="violet">draft only</Badge>
                </Group>
                <Text size="xs" c="dimmed">
                  本区只展示当前草稿，不再内置任何角色模板；需要持久化请点“保存配置”，需要进入 AP 请再点“注入种子”。
                </Text>
              </div>
              <Badge variant="outline">{draft.persona_name || '未命名'}</Badge>
            </Group>
            <div className="empty-box compact">
              当前人设名称：{draft.persona_name || '未命名'}。角色信息完全以配置里的文本为准，切换时不会自动混入旧模板。
            </div>
          </Card>

          <Card className="agent-chat-panel">
            <Group justify="space-between" mb="xs">
              <Group gap={8}>
                <IconMessageCircle size={18} />
                <Text fw={800}>对话测试</Text>
              </Group>
              <Group gap={6}>
                {debtMessageCount ? (
                  <Badge variant="light" color="yellow">{formatCount(debtMessageCount)} 历史债务</Badge>
                ) : null}
                <Badge variant="light">{formatCount(displayMessages.length)} messages</Badge>
              </Group>
            </Group>
            <Group justify="space-between" gap="xs" mb="xs">
              <Text size="xs" c="dimmed">
                历史坏样本默认折叠为审计证据，不改写原始 PA 历史；需要看原文时可切换。
              </Text>
              <Switch
                size="xs"
                label="折叠历史债务"
                checked={collapseDebtMessages}
                onChange={(event) => setCollapseDebtMessages(event.currentTarget.checked)}
              />
            </Group>
            <ScrollArea.Autosize mah={420} className="agent-message-scroll">
              <Stack gap="xs">
                {displayMessages.length ? displayMessages.map((item) => (
                  <MessageBubble
                    key={String(item.id || `${item.role}-${item.created_at_ms}`)}
                    item={item}
                    auditRow={replyAuditById.get(String(item.id || ''))}
                    collapseDebt={collapseDebtMessages}
                    onInspect={setSelected}
                    imagePreviewMap={imagePreviewMap}
                  />
                )) : <div className="empty-box">等待第一条消息。</div>}
              </Stack>
            </ScrollArea.Autosize>
            <ReplyActionAuditPanel
              audit={replyActionAudit}
              debtPreview={replyDebtPreview}
              busy={busy}
              onRefresh={refreshReplyActionAudit}
              onDebtPreview={refreshReplyDebtPreview}
              onInspect={setSelected}
            />
            <Divider my="sm" />
            <Textarea
              minRows={3}
              autosize
              value={input}
              onChange={(event) => setInput(event.currentTarget.value)}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            <div className="agent-attachment-strip">
              <FileInput
                leftSection={<IconFile size={16} />}
                placeholder="选择图片/文件"
                multiple
                clearable
                value={fileDraft}
                onChange={(files) => {
                  setFileDraft(asArray<File>(files));
                  setAttachmentPreview(null);
                }}
              />
              <TextInput
                placeholder="附件摘要 / OCR / 视觉描述"
                value={attachmentNote}
                onChange={(event) => {
                  setAttachmentNote(event.currentTarget.value);
                  setAttachmentPreview(null);
                }}
              />
              <Button
                variant="light"
                leftSection={<IconPhoto size={16} />}
                onClick={() => {
                  const text = attachmentNote.trim();
                  if (!text) return;
                  setAttachmentDraft((prev) => [
                    ...prev,
                    { id: `note_${Date.now()}`, kind: 'text', name: 'manual_attachment_note', text, summary: text },
                  ]);
                  setAttachmentNote('');
                  setAttachmentPreview(null);
                }}
              >
                添加摘要
              </Button>
            </div>
            <Group justify="space-between" mt="xs" gap="xs">
              <Text size="xs" c="dimmed">
                附件会先摘要化进入 AP，原始二进制不会直接写入 PA 历史。
              </Text>
              <Button size="xs" variant="subtle" leftSection={<IconPhoto size={14} />} loading={isBusy('tool')} onClick={previewAttachments}>
                预览附件
              </Button>
            </Group>
            <AttachmentDraftPanel
              fileDraft={fileDraft}
              attachmentDraft={attachmentDraft}
              attachmentNote={attachmentNote}
              preview={attachmentPreview}
              onInspect={setSelected}
              onRemoveDraft={(id) => {
                setAttachmentDraft((prev) => prev.filter((item) => String(item.id || '') !== id));
                setAttachmentPreview(null);
              }}
              onClearFiles={() => {
                setFileDraft([]);
                setAttachmentPreview(null);
              }}
            />
            <SimpleGrid cols={{ base: 1, sm: 4 }} spacing="xs" mt="sm" className="pa-send-runtime-controls">
              <NumberInput
                size="xs"
                label="LLM 前 AP tick"
                description="本轮消息专用"
                value={sendPreTicks}
                min={0}
                max={40}
                step={1}
                onChange={(value) => setSendPreTicks(value === '' ? '' : Math.max(0, Math.min(40, Number(value) || 0)))}
              />
              <NumberInput
                size="xs"
                label="LLM 后 AP tick"
                description="本轮消息专用"
                value={sendPostTicks}
                min={0}
                max={20}
                step={1}
                onChange={(value) => setSendPostTicks(value === '' ? '' : Math.max(0, Math.min(20, Number(value) || 0)))}
              />
              <Switch
                size="sm"
                label="等 LLM 时跑空 tick"
                description="抵扣下一次 LLM 前 tick"
                checked={sendWaitTicks}
                onChange={(event) => setSendWaitTicks(event.currentTarget.checked)}
              />
              <Button size="xs" variant="light" leftSection={<IconSparkles size={14} />} onClick={pokeAgent}>
                戳一戳
              </Button>
            </SimpleGrid>
            {fileDraft.length || attachmentDraft.length ? (
              <Group gap={6} mt="xs">
                {fileDraft.map((file) => (
                  <Badge key={file.name} variant="light" leftSection={file.type.startsWith('image/') ? <IconPhoto size={12} /> : <IconFile size={12} />}>
                    {shortText(file.name, 28)}
                  </Badge>
                ))}
                {attachmentDraft.map((item) => (
                  <Badge key={String(item.id)} variant="outline">
                    {shortText(item.text || item.summary || item.name, 28)}
                  </Badge>
                ))}
              </Group>
            ) : null}
            <Group justify="space-between" mt="sm">
              <Text size="xs" c="dimmed">
                Ctrl / Cmd + Enter
              </Text>
              <Button rightSection={<IconSend size={16} />} loading={sending} onClick={() => void send()}>
                发送
              </Button>
            </Group>
          </Card>

          <MultimodalReadinessPanel
            readiness={multimodalReadiness}
            busy={busy}
            onRefresh={refreshMultimodalReadiness}
            onInspect={setSelected}
          />

          <Card className="chart-card">
            <Group justify="space-between" mb="xs">
              <Text fw={800}>能量历史</Text>
              <Badge variant="light">{formatCount(snapshots.length)} snapshots</Badge>
            </Group>
            <EnergyTrendChart snapshots={snapshots} dark={dark} />
          </Card>

          <ToolRunLogCard
            events={toolEvents}
            counts={toolEventCounts}
            activeTasks={toolActiveTasks}
            activeToolTask={(status?.active_tool_task || {}) as AnyRecord}
            view={toolLogView}
            busy={isBusy('diag') || isBusy('tool')}
            onViewChange={setToolLogView}
            onRefresh={() => void refreshToolEvents(true)}
            onSelect={setSelected}
          />

          <LibraryReviewReaderCard review={selectedLibraryReview} onInspect={setSelected} />

          <Card className="agent-cloud-card">
            <Group justify="space-between" mb="xs">
              <Text fw={800}>状态池对象云</Text>
              <Group gap={6}>
                <Badge variant="light" color="blue">ER</Badge>
                <Badge variant="light" color="violet">EV</Badge>
                <Badge variant="light" color="yellow">CP</Badge>
              </Group>
            </Group>
            <div className="agent-cloud agent-cloud-bubbles">
              {cloudLayout.length ? cloudLayout.map((item) => <CloudObject key={`legacy_${item.id}_${item.rank}_${item.group_count || 1}`} item={item} onSelect={setSelected} />) : <div className="empty-chart">等待状态池对象。</div>}
            </div>
          </Card>
        </Stack>

        <Stack className="agent-right" gap="md">
          <Card className="control-card">
            <Tabs defaultValue="diag" className="agent-config-tabs">
              <Tabs.List>
                <Tabs.Tab value="diag">诊断</Tabs.Tab>
                <Tabs.Tab value="selftest">自检</Tabs.Tab>
                <Tabs.Tab value="wake">触发</Tabs.Tab>
                <Tabs.Tab value="tools">工具</Tabs.Tab>
                <Tabs.Tab value="ab">实验</Tabs.Tab>
                <Tabs.Tab value="outbox">发件</Tabs.Tab>
                <Tabs.Tab value="events">事件</Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="diag" pt="sm">
                <Stack gap={8}>
                  <div className="agent-morning-brief-panel">
                    <Group justify="space-between" gap="xs" mb="xs">
                      <Group gap={8}>
                        <IconClipboardList size={16} />
                        <Text size="sm" fw={800}>晨间简报</Text>
                      </Group>
                      <Group gap={6}>
                        {morningBrief ? (
                          <Badge variant="light" color={morningBrief.ok ? 'teal' : 'yellow'}>
                            {String(morningBrief.label || morningBrief.verdict || 'brief')}
                          </Badge>
                        ) : null}
                        <Button size="compact-xs" variant="subtle" loading={busy} onClick={() => loadMorningBrief(false)}>
                          预览
                        </Button>
                        <Button size="compact-xs" variant="light" loading={busy} onClick={() => loadMorningBrief(true)}>
                          写入
                        </Button>
                      </Group>
                    </Group>
                    <Text size="xs" c="dimmed">
                      给明早第一眼看的本地 markdown：当前能力、安全开关、下一步和操作顺序；不会写 PA 对话历史。
                    </Text>
                    {morningBrief ? (
                      <Textarea mt="xs" autosize minRows={5} maxRows={9} readOnly value={String(morningBrief.markdown || '')} />
                    ) : (
                      <div className="empty-box compact">尚未生成晨间简报。</div>
                    )}
                  </div>
                  <div className="agent-handoff-panel">
                    <Group justify="space-between" gap="xs" mb="xs">
                      <Group gap={8}>
                        <IconDeviceFloppy size={16} />
                        <Text size="sm" fw={800}>交接包</Text>
                      </Group>
                      <Group gap={6}>
                        {handoff ? (
                          <Badge variant="light" color={handoff.verdict === 'ready' ? 'teal' : handoff.verdict === 'needs_action' ? 'red' : 'yellow'}>
                            {String(handoff.label || handoff.verdict || 'handoff')}
                          </Badge>
                        ) : null}
                        <Button size="compact-xs" variant="subtle" loading={busy} onClick={() => loadHandoff(false)}>
                          生成
                        </Button>
                        <Button size="compact-xs" variant="light" loading={busy} onClick={() => loadHandoff(true)}>
                          写入
                        </Button>
                      </Group>
                    </Group>
                    <Text size="xs" c="dimmed">
                      汇总验收结论、配置、AP 状态、最近消息/想法和下一步建议；写入后保存到本地 handoff JSON。
                    </Text>
                    {handoff ? (
                      <>
                        <Group gap={6} mt="xs">
                          <Badge size="xs" variant="outline">messages {formatCount(handoff.session?.message_count)}</Badge>
                          <Badge size="xs" variant="outline">thoughts {formatCount(handoff.session?.thought_count)}</Badge>
                          <Badge size="xs" variant="outline">turns {formatCount(handoff.session?.turn_count)}</Badge>
                          <Badge size="xs" variant="outline" color={handoff.ok ? 'teal' : 'red'}>{handoff.ok ? 'ok' : 'needs action'}</Badge>
                        </Group>
                        <Textarea
                          mt="xs"
                          autosize
                          minRows={5}
                          maxRows={9}
                          readOnly
                          value={String(handoff.markdown || '')}
                        />
                      </>
                    ) : (
                      <div className="empty-box compact">尚未生成交接包。</div>
                    )}
                  </div>
                  {readiness ? (
                    <div className="agent-quality-dashboard">
                      <Group justify="space-between" gap={6}>
                        <Text size="xs" fw={800}>启动体检摘要</Text>
                        <Badge variant="light" color={readiness.overall === 'pass' ? 'teal' : readiness.overall === 'fail' ? 'red' : 'yellow'}>
                          {String(readiness.overall || 'warn')}
                        </Badge>
                      </Group>
                      <Group gap={6}>
                        <Badge size="xs" variant="outline" color="teal">pass {formatCount(readiness?.counts?.pass)}</Badge>
                        <Badge size="xs" variant="outline" color="yellow">warn {formatCount(readiness?.counts?.warn)}</Badge>
                        <Badge size="xs" variant="outline" color="red">fail {formatCount(readiness?.counts?.fail)}</Badge>
                      </Group>
                    </div>
                  ) : null}
                  <Group grow>
                    <MetricCard label="状态文件" value={`${formatNumber(diagnostics?.health?.state_file_kb, 1)} KB`} note={diagnostics?.health?.fallback_active ? 'fallback active' : 'llm configured'} />
                    <MetricCard label="轮次" value={formatCount(diagnostics?.health?.turn_count)} note={`thought ${formatCount(diagnostics?.health?.thought_count)}`} />
                  </Group>
                  {diagnostics?.quality?.available ? (
                    <div className="agent-quality-dashboard">
                      <Group justify="space-between" gap={6}>
                        <Text size="xs" fw={800}>Thought 质量</Text>
                        <Badge variant="light" color={asNumber(diagnostics?.quality?.average?.overall, 0) >= 0.7 ? 'teal' : 'yellow'}>
                          {formatPercent(diagnostics?.quality?.average?.overall, 0)}
                        </Badge>
                      </Group>
                      <Group gap={6}>
                        <Badge size="xs" variant="outline">AP {formatPercent(diagnostics?.quality?.average?.ap_usage, 0)}</Badge>
                        <Badge size="xs" variant="outline">连续 {formatPercent(diagnostics?.quality?.average?.continuity, 0)}</Badge>
                        <Badge size="xs" variant="outline">人设 {formatPercent(diagnostics?.quality?.average?.persona_fit, 0)}</Badge>
                        <Badge size="xs" variant="outline">克制 {formatPercent(diagnostics?.quality?.average?.factual_restraint, 0)}</Badge>
                      </Group>
                    </div>
                  ) : null}
                  {asArray<string>(diagnostics?.recommendations).map((item) => (
                    <Text key={item} size="xs" c="dimmed">
                      {item}
                    </Text>
                  ))}
                </Stack>
              </Tabs.Panel>
              <Tabs.Panel value="selftest" pt="sm">
                <Stack gap="xs">
                  <div className="agent-morning-panel">
                    <Group justify="space-between" mb="xs">
                      <Group gap={8}>
                        <IconCircleCheck size={16} />
                        <Text size="sm" fw={800}>一键晨检</Text>
                      </Group>
                      <Group gap={6}>
                        {morningCheck ? (
                          <Badge variant="light" color={morningCheck.overall === 'pass' ? 'teal' : morningCheck.overall === 'fail' ? 'red' : 'yellow'}>
                            {String(morningCheck.overall)}
                          </Badge>
                        ) : null}
                        <Button size="xs" variant="light" leftSection={<IconTestPipe size={14} />} loading={busy} onClick={runMorningCheck}>
                          运行晨检
                        </Button>
                      </Group>
                    </Group>
                    <Text size="xs" c="dimmed">
                      汇总 acceptance、自检、历史污染检查和外部发送安全状态；默认沙盒运行，不写入 PA 对话历史。
                    </Text>
                    {morningCheck ? (
                      <>
                        <Group gap={6} mt="xs">
                          <Badge size="xs" variant="outline" color="teal">pass {formatCount(morningCheck.counts?.pass)}</Badge>
                          <Badge size="xs" variant="outline" color="yellow">warn {formatCount(morningCheck.counts?.warn)}</Badge>
                          <Badge size="xs" variant="outline" color="red">fail {formatCount(morningCheck.counts?.fail)}</Badge>
                          <Badge size="xs" variant="outline">{formatCount(morningCheck.latency_ms)} ms</Badge>
                          <Badge size="xs" variant="outline" color={morningCheck.history_unchanged ? 'teal' : 'red'}>
                            {morningCheck.history_unchanged ? 'history clean' : 'history changed'}
                          </Badge>
                        </Group>
                        <Stack gap={6} mt="xs">
                          {asArray<AnyRecord>(morningCheck.checks).map((check) => (
                            <button key={String(check.id)} type="button" className="agent-readiness-row" onClick={() => setSelected(check)}>
                              <Badge size="xs" variant="light" color={check.status === 'pass' ? 'teal' : check.status === 'fail' ? 'red' : 'yellow'}>{String(check.status)}</Badge>
                              <span>
                                <strong>{shortText(String(check.id || '-'), 34)}</strong>
                                <small>{shortText(String(check.detail || ''), 118)}</small>
                              </span>
                            </button>
                          ))}
                        </Stack>
                      </>
                    ) : (
                      <div className="empty-box compact">尚未运行本轮晨检；可先用它生成早上验收快照。</div>
                    )}
                  </div>
                  {morningHistory.length ? (
                    <>
                      <Divider label="晨检历史" labelPosition="left" />
                      <ScrollArea.Autosize mah={220}>
                        <Stack gap={6}>
                          {morningHistory.slice().reverse().map((run) => (
                            <button key={String(run.id || run.ts)} type="button" className="agent-event-row" onClick={() => setSelected(run)}>
                              <span>
                                <strong>{String(run.acceptance?.label || run.overall || 'unknown')} · {formatCount(run.latency_ms)} ms</strong>
                                <small>{timeLabel(run.ts)} | pass {formatCount(run.counts?.pass)} warn {formatCount(run.counts?.warn)} fail {formatCount(run.counts?.fail)}</small>
                                <small>{run.history_unchanged ? 'history clean' : 'history changed'}</small>
                              </span>
                              <Badge variant="light" color={run.overall === 'pass' ? 'teal' : run.overall === 'fail' ? 'red' : 'yellow'}>
                                {String(run.overall || '-')}
                              </Badge>
                            </button>
                          ))}
                        </Stack>
                      </ScrollArea.Autosize>
                    </>
                  ) : null}
                  <Divider label="场景自检" labelPosition="left" />
                  <div className="agent-selftest-panel">
                    <Group justify="space-between" mb="xs">
                      <Group gap={8}>
                        <IconTestPipe size={16} />
                        <Text size="sm" fw={800}>PA 场景自检</Text>
                      </Group>
                      <Group gap={6}>
                        {selftest ? (
                          <Badge variant="light" color={selftest.overall === 'pass' ? 'teal' : selftest.overall === 'fail' ? 'red' : 'yellow'}>
                            {String(selftest.overall)}
                          </Badge>
                        ) : null}
                        <Button size="xs" variant="light" leftSection={<IconTestPipe size={14} />} loading={busy} onClick={runSelftest}>
                          运行自检
                        </Button>
                      </Group>
                    </Group>
                    <Text size="xs" c="dimmed">
                      沙盒组合测试：Readiness、Prompt、fallback thought、附件预览、唤醒矩阵、NapCat guide、工具与配置快照。不会写入 PA 对话历史。
                    </Text>
                    {selftest ? (
                      <>
                        <Group gap={6} mt="xs">
                          <Badge size="xs" variant="outline" color="teal">pass {formatCount(selftest.counts?.pass)}</Badge>
                          <Badge size="xs" variant="outline" color="yellow">warn {formatCount(selftest.counts?.warn)}</Badge>
                          <Badge size="xs" variant="outline" color="red">fail {formatCount(selftest.counts?.fail)}</Badge>
                          <Badge size="xs" variant="outline">{formatCount(selftest.latency_ms)} ms</Badge>
                          <Badge size="xs" variant="outline" color={selftest.history_unchanged ? 'teal' : 'red'}>
                            {selftest.history_unchanged ? 'history clean' : 'history changed'}
                          </Badge>
                        </Group>
                        <Stack gap={6} mt="xs">
                          {asArray<AnyRecord>(selftest.checks).map((check) => (
                            <button key={String(check.id)} type="button" className="agent-readiness-row" onClick={() => setSelected(check)}>
                              <Badge size="xs" variant="light" color={check.status === 'pass' ? 'teal' : check.status === 'fail' ? 'red' : 'yellow'}>{String(check.status)}</Badge>
                              <span>
                                <strong>{shortText(String(check.id || '-'), 34)}</strong>
                                <small>{shortText(String(check.detail || ''), 118)}</small>
                              </span>
                            </button>
                          ))}
                        </Stack>
                      </>
                    ) : (
                      <div className="empty-box compact">尚未运行本轮自检。</div>
                    )}
                  </div>
                  {selftestHistory.length ? (
                    <>
                      <Divider label="自检历史" labelPosition="left" />
                      <ScrollArea.Autosize mah={260}>
                        <Stack gap={6}>
                          {selftestHistory.slice().reverse().map((run) => (
                            <button key={String(run.id || run.ts)} type="button" className="agent-event-row" onClick={() => setSelected(run)}>
                              <span>
                                <strong>{String(run.overall || 'unknown')} · {formatCount(run.latency_ms)} ms</strong>
                                <small>{timeLabel(run.ts)} | pass {formatCount(run.counts?.pass)} warn {formatCount(run.counts?.warn)} fail {formatCount(run.counts?.fail)}</small>
                                <small>{run.history_unchanged ? 'history clean' : 'history changed'}</small>
                              </span>
                              <Badge variant="light" color={run.overall === 'pass' ? 'teal' : run.overall === 'fail' ? 'red' : 'yellow'}>
                                {String(run.overall || '-')}
                              </Badge>
                            </button>
                          ))}
                        </Stack>
                      </ScrollArea.Autosize>
                    </>
                  ) : null}
                </Stack>
              </Tabs.Panel>
              <Tabs.Panel value="wake" pt="sm">
                <Stack gap="xs">
                  <div className="agent-trigger-policy-panel">
                    <Group justify="space-between" align="flex-start" gap="xs">
                      <div className="agent-trigger-policy-head">
                        <Group gap={8}>
                          <IconMessageCircle size={16} />
                          <Text size="sm" fw={800}>触发策略总览</Text>
                        </Group>
                        <Text size="xs" c="dimmed">
                          把私聊、群聊、关键词、NapCat 和矩阵验收放在同一处看，方便确认 PA 什么时候应该醒。
                        </Text>
                      </div>
                      <Group gap={6} wrap="wrap">
                        <Badge variant="light" color={policyRiskColor}>
                          {policyRisk === 'live' ? 'live send' : policyRisk === 'dry_run' ? 'dry-run' : 'local safe'}
                        </Badge>
                        <Badge variant="outline">{policyPlatform}</Badge>
                        {policyWebhook ? (
                          <Button size="compact-xs" variant="subtle" onClick={() => setSelected({ webhook_url: policyWebhook, guide: napcatGuide })}>
                            Webhook
                          </Button>
                        ) : null}
                      </Group>
                    </Group>
                    <div className="agent-trigger-policy-grid">
                      {policyRows.map((row) => (
                        <button key={row.label} type="button" className="agent-trigger-policy-item" onClick={() => setSelected(row)}>
                          <span>{row.label}</span>
                          <strong>{row.value}</strong>
                          <small>{row.note}</small>
                        </button>
                      ))}
                    </div>
                    <Group gap={6} wrap="wrap">
                      <Button size="xs" variant="light" leftSection={<IconTestPipe size={14} />} onClick={runWakeMatrix} loading={busy}>
                        跑矩阵
                      </Button>
                      <Button size="xs" variant="subtle" onClick={previewWake} loading={busy}>
                        预览当前文本
                      </Button>
                      <Button size="xs" variant="subtle" onClick={previewNapcatEvent} loading={busy}>
                        NapCat 预览
                      </Button>
                      <Button size="xs" variant="subtle" onClick={simulateNapcat} loading={busy}>
                        NapCat 模拟
                      </Button>
                      <Button size="xs" variant="subtle" onClick={refreshNapcatGuide} loading={busy}>
                        刷新接入状态
                      </Button>
                    </Group>
                    {wakePolicy ? (
                      <div className="agent-wake-policy-grid">
                        {policyCases.map((item) => (
                          <button key={String(item.id || item.label)} type="button" className="agent-wake-policy-row" onClick={() => setSelected(item)}>
                            <Badge size="xs" variant="light" color={item.should_wake ? 'teal' : 'gray'}>
                              {item.should_wake ? 'wake' : 'quiet'}
                            </Badge>
                            <span>
                              <strong>{shortText(String(item.label || '-'), 32)}</strong>
                              <small>{shortText(`${item.reason || '-'}${item.keyword ? ` · ${item.keyword}` : ''} · ${item.note || ''}`, 110)}</small>
                            </span>
                          </button>
                        ))}
                      </div>
                    ) : null}
                    <Group gap={6}>
                      <Badge size="xs" variant="outline" color="teal">只读策略</Badge>
                      {wakePolicy ? <Badge size="xs" variant="outline">{String(wakePolicy.side_effects || 'read_only')}</Badge> : null}
                      <Button size="compact-xs" variant="subtle" loading={busy} onClick={() => refreshWakePolicy(true)}>
                        刷新策略
                      </Button>
                    </Group>
                  </div>
                  {napcatGuide ? (
                    <div className="agent-napcat-guide">
                      <Group justify="space-between" mb="xs">
                        <Group gap={8}>
                          <IconPlugConnected size={16} />
                          <Text size="sm" fw={800}>NapCat 接入助手</Text>
                        </Group>
                        <Group gap={6}>
                          <Badge variant="light" color={napcatGuide.overall === 'pass' ? 'teal' : napcatGuide.overall === 'fail' ? 'red' : 'yellow'}>
                            {String(napcatGuide.overall || 'warn')}
                          </Badge>
                          <Button size="compact-xs" variant="subtle" onClick={() => setSelected(napcatGuide)}>
                            JSON
                          </Button>
                          <ActionIcon size="sm" variant="subtle" loading={busy} onClick={refreshNapcatGuide}>
                            <IconRefresh size={14} />
                          </ActionIcon>
                        </Group>
                      </Group>
                      <TextInput size="xs" readOnly label="Webhook URL" value={String(napcatGuide.webhook_url || '')} onFocus={(event) => event.currentTarget.select()} />
                      <Group gap={6} mt="xs">
                        <Badge size="xs" variant="outline">{triggerModesLabel(napcatGuide.current?.trigger_modes, napcatGuide.current?.trigger_mode)}</Badge>
                        <Badge size="xs" variant="outline" color={napcatGuide.current?.qq_napcat_enabled ? 'teal' : 'gray'}>{napcatGuide.current?.qq_napcat_enabled ? 'NapCat on' : 'NapCat off'}</Badge>
                        <Badge size="xs" variant="outline" color={napcatGuide.current?.qq_napcat_dry_run ? 'yellow' : 'teal'}>{napcatGuide.current?.qq_napcat_dry_run ? 'dry-run' : 'live send'}</Badge>
                      </Group>
                      <Stack gap={4} mt="xs">
                        {asArray<AnyRecord>(napcatGuide.checks).map((check) => (
                          <button key={String(check.id)} type="button" className="agent-readiness-row" onClick={() => setSelected(check)}>
                            <Badge size="xs" variant="light" color={check.status === 'pass' ? 'teal' : check.status === 'fail' ? 'red' : 'yellow'}>{String(check.status)}</Badge>
                            <span>
                              <strong>{shortText(String(check.id || '-'), 28)}</strong>
                              <small>{shortText(String(check.detail || check.action || ''), 104)}</small>
                            </span>
                          </button>
                        ))}
                      </Stack>
                    </div>
                  ) : null}
                  <div className="agent-wake-event-editor">
                    <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="xs">
                      <Select
                        size="xs"
                        label="消息场景"
                        value={wakeMessageType}
                        data={[
                          { value: 'group', label: '群聊' },
                          { value: 'private', label: '私聊' },
                        ]}
                        onChange={(value) => setWakeMessageType(value || 'group')}
                      />
                      <TextInput
                        size="xs"
                        label="mentions / at"
                        value={wakeMentions}
                        placeholder="PA, psyarch"
                        onChange={(event) => setWakeMentions(event.currentTarget.value)}
                      />
                    </SimpleGrid>
                    <Textarea
                      label="唤醒预览文本"
                      minRows={2}
                      autosize
                      value={wakeText}
                      onChange={(event) => setWakeText(event.currentTarget.value)}
                    />
                    <Text size="xs" c="dimmed">
                      预览唤醒 / NapCat 预览只写诊断日志；NapCat 模拟会走完整 adapter 入口，命中唤醒时会写入 PA 历史并运行 tick。
                    </Text>
                  </div>
                  <Group grow>
                    <Button size="xs" variant="light" onClick={previewWake} loading={busy}>
                      预览唤醒
                    </Button>
                    <Button size="xs" variant="light" onClick={previewNapcatEvent} loading={busy}>
                      NapCat 预览
                    </Button>
                    <Button size="xs" variant="light" onClick={simulateNapcat} loading={busy}>
                      NapCat 模拟
                    </Button>
                  </Group>
                  <Textarea minRows={2} autosize value={napcatText} onChange={(event) => setNapcatText(event.currentTarget.value)} />
                  <Divider label="Outbound" labelPosition="left" />
                  <Textarea minRows={2} autosize value={replyText} onChange={(event) => setReplyText(event.currentTarget.value)} />
                  <Button size="xs" variant="light" onClick={testNapcatReply} loading={busy}>
                    测试 NapCat 发送
                  </Button>
                  <Divider label="Wake Matrix" labelPosition="left" />
                  <Button size="xs" variant="light" leftSection={<IconTestPipe size={14} />} onClick={runWakeMatrix} loading={busy}>
                    运行触发矩阵
                  </Button>
                  {(wakeMatrix || wakeMatrixHistory.length) ? (
                    <Stack gap={6}>
                      {wakeMatrix ? (
                        <Group gap={6}>
                          <Badge variant="light" color={asNumber(wakeMatrix.failed_count, 0) > 0 ? 'red' : 'teal'}>
                            {formatCount(wakeMatrix.passed_count)} / {formatCount(wakeMatrix.expected_count)}
                          </Badge>
                          <Badge variant="outline">{triggerModesLabel(wakeMatrix.trigger_modes, wakeMatrix.trigger_mode)}</Badge>
                          <Badge variant="outline">{wakeMatrix.allow_group_without_at ? '群聊全量' : '群聊需触发'}</Badge>
                        </Group>
                      ) : null}
                      <ScrollArea.Autosize mah={260}>
                        <Stack gap={6}>
                          {asArray<AnyRecord>(wakeMatrix?.cases || wakeMatrixHistory[wakeMatrixHistory.length - 1]?.cases).map((item, index) => (
                            <button key={`${item.name || index}-${item.reason || ''}`} type="button" className="agent-event-row" onClick={() => setSelected(item)}>
                              <span>
                                <strong>{item.name || `case ${index + 1}`}</strong>
                                <small>{item.should_wake ? 'wake' : 'sleep'} · {item.reason || '-'} {item.keyword ? `· ${item.keyword}` : ''}</small>
                                <small>{shortText(item.text || '', 84)}</small>
                              </span>
                              <Badge variant="light" color={item.passed === false ? 'red' : item.should_wake ? 'teal' : 'gray'}>
                                {item.passed === false ? 'miss' : item.should_wake ? 'on' : 'off'}
                              </Badge>
                            </button>
                          ))}
                        </Stack>
                      </ScrollArea.Autosize>
                    </Stack>
                  ) : null}
                  <Divider label="Wake Trace" labelPosition="left" />
                  <ScrollArea.Autosize mah={210}>
                    <Stack gap={6}>
                      {wakePreviews.length ? wakePreviews.slice().reverse().map((item, index) => (
                        <button key={`${item.ts || index}-${item.reason || 'wake'}`} type="button" className="agent-event-row" onClick={() => setSelected(item)}>
                          <span>
                            <strong>{item.should_wake ? 'wake' : 'sleep'} · {item.reason || '-'}</strong>
                            <small>{timeLabel(item.ts)} | {item.message_type || '-'} | {triggerModesLabel(item.trigger_modes, item.trigger_mode)}</small>
                            <small>{shortText(item.text || '', 88)}</small>
                          </span>
                          <Badge variant="light" color={item.should_wake ? 'teal' : 'gray'}>
                            {item.keyword || (item.should_wake ? 'on' : 'off')}
                          </Badge>
                        </button>
                      )) : <div className="empty-box">暂无唤醒预览。</div>}
                    </Stack>
                  </ScrollArea.Autosize>
                </Stack>
              </Tabs.Panel>
              <Tabs.Panel value="tools" pt="sm">
                <Stack gap="xs">
                  {integrations ? (
                    <div className="agent-integration-panel">
                      <Group justify="space-between" align="flex-start" gap="xs">
                        <div>
                          <Group gap={8}>
                            <IconPlugConnected size={16} />
                            <Text size="sm" fw={800}>集成注册表</Text>
                            <Badge variant="light" color="teal">{formatCount(integrationReadyLike)} ready</Badge>
                            <Badge variant="outline">{String(integrations.side_effects || 'read_only')}</Badge>
                          </Group>
                          <Text size="xs" c="dimmed">
                            MCP、Skills、NapCat、多模态和模型号池的真实接入状态；本面板只读，不执行工具。
                          </Text>
                        </div>
                        <Button size="compact-xs" variant="subtle" onClick={() => setSelected(integrations)}>
                          JSON
                        </Button>
                      </Group>
                      <div className="agent-integration-grid">
                        {integrationRows.map((row) => (
                          <button key={String(row.id)} type="button" className="agent-integration-item" onClick={() => setSelected(row)}>
                            <Group justify="space-between" gap={6} wrap="nowrap">
                              <strong>{shortText(String(row.label || row.id || '-'), 28)}</strong>
                              <Badge size="xs" variant="light" color={row.status === 'live' ? 'red' : row.status === 'ready' || row.status === 'dry_run' || row.status === 'summary_only' ? 'teal' : row.status === 'fallback' || row.status === 'probe' || row.status === 'standby' ? 'yellow' : 'gray'}>
                                {String(row.status || '-')}
                              </Badge>
                            </Group>
                            <small>{shortText(String(row.detail || row.next_step || ''), 96)}</small>
                          </button>
                        ))}
                      </div>
                      <Group gap={6}>
                        {asArray<AnyRecord>(integrations.recommendations).slice(0, 3).map((item) => (
                          <Badge key={String(item)} size="xs" variant="outline">{shortText(String(item), 34)}</Badge>
                        ))}
                      </Group>
                    </div>
                  ) : null}
                  {protocolRegistry ? (
                    <div className="agent-protocol-panel">
                      <Group justify="space-between" align="flex-start" gap="xs">
                        <div>
                          <Group gap={8}>
                            <IconPlugConnected size={16} />
                            <Text size="sm" fw={800}>MCP / Skills 协议注册表</Text>
                            <Badge variant="light" color="teal">{formatCount(protocolReadyLike)} active</Badge>
                            <Badge variant="outline">{String(protocolRegistry.side_effects || 'read_only')}</Badge>
                          </Group>
                          <Text size="xs" c="dimmed">
                            {String(protocolRegistry.safety_note || '只读协议蓝图；不会连接外部 server，也不会执行 skill。')}
                          </Text>
                        </div>
                        <Button size="compact-xs" variant="subtle" onClick={() => setSelected(protocolRegistry)}>
                          JSON
                        </Button>
                      </Group>
                      <div className="agent-protocol-grid">
                        {protocolRows.map((row) => (
                          <button key={String(row.id)} type="button" className="agent-protocol-item" onClick={() => setSelected(row)}>
                            <Group justify="space-between" gap={6} wrap="nowrap">
                              <strong>{shortText(String(row.label || row.id || '-'), 30)}</strong>
                              <Badge size="xs" variant="light" color={row.external_call ? 'red' : row.writes_ap_runtime || row.writes_pa_history ? 'yellow' : row.status === 'planned' || row.status === 'off' ? 'gray' : 'teal'}>
                                {String(row.status || row.kind || '-')}
                              </Badge>
                            </Group>
                            <small>{shortText(String(row.detail || row.next_step || ''), 92)}</small>
                            <small>{row.tool ? `tool: ${String(row.tool)}` : String(row.kind || '')} · {row.dry_run_first ? 'dry-run first' : row.writes_ap_runtime ? 'writes AP' : 'local'}</small>
                          </button>
                        ))}
                      </div>
                      <Group gap={6}>
                        {asArray<AnyRecord>(protocolRegistry.readiness).map((item) => (
                          <Badge key={String(item.id)} size="xs" variant="outline" color={item.status === 'fail' ? 'red' : item.status === 'warn' ? 'yellow' : 'teal'}>
                            {String(item.label || item.id)}:{String(item.status)}
                          </Badge>
                        ))}
                      </Group>
                    </div>
                  ) : null}
                  {toolMatrix ? (
                    <div className="agent-tool-matrix-panel">
                      <Group justify="space-between" align="flex-start" gap="xs">
                        <div>
                          <Group gap={8}>
                            <IconHammer size={16} />
                            <Text size="sm" fw={800}>能力矩阵</Text>
                            <Badge variant="light" color="teal">{formatCount(toolMatrix.counts?.enabled)} on</Badge>
                            <Badge variant="outline">{formatCount(toolMatrix.counts?.stub)} stub</Badge>
                          </Group>
                          <Text size="xs" c="dimmed">
                            {String(toolMatrix.safety_note || '只读矩阵；执行工具才会回灌 AP。')}
                          </Text>
                        </div>
                        <Button size="compact-xs" variant="subtle" onClick={() => setSelected(toolMatrix)}>
                          JSON
                        </Button>
                      </Group>
                      <div className="agent-tool-matrix-grid">
                        {asArray<AnyRecord>(toolMatrix.tools).map((tool) => (
                          <button key={String(tool.name)} type="button" className="agent-tool-matrix-item" onClick={() => setSelected(tool)}>
                            <Group justify="space-between" gap={6} wrap="nowrap">
                              <strong>{shortText(String(tool.label || tool.name || '-'), 28)}</strong>
                              <Badge size="xs" variant="light" color={tool.enabled ? (tool.writes_ap_runtime ? 'yellow' : 'teal') : 'gray'}>
                                {tool.enabled ? String(tool.mode || 'on') : 'off'}
                              </Badge>
                            </Group>
                            <small>{shortText(String(tool.operator_note || tool.description || ''), 88)}</small>
                          </button>
                        ))}
                      </div>
                      <Group gap={6}>
                        {asArray<AnyRecord>(toolMatrix.checks).map((check) => (
                          <Badge key={String(check.id)} size="xs" variant="outline" color={check.status === 'fail' ? 'red' : check.status === 'warn' ? 'yellow' : 'teal'}>
                            {String(check.id)}:{String(check.status)}
                          </Badge>
                        ))}
                      </Group>
                    </div>
                  ) : null}
                  <Select
                    label="本地工具"
                    value={toolName}
                    data={toolOptions.length ? toolOptions : [{ value: 'time', label: '本地时间' }]}
                    onChange={(value) => setToolName(value || 'time')}
                  />
                  <Textarea
                    label="参数 JSON"
                    minRows={3}
                    autosize
                    value={toolArgs}
                    onChange={(event) => setToolArgs(event.currentTarget.value)}
                  />
                  <Button size="xs" variant="light" leftSection={<IconHammer size={14} />} loading={busy} onClick={runTool}>
                    执行并回灌 AP
                  </Button>
                  <Text size="xs" c="dimmed">
                    手动执行会写事件；成功结果会回灌 AP 并刷新快照。只想看能力状态时使用上方矩阵。
                  </Text>
                  <ScrollArea.Autosize mah={180}>
                    <Stack gap={6}>
                      {tools.length ? tools.map((tool) => (
                        <button key={String(tool.name)} type="button" className="agent-tool-row" onClick={() => setSelected(tool)}>
                          <span>
                            <strong>{tool.label || tool.name}</strong>
                            <small>{shortText(tool.description || '', 72)}</small>
                          </span>
                          <Badge variant="light" color={tool.enabled === false ? 'gray' : 'teal'}>
                            {tool.enabled === false ? 'off' : 'on'}
                          </Badge>
                        </button>
                      )) : <div className="empty-box">刷新后显示工具。</div>}
                    </Stack>
                  </ScrollArea.Autosize>
                </Stack>
              </Tabs.Panel>
              <Tabs.Panel value="ab" pt="sm">
                <Stack gap="xs">
                  <Textarea minRows={3} autosize value={abText} onChange={(event) => setAbText(event.currentTarget.value)} />
                  <Group grow>
                    <Button size="xs" variant="light" leftSection={<IconTestPipe size={14} />} loading={busy} onClick={runPromptAb}>
                      运行 A/B 探针
                    </Button>
                    <Button size="xs" variant="light" leftSection={<IconFile size={14} />} loading={busy} onClick={previewPrompt}>
                      预览 Prompt
                    </Button>
                  </Group>
                  {promptPreview ? (
                    <div className="agent-quality-dashboard">
                      <Group justify="space-between" gap={6}>
                        <Text size="xs" fw={800}>Prompt 预算</Text>
                        <Badge variant="light" color={promptBudgetColor(asNumber(promptPreview.budgets?.estimated_tokens, 0))}>
                          {formatCount(promptPreview.budgets?.estimated_tokens)} tokens
                        </Badge>
                      </Group>
                      <Group gap={6}>
                        <Badge size="xs" variant="outline">system {formatCount(promptPreview.budgets?.system_chars)}</Badge>
                        <Badge size="xs" variant="outline">user {formatCount(promptPreview.budgets?.user_chars)}</Badge>
                        <Badge size="xs" variant="outline">AP {formatCount(promptPreview.budgets?.ap_packet_chars)}</Badge>
                      </Group>
                      {asArray<string>(promptPreview.warnings).length ? (
                        <Stack gap={4} mt={6}>
                          {asArray<string>(promptPreview.warnings).slice(0, 3).map((item) => (
                            <Text key={item} size="xs" c="orange">{item}</Text>
                          ))}
                        </Stack>
                      ) : (
                        <Text size="xs" c="dimmed" mt={6}>当前 prompt 预算正常。</Text>
                      )}
                    </div>
                  ) : null}
                  {abResult ? (
                    <Stack gap={6}>
                      {asArray<AnyRecord>(abResult.variants).map((row) => (
                        <button key={String(row.variant)} type="button" className="agent-tool-row" onClick={() => setSelected(row)}>
                          <span>
                            <strong>{row.variant}</strong>
                            <small>{shortText(row.thought || row.why || '', 78)}</small>
                          </span>
                          <Badge variant="light" color={row.variant === abResult.best?.variant ? 'teal' : 'gray'}>
                            {formatPercent(row.quality?.overall, 0)}
                          </Badge>
                        </button>
                      ))}
                    </Stack>
                  ) : null}
                  {promptExperiments.length ? (
                    <>
                      <Divider label="历史实验" labelPosition="left" />
                      <ScrollArea.Autosize mah={220}>
                        <Stack gap={6}>
                          {promptExperiments.slice().reverse().map((item, index) => (
                            <button key={`${item.id || item.ts || index}`} type="button" className="agent-experiment-row" onClick={() => setSelected(item)}>
                              <span>
                                <strong>{item.best || '-'} · 质量分 {formatPercent(item.best_quality, 0)}</strong>
                                <small>{timeLabel(item.ts)} | {item.variant_count || 0} variants | {formatCount(item.latency_ms || 0)} ms</small>
                                <em>{shortText(item.text || '', 74)}</em>
                                <span className="agent-experiment-scoreline">
                                  {asArray<AnyRecord>(item.variants).slice(0, 4).map((variant) => (
                                    <i key={String(variant.variant)}>
                                      {variant.variant}:{formatPercent(variant.quality?.overall, 0)}
                                    </i>
                                  ))}
                                </span>
                              </span>
                              <Button
                                size="compact-xs"
                                variant="light"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  applyPromptVariant(item.best);
                                }}
                              >
                                套用
                              </Button>
                            </button>
                          ))}
                        </Stack>
                      </ScrollArea.Autosize>
                    </>
                  ) : null}
                  <Text size="xs" c="dimmed">
                    沙盒评估，不写入 PA 历史，也不回灌 AP。
                  </Text>
                </Stack>
              </Tabs.Panel>
              <Tabs.Panel value="outbox" pt="sm">
                <ScrollArea.Autosize mah={320}>
                  <OutboxList rows={outbox} onSelect={setSelected} />
                </ScrollArea.Autosize>
              </Tabs.Panel>
              <Tabs.Panel value="events" pt="sm">
                <ScrollArea.Autosize mah={320}>
                  <EventList events={events} onSelect={setSelected} />
                </ScrollArea.Autosize>
              </Tabs.Panel>
            </Tabs>
          </Card>

          <Card className="control-card">
            <Group justify="space-between" mb="xs">
              <Text fw={800}>连续想法</Text>
              <Group gap={6}>
                <Badge variant="light">{formatCount(thoughtPage?.total ?? status?.session?.thought_count ?? thoughts.length)}</Badge>
                {thoughtPage ? <Badge variant="outline">offset {formatCount(thoughtOffset)}</Badge> : null}
              </Group>
            </Group>
            <ThoughtQualityChart thoughts={thoughts} dark={dark} />
            <ThoughtContinuityPanel
              report={thoughtContinuity}
              busy={busy}
              onRefresh={refreshThoughtContinuity}
              onInspect={setSelected}
            />
            <Group gap="xs" my="xs">
              <Button size="xs" variant="light" loading={busy} onClick={() => void loadThoughtPage(Math.max(0, thoughtOffset + 8))} disabled={thoughtPage ? !thoughtPage.has_more : false}>
                更早
              </Button>
              <Button size="xs" variant="subtle" loading={busy} onClick={() => { setThoughtOffset(0); setThoughtPage(null); }}>
                最新
              </Button>
            </Group>
            <ScrollArea.Autosize mah={540}>
              <Stack gap="sm">
                {thoughts.length ? thoughts.map((item) => <ThoughtCard key={String(item.id)} item={item} onSelect={setSelected} />) : <div className="empty-box">等待 thought。</div>}
              </Stack>
            </ScrollArea.Autosize>
          </Card>

          <Card className="control-card">
            <Text fw={800} mb="xs">AP 认知摘要</Text>
            <Stack gap={8}>
              <PromptContractPanel
                contract={promptContract}
                busy={busy}
                onRefresh={refreshPromptContract}
                onInspect={setSelected}
              />
              <CognitiveTimelinePanel
                timeline={cognitiveTimeline}
                dark={dark}
                busy={busy}
                onRefresh={refreshCognitiveTimeline}
                onInspect={setSelected}
              />
              {topObjects.slice(0, 5).map((item) => (
                <button key={`${item.id}-${item.rank}`} type="button" className="agent-object-row" onClick={() => setSelected(item)}>
                  <span>{shortDisplayText(item.display || item.id, 42)}</span>
                  <strong>{formatNumber(item.total_energy, 3)}</strong>
                </button>
              ))}
              {topMemory.length ? (
                <>
                  <Divider label="高能记忆" labelPosition="left" />
                  {topMemory.slice(0, 4).map((item) => (
                    <Text key={`${item.id}-${item.rank}`} size="xs" c="dimmed">
                      {shortDisplayText(item.display || item.id, 70)}
                    </Text>
                  ))}
                </>
              ) : null}
              {cfs.length ? (
                <>
                  <Divider label="CFS" labelPosition="left" />
                  <Group gap={6}>
                    {cfs.slice(0, 7).map((item) => (
                      <Badge key={`${item.name}-${item.target}`} variant="light">
                        {item.name}:{formatNumber(item.level, 2)}
                      </Badge>
                    ))}
                  </Group>
                </>
              ) : null}
              {ntRows.length ? (
                <>
                  <Divider label="NT" labelPosition="left" />
                  <Group gap={6}>
                    {ntRows.slice(0, 6).map((item) => (
                      <Badge key={String(item.channel)} variant="outline">
                        {item.channel}:{formatNumber(item.value, 2)}
                      </Badge>
                    ))}
                  </Group>
                </>
              ) : null}
            </Stack>
          </Card>

          <Card className="control-card">
            <details open>
              <summary className="agent-details-summary">选中对象 / 调试包</summary>
              <JsonInspector value={selectedPreview} title="PA / AP JSON" maxHeight={520} />
            </details>
          </Card>
        </Stack>
      </div>
    </div>
  );
  );
*/

export default AgentPage;


