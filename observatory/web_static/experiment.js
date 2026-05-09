const STATE = {
  protocol: null,
  datasets: [],
  datasetPreview: null,
  runs: [],
  selectedDatasetKey: "",
  selectedRunId: "",
  activeJobId: "",
  activeRunId: "",
  jobPollTimer: null,
  lastJob: null,
  lastManifest: null,
  lastMetricsRows: [],
  lastMetricsEvery: 1,
  lastMetricsFetchMs: 0,
  metricPerspective: 'aggregate',
  autoTunerDefaults: null,
  livePaused: false,
  liveDashboard: null,
  liveLastFetchMs: 0,
  liveActionLog: [],
  liveAutoTuneLog: [],
  llmPollTimer: null,
};
window.STATE = STATE;

const DOM = {};
window.DOM = DOM;
let LIVE_TIMER = null;
const EXP_SETTINGS_KEY = 'ap-observatory-experiment-settings-v1';

function byId(id) { return document.getElementById(id); }
function asArray(v) { return Array.isArray(v) ? v : []; }
function asNumber(v, d = 0) { const n = Number(v); return Number.isFinite(n) ? n : d; }
function formatNumber(v, digits = 4) { return asNumber(v, 0).toFixed(digits); }
function formatMaybe(v, digits = 4) { return asNumber(v, 0).toFixed(digits); }
function formatPercent(v, digits = 2) { return `${formatNumber(asNumber(v, 0) * 100, digits)}%`; }
function formatSigned(v, digits = 4) { const n = asNumber(v, 0); return `${n >= 0 ? '+' : ''}${formatNumber(n, digits)}`; }
function formatDelta(v, digits = 4) { return formatSigned(v, digits); }
function formatRange(minV, maxV, digits = 4) { return `${formatNumber(minV, digits)} ~ ${formatNumber(maxV, digits)}`; }
function formatDuration(ms) { const n = asNumber(ms, 0); return n >= 1000 ? `${formatNumber(n / 1000, 2)} s` : `${formatNumber(n, 0)} ms`; }

function canUseStorage(){ try { return typeof window !== 'undefined' && !!window.localStorage; } catch { return false; } }
function loadExperimentSettings(){
  if(!canUseStorage()) return {};
  try { return JSON.parse(window.localStorage.getItem(EXP_SETTINGS_KEY) || '{}') || {}; } catch { return {}; }
}
function saveExperimentSettings(){
  if(!canUseStorage()) return;
  const data = {
    selectedDatasetKey: STATE.selectedDatasetKey || '',
    selectedRunId: STATE.selectedRunId || '',
    activeJobId: STATE.activeJobId || '',
    activeRunId: STATE.activeRunId || '',
    resetMode: DOM.expResetMode?.value || 'keep',
    cleanRun: Boolean(DOM.expCleanRunChk?.checked),
    maxTicks: DOM.expMaxTicks?.value || '',
    runAllTicks: Boolean(DOM.expRunAllTicksChk?.checked),
    timeBasisOverride: DOM.expTimeBasisOverride?.value || '',
    exportJson: Boolean(DOM.expExportJsonChk?.checked),
    exportHtml: Boolean(DOM.expExportHtmlChk?.checked),
    downsampleEvery: DOM.expDownsampleEvery?.value || '1',
  };
  try { window.localStorage.setItem(EXP_SETTINGS_KEY, JSON.stringify(data)); } catch {}
}
function restoreExperimentSettings(){
  const data = loadExperimentSettings();
  if(data.selectedDatasetKey) STATE.selectedDatasetKey = String(data.selectedDatasetKey || '');
  if(data.selectedRunId) STATE.selectedRunId = String(data.selectedRunId || '');
  if(data.activeJobId) STATE.activeJobId = String(data.activeJobId || '');
  if(data.activeRunId) STATE.activeRunId = String(data.activeRunId || '');
  if(DOM.expResetMode && data.resetMode) DOM.expResetMode.value = String(data.resetMode || 'keep');
  if(DOM.expCleanRunChk) DOM.expCleanRunChk.checked = Boolean(data.cleanRun);
  if(DOM.expMaxTicks && data.maxTicks !== undefined) DOM.expMaxTicks.value = String(data.maxTicks || '');
  if(DOM.expRunAllTicksChk) DOM.expRunAllTicksChk.checked = Boolean(data.runAllTicks);
  if(DOM.expTimeBasisOverride && data.timeBasisOverride !== undefined) DOM.expTimeBasisOverride.value = String(data.timeBasisOverride || '');
  if(DOM.expExportJsonChk) DOM.expExportJsonChk.checked = Boolean(data.exportJson);
  if(DOM.expExportHtmlChk) DOM.expExportHtmlChk.checked = Boolean(data.exportHtml);
  if(DOM.expDownsampleEvery && data.downsampleEvery) DOM.expDownsampleEvery.value = String(data.downsampleEvery || '1');
  if(DOM.expMaxTicks) DOM.expMaxTicks.disabled = Boolean(DOM.expRunAllTicksChk?.checked);
  if(DOM.expResetMode) DOM.expResetMode.disabled = Boolean(DOM.expCleanRunChk?.checked);
}
function formatCount(v) { return String(Math.round(asNumber(v, 0))); }
function formatBool(v) { return v ? '是' : '否'; }
function formatTime(v) { const n = asNumber(v, 0); if (!n) return '-'; try { return new Date(n).toLocaleString('zh-CN', { hour12: false }); } catch { return String(v); } }
function esc(v) { return readableApText(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
function emptyState(text) { return `<div class="empty-state">${esc(text)}</div>`; }
function readableApText(value) {
  const text = String(value ?? '');
  if (!text.includes(' + ')) return text;
  return text.replace(/\{([^{}]*)\}/g, (_, inner) => `{${String(inner).replace(/\s+\+\s+/g, ' ')}}`);
}
function truncateText(value, maxLen = 180) { const text = readableApText(value); return text.length <= maxLen ? text : `${text.slice(0, maxLen)}…`; }
function miniRow(title, desc) { return `<article class="mini-row"><div class="title">${esc(title || '-')}</div><div class="desc">${esc(desc || '-').replace(/\n/g,'<br>')}</div></article>`; }
function metricCard(label, value, note = '') { return `<article class="metric-card"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="note">${esc(note)}</div></article>`; }
function setFeedback(el, message, kind='ok') { if(!el) return; el.textContent = `${formatTime(Date.now())} | ${message}`; el.classList.remove('ok','err','busy'); el.classList.add(kind); }
function pushBounded(list, item, maxSize = 80) { const arr = asArray(list).slice(); arr.push(item); return arr.slice(-Math.max(1, maxSize)); }
function currentMetricPerspective() { return STATE.metricPerspective === 'latest' ? 'latest' : 'aggregate'; }
function isCountLikeMetricKey(key) {
  const raw = String(key || '').trim().toLowerCase();
  return Boolean(raw) && /(?:count|size|len)$/.test(raw);
}
function isAdditiveMetricKey(key) {
  const raw = String(key || '').trim().toLowerCase();
  return Boolean(raw) && (isCountLikeMetricKey(raw) || raw.startsWith('timing_'));
}
function formatMetricDigest(st, key) {
  if (!st) return '';
  const raw = String(key || '').trim().toLowerCase();
  const parts = [];
  if (raw.startsWith('timing_')) parts.push('累计 ' + formatDuration(st.sum));
  else if (isCountLikeMetricKey(raw)) parts.push('累计 ' + formatCount(st.sum));
  else if (isAdditiveMetricKey(raw)) parts.push('累计 ' + formatMaybe(st.sum, 3));
  parts.push('最小 ' + formatMaybe(st.min, 3));
  parts.push('最大 ' + formatMaybe(st.max, 3));
  parts.push('平均 ' + formatMaybe(st.mean, 3));
  parts.push('中位 ' + formatMaybe(st.median, 3));
  parts.push('最新 ' + formatMaybe(st.latest, 3));
  parts.push('首末差值 ' + formatMaybe(st.delta, 3));
  return parts.join(' | ');
}
function renderMetricPerspectiveToolbar() {
  if (!DOM.expMetricPerspectiveBar) return;
  const mode = currentMetricPerspective();
  const note = mode === 'aggregate'
    ? '当前按整场聚合阅读摘要：更适合判断整场是否真的发生过认知拼接，而不会被最后一拍误导。'
    : '当前按最后一拍阅读摘要：更适合观察当前 tick 的即时状态，但不代表整场总貌。';
  DOM.expMetricPerspectiveBar.innerHTML = [
    '<div class="exp-perspective-label">统计口径</div>',
    '<div class="exp-perspective-actions">',
    `<button type="button" class="segmented-btn ${mode === 'aggregate' ? 'active' : ''}" data-metric-perspective="aggregate">整场聚合</button>`,
    `<button type="button" class="segmented-btn ${mode === 'latest' ? 'active' : ''}" data-metric-perspective="latest">最后一拍</button>`,
    '</div>',
    `<div class="exp-perspective-note">${esc(note)}</div>`,
  ].join('');
  DOM.expMetricPerspectiveBar.querySelectorAll('[data-metric-perspective]').forEach((node)=> {
    node.addEventListener('click', ()=> setMetricPerspective(node.getAttribute('data-metric-perspective')));
  });
}
function setMetricPerspective(mode) {
  const next = String(mode || '').trim() === 'latest' ? 'latest' : 'aggregate';
  if (STATE.metricPerspective === next) return;
  STATE.metricPerspective = next;
  renderMetricPerspectiveToolbar();
  renderRunSummary();
  renderMetricsOverview();
}
function actionKindLabel(kind) {
  const k = String(kind || '').trim();
  const mapping = {
    weather_stub: '天气查询（weather_stub）',
    attention_focus: '注意聚焦（attention_focus）',
    attention_focus_mode: '注意聚焦模式（attention_focus_mode）',
    attention_diverge_mode: '注意发散模式（attention_diverge_mode）',
    recall: '回忆（recall）',
  };
  return mapping[k] || (k || '未知行动');
}
function metricLabel(key) {
  const mapping = {
    pool_total_er: '实能量（ER）',
    pool_total_ev: '虚能量（EV）',
    pool_total_cp: '认知压（CP）',
    pool_ev_to_er_ratio: '虚实能量比（EV/ER，诊断）',
    energy_concentration: '状态池能量集中度',
    effective_peak_count: '状态池有效峰数',
    complexity_score: '状态池复杂度得分',
    core_energy_concentration: '状态池核心能量集中度',
    core_effective_peak_count: '状态池核心有效峰数',
    core_complexity_score: '状态池核心复杂度得分',
    pool_active_item_count: '状态池活跃条目数',
    pool_high_cp_item_count: '高认知压条目数',
    pool_er_top5_count: '状态池 ER Top5 可见条目数',
    pool_ev_top5_count: '状态池 EV Top5 可见条目数',
    pool_er_structure_top5_count: 'ER 结构 Top5 数',
    pool_ev_structure_top5_count: 'EV 结构 Top5 数',
    pool_er_atomic_feature_sa_top5_count: 'ER Top5 原子 SA 证据数',
    pool_ev_atomic_feature_sa_top5_count: 'EV Top5 原子 SA 证据数',
    pool_er_top1_er: '状态池 ER 峰值对象 ER',
    pool_ev_top1_ev: '状态池 EV 峰值对象 EV',
    pool_runtime_resolution_degraded_item_count: '运行态降分辨率对象数',
    pool_runtime_resolution_active_component_count: '运行态活跃组件数',
    pool_runtime_resolution_dropped_component_count: '运行态淡出组件数',
    maintenance_runtime_resolution_refreshed_item_count: '维护刷新分辨率对象数',
    maintenance_runtime_resolution_degraded_item_count: '维护后仍降分辨率对象数',
    pool_contextual_item_ratio: '状态池广义来源链占比',
    pool_explicit_context_item_ratio: '状态池显式上下文占比',
    pool_multi_context_item_ratio: '状态池多上下文对象占比',
    pool_residual_origin_item_ratio: '状态池残差来源对象占比',
    pool_context_path_depth_mean: '状态池广义来源路径深度',
    pool_explicit_context_path_depth_mean: '状态池显式上下文路径深度',
    attention_memory_item_count: '注意力记忆条目数',
    attention_cam_item_count: '注意力当前工作集条目数',
    cam_item_count: '当前工作集条目数',
    attention_cam_item_cap: '注意力 CAM 上限',
    attention_state_pool_candidate_count: '状态池候选条目数',
    attention_skipped_memory_item_count: '记忆跳过条目数',
    attention_consumed_total_energy: '注意力消耗总能量',
    attention_base_memory_total_energy: '注意力基础 CAM 能量',
    attention_final_memory_total_energy: '注意力滤波后 CAM 能量',
    attention_energy_budget: '注意力能量预算',
    attention_energy_budget_base: '注意力能量预算基线',
    attention_energy_budget_min: '注意力能量预算下限',
    attention_energy_budget_max: '注意力能量预算上限',
    attention_mod_attention_energy_budget: 'NT/行动调制后注意力能量预算',
    attention_energy_budget_enabled: '注意力能量预算开关',
    attention_energy_filter_applied: '注意力能量滤波已应用',
    attention_gain_budget_applied: '注意力净增益预算已应用',
    attention_gross_gain_energy_applied: '注意力毛增益能量',
    attention_suppressed_total_energy: '注意力抑制能量',
    attention_net_delta_energy: '注意力净增能量',
    attention_gain_weight_total: '注意力增益权重总量',
    attention_gain_floor: '注意力增益权重门槛',
    attention_suppression_floor: '注意力抑制权重门槛',
    attention_suppression_min_ratio: '注意力最低保留比例',

    external_sa_count: '外源 SA 数',
    internal_sa_count: '内源 SA 数',
    internal_attribute_count: '内源属性刺激元数',
    internal_numeric_attribute_count: '内源数值属性刺激元数',
    internal_time_like_attribute_count: '内源时间类属性刺激元数',
    internal_cfs_attribute_count: '内源 CFS 属性刺激元数',
    internal_cfs_pressure_family_attribute_count: '内源压力族属性刺激元数',
    internal_cfs_expectation_family_attribute_count: '内源期待族属性刺激元数',
    internal_reward_signal_attribute_count: '内源奖励信号属性数',
    internal_punish_signal_attribute_count: '内源惩罚信号属性数',
    internal_teacher_reward_signal_attribute_count: '内源教师奖励属性数',
    internal_teacher_punish_signal_attribute_count: '内源教师惩罚属性数',
    merged_flat_token_count: '合流后 flat token 数',
    cache_input_flat_token_count: '输入 flat token 数',
    cache_residual_flat_token_count: '中和后 flat token 数',
    landed_flat_token_count: '落地 flat token 数',
    internal_flat_token_count: '内源 flat token 数',
    internal_minus_external_sa_count: '内外源 SA 差值',
    internal_to_external_sa_ratio: '内外源 SA 比值',
    input_len: '原始输入字符数',
    induction_total_delta_ev: '感应赋能总虚能量增量',
    induction_applied_total_ev: '感应赋能结构直投实际落地虚能量',
    induction_structure_applied_total_ev: '感应赋能结构直投实际落地虚能量',
    induction_skipped_target_total_ev: '感应赋能结构直投被跳过虚能量',
    induction_total_ev_consumed: '局部传播消耗虚能量',
    induction_propagated_budget_total_ev: '分层图景累计传播预算 EV',
    induction_propagated_ev_total: '局部传播虚能量总量',
    induction_ev_from_er_total: 'ER 诱发 EV 总量',
    induction_source_item_count: '感应实际参与源对象数',
    induction_source_available_st_count: '可用源中的 ST 数',
    induction_source_selected_from_ev_count: '含 EV 的参与源数',
    induction_source_selected_from_er_count: '含 ER 的参与源数',
    induction_source_selected_from_cp_abs_count: '认知压回退入选源数',
    induction_source_selection_cap_hit: '感应源容量触顶标记',
    induction_source_max_items: '感应源最大名额（旧混合模式）',
    induction_source_candidate_top_k: '感应源候选扫描数（旧混合模式）',
    induction_source_ev_quota_ratio: '感应源 EV 配额比例（旧混合模式）',
    induction_source_ev_quota_count: '感应源 EV 配额数（旧混合模式）',
    induction_source_available_with_local_target_hint_count: '可继续传播源数（提示）',
    induction_source_selected_with_local_target_hint_count: '入选可传播源数',
    induction_source_selected_zero_local_target_hint_count: '入选空候选源数',
    induction_growth_target_count: 'A+B 生长目标数',
    induction_growth_identity_hit_count: '完整身份命中数',
    induction_growth_identity_created_count: '完整身份创建数',
    induction_growth_identity_local_cache_hit_count: '本轮身份缓存命中数',
    induction_growth_identity_shared_cache_hit_count: '跨 tick 身份缓存命中数',
    induction_growth_identity_shared_cache_stale_count: '跨 tick 身份缓存陈旧数',
    induction_growth_identity_create_exact_lookup_skipped_count: '创建前跳过重复精确查找数',
    induction_growth_persistence_batch_enabled: '生长创建持久化批处理',
    induction_growth_target_apply_ref_fast_merge_enabled: '目标入池 ref 快合并开关',
    induction_growth_target_apply_fast_ref_hit_merge_count: '目标入池 ref 快合并命中数',
    induction_growth_target_apply_insert_log_enabled: '目标入池逐条日志开关',
    induction_growth_target_apply_insert_log_suppressed_count: '目标入池日志抑制数',
    induction_growth_runtime_only_count: '未绑定运行态暂存数',
    induction_growth_pruned_low_energy_count: '低能生长剪枝数',
    induction_growth_failed_count: '生长投影失败数',
    induction_growth_deduped_count: '生长目标去重数',
    runtime_residual_promotion_exact_rebind_count: '残余包精确重绑定数',
    runtime_residual_promotion_full_identity_count: '残余包完整身份晋升数',
    runtime_residual_promotion_hdb_fallback_count: '残余包完整查存回退数',
    induction_raw_residual_entry_count: '原始残差条目数',
    induction_raw_residual_entry_with_existing_structure_count: '原始残差命中已存结构条目数',
    induction_raw_residual_entry_routed_to_structure_count: '原始残差实际转结构条目数',
    induction_raw_residual_existing_structure_target_count: '原始残差结构候选数',
    induction_raw_residual_entry_materialized_structure_count: '原始残差现场补建结构条目数',
    induction_raw_residual_materialized_structure_target_count: '原始残差现场补建结构目标数',
    induction_raw_residual_entry_with_component_structure_count: '原始残差命中组分结构条目数',
    induction_raw_residual_entry_routed_to_component_structure_count: '原始残差实际转组分结构条目数',
    induction_raw_residual_component_structure_target_count: '原始残差组分结构候选数',
    induction_target_count: '感应赋能总目标数',
    induction_structure_target_count: '感应赋能结构目标数',
    induction_memory_target_count: '感应赋能记忆目标数',
    induction_raw_residual_structure_target_count: '原始残差结构目标数',
    induction_raw_residual_exact_structure_target_count: '原始残差完整签名结构目标数',
    induction_raw_residual_component_structure_ev_target_count: '原始残差组分回退结构目标数',
    induction_raw_residual_memory_target_count: '原始残差记忆目标数',
    induction_applied_target_count: '感应赋能结构直投实际落地目标数',
    induction_structure_applied_target_count: '感应赋能结构直投实际落地目标数',
    induction_skipped_target_count: '感应赋能结构直投被跳过目标数',
    induction_structure_skipped_target_count: '感应赋能结构直投被跳过目标数',
    induction_skipped_cs_event_target_count: '感应赋能被跳过的 CS 事件目标数',
    induction_propagated_target_count: '局部传播目标数',
    induction_induced_target_count: 'ER 诱发目标数',
    induction_structure_target_total_ev: '感应赋能结构目标计划 EV',
    induction_memory_target_total_ev: '感应赋能记忆目标计划 EV',
    induction_raw_residual_target_total_ev: '原始残差总 EV',
    induction_raw_residual_structure_target_total_ev: '原始残差转结构 EV',
    induction_raw_residual_exact_structure_target_total_ev: '原始残差完整签名结构 EV',
    induction_raw_residual_component_structure_target_total_ev: '原始残差组分回退结构 EV',
    induction_raw_residual_memory_target_total_ev: '原始残差转记忆 EV',
    induction_raw_residual_hit_memory_target_total_ev: '原始残差命中后转记忆 EV',
    induction_raw_residual_miss_memory_target_total_ev: '原始残差未命中仅记忆 EV',
    induction_raw_residual_hit_path_target_total_ev: '原始残差命中路径总 EV',
    induction_structure_target_ev_share: '感应赋能结构路径 EV 占比',
    induction_memory_target_ev_share: '感应赋能记忆路径 EV 占比',
    induction_raw_residual_structure_target_ev_share: '原始残差结构 EV 占比',
    induction_raw_residual_exact_structure_ev_share: '原始残差结构路径中完整签名 EV 占比',
    induction_raw_residual_component_structure_ev_share: '原始残差结构路径中组分回退 EV 占比',
    induction_raw_residual_memory_target_ev_share: '原始残差记忆 EV 占比',
    induction_raw_residual_hit_path_structure_ev_share: '原始残差命中路径结构占比',
    induction_raw_residual_hit_path_memory_ev_share: '原始残差命中路径记忆占比',
    stimulus_transfer_round_count: '刺激级转移审计轮次',
    stimulus_transfer_selected_round_count: '刺激级有命中转移轮次',
    stimulus_transfer_matched_er: '刺激级命中对象 ER 转移',
    stimulus_transfer_matched_ev: '刺激级命中对象 EV 转移',
    stimulus_transfer_matched_total: '刺激级命中对象转移总量',
    stimulus_final_residual_er: '刺激级逐轮审计最终残余 ER',
    stimulus_final_residual_ev: '刺激级逐轮审计最终残余 EV',
    stimulus_final_residual_total: '刺激级逐轮审计最终残余总量',
    stimulus_transfer_minus_residual_total: '刺激级命中转移减残余',
    stimulus_transfer_to_residual_ratio: '刺激级命中转移/残余比',
    stimulus_transfer_share_of_matched_plus_residual: '刺激级命中转移占比',
    stimulus_transfer_dominates_residual: '刺激级命中转移占优',
    stimulus_effective_transfer_fraction_mean: '刺激级有效转移比例均值',
    stimulus_effective_transfer_fraction_max: '刺激级有效转移比例最大值',
    stimulus_transfer_similarity_mean: '刺激级转移相似度均值',
    stimulus_transfer_similarity_max: '刺激级转移相似度最大值',
    stimulus_object_projection_count: '刺激级完整对象投影数',
    stimulus_object_projection_er: '刺激级完整对象投影 ER',
    stimulus_object_projection_ev: '刺激级完整对象投影 EV',
    stimulus_object_projection_total: '刺激级完整对象投影总量',
    stimulus_object_projection_seed_total: '刺激级种子对象投影总量',
    stimulus_object_projection_matched_total: '刺激级命中对象投影总量',
    stimulus_object_projection_relation_total: '刺激级关系对象投影总量',
    stimulus_memory_tail_absorbed_er: '刺激尾巴记忆吸收 ER',
    stimulus_memory_tail_absorbed_ev: '刺激尾巴记忆吸收 EV',
    stimulus_memory_tail_absorbed_total: '刺激尾巴记忆吸收总量',
    stimulus_unhandled_residual_er: '未处理残余 ER',
    stimulus_unhandled_residual_ev: '未处理残余 EV',
    stimulus_unhandled_residual_total: '未处理残余总量',
    stimulus_object_projection_minus_unhandled_residual_total: '对象投影减未处理残余',
    stimulus_object_projection_to_unhandled_residual_ratio: '对象投影/未处理残余比',
    stimulus_object_projection_share_of_projection_plus_unhandled_residual: '对象投影落地占比',
    stimulus_object_projection_dominates_unhandled_residual: '对象投影占优未处理残余',
    stimulus_object_projection_dominates_raw_residual: '对象投影占优逐轮残余',
    stimulus_local_child_candidate_count: '局部子候选数',
    stimulus_local_child_candidate_pruned_count: '局部子候选剪枝数',
    stimulus_best_match_candidate_count: '精评分候选数',
    stimulus_best_match_pruned_count: '精评分候选剪枝数',
    stimulus_cut_common_part_total_count: '共同切割总次数',
    stimulus_best_match_common_part_count: '精评分共同切割次数',
    stimulus_cut_exact_fast_path_hit_count: '完全相同切割快路径命中数',
    stimulus_cut_full_inclusion_fast_path_hit_count: '完整包含切割快路径命中数',
    stimulus_cut_single_group_fast_path_hit_count: '单共现组切割快路径命中数',
    stimulus_cut_ordered_subsequence_fast_path_hit_count: '有序子序列切割快路径命中数',
    stimulus_cut_cache_hit_count: '共同切割缓存命中数',
    stimulus_cut_cache_zero_copy_hit_count: '共同切割零拷贝命中数',
    stimulus_cut_cache_store_count: '共同切割缓存写入数',
    stimulus_cut_cache_deepcopy_count: '共同切割缓存深拷贝数',
    stimulus_cut_normalize_cache_hit_count: '序列组规范化缓存命中数',
    stimulus_cut_normalize_reusable_hit_count: '刺激级规范化直接复用次数',
    stimulus_cut_normalize_reusable_group_count: '刺激级规范化直接复用组数',
    stimulus_cut_signature_fast_path_hit_count: '刺激级签名直读次数',
    stimulus_cut_empty_group_fast_path_hit_count: '刺激级空残差组快构造次数',
    stimulus_cut_reindex_fast_path_hit_count: '刺激级重索引复用次数',
    stimulus_anchor_owner_residual_presence_cache_hit_count: '锚点 owner 残差存在本轮缓存命中',
    stimulus_anchor_owner_residual_presence_shared_cache_hit_count: '锚点 owner 残差存在跨 tick 缓存命中',
    stimulus_anchor_owner_residual_presence_shared_cache_store_count: '锚点 owner 残差存在跨 tick 缓存写入',
    stimulus_anchor_owner_residual_presence_scan_count: '锚点 owner 残差存在扫描次数',
    stimulus_early_stop_object_projection_dominance_triggered: '对象投影占优早停触发',
    stimulus_early_stop_object_projection_dominance_completed_rounds: '对象投影占优早停完成轮次',
    stimulus_early_stop_object_projection_dominance_ratio: '对象投影占优早停比例',
    stimulus_early_stop_object_projection_transfer_guard_blocked_count: '对象投影早停被转移护栏拦截',
    stimulus_early_stop_object_projection_transfer_total_at_stop: '早停时命中转移总量',
    stimulus_early_stop_object_projection_transfer_ratio_at_stop: '早停时命中转移/残余比',
    stimulus_early_stop_object_projection_total_at_stop: '早停时对象投影总量',
    stimulus_early_stop_remaining_total_at_stop: '早停时剩余尾巴总量',
    cache_priority_cut_exact_fast_path_hit_count: '中和完全相同切割快路径命中数',
    cache_priority_cut_full_inclusion_fast_path_hit_count: '中和完整包含切割快路径命中数',
    cache_priority_cut_single_group_fast_path_hit_count: '中和单共现组切割快路径命中数',
    cache_priority_cut_ordered_subsequence_fast_path_hit_count: '中和有序子序列切割快路径命中数',
    cache_priority_cut_cache_hit_count: '中和共同切割缓存命中数',
    cache_priority_cut_cache_zero_copy_hit_count: '中和共同切割零拷贝命中数',
    cache_priority_cut_cache_store_count: '中和共同切割缓存写入数',
    cache_priority_cut_cache_deepcopy_count: '中和共同切割缓存深拷贝数',
    cache_priority_cut_normalize_cache_hit_count: '中和序列组规范化缓存命中数',
    cache_priority_cut_normalize_reusable_hit_count: '中和规范化直接复用次数',
    cache_priority_cut_normalize_reusable_group_count: '中和规范化直接复用组数',
    cache_priority_cut_signature_fast_path_hit_count: '中和签名直读次数',
    cache_priority_cut_empty_group_fast_path_hit_count: '中和空残差组快构造次数',
    cache_priority_cut_reindex_fast_path_hit_count: '中和重索引复用次数',
    induction_cut_cache_hit_count: '感应共同切割缓存命中数',
    induction_cut_cache_zero_copy_hit_count: '感应共同切割零拷贝命中数',
    induction_cut_cache_store_count: '感应共同切割缓存写入数',
    induction_cut_cache_deepcopy_count: '感应共同切割缓存深拷贝数',
    induction_cut_normalize_reusable_hit_count: '感应规范化直接复用次数',
    induction_cut_normalize_reusable_group_count: '感应规范化直接复用组数',
    induction_cut_signature_fast_path_hit_count: '感应签名直读次数',
    induction_cut_empty_group_fast_path_hit_count: '感应空残差组快构造次数',
    induction_cut_reindex_fast_path_hit_count: '感应重索引复用次数',
    induction_cut_full_inclusion_fast_path_hit_count: '感应完整包含切割快路径命中数',
    induction_cut_single_group_fast_path_hit_count: '感应单共现组切割快路径命中数',
    induction_cut_ordered_subsequence_fast_path_hit_count: '感应有序子序列切割快路径命中数',
    stimulus_shadow_raw_residual_candidate_count: '影子残差候选数',
    stimulus_shadow_raw_residual_candidate_pruned_count: '影子残差候选剪枝数',
    stimulus_shadow_raw_residual_skipped_count: '影子残差精评分跳过数',
    stimulus_shadow_raw_residual_common_part_count: '影子残差共同切割次数',
    induction_raw_residual_structure_budget_weight: '原始残差结构预算权重',
    induction_raw_residual_exact_structure_budget_weight: '原始残差完整签名结构预算权重',
    induction_raw_residual_materialized_structure_budget_weight: '原始残差现场补建结构预算权重',
    induction_raw_residual_component_structure_budget_weight: '原始残差组分回退结构预算权重',
    induction_raw_residual_hit_memory_budget_weight: '原始残差命中后记忆预算权重',
    induction_raw_residual_miss_memory_budget_weight: '原始残差未命中记忆预算权重',
    induction_raw_residual_projection_profile_local_cache_hit_count: '残差投影 profile 本轮缓存命中数',
    induction_raw_residual_projection_profile_shared_cache_hit_count: '残差投影 profile 跨 tick 缓存命中数',
    induction_raw_residual_projection_profile_cache_store_count: '残差投影 profile 缓存写入数',
    induction_raw_residual_exact_candidates_local_cache_hit_count: '残差完整候选本轮缓存命中数',
    induction_raw_residual_exact_candidates_shared_cache_hit_count: '残差完整候选跨 tick 缓存命中数',
    induction_raw_residual_exact_candidates_cache_store_count: '残差完整候选缓存写入数',
    induction_raw_residual_component_candidates_local_cache_hit_count: '残差组分候选本轮缓存命中数',
    induction_raw_residual_component_candidates_shared_cache_hit_count: '残差组分候选跨 tick 缓存命中数',
    induction_raw_residual_component_candidates_cache_store_count: '残差组分候选缓存写入数',
    induction_full_inclusion_shared_cache_hit_count: '感应完整包含跨 tick 缓存命中数',
    induction_full_inclusion_shared_cache_store_count: '感应完整包含缓存写入数',
    induction_applied_ev_ratio: '感应赋能结构直投落地比例',
    induction_structure_applied_ev_ratio: '感应赋能结构直投落地比例',
    induction_applied_target_ratio: '感应赋能结构目标落地比例',
    induction_structure_applied_target_ratio: '感应赋能结构目标落地比例',
    induction_propagated_target_ratio: '局部传播目标占比',
    induction_ev_from_er_ratio: 'ER 诱发 EV 占比',
    induction_targets_per_source_mean: '每源平均目标数',
    induction_fallback_used: '感应赋能指针回退标记',
    induction_energy_graph_v2_enabled: '分层能量图景 V2 开关',
    induction_energy_graph_config_max_rounds: '分层能量图景配置轮数上限',
    induction_energy_graph_round_count_max: '分层能量图景实际最大轮数',
    induction_energy_graph_depth_max: '分层能量图景最大深度',
    induction_energy_graph_frontier_generated_count: '分层能量图景前沿生成数',
    induction_energy_graph_frontier_pruned_count: '分层能量图景前沿剪枝数',
    induction_energy_graph_terminal_memory_count: '分层能量图景终端记忆数',
    induction_energy_graph_root_reinduction_count: '分层能量图景根源再诱发次数',
    induction_energy_graph_layer_count: '分层能量图景层数',
    induction_energy_graph_layer_max_width: '分层能量图景最大层宽',
    induction_energy_graph_layer_total_nodes: '分层能量图景层节点总数',
    induction_energy_graph_round_summary_count: '分层能量图景轮摘要数',
    induction_energy_graph_frontier_budget_total_ev: '分层能量图景前沿预算 EV',
    induction_energy_graph_root_induction_budget_total_ev: '分层能量图景根源再诱发预算 EV',
    induction_energy_graph_round_delta_ev_total: '分层能量图景轮增量 EV 总和',
    induction_energy_graph_round_delta_ev_max: '分层能量图景单轮最大增量 EV',
    induction_energy_graph_round_delta_ev_last: '分层能量图景末轮增量 EV',
    induction_energy_graph_frontier_in_count_max: '分层能量图景单轮最大前沿输入数',
    induction_energy_graph_frontier_out_count_max: '分层能量图景单轮最大前沿输出数',

    internal_candidate_structure_count: '内源候选结构数',
    internal_selected_structure_count: '内源入选结构数',
    internal_fragment_count: '内源片段数',
    internal_source_structure_count: '内源来源结构数',
    internal_resolution_raw_sa_count: '内源原始细节单元数（兼容旧 SA 口径）',
    internal_resolution_selected_sa_count: '内源入选细节单元数（兼容旧 SA 口径）',
    internal_resolution_budget_sa_cap: '内源细节预算上限（兼容旧 SA 口径）',
    internal_resolution_max_structures_per_tick: '内源结构预算上限',
    internal_resolution_detail_budget: '内源细节分辨率预算',
    internal_resolution_detail_budget_base: '内源基础细节预算',
    internal_resolution_detail_budget_adr_gain: '内源细节预算肾上腺素增益',
    internal_resolution_raw_unit_count: '内源原始细节单元数',
    internal_resolution_raw_unit_count_total: '内源原始细节总单元数',
    internal_resolution_raw_unit_count_total_candidates: '内源候选细节总单元数',
    internal_resolution_selected_unit_count: '内源已选细节单元数',
    internal_resolution_structure_count_selected: '内源已选结构数量',
    internal_resolution_runtime_priority_structure_count_total_candidates: '高优先级属性候选结构数',
    internal_resolution_runtime_priority_structure_count: '高优先级属性入选结构数',
    internal_resolution_runtime_priority_family_match_total_candidates: '高优先级属性候选 family 命中总数',
    internal_resolution_runtime_priority_family_match_total: '高优先级属性入选 family 命中总数',
    internal_resolution_runtime_family_bonus_total: '高优先级属性结构总加分',
    internal_resolution_selected_attribute_unit_count: '内源已选属性单元数',
    internal_resolution_selected_priority_attribute_unit_count: '内源已选高优先级属性单元数',
    internal_resolution_rescued_priority_attribute_unit_count: '内源 rescue 高优先级属性单元数',
    internal_cam_runtime_priority_projection_enabled: 'CAM 高优先级侧路开关状态',
    internal_cam_runtime_priority_projection_candidate_count: 'CAM 高优先级侧路候选结构数',
    internal_cam_runtime_priority_projection_fragment_count: 'CAM 高优先级侧路投影片段数',
    internal_cam_runtime_priority_projection_family_count: 'CAM 高优先级侧路投影 family 数',
    internal_cam_runtime_priority_projection_unit_count: 'CAM 高优先级侧路投影属性单元数',
    internal_cam_runtime_priority_projection_ratio: 'CAM 高优先级侧路投影比例',
    internal_cam_runtime_priority_projection_require_unrepresented: 'CAM 侧路仅投未显影 family',
    internal_resolution_cursor_count: '内源分辨率游标数',
    internal_resolution_history_count: '内源分辨率历史数',
    internal_resolution_history_bucket_count: '内源分辨率疲劳桶数',
    internal_resolution_focus_credit_count: '内源聚焦信用条目数',
    internal_csa_count: '内源结构片段数',
    structure_round_count: '结构级查存轮次',
    stimulus_round_count: '刺激级查存轮次',
    stimulus_new_structure_count: '刺激级新建结构数',
    stimulus_match_v2_candidate_count: '刺激级 V2 候选数',
    stimulus_match_v2_eligible_count: '刺激级 V2 可参与候选数',
    stimulus_match_v2_eligible_ratio: '刺激级 V2 可参与比例',
    stimulus_match_v2_score_mean: '刺激级 V2 综合分数均值',
    stimulus_match_v2_base_score_mean: '刺激级 V2 基础分数均值',
    stimulus_match_v2_numeric_score_mean: '刺激级 V2 数值接近度均值',
    stimulus_match_v2_numeric_time_like_score_mean: '刺激级 V2 时间因子数值接近度均值',
    stimulus_match_v2_numeric_time_like_scored_count: '刺激级 V2 时间因子已评分候选数',
    stimulus_match_v2_numeric_time_like_scored_ratio: '刺激级 V2 时间因子已评分候选占比',
    stimulus_match_v2_numeric_time_like_nonzero_count: '刺激级 V2 时间因子显影候选数',
    stimulus_match_v2_numeric_time_like_nonzero_ratio: '刺激级 V2 时间因子显影候选占比',
    stimulus_match_v2_numeric_time_like_family_count_mean: '刺激级 V2 时间因子家族数均值',
    stimulus_match_v2_numeric_time_like_wildcard_applied_count: '刺激级 V2 时间 wildcard 候选数',
    stimulus_match_v2_numeric_time_like_wildcard_applied_ratio: '刺激级 V2 时间 wildcard 候选占比',
    stimulus_match_v2_numeric_family_count_mean: '刺激级 V2 数值家族数均值',
    stimulus_match_v2_numeric_scored_count: '刺激级 V2 数值已评分候选数',
    stimulus_match_v2_numeric_scored_ratio: '刺激级 V2 数值已评分候选占比',
    stimulus_match_v2_numeric_nonzero_count: '刺激级 V2 数值显影候选数',
    stimulus_match_v2_numeric_nonzero_ratio: '刺激级 V2 数值显影候选占比',
    stimulus_match_v2_order_alignment_mean: '刺激级 V2 顺序对齐均值',
    stimulus_match_v2_attribute_anchor_mean: '刺激级 V2 属性锚点均值',
    stimulus_match_v2_context_support_mean: '刺激级 V2 上下文支撑均值',
    stimulus_match_v2_energy_profile_mean: '刺激级 V2 能量图景相似度均值',
    stimulus_match_v2_structure_inclusion_mean: '刺激级 V2 结构包含度均值',
    stimulus_match_v2_time_factor_bonus_applied_count: '刺激级 V2 时间软增益触发候选数',
    stimulus_match_v2_time_factor_bonus_applied_ratio: '刺激级 V2 时间软增益触发候选占比',
    stimulus_match_v2_time_factor_bonus_mean: '刺激级 V2 时间软增益均值',
    stimulus_match_v2_soft_partial_eligible_count: '刺激级 V2 软部分匹配候选数',
    stimulus_match_v2_soft_partial_eligible_ratio: '刺激级 V2 软部分匹配候选占比',
    stimulus_match_v2_soft_partial_selected_count: '刺激级 V2 软部分入竞候选数',
    stimulus_match_v2_soft_partial_selected_ratio: '刺激级 V2 软部分入竞候选占比',
    stimulus_match_v2_bundle_exact_selected_count: '刺激级 V2 精确 bundle 入竞候选数',
    stimulus_match_v2_bundle_exact_selected_ratio: '刺激级 V2 精确 bundle 入竞候选占比',
    stimulus_match_v2_exact_match_selected_count: '刺激级 V2 完全匹配入竞候选数',
    stimulus_match_v2_exact_match_selected_ratio: '刺激级 V2 完全匹配入竞候选占比',
    stimulus_match_v2_threshold_margin_mean: '刺激级 V2 阈值余量均值',
    stimulus_match_v2_blend_gain_mean: '刺激级 V2 混合增益均值',
    stimulus_shadow_memory_match_v2_candidate_count: '刺激级影子残差记忆 V2 候选数',
    stimulus_shadow_memory_match_v2_eligible_count: '刺激级影子残差记忆 V2 可参与候选数',
    stimulus_shadow_memory_match_v2_eligible_ratio: '刺激级影子残差记忆 V2 可参与比例',
    stimulus_shadow_memory_match_v2_score_mean: '刺激级影子残差记忆 V2 综合分数均值',
    stimulus_shadow_memory_match_v2_numeric_time_like_score_mean: '刺激级影子残差记忆 V2 时间因子数值接近度均值',
    stimulus_shadow_memory_match_v2_numeric_time_like_nonzero_count: '刺激级影子残差记忆 V2 时间因子显影候选数',
    stimulus_shadow_memory_match_v2_numeric_time_like_wildcard_applied_count: '刺激级影子残差记忆 V2 时间 wildcard 候选数',
    stimulus_shadow_memory_match_v2_time_factor_bonus_applied_count: '刺激级影子残差记忆 V2 时间软增益触发候选数',
    stimulus_shadow_memory_match_v2_time_factor_bonus_mean: '刺激级影子残差记忆 V2 时间软增益均值',
    structure_match_v2_candidate_count: '结构级 V2 候选组数',
    structure_match_v2_eligible_count: '结构级 V2 可参与候选组数',
    structure_match_v2_eligible_ratio: '结构级 V2 可参与比例',
    structure_match_v2_score_mean: '结构级 V2 综合分数均值',
    structure_match_v2_base_score_mean: '结构级 V2 基础分数均值',
    structure_match_v2_numeric_score_mean: '结构级 V2 数值接近度均值',
    structure_match_v2_numeric_time_like_score_mean: '结构级 V2 时间因子数值接近度均值',
    structure_match_v2_numeric_time_like_scored_count: '结构级 V2 时间因子已评分候选组数',
    structure_match_v2_numeric_time_like_scored_ratio: '结构级 V2 时间因子已评分候选组占比',
    structure_match_v2_numeric_time_like_nonzero_count: '结构级 V2 时间因子显影候选组数',
    structure_match_v2_numeric_time_like_nonzero_ratio: '结构级 V2 时间因子显影候选组占比',
    structure_match_v2_numeric_time_like_family_count_mean: '结构级 V2 时间因子家族数均值',
    structure_match_v2_numeric_time_like_wildcard_applied_count: '结构级 V2 时间 wildcard 候选组数',
    structure_match_v2_numeric_time_like_wildcard_applied_ratio: '结构级 V2 时间 wildcard 候选组占比',
    structure_match_v2_numeric_family_count_mean: '结构级 V2 数值家族数均值',
    structure_match_v2_numeric_scored_count: '结构级 V2 数值已评分候选组数',
    structure_match_v2_numeric_scored_ratio: '结构级 V2 数值已评分候选组占比',
    structure_match_v2_numeric_nonzero_count: '结构级 V2 数值显影候选组数',
    structure_match_v2_numeric_nonzero_ratio: '结构级 V2 数值显影候选组占比',
    structure_match_v2_order_alignment_mean: '结构级 V2 顺序对齐均值',
    structure_match_v2_attribute_anchor_mean: '结构级 V2 属性锚点均值',
    structure_match_v2_context_support_mean: '结构级 V2 上下文支撑均值',
    structure_match_v2_energy_profile_mean: '结构级 V2 能量图景相似度均值',
    structure_match_v2_structure_inclusion_mean: '结构级 V2 结构包含度均值',
    structure_match_v2_time_factor_bonus_applied_count: '结构级 V2 时间软增益触发候选组数',
    structure_match_v2_time_factor_bonus_applied_ratio: '结构级 V2 时间软增益触发候选组占比',
    structure_match_v2_time_factor_bonus_mean: '结构级 V2 时间软增益均值',
    structure_match_v2_soft_partial_eligible_count: '结构级 V2 软部分匹配候选组数',
    structure_match_v2_soft_partial_eligible_ratio: '结构级 V2 软部分匹配候选组占比',
    structure_match_v2_soft_partial_selected_count: '结构级 V2 软部分入竞候选组数',
    structure_match_v2_soft_partial_selected_ratio: '结构级 V2 软部分入竞候选组占比',
    structure_match_v2_bundle_exact_selected_count: '结构级 V2 精确 bundle 入竞候选组数',
    structure_match_v2_bundle_exact_selected_ratio: '结构级 V2 精确 bundle 入竞候选组占比',
    structure_match_v2_exact_match_selected_count: '结构级 V2 完全匹配入竞候选组数',
    structure_match_v2_exact_match_selected_ratio: '结构级 V2 完全匹配入竞候选组占比',
    structure_match_v2_threshold_margin_mean: '结构级 V2 阈值余量均值',
    structure_match_v2_blend_gain_mean: '结构级 V2 混合增益均值',
    structure_round_synthetic_count: '结构级 synthetic 单组轮次',
    structure_round_synthetic_ratio: '结构级 synthetic 单组占比',
    structure_round_implicit_single_count: '结构级 implicit_single_st 轮次',
    structure_round_implicit_single_ratio: '结构级 implicit_single_st 占比',
    structure_round_competitive_count: '结构级真实候选竞争轮次',
    structure_round_competitive_ratio: '结构级真实候选竞争占比',
    cs_action_count: '认知拼接动作次数',
    cs_candidate_count: '认知拼接候选数',
    cs_candidate_raw_accepted_count: '认知拼接原始可接受候选数',
    cs_candidate_deduped_count: '认知拼接去重后候选数',
    cs_candidate_deduped_pruned_count: '认知拼接去重剪枝数',
    cs_candidate_rejected_low_score_count: '认知拼接低分淘汰数',
    cs_candidate_rejected_v2_low_score_count: '认知拼接 V2 低分淘汰数',
    cs_candidate_rejected_component_limit_count: '认知拼接组分上限淘汰数',
    cs_candidate_rejected_non_positive_edge_count: '认知拼接非正边淘汰数',
    cs_candidate_replacement_count: '认知拼接同签名替换数',
    cs_candidate_kept_existing_count: '认知拼接同签名保留旧候选数',
    cs_candidate_threshold_margin_mean: '认知拼接阈值余量均值',
    cs_candidate_match_count_mean: '认知拼接匹配数量均值',
    cs_candidate_attribute_bonus_mean: '认知拼接属性加分均值',
    cs_candidate_effective_match_units_mean: '认知拼接有效匹配单元均值',
    cs_candidate_v2_score_mean: '认知拼接 V2 综合分数均值',
    cs_candidate_v2_base_score_mean: '认知拼接 V2 基础分数均值',
    cs_candidate_v2_threshold_margin_mean: '认知拼接 V2 阈值余量均值',
    cs_candidate_v2_context_cover_mean: '认知拼接 V2 上下文覆盖均值',
    cs_candidate_v2_order_alignment_mean: '认知拼接 V2 顺序对齐均值',
    cs_candidate_v2_tail_match_mean: '认知拼接 V2 尾端匹配均值',
    cs_candidate_v2_context_db_support_mean: '认知拼接 V2 上下文库支撑均值',
    cs_candidate_v2_energy_profile_mean: '认知拼接 V2 能量图景相似度均值',
    cs_candidate_v2_match_count_mean: '认知拼接 V2 匹配数量均值',
    cs_candidate_v2_attribute_bonus_mean: '认知拼接 V2 属性加分均值',
    cs_concat_count: '认知拼接上下文拼接数',
    cs_concat_narrative_count: '认知拼接叙事层普通拼接数',
    cs_created_count: '认知拼接新建数',
    cs_extended_count: '认知拼接扩展数',
    cs_merged_count: '认知拼接合并数',
    cs_reinforced_count: '认知拼接强化数',
    cs_seed_event_count: '认知拼接事件种子数',
    cs_seed_structure_count: '认知拼接结构种子数',
    cs_enabled: '认知拼接启用状态',
    cs_narrative_top_total_energy: '认知拼接叙事总能量',
    cs_narrative_top_grasp: '认知拼接叙事把握感',
    cs_narrative_grasp_max: '认知拼接叙事最大把握感',
    cs_narrative_grasp_positive_count: '认知拼接带把握感叙事数',
    cs_event_grasp_selected_event_count: '认知拼接把握入选事件数',
    cs_event_grasp_emitted_count: '认知拼接把握发射次数',
    cs_event_grasp_focus_candidate_item_count: '认知拼接把握焦点候选数',
    cs_event_grasp_cam_seed_count: '认知拼接把握 CAM 种子数',
    cs_event_grasp_post_action_seed_count: '认知拼接把握后拼接种子数',
    cs_event_grasp_cam_selected_event_count: '认知拼接把握 CAM 入选事件数',
    cs_event_grasp_post_action_selected_event_count: '认知拼接把握后拼接入选事件数',

    cfs_dissonance_max: '违和感峰值',
    cfs_pressure_max: '压力峰值',
    cfs_grasp_max: '把握感峰值',
    cfs_complexity_max: '复杂度峰值',
    cfs_simplicity_max: '简感/轻松感峰值',
    cfs_relief_max: '缓解感/松弛感峰值',
    cfs_reassurance_max: '安抚感/安心感峰值',
    cfs_surprise_max: '惊讶感峰值',
    cfs_repetition_max: '重复感峰值',
    cfs_expectation_max: '期待感峰值',
    cfs_expectation_verified_max: '已证实期待峰值',
    cfs_expectation_unverified_max: '未证实期待峰值',
    cfs_correctness_max: '正确感峰值',
    cfs_pressure_verified_max: '已证实压力峰值',
    cfs_pressure_unverified_max: '未证实压力峰值',

    cfs_dissonance_live_total_energy: '违和感总量',
    cfs_correctness_live_total_energy: '正确感总量',
    cfs_expectation_live_total_energy: '期待总量',
    cfs_expectation_verified_live_total_energy: '已证实期待总量',
    cfs_expectation_unverified_live_total_energy: '未证实期待总量',
    cfs_pressure_live_total_energy: '压力总量',
    cfs_pressure_verified_live_total_energy: '已证实压力总量',
    cfs_pressure_unverified_live_total_energy: '未证实压力总量',
    cfs_expectation_family_live_total_energy: '期待族总量',
    cfs_pressure_family_live_total_energy: '压力族总量',
    cfs_grasp_live_total_energy: '把握感总量',
    cfs_complexity_live_total_energy: '复杂度总量',
    cfs_simplicity_live_total_energy: '简感/轻松感总量',
    cfs_relief_live_total_energy: '缓解感/松弛感总量',
    cfs_reassurance_live_total_energy: '安抚感/安心感总量',
    cfs_surprise_live_total_energy: '惊讶感总量',
    cfs_repetition_live_total_energy: '重复感总量',
    cfs_total_strength: '认知感受总强度',

    cfs_signal_count: '即时感受信号总数',
    cfs_dissonance_count: '违和即时触发次数',
    cfs_surprise_count: '惊讶即时触发次数',
    cfs_repetition_count: '重复感即时触发次数',
    cfs_expectation_count: '期待感即时触发次数',
    cfs_expectation_verified_count: '已证实期待次数',
    cfs_expectation_unverified_count: '未证实期待次数',
    cfs_pressure_count: '压力即时触发次数',
    cfs_pressure_verified_count: '已证实压力次数',
    cfs_grasp_count: '把握感即时触发次数',
    cfs_simplicity_count: '简感/轻松感即时触发次数',
    cfs_relief_count: '缓解感/松弛感即时触发次数',
    cfs_reassurance_count: '安抚感/安心感即时触发次数',
    cfs_pressure_unverified_count: '未证实压力次数',
    cfs_expectation_verified_live_active: '已证实期待运行态激活标记',
    cfs_expectation_verified_decay_only: '已证实期待仅持续未新触发标记',
    cfs_expectation_unverified_live_active: '未证实期待运行态激活标记',
    cfs_expectation_unverified_decay_only: '未证实期待仅持续未新触发标记',
    cfs_pressure_verified_live_active: '已证实压力运行态激活标记',
    cfs_pressure_verified_decay_only: '已证实压力仅持续未新触发标记',
    cfs_pressure_live_active: '压力运行态激活标记',
    cfs_pressure_decay_only: '压力仅持续未新触发标记',
    cfs_pressure_unverified_live_active: '未证实压力运行态激活标记',
    cfs_pressure_unverified_decay_only: '未证实压力仅持续未新触发标记',

    cfs_dissonance_live_item_count: '违和感覆盖对象数',
    cfs_dissonance_live_attribute_count: '违和感属性条目数',
    cfs_dissonance_live_total_ev: '违和感总虚能量',
    cfs_correctness_live_item_count: '正确感覆盖对象数',
    cfs_correctness_live_attribute_count: '正确感属性条目数',
    cfs_correctness_live_total_er: '正确感总实能量',
    cfs_expectation_live_item_count: '期待覆盖对象数',
    cfs_expectation_live_attribute_count: '期待属性条目数',
    cfs_expectation_verified_live_item_count: '已证实期待覆盖对象数',
    cfs_expectation_verified_live_attribute_count: '已证实期待属性条目数',
    cfs_expectation_verified_live_total_er: '已证实期待总实能量',
    cfs_expectation_unverified_live_item_count: '未证实期待覆盖对象数',
    cfs_expectation_unverified_live_attribute_count: '未证实期待属性条目数',
    cfs_expectation_unverified_live_total_er: '未证实期待总实能量',
    cfs_pressure_live_item_count: '压力覆盖对象数',
    cfs_pressure_live_attribute_count: '压力属性条目数',
    cfs_pressure_verified_live_item_count: '已证实压力覆盖对象数',
    cfs_pressure_verified_live_attribute_count: '已证实压力属性条目数',
    cfs_pressure_verified_live_total_ev: '已证实压力总虚能量',
    cfs_pressure_unverified_live_item_count: '未证实压力覆盖对象数',
    cfs_pressure_unverified_live_attribute_count: '未证实压力属性条目数',
    cfs_pressure_unverified_live_total_ev: '未证实压力总虚能量',
    cfs_expectation_family_live_item_count: '期待族覆盖对象数',
    cfs_expectation_family_live_attribute_count: '期待族属性条目数',
    cfs_pressure_family_live_item_count: '压力族覆盖对象数',
    cfs_pressure_family_live_attribute_count: '压力族属性条目数',
    cfs_grasp_live_item_count: '把握感覆盖对象数',
    cfs_grasp_live_attribute_count: '把握感属性条目数',
    cfs_simplicity_live_item_count: '简感/轻松感覆盖对象数',
    cfs_simplicity_live_attribute_count: '简感/轻松感属性条目数',
    cfs_simplicity_live_total_er: '简感/轻松感总实能量',
    cfs_relief_live_item_count: '缓解感/松弛感覆盖对象数',
    cfs_relief_live_attribute_count: '缓解感/松弛感属性条目数',
    cfs_relief_live_total_er: '缓解感/松弛感总实能量',
    cfs_reassurance_live_item_count: '安抚感/安心感覆盖对象数',
    cfs_reassurance_live_attribute_count: '安抚感/安心感属性条目数',
    cfs_reassurance_live_total_er: '安抚感/安心感总实能量',
    cfs_surprise_live_item_count: '惊讶感覆盖对象数',
    cfs_surprise_live_attribute_count: '惊讶感属性条目数',
    cfs_repetition_live_item_count: '重复感覆盖对象数',
    cfs_repetition_live_attribute_count: '重复感属性条目数',
    cfs_complexity_count: '复杂度触发次数',
    cfs_complexity_live_item_count: '复杂度覆盖对象数',
    cfs_complexity_live_attribute_count: '复杂度属性条目数',
    cfs_complexity_live_total_er: '复杂度总实能量',
    cfs_complexity_live_total_ev: '复杂度总虚能量',
    cfs_correct_event_count: '正确事件触发次数',
    cfs_correct_event_max: '正确事件峰值',
    cfs_correct_event_live_item_count: '正确事件覆盖对象数',
    cfs_correct_event_live_attribute_count: '正确事件属性条目数',
    cfs_correct_event_live_total_energy: '正确事件总能量',
    cfs_correct_event_live_total_er: '正确事件总实能量',

    rwd_pun_rwd: '系统奖励信号',
    rwd_pun_pun: '系统惩罚信号',
    teacher_rwd: '教师奖励',
    teacher_pun: '教师惩罚',
    teacher_applied_count: '教师主绑定次数',
    teacher_total_binding_applied_count: '教师总绑定次数',
    teacher_primary_target_atomic: '教师主目标原子化标记',
    teacher_context_binding_enabled: '教师上下文镜像绑定开关',
    teacher_context_binding_candidate_count: '教师上下文镜像候选数',
    teacher_context_binding_applied_count: '教师上下文镜像绑定数',
    teacher_focus_directive_enabled: '教师聚焦指令开关',
    teacher_focus_directive_count: '教师聚焦指令数',
    teacher_focus_context_carrier_count: '教师上下文载体聚焦数',
    teacher_focus_directive_total_strength: '教师聚焦总强度',
    teacher_focus_directive_max_focus_boost: '教师聚焦最大加权',
    teacher_focus_directive_ttl_max: '教师聚焦最大存活 tick',
    teacher_local_alias_enabled: '教师局部别名缓存开关',
    teacher_local_alias_active_count: '教师局部别名活跃数',
    teacher_local_alias_available_count: '教师局部别名可用数',
    teacher_local_alias_matched_count: '教师局部别名匹配数',
    teacher_local_alias_overlay_applied_count: '教师局部别名注入次数',
    teacher_local_alias_overlay_rwd: '教师局部别名注入奖励',
    teacher_local_alias_overlay_pun: '教师局部别名注入惩罚',
    teacher_local_alias_overlay_match_score: '教师局部别名匹配分',
    reward_signal_live_total_energy: '奖励信号运行态总量',
    reward_signal_live_attribute_count: '奖励信号运行态属性数',
    punish_signal_live_total_energy: '惩罚信号运行态总量',
    punish_signal_live_attribute_count: '惩罚信号运行态属性数',
    teacher_reward_signal_live_total_energy: '教师奖励运行态总量',
    teacher_reward_signal_live_attribute_count: '教师奖励运行态属性数',
    teacher_punish_signal_live_total_energy: '教师惩罚运行态总量',
    teacher_punish_signal_live_attribute_count: '教师惩罚运行态属性数',
    label_teacher_rwd: '教师奖励标签',
    label_teacher_pun: '教师惩罚标签',
    label_should_call_weather: '天气调用标签',

    nt_COR: '皮质醇（COR）',
    nt_ADR: '肾上腺素（ADR）',
    nt_SER: '血清素（SER）',
    nt_END: '内啡肽（END）',
    nt_DA: '多巴胺（DA）',
    nt_OXY: '催产素（OXY）',
    nt_NOV: '新颖探索（NOV）',
    nt_FOC: '专注锁定（FOC）',
    nt_channel_count: 'NT 通道数',
    iesm_emotion_update_key_count: 'IESM 递质调制通道数',
    iesm_emotion_update_abs_total: 'IESM 递质调制绝对总量',
    iesm_emotion_update_DA: 'IESM 递质调制 多巴胺（DA）',
    iesm_emotion_update_ADR: 'IESM 递质调制 肾上腺素（ADR）',
    iesm_emotion_update_OXY: 'IESM 递质调制 催产素（OXY）',
    iesm_emotion_update_SER: 'IESM 递质调制 血清素（SER）',
    iesm_emotion_update_END: 'IESM 递质调制 内啡肽（END）',
    iesm_emotion_update_COR: 'IESM 递质调制 皮质醇（COR）',
    iesm_emotion_update_NOV: 'IESM 递质调制 新颖探索（NOV）',
    iesm_emotion_update_FOC: 'IESM 递质调制 专注锁定（FOC）',
    emotion_hdb_base_weight_er_gain_scale: 'NT-HDB 现实学习增益缩放',
    emotion_hdb_base_weight_ev_wear_scale: 'NT-HDB 虚循环磨损缩放',
    emotion_hdb_ev_propagation_threshold_scale: 'NT-HDB EV 传播阈值缩放',
    emotion_hdb_ev_propagation_ratio_scale: 'NT-HDB EV 传播比例缩放',
    emotion_hdb_er_induction_ratio_scale: 'NT-HDB ER 诱发比例缩放',
    attention_mod_min_cam_items: '注意力最小保留条目',
    attention_mod_focus_boost_weight: '注意力聚焦增益权重',
    attention_mod_min_total_energy: '注意力最小总能量门槛',
    attention_mod_priority_weight_total_energy: '注意力总能量权重',
    attention_mod_priority_weight_cp_abs: '注意力认知压权重',
    attention_mod_priority_weight_salience: '注意力显著性权重',
    attention_mod_priority_weight_fatigue: '注意力疲劳权重',
    attention_mod_priority_weight_recency_gain: '注意力近因增益权重',
    attention_cutoff_keep_ratio: '注意力动态保留比例',
    attention_cutoff_score_entropy: '注意力分数熵',
    attention_cutoff_score_concentration: '注意力分数集中度',

    action_executed_count: '行动执行总数',
    action_executed_count_source_visible: '行动执行总数（契约可见）',
    action_executed_count_synthetic_only: '行动执行总数（仅反馈 tick）',
    action_attempted_count: '行动尝试总数',
    action_attempted_count_source_visible: '行动尝试总数（契约可见）',
    action_attempted_count_synthetic_only: '行动尝试总数（仅反馈 tick）',
    action_scheduled_weather_stub: '天气查询调度次数',
    action_scheduled_weather_stub_source_visible: '天气查询调度次数（契约可见）',
    action_scheduled_weather_stub_synthetic_only: '天气查询调度次数（仅反馈 tick）',
    iesm_triggered_rule_count: 'IESM 命中规则数',
    iesm_triggered_rule_count_source_visible: 'IESM 命中规则数（契约可见）',
    iesm_triggered_rule_count_synthetic_only: 'IESM 命中规则数（仅反馈 tick）',
    iesm_triggered_script_count: 'IESM 命中脚本数',
    iesm_triggered_script_count_source_visible: 'IESM 命中脚本数（契约可见）',
    iesm_triggered_script_count_synthetic_only: 'IESM 命中脚本数（仅反馈 tick）',
    iesm_action_trigger_count: 'IESM 行动触发数',
    iesm_action_trigger_count_source_visible: 'IESM 行动触发数（契约可见）',
    iesm_action_trigger_count_synthetic_only: 'IESM 行动触发数（仅反馈 tick）',
    iesm_action_trigger_targeted_count: 'IESM 行动触发带目标数',
    iesm_action_trigger_targeted_count_source_visible: 'IESM 行动触发带目标数（契约可见）',
    iesm_action_trigger_targeted_count_synthetic_only: 'IESM 行动触发带目标数（仅反馈 tick）',
    iesm_action_trigger_target_missing_count: 'IESM 行动触发缺目标数',
    iesm_action_trigger_target_missing_count_source_visible: 'IESM 行动触发缺目标数（契约可见）',
    iesm_action_trigger_target_missing_count_synthetic_only: 'IESM 行动触发缺目标数（仅反馈 tick）',
    iesm_action_trigger_weather_stub_count: 'IESM 天气查询触发数',
    iesm_action_trigger_weather_stub_count_source_visible: 'IESM 天气查询触发数（契约可见）',
    iesm_action_trigger_weather_stub_count_synthetic_only: 'IESM 天气查询触发数（仅反馈 tick）',
    iesm_action_trigger_targeted_weather_stub_count: 'IESM 天气触发带目标数',
    iesm_action_trigger_targeted_weather_stub_count_source_visible: 'IESM 天气触发带目标数（契约可见）',
    iesm_action_trigger_targeted_weather_stub_count_synthetic_only: 'IESM 天气触发带目标数（仅反馈 tick）',
    iesm_action_trigger_target_missing_weather_stub_count: 'IESM 天气触发缺目标数',
    iesm_action_trigger_target_missing_weather_stub_count_source_visible: 'IESM 天气触发缺目标数（契约可见）',
    iesm_action_trigger_target_missing_weather_stub_count_synthetic_only: 'IESM 天气触发缺目标数（仅反馈 tick）',
    iesm_triggered_rule_innate_action_weather_stub_from_query_weather_count: 'IESM 强天气规则命中数',
    iesm_triggered_rule_innate_action_weather_stub_from_query_weather_count_source_visible: 'IESM 强天气规则命中数（契约可见）',
    iesm_triggered_rule_innate_action_weather_stub_from_query_weather_count_synthetic_only: 'IESM 强天气规则命中数（仅反馈 tick）',
    iesm_triggered_rule_innate_action_weather_stub_from_weather_question_count: 'IESM 隐式天气问句命中数',
    iesm_triggered_rule_innate_action_weather_stub_from_weather_question_count_source_visible: 'IESM 隐式天气问句命中数（契约可见）',
    iesm_triggered_rule_innate_action_weather_stub_from_weather_question_count_synthetic_only: 'IESM 隐式天气问句命中数（仅反馈 tick）',
    iesm_triggered_rule_innate_action_weather_stub_from_weather_only_count: 'IESM 弱天气规则命中数',
    iesm_triggered_rule_innate_action_weather_stub_from_weather_only_count_source_visible: 'IESM 弱天气规则命中数（契约可见）',
    iesm_triggered_rule_innate_action_weather_stub_from_weather_only_count_synthetic_only: 'IESM 弱天气规则命中数（仅反馈 tick）',
    action_executed_attention_focus: '注意聚焦执行次数',
    action_executed_recall: '回忆执行次数',
    action_executed_weather_stub: '天气查询执行次数',
    action_executed_weather_stub_source_visible: '天气查询执行次数（契约可见）',
    action_executed_weather_stub_synthetic_only: '天气查询执行次数（仅反馈 tick）',
    action_attempted_attention_diverge_mode: '注意发散尝试次数',
    action_attempted_attention_focus: '注意聚焦尝试次数',
    action_attempted_diverge_mode: '发散模式尝试次数',
    action_attempted_focus_mode: '聚焦模式尝试次数',
    action_attempted_recall: '回忆尝试次数',
    action_attempted_weather_stub: '天气查询尝试次数',
    action_attempted_weather_stub_source_visible: '天气查询尝试次数（契约可见）',
    action_attempted_weather_stub_synthetic_only: '天气查询尝试次数（仅反馈 tick）',
    action_executed_attention_diverge_mode: '注意发散执行次数',
    action_executed_diverge_mode: '发散模式执行次数',
    action_executed_focus_mode: '聚焦模式执行次数',
    action_drive_max: '最大行动驱动力',
    action_drive_mean: '平均行动驱动力',
    action_drive_active_count: '活跃行动节点数',
    action_node_count: '行动节点总数',
    action_base_threshold_mean: '平均基础行动阈值',
    action_effective_threshold_mean: '平均实时行动阈值',
    action_threshold_scale_mean: '平均行动阈值缩放',
    action_threshold_nt_scale_mean: '平均 NT 阈值缩放',
    action_threshold_rwd_pun_scale_mean: '平均奖惩阈值缩放',
    action_threshold_fatigue_scale_mean: '平均疲劳阈值缩放',
    action_threshold_rwd_pun_enabled_node_count: '奖惩阈值调制节点数',
    action_learning_threshold_delta_mean: '平均行动阈值偏移',
    action_learning_threshold_delta_sum: '行动阈值偏移总量',
    action_learning_reward_drive_gain_total: '奖励等效行动增益总量',
    action_learning_punish_drive_penalty_total: '惩罚等效行动惩罚总量',
  action_local_drive_scale_mean: '平均局部drive缩放',
  action_local_drive_modulated_node_count: '局部drive调制节点数',
  action_local_targeted_node_count: '有目标行动节点数',
  action_local_lookup_hit_count: '局部奖惩命中节点数',
  action_local_lookup_text_fallback_hit_count: '局部奖惩文本回落命中节点数',
  action_local_lookup_miss_count: '局部奖惩未命中节点数',
  action_local_lookup_skipped_count: '局部奖惩跳过节点数',
  action_local_target_missing_count: '局部奖惩缺少目标节点数',
  action_local_modulation_disabled_count: '局部奖惩关闭节点数',
  action_local_lookup_text_fallback_hit_count_weather_stub: '天气局部奖惩文本回落命中数',
  action_local_reward_drive_bonus_total: '局部奖励drive增益总量',
  action_local_punish_drive_penalty_total: '局部惩罚drive惩罚总量',
    action_node_weather_stub_count: '天气查询行动节点数',
    action_active_weather_stub_count: '天气查询活跃节点数',
    action_ready_weather_stub_count: '天气查询就绪节点数',
    action_drive_weather_stub_max: '天气查询驱动力峰值',
    action_drive_weather_stub_mean: '天气查询平均驱动力',
    action_effective_threshold_weather_stub_mean: '天气查询平均实时阈值',
    action_drive_margin_weather_stub_max: '天气查询最大驱动裕量',
    action_drive_margin_weather_stub_mean: '天气查询平均驱动裕量',

    time_sensor_bucket_update_count: '时间桶更新数',
    time_sensor_attribute_binding_count: '时间属性绑定数',
    time_sensor_projection_binding_count: '时间投影绑定数',
    time_sensor_legacy_binding_count: '时间旧峰值绑定数',
    time_sensor_memory_sample_count: '时间感受记忆样本数',
    time_sensor_delayed_task_registered_count: '延迟任务注册次数',
    time_sensor_delayed_task_updated_count: '延迟任务更新次数',
    time_sensor_delayed_task_executed_count: '延迟任务执行次数',
    time_sensor_delayed_task_pruned_count: '延迟任务清理次数',
    time_sensor_delayed_task_capacity_skip_count: '延迟任务容量跳过次数',
    time_sensor_delayed_task_table_size: '延迟任务表大小',
    time_sensor_bucket_energy_max: '时间桶能量峰值',
    time_sensor_bucket_energy_sum: '时间桶能量总和',
    time_sensor_delayed_task_skipped_capacity_count: '延迟任务容量跳过次数',
    time_sensor_memory_used_count: '时间感受取样记忆数',

    map_count: '记忆赋能条目数',
    map_feedback_count: '记忆反馈条目数',
    map_apply_count: '记忆赋能应用次数',
    map_total_er: '记忆赋能总实能量',
    map_total_ev: '记忆赋能总虚能量',
    map_feedback_total_ev: '记忆反馈总虚能量',
    memory_path_mode: '记忆主链模式',
    memory_runtime_projection_count: '残差运行态对象投影条目数',
    memory_feedback_applied_count: '记忆反馈落地次数',
    memory_feedback_total_er: '记忆反馈总实能量',
    memory_feedback_total_ev: '记忆反馈总虚能量',
    memory_feedback_total_energy: '记忆反馈总能量',
    memory_feedback_packet_count: '记忆包回放次数',
    memory_feedback_packet_total_er: '记忆包回放总实能量',
    memory_feedback_packet_total_ev: '记忆包回放总虚能量',
    memory_feedback_structure_projection_attempted_count: '结构直投尝试次数',
    memory_feedback_structure_projection_skipped_count: '结构直投被裁掉次数',
    memory_feedback_structure_projection_count: '结构直投次数',
    memory_feedback_structure_projection_effective_ratio: '结构直投有效率',
    memory_feedback_structure_projection_total_er: '结构直投总实能量',
    memory_feedback_structure_projection_total_ev: '结构直投总虚能量',

    hdb_structure_count: 'HDB 结构总数',
    hdb_group_count: 'HDB 结构组总数',
    hdb_episodic_count: '情节记忆总数',
    hdb_structure_context_path_depth_mean: 'HDB 平均上下文路径深度',
    hdb_contextual_structure_ratio: 'HDB 上下文化结构占比',
    hdb_multi_context_structure_ratio: 'HDB 多上下文结构占比',
    hdb_same_content_multi_context_ratio: 'HDB 同内容多上下文占比',
    hdb_contextual_diff_entry_ratio: 'HDB 上下文差异链接占比',
    hdb_residual_diff_entry_ratio: 'HDB 残差局部链接占比',
    hdb_primary_pointer_count: 'HDB 主指针数',
    hdb_fallback_pointer_count: 'HDB 回退指针数',
    hdb_signature_index_count: 'HDB 签名索引数',
    hdb_recent_cache_count: 'HDB 最近 DB 缓存数',
    hdb_exact_lookup_cache_count: 'HDB 精确结构缓存数',
    hdb_numeric_bucket_family_count: 'HDB 数值家族数',
    hdb_numeric_bucket_count: 'HDB 数值桶数',

    timing_total_logic_ms: '总逻辑耗时',
    timing_sensor_ms: '文本感受器耗时',
    timing_maintenance_ms: '状态池维护耗时',
    timing_structure_level_ms: '结构级耗时',
    timing_stimulus_level_ms: '刺激级耗时',
    timing_cache_neutralization_ms: '缓存中和耗时',
    timing_induction_and_memory_ms: '归纳与记忆耗时',
    timing_attention_ms: '注意力耗时',
    timing_cognitive_stitching_ms: '认知拼接耗时',
    timing_iesm_ms: 'IESM 耗时',
    timing_action_ms: '行动耗时',
    timing_emotion_ms: '情绪耗时',
    timing_cfs_ms: '认知感受耗时',
    timing_time_sensor_ms: '时间感受器耗时',

    sensor_feature_sa_count: '基础刺激元数量',
    sensor_attribute_sa_count: '属性刺激元数量',
    sensor_attribute_sa_per_feature_ratio: '每个基础刺激元对应的属性刺激元比例',
    sensor_csa_bundle_count: '结构包数量',
    sensor_echo_frames_used_count: '参与的残响帧数',
    sensor_echo_current_round: '当前轮残响数',
    sensor_echo_pool_size: '残响池大小',

    maintenance_before_active_item_count: '维护前活跃条目数',
    maintenance_after_active_item_count: '维护后活跃条目数',
    maintenance_delta_active_item_count: '维护活跃条目变化',
    maintenance_before_high_cp_item_count: '维护前高压条目数',
    maintenance_after_high_cp_item_count: '维护后高压条目数',
    maintenance_delta_high_cp_item_count: '维护高压条目变化',
    maintenance_event_count: '维护事件数',

    energy_balance_target_ratio: '能量平衡目标虚实比（旧闭环）',
    energy_balance_ratio_raw: '能量平衡原始虚实比（旧闭环）',
    energy_balance_ratio_smooth: '能量平衡平滑虚实比（旧闭环）',
    energy_balance_error_log: '能量平衡对数误差',
    energy_balance_g_before: '能量平衡控制增益（更新前）',
    energy_balance_g_after: '能量平衡控制增益（更新后）',
    energy_balance_ev_propagation_ratio_scale: '能量平衡 EV 传播缩放',
    energy_balance_er_induction_ratio_scale: '能量平衡 ER 诱发缩放',
    energy_balance_updated: '能量平衡已更新标记',
    energy_balance_hdb_scale_count: '能量平衡输出缩放项数',
    hdb_requested_ev_propagation_ratio: 'HDB 请求 EV 传播比例',
    hdb_effective_ev_propagation_ratio: 'HDB 实际 EV 传播比例',
    hdb_requested_er_induction_ratio: 'HDB 请求 ER 诱发比例',
    hdb_effective_er_induction_ratio: 'HDB 实际 ER 诱发比例',
    hdb_ev_propagation_ratio_clamped: 'HDB EV 传播比例截断标记',
    hdb_er_induction_ratio_clamped: 'HDB ER 诱发比例截断标记',

    pool_apply_merged_item_count: '状态池合并条目数',
    pool_apply_new_item_count: '状态池新增条目数',
    pool_apply_updated_item_count: '状态池更新条目数',
    pool_apply_total_delta_cp: '状态池认知压增量',
    pool_apply_total_delta_er: '状态池实能量增量',
    pool_apply_total_delta_ev: '状态池虚能量增量',

    episode_repeat_index: '情节重复索引',
    tick_in_episode_index: '情节内 Tick 序号',
  };
  if (mapping[key]) return mapping[key];
  return String(key || '')
    .replace(/^cfs_/, '认知感受_')
    .replace(/^nt_/, '递质_')
    .replace(/^timing_/, '耗时_')
    .replace(/^action_/, '行动_')
    .replace(/^time_sensor_/, '时间感受器_')
    .replace(/^sensor_/, '感受器_')
    .replace(/^pool_/, '状态池_')
    .replace(/^map_/, '记忆赋能_')
    .replace(/^iesm_/, 'IESM_')
    .replace(/^energy_balance_/, '能量平衡_')
    .replace(/^maintenance_/, '维护_')
    .replace(/^internal_/, '内源_')
    .replace(/^external_/, '外源_')
    .replace(/weather_stub/g, '天气查询')
    .replace(/source_visible/g, '契约可见')
    .replace(/synthetic_only/g, '仅反馈 tick')
    .replace(/triggered/g, '命中')
    .replace(/trigger/g, '触发')
    .replace(/rule/g, '规则')
    .replace(/attempted/g, '尝试')
    .replace(/executed/g, '执行')
    .replace(/scheduled/g, '调度')
    .replace(/_/g, ' ');
}

function getSeriesValues(rows, key) {
  return asArray(rows).map((row)=> Number(row?.[key])).filter((v)=> Number.isFinite(v));
}

function analyzeSeries(rows, key) {
  const values = getSeriesValues(rows, key);
  if (!values.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  return {
    values,
    min,
    max,
    allZero: min === 0 && max === 0,
    isConstant: min === max,
  };
}

function isMeaninglessSeries(rows, key, options = {}) {
  const keepConstant = !!options?.keepConstant;
  const hideConstant = !!options?.hideConstant;
  if (!key || /(?:^|_)(enabled|disabled)$/.test(key)) return true;
  if (['cs_narrative_top_grasp','cs_narrative_top_total_energy'].includes(String(key))) {
    const stats = analyzeSeries(rows, key);
    if (!stats || stats.allZero) return true;
  }
  const stats = analyzeSeries(rows, key);
  if (!stats) return true;
  if (stats.allZero) return true;
  if (stats.isConstant && hideConstant && !keepConstant) return true;
  return false;
}
async function apiGet(url, timeoutMs = 12000){
  const controller = new AbortController();
  const timer = setTimeout(()=> controller.abort(), timeoutMs);
  try {
    const r = await fetch(url, { signal: controller.signal });
    const data = await r.json();
    if(!r.ok || data.success===false) throw new Error(data.message || url);
    return data;
  } catch (error) {
    if (error?.name === 'AbortError') throw new Error(`请求超时：${url}`);
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
async function apiPost(url, body, timeoutMs = 12000){
  const controller = new AbortController();
  const timer = setTimeout(()=> controller.abort(), timeoutMs);
  try {
    const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{}),signal: controller.signal});
    const data = await r.json();
    if(!r.ok || data.success===false) throw new Error(data.message || url);
    return data;
  } catch (error) {
    if (error?.name === 'AbortError') throw new Error(`请求超时：${url}`);
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
window.apiGet = apiGet;
window.apiPost = apiPost;
window.metricCard = metricCard;
window.miniRow = miniRow;
window.emptyState = emptyState;
window.formatCount = formatCount;
window.formatBool = formatBool;
window.formatNumber = formatNumber;
window.formatMaybe = formatMaybe;
window.formatPercent = formatPercent;
window.formatSigned = formatSigned;
window.formatDelta = formatDelta;
window.formatRange = formatRange;
window.formatDuration = formatDuration;
window.setFeedback = setFeedback;

function datasetKey(ref) {
  const source = String(ref?.source || '').trim();
  const rel = String(ref?.rel_path || '').trim();
  return source && rel ? `${source}::${rel}` : '';
}
function parseDatasetKey(key) {
  const raw = String(key || '');
  const parts = raw.split('::');
  if (parts.length < 2) return null;
  return { source: parts[0], rel_path: parts.slice(1).join('::') };
}
function getSelectedDatasetRef() {
  return parseDatasetKey(String(DOM.expDatasetSelect?.value || STATE.selectedDatasetKey || ''));
}
window.getSelectedDatasetRef = getSelectedDatasetRef;

function bindDom() {
  [
    'expBackBtn','expRefreshProtocolBtn','expProtocolCards','expProtocolYamlFields','expProtocolJsonlFields','expProtocolYamlExample','expProtocolJsonlExample',
    'expRefreshDatasetsBtn','expDatasetSelect','expDatasetMeta','expDatasetOverviewCards','expPreviewBtn','expExpandBtn','expDatasetPreviewMeta','expDatasetPreview',
    'expImportFilename','expImportFormat','expImportContent','expImportBtn','expImportFeedback',
    'expClearRuntimeBtn','expClearHdbBtn','expClearAllBtn','expClearFeedback',
    'expResetMode','expCleanRunChk','expMaxTicks','expRunAllTicksChk','expTimeBasisOverride','expExportJsonChk','expExportHtmlChk','expRunStartBtn','expRunStopBtn','expProgressBar','expJobMeta','expJobFeedback','expJobOverviewCards','expJobSummary','expJobAutoTuner',
    'expRefreshRunsBtn','expDeleteRunBtn','expClearRunsBtn','expRunsList','expDownsampleEvery','expRunMeta','expRunOverviewCards','expRunSummary',
    'expMetricsOverviewCards','expMetricsNarrative','expChartDeck',
    'expLivePauseBtn','expLiveClearBtn','expLiveMeta','expLiveStateTop','expLiveCsTop','expLiveCfsTotals','expLiveAutoTuneLog','expLiveActionLog',
    'expChartModal','expChartModalScrim','expChartModalTitle','expChartModalSubtitle','expChartModalDesc','expChartModalChart','expChartModalStats','expChartModalFactors','expChartModalCloseBtn','expChartModalFullscreenBtn',
    'expLlmConfigMeta','expLlmEnabledChk','expLlmAutoChk','expLlmBaseUrl','expLlmModel','expLlmApiKey','expLlmMaxPromptChars','expLlmRefreshBtn','expLlmSaveBtn','expLlmSaveFeedback','expLlmStartBtn','expLlmStartForceBtn','expLlmStatusRefreshBtn','expLlmStatusMeta','expLlmStatusFeedback','expLlmReport','expLlmCopyReportBtn','expLlmDownloadReportBtn'
  ].forEach((id)=> DOM[id]=byId(id));

  DOM.expRefreshRunsInlineBtn = byId('expRefreshRunsInlineBtn');
  DOM.expRefreshRunSummaryBtn = byId('expRefreshRunSummaryBtn');

  if (!DOM.expRefreshRunsInlineBtn && DOM.expDownsampleEvery?.parentElement) {
    const btn = document.createElement('button');
    btn.id = 'expRefreshRunsInlineBtn';
    btn.className = 'ghost';
    btn.type = 'button';
    btn.textContent = '刷新运行记录';
    DOM.expDownsampleEvery.parentElement.parentElement?.insertBefore(btn, DOM.expDownsampleEvery.parentElement);
    DOM.expRefreshRunsInlineBtn = btn;
  }
  if (!DOM.expRefreshRunSummaryBtn && DOM.expRunMeta?.parentElement) {
    const toolbar = DOM.expRunMeta.parentElement;
    const btn = document.createElement('button');
    btn.id = 'expRefreshRunSummaryBtn';
    btn.className = 'ghost';
    btn.type = 'button';
    btn.textContent = '刷新摘要';
    toolbar.appendChild(btn);
    DOM.expRefreshRunSummaryBtn = btn;
  }
  DOM.expMetricPerspectiveBar = byId('expMetricPerspectiveBar');
  if (!DOM.expMetricPerspectiveBar && DOM.expMetricsOverviewCards?.parentElement) {
    const bar = document.createElement('div');
    bar.id = 'expMetricPerspectiveBar';
    bar.className = 'exp-perspective-toolbar';
    DOM.expMetricsOverviewCards.parentElement.insertBefore(bar, DOM.expMetricsOverviewCards);
    DOM.expMetricPerspectiveBar = bar;
  }
  if (DOM.expChartModal) {
    DOM.expChartModal.hidden = true;
    DOM.expChartModal.setAttribute('aria-hidden', 'true');
  }
}

function normalizeRowsForChart(rowsList, series) {
  const src = asArray(rowsList).filter((r)=>r && typeof r === 'object');
  if (!src.length) return [];
  const tickMap = new Map();
  src.forEach((row, idx) => {
    const tick = asNumber(row.tick_index, idx);
    tickMap.set(tick, row);
  });
  const ticks = Array.from(tickMap.keys()).sort((a,b)=>a-b);
  const minTick = ticks[0], maxTick = ticks[ticks.length-1];
  const prev = Object.create(null);
  const keys = asArray(series).map((s)=>String(s?.key || '')).filter(Boolean);
  const out = [];
  for(let tick=minTick; tick<=maxTick; tick+=1){
    const row = tickMap.get(tick);
    const next = { tick_index: tick, __synthetic_gap__: !row };
    if (row) Object.assign(next, row);
    keys.forEach((key)=>{
      const raw = row?.[key];
      const num = Number(raw);
      if (Number.isFinite(num)) { next[key] = num; prev[key] = num; }
      else if (Object.prototype.hasOwnProperty.call(prev, key)) next[key] = prev[key];
      else next[key] = 0;
    });
    out.push(next);
  }
  return out;
}

function chartNoDataMessage() {
  const every = Math.max(1, asNumber(STATE.lastMetricsEvery, 1));
  if (every > 1) {
    return `暂无可绘制数据。当前下采样步长为 ${every}，稀疏事件型指标可能被采样掩盖；建议先将下采样调为 1 再查看。`;
  }
  return '暂无可绘制数据。';
}

function renderLineChart(container, cfg) {
  if (!container) return;
  const sourceSeries = asArray(cfg?.series);
  const rows0 = normalizeRowsForChart(cfg?.rows, sourceSeries);
  const series = sourceSeries.filter((s)=> rows0.some((r)=> Number.isFinite(Number(r?.[s.key])) && Number(r?.[s.key]) !== 0));
  const rows = normalizeRowsForChart(cfg?.rows, series);
  if (!rows.length || !series.length) { container.innerHTML = emptyState(chartNoDataMessage()); return; }
  const xs = rows.map((r, i) => asNumber(r.tick_index, i));
  let yMin = Infinity, yMax = -Infinity;
  series.forEach((s)=> rows.forEach((r)=>{ const v=asNumber(r[s.key],0); if(v<yMin) yMin=v; if(v>yMax) yMax=v; }));
  if (!Number.isFinite(yMin) || !Number.isFinite(yMax)) { yMin = 0; yMax = 1; }
  if (Math.abs(yMax - yMin) < 1e-9) yMax = yMin + 1;
  const w = 980, h = 360, padL = 54, padR = 20, padT = 14, padB = 36;
  const xMin = xs[0], xMax = xs[xs.length-1], xSpan = Math.max(1e-9, xMax - xMin), ySpan = Math.max(1e-9, yMax - yMin);
  const X = (x) => padL + ((x - xMin) / xSpan) * (w - padL - padR);
  const Y = (y) => padT + (1 - (y - yMin) / ySpan) * (h - padT - padB);
  const grid = Array.from({length:5}, (_,i)=>{ const yy = padT + (i/4)*(h-padT-padB); return `<line x1="${padL}" y1="${yy.toFixed(2)}" x2="${w-padR}" y2="${yy.toFixed(2)}" stroke="rgba(21,55,45,0.10)" stroke-width="1" />`; }).join('');
  const paths = series.map((s)=>{
    let d='';
    rows.forEach((r, i)=>{ const x = X(xs[i]); const y = Y(asNumber(r[s.key],0)); d += i===0 ? `M ${x.toFixed(2)} ${y.toFixed(2)}` : ` L ${x.toFixed(2)} ${y.toFixed(2)}`; });
    return `<path d="${d}" fill="none" stroke="${esc(s.color || '#18453b')}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" opacity="0.94" />`;
  }).join('');
  const points = series.map((s)=> rows.map((r, i)=> { const x = X(xs[i]); const y = Y(asNumber(r[s.key], 0)); return `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="8" fill="transparent" data-tip="${esc((r.__tick_label || ('tick ' + r.tick_index)) + ' | ' + (s.name || s.key) + '：' + formatMaybe(r[s.key], 3))}"></circle>`; }).join('')).join('');
  const legend = `<div class="chart-legend">${series.map((s)=>`<span class="chart-chip"><span class="chart-swatch" style="background:${esc(s.color||'#18453b')}"></span>${esc(s.name||s.key)}</span>`).join('')}</div>`;
  container.innerHTML = `<div class="chart-hover-tip" hidden></div><svg class="chart-svg" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">${grid}${paths}${points}<line x1="${padL}" y1="${h-padB}" x2="${w-padR}" y2="${h-padB}" stroke="rgba(21,55,45,0.18)"/><line x1="${padL}" y1="${padT}" x2="${padL}" y2="${h-padB}" stroke="rgba(21,55,45,0.18)"/><text x="${padL}" y="${padT+10}" fill="rgba(21,55,45,0.64)" font-size="11">${esc(yMax.toFixed(3))}</text><text x="${padL}" y="${h-padB+18}" fill="rgba(21,55,45,0.64)" font-size="11">${esc(yMin.toFixed(3))}</text><text x="${padL}" y="${h-8}" fill="rgba(21,55,45,0.64)" font-size="11">tick ${esc(String(xMin))}</text><text x="${w-padR-60}" y="${h-8}" fill="rgba(21,55,45,0.64)" font-size="11">tick ${esc(String(xMax))}</text></svg>${legend}`;
  bindChartHover(container);
}
function renderBarChart(container, cfg) {
  if (!container) return;
  const sourceSeries = asArray(cfg?.series);
  const rows0 = normalizeRowsForChart(cfg?.rows, sourceSeries);
  const series = sourceSeries.filter((s)=> rows0.some((r)=> Number.isFinite(Number(r?.[s.key])) && Number(r?.[s.key]) !== 0));
  const rows = normalizeRowsForChart(cfg?.rows, series);
  if (!rows.length || !series.length) { container.innerHTML = emptyState(chartNoDataMessage()); return; }
  const w = 980, h = 360, padL = 44, padR = 18, padT = 14, padB = 34;
  const xs = rows.map((_, i) => i);
  let yMax = 0;
  series.forEach((s)=> rows.forEach((r)=> { yMax = Math.max(yMax, asNumber(r[s.key], 0)); }));
  yMax = Math.max(1, yMax);
  const barGroupWidth = (w - padL - padR) / Math.max(1, rows.length);
  const barWidth = Math.max(1, (barGroupWidth * 0.82) / Math.max(1, series.length));
  const Y = (v)=> padT + (1 - (v / yMax)) * (h - padT - padB);
  const bars = [];
  rows.forEach((r, i)=> {
    series.forEach((s, si)=> {
      const v = asNumber(r[s.key], 0);
      const x = padL + i * barGroupWidth + si * barWidth;
      const y = Y(v);
      const bh = Math.max(1, (h - padB) - y);
      bars.push(`<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${Math.max(1, barWidth - 1).toFixed(2)}" height="${bh.toFixed(2)}" fill="${esc(s.color || '#18453b')}" rx="2" data-tip="${esc((r.__tick_label || ('tick ' + r.tick_index)) + ' | ' + (s.name || s.key) + '：' + formatMaybe(v, 3))}" />`);
    });
  });
  const legend = `<div class="chart-legend">${series.map((s)=>`<span class="chart-chip"><span class="chart-swatch" style="background:${esc(s.color || '#18453b')}"></span>${esc(s.name || s.key)}</span>`).join('')}</div>`;
  container.innerHTML = `<div class="chart-hover-tip" hidden></div><svg class="chart-svg" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">${bars.join('')}<line x1="${padL}" y1="${h-padB}" x2="${w-padR}" y2="${h-padB}" stroke="rgba(21,55,45,0.18)"/><line x1="${padL}" y1="${padT}" x2="${padL}" y2="${h-padB}" stroke="rgba(21,55,45,0.18)"/></svg>${legend}`;
  bindChartHover(container);
}
function renderAreaChart(container, cfg) {
  if (!container) return;
  const sourceSeries = asArray(cfg?.series);
  const rows0 = normalizeRowsForChart(cfg?.rows, sourceSeries);
  const series = sourceSeries.filter((s)=> rows0.some((r)=> Number.isFinite(Number(r?.[s.key])) && Number(r?.[s.key]) !== 0));
  const rows = normalizeRowsForChart(cfg?.rows, series);
  if (!rows.length || !series.length) { container.innerHTML = emptyState(chartNoDataMessage()); return; }
  const xs = rows.map((r, i) => asNumber(r.tick_index, i));
  let yMin = 0, yMax = -Infinity;
  series.forEach((s)=> rows.forEach((r)=>{ const v=asNumber(r[s.key],0); if(v>yMax) yMax=v; }));
  if (!Number.isFinite(yMax) || yMax <= 0) yMax = 1;
  const w = 980, h = 360, padL = 54, padR = 20, padT = 14, padB = 36;
  const xMin = xs[0], xMax = xs[xs.length-1], xSpan = Math.max(1e-9, xMax - xMin), ySpan = Math.max(1e-9, yMax - yMin);
  const X = (x) => padL + ((x - xMin) / xSpan) * (w - padL - padR);
  const Y = (y) => padT + (1 - (y - yMin) / ySpan) * (h - padT - padB);
  const baseY = h - padB;
  const areas = series.map((s)=> {
    let line = '';
    rows.forEach((r, i)=> { const x = X(xs[i]); const y = Y(asNumber(r[s.key],0)); line += i===0 ? `M ${x.toFixed(2)} ${y.toFixed(2)}` : ` L ${x.toFixed(2)} ${y.toFixed(2)}`; });
    const firstX = X(xs[0]);
    const lastX = X(xs[xs.length - 1]);
    const area = `${line} L ${lastX.toFixed(2)} ${baseY.toFixed(2)} L ${firstX.toFixed(2)} ${baseY.toFixed(2)} Z`;
    return `<path d="${area}" fill="${esc(s.color || '#18453b')}" opacity="0.16" /><path d="${line}" fill="none" stroke="${esc(s.color || '#18453b')}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" opacity="0.96" />`;
  }).join('');
  const points = series.map((s)=> rows.map((r, i)=> { const x = X(xs[i]); const y = Y(asNumber(r[s.key], 0)); return `<circle cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="8" fill="transparent" data-tip="${esc((r.__tick_label || ('tick ' + r.tick_index)) + ' | ' + (s.name || s.key) + '：' + formatMaybe(r[s.key], 3))}"></circle>`; }).join('')).join('');
  const legend = `<div class="chart-legend">${series.map((s)=>`<span class="chart-chip"><span class="chart-swatch" style="background:${esc(s.color||'#18453b')}"></span>${esc(s.name||s.key)}</span>`).join('')}</div>`;
  container.innerHTML = `<div class="chart-hover-tip" hidden></div><svg class="chart-svg" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">${areas}${points}<line x1="${padL}" y1="${baseY}" x2="${w-padR}" y2="${baseY}" stroke="rgba(21,55,45,0.18)"/><line x1="${padL}" y1="${padT}" x2="${padL}" y2="${baseY}" stroke="rgba(21,55,45,0.18)"/></svg>${legend}`;
  container.classList.add('chart-area-mode');
  bindChartHover(container);
}
function renderStackedBarChart(container, cfg) {
  if (!container) return;
  const sourceSeries = asArray(cfg?.series);
  const rows0 = normalizeRowsForChart(cfg?.rows, sourceSeries);
  const series = sourceSeries.filter((s)=> rows0.some((r)=> Number.isFinite(Number(r?.[s.key])) && Number(r?.[s.key]) !== 0));
  const rows = normalizeRowsForChart(cfg?.rows, series);
  if (!rows.length || !series.length) { container.innerHTML = emptyState(chartNoDataMessage()); return; }
  const w = 980, h = 360, padL = 44, padR = 18, padT = 14, padB = 34;
  const totals = rows.map((r)=> series.reduce((sum, s)=> sum + Math.max(0, asNumber(r[s.key], 0)), 0));
  const yMax = Math.max(1, ...totals);
  const barGroupWidth = (w - padL - padR) / Math.max(1, rows.length);
  const barWidth = Math.max(8, barGroupWidth * 0.52);
  const Y = (v)=> padT + (1 - (v / yMax)) * (h - padT - padB);
  const bars = [];
  rows.forEach((r, i)=> {
    let acc = 0;
    series.forEach((s)=> {
      const v = Math.max(0, asNumber(r[s.key], 0));
      const nextAcc = acc + v;
      const y = Y(nextAcc);
      const bh = Math.max(1, Y(acc) - y);
      const x = padL + i * barGroupWidth + (barGroupWidth - barWidth) / 2;
      bars.push(`<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barWidth.toFixed(2)}" height="${bh.toFixed(2)}" fill="${esc(s.color || '#18453b')}" rx="2" data-tip="${esc((r.__tick_label || ('tick ' + r.tick_index)) + ' | ' + (s.name || s.key) + '：' + formatMaybe(v, 3))}" />`);
      acc = nextAcc;
    });
  });
  const legend = `<div class="chart-legend">${series.map((s)=>`<span class="chart-chip"><span class="chart-swatch" style="background:${esc(s.color || '#18453b')}"></span>${esc(s.name || s.key)}</span>`).join('')}</div>`;
  container.innerHTML = `<div class="chart-hover-tip" hidden></div><svg class="chart-svg" viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">${bars.join('')}<line x1="${padL}" y1="${h-padB}" x2="${w-padR}" y2="${h-padB}" stroke="rgba(21,55,45,0.18)"/><line x1="${padL}" y1="${padT}" x2="${padL}" y2="${h-padB}" stroke="rgba(21,55,45,0.18)"/></svg>${legend}`;
  bindChartHover(container);
}
function renderChart(container, cfg) {
  const type = String(cfg?.chartType || 'line');
  if (type === 'area') return renderAreaChart(container, cfg);
  if (type === 'bar_stacked') return renderStackedBarChart(container, cfg);
  if (type === 'bar' || type === 'bar_grouped' || type === 'bar_stacked') return renderBarChart(container, cfg);
  return renderLineChart(container, cfg);
}

const CHART_COLORS = ['#1f6f5f','#c17c4a','#5b8def','#b05d8f','#2f8f83','#d1a545','#5d6cc1','#7a9e47','#c45f43','#3b7ea6','#8c6dd7','#9b774a'];
function buildSeries(keys, startIndex = 0) {
  return asArray(keys).map((entry, idx)=> {
    const key = typeof entry === 'string' ? entry : String(entry?.key || '');
    const preserveFlatLine = !!(entry && typeof entry === 'object' && entry.preserveFlatLine);
    const name = (entry && typeof entry === 'object' && entry.name) ? String(entry.name) : metricLabel(key);
    return { key, name, preserveFlatLine, color: CHART_COLORS[(startIndex + idx) % CHART_COLORS.length] };
  });
}
function chartConfig(id, section, title, subtitle, description, chartType, keys, extra = {}) { return { id, section, title, subtitle, description, chartType, series: buildSeries(keys, extra.colorOffset || 0), ...extra }; }
function getRenderableSeries(rows, series) { return asArray(series).filter((s)=> !isMeaninglessSeries(rows, s?.key, { keepConstant: !!s?.preserveFlatLine })); }
function metricsHaveSignal(rows, keys) {
  return asArray(keys).some((entry)=> {
    const key = typeof entry === 'string' ? entry : String(entry?.key || '');
    const stats = analyzeSeries(rows, key);
    return !!(stats && !stats.allZero);
  });
}
function renderMetricCardSpecs(rows, specs) {
  return asArray(specs)
    .filter((spec)=> spec && (spec.alwaysShow || metricsHaveSignal(rows, spec.keys || [])))
    .map((spec)=> metricCard(spec.label, spec.value, spec.note))
    .join('');
}
function renderMiniRowSpecs(rows, specs) {
  return asArray(specs)
    .filter((spec)=> spec && (spec.alwaysShow || metricsHaveSignal(rows, spec.keys || [])))
    .map((spec)=> miniRow(spec.title, spec.desc))
    .join('');
}
function getChartSeriesState(rows, series) {
  const src = asArray(series);
  const visibleSeries = getRenderableSeries(rows, src);
  const zeroSeries = src.filter((item)=> {
    const stats = analyzeSeries(rows, item?.key);
    return !!(stats && stats.allZero);
  });
  const missingSeries = src.filter((item)=> !analyzeSeries(rows, item?.key));
  return {
    visibleSeries,
    zeroSeries,
    missingSeries,
    allZero: src.length > 0 && !visibleSeries.length && zeroSeries.length === src.length,
  };
}
function getHiddenChartReason(chartState) {
  const visibleCount = asArray(chartState?.visibleSeries).length;
  if (visibleCount > 0) return '';
  const zeroCount = asArray(chartState?.zeroSeries).length;
  const missingCount = asArray(chartState?.missingSeries).length;
  if (chartState?.allZero) return '全部序列为 0';
  if (missingCount > 0 && zeroCount === 0) return '当前运行缺少这些字段';
  if (missingCount > 0 && zeroCount > 0) return '部分字段缺失，部分序列为 0';
  return '当前运行没有可绘制信号';
}
function renderHiddenChartRow(cfg, chartState) {
  const zeroSeries = asArray(chartState?.zeroSeries);
  const missingSeries = asArray(chartState?.missingSeries);
  const zeroNames = zeroSeries.map((item)=> item?.name || item?.key || '-').filter(Boolean);
  const missingNames = missingSeries.map((item)=> item?.name || item?.key || '-').filter(Boolean);
  const zeroLabel = zeroNames.length > 5 ? `${zeroNames.slice(0, 5).join('、')} 等 ${zeroNames.length} 项` : zeroNames.join('、');
  const missingLabel = missingNames.length > 5 ? `${missingNames.slice(0, 5).join('、')} 等 ${missingNames.length} 项` : missingNames.join('、');
  const reason = getHiddenChartReason(chartState);
  const detailParts = [
    cfg.subtitle || '',
    cfg.description || '',
    zeroLabel ? `全零：${zeroLabel}` : '',
    missingLabel ? `缺字段：${missingLabel}` : '',
  ].filter(Boolean);
  return miniRow(`${cfg.title} · ${reason}`, detailParts.join('\n') || '本次运行没有足够数据绘制这张图。');
}

const CHART_SECTIONS = [
  { id: 'overview', title: '运行总览', description: '先看整体稳态：能量、负载与状态池规模是否健康。', diagnostic: false },
  { id: 'context', title: '激活/旧上下文审计', description: '折叠观察旧 residual/context/provenance 口径。新版正式 growth 身份优先看完整特征汇聚，不把 owner DB 当身份。', diagnostic: true },
  { id: 'induction', title: '能量传播', description: '把局部 EV 传播与 ER 诱发 EV 拆开看，避免只盯总能量。', diagnostic: false },
  { id: 'sensor', title: '感受器', description: '专门观察文本感受器输入文本、输入长度、外源构成与残响参与情况。', diagnostic: false },
  { id: 'stimulus', title: '刺激链路', description: '观察外源输入、内源补充、合流中和与落地是否连贯。', diagnostic: false },
  { id: 'internal', title: '内源解析与查存', description: '检查内源刺激来源、预算约束、分辨率和刺激级查存一体是否能把多对象叠加态重新采样为新种子。', diagnostic: false },
  { id: 'stitching', title: 'CS 回滚诊断', description: '仅在显式开启 residual/CS 对照时观察认知拼接；默认 growth 主链下它不是主要结论来源。', diagnostic: true },
  { id: 'cfs', title: '认知感受', description: '把峰值、运行态维持量与触发频次拆开看，避免语义混杂。', diagnostic: false },
  { id: 'reward', title: '奖惩与监督', description: '观察系统奖惩、教师信号与期望契约监督是否生效。', diagnostic: false },
  { id: 'neuro', title: '情绪递质', description: '将应激稳定与奖励趋近两类递质分开观察。', diagnostic: false },
  { id: 'action', title: '行动链路', description: '拆开执行结果、尝试调度、驱动力与节点规模。', diagnostic: false },
  { id: 'time', title: '时间感受器', description: '区分时间绑定活动与延迟任务活动。', diagnostic: false },
  { id: 'map', title: 'MAP兼容诊断', description: '观察旧 MAP/记忆反馈兼容支路；默认主链优先看感应生长和运行态记忆旁路。', diagnostic: true },
  { id: 'performance', title: '性能分析', description: '主性能与细分性能分开显示，方便定位真正大头。', diagnostic: false },
  { id: 'diagnostic', title: '诊断图表', description: '保留调试所需的补充指标，但不干扰主视图。', diagnostic: true },
];

const CHART_CONFIGS = [
  chartConfig('pool_energy','overview','状态池总能量','实能量、虚能量与认知压的整体趋势','用于判断系统是否稳定维持活跃运行。','line',['pool_total_er','pool_total_ev','pool_total_cp']),
  chartConfig('pool_load','overview','状态池规模与负载','活跃条目、高压条目与注意力负载','用于判断状态池是否过载、过空或被某类负载占满。','line',['pool_active_item_count','pool_high_cp_item_count','attention_memory_item_count','attention_cam_item_count']),
  chartConfig('pool_structure_vs_atomic_top','overview','结构 Top 与原子 SA 证据','ER/EV Top5 中完整结构峰和原子特征证据的数量对照','用于避免把外源字符 SA 的真实证据峰误读成旧 residual/context 半成品。新版默认口径下，ER 侧可以保留原子 SA 证据；真正判断感应生长是否有效，应重点看结构 Top、EV 侧原子 SA 数、induction_growth_* 与 CS 是否关闭。','bar_grouped',['pool_er_structure_top5_count','pool_ev_structure_top5_count','pool_er_atomic_feature_sa_top5_count','pool_ev_atomic_feature_sa_top5_count']),
  chartConfig('attention_energy_resource','overview','注意力能量资源','预算、净增、抑制与滤波后 CAM 能量','用于观察注意力滤波到底给系统注入了多少受限能量，以及它如何和基础 CAM 能量、抑制量共同形成最终内源刺激强度。','line',['attention_energy_budget','attention_net_delta_energy','attention_gain_budget_applied','attention_suppressed_total_energy','attention_base_memory_total_energy','attention_final_memory_total_energy']),
  chartConfig('pool_complexity_score','overview','状态池复杂度双口径','全量复杂度与核心复杂度并排对照','用于区分“弱 SA 长尾很多”与“真正结构性复杂度高”这两种不同图景。','line',['complexity_score','core_complexity_score']),
  chartConfig('pool_peak_concentration','overview','状态池峰形集中度','全量/核心能量集中度','用于观察能量是被少数峰锁住，还是正在向更均匀的多峰结构展开。','line',['energy_concentration','core_energy_concentration']),
  chartConfig('pool_peak_count','overview','状态池有效峰数','全量/核心有效峰数','用于观察复杂度变化到底来自整体尾巴膨胀，还是来自核心结构峰真的变多。','line',['effective_peak_count','core_effective_peak_count']),
  chartConfig('overview_hdb','overview','长期积累规模','结构、结构组与情节记忆的增长','用于观察长期积累是否在稳定形成。','area',['hdb_structure_count','hdb_group_count','hdb_episodic_count']),
  chartConfig('runtime_resolution_state_pool','overview','运行态分辨率','状态池对象组件在运行态保留、淡出与维护刷新','用于审计新版退化口径：组件能量低于阈值时只是状态池显示/解释分辨率下降，仍保留完整 root identity，不重新查存一体，也不创建退化 HDB 身份。','bar_grouped',['pool_runtime_resolution_degraded_item_count','pool_runtime_resolution_active_component_count','pool_runtime_resolution_dropped_component_count','maintenance_runtime_resolution_refreshed_item_count','maintenance_runtime_resolution_degraded_item_count']),
  chartConfig('energy_balance_ratio_track','diagnostic','旧式虚实比诊断','当前 EV/ER、旧闭环平滑比值与目标比值','默认新口径下它主要用于诊断或回退实验，不应再被误读成系统必须追踪的主目标。','line',['pool_ev_to_er_ratio','energy_balance_ratio_smooth',{ key:'energy_balance_target_ratio', preserveFlatLine:true }]),
  chartConfig('energy_balance_gain_track','diagnostic','旧式能量平衡控制输出','当前共享控制增益','仅在启用可选旧闭环控制器后才有实质意义；默认关闭时它更像回退实验探针。','line',[{ key:'energy_balance_g_after', preserveFlatLine:true }]),
  chartConfig('energy_balance_effective_track','diagnostic','旧式闭环 HDB 生效比例','请求比例、实际比例与运行时截断后的差异','用于审计可选旧闭环控制器虽已出手时，HDB 真实生效值是否已经撞上 0~1 的运行时上限。','line',[{ key:'hdb_requested_ev_propagation_ratio', preserveFlatLine:true },{ key:'hdb_effective_ev_propagation_ratio', preserveFlatLine:true },{ key:'hdb_requested_er_induction_ratio', preserveFlatLine:true },{ key:'hdb_effective_er_induction_ratio', preserveFlatLine:true }]),

  chartConfig('context_pool','context','状态池激活/旧上下文审计','广义激活链、显式旧上下文、多路径与残差来源占比','用于把 provenance、legacy residual/context 半成品和正式 growth 完整身份分开观察。新版默认下，正式 HDB-backed 生长对象应按完整特征身份汇聚；显式上下文升高通常表示兼容/诊断路径仍在产生带 context 的对象。','line',['pool_contextual_item_ratio','pool_explicit_context_item_ratio','pool_multi_context_item_ratio','pool_residual_origin_item_ratio'], { diagnostic: true }),
  chartConfig('context_hdb','context','HDB 上下文化残留诊断','上下文化结构、多上下文结构与同内容多上下文占比','用于审计旧上下文身份是否还在长期库里残留。新版感应生长下，A+B 的身份应由完整特征解析并聚合，owner/context 只应作为激活来源或审计信息；该图不再代表主身份哲学。','line',['hdb_contextual_structure_ratio','hdb_multi_context_structure_ratio','hdb_same_content_multi_context_ratio'], { diagnostic: true }),
  chartConfig('context_path','context','来源路径深度诊断','状态池广义/显式路径与 HDB 平均上下文路径深度','用于判断对象是否仍携带较深 legacy context/provenance 路径。默认 growth 主链只把这些路径作为审计来源，不把它们当完整结构身份。','line',['pool_context_path_depth_mean','pool_explicit_context_path_depth_mean','hdb_structure_context_path_depth_mean'], { diagnostic: true }),
  chartConfig('residual_linking','context','残差局部链接','上下文差异链接与残差局部链接占比','用于诊断 HDB 内部 diff/residual 边是否仍保持局部传播。它描述数据库内部边，不代表状态池对象必须以 B(context=A) 半成品存在。','line',[{ key:'hdb_contextual_diff_entry_ratio', preserveFlatLine:true },{ key:'hdb_residual_diff_entry_ratio', preserveFlatLine:true }], { diagnostic: true }),
  chartConfig('hdb_pointer_cache','context','HDB 指针与缓存诊断','主/回退指针、签名索引、缓存与数值桶规模','用于观察新的查存一体缓存是否真的积累起来，以及 fallback / 数值软匹配索引是否已经建稳。','bar_grouped',['hdb_primary_pointer_count','hdb_fallback_pointer_count','hdb_signature_index_count','hdb_recent_cache_count','hdb_exact_lookup_cache_count','hdb_numeric_bucket_family_count','hdb_numeric_bucket_count'], { diagnostic: true }),

    chartConfig('induction_energy','induction','感应赋能能量构成','总增量、局部传播与 ER 诱发 EV 的拆分','用于把“已有预期继续扩散”和“现实证据诱发新预期”明确拆开。','line',['induction_total_delta_ev','induction_propagated_ev_total','induction_ev_from_er_total']),
    chartConfig('induction_split','induction','感应赋能去向分流','总 EV 中有多少走结构直投，有多少走记忆激活路径','用于避免把 memory path 的正常分流，误判成结构直投失败。','area',['induction_total_delta_ev','induction_structure_target_total_ev','induction_memory_target_total_ev']),
    chartConfig('induction_landing','induction','感应赋能结构直投落地质量','结构路径计划 EV、实际落地 EV 与被跳过 EV','用于判断真正投向状态池结构路径的那部分 EV，是否在投影阶段被挡住。','line',['induction_structure_target_total_ev','induction_applied_total_ev','induction_skipped_target_total_ev']),
    chartConfig('induction_topology','induction','感应赋能路径规模','源对象数、总目标、结构目标与记忆目标','用于判断感应赋能更偏直接入池，还是更多先进入记忆激活池。','bar_grouped',['induction_source_item_count','induction_target_count','induction_structure_target_count','induction_memory_target_count']),
  chartConfig('induction_source_mix','induction','感应源构成','全池运行态源中的 ST / ER / EV 参与情况','用于判断默认“全状态池有能量对象参与”口径下，真正进入传播的源对象更偏 ST、ER 还是 EV；旧混合模式下仍可用来观察 cp 回退补位。','bar_grouped',['induction_source_available_st_count','induction_source_selected_from_ev_count','induction_source_selected_from_er_count','induction_source_selected_from_cp_abs_count']),
  chartConfig('induction_source_quality','induction','感应源本地候选质量','可继续传播源提示、真正可传播源与空候选源','用于判断参与的高能 source 里，有多少真的带着可用局部残差目标，而不是只有能量没有局部数据库路径。','bar_grouped',['induction_source_available_with_local_target_hint_count','induction_source_selected_with_local_target_hint_count','induction_source_selected_zero_local_target_hint_count','induction_target_count']),
    chartConfig('induction_raw_residual_hit','induction','原始残差结构复用/补建','原始残差条目、命中已存结构、现场补建结构与最终结构候选','用于判断 residual/context 局部链里，是已有结构在被复用，还是主路已经现场补出了新的结构对象。','bar_grouped',['induction_raw_residual_entry_count','induction_raw_residual_entry_with_existing_structure_count','induction_raw_residual_entry_materialized_structure_count','induction_raw_residual_entry_routed_to_structure_count','induction_raw_residual_existing_structure_target_count','induction_raw_residual_materialized_structure_target_count']),
    chartConfig('induction_raw_residual_component_hit','induction','原始残差组分回退命中','全签名 miss 后，组分结构命中与实际转结构情况','用于判断晚期 residual 是否只是整体签名太新，但局部组分其实已经能在 HDB 里复用。','bar_grouped',['induction_raw_residual_entry_count','induction_raw_residual_entry_with_component_structure_count','induction_raw_residual_entry_routed_to_component_structure_count','induction_raw_residual_component_structure_target_count']),
    chartConfig('induction_raw_residual_split','induction','原始残差双路径分流','原始残差走结构与走记忆的 EV 分流','用于判断原始残差命中现成结构之后，预算是否真的流向结构链，而不是仍几乎全部留在记忆路径。','area',['induction_raw_residual_target_total_ev','induction_raw_residual_structure_target_total_ev','induction_raw_residual_memory_target_total_ev']),
    chartConfig('induction_raw_residual_structure_kind','induction','原始残差结构路径细分','结构路径中的完整签名复用与组分回退 EV','用于区分结构路径变厚后，究竟是完整签名命中在起作用，还是组分级回退在托底。','area',['induction_raw_residual_structure_target_total_ev','induction_raw_residual_exact_structure_target_total_ev','induction_raw_residual_component_structure_target_total_ev']),
    chartConfig('induction_raw_residual_budget_kind','induction','原始残差结构预算细分','总体结构预算、完整签名预算、现场补建预算与组分回退预算','用于判断结构路径预算具体投向了哪种复用方式。','line',['induction_raw_residual_structure_budget_weight','induction_raw_residual_exact_structure_budget_weight','induction_raw_residual_materialized_structure_budget_weight','induction_raw_residual_component_structure_budget_weight']),
    chartConfig('induction_raw_residual_static_cache','induction','原始残差静态解析缓存','投影 profile、完整候选、组分候选与完整包含判定的本轮/跨 tick 缓存','用于确认性能优化是否减少重复 owner-subtract、签名查询、组分查询和包含判定；默认只开启投影 profile 缓存，候选列表缓存因活跃学习期索引版本变化频繁而默认关闭。这些字段只缓存结构形状，不缓存 entry runtime_weight、疲劳或本轮 EV/ER 分配。','bar_grouped',['induction_raw_residual_projection_profile_local_cache_hit_count','induction_raw_residual_projection_profile_shared_cache_hit_count','induction_raw_residual_projection_profile_cache_store_count','induction_raw_residual_exact_candidates_local_cache_hit_count','induction_raw_residual_exact_candidates_shared_cache_hit_count','induction_raw_residual_exact_candidates_cache_store_count','induction_raw_residual_component_candidates_local_cache_hit_count','induction_raw_residual_component_candidates_shared_cache_hit_count','induction_raw_residual_component_candidates_cache_store_count','induction_full_inclusion_shared_cache_hit_count','induction_full_inclusion_shared_cache_store_count']),
    chartConfig('induction_raw_residual_hit_split','induction','原始残差命中内部分流','只看“已命中现成结构”的条目：转结构 EV、命中后仍走记忆 EV，以及未命中纯记忆 EV','用于区分“结构 share 太保守”和“其实是命中率太低”这两种完全不同的问题。','area',['induction_raw_residual_structure_target_total_ev','induction_raw_residual_hit_memory_target_total_ev','induction_raw_residual_miss_memory_target_total_ev']),
    chartConfig('induction_growth_projection','induction','感应生长投影质量','A+B 生长目标、完整身份命中/创建、暂存、剪枝与去重','用于审计新版默认感应生长方案是否真的把 A 的局部残差 B 直接投影成完整结构 A+B，而不是回到旧的 B(context=A) 半成品路径。','bar_grouped',[{ key:'induction_projection_mode_growth', preserveFlatLine:true },'induction_projection_raw_target_count','induction_projection_projected_target_count','induction_growth_target_count','induction_growth_identity_hit_count','induction_growth_identity_created_count','induction_growth_identity_local_cache_hit_count','induction_growth_identity_shared_cache_hit_count','induction_growth_identity_shared_cache_stale_count','induction_growth_identity_create_exact_lookup_skipped_count',{ key:'induction_growth_persistence_batch_enabled', preserveFlatLine:true },{ key:'induction_growth_target_apply_ref_fast_merge_enabled', preserveFlatLine:true },'induction_growth_target_apply_fast_ref_hit_merge_count',{ key:'induction_growth_target_apply_insert_log_enabled', preserveFlatLine:true },'induction_growth_target_apply_insert_log_suppressed_count','induction_growth_runtime_only_count','induction_growth_pruned_low_energy_count','induction_growth_failed_count','induction_growth_deduped_count']),
    chartConfig('induction_growth_energy','induction','感应生长 ER/EV 份额','生长对象统计 ER、预测 EV 与总体感应 EV 对照','用于确认 A+B 结构整体显示的 ER/EV 只是组件统计：来源 A 的真实 ER 可以作为 source-side ER 份额出现，残差 B 的预测能量仍应主要体现为 EV。','line',['induction_growth_total_delta_er','induction_growth_total_delta_ev','induction_growth_source_component_er_total','induction_growth_residual_component_ev_total','induction_total_delta_er','induction_total_delta_ev']),
    chartConfig('induction_growth_guardrails','induction','感应生长保护与旁路','低能剪枝、缺源/缺残差、运行态暂存与记忆终端旁路','用于确认 growth 主链没有退回旧半成品路径，同时也没有无界物化：低能候选可被剪掉，纯虚/未绑定候选可暂存，终端记忆可旁路到记忆激活路径。','bar_grouped',['induction_growth_pruned_low_energy_count','induction_growth_runtime_only_count','induction_growth_memory_candidate_count','induction_growth_memory_terminal_passthrough_count','induction_growth_skipped_missing_source_count','induction_growth_skipped_missing_residual_count','induction_growth_failed_count']),
    chartConfig('induction_ratio','induction','感应赋能局部性','局部传播目标占比、ER 诱发 EV 占比与每源平均目标数','用于判断当前更像“沿局部残差链扩散”，还是“由现实证据大规模诱发新预期”。','line',['induction_propagated_target_ratio','induction_ev_from_er_ratio','induction_targets_per_source_mean']),
    chartConfig('induction_energy_graph_shape','induction','分层能量图景形态','V2 是否开启、配置轮数上限、实际轮数、深度、层数与最大层宽','用于判断新的分形式 ER/EV 图景是否真的在多轮多层地展开，并区分“配置允许几轮”和“本 tick 实际跑出了几轮”。','line',[{ key:'induction_energy_graph_v2_enabled', preserveFlatLine:true },{ key:'induction_energy_graph_config_max_rounds', preserveFlatLine:true },'induction_energy_graph_round_count_max','induction_energy_graph_depth_max','induction_energy_graph_layer_max_width','induction_energy_graph_layer_count']),
    chartConfig('induction_energy_graph_budget','induction','分层能量图景预算拆分','累计传播预算、前沿预算、根源再诱发预算与实际总增量','用于并排核对“预算投了多少”和“最终真正长出了多少 EV”，判断 V2 图景是否在有效工作。','line',['induction_propagated_budget_total_ev','induction_energy_graph_frontier_budget_total_ev','induction_energy_graph_root_induction_budget_total_ev','induction_total_delta_ev']),
    chartConfig('induction_energy_graph_frontier','induction','分层能量图景前沿演化','前沿生成、剪枝、终端记忆与根源再诱发次数','用于观察前沿是持续展开、被大量剪枝，还是逐渐沉到终端记忆节点。','bar_grouped',['induction_energy_graph_frontier_generated_count','induction_energy_graph_frontier_pruned_count','induction_energy_graph_terminal_memory_count','induction_energy_graph_root_reinduction_count']),
    chartConfig('induction_energy_graph_layers','induction','分层能量图景层级规模','总层节点数、最大层宽与单轮最大前沿进出量','用于观察层内是否形成真正的扇出，以及传播是否在某一层突然卡死或过度膨胀。','line',['induction_energy_graph_layer_total_nodes','induction_energy_graph_layer_max_width','induction_energy_graph_frontier_in_count_max','induction_energy_graph_frontier_out_count_max']),
    chartConfig('induction_energy_graph_delta','induction','分层能量图景轮增量','各轮增量总和、单轮最大增量与末轮增量','用于判断 V2 图景是在前几轮迅速衰减，还是能在多轮中持续保留有效的 EV 贡献。','line',['induction_energy_graph_round_delta_ev_total','induction_energy_graph_round_delta_ev_max','induction_energy_graph_round_delta_ev_last']),

  chartConfig('sensor_text','sensor','输入文本与外源长度','输入字符数、外源 SA 与输入 token 规模','用于直接观察文本感受器当前输入规模与分段后的外源量。','line',['input_len','external_sa_count','cache_input_flat_token_count']),
  chartConfig('sensor_compose','sensor','文本感受器输出构成','基础刺激元、属性刺激元、结构包与残响参与情况','用于判断文本感受器输出是否完整，以及残响是否正常介入。','bar_grouped',['sensor_feature_sa_count','sensor_attribute_sa_count','sensor_csa_bundle_count','sensor_echo_frames_used_count']),

  chartConfig('stimulus_size','stimulus','刺激规模','从外源输入到合流、中和、落地的规模变化','如果某一段长期为 0 或骤降，通常意味着链路缺数或中和异常。','line',['external_sa_count','merged_flat_token_count','cache_residual_flat_token_count','landed_flat_token_count']),
  chartConfig('stimulus_balance','stimulus','内外源平衡','观察内源刺激与外源刺激的相对规模','用于判断内源刺激是否过弱、过强或失去约束。','line',['external_sa_count','internal_sa_count','internal_minus_external_sa_count','internal_to_external_sa_ratio']),
  chartConfig('stimulus_energy_landing','stimulus','刺激能量落地口径','完整对象投影、记忆尾巴吸收、未处理残余与旧逐轮转移审计','新版 growth 主口径看“完整对象投影 + 当前刺激完整记忆尾巴吸收”是否压过未处理残余；旧 stimulus_transfer_* 仍保留为 selected-match 逐轮审计，不能单独代表刺激能量是否落地失败。','line',['stimulus_object_projection_total','stimulus_memory_tail_absorbed_total','stimulus_unhandled_residual_total','stimulus_transfer_matched_total','stimulus_final_residual_total']),
  chartConfig('stimulus_energy_dominance','stimulus','刺激能量落地验收','对象投影/未处理残余比、对象投影落地占比、逐轮命中转移占比与早停护栏','用于验收“大多数时候给命中/完整对象的能量高于最终剩余”。对象投影占优为 1 且未处理残余接近 0，说明当前刺激尾巴已经通过完整记忆 id 并入状态池，不再需要残余包晋升。','line',[{ key:'stimulus_object_projection_dominates_unhandled_residual', preserveFlatLine:true },'stimulus_object_projection_to_unhandled_residual_ratio','stimulus_object_projection_share_of_projection_plus_unhandled_residual','stimulus_transfer_share_of_matched_plus_residual',{ key:'stimulus_early_stop_object_projection_dominance_triggered', preserveFlatLine:true },'stimulus_early_stop_object_projection_transfer_guard_blocked_count']),
  chartConfig('stimulus_v2_match','stimulus','刺激级 V2 匹配质量','综合分、基础分、数值匹配、时间因子与顺序对齐','用于并排审计刺激级新评分口径是否真的比 legacy 更贴近“像人”的软匹配哲学。','line',['stimulus_match_v2_score_mean','stimulus_match_v2_base_score_mean','stimulus_match_v2_numeric_score_mean','stimulus_match_v2_numeric_time_like_score_mean','stimulus_match_v2_order_alignment_mean']),
  chartConfig('stimulus_v2_support','stimulus','刺激级 V2 支撑与混合效果','可参与比例、属性锚点、上下文支撑、能量图景、阈值余量与混合增益','用于区分 V2 分数偏低是候选根本不合格，还是支撑因子、阈值余量或 blended 夺权力度不够。','line',['stimulus_match_v2_eligible_ratio','stimulus_match_v2_attribute_anchor_mean','stimulus_match_v2_context_support_mean','stimulus_match_v2_energy_profile_mean','stimulus_match_v2_threshold_margin_mean','stimulus_match_v2_blend_gain_mean']),
  chartConfig('numeric_v2_activation','stimulus','数值刺激元显影覆盖率','刺激级/结构级数值显影占比与刺激级数值已评分占比','用于直接区分“数值通路根本没进来”“数值通路进来了但大多没起作用”“数值通路已经真实参与匹配”。','line',['stimulus_match_v2_numeric_scored_ratio','stimulus_match_v2_numeric_nonzero_ratio','structure_match_v2_numeric_scored_ratio','structure_match_v2_numeric_nonzero_ratio']),
  chartConfig('time_factor_v2_activation','time','时间因子显影覆盖率','时间绑定活跃度与 V2 时间因子显影占比','用于判断时间感受是否只是被绑定出来，还是已经真实进入后续 stimulus / structure 匹配评分。','line',['time_sensor_attribute_binding_count','stimulus_match_v2_numeric_time_like_nonzero_ratio','structure_match_v2_numeric_time_like_nonzero_ratio']),
  chartConfig('time_factor_v2_pipeline','time','时间因子显影链路','绑定、内源属性显影、刺激级显影与结构级显影的逐段数量','用于直接排查“时间感受到底卡在绑定、内源展开、刺激级竞争还是结构级竞争”这四个阶段中的哪一段。','bar_grouped',['time_sensor_attribute_binding_count','time_sensor_projection_binding_count','internal_time_like_attribute_count','stimulus_match_v2_numeric_time_like_nonzero_count','structure_match_v2_numeric_time_like_nonzero_count']),
  chartConfig('time_factor_v2_bonus','time','时间因子软增益','刺激级/结构级的时间软增益均值与触发数量','用于判断时间感受不只是“被看见”，而是有没有真的对候选竞争分数形成放大。','line',['stimulus_match_v2_time_factor_bonus_mean','structure_match_v2_time_factor_bonus_mean','stimulus_match_v2_time_factor_bonus_applied_count','structure_match_v2_time_factor_bonus_applied_count']),
  chartConfig('time_factor_v2_wildcard','time','时间 wildcard 显影','刺激级/结构级时间 wildcard 使用次数','用于审计 runtime-em 主链下，残差记忆是否真的通过时间 wildcard 进入软匹配，而不是仍依赖旧记忆池硬查询。','bar_grouped',['stimulus_match_v2_numeric_time_like_wildcard_applied_count','structure_match_v2_numeric_time_like_wildcard_applied_count']),
  chartConfig('time_factor_v2_memory_shadow','time','时间记忆影子显影','影子残差记忆候选中的时间显影、soft bonus 与 wildcard','用于在不改主竞争赢家的前提下，先观察 owner-local residual memory 候选是否真实吃到 V2 时间口径。','bar_grouped',['stimulus_shadow_memory_match_v2_candidate_count','stimulus_shadow_memory_match_v2_eligible_count','stimulus_shadow_memory_match_v2_numeric_time_like_nonzero_count','stimulus_shadow_memory_match_v2_time_factor_bonus_applied_count','stimulus_shadow_memory_match_v2_numeric_time_like_wildcard_applied_count']),
  chartConfig('time_factor_v2_memory_shadow_quality','time','时间记忆影子质量','影子残差记忆候选的综合分、时间接近度与时间软增益均值','用于区分“影子候选存在但时间因子没起作用”和“时间口径已经真实抬分”。','line',['stimulus_shadow_memory_match_v2_score_mean','stimulus_shadow_memory_match_v2_numeric_time_like_score_mean','stimulus_shadow_memory_match_v2_time_factor_bonus_mean']),
  chartConfig('numeric_v2_cost','stimulus','数值刺激元负载与代价','属性刺激元数量、属性比率与关键耗时','用于同时观察数值刺激元显影带来的感受器负载和刺激级检索代价，方便做性能-效果折中。','line',['sensor_attribute_sa_count','sensor_attribute_sa_per_feature_ratio','timing_sensor_ms','timing_stimulus_level_ms']),
  chartConfig('stimulus_candidate_cost','stimulus','刺激级候选代价','owner-local 候选、剪枝与最大共同切割次数','用于定位刺激级查存一体是否被某些局部数据库的候选数量或共同切割拖慢。新版性能护栏会优先保留局部权重/近因更高的候选；promotion 关闭时影子残差精评分可默认跳过，只保留计数诊断。共同切割 exact/full-inclusion/single-group/ordered-subsequence 快路径、缓存/零拷贝命中、规范化复用命中用于判断重复 DP/normalize 是否已被性能快路径吸收。','bar_grouped',['stimulus_local_child_candidate_count','stimulus_local_child_candidate_pruned_count','stimulus_best_match_candidate_count','stimulus_best_match_pruned_count','stimulus_cut_common_part_total_count','stimulus_best_match_common_part_count','stimulus_cut_exact_fast_path_hit_count','stimulus_cut_full_inclusion_fast_path_hit_count','stimulus_cut_single_group_fast_path_hit_count','stimulus_cut_ordered_subsequence_fast_path_hit_count','stimulus_cut_cache_hit_count','stimulus_cut_cache_zero_copy_hit_count','stimulus_cut_cache_store_count','stimulus_cut_normalize_cache_hit_count','stimulus_cut_normalize_reusable_hit_count','stimulus_cut_normalize_reusable_group_count','stimulus_cut_signature_fast_path_hit_count','stimulus_cut_empty_group_fast_path_hit_count','stimulus_cut_reindex_fast_path_hit_count','stimulus_anchor_owner_residual_presence_cache_hit_count','stimulus_anchor_owner_residual_presence_shared_cache_hit_count','stimulus_anchor_owner_residual_presence_shared_cache_store_count','stimulus_anchor_owner_residual_presence_scan_count','stimulus_shadow_raw_residual_candidate_count','stimulus_shadow_raw_residual_candidate_pruned_count','stimulus_shadow_raw_residual_skipped_count','stimulus_shadow_raw_residual_common_part_count']),
  chartConfig('internal_source','internal','内源解析与预算','候选结构、入选结构、片段数与细节预算的合并视图','用于同时判断上游候选是否足够，以及内源分辨率预算是否真的压缩了当前内源刺激。','bar_grouped',['internal_candidate_structure_count','internal_selected_structure_count','internal_fragment_count','internal_resolution_raw_sa_count','internal_resolution_selected_sa_count','internal_resolution_budget_sa_cap']),
  chartConfig('internal_attribute_projection','internal','内源属性刺激元投影','内源属性总数、数值属性数与时间类属性数','用于判断运行时绑定属性是否已经真正进入内源刺激，而不是只停留在结构级 debug 或 state-pool 绑定层。','bar_grouped',['internal_attribute_count','internal_numeric_attribute_count','internal_time_like_attribute_count','internal_sa_count']),
  chartConfig('internal_cfs_projection','internal','内源 CFS 属性显影','CFS 总属性、压力族与期待族在内源中的投影计数','用于观察认知感受运行态是否会在下一 tick 真正进入内源刺激流，而不是只停留在 state-pool 绑定层。','bar_grouped',['internal_cfs_attribute_count','internal_cfs_pressure_family_attribute_count','internal_cfs_expectation_family_attribute_count','internal_numeric_attribute_count']),
  chartConfig('internal_feedback_projection','internal','内源奖惩/教师属性显影','教师奖励、教师惩罚、奖励信号与惩罚信号在内源中的投影计数','用于直接核对 runtime-bound feedback 属性是否跨 tick 进入内源刺激。','bar_grouped',['internal_teacher_reward_signal_attribute_count','internal_teacher_punish_signal_attribute_count','internal_reward_signal_attribute_count','internal_punish_signal_attribute_count']),
  chartConfig('internal_resolution_detail','internal','内源分辨率细项','细节预算、原始细节单元、已选细节单元与已选结构数','用于更细地查看注意力滤波和内源分辨率预算到底压掉了哪些细节。','bar_grouped',['internal_resolution_detail_budget','internal_resolution_raw_unit_count','internal_resolution_selected_unit_count','internal_resolution_structure_count_selected']),
  chartConfig('internal_runtime_priority_resolution','internal','高优先级运行时属性保留链路','高优先级属性结构入选、属性单元保留与 rescue 计数','用于直接判断 teacher / reward / punish / cfs / 时间感受 这类运行时属性，是卡在结构入选阶段，还是卡在 unit trim 阶段。','bar_grouped',['internal_resolution_runtime_priority_structure_count_total_candidates','internal_resolution_runtime_priority_structure_count','internal_resolution_selected_priority_attribute_unit_count','internal_resolution_rescued_priority_attribute_unit_count']),
  chartConfig('internal_cam_runtime_priority_sidepath','internal','CAM 高优先级属性侧路','侧路候选、投影片段、family 数与属性单元数','用于观察当主 fragment 尚未表达 teacher / reward / punish / CFS / 时间感受 family 时，CAM 侧路是否补出了一条轻量属性片段。','bar_grouped',['internal_cam_runtime_priority_projection_candidate_count','internal_cam_runtime_priority_projection_fragment_count','internal_cam_runtime_priority_projection_family_count','internal_cam_runtime_priority_projection_unit_count']),
  chartConfig('internal_resolution_pool','internal','内源来源与工作集关系','当前工作集、来源结构、候选结构与最终片段','用于观察注意力工作集经过内源解析后，最终有多少结构真的吐出了片段。','bar_grouped',['cam_item_count','internal_source_structure_count','internal_candidate_structure_count','internal_fragment_count']),
  chartConfig('retrieval_rounds','internal','查存轮次','结构级、刺激级与内源重采样活动','用于判断系统是否真正经历结构级/刺激级查存一体，并让内源刺激把状态池叠加图景重新采样为新种子。CS 动作数只作为显式开启时的兼容背景，不再是默认主链验收项。','bar_grouped',['structure_round_count','stimulus_round_count','cs_action_count']),
  chartConfig('structure_v2_match','internal','结构级 V2 匹配质量','综合分、基础分、数值匹配、时间因子与顺序对齐','用于观察结构级候选组的软匹配质量，避免只看组命中数量而忽略命中是否合理。','line',['structure_match_v2_score_mean','structure_match_v2_base_score_mean','structure_match_v2_numeric_score_mean','structure_match_v2_numeric_time_like_score_mean','structure_match_v2_order_alignment_mean']),
  chartConfig('structure_v2_support','internal','结构级 V2 支撑与混合效果','可参与比例、属性锚点、上下文支撑、能量图景、结构包含度、阈值余量与混合增益','用于判断结构级 blended 排序偏移到底来自上下文/属性支撑，还是来自新的 V2 曲线与阈值余量。','line',['structure_match_v2_eligible_ratio','structure_match_v2_attribute_anchor_mean','structure_match_v2_context_support_mean','structure_match_v2_energy_profile_mean','structure_match_v2_structure_inclusion_mean','structure_match_v2_threshold_margin_mean','structure_match_v2_blend_gain_mean']),
  chartConfig('v2_soft_partial_competition','internal','软部分匹配竞争','刺激级/结构级软部分候选与入竞数量','用于审计“尽可能匹配”是否真的进入主竞争链，而不是仍被完全包含门槛硬挡在外面。','bar_grouped',['stimulus_match_v2_soft_partial_eligible_count','stimulus_match_v2_soft_partial_selected_count','structure_match_v2_soft_partial_eligible_count','structure_match_v2_soft_partial_selected_count']),
  chartConfig('v2_bundle_exact_retention','internal','精确 bundle 保真','刺激级/结构级精确 bundle 与完全匹配入竞数量','用于同时观察软竞争已经放开以后，系统是否仍保留足够的身份保真，而不是把所有候选都糊成一片。','bar_grouped',['stimulus_match_v2_bundle_exact_selected_count','stimulus_match_v2_exact_match_selected_count','structure_match_v2_bundle_exact_selected_count','structure_match_v2_exact_match_selected_count']),
  chartConfig('structure_v2_path','internal','结构级路径分流','synthetic 单组、implicit_single_st 与真实候选竞争轮次','用于直接区分“结构级没跑”“结构级只走 synthetic 单组快捷路径”和“结构级真的进入 group 竞争”。','bar_grouped',['structure_round_count','structure_round_synthetic_count','structure_round_implicit_single_count','structure_round_competitive_count']),

  chartConfig('stitching_flow','stitching','认知拼接流程','种子、候选、动作、上下文拼接与强化','仅用于 residual/CS 回滚或 A/B 对照；默认 growth + CS disabled 时，这张图全 0 是预期背景，不应解读成感应生长缺失。','bar_grouped',['cs_seed_event_count','cs_seed_structure_count','cs_candidate_count','cs_action_count','cs_concat_count','cs_reinforced_count'], { diagnostic: true }),
  chartConfig('stitching_output','stitching','认知拼接产出','动作、上下文拼接、强化、刺激级新建结构、新建、扩展与合并','仅用于旧 residual/CS 路径排查。新版主链的新结构形成优先看感应生长身份命中/创建和刺激级查存一体，不再把 CS 产出当默认主指标。','bar_grouped',['cs_action_count','cs_concat_count','cs_reinforced_count','stimulus_new_structure_count','cs_created_count','cs_extended_count','cs_merged_count'], { diagnostic: true }),
  chartConfig('stitching_grasp_flow','stitching','认知拼接把握链路','焦点种子、入选事件与真正发射次数','旧 CS 叙事事件链路诊断。默认新版叙事应优先看状态池 Top、感应生长 A+B 与内源刺激重采样，不要求每 tick 都有 CS 把握事件。','bar_grouped',['cs_event_grasp_cam_seed_count','cs_event_grasp_post_action_seed_count','cs_event_grasp_selected_event_count','cs_event_grasp_emitted_count'], { diagnostic: true }),
  chartConfig('stitching_grasp_sources','stitching','认知拼接把握来源','CAM 入选与后拼接入选的来源拆分','旧 CS 把握来源诊断，只在显式启用 CS 时用于区分 CAM 旧事件与本 tick 拼接事件。','bar_grouped',['cs_event_grasp_cam_selected_event_count','cs_event_grasp_post_action_selected_event_count','cs_event_grasp_focus_candidate_item_count'], { diagnostic: true }),
  chartConfig('stitching_narrative','stitching','认知拼接叙事成熟度','主叙事总能量、主叙事把握感、普通拼接叙事数与叙事区最大把握感','旧 CS 叙事成熟度诊断。默认 growth 主链下，应把它作为回滚参考，而不是把 0 值视为叙事失败。','line',['cs_narrative_top_total_energy','cs_narrative_top_grasp','cs_concat_narrative_count','cs_narrative_grasp_max'], { diagnostic: true }),
  chartConfig('stitching_v2_match','stitching','认知拼接 V2 匹配质量','综合分数、上下文覆盖、顺序对齐、尾端匹配与匹配数量','用于在 legacy 仍执行时，并排审计 V2 口径认为“这批候选到底匹不匹配”，并观察长上下文是否真的更容易胜出。','line',['cs_candidate_v2_score_mean','cs_candidate_v2_context_cover_mean','cs_candidate_v2_order_alignment_mean','cs_candidate_v2_tail_match_mean','cs_candidate_v2_match_count_mean'], { diagnostic: true }),
  chartConfig('stitching_v2_support','stitching','认知拼接 V2 支撑与余量','基础分数、上下文库支撑、能量图景相似度、属性加分与阈值余量','用于判断 V2 分数偏低，到底是边支撑弱、能量图景不合、属性上下文没接上，还是整体离阈值太近。','line',['cs_candidate_v2_base_score_mean','cs_candidate_v2_context_db_support_mean','cs_candidate_v2_energy_profile_mean','cs_candidate_v2_attribute_bonus_mean','cs_candidate_v2_threshold_margin_mean'], { diagnostic: true }),
  chartConfig('cfs_peak','cfs','认知感受峰值','关注本轮最强的主观感受峰值','峰值适合看“有没有触发”，不适合代替总量。','line',['cfs_dissonance_max','cfs_pressure_max','cfs_grasp_max','cfs_complexity_max','cfs_simplicity_max','cfs_relief_max','cfs_reassurance_max','cfs_surprise_max','cfs_correct_event_max','cfs_repetition_max']),
  chartConfig('cfs_live','cfs','认知感受运行态总量','关注感受在运行态中的维持强度','用于判断感受是否只是一闪而过，还是持续维持。','line',['cfs_dissonance_live_total_energy','cfs_correctness_live_total_energy','cfs_correct_event_live_total_energy','cfs_expectation_live_total_energy','cfs_pressure_live_total_energy','cfs_grasp_live_total_energy','cfs_complexity_live_total_energy','cfs_simplicity_live_total_energy','cfs_relief_live_total_energy','cfs_reassurance_live_total_energy','cfs_repetition_live_total_energy']),
  chartConfig('cfs_count','cfs','认知感受即时触发频次','只看本 tick 新产生的感受信号','适合发现某条感受通道有没有新触发，但不代表持续态是否还在衰减维持。','bar_grouped',['cfs_signal_count','cfs_dissonance_count','cfs_surprise_count','cfs_repetition_count','cfs_expectation_count','cfs_pressure_count','cfs_simplicity_count','cfs_relief_count','cfs_reassurance_count']),
  chartConfig('cfs_global_balance','cfs','全局认知感受平衡','复杂度、简感与重复感的持续态对照','用于观察系统当前更偏紧张复杂、轻松简化，还是陷入重复疲劳。','line',['cfs_complexity_live_total_energy','cfs_simplicity_live_total_energy','cfs_repetition_live_total_energy']),
  chartConfig('cfs_global_count','cfs','全局认知感受即时触发','只看复杂度、简感与重复感在本 tick 是否新增触发','适合配合全局认知感受持续态一起看，区分“新触发”与“旧状态仍在维持”。','bar_grouped',['cfs_complexity_count','cfs_simplicity_count','cfs_repetition_count']),
  chartConfig('cfs_positive_guidance','cfs','正向认知感受持续态','正确事件、把握感、简感以及恢复/安抚感受的维持强度','用于观察系统是否不仅能报错和警觉，也能维持正向判断与恢复后的安定感。','line',['cfs_correct_event_live_total_energy','cfs_grasp_live_total_energy','cfs_simplicity_live_total_energy','cfs_relief_live_total_energy','cfs_reassurance_live_total_energy']),
  chartConfig('cfs_positive_count','cfs','正向认知感受即时触发','正确事件、把握感、简感以及恢复/安抚感受的当 tick 触发频次','用于配合正向持续态图，判断“正向感受是新近产生还是只是余波未退”。','bar_grouped',['cfs_correct_event_count','cfs_grasp_count','cfs_simplicity_count','cfs_relief_count','cfs_reassurance_count']),
  chartConfig('cfs_pressure_semantics','cfs','压力即时触发 vs 持续态','区分“本 tick 新触发”与“旧压力仍在持续”','若 `压力即时触发次数=0` 但 `压力运行态激活标记=1`，说明不是没压力，而是没有新增触发，旧压力仍在衰减维持。','bar_grouped',['cfs_pressure_count','cfs_pressure_live_active','cfs_pressure_decay_only','cfs_pressure_live_attribute_count','cfs_pressure_live_total_energy']),
  chartConfig('cfs_next_tick_projection','cfs','CFS next-tick 显影链路','运行态压力/期待族与内源投影的分段对照','用于排查 CFS 是“已经维持但没投影到内源”，还是“根本没有运行态维持”。','bar_grouped',['cfs_pressure_family_live_attribute_count','internal_cfs_pressure_family_attribute_count','cfs_expectation_family_live_attribute_count','internal_cfs_expectation_family_attribute_count']),
  chartConfig('cfs_verification_count','cfs','期待/压力验证频次','已证实/未证实期待与压力的当 tick 触发频次','用于直接观察教师奖惩和运行态奖惩进入 CFS 后，更常落成被追认的期待/压力，还是只是未被现实追认的预期/威胁。','bar_grouped',['cfs_expectation_verified_count','cfs_expectation_unverified_count','cfs_pressure_verified_count','cfs_pressure_unverified_count']),
  chartConfig('cfs_expectation_verification_mix','cfs','期待验证分叉','已证实/未证实期待与期待族总量','用于直接判断期待通道更偏向被现实追认，还是主要停留在未证实预期。','line',['cfs_expectation_verified_live_total_energy','cfs_expectation_unverified_live_total_energy','cfs_expectation_family_live_total_energy']),
  chartConfig('cfs_pressure_verification_mix','cfs','压力验证分叉','已证实/未证实压力与压力族总量','用于直接判断压力通道更偏向被现实验证，还是主要停留在未证实威胁。','line',['cfs_pressure_verified_live_total_energy','cfs_pressure_unverified_live_total_energy','cfs_pressure_family_live_total_energy']),
  chartConfig('reward_system','reward','系统奖惩','系统自身的奖励与惩罚信号构成','用于观察单个 tick 内部奖励与惩罚是如何共同组成的。','bar_stacked',['rwd_pun_rwd','rwd_pun_pun']),
  chartConfig('reward_teacher','reward','教师监督与期望契约','教师信号、监督标签与绑定次数','用于核对监督链路有没有真正打到运行中。','bar_grouped',['teacher_rwd','teacher_pun','teacher_applied_count','teacher_total_binding_applied_count','label_teacher_rwd','label_teacher_pun','label_should_call_weather']),
  chartConfig('reward_runtime_projection','reward','运行态奖惩显影链路','教师应用、上下文镜像绑定、运行态绑定与内源投影的逐段视图','用于直接判断奖励/惩罚类 runtime 属性卡在主绑定、上下文承载、运行态保持还是内源展开。','bar_grouped',['teacher_applied_count','teacher_context_binding_applied_count','teacher_reward_signal_live_attribute_count','teacher_punish_signal_live_attribute_count','internal_teacher_reward_signal_attribute_count','internal_teacher_punish_signal_attribute_count','reward_signal_live_attribute_count','punish_signal_live_attribute_count']),
  chartConfig('teacher_feedback_focus','reward','教师反馈下一拍聚焦','教师标签、主目标原子化、上下文镜像绑定、focus 指令与运行态教师信号','用于判断教师反馈是否不仅绑定成功，还真的沿着合适的上下文载体创造了再进 CAM 的机会。','line',['teacher_rwd','teacher_pun','teacher_primary_target_atomic','teacher_context_binding_candidate_count','teacher_context_binding_applied_count','teacher_focus_directive_count','teacher_focus_context_carrier_count','teacher_focus_directive_total_strength','teacher_focus_directive_max_focus_boost','teacher_reward_signal_live_total_energy','teacher_punish_signal_live_total_energy']),
  chartConfig('teacher_local_alias_bridge','reward','教师局部塑形别名桥','教师反馈短期别名缓存的活跃、匹配、注入与天气局部奖惩','用于确认教师侧信号是否被桥接到下一次同类输入的 action target，而不是只停留在教师绑定或全局奖惩层。','line',['teacher_local_alias_active_count','teacher_local_alias_available_count','teacher_local_alias_matched_count','teacher_local_alias_overlay_applied_count','teacher_local_alias_overlay_rwd','teacher_local_alias_overlay_pun','teacher_local_alias_overlay_match_score','action_local_reward_signal_total_weather_stub','action_local_punish_signal_total_weather_stub','action_local_reward_drive_bonus_total_weather_stub','action_local_punish_drive_penalty_total_weather_stub']),
  chartConfig('neuro_stress','neuro','应激与稳定递质','应激、稳定与恢复相关递质','用于观察系统是否长期过度紧绷或持续低活性。','line',['nt_COR','nt_ADR','nt_SER','nt_END']),
  chartConfig('neuro_reward','neuro','奖励与趋近递质','趋近、社会联结与奖赏倾向','用于观察奖励驱动是否与任务阶段一致。','line',['nt_DA','nt_OXY','nt_END']),
  chartConfig('neuro_explore_focus','neuro','探索与专注递质','新颖探索、专注锁定与其收放平衡','用于观察系统当前更偏探索扩散，还是更偏聚焦收窄。','line',['nt_NOV','nt_FOC','nt_DA','nt_COR']),
  chartConfig('neuro_iesm_update_summary','neuro','IESM 递质脚本调制概览','规则层本 tick 直接下发的递质调制规模','用于确认 NT 调制是否仍完全埋在 EMgr 内部，还是已经开始由先天脚本层显式参与。','bar_grouped',['iesm_emotion_update_key_count','iesm_emotion_update_abs_total']),
  chartConfig('neuro_iesm_update_channels','neuro','IESM 递质脚本分通道调制','规则层对 8 通道的逐通道增减','用于调试和验收 emotion_update 规则到底改了哪些递质，而不是只看最终 NT 状态被动变化。','line',['iesm_emotion_update_DA','iesm_emotion_update_ADR','iesm_emotion_update_OXY','iesm_emotion_update_SER','iesm_emotion_update_END','iesm_emotion_update_COR','iesm_emotion_update_NOV','iesm_emotion_update_FOC']),
  chartConfig('neuro_attention_mod','neuro','NT 对注意力的实时调制','容量、最小保留、聚焦增益、能量门槛与能量预算','用于直接观察 NT 通道如何改变本轮注意力的选取风格，以及调制后的注意力能量预算是否真的落到净增量上。','line',['attention_cam_item_cap','attention_mod_min_cam_items','attention_mod_focus_boost_weight','attention_mod_min_total_energy','attention_mod_attention_energy_budget','attention_energy_budget','attention_net_delta_energy']),
  chartConfig('neuro_attention_energy_budget','neuro','注意力能量预算调制','预算基线、NT/行动调制值、最终预算与滤波开关','用于单独审计“注意力资源”这条能量预算链路：当前基线目标约 8，NT/行动会在边界内造成更大波动，最终净增仍应受预算约束。','line',[{ key:'attention_energy_budget_base', preserveFlatLine:true },'attention_mod_attention_energy_budget','attention_energy_budget',{ key:'attention_energy_budget_min', preserveFlatLine:true },{ key:'attention_energy_budget_max', preserveFlatLine:true },{ key:'attention_energy_filter_applied', preserveFlatLine:true }]),
  chartConfig('neuro_attention_priority','neuro','NT 对注意力排序的权重调制','总能量、认知压、显著性、疲劳与近因偏置','用于观察当前 NT 口径下，注意力更偏向能量、压力、突发性还是近因新鲜度。','line',['attention_mod_priority_weight_total_energy','attention_mod_priority_weight_cp_abs','attention_mod_priority_weight_salience','attention_mod_priority_weight_fatigue','attention_mod_priority_weight_recency_gain']),
  chartConfig('neuro_hdb_mod','neuro','NT 对学习传播的调制','现实学习增益、虚循环磨损、传播阈值、传播比例与 ER 诱发比例','用于直接观察 NT 通道如何改变 HDB 的学习与传播风格。','line',['emotion_hdb_base_weight_er_gain_scale','emotion_hdb_base_weight_ev_wear_scale','emotion_hdb_ev_propagation_threshold_scale','emotion_hdb_ev_propagation_ratio_scale','emotion_hdb_er_induction_ratio_scale']),
  chartConfig('action_result','action','行动执行结果','单个 tick 内执行结果的组成','适合观察 weather_stub、回忆、注意聚焦链路是否真的跑通。','bar_stacked',['action_executed_attention_focus','action_executed_recall','action_executed_weather_stub','action_executed_count']),
  chartConfig('action_schedule','action','行动尝试与调度','执行前的尝试与调度活动','用于区分“没有想做”还是“想做但没执行成功”。','bar_grouped',['action_attempted_count','action_scheduled_weather_stub']),
  chartConfig('action_iesm_front','action','IESM 前端触发','规则命中、脚本命中与行动触发数','用于判断问题在先天规则前段，还是在行动器后段落地。','bar_grouped',['iesm_triggered_rule_count','iesm_triggered_script_count','iesm_action_trigger_count']),
  chartConfig('action_attention_mode_bridge','action','复杂度到注意力模式桥','复杂度/简感触发与 focus/diverge 尝试、执行','用于直接验收 `cfs_complexity / cfs_simplicity -> attention_focus_mode / attention_diverge_mode` 是否已经贯通，而不是只停留在 CFS 层。','bar_grouped',['cfs_complexity_count','cfs_simplicity_count','action_attempted_focus_mode','action_executed_focus_mode','action_attempted_diverge_mode','action_executed_diverge_mode']),
  chartConfig('action_weather_chain','action','天气行动全链路','天气规则触发、尝试、调度与执行','用于直接区分“规则已经触发”与“行动器真正执行”。','bar_grouped',['iesm_action_trigger_weather_stub_count','action_attempted_weather_stub','action_scheduled_weather_stub','action_executed_weather_stub']),
  chartConfig('action_weather_rule_split','action','天气规则三档分流','弱提及、隐式问句、强查询与执行落点','用于判断当前样本只是顺手提天气，还是已经形成隐式/显式天气求助。','bar_grouped',['iesm_triggered_rule_innate_action_weather_stub_from_weather_only_count','iesm_triggered_rule_innate_action_weather_stub_from_weather_question_count','iesm_triggered_rule_innate_action_weather_stub_from_query_weather_count','action_executed_weather_stub_source_visible','action_executed_weather_stub_synthetic_only']),
  chartConfig('action_weather_drive','action','天气驱动力与阈值','天气节点驱动力、阈值与最大裕量','用于直接判断天气行动是根本没被唤醒，还是被阈值卡住。','line',['action_drive_weather_stub_max','action_effective_threshold_weather_stub_mean','action_drive_margin_weather_stub_max']),
  chartConfig('action_threshold_components','action','行动阈值调制构成','基础阈值、实时阈值、NT/奖惩/疲劳缩放','用于直接审计行动阈值究竟被哪一层调高或调低，避免把“不行动”误判成单纯 drive 不足。','line',['action_base_threshold_mean','action_effective_threshold_mean','action_threshold_nt_scale_mean','action_threshold_rwd_pun_scale_mean','action_threshold_fatigue_scale_mean']),
  chartConfig('action_reward_learning','action','奖惩对行动的全局影响','系统奖惩、阈值偏移、奖励增益与惩罚代价','用于核对 reward 是否真的在降阈值、punish 是否真的在升阈值，而不是只存在于情绪或状态池里。','line',['rwd_pun_rwd','rwd_pun_pun','action_learning_threshold_delta_mean','action_learning_reward_drive_gain_total','action_learning_punish_drive_penalty_total']),
  chartConfig('action_local_drive_learning','action','局部奖惩对drive塑形','局部目标覆盖、命中、drive缩放与奖惩增减','用于判断对象级 reward/punish 是否真的改变了对应行动节点本轮获得的 drive，而不是只有全局阈值在动。','line',['action_local_targeted_node_count','action_local_lookup_hit_count','action_local_drive_modulated_node_count','action_local_drive_scale_mean','action_local_reward_drive_bonus_total','action_local_punish_drive_penalty_total']),
  chartConfig('action_local_lookup_detail','action','局部奖惩查找明细','局部命中、文本回落命中、真实 miss、skipped、缺目标与关闭节点','用于区分“直查命中”“文本桥接命中”“查了但没找到”“压根不该查/不能查”和“节点主动关闭局部塑形”，避免误读局部奖惩链路。','bar_grouped',['action_local_targeted_node_count','action_local_lookup_hit_count','action_local_lookup_text_fallback_hit_count','action_local_lookup_miss_count','action_local_lookup_skipped_count','action_local_target_missing_count','action_local_modulation_disabled_count']),
  chartConfig('action_local_exec_split','action','局部奖惩执行分化','局部命中、drive 缩放、尝试与执行的并排走势','用于直接观察“局部奖惩命中以后，行动尝试/执行有没有真的分化”，避免只看 scale 却看不到行为后果。','line',['action_local_lookup_hit_count','action_local_drive_scale_mean','action_attempted_count','action_executed_count']),
  chartConfig('action_weather_trigger_target_status','action','天气触发目标绑定状态','weather_stub 的总触发、带目标触发与缺目标触发','用于直接判断天气行动局部奖惩失效究竟是因为 IESM 没给目标，还是给了目标但后续 lookup 仍没命中。','bar_grouped',['iesm_action_trigger_weather_stub_count','iesm_action_trigger_targeted_weather_stub_count','iesm_action_trigger_target_missing_weather_stub_count']),
  chartConfig('action_weather_local_lookup_detail','action','天气局部奖惩查找明细','只看 weather_stub 的命中、文本回落命中、miss、skipped、缺目标与关闭原因','用于判断天气行动没有被塑形时，究竟卡在 target 缺失、直查 miss，还是已经通过文本桥接命中。','bar_grouped',['action_local_targeted_node_count_weather_stub','action_local_lookup_hit_count_weather_stub','action_local_lookup_text_fallback_hit_count_weather_stub','action_local_lookup_miss_count_weather_stub','action_local_lookup_skipped_count_weather_stub','action_local_target_missing_count_weather_stub','action_local_modulation_disabled_count_weather_stub']),
  chartConfig('action_weather_local_exec_split','action','天气局部塑形 vs 执行','weather_stub 的局部命中、scale 与尝试/执行并排','用于直接判断天气局部塑形是否真的传导到了 weather_stub 的尝试与执行，而不是被总体动作指标淹没。','line',['action_local_lookup_hit_count_weather_stub','action_local_drive_scale_mean_weather_stub','action_attempted_weather_stub','action_executed_weather_stub']),
  chartConfig('action_teacher_cfs_bridge','action','教师奖惩到行动塑形桥','教师应用、奖惩 live、期待/压力验证与天气局部 drive 的并排链路','用于把 `teacher -> reward/punish live -> expectation/pressure -> weather 局部塑形` 放到一张图里，直接验收新口径联动。','line',['teacher_applied_count','reward_signal_live_total_energy','punish_signal_live_total_energy','cfs_expectation_verified_count','cfs_pressure_verified_count','action_local_reward_drive_bonus_total_weather_stub','action_local_punish_drive_penalty_total_weather_stub','action_executed_weather_stub']),
  chartConfig('action_weather_nodes','action','天气节点活化状态','天气节点总数、活跃数与就绪数','用于区分“节点没生成”“节点已活化”“节点已过阈值但没执行”。','bar_grouped',['action_node_weather_stub_count','action_active_weather_stub_count','action_ready_weather_stub_count']),
  chartConfig('action_contract_visibility','action','契约可见执行口径','拆开 source tick 可见执行与 synthetic feedback tick 上的执行','用于避免把反馈 tick 上的执行错读成契约窗口内已经满足的执行。','bar_grouped',['action_executed_weather_stub','action_executed_weather_stub_source_visible','action_executed_weather_stub_synthetic_only','action_executed_count_source_visible','action_executed_count_synthetic_only']),
  chartConfig('action_drive','action','行动驱动力','行动系统的最大与平均驱动力','驱动力是连续值，应与节点规模分开观察。','line',['action_drive_max','action_drive_mean']),
  chartConfig('action_nodes','action','行动节点规模','行动节点总数与活跃行动节点数','用于判断行动网络是否在增长或僵死。','bar_grouped',['action_node_count','action_drive_active_count']),
  chartConfig('time_binding','time','时间绑定活动','时间桶与时间属性的绑定活动','用于判断时间感受器是否在正常生成绑定，以及绑定是否仍然只停留在旧的原子峰值对象。','bar_grouped',['time_sensor_bucket_update_count','time_sensor_attribute_binding_count','time_sensor_projection_binding_count','time_sensor_legacy_binding_count','time_sensor_memory_sample_count']),
  chartConfig('time_delayed','time','延迟任务活动','延迟任务的注册、更新、执行与清理','用于观察延迟反馈、期望契约与时间任务的活动负载。','bar_grouped',['time_sensor_delayed_task_registered_count','time_sensor_delayed_task_updated_count','time_sensor_delayed_task_executed_count','time_sensor_delayed_task_pruned_count','time_sensor_delayed_task_capacity_skip_count','time_sensor_delayed_task_table_size']),
  chartConfig('map_scale','map','记忆赋能规模','赋能、反馈与应用次数','旧 MAP/记忆池兼容诊断。默认 growth 主链下，记忆终端更应结合 induction_growth_memory_terminal_passthrough_count 与运行态记忆投影理解。','bar_grouped',['map_count','map_feedback_count','map_apply_count'], { diagnostic: true }),
  chartConfig('map_runtime_projection','map','残差主链 / MAP兼容显影','MAP 兼容应用、运行态投影、兼容回流与结构直投','用于确认 legacy MAP 兼容支路是否仍在运行。新版默认主链下，它不是感应生长的主验收项；若需要看记忆终端旁路，应配合感应生长保护图。','bar_grouped',['map_apply_count','memory_runtime_projection_count','memory_feedback_applied_count','memory_feedback_structure_projection_count'], { diagnostic: true }),
  chartConfig('map_feedback_split','map','MAP兼容反馈分流次数','兼容回流总落地、整包回放与结构直投','旧 MAP 反馈兼容诊断，用于回滚或对照旧记忆反馈支路，不代表新版完整身份生长的默认路径。','bar_grouped',['memory_feedback_applied_count','memory_feedback_packet_count','memory_feedback_structure_projection_count'], { diagnostic: true }),
  chartConfig('map_energy','map','记忆赋能能量','MAP 与反馈链路的能量变化','旧 MAP 能量诊断。默认主口径请优先看感应生长 source-side ER 与 residual-side EV 的组件审计。','line',['map_total_er','map_total_ev','map_feedback_total_ev'], { diagnostic: true }),
  chartConfig('map_feedback_energy_split','map','记忆反馈能量分流','反馈总 EV、整包回放 EV 与结构直投 EV','旧记忆反馈预算诊断；在新版默认下主要用于解释兼容支路是否仍产生额外运行态投影。','line',['memory_feedback_total_ev','memory_feedback_packet_total_ev','memory_feedback_structure_projection_total_ev'], { diagnostic: true }),
  chartConfig('map_feedback_projection_quality','map','结构直投有效性','尝试次数、有效次数、被裁掉次数与有效率','旧 MAP 结构直投诊断，用于确认兼容反馈是否被疲劳/阈值裁掉；默认生长路径请优先看 induction_growth_*。','line',['memory_feedback_structure_projection_attempted_count','memory_feedback_structure_projection_count','memory_feedback_structure_projection_skipped_count','memory_feedback_structure_projection_effective_ratio'], { diagnostic: true }),
  chartConfig('cache_neutralization_cut_cache','performance','缓存中和切割缓存','优先中和阶段的共同切割快路径、缓存命中与零拷贝','用于判断新刺激进入状态池前的优先中和是否被重复 common-part/normalize 计算拖慢。cache_priority_cut_* 只统计中和阶段的 CutEngine，不改变 SA 粒度能量结算；缓存命中、零拷贝和 normalized group 复用越高，通常说明重复比较被吸收。若完整 common-part 缓存命中长期接近 0 且中和耗时升高，可回滚 priority_neutralization_common_part_cache_enabled。','bar_grouped',['cache_priority_cut_exact_fast_path_hit_count','cache_priority_cut_full_inclusion_fast_path_hit_count','cache_priority_cut_single_group_fast_path_hit_count','cache_priority_cut_ordered_subsequence_fast_path_hit_count','cache_priority_cut_cache_hit_count','cache_priority_cut_cache_zero_copy_hit_count','cache_priority_cut_cache_store_count','cache_priority_cut_cache_deepcopy_count','cache_priority_cut_normalize_cache_hit_count','cache_priority_cut_normalize_reusable_hit_count','cache_priority_cut_normalize_reusable_group_count','cache_priority_cut_signature_fast_path_hit_count','cache_priority_cut_empty_group_fast_path_hit_count','cache_priority_cut_reindex_fast_path_hit_count','timing_cache_neutralization_ms']),
  chartConfig('runtime_residual_promotion','performance','运行态残余包晋升','精确重绑定、完整身份晋升、旧查存回退与晋升结果','用于观察剩余刺激残余包在被注意力或高能路径选中后，是直接命中已有 context-free 完整结构并重绑定，还是按残余包自己的完整特征解析/创建 HDB-backed ST，或最后回退到旧完整刺激级查存一体。完整身份晋升是新版主口径，避免长残余包被旧 fallback 局部命中成单 SA 或短结构。','bar_grouped',['runtime_residual_promotion_attempted_count','runtime_residual_promotion_promoted_count','runtime_residual_promotion_exact_rebind_count','runtime_residual_promotion_full_identity_count','runtime_residual_promotion_hdb_fallback_count','runtime_residual_promotion_created_count','runtime_residual_promotion_matched_count']),
  chartConfig('timing_main','performance','主性能耗时','最主要的四个耗时大头','适合先看哪条链路在拖慢整体 Tick。','line',['timing_total_logic_ms','timing_structure_level_ms','timing_stimulus_level_ms','timing_cache_neutralization_ms']),
  chartConfig('timing_detail','performance','细分性能耗时','其余主要模块耗时','适合进一步判断是归纳、注意力、IESM 还是情绪链路偏慢。','line',['timing_induction_and_memory_ms','timing_attention_ms','timing_cognitive_stitching_ms','timing_iesm_ms','timing_action_ms','timing_emotion_ms','timing_cfs_ms','timing_time_sensor_ms']),
  chartConfig('diag_pool_apply','diagnostic','状态池落地应用','新增、更新、合并与能量增量','用于检查刺激包落地到状态池时，增量结构是否合理。','bar_grouped',['pool_apply_merged_item_count','pool_apply_new_item_count','pool_apply_updated_item_count','pool_apply_total_delta_cp','pool_apply_total_delta_er','pool_apply_total_delta_ev']),
  chartConfig('diag_attention','diagnostic','注意力诊断','候选量、容量预算、能量预算、跳过量与消耗能量','用于分析注意力为什么没有选中更多记忆，或为什么耗能异常；同时把数量上限和能量资源分开看，避免把 CAM 容量误读成能量预算。','bar_grouped',['attention_state_pool_candidate_count','attention_cam_item_cap','attention_skipped_memory_item_count','attention_consumed_total_energy','attention_energy_budget','attention_net_delta_energy','attention_gross_gain_energy_applied']),
  chartConfig('diag_maintenance','diagnostic','维护阶段诊断','维护前后状态与维护事件数','用于检查维护模块是否在实际清理，而不是形同虚设。','bar_grouped',['maintenance_before_active_item_count','maintenance_after_active_item_count','maintenance_delta_active_item_count','maintenance_before_high_cp_item_count','maintenance_after_high_cp_item_count','maintenance_delta_high_cp_item_count','maintenance_event_count']),
  chartConfig('diag_map_detail','diagnostic','记忆赋能补充诊断','MAP 条目、反馈与能量细项','用于进一步查看 MAP 的应用次数、反馈次数与能量变化。','bar_grouped',['map_count','map_feedback_count','map_apply_count','map_total_er','map_total_ev','map_feedback_total_ev']),
  chartConfig('diag_cfs_coverage','diagnostic','认知感受覆盖诊断','认知感受覆盖对象数与属性条目数','用于判断某种感受是没触发，还是触发了但绑定覆盖太窄。','bar_grouped',['cfs_dissonance_live_item_count','cfs_dissonance_live_attribute_count','cfs_correctness_live_item_count','cfs_correctness_live_attribute_count','cfs_expectation_live_item_count','cfs_expectation_live_attribute_count','cfs_pressure_live_item_count','cfs_pressure_live_attribute_count']),
  chartConfig('diag_cfs_global_coverage','diagnostic','全局/正向感受覆盖诊断','复杂度、简感、重复感、正确事件与把握感的覆盖对象数和属性条目数','用于快速看出全局或偏正向感受是根本没落地，还是已经写进状态池但能量偏弱。','bar_grouped',['cfs_complexity_live_item_count','cfs_complexity_live_attribute_count','cfs_simplicity_live_item_count','cfs_simplicity_live_attribute_count','cfs_repetition_live_item_count','cfs_repetition_live_attribute_count','cfs_correct_event_live_item_count','cfs_correct_event_live_attribute_count','cfs_grasp_live_item_count','cfs_grasp_live_attribute_count']),
  chartConfig('diag_echo_and_input','diagnostic','输入与残响诊断','原始输入长度、残响池与情节节奏','用于判断输入分段、残响池与情节节奏是否异常。','line',['input_len','sensor_echo_current_round','sensor_echo_pool_size','tick_in_episode_index','episode_repeat_index']),
  chartConfig('diag_cs_detail','diagnostic','认知拼接诊断','候选、上下文拼接、新建、扩展、合并与强化','用于查看认知拼接到底是没候选，还是候选很多但主要落在 context-match V2 的普通结构拼接上。','bar_grouped',['cs_candidate_count','cs_concat_count','cs_created_count','cs_extended_count','cs_merged_count','cs_reinforced_count','cs_seed_event_count','cs_seed_structure_count']),
];

function sortedNumericMetricKeys(rows) {
  const keys = new Set();
  asArray(rows).forEach((row)=> {
    Object.entries(row || {}).forEach(([k,v])=> {
      if (k.startsWith('__')) return;
      if (typeof v === 'number' && Number.isFinite(v)) keys.add(k);
    });
  });
  return Array.from(keys).sort();
}

function getChartMetricKeys(cfg) { return asArray(cfg?.series).map((s)=> String(s?.key || '')).filter(Boolean); }
function buildDiagnosticChartConfigs(rows) {
  const existing = new Set(CHART_CONFIGS.flatMap((cfg)=> getChartMetricKeys(cfg)));
  const leftovers = sortedNumericMetricKeys(rows).filter((k)=> !existing.has(k) && !['tick_index','dataset_tick_index','source_dataset_tick_index','started_at_ms','finished_at_ms'].includes(k) && !isMeaninglessSeries(rows, k));
  const groups = [
    { id: 'diag_reward_tail', title: '奖惩补充诊断', subtitle: '主图未覆盖的奖惩与标签指标', description: '用于联调教师信号、奖惩标签与执行契约。', prefixes: ['rwd_pun_','teacher_','label_'], chartType: 'bar_grouped' },
    { id: 'diag_time_tail', title: '时间能量与延迟任务诊断', subtitle: '时间感受器的补充技术指标', description: '主要看时间桶能量、记忆抽样与延迟任务容量是否异常。', prefixes: ['time_sensor_'], chartType: 'bar_grouped' },
    { id: 'diag_cfs_tail', title: '认知感受细粒度诊断', subtitle: '主图未覆盖的认知感受细项', description: '用于查看复杂度、正确事件等更细粒度感受通道。', prefixes: ['cfs_'], chartType: 'bar_grouped' },
    { id: 'diag_action_tail', title: '行动细项诊断', subtitle: '动作尝试与执行的细分类', description: '用于看具体是哪一类动作在尝试、执行或被抑制。', prefixes: ['action_attempted_','action_executed_'], chartType: 'bar_grouped' },
    { id: 'diag_sensor_tail', title: '感受器补充诊断', subtitle: '主图未覆盖的感受器与输入指标', description: '用于查看感受器残余指标。', prefixes: ['sensor_','external_'], chartType: 'bar_grouped' },
    { id: 'diag_cache_tail', title: '缓存与输入诊断', subtitle: '输入长度与 flat token 相关补充项', description: '用于查看输入长度、flat token 规模与缓存残余指标。', prefixes: ['cache_','input_'], chartType: 'bar_grouped' },
    { id: 'diag_internal_tail', title: '内源分辨率补充诊断', subtitle: '预算、候选与丢弃细项', description: '用于进一步查看内源解析中哪些结构被保留、丢弃或压缩。', prefixes: ['internal_resolution_','internal_'], chartType: 'bar_grouped' },
    { id: 'diag_timing_tail', title: '细分耗时补充诊断', subtitle: '主图未覆盖的 timing 细项', description: '用于继续追查真正的性能耗时尾部。', prefixes: ['timing_'], chartType: 'line' },
    { id: 'diag_cs_tail', title: '认知拼接补充诊断', subtitle: '拼接运行态与叙事细项', description: '用于查看认知拼接是否只是启用，还是已经形成叙事输出。', prefixes: ['cs_'], chartType: 'bar_grouped' },
    { id: 'diag_misc_tail', title: '其余补充诊断', subtitle: '少量剩余技术指标', description: '只作为调试兜底，不建议直接据此调参。', prefixes: [], chartType: 'bar_grouped' },
  ];
  const out = [];
  let remaining = leftovers.slice();
  groups.forEach((group, groupIndex)=> {
    const matched = group.prefixes.length
      ? remaining.filter((k)=> group.prefixes.some((prefix)=> k.startsWith(prefix)) && !isMeaninglessSeries(rows, k)).slice(0, 10)
      : remaining.filter((k)=> !isMeaninglessSeries(rows, k)).slice(0, 10);
    if (!matched.length) return;
    remaining = remaining.filter((k)=> !matched.includes(k));
    out.push(chartConfig(group.id, 'diagnostic', group.title, group.subtitle, group.description, group.chartType, matched, { colorOffset: groupIndex * 2 }));
  });
  return out;
}

function normalizeMetricRows(rows) {
  const src = asArray(rows).slice().sort((a,b)=> asNumber(a?.tick_index, 0) - asNumber(b?.tick_index, 0));
  if (!src.length) return [];
  const numericKeys = sortedNumericMetricKeys(src);
  const byTick = new Map(src.map((row)=> [asNumber(row?.tick_index, 0), row]));
  const maxTick = Math.max(...src.map((row)=> asNumber(row?.tick_index, 0)));
  const lastValues = Object.create(null);
  const normalized = [];
  for (let tick = 0; tick <= maxTick; tick += 1) {
    const base = byTick.get(tick) || { tick_index: tick };
    const row = { ...base, __tick_label: 'tick ' + tick };
    numericKeys.forEach((key)=> {
      const raw = row[key];
      if (typeof raw === 'number' && Number.isFinite(raw)) lastValues[key] = raw;
      else if (Object.prototype.hasOwnProperty.call(lastValues, key)) row[key] = lastValues[key];
      else row[key] = 0;
    });
    normalized.push(row);
  }
  return normalized;
}

function renderChartFactors(cfg) {
  const keys = getChartMetricKeys(cfg);
  const rowsForFilter = asArray(STATE.lastMetricsRows);
  const visibleKeys = asArray(rowsForFilter.length ? getRenderableSeries(rowsForFilter, cfg?.series || []) : []).map((s)=> s.key);
  const missingExportKeys = rowsForFilter.length
    ? keys.filter((key)=> !rowsForFilter.some((row)=> row && Object.prototype.hasOwnProperty.call(row, key)))
    : [];
  const explainMap = {
    diag_time_tail: '这张图主要回答两个问题：时间桶里的能量是不是在异常堆积；延迟任务是不是因为容量或采样策略而失真。若时间桶能量长期过高，通常说明时间感受绑定或衰减不平衡。',
    diag_cfs_tail: '这张图不是看主通道峰值，而是看更细的感受通道是否真的被绑定并维持。若事件计数有了，但 live item / live attribute 长期为 0，说明绑定链路可能过严。',
    diag_action_tail: '这张图用于区分“想做但没做成”和“根本没想做”。如果 attempted 高而 executed 低，问题多半在驱动力阈值、竞争或执行条件。',
    diag_cache_tail: '这张图主要看输入进入缓存后，flat token 与中和残余是否异常膨胀或异常归零。若输入长度正常但 token 长期极端，优先回看分段与缓存中和策略。',
    diag_internal_tail: '这张图是内源解析的细账本。适合判断到底是 rich candidate 太少、selected 太少，还是 dropped 太多。',
    diag_timing_tail: '这张图用于继续追查主性能图没有单独展示的耗时尾部。看到某一项升高后，应回到对应模块主链路排查。',
    diag_cs_tail: '这张图用于看认知拼接是否真的从“启用”走到了“形成叙事或结构输出”。如果 enabled 一直是 1，但 narrative / created 长期接近 0，说明拼接阈值或候选质量存在问题。',
    diag_map_detail: '这张图用于判断 MAP 兼容支路是“没条目”“没反馈”，还是“有反馈但没真正转成稳定能量”。',
  };
  const factorMap = {
    overview_hdb: [
      { title: '真实影响因素：长期结构沉积速率', desc: '这张图由 HDB 新建、切割、合并、认知拼接持久化、情节记忆写入共同决定。放到运行总览里，是为了把长期沉积和当前活跃态放在同一视角下观察。' },
    ],
    runtime_resolution_state_pool: [
      { title: '真实影响因素：运行态分辨率下降', desc: '这张图对应新版退化口径：对象的部分组件能量低于阈值后，状态池只降低显示/解释分辨率，仍保留原完整结构/root id，不重新跑查存一体，也不把退化后的短内容写成新的 HDB 身份。' },
      { title: '如何读这张图', desc: '`active_component_count` 与 `dropped_component_count` 的比例表示当前完整结构还有多少组件可见；维护刷新/仍降分辨率对象数用于判断半衰期和软容量是否让对象退化过快。' },
    ],
    context_pool: [
      { title: '真实影响因素：完整身份聚合是否生效', desc: '`state_pool.config.state_pool_config.yaml` 中的 `enable_semantic_same_object_merge` 与 `aggregate_same_semantic_incoming_objects` 会影响相同完整特征是否汇聚。新版主链看完整身份收敛；多上下文字段只作为旧口径审计。' },
      { title: '如何读旧上下文占比', desc: '`状态池广义来源链占比` 包含 parent_ids / context_ref / context_path 等元信息，很多独立 SA 入池时也会带 parent_ids，因此长期等于 1 不一定异常。新版主链下，优先把它当激活审计，而不是对象身份。' },
      { title: '真实影响因素：运行态保活链', desc: '如果残差来源占比偏低，可能只是状态池衰减、软容量或中和让弱路径先掉光。判断新版 growth 是否生效时，应优先看 induction_growth_*、结构 Top 与 CS 是否关闭。' },
    ],
    context_hdb: [
      { title: '真实影响因素：旧上下文身份残留', desc: '新版 growth 主链下，A+B 的正式身份应由完整特征/root id 决定，owner/context 只作激活审计。若这些指标长期很高，优先排查 legacy residual/CS 或旧数据残留；若为 0，不应被自动判为主链失败。' },
      { title: '如何读这张图', desc: '这张图保留给回滚、迁移和旧 run 对照。判断当前叙事与完整身份是否健康，请优先回到感应生长、运行态分辨率、结构 Top 与内源重采样图。' },
    ],
    context_path: [
      { title: '真实影响因素：provenance 元信息是否仍在传递', desc: '这张图主要检查 `context_ref_object_id / context_owner_structure_id / context_path_ids` 这类旧上下文或来源链元信息。新版正式对象身份不依赖这些字段，显式路径深度贴地并不等价于感应生长失败。' },
    ],
    residual_linking: [
      { title: '真实影响因素：残差是否沿局部链保存', desc: '`hdb.config.hdb_config.yaml` 中的 `stimulus_residual_context_confidence` 会影响残差上下文被保留下来的强度；而 `internal_storage_projection_*` 相关参数会影响这些残差能否继续进入当前内源链。若“残差局部链接占比”低，优先查这条链，而不是只看总结构数。' },
    ],
    induction_energy: [
      { title: '真实影响因素：局部 EV 传播比例', desc: '`hdb.config.hdb_config.yaml` 与 `emotion.config.emotion_config.yaml` 中的 `ev_propagation_ratio` 决定已有虚能量沿局部残差链继续扩散的预算。该值主要抬高“局部传播虚能量总量”，而不是直接制造新的 ER 诱发 EV。' },
      { title: '真实影响因素：ER 诱发比例', desc: '`hdb.config.hdb_config.yaml` 与 `emotion.config.emotion_config.yaml` 中的 `er_induction_ratio` 决定现实证据能拿出多少预算去诱发新的预期对象。它主要对应“ER 诱发 EV 总量”，若这条线过低，说明现实证据难以转成预测扩散。' },
    ],
    induction_split: [
      { title: '真实影响因素：结构路径与记忆路径的分流比例', desc: '当前 induction 不是只把 EV 往状态池结构里投；相当一部分目标会被路由到记忆激活池。因此“结构直投不高”并不自动等于链路失效，必须先看 `结构目标计划 EV` 与 `记忆目标计划 EV` 的分流。' },
      { title: '如何读这张图', desc: '如果 memory path 明显更高，而结构直投线较低，这是正常的“先入记忆、后经反馈回池”的运行策略；只有当结构路径本身占比不低，却长期落地差时，才应怀疑结构投影阶段真的被挡住。' },
    ],
    induction_landing: [
      { title: '真实影响因素：结构目标里是否混入不可投影对象', desc: '这张图只看结构直投路径。如果“结构目标计划 EV”明显高于“结构直投实际落地虚能量”，且“结构直投被跳过虚能量”不低，才说明结构候选里混入了运行态不会接收的对象。当前最典型的就是 `cognitive_stitching_event_structure`。' },
      { title: '真实影响因素：induction 非可投影目标过滤开关', desc: '`hdb.config.hdb_config.yaml` 中的 `induction_filter_nonprojectable_targets` 会在感应赋能上游直接滤掉本来就进不了状态池的目标。正常实验建议保持开启，否则会看到账面 EV 虚高、实际入池 EV 偏低。' },
      { title: '如何读这张图', desc: '理想情况是“结构目标计划 EV”和“结构直投实际落地 EV”接近，且“结构直投被跳过 EV”接近 0；如果这里只是低，但上一张分流图显示 memory path 才是大头，那不应把它误判成总链路 blocked。' },
    ],
    induction_topology: [
      { title: '真实影响因素：本轮可作为源的结构对象数', desc: '`感应赋能源对象数` 首先受状态池中带结构指针的对象数量影响；如果源对象本身就少，后面无论是结构直投还是记忆路径都不会厚起来。' },
      { title: '真实影响因素：目标是更多走结构，还是更多走记忆', desc: '`总目标 / 结构目标 / 记忆目标` 可以直接回答本轮 induction 更偏“直接入池”还是“先强化记忆”。如果记忆目标长期占绝对大头，结构直投比值偏低并不意味着异常。' },
    ],
    induction_source_mix: [
      { title: '真实影响因素：默认口径是全池参与，不是先筛 ST', desc: '默认 `all_energetic_runtime` 模式下，整个状态池里所有带 ER/EV 的运行态对象都会进入感应赋能源集合；这张图更多是在拆这些已参与源对象里，ST 占多少、含 ER/EV 的源有多少，而不是说明“只有这些源才被允许参与”。' },
      { title: '真实影响因素：最大名额与扫描深度主要影响旧混合模式', desc: '`induction_source_max_items`、`induction_source_candidate_top_k` 在默认无限制模式下通常只是观测项；只有切回旧混合/限额模式，才会真正决定“每 tick 带多少源进来、往下扫多深”。如果你看到 cap hit 偏高，要先确认当前是不是还开着限额模式。' },
      { title: '真实影响因素：EV 配额与 cp 回退只在旧混合模式下有强解释力', desc: '`induction_source_ev_quota_ratio` 与 `认知压回退入选源数` 主要用于解释 `hybrid_er_ev` 这类旧混合选源；默认新口径下，更该看的是“有多少源对象本身带 ER/EV”，而不是把这两项当成常开门控。' },
    ],
    induction_source_quality: [
      { title: '真实影响因素：本地 diff_table 是否真的有货', desc: '`可用本地候选结构数` 与 `入选可传播源数` 反映的是这些 source 背后的结构数据库里，是否真的存在可走的局部目标。若源看起来很多，但“入选空候选源数”持续偏高，说明高能 source 里有相当一批实际上无法传播。' },
      { title: '真实影响因素：本地候选偏置模式', desc: '`induction_source_local_target_bias_mode=prefer_nonzero` 会优先把“真有本地候选”的 source 往前排，避免高 EV 但 `candidate_entries=0` 的结构白占名额。若你关掉这个偏置，通常会看到空候选源数回升。' },
      { title: '如何读这张图', desc: '如果“可用本地候选结构数”高，但“入选可传播源数”低，说明选源名额或扫描深度不足；如果两者都高，但 `感应赋能目标数` 仍低，则更像是局部边权或目标筛选阶段把传播压薄了。' },
    ],
    induction_raw_residual_hit: [
      { title: '真实影响因素：原始残差是否已经有现成结构可接', desc: '这张图直接回答一个关键问题：当前局部 residual/context 链里，有多少条目其实早就在 HDB 里有同签名结构。如果“命中已存结构条目数”不低，而过去结构路径却始终很弱，说明问题并不在“没有结构”，而在“没有把这条结构路径接上”。' },
      { title: '真实影响因素：原始残差转结构开关与目标上限', desc: '`hdb.config.hdb_config.yaml` 中的 `induction_raw_residual_existing_structure_projection_enabled` 控制这条双路径是否打开；`induction_raw_residual_structure_target_top_k` 控制每条原始残差最多把预算分给几个现成结构。若前两条线高、但“实际转结构条目数”低，优先查这里。' },
      { title: '如何读这张图', desc: '理想情况不是把所有原始残差都硬塞进结构路径，而是：当确实存在高质量同签名结构时，至少有一部分条目能稳定转过去。若“条目数高、命中高、转结构低”，通常是分流开关或比例太保守；若“条目数高、命中低”，则说明现阶段 residual 还主要停留在记忆材料层。' },
    ],
    induction_raw_residual_component_hit: [
      { title: '真实影响因素：全签名 miss 但组分仍可复用', desc: '这张图专门回答“是不是整体 residual 太新，导致完整签名根本命不中，但其中若干大组分其实早已存在”。如果这里有数据，而上一张 exact 命中图偏低，就说明问题不在局部链完全失效，而在完整签名过于稀疏。' },
      { title: '真实影响因素：组分回退开关与组分门槛', desc: '`induction_raw_residual_group_component_projection_enabled` 控制这条回退是否开启；`induction_raw_residual_component_min_group_units` 控制多小的组分才允许进入回退；`induction_raw_residual_component_target_top_k` 控制每条 residual 最多保留多少个组分结构目标。若“命中组分结构条目数”高、但“实际转组分结构条目数”低，优先查这三项。' },
      { title: '如何读这张图', desc: '它不表示系统在“乱拼结构”，而是在完整签名 miss 时做一个保守兜底：只复用已经存在的 exact 组分结构。如果这一组长期为 0，说明当前 residual 要么没有足够大的组分，要么组分本身也没有在 HDB 中沉淀下来。' },
    ],
    induction_raw_residual_split: [
      { title: '真实影响因素：原始残差结构分流比例', desc: '`hdb.config.hdb_config.yaml` 中的 `induction_raw_residual_structure_share` 决定命中现成结构后，有多少预算直接留给结构路径，剩余多少继续留在 memory path。它是这张图里“转结构 EV”和“转记忆 EV”最直接的控制旋钮。' },
      { title: '真实影响因素：上下文优先级与现成结构质量', desc: '同签名结构可能有多个；当前实现会优先考虑 `context_owner_structure_id` 更贴近当前源结构的候选。若“命中现成结构条目数”不低，但“转结构 EV”仍然偏小，除了 share 之外，也要看这些同签名结构是不是上下文上不够贴近。' },
      { title: '如何读这张图', desc: '这张图看的是总体口径：其中“转记忆 EV”同时包含“命中后仍保留的记忆预算”和“根本没命中结构、只能走记忆”的预算。所以如果总体上 memory 很高，不能立刻断言是 share 太保守；还要结合下一张“命中内部分流”一起看。' },
    ],
    induction_raw_residual_structure_kind: [
      { title: '真实影响因素：结构路径到底由谁撑起来', desc: '这里把 `原始残差转结构 EV` 进一步拆成“完整签名命中”和“组分回退”两部分。若结构路径突然变厚，但几乎全来自组分回退，说明系统已经能复用局部块，却还没在完整 residual 级别沉淀出可直接复用的结构。' },
      { title: '真实影响因素：完整签名稀疏度 vs 组分沉淀度', desc: '如果 `完整签名结构 EV` 长期很低而 `组分回退结构 EV` 很高，优先排查 residual 是否过长、过新、过细碎；若两者都低，则是局部链整体供给不足。这个判断比盲目继续抬 `structure_share` 更可靠。' },
    ],
    induction_raw_residual_budget_kind: [
      { title: '真实影响因素：结构预算在 exact 与 component 之间怎么分', desc: '`原始残差结构预算权重` 是总体；其中 `完整签名结构预算权重` 表示真正投给 exact 命中的份额，`组分回退结构预算权重` 表示在 full-signature miss 时投给组分结构的份额。若 component 预算长期为 0，而 component 命中图已有数据，说明回退结果没有真正接上分流。' },
      { title: '真实影响因素：coverage-scaled structure share', desc: '组分回退不是简单复制 `induction_raw_residual_structure_share`。当前实现会按“命中的组分单元数 / residual 总单元数”缩放结构 share，所以 component 预算偏小未必是 bug，也可能是只命中了 residual 的一小部分。' },
    ],
    induction_raw_residual_hit_split: [
      { title: '真实影响因素：命中条目内部的真实 share', desc: '这张图的“命中”现在同时包括完整签名命中与组分回退命中。它直接对照 `转结构 EV` 和 `命中后仍走记忆 EV`。如果这里结构 EV 仍长期明显低于命中后记忆 EV，才说明 `induction_raw_residual_structure_share` 可能真的偏保守。' },
      { title: '真实影响因素：命中率与签名稀疏度是另一条问题轴', desc: '若“未命中仅记忆 EV”长期很高，而前两条并不夸张，说明当前主要问题不是 structure share，而是很多 residual 连 exact 或 component 级结构都接不上。这时更该回查 residual 长度、group 切分、signature 稀疏度与上下文贴近度。' },
      { title: '如何读这张图', desc: '理想状态通常是：命中条目内部，结构 EV 至少不应长期远低于命中后记忆 EV；同时“未命中仅记忆 EV”也不应长期压倒性统治。若前者异常，优先看 share；若后者异常，优先看命中率与结构可接性。' },
    ],
    induction_ratio: [
      { title: '真实影响因素：当前更偏“沿旧预期扩散”还是“由现实重新诱发”', desc: '`局部传播目标占比` 高，说明系统主要沿已有残差链续写预期；`ER 诱发 EV 占比` 高，说明当前更多是现实证据重新拉起新预期。这两条一起看，才能判断 EV 低到底是传播不足，还是诱发不足。' },
    ],
    induction_energy_graph_shape: [
      { title: '真实影响因素：V2 总开关与配置轮数上限', desc: '`hdb.config.hdb_config.yaml` 里的 `induction_energy_graph_v2_enabled` 与 `induction_energy_graph_v2_max_rounds` 决定这条分层图景链路是否实际开启、以及每个根源最多允许展开几轮；图里的“实际最大轮数”则是本 tick 真正跑出来的观测值。若实际值长期只有 0 或 1，优先先看配置上限和源对象是否有局部候选，而不是误判成 residual 链没内容。' },
      { title: '真实影响因素：根源 ER 衰减与前沿可续航性', desc: '`induction_energy_graph_v2_root_er_decay_ratio` 越高，根源 ER 越能在多轮持续再诱发；`induction_energy_graph_v2_min_frontier_ev` 与 `induction_energy_graph_v2_max_frontier_nodes_per_source` 则共同决定层数和最大层宽能否长出来。' },
    ],
    induction_energy_graph_budget: [
      { title: '真实影响因素：根源自身 EV 与根源再诱发比例', desc: '`induction_energy_graph_v2_root_source_ev_ratio` 决定根源对象首轮拿多少自身 EV 直接投入图景；`induction_energy_graph_v2_er_round_ratio` 决定每轮根源还能再拿出多少 ER 去诱发新一层。前者更像“已有预期起步预算”，后者更像“现实证据续航预算”。' },
      { title: '真实影响因素：前沿下传比例与最小预算门槛', desc: '`induction_energy_graph_v2_frontier_ev_ratio` 决定前沿 EV 传给下一层时保留多少；`induction_energy_graph_v2_min_budget` 决定预算低到何时直接不再分叉。若累计传播预算不低但总增量始终薄，通常就是这组门槛太保守。' },
    ],
    induction_energy_graph_frontier: [
      { title: '真实影响因素：前沿上限与剪枝阈值', desc: '`induction_energy_graph_v2_max_frontier_nodes_per_source` 决定每个源在任一轮最多保留多少前沿节点；`induction_energy_graph_v2_min_frontier_ev` 与 `induction_energy_graph_v2_min_budget` 一起决定有多少节点会被直接剪枝。若“前沿生成数”高但“前沿剪枝数”也异常高，说明图景正在过度稀释。' },
      { title: '如何读这张图', desc: '`终端记忆数` 上升，表示图景已经深入到了没有下级数据库、只能停留为记忆残差的末梢；`根源再诱发次数` 高，表示这更像用户理论里的“同一个根源 ER 在多轮持续诱发”而不是一跳即停。' },
    ],
    induction_energy_graph_layers: [
      { title: '真实影响因素：每层可保留目标数', desc: '`induction_energy_graph_v2_target_top_k` 会直接限制每个前沿节点单步最多向多少下级目标分配预算，因此会显著影响“层节点总数”和“单轮最大前沿输出数”。如果前沿输入不低但输出总压不起来，优先查这里。' },
      { title: '如何读这张图', desc: '理想情况下，`单轮最大前沿输入数` 与 `单轮最大前沿输出数` 会在某些轮次形成可见放大，而不是一路贴地；若层节点总数很高但最大层宽始终很低，则说明图景主要在纵向递归、尚未形成明显横向扇出。' },
    ],
    induction_energy_graph_delta: [
      { title: '真实影响因素：多轮续航而不是单轮爆发', desc: '`轮增量 EV 总和` 高但 `末轮增量 EV` 很快归零，说明图景更像一次性爆发；若 `末轮增量 EV` 仍稳定非零，则说明多轮递归确实还在做功，更接近你要的“层层探索更深结构”。' },
      { title: '真实影响因素：ER 衰减与传播保真度的平衡', desc: '`induction_energy_graph_v2_root_er_decay_ratio` 太低会让后几轮迅速掉空；`induction_energy_graph_v2_frontier_ev_ratio` 太低则会让每层传下去的 EV 很快碎掉。两者要配平，才能让“单轮最大增量”和“末轮增量”都保持可解释。' },
    ],
    sensor_text: [
      { title: '真实影响因素：文本感受器输入规模', desc: '输入字符数、外源 SA、输入 flat token 数共同反映文本感受器把原始文本切成了多少可处理对象。若字符数正常但外源 SA 很低，优先查文本切分和标点分段链。' },
    ],
    sensor_compose: [
      { title: '真实影响因素：感受器构件输出', desc: '基础刺激元、属性刺激元、结构包、残响帧数反映文本感受器输出的“层次完整度”。如果长期只有基础刺激元而缺属性或结构包，应优先查属性抽取与打包链路。' },
    ],
    pool_energy: [
      { title: '真实影响因素：状态池注入与衰减', desc: '这张图主要受状态池落地增量、维护衰减、记忆反馈注入、情绪与认知感受绑定的综合影响。若总能量持续单边上涨或过快掉空，应先回查状态池落地和维护链。' },
    ],
    pool_load: [
      { title: '真实影响因素：注意力候选规模与维护阈值', desc: '`attention_state_pool_candidate_count`、`attention_cam_item_cap` 与状态池维护阈值会共同决定活跃条目数和高认知压条目数。若活跃条目异常膨胀，先查注意力候选与维护链。' },
    ],
    pool_complexity_score: [
      { title: '真实影响因素：全量复杂度与核心复杂度不是一回事', desc: '`复杂度得分` 会把大量弱 SA 尾巴也算进去，所以更适合解释“繁重/忙乱”；`核心复杂度得分` 则尽量只看结构主峰，更适合解释“简感/轻松感为什么没被永久压死”。如果前者高、后者低，通常说明系统是尾巴多，不一定是真的核心结构混乱。' },
    ],
    pool_peak_concentration: [
      { title: '真实影响因素：能量是否被少数热点锁死', desc: '`状态池能量集中度` 越高，说明总能量越被少数热点对象占住；`核心能量集中度` 则只看结构主峰。若全量集中度低但核心集中度高，往往表示尾巴散得很开，但真正主线仍很聚焦。' },
    ],
    pool_peak_count: [
      { title: '真实影响因素：峰数决定的是“有几个主峰在竞争”', desc: '`有效峰数` 可以粗略理解成当前有多少个能量峰在分能量；`核心有效峰数` 则回答结构主峰层面到底有几条强主线。它比单看对象数更接近“当前认知图景到底是单峰、双峰还是多峰”。' },
    ],
    stimulus_size: [
      { title: '真实影响因素：输入分段、中和与落地', desc: '外源 SA、合流 token、中和后 token、落地 token 分别对应文本感受器分段、缓存中和、状态池落地几个阶段。若中间某一段长期掉 0，应直接回查对应链路是否断数。' },
    ],
    stimulus_balance: [
      { title: '真实影响因素：内源预算与外源分段规模', desc: '这张图同时受外源输入分段长度、内源结构候选规模、内源细节预算约束影响。若内源长期远低于外源，优先看内源候选与预算；若长期远高于外源，则看疲劳与回忆约束是否失效。' },
    ],
    stimulus_energy_landing: [
      { title: '新版主口径：完整对象投影 + 记忆尾巴吸收', desc: '`stimulus_object_projection_total` 是刺激级查存一体直接落到完整结构/字符串/关系对象上的能量；`stimulus_memory_tail_absorbed_total` 是没有被逐轮完全吃掉的刺激尾巴按当前完整 episodic memory_id 并入状态池的能量。它们合起来才是 growth 口径下的主要落地面。' },
      { title: '旧口径仍保留为审计，不单独判失败', desc: '`stimulus_transfer_matched_total` / `stimulus_final_residual_total` 只描述 selected-match 贪婪轮次里显式转走了多少、还剩多少。新版里剩余尾巴可以直接变成当前完整记忆对象，所以旧 residual 大不等于污染，也不等于残余包需要晋升。' },
    ],
    stimulus_energy_dominance: [
      { title: '验收标准：未处理残余应接近 0', desc: '`stimulus_unhandled_residual_total` 才表示既没有落到完整对象投影，也没有被当前 memory_id 吸收的尾巴。正常 growth 运行中，它应长期接近 0；`stimulus_object_projection_dominates_unhandled_residual` 大多数 tick 应为 1。' },
      { title: '性能解释：对象投影占优早停只砍旧尾巴审计', desc: '`stimulus_early_stop_object_projection_dominance_triggered` 触发时，表示完整对象投影已经压过剩余尾巴，而且记忆 id 已准备好接住尾巴。转移护栏拦截次数高，说明逐轮命中转移还不够明显，系统会多跑几轮来满足你要求的“命中对象能量高于最终剩余”。' },
    ],
    stimulus_v2_match: [
      { title: '真实影响因素：刺激级软匹配评分权重', desc: '这张图直接受 `hdb/config/hdb_config.yaml` 里的 `match_scoring_v2_*_weight`、数值容差、S 型曲线参数与最低分阈值影响。综合分偏低时，要先拆看是基础分不足、数值不接近，还是顺序对齐不自然。' },
      { title: '如何读这张图', desc: '如果 `V2 基础分` 不低，但 `V2 综合分` 仍明显偏低，通常说明数值、顺序、属性或上下文这些软因子没有给到支撑；如果几条线一起低，则是候选本身就不够像。' },
    ],
    stimulus_v2_support: [
      { title: '真实影响因素：候选合格率与 blended 夺权力度', desc: '`stimulus_match_v2_eligible_ratio` 反映 V2 视角下到底有多少候选值得参与竞争；`stimulus_match_v2_blend_gain_mean` 反映 blended 排序相对 legacy 的平均增益。若合格率高但增益仍低，说明当前 blend 权重还偏保守。' },
      { title: '真实影响因素：属性锚点、上下文支撑与能量图景', desc: '属性锚点分、上下文支撑分、能量图景相似度分别回答“像不像同一类东西”“上下文链支不支持”“虚实能量结构像不像”。其中任何一条长期过低，都会让 V2 更像审计失败，而不是排序夺权成功。' },
    ],
    numeric_v2_activation: [
      { title: '如何读这张图', desc: '`numeric_scored_ratio` 表示候选里有多少对象真的带着可计算的数值因子进入了 V2；`numeric_nonzero_ratio` 表示这些数值因子里又有多少真的提供了正向贡献。前者低说明数值通路根本没接进来，后者低则说明接进来了但大多不相似。' },
      { title: '真实影响因素：数值属性 SA 开关与候选构成', desc: '这张图首先受 `sensor_enable_stimulus_intensity_attribute_sa`、属性 ER/EV 比例、以及当前输入是否真的形成了带数值因子的候选影响。结构级数值显影长期为 0 时，不一定是 bug，也可能只是当前运行没有进入真正的结构级 group 竞争。' },
    ],
    numeric_v2_cost: [
      { title: '如何读这张图', desc: '`sensor_attribute_sa_count` 和 `sensor_attribute_sa_per_feature_ratio` 回答“当前每拍额外塞进来了多少数值属性刺激元”；`timing_sensor_ms` 与 `timing_stimulus_level_ms` 则回答这件事的直接代价。适合做性能-效果折中，不适合单独判定理论正确性。' },
      { title: '真实影响因素：属性刺激元膨胀与刺激级检索成本', desc: '如果数值显影确实起来了，但这张图同时显示属性刺激元数量和刺激级耗时明显飙升，说明下一步该优先做 attribute SA 限流、采样或更轻量的数值侧带，而不是盲目继续堆开关。' },
    ],
    stimulus_sensor: [
      { title: '真实影响因素：文本感受器切分与残响参与', desc: '基础刺激元、属性刺激元、结构包、残响帧数由文本切分器、属性抽取和 echo 参与共同决定。若基础量正常但结构包长期为 0，先查结构封装与输入解析链。' },
    ],
    stimulus_candidate_cost: [
      { title: '真实影响因素：局部候选与共同切割', desc: '这张图里的候选数、剪枝数和共同切割次数直接对应刺激级查存一体的主要 CPU 花销。若耗时高但候选数不高，通常要看 normalize / cut 缓存命中；若候选数高，则优先看 owner-local 残差索引和候选剪枝。' },
      { title: '缓存解释：残差存在性缓存不改变结果', desc: '`锚点 owner 残差存在跨 tick 缓存` 只缓存某个 owner DB 是否存在 residual/common 条目这个布尔形状信息，key 带 owner id、db id、updated_at 和 diff_table 长度。它不缓存能量、疲劳、分数或转移量，所以属于低风险性能优化。' },
    ],
    internal_source: [
      { title: '真实影响因素：内源结构数量上限', desc: '`hdb.main.py` 中的 `internal_resolution_max_structures_per_tick`。当“内源候选结构数”持续高、但“内源入选结构数”长期卡住时，应优先看这个上限。' },
      { title: '真实影响因素：内源细节预算', desc: '`hdb.main.py` 中的 `internal_resolution_detail_budget_base` 与 `internal_resolution_detail_budget_adr_gain`。如果结构入选了，但“内源原始 SA 数”到“内源入选 SA 数”压缩很重，主要受这组预算控制。这里的 SA 目前是兼容旧图表口径，底层真实实现对应的是细节单元。' },
      { title: '真实影响因素：每结构细节上限', desc: '`hdb.main.py` 中的 `internal_resolution_min_detail_per_structure`、`internal_resolution_max_detail_per_structure`、`internal_resolution_flat_unit_cap_per_structure`。它们决定单个来源结构最多能吐出多少字符级细节。' },
      { title: '真实影响因素：注意力工作集规模', desc: '`attention.main.py` 输出的 `cam_item_count` 会直接影响内源来源候选。若候选本身就少，问题更可能在注意力筛选链，而不是内源预算链。' },
    ],
    internal_attribute_projection: [
      { title: '真实影响因素：运行态绑定属性是否允许投影', desc: '这张图最直接受 `hdb.config.hdb_config.yaml` 中的 `internal_fragment_include_runtime_bound_attributes`、`internal_fragment_runtime_attribute_numeric_only` 与 `internal_fragment_runtime_attribute_max_count` 控制。若 state-pool 明明已经绑定了属性，这里却始终为 0，优先排查这组三个开关。' },
      { title: '如何读这张图', desc: '总属性数起来了但数值属性数很低，说明投影进来的大多是离散属性；时间类属性数起来了，才说明时间感受确实跨过了“运行态绑定 -> 内源刺激”的那道坎。' },
    ],
    internal_cfs_projection: [
      { title: '真实影响因素：CFS 运行态是否被投影进内源', desc: '如果 `cfs_*_live_*` 已经存在，但这里的 `内源 CFS 属性` 长期为 0，说明 CFS 只停在状态池绑定，没有真正被内源刺激流消费。' },
      { title: '如何读这张图', desc: '这里使用“族计数”而不是只看 `cfs_pressure`/`cfs_expectation` 精确名，是为了把 `..._verified`、`..._unverified` 这些同家族变体一起算进去。' },
    ],
    internal_feedback_projection: [
      { title: '真实影响因素：奖惩/教师信号是否跨 tick 留存', desc: '这张图用于核对 reward/punish/teacher 系列运行态属性有没有真正进入下一拍内源刺激。若教师应用次数有了，但这里仍长期为 0，说明问题不在标签读入，而在 runtime-bound attribute -> internal fragment 这段桥接。' },
    ],
    internal_resolution_detail: [
      { title: '真实影响因素：内源细节预算与实际入选量', desc: '这张图直接回答“预算给了多少”“原始细节有多少”“最后真正入选了多少”。它最适合观察注意力滤波和内源分辨率机制到底压缩了多少 SA/细节单元。' },
      { title: '真实影响因素：结构数与细节数的双重门控', desc: '`internal_resolution_structure_count_selected` 反映选中了多少来源结构，`internal_resolution_selected_unit_count` 反映这些结构最终吐出了多少细节。结构选得上来但细节仍少，说明压缩发生在细节预算而不是候选结构阶段。' },
    ],
    internal_runtime_priority_resolution: [
      { title: '如何读这张图', desc: '`高优先级属性候选结构数 -> 高优先级属性入选结构数 -> 已选高优先级属性单元数 -> rescue 高优先级属性单元数` 这条链，分别对应“结构层候选”“结构层保留”“unit trim 后仍活着”“靠 rescue 机制活下来”。' },
      { title: '真实影响因素：不是所有 bridge 问题都卡在同一层', desc: '如果高优先级属性候选结构数已经有了，但入选结构数很低，说明主要卡在 fragment 竞争；如果结构已经入选，但高优先级属性单元仍接近 0，说明主要卡在 internal resolution 的 unit trim。' },
    ],
    internal_cam_runtime_priority_sidepath: [
      { title: '如何读这张图', desc: '`侧路候选结构数 -> 投影片段数 -> 投影 family 数 -> 投影属性单元数` 这条链，对应的是“主 fragment 没显出来时，CAM 是否额外补了一条轻量属性侧路”。' },
      { title: '真实影响因素：这是补洞侧路，不是主竞争通道', desc: '如果这里持续升高，而 `internal_feedback_projection` 仍很低，说明侧路被造出来了，但后面还可能卡在 internal resolution 或 stimulus merge；如果这里长期为 0，则更可能是 CAM 本身没有带到对应 runtime family，或 family 已被主 fragment 表达而被侧路主动跳过。' },
    ],
    internal_resolution_pool: [
      { title: '真实影响因素：注意力工作集到内源片段的转化', desc: '`cam_item_count` 是当前注意力工作集规模，`internal_source_structure_count` / `internal_candidate_structure_count` / `internal_fragment_count` 则表示其中多少对象真正进入了内源解析并产出片段。这个视图能直接看出注意力滤波效果。' },
    ],
    retrieval_rounds: [
      { title: '如何读这张图', desc: '这张图展示的是“结构级查存轮次 / 刺激级查存轮次 / 认知拼接动作次数”。如果你当前只看到一个有效系列，通常不是图坏了，而是另外两项在这段运行里恒定为 0 或恒定不变，已被无意义系列过滤自动隐藏。' },
      { title: '真实影响因素：上游是否真的进入对应阶段', desc: '结构级轮次取决于结构级查存是否实际发生；刺激级轮次取决于刺激级贪婪匹配是否进入循环；认知拼接动作次数则取决于候选事件、权重阈值与动作上限。某项长期消失，优先说明那条链根本没被跑起来。' },
      { title: '特殊情况：新版 growth 默认下结构级为 0 可能是预期', desc: '如果当前运行明确关闭了 `enable_structure_level_retrieval_storage`，那 `structure_round_count=0`、结构级 V2 全 0 往往不是故障。新版默认主链更应看“刺激级查存一体 + 感应生长 A+B + 内源刺激重采样”，CS 只有在显式开启 residual/对照路径时才是重点。' },
    ],
    structure_v2_match: [
      { title: '真实影响因素：结构级候选组的软匹配质量', desc: '结构级 V2 不是只看“组命中了没有”，而是看命中的组像不像当前刺激与上下文真正需要的结构组合。基础分、数值接近、顺序对齐的任一项失真，都会让这张图提前暴露问题。' },
      { title: '如何读这张图', desc: '如果结构级 `V2 综合分` 长期高于刺激级，但最终行为仍不自然，说明更可能是后段竞争、赋能或行动链问题；如果结构级本身就偏低，优先查 group 候选构成和上下文路径。' },
      { title: '特殊情况：全 0 不一定是坏', desc: '当 `enable_structure_level_retrieval_storage=false` 或本轮根本没有进入结构级查存时，这张图可能整段为 0。那表示“结构级本轮未参与”，不是“结构级 V2 算分器坏了”。要先结合 `structure_round_count` 与运行配置一起判断。' },
      { title: '特殊情况：有轮次但 V2 仍为 0', desc: '如果 `structure_round_count` 不为 0，但结构级 V2 仍全 0，另一种常见情况是结构层只走了 `implicit_single_st` 这类 synthetic 单组快捷路径：有结构级活动，但没有真正进入 group 候选软匹配竞争，因此这组 V2 指标天然没有可统计的对象。' },
    ],
    structure_v2_support: [
      { title: '真实影响因素：结构包含度、上下文支撑与 blended 结果', desc: '`structure_match_v2_structure_inclusion_mean` 表示候选结构组对当前输入的覆盖程度；上下文支撑和属性锚点则表示“这组结构是否真属于这个语境”。如果覆盖高但 blended 增益仍低，说明 legacy 与 V2 的排序差异还没有真正夺权。' },
      { title: '真实影响因素：阈值余量不是噪音', desc: '阈值余量低并不一定表示图坏了，而是表示候选正在阈值附近犹豫。此时若强行加大 blend 或降阈值，可能会把噪音一并放大，所以最好结合 `eligible_ratio` 和 `energy_profile_mean` 一起看。' },
      { title: '特殊情况：支撑项全 0 先查是否根本没跑结构级', desc: '如果这张图所有系列都贴地，而 `structure_round_count` 也长期为 0，优先结论应是“当前路线没有走结构级”，而不是“上下文支撑/属性锚点算法全坏了”。在新版 growth 默认路线下，这通常意味着要转看刺激级、感应生长、内源刺激与行动闭环。' },
    ],
    structure_v2_path: [
      { title: '真实影响因素：结构级是否真的进入 group 竞争', desc: '`structure_round_synthetic_count` 和 `structure_round_implicit_single_count` 高，通常表示结构层主要在走 synthetic 单组快捷路径；`structure_round_competitive_count` 高，才表示真正进入了 group 候选竞争。' },
      { title: '如何读这张图', desc: '如果 `structure_round_count` 不为 0，但后两项长期贴地，而 synthetic/implicit_single 持续升高，那结构级 V2 全 0 往往是路径现象，不是算分器坏掉。只有真实竞争轮次已经起来、V2 仍全 0，才值得继续追查字段漏传或算分问题。' },
    ],
    stitching_flow: [
      { title: '真实影响因素：认知拼接前段转化率', desc: '从事件种子、结构种子到候选、动作、强化，反映的是认知拼接前段是否真的跑起来。如果种子有、候选有，但动作始终低，问题多半在权重阈值或动作限额。' },
    ],
    stitching_output: [
      { title: '真实影响因素：字符串关系产出与认知拼接后段产出', desc: '你当前看到的许多长字符串对象，未必来自 `cognitive_stitching.main` 的 `created/extended/merged` 计数，也可能来自刺激级 `goal_b_string_relation_seed` 等字符串关系产出。因此这张图现在把 `stimulus_new_structure_count` 一并纳入，避免“明明有新字符串对象，图却空白”的错位。' },
    ],
    stitching_grasp_flow: [
      { title: '真实影响因素：焦点来源与能量门槛', desc: '`cs_event_grasp_cam_seed_count`、`cs_event_grasp_post_action_seed_count` 回答“哪些事件有资格进入 grasp 焦点”；`cs_event_grasp_selected_event_count`、`cs_event_grasp_emitted_count` 回答“它们有没有真的过事件识别与最低总能量门槛”。如果种子有了但 emitted 长期为 0，优先看 `event_grasp_min_total_energy` 与事件总能量保持。' },
      { title: '如何读这张图', desc: '如果后拼接种子高、CAM 种子低，说明当前叙事更依赖本 tick 新鲜拼接；如果 CAM 种子也高，说明已有成熟事件开始稳定进入注意力。' },
    ],
    stitching_grasp_sources: [
      { title: '真实影响因素：旧 CAM 成熟事件 vs 新鲜拼接事件', desc: '`cs_event_grasp_cam_selected_event_count` 高，说明 grasp 更多来自已在注意力里的成熟事件；`cs_event_grasp_post_action_selected_event_count` 高，说明新鲜拼接事件已经能在当前主链顺序下获得把握。若两边都长期为 0，但 `cs_action_count` 不低，就该优先排查事件识别或 grasp 能量门槛。' },
    ],
    stitching_narrative: [
      { title: '真实影响因素：主叙事能量与把握并不等价', desc: '`cs_narrative_top_total_energy` 高只说明主叙事对象在当前轮有存在感；`cs_narrative_top_grasp` 高才说明当前 top1 已形成较稳定的可把握事件。若 top1 grasp 仍低，但 `cs_narrative_grasp_max` 已升高，则说明“成熟事件已经存在，只是这一拍最强对象不是它”。' },
      { title: '真实影响因素：事件把握来自能量、内部平衡与竞争余量', desc: '`event_grasp_min_total_energy`、事件总能量、组分 ER/EV 平衡、以及同 tick 的领先优势，都会共同决定 grasp 是否起得来。若总能量有了但两条 grasp 线都长期上不去，优先回查这些真实约束。' },
    ],
    stitching_v2_match: [
      { title: '真实影响因素：V2 匹配质量权重', desc: '这张图直接受 `cognitive_stitching/config/cognitive_stitching_config.yaml` 里的 `cs_v2_context_cover_weight`、`cs_v2_order_weight`、`cs_v2_tail_match_weight` 与 `cs_v2_min_match_score` 影响。若综合分数低，先拆看是上下文覆盖差、顺序不自然，还是尾端匹配本身太弱。' },
      { title: '真实影响因素：当前仍是 legacy 执行、V2 审计并行', desc: '当前模式下真正驱动产出的仍是 legacy score；这张图回答的是“如果按 V2 哲学审计，同一批候选看起来是否健康”。因此它最适合做 A/B 对照，而不是单独替代产出图。' },
    ],
    stitching_v2_support: [
      { title: '真实影响因素：上下文库支撑与能量图景相似度', desc: '`cs_candidate_v2_context_db_support_mean` 主要看 diff 边与上下文链是否真的支持当前拼接；`cs_candidate_v2_energy_profile_mean` 则看来源与目标在 ER/EV 图景上是否相似。若前者低，优先查上下文库边质量；若后者低，优先查能量传播与感应赋能后的图景是否失真。' },
      { title: '真实影响因素：阈值余量与疲劳闸门', desc: 'V2 阈值余量由 `cs_v2_min_match_score` 和当前候选分数共同决定；同一路径反复出现时，还会被 `cs_v2_same_pair_fatigue_enabled` 与 legacy 的 same-pair fatigue 链共同压缩。若基础分不低但余量仍薄，通常是阈值偏高或疲劳过强。' },
    ],
    cfs_peak: [
      { title: '真实影响因素：触发阈值与当前事件强度', desc: '峰值图回答的是“有没有触发到”。它主要受当前 tick 的事件冲突、期待落空、惊讶输入、复杂度与把握感计算影响。若某通道长期为 0，优先排查触发条件而不是总量维持。' },
    ],
    cfs_live: [
      { title: '真实影响因素：绑定维持与衰减', desc: '运行态总量不是瞬时触发，而是绑定到状态池后的维持结果。若峰值存在但总量长期很低，通常说明绑定后维持链太弱、衰减过强，或绑定对象数太少。' },
    ],
    cfs_count: [
      { title: '真实影响因素：通道即时触发频次', desc: '这张图只回答“这一拍有没有新触发”。若某通道即时频次为 0，但运行态总量仍在，就说明它不是没存在，而是没有新增触发。' },
    ],
    cfs_global_balance: [
      { title: '真实影响因素：复杂度、简感与重复疲劳的拉扯', desc: '`复杂度总量` 高说明当前更偏繁重和收窄；`简感/轻松感总量` 高说明系统处在较低复杂度且惩罚压力不高的恢复带；`重复感总量` 高则更像疲劳或套路化。三者一起看，比单看某一条更接近当前整体主观状态。' },
    ],
    cfs_global_count: [
      { title: '真实影响因素：全局感受是新触发还是旧状态维持', desc: '这张图专门看复杂度、简感和重复感在本 tick 是否新增触发。若即时触发降为 0 但持续态还高，说明系统只是延续前几拍的全局状态，不是本拍重新判断出来的。' },
    ],
    cfs_positive_guidance: [
      { title: '真实影响因素：正向判断链是否能维持', desc: '`正确事件总能量` 更像“刚刚确认对了一件事”，`把握感总量` 更像“当前理解是稳的”，`简感/轻松感总量` 则更像“系统负担确实在下降”。如果它们偶尔起峰但维持不住，优先怀疑绑定后维持链和衰减，不要先怀疑触发逻辑完全没工作。' },
    ],
    cfs_positive_count: [
      { title: '真实影响因素：正向感受的新增触发频次', desc: '这张图适合和正向持续态图配合看：如果正确事件、把握感或简感频次不低，但持续态总量仍低，更像是维持链太弱，而不是正向感受根本没产生。' },
    ],
    cfs_pressure_semantics: [
      { title: '真实影响因素：即时触发 vs 运行态维持', desc: '`压力即时触发次数` 只统计这一拍新发出的 pressure 信号；`压力运行态激活标记` 则表示状态池里仍存在 pressure 绑定；`压力仅持续未新触发标记` 用来直接指出“这一拍没有新 pressure，但旧 pressure 还在衰减维持”。' },
      { title: '如何读这张图', desc: '如果 `压力即时触发次数=0` 但 `压力运行态激活标记=1`，这不是 bug，而是“旧压力还没消退”。若两者都长期为 0，才更像 pressure 通道真的没有工作。' },
    ],
    cfs_next_tick_projection: [
      { title: '真实影响因素：运行态家族维持 vs 下一拍内源投影', desc: '左半边是状态池里压力/期待家族是否还活着，右半边是这些家族在下一拍有没有真正被投影成内源属性刺激元。左高右低通常意味着桥接或内源预算在拦截。' },
    ],
    cfs_verification_count: [
      { title: '真实影响因素：被追认 vs 未被追认的即时分叉', desc: '这张图只看本 tick 新产生的 `已证实/未证实期待` 与 `已证实/未证实压力`。它更适合回答“当前样本是在制造被现实追认的判断，还是只在堆背景预期/威胁”。' },
    ],
    reward_system: [
      { title: '真实影响因素：系统内部奖惩结算', desc: '系统奖励与惩罚由期望契约、行动成功/失败、违和与正确性链路共同驱动。若奖励和惩罚都长期为 0，应先查是否根本没有结算事件进入奖惩模块。' },
    ],
    reward_teacher: [
      { title: '真实影响因素：教师标签与实际应用次数', desc: '教师奖励/惩罚、标签值、实际应用次数分别表示“数据集给了什么监督”“系统读到了什么标签”“最后有没有真正落地到当前 tick”。三者不一致时，应优先查标签读取和应用链。' },
    ],
    reward_runtime_projection: [
      { title: '真实影响因素：教师应用、运行态绑定与下一拍内源投影', desc: '这张图把 `teacher_applied_count`、`teacher_*_live_*` 和 `internal_teacher_*` 放到同一条链上。若教师已应用，但运行态属性数或内源投影数不跟，说明是落库/桥接链的问题，而不是标签数据本身。' },
    ],
    action_teacher_cfs_bridge: [
      { title: '真实影响因素：教师奖惩如何真正改写行动', desc: '这张图把 `teacher_applied_count`、`reward/punish live`、`已证实期待/压力`、以及 `weather_stub` 的局部 reward bonus / punish penalty 串在一起。它最适合回答“教师奖惩是不是只在情绪层打转，还是已经沿认知感受链传导到了具体行动节点”。' },
    ],
    neuro_stress: [
      { title: '真实影响因素：违和、压力与恢复链的合成结果', desc: '这张图不是“情绪标签”，而是 NT 慢变量的结果层。`COR/ADR` 更像警戒与应激，`SER/END` 更像稳定与缓冲。若前两条长期高、后两条长期低，通常说明系统长期处在高冲突高负载。' },
    ],
    neuro_reward: [
      { title: '真实影响因素：正确感、奖励信号与亲和维持', desc: '`DA/OXY/END` 共同反映趋近、联结与舒缓链路。它们既受 CFS 与奖励信号驱动，也会反过来影响行动阈值、学习强度与表达风格。' },
    ],
    neuro_explore_focus: [
      { title: '真实影响因素：探索窗口与锁定窗口的竞争', desc: '`NOV` 高表示系统更愿意给新线索、意外变化和未证实路径机会；`FOC` 高表示系统更愿意收窄搜索、锁定当前主线。把 `DA/COR` 放在一起，是为了同时看到“趋近推进”和“保守约束”如何共同塑形这两个新通道。' },
      { title: '如何读这张图', desc: '理想状态通常不是 `NOV` 或 `FOC` 长期单边打满，而是会随任务阶段切换：探索期 `NOV` 短升，收敛期 `FOC` 抬高。若两者都长期贴地，说明 NT 对注意力风格的调制不明显；若两者都长期高位，则要警惕上游 CFS 或奖励/惩罚结算过强。' },
    ],
    neuro_attention_mod: [
      { title: '真实影响因素：NT 已经不只是“有值”，而是真在改注意力', desc: '这张图展示的是 NT 调制后的注意力输出结果，而不是通道原始值本身。`attention_cam_item_cap` 和 `attention_mod_min_cam_items` 决定本轮大致要看多宽；`focus_boost_weight` 与 `min_total_energy` 决定更像“广扫”还是“精看”；`attention_mod_attention_energy_budget / attention_energy_budget / attention_net_delta_energy` 用来核对能量预算是否被调制并真正约束净增。' },
    ],
    neuro_attention_energy_budget: [
      { title: '真实影响因素：注意力能量预算不是 CAM 数量', desc: '`attention_energy_budget_base` 是基线资源，当前默认目标约 8；`attention_mod_attention_energy_budget` 是 NT/行动给出的调制建议；`attention_energy_budget` 是最终裁剪后的本轮可注入能量。净增量长期超过最终预算才需要怀疑预算约束失效。' },
    ],
    neuro_attention_priority: [
      { title: '真实影响因素：排序偏置的实时重配', desc: '这里能直接看到 NT 如何改变注意力的排序口味：是更偏总能量、更偏认知压、更偏显著性/意外，还是更偏近因新鲜度。相比只看 CAM 数量，这张图更接近“为什么会选这些对象”。' },
    ],
    neuro_hdb_mod: [
      { title: '真实影响因素：NT 对学习传播参数的真实输出', desc: '这张图直接显示 NT 对 HDB 的运行时缩放结果，而不是静态配置。`base_weight_er_gain` 更偏现实证据学习，`base_weight_ev_wear` 更偏对纯虚循环的磨损，`ev_propagation_*` 与 `er_induction_ratio` 则决定预期扩散和现实诱发的力度。' },
      { title: '如何读这张图', desc: '若 `emotion_hdb_ev_propagation_ratio_scale` 抬高而 `emotion_hdb_ev_propagation_threshold_scale` 同时降低，说明系统更愿意让已有预期继续扩散；若 `emotion_hdb_er_induction_ratio_scale` 抬高，则说明现实证据更容易继续诱发新的预期对象。' },
    ],
    action_result: [
      { title: '真实影响因素：执行链是否真正落地', desc: '这张图看的是已执行结果，而不是尝试。若尝试存在但执行为 0，优先排查驱动力阈值、行动竞争、执行条件与行动器返回结果。' },
    ],
    action_schedule: [
      { title: '真实影响因素：想做什么 与 被调度什么', desc: '行动尝试总数代表当前产生了多少行动意图，调度次数代表其中有多少真的被送入行动器。两者差得很大时，问题多半在调度与门控。' },
    ],
    action_iesm_front: [
      { title: '真实影响因素：先天规则前段是否真的命中', desc: '`IESM 命中规则数` 说明规则条件本身有没有成立，`IESM 命中脚本数` 说明有没有额外脚本联动，`IESM 行动触发数` 则说明最终有没有吐出供行动器消费的 action_trigger。若这里已经有数，但后面的尝试/执行仍为 0，问题就在行动驱动力、阈值或调度器。' },
    ],
    action_weather_chain: [
      { title: '真实影响因素：触发不等于执行', desc: '`IESM 天气查询触发数` 只说明先天规则看到了“该考虑天气行动”；`天气查询尝试次数` 说明行动节点真正获得了驱动力；`天气查询调度次数` 说明它进入了异步或延时执行；`天气查询执行次数` 才代表行动器真的返回成功。四段里断在哪一段，问题就在哪一层。' },
      { title: '真实影响因素：弱样本会触发但不过阈值', desc: '只含“天气”而没有明确“查询/帮我查”意图的弱样本，理论上可以让 `IESM 天气查询触发数` 抬头，但 `天气查询执行次数` 仍为 0。若你看到这种形态，它更像阈值与驱动力设计使然，而不是前端没拿到数据。' },
    ],
    teacher_feedback_focus: [
      { title: '如何读这张图', desc: '`教师奖励/惩罚` 是外部标签输入；`教师主目标原子化标记` 表示主绑定是不是类似 `{A}` 这样的原子对象；`教师上下文镜像候选数 / 绑定数` 表示有没有把教师信号同步到当前 attention 可见的大结构载体；`教师上下文载体聚焦数` 则表示有没有继续为这些载体发下一拍 focus 侧路。' },
      { title: '真实影响因素：绑定成功不等于下一拍能显影', desc: '如果运行态教师信号已有值，但 `教师主目标原子化标记=1` 且 `教师上下文镜像绑定数=0`，说明监督仍只停在原子目标上；这类目标即使理论 attention 分很高，也可能被 CAM 的 atomic shadow 规则跳过。若上下文镜像绑定已发生而 reward 仍不显影，则应继续排查内源展开和 runtime family 传递。' },
    ],
      action_weather_rule_split: [
        { title: '真实影响因素：弱提及 / 隐式问句 / 强查询三档分流', desc: '`IESM 弱天气规则命中数` 代表只是顺手提到天气；`IESM 隐式天气问句命中数` 代表已经在借天气做决策，但未明确说“帮我查”；`IESM 强天气规则命中数` 则代表显式查询请求。三者能把“随口一提”和“其实已经在求助”拆开。' },
        { title: '真实影响因素：执行落点在 source 还是 synthetic', desc: '`天气查询执行次数（契约可见）` 与 `天气查询执行次数（仅反馈 tick）` 的分流能回答“动作到底落在当前样本窗口，还是落到反馈回合了”。这对判断期望契约失败是否只是窗口设计问题非常关键。' },
      ],
      action_weather_drive: [
        { title: '真实影响因素：节点驱动力是否真正超过实时阈值', desc: '`天气查询驱动力峰值` 反映当前最强天气节点被推到了哪里；`天气查询平均实时阈值` 则包含 NT 调制、疲劳和基准阈值后的真实执行门槛；`天气查询最大驱动裕量` 是两者之差，转正才代表至少有一个天气节点已经具备执行资格。' },
        { title: '如何读弱触发', desc: '如果 `IESM 天气查询触发数` 已经有值，但这里长期表现为“驱动力峰值 < 平均实时阈值、最大裕量为负”，那说明问题不在规则命中，而在弱触发给到天气节点的 drive 仍不够。此时应优先排查阈值设计、奖励预期与当前递质/疲劳调制。' },
        { title: '注意：这里看的是 tick 结束时残余驱动力', desc: '行动节点快照记录的是本 tick 执行/消耗之后的残余 drive。若某拍已经成功尝试并扣除了阈值量，图上 residual drive 可能反而很低。判断“当拍到底有没有过阈值”时，应联合 `天气查询尝试次数`、`天气查询调度次数` 与执行结果一起读。' },
      ],
      action_weather_nodes: [
        { title: '真实影响因素：天气节点在哪一层失血', desc: '`天气查询行动节点数` 为 0 说明天气触发没有真正落成节点；`天气查询活跃节点数` 高但 `天气查询就绪节点数` 低，说明节点被唤醒但还没过阈值；若就绪节点已有值而执行仍为 0，则应优先排查调度器、异步延迟与执行器返回。' },
      ],
      action_contract_visibility: [
        { title: '真实影响因素：契约窗口只看 source tick', desc: '期望契约的满足判定只在 source tick 上进行；synthetic feedback tick 不消耗也不满足窗口。因此“总执行数”不等于“契约可见执行数”，这张图专门用来拆开这两层口径。' },
        { title: '真实影响因素：异步动作的落点', desc: '若天气查询在 synthetic feedback tick 上执行，则 `天气查询执行次数（仅反馈 tick）` 会升高，而 `天气查询执行次数（契约可见）` 仍可能为 0。此时优先排查异步调度延迟与契约窗口设计，而不是误判行动器完全没执行。' },
      ],
    energy_balance_ratio_track: [
      { title: '真实影响因素：这是一张旧闭环诊断图', desc: '`pool_ev_to_er_ratio` 是当前 tick 的即时虚实比；`能量平衡平滑虚实比` 与 `能量平衡目标虚实比` 只有在启用可选旧闭环控制器时才代表真实控制目标。默认新口径下，更应把它看成“预测链整体是否偏薄”的诊断参考。' },
      { title: '如何与当前理论一起理解', desc: '默认理论不再要求把全局 EV/ER 直接压到单一目标值，因此这张图不应被当作主验收图。若它偏低，优先继续拆看传播、ER 诱发、残差结构命中和保活链，而不是先反推“系统必须把比值拉回 1.x”。' },
    ],
    energy_balance_gain_track: [
      { title: '真实影响因素：g 是旧闭环控制器的出手量', desc: '`能量平衡控制增益（更新后）` 是可选旧闭环控制器内部核心输出；`能量平衡 EV 传播缩放` 与 `能量平衡 ER 诱发缩放` 是它真正写回 HDB 的两条调制链。默认关闭时，这张图长期为 0 或 1 都是正常现象。' },
      { title: '如何读增益方向', desc: '只有在你明确打开旧闭环后，这张图才表示“控制器有没有出手”。默认新口径下，不需要用它来判断系统是否理论正确。' },
    ],
    energy_balance_effective_track: [
      { title: '真实影响因素：请求值与实际值不是一回事', desc: '`HDB 请求 EV 传播比例` / `HDB 请求 ER 诱发比例` 是旧闭环控制器本 tick 写入 HDB 配置的比例；`HDB 实际 ... 比例` 则是诱发引擎真正采用的运行时值。当前实现里这两条比例在运行时会被截断到 0~1。' },
      { title: '如何读饱和', desc: '若你主动启用旧闭环后，请求值继续上升，但实际值长期贴在 1.0，说明控制器已经把这两条链推到上限，再继续抬 `g` 也只会空转。此时应优先回查局部目标拓扑、记忆反馈落地、EV 保活/衰减，而不是继续怀疑控制器没工作。' },
    ],
    action_drive: [
      { title: '真实影响因素：驱动力生成公式', desc: '最大/平均驱动力来自行动节点竞争后的驱动力分布。若尝试很多但驱动力始终过低，应回查行动触发条件、奖励预期和当前注意焦点。' },
    ],
    action_nodes: [
      { title: '真实影响因素：行动网络是否活化', desc: '行动节点总数与活跃节点数反映当前可行动作库和当前实际被激活的子集。若节点数存在但活跃数长期过低，问题在驱动力或门控，不在动作库缺失。' },
    ],
    time_binding: [
      { title: '真实影响因素：时间绑定是否正常发生', desc: '时间桶更新数、时间属性绑定数、时间记忆样本数共同反映时间感受器是否在运作。若记忆样本有而绑定数很低，应优先查时间属性绑定条件。' },
    ],
    time_delayed: [
      { title: '真实影响因素：延迟任务表与容量限制', desc: '注册、更新、执行、清理、容量跳过、表大小一起反映延迟任务系统负载。若容量跳过非 0 或表大小持续堆高，应先回查任务容量和清理策略。' },
    ],
    map_energy: [
      { title: '真实影响因素：反馈能量是虚转实还是停留在虚能量', desc: '`map_total_er`、`map_total_ev`、`map_feedback_total_ev` 用来区分记忆赋能最后有没有真正沉到实能量。若反馈虚能量持续高但实能量始终不抬头，问题在反馈落地或状态池吸收。' },
    ],
    map_feedback_split: [
      { title: '真实影响因素：反馈是整包回放还是结构直投', desc: '`memory_feedback_applied_count` 是总反馈入口；`memory_feedback_packet_count` 表示有多少次预算被留在 stimulus packet 整包回放；`memory_feedback_structure_projection_count` 表示有多少次预算被拆给结构引用对象继续传播。若总反馈有了但结构直投长期接近 0，说明反馈仍偏“整包重放”。' },
      { title: '优先回查的真实参数', desc: '优先看 `observatory.memory_feedback_stimulus_packet_structure_projection_ratio`，它直接决定 stimulus packet 型记忆反馈中，有多少比例会被拆去做结构直投，而不是继续留在 packet 回放链。' },
    ],
    map_feedback_energy_split: [
      { title: '真实影响因素：反馈 EV 预算落在哪里', desc: '`memory_feedback_total_ev` 是总反馈 EV；`memory_feedback_packet_total_ev` 是整包回放链拿到的 EV；`memory_feedback_structure_projection_total_ev` 是结构直投链拿到的 EV。若总反馈不低但结构直投 EV 长期过薄，说明“沿结构引用继续局部预测”的链路仍然偏弱。' },
      { title: '如何判断该调哪边', desc: '如果 `pool_ev_to_er_ratio` 这个诊断口径长期偏低，同时 packet EV 明显高于 structure projection EV，优先提高 `memory_feedback_stimulus_packet_structure_projection_ratio`；若 EV 已不薄、但 packet EV 被压得太低，则反向回收该比例。' },
    ],
    map_feedback_projection_quality: [
      { title: '真实影响因素：结构引用是不是分得太散', desc: '`memory_feedback_structure_projection_attempted_count` 高、但 `memory_feedback_structure_projection_count` 很低，通常说明单条记忆材料挂了太多结构引用，导致单目标预算太薄，进投影前就被疲劳阈值裁掉。' },
      { title: '优先回查的真实链路', desc: '优先看 stimulus memory material 里的 `structure_energy_profile` 是否体现了本 tick 的真实命中强弱；如果结构权重仍近似均摊，再高的结构直投比例也会被平均稀释。其次看 `observatory.memory_feedback_structure_projection_max_targets` 是否过大，以及 `projection_fatigue_*` 是否把薄投影继续裁空。' },
      { title: '最直接的调参对象', desc: '`observatory.memory_feedback_structure_projection_max_targets` 控制“每条记忆反馈最多分给多少个结构目标”；`observatory.memory_feedback_stimulus_packet_structure_projection_ratio` 控制“总预算里有多少先拆给结构直投”。前者解决“分得太散”，后者解决“分给结构的总量太少”。' },
    ],
    hdb_growth: [
      { title: '可调参数：长期积累速率', desc: '优先结合 HDB 新建、切割、合并相关阈值观察，重点看是否“几乎不增长”或“增长过快导致噪声累积”。' },
    ],
    timing_main: [
      { title: '真实影响因素：主链大头模块', desc: '总逻辑耗时、结构级耗时、刺激级耗时、缓存中和耗时对应最主要的主链模块。应先看哪一条曲线抬头，再回到对应模块参数，而不要直接全局乱调。' },
    ],
    timing_detail: [
      { title: '真实影响因素：尾部耗时归因', desc: '细分性能图用于定位注意力、归纳记忆、认知拼接、IESM、情绪、时间感受器等尾部模块。若主图有抬头但主链四项解释不了，就看这里。' },
    ],
    diag_pool_apply: [
      { title: '真实影响因素：状态池落地方式', desc: '新增、更新、合并和能量增量共同说明刺激包是以“创建新对象”为主，还是以“更新已有对象”为主。若新增长期过高，可能存在融合不足；若合并长期过高，可能表示对象过度集中。' },
    ],
    diag_attention: [
      { title: '真实影响因素：候选规模、容量上限与能量预算', desc: '状态池候选条目数、CAM 上限、跳过记忆条目数、消耗能量和注意力能量预算一起决定注意力为什么“看不到”更多对象。候选多但上限小，问题在容量；净增偏高则看能量预算和滤波；候选少，则问题在上游筛选。' },
    ],
    diag_maintenance: [
      { title: '真实影响因素：维护前后净变化', desc: '维护前后活跃条目、高压条目和维护事件数共同反映维护是否真的在工作。若前后几乎不变但事件数很高，说明维护规则可能过软；若删得过猛，则可能过硬。' },
    ],
    diag_cfs_coverage: [
      { title: '真实影响因素：触发后覆盖面', desc: '这张图不是看感受强度，而是看每类感受触发后覆盖了多少对象、绑定了多少属性。若峰值存在但覆盖面很窄，说明绑定条件过严或对象分布过碎。' },
    ],
    diag_cfs_global_coverage: [
      { title: '真实影响因素：全局/正向感受是否真的落进状态池', desc: '这张图专门补主图看不出的一个问题：某类感受可能确实触发了，但 runtime 覆盖对象数或属性条目数太少，导致总量弱、投影弱、后续很难再被注意力接住。若对象数和属性数都为 0，才更像根本没落地。' },
    ],
    diag_echo_and_input: [
      { title: '真实影响因素：输入长度与残响介入', desc: '输入 flat token、原始输入长度、残响当前轮数、残响池大小一起反映文本输入与 echo 机制的整体负载。若残响长期不参与，可回查 echo 策略；若残响池过大，则回查清理与衰减。' },
    ],
    diag_cs_detail: [
      { title: '真实影响因素：认知拼接细部账本', desc: '这里看的是认知拼接在更细粒度上的运行账本，不是单纯结果图。适合排查为什么种子能来、候选能来，但最终产出和强化之间断层。' },
    ],
    diag_time_tail: [
      { title: '可调参数：延迟任务容量', desc: '`time_sensor.delayed_task_capacity`。若“容量跳过次数”非零，应优先调这里。' },
      { title: '可调参数：时间记忆采样数', desc: '`time_sensor.memory_sample_limit`。若时间取样记忆数长期过小或过大，可优先调这里。' },
    ],
    diag_internal_tail: [
      { title: '真实影响因素：细节疲劳窗口', desc: '`hdb.main.py` 中的 `internal_resolution_detail_fatigue_window`、`internal_resolution_detail_fatigue_start`、`internal_resolution_detail_fatigue_full`、`internal_resolution_detail_fatigue_min_scale`、`internal_resolution_detail_fatigue_beta`。若同类细节被反复抽到后迅速变瘦，这组参数直接参与限制。' },
      { title: '真实影响因素：锚点与丰富度偏置', desc: '`internal_resolution_stable_anchor_count`、`internal_resolution_anchor_ratio`、`internal_resolution_rich_structure_ratio`、`internal_resolution_rich_structure_min_units`、`internal_resolution_structure_richness_power`。它们决定细节预算更偏向锚点，还是偏向更“丰富”的结构。' },
    ],
    diag_timing_tail: [
      { title: '可调参数：按慢模块回溯', desc: '该图用于继续追踪尾部耗时，看到某个 timing 项异常后，应回到该模块的主参数而不是在这里直接拍脑袋调。' },
    ],
    diag_cs_tail: [
      { title: '真实影响因素：是否只是启用但未形成输出', desc: '`cs_enabled` 只表示功能开关打开，不表示真的发生拼接。因此它不应进图；真正该看的是 `cs_candidate_count`、`cs_action_count`、`cs_concat_count`、`cs_created_count`、`cs_extended_count`、`cs_merged_count`。' },
      { title: '真实影响因素：CS 兼容链路 vs 事件层输出', desc: '新版默认主链不是 CS；只有显式开启 residual/CS 对照时，才需要深入看 `cs_action_count`。若它非零但 `cs_created_count/cs_extended_count/cs_merged_count` 为 0，往往表示动作主要落在 `cs_concat_count` 对应的普通结构拼接，而不是事件层失效。' },
    ],
    diag_map_detail: [
      { title: '真实影响因素：MAP 条目来源', desc: '`map_apply_count`、`map_feedback_count`、`map_count` 先受回忆链路与记忆激活条目数影响。若条目数低，先查 recall / memory activation，不是先调能量。' },
      { title: '真实影响因素：反馈能量链路', desc: '`map_feedback_total_ev`、`map_total_er`、`map_total_ev` 用来区分“有反馈但只停留在虚能量”还是“已经沉到实能量”。如果反馈数有了但总实能量上不来，问题在反馈落地或状态池吸收链。' },
    ],
    map_scale: [
      { title: '真实影响因素：回忆命中与激活规模', desc: '这张图里的“记忆赋能条目数 / 记忆反馈条目数 / 记忆赋能应用次数”不是孤立参数，它们先受回忆是否命中、记忆激活池是否形成、以及当前 tick 是否真的发生赋能应用影响。' },
      { title: '如何读这张图', desc: '如果“条目数”高但“应用次数”低，说明有记忆候选却没真正打进状态池；如果“反馈条目数”低，优先排查记忆反馈链是否被上游回忆命中率限制。' },
    ],
    diag_cfs_tail: [
      { title: '真实影响因素：绑定对象数量', desc: '`...live_item_count` 与 `...live_attribute_count` 先回答“有没有真正绑定到状态池对象”。若事件计数有、但绑定对象数长期为 0，优先排查绑定条件而不是只看峰值。' },
      { title: '真实影响因素：ER / EV 落点', desc: '`cfs_correctness_live_total_er`、`cfs_dissonance_live_total_ev` 这类指标分别表示对应感受当前主要沉在实能量还是虚能量。若峰值高但总量始终起不来，通常是绑定后维持链或衰减链过强。' },
    ],
    diag_cs_detail: [
      { title: '真实影响因素：种子与动作转化率', desc: '`cs_seed_event_count`、`cs_seed_structure_count` 对照 `cs_candidate_count`、`cs_action_count`、`cs_concat_count`、`cs_created_count` 看的是“种子 -> 候选 -> 动作 -> 结构拼接/事件层”的转化率。真正异常是转化断层，不是单看某个点值。' },
      { title: '真实影响因素：叙事输出是否尚未成熟', desc: '`cs_narrative_top_total_energy`、`cs_narrative_top_grasp` 长期为 0，并不只意味着“没事件”；也可能是旧 CAM 里没有成熟事件、post-CS 事件还没过 grasp 能量门槛，或主叙事对象虽有能量但还没形成稳定把握。应结合 `cs_event_grasp_*` 系列一起判断。' },
    ],
    diag_misc_tail: [
      { title: '说明', desc: '这是混合兜底图，不建议直接据此调参。应先按系列名称回到对应模块，再查看该模块的主图和参数。' },
    ],
  };
  const rows = [
    { title: '图表覆盖指标', desc: '当前图覆盖：' + ((visibleKeys.length ? visibleKeys : keys).map(metricLabel).join('、') || '-') },
    ...(missingExportKeys.length ? [{
      title: '当前运行缺字段',
      desc: '这次运行的 metrics.jsonl 尚未包含：' + missingExportKeys.map(metricLabel).join('、') + '。这通常表示它是较早生成的旧 run，需要重跑后才能看到新兼容指标，不代表当前链路本身没有数据。',
    }] : []),
    ...(explainMap[cfg?.id] ? [{ title: '图表意义', desc: explainMap[cfg.id] }] : []),
    ...asArray(factorMap[cfg?.id]),
  ];
  return `<details class="details-panel exp-chart-factors"><summary><h4>主要影响因素与调参线索</h4></summary><div class="details-body">${rows.map((r)=>miniRow(r.title, r.desc)).join('')}</div></details>`;
}

function bindChartHover(container) {
  const tip = container.querySelector('.chart-hover-tip');
  if (!tip) return;
  container.querySelectorAll('[data-tip]').forEach((node)=> {
    node.addEventListener('mouseenter', ()=> {
      tip.textContent = node.getAttribute('data-tip') || '';
      tip.hidden = false;
    });
    node.addEventListener('mouseleave', ()=> {
      tip.hidden = true;
    });
  });
}

function openChartModal(cfg) {
  if (!DOM.expChartModal) return;
  const rows = STATE.lastMetricsRows;
  const visibleSeries = getRenderableSeries(rows, cfg?.series || []);
  DOM.expChartModal.hidden = false;
  DOM.expChartModal.classList.remove('hidden');
  DOM.expChartModal.setAttribute('aria-hidden', 'false');
  if (DOM.expChartModalTitle) DOM.expChartModalTitle.textContent = String(cfg?.title || '图表放大查看');
  if (DOM.expChartModalSubtitle) DOM.expChartModalSubtitle.textContent = String(cfg?.subtitle || '');
  if (DOM.expChartModalDesc) DOM.expChartModalDesc.textContent = String(cfg?.description || '');
  if (DOM.expChartModalChart) renderChart(DOM.expChartModalChart, { rows, series: visibleSeries, chartType: cfg?.chartType || 'line', title: cfg?.title || '' });
  if (DOM.expChartModalStats) {
    DOM.expChartModalStats.innerHTML = asArray(visibleSeries).map((s)=>{
      const st = summarizeMetric(rows, s.key);
      return st ? miniRow(s.name || s.key, formatMetricDigest(st, s.key)) : '';
    }).join('');
  }
  if (DOM.expChartModalFactors) DOM.expChartModalFactors.innerHTML = renderChartFactors(cfg);
}
function closeChartModal() {
  if (!DOM.expChartModal) return;
  DOM.expChartModal.hidden = true;
  DOM.expChartModal.classList.add('hidden');
  DOM.expChartModal.setAttribute('aria-hidden', 'true');
  if (DOM.expChartModalChart) DOM.expChartModalChart.innerHTML = '';
}
function renderChartDeck(){
  if (!DOM.expChartDeck) return;
  const rows = normalizeMetricRows(STATE.lastMetricsRows);
  STATE.lastMetricsRows = rows;
  if (!rows.length) {
    DOM.expChartDeck.innerHTML = emptyState('当前运行还没有统计数据，请先选择一条运行记录。');
    return;
  }
  const allConfigs = CHART_CONFIGS.concat(buildDiagnosticChartConfigs(rows));
  const chartStates = new Map(allConfigs.map((cfg)=> [cfg.id, getChartSeriesState(rows, cfg.series)]));
  DOM.expChartDeck.innerHTML = CHART_SECTIONS.map((section)=> {
    const items = allConfigs.filter((cfg)=> cfg.section === section.id);
    if (!items.length) return '';
    const activeItems = [];
    const hiddenItems = [];
    items.forEach((cfg)=> {
      const chartState = chartStates.get(cfg.id) || getChartSeriesState(rows, cfg.series);
      if (getHiddenChartReason(chartState)) hiddenItems.push(cfg);
      else activeItems.push(cfg);
    });
    if (!activeItems.length && !hiddenItems.length) return '';
    const cards = activeItems.map((cfg)=> {
      const chartState = chartStates.get(cfg.id) || getChartSeriesState(rows, cfg.series);
      const visibleSeries = chartState.visibleSeries;
      const stats = visibleSeries.map((s)=> { const st = summarizeMetric(rows, s.key); return st ? miniRow(s.name, formatMetricDigest(st, s.key)) : ''; }).join('');
      const canOpen = visibleSeries.length > 0;
      const actionHtml = canOpen
        ? '<div class="exp-chart-actions"><button type="button" class="ghost exp-chart-open-btn" data-chart-open="' + esc(cfg.id) + '">放大查看</button></div>'
        : '';
      const clickableClass = canOpen ? ' clickable' : '';
      return '<article class="subpanel exp-chart-card"><div class="exp-chart-head"><div class="section-head"><div><h4>' + esc(cfg.title) + '</h4><div class="meta">' + esc(cfg.subtitle || '') + '</div></div></div>' + actionHtml + '</div><p class="exp-chart-description">' + esc(cfg.description || '') + '</p><div id="chart_' + esc(cfg.id) + '" class="chart-wrap' + clickableClass + ' exp-spaced-top"></div><div class="stack exp-spaced-top exp-chart-stats-scroll">' + stats + '</div>' + renderChartFactors(cfg) + '</article>';
    }).join('');
    const hiddenPanel = hiddenItems.length
      ? '<details class="details-panel exp-hidden-chart-list"><summary><div><h4>本节暂不显示的图表</h4><div class="meta">' + esc(`${hiddenItems.length} 张图表在当前运行中全零、缺字段或没有可绘制信号`) + '</div></div></summary><div class="details-body stack">' + hiddenItems.map((cfg)=> renderHiddenChartRow(cfg, chartStates.get(cfg.id) || getChartSeriesState(rows, cfg.series))).join('') + '</div></details>'
      : '';
    const gridHtml = cards
      ? '<div class="exp-chart-grid' + (section.diagnostic ? ' exp-chart-grid-diagnostic' : '') + '">' + cards + '</div>'
      : emptyState('本节当前没有可绘制图表。可展开下方清单查看被隐藏的全零或缺字段图表。');
    if (section.diagnostic) {
      return '<details class="details-panel exp-chart-group-card"><summary><div><h3>' + esc(section.title) + '</h3><div class="meta">' + esc(section.description || '') + '</div></div></summary><div class="details-body">' + gridHtml + hiddenPanel + '</div></details>';
    }
    return '<section class="subpanel exp-chart-group-card"><div class="section-head"><div><h3>' + esc(section.title) + '</h3><div class="meta">' + esc(section.description || '') + '</div></div></div>' + gridHtml + hiddenPanel + '</section>';
  }).join('');
  allConfigs.forEach((cfg)=> {
    const chartState = chartStates.get(cfg.id) || getChartSeriesState(rows, cfg.series);
    if (chartState.allZero) return;
    renderChart(byId('chart_' + cfg.id), { rows, series: chartState.visibleSeries, chartType: cfg.chartType || 'line', title: cfg.title });
  });
  DOM.expChartDeck.querySelectorAll('[data-chart-open]').forEach((el)=> el.addEventListener('click', ()=> {
    const cfg = allConfigs.find((item)=> item.id === el.getAttribute('data-chart-open'));
    if (cfg) openChartModal(cfg);
  }));
  DOM.expChartDeck.querySelectorAll('.chart-wrap.clickable').forEach((el)=> el.addEventListener('click', ()=> {
    const id = String(el.id || '').replace(/^chart_/, '');
    const cfg = allConfigs.find((item)=> item.id === id);
    if (cfg) openChartModal(cfg);
  }));
}

function renderPoolEnergyTopLine(items, energyKey) {
  const key = String(energyKey || '').toLowerCase() === 'ev' ? 'ev' : 'er';
  const label = key === 'ev' ? 'EV' : 'ER';
  const otherKey = key === 'ev' ? 'er' : 'ev';
  return asArray(items).slice(0, 5).map((it, idx)=> {
    const rank = asNumber(it?.rank, idx + 1);
    const display = truncateText(it?.display || it?.display_text || it?.ref_object_id || it?.item_id || '-', 52);
    const about = truncateText(it?.about || it?.anchor_display || it?.target_display || it?.context_text || '', 40);
    const type = it?.ref_object_type ? `/${it.ref_object_type}` : '';
    const aboutText = about ? ` <- ${about}` : '';
    const priorityText = Number.isFinite(Number(it?.attention_priority)) && Number(it?.attention_priority) !== 0
      ? ` · P ${formatMaybe(it?.attention_priority, 4)}`
      : '';
    const bonusText = Number.isFinite(Number(it?.reward_action_bonus)) && Number(it?.reward_action_bonus) !== 0
      ? ` · 偏置 ${formatMaybe(it?.reward_action_bonus, 4)}`
      : '';
    const fatigueText = Number.isFinite(Number(it?.repeat_attention_penalty)) && Number(it?.repeat_attention_penalty) !== 0
      ? ` · 疲劳 ${formatMaybe(it?.repeat_attention_penalty, 4)}`
      : '';
    return `${rank}. ${display}${type}${aboutText} · ${label} ${formatMaybe(it?.[key], 4)} · ${otherKey.toUpperCase()} ${formatMaybe(it?.[otherKey], 4)}${priorityText}${bonusText}${fatigueText}`;
  }).join('\n');
}

function isAtomicFeatureSaTopRow(row) {
  const type = String(row?.ref_object_type || row?.object_type || row?.type || '').trim().toLowerCase();
  if (type !== 'sa') return false;
  let display = readableApText(row?.display || row?.display_text || row?.text || '').trim();
  if (display.startsWith('{') && display.endsWith('}') && display.length >= 2) {
    display = display.slice(1, -1).trim();
  }
  if (!display) return true;
  if (display.includes(':') || display.includes('：') || display.includes('行动节点') || display.includes('时间感受')) {
    return false;
  }
  return Array.from(display).length <= 2;
}

function structureRowsFromDashboardTop(rows, limit = 18) {
  return asArray(rows)
    .filter((it)=> !isAtomicFeatureSaTopRow(it))
    .slice(0, Math.max(1, Number(limit) || 18));
}

function structureTopItemsOfMetricRow(row, key) {
  const metricKey = String(key || '').trim();
  const structureKey = metricKey === 'pool_ev_top5' ? 'pool_ev_structure_top5' : 'pool_er_structure_top5';
  const structureRows = asArray(row?.[structureKey]);
  if (!structureRows.length && Number(row?.[`${structureKey}_same_as_top5`] || 0) > 0) return asArray(row?.[metricKey]);
  return structureRows.length ? structureRows : asArray(row?.[metricKey]);
}

function renderPoolEnergyTopNarrative(rows) {
  const samples = asArray(rows)
    .filter((row)=> structureTopItemsOfMetricRow(row, 'pool_er_top5').length || structureTopItemsOfMetricRow(row, 'pool_ev_top5').length || asArray(row?.attention_top5).length)
    .slice(-10);
  if (!samples.length) return '';
  const intro = miniRow(
    '结构 ER/EV 与注意 Top5 连续观察',
    `展示最近 ${samples.length} 个有峰值数据的 tick。ER/EV 默认优先使用排除原子特征 SA 后的结构 Top，避免把外源字符证据误读成旧上下文残差；注意 Top5 则更接近这一拍真正被分配注意资源的对象。`
  );
  const body = samples.map((row)=> {
    const erLine = renderPoolEnergyTopLine(structureTopItemsOfMetricRow(row, 'pool_er_top5'), 'er') || '暂无 ER 结构峰值对象';
    const evLine = renderPoolEnergyTopLine(structureTopItemsOfMetricRow(row, 'pool_ev_top5'), 'ev') || '暂无 EV 结构峰值对象';
    const attentionLine = renderPoolEnergyTopLine(row.attention_top5, 'er') || '暂无注意力峰对象';
    const input = truncateText(row.input_text_preview || row.input_queue_tick_text_preview || '', 80);
    const title = `tick ${row.tick_index ?? '-'} · ER 结构证据峰 / EV 结构预期峰`;
    const desc = [
      input ? `输入：${input}` : '',
      `ER 结构 Top5:\n${erLine}`,
      `EV 结构 Top5:\n${evLine}`,
      `注意 Top5:\n${attentionLine}`,
    ].filter(Boolean).join('\n');
    return miniRow(title, desc);
  }).join('');
  return intro + body;
}

function renderMetricNarrative() {
  if (!DOM.expMetricsNarrative) return;
  const rows = asArray(STATE.lastMetricsRows);
  if (!rows.length) {
    DOM.expMetricsNarrative.innerHTML = emptyState('当前还没有可叙述的 metrics 数据。');
    return;
  }
  const last = rows.at(-1) || {};
  const first = rows[0] || {};
  const mode = currentMetricPerspective();
  const timing = summarizeMetric(rows, 'timing_total_logic_ms');
  const ext = summarizeMetric(rows, 'external_sa_count');
  const internal = summarizeMetric(rows, 'internal_sa_count');
  const cfs = summarizeMetric(rows, 'cfs_dissonance_max');
  const csCandidate = summarizeMetric(rows, 'cs_candidate_count');
  const csAction = summarizeMetric(rows, 'cs_action_count');
  const csConcat = summarizeMetric(rows, 'cs_concat_count');
  const csCreated = summarizeMetric(rows, 'cs_created_count');
  const csExtended = summarizeMetric(rows, 'cs_extended_count');
  const summaryHtml = renderMiniRowSpecs(rows, [
    { alwaysShow: true, title: '当前统计口径', desc: mode === 'aggregate' ? `整场聚合 | tick ${first.tick_index ?? '-'} ~ ${last.tick_index ?? '-'} | 用于判断整场是否真的发生过某类现象。` : `最后一拍 | tick ${last.tick_index ?? '-'} | 用于观察当前这一拍的即时状态。` },
    { alwaysShow: true, title: mode === 'aggregate' ? '整场运行摘要' : '最新运行摘要', desc: mode === 'aggregate' ? `外源 SA 累计 ${formatCount(ext?.sum || 0)} | 内源 SA 累计 ${formatCount(internal?.sum || 0)} | 总逻辑累计 ${formatDuration(timing?.sum || 0)}` : `tick ${last.tick_index ?? '-'} | 外源 SA ${formatCount(last.external_sa_count || 0)} | 内源 SA ${formatCount(last.internal_sa_count || 0)} | 总逻辑耗时 ${formatMaybe(last.timing_total_logic_ms || 0, 1)} ms` },
    { keys: ['timing_total_logic_ms'], title: '性能概览', desc: mode === 'aggregate' ? `总逻辑耗时：累计 ${formatDuration(timing?.sum || 0)} | 平均 ${formatMaybe(timing?.mean || 0,1)} ms | 峰值 ${formatMaybe(timing?.max || 0,1)} ms` : `总逻辑耗时：最小 ${formatMaybe(timing?.min || 0,1)} | 最大 ${formatMaybe(timing?.max || 0,1)} | 平均 ${formatMaybe(timing?.mean || 0,1)} | 最新 ${formatMaybe(timing?.latest || 0,1)}` },
    { keys: ['external_sa_count','internal_sa_count'], title: '刺激规模概览', desc: mode === 'aggregate' ? `外源 SA：累计 ${formatCount(ext?.sum || 0)} | 平均 ${formatMaybe(ext?.mean || 0,1)}；内源 SA：累计 ${formatCount(internal?.sum || 0)} | 平均 ${formatMaybe(internal?.mean || 0,1)}` : `外源 SA：最新 ${formatMaybe(ext?.latest || 0,0)} | 平均 ${formatMaybe(ext?.mean || 0,1)}；内源 SA：最新 ${formatMaybe(internal?.latest || 0,0)} | 平均 ${formatMaybe(internal?.mean || 0,1)}` },
    { keys: ['cs_candidate_count','cs_action_count','cs_concat_count','cs_created_count','cs_extended_count'], title: '认知拼接概览', desc: mode === 'aggregate' ? `候选累计 ${formatCount(csCandidate?.sum || 0)} | 动作累计 ${formatCount(csAction?.sum || 0)} | 上下文拼接 ${formatCount(csConcat?.sum || 0)} | 新建 ${formatCount(csCreated?.sum || 0)} | 扩展 ${formatCount(csExtended?.sum || 0)}` : `候选最新 ${formatCount(csCandidate?.latest || 0)} | 动作最新 ${formatCount(csAction?.latest || 0)} | 上下文拼接最新 ${formatCount(csConcat?.latest || 0)} | 新建最新 ${formatCount(csCreated?.latest || 0)} | 扩展最新 ${formatCount(csExtended?.latest || 0)}` },
    { keys: ['cfs_dissonance_max'], title: '认知感受概览', desc: mode === 'aggregate' ? `违和感峰值：上界 ${formatMaybe(cfs?.max || 0,4)} | 平均 ${formatMaybe(cfs?.mean || 0,4)} | 最新 ${formatMaybe(cfs?.latest || 0,4)}` : `违和感峰值：最小 ${formatMaybe(cfs?.min || 0,4)} | 最大 ${formatMaybe(cfs?.max || 0,4)} | 平均 ${formatMaybe(cfs?.mean || 0,4)} | 最新 ${formatMaybe(cfs?.latest || 0,4)}` },
  ]);
  DOM.expMetricsNarrative.innerHTML = renderPoolEnergyTopNarrative(rows) + summaryHtml;
}

function summarizeMetric(rows, key) {
  const vals = asArray(rows).map((row)=> Number(row?.[key])).filter((v)=> Number.isFinite(v));
  if (!vals.length) return null;
  const sorted = vals.slice().sort((a,b)=> a-b);
  const sum = vals.reduce((s,v)=> s+v, 0);
  const mean = sum / vals.length;
  const median = sorted.length % 2 ? sorted[Math.floor(sorted.length/2)] : (sorted[sorted.length/2 - 1] + sorted[sorted.length/2]) / 2;
  return {
    sum,
    min: sorted[0] || 0,
    max: sorted[sorted.length - 1] || 0,
    mean,
    median,
    latest: vals[vals.length - 1] || 0,
    delta: (vals[vals.length - 1] || 0) - (vals[0] || 0),
  };
}

function renderProtocol(data) {
  const doc = data || {};
  if (DOM.expProtocolCards) {
    DOM.expProtocolCards.innerHTML = [
      metricCard('协议版本', doc.version || '-', '实验数据集的当前公开协议说明'),
      metricCard('推荐格式', doc.recommended_format || 'YAML / JSONL', '默认建议 YAML 模板'),
      metricCard('导入格式数', formatCount(asArray(doc.formats || ['yaml','jsonl']).length), '支持 YAML / JSONL 等'),
    ].join('');
  }
  if (DOM.expProtocolYamlFields) {
    const rows = asArray(doc.yaml_required_fields).concat(asArray(doc.yaml_optional_fields)).map((x)=> miniRow(x.field || x.name || '-', x.meaning || x.desc || '-'));
    DOM.expProtocolYamlFields.innerHTML = rows.join('') || emptyState('暂无 YAML 标准字段。');
  }
  if (DOM.expProtocolJsonlFields) {
    DOM.expProtocolJsonlFields.innerHTML = asArray(doc.jsonl_fields).map((x)=> miniRow(x.field || x.name || '-', x.meaning || x.desc || '-')).join('') || emptyState('暂无 JSONL 标准字段。');
  }
  if (DOM.expProtocolYamlExample) DOM.expProtocolYamlExample.textContent = String(doc.yaml_example || '');
  if (DOM.expProtocolJsonlExample) DOM.expProtocolJsonlExample.textContent = String(doc.jsonl_example || '');
}

async function refreshProtocol(silent=false){
  try {
    const res = await apiGet('/api/experiment/dataset_protocol');
    STATE.protocol = res.data || null;
    renderProtocol(STATE.protocol);
    if(!silent) setFeedback(DOM.expJobFeedback, '已刷新标准说明。', 'ok');
  } catch(error){
    if (DOM.expProtocolCards) DOM.expProtocolCards.innerHTML = emptyState(`标准说明加载失败：${error.message}`);
    if(!silent) setFeedback(DOM.expJobFeedback, `刷新标准说明失败：${error.message}`, 'err');
    throw error;
  }
}

function renderDatasets() {
  const items = asArray(STATE.datasets?.datasets);
  if (DOM.expDatasetSelect) {
    DOM.expDatasetSelect.innerHTML = items.map((d)=> `<option value="${esc(datasetKey(d))}">${esc(d.meta?.dataset_id || d.rel_path || datasetKey(d))}</option>`).join('');
    if (!STATE.selectedDatasetKey && items.length) STATE.selectedDatasetKey = datasetKey(items[0]);
    if (STATE.selectedDatasetKey && !items.some((d)=> datasetKey(d) === STATE.selectedDatasetKey) && items.length) STATE.selectedDatasetKey = datasetKey(items[0]);
    DOM.expDatasetSelect.value = STATE.selectedDatasetKey;
  }
  const ds = items.find((d)=> datasetKey(d) === STATE.selectedDatasetKey) || items[0] || null;
  const overrideKeys = asArray(ds?.meta?.app_config_override_keys);
  if (DOM.expDatasetMeta) DOM.expDatasetMeta.textContent = ds ? `source=${ds.source || '-'} | dataset_id=${ds.meta?.dataset_id || '-'} | estimated_ticks=${ds.meta?.estimated_ticks ?? '-'}` : '尚未选择数据集。';
  if (DOM.expDatasetOverviewCards) {
    DOM.expDatasetOverviewCards.innerHTML = ds ? [
      metricCard('数据集 ID', ds.meta?.dataset_id || '-', ds.rel_path || '-'),
      metricCard('时间基准', ds.meta?.time_basis || '-', `来源：${ds.source || '-'}`),
      metricCard('估计 Tick', formatCount(ds.meta?.estimated_ticks || 0), `标签 Tick：${formatCount(ds.meta?.labeled_ticks || 0)}`),
      metricCard('用途 / 标题', ds.meta?.title || '-', ds.meta?.description || '暂无说明'),
      metricCard('实验目标', ds.meta?.experiment_goal || '-', asArray(ds.meta?.evaluation_dimensions).slice(0,2).join('；') || '暂无目标说明'),
      metricCard('运行开关', overrideKeys.length ? `${formatCount(overrideKeys.length)} 项` : '默认', overrideKeys.slice(0,3).join('；') || '无数据集级运行覆写'),
    ].join('') : emptyState('暂无可用数据集。');
  }
}

async function refreshDatasets(silent=false){
  try {
    const res = await apiGet('/api/experiment/datasets', 30000);
    STATE.datasets = res.data || null;
    renderDatasets();
    if(!silent) setFeedback(DOM.expJobFeedback, '已刷新数据集列表。', 'ok');
  } catch(error){
    if (DOM.expDatasetOverviewCards) DOM.expDatasetOverviewCards.innerHTML = emptyState(`数据集加载失败：${error.message}`);
    if(!silent) setFeedback(DOM.expJobFeedback, `刷新数据集失败：${error.message}`, 'err');
    throw error;
  }
}

async function previewDataset(){
  const ref = getSelectedDatasetRef();
  if(!ref) return setFeedback(DOM.expJobFeedback, '请先选择数据集。', 'err');
  try {
    const res = await apiPost('/api/experiment/datasets/preview', { dataset_ref: ref, limit: 24 });
    const data = res.data || {};
    const overrideKeys = asArray(data.overview?.app_config_override_keys);
    if(DOM.expDatasetPreviewMeta) DOM.expDatasetPreviewMeta.textContent = `预览 ${formatCount(asArray(data.preview_ticks).length)}/${formatCount(data.total_ticks || 0)} tick${overrideKeys.length ? ` | 运行开关 ${formatCount(overrideKeys.length)} 项` : ''}`;
    if(DOM.expDatasetPreview) {
      const overrideRow = overrideKeys.length
        ? miniRow('运行开关', `本数据集会在单次 run 内临时覆写：${overrideKeys.join(', ')}`)
        : '';
      const tickRows = asArray(data.preview_ticks).map((t)=> miniRow(`tick ${t.tick_index ?? '-'} · ep ${t.episode_id || '-'}`, `输入：${t.input_text || '（空 tick）'}\n标签：${asArray(t.tags).join(', ') || '-'}`)).join('');
      DOM.expDatasetPreview.innerHTML = `${overrideRow}${tickRows}` || emptyState('暂无预览数据。');
    }
  } catch(error){
    setFeedback(DOM.expJobFeedback, `预览失败：${error.message}`, 'err');
  }
}

async function expandDataset(){
  const ref = getSelectedDatasetRef();
  if(!ref) return setFeedback(DOM.expJobFeedback, '请先选择数据集。', 'err');
  try {
    const res = await apiPost('/api/experiment/datasets/expand', { dataset_ref: ref, limit: 120 });
    const data = res.data || {};
    if(DOM.expDatasetPreviewMeta) DOM.expDatasetPreviewMeta.textContent = `展开 ${formatCount(asArray(data.expanded_ticks).length)}/${formatCount(data.total_ticks || 0)} tick`;
    if(DOM.expDatasetPreview) DOM.expDatasetPreview.innerHTML = asArray(data.expanded_ticks).map((t)=> miniRow(`tick ${t.tick_index ?? '-'} · ep ${t.episode_id || '-'}`, `输入：${t.input_text || '（空 tick）'}\n标签：${asArray(t.tags).join(', ') || '-'}`)).join('') || emptyState('暂无展开数据。');
  } catch(error){
    setFeedback(DOM.expJobFeedback, `展开失败：${error.message}`, 'err');
  }
}

async function importDataset(){
  const filename = String(DOM.expImportFilename?.value || '').trim();
  const format = String(DOM.expImportFormat?.value || '').trim();
  const content = String(DOM.expImportContent?.value || '');
  if (!filename || !format || !content.trim()) return setFeedback(DOM.expImportFeedback || DOM.expJobFeedback, '请填写文件名、格式与内容。', 'err');
  try {
    await apiPost('/api/experiment/datasets/import', { filename, format, content });
    setFeedback(DOM.expImportFeedback || DOM.expJobFeedback, '已导入数据集。', 'ok');
    await refreshDatasets(true);
  } catch(error){
    setFeedback(DOM.expImportFeedback || DOM.expJobFeedback, `导入失败：${error.message}`, 'err');
  }
}

async function clearRuntime(){ try { await apiPost('/api/experiment/runtime/clear', {}); setFeedback(DOM.expClearFeedback || DOM.expJobFeedback, '已清空运行态。', 'ok'); } catch(error){ setFeedback(DOM.expClearFeedback || DOM.expJobFeedback, `清空运行态失败：${error.message}`, 'err'); } }
async function clearHdb(){ try { await apiPost('/api/experiment/hdb/clear', {}); setFeedback(DOM.expClearFeedback || DOM.expJobFeedback, '已清空 HDB。', 'ok'); } catch(error){ setFeedback(DOM.expClearFeedback || DOM.expJobFeedback, `清空 HDB 失败：${error.message}`, 'err'); } }
async function clearAll(){ try { await apiPost('/api/experiment/clear_all', {}); setFeedback(DOM.expClearFeedback || DOM.expJobFeedback, '已执行全清理。', 'ok'); } catch(error){ setFeedback(DOM.expClearFeedback || DOM.expJobFeedback, `全清理失败：${error.message}`, 'err'); } }

function renderMetricsOverview(){
  const rows = asArray(STATE.lastMetricsRows);
  const mode = currentMetricPerspective();
  if (DOM.expMetricsOverviewCards) {
    const last = rows.at(-1) || {};
    const first = rows[0] || {};
    const ext = summarizeMetric(rows, 'external_sa_count');
    const timing = summarizeMetric(rows, 'timing_total_logic_ms');
    const csCandidate = summarizeMetric(rows, 'cs_candidate_count');
    const csAction = summarizeMetric(rows, 'cs_action_count');
    const csConcat = summarizeMetric(rows, 'cs_concat_count');
    const csCreated = summarizeMetric(rows, 'cs_created_count');
    const csExtended = summarizeMetric(rows, 'cs_extended_count');
    const actionAttempt = summarizeMetric(rows, 'action_attempted_count');
    const actionExecuted = summarizeMetric(rows, 'action_executed_count');
    const localHit = summarizeMetric(rows, 'action_local_lookup_hit_count');
    const localTextFallbackHit = summarizeMetric(rows, 'action_local_lookup_text_fallback_hit_count');
    const localScale = summarizeMetric(rows, 'action_local_drive_scale_mean');
    const localRewardBonus = summarizeMetric(rows, 'action_local_reward_drive_bonus_total');
    const localPunishPenalty = summarizeMetric(rows, 'action_local_punish_drive_penalty_total');
    const weatherLocalHit = summarizeMetric(rows, 'action_local_lookup_hit_count_weather_stub');
    const weatherLocalTextFallbackHit = summarizeMetric(rows, 'action_local_lookup_text_fallback_hit_count_weather_stub');
    const weatherLocalTargetMissing = summarizeMetric(rows, 'action_local_target_missing_count_weather_stub');
    const weatherLocalScale = summarizeMetric(rows, 'action_local_drive_scale_mean_weather_stub');
    const weatherLocalRewardBonus = summarizeMetric(rows, 'action_local_reward_drive_bonus_total_weather_stub');
    const weatherLocalPunishPenalty = summarizeMetric(rows, 'action_local_punish_drive_penalty_total_weather_stub');
    const weatherActionAttempt = summarizeMetric(rows, 'action_attempted_weather_stub');
    const weatherActionExecuted = summarizeMetric(rows, 'action_executed_weather_stub');
    const weatherTriggerCount = summarizeMetric(rows, 'iesm_action_trigger_weather_stub_count');
    const weatherTriggerTargeted = summarizeMetric(rows, 'iesm_action_trigger_targeted_weather_stub_count');
    const weatherTriggerMissing = summarizeMetric(rows, 'iesm_action_trigger_target_missing_weather_stub_count');
    const teacherApplied = summarizeMetric(rows, 'teacher_applied_count');
    const rewardLive = summarizeMetric(rows, 'reward_signal_live_total_energy');
    const punishLive = summarizeMetric(rows, 'punish_signal_live_total_energy');
    const expectationVerified = summarizeMetric(rows, 'cfs_expectation_verified_count');
    const pressureVerified = summarizeMetric(rows, 'cfs_pressure_verified_count');
    const iesmEmotionUpdate = summarizeMetric(rows, 'iesm_emotion_update_abs_total');
    const poolComplexity = summarizeMetric(rows, 'complexity_score');
    const poolCoreComplexity = summarizeMetric(rows, 'core_complexity_score');
    const poolPeakCount = summarizeMetric(rows, 'effective_peak_count');
    const poolCorePeakCount = summarizeMetric(rows, 'core_effective_peak_count');
    DOM.expMetricsOverviewCards.innerHTML = renderMetricCardSpecs(
      rows,
      mode === 'aggregate'
        ? [
            { alwaysShow: true, label: '统计口径', value: '整场聚合', note: `tick ${first.tick_index ?? '-'} ~ ${last.tick_index ?? '-'} | 避免被最后一拍误导` },
            { alwaysShow: true, label: '已加载行数', value: formatCount(rows.length), note: `下采样步长 ${formatCount(STATE.lastMetricsEvery)}` },
            { alwaysShow: true, label: '最新刷新', value: formatTime(STATE.lastMetricsFetchMs), note: '图表与摘要使用同一份 rows' },
            { keys: ['external_sa_count'], label: '外源 SA 累计', value: formatCount(ext?.sum || 0), note: `平均 ${formatMaybe(ext?.mean || 0, 1)} | 最新 ${formatCount(ext?.latest || 0)}` },
            { keys: ['complexity_score','core_complexity_score','effective_peak_count','core_effective_peak_count'], label: '复杂度双口径', value: `全量 ${formatMaybe(poolComplexity?.mean || 0, 3)} | 核心 ${formatMaybe(poolCoreComplexity?.mean || 0, 3)}`, note: `峰数 全量 ${formatMaybe(poolPeakCount?.mean || 0, 2)} | 核心 ${formatMaybe(poolCorePeakCount?.mean || 0, 2)}` },
            { keys: ['cs_candidate_count','cs_action_count','cs_concat_count','cs_created_count','cs_extended_count'], label: '认知拼接动作累计', value: formatCount(csAction?.sum || 0), note: `候选 ${formatCount(csCandidate?.sum || 0)} | 上下文拼接 ${formatCount(csConcat?.sum || 0)} | 新建 ${formatCount(csCreated?.sum || 0)} | 扩展 ${formatCount(csExtended?.sum || 0)}` },
            { keys: ['action_local_lookup_hit_count','action_local_lookup_text_fallback_hit_count','action_local_lookup_miss_count','action_local_lookup_skipped_count','action_attempted_count','action_executed_count','action_local_reward_drive_bonus_total','action_local_punish_drive_penalty_total'], label: '局部行动塑形累计', value: `命中 ${formatCount(localHit?.sum || 0)} | 平均 scale ${formatMaybe(localScale?.mean || 1, 3)}`, note: `尝试 ${formatCount(actionAttempt?.sum || 0)} | 执行 ${formatCount(actionExecuted?.sum || 0)} | 奖励+ ${formatMaybe(localRewardBonus?.sum || 0, 3)} | 惩罚- ${formatMaybe(localPunishPenalty?.sum || 0, 3)}` },
            { keys: ['iesm_action_trigger_weather_stub_count','iesm_action_trigger_targeted_weather_stub_count','iesm_action_trigger_target_missing_weather_stub_count','action_local_lookup_hit_count_weather_stub','action_local_target_missing_count_weather_stub'], label: '天气目标绑定累计', value: `带目标 ${formatCount(weatherTriggerTargeted?.sum || 0)} / 触发 ${formatCount(weatherTriggerCount?.sum || 0)}`, note: `缺目标 ${formatCount(weatherTriggerMissing?.sum || 0)} | 局部命中 ${formatCount(weatherLocalHit?.sum || 0)} | 局部缺目标 ${formatCount(weatherLocalTargetMissing?.sum || 0)}` },
            { keys: ['action_local_lookup_hit_count_weather_stub','action_local_lookup_text_fallback_hit_count_weather_stub','action_local_target_missing_count_weather_stub','action_attempted_weather_stub','action_executed_weather_stub','action_local_reward_drive_bonus_total_weather_stub','action_local_punish_drive_penalty_total_weather_stub'], label: '天气局部塑形累计', value: `命中 ${formatCount(weatherLocalHit?.sum || 0)} | 缺目标 ${formatCount(weatherLocalTargetMissing?.sum || 0)}`, note: `scale ${formatMaybe(weatherLocalScale?.mean || 1, 3)} | 尝试 ${formatCount(weatherActionAttempt?.sum || 0)} | 执行 ${formatCount(weatherActionExecuted?.sum || 0)} | 奖励+ ${formatMaybe(weatherLocalRewardBonus?.sum || 0, 3)} | 惩罚- ${formatMaybe(weatherLocalPunishPenalty?.sum || 0, 3)}` },
            { keys: ['teacher_applied_count','reward_signal_live_total_energy','punish_signal_live_total_energy','cfs_expectation_verified_count','cfs_pressure_verified_count','action_local_reward_drive_bonus_total_weather_stub','action_local_punish_drive_penalty_total_weather_stub','iesm_emotion_update_abs_total'], label: '教师-认知-天气链累计', value: `教师 ${formatCount(teacherApplied?.sum || 0)} | 已证实期待 ${formatCount(expectationVerified?.sum || 0)} | 已证实压力 ${formatCount(pressureVerified?.sum || 0)}`, note: `reward峰值 ${formatMaybe(rewardLive?.max || 0, 3)} | punish峰值 ${formatMaybe(punishLive?.max || 0, 3)} | 奖励+ ${formatMaybe(weatherLocalRewardBonus?.sum || 0, 3)} | 惩罚- ${formatMaybe(weatherLocalPunishPenalty?.sum || 0, 3)} | IESM ${formatMaybe(iesmEmotionUpdate?.sum || 0, 3)}` },
            { keys: ['timing_total_logic_ms'], label: '总逻辑耗时累计', value: formatDuration(timing?.sum || 0), note: `平均 ${formatMaybe(timing?.mean || 0, 1)} ms | 峰值 ${formatMaybe(timing?.max || 0, 1)} ms` },
          ]
        : [
            { alwaysShow: true, label: '统计口径', value: '最后一拍', note: `tick ${last.tick_index ?? '-'} | 适合观察当前即时状态` },
            { alwaysShow: true, label: '已加载行数', value: formatCount(rows.length), note: `下采样步长 ${formatCount(STATE.lastMetricsEvery)}` },
            { alwaysShow: true, label: '最新刷新', value: formatTime(STATE.lastMetricsFetchMs), note: '图表与摘要使用同一份 rows' },
            { keys: ['external_sa_count','merged_flat_token_count'], label: '最新外源 SA', value: formatCount(last.external_sa_count || 0), note: `合流 flat token：${formatCount(last.merged_flat_token_count || 0)}` },
            { keys: ['complexity_score','core_complexity_score','effective_peak_count','core_effective_peak_count'], label: '当前复杂度双口径', value: `全量 ${formatMaybe(last.complexity_score || 0, 3)} | 核心 ${formatMaybe(last.core_complexity_score || 0, 3)}`, note: `峰数 全量 ${formatMaybe(last.effective_peak_count || 0, 2)} | 核心 ${formatMaybe(last.core_effective_peak_count || 0, 2)}` },
            { keys: ['cs_candidate_count','cs_action_count','cs_concat_count','cs_created_count','cs_extended_count'], label: '最新认知拼接', value: formatCount(last.cs_action_count || 0), note: `候选 ${formatCount(last.cs_candidate_count || 0)} | 上下文拼接 ${formatCount(last.cs_concat_count || 0)} | 新建 ${formatCount(last.cs_created_count || 0)} | 扩展 ${formatCount(last.cs_extended_count || 0)}` },
            { keys: ['action_local_lookup_hit_count','action_local_lookup_text_fallback_hit_count','action_local_lookup_miss_count','action_local_lookup_skipped_count','action_attempted_count','action_executed_count','action_local_reward_drive_bonus_total','action_local_punish_drive_penalty_total'], label: '当前局部行动塑形', value: `命中 ${formatCount(last.action_local_lookup_hit_count || 0)} | 文本回落 ${formatCount(last.action_local_lookup_text_fallback_hit_count || 0)} | scale ${formatMaybe(last.action_local_drive_scale_mean || 1, 3)}`, note: `尝试 ${formatCount(last.action_attempted_count || 0)} | 执行 ${formatCount(last.action_executed_count || 0)} | 奖励+ ${formatMaybe(last.action_local_reward_drive_bonus_total || 0, 3)} | 惩罚- ${formatMaybe(last.action_local_punish_drive_penalty_total || 0, 3)}` },
            { keys: ['iesm_action_trigger_weather_stub_count','iesm_action_trigger_targeted_weather_stub_count','iesm_action_trigger_target_missing_weather_stub_count','action_local_lookup_hit_count_weather_stub','action_local_lookup_text_fallback_hit_count_weather_stub'], label: '当前天气目标绑定', value: `带目标 ${formatCount(last.iesm_action_trigger_targeted_weather_stub_count || 0)} / 触发 ${formatCount(last.iesm_action_trigger_weather_stub_count || 0)}`, note: `缺目标 ${formatCount(last.iesm_action_trigger_target_missing_weather_stub_count || 0)} | 局部命中 ${formatCount(last.action_local_lookup_hit_count_weather_stub || 0)} | 文本回落 ${formatCount(last.action_local_lookup_text_fallback_hit_count_weather_stub || 0)}` },
            { keys: ['action_local_lookup_hit_count_weather_stub','action_local_lookup_text_fallback_hit_count_weather_stub','action_local_target_missing_count_weather_stub','action_attempted_weather_stub','action_executed_weather_stub','action_local_reward_drive_bonus_total_weather_stub','action_local_punish_drive_penalty_total_weather_stub'], label: '当前天气局部塑形', value: `命中 ${formatCount(last.action_local_lookup_hit_count_weather_stub || 0)} | 文本回落 ${formatCount(last.action_local_lookup_text_fallback_hit_count_weather_stub || 0)} | 缺目标 ${formatCount(last.action_local_target_missing_count_weather_stub || 0)}`, note: `scale ${formatMaybe(last.action_local_drive_scale_mean_weather_stub || 1, 3)} | 尝试 ${formatCount(last.action_attempted_weather_stub || 0)} | 执行 ${formatCount(last.action_executed_weather_stub || 0)} | 奖励+ ${formatMaybe(last.action_local_reward_drive_bonus_total_weather_stub || 0, 3)} | 惩罚- ${formatMaybe(last.action_local_punish_drive_penalty_total_weather_stub || 0, 3)}` },
            { keys: ['teacher_applied_count','reward_signal_live_total_energy','punish_signal_live_total_energy','cfs_expectation_verified_count','cfs_pressure_verified_count','action_local_reward_drive_bonus_total_weather_stub','action_local_punish_drive_penalty_total_weather_stub','iesm_emotion_update_abs_total'], label: '当前教师-认知-天气链', value: `教师 ${formatCount(last.teacher_applied_count || 0)} | 已证实期待 ${formatCount(last.cfs_expectation_verified_count || 0)} | 已证实压力 ${formatCount(last.cfs_pressure_verified_count || 0)}`, note: `reward ${formatMaybe(last.reward_signal_live_total_energy || 0, 3)} | punish ${formatMaybe(last.punish_signal_live_total_energy || 0, 3)} | 奖励+ ${formatMaybe(last.action_local_reward_drive_bonus_total_weather_stub || 0, 3)} | 惩罚- ${formatMaybe(last.action_local_punish_drive_penalty_total_weather_stub || 0, 3)} | IESM ${formatMaybe(last.iesm_emotion_update_abs_total || 0, 3)}` },
            { keys: ['timing_total_logic_ms','timing_stimulus_level_ms','timing_cache_neutralization_ms'], label: '最新总耗时', value: `${formatMaybe(last.timing_total_logic_ms || 0, 1)} ms`, note: `刺激级：${formatMaybe(last.timing_stimulus_level_ms || 0, 1)} | 中和：${formatMaybe(last.timing_cache_neutralization_ms || 0, 1)}` },
          ]
    );
  }
  renderMetricNarrative();
}
function renderRunSummary(){
  const man = STATE.lastManifest || {};
  const rows = asArray(STATE.lastMetricsRows);
  const mode = currentMetricPerspective();
  const runtimeBaseline = man.runtime_baseline || {};
  const hdbBefore = runtimeBaseline.hdb_before_reset?.summary || {};
  const hdbAfter = runtimeBaseline.hdb_after_reset?.summary || {};
  const hdbDataDir = runtimeBaseline.hdb_after_reset?.hdb_data_dir || runtimeBaseline.hdb_before_reset?.hdb_data_dir || '-';
  if (DOM.expRunMeta) DOM.expRunMeta.textContent = `status=${man.status || '-'} | dataset=${man.dataset?.dataset_id || '-'} | done=${man.tick_done ?? 0}/${man.dataset?.total_ticks ?? '-'}`;
  if (DOM.expRunOverviewCards) {
    const expc = man.expectation_contracts || {};
    const at = man.auto_tuner || {};
    DOM.expRunOverviewCards.innerHTML = [
      metricCard('运行状态', man.status || '-', `run_id=${man.run_id || '-'}`),
      metricCard('已执行 Tick', formatCount(man.tick_done || 0), `source=${formatCount(man.source_tick_done || 0)} | synthetic=${formatCount(man.synthetic_tick_done || 0)}`),
      metricCard('数据集', man.dataset?.dataset_id || '-', man.dataset?.dataset_ref?.rel_path || '-'),
      metricCard('期待契约', formatCount(expc.registered_count || 0), `success=${formatCount(expc.success_count || 0)} | failure=${formatCount(expc.failure_count || 0)}`),
      metricCard('调参器', formatBool(Boolean(at.enabled)), `短期=${formatBool(Boolean(at.short_term?.enabled ?? true))} | 长期=${formatBool(Boolean(at.long_term?.enabled ?? true))}`),
      metricCard('时间感受器', man.time_sensor_runtime_override?.time_basis || 'tick', `tick_interval_sec=${man.time_sensor_runtime_override?.tick_interval_sec ?? '-'}`),
      metricCard('HDB 起始基线', formatCount(hdbBefore.structure_count || 0), `after_reset=${formatCount(hdbAfter.structure_count || 0)} | dir=${truncateText(String(hdbDataDir || '-'), 44)}`),
    ].join('');
  }
  if (DOM.expRunSummary) {
    const last = rows.at(-1) || {};
    const first = rows[0] || {};
    const ext = summarizeMetric(rows, 'external_sa_count');
    const internal = summarizeMetric(rows, 'internal_sa_count');
    const timing = summarizeMetric(rows, 'timing_total_logic_ms');
    const csCandidate = summarizeMetric(rows, 'cs_candidate_count');
    const csAction = summarizeMetric(rows, 'cs_action_count');
    const csConcat = summarizeMetric(rows, 'cs_concat_count');
    const csCreated = summarizeMetric(rows, 'cs_created_count');
    const csExtended = summarizeMetric(rows, 'cs_extended_count');
    const csMerged = summarizeMetric(rows, 'cs_merged_count');
    const actionAttempt = summarizeMetric(rows, 'action_attempted_count');
    const actionExecuted = summarizeMetric(rows, 'action_executed_count');
    const localHit = summarizeMetric(rows, 'action_local_lookup_hit_count');
    const localTextFallbackHit = summarizeMetric(rows, 'action_local_lookup_text_fallback_hit_count');
    const localMiss = summarizeMetric(rows, 'action_local_lookup_miss_count');
    const localSkipped = summarizeMetric(rows, 'action_local_lookup_skipped_count');
    const localScale = summarizeMetric(rows, 'action_local_drive_scale_mean');
    const localRewardBonus = summarizeMetric(rows, 'action_local_reward_drive_bonus_total');
    const localPunishPenalty = summarizeMetric(rows, 'action_local_punish_drive_penalty_total');
    const weatherLocalHit = summarizeMetric(rows, 'action_local_lookup_hit_count_weather_stub');
    const weatherLocalTextFallbackHit = summarizeMetric(rows, 'action_local_lookup_text_fallback_hit_count_weather_stub');
    const weatherLocalMiss = summarizeMetric(rows, 'action_local_lookup_miss_count_weather_stub');
    const weatherLocalSkipped = summarizeMetric(rows, 'action_local_lookup_skipped_count_weather_stub');
    const weatherLocalTargetMissing = summarizeMetric(rows, 'action_local_target_missing_count_weather_stub');
    const weatherLocalScale = summarizeMetric(rows, 'action_local_drive_scale_mean_weather_stub');
    const weatherLocalRewardBonus = summarizeMetric(rows, 'action_local_reward_drive_bonus_total_weather_stub');
    const weatherLocalPunishPenalty = summarizeMetric(rows, 'action_local_punish_drive_penalty_total_weather_stub');
    const weatherActionAttempt = summarizeMetric(rows, 'action_attempted_weather_stub');
    const weatherActionExecuted = summarizeMetric(rows, 'action_executed_weather_stub');
    const weatherTriggerCount = summarizeMetric(rows, 'iesm_action_trigger_weather_stub_count');
    const weatherTriggerTargeted = summarizeMetric(rows, 'iesm_action_trigger_targeted_weather_stub_count');
    const weatherTriggerMissing = summarizeMetric(rows, 'iesm_action_trigger_target_missing_weather_stub_count');
    const teacherApplied = summarizeMetric(rows, 'teacher_applied_count');
    const rewardLive = summarizeMetric(rows, 'reward_signal_live_total_energy');
    const punishLive = summarizeMetric(rows, 'punish_signal_live_total_energy');
    const expectationVerified = summarizeMetric(rows, 'cfs_expectation_verified_count');
    const pressureVerified = summarizeMetric(rows, 'cfs_pressure_verified_count');
    const iesmEmotionUpdate = summarizeMetric(rows, 'iesm_emotion_update_abs_total');
    DOM.expRunSummary.innerHTML = renderMiniRowSpecs(rows, [
      { alwaysShow: true, title: '当前统计口径', desc: mode === 'aggregate' ? '整场聚合：适合回答整场有没有真的发生过认知拼接、内源解析或耗时波动。' : '最后一拍：适合观察当前 tick 的即时状态，但不代表整场总貌。' },
      { alwaysShow: true, title: mode === 'aggregate' ? '整场聚合摘要' : '最后一条 tick 指标', desc: mode === 'aggregate' ? `tick ${first.tick_index ?? '-'} ~ ${last.tick_index ?? '-'} | 外源SA累计 ${formatCount(ext?.sum || 0)} | 内源SA累计 ${formatCount(internal?.sum || 0)} | 总逻辑累计 ${formatDuration(timing?.sum || 0)}` : `tick ${last.tick_index ?? '-'} | 外源SA ${last.external_sa_count ?? 0} | 合流 flat token ${last.merged_flat_token_count ?? 0} | 总耗时 ${last.timing_total_logic_ms ?? 0}ms` },
      { keys: ['cs_candidate_count','cs_action_count','cs_concat_count','cs_created_count','cs_extended_count','cs_merged_count'], title: mode === 'aggregate' ? '认知拼接整场摘要' : '认知拼接当前摘要', desc: mode === 'aggregate' ? `候选累计 ${formatCount(csCandidate?.sum || 0)} | 动作累计 ${formatCount(csAction?.sum || 0)} | 上下文拼接 ${formatCount(csConcat?.sum || 0)} | 新建 ${formatCount(csCreated?.sum || 0)} | 扩展 ${formatCount(csExtended?.sum || 0)} | 合并 ${formatCount(csMerged?.sum || 0)}` : `候选 ${formatCount(last.cs_candidate_count || 0)} | 动作 ${formatCount(last.cs_action_count || 0)} | 上下文拼接 ${formatCount(last.cs_concat_count || 0)} | 新建 ${formatCount(last.cs_created_count || 0)} | 扩展 ${formatCount(last.cs_extended_count || 0)} | 合并 ${formatCount(last.cs_merged_count || 0)}` },
      { keys: ['action_local_lookup_hit_count','action_local_lookup_text_fallback_hit_count','action_local_lookup_miss_count','action_local_lookup_skipped_count','action_attempted_count','action_executed_count','action_local_reward_drive_bonus_total','action_local_punish_drive_penalty_total'], title: mode === 'aggregate' ? '局部行动塑形整场摘要' : '局部行动塑形当前摘要', desc: mode === 'aggregate' ? `命中累计 ${formatCount(localHit?.sum || 0)} | 文本回落累计 ${formatCount(localTextFallbackHit?.sum || 0)} | miss累计 ${formatCount(localMiss?.sum || 0)} | skipped累计 ${formatCount(localSkipped?.sum || 0)} | scale均值 ${formatMaybe(localScale?.mean || 1, 3)} | 尝试累计 ${formatCount(actionAttempt?.sum || 0)} | 执行累计 ${formatCount(actionExecuted?.sum || 0)} | 奖励+ ${formatMaybe(localRewardBonus?.sum || 0, 3)} | 惩罚- ${formatMaybe(localPunishPenalty?.sum || 0, 3)}` : `命中 ${formatCount(last.action_local_lookup_hit_count || 0)} | 文本回落 ${formatCount(last.action_local_lookup_text_fallback_hit_count || 0)} | miss ${formatCount(last.action_local_lookup_miss_count || 0)} | skipped ${formatCount(last.action_local_lookup_skipped_count || 0)} | scale ${formatMaybe(last.action_local_drive_scale_mean || 1, 3)} | 尝试 ${formatCount(last.action_attempted_count || 0)} | 执行 ${formatCount(last.action_executed_count || 0)} | 奖励+ ${formatMaybe(last.action_local_reward_drive_bonus_total || 0, 3)} | 惩罚- ${formatMaybe(last.action_local_punish_drive_penalty_total || 0, 3)}` },
      { keys: ['action_local_lookup_hit_count_weather_stub','action_local_lookup_text_fallback_hit_count_weather_stub','action_local_lookup_miss_count_weather_stub','action_local_lookup_skipped_count_weather_stub','action_local_target_missing_count_weather_stub','action_attempted_weather_stub','action_executed_weather_stub','action_local_reward_drive_bonus_total_weather_stub','action_local_punish_drive_penalty_total_weather_stub'], title: mode === 'aggregate' ? '天气局部塑形整场摘要' : '天气局部塑形当前摘要', desc: mode === 'aggregate' ? `命中累计 ${formatCount(weatherLocalHit?.sum || 0)} | 文本回落累计 ${formatCount(weatherLocalTextFallbackHit?.sum || 0)} | miss累计 ${formatCount(weatherLocalMiss?.sum || 0)} | skipped累计 ${formatCount(weatherLocalSkipped?.sum || 0)} | 缺目标累计 ${formatCount(weatherLocalTargetMissing?.sum || 0)} | scale均值 ${formatMaybe(weatherLocalScale?.mean || 1, 3)} | 尝试累计 ${formatCount(weatherActionAttempt?.sum || 0)} | 执行累计 ${formatCount(weatherActionExecuted?.sum || 0)} | 奖励+ ${formatMaybe(weatherLocalRewardBonus?.sum || 0, 3)} | 惩罚- ${formatMaybe(weatherLocalPunishPenalty?.sum || 0, 3)}` : `命中 ${formatCount(last.action_local_lookup_hit_count_weather_stub || 0)} | 文本回落 ${formatCount(last.action_local_lookup_text_fallback_hit_count_weather_stub || 0)} | miss ${formatCount(last.action_local_lookup_miss_count_weather_stub || 0)} | skipped ${formatCount(last.action_local_lookup_skipped_count_weather_stub || 0)} | 缺目标 ${formatCount(last.action_local_target_missing_count_weather_stub || 0)} | scale ${formatMaybe(last.action_local_drive_scale_mean_weather_stub || 1, 3)} | 尝试 ${formatCount(last.action_attempted_weather_stub || 0)} | 执行 ${formatCount(last.action_executed_weather_stub || 0)} | 奖励+ ${formatMaybe(last.action_local_reward_drive_bonus_total_weather_stub || 0, 3)} | 惩罚- ${formatMaybe(last.action_local_punish_drive_penalty_total_weather_stub || 0, 3)}` },
      { keys: ['teacher_applied_count','reward_signal_live_total_energy','punish_signal_live_total_energy','cfs_expectation_verified_count','cfs_pressure_verified_count','action_local_reward_drive_bonus_total_weather_stub','action_local_punish_drive_penalty_total_weather_stub','iesm_emotion_update_abs_total'], title: mode === 'aggregate' ? '教师-认知-天气链整场摘要' : '教师-认知-天气链当前摘要', desc: mode === 'aggregate' ? `教师应用累计 ${formatCount(teacherApplied?.sum || 0)} | 已证实期待累计 ${formatCount(expectationVerified?.sum || 0)} | 已证实压力累计 ${formatCount(pressureVerified?.sum || 0)} | reward峰值 ${formatMaybe(rewardLive?.max || 0, 3)} | punish峰值 ${formatMaybe(punishLive?.max || 0, 3)} | 奖励+ ${formatMaybe(weatherLocalRewardBonus?.sum || 0, 3)} | 惩罚- ${formatMaybe(weatherLocalPunishPenalty?.sum || 0, 3)} | IESM累计 ${formatMaybe(iesmEmotionUpdate?.sum || 0, 3)}` : `教师 ${formatCount(last.teacher_applied_count || 0)} | 已证实期待 ${formatCount(last.cfs_expectation_verified_count || 0)} | 已证实压力 ${formatCount(last.cfs_pressure_verified_count || 0)} | reward ${formatMaybe(last.reward_signal_live_total_energy || 0, 3)} | punish ${formatMaybe(last.punish_signal_live_total_energy || 0, 3)} | 奖励+ ${formatMaybe(last.action_local_reward_drive_bonus_total_weather_stub || 0, 3)} | 惩罚- ${formatMaybe(last.action_local_punish_drive_penalty_total_weather_stub || 0, 3)} | IESM ${formatMaybe(last.iesm_emotion_update_abs_total || 0, 3)}` },
      { keys: ['iesm_action_trigger_weather_stub_count','iesm_action_trigger_targeted_weather_stub_count','iesm_action_trigger_target_missing_weather_stub_count'], title: mode === 'aggregate' ? '天气触发目标绑定摘要' : '天气触发目标绑定当前摘要', desc: mode === 'aggregate' ? `天气触发累计 ${formatCount(weatherTriggerCount?.sum || 0)} | 带目标累计 ${formatCount(weatherTriggerTargeted?.sum || 0)} | 缺目标累计 ${formatCount(weatherTriggerMissing?.sum || 0)}` : `天气触发 ${formatCount(last.iesm_action_trigger_weather_stub_count || 0)} | 带目标 ${formatCount(last.iesm_action_trigger_targeted_weather_stub_count || 0)} | 缺目标 ${formatCount(last.iesm_action_trigger_target_missing_weather_stub_count || 0)}` },
      { alwaysShow: true, title: '运行选项', desc: `reset_mode=${man.options?.reset_mode || '-'} | export_json=${formatBool(Boolean(man.options?.export_json))} | export_html=${formatBool(Boolean(man.options?.export_html))} | time_basis=${man.options?.time_sensor_time_basis || '(default)'}` },
      { alwaysShow: true, title: '起始 HDB 基线', desc: `before_reset: st=${formatCount(hdbBefore.structure_count || 0)} | group=${formatCount(hdbBefore.group_count || 0)} | after_reset: st=${formatCount(hdbAfter.structure_count || 0)} | group=${formatCount(hdbAfter.group_count || 0)} | dir=${truncateText(String(hdbDataDir || '-'), 96)}` },
      { alwaysShow: true, title: '执行进度解释', desc: `source_tick_done=${formatCount(man.source_tick_done || 0)} | synthetic_tick_done=${formatCount(man.synthetic_tick_done || 0)} | executed_tick_done_total=${formatCount(man.executed_tick_done_total || 0)} | tick_planned=${formatCount(man.tick_planned || 0)}` },
    ]);
  }
}

async function refreshRuns(silent=false){ try { const res = await apiGet('/api/experiment/runs?limit=48'); STATE.runs = asArray(res.data?.items || res.data?.runs); if (DOM.expRunsList) { DOM.expRunsList.innerHTML = STATE.runs.map((r)=> `<button class="list-row-btn ${STATE.selectedRunId===r.run_id?'active':''}" data-run-id="${esc(r.run_id)}"><span>${esc(r.run_id)}</span><span class="meta">${esc(r.status || '-')} | ${esc(r.dataset_id || '-')} | ${formatCount(r.tick_done || 0)}/${formatCount(r.tick_planned || 0)}</span></button>`).join('') || emptyState('当前还没有实验运行记录。'); DOM.expRunsList.querySelectorAll('[data-run-id]').forEach((el)=> el.addEventListener('click', ()=> selectRun(el.getAttribute('data-run-id'), { reloadMetrics: true }))); } if(!STATE.selectedRunId && STATE.runs.length) STATE.selectedRunId = STATE.runs[0].run_id; if(STATE.selectedRunId) await selectRun(STATE.selectedRunId, { reloadMetrics: true, silent: true }); if(!silent) setFeedback(DOM.expJobFeedback, '已刷新运行记录。', 'ok'); } catch(error){ if(!silent) setFeedback(DOM.expJobFeedback, `刷新运行记录失败：${error.message}`, 'err'); } }
function notifyAutoTunerMetricContextChanged(){ if (typeof window.renderAutoTunerMetricInsights === 'function') { try { window.renderAutoTunerMetricInsights(); } catch {} } }
async function deleteSelectedRun(){ const rid = String(STATE.selectedRunId || '').trim(); if(!rid) return setFeedback(DOM.expJobFeedback, '当前没有选中的运行记录。', 'err'); try { await apiPost('/api/experiment/run/delete', { run_id: rid }); setFeedback(DOM.expJobFeedback, `已删除运行 ${rid}`, 'ok'); if (STATE.selectedRunId === rid) { STATE.selectedRunId = ''; STATE.lastManifest = null; STATE.lastMetricsRows = []; renderRunSummary(); renderMetricsOverview(); renderChartDeck(); notifyAutoTunerMetricContextChanged(); } await refreshRuns(true); } catch(error){ setFeedback(DOM.expJobFeedback, `删除运行失败：${error.message}`, 'err'); } }
async function clearRuns(){ try { await apiPost('/api/experiment/runs/clear', {}); STATE.selectedRunId = ''; STATE.lastManifest = null; STATE.lastMetricsRows = []; renderRunSummary(); renderMetricsOverview(); renderChartDeck(); notifyAutoTunerMetricContextChanged(); await refreshRuns(true); setFeedback(DOM.expJobFeedback, '已清空运行记录。', 'ok'); } catch(error){ setFeedback(DOM.expJobFeedback, `清空运行记录失败：${error.message}`, 'err'); } }
async function selectRun(runId, { reloadMetrics = true, silent = false } = {}) {
  const rid = String(runId || '').trim();
  if(!rid) return;
  STATE.selectedRunId = rid;
  saveExperimentSettings();
  try {
    const m1 = await apiGet(`/api/experiment/run/manifest?run_id=${encodeURIComponent(rid)}`);
    STATE.lastManifest = m1.data || null;
    let m2 = { data: { rows: STATE.lastMetricsRows, downsample_every: STATE.lastMetricsEvery || 1 } };
    let effectiveEvery = Math.max(1, asNumber(DOM.expDownsampleEvery?.value, 1));
    if (reloadMetrics) {
      const man = STATE.lastManifest || {};
      const executedTickDone = Math.max(
        asNumber(man.executed_tick_done_total, 0),
        asNumber(man.tick_done, 0),
        asNumber(man.tick_planned, 0),
      );
      const shouldForceFullMetrics = executedTickDone > 0 && executedTickDone <= 4000;
      if (shouldForceFullMetrics) effectiveEvery = 1;
      m2 = await apiGet(`/api/experiment/run/metrics?run_id=${encodeURIComponent(rid)}&downsample_every=${effectiveEvery}`);
    }
    STATE.lastMetricsRows = asArray(m2.data?.rows);
    STATE.lastMetricsEvery = Math.max(1, asNumber(m2.data?.downsample_every, effectiveEvery));
    STATE.lastMetricsFetchMs = Date.now();
    renderRunSummary();
    renderMetricsOverview();
    renderChartDeck();
    notifyAutoTunerMetricContextChanged();
    await refreshLlmStatus(rid, true).catch(()=>{});
    if(!silent) {
      const requestedEvery = Math.max(1, asNumber(DOM.expDownsampleEvery?.value, 1));
      const extra = reloadMetrics && requestedEvery !== STATE.lastMetricsEvery
        ? `（已自动按 ${STATE.lastMetricsEvery} 取数，避免稀疏事件图被下采样掩盖）`
        : '';
      setFeedback(DOM.expJobFeedback, `已加载运行 ${rid}${extra}`, 'ok');
    }
  } catch(error){
    if(!silent) setFeedback(DOM.expJobFeedback, `加载运行失败：${error.message}`, 'err');
  }
}

function renderJobPanel(job){
  if (!DOM.expJobMeta || !job) return;
  const done = asNumber(job.tick_done, 0), planned = asNumber(job.tick_planned, 0);
  DOM.expJobMeta.textContent = `job=${job.job_id || '-'} | status=${job.status || '-'} | ${done}/${planned || '?'}`;
  if (DOM.expProgressBar) DOM.expProgressBar.style.width = `${planned ? Math.round(Math.max(0, Math.min(1, done / Math.max(1, planned))) * 100) : 0}%`;
  if (DOM.expJobOverviewCards) DOM.expJobOverviewCards.innerHTML = [
    metricCard('当前状态', job.status || '-', job.error || '状态自动刷新'),
    metricCard('当前进度', `${formatCount(done)}/${formatCount(planned)}`, `executed=${formatCount(job.executed_tick_done_total || done)}`),
    metricCard('运行记录', job.run_id || '-', `dataset=${job.dataset_id || '-'}`),
  ].join('');
  if (DOM.expJobSummary) DOM.expJobSummary.innerHTML = miniRow('任务说明', `source_tick_done=${formatCount(job.source_tick_done || 0)} | synthetic_tick_done=${formatCount(job.synthetic_tick_done || 0)} | executed_total=${formatCount(job.executed_tick_done_total || 0)}`);
}
window.renderJobPanel = renderJobPanel;

function stopJobPolling(){ if(STATE.jobPollTimer){ clearInterval(STATE.jobPollTimer); STATE.jobPollTimer = null; } }
async function pollJob(jobId, runId){ const jid = String(jobId || '').trim(); if(!jid) return; try { const res = await apiGet(`/api/experiment/jobs?job_id=${encodeURIComponent(jid)}`); const job = res.data || null; STATE.lastJob = job; renderJobPanel(job); const status = String(job?.status || ''); if (['completed','failed','cancelled','stopped_max_ticks'].includes(status)) { stopJobPolling(); STATE.activeJobId = ''; STATE.activeRunId = ''; saveExperimentSettings(); await refreshRuns(true); const rid = String(runId || job?.run_id || ''); if (rid) await selectRun(rid, { reloadMetrics: true, silent: true }); } } catch(error){ setFeedback(DOM.expJobFeedback, `刷新任务进度失败：${error.message}`, 'err'); } }
function startJobPolling(jobId, runId){ stopJobPolling(); STATE.activeJobId = String(jobId || ''); STATE.activeRunId = String(runId || ''); saveExperimentSettings(); pollJob(jobId, runId); STATE.jobPollTimer = setInterval(()=> pollJob(jobId, runId), 2500); }
window.startRun = async function startRun(){ const ref = getSelectedDatasetRef(); if(!ref) return setFeedback(DOM.expJobFeedback, '请先选择数据集。', 'err'); const runAll = Boolean(DOM.expRunAllTicksChk?.checked); const cleanRun = Boolean(DOM.expCleanRunChk?.checked); if(cleanRun && !window.confirm('纯净运行会在启动前清空 HDB、状态池、传感器残响、注意力/行动/时间感受运行态和 tick 计数。确认要先清空所有数据再运行吗？')) return; const options = { reset_mode: cleanRun ? 'clear_all' : (String(DOM.expResetMode?.value || 'keep').trim() || 'keep'), clean_run: cleanRun, export_json: Boolean(DOM.expExportJsonChk?.checked), export_html: Boolean(DOM.expExportHtmlChk?.checked), time_sensor_time_basis: String(DOM.expTimeBasisOverride?.value || '').trim() || null, max_ticks: (runAll ? null : (String(DOM.expMaxTicks?.value || '').trim() ? Math.max(1, asNumber(DOM.expMaxTicks?.value, 0)) : null)) }; saveExperimentSettings(); setFeedback(DOM.expJobFeedback, cleanRun ? '正在启动纯净实验任务：会先清空全部数据…' : '正在启动实验任务…', 'busy'); try { const res = await apiPost('/api/experiment/run/start', { dataset_ref: ref, options }); const jobId = String(res.data?.job_id || '').trim(); const runId = String(res.data?.run_id || '').trim(); if(!jobId) throw new Error('后端没有返回 job_id。'); startJobPolling(jobId, runId); setFeedback(DOM.expJobFeedback, `任务已启动：${jobId} | run=${runId || '-'}`, 'ok'); } catch(error){ setFeedback(DOM.expJobFeedback, `启动失败：${error.message}`, 'err'); } };
window.stopRun = async function stopRun(){ const jid = String(STATE.activeJobId || '').trim(); if(!jid) return setFeedback(DOM.expJobFeedback, '当前没有运行中的任务。', 'err'); try { const res = await apiPost('/api/experiment/run/stop', { job_id: jid }); STATE.lastJob = res.data || STATE.lastJob; renderJobPanel(STATE.lastJob); startJobPolling(jid, STATE.activeRunId || STATE.lastJob?.run_id || ''); setFeedback(DOM.expJobFeedback, `已请求停止 ${jid}。`, 'ok'); } catch(error){ setFeedback(DOM.expJobFeedback, `停止失败：${error.message}`, 'err'); } };

async function refreshLiveMonitor(){
  try {
    const res = await apiGet('/api/dashboard');
    STATE.liveDashboard = res.data || null;
    STATE.liveLastFetchMs = Date.now();
    const dash = STATE.liveDashboard || {};
    if (DOM.expLiveMeta) DOM.expLiveMeta.textContent = `最后刷新：${formatTime(STATE.liveLastFetchMs)}${STATE.livePaused ? ' | 已暂停自动刷新' : ''}`;
    const top = asArray(dash?.state_snapshot?.top_items);
    const structureTop = structureRowsFromDashboardTop(top, 18);
    if (DOM.expLiveStateTop) DOM.expLiveStateTop.innerHTML = structureTop.map((it)=>miniRow(`${truncateText(it.display || it.display_text || '-', 72)} · ${it.ref_object_type || '-'}`, `ER ${formatMaybe(it.er)} | EV ${formatMaybe(it.ev)} | CP ${formatMaybe(it.cp_abs)} | id ${it.ref_object_id || '-'}`)).join('') || emptyState('当前没有结构 Top。原子 SA 证据已在此处隐藏，可回到指标图查看原子/结构 Top 对照。');
    const rep = dash?.last_report || {};
    const items = asArray(rep?.cognitive_stitching?.narrative_top_items);
    if (DOM.expLiveCsTop) {
      const eg = rep?.cognitive_stitching?.event_grasp || {};
      const fallbackTop = top.filter((it)=> String(it.ref_object_type || '') === 'st' && String(it.display || '').length > 1).slice(0,12);
      DOM.expLiveCsTop.innerHTML = items.length
        ? items.slice(0,12).map((it, idx)=>miniRow(`Top${idx+1} · 总能量 ${formatMaybe(it.total_energy)} · 把握感 ${formatMaybe(it.event_grasp)}`, `${truncateText(it.visible_text || it.display_text || it.event_text || '-', 220)}\nref ${it.event_ref_id || '-'} | st ${it.structure_id || '-'} | 组分 ${it.component_count ?? '-'} | grasp来源 ${asArray(it.selection_sources).join('/') || eg.focus_mode || '-'}`)).join('')
        : (fallbackTop.length
            ? fallbackTop.map((it, idx)=>miniRow(`字符串对象 Top${idx+1} · CP ${formatMaybe(it.cp_abs)} · ER ${formatMaybe(it.er)}`, `${truncateText(it.display || '-', 220)}\nid ${it.ref_object_id || '-'} | 类型 ${it.ref_object_type || '-'}`)).join('')
            : emptyState(`当前没有 CS 回滚诊断 Top，也没有可回退展示的字符串对象 Top。默认 growth + CS disabled 下这是正常背景。最近一次 grasp：reason=${eg.reason || '-'} | mode=${eg.focus_mode || '-'} | selected=${eg.selected_event_count ?? '-'} | emitted=${eg.emitted_count ?? '-'}`));
    }
    const totals = dash?.state_snapshot?.summary?.bound_attribute_energy_totals || {};
    const cfsRows = Object.values(totals).filter((r)=> String(r?.attribute_name || '').startsWith('cfs_')).sort((l,r)=> asNumber(r?.total_energy,0)-asNumber(l?.total_energy,0));
    if (DOM.expLiveCfsTotals) DOM.expLiveCfsTotals.innerHTML = cfsRows.length ? cfsRows.slice(0,18).map((r)=>miniRow(`${r.attribute_name || '-'} · 总 ${formatMaybe(r.total_energy)}`, `ER ${formatMaybe(r.total_er)} | EV ${formatMaybe(r.total_ev)} | 覆盖对象 ${formatCount(r.item_count || 0)} | 属性条目 ${formatCount(r.attribute_count || 0)}`)).join('') : emptyState('当前没有 cfs_* 的 bound attributes 聚合数据。');

    const lastTick = rep?.trace_id || dash?.trace_id || `t${Date.now()}`;
    const autoTune = rep?.auto_tuner_short_term || rep?.auto_tuner || {};
    const appliedUpdates = asArray(autoTune?.applied_updates);
    STATE.liveAutoTuneLog = pushBounded(STATE.liveAutoTuneLog, {
      trace_id: lastTick,
      title: `tick ${lastTick} | 短期微调 ${appliedUpdates.length ? '生效' : '未生效'}`,
      desc: appliedUpdates.length ? appliedUpdates.slice(0,6).map((u)=> `${u.param || '-'} | Δ=${formatMaybe(u.delta,6)} | ${u.reason || '-'}`).join('\n') : `原因：${autoTune?.reason || '当前窗口没有需要处理的明显偏离。'}`,
    }, 80);
    if (DOM.expLiveAutoTuneLog) DOM.expLiveAutoTuneLog.innerHTML = STATE.liveAutoTuneLog.slice().reverse().slice(0,10).map((it)=>miniRow(it.title, truncateText(it.desc, 140))).join('') || emptyState('还没有短期微调条目。');

    const action = rep?.action || {};
    const executed = asArray(action?.executed_actions);
    const triggers = asArray(action?.triggered_actions || action?.triggered || []);
    STATE.liveActionLog = pushBounded(STATE.liveActionLog, {
      trace_id: lastTick,
      title: `tick ${lastTick} | 触发 ${formatCount(triggers.length)} | 执行 ${formatCount(executed.filter((x)=>x?.success).length)}/${formatCount(executed.length)}`,
      desc: executed.length ? executed.slice(0,6).map((row)=> {
        const kind = String(row?.action_kind || row?.kind || 'unknown');
        const params = row?.params && typeof row.params === 'object' ? Object.entries(row.params).slice(0,4).map(([k,v])=> `${k}=${String(v)}`).join(', ') : '';
        return `${actionKindLabel(kind)}${row?.action_id ? `(${row.action_id})` : ''} | ${row?.success ? 'OK' : 'SKIP'}${params ? ` | 参数 ${params}` : ''}${row?.reason ? ` | ${row.reason}` : ''}`;
      }).join('\n') : '本 tick 没有执行动作。',
    }, 80);
    if (DOM.expLiveActionLog) DOM.expLiveActionLog.innerHTML = STATE.liveActionLog.slice().reverse().slice(0,10).map((it)=>miniRow(it.title, truncateText(it.desc, 140))).join('') || emptyState('还没有行动触发/执行条目。');
  } catch(error) {}
}
window.refreshLiveMonitor = refreshLiveMonitor;

async function refreshLlmConfig(silent=false){
  try {
    const res = await apiGet('/api/experiment/llm_review/config');
    const cfg = res.data?.config || {};
    if (DOM.expLlmConfigMeta) DOM.expLlmConfigMeta.textContent = `来源：配置文件 | Key：${cfg.api_key_masked || '-'}`;
    if (DOM.expLlmEnabledChk) DOM.expLlmEnabledChk.checked = Boolean(cfg.enabled);
    if (DOM.expLlmAutoChk) DOM.expLlmAutoChk.checked = Boolean(cfg.auto_analyze_on_completion ?? cfg.auto_review_on_completion);
    if (DOM.expLlmBaseUrl) DOM.expLlmBaseUrl.value = String(cfg.base_url || '');
    if (DOM.expLlmModel) DOM.expLlmModel.value = String(cfg.model || '');
    if (DOM.expLlmMaxPromptChars) DOM.expLlmMaxPromptChars.value = String(cfg.max_prompt_chars || 900000);
    if (!silent) setFeedback(DOM.expLlmSaveFeedback, '已刷新 LLM Review 配置。', 'ok');
  } catch(error){ if(!silent) setFeedback(DOM.expLlmSaveFeedback, `刷新 LLM 配置失败：${error.message}`, 'err'); }
}
async function saveLlmConfig(){
  try {
    const config = {
      enabled: Boolean(DOM.expLlmEnabledChk?.checked),
      auto_analyze_on_completion: Boolean(DOM.expLlmAutoChk?.checked),
      base_url: String(DOM.expLlmBaseUrl?.value || '').trim(),
      model: String(DOM.expLlmModel?.value || '').trim(),
      api_key: String(DOM.expLlmApiKey?.value || '').trim(),
      max_prompt_chars: Math.max(1000, asNumber(DOM.expLlmMaxPromptChars?.value, 900000)),
    };
    await apiPost('/api/experiment/llm_review/config/save', { config });
    await refreshLlmConfig(true);
    setFeedback(DOM.expLlmSaveFeedback, '已保存 LLM Review 配置。', 'ok');
  } catch(error){ setFeedback(DOM.expLlmSaveFeedback, `保存 LLM 配置失败：${error.message}`, 'err'); }
}
async function refreshLlmStatus(runId, silent=false){
  const rid = String(runId || STATE.selectedRunId || '').trim();
  if(!rid) return;
  try {
    const [st, rp] = await Promise.all([
      apiGet(`/api/experiment/run/llm_review_status?run_id=${encodeURIComponent(rid)}`),
      apiGet(`/api/experiment/run/llm_review_report?run_id=${encodeURIComponent(rid)}`),
    ]);
    const status = st.data || {};
    const reportPayload = rp.data || {};
    const report = String(reportPayload.text || reportPayload.report_markdown || reportPayload.report_text || '');
    const stage = String(status.stage || '-');
    const errorCode = String(status.error || status.error_code || '-');
    const message = String(status.message || '-');
    const reportPath = String(status.report_path || '-');
    const rawPath = String(status.raw_path || '-');
    const errorPath = String(status.error_path || '-');
    const receivedChars = asNumber(status.received_chars, 0);
    const reportChars = asNumber(reportPayload.char_count, 0);
    const reportSource = String(reportPayload.source || status.report_source_hint || '-');
    const reportExists = Boolean(reportPayload.exists ?? status.report_exists);
    const reportFileExists = Boolean(reportPayload.report_file_exists ?? status.report_exists);
    const rawExists = Boolean(reportPayload.raw_file_exists ?? status.raw_exists);
    const errorExists = Boolean(reportPayload.error_file_exists ?? status.error_exists);
    const reportSizeBytes = asNumber(status.report_size_bytes, 0);
    const rawSizeBytes = asNumber(status.raw_size_bytes, 0);
    const errorSizeBytes = asNumber(status.error_size_bytes, 0);
    const jobId = String(status.job_id || '-');
    const jobStatus = String(status.job_status || status.status || '-');
    const jobError = String(status.job_error || '-');
    if (DOM.expLlmStatusMeta) {
      DOM.expLlmStatusMeta.textContent = `run_id=${rid} | status=${status.status || '-'} | stage=${stage} | job_id=${jobId} | job=${jobStatus} | report=${reportSource}/${reportExists ? 'yes' : 'no'} | chars=${receivedChars || reportChars} | error=${errorCode}`;
    }
    if (DOM.expLlmReport) {
      DOM.expLlmReport.textContent = report || [
        '当前还没有可展示的 LLM Review 报告。',
        `状态：${status.status || '-'}`,
        `任务状态：${jobStatus}`,
        `阶段：${stage}`,
        `错误码：${errorCode}`,
        `消息：${message}`,
        `任务错误：${jobError}`,
        `报告来源：${reportSource}`,
        `报告内容可见：${reportExists ? '是' : '否'}`,
        `报告文件存在：${reportFileExists ? '是' : '否'}`,
        `原始响应存在：${rawExists ? '是' : '否'}`,
        `错误文件存在：${errorExists ? '是' : '否'}`,
        `报告字节：${formatCount(reportSizeBytes)}`,
        `原始响应字节：${formatCount(rawSizeBytes)}`,
        `错误文件字节：${formatCount(errorSizeBytes)}`,
        `报告路径：${reportPath}`,
        `原始响应路径：${rawPath}`,
        `错误路径：${errorPath}`,
      ].join('\n');
    }
    if (!silent) {
      const note = report && reportSource !== 'report' ? `已刷新 LLM Review 状态（正文来自 ${reportSource} 兜底）。` : '已刷新 LLM Review 状态。';
      setFeedback(DOM.expLlmStatusFeedback, note, report && reportSource !== 'report' ? 'warn' : 'ok');
    }
  } catch(error){ if(!silent) setFeedback(DOM.expLlmStatusFeedback, `刷新 LLM Review 状态失败：${error.message}`, 'err'); }
}
function stopLlmPolling(){ if(STATE.llmPollTimer){ clearInterval(STATE.llmPollTimer); STATE.llmPollTimer = null; } }
function startLlmPolling(runId){
  const rid = String(runId || '').trim();
  if(!rid) return;
  stopLlmPolling();
  refreshLlmStatus(rid, true).catch(()=>{});
  STATE.llmPollTimer = setInterval(async ()=> {
    try {
      await refreshLlmStatus(rid, true);
      const meta = String(DOM.expLlmStatusMeta?.textContent || '');
      if (/status=(completed|failed|cancelled|done|error)/i.test(meta)) stopLlmPolling();
    } catch {}
  }, 2000);
}
async function startLlmReview(){
  const rid = String(STATE.selectedRunId || '').trim();
  if(!rid) return setFeedback(DOM.expLlmStatusFeedback, '请先选择一个运行记录。', 'err');
  try {
    const res = await apiPost('/api/experiment/run/llm_review/start', { run_id: rid, force: false });
    const jobId = String(res.data?.job_id || '');
    setFeedback(DOM.expLlmStatusFeedback, `已启动 LLM Review 任务。${jobId ? ` job_id=${jobId}` : ''}`, 'ok');
    await refreshLlmStatus(rid, true);
    startLlmPolling(rid);
  } catch(error){ setFeedback(DOM.expLlmStatusFeedback, `启动 LLM Review 失败：${error.message}`, 'err'); }
}
async function startLlmReviewForce(){
  const rid = String(STATE.selectedRunId || '').trim();
  if(!rid) return setFeedback(DOM.expLlmStatusFeedback, '请先选择一个运行记录。', 'err');
  try {
    const res = await apiPost('/api/experiment/run/llm_review/start', { run_id: rid, force: true });
    const jobId = String(res.data?.job_id || '');
    setFeedback(DOM.expLlmStatusFeedback, `已强制启动 LLM Review 任务。${jobId ? ` job_id=${jobId}` : ''}`, 'ok');
    await refreshLlmStatus(rid, true);
    startLlmPolling(rid);
  } catch(error){ setFeedback(DOM.expLlmStatusFeedback, `强制启动 LLM Review 失败：${error.message}`, 'err'); }
}
function copyLlmReport(){ const text = String(DOM.expLlmReport?.textContent || ''); if(!text) return; navigator.clipboard?.writeText(text); }
function downloadLlmReport(){ const text = String(DOM.expLlmReport?.textContent || ''); if(!text) return; const blob = new Blob([text], {type:'text/markdown;charset=utf-8'}); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `llm_review_${STATE.selectedRunId || 'latest'}.md`; a.click(); URL.revokeObjectURL(url); }

document.addEventListener('DOMContentLoaded', async () => {
  bindDom();
  restoreExperimentSettings();
  renderMetricPerspectiveToolbar();
  if (DOM.expBackBtn) DOM.expBackBtn.addEventListener('click', ()=> { try { window.history.back(); } catch { window.location.href = '/'; } });
  if (DOM.expRefreshProtocolBtn) DOM.expRefreshProtocolBtn.addEventListener('click', ()=> refreshProtocol());
  if (DOM.expRefreshDatasetsBtn) DOM.expRefreshDatasetsBtn.addEventListener('click', ()=> refreshDatasets());
  if (DOM.expPreviewBtn) DOM.expPreviewBtn.addEventListener('click', ()=> previewDataset());
  if (DOM.expExpandBtn) DOM.expExpandBtn.addEventListener('click', ()=> expandDataset());
  if (DOM.expImportBtn) DOM.expImportBtn.addEventListener('click', ()=> importDataset());
  if (DOM.expRunStartBtn) DOM.expRunStartBtn.addEventListener('click', ()=> window.startRun());
  if (DOM.expRunStopBtn) DOM.expRunStopBtn.addEventListener('click', ()=> window.stopRun());
  if (DOM.expLivePauseBtn) DOM.expLivePauseBtn.addEventListener('click', ()=> {
    STATE.livePaused = !STATE.livePaused;
    DOM.expLivePauseBtn.textContent = STATE.livePaused ? '继续刷新' : '暂停刷新';
    if (!STATE.livePaused) refreshLiveMonitor();
  });
  if (DOM.expLiveClearBtn) DOM.expLiveClearBtn.addEventListener('click', ()=> {
    STATE.liveActionLog = [];
    STATE.liveAutoTuneLog = [];
    if (DOM.expLiveAutoTuneLog) DOM.expLiveAutoTuneLog.innerHTML = emptyState('还没有短期微调条目。');
    if (DOM.expLiveActionLog) DOM.expLiveActionLog.innerHTML = emptyState('还没有行动触发/执行条目。');
  });
  if (DOM.expRefreshRunsBtn) DOM.expRefreshRunsBtn.addEventListener('click', ()=> refreshRuns());
  if (DOM.expRefreshRunsInlineBtn) DOM.expRefreshRunsInlineBtn.addEventListener('click', ()=> refreshRuns());
  if (DOM.expRefreshRunSummaryBtn) DOM.expRefreshRunSummaryBtn.addEventListener('click', ()=> { if (STATE.selectedRunId) selectRun(STATE.selectedRunId, { reloadMetrics: true }); else refreshRuns(); });
  if (DOM.expDeleteRunBtn) DOM.expDeleteRunBtn.addEventListener('click', ()=> deleteSelectedRun());
  if (DOM.expClearRunsBtn) DOM.expClearRunsBtn.addEventListener('click', ()=> clearRuns());
  if (DOM.expClearRuntimeBtn) DOM.expClearRuntimeBtn.addEventListener('click', ()=> clearRuntime());
  if (DOM.expClearHdbBtn) DOM.expClearHdbBtn.addEventListener('click', ()=> clearHdb());
  if (DOM.expClearAllBtn) DOM.expClearAllBtn.addEventListener('click', ()=> clearAll());
  ['expResetMode','expCleanRunChk','expMaxTicks','expTimeBasisOverride','expExportJsonChk','expExportHtmlChk'].forEach((id)=> {
    const el = DOM[id];
    if (el) el.addEventListener('change', saveExperimentSettings);
  });
  if (DOM.expRunAllTicksChk) DOM.expRunAllTicksChk.addEventListener('change', ()=> {
    if (DOM.expMaxTicks) DOM.expMaxTicks.disabled = Boolean(DOM.expRunAllTicksChk.checked);
    saveExperimentSettings();
  });
  if (DOM.expCleanRunChk) DOM.expCleanRunChk.addEventListener('change', ()=> {
    if (DOM.expResetMode) DOM.expResetMode.disabled = Boolean(DOM.expCleanRunChk.checked);
    saveExperimentSettings();
  });
  if (DOM.expDatasetSelect) DOM.expDatasetSelect.addEventListener('change', ()=> { STATE.selectedDatasetKey = String(DOM.expDatasetSelect.value || ''); saveExperimentSettings(); renderDatasets(); });
  if (DOM.expDownsampleEvery) DOM.expDownsampleEvery.addEventListener('change', ()=> { saveExperimentSettings(); if (STATE.selectedRunId) selectRun(STATE.selectedRunId, { reloadMetrics: true }); });
  if (DOM.expLlmRefreshBtn) DOM.expLlmRefreshBtn.addEventListener('click', ()=> refreshLlmConfig());
  if (DOM.expLlmStatusRefreshBtn) DOM.expLlmStatusRefreshBtn.addEventListener('click', ()=> refreshLlmStatus(STATE.selectedRunId));
  if (DOM.expLlmSaveBtn) DOM.expLlmSaveBtn.addEventListener('click', ()=> saveLlmConfig());
  if (DOM.expLlmStartBtn) DOM.expLlmStartBtn.addEventListener('click', ()=> startLlmReview());
  if (DOM.expLlmStartForceBtn) DOM.expLlmStartForceBtn.addEventListener('click', ()=> startLlmReviewForce());
  if (DOM.expLlmCopyReportBtn) DOM.expLlmCopyReportBtn.addEventListener('click', ()=> copyLlmReport());
  if (DOM.expLlmDownloadReportBtn) DOM.expLlmDownloadReportBtn.addEventListener('click', ()=> downloadLlmReport());
  await refreshProtocol(false).catch(()=>{});
  await refreshDatasets(false).catch(()=>{});
  await refreshRuns(false).catch(()=>{});
  if (STATE.activeJobId) startJobPolling(STATE.activeJobId, STATE.activeRunId);
  await refreshLlmConfig(true).catch(()=>{});
  if (STATE.selectedRunId) await refreshLlmStatus(STATE.selectedRunId, true).catch(()=>{});
  await refreshLiveMonitor().catch(()=>{});
  LIVE_TIMER = setInterval(()=> { if (!STATE.livePaused) refreshLiveMonitor(); }, 3000);
  if (DOM.expChartModalCloseBtn) DOM.expChartModalCloseBtn.addEventListener('click', closeChartModal);
  if (DOM.expChartModalScrim) DOM.expChartModalScrim.addEventListener('click', closeChartModal);
  if (DOM.expChartModalFullscreenBtn) DOM.expChartModalFullscreenBtn.addEventListener('click', ()=> DOM.expChartModal?.classList.toggle('modal-fullscreen'));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && DOM.expChartModal && !DOM.expChartModal.hidden) closeChartModal();
  });
});
