const S = { d: null, r: null, settingsTab: "observatory", settingsDrafts: {} };
S.innateRulesBundle = null;
S.innateRulesDoc = null;
S.innateRulesSelectedId = null;
S.innateRulesDirty = false;

// Action runtime monitoring snapshot / 行动模块运行态监控快照
S.actionRuntime = null;
S.actionRuntimeAutoTimer = null;

// Phase B: graph editor runtime state / B目标：图形编辑器运行态
S.irGraph = {
  open: false,
  ruleId: null,
  graph: null,
  dirty: false,
  selectedNodeId: null,
  selectedEdgeId: null,
  connectingFrom: null, // nodeId
  // View state / 视图状态（缩放与平移）
  view: {
    zoom: 1.0,
    minZoom: 0.25,
    maxZoom: 1.75,
    // Side panels visibility / 侧栏显隐（让画布可扩展）
    showPalette: true,
    showProps: true,
  },
  world: {
    width: 1200,
    height: 720,
  },
};

const E = {};

// Sync viewport vars for stable modal sizing / 同步视口变量，稳定弹窗尺寸
// Why: some browsers/webviews compute 100vh/100vw incorrectly on first paint.
// 原因：部分浏览器/WebView 初次布局时 100vh/100vw 不稳定，导致弹窗工具栏“刚打开看不到”。
function syncViewportVars() {
  try {
    document.documentElement.style.setProperty("--app-vh", `${window.innerHeight}px`);
    document.documentElement.style.setProperty("--app-vw", `${window.innerWidth}px`);
  } catch {}
}

document.addEventListener("DOMContentLoaded", async () => {
  syncViewportVars();
  window.addEventListener("resize", syncViewportVars);
  [
    "overviewCards",
    "inputText",
    "tickCount",
    "checkTarget",
    "repairJobId",
    "pipelineEnableCognitiveStitchingChk",
    "pipelineEnableStructureLevelChk",
    "pipelineEnableGoalBCharSaStringModeChk",
    "pipelineEnableEnergyBalanceChk",
    "pipelineEnableDelayedTasksChk",
    "pipelineSwitchApplyBtn",
    "pipelineSwitchResetBtn",
    "pipelineSwitchFeedback",
    "actionFeedback",
    "sensorCards",
    "sensorUnits",
    "sensorGroups",
    "flowTimeline",
    "recentCycles",
    "actionResult",
    "stateCards",
    "stateEnergyByType",
    "stateItems",
    "hdbCards",
    "recentStructures",
    "recentGroups",
    "recentEpisodic",
    "memoryActivationSort",
    "memoryActivationList",
    "recentIssues",
    "repairJobs",
    "structureQuery",
    "groupQuery",
    "episodicLimit",
    "structureDetail",
    "groupDetail",
    "episodicDetail",
    "settingsTabs",
    "settingsPanel",
    "sensorMeta",
    "timeSensorMeta",
    "timeSensorBuckets",
    "timeSensorMemories",
    "flowMeta",
    "actionRuntimeRefreshBtn",
    "actionRuntimeAutoChk",
    "actionRuntimeMeta",
    "actionStopAllBtn",
    "actionStopMode",
    "actionStopValue",
    "actionStopValueList",
    "actionStopHoldTicks",
    "actionStopReason",
    "actionStopBtn",
    "actionStopFeedback",
    "actionRuntimeExecutors",
    "actionRuntimeNodes",
    "actionRuntimeExecuted",
    "stateMeta",
    "hdbMeta",
    "floatingRefreshBtn",
    "innateRulesMeta",
    "innateRulesFeedback",
    "innateRulesList",
    "innateRulesEditor",
    "innateRulesYaml",
    "innateRulesResult",
    "irGraphModal",
    "irGraphScrim",
    "irGraphLayout",
    "irGraphCanvas",
    "irGraphWorld",
    "irGraphEdges",
    "irGraphNodes",
    "irGraphProps",
    "irGraphHint",
    "irGraphFeedback",
    "irGraphTogglePaletteBtn",
    "irGraphTogglePropsBtn",
    "irGraphDeleteSelectedBtn2",
    "irGraphFullscreenBtn",
    "irGraphDeleteNodeBtn",
    "irGraphDeleteEdgeBtn",
    "irGraphZoomOutBtn",
    "irGraphZoomRange",
    "irGraphZoomInBtn",
    "irGraphZoomResetBtn",
    "irGraphZoomFitBtn",
    "irGraphZoomLabel",
  ].forEach((id) => {
    E[id] = document.getElementById(id);
  });

  B("runCycleBtn", runCycle);
  B("tickBtn", () => runTicks(1));
  B("runTicksBtn", () => runTicks(+E.tickCount?.value || 1));
  B("refreshBtn", () => refreshDashboard());
  // 强制刷新前端静态资源（用于解决浏览器缓存导致“看不到新 UI”的问题）。
  // 注意：这与“刷新数据”不同，它会重新加载页面。
  B("floatingRefreshBtn", () => forceReloadUi());
  B("reloadBtn", () => act("/api/reload", {}, "已重载配置。"));
  B("openReportBtn", () => act("/api/open_report", { trace_id: "latest" }, "已尝试打开报告。"));
  B("checkBtn", () => act("/api/check", { target: (E.checkTarget?.value || "").trim() || null }, "已执行自检。"));
  B("repairBtn", () => {
    const target = (E.checkTarget?.value || "").trim();
    target ? act("/api/repair", { target }, `已执行修复 ${target}。`) : fb("请填写修复目标 ID。", true);
  });
  B("repairAllBtn", () => act("/api/repair_all", {}, "已启动全局快速修复。"));
  B("idleConsolidateBtn", () => idleConsolidate());
  B("pipelineSwitchApplyBtn", () => applyPipelineSwitchesFromUi());
  B("pipelineSwitchResetBtn", () => resetPipelineSwitchesToEffective());
  B("stopRepairBtn", () => {
    const jobId = (E.repairJobId?.value || "").trim();
    jobId ? act("/api/stop_repair", { repair_job_id: jobId }, `已请求停止 ${jobId}。`) : fb("请填写修复任务 ID。", true);
  });
  B("clearHdbBtn", () => act("/api/clear_hdb", {}, "HDB 已清空。"));
  B("clearAllBtn", () => act("/api/clear_all", {}, "运行态数据已清空。"));
  B("queryStructureBtn", qStructure);
  B("queryGroupBtn", qGroup);
  B("queryEpisodicBtn", qEm);
  B("shutdownBtn", () => act("/api/shutdown", {}, "本地观测台正在关闭。"));
  B("actionRuntimeRefreshBtn", () => refreshActionRuntime());
  B("actionStopAllBtn", () => stopActionNodes({ mode: "all", value: null }));
  B("actionStopBtn", () => stopActionNodesFromUi());
  B("innateRulesRefreshBtn", () => refreshInnateRules());
  B("innateRulesValidateBtn", validateInnateRules);
  B("innateRulesSaveBtn", saveInnateRules);
  B("innateRulesSimulateBtn", simulateInnateRules);
  B("innateRulesAddFocusBtn", () => addInnateRuleTemplate("focus"));
  B("innateRulesAddWindowBtn", () => addInnateRuleTemplate("window"));
  B("innateRulesAddTimerBtn", () => addInnateRuleTemplate("timer"));
  B("innateRulesImportYamlBtn", importInnateRulesYaml);
  B("innateRulesExportYamlBtn", exportInnateRulesYaml);

  // Graph editor modal (Phase B) / 图形编辑器弹窗（B目标）
  B("irGraphCloseBtn", closeIrGraphModal);
  B("irGraphScrim", closeIrGraphModal);
  B("irGraphApplyBtn", applyIrGraphToSelectedRule);
  B("irGraphSyncBtn", syncIrGraphFromSelectedRule);
  B("irGraphAddCfsBtn", () => irGraphAddNode("cfs"));
  B("irGraphAddWindowBtn", () => irGraphAddNode("state_window"));
  B("irGraphAddTimerBtn", () => irGraphAddNode("timer"));
  B("irGraphAddMetricBtn", () => irGraphAddNode("metric"));
  B("irGraphAddCfsEmitBtn", () => irGraphAddNode("cfs_emit"));
  B("irGraphAddFocusBtn", () => irGraphAddNode("focus"));
  B("irGraphAddEmitBtn", () => irGraphAddNode("emit_script"));
  B("irGraphAddEmotionBtn", () => irGraphAddNode("emotion_update"));
  B("irGraphAddTriggerBtn", () => irGraphAddNode("action_trigger"));
  B("irGraphAddPoolEnergyBtn", () => irGraphAddNode("pool_energy"));
  B("irGraphAddBindAttrBtn", () => irGraphAddNode("pool_bind_attribute"));
  B("irGraphAddDelayBtn", () => irGraphAddNode("delay"));
  B("irGraphAddBranchBtn", () => irGraphAddNode("branch"));
  B("irGraphAddLogBtn", () => irGraphAddNode("log"));
  B("irGraphDeleteNodeBtn", deleteSelectedIrGraphNode);
  B("irGraphDeleteEdgeBtn", deleteSelectedIrGraphEdge);
  B("irGraphZoomOutBtn", () => irGraphAdjustZoom(-0.1));
  B("irGraphZoomInBtn", () => irGraphAdjustZoom(+0.1));
  B("irGraphZoomResetBtn", () => irGraphSetZoom(1.0, { keepCenter: true }));
  B("irGraphZoomFitBtn", () => irGraphFitToView());
  B("irGraphTogglePaletteBtn", () => irGraphToggleSidePanel("palette"));
  B("irGraphTogglePropsBtn", () => irGraphToggleSidePanel("props"));
  B("irGraphDeleteSelectedBtn2", irGraphDeleteSelectedFromToolbar);
  B("irGraphFullscreenBtn", irGraphToggleFullscreen);
  if (E.irGraphZoomRange) {
    E.irGraphZoomRange.addEventListener("input", () => {
      irGraphSetZoom(Number(E.irGraphZoomRange.value || 1.0), { keepCenter: true });
    });
  }

  if (E.inputText) {
    E.inputText.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        runCycle();
      }
    });
  }

  if (E.actionRuntimeAutoChk) {
    E.actionRuntimeAutoChk.addEventListener("change", () => {
      const on = Boolean(E.actionRuntimeAutoChk.checked);
      if (on) {
        startActionRuntimeAutoRefresh();
        refreshActionRuntime(true);
      } else {
        stopActionRuntimeAutoRefresh();
      }
    });
  }
  if (E.actionStopMode) {
    E.actionStopMode.addEventListener("change", () => {
      // Clear value to avoid stopping the wrong target after switching mode.
      // 切换模式后清空 value，避免误停止。
      if (E.actionStopValue) E.actionStopValue.value = "";
      renderActionStopValueList();
    });
  }

  // Load rules bundle once at startup (non-blocking).
  // 启动时拉取一次规则（不阻塞主刷新）。
  refreshInnateRules(true);
  // Load action runtime snapshot once at startup (non-blocking).
  // 启动时也拉取一次行动运行态快照（不阻塞主刷新）。
  refreshActionRuntime(true);
  if (E.structureQuery) {
    E.structureQuery.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        qStructure();
      }
    });
  }
  if (E.groupQuery) {
    E.groupQuery.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        qGroup();
      }
    });
  }
  if (E.episodicLimit) {
    E.episodicLimit.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        qEm();
      }
    });
  }
  if (E.memoryActivationSort) {
    E.memoryActivationSort.addEventListener("change", () => {
      hdbView();
      flow();
    });
  }

  await refreshDashboard(true);
});

function forceReloadUi() {
  try {
    const url = new URL(window.location.href);
    // Cache-busting query to ensure app.js/styles.css are re-fetched.
    // 通过时间戳参数强制绕过缓存。
    url.searchParams.set("v", String(Date.now()));
    // Use replace to avoid polluting history.
    // 用 replace 避免产生额外历史记录。
    window.location.replace(url.toString());
  } catch {
    // Fallback: plain reload.
    // 回退：直接刷新。
    window.location.reload();
  }
}

function B(id, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener("click", fn);
}

function n(value) {
  if (value === null || value === undefined || value === "") return "-";
  const num = typeof value === "number" ? value : Number(value);
  return Number.isFinite(num) ? num.toFixed(4) : "-";
}

function y(value) {
  return value ? "是" : "否";
}

function a(value) {
  return Array.isArray(value) ? value : [];
}

function esc(value) {
  return readableApText(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function tm(value) {
  const num = +value || 0;
  if (!num) return "-";
  try {
    return new Date(num).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return String(value);
  }
}

function fmtBytes(value) {
  const num = Number(value ?? 0) || 0;
  if (!(num > 0)) return "0B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let n0 = num;
  let u = 0;
  while (n0 >= 1024 && u < units.length - 1) {
    n0 /= 1024;
    u += 1;
  }
  const fixed = n0 >= 100 ? 0 : n0 >= 10 ? 1 : 2;
  return `${n0.toFixed(fixed)}${units[u]}`;
}

function pp(value) {
  return JSON.stringify(value ?? null, null, 2);
}

function readableApText(value) {
  const text = String(value ?? "");
  if (!text.includes(" + ")) return text;
  return text.replace(/\{([^{}]*)\}/g, (_, inner) => `{${String(inner).replace(/\s+\+\s+/g, " ")}}`);
}

// Plain object formatting helpers (no JSON in UI) / 纯文本格式化工具（UI 中不展示 JSON）
// 目标：让观测台更适合“验收/审计”而不是“直接丢一坨 JSON”。
function fmtScalarPlain(value, depth = 0) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return String(Number.isFinite(value) ? n(value) : value);
  if (typeof value === "boolean") return y(value);
  if (typeof value === "string") return readableApText(value);
  if (Array.isArray(value)) {
    const parts = value.map((v) => fmtScalarPlain(v, depth + 1)).filter(Boolean);
    return parts.length ? parts.slice(0, 12).join(" / ") : "-";
  }
  if (typeof value === "object") {
    if (depth >= 1) return "（对象）";
    const pairs = Object.entries(value || {}).filter(([k]) => String(k || "").trim());
    if (!pairs.length) return "（空对象）";
    return pairs
      .slice(0, 10)
      .map(([k, v]) => `${String(k)}:${fmtScalarPlain(v, depth + 1)}`)
      .join(" / ");
  }
  return String(value);
}

function fmtKvInline(obj, limit = 10) {
  const pairs = Object.entries(obj && typeof obj === "object" ? obj : {}).filter(([k]) => String(k || "").trim());
  if (!pairs.length) return "（无）";
  return pairs
    .slice(0, limit)
    .map(([k, v]) => `${String(k)}=${fmtScalarPlain(v)}`)
    .join(" / ");
}

function fmtRuleRef(obj) {
  // Format rule source for human readability (no JSON).
  // 规则来源格式化：尽量人类可读（不输出 JSON）。
  if (!obj || typeof obj !== "object") return "-";
  const title = String(obj.rule_title || obj.title || "").trim();
  const rid = String(obj.rule_id || "").trim();
  const phase = String(obj.rule_phase || obj.phase || "").trim();
  const priRaw = obj.rule_priority ?? obj.rule_pri ?? obj.priority;
  const pri = priRaw === null || priRaw === undefined ? "" : String(priRaw);
  const parts = [];
  if (title) parts.push(title);
  if (rid) parts.push(`id=${rid}`);
  if (phase) parts.push(`phase=${phase}`);
  if (pri) parts.push(`pri=${pri}`);
  return parts.length ? parts.join(" | ") : "-";
}

function fmtActionSourceBrief(src) {
  // Action/CFS source formatting for UI cards (no JSON).
  // 行动触发源/信号来源格式化（不输出 JSON）。
  if (!src) return "-";
  if (typeof src === "string") return src;
  if (typeof src !== "object") return String(src);
  const kind = String(src.kind || src.source_kind || "unknown");
  const rule = fmtRuleRef(src);
  const strength = src.strength !== undefined && src.strength !== null ? `strength=${n(src.strength)}` : "";
  const parts = [kind];
  if (rule && rule !== "-") parts.push(`规则 ${rule}`);
  if (strength) parts.push(strength);
  return parts.join(" | ");
}

function whenReasonsText(reasons, separator = " / ") {
  // IESM when-evaluation reasons are usually [{zh,en}, ...].
  // IESM 条件命中原因通常是 [{zh,en}, ...]，这里做中文优先提取。
  const items = a(reasons)
    .map((r) => {
      if (!r) return "";
      if (typeof r === "string") return r.trim();
      if (typeof r !== "object") return String(r).trim();
      return String(r.zh || r.message_zh || r.en || r.message_en || "").trim();
    })
    .filter(Boolean);
  return items.length ? items.join(separator) : "";
}

function kvListHtml(obj, { limit, emptyText } = {}) {
  const pairs = Object.entries(obj && typeof obj === "object" ? obj : {}).filter(([k]) => String(k || "").trim());
  if (!pairs.length) return `<div class="empty-state">${esc(emptyText || "无")}</div>`;
  const lim = Number.isFinite(+limit) ? Math.max(1, Math.min(256, +limit)) : 32;
  return `<div class="kv-list">${pairs
    .slice(0, lim)
    .map(([k, v]) => `<div class="kv-row"><div class="k">${esc(String(k))}</div><div class="v">${esc(fmtScalarPlain(v))}</div></div>`)
    .join("")}</div>`;
}

// =====================================================================
// Readable Render Helpers (No JSON in UI) / 可读渲染工具（UI 中不展示 JSON）
// =====================================================================

function ntLabel(code, labels) {
  // NT channel label helper / 递质通道中文名辅助
  const c = String(code || "").trim();
  const m = labels && typeof labels === "object" ? labels : {};
  const lab = String(m[c] || "").trim();
  return lab || (c ? c : "-");
}

function halfLifeTicksFromDecayRatio(decayRatio) {
  // Exponential decay half-life in ticks: ratio^t = 0.5 => t = ln(0.5)/ln(ratio)
  // 指数衰减半衰期（tick 数）：ratio^t = 0.5 => t = ln(0.5)/ln(ratio)
  const r = Number(decayRatio);
  if (!(r > 0 && r < 1)) return null;
  const t = Math.log(0.5) / Math.log(r);
  if (!Number.isFinite(t) || t <= 0) return null;
  return t;
}

function renderIesmAuditHtml(audit) {
  // IESM audit: show key numbers as cards + keep a small raw tail.
  // IESM 审计：关键数字用卡片展示，剩余字段做小尾巴保留（便于排查）。
  const a0 = audit && typeof audit === "object" ? audit : {};
  const cards = [
    card("耗时（elapsed_ms）", `${a0.elapsed_ms ?? "-"} ms`, `tick ${a0.tick_id || "-"} | trace ${a0.trace_id || "-"}`),
    card("规则总数（rule_count）", a0.rule_count ?? 0, `触发规则 ${a0.triggered_rule_count ?? 0}`),
    card(
      "CFS 信号（input -> output）",
      `${a0.cfs_signal_input_count ?? 0} -> ${a0.cfs_signal_output_count ?? 0}`,
      `本轮新增 ${a0.cfs_signal_emitted_count ?? 0}`,
    ),
    card("行动触发（action_trigger）", a0.action_trigger_count ?? 0, `聚焦指令 ${a0.focus_directive_count ?? 0}`),
    card("状态池效果（pool_effect）", a0.pool_effect_count ?? 0, `触发记录 ${a0.triggered_script_count ?? 0}`),
  ].join("");

  const notes = a(a0.notes);
  const notesHtml = notes.length
    ? `<div class="sub-section"><div class="sub-title">备注（notes）</div>${rows(
        notes.slice(0, 24).map((t, idx) => ({ title: `#${idx + 1}`, desc: String(t || "") || "-" })),
        "（无备注）",
      )}</div>`
    : `<div class="soft-note">备注（notes）：（无）</div>`;

  const known = new Set([
    "elapsed_ms",
    "rule_count",
    "triggered_rule_count",
    "triggered_script_count",
    "cfs_signal_input_count",
    "cfs_signal_emitted_count",
    "cfs_signal_output_count",
    "focus_directive_count",
    "emotion_update_key_count",
    "action_trigger_count",
    "pool_effect_count",
    "notes",
    "trace_id",
    "tick_id",
  ]);
  const tail = {};
  for (const [k, v] of Object.entries(a0)) {
    if (known.has(String(k))) continue;
    tail[String(k)] = v;
  }
  const tailHtml = Object.keys(tail).length
    ? `<div class="sub-section"><div class="sub-title">其他字段（raw tail）</div>${kvListHtml(tail, { limit: 32 })}</div>`
    : "";

  return `<div class="detail-grid">${cards}</div>${notesHtml}${tailHtml}`;
}

function renderThresholdModulationHtml(thresholdMod, ntLabels) {
  // Drive threshold modulation renderer / 行动阈值调制展示
  const m = thresholdMod && typeof thresholdMod === "object" ? thresholdMod : {};
  const scaleMin = m.threshold_scale_min ?? "-";
  const scaleMax = m.threshold_scale_max ?? "-";
  const fatigueOn = m.action_fatigue_enabled !== false;
  const coefs = m.threshold_scale_by_nt && typeof m.threshold_scale_by_nt === "object" ? m.threshold_scale_by_nt : {};

  const formula =
    "effective_threshold = base_threshold * clamp(1 + Σ(nt[ch]*coef), min, max) * fatigue_scale";
  const cards = [
    card("scale 下限（min）", scaleMin, "避免过度冲动导致失控"),
    card("scale 上限（max）", scaleMax, "避免过度保守导致不行动"),
    card("疲劳调制", fatigueOn ? "启用" : "关闭", "fatigue 会额外抬高阈值，避免无限循环"),
  ].join("");

  const coefRows = Object.entries(coefs)
    .map(([ch, coef]) => {
      const c = Number(coef);
      const effect = Number.isFinite(c) ? (c < 0 ? "降低阈值（更容易行动）" : c > 0 ? "提高阈值（更保守）" : "不影响") : "未知";
      return {
        title: `${ntLabel(ch, ntLabels)} · coef ${Number.isFinite(c) ? n(c) : String(coef)}`,
        desc: effect,
      };
    })
    .sort((l, r) => String(l.title).localeCompare(String(r.title), "zh-Hans-CN"));

  return [
    `<div class="soft-note">计算口径（MVP）：${esc(formula)}。说明：coef 为线性系数，实际行为以情绪状态与疲劳共同决定。</div>`,
    `<div class="detail-grid">${cards}</div>`,
    `<div class="sub-section"><div class="sub-title">递质系数（threshold_scale_by_nt）</div>${rows(
      coefRows,
      "（无系数映射）",
    )}</div>`,
  ].join("");
}

function renderActionLearningSummaryHtml(summary) {
  const s = summary && typeof summary === "object" ? summary : {};
  const examples = a(s.examples);
  const cards = [
    card("人形主路径", s.humanlike_runtime_sync_enabled === false ? "关闭" : "开启", `全局信号节点 ${s.runtime_signal_node_active_count ?? 0} | 行动节点 ${s.runtime_action_node_active_count ?? 0}`),
    card("局部塑形开关", s.local_drive_modulation_enabled === false ? "关闭" : "开启", "对象级 reward/punish 是否参与本轮 drive 塑形"),
    card("目标行动节点", s.targeted_node_count ?? 0, "带 target_ref / target_item 的行动节点"),
    card("局部命中节点", s.local_lookup_hit_count ?? 0, `text_fallback ${s.local_lookup_text_fallback_hit_count ?? 0} | miss ${s.local_lookup_miss_count ?? 0} / skipped ${s.local_lookup_skipped_count ?? 0}`),
    card("目标缺失 / 关闭", s.local_target_missing_count ?? 0, `disabled ${s.local_modulation_disabled_count ?? 0}`),
    card("局部调制节点", s.local_modulated_node_count ?? 0, `平均 scale ${n(s.local_drive_scale_mean ?? 1.0)}`),
    card("局部奖励增益", n(s.local_reward_drive_bonus_total ?? 0), "对象级 reward 带来的 drive 额外放大"),
    card("局部惩罚代价", n(s.local_punish_drive_penalty_total ?? 0), "对象级 punish 带来的 drive 压低"),
    card("行动节点执行显影", s.runtime_action_node_executed_count ?? 0, `target_ref ${s.runtime_action_target_ref_count ?? 0} | target_item ${s.runtime_action_target_item_count ?? 0}`),
  ].join("");
  const exampleRows = rows(examples.map((item) => ({
    title: `${item.action_kind || "-"} · ${item.action_id || "-"}`,
    desc:
      `目标 ${item.target_display || item.target_ref_object_id || item.target_item_id || "-"}\n` +
      `reward ${n(item.reward)} | punish ${n(item.punish)} | scale ${n(item.scale_clamped)}\n` +
      `奖励增益 ${n(item.reward_bonus_gain)} | 惩罚代价 ${n(item.punish_penalty_gain)}`,
  })), "本轮没有局部塑形命中的行动节点。");
  return `<div class="detail-grid">${cards}</div><div class="sub-section"><div class="sub-title">局部塑形样例</div>${exampleRows}</div>`;
}

function localModReasonLabel(mod) {
  const reason = mod && typeof mod === "object" && mod.detail && typeof mod.detail === "object"
    ? String(mod.detail.reason || "")
    : "";
  const labels = {
    local_feedback_not_found: "未命中反馈",
    config_disabled: "全局关闭",
    node_disabled: "节点关闭",
    target_required_but_missing: "缺少目标",
    lookup_target_missing: "无目标可查",
    non_positive_gain: "gain<=0",
  };
  return labels[reason] || reason || "跳过";
}

function formatLocalDriveModulationText(mod) {
  const m = mod && typeof mod === "object" ? mod : {};
  const reason = m.detail && typeof m.detail === "object" ? String(m.detail.reason || "") : "";
  let status = String(m.lookup_status || "");
  if (!status) {
    if (m.lookup_hit) status = "hit";
    else if (reason === "local_feedback_not_found") status = "miss";
    else status = "skipped";
  }
  if (status === "hit") {
    return `命中 reward ${n(m.reward)} / punish ${n(m.punish)} / scale ${n(m.scale_clamped ?? 1)}`;
  }
  if (status === "miss") {
    return "未命中反馈";
  }
  return `跳过 ${localModReasonLabel(m)}`;
}

function renderEmotionNtStateHtml(emotion) {
  // Emotion NT channels renderer / 情绪递质通道展示（中文优先）
  const e = emotion && typeof emotion === "object" ? emotion : {};
  const labels = e.nt_channel_labels || {};
  const snap = e.nt_state_snapshot || {};
  const channels = (snap.channels && typeof snap.channels === "object" ? snap.channels : {}) || {};
  const after = (e.nt_state_after && typeof e.nt_state_after === "object" ? e.nt_state_after : {}) || {};
  const channelKeys = emotionChannelKeys(e);

  const soft = snap.soft_cap && typeof snap.soft_cap === "object" ? snap.soft_cap : {};
  const softEnabled = soft.enabled !== false;
  const softNote = softEnabled
    ? `<div class="soft-note">软上限（极限算法）已启用：eps=${esc(String(soft.eps ?? "-"))}，k_default=${esc(String(soft.k_default ?? "-"))}。公式（正向增量）：${esc(String(soft.formula_zh || "after=max-gap*exp(-delta/k)"))}</div>`
    : `<div class="soft-note">软上限（极限算法）未启用：通道会用硬钳制 clamp 到 max。</div>`;

  const rowsData = channelKeys
    .map((ch) => {
      const spec = channels[ch] || {};
      const v = after[ch] ?? spec.value ?? 0.0;
      const lo = spec.min ?? 0.0;
      const hi = spec.max ?? 1.0;
      const base = spec.base ?? 0.0;
      const k = spec.soft_cap_k ?? soft.k_default ?? "-";
      const ratio = spec.decay_ratio ?? e.decay?.global_decay_ratio ?? "-";
      const hl = halfLifeTicksFromDecayRatio(ratio);
      const hlText = hl ? `半衰期 ~${n(hl)} tick` : "半衰期 -";
      return {
        title: `${ntLabel(ch, labels)} · ${n(v)}`,
        desc:
          `范围 [${n(lo)}, ${n(hi)}) | 基线 base ${n(base)} | 衰减 decay_ratio ${typeof ratio === "number" ? n(ratio) : String(ratio)} | ${hlText}\n` +
          `软上限参数 k ${typeof k === "number" ? n(k) : String(k)}`,
      };
    })
    .sort((l, r) => String(l.title).localeCompare(String(r.title), "zh-Hans-CN"));

  return softNote + rows(rowsData, "当前没有递质通道状态。");
}

function renderEmotionDeltasHtml(deltas, ntLabels) {
  const d = deltas && typeof deltas === "object" ? deltas : {};
  const rowsData = Object.entries(d)
    .map(([ch, dv]) => ({
      title: `${ntLabel(ch, ntLabels)} · Δ ${n(dv)}`,
      desc: "说明：这是本 tick 实际写入该通道的增量（已包含脚本增量 + CFS 增量）。",
    }))
    .sort((l, r) => String(l.title).localeCompare(String(r.title), "zh-Hans-CN"));
  return rows(rowsData, "本轮没有通道增量。");
}

function renderEmotionModulationHtml(modulation, ntLabels) {
  // Modulation renderer: prioritize attention modulation (current prototype focuses on this).
  // 调制展示：当前原型优先展示 attention 调制（高收益、可验收）。
  const m = modulation && typeof modulation === "object" ? modulation : {};
  const att = m.attention && typeof m.attention === "object" ? m.attention : null;
  if (!att) return `<div class="empty-state">本轮没有调制输出。</div>`;

  const cards = [
    card("attention.top_n", att.top_n ?? "-", "下一 tick 进入 CAM 的对象数量上限"),
    card("CP 权重", att.priority_weight_cp_abs ?? "-", "认知压（|CP|）对注意力优先级的权重"),
    card("疲劳权重", att.priority_weight_fatigue ?? "-", "疲劳对注意力优先级的权重"),
    card("min_total_energy", att.min_total_energy ?? "-", "低于该能量的对象可能被忽略"),
  ].join("");

  const nts = att.nt_snapshot && typeof att.nt_snapshot === "object" ? att.nt_snapshot : {};
  const ntLines = Object.entries(nts)
    .map(([ch, v]) => `${ntLabel(ch, ntLabels)}=${n(v)}`)
    .join(" / ");

  return [
    `<div class="detail-grid">${cards}</div>`,
    `<div class="soft-note">递质快照（用于解释调制来源）：${esc(ntLines || "（无）")}</div>`,
  ].join("");
}

// Minimal YAML-like dump for config editing (no JSON in textarea).
// 用于“设置”页 dict/list 的编辑展示：输出简易 YAML（避免前端出现 JSON）。
function yamlScalarText(value) {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  const s = String(value);
  if (!s) return '""';
  const needsQuote =
    /[\n\r\t]/.test(s) ||
    /[:#\[\]{},&*!|>'"%@`]/.test(s) ||
    s.startsWith("-") ||
    s.startsWith(" ") ||
    s.endsWith(" ");
  if (!needsQuote) return s;
  return `"${s.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

function dumpYamlLike(value, indent = 0, depth = 0) {
  const pad = " ".repeat(Math.max(0, indent));
  if (depth > 3) return `${pad}# ...`;
  if (Array.isArray(value)) {
    if (!value.length) return `${pad}[]`;
    const lines = [];
    for (const item of value.slice(0, 64)) {
      if (item && typeof item === "object" && !Array.isArray(item)) {
        const entries = Object.entries(item).filter(([k]) => String(k || "").trim());
        if (!entries.length) {
          lines.push(`${pad}- {}`);
          continue;
        }
        const [k0, v0] = entries[0];
        lines.push(`${pad}- ${String(k0)}: ${item && typeof v0 === "object" ? "" : yamlScalarText(v0)}`);
        for (const [k, v] of entries.slice(1)) {
          if (v && typeof v === "object") {
            lines.push(`${pad}  ${String(k)}:`);
            lines.push(dumpYamlLike(v, indent + 4, depth + 1));
          } else {
            lines.push(`${pad}  ${String(k)}: ${yamlScalarText(v)}`);
          }
        }
      } else {
        lines.push(`${pad}- ${yamlScalarText(item)}`);
      }
    }
    return lines.join("\n");
  }
  if (value && typeof value === "object") {
    const pairs = Object.entries(value).filter(([k]) => String(k || "").trim());
    if (!pairs.length) return `${pad}{}`;
    const lines = [];
    for (const [k, v] of pairs.slice(0, 64)) {
      if (Array.isArray(v) || (v && typeof v === "object")) {
        lines.push(`${pad}${String(k)}:`);
        lines.push(dumpYamlLike(v, indent + 2, depth + 1));
      } else {
        lines.push(`${pad}${String(k)}: ${yamlScalarText(v)}`);
      }
    }
    return lines.join("\n");
  }
  return `${pad}${yamlScalarText(value)}`;
}

function te(item) {
  return +(item?.total_energy ?? ((+item?.er || 0) + (+item?.ev || 0))) || 0;
}

function textList(values, separator = " / ") {
  const items = a(values)
    .map((value) => String(value ?? "").trim())
    .filter(Boolean);
  return items.length ? items.join(separator) : "";
}

function listOr(values, fallback = "无", separator = " / ") {
  return textList(values, separator) || fallback;
}

// CFS kind label / 认知感受 kind 中文名（含简写）
// 说明：用户界面尽量中文优先；保留英文 kind 便于与日志/规则字段对齐。
function cfsKindLabel(kind) {
  const k = String(kind || "").trim();
  const map = {
    dissonance: "违和感（dissonance）",
    correctness: "正确感（correctness）",
    correct_event: "正确事件/正确感（correct_event）",
    surprise: "惊（surprise）",
    expectation: "期待（expectation）",
    expectation_verified: "期待验证（expectation_verified）",
    expectation_unverified: "期待不验（expectation_unverified）",
    pressure: "压力（pressure）",
    pressure_verified: "压力验证（pressure_verified）",
    pressure_unverified: "压力不验（pressure_unverified）",
    complexity: "繁/简（complexity）",
    simplicity: "简感/轻松感（simplicity）",
    cfs_simplicity: "简感/轻松感（simplicity）",
    relief: "释然感/缓解感（relief）",
    reassurance: "安心感/安抚感（reassurance）",
    repetition: "重复感/疲劳（repetition）",
    grasp: "把握感/置信度（grasp）",
  };
  return map[k] || (k ? `未知感受（${k}）` : "-");
}

function cfsScopeLabel(scope) {
  const s = String(scope || "");
  if (s === "object") return "对象（object）";
  if (s === "global") return "全局（global）";
  return s || "-";
}

function refTypeLabel(refType) {
  const t = String(refType || "");
  const map = {
    sa: "SA（基础刺激元）",
    csa: "CSA（组合刺激元，门控约束）",
    st: "ST（结构）",
    sg: "SG（结构组）",
    em: "EM（情景记忆）",
    cfs_signal: "CFS（认知感受信号）",
    action_node: "行动节点（Action Node，行动意图）",
  };
  return map[t] || (t ? t : "-");
}

function htmlLines(lines) {
  const safe = a(lines)
    .map((line) => String(line ?? "").trim())
    .filter(Boolean)
    .map(esc);
  return safe.length ? safe.join("<br>") : "无";
}

function projectionTargetId(item) {
  return item?.memory_id || item?.structure_id || item?.target_structure_id || "-";
}

function projectionKindLabel(kind, memoryPathMode = "", projectedRefType = "") {
  const key = String(kind || "").trim();
  const runtimeOnly = String(memoryPathMode || "").trim() === "runtime_em_only";
  if (key === "memory_runtime_projection") {
    const projectionType = String(projectedRefType || "").trim().toLowerCase();
    if (projectionType === "em") return "残差运行态对象（EM 兼容壳）";
    if (projectionType === "st") return "残差运行态对象（ST 语义）";
    return "残差运行态对象";
  }
  const map = {
    structure: "结构对象（ST）",
    memory: runtimeOnly ? "残差记忆对象" : "记忆对象（EM）",
  };
  return map[key] || (key ? key : "结构对象（ST）");
}

function fmtStateTitle(item) {
  const t = item.ref_object_type || item.object_type || "obj";
  return `[${refTypeLabel(t)}] ${readableApText(item.display || item.display_text || item.ref_object_id || "-")}`;
}

function residualKindLabel(kind) {
  const k = String(kind || "").trim();
  const map = {
    stimulus_raw_residual: "刺激级原始残差",
    structure_raw_residual: "结构级原始残差",
    residual_context: "残差上下文链",
    residual_context_common: "残差共有结构",
  };
  return map[k] || (k ? k : "非残差链直出");
}

function runtimeMetaView(item) {
  const snap = item?.ref_snapshot && typeof item.ref_snapshot === "object" ? item.ref_snapshot : {};
  return { ...snap, ...item, ref_snapshot: snap };
}

function fmtContextObjectRef(refType, refId) {
  const id = String(refId || "").trim();
  if (!id) return "-";
  const typeLabel = refTypeLabel(refType);
  return typeLabel && typeLabel !== "-" ? `${typeLabel}:${id}` : id;
}

function contextPathDepthOf(item) {
  const depth = a(item?.context_path_ids).map((x) => String(x || "").trim()).filter(Boolean).length;
  if (depth > 0) return depth;
  return item?.context_ref_object_id || item?.context_owner_structure_id ? 1 : 0;
}

function fmtContextPath(pathIds, maxLen = 4) {
  const ids = a(pathIds).map((x) => String(x || "").trim()).filter(Boolean);
  if (!ids.length) return "无显式来源路径";
  const head = ids.slice(0, maxLen).join(" → ");
  return ids.length > maxLen ? `${head} → …（共 ${ids.length} 层）` : head;
}

function hasContextMeta(item) {
  const view = runtimeMetaView(item);
  return Boolean(
    view?.context_ref_object_id ||
    view?.context_owner_id ||
    view?.context_owner_structure_id ||
    a(view?.context_path_ids).length ||
    view?.context_text,
  );
}

function hasResidualMeta(item) {
  const view = runtimeMetaView(item);
  return Boolean(view?.residual_origin_kind || view?.residual_origin_entry_id || view?.residual_kind || view?.source_em_id);
}

function isResidualMemoryRuntimeItem(item) {
  const view = runtimeMetaView(item);
  const refType = String(view?.ref_object_type || view?.object_type || "").trim().toLowerCase();
  const sourceEmId = String(view?.source_em_id || view?.memory_id || "").trim();
  const residualKind = String(view?.residual_kind || "").trim().toLowerCase();
  if (refType === "em" && sourceEmId) return true;
  if (String(view?.residual_memory_as_structure || "").toLowerCase() === "true" && sourceEmId) return true;
  return Boolean(sourceEmId && residualKind === "memory");
}

function residualRuntimeObjectTypeLabel(item) {
  const view = runtimeMetaView(item);
  const projectionType = String(
    view?.projection_ref_object_type ||
    view?.projected_ref_object_type ||
    view?.memory_projection_object_type_actual ||
    view?.ref_object_type ||
    view?.object_type ||
    ""
  ).trim().toLowerCase();
  if (projectionType === "em") return "残差运行态对象（EM 兼容壳）";
  if (projectionType === "st") return "残差运行态对象（ST 语义）";
  return "残差运行态对象";
}

function fmtContextSummary(item) {
  if (!item) return "无对象";
  const view = runtimeMetaView(item);
  const ownerId = String(view.context_owner_id || view.context_owner_structure_id || "").trim();
  const refId = String(view.context_ref_object_id || "").trim();
  const refType = String(view.context_ref_object_type || "").trim();
  const contextText = String(view.context_text || "").trim();
  const pathIds = a(view.context_path_ids).map((x) => String(x || "").trim()).filter(Boolean);
  const depth = contextPathDepthOf(view);
  if (!ownerId && !refId && !pathIds.length && !contextText) {
    return "当前没有显式来源字段，通常表示它是完整身份对象或本轮直接进入的叶子对象。";
  }
  const parts = [];
  if (contextText) {
    parts.push(`来源文本 ${readableApText(contextText)}`);
  }
  if (ownerId) {
    parts.push(`上级结构 ${ownerId}`);
  }
  if (refId && refId !== ownerId) {
    parts.push(`直接参考 ${fmtContextObjectRef(refType, refId)}`);
  }
  parts.push(`路径深度 ${depth}`);
  parts.push(`路径 ${fmtContextPath(pathIds)}`);
  return parts.join(" | ");
}

function fmtResidualSummary(item) {
  if (!item) return "无对象";
  const view = runtimeMetaView(item);
  const kind = String(view.residual_origin_kind || "").trim();
  const residualKind = String(view.residual_kind || "").trim();
  const sourceEmId = String(view.source_em_id || "").trim();
  const entryId = String(view.residual_origin_entry_id || "").trim();
  if (!kind && !entryId && !residualKind && !sourceEmId) {
    return "当前不在显式残差链上，更接近直接命中/直接投影对象。";
  }
  const parts = [];
  if (residualKind === "memory") parts.push("类型 记忆残差");
  else if (residualKind === "structure") parts.push("类型 结构残差");
  if (kind) parts.push(`来源 ${residualKindLabel(kind)}`);
  if (sourceEmId) parts.push(`记忆源 ${sourceEmId}`);
  if (entryId) parts.push(`残差条目 ${entryId}`);
  return parts.join(" | ");
}

function buildContextAuditRows(items, limit = 6) {
  return a(items)
    .filter((item) => hasContextMeta(item) || hasResidualMeta(item))
    .slice(0, limit)
    .map((item) => ({
      title: fmtStateTitle(item),
      desc:
        `上下文 ${fmtContextSummary(item)}\n` +
        `残差 ${fmtResidualSummary(item)}\n` +
        `ER ${n(item.er)} | EV ${n(item.ev)} | CP ${n(item.cp_abs)} | 总 ${n(te(item))}`,
    }));
}

function buildStructureContextRows(items, limit = 6) {
  return a(items)
    .filter((item) => hasContextMeta(item) || hasResidualMeta(item))
    .slice(0, limit)
    .map((item) => ({
      title: `${readableApText(item.display_text || item.structure_id || "-")} · ${item.structure_id || "-"}`,
      desc:
        `来源/激活路径 ${fmtContextSummary(item)}\n` +
        `残差 ${fmtResidualSummary(item)}\n` +
        `签名 ${item.signature || "-"}\n` +
        `权重 W ${n(item.base_weight)} | 近因增益 G ${n(item.recent_gain)} | 疲劳 ${n(item.fatigue)}`,
    }));
}

function fmtGroupText(group) {
  if (!group) return "";
  if (typeof group?.display_text === "string" && group.display_text.trim()) {
    return readableApText(group.display_text.trim());
  }

  const orderedUnits = a(group?.units)
    .filter((unit) => unit && (unit.unit_id || unit.id || unit.token || unit.display_text))
    .slice()
    .sort((left, right) =>
      (+left?.sequence_index || 0) - (+right?.sequence_index || 0) ||
      String(left?.unit_id || left?.id || "").localeCompare(String(right?.unit_id || right?.id || "")),
    );
  if (!orderedUnits.length) {
    const rawTokens = a(group?.tokens).map((token) => String(token || "").trim()).filter(Boolean);
    return rawTokens.length ? `{${rawTokens.join(" ")}}` : "";
  }

  const unitsById = new Map(
    orderedUnits
      .map((unit) => [String(unit?.unit_id || unit?.id || ""), unit])
      .filter(([id]) => Boolean(id)),
  );
  const orderedBundles = a(group?.csa_bundles)
    .filter((bundle) => bundle && (bundle.bundle_id || bundle.anchor_unit_id))
    .slice()
    .sort((left, right) =>
      (+unitsById.get(String(left?.anchor_unit_id || ""))?.sequence_index || 0) -
        (+unitsById.get(String(right?.anchor_unit_id || ""))?.sequence_index || 0) ||
      String(left?.bundle_id || "").localeCompare(String(right?.bundle_id || "")),
    );
  const bundleById = new Map(
    orderedBundles
      .map((bundle) => [String(bundle?.bundle_id || ""), bundle])
      .filter(([id]) => Boolean(id)),
  );

  const emittedBundleIds = new Set();
  const coveredUnitIds = new Set();
  const rawSegments = [];
  const segmentKey = (unit) => [
    String(unit?.source_type || ""),
    String(unit?.origin_frame_id || ""),
    String(unit?.source_group_index ?? unit?.group_index ?? 0),
    String(Boolean(unit?.order_sensitive || group?.order_sensitive)),
    String(unit?.string_unit_kind || group?.string_unit_kind || ""),
    String(unit?.string_token_text || group?.string_token_text || ""),
  ].join("");

  orderedUnits.forEach((unit) => {
    const unitId = String(unit?.unit_id || unit?.id || "");
    if (unitId && coveredUnitIds.has(unitId)) return;

    const bundleId = String(unit?.bundle_id || "");
    const bundle = bundleId ? bundleById.get(bundleId) : null;
    if (bundle && !emittedBundleIds.has(bundleId) && unitId === String(bundle?.anchor_unit_id || "")) {
      const memberTokens = a(bundle?.member_unit_ids)
        .map((memberId) => unitsById.get(String(memberId || "")))
        .map((member) => member?.token || member?.display_text || "")
        .filter(Boolean);
      if (memberTokens.length) {
        rawSegments.push({ text: `(${memberTokens.join(" ")})`, grouped: false });
        emittedBundleIds.add(bundleId);
        a(bundle?.member_unit_ids).forEach((memberId) => {
          const text = String(memberId || "");
          if (text) coveredUnitIds.add(text);
        });
        return;
      }
    }

    const token = String(unit?.token || unit?.display_text || "").trim();
    if (!token) return;
    if (unitId) coveredUnitIds.add(unitId);
    rawSegments.push({
      text: token,
      grouped: Boolean(unit?.order_sensitive || group?.order_sensitive) && String(unit?.string_unit_kind || group?.string_unit_kind || "") === "char_sequence",
      key: segmentKey(unit),
    });
  });

  const segments = [];
  for (let i = 0; i < rawSegments.length; i += 1) {
    const current = rawSegments[i];
    if (!current?.grouped) {
      segments.push(current?.text || "");
      continue;
    }
    const chars = [current.text || ""];
    while (i + 1 < rawSegments.length && rawSegments[i + 1]?.grouped && rawSegments[i + 1]?.key === current.key) {
      i += 1;
      chars.push(rawSegments[i]?.text || "");
    }
    segments.push(chars.join(""));
  }
  const deduped = [];
  const seen = new Set();
  segments.forEach((segment) => {
    const text = String(segment || "").trim();
    if (!text || seen.has(text)) return;
    seen.add(text);
    deduped.push(text);
  });

  return deduped.length ? `{${deduped.join(" ")}}` : "";
}

function fmtSequenceGroups(groups) {
  return a(groups)
    .map((group) => fmtGroupText(group))
    .filter(Boolean)
    .join(" / ");
}

function groupedTextFromItem(item) {
  if (!item) return "";
  return (
    fmtSequenceGroups(item.sequence_groups) ||
    fmtSequenceGroups(item.canonical_sequence_groups) ||
    fmtSequenceGroups(item.raw_sequence_groups) ||
    fmtSequenceGroups(item.group_structure?.sequence_groups) ||
    fmtSequenceGroups(item.structure?.sequence_groups)
  );
}

function pickGroupedText(item, fallback = "-") {
  if (!item) return fallback;
  return readableApText(
    item.grouped_display_text ||
    item.canonical_grouped_display_text ||
    item.raw_grouped_display_text ||
    groupedTextFromItem(item) ||
    item.common_display ||
    item.display_text ||
    fallback
  );
}

function fmtCommonGroups(groups) {
  return (
    fmtSequenceGroups(groups) ||
    a(groups)
      .map((group) => group?.display_text || "-")
      .filter(Boolean)
      .join(" / ")
  );
}

function fmtChain(items, mode) {
  return htmlLines(
    a(items).map((item) => {
      if (mode === "structure") {
        return `${item.owner_display_text || item.owner_id || "-"}(${item.owner_kind || "-"}) -> ${item.candidate_count || 0}`;
      }
      return `${item.owner_display_text || item.owner_structure_id || "-"} -> ${item.candidate_count || 0}`;
    }),
  );
}

function fmtBudget(entries) {
  return htmlLines(
    Object.entries(entries || {}).map(([key, value]) => {
      if (typeof value === "object" && value) {
        return `${key}: ER ${n(value.er)} / EV ${n(value.ev)} / Total ${n(value.total)}`;
      }
      return `${key}: ${value}`;
    }),
  );
}

function fmtSensorUnit(unit) {
  const hidden = unit.display_visible === false ? "[hidden] " : "";
  const attr = unit.attribute_name ? `\n属性 ${unit.attribute_name} = ${unit.attribute_value}` : "";
  const bundle = unit.bundle_display ? `\nCSA ${unit.bundle_display}` : "";
  const suppression = Number(unit.suppression_ratio || 0);
  const fatigue = suppression > 0 || Number(unit.window_count || 0) > 0
    ? `\n感受器疲劳 suppression ${n(suppression)} | ER ${n(unit.er_before_fatigue)} -> ${n(unit.er_after_fatigue)} | count ${unit.window_count || 0}/${unit.threshold_count || 0} | window ${unit.window_rounds || 0} | round ${unit.sensor_round || 0}`
    : "";
  return {
    title: `${hidden}${unit.display || unit.token || "未命名"} | ${unit.unit_kind || "unit"} / ${unit.role || "-"}`,
    desc: `source ${unit.source_type || "current"} / G${unit.group_index ?? 0} / seq ${unit.sequence_index ?? 0}\nER ${n(unit.er)} | EV ${n(unit.ev)} | Total ${n(unit.total_energy)}${attr}${bundle}${fatigue}\n对象 ${unit.id || "-"}`,
  };
}

function fmtStimulusGroup(group) {
  const groupedText = fmtSequenceGroups([group]) || group.display_text || "-";
  return {
    title: `${group.source_type || "unknown"} / G${group.group_index ?? 0}`,
    desc:
      `时序组 / Sequence Group ${groupedText}\n` +
      `可见文本 / Visible ${group.visible_text || group.display_text || "-"}\n` +
      `Tokens ${listOr(group.tokens, "-", " / ")}\n` +
      `Visible ${listOr(group.visible_tokens, "-", " / ")}\n` +
      `SA ${group.sa_count || 0} | CSA bundles ${group.csa_count || 0} | ER ${n(group.total_er)} | EV ${n(group.total_ev)}\n` +
      `Bundles ${listOr(group.csa_bundles, "-", " | ")}\n` +
      `来源统计（source_type_counts）${fmtKvInline(group.source_type_counts || {})}（用于检查外源/内源是否合流进入同一时序组）`,
  };
}

function fmtProjectionCard(item) {
  const targetId = projectionTargetId(item);
  const view = runtimeMetaView(item);
  const extraLines = [];
  const memoryPathMode = String(item?.path_mode || "").trim();
  if (hasContextMeta(view)) extraLines.push(`上下文 ${fmtContextSummary(view)}`);
  if (hasResidualMeta(view)) extraLines.push(`残差 ${fmtResidualSummary(view)}`);
  return {
    title: `${item.display_text || targetId || "-"} · ${projectionKindLabel(item?.projection_kind, memoryPathMode, item?.projected_ref_object_type || item?.projection_ref_object_type || "")}`,
    desc:
      `目标 ${targetId}` +
      `${item.backing_structure_id ? ` | backing ${item.backing_structure_id}` : ""}\n` +
      `ER ${n(item.er)} | EV ${n(item.ev)}\n` +
      `原因 ${item.reason || "-"}${item.result ? ` | 结果 ${item.result}` : ""}` +
      `${extraLines.length ? `\n${extraLines.join("\n")}` : ""}`,
  };
}

function currentMemorySort() {
  return E.memoryActivationSort?.value || "energy_desc";
}

function sortMemoryActivations(items, sortBy = "energy_desc") {
  const rows = a(items).slice();
  rows.sort((left, right) => {
    if (sortBy === "recent_desc") {
      return (
        (+right?.last_updated_at || 0) - (+left?.last_updated_at || 0) ||
        te(right) - te(left) ||
        String(left?.memory_id || "").localeCompare(String(right?.memory_id || ""))
      );
    }
    return (
      te(right) - te(left) ||
      (+right?.last_updated_at || 0) - (+left?.last_updated_at || 0) ||
      String(left?.memory_id || "").localeCompare(String(right?.memory_id || ""))
    );
  });
  return rows;
}

function emotionChannelKeys(emotion) {
  const e = emotion && typeof emotion === "object" ? emotion : {};
  const keys = new Set();
  const labels = e.nt_channel_labels && typeof e.nt_channel_labels === "object" ? e.nt_channel_labels : {};
  const meta = e.nt_channel_meta && typeof e.nt_channel_meta === "object" ? e.nt_channel_meta : {};
  const after = e.nt_state_after && typeof e.nt_state_after === "object" ? e.nt_state_after : {};
  const channels = e.nt_state_snapshot?.channels && typeof e.nt_state_snapshot.channels === "object"
    ? e.nt_state_snapshot.channels
    : {};
  [labels, meta, after, channels].forEach((bucket) => {
    Object.keys(bucket || {}).forEach((key) => {
      const text = String(key || "").trim();
      if (text) keys.add(text);
    });
  });
  return Array.from(keys).sort((left, right) => String(left).localeCompare(String(right), "zh-Hans-CN"));
}

function inductionModeLabel(mode) {
  const key = String(mode || "").trim();
  if (key === "er_induction") return "ER 诱发";
  if (key === "ev_propagation") return "EV 传播";
  return key || "-";
}

function memoryPathModeFromActivation(memoryActivation) {
  const activation = memoryActivation && typeof memoryActivation === "object" ? memoryActivation : {};
  return activation.path_mode || (activation.dedicated_memory_pool_enabled === false ? "runtime_em_only" : "dedicated_map");
}

function buildMemoryUiModel(report, hdbSnapshot) {
  const rpt = report && typeof report === "object" ? report : {};
  const hdb = hdbSnapshot && typeof hdbSnapshot === "object" ? hdbSnapshot : {};
  const hdbSummary = hdb.summary && typeof hdb.summary === "object" ? hdb.summary : hdb;
  const memoryActivation = rpt.memory_activation && typeof rpt.memory_activation === "object" ? rpt.memory_activation : {};
  const snapshot = memoryActivation.snapshot && typeof memoryActivation.snapshot === "object" ? memoryActivation.snapshot : {};
  const snapshotSummary = snapshot.summary && typeof snapshot.summary === "object" ? snapshot.summary : {};
  const pathMode = memoryPathModeFromActivation(memoryActivation);
  const runtimeOnly = pathMode === "runtime_em_only";
  const count = runtimeOnly
    ? +snapshotSummary.count || 0
    : (+hdbSummary.memory_activation_count || +snapshotSummary.count || 0);
  const totalEr = runtimeOnly
    ? +snapshotSummary.total_er || 0
    : (+hdbSummary.memory_activation_total_er || +snapshotSummary.total_er || 0);
  const totalEv = runtimeOnly
    ? +snapshotSummary.total_ev || 0
    : (+hdbSummary.memory_activation_total_ev || +snapshotSummary.total_ev || 0);
  const totalEnergy = runtimeOnly
    ? +snapshotSummary.total_energy || (totalEr + totalEv)
    : (+hdbSummary.memory_activation_total_energy || +snapshotSummary.total_energy || (totalEr + totalEv));
  return {
    pathMode,
    runtimeOnly,
    pathLabel: runtimeOnly ? "状态池残差对象主链" : "MAP 兼容主链",
    summaryLabel: runtimeOnly ? "运行态残差对象" : "MAP 兼容池（旧记忆赋能）",
    shortLabel: runtimeOnly ? "残差对象" : "MAP 兼容池",
    listTitle: runtimeOnly ? "残差对象视图" : "MAP 兼容视图",
    listEmptyText: runtimeOnly ? "当前没有活跃残差对象。" : "当前没有 MAP 兼容条目。",
    count,
    totalEr,
    totalEv,
    totalEnergy,
    items: runtimeOnly ? a(snapshot.items) : a(hdb.recent_memory_activations),
    applyLabel: runtimeOnly ? "残差对象赋能" : "MAP兼容赋能",
    applyNote: runtimeOnly
      ? `状态池残差对象主链 | 总EV ${n(totalEv)}`
      : `MAP 兼容主链 | 总EV ${n(totalEv)}`,
  };
}

function fmtMemoryActivationCard(item) {
  if (item?.runtime_only) {
    const runtimeProjectionLabel = residualRuntimeObjectTypeLabel(item);
    return {
      title: `${item.display_text || item.grouped_display_text || item.memory_id || "-"} | ${item.item_id || item.memory_id || "-"}`,
      desc:
        `${runtimeProjectionLabel}\n` +
        `当前能量 ER ${n(item.er)} | EV ${n(item.ev)} | Total ${n(te(item))}\n` +
        `本轮落池 ER ${n(item.last_delta_er)} | EV ${n(item.last_delta_ev)}\n` +
        `路径 ${item.path_mode || "runtime_em_only"} | 创建 ${tm(item.created_at)} | 最近更新 ${tm(item.last_updated_at)}\n` +
        `来源 owner ${item.context_owner_id || "-"} | ref ${item.context_ref_object_id || "-"}\n` +
        `来源文本 ${item.context_text || "-"}\n` +
        `关联结构 / ST ${listOr(a(item.structure_ref_items).map((ref) => ref.display_text || ref.structure_id), "-", " / ")}\n` +
        `关联结构组 / SG ${listOr(a(item.group_ref_items).map((ref) => ref.group_id), "-", " / ")}\n` +
        `来源残差 / Source EM ${item.source_em_id || item.memory_id || "-"}`,
    };
  }
  const modeTotals = item?.mode_totals || {};
  const modeTotalsEr = item?.mode_totals_er || {};
  const modeTotalsEv = item?.mode_totals_ev || {};
  const recentEvent = a(item?.recent_events)[a(item?.recent_events).length - 1] || {};
  const recentFeedback = a(item?.recent_feedback_events)[a(item?.recent_feedback_events).length - 1] || {};
  const extraModes = Object.entries(modeTotals)
    .filter(([key]) => !["er_induction", "ev_propagation"].includes(key))
    .map(
      ([key, value]) =>
        `${key} ER ${n(modeTotalsEr[key])} | EV ${n(modeTotalsEv[key])} | Total ${n(value)}`,
    )
    .join(" | ");
  return {
    title: `${item.display_text || item.event_summary || item.memory_id || "-"} | ${item.memory_id || "-"}`,
    desc:
      `当前能量 / Current ER ${n(item.er)} | EV ${n(item.ev)} | Total ${n(te(item))}\n` +
      `最近增量 / Last Delta ER ${n(item.last_delta_er)} | EV ${n(item.last_delta_ev)}\n` +
      `最近衰减 / Last Decay ER ${n(item.last_decay_delta_er)} | EV ${n(item.last_decay_delta_ev)}\n` +
      `累计赋能 / Total Delta ER ${n(item.total_delta_er)} | EV ${n(item.total_delta_ev)}\n` +
      `模式累计 / By Mode er_induction ER ${n(modeTotalsEr.er_induction)} | EV ${n(modeTotalsEv.er_induction)} | Total ${n(modeTotals.er_induction)}\n` +
      `模式累计 / By Mode ev_propagation ER ${n(modeTotalsEr.ev_propagation)} | EV ${n(modeTotalsEv.ev_propagation)} | Total ${n(modeTotals.ev_propagation)}${extraModes ? `\n其它模式 / Extra Modes ${extraModes}` : ""}\n` +
      `更新 / Updates ${item.update_count || 0} | 命中 / Hits ${item.hit_count || 0} | 最近更新 / Updated ${tm(item.last_updated_at)}\n` +
      `兼容回流 / Compat Feedback ${item.feedback_count || 0} | 上次 ER ${n(item.last_feedback_er)} | 上次 EV ${n(item.last_feedback_ev)} | 累计 ER ${n(item.total_feedback_er)} | 累计 EV ${n(item.total_feedback_ev)}\n` +
      `结构引用 / ST ${listOr(a(item.structure_ref_items).map((ref) => ref.display_text || ref.structure_id), "-", " / ")}\n` +
      `结构组引用 / SG ${listOr(a(item.group_ref_items).map((ref) => ref.group_id), "-", " / ")}\n` +
      `来源结构 / Source ST ${listOr(item.source_structure_ids, "-", " / ")}\n` +
      `最近赋能 / Latest Activation ${recentEvent.trace_id || "-"} | ER ${n(recentEvent.delta_er)} | EV ${n(recentEvent.delta_ev)} | ${tm(recentEvent.timestamp_ms)}\n` +
      `最近兼容回流 / Latest Compat Feedback ${recentFeedback.trace_id || "-"} | ER ${n(recentFeedback.delta_er)} | EV ${n(recentFeedback.delta_ev)} | 目标 ${recentFeedback.target_count || 0} | ${tm(recentFeedback.timestamp_ms)}`,
  };
}

function fmtMemoryFeedbackResult(item) {
  return {
    title: `${item.display_text || item.memory_id || "-"} | ${item.memory_kind || "-"}`,
    desc:
      `本轮兼容回流 / Compat Feedback Delta ER ${n(item.delta_er)} | EV ${n(item.delta_ev)}\n` +
      `记忆内容 / Memory ${item.grouped_display_text || item.display_text || "-"}\n` +
      `回流目标 / Returned Targets ${listOr(item.target_display_texts, "-", " / ")}\n` +
      `${item.memory_kind === "stimulus_packet"
        ? `兼容反馈刺激包 / Compat Feedback Packet ${item.packet?.grouped_display_text || item.packet?.display_text || "-"}\n落池后残余 / Residual After Apply ${item.landed_packet?.grouped_display_text || item.landed_packet?.display_text || "-"}`
        : `结构回流 / Structure Projections ${listOr(a(item.projections).map((projection) => projection.display_text || projection.structure_id), "-", " / ")}`}`,
  };
}

function fmtRefs(items) {
  return a(items)
    .map((item) => `${pickGroupedText(item, item?.structure_id || "-")}(${item?.structure_id || "-"})`)
    .join("，") || "无 / None";
}

function fmtCommon(commonPart) {
  if (!commonPart) return "无 / None";
  return (
    fmtCommonGroups(commonPart.common_groups) ||
    commonPart.common_display ||
    textList(commonPart.common_tokens, " / ") ||
    commonPart.common_signature ||
    "无 / None"
  );
}

function fmtStorageAction(action) {
  if (!action) return "";
  return htmlLines([
    `类型 / Type: ${action.type_zh || action.type || "action"}`,
    `写入位置 / Storage: ${action.storage_table_zh || action.storage_table || "-"} | DB ${action.resolved_db_id || "-"}`,
    action.entry_id ? `记录ID / Entry: ${action.entry_id}` : "",
    action.group_id ? `结构组 / Group: ${action.group_id}` : "",
    action.owner_id ? `所属对象 / Owner: ${action.owner_id}` : "",
    action.raw_display_text ? `原始残差 / Raw: ${action.raw_display_text}` : "",
    action.canonical_display_text ? `还原结构 / Canonical: ${action.canonical_display_text}` : "",
    action.memory_id ? `记忆ID / em_id: ${action.memory_id}` : "",
  ]);
}

function fmtStorageSummary(summary) {
  if (!summary) return "无 / None";
  const header = htmlLines([
    `${pickGroupedText(summary, summary.owner_display_text || summary.owner_id || "-")} (${summary.owner_kind || "-"})`,
    `数据库 / DB: ${summary.resolved_db_id || "-"}`,
    `新建结构组 / New groups: ${listOr(summary.new_group_ids, "无 / None", ", ")}`,
  ]);
  const actions = a(summary.actions).map(fmtStorageAction).filter(Boolean);
  return `${header}${actions.length ? `<br><br>${actions.join("<br><br>")}` : ""}`;
}

function fmtResidualMemory(item) {
  if (!item) return "无 / None";
  return htmlLines([
    `${item.kind === "raw_residual_memory" ? "原始残差信息 / Raw Residual Memory" : "残差信息 / Residual"}${item.entry_id ? ` | ${item.entry_id}` : ""}${item.memory_id ? ` | em_id ${item.memory_id}` : ""}`,
    `还原结构 / Canonical: ${item.canonical_grouped_display_text || item.canonical_display_text || pickGroupedText(item)}`,
    item.raw_grouped_display_text || item.raw_display_text ? `原始记录 / Raw: ${item.raw_grouped_display_text || item.raw_display_text}` : "",
    stText(item.stats),
  ]);
}

function fmtNeutralizationDiagnostic(item, fmtTarget) {
  if (!item) return null;
  const useFmt = typeof fmtTarget === "function";
  const tgt = {
    target_ref_object_id: item.target_ref_object_id,
    target_ref_object_type: item.target_ref_object_type,
    target_item_id: item.target_item_id,
    target_display: item.target_display,
  };
  // Back-compat: some older diagnostics may only have target_item_id=st_000123 without ref fields.
  // 兼容：早期诊断数据可能只有 target_item_id=st_000123（没有 ref 字段），这里做一次“按前缀推断”。
  const rawId = String(item.target_item_id || "").trim();
  if (!String(tgt.target_ref_object_id || "").trim() && rawId) {
    if (rawId.startsWith("st_")) {
      tgt.target_ref_object_type = "st";
      tgt.target_ref_object_id = rawId;
    } else if (rawId.startsWith("sa_")) {
      tgt.target_ref_object_type = "sa";
      tgt.target_ref_object_id = rawId;
    } else if (rawId.startsWith("em_")) {
      tgt.target_ref_object_type = "em";
      tgt.target_ref_object_id = rawId;
    } else if (rawId.startsWith("sg_")) {
      tgt.target_ref_object_type = "sg";
      tgt.target_ref_object_id = rawId;
    }
  }
  const disp = useFmt ? fmtTarget(tgt) : (item.target_display || item.target_item_id || "-");
  const refId = String(item.target_ref_object_id || "").trim();
  const refType = String(item.target_ref_object_type || "").trim();
  // 若已经使用 fmtTargetWithPool，则它已包含 id/type/属性等信息，这里不重复拼接 refPart。
  const refPart = !useFmt && refId ? ` | ${refTypeLabel(refType)}:${refId}` : "";
  const status = NEUTRALIZATION_STATUS_LABELS[String(item.status || "").trim()] || String(item.status || "未标记");
  const reason = NEUTRALIZATION_REASON_LABELS[String(item.skipped_reason || "").trim()] || String(item.skipped_reason || "正常");
  const mode = String(item.neutralization_mode || "").trim() === "soft_partial_cache" ? "结构软匹配 + SA结算" : (
    String(item.neutralization_mode || "").trim() === "event_component_complementary" ? "事件组分互补中和" : "精确结构中和"
  );
  const saSummary =
    Number(item.sa_target_count || 0) > 0 || Number(item.sa_settled_count || 0) > 0
      ? `命中 SA ${item.sa_resolved_count || 0}/${item.sa_target_count || 0} | 已结算 ${item.sa_settled_count || 0}`
      : "本轮没有可结算的 SA";
  const saPreview = a(item.sa_settlements)
    .slice(0, 4)
    .map((row) => `${row.target_display || row.target_ref_object_id || "-"}:${row.energy_key || "-"} 缺口 ${n(row.deficit)} | 包内 ${n(row.packet_available)} | 实结算 ${n(row.consumed)}`)
    .join(" / ");
  const requiredLine =
    item.raw_required_amount !== undefined && Number(item.raw_required_amount) !== Number(item.required_amount)
      ? `原始差额 ${n(item.raw_required_amount)} | 本轮预算 ${n(item.required_amount)}`
      : `需要 / Required ${n(item.required_amount)}`;
  return {
    title: `${disp}${refPart} | ${item.required_energy_key || "-"}`,
    desc:
      `状态 ${status} | 模式 ${mode} | 原因 ${reason}\n` +
      `${requiredLine} | 可供 ${n(item.available_amount)} | 包内同侧余量 ${n(item.packet_available_amount)} | 已中和 ${n(item.consumed_amount)} | 缺口 ${n(item.shortfall_amount)} | 全差额缺口 ${n(item.full_shortfall_amount)}\n` +
      `匹配分 ${n(item.match_score)} | 结构覆盖 ${n(item.structure_coverage)} | 输入覆盖 ${n(item.input_coverage)} | 顺序 ${n(item.order_score)} | bundle ${n(item.bundle_score)}\n` +
      `潜在覆盖 结构 ${n(item.potential_structure_coverage)} / 输入 ${n(item.potential_input_coverage)} | common ${item.common_length || 0} | 匹配单元 ${item.matched_unit_count || 0}\n` +
      `${saSummary}${saPreview ? `\nSA 结算预览 ${saPreview}` : ""}\n` +
      `匹配内容 ${listOr(item.matched_tokens, "-", " / ")}`,
  };
}

function card(key, value, note = "") {
  return `<article class="card"><div class="label">${esc(key)}</div><div class="value">${esc(value)}</div><div class="note">${esc(note)}</div></article>`;
}

function shortInputPreview(value, limit = 28) {
  const text = String(value ?? "");
  if (!text) return "";
  return text.length > limit ? `${text.slice(0, Math.max(0, limit - 1))}…` : text;
}

function buildInputQueueViewModel(report) {
  const queue = report?.input_queue || {};
  const sensor = report?.sensor || {};
  const processedText = String(queue.tick_text || sensor.input_text || "").trim();
  const submittedText = String(queue.submitted_text || "").trim();
  const queueSourceText = String(queue.source_text || "").trim();
  const pendingAfter = Math.max(0, Number(queue.pending_count_after_dequeue || 0) || 0);
  const queuedCount = Math.max(0, Number(queue.queued_from_new_input_count || 0) || 0);
  const processedLabel = processedText || "空 Tick";
  const submittedLabel = submittedText || "无";
  const queueSourceLabel = queueSourceText || "无";
  const summaryParts = [`处理 ${shortInputPreview(processedLabel)}`];
  if (submittedText) {
    summaryParts.push(`提交 ${shortInputPreview(submittedText)}`);
  } else if (queueSourceText && queueSourceText !== processedText) {
    summaryParts.push(`最近提交 ${shortInputPreview(queueSourceText)}`);
  }
  if (pendingAfter > 0) summaryParts.push(`余量 ${pendingAfter}`);
  return {
    processedText,
    processedLabel,
    submittedText,
    submittedLabel,
    queueSourceText,
    queueSourceLabel,
    pendingAfter,
    queuedCount,
    summaryText: summaryParts.join(" | "),
  };
}

function empty(text) {
  return `<div class="empty-state">${esc(text)}</div>`;
}

function rows(items, emptyText = "当前没有数据。") {
  return items && items.length
    ? items
        .map((item) => `<article class="mini-row"><div class="title">${esc(item.title || "-")}</div><div class="desc">${esc(item.desc || "-").replace(/\n/g, "<br>")}</div></article>`)
        .join("")
    : empty(emptyText);
}

function fb(message, isError) {
  if (!E.actionFeedback) return;
  E.actionFeedback.textContent = message;
  E.actionFeedback.style.color = isError ? "var(--danger)" : "var(--muted)";
}

// Innate rules feedback (local to the innate rules section) / 先天规则区专用反馈
function irFb(message, kind) {
  if (!E.innateRulesFeedback) return;
  const k = String(kind || "ok");
  // Add a timestamp to make "button did something" more obvious.
  // 增加时间戳，让“按了按钮确实有反应”更直观。
  const stamp = tm(Date.now());
  E.innateRulesFeedback.textContent = `${stamp} | ${message}`;
  E.innateRulesFeedback.classList.remove("ok", "err", "busy");
  if (k === "err" || k === "busy" || k === "ok") E.innateRulesFeedback.classList.add(k);
}

// Graph editor feedback (local to the graph modal) / 图形编辑器专用反馈
// 目的：避免用户按了按钮“没反应”，因为 fb() 写到主界面底部不明显。
function irGraphFb(message, kind) {
  if (!E.irGraphFeedback) {
    // Fallback: write into hint if palette is visible.
    // 回退：至少把信息写到 hint。
    _setIrGraphHint(String(message || ""));
    return;
  }
  const k = String(kind || "ok");
  const stamp = tm(Date.now());
  E.irGraphFeedback.textContent = `${stamp} | ${message}`;
  E.irGraphFeedback.classList.remove("ok", "err", "busy");
  if (k === "err" || k === "busy" || k === "ok") E.irGraphFeedback.classList.add(k);
}

function irFlashFeedback() {
  if (!E.innateRulesFeedback) return;
  E.innateRulesFeedback.classList.remove("flash");
  // Force reflow to restart animation.
  void E.innateRulesFeedback.offsetWidth;
  E.innateRulesFeedback.classList.add("flash");
}

function irFlashResultBox() {
  if (!E.innateRulesResult) return;
  E.innateRulesResult.classList.remove("flash");
  // Force reflow to restart animation.
  void E.innateRulesResult.offsetWidth;
  E.innateRulesResult.classList.add("flash");
}

function irSetResultBoxKind(kind) {
  if (!E.innateRulesResult) return;
  const k = String(kind || "");
  E.innateRulesResult.classList.remove("ok", "err", "busy");
  if (k === "ok" || k === "err" || k === "busy") E.innateRulesResult.classList.add(k);
}

const IR_OP_BTN_IDS = [
  "innateRulesRefreshBtn",
  "innateRulesValidateBtn",
  "innateRulesSaveBtn",
  "innateRulesSimulateBtn",
  "innateRulesImportYamlBtn",
  "innateRulesExportYamlBtn",
];

function setIrBusy(busy, activeBtnId, activeText) {
  IR_OP_BTN_IDS.forEach((id) => {
    const btn = document.getElementById(id);
    if (!btn) return;
    if (!btn.dataset.origText) btn.dataset.origText = btn.textContent || "";
    btn.disabled = Boolean(busy);
    if (busy && id === String(activeBtnId || "")) {
      btn.textContent = String(activeText || "处理中…");
    } else {
      btn.textContent = btn.dataset.origText;
    }
  });
}

function irIssuesText(items, label, maxCount = 12) {
  const rows2 = a(items).filter((x) => x && typeof x === "object");
  if (!rows2.length) return `${label}：0`;
  const head = `${label}：${rows2.length}`;
  const lines = rows2.slice(0, maxCount).map((it) => {
    const path = String(it.path || it.loc || "$");
    const msg = String(it.message_zh || it.zh || it.message_en || it.en || it.message || "-");
    return `- ${path}: ${msg}`;
  });
  const tail = rows2.length > maxCount ? [`（仅展示前 ${maxCount} 条，剩余 ${rows2.length - maxCount} 条略）`] : [];
  return [head, ...lines, ...tail].join("\n");
}

function irResultText(op, data) {
  const d = data && typeof data === "object" ? data : {};
  const code = String(d.code || d.status || "-");
  const msg = String(d.message || "-");
  const lines = [`操作（op）: ${String(op || "-")}`, `code: ${code}`, `message: ${msg}`];
  if (op === "refresh") {
    lines.push(`规则路径: ${String(d.rules_path || "-")}`);
    lines.push(`加载时间: ${d.rules_loaded_at_ms ? tm(d.rules_loaded_at_ms) : "-"}`);
    lines.push(`规则版本: schema ${String(d.rules_schema_version || "-")} / rules ${String(d.rules_version || "-")}`);
    lines.push(`规则数: ${String(d.rule_count ?? "-")}`);
    lines.push(`引擎启用: ${Boolean(d.engine_enabled) ? "是" : "否"}`);
    lines.push("");
    lines.push(irIssuesText(d.errors, "错误（errors）"));
    lines.push("");
    lines.push(irIssuesText(d.warnings, "警告（warnings）"));
    return lines.join("\n");
  }
  if (op === "validate" || op === "import_yaml") {
    lines.push(`校验通过: ${Boolean(d.valid) ? "是" : "否"}`);
    lines.push(irIssuesText(d.errors, "错误（errors）"));
    lines.push("");
    lines.push(irIssuesText(d.warnings, "警告（warnings）"));
    return lines.join("\n");
  }
  if (op === "save") {
    lines.push(`已保存: ${Boolean(d.saved) ? "是" : "否"}`);
    const b = d.data && typeof d.data === "object" ? d.data : {};
    lines.push(`规则路径: ${String(b.rules_path || "-")}`);
    lines.push(`备份目录: ${String(b.rules_backup_dir || "-")}`);
    lines.push(`保存信息: ${String(b.save_message || "-")}`);
    lines.push(`规则数: ${String(b.rule_count ?? "-")} | 错误 ${a(b.errors).length} | 警告 ${a(b.warnings).length}`);
    return lines.join("\n");
  }
  if (op === "simulate") {
    lines.push(`模拟 ok: ${Boolean(d.ok) ? "是" : "否"}`);
    const b = d.data && typeof d.data === "object" ? d.data : {};
    const audit = b.audit && typeof b.audit === "object" ? b.audit : {};
    const counts = b.counts && typeof b.counts === "object" ? b.counts : {};
    lines.push(`触发规则: ${a(b.triggered_rules).length} | 触发脚本: ${a(b.triggered_scripts).length}`);
    lines.push(`输出: focus=${counts.focus_directive_count ?? "-"} | emotion=${counts.emotion_update_key_count ?? "-"} | action_trigger=${counts.action_trigger_count ?? "-"} | pool_effect=${counts.pool_effect_count ?? "-"}`);
    lines.push(`耗时: ${audit.elapsed_ms ?? "-"} ms`);
    return lines.join("\n");
  }
  return lines.join("\n");
}

function configValueText(value) {
  if (value === undefined) return "未设置（Not set）";
  if (value === null) return "null";
  if (typeof value === "string") return value || '""';
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return dumpYamlLike(value);
}

function settingsValueEquals(left, right) {
  return JSON.stringify(left ?? null) === JSON.stringify(right ?? null);
}

function moduleSettingsDraft(moduleName) {
  return S.settingsDrafts?.[moduleName] || {};
}

function fieldHasDraft(moduleName, field) {
  return Object.prototype.hasOwnProperty.call(moduleSettingsDraft(moduleName), field?.key || "");
}

function configEditorValue(moduleNameOrField, maybeField) {
  const field = maybeField || moduleNameOrField;
  const moduleName = maybeField ? moduleNameOrField : S.settingsTab;
  const value = fieldHasDraft(moduleName, field)
    ? moduleSettingsDraft(moduleName)[field.key]
    : field?.file_value;
  if (field?.type === "dict" || field?.type === "list") return dumpYamlLike(value);
  if (field?.type === "bool") return Boolean(value);
  if (value === undefined || value === null) return "";
  return String(value);
}

function rememberSettingsDraft(moduleName, key, value) {
  if (!moduleName || !key) return;
  const current = { ...moduleSettingsDraft(moduleName) };
  current[key] = value;
  S.settingsDrafts[moduleName] = current;
}

function setSettingsDraft(moduleName, values) {
  if (!moduleName) return;
  S.settingsDrafts[moduleName] = { ...(values || {}) };
}

function clearSettingsDraft(moduleName) {
  if (!moduleName) return;
  delete S.settingsDrafts[moduleName];
}

function normalizeSettingsTab() {
  const modules = Object.keys(S.d?.module_configs || {});
  if (!modules.length) {
    S.settingsTab = "observatory";
    return null;
  }
  if (!modules.includes(S.settingsTab)) S.settingsTab = modules[0];
  return S.settingsTab;
}

function renderSettingsInput(moduleName, field) {
  const inputId = `cfg_${moduleName}_${field.key}`;
  const editorValue = configEditorValue(moduleName, field);
  if (field.type === "bool") {
    return `<label class="toggle-row" for="${esc(inputId)}"><input id="${esc(inputId)}" class="config-input" data-key="${esc(field.key)}" data-type="${esc(field.type)}" type="checkbox" ${editorValue ? "checked" : ""} /><span>启用（Enabled）</span></label>`;
  }
  if (field.type === "dict" || field.type === "list") {
    return `<textarea id="${esc(inputId)}" class="config-input config-textarea" data-key="${esc(field.key)}" data-type="${esc(field.type)}">${esc(editorValue)}</textarea>`;
  }
  const htmlType = field.type === "int" || field.type === "float" ? "number" : "text";
  const step = field.type === "int" ? "1" : field.type === "float" ? "any" : "";
  const value = esc(editorValue);
  return `<input id="${esc(inputId)}" class="config-input" data-key="${esc(field.key)}" data-type="${esc(field.type)}" type="${htmlType}" ${step ? `step="${step}"` : ""} value="${value}" />`;
}

function renderSettingField(moduleName, field) {
  const notes = a(field.comment_lines);
  const hasDraft = fieldHasDraft(moduleName, field);
  const draftValue = hasDraft ? moduleSettingsDraft(moduleName)[field.key] : undefined;
  const isDirty = hasDraft && !settingsValueEquals(draftValue, field.file_value);
  const help = notes.length
    ? notes.map((line) => `<div>${esc(line)}</div>`).join("")
    : `<div>暂无字段注释 / No annotation yet.</div>`;
  const overrideChip = field.has_override
    ? `<span class="chip warn">运行时覆盖（Override）：${esc(configValueText(field.override_value))}</span>`
    : `<span class="chip">无覆盖（No override）</span>`;
  const draftChip = isDirty
    ? `<span class="chip accent">草稿未保存（Draft）</span>`
    : `<span class="chip">文件同步（Synced）</span>`;
  return `<article class="setting-item">
    <div class="setting-head">
      <label for="${esc(`cfg_${moduleName}_${field.key}`)}">${esc(field.key)}</label>
      <div class="chips">
        <span class="chip">${esc(field.type || "str")}</span>
        <span class="chip">${field.hot_reload_supported ? "热加载（Hot reload）" : "需重启（Restart required）"}</span>
        ${overrideChip}
        ${draftChip}
      </div>
    </div>
    ${renderSettingsInput(moduleName, field)}
    <div class="setting-values">
      <div><strong>文件值 / File:</strong> <pre>${esc(configValueText(field.file_value))}</pre></div>
      <div><strong>生效值 / Effective:</strong> <pre>${esc(configValueText(field.effective_value))}</pre></div>
      <div><strong>默认值 / Default:</strong> <pre>${esc(configValueText(field.default_value))}</pre></div>
    </div>
    <div class="setting-help">${help}</div>
  </article>`;
}

function renderSettingsPanel(moduleName, config) {
  const sections = a(config?.sections);
  const header = `<section class="detail-card settings-summary-card">
    <h5>${esc(config?.title || moduleName)}</h5>
    <div class="kv-list">
      <div class="kv-row"><div class="k">配置文件 / Config Path</div><div class="v">${esc(config?.path || "-")}</div></div>
      <div class="kv-row"><div class="k">说明 / Notes</div><div class="v">编辑器显示的是文件值，保存后通过模块自带热加载接口立即刷新；若该模块被观测台运行时覆盖，则“生效值”可能与“文件值”不同。<br>Editor shows file values. After save, the built-in hot reload path is executed immediately. If Observatory applies runtime overrides, effective values may differ from file values.</div></div>
    </div>
    <div class="compact-actions">
      <button id="settingsSaveBtn" class="primary">保存并加载 / Save + Reload</button>
      <button id="settingsResetBtn" class="ghost">重置为文件值 / Reset</button>
    </div>
  </section>`;
  const body = sections.length
    ? sections
        .map(
          (section) => `<section class="settings-group">
            <div class="section-head">
              <h4>${esc(section.title || "未分组 / Ungrouped")}</h4>
              <span class="meta">${a(section.fields).length} 项（fields）</span>
            </div>
            <div class="settings-grid">
              ${a(section.fields).map((field) => renderSettingField(moduleName, field)).join("")}
            </div>
          </section>`,
        )
        .join("")
    : empty("当前没有字段级配置说明。");
  return `${header}${body}`;
}

function readConfigInputNode(node) {
  const type = node?.dataset?.type;
  if (type === "bool") {
    return Boolean(node.checked);
  }
  const raw = node?.value ?? "";
  if (type === "int") {
    return raw === "" ? "" : Number.parseInt(raw, 10);
  }
  if (type === "float") {
    return raw === "" ? "" : Number(raw);
  }
  return raw;
}

function readSettingsValues(moduleName) {
  const values = {};
  document.querySelectorAll("#settingsPanel .config-input").forEach((node) => {
    const key = node.dataset.key;
    if (!key) return;
    values[key] = readConfigInputNode(node);
  });
  if (moduleName) {
    setSettingsDraft(moduleName, values);
  }
  return values;
}

function bindSettingsUi(moduleName) {
  document.querySelectorAll(".settings-tab-btn").forEach((node) => {
    node.addEventListener("click", () => {
      S.settingsTab = node.dataset.module || "observatory";
      misc();
    });
  });
  const saveBtn = document.getElementById("settingsSaveBtn");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      try {
        const pendingValues = readSettingsValues(moduleName);
        const response = await P("/api/config/save", {
          module: moduleName,
          values: pendingValues,
        });
        S.r = response.data;
        const rejectedKeys = a(response.data?.rejected_values)
          .map((item) => item?.key)
          .filter(Boolean);
        if (rejectedKeys.length) {
          const rejectedDraft = {};
          rejectedKeys.forEach((key) => {
            rejectedDraft[key] = pendingValues[key];
          });
          setSettingsDraft(moduleName, rejectedDraft);
        } else {
          clearSettingsDraft(moduleName);
        }
        await refreshDashboard(true);
        fb(`已保存并热加载 ${moduleName} 配置。`);
        if (response.data?.rejected_values?.length) {
          fb(`已保存 ${moduleName}，但有 ${response.data.rejected_values.length} 个字段被拒绝，请检查输入格式。`, true);
        }
      } catch (error) {
        fb(`保存配置失败: ${error.message}`, true);
      }
    });
  }
  const resetBtn = document.getElementById("settingsResetBtn");
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      clearSettingsDraft(moduleName);
      misc();
      fb(`已重置 ${moduleName} 草稿到文件值 / Reset ${moduleName} draft to file values`);
    });
  }
  document.querySelectorAll("#settingsPanel .config-input").forEach((node) => {
    const syncDraft = () => rememberSettingsDraft(moduleName, node.dataset.key || "", readConfigInputNode(node));
    node.addEventListener("input", syncDraft);
    node.addEventListener("change", syncDraft);
  });
}

async function G(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok || data.success === false) throw new Error(data.message || url);
  return data;
}

async function P(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await response.json();
  if (!response.ok || data.success === false) {
    const parts = [data.message || url];
    if (data.error_type) parts.push(`type=${data.error_type}`);
    if (data.traceback) parts.push(data.traceback);
    throw new Error(parts.filter(Boolean).join("\n"));
  }
  return data;
}

async function refreshDashboard(silent = false) {
  try {
    const response = await G("/api/dashboard");
    S.d = response.data;
    draw();
    // Keep Action Runtime panel in sync with the latest cycle.
    // 避免出现“流程日志里 Drive 明明有节点，但实时监控仍显示 tick_counter=0/无节点”的割裂观感。
    refreshActionRuntime(true);
    if (!silent) fb("已刷新观测台 / Dashboard refreshed.");
  } catch (error) {
    fb(`刷新失败 / Refresh failed: ${error.message}`, true);
  }
}

// =====================================================================
// Pipeline Switches / 流程阶段开关（前端快捷入口）
// =====================================================================

function pipelineEffectiveSwitches() {
  const effective = S.d?.module_configs?.observatory?.effective || {};
  const ebc = S.d?.module_configs?.energy_balance?.effective || {};
  const ts = S.d?.module_configs?.time_sensor?.effective || {};
  return {
    enableCognitiveStitching: Boolean(effective.enable_cognitive_stitching),
    enableStructureLevelRetrievalStorage: Boolean(effective.enable_structure_level_retrieval_storage),
    enableGoalBCharSaStringMode: Boolean(effective.enable_goal_b_char_sa_string_mode),
    enableEnergyBalanceController: Boolean(ebc.enabled),
    enableDelayedTasks: Boolean(ts.enable_delayed_tasks),
    configPath: String(S.d?.module_configs?.observatory?.path || "").trim(),
    energyBalanceConfigPath: String(S.d?.module_configs?.energy_balance?.path || "").trim(),
    timeSensorConfigPath: String(S.d?.module_configs?.time_sensor?.path || "").trim(),
  };
}

function renderPipelineSwitchesPanel() {
  if (!E.pipelineEnableCognitiveStitchingChk || !E.pipelineEnableStructureLevelChk) return;
  const sw = pipelineEffectiveSwitches();
  // Sync UI to effective values (not file values) / 同步到“生效值”，而不是“文件值”。
  // Note: This panel is a quick switchboard; it should reflect the true runtime loop status.
  E.pipelineEnableCognitiveStitchingChk.checked = Boolean(sw.enableCognitiveStitching);
  E.pipelineEnableStructureLevelChk.checked = Boolean(sw.enableStructureLevelRetrievalStorage);
  if (E.pipelineEnableGoalBCharSaStringModeChk) E.pipelineEnableGoalBCharSaStringModeChk.checked = Boolean(sw.enableGoalBCharSaStringMode);
  if (E.pipelineEnableEnergyBalanceChk) E.pipelineEnableEnergyBalanceChk.checked = Boolean(sw.enableEnergyBalanceController);
  if (E.pipelineEnableDelayedTasksChk) E.pipelineEnableDelayedTasksChk.checked = Boolean(sw.enableDelayedTasks);
  if (E.pipelineSwitchFeedback) {
    const parts = [
      `当前生效值（Effective values）`,
      `认知拼接（Cognitive Stitching，缩写 CS）=${y(sw.enableCognitiveStitching)}`,
      `结构级查存一体（Structure-level Retrieval-Storage）=${y(sw.enableStructureLevelRetrievalStorage)}`,
      `使用字符串方案（字符串作为顺序敏感结构）=${y(sw.enableGoalBCharSaStringMode)}`,
      `能量平衡控制器（Energy Balance Controller，缩写 EBC）=${y(sw.enableEnergyBalanceController)}`,
      `时间感受器延迟任务（Delayed Tasks）=${y(sw.enableDelayedTasks)}`,
      sw.configPath ? `配置文件=${sw.configPath}` : "",
      sw.energyBalanceConfigPath ? `能量平衡配置文件=${sw.energyBalanceConfigPath}` : "",
      sw.timeSensorConfigPath ? `时间感受器配置文件=${sw.timeSensorConfigPath}` : "",
    ].filter(Boolean);
    E.pipelineSwitchFeedback.textContent = parts.join(" | ");
  }
}

function resetPipelineSwitchesToEffective() {
  const sw = pipelineEffectiveSwitches();
  if (E.pipelineEnableCognitiveStitchingChk) E.pipelineEnableCognitiveStitchingChk.checked = Boolean(sw.enableCognitiveStitching);
  if (E.pipelineEnableStructureLevelChk) E.pipelineEnableStructureLevelChk.checked = Boolean(sw.enableStructureLevelRetrievalStorage);
  if (E.pipelineEnableGoalBCharSaStringModeChk) E.pipelineEnableGoalBCharSaStringModeChk.checked = Boolean(sw.enableGoalBCharSaStringMode);
  if (E.pipelineEnableEnergyBalanceChk) E.pipelineEnableEnergyBalanceChk.checked = Boolean(sw.enableEnergyBalanceController);
  if (E.pipelineEnableDelayedTasksChk) E.pipelineEnableDelayedTasksChk.checked = Boolean(sw.enableDelayedTasks);
  if (E.pipelineSwitchFeedback) E.pipelineSwitchFeedback.textContent = "已重置为当前生效值（Effective values）。";
}

async function applyPipelineSwitchesFromUi() {
  const wantCs = Boolean(E.pipelineEnableCognitiveStitchingChk?.checked);
  const wantStructure = Boolean(E.pipelineEnableStructureLevelChk?.checked);
  const wantGoalB = Boolean(E.pipelineEnableGoalBCharSaStringModeChk?.checked);
  const wantEbc = Boolean(E.pipelineEnableEnergyBalanceChk?.checked);
  const wantDelayed = Boolean(E.pipelineEnableDelayedTasksChk?.checked);
  if (E.pipelineSwitchFeedback) E.pipelineSwitchFeedback.textContent = "正在保存并热加载（Saving + reloading）…";
  try {
    // 1) Observatory is the master switch for pipeline stages.
    await P("/api/config/save", {
      module: "observatory",
      values: {
        enable_cognitive_stitching: wantCs,
        enable_structure_level_retrieval_storage: wantStructure,
        enable_goal_b_char_sa_string_mode: wantGoalB,
      },
    });

    // 2) Keep cognitive_stitching's file value in sync for human inspection.
    // 注意：运行时会被 Observatory 的 runtime_override 覆盖（以观测台开关为准）。
    // 这里同步文件值，只是为了减少“文件值与生效值不一致”的困惑。
    try {
      await P("/api/config/save", { module: "cognitive_stitching", values: { enabled: wantCs } });
    } catch (error) {
      if (E.pipelineSwitchFeedback) {
        E.pipelineSwitchFeedback.textContent = `已保存观测台开关，但同步认知拼接模块配置失败：${error.message}（不影响本轮生效值）。`;
      }
    }

    // 3) Energy balance controller switch.
    try {
      await P("/api/config/save", { module: "energy_balance", values: { enabled: wantEbc } });
    } catch (error) {
      if (E.pipelineSwitchFeedback) {
        E.pipelineSwitchFeedback.textContent = `已保存流程开关，但同步能量平衡控制器配置失败：${error.message}（不影响本轮生效值）。`;
      }
    }

    // 4) Time sensor delayed tasks switch (rhythm experiment key).
    try {
      await P("/api/config/save", { module: "time_sensor", values: { enable_delayed_tasks: wantDelayed } });
    } catch (error) {
      if (E.pipelineSwitchFeedback) {
        E.pipelineSwitchFeedback.textContent = `已保存流程开关，但同步时间感受器延迟任务配置失败：${error.message}（不影响本轮生效值）。`;
      }
    }

    await refreshDashboard(true);
    if (E.pipelineSwitchFeedback) E.pipelineSwitchFeedback.textContent = "已保存并热加载开关（Applied）。";
    fb("已应用流程阶段开关。");
  } catch (error) {
    if (E.pipelineSwitchFeedback) E.pipelineSwitchFeedback.textContent = `保存失败：${error.message}`;
    fb(`保存流程阶段开关失败: ${error.message}`, true);
    await refreshDashboard(true);
  }
}

// =====================================================================
// Action Runtime View / 行动运行态监控（实时快照）
// =====================================================================

async function refreshActionRuntime(silent = false) {
  try {
    const response = await G("/api/action_runtime");
    S.actionRuntime = response.data || null;
    renderActionRuntime();
    if (!silent) fb("已刷新行动模块运行态快照。");
  } catch (error) {
    if (!silent) fb(`刷新行动快照失败: ${error.message}`, true);
  }
}

function renderActionRuntime() {
  if (!E.actionRuntimeMeta || !E.actionRuntimeExecutors || !E.actionRuntimeNodes || !E.actionRuntimeExecuted) return;
  const snap = S.actionRuntime || null;
  if (!snap || typeof snap !== "object") {
    E.actionRuntimeMeta.textContent = "尚未加载行动运行态快照。";
    E.actionRuntimeExecutors.innerHTML = empty("等待刷新行动快照…");
    E.actionRuntimeNodes.innerHTML = empty("等待刷新行动快照…");
    E.actionRuntimeExecuted.innerHTML = empty("等待刷新行动快照…");
    return;
  }
  renderActionStopValueList();

  const stats = snap.stats || {};
  const nodes = a(snap.nodes);
  const exs = a(snap.executors_registry);
  const executed = a(snap.recent_executed_actions);
  const actionLearningSummary = snap.action_learning_summary || {};

  // Chinese-first action kind label / 行动类型中文名（中文优先）
  const actionKindTitle = (kind) => {
    const k = String(kind || "").trim();
    if (!k) return "-";
    const ex = exs.find((x) => String(x?.action_kind || "").trim() === k);
    const zh = String(ex?.title_zh || "").trim();
    return zh ? (zh.includes(k) ? zh : `${zh}（${k}）`) : k;
  };
  E.actionRuntimeMeta.textContent =
    `tick_counter（节拍计数）=${stats.tick_counter ?? "-"} | 行动节点=${stats.node_count ?? nodes.length} | 行动器注册=${exs.length} | ` +
    `最近执行记录=${stats.executed_history_count ?? executed.length} | 局部塑形节点=${actionLearningSummary.local_modulated_node_count ?? 0} | 模块版本=${snap.version || "-"}`;

  const fmtSchema = (schema) => {
    const pairs = Object.entries(schema && typeof schema === "object" ? schema : {}).filter(([k]) => String(k || "").trim());
    if (!pairs.length) return "（无）";
    return pairs
      .slice(0, 16)
      .map(([k, v]) => `${String(k)}:${String(v)}`)
      .join(" / ");
  };
  const fmtSource = (src) => {
    return fmtActionSourceBrief(src);
  };

  E.actionRuntimeExecutors.innerHTML = rows(
    exs.map((ex) => ({
      title: `${ex.title_zh || ex.action_kind || "-"} · 行动类型（action_kind）=${ex.action_kind || "-"}`,
      desc: `${ex.desc_zh || "-"}\n参数口径（params_schema）${fmtSchema(ex.params_schema || {})}\n常见触发来源 ${a(ex.sources_zh).join("，") || "-"}`,
    })),
    "当前没有行动器注册信息。",
  );

  E.actionRuntimeNodes.innerHTML = rows(
    nodes.slice(0, 64).map((node) => ({
      // threshold_components: 用于解释“阈值为什么变高/变低”（例如 NT 调制、疲劳调制）
      // threshold_components: explain why threshold changed (NT/fatigue/etc.).
      title: `${actionKindTitle(node.action_kind || "")} · ${node.action_id || "-"}`,
      desc:
        `drive ${n(node.drive)} | 本轮消耗 ${n(node.tick_consumed_drive_total ?? node.last_consumed_drive ?? 0)} | 基准阈值 ${n(node.base_threshold)} | 实时阈值 ${n(node.effective_threshold)}（scale ${n(node.threshold_scale)}）\n` +
        `目标 ${node.target_display || node.target_ref_object_id || node.target_item_id || "-"}\n` +
        `阈值分量（components）${Object.keys(node.threshold_components || {}).length ? Object.entries(node.threshold_components || {}).map(([k, v]) => `${k}:${n(v)}`).join(" / ") : "-"}\n` +
`局部塑形 ${formatLocalDriveModulationText(node.local_drive_modulation)}\n` +
        `疲劳（fatigue）${n(node.fatigue)} | 本 tick 增益 ${n(node.tick_gain_total)} | cooldown ${node.cooldown_ticks ?? 0}\n` +
        `last_attempt ${node.last_attempt_tick ?? "-"} | last_trigger ${node.last_trigger_tick ?? "-"} | last_update ${node.last_update_tick ?? "-"}\n` +
        `${(Number(node.stop_until_tick ?? -1) >= 0 || Number(node.last_stop_tick ?? -1) >= 0) ? `停止门控 stop_until_tick ${node.stop_until_tick ?? "-"} | last_stop ${node.last_stop_tick ?? "-"} | reason ${node.last_stop_reason || "-"}\n` : ""}` +
        `最近触发源 ${a(node.trigger_sources).map(fmtSource).join(" / ") || "-"}`,
    })),
    "当前没有行动节点。",
  );

  E.actionRuntimeExecuted.innerHTML = rows(
    executed
      .slice(-40)
      .reverse()
      .map((ex) => {
        const origin = ex.origin || {};
        const passive = Boolean(origin.passive_iesm);
        const active = Boolean(origin.active_internal);
        const originText = passive && active ? "来源：先天+内驱" : passive ? "来源：先天（IESM）" : active ? "来源：内驱（非IESM）" : "来源：未知";
        const ok = ex.success === false ? false : true;
        const statusText = ok ? "结果：成功" : "结果：失败";
        const tg = ex.tick_gain_by_source_kind || {};
        const by = Object.keys(tg).length ? Object.entries(tg).map(([k, v]) => `${k}:${n(v)}`).join(" / ") : "-";
        const ts = ex.recorded_at_ms ? tm(ex.recorded_at_ms) : "-";
        const fail = !ok && ex.failure_reason ? `\n失败原因 ${String(ex.failure_reason)}` : "";
        return {
          title: `tick#${ex.tick_number ?? "-"} · ${ok ? "成功" : "失败"} · ${actionKindTitle(ex.action_kind || "")} · ${ex.action_id || "-"}`,
          desc:
            `${originText} | ${statusText} | 记录时间 ${ts}${fail}\n` +
            `drive ${n(ex.drive_before)} -> ${n(ex.drive_after)} | 消耗 ${n(ex.consumed_drive ?? 0)} | 阈值 ${n(ex.effective_threshold)}（基准 ${n(ex.base_threshold)} * scale ${n(ex.threshold_scale)}） | fatigue ${n(ex.fatigue)}\n` +
`目标 ${ex.target_display || ex.target_ref_object_id || ex.target_item_id || "-"} | 局部塑形 ${formatLocalDriveModulationText(ex.local_drive_modulation)}\n` +
            `本 tick 增益 ${n(ex.tick_gain_total)} | 来源增益 ${by}`,
        };
      }),
    "最近没有执行/尝试记录。",
  );
}

// =====================================================================
// Action Stop UI / 行动停止接口（前端）
// =====================================================================

function renderActionStopValueList() {
  if (!E.actionStopValueList || !E.actionStopMode) return;
  const snap = S.actionRuntime || {};
  const mode = String(E.actionStopMode.value || "action_kind");
  const nodes = a(snap.nodes);
  const exs = a(snap.executors_registry);
  let values = [];
  if (mode === "action_id") values = nodes.map((n2) => String(n2.action_id || "")).filter(Boolean);
  else values = exs.map((x) => String(x.action_kind || "")).filter(Boolean);
  values = Array.from(new Set(values)).sort();
  E.actionStopValueList.innerHTML = values.map((v) => `<option value="${esc(v)}"></option>`).join("");
  if (E.actionStopValue) {
    E.actionStopValue.placeholder = mode === "action_id" ? "输入 action_id（行动节点 ID）" : "输入 action_kind（行动器类型）";
  }
}

async function stopActionNodesFromUi() {
  const mode = String(E.actionStopMode?.value || "action_kind");
  const valueRaw = String(E.actionStopValue?.value || "").trim();
  if (mode !== "all" && !valueRaw) {
    fb("请先填写要停止的目标（value）。", true);
    return;
  }
  await stopActionNodes({ mode, value: valueRaw });
}

async function stopActionNodes({ mode, value }) {
  try {
    const hold = Math.max(0, Math.min(10000, Number(E.actionStopHoldTicks?.value || 2) || 0));
    const reason = String(E.actionStopReason?.value || "manual_stop").trim() || "manual_stop";
    if (E.actionStopFeedback) E.actionStopFeedback.textContent = "正在执行停止…";
    const res = await P("/api/action_stop", { mode, value, hold_ticks: hold, reason });
    const data = res.data || {};
    const stopped = data.stopped_count ?? data.stopped_action_ids?.length ?? 0;
    const msg = `已停止 ${stopped} 个行动节点（mode=${data.mode || mode}，hold_ticks=${data.hold_ticks ?? hold}）。`;
    if (E.actionStopFeedback) E.actionStopFeedback.textContent = msg;
    fb(msg);
    await refreshActionRuntime(true);
  } catch (error) {
    if (E.actionStopFeedback) E.actionStopFeedback.textContent = `停止失败：${error.message}`;
    fb(`停止失败：${error.message}`, true);
  }
}

function startActionRuntimeAutoRefresh() {
  if (S.actionRuntimeAutoTimer) return;
  S.actionRuntimeAutoTimer = setInterval(() => refreshActionRuntime(true), 1200);
}

function stopActionRuntimeAutoRefresh() {
  if (!S.actionRuntimeAutoTimer) return;
  clearInterval(S.actionRuntimeAutoTimer);
  S.actionRuntimeAutoTimer = null;
}

function draw() {
  overview();
  renderPipelineSwitchesPanel();
  sensor();
  timeSensorView();
  flow();
  renderActionRuntime();
  stateView();
  hdbView();
  enhanceMemoryAwareViews();
  misc();
  renderInnateRules();
  if (E.actionResult) E.actionResult.textContent = S.r ? fmtScalarPlain(S.r) : "等待操作…";
}

function enhanceMemoryAwareViews() {
  renderOverviewMemorySummary();
  renderHdbMemorySummary();
  renderRecentCyclesMemorySummary();
}

function renderOverviewMemorySummary() {
  if (!S.d || !E.overviewCards) return;
  const report = S.d.last_report || {};
  const inputView = buildInputQueueViewModel(report);
  const snapshot = S.d.state_snapshot || {};
  const energy = S.d.state_energy_summary || {};
  const hdb = S.d.hdb_snapshot?.summary || {};
  const maint = S.d.maintenance_runtime || {};
  const hdbIdle = maint.hdb_last_idle_consolidation || null;
  const csIdle = maint.cs_last_idle_consolidation || null;
  const hdbTs = Number(hdbIdle?.data?.timestamp_ms ?? 0) || 0;
  const csTs = Number(csIdle?.data?.timestamp_ms ?? 0) || 0;
  const idleTs = Math.max(hdbTs, csTs);
  const idleWhen = idleTs ? tm(idleTs) : "尚未执行";
  const idleDetailParts = [];
  if (hdbIdle?.data) {
    idleDetailParts.push(`HDB trim diff ${hdbIdle.data.trimmed_diff_entry_total ?? 0} | group ${hdbIdle.data.trimmed_group_entry_total ?? 0}`);
  }
  if (csIdle?.data) {
    const before = csIdle.data.avg_parent_depth_before ?? 0;
    const after = csIdle.data.avg_parent_depth_after ?? 0;
    const released = csIdle.data.released_cache_est_bytes ?? 0;
    idleDetailParts.push(`CS depth ${Number(before).toFixed?.(2) ?? before}→${Number(after).toFixed?.(2) ?? after} | cache≈${fmtBytes(released)}`);
  }
  const idleDetail = idleDetailParts.length ? idleDetailParts.join(" | ") : "点击右侧按钮可手动触发。";
  const timing = report.timing || {};
  const totalMs = Number(timing.total_logic_ms ?? timing.total_ms ?? 0) || 0;
  const timeNote = totalMs ? ` | 耗时 ${Math.round(totalMs)}ms` : "";
  const memoryUi = buildMemoryUiModel(report, S.d.hdb_snapshot || {});
  E.overviewCards.innerHTML = [
    card("最近轮次 / Latest Cycle", S.d.meta?.last_cycle_id || "尚未运行", `${inputView.summaryText}${timeNote}`),
    card("状态池对象 / State Items", snapshot.summary?.active_item_count || 0, `高认知压 / High CP ${snapshot.summary?.high_cp_item_count || 0}`),
    card("总能量 / Total Energy", `ER ${n(energy.total_er)} / EV ${n(energy.total_ev)}`, `CP ${n(energy.total_cp)}`),
    card("记忆体 / Attention Memory", report.attention?.memory_item_count || 0, `抽取消耗 / Consumed ${n(report.attention?.consumed_total_energy)}`),
    card("HDB", `ST ${hdb.structure_count || 0} / SG ${hdb.group_count || 0}`, `EM ${hdb.episodic_count || 0}`),
    card(
      memoryUi.summaryLabel,
      memoryUi.count,
      `ER ${n(memoryUi.totalEr)} | EV ${n(memoryUi.totalEv)} | Total ${n(memoryUi.totalEnergy)} | ${memoryUi.pathLabel}`,
    ),
    card("闲时巩固 / Idle Consolidation", idleWhen, idleDetail),
    card("历史轮次 / Recent Cycles", a(S.d.recent_cycles).length, `启动于 / Started ${tm(S.d.meta?.started_at)}`),
  ].join("");
}

function renderHdbMemorySummary() {
  if (!S.d) return;
  const report = S.d.last_report || {};
  const hdb = S.d.hdb_snapshot || {};
  const summary = hdb.summary || {};
  const memoryUi = buildMemoryUiModel(report, hdb);
  if (E.hdbMeta) {
    E.hdbMeta.textContent =
      `ST ${summary.structure_count || 0} | SG ${summary.group_count || 0} | ` +
      `EM ${summary.episodic_count || 0} | ${memoryUi.shortLabel} ${memoryUi.count} | ` +
      `${memoryUi.shortLabel} Total ${n(memoryUi.totalEnergy)}`;
  }
  if (E.hdbCards) {
    E.hdbCards.innerHTML = [
      card("结构 / 结构组", `${summary.structure_count || 0} / ${summary.group_count || 0}`, `EM ${summary.episodic_count || 0}`),
      card(
        memoryUi.summaryLabel,
        memoryUi.count,
        `ER ${n(memoryUi.totalEr)} | EV ${n(memoryUi.totalEv)} | Total ${n(memoryUi.totalEnergy)} | ${memoryUi.pathLabel}`,
      ),
      card("局部数据库 / Structure DB", summary.structure_db_count || 0, `Issue ${summary.issue_count || 0}`),
      card("修复任务 / Repair", summary.active_repair_job_count || 0, "活动修复任务 / Active repair jobs"),
      card("指针索引 / Pointer Index", Object.entries(hdb.stats?.pointer_index || {}).map(([key, value]) => `${key}:${value}`).join(" | ") || "-", "索引摘要 / Pointer summary"),
    ].join("");
  }
}

function renderRecentCyclesMemorySummary() {
  if (!E.recentCycles) return;
  E.recentCycles.innerHTML = rows(
    a(S.d?.recent_cycles).map((cycle) => {
      const runtimeOnly = String(cycle.memory_path_mode || "").trim() === "runtime_em_only";
      const activationLabel = runtimeOnly ? "残差对象赋能" : "MAP兼容赋能";
      const stockLabel = runtimeOnly ? "residual_runtime" : "map_compat_pool";
      const feedbackLine = runtimeOnly
        ? "MAP 兼容反馈主链已关闭"
        : `compat_feedback ER ${n(cycle.memory_feedback_total_er)} | EV ${n(cycle.memory_feedback_total_ev)}`;
      const processedText = String(cycle.tick_text || cycle.input_text || "").trim() || "空 Tick";
      const submittedText = String(cycle.submitted_text || "").trim();
      const queueNote = submittedText && submittedText !== processedText ? `提交 ${shortInputPreview(submittedText)} | ` : "";
      return {
        title: `${cycle.trace_id || "-"} · 处理 ${shortInputPreview(processedText)}`,
        desc:
          `${queueNote}队列余量 ${cycle.pending_queue_after_tick ?? 0}\n` +
          `记忆体 ${cycle.attention_memory_count || 0} | ${activationLabel} ${cycle.memory_activation_applied_count || 0} | 路径 ${cycle.memory_path_mode || "-"}` + "\n" +
          `认知拼接（Cognitive Stitching，缩写 CS）候选 ${cycle.cs_candidate_count ?? "-"} | 动作 ${cycle.cs_action_count ?? "-"} | 退化 ${cycle.cs_degenerated_event_count ?? "-"}\n` +
          `刺激级查存轮次 ${cycle.stimulus_rounds ?? "-"} | 结构级查存轮次 ${cycle.structure_rounds ?? "-"}\n` +
          `命中结构 ${fmtRefs(cycle.matched_structure_refs)}\n` +
          `新结构 ${fmtRefs(cycle.new_structure_refs)}\n` +
          `${stockLabel} ER ${n(cycle.memory_activation_total_er)} | EV ${n(cycle.memory_activation_total_ev)}\n` +
          `${feedbackLine} | induction EV ${n(cycle.total_delta_ev)}`,
      };
    }),
    "当前没有最近轮次 / No recent cycles yet.",
  );
}

function overview() {
  if (!S.d || !E.overviewCards) return;
  const report = S.d.last_report || {};
  const inputView = buildInputQueueViewModel(report);
  const snapshot = S.d.state_snapshot || {};
  const energy = S.d.state_energy_summary || {};
  const hdb = S.d.hdb_snapshot?.summary || {};
  const memoryUi = buildMemoryUiModel(report, S.d.hdb_snapshot || {});
  const maint = S.d.maintenance_runtime || {};
  const hdbIdle = maint.hdb_last_idle_consolidation || null;
  const csIdle = maint.cs_last_idle_consolidation || null;
  const hdbTs = Number(hdbIdle?.data?.timestamp_ms ?? 0) || 0;
  const csTs = Number(csIdle?.data?.timestamp_ms ?? 0) || 0;
  const idleTs = Math.max(hdbTs, csTs);
  const idleWhen = idleTs ? tm(idleTs) : "尚未执行";
  const idleDetailParts = [];
  if (hdbIdle?.data) idleDetailParts.push(`HDB trim diff ${hdbIdle.data.trimmed_diff_entry_total ?? 0}`);
  if (csIdle?.data) idleDetailParts.push(`CS depth ${n(csIdle.data.avg_parent_depth_before)}→${n(csIdle.data.avg_parent_depth_after)}`);
  const idleDetail = idleDetailParts.length ? idleDetailParts.join(" | ") : "点击按钮可触发";
  E.overviewCards.innerHTML = [
    card("最近轮次", S.d.meta?.last_cycle_id || "尚未运行", inputView.summaryText),
    card("状态池对象", snapshot.summary?.active_item_count || 0, `高认知压 ${snapshot.summary?.high_cp_item_count || 0}`),
    card("总能量", `ER ${n(energy.total_er)} / EV ${n(energy.total_ev)}`, `CP ${n(energy.total_cp)}`),
    card("记忆体", report.attention?.memory_item_count || 0, `抽取消耗 ${n(report.attention?.consumed_total_energy)}`),
    card("HDB", `ST ${hdb.structure_count || 0} / SG ${hdb.group_count || 0}`, `EM ${hdb.episodic_count || 0}`),
    card(memoryUi.shortLabel, memoryUi.count, `ER ${n(memoryUi.totalEr)} | EV ${n(memoryUi.totalEv)} | ${memoryUi.pathLabel}`),
    card("闲时巩固", idleWhen, idleDetail),
    card("历史轮次", a(S.d.recent_cycles).length, `启动于 ${tm(S.d.meta?.started_at)}`),
  ].join("");
}

function sensor() {
  const report = S.d?.last_report || {};
  const s = report.sensor || {};
  const inputView = buildInputQueueViewModel(report);
  const rt = S.d?.sensor_runtime?.config_summary || {};
  const rtTokenizer =
    String(rt.tokenizer_backend_effective || rt.tokenizer_backend || rt.tokenizer_backend_config || "-") || "-";
  const rtTokenizerAvail = rt.tokenizer_available;
  if (E.sensorMeta) E.sensorMeta.textContent = `本 tick 处理: ${inputView.processedLabel} | 本次提交: ${inputView.submittedLabel} | 队列余量 ${inputView.pendingAfter}`;
  if (E.sensorCards) {
    E.sensorCards.innerHTML = [
      card("本 tick 处理片段", inputView.processedLabel, `归一化 ${s.normalized_text || "-"} | FIFO 队列顺序处理`),
      card("本次提交文本", inputView.submittedLabel, `最近源文本 ${inputView.queueSourceLabel} | 新入队 ${inputView.queuedCount} 段 | 队列余量 ${inputView.pendingAfter}`),
      card("分词后端", s.tokenizer_backend || rtTokenizer || "-", `可用 ${y(s.tokenizer_available ?? rtTokenizerAvail)}`),
      card("模式", s.mode || rt.default_mode || "-", `fallback ${y(s.tokenizer_fallback)}`),
      card("SA / CSA", `${s.sa_count || 0} / ${s.csa_count || 0}`, `刺激组 ${a(s.groups).length} | bundles ${s.csa_bundle_count ?? 0}`),
      card("Echo", a(s.echo_frames_used).length, `衰减 ${s.echo_decay_summary?.decay_mode || rt.echo_decay_mode || "-"}`),
      card("刺激疲劳", s.fatigue_summary?.suppressed_unit_count || 0, `抑制ER ${n(s.fatigue_summary?.total_er_suppressed)} | 归零 ${s.fatigue_summary?.zero_er_unit_count || 0}`),
    ].join("");
  }
  if (E.sensorUnits) E.sensorUnits.innerHTML = rows(a(s.feature_units).map(fmtSensorUnit), "当前没有刺激单元。");
  if (E.sensorGroups) E.sensorGroups.innerHTML = rows(a(s.groups).map(fmtStimulusGroup), "当前没有刺激组。");
}

function timeSensorView() {
  if (!E.timeSensorMeta || !E.timeSensorBuckets || !E.timeSensorMemories) return;
  const report = S.d?.last_report || {};
  const ts = report.time_sensor || {};
  if (!ts || typeof ts !== "object" || Object.keys(ts).length === 0) {
    E.timeSensorMeta.textContent = "尚未产生时间感受数据（请先运行一次循环）。";
    E.timeSensorBuckets.innerHTML = empty("等待时间感受器输出…");
    E.timeSensorMemories.innerHTML = empty("等待时间感受器输出…");
    return;
  }

  if (ts.error) {
    E.timeSensorMeta.textContent = `时间感受器报错: ${String(ts.error)}`;
    E.timeSensorBuckets.innerHTML = empty("时间感受器执行失败。");
    E.timeSensorMemories.innerHTML = empty("时间感受器执行失败。");
    return;
  }

  const enabled = ts.enabled !== false;
  const nowMs = Number(ts.now_ms || report.started_at || 0) || 0;
  const timeBasis = String(ts.time_basis || "wallclock").trim() || "wallclock";
  const tickIndex = ts.tick_index !== undefined && ts.tick_index !== null ? Number(ts.tick_index) : null;
  const used = Number(ts.memory_used_count || 0) || 0;
  const mode = String(ts.source_mode || "-");
  const outMode = String(ts.output_mode || "bucket_nodes");
  // New flags (can be enabled simultaneously) / 新版双开关（可同时启用）
  const enableBucketNodes = ts.enabled_bucket_nodes !== undefined ? Boolean(ts.enabled_bucket_nodes) : outMode === "bucket_nodes" || outMode === "both";
  const enableBindAttribute = ts.enabled_bind_attribute !== undefined ? Boolean(ts.enabled_bind_attribute) : outMode === "bind_attribute" || outMode === "both";
  const outLabel = enableBucketNodes && enableBindAttribute ? "桶节点 + 属性绑定" : enableBindAttribute ? "绑定属性（推荐）" : enableBucketNodes ? "时间桶节点" : "不输出";
  const basisLabel = timeBasis === "tick" ? `tick(${tickIndex ?? "-"})` : "wallclock";
  E.timeSensorMeta.textContent = `${enabled ? "启用" : "禁用"} | 基准 ${basisLabel} | 输出 ${outLabel} | 来源 ${mode} | 参与记忆 ${used} | 时间 ${nowMs ? tm(nowMs) : "-"}`;

  const bucketUpdates = a(ts.bucket_updates);
  const poolEvents = a(ts.pool_events);

  const bucketSummary = bucketUpdates.length
    ? bucketUpdates
        .slice(0, 10)
        .map((b) => `${String(b.label_zh || b.bucket_id || "-")}=${n(b.assigned_energy)}`)
        .join(" / ")
    : "-";

  const parts = [];

  if (enableBindAttribute) {
    const binds = a(ts.attribute_bindings);
    parts.push(
      dCard(
        "时间感受绑定（属性刺激元绑定）",
        rows(
          binds.slice(0, 64).map((b) => {
            const du = String(b.delta_unit || (timeBasis === "tick" ? "tick" : "s"));
            const delta = b.delta_value !== undefined && b.delta_value !== null ? b.delta_value : b.delta_sec;
            const dt = delta === undefined || delta === null ? "-" : n(delta);
            const u = du === "tick" ? "tick" : "s";
            const centerU = u;
            return {
              title: `${b.attribute_display || "时间感受"} → ${b.target_display || b.target_item_id || "-"}`,
              desc:
                `目标 ${b.target_display || "-"} | ${refTypeLabel(b.target_ref_object_type)}:${b.target_ref_object_id || "-"} | item ${b.target_item_id || "-"}\n` +
                `来源记忆 ${b.memory_display_text || b.memory_id || "-"} | Δt ${dt}${u} | 波峰增量 ${n(b.target_delta_energy)}\n` +
                `主桶 ${b.bucket_label_zh || b.bucket_id || "-"}（w=${n(b.bucket_weight)}） | center ${n(b.bucket_center_sec)}${centerU}\n` +
                (b.bucket_secondary_id ? `副桶 ${b.bucket_secondary_label_zh || b.bucket_secondary_id || "-"}（w=${n(b.bucket_secondary_weight)}） | center ${n(b.bucket_secondary_center_sec)}${centerU}\n` : "") +
                `桶能量汇总（Top10）${bucketSummary}`,
            };
          }),
          "本轮没有生成时间感受绑定（通常表示：本 tick 没有可用的时间感受源，或延迟赋能未命中）。",
        ),
      ),
    );
  }

  if (enableBucketNodes) {
    const byRef = {};
    for (const ev of poolEvents) {
      if (!ev || typeof ev !== "object") continue;
      const ref = String(ev.ref_id || "");
      if (!ref) continue;
      byRef[ref] = ev;
    }
    parts.push(
      dCard(
        "时间桶节点赋能（数值桶节点）",
        rows(
          bucketUpdates
            .slice(0, 32)
            .map((b) => {
              const key = String(b.energy_key || "ev");
              const e = Number(b.assigned_energy || 0) || 0;
              const ref = String(b.ref_object_id || "");
              const pe = byRef[ref] || {};
              const op = pe.op ? `写入 ${String(pe.op)}` : "写入 -";
              const delta = key === "er" ? `ΔER ${n(e)}` : `ΔEV ${n(e)}`;
              const unit = String(b.unit || (timeBasis === "tick" ? "tick" : "s"));
              const u = unit === "tick" ? "tick" : "s";
              const center = b.center_sec !== undefined ? `center ${n(b.center_sec)}${u}` : "";
              const range = Array.isArray(b.range_sec) ? `range ${String(b.range_sec[0] ?? "-")}~${String(b.range_sec[1] ?? "-")}${u}` : "";
              return {
                title: `${b.label_zh || b.bucket_id || "-"} · ${delta}`,
                desc: `${op} | ref_id ${ref || "-"}\n${[center, range].filter(Boolean).join(" | ") || "-"}`,
              };
            }),
          "本轮没有时间桶被赋能（可能是当前时间感受能量不足，或阈值较高）。",
        ),
      ),
    );
  } else if (bucketUpdates.length) {
    // When bucket nodes are not written into StatePool, still show the computed bucket energies.
    // 当未启用“桶节点入池”时，仍然展示计算出的桶能量（便于验收双桶/分段口径）。
    parts.push(
      dCard(
        "时间桶能量（仅计算，不入池）",
        rows(
          bucketUpdates.slice(0, 32).map((b) => {
            const key = String(b.energy_key || "ev");
            const e = Number(b.assigned_energy || 0) || 0;
            const delta = key === "er" ? `ΔER ${n(e)}` : `ΔEV ${n(e)}`;
            const unit = String(b.unit || (timeBasis === "tick" ? "tick" : "s"));
            const u = unit === "tick" ? "tick" : "s";
            const center = b.center_sec !== undefined ? `center ${n(b.center_sec)}${u}` : "";
            const range = Array.isArray(b.range_sec) ? `range ${String(b.range_sec[0] ?? "-")}~${String(b.range_sec[1] ?? "-")}${u}` : "";
            return {
              title: `${b.label_zh || b.bucket_id || "-"} · ${delta}`,
              desc: `${[center, range].filter(Boolean).join(" | ") || "-"}`,
            };
          }),
          "本轮没有时间桶能量（可能是当前时间感受能量不足，或阈值较高）。",
        ),
      ),
    );
  }

  // Delayed energization tasks (biological clock MVP) / 延迟赋能任务（生物钟 MVP）
  // Note: only attribute time-feelings can register tasks (theory 4.2.8).
  const dt = ts.delayed_tasks;
  if (dt && typeof dt === "object") {
    const execEnabled = dt.enabled !== false;
    const reg = dt.registered && typeof dt.registered === "object" ? dt.registered : {};
    const regEnabled = reg.enabled !== false;
    const tableSize = Number(dt.table_size ?? reg.table_size ?? 0) || 0;
    const executedCount = Number(dt.executed_count || 0) || 0;
    const regCount = Number(reg.registered_count || 0) || 0;
    const updCount = Number(reg.updated_count || 0) || 0;
    const prunedCount = Number(reg.pruned_count || 0) || 0;
    const skipped = reg.skipped && typeof reg.skipped === "object" ? reg.skipped : {};
    const skippedText = `small ${Number(skipped.small_delta || 0) || 0} | fatigue ${Number(skipped.fatigue || 0) || 0} | bad ${Number(skipped.bad || 0) || 0}`;
    const tasks = a(reg.tasks);
    const executed = a(dt.executed);

    const overviewRow = {
      title: `${execEnabled && regEnabled ? "启用" : "禁用"} · 表内 ${tableSize}`,
      desc: `本 tick 执行 ${executedCount} | 注册 ${regCount} / 更新 ${updCount} | 裁剪 ${prunedCount} | skipped ${skippedText}`,
    };

    if (!execEnabled && !regEnabled) {
      parts.push(dCard("延迟赋能任务（生物钟）", empty("未启用（enable_delayed_tasks=false）。")));
    } else {
      parts.push(
        dCard(
          "延迟赋能任务表（生物钟）",
          rows(
            [
              overviewRow,
              ...tasks.slice(0, 16).map((t) => {
                const tb = String(t.time_basis || timeBasis);
                const intervalUnit = tb === "tick" ? "tick" : "s";
                const intervalText = t.interval_value !== undefined && t.interval_value !== null ? `${n(t.interval_value)}${intervalUnit}` : "-";
                let dueText = "-";
                if (tb === "tick") {
                  const dueTick = t.due_tick !== undefined && t.due_tick !== null ? Number(t.due_tick) : null;
                  if (dueTick !== null && !Number.isNaN(dueTick)) {
                    const inTicks = tickIndex !== null && !Number.isNaN(Number(tickIndex)) ? dueTick - Number(tickIndex) : null;
                    dueText = `due_tick ${dueTick}${inTicks !== null ? ` | in ${inTicks}` : ""}`;
                  } else {
                    dueText = `due_tick ${String(t.due_tick ?? "-")}`;
                  }
                } else {
                  const dueAt = t.due_at_ms !== undefined && t.due_at_ms !== null ? Number(t.due_at_ms) : 0;
                  dueText = dueAt ? `due ${tm(dueAt)}` : "due -";
                }
                return {
                  title: `${t.target_display || t.target_ref_object_id || t.target_item_id || "-"} · w=${n(t.weight)}`,
                  desc:
                    `目标 ${refTypeLabel(t.target_ref_object_type)}:${t.target_ref_object_id || "-"} | item ${t.target_item_id || "-"}\n` +
                    `interval ${intervalText} | ${dueText} | register_count ${Number(t.register_count || 0) || 0}`,
                };
              }),
            ],
            "任务表为空（本 tick 没有满足注册条件的时间感受绑定）。",
          ),
        ),
      );

      parts.push(
        dCard(
          "延迟赋能执行（生物钟）",
          rows(
            [
              { title: `本 tick 执行 ${executedCount}`, desc: `events ${a(dt.pool_events).length} | time_basis ${timeBasis}` },
              ...executed.slice(0, 16).map((x) => ({
                title: `${x.ok ? "OK" : "FAIL"} · ${x.target_display || x.target_item_id || "-"}`,
                desc:
                  `item ${x.target_item_id || "-"} | Δ${String(x.energy_key || "ev").toUpperCase()} ${n(x.delta_energy)} | w=${n(x.weight)}\n` +
                  `due ${String(x.due_reason || "-")}`,
              })),
            ],
            "本 tick 没有执行到期任务。",
          ),
        ),
      );
    }
  }

  E.timeSensorBuckets.innerHTML = parts.length ? parts.join("") : empty("当前输出模式没有启用 bucket_nodes / bind_attribute。");

  E.timeSensorMemories.innerHTML = rows(
    a(ts.memory_rows)
      .slice(0, 24)
      .map((m) => {
        const du = String(m.delta_unit || (timeBasis === "tick" ? "tick" : "s"));
        const u = du === "tick" ? "tick" : "s";
        const delta = m.delta_value !== undefined && m.delta_value !== null ? m.delta_value : m.delta_sec;
        const dt = delta === undefined || delta === null ? "-" : n(delta);
        return {
          title: `${m.display_text || m.memory_id || "-"} · Δt ${dt}${u}`,
          desc:
            `memory_id ${m.memory_id || "-"} | total_energy ${n(m.total_energy)} | time_energy ${n(m.time_feeling_energy)}\n` +
            `桶1 ${m.bucket_1 || "-"} w=${n(m.w1)} | 桶2 ${m.bucket_2 || "-"} w=${n(m.w2)}`,
        };
      }),
    "本轮没有参与时间感受计算的记忆条目。",
  );
}

function fBlock(title, description, parts) {
  return `<article class="timeline-step flow-step"><div class="flow-step-header"><div><h4>${esc(title)}</h4><p>${esc(description)}</p></div></div><div class="detail-stack">${parts.join("")}</div></article>`;
}

function dCard(title, content, className = "") {
  return `<section class="detail-card ${className}"><h5>${esc(title)}</h5><div class="detail-card-body">${content}</div></section>`;
}

const NEUTRALIZATION_STATUS_LABELS = {
  applied: "已应用",
  shortfall: "有缺口",
  skipped: "已剪枝",
  below_effect_threshold: "能量过薄未生效",
};

const NEUTRALIZATION_REASON_LABELS = {
  no_token_overlap: "没有 token 重合",
  low_potential_structure_coverage: "潜在结构覆盖率过低",
  packet_no_opposite_energy: "刺激包没有对向能量",
  no_common_part: "没有形成有效共同部分",
  low_structure_coverage: "实际结构覆盖率过低",
  low_match_score: "软匹配分过低",
  exact_signature_miss: "未达到旧版精确命中条件",
  effective_budget_below_threshold: "本轮可用预算低于生效阈值",
  matched_energy_too_thin: "命中能量过薄",
  matched_energy_empty: "命中内容没有可消费能量",
  no_runtime_sa_target: "匹配到了结构，但没有解析到可结算 SA",
  matched_sa_no_opposite_energy: "命中的 SA 没有拿到对向能量",
  matched_sa_balanced: "命中的 SA 当前已基本平衡",
};

function stText(stats) {
  if (!stats) return "无";
  return `W ${n(stats.base_weight)} | G ${n(stats.recent_gain)} | fatigue ${n(stats.fatigue)} | runtime_er ${n(stats.runtime_er)} | runtime_ev ${n(stats.runtime_ev)} | match ${stats.match_count_total || 0}`;
}

function flow() {
  const report = S.d?.last_report;
  if (!report || !E.flowTimeline) {
    if (E.flowTimeline) E.flowTimeline.innerHTML = empty("执行一次循环后，这里会显示完整流程。");
    if (E.recentCycles) E.recentCycles.innerHTML = empty("当前没有最近轮次。");
    return;
  }

  if (E.flowMeta) E.flowMeta.textContent = `trace ${report.trace_id || "-"} | 时间 ${tm(report.started_at)}`;
  let flowStepCounter = 1;
  const stepBlock = (title, desc, cards) => fBlock(`${flowStepCounter++}. ${title}`, desc, cards);

  // Build a small lookup from the final StatePool snapshot for better target display.
  // 用最终状态池快照构建索引：把 CFS/行动的“目标 id”补全成更可读的对象展示文本。
  const finalStateSnapshot = report.final_state?.state_snapshot || {};
  const finalHdbSnapshot = report.final_state?.hdb_snapshot || {};
  const finalHdbSummary = finalHdbSnapshot.summary || {};
  const finalPoolItems = a(finalStateSnapshot.top_items);
  const poolByItemId = new Map();
  const poolByRef = new Map();
  for (const row of finalPoolItems) {
    if (!row || typeof row !== "object") continue;
    const itemId = String(row.item_id || row.id || "").trim();
    const refId = String(row.ref_object_id || "").trim();
    // Normalize type for stable lookup / 统一 type 大小写，避免 ST/st 等不一致导致查不到目标。
    const refTypeRaw = String(row.ref_object_type || "").trim();
    const refType = refTypeRaw.toLowerCase();
    if (itemId) poolByItemId.set(itemId, row);
    if (refId && refType) poolByRef.set(`${refType}:${refId}`, row);
    // Alias indexing / 别名索引：语义合并后同一对象可能同时拥有 sa_* 与 st_* 等多个 ref_id。
    // 这里把 ref_alias_ids 也加入索引，避免前端渲染只剩 “st_000xxx/sa_xxx” 而找不到内容。
    const aliases = a(row.ref_alias_ids).map((x) => String(x || "").trim()).filter(Boolean);
    for (const aid of aliases) {
      // Infer type from id prefix when possible / 尽力从 id 前缀推断类型
      let ty = "";
      if (aid.startsWith("st_")) ty = "st";
      else if (aid.startsWith("sa_")) ty = "sa";
      else if (aid.startsWith("csa_")) ty = "csa";
      else if (aid.startsWith("em_")) ty = "em";
      else if (aid.startsWith("cfs_")) ty = "cfs_signal";
      else if (aid.startsWith("action_")) ty = "action_node";
      // Always index with the inferred type if available; also index with the row's own type.
      // 若推断到类型则用推断类型索引；同时也用 row 本身类型索引（更稳健）。
      if (ty) poolByRef.set(`${String(ty).toLowerCase()}:${aid}`, row);
      if (refType) poolByRef.set(`${refType}:${aid}`, row);
    }
  }
  const resolvePoolRowForTarget = (target) => {
    const t = target && typeof target === "object" ? target : {};
    const itemId = String(t.target_item_id || t.item_id || "").trim();
    const refId = String(t.target_ref_object_id || t.ref_object_id || "").trim();
    const refTypeRaw = String(t.target_ref_object_type || t.ref_object_type || "").trim();
    const refType = refTypeRaw.toLowerCase();
    if (itemId && poolByItemId.has(itemId)) return poolByItemId.get(itemId);
    if (refId && refType && poolByRef.has(`${refType}:${refId}`)) return poolByRef.get(`${refType}:${refId}`);
    // Best-effort scan by ref_object_id (ignore type mismatch / casing).
    // 兜底：按 ref_object_id 扫一次（忽略 type 不一致/大小写差异）。
    if (refId) {
      for (const [k, v] of poolByRef.entries()) {
        if (String(k || "").endsWith(`:${refId}`)) return v;
      }
    }
    // If still not found, scan by alias id (best-effort).
    // 若仍未找到：兜底按 ref_alias_ids 扫描一次（仅渲染时做，成本可接受）。
    if (refId) {
      for (const row of finalPoolItems) {
        const aliases = a(row.ref_alias_ids).map((x) => String(x || "").trim()).filter(Boolean);
        if (aliases.includes(refId)) return row;
      }
    }
    return null;
  };
  const fmtTargetWithPool = (target) => {
    const t = target && typeof target === "object" ? target : {};
    const refId = String(t.target_ref_object_id || "").trim();
    const refTypeRaw = String(t.target_ref_object_type || "").trim();
    const refType = refTypeRaw.toLowerCase();
    const itemId = String(t.target_item_id || "").trim();
    const rawDisplay = String(t.target_display || "").trim();
    const row = resolvePoolRowForTarget(t);
    // 注意：row.display_detail 往往是 attrs/runtime_attrs 的解释摘要，不是对象本身内容；
    // 这里必须优先展示对象内容（row.display），避免“自粘式只剩 runtime_attrs / st_id”的糟糕体验。
    // Note: prefer real object content (row.display) over debug detail (row.display_detail).
    const poolMain = row ? String(row.display || "").trim() : "";
    const poolDetail = row ? String(row.display_detail || "").trim() : "";
    const display = poolMain || rawDisplay || poolDetail || refId || itemId || "-";
    const idPart = refId ? `${refTypeLabel(refType)}:${refId}` : (itemId ? `item:${itemId}` : "-");
    const attrs = row ? a(row.attribute_displays).slice(0, 4).filter(Boolean) : [];
    const rtAttrs = row ? a(row.bound_attribute_displays).slice(0, 4).filter(Boolean) : [];
    const extra =
      (attrs.length ? ` | 属性 ${attrs.join("，")}` : "") +
      (rtAttrs.length ? ` | 运行态属性 ${rtAttrs.join("，")}` : "");
    return `${display} | ${idPart}${extra}`;
  };
  // A slightly more explicit target formatter for newcomer-friendly panels.
  // 新手面板专用：在目标后面补充 ER/EV/CP 等能量读数，方便直观理解“哪里在痛/哪里在期待”。
  const fmtTargetWithEnergy = (target) => {
    const t = target && typeof target === "object" ? target : {};
    const row = resolvePoolRowForTarget(t);
    const base = fmtTargetWithPool(target);
    if (!row) return base;
    return `${base} | ER ${n(row.er)} | EV ${n(row.ev)} | CP ${n(row.cp_abs)} | 总 ${n(te(row))}`;
  };

  const maintenance = report.maintenance || {};
  const attention = report.attention || {};
  const structureLevel = report.structure_level?.result || {};
  const structureDebug = structureLevel.debug || {};
  const mergedStimulus = report.merged_stimulus || {};
  // "merged_stimulus" in summary mode is a head preview (groups<=10, units<=24) plus totals.
  // 为避免误读，这里同时展示“预览数量”和“总计数量”。
  const mergedStimulusPreviewGroupCount = a(mergedStimulus.groups).length;
  const mergedStimulusPreviewUnitCount = a(mergedStimulus.feature_units).length;
  const mergedStimulusTotalGroupCount = mergedStimulus.group_count ?? mergedStimulusPreviewGroupCount;
  const mergedStimulusTotalUnitCount = mergedStimulus.unit_count ?? mergedStimulusPreviewUnitCount;
  const mergedStimulusPreviewTruncated =
    mergedStimulusTotalGroupCount > mergedStimulusPreviewGroupCount ||
    mergedStimulusTotalUnitCount > mergedStimulusPreviewUnitCount;
  const cache = report.cache_neutralization || {};
  const stimulusLevel = report.stimulus_level?.result || {};
  const stimulusDebug = stimulusLevel.debug || {};
  const poolApply = report.pool_apply || {};
  const induction = report.induction?.result || {};
  const inductionDebug = induction.debug || {};
  const inductionSourceSelection = report.induction?.source_selection || induction.source_selection || {};
  const inductionRoundSummaries = a(induction.energy_graph_round_summaries);
  const inductionLayerHistogram = induction.energy_graph_layer_histogram || {};
  const inductionLayerSummary = Object.entries(inductionLayerHistogram)
    .sort((left, right) => (+left?.[0] || 0) - (+right?.[0] || 0))
    .map(([depth, count]) => `L${depth}:${count}`)
    .join(" | ");
  const memoryActivation = report.memory_activation || {};
  const contextAuditPoolRows = buildContextAuditRows(finalPoolItems, 6);
  const contextAuditStructureRows = buildStructureContextRows(finalHdbSnapshot.recent_structures, 6);
  const memoryActivationApply = memoryActivation.apply_result || {};
  const memoryActivationSnapshot = memoryActivation.snapshot || {};
  const memoryUi = buildMemoryUiModel(report, finalHdbSnapshot);
  const memoryPathMode = memoryUi.pathMode;
  const memoryPathLabel = memoryUi.pathLabel;
  const memoryRuntimeProjection = report.memory_runtime_projection || memoryActivation.runtime_projection || {};
  const memoryRuntimeProjectionItems = a(memoryRuntimeProjection.items);
  const memoryRuntimeProjectionSummary = memoryRuntimeProjection.summary || {};
  const memoryRuntimeShadowMode = Boolean(memoryRuntimeProjection.shadow_mode);
  const memoryFeedback = report.memory_feedback || memoryActivation.feedback_result || {};
  const memoryFeedbackItems = a(memoryFeedback.items);
  const memoryFeedbackStimulusCount = memoryFeedbackItems.filter((item) => item?.memory_kind === "stimulus_packet").length;
  const memoryFeedbackStructureCount = memoryFeedbackItems.filter((item) => item?.memory_kind === "structure_group").length;
  const memoryFeedbackTargetCount = memoryFeedbackItems.reduce((sum, item) => sum + (+item?.target_count || 0), 0);
  const memoryFeedbackVisible = memoryPathMode === "dedicated_map" && memoryFeedback.hidden_in_ui !== true && memoryFeedback.ui_visible !== false;
  const showMemoryFeedbackBlock =
    memoryFeedbackVisible &&
    (
      (+memoryFeedback.applied_count || 0) > 0 ||
      memoryFeedbackTargetCount > 0 ||
      (+memoryFeedback.record_result?.recorded_count || 0) > 0
    );
  const inductionSources = a(inductionDebug.source_details);
  const inductionSourceHitCount = inductionSources.filter((source) => a(source?.candidate_entries).length > 0).length;
  const inductionSourceMissCount = Math.max(0, inductionSources.length - inductionSourceHitCount);
  const inductionErSourceCount =
    +inductionSourceSelection.induction_source_selected_from_er_count ||
    inductionSources.filter((source) => (+source?.source_er || 0) > 0).length;
  const inductionEvSourceCount =
    +inductionSourceSelection.induction_source_selected_from_ev_count ||
    inductionSources.filter((source) => (+source?.source_ev || 0) > 0).length;
  const energyGraphConfig = induction.energy_graph_config || {};
  const energyGraphMaxRounds =
    +induction.energy_graph_config_max_rounds ||
    +energyGraphConfig.max_rounds ||
    0;
  const energyGraphRoundLimitLabel = energyGraphMaxRounds > 0 ? energyGraphMaxRounds : "剪枝停止";
  const showEnergyGraphBlock =
    Boolean(induction.energy_graph_v2_enabled) &&
    (
      (+induction.energy_graph_round_count_max || 0) > 0 ||
      (+induction.energy_graph_frontier_generated_count || 0) > 0 ||
      (+induction.energy_graph_root_reinduction_count || 0) > 0 ||
      inductionRoundSummaries.length > 0 ||
      a(inductionDebug.source_details).some((source) => a(source?.candidate_entries).length > 0)
    );
  const cfs = report.cognitive_feeling || {};
  const cfsSignals = a(cfs.cfs_signals);
  const cfsWrites = cfs.writes || {};
  const cfsRuntimeNodes = a(cfsWrites.runtime_nodes);
  const cfsAttrBindings = a(cfsWrites.attribute_bindings);
  const emotion = report.emotion || {};
  const innateScript = report.innate_script || {};
  const focusData = innateScript.focus || {};
  const innateCfsSignals = a(focusData.cfs_signals);
  const focusDirectivesNew = a(focusData.focus_directives);
  const action = report.action || {};
  const executedActions = a(action.executed_actions);
  const focusDirectivesOut = a(action.focus_directives_out);
  const actionModulationOut = action.modulation_out || {};
  const actionNodes = a(action.nodes);
  const actionTriggers = a(action.triggers);
  const actionExecutors = a(action.executors_registry);
  const thresholdMod = action.threshold_modulation || {};
  const actionLearningSummary = action.action_learning_summary || {};
  const energyBalance = report.energy_balance || {};

  // Action kind label (Chinese-first, bilingual) / 行动类型中文名（中文优先 + 中英文双语）
  const actionKindTitle = (kind) => {
    const k = String(kind || "").trim();
    if (!k) return "-";
    const ex = actionExecutors.find((x) => String(x?.action_kind || "").trim() === k);
    const zh = String(ex?.title_zh || "").trim();
    if (!zh) return k;
    // Ensure bilingual: append (kind) if not already present.
    // 确保双语：若中文标题里没出现 kind，则补上（kind）。
    return zh.includes(k) ? zh : `${zh}（${k}）`;
  };
  const cacheShortfallSummary =
    Object.entries(
      a(cache.priority_diagnostics).reduce((acc, item) => {
        const key = item?.required_energy_key || "energy";
        acc[key] = (acc[key] || 0) + Number(item?.shortfall_amount || 0);
        return acc;
      }, {}),
    )
      .map(([key, value]) => `${key} ${n(value)}`)
      .join(" / ") || "无 / None";
  const pickFiniteMetric = (row, keys) => {
    for (const key of a(keys)) {
      const num = Number(row?.[key]);
      if (Number.isFinite(num)) return num;
    }
    return null;
  };

  const fmtRetrievalScoreAudit = (row, options = {}) => {
    const legacyBase = pickFiniteMetric(row, options.legacyBaseKeys || ["match_score_legacy", "base_similarity_legacy", "match_score", "base_similarity"]);
    const v2Base = pickFiniteMetric(row, options.v2BaseKeys || ["match_score_v2", "base_similarity_v2"]);
    const blendedBase = pickFiniteMetric(row, options.blendedBaseKeys || ["match_score", "base_similarity"]);
    const legacyCompetition = pickFiniteMetric(row, options.legacyCompetitionKeys || ["competition_score_legacy"]);
    const v2Competition = pickFiniteMetric(row, options.v2CompetitionKeys || ["competition_score_v2"]);
    const blendedCompetition = pickFiniteMetric(row, options.blendedCompetitionKeys || ["competition_score", "score", "similarity_score", "similarity"]);
    const thresholdMargin = pickFiniteMetric(row, options.thresholdMarginKeys || ["v2_threshold_margin"]);
    const availableComponentCount = pickFiniteMetric(row, options.availableComponentKeys || ["v2_available_component_count"]);
    const lines = [];
    if (legacyBase !== null || v2Base !== null || blendedBase !== null) {
      lines.push(`并排基础分：Legacy ${n(legacyBase)} | V2 ${n(v2Base)} | blended ${n(blendedBase)}`);
    }
    if (legacyCompetition !== null || v2Competition !== null || blendedCompetition !== null) {
      lines.push(`并排竞争分：Legacy ${n(legacyCompetition)} | V2 ${n(v2Competition)} | blended ${n(blendedCompetition)}`);
    }
    if (thresholdMargin !== null || availableComponentCount !== null) {
      lines.push(`V2 阈值余量 ${n(thresholdMargin)} | 生效子项 ${availableComponentCount === null ? "-" : String(Math.round(availableComponentCount))}`);
    }
    return lines.join("\n");
  };

  const fmtRetrievalV2Breakdown = (row) => {
    const componentKeys = [
      "v2_base_score",
      "v2_numeric_score",
      "v2_order_alignment_score",
      "v2_attribute_anchor_score",
      "v2_context_support_score",
      "v2_energy_profile_score",
      "v2_structure_inclusion_score",
    ];
    if (!componentKeys.some((key) => Number.isFinite(Number(row?.[key])))) return "";
    return [
      `V2 组成：base ${n(row?.v2_base_score)} | 数值 ${n(row?.v2_numeric_score)} | 顺序 ${n(row?.v2_order_alignment_score)} | 属性锚点 ${n(row?.v2_attribute_anchor_score)}`,
      `V2 支撑：上下文 ${n(row?.v2_context_support_score)} | 能量图景 ${n(row?.v2_energy_profile_score)} | 结构包含度 ${n(row?.v2_structure_inclusion_score)}`,
    ].join("\n");
  };

  const structureScoreAuditOptions = {
    legacyBaseKeys: ["base_similarity_legacy", "base_similarity"],
    v2BaseKeys: ["base_similarity_v2"],
    blendedBaseKeys: ["base_similarity"],
    legacyCompetitionKeys: ["competition_score_legacy"],
    v2CompetitionKeys: ["competition_score_v2"],
    blendedCompetitionKeys: ["competition_score", "score", "similarity"],
  };
  const stimulusScoreAuditOptions = {};

  const structureRounds = a(structureDebug.round_details).length
    ? a(structureDebug.round_details)
        .map((round) => {
          const selected = round.selected_group;
          const selectedLines = selected
            ? [
                `${pickGroupedText(selected, selected.group_id || "-")} | ${selected.group_id || "-"} | score ${n(selected.score ?? selected.competition_score)}`,
                `必要结构 / Required: ${fmtRefs(selected.required_structures || selected.required_ids)}`,
                `偏置结构 / Bias: ${fmtRefs(selected.bias_structures)}`,
                `共同部分 / Common: ${fmtCommon(selected.common_part)}`,
                fmtRetrievalScoreAudit(selected, structureScoreAuditOptions),
                fmtRetrievalV2Breakdown(selected),
              ].filter(Boolean)
            : null;
          return `<article class="detail-card nested"><h5>结构级 Round ${esc(round.round_index || 0)}</h5><div class="kv-list"><div class="kv-row"><div class="k">预算前 / Budget Before</div><div class="v">${fmtBudget(round.budget_before)}</div></div><div class="kv-row"><div class="k">预算后 / Budget After</div><div class="v">${fmtBudget(round.budget_after)}</div></div><div class="kv-row"><div class="k">选中结构组 / Selected Group</div><div class="v">${selectedLines ? htmlLines(selectedLines) : "本轮未命中结构组 / No group match"}</div></div><div class="kv-row"><div class="k">偏置结构 / Bias Structures</div><div class="v">${htmlLines([fmtRefs(round.bias_structures)])}</div></div><div class="kv-row"><div class="k">内源片段 / Internal Fragments</div><div class="v">${htmlLines(a(round.internal_fragments).map((fragment) => `${pickGroupedText(fragment, fragment.display_text || fragment.fragment_id || "-")} | ER ${n(fragment.er_hint)} | EV ${n(fragment.ev_hint)} | Total ${n(fragment.energy_hint)}${fragment.ext?.goal_b_has_string_group ? ` | GoalB字符串 ${listOr(fragment.ext?.goal_b_string_texts, "-", " + ")}` : ""}${fragment.ext?.display_fallback_char_split ? ` | fallback_split ${y(fragment.ext?.display_fallback_char_split)}` : ""}${fragment.ext?.sequence_group_count != null ? ` | seq_groups ${fragment.ext.sequence_group_count}` : ""}`))}</div></div><div class="kv-row"><div class="k">链式打开 / Chain</div><div class="v">${fmtChain(round.chain_steps, "structure")}</div></div><div class="kv-row"><div class="k">局部库动作 / Local DB Actions</div><div class="v">${fmtStorageSummary(round.storage_summary)}</div></div></div><div class="sub-section"><div class="sub-title">候选结构组 / Candidate Groups</div>${rows(a(round.candidate_groups).map((item) => ({ title: `${pickGroupedText(item, item.group_id || "-")} | ${item.group_id || "-"} | score ${n(item.score ?? item.competition_score)}`, desc: [`必要结构 / Required: ${fmtRefs(item.required_structures || item.required_ids)}`, `偏置结构 / Bias: ${fmtRefs(item.bias_structures)}`, `共同部分 / Common: ${fmtCommon(item.common_part)}`, `可用 / Eligible ${y(item.eligible)} | owner ${item.owner_kind || "-"} / ${item.owner_id || "-"} | depth ${item.chain_depth ?? 0}`, `similarity ${n(item.similarity)} | base ${n(item.base_similarity)} | coverage ${n(item.coverage_ratio)} | structure ${n(item.structure_ratio)}`, `wave ${n(item.wave_similarity)} | path ${n(item.path_strength)} | runtime ${n(item.runtime_weight)} | W ${n(item.base_weight)} | G ${n(item.recent_gain)} | fatigue ${n(item.fatigue)}`, fmtRetrievalScoreAudit(item, structureScoreAuditOptions), fmtRetrievalV2Breakdown(item)].filter(Boolean).join("\n") })), "本轮没有候选结构组 / No structure-group candidates.")}</div></article>`;
        })
        .join("")
    : empty("本轮没有结构级轮次细节 / No structure rounds.");

  // ==================================================================
  // 新手友好：把“像人类的认知感受”做成一个总览面板（更容易验收与对外演示）
  // ==================================================================
  const cfsKindGroups = (() => {
    const groups = {};
    for (const sig of cfsSignals) {
      if (!sig || typeof sig !== "object") continue;
      const kind = String(sig.kind || "").trim();
      if (!kind) continue;
      const st = +sig.strength || 0;
      const g = groups[kind] || { kind, count: 0, sum: 0, max: 0, signals: [] };
      g.count += 1;
      g.sum += st;
      if (st > g.max) g.max = st;
      g.signals.push(sig);
      groups[kind] = g;
    }
    const list = Object.values(groups)
      .map((g) => {
        const top = a(g.signals).slice().sort((l, r) => (+r?.strength || 0) - (+l?.strength || 0)).slice(0, 3);
        const ruleCount = {};
        for (const s of a(g.signals)) {
          const rt = String(s?.rule_title || s?.rule_id || "").trim();
          if (!rt) continue;
          ruleCount[rt] = (ruleCount[rt] || 0) + 1;
        }
        const topRules = Object.entries(ruleCount)
          .sort((a0, b0) => (+b0[1] || 0) - (+a0[1] || 0))
          .slice(0, 2)
          .map(([name, c]) => `${name}×${c}`)
          .join(" / ");
        return {
          kind: g.kind,
          count: g.count,
          avg: g.count ? g.sum / g.count : 0,
          max: g.max,
          top,
          topRules,
        };
      })
      .sort((l, r) => (+r?.max || 0) - (+l?.max || 0) || (+r?.count || 0) - (+l?.count || 0));
    return { groups, list };
  })();

  const importantKinds = [
    "dissonance",
    "expectation",
    "pressure",
    "surprise",
    "correct_event",
    "grasp",
    "complexity",
    "repetition",
  ];
  const importantFeelingRows = importantKinds.map((kind) => {
    const g = cfsKindGroups.groups[kind];
    if (!g || !a(g.signals).length) {
      return { title: `${cfsKindLabel(kind)} · 无`, desc: "本轮未出现该感受（可视为当前不显著）。" };
    }
    const top = a(g.signals).slice().sort((l, r) => (+r?.strength || 0) - (+l?.strength || 0))[0] || {};
    return {
      title: `${cfsKindLabel(kind)} · 强度 ${n(top.strength)} · 共 ${g.count} 条`,
      desc: `目标 ${fmtTargetWithEnergy(top.target)}\n触发规则 ${fmtRuleRef(top)}`,
    };
  });
  const kindSummaryRows = cfsKindGroups.list.slice(0, 10).map((g) => {
    const topLines = a(g.top).map((s, idx) => `Top${idx + 1} (${n(s.strength)}) ${fmtTargetWithPool(s.target)}`).join("\n");
    const rulesLine = g.topRules ? `主要触发规则 ${g.topRules}` : "主要触发规则 -";
    return {
      title: `${cfsKindLabel(g.kind)} · ${g.count} 条 · max ${n(g.max)} · avg ${n(g.avg)}`,
      desc: `${topLines || "本轮无可展示目标。"}\n${rulesLine}`,
    };
  });

  const ebcEnabled = y(energyBalance.enabled);
  const ebcLine1 = `EV/ER raw ${n(energyBalance.ratio_raw)} | smooth ${n(energyBalance.ratio_smooth)} | target ${n(energyBalance.target_ratio)}`;
  const ebcLine2 = `g ${n(energyBalance.g_before)} -> ${n(energyBalance.g_after)} | ki ${n(energyBalance.ki)} | updated ${y(energyBalance.updated)}`;
  const ebcLine3 =
    energyBalance.hdb_scales_out && Object.keys(energyBalance.hdb_scales_out || {}).length
      ? `输出 scales ${Object.entries(energyBalance.hdb_scales_out).map(([k, v]) => `${k}=${n(v)}`).join(" / ")}`
      : `输出 scales -（${energyBalance.skipped_reason || "no_output"}）`;

  // Pipeline switches (effective values) / 流程阶段开关（以“生效值”为准）：
  // - 认知拼接（Cognitive Stitching，缩写 CS）
  // - 结构级查存一体（Structure-level Retrieval-Storage）
  const pipelineSwitches = pipelineEffectiveSwitches();
  const showCognitiveStitchingPanel = Boolean(pipelineSwitches.enableCognitiveStitching);
  const showStructureLevelPanel = Boolean(pipelineSwitches.enableStructureLevelRetrievalStorage);

  // Cognitive Stitching panel data (narrative-friendly).
  // 认知拼接（Cognitive Stitching）面板：用于“叙事化想法”验收与调参观察。
  const cs = report.cognitive_stitching || {};
  const csTop = a(cs.narrative_top_items);
  const csActions = a(cs.actions);
  const csCandidates = a(cs.candidate_preview);
  const csCandidateAudit = cs.candidate_audit || {};
  const csEventGrasp = cs.event_grasp || {};
  const csDegeneration = cs.event_degeneration || {};
  const csDegenerationActions = a(csDegeneration.actions_preview);

  const csActionFamilyLabel = (family, actionName) => {
    const f = String(family || "").trim();
    const a0 = String(actionName || "").trim();
    if (a0.startsWith("reinforce_concat_context_structure")) return "强化上下文拼接结构";
    if (a0.startsWith("reinforce_")) return "强化事件（Reinforce Event）";
    if (f === "concat_context_structure") return "上下文拼接结构";
    if (f === "create_event") return "新建事件（Create Event）";
    if (f === "extend_event") return "扩展事件（Extend Event）";
    if (f === "merge_event") return "桥接合并事件（Bridge Merge Event）";
    return f || "-";
  };

  const csRejectedReasonLabel = (reason) => {
    const key = String(reason || "").trim();
    if (key === "below_min_candidate_score") return "候选总分低于最低阈值";
    if (key === "below_v2_min_match_score") return "候选 V2 分数低于最低匹配阈值";
    if (key === "component_count_exceeded") return "拼接后的组分数量超过上限";
    if (key === "non_positive_edge") return "扩展边权重无效或正边总量为 0";
    return key || "-";
  };

  const csCompetitionLabel = (outcome) => {
    const key = String(outcome || "").trim();
    if (key === "stored_new") return "首次入榜";
    if (key === "replaced_existing") return "同签名竞争中替换旧候选";
    if (key === "kept_existing") return "同签名竞争中保留旧候选";
    return key || "-";
  };

  const csScoreBreakdownLine = (row) =>
    `基础分 ${n(row.base_score)} = 边权 ${n(row.edge_ratio_component)} + 匹配 ${n(row.match_strength_component)} + 上下文 ${n(row.context_support_component)} + 能量均衡 ${n(row.energy_balance_component)} + 运行均衡 ${n(row.runtime_balance_component)} + 跨度 ${n(row.bridge_span_component)}`;

  const csScaleLine = (row) =>
    `缩放项：锚点 ${n(row.anchor_scale)} × 疲劳 ${n(row.fatigue_scale)} => 最终分 ${n(row.score)} | 最低阈值 ${n(row.min_candidate_score)} | 阈值余量 ${n(row.threshold_margin)}`;

  const csExecutionScoreSourceLabel = (row) => {
    const source = String(row?.score_source || "").trim().toLowerCase();
    if (source === "v2") return "V2 执行分";
    if (source === "legacy") return "Legacy 执行分";
    return source || "未标注";
  };

  const csExecutionModeLine = (row) =>
    `执行口径（score_source）${csExecutionScoreSourceLabel(row)} | execution_uses_v2_score ${y(Boolean(row?.execution_uses_v2_score))}`;

  const csParallelScoreLine = (row) => {
    const parts = [];
    if (Number.isFinite(Number(row?.legacy_score))) parts.push(`Legacy ${n(row.legacy_score)} | legacy_threshold_margin ${n(row.legacy_threshold_margin)}`);
    if (Number.isFinite(Number(row?.v2_score))) parts.push(`V2 ${n(row.v2_score)} | v2_threshold_margin ${n(row.v2_threshold_margin)}`);
    return parts.length ? `并排审计分数：${parts.join(" | ")}` : "";
  };

  const csV2SoftLine = (row) => {
    const hasBase = Number.isFinite(Number(row?.v2_base_score_raw)) || Number.isFinite(Number(row?.v2_base_score_soft)) || Number.isFinite(Number(row?.v2_base_score));
    const hasGate = Number.isFinite(Number(row?.v2_fatigue_gate_raw)) || Number.isFinite(Number(row?.v2_fatigue_gate_soft)) || Number.isFinite(Number(row?.v2_fatigue_gate));
    const hasComponents =
      Number.isFinite(Number(row?.v2_context_cover_score)) ||
      Number.isFinite(Number(row?.v2_context_cover_soft_score)) ||
      Number.isFinite(Number(row?.v2_order_alignment_score)) ||
      Number.isFinite(Number(row?.v2_order_alignment_soft_score)) ||
      Number.isFinite(Number(row?.v2_tail_match_score)) ||
      Number.isFinite(Number(row?.v2_tail_match_soft_score));
    const lines = [];
    if (hasBase) lines.push(`V2 基础分：raw ${n(row?.v2_base_score_raw)} -> soft ${n(row?.v2_base_score_soft)} -> blended ${n(row?.v2_base_score)}`);
    if (hasGate) lines.push(`V2 疲劳门控：raw ${n(row?.v2_fatigue_gate_raw)} -> soft ${n(row?.v2_fatigue_gate_soft)} -> applied ${n(row?.v2_fatigue_gate)}`);
    if (hasComponents) {
      lines.push(
        `V2 子项柔化：context ${n(row?.v2_context_cover_score)} -> ${n(row?.v2_context_cover_soft_score)} | ` +
        `order ${n(row?.v2_order_alignment_score)} -> ${n(row?.v2_order_alignment_soft_score)} | ` +
        `tail ${n(row?.v2_tail_match_score)} -> ${n(row?.v2_tail_match_soft_score)}`
      );
    }
    return lines.join("\n");
  };

  const csRejectedReasonSummary = Object.entries(csCandidateAudit.rejected_reason_counts || {})
    .sort((l, r) => (+r?.[1] || 0) - (+l?.[1] || 0))
    .map(([reason, count]) => `${csRejectedReasonLabel(reason)} ${count}`)
    .join(" / ");

  const csNarrativeRows = csTop.map((item, idx) => {
    const title =
      `Top${idx + 1} · 总能量 ${n(item.total_energy)} · 实能量（Reality Energy，缩写 ER）${n(item.er)} / ` +
      `虚能量（Virtual Energy，缩写 EV）${n(item.ev)}`;
    const desc =
      `事件内容 ${item.display || item.ref_object_id || "-"}\n` +
      `事件引用签名（event_ref_id）${item.ref_object_id || "-"}\n` +
      `事件结构ID（HDB structure_id）${item.structure_id || "-"}\n` +
      `认知压力（Cognitive Pressure，缩写 CP）${n(item.cp_abs)} | 显著性（salience_score）${n(item.salience_score)} | 把握感（event_grasp）${n(item.event_grasp)}\n` +
      `组分数量（component_count）${item.component_count || 0}\n` +
      `事件结构数据库（Event Structure DataBase，缩写 ESDB）父链深度 ${item.esdb_parent_depth ?? 0} | 父引用数 ${item.esdb_parent_count ?? 0} | 增量残差边 ${item.esdb_delta_entry_count ?? 0} | materialized ${y(item.esdb_materialized)} | 更新次数 ${item.esdb_update_count ?? 0}`;
    return { title, desc };
  });

  const csActionRows = csActions.slice(0, 16).map((action) => {
    const isConcat = String(action.action_family || "") === "concat_context_structure";
    return {
      title: `${csActionFamilyLabel(action.action_family, action.action)} · score ${n(action.score)} · absorb_ratio ${n(action.absorb_ratio)}`,
      desc:
        (isConcat
          ? `结构 ${action.structure_display || action.structure_id || "-"}\n` +
            `结构ID（HDB structure_id）${action.structure_id || "-"} | 运行态 item ${action.structure_item_id || "-"}\n` +
            `上下文 owner ${action.context_owner_id || "-"} | context_ref ${action.context_ref_object_id || "-"}\n`
          : `事件 ${action.event_display || action.event_ref_id || "-"}\n` +
            `事件引用签名（event_ref_id）${action.event_ref_id || "-"} | 事件结构ID（HDB structure_id）${action.event_structure_id || "-"}\n` +
            `组分数量（component_count）${action.event_component_count || 0}\n`) +
        `来源（source）${action.source_kind || "-"}: ${action.source_display || action.source_ref_id || "-"}\n` +
        `目标（target）${action.target_kind || "-"}: ${action.target_display || action.target_ref_id || "-"}\n` +
        `匹配模式（match_mode）${action.match_mode || "-"} | 匹配跨度（matched_span）${action.matched_span ?? 0} | 前缀组分（prefix_components）${action.prefix_components ?? 0}\n` +
        `上下文命中数量（context_k）${action.context_k ?? 0} | 上下文命中比例（context_ratio）${n(action.context_ratio)} | 最近距离（context_distance）${action.context_distance ?? 0}\n` +
        `边权重占比（edge_weight_ratio）${n(action.edge_weight_ratio)} | 匹配强度（match_strength）${n(action.match_strength)} | 能量均衡（energy_balance）${n(action.energy_balance)} | 运行均衡（runtime_balance）${n(action.runtime_balance)}\n` +
        `${csScoreBreakdownLine(action)}\n` +
        `${csScaleLine(action)}\n` +
        `${csExecutionModeLine(action)}${csParallelScoreLine(action) ? `\n${csParallelScoreLine(action)}` : ""}${csV2SoftLine(action) ? `\n${csV2SoftLine(action)}` : ""}\n` +
        `吸收能量（absorbed）ER ${n(action.absorbed_er)} / EV ${n(action.absorbed_ev)} | 总 ${n(action.absorbed_total)}\n` +
        `疲劳（fatigue）${n(action.fatigue_before)} -> ${n(action.fatigue_after)}`,
    };
  });

  const csCandidateRows = csCandidates.slice(0, 12).map((cand, idx) => ({
    title: `候选 ${idx + 1} · ${csActionFamilyLabel(cand.action_type, "")} · score ${n(cand.score)}`,
    desc:
      `来源（source）${cand.source_kind || "-"}: ${cand.source_display || "-"}\n` +
      `目标（target）${cand.target_kind || "-"}: ${cand.target_display || "-"}\n` +
      `${cand.result_display ? `结果结构（result）${cand.result_display} | context_owner ${cand.context_owner_id || "-"}\n` : ""}` +
      `匹配模式（match_mode）${cand.match_mode || "-"} | 上下文命中数量（context_k）${cand.context_k ?? 0} | 上下文命中比例（context_ratio）${n(cand.context_ratio)} | 匹配跨度（matched_span）${cand.matched_span ?? 0}\n` +
      `边权重占比（edge_weight_ratio）${n(cand.edge_weight_ratio)} | 匹配强度（match_strength）${n(cand.match_strength)} | 路径支持 ${n(cand.path_support_score)} | 尾部命中 ${n(cand.last_token_score)} | 能量均衡（energy_balance）${n(cand.energy_balance)} | 运行均衡（runtime_balance）${n(cand.runtime_balance)}\n` +
      `${csScoreBreakdownLine(cand)}\n` +
      `${csScaleLine(cand)}\n` +
      `${csExecutionModeLine(cand)}${csParallelScoreLine(cand) ? `\n${csParallelScoreLine(cand)}` : ""}${csV2SoftLine(cand) ? `\n${csV2SoftLine(cand)}` : ""}\n` +
      `疲劳前值（fatigue_before）${n(cand.fatigue_before)} | 桥接跨度比例（bridge_span_ratio）${n(cand.bridge_span_ratio)}`,
  }));

  const csAuditRejectionRows = a(csCandidateAudit.rejection_preview).slice(0, 10).map((item, idx) => ({
    title: `淘汰 ${idx + 1} · ${csRejectedReasonLabel(item.reason)}${item.action_type ? ` · ${csActionFamilyLabel(item.action_type, "")}` : ""}`,
    desc:
      `来源 ${item.source_display || "-"} -> 目标 ${item.target_display || "-"}\n` +
      `匹配模式 ${item.match_mode || "-"} | 分数 ${n(item.score)} / 最低阈值 ${n(item.min_candidate_score)} | 阈值余量 ${n(item.threshold_margin)}\n` +
      `基础分 ${n(item.base_score)} | 边权占比 ${n(item.edge_weight_ratio)} | 匹配强度 ${n(item.match_strength)} | 上下文比例 ${n(item.context_ratio)}\n` +
      `${csExecutionModeLine(item)}${csParallelScoreLine(item) ? `\n${csParallelScoreLine(item)}` : ""}${csV2SoftLine(item) ? `\n${csV2SoftLine(item)}` : ""}\n` +
      `能量均衡 ${n(item.energy_balance)} | 运行均衡 ${n(item.runtime_balance)} | 桥接跨度 ${n(item.bridge_span_ratio)} | 锚点缩放 ${n(item.anchor_scale)} | 疲劳缩放 ${n(item.fatigue_scale)}${item.max_component_count ? `\n组分数 ${item.new_component_count || 0} / 上限 ${item.max_component_count}` : ""}`,
  }));

  const csAuditCompetitionRows = a(csCandidateAudit.competition_preview).slice(0, 10).map((item, idx) => ({
    title: `竞争 ${idx + 1} · ${csCompetitionLabel(item.outcome)} · incoming ${n(item.incoming_score)} / existing ${n(item.existing_score)}`,
    desc:
      `签名 ${item.candidate_signature || "-"}\n` +
      `新候选 ${item.incoming_source_display || "-"} -> ${item.incoming_target_display || "-"}\n` +
      `旧候选 ${item.existing_source_display || "-"} -> ${item.existing_target_display || "-"}\n` +
      `动作 ${csActionFamilyLabel(item.action_type, "")} | 匹配模式 ${item.match_mode || "-"}`,
  }));

  const csDegenerationActionRows = csDegenerationActions.slice(0, 12).map((act, idx) => ({
    title: `退化动作 ${idx + 1} · 转移能量 ER ${n(act.transferred_er)} / EV ${n(act.transferred_ev)} · created_target_item ${y(act.created_target_item)}`,
    desc:
      `源事件引用签名（source_event_ref_id）${act.source_event_ref_id || "-"}\n` +
      `目标事件引用签名（target_event_ref_id）${act.target_event_ref_id || "-"}\n` +
      `源事件结构ID（source_structure_id）${act.source_structure_id || "-"}\n` +
      `目标事件结构ID（target_structure_id）${act.target_structure_id || "-"}\n` +
      `移除组分（removed_component_refs）${listOr(act.removed_component_refs, "（无）", " / ")}\n` +
      `保留组分（kept_component_refs）${listOr(act.kept_component_refs, "（无）", " / ")}`,
  }));
  const contextActiveCount = +(finalStateSnapshot.summary?.active_item_count || 0);
  const contextItemRatio = contextActiveCount > 0 ? (+finalStateSnapshot.summary?.contextual_item_count || 0) / contextActiveCount : 0;
  const residualItemRatio = contextActiveCount > 0 ? (+finalStateSnapshot.summary?.residual_origin_item_count || 0) / contextActiveCount : 0;
  const hdbContextualCount = +(finalHdbSummary.contextual_structure_count || 0);
  const hdbDiffCount = +(finalHdbSummary.diff_entry_count || 0);
  const sameContentContextRatio = hdbContextualCount > 0 ? (+finalHdbSummary.same_content_multi_context_count || 0) / hdbContextualCount : 0;
  const residualDiffRatio = hdbDiffCount > 0 ? (+finalHdbSummary.residual_diff_entry_count || 0) / hdbDiffCount : 0;

  E.flowTimeline.innerHTML = [
    stepBlock("新手总览（类人感受与闭环）", "把“违和感/期待/压力/惊/正确感/把握感”等认知感受做成一眼可读的面板，便于新测试者快速理解系统此刻在‘感受什么’。", [
      dCard("关键认知感受（重点）", rows(importantFeelingRows, "本轮没有认知感受信号。")),
      dCard("认知感受按类型汇总（Top kinds）", rows(kindSummaryRows, "本轮没有认知感受信号。")),
      dCard("实能量与虚能量平衡控制器（Energy Balance Controller，缩写 EBC，可插拔）", rows([
        { title: `启用 ${ebcEnabled}`, desc: `${ebcLine1}\n${ebcLine2}\n${ebcLine3}` },
      ], "本轮没有 EBC 数据。")),
    ]),

    stepBlock("状态池维护", "先做衰减、中和、淘汰与合并。", [
      dCard("维护账本", [
        card("维护前 / 后", `${maintenance.before_summary?.active_item_count || 0} / ${maintenance.after_summary?.active_item_count || 0}`, "状态池对象数量变化"),
        card("衰减 / 中和", `${maintenance.summary?.decayed_item_count || 0} / ${maintenance.summary?.neutralized_item_count || 0}`, "本轮维护触发次数"),
        card("淘汰 / 合并", `${maintenance.summary?.pruned_item_count || 0} / ${maintenance.summary?.merged_item_count || 0}`, "维护中发生的结构整理"),
        card(
          "软上限衰减（Soft Cap）",
          `pressure ${n(maintenance.summary?.soft_capacity?.pressure_ratio)} / power ${n(maintenance.summary?.soft_capacity?.decay_power)}`,
          `start ${maintenance.summary?.soft_capacity?.start_items ?? "-"} | full ${maintenance.summary?.soft_capacity?.full_items ?? "-"}`,
        ),
      ].join(""), "detail-grid"),
      dCard("状态池事件", rows(a(maintenance.events).map((event) => ({
        title: `${event.event_type || "event"} · ${event.target_display || event.target_item_id || "-"}`,
        desc: `原因 ${event.reason || "-"} | ΔER ${n(event.delta?.delta_er)} | ΔEV ${n(event.delta?.delta_ev)} | ΔCP ${n(event.delta?.delta_cp_abs)}\n前 ${n(event.before?.er)} / ${n(event.before?.ev)} / ${n(event.before?.cp_abs)} -> 后 ${n(event.after?.er)} / ${n(event.after?.ev)} / ${n(event.after?.cp_abs)}`,
      })), "本轮维护没有记录额外事件。")),
    ]),

    stepBlock("激活/旧上下文审计", "这一步不改变算法本身，只把旧 residual/context/provenance 元数据摊开。新版 growth 主链下，正式对象身份仍以完整特征解析为准；这里的 owner/ref/path 只用于激活来源和回滚诊断。", [
      dCard("审计摘要", [
        card("状态池旧上下文元数据", `${finalStateSnapshot.summary?.contextual_item_count || 0}`, `多级路径 ${finalStateSnapshot.summary?.multi_context_item_count || 0} | 平均深度 ${n(finalStateSnapshot.summary?.context_path_depth_mean)}`),
        card("状态池残差来源审计", `${finalStateSnapshot.summary?.residual_origin_item_count || 0}`, "还能追溯到旧残差链；用于审计激活路径，不代表正式结构身份。"),
        card("HDB 旧上下文结构", `${finalHdbSummary.contextual_structure_count || 0}`, `同内容多上下文 ${finalHdbSummary.same_content_multi_context_count || 0}`),
        card("HDB 残差索引", `${finalHdbSummary.residual_diff_entry_count || 0}`, `diff 总数 ${finalHdbSummary.diff_entry_count || 0} | 带记忆引用 ${finalHdbSummary.diff_entry_with_memory_ref_count || 0}`),
        card("旧上下文元数据占比", n(contextItemRatio), `残差来源占比 ${n(residualItemRatio)} | 只作兼容/审计，不作新版身份标准。`),
        card("HDB 分流 / 局部性占比", `${n(sameContentContextRatio)} / ${n(residualDiffRatio)}`, "前者审计旧同内容多 context 残留，后者看数据库内部 diff 是否仍沿残差局部路径传播。"),
      ].join(""), "detail-grid"),
      dCard("状态池前排样本", rows(contextAuditPoolRows, "当前前排状态池对象还没有显式上下文/残差链样本。")),
      dCard("HDB 最近结构样本", rows(contextAuditStructureRows, "当前最近结构里还没有显式上下文/残差链样本。")),
    ]),

    showCognitiveStitchingPanel
      ? stepBlock("认知拼接（Cognitive Stitching，缩写 CS）", "在状态池维护之后，把多个结构对象或事件对象拼接成更长的事件链，形成可叙事的‘当前认知候选’。字段解释：实能量（ER）、虚能量（EV）、认知压力（CP）。", [
          dCard("认知拼接账本（Summary）", [
            card("启用（enabled）", y(cs.enabled), `状态（reason）${cs.reason || "-"} | 返回码（code）${cs.code || "-"} | message ${cs.message || "-"}`),
            card("种子对象（seed）", cs.seed_structure_count || 0, `结构对象 ${cs.seed_plain_structure_count || 0} | 事件对象 ${cs.seed_event_count || 0}`),
            card(
              "候选/动作（candidates/actions）",
              `${cs.candidate_count || 0} / ${cs.action_count || 0}`,
              `上下文拼接 ${cs.concat_count || 0} | 新建事件 ${cs.created_count || 0} | 扩展 ${cs.extended_count || 0} | 合并 ${cs.merged_count || 0} | 强化 ${cs.reinforced_count || 0}`,
            ),
            card(
              "事件结构数据库（Event Structure DataBase，缩写 ESDB）",
              `${cs.esdb_event_count || 0}`,
              `materialized ${cs.esdb_materialized_event_count || 0} | delta_entries ${cs.esdb_delta_entry_total || 0}`,
            ),
            card("同类拼接疲劳状态表（pair_fatigue）", cs.pair_fatigue_state_size || 0, "用于数值化抑制短时间内重复抽能；不会硬阻断。"),
            card(
              "事件把握感（event_grasp）",
              csEventGrasp.emitted_count ?? "-",
              `selected ${csEventGrasp.selected_event_count ?? "-"} | CAM seed ${csEventGrasp.cam_seed_count ?? "-"} | post-CS seed ${csEventGrasp.post_action_seed_count ?? "-"} | mode ${csEventGrasp.focus_mode || "-"} | reason ${csEventGrasp.reason || "-"}`,
            ),
          ].join(""), "detail-grid"),
          dCard("事件退化账本（Event Degeneration Summary）", [
            card("启用（enabled）", y(csDegeneration.enabled), `原因（reason）${csDegeneration.reason || "-"}`),
            card(
              "候选/退化（candidate/degenerated）",
              `${csDegeneration.candidate_event_count ?? "-"} / ${csDegeneration.degenerated_count ?? "-"} `,
              `每 tick 上限 ${csDegeneration.max_events_per_tick ?? "-"} | 最少保留组分数 ${csDegeneration.min_components ?? "-"} | share 阈值 ${n(csDegeneration.share_threshold)} | 最小组分能量 ${n(csDegeneration.min_component_energy)}`,
            ),
          ].join(""), "detail-grid"),
          dCard("事件退化动作预览（Actions Preview）", rows(csDegenerationActionRows, "本轮没有发生事件退化（可能是没有弱组分，或已低于最少保留组分数）。")),
          dCard("候选评分审计（Candidate Audit）", [
            card("通过硬门槛的原始候选", csCandidateAudit.raw_accepted_count || 0, "已经过组分上限、边权有效性与最低分阈值三道硬门槛。"),
            card("去重后保留候选", csCandidateAudit.deduped_candidate_count || 0, `同签名裁剪 ${csCandidateAudit.deduped_pruned_count || 0} | 最终动作 ${cs.action_count || 0}`),
            card("被淘汰候选", csCandidateAudit.rejected_count || 0, csRejectedReasonSummary || "当前没有记录淘汰原因。"),
            card("同签名竞争", `${csCandidateAudit.replacement_count || 0} / ${csCandidateAudit.kept_existing_count || 0}`, "前者表示新候选顶掉旧候选；后者表示旧候选守住名额。"),
            card("平均最终分 / 阈值余量", `${n(csCandidateAudit.score_means?.score)} / ${n(csCandidateAudit.score_means?.threshold_margin)}`, `基础分 ${n(csCandidateAudit.score_means?.base_score)} | 锚点缩放 ${n(csCandidateAudit.score_means?.anchor_scale)} | 疲劳缩放 ${n(csCandidateAudit.score_means?.fatigue_scale)}`),
            card("平均匹配质量", `${n(csCandidateAudit.score_means?.match_strength)} / ${n(csCandidateAudit.score_means?.context_ratio)}`, `边权占比 ${n(csCandidateAudit.score_means?.edge_weight_ratio)} | 能量均衡 ${n(csCandidateAudit.score_means?.energy_balance)} | 运行均衡 ${n(csCandidateAudit.score_means?.runtime_balance)}`),
          ].join(""), "detail-grid"),
          dCard("当前拼接事件能量 Top-N（叙事化视图）", rows(csNarrativeRows, "当前状态池里没有认知拼接事件对象（可能是能量不足或本轮没有拼接）。")),
          dCard("本轮拼接动作（最新动作）", rows(csActionRows, "本轮没有发生事件新建/扩展/合并动作。")),
          dCard("候选预览（Candidate Preview）", rows(csCandidateRows, "本轮没有候选（可能是种子能量不足，或在最低分阈值前就被刷掉了）。")),
          dCard("被阈值刷掉的候选（Top）", rows(csAuditRejectionRows, "本轮没有记录被淘汰的候选。若候选数长期为 0，请优先检查种子能量、扩展边权重与最低候选阈值。")),
          dCard("同签名竞争记录（Top）", rows(csAuditCompetitionRows, "本轮没有发生同签名竞争；说明候选之间目前还不够拥挤，或大多属于不同拼接结果。")),
        ])
      : "",

    stepBlock("注意力滤波（Attention Filter，缩写 AF）", "聚焦优先 + 动态阈值抑制 + 有代价抽取，形成当前注意记忆体（Current Attention Memory，缩写 CAM）。", [
      dCard("注意力账本", [
        card(
          "候选 / 入选",
          `${attention.state_pool_candidate_count || 0} / ${attention.memory_item_count || 0}`,
          `资源上限 cap ${attention.cam_item_cap ?? attention.top_n ?? 16} | 兜底 min ${attention.min_cam_items ?? 2}`,
        ),
        card(
          "动态阈值 / Cutoff",
          `cutoff ${n(attention.dynamic_cutoff?.cutoff_score)}`,
          `ratio ${n(attention.dynamic_cutoff?.keep_ratio)} | 集中度 ${n(attention.dynamic_cutoff?.score_concentration)}`,
        ),
        card(
          "入选来源",
          `focus ${attention.selected_by_counts?.focus_directive || 0} / cutoff ${attention.selected_by_counts?.cutoff || 0}`,
          `min_keep ${attention.selected_by_counts?.min_keep || 0}`,
        ),
          card("抽取比例", n(attention.consume_ratio), y(attention.consume_enabled)),
          card("抽取消耗", `ER ${n(attention.consumed_total_er)} / EV ${n(attention.consumed_total_ev)}`, `总消耗 ${n(attention.consumed_total_energy)}`),
          card(
            "CAM 中残差运行态对象",
            a(attention.top_items).filter(isResidualMemoryRuntimeItem).length,
            `运行态投影 ${memoryRuntimeProjectionSummary.inserted_count || 0} | shadow ${y(memoryRuntimeShadowMode)}`,
          ),
        card(
          "进入结构级查存的结构对象（Structure，缩写 ST）",
          a(attention.structure_items).length,
          "结构对象（ST）是结构级查存一体的输入；当结构级查存一体关闭时，它们仍会用于把当前注意记忆体（CAM）构造成内源刺激（并受 DARL+PARS 预算约束），但不会执行结构级存储。",
        ),
      ].join(""), "detail-grid"),
      dCard("CAM 明细（入选对象）", rows(a(attention.top_items).slice(0, 12).map((item) => ({
        title: fmtStateTitle(item),
        desc: `来源 ${item.selected_by || "-"} | focus_boost ${n(item.focus_boost)} | priority ${n(item.attention_priority)}${item.attention_priority_base !== undefined ? `（base ${n(item.attention_priority_base)} + RA ${n(item.reward_action_bonus ?? 0)}）` : ""}\n对象 ${item.ref_object_id || item.structure_id || item.item_id || "-"} | ER ${n(item.er)} | EV ${n(item.ev)} | CP ${n(item.cp_abs)} | Total ${n(te(item))}\n结构模式 ${item.structure_sequence_mode || "-"} | GoalB 混合结构 ${y(item.goal_b_mixed_structure)}\nfatigue ${n(item.fatigue)} | recency ${n(item.recency_gain)} | 更新 ${item.update_count || 0} 次${item.memory_er !== undefined ? `\n抽取: 池前 ER ${n(item.pool_before_er)} / EV ${n(item.pool_before_ev)} -> 抽取 ER ${n(item.memory_er)} / EV ${n(item.memory_ev)} -> 池后 ER ${n(item.pool_after_er)} / EV ${n(item.pool_after_ev)}` : ""}${item.reward_action_bonus_detail ? `\n奖惩/行动软增益 ${n(item.reward_action_bonus ?? 0)} | ${fmtScalarPlain(item.reward_action_bonus_detail)}` : ""}${hasContextMeta(item) ? `\n上下文 ${fmtContextSummary(item)}` : ""}${hasResidualMeta(item) ? `\n残差 ${fmtResidualSummary(item)}` : ""}`,
      })), "当前没有 CAM 入选对象。")),
    ]),

    showStructureLevelPanel
      ? stepBlock("结构级查存一体（Structure-level Retrieval-Storage）", "结构级以结构对象（Structure，缩写 ST）粒度做链式查存、局部库存储和残差下沉。", [
      dCard("命中与预算 / Matches & Budget", [
        card("CAM 结构数", structureLevel.cam_stub_count || 0, `轮次 ${structureLevel.round_count || 0}`),
        card("命中结构组", a(structureLevel.matched_group_ids).length, listOr(structureLevel.matched_group_ids, "无", ", ")),
        card("新建结构组", a(structureLevel.new_group_ids).length, listOr(structureLevel.new_group_ids, "无", ", ")),
        card("偏置 / 内源片段", `${a(structureLevel.bias_structure_ids).length} / ${a(structureLevel.internal_stimulus_fragments).length}`, `fallback ${y(structureLevel.fallback_used)}`),
      ].join(""), "detail-grid"),
      dCard("进入结构级的结构内容 / CAM Structures", rows(a(structureDebug.cam_items).map((item) => ({
        title: `${pickGroupedText(item, item.display_text || item.structure_id || "-")} · ${item.structure_id || "-"}`,
        desc: `ER ${n(item.er)} | EV ${n(item.ev)} | Total ${n(item.total_energy)}\nW ${n(item.base_weight)} | G ${n(item.recent_gain)} | fatigue ${n(item.fatigue)} | match ${item.match_count_total || 0}`,
      })), "本轮没有结构级 CAM 项。")),
      dCard("结构组轮次 / Structure Rounds", structureRounds),
      dCard("新建结构组 / New Groups", rows(a(structureDebug.new_group_details).map((group) => ({
        title: `${pickGroupedText(group, group.group_id || "-")} | ${group.group_id || "-"}`,
        desc: `必要结构 / Required: ${fmtRefs(group.required_structures)}\n偏置结构 / Bias: ${fmtRefs(group.bias_structures)}\n平均能量画像 / Avg profile ${fmtKvInline(group.avg_energy_profile || {})}\nW ${n(group.base_weight)} | G ${n(group.recent_gain)} | fatigue ${n(group.fatigue)} | match ${group.match_count_total || 0}`,
      })), "本轮没有新建结构组。")),
      ])
      : "",

    stepBlock(
      "完整刺激合流",
      "外源刺激与内源刺激在这里合流。内源刺激来源：若启用结构级查存一体，则使用结构级输出的内源片段；若关闭结构级查存一体，则把当前注意记忆体（Current Attention Memory，缩写 CAM）直接构造成内源共现刺激包（并通过内源分辨率预算 DARL+PARS 做成本约束）。",
      [
      dCard("完整刺激账本", [
        card("显示文本", mergedStimulus.display_text || "空", `packet ${mergedStimulus.packet_id || "-"}`),
        card("ER / EV", `${n(mergedStimulus.total_er)} / ${n(mergedStimulus.total_ev)}`, `flat tokens ${a(mergedStimulus.flat_tokens).length}`),
        card(
          "刺激组 / 单元（预览/总计）",
          `${mergedStimulusPreviewGroupCount} / ${mergedStimulusPreviewUnitCount}`,
          `总计 ${mergedStimulusTotalGroupCount} / ${mergedStimulusTotalUnitCount}${mergedStimulusPreviewTruncated ? "（预览已截断）" : ""} | 外源与内源统一工作集`,
        ),
        card("来源统计（source_type_counts）", fmtKvInline(mergedStimulus.source_type_counts || {}), "按 unit.source_type 统计，用于检查外源/内源混入与来源比例。"),
      ].join(""), "detail-grid"),
      dCard("刺激组明细", rows(a(mergedStimulus.groups).map(fmtStimulusGroup), "当前完整刺激为空。")),
      dCard("刺激单元明细", `<div class="scroll-shell">${rows(a(mergedStimulus.feature_units).map(fmtSensorUnit), "当前没有刺激单元。")}</div>`),
    ],
    ),

    stepBlock("缓存中和", "完整刺激在进入刺激级查存一体之前，会先做缓存中和。这里先用结构级软匹配找缓存锚点，再把真正的中和结算落到命中的 SA 上，用来降低认知压并减少后续无谓学习。", [
      dCard("中和指标 / Neutralization", [
        card("缓存中和", cache.priority_summary?.priority_neutralized_item_count || 0, `事件 ${a(cache.priority_events).length}`),
        card("包体差额", `ER ${n(cache.priority_summary?.consumed_er)} / EV ${n(cache.priority_summary?.consumed_ev)}`, `tokens ${cache.priority_summary?.input_flat_token_count || 0} -> ${cache.priority_summary?.residual_flat_token_count || 0}`),
        card("缺口 / Shortfall", cacheShortfallSummary, "无对向能量可中和时，这里显示缺口"),
        card("输入包", pickGroupedText(cache.input_packet, "空"), `ER ${n(cache.input_packet?.total_er)} / EV ${n(cache.input_packet?.total_ev)}`),
        card("剩余包", pickGroupedText(cache.residual_packet, "空"), `ER ${n(cache.residual_packet?.total_er)} / EV ${n(cache.residual_packet?.total_ev)}`),
      ].join(""), "detail-grid"),
      dCard("缓存中和事件", rows(a(cache.priority_events).map((event) => ({
        title: `${fmtTargetWithPool({
          target_ref_object_id: event.target_ref_object_id,
          target_ref_object_type: event.target_ref_object_type,
          target_item_id: event.target_item_id,
          target_display: event.target_display,
        })} · ${event.event_type || "priority_stimulus_neutralization"}`,
        desc: `匹配签名 ${event.matched_structure_signature || "-"}\n匹配内容 ${listOr(event.extra_context?.matched_tokens, "-", " / ")}\n结算 SA ${event.extra_context?.sa_settled_count || 0}/${event.extra_context?.sa_target_count || 0} | ER ${n(event.extra_context?.consumed_er)} / EV ${n(event.extra_context?.consumed_ev)} | 原因 ${event.reason || "-"}`,
      })), "本轮没有缓存中和事件。")),
      dCard(
        "缓存中和诊断 / Diagnostics",
        rows(
          a(cache.priority_diagnostics).map((d) => fmtNeutralizationDiagnostic(d, fmtTargetWithPool)),
          "本轮没有缓存中和诊断。",
        ),
      ),
    ]),
  ].join("");

  const stimulusBlocksEnhanced = a(stimulusDebug.round_details).length ? a(stimulusDebug.round_details).map((round) => {
    const selected = round.selected_match;
    const selectedLines = selected
      ? [
          `${pickGroupedText(selected, selected.structure_id || "-")} (${selected.structure_id || "-"}) | mode ${selected.match_mode || "-"} | exact ${y(selected.exact_match)} | full ${y(selected.full_structure_included)} | sigma ${n(selected.similarity_score)} | match ${n(selected.match_score)} | coverage ${n(selected.coverage_ratio)} | structure_ratio ${n(selected.structure_match_ratio)} | score ${n(selected.competition_score ?? selected.match_score)} | runtime ${n(selected.runtime_weight)}`,
          fmtRetrievalScoreAudit(selected, stimulusScoreAuditOptions),
          fmtRetrievalV2Breakdown(selected),
        ].filter(Boolean)
      : null;
    return `<article class="detail-card nested"><h5>刺激级 Round ${esc(round.round_index || 0)}</h5><div class="kv-list"><div class="kv-row"><div class="k">锚点 / Anchor</div><div class="v">${round.anchor_unit ? htmlLines([`${round.anchor_unit.display || round.anchor_unit.token || "-"} | ${round.anchor_unit.role || round.anchor_unit.unit_kind || "-"} | source ${round.anchor_unit.source_type || "-"} | group ${round.anchor_unit.group_index ?? "-"} | seq ${round.anchor_unit.sequence_index ?? "-"} | ER ${n(round.anchor_unit.er)} | EV ${n(round.anchor_unit.ev)} | punct ${y(round.anchor_unit.is_punctuation)}`]) : "无 / None"}</div></div><div class="kv-row"><div class="k">局部工作组 / Focus Group</div><div class="v">${htmlLines([`${round.focus_group_text_before || "-"} | group ${round.focus_group_index ?? "-"} | source ${round.focus_group_source_type || "-"}`])}</div></div><div class="kv-row"><div class="k">轮前残余 / Remaining Before</div><div class="v">${htmlLines([`${round.remaining_grouped_text_before || listOr(round.remaining_tokens_before, "空 / Empty", " / ")} | ER ${n(round.remaining_total_er_before)} | EV ${n(round.remaining_total_ev_before)}`])}</div></div><div class="kv-row"><div class="k">候选来源 / Candidate Source</div><div class="v">${htmlLines([`${round.candidate_lookup_source || "-"} | ${a(round.candidate_signature_hits).map((hit) => `${hit.signature || "-"}:${hit.candidate_count || 0}`).join(" | ") || "无 / None"}`])}</div></div><div class="kv-row"><div class="k">链式打开 / Chain</div><div class="v">${fmtChain(round.chain_steps, "stimulus")}</div></div><div class="kv-row"><div class="k">命中结构 / Selected</div><div class="v">${selectedLines ? htmlLines(selectedLines) : "本轮未命中结构 / No match"}</div></div><div class="kv-row"><div class="k">权重前后 / Weights</div><div class="v">${htmlLines([`${stText(round.structure_stats_before)} -> ${stText(round.structure_stats_after)}`])}</div></div><div class="kv-row"><div class="k">覆盖范围 / Coverage</div><div class="v">${htmlLines([`[${(round.covered_range || [])[0] ?? 0}, ${(round.covered_range || [])[1] ?? 0}) | tokens ${listOr(round.covered_tokens, "-", " / ")}`])}</div></div><div class="kv-row"><div class="k">能量转移 / Energy Transfer</div><div class="v">${htmlLines([`competition ${n(round.effective_transfer_fraction)} | sigma ${n(round.transfer_similarity)} | ER ${n(round.transferred_er)} | EV ${n(round.transferred_ev)}`])}</div></div><div class="kv-row"><div class="k">新建共同结构 / New Common</div><div class="v">${round.created_common_structure ? htmlLines([`${pickGroupedText(round.created_common_structure, round.created_common_structure.structure_id || "-")} (${round.created_common_structure.structure_id || "-"}) | ${stText(round.created_common_structure.stats)}`]) : "无 / None"}</div></div><div class="kv-row"><div class="k">新建残差信息 / New Residual</div><div class="v">${round.created_residual_structure ? fmtResidualMemory(round.created_residual_structure) : "无 / None"}</div></div><div class="kv-row"><div class="k">扩展结构路径 / Fresh Path</div><div class="v">${round.created_fresh_structure ? htmlLines([`${pickGroupedText(round.created_fresh_structure, round.created_fresh_structure.structure_id || "-")} (${round.created_fresh_structure.structure_id || "-"}) | ${stText(round.created_fresh_structure.stats)}`]) : "无 / None"}</div></div><div class="kv-row"><div class="k">轮后残余 / Remaining After</div><div class="v">${htmlLines([`${round.remaining_grouped_text_after || listOr(round.remaining_tokens_after, "空 / Empty", " / ")} | ER ${n(round.remaining_total_er_after)} | EV ${n(round.remaining_total_ev_after)}`])}</div></div></div><div class="sub-section"><div class="sub-title">候选结构 / Candidate Structures</div>${rows(a(round.candidate_details).slice(0, 8).map((item) => ({ title: `${pickGroupedText(item, item.structure_id || "-")} | score ${n(item.competition_score ?? item.match_score)}`, desc: [`${item.structure_id || "-"} | mode ${item.match_mode || "-"} | exact ${y(item.exact_match)} | full ${y(item.full_structure_included)}`, `sigma ${n(item.similarity_score)} | match ${n(item.match_score)} | coverage ${n(item.coverage_ratio)} | structure_ratio ${n(item.structure_match_ratio)}`, `runtime ${n(item.runtime_weight)} | entry_runtime ${n(item.entry_runtime_weight)} | depth ${item.chain_depth ?? 0} | anchor ${y(item.contains_anchor)} | eligible ${y(item.eligible)} | owner ${item.owner_structure_id || item.parent_structure_id || "-"}`, `common ${fmtCommon(item.common_part)}`, fmtRetrievalScoreAudit(item, stimulusScoreAuditOptions), fmtRetrievalV2Breakdown(item), stText(item.stats)].filter(Boolean).join("\n") })), "本轮没有候选结构 / No candidates.")}</div></article>`;
  }).join("") : empty("本轮没有刺激级轮次细节 / No stimulus rounds.");

  E.flowTimeline.innerHTML += [
    stepBlock("刺激级查存一体", "刺激级按 anchor 局部组做贪婪链式匹配。", [
      dCard("匹配与切割", [
        card("轮次", stimulusLevel.round_count || 0, `剩余 SA ${stimulusLevel.remaining_stimulus_sa_count || 0}`),
        card("命中结构", a(stimulusLevel.matched_structure_ids).length, listOr(stimulusLevel.matched_structure_ids, "无", ", ")),
        card("新建结构", a(stimulusLevel.new_structure_ids).length, listOr(stimulusLevel.new_structure_ids, "无", ", ")),
        card("索引写入 / 切割", `${stimulusLevel.storage_summary?.written_index_count || 0} / ${stimulusLevel.storage_summary?.cut_count || 0}`, `fallback ${y(stimulusLevel.fallback_used)}`),
      ].join(""), "detail-grid"),
      dCard("逐轮贪婪路径", stimulusBlocksEnhanced),
      dCard("运行态结构/记忆投影", rows(a(stimulusLevel.runtime_projection_structures).map(fmtProjectionCard), "本轮没有运行态结构投影。")),
    ]),
  ].join("");

  E.flowTimeline.innerHTML += [
    showEnergyGraphBlock ? stepBlock("能量图景二代", "默认每个 tick 只推进一轮：同一源做一次 ER 诱发，并让当前 EV 前沿只下传一层。只有把最大轮数调大时，这里才会出现同 tick 的后续重复诱发。", [
      dCard("图景摘要", [
        card("启用", y(induction.energy_graph_v2_enabled), `传播预算 EV ${n(induction.propagated_budget_total_ev)}`),
        card("实际轮次 / 深度", `${induction.energy_graph_round_count_max || 0} / ${induction.energy_graph_depth_max || 0}`, `配置上限 ${energyGraphRoundLimitLabel} | 目标 ${a(induction.induction_targets).length}`),
        card("前沿 / 剪枝", `${induction.energy_graph_frontier_generated_count || 0} / ${induction.energy_graph_frontier_pruned_count || 0}`, `终止于记忆残差 ${induction.energy_graph_terminal_memory_count || 0}`),
        card("根源重复诱发", induction.energy_graph_root_reinduction_count || 0, `总 deltaEV ${n(induction.total_delta_ev)}`),
      ].join(""), "detail-grid"),
      dCard("层级直方图", rows(inductionLayerSummary ? [{ title: "层级分布", desc: inductionLayerSummary }] : [], "本轮没有层级直方图数据。")),
      dCard("逐轮摘要", rows(inductionRoundSummaries.map((row) => ({
        title: `第 ${row.round_index || "-"} 轮`,
        desc:
          `前沿 ${row.frontier_in_count || 0} -> ${row.frontier_out_count || 0} | ` +
          `剪枝 ${row.frontier_pruned_count || 0} | 终止 ${row.frontier_memory_terminal_count || 0} | 根源重诱发 ${row.root_reinduction_count || 0}\n` +
          `frontierEV ${n(row.frontier_budget_ev)} | rootInductionEV ${n(row.root_induction_budget_ev)} | deltaEV ${n(row.round_delta_ev)}`,
      })), "本轮没有逐轮摘要。")),
      dCard("源图详情", rows(a(inductionDebug.source_details).map((source) => ({
        title: `${source.display_text || source.source_structure_id || "-"} | ${source.source_structure_id || "-"}`,
        desc:
          `ER ${n(source.source_er)} | EV ${n(source.source_ev)} | db ${source.pointer_info?.resolved_db_id || "-"} | fallback ${y(source.pointer_info?.used_fallback)}\n` +
          `round ${source.energy_graph_summary?.round_count || 0} | depth ${source.energy_graph_summary?.depth_max || 0} | reinduction ${source.energy_graph_summary?.root_reinduction_count || 0}\n` +
          (a(source.candidate_entries).map((entry) =>
            `${entry.target_display_text || entry.target_structure_id || "-"} | ${entry.mode || "-"} | ${entry.projection_kind || "structure"} | id ${projectionTargetId(entry)} | round ${entry.energy_graph_round || "-"} | depth ${entry.energy_graph_depth || "-"} | from ${entry.frontier_source_kind || "-"} | deltaEV ${n(entry.delta_ev)} | runtime ${n(entry.runtime_weight)}`
          ).join("\n") || "本轮没有候选条目。"),
      })), "本轮没有感应赋能源图详情。")),
    ]) : "",
  ].join("");

  E.flowTimeline.innerHTML += [
    stepBlock("状态池回写与结构投影", "刺激级结束后再统一回写剩余刺激与结构投影。", [
      dCard("回写指标", [
        card("新建 / 更新", `${poolApply.apply_result?.new_item_count || 0} / ${poolApply.apply_result?.updated_item_count || 0}`, `合并 ${poolApply.apply_result?.merged_item_count || 0}`),
        card("状态增量", `ΔER ${n(poolApply.apply_result?.state_delta_summary?.total_delta_er)}`, `ΔEV ${n(poolApply.apply_result?.state_delta_summary?.total_delta_ev)}`),
        card("落地包", poolApply.landed_packet?.display_text || "空", `ER ${n(poolApply.landed_packet?.total_er)} / EV ${n(poolApply.landed_packet?.total_ev)}`),
        card("结构/记忆投影", a(poolApply.runtime_projection).length, `bias ${a(poolApply.bias_projection).length}`),
      ].join(""), "detail-grid"),
      dCard("回写事件", rows(a(poolApply.events).map((event) => ({
        title: `${event.event_type || "event"} · ${event.target_display || event.target_item_id || "-"}`,
        desc: `类型 ${event.target_ref_object_type || "-"} | 原因 ${event.reason || "-"}\nΔER ${n(event.delta?.delta_er)} | ΔEV ${n(event.delta?.delta_ev)} | ΔCP ${n(event.delta?.delta_cp_abs)}`,
      })), "本轮没有额外状态池事件。")),
      dCard("偏置投影", rows(a(poolApply.bias_projection).map(fmtProjectionCard), "本轮没有结构级 bias 投影。")),
      dCard("运行态结构/记忆投影", rows(a(poolApply.runtime_projection).map(fmtProjectionCard), "本轮没有刺激级运行态投影。")),
    ]),

    stepBlock("感应赋能", "默认对状态池内全部有能量对象执行感应赋能；这里只对能量过低、无法形成有效落池的候选目标做剪枝。EV 传播消耗源 EV，ER 诱发不消耗源 ER。", [
      dCard("传播与诱发", [
        card("可用源 / 实际参与", `${inductionSourceSelection.induction_source_available_runtime_count || induction.source_item_count || 0} / ${induction.source_item_count || 0}`, `ST ${inductionSourceSelection.induction_source_selected_st_count || 0} | 非ST ${inductionSourceSelection.induction_source_selected_non_st_count || 0}`),
        card("ER 源 / EV 源", `${inductionErSourceCount} / ${inductionEvSourceCount}`, `ER+EV ${inductionSourceSelection.induction_source_selected_from_er_ev_count || 0} | cap_hit ${y(inductionSourceSelection.induction_source_selection_cap_hit)}`),
        card("命中源 / 无候选", `${inductionSourceHitCount} / ${inductionSourceMissCount}`, `局部目标提示 ${inductionSourceSelection.induction_source_selected_with_local_target_hint_count || 0}`),
        card("EV 传播 / ER 诱发", `${induction.propagated_target_count || 0} / ${induction.induced_target_count || 0}`, `fallback ${y(induction.fallback_used)}`),
        card("总 delta_ev", n(induction.total_delta_ev), `总 ev 消耗 ${n(induction.total_ev_consumed)}`),
        card("结构回写 / 残差对象赋能", `${a(report.induction?.applied_targets).length} / ${memoryActivationApply.applied_count || 0}`, memoryUi.applyNote),
      ].join(""), "detail-grid"),
      dCard("源对象与候选目标", rows(inductionSources.map((source) => ({
        title: `${source.display_text || source.source_structure_id || "-"} · ${source.source_item_id || source.source_structure_id || "-"}`,
        desc: `源类型 ${source.source_ref_object_type || "-"} | 源能量 ER ${n(source.source_er)} | EV ${n(source.source_ev)}\n支持结构 ${a(source.resolved_support_structure_ids || source.support_structure_ids).join(" / ") || "-"}\n局部数据库 ${source.pointer_info?.resolved_db_id || "-"} | fallback ${y(source.pointer_info?.used_fallback)}\n${a(source.candidate_entries).map((entry) => `${entry.target_display_text || entry.target_structure_id || "-"} | ${inductionModeLabel(entry.mode)} | 目标类 ${projectionKindLabel(entry.projection_kind, memoryPathMode)} | id ${projectionTargetId(entry)} | ΔEV ${n(entry.delta_ev)} | runtime ${n(entry.runtime_weight)} | share ${n(entry.normalized_share)} | entries ${entry.entry_count || 0} | W ${n(entry.base_weight)} | G ${n(entry.recent_gain)} | fatigue ${n(entry.fatigue)}`).join("\n") || (source.skipped_reason ? `本轮未执行有效赋能：${source.skipped_reason}` : "该源对象本轮没有命中可赋能目标。")}`,
      })), "本轮没有实际参与的感应源对象。")),
      dCard("赋能回写", rows(a(report.induction?.applied_targets).map(fmtProjectionCard), "本轮没有感应赋能回写目标。")),
      dCard(memoryUi.listTitle, rows(sortMemoryActivations(memoryUi.items, currentMemorySort()).map(fmtMemoryActivationCard), memoryUi.runtimeOnly ? "当前走状态池残差对象主链；这里展示状态池内活跃残差对象视图。" : "本轮没有 MAP 兼容条目。")),
    ]),
  ].join("");

  E.flowTimeline.innerHTML += [
    showMemoryFeedbackBlock ? stepBlock("MAP 兼容反馈（Compat Feedback）", `当前记忆路径：${memoryPathLabel}。这里只有在旧 MAP 兼容支路真实产生回流时才显示；默认的新口径主路径并不依赖这条链路。${memoryRuntimeProjection.enabled ? (memoryRuntimeShadowMode ? "（当前是 shadow 观测态）" : "（当前是主路径，可进入 CAM）") : "（当前未启用运行态投影）"}。`, [
      dCard("兼容反馈概览", [
          card("本轮回流（Applied）", memoryFeedback.applied_count || 0, `刺激流 ${memoryFeedbackStimulusCount} | 结构 ${memoryFeedbackStructureCount}`),
          card("回流能量（Returned Energy）", `ER ${n(memoryFeedback.total_feedback_er)} / EV ${n(memoryFeedback.total_feedback_ev)}`, `总 ${n(memoryFeedback.total_feedback_energy)}`),
          card("回流目标（Targets）", memoryFeedbackTargetCount, "反馈主粒度仍以 SA/ST 为主；EM 是否进入状态池取决于残差记忆对象化开关"),
          card("残差运行态对象投影", memoryRuntimeProjectionSummary.inserted_count || 0, `attempt ${memoryRuntimeProjectionSummary.attempted_count || 0} | shadow ${y(memoryRuntimeShadowMode)}`),
          card("MAP 兼容记录", memoryFeedback.record_result?.recorded_count || 0, `ER ${n(memoryFeedback.record_result?.total_feedback_er)} | EV ${n(memoryFeedback.record_result?.total_feedback_ev)}`),
        ].join(""), "detail-grid"),
        dCard("残差运行态对象投影（Residual Memory Runtime Projection）", rows(memoryRuntimeProjectionItems.map(fmtProjectionCard), "本轮没有残差运行态对象投影记录。")),
        dCard("兼容反馈条目（Compat Feedback Items）", rows(memoryFeedbackItems.map(fmtMemoryFeedbackResult), "本轮没有 MAP 兼容反馈条目。")),
      dCard("MAP 兼容回写记录（MAP Records）", rows(a(memoryFeedback.record_result?.items).map((item) => ({
        title: `${item.display_text || item.memory_id || "-"} | ${item.memory_id || "-"}`,
        desc:
          `当前能量 ER ${n(item.er)} | EV ${n(item.ev)} | 总 ${n(te(item))}\n` +
          `最近兼容回流 ER ${n(item.last_feedback_er)} | EV ${n(item.last_feedback_ev)}\n` +
          `累计兼容回流 ER ${n(item.total_feedback_er)} | EV ${n(item.total_feedback_ev)}\n` +
          `来源记忆（EM）${item.event_summary || item.display_text || "-"}`,
      })), "本轮没有新的 MAP 兼容回写记录。")),
    ]) : "",
  ].join("");

  E.flowTimeline.innerHTML += [
    stepBlock("认知感受系统（CFS 认知感受信号）", "从状态池与注意力记忆体中生成元认知信号（违和感/正确感/期待/压力/置信度等），并写回运行态供下一 tick（节拍）消费。", [
      dCard("认知感受概览（CFS）", [
        card("信号数", cfsSignals.length, `tick（节拍） ${cfs.meta?.tick_number ?? "-"}`),
        card("写回节点", cfsRuntimeNodes.length, `属性绑定 ${cfsAttrBindings.length}`),
      ].join(""), "detail-grid"),
      dCard(
        "运行态认知感受实时状态（绑定属性总量）",
        rows(
          Object.values(finalStateSnapshot?.summary?.bound_attribute_energy_totals || {})
            .filter((row) => String(row?.attribute_name || "").startsWith("cfs_"))
            .sort((l, r) => (+r?.total_energy || 0) - (+l?.total_energy || 0))
            .slice(0, 18)
            .map((row) => ({
              title: `${row.attribute_name || "-"} · 总 ${n(row.total_energy)}`,
              desc: `ER ${n(row.total_er)} | EV ${n(row.total_ev)} | 覆盖对象 ${row.item_count ?? 0} | 属性条目 ${row.attribute_count ?? 0}`,
            })),
          "当前没有运行态绑定属性汇总（bound_attribute_energy_totals）记录。"
        )
      ),
      dCard("认知感受信号（CFS）", rows(cfsSignals.slice().sort((l, r) => (+r?.strength || 0) - (+l?.strength || 0)).slice(0, 16).map((sig) => ({
        title: `${cfsKindLabel(sig.kind)} · ${cfsScopeLabel(sig.scope)} · 强度 ${n(sig.strength)}`,
        desc:
          `目标 ${fmtTargetWithPool(sig.target)}\n` +
          `触发规则 ${fmtRuleRef(sig)}\n` +
          `原因 ${textList(sig.reasons) || "-"}\n` +
          `证据 ${fmtKvInline(sig.evidence || {})}`,
      })), "本轮没有生成认知感受信号。")),
      dCard("写回结果", rows(cfsAttrBindings.slice(0, 16).map((item) => ({
        title: `${item.kind || "-"} -> ${item.target_item_id || "-"}`,
        desc: `属性 ${item.attribute_sa_id || "-"} | 成功 ${y(item.success)} | 代码 ${item.code || "-"}`,
      })), "本轮没有属性绑定写回。")),
    ]),

    stepBlock("先天编码脚本管理器（IESM）", "基于状态窗口与认知感受（CFS）生成‘先天触发源’，并可输出情绪增量（emotion_update）与行动触发（action_trigger）。情绪增量会在下一步 EMgr（情绪管理器）同 tick 生效。", [
      dCard("脚本概览", [
        card("脚本版本", innateScript.active_scripts?.script_version || "-", `启用脚本 ${a(innateScript.active_scripts?.scripts).length}`),
        card("状态窗口检查", a(innateScript.state_window_checks).length, `聚焦触发源 ${focusDirectivesNew.length}`),
        card("CFS 输出（IESM）", innateCfsSignals.length, "规则引擎运行态信号（输入+新生成）"),
        card("情绪更新（emotion_update）", Object.keys(focusData.emotion_updates || {}).length, "本 tick 会被 EMgr 吸收"),
        card("行动触发（action_trigger）", a(focusData.action_triggers).length, "本 tick 会进入 Drive 竞争"),
      ].join(""), "detail-grid"),
      dCard("状态窗口检查", rows(a(innateScript.state_window_checks).map((item) => {
        const stage = item.stage || "-";
        if (item.error) {
          return { title: `${stage}`, desc: `错误 ${item.error}` };
        }
        const triggered = a(item.check?.triggered_scripts);
        const summary = item.packet_summary || {};
        return {
          title: `${stage} · 触发 ${triggered.length}`,
          desc:
            `CP 快速上升 fast_cp_rise ${summary.fast_cp_rise_item_count || 0} | CP 快速下降 fast_cp_drop ${summary.fast_cp_drop_item_count || 0}\n` +
            `${triggered.map((sc) => `脚本 ${sc.script_id || "-"} | 触发 ${sc.trigger || "-"} | 次数 ${sc.trigger_count || 0}`).join("\n") || "无触发脚本。"}`,
        };
      }), "本轮没有窗口检查结果。")),
      dCard("规则引擎输出的认知感受信号（IESM.cfs_signals）", rows(innateCfsSignals.slice().sort((l, r) => (+r?.strength || 0) - (+l?.strength || 0)).slice(0, 16).map((sig) => ({
        title: `${cfsKindLabel(sig.kind)} · ${cfsScopeLabel(sig.scope)} · 强度 ${n(sig.strength)}`,
        desc:
          `目标 ${fmtTargetWithPool(sig.target)}\n` +
          `触发规则 ${fmtRuleRef(sig)}\n` +
          `原因 ${textList(sig.reasons) || "-"}\n` +
          `证据 ${fmtKvInline(sig.evidence || {})}`,
      })), "本轮规则引擎没有输出认知感受信号。")),
      dCard("本轮生成的聚焦触发源（focus_directives）", rows(focusDirectivesNew.slice(0, 16).map((d) => ({
        title: `${d.directive_id || "-"} · ${d.source_kind || "-"} · 强度 ${n(d.strength)}`,
        desc:
          `加成 ${n(d.focus_boost)} | 存活 ttl ${d.ttl_ticks || 0}\n` +
          `目标 ${fmtTargetWithPool({ target_ref_object_id: d.target_ref_object_id, target_ref_object_type: d.target_ref_object_type, target_item_id: d.target_item_id, target_display: d.target_display })}\n` +
          `原因 ${(a(d.reasons)[0] || "-")}`,
      })), "本轮没有生成新的聚焦触发源。")),
      dCard("情绪更新（emotion_update）", kvListHtml(focusData.emotion_updates || {}, { emptyText: "本轮没有情绪通道增量。" })),
      dCard("行动触发（action_trigger）", rows(a(focusData.action_triggers).slice(0, 16).map((item) => ({
        title: `${actionKindTitle(item.action_kind || item.kind || "")} · ${item.action_id || item.id || "-"} · gain ${n(item.gain ?? item.drive_gain)}`,
        desc:
          `阈值 ${n(item.threshold)} | 冷却 ${item.cooldown_ticks ?? 0}\n` +
          `来源规则 ${fmtRuleRef(item)}\n` +
          `参数（params）${fmtKvInline(item.params || {})}`,
      })), "本轮没有行动触发。")),
      dCard("本轮触发的规则（triggered_rules）", rows(a(focusData.triggered_rules).slice(0, 20).map((r) => ({
        title: `${r.rule_title || r.rule_id || "-"} | id=${r.rule_id || "-"} | phase=${r.rule_phase || r.phase || "-"} | pri=${r.rule_priority ?? r.priority ?? "-"}`,
        desc:
          `原因 ${whenReasonsText(r.reasons) || "-"}\n` +
          `命中摘要 ${fmtKvInline(r.matches_summary || {})}`,
      })), "本轮没有任何规则触发。")),
      dCard("审计（IESM）", renderIesmAuditHtml(focusData.audit || {})),
    ]),

    stepBlock("情绪管理器（EMgr）与递质通道（NT）", "维护 NT（递质通道）慢变量并输出调制包；输入来自 CFS + IESM 的 emotion_update（脚本增量）。调制会在下一 tick（节拍）影响注意力/学习/行动风格。", [
      dCard("递质概览（NT）", [
        card("奖励/惩罚（rwd/pun）", `${n(emotion.rwd_pun_snapshot?.rwd)} / ${n(emotion.rwd_pun_snapshot?.pun)}`, `全局衰减（global_decay）${n(emotion.decay?.global_decay_ratio)}`),
        card("通道数", emotionChannelKeys(emotion).length, `tick（节拍）${emotion.audit?.tick_id || report.trace_id || "-"}`),
      ].join(""), "detail-grid"),
      dCard("递质通道（NT，更新后）", renderEmotionNtStateHtml(emotion)),
      dCard("通道说明（NT 通道含义）", rows(Object.entries(emotion.nt_channel_meta || {}).map(([ch, meta]) => ({
        title: `${ntLabel(ch, emotion.nt_channel_labels || {})}`,
        desc: String((meta && typeof meta === "object" ? meta.desc_zh : "") || "-"),
      })), "当前没有通道说明信息。")),
      dCard("本 tick 应用的通道增量（applied deltas）", renderEmotionDeltasHtml(emotion.deltas?.applied || {}, emotion.nt_channel_labels || {})),
      dCard("调制输出（modulation）", renderEmotionModulationHtml(emotion.modulation || {}, emotion.nt_channel_labels || {})),
    ]),

    stepBlock("行动管理模块（Drive 驱动力）", "对候选行动节点更新 Drive（驱动力）并竞争执行；执行时按阈值消耗 Drive（消耗而非清零）。注意：本模块会区分“先天触发（IESM）”与“内驱触发（非 IESM）”，便于审计。", [
      dCard("行动概览", [
        card("触发源", actionTriggers.length, "来自 CFS/IESM/复杂度等"),
        card("执行动作", executedActions.length, executedActions.length ? "已发生 Drive 消耗" : "本轮无执行"),
        card("输出聚焦指令", focusDirectivesOut.length, "下一 tick（节拍）生效"),
        card("输出调制", Object.keys(actionModulationOut || {}).length, `注意力 top_n（attention.top_n）${actionModulationOut?.attention?.top_n ?? "-"}`),
      ].join(""), "detail-grid"),
      dCard("行动器注册表（已注册行动接口）", rows(actionExecutors.map((ex) => ({
        title: `${ex.title_zh || ex.action_kind || "-"} · kind=${ex.action_kind || "-"}`,
        desc: `${ex.desc_zh || "-"}\n参数口径（params_schema）${fmtKvInline(ex.params_schema || {})}\n常见触发来源 ${a(ex.sources_zh).join("，") || "-"}`,
      })), "当前没有行动器注册信息。")),
      dCard("阈值调制（threshold_modulation）", renderThresholdModulationHtml(thresholdMod || {}, emotion.nt_channel_labels || {})),
      dCard("行动学习摘要（action_learning_summary）", renderActionLearningSummaryHtml(actionLearningSummary || {})),
      dCard("执行记录", rows(executedActions.slice(0, 16).map((item) => ({
        title: `${actionKindTitle(item.action_kind || "")} · ${item.action_id || "-"}`,
        desc:
          `drive ${n(item.drive_before)} -> ${n(item.drive_after)} | 消耗 ${n(item.consumed_drive ?? 0)} | 基准阈值 ${n(item.base_threshold)} | 实时阈值 ${n(item.effective_threshold)}（scale ${n(item.threshold_scale)}）\n` +
          `疲劳（fatigue）${n(item.fatigue)} | 本 tick 增益 ${n(item.tick_gain_total)}\n` +
          `目标 ${item.target_display || item.target_ref_object_id || item.target_item_id || "-"}\n` +
`局部塑形 ${formatLocalDriveModulationText(item.local_drive_modulation)}\n` +
          `来源：${item.origin?.passive_iesm ? "被动（先天脚本 IESM）" : ""}${item.origin?.passive_iesm && item.origin?.active_internal ? " + " : ""}${item.origin?.active_internal ? "主动（内驱/非 IESM）" : ""}\n` +
          `触发源（最近）${a(item.trigger_sources).map((s) => fmtActionSourceBrief(s)).join(" / ") || "-"}\n` +
          `本 tick 增益分解 ${fmtKvInline(item.tick_gain_by_source_kind || {})}\n` +
          `产物摘要 focus_directives=${a(item.produced?.focus_directives).length} | modulation_keys=${Object.keys(item.produced?.modulation || {}).length}`,
      })), "本轮没有执行任何动作。")),
      dCard("输出聚焦指令（focus_directives_out）", rows(focusDirectivesOut.slice(0, 16).map((d) => ({
        title: `${d.directive_id || "-"} · ${d.source_kind || "-"} · 强度 ${n(d.strength)}`,
        desc:
          `加成 ${n(d.focus_boost)} | 存活 ttl ${d.ttl_ticks || 0}\n` +
          `目标 ${fmtTargetWithPool({ target_ref_object_id: d.target_ref_object_id, target_ref_object_type: d.target_ref_object_type, target_item_id: d.target_item_id, target_display: d.target_display })}\n` +
          `原因 ${(a(d.reasons)[0] || "-")}`,
      })), "本轮没有输出新的聚焦指令。")),
      dCard("输出调制（modulation_out）", kvListHtml(actionModulationOut || {}, { emptyText: "本轮没有输出调制。" })),
      dCard("节点快照（Drive）", rows(actionNodes.slice(0, 24).map((node) => ({
        title: `${actionKindTitle(node.action_kind || "")} · ${node.action_id || "-"}`,
        desc:
          `drive ${n(node.drive)} | 本轮消耗 ${n(node.tick_consumed_drive_total ?? node.last_consumed_drive ?? 0)} | 基准阈值 ${n(node.base_threshold)} | 实时阈值 ${n(node.effective_threshold)}（scale ${n(node.threshold_scale)}）\n` +
          `目标 ${node.target_display || node.target_ref_object_id || node.target_item_id || "-"}\n` +
`局部塑形 ${formatLocalDriveModulationText(node.local_drive_modulation)}\n` +
          `疲劳（fatigue）${n(node.fatigue)} | 本 tick 增益 ${n(node.tick_gain_total)} | cooldown ${node.cooldown_ticks ?? 0}\n` +
          `last_trigger ${node.last_trigger_tick ?? "-"} | last_update ${node.last_update_tick ?? "-"}`,
      })), "当前没有行动节点。")),
    ]),
  ].join("");

  if (E.recentCycles) {
    E.recentCycles.innerHTML = rows(a(S.d.recent_cycles).map((cycle) => {
      const runtimeOnly = String(cycle.memory_path_mode || "").trim() === "runtime_em_only";
      const processedText = String(cycle.tick_text || cycle.input_text || "").trim() || "空 Tick";
      const submittedText = String(cycle.submitted_text || "").trim();
      return {
        title: `${cycle.trace_id || "-"} · 处理 ${shortInputPreview(processedText)}`,
        desc:
          `${submittedText && submittedText !== processedText ? `提交 ${shortInputPreview(submittedText)} | ` : ""}队列余量 ${cycle.pending_queue_after_tick ?? 0}\n` +
      `记忆体 ${cycle.attention_memory_count || 0} | ${runtimeOnly ? "残差对象赋能" : "MAP兼容赋能"} ${cycle.memory_activation_applied_count || 0} | 路径 ${cycle.memory_path_mode || "-"}\n` +
          `认知拼接（Cognitive Stitching，缩写 CS）候选 ${cycle.cs_candidate_count ?? "-"} | 动作 ${cycle.cs_action_count ?? "-"} | 退化 ${cycle.cs_degenerated_event_count ?? "-"}\n` +
          `刺激级查存轮次 ${cycle.stimulus_rounds ?? "-"} | 结构级查存轮次 ${cycle.structure_rounds ?? "-"}\n` +
          `命中结构 ${fmtRefs(cycle.matched_structure_refs)}\n` +
          `新结构 ${fmtRefs(cycle.new_structure_refs)}\n` +
          `delta_ev ${n(cycle.total_delta_ev)} | ${runtimeOnly ? "residual_runtime_ev" : "memory_pool_ev"} ${n(cycle.memory_activation_total_ev)}`,
      };
    }), "当前没有最近轮次。");
  }
}

function stateView() {
  const snapshot = S.d?.state_snapshot || {};
  const energy = S.d?.state_energy_summary || {};
  const summary = snapshot.summary || {};
  const poolEvToErRatio = Number(energy.total_er || 0) > 0 ? Number(energy.total_ev || 0) / Number(energy.total_er || 1) : 0;
  if (E.stateMeta) {
    E.stateMeta.textContent =
      `对象 ${summary.active_item_count || 0} | ` +
      `实能量（ER）${n(energy.total_er)} | 虚能量（EV）${n(energy.total_ev)} | ` +
      `上下文化对象 ${summary.contextual_item_count || 0} | 残差来源 ${summary.residual_origin_item_count || 0}`;
  }
  if (E.stateCards) {
    E.stateCards.innerHTML = [
      card("活跃对象", summary.active_item_count || 0, `高 ER ${summary.high_er_item_count || 0}`),
      card("高虚能量（EV）", summary.high_ev_item_count || 0, `高认知压（CP）${summary.high_cp_item_count || 0}`),
      card("对象类型", Object.entries(summary.object_type_counts || {}).map(([key, value]) => `${refTypeLabel(key)}:${value}`).join(" | ") || "-", "类型分布"),
      card("总能量", `实ER ${n(energy.total_er)} | 虚EV ${n(energy.total_ev)}`, `认知压 CP ${n(energy.total_cp)} | EV/ER ${n(poolEvToErRatio)}`),
      card("上下文化对象", summary.contextual_item_count || 0, `多级路径 ${summary.multi_context_item_count || 0} | 平均深度 ${n(summary.context_path_depth_mean)}`),
      card("残差来源对象", summary.residual_origin_item_count || 0, "还能追溯到残差链，适合判断当前对象是不是从残差递归长出来的。"),
    ].join("");
  }
  if (E.stateEnergyByType) {
    const auditRows = [
      {
        title: "这些数字怎么读",
        desc:
          "上下文化对象：至少带有一个可追溯的 owner / ref / path。\n" +
          "多级路径对象：路径深度大于 1，通常说明对象已经沿残差链继续下沉或继续展开。",
      },
      {
        title: "当前状态池分布",
        desc:
          `上下文化对象 ${summary.contextual_item_count || 0} / ${summary.active_item_count || 0}\n` +
          `多级路径对象 ${summary.multi_context_item_count || 0} | 平均路径深度 ${n(summary.context_path_depth_mean)}\n` +
          `残差来源对象 ${summary.residual_origin_item_count || 0}`,
      },
      {
        title: "解释建议",
        desc:
          "如果活跃对象很多，但上下文化对象很少，说明系统更多停留在叶子级对象。\n" +
          "如果多级路径对象开始上升，通常表示残差结构正在逐层打开，而不是只停在表层命中。",
      },
    ];
    E.stateEnergyByType.innerHTML = [
      dCard("上下文与残差审计（状态池）", rows(auditRows), "detail-card"),
      dCard("当前显著样本（状态池 Top）", rows(buildContextAuditRows(snapshot.top_items, 8), "当前前排状态池对象里还没有显式上下文/残差链样本。")),
      dCard("按类型能量分布", rows(Object.entries(energy.energy_by_type || {}).map(([key, value]) => ({
        title: refTypeLabel(key),
        desc: `数量 ${value.count || 0} | 实ER ${n(value.total_er)} | 虚EV ${n(value.total_ev)} | CP ${n(value.total_cp)}`,
      })), "当前没有按类型汇总的能量。")),
    ].join("");
  }
  if (E.stateItems) {
    E.stateItems.innerHTML = rows(a(snapshot.top_items).slice(0, 24).map((item) => ({
      title: fmtStateTitle(item),
      desc:
        `对象 ${item.ref_object_id || item.structure_id || item.item_id || "-"} | 实ER ${n(item.er)} | 虚EV ${n(item.ev)} | CP ${n(item.cp_abs)} | 总 ${n(te(item))}\n` +
        `上下文 ${fmtContextSummary(item)}\n` +
        `残差 ${fmtResidualSummary(item)}\n` +
        `结构模式 ${item.structure_sequence_mode || "-"} | GoalB 混合结构 ${y(item.goal_b_mixed_structure)}\n` +
        `疲劳（fatigue）${n(item.fatigue)} | 近因增益（recency）${n(item.recency_gain)} | 更新 ${item.update_count || 0} 次`,
    })), "当前状态池为空。");
  }
}

function hdbView() {
  const report = S.d?.last_report || {};
  const hdb = S.d?.hdb_snapshot || {};
  const summary = hdb.summary || {};
  const memoryUi = buildMemoryUiModel(report, hdb);
  if (E.hdbMeta) {
    E.hdbMeta.textContent =
      `结构（ST）${summary.structure_count || 0} | ` +
      `结构组（SG）${summary.group_count || 0} | ` +
      `情景记忆（EM）${summary.episodic_count || 0} | ` +
      `${memoryUi.summaryLabel}${memoryUi.count} | ` +
      `上下文化结构 ${summary.contextual_structure_count || 0}`;
  }
  if (E.hdbCards) {
    E.hdbCards.innerHTML = [
      card("结构 / 结构组", `${summary.structure_count || 0} / ${summary.group_count || 0}`, `EM ${summary.episodic_count || 0}`),
      card(memoryUi.summaryLabel, memoryUi.count, `ER ${n(memoryUi.totalEr)} | EV ${n(memoryUi.totalEv)} | ${memoryUi.pathLabel}`),
      card("局部数据库", summary.structure_db_count || 0, `问题（Issue）${summary.issue_count || 0}`),
      card("修复（Repair）", summary.active_repair_job_count || 0, "活动修复任务"),
      card("上下文化结构", summary.contextual_structure_count || 0, `多级路径 ${summary.multi_context_structure_count || 0} | 平均深度 ${n(summary.structure_context_path_depth_mean)}`),
      card("同内容多上下文", summary.same_content_multi_context_count || 0, "同一签名在多个上下文 owner 下并存，更贴近“同内容不等于同对象”的理论约束。"),
      card("残差索引", summary.residual_diff_entry_count || 0, `diff 总数 ${summary.diff_entry_count || 0} | 带记忆引用 ${summary.diff_entry_with_memory_ref_count || 0}`),
      card("指针索引", Object.entries(hdb.stats?.pointer_index || {}).map(([key, value]) => `${key}:${value}`).join(" | ") || "-", "指针摘要"),
    ].join("");
  }
  if (E.recentStructures) {
    const structureAuditRows = [
      {
        title: "这些数字怎么读",
        desc:
          "上下文化结构：结构对象携带了 owner / ref / path 这类可追溯语义。\n" +
          "同内容多上下文：同样的签名在多个上下文 owner 下共存，说明系统没有把“同内容但不同语境”的对象粗暴压成一个。",
      },
      {
        title: "当前 HDB 分布",
        desc:
          `上下文化结构 ${summary.contextual_structure_count || 0} / ${summary.structure_count || 0}\n` +
          `多级路径结构 ${summary.multi_context_structure_count || 0} | 平均路径深度 ${n(summary.structure_context_path_depth_mean)}\n` +
          `残差 diff 条目 ${summary.residual_diff_entry_count || 0} / 全部 diff ${summary.diff_entry_count || 0}`,
      },
    ];
    E.recentStructures.innerHTML = [
      dCard("结构上下文审计", rows(structureAuditRows), "detail-card"),
      dCard("最近结构（带上下文说明）", rows(a(hdb.recent_structures).map((item) => ({
        title: `${item.display_text || item.structure_id || "-"} · ${item.structure_id || "-"}`,
        desc:
          `签名（signature）${item.signature || "-"}\n` +
          `上下文 ${fmtContextSummary(item)}\n` +
          `残差 ${fmtResidualSummary(item)}\n` +
          `权重（W）${n(item.base_weight)} | 近因增益（G）${n(item.recent_gain)} | 疲劳（fatigue）${n(item.fatigue)}`,
      })), "当前没有最近结构。")),
      dCard("上下文样本（最近结构 Top）", rows(buildStructureContextRows(hdb.recent_structures, 8), "当前最近结构里还没有显式上下文/残差链样本。")),
    ].join("");
  }
  if (E.recentGroups) {
    E.recentGroups.innerHTML = rows(a(hdb.recent_groups).map((item) => ({
      title: item.group_id || "-",
      desc: `必需结构（required）${fmtRefs(item.required_structures)}\n偏置结构（bias）${fmtRefs(item.bias_structures)}\n能量画像（profile）${fmtKvInline(item.avg_energy_profile || {})}`,
    })), "当前没有最近结构组。");
  }
  if (E.recentEpisodic) {
    E.recentEpisodic.innerHTML = rows(a(hdb.recent_episodic).map((item) => ({
      title: `${item.episodic_id || item.id || "-"} · ${item.event_summary || "-"}`,
      desc: `ST ${fmtRefs(item.structure_ref_items)}\nSG ${a(item.group_ref_items).map((value) => value.group_id || "-").join("，") || "无"}`,
    })), "当前没有最近情景记忆。");
  }
  if (E.memoryActivationList) {
    E.memoryActivationList.innerHTML = rows(
      sortMemoryActivations(memoryUi.items, currentMemorySort()).map(fmtMemoryActivationCard),
      memoryUi.listEmptyText,
    );
  }
  if (E.repairJobs) {
    E.repairJobs.innerHTML = rows(a(hdb.repair_jobs).map((job) => ({
      title: `${job.repair_job_id || "-"} · ${job.status || "-"}`,
      desc: `范围 ${job.scope || "-"} | 目标 ${job.target_id || "全局"}\nprocessed ${job.processed_count || 0} | repaired ${job.repaired_count || 0}`,
    })), "当前没有活动修复任务。");
  }
  if (E.recentIssues) {
    E.recentIssues.innerHTML = rows(a(hdb.recent_issues).map((issue) => ({
      title: `${issue.type || "-"} · ${issue.target_id || "-"}`,
      desc: `suggest ${listOr(issue.repair_suggestion, "-", ", ")}\nmessage ${issue.message || "-"}`,
    })), "当前没有 issue。");
  }
}

function miscLegacyReadOnly() {
  if (E.settingsTabs) {
    E.settingsTabs.innerHTML = rows(Object.entries(S.d?.module_configs || {}).map(([key, value]) => ({
      title: key,
      desc: value.path || "-",
    })), "当前没有模块配置。");
  }
  if (E.settingsPanel) {
    E.settingsPanel.innerHTML = `<section class="detail-card"><h5>配置快照</h5>${kvListHtml(S.d?.module_configs || {}, { emptyText: "无配置快照。" })}</section>`;
  }
}

function misc() {
  const moduleConfigs = S.d?.module_configs || {};
  const activeModule = normalizeSettingsTab();
  if (E.settingsTabs) {
    E.settingsTabs.innerHTML = Object.keys(moduleConfigs).length
      ? Object.entries(moduleConfigs)
          .map(
            ([key, value]) => `<button class="tab-btn settings-tab-btn ${key === activeModule ? "active" : ""}" data-module="${esc(key)}"><strong>${esc(value.title || key)}</strong><span class="muted-inline">${esc(value.path || "-")}</span></button>`,
          )
          .join("")
      : empty("当前没有模块配置。");
  }
  if (E.settingsPanel) {
    E.settingsPanel.innerHTML = activeModule
      ? renderSettingsPanel(activeModule, moduleConfigs[activeModule])
      : empty("当前没有配置内容。");
  }
  if (activeModule) bindSettingsUi(activeModule);
}

async function runCycle() {
  const text = E.inputText?.value ?? "";
  try {
    S.r = (await P("/api/cycle", { text })).data;
    await refreshDashboard(true);
    fb("已执行完整循环。");
  } catch (error) {
    fb(`执行失败: ${error.message}`, true);
  }
}

async function runTicks(count) {
  const total = Math.max(1, +count || 1);
  try {
    S.r = (await P("/api/tick", { count: total })).data;
    await refreshDashboard(true);
    fb(`已执行 ${total} 轮 Tick。`);
  } catch (error) {
    fb(`Tick 失败: ${error.message}`, true);
  }
}

async function act(url, body, message) {
  try {
    S.r = (await P(url, body)).data;
    await refreshDashboard(true);
    fb(message);
    draw();
  } catch (error) {
    fb(`操作失败: ${error.message}`, true);
  }
}

async function idleConsolidate() {
  try {
    fb("正在启动闲时巩固/压缩…");
    const job = (await P("/api/idle_consolidate", { background: true })).data || {};
    S.r = job;
    draw();
    const jobId = String(job.job_id || "").trim();
    if (!jobId) {
      fb("启动失败：未获得 job_id。", true);
      return;
    }
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 450));
      const j = (await G(`/api/idle_consolidate_status?job_id=${encodeURIComponent(jobId)}`)).data || {};
      S.r = j;
      draw();
      const status = String(j.status || "");
      if (status === "completed") {
        fb("闲时巩固/压缩已完成。");
        break;
      }
      if (status === "failed") {
        fb(`闲时巩固/压缩失败: ${String(j.error || "-")}`, true);
        break;
      }
    }
    await refreshDashboard(true);
  } catch (error) {
    fb(`闲时巩固/压缩失败: ${error.message}`, true);
  }
}

function qv(input, fallback) {
  return typeof input === "string" ? input.trim() : String(fallback ?? "").trim();
}

async function qStructure(id) {
  const value = qv(id, E.structureQuery?.value || "");
  if (!value) return fb("请输入结构 ID。", true);
  try {
    S.r = (await G(`/api/structure?structure_id=${encodeURIComponent(value)}`)).data;
    await refreshDashboard(true);
    if (E.structureDetail) E.structureDetail.innerHTML = `<section class="detail-card"><h5>${esc(value)}</h5>${kvListHtml(S.r, { emptyText: "无结构详情。" })}</section>`;
    if (E.actionResult) E.actionResult.textContent = fmtScalarPlain(S.r);
    E.structureDetail?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    fb(`已查询结构 ${value}。`);
  } catch (error) {
    fb(`查询结构失败: ${error.message}`, true);
  }
}

async function qGroup(id) {
  const value = qv(id, E.groupQuery?.value || "");
  if (!value) return fb("请输入结构组 ID。", true);
  try {
    S.r = (await G(`/api/group?group_id=${encodeURIComponent(value)}`)).data;
    await refreshDashboard(true);
    if (E.groupDetail) E.groupDetail.innerHTML = `<section class="detail-card"><h5>${esc(value)}</h5>${kvListHtml(S.r, { emptyText: "无结构组详情。" })}</section>`;
    if (E.actionResult) E.actionResult.textContent = fmtScalarPlain(S.r);
    E.groupDetail?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    fb(`已查询结构组 ${value}。`);
  } catch (error) {
    fb(`查询结构组失败: ${error.message}`, true);
  }
}

async function qEm() {
  const limit = Math.max(1, +E.episodicLimit?.value || 10);
  try {
    S.r = (await G(`/api/episodic?limit=${limit}`)).data;
    await refreshDashboard(true);
    const items = Array.isArray(S.r) ? S.r : a(S.r?.items);
    if (E.episodicDetail) {
      E.episodicDetail.innerHTML = `<section class="detail-card"><h5>最近情景记忆</h5>${rows(
        a(items)
          .slice(0, 24)
          .map((item, idx) => ({
            title: item?.memory_id || item?.event_id || item?.id || `记录 ${idx + 1}`,
            desc: fmtScalarPlain(item),
          })),
        "无情景记忆记录。",
      )}</section>`;
    }
    fb(`已查询最近 ${limit} 条情景记忆。`);
  } catch (error) {
    fb(`查询情景记忆失败: ${error.message}`, true);
  }
}

// =====================================================================
// Innate Rules UI / 先天规则编辑器（Phase A）
// =====================================================================

function deepClone(value) {
  return JSON.parse(JSON.stringify(value ?? null));
}

function rulesDoc() {
  if (!S.innateRulesDoc) S.innateRulesDoc = { rules_schema_version: "1.0", rules_version: "0.0", enabled: true, defaults: {}, rules: [] };
  if (!Array.isArray(S.innateRulesDoc.rules)) S.innateRulesDoc.rules = [];
  return S.innateRulesDoc;
}

async function refreshInnateRules(silent = false) {
  try {
    if (!silent) {
      setIrBusy(true, "innateRulesRefreshBtn", "刷新中…");
      irFb("正在刷新：读取先天规则文件并进行规范化处理…", "busy");
    }
    const data = (await G("/api/innate_rules")).data;
    S.innateRulesBundle = data;
    S.innateRulesDoc = deepClone(data.normalized_doc || {});
    S.innateRulesDirty = false;
    if (!S.innateRulesSelectedId) {
      const first = a(S.innateRulesDoc?.rules)[0];
      S.innateRulesSelectedId = first?.id || null;
    }
    if (E.innateRulesYaml) E.innateRulesYaml.value = data.file_yaml || data.normalized_yaml || "";
    if (!silent) {
      const doc = S.innateRulesDoc || {};
      const ruleCount = a(doc.rules).length;
      const errCount = a(data.errors).length;
      const warnCount = a(data.warnings).length;
      const enabled = Boolean(data.rules_engine_enable) && Boolean(doc.enabled) && errCount === 0;
      // 显示一份“刷新结果快照”，让用户明显感知按钮生效，并便于排错。
      // Show a refresh snapshot so users can immediately see what happened.
      if (E.innateRulesResult) {
        E.innateRulesResult.textContent = irResultText("refresh", {
          code: "OK",
          message: "rules refreshed",
          rules_path: data.rules_path,
          rules_loaded_at_ms: data.rules_loaded_at_ms,
          rules_schema_version: doc.rules_schema_version,
          rules_version: doc.rules_version,
          rule_count: ruleCount,
          engine_enabled: enabled,
          errors: a(data.errors),
          warnings: a(data.warnings),
        });
      }
      const kind = errCount ? "err" : "ok";
      irFb(`已刷新先天规则：规则 ${ruleCount} 条，错误 ${errCount}，警告 ${warnCount}，引擎 ${enabled ? "启用" : "未启用"}。`, kind);
      irSetResultBoxKind(kind);
      irFlashResultBox();
      irFlashFeedback();
      // 让用户“明显看到结果框确实更新了”（对验收更友好）。
      // Help the user notice the result box update (more acceptance-friendly).
      setTimeout(() => E.innateRulesResult?.scrollIntoView?.({ behavior: "smooth", block: "start" }), 0);
      fb("已刷新先天规则。");
    }
    draw();
  } catch (error) {
    if (!silent) {
      irFb(`刷新失败：${error.message}`, "err");
      fb(`刷新先天规则失败: ${error.message}`, true);
    }
  } finally {
    if (!silent) setIrBusy(false);
  }
}

function renderInnateRules() {
  if (!E.innateRulesList || !E.innateRulesEditor || !E.innateRulesMeta) return;
  const bundle = S.innateRulesBundle;
  const doc = rulesDoc();
  if (!bundle) {
    E.innateRulesMeta.textContent = "规则尚未加载。";
    E.innateRulesList.innerHTML = empty("正在加载规则…");
    E.innateRulesEditor.innerHTML = empty("请选择规则。");
    return;
  }

  const errCount = a(bundle.errors).length;
  const warnCount = a(bundle.warnings).length;
  const ruleCount = a(doc.rules).length;
  const enabled = Boolean(bundle.rules_engine_enable) && Boolean(doc.enabled) && errCount === 0;
  const rulesPath = bundle.rules_path || "-";
  const rulesVer = String(doc.rules_version || "-");
  const schemaVer = String(doc.rules_schema_version || "-");
  const loadedAt = bundle.rules_loaded_at_ms ? tm(bundle.rules_loaded_at_ms) : "-";
  E.innateRulesMeta.textContent =
    `规则文件：${rulesPath} | 版本：${rulesVer} | 规范：${schemaVer} | 加载：${loadedAt} | ` +
    `引擎：${enabled ? "启用" : "未启用"} | 规则数：${ruleCount} | 错误：${errCount} | 警告：${warnCount}` +
    (S.innateRulesDirty ? " | 草稿：已修改（未保存）" : "");

  // ---- List ----
  E.innateRulesList.innerHTML = ruleCount
    ? a(doc.rules)
        .map((rule) => {
          const active = rule?.id && rule.id === S.innateRulesSelectedId;
          const on = Boolean(rule?.enabled);
          const whenText = summarizeWhen(rule?.when);
          const thenText = summarizeThen(rule?.then);
          const chips = [
            `<span class="chip ${on ? "" : "warn"}">${on ? "启用" : "禁用"}</span>`,
            `<span class="chip">优先级 ${rule?.priority ?? 0}</span>`,
            rule?.cooldown_ticks ? `<span class="chip warn">冷却 ${rule.cooldown_ticks} tick</span>` : `<span class="chip">无冷却</span>`,
          ].join("");
          return `<article class="mini-row rule-row ${active ? "active" : ""}" data-rule-id="${esc(rule?.id || "")}">
            <div class="title">${esc(rule?.title || rule?.id || "-")}</div>
            <div class="desc">规则ID ${esc(rule?.id || "-")}\n触发 ${esc(whenText)}\n动作 ${esc(thenText)}</div>
            <div class="chips">${chips}</div>
          </article>`;
        })
        .join("")
    : empty("当前没有规则。");

  document.querySelectorAll(".rule-row").forEach((node) => {
    node.addEventListener("click", () => {
      S.innateRulesSelectedId = node.dataset.ruleId || null;
      draw();
    });
  });

  // ---- Editor ----
  const selected = a(doc.rules).find((r) => r?.id === S.innateRulesSelectedId) || null;
  E.innateRulesEditor.innerHTML = selected ? renderRuleEditor(selected) : empty("请选择一条规则进行编辑。");
  bindRuleEditor(selected);
}

function summarizeWhen(whenExpr) {
  if (!whenExpr || typeof whenExpr !== "object") return "-";
  const key = Object.keys(whenExpr)[0];
  const val = whenExpr[key];
  if (key === "cfs") {
    const kinds = a(val?.kinds).join(",") || "*";
    const min = val?.min_strength ?? "-";
    return `认知感受（CFS） kinds=[${kinds}] 最小强度>=${min}`;
  }
  if (key === "state_window") {
    return `状态窗口 stage=${val?.stage ?? "any"} 认知压强（CP）快速上升>=${val?.fast_cp_rise_min ?? 0} 快速下降>=${val?.fast_cp_drop_min ?? 0}`;
  }
  if (key === "timer") {
    return `定时器 every_n_ticks=${val?.every_n_ticks ?? "-"} at_tick=${val?.at_tick ?? "-"}`;
  }
  if (key === "metric") {
    const preset = String(val?.preset || "");
    const metric = String(val?.metric || "");
    const channel = String(val?.channel || "");
    const mode = String(val?.mode || "state");
    const op = String(val?.op || ">=");
    const selector = val?.selector || {};
    const selMode = String(selector?.mode || "");
    const sel =
      selMode === "specific_ref"
        ? ` target=${String(selector?.ref_object_type || "")}:${String(selector?.ref_object_id || "")}`
        : selMode === "specific_item"
          ? ` item_id=${String(selector?.item_id || "")}`
          : selMode === "contains_text"
            ? ` contains="${String(selector?.contains_text || "")}"`
            : selMode === "top_n"
              ? ` top_n=${String(selector?.top_n || "")}`
              : selMode
                ? ` selector=${selMode}`
                : "";
    const cmp =
      op === "between"
        ? ` between[${val?.min ?? "-"}, ${val?.max ?? "-"}]`
        : op === "exists"
          ? " exists"
            : op === "changed"
              ? " changed"
              : ` ${op} ${val?.value ?? "-"}`;
    const left = preset ? `preset=${preset}${channel ? ` channel=${channel}` : ""}` : `metric=${metric}`;
    return `指标（metric） ${left} mode=${mode}${cmp}${sel}`;
  }
  if (key === "any" || key === "all") {
    return `${key === "any" ? "任一（any）" : "同时（all）"}(${a(val).map(summarizeWhen).join(" | ")})`;
  }
  if (key === "not") return `not(${summarizeWhen(val)})`;
  return key;
}

function summarizeThen(actions) {
  const list = a(actions);
  if (!list.length) return "-";
  return list
    .map((a0) => {
      if (!a0 || typeof a0 !== "object") return "?";
      const key = Object.keys(a0)[0];
      if (key === "cfs_emit") return `认知感受生成（cfs_emit）:${a0.cfs_emit?.kind || "-"}`;
      if (key === "focus") return "注意力聚焦（focus）";
      if (key === "emit_script") return `触发记录（emit_script）:${a0.emit_script?.script_id || "-"}`;
      if (key === "emotion_update") return "情绪更新（emotion_update）";
      if (key === "action_trigger") return "行动触发（action_trigger）";
      if (key === "pool_energy") return "对对象赋能量（ER/EV）（pool_energy）";
      if (key === "pool_bind_attribute") return "绑定属性（pool_bind_attribute）";
      if (key === "delay") return "延时（delay）";
      if (key === "branch") return "分支（branch）";
      if (key === "log") return "日志（log）";
      return key;
    })
    .join("，");
}

function renderRuleEditor(rule) {
  const whenModel = editorWhenModel(rule.when);
  const actions = a(rule.then);
  const actionRows = actions.length
    ? actions
        .map((act, idx) => renderActionRow(act, idx))
        .join("")
    : `<div class="empty-state">当前没有动作，请添加。</div>`;

  const clauseRows = whenModel.clauses.length
    ? whenModel.clauses.map((clause, idx) => renderClauseRow(clause, idx)).join("")
    : `<div class="empty-state">当前没有触发条件，请添加。</div>`;

  return `<section class="detail-card">
    <div class="section-head">
      <h5>${esc(rule.title || rule.id || "规则")}</h5>
      <div class="toolbar">
        <button class="ghost" id="irGraphOpenBtn" type="button">图形编排（可视化）</button>
        <button class="ghost danger" id="irDeleteRuleBtn" type="button">删除规则</button>
      </div>
    </div>
    <div class="settings-grid">
      <article class="setting-item">
        <label>规则ID（id）</label>
        <input class="ir-basic" data-field="id" type="text" value="${esc(rule.id || "")}" />
        <div class="soft-note">建议稳定：a-z 开头，仅含 a-z0-9_。</div>
      </article>
      <article class="setting-item">
        <label>标题（title）</label>
        <input class="ir-basic" data-field="title" type="text" value="${esc(rule.title || "")}" />
      </article>
      <article class="setting-item">
        <label>启用（enabled）</label>
        <label class="toggle-row"><input class="ir-basic" data-field="enabled" type="checkbox" ${rule.enabled ? "checked" : ""} /><span>启用</span></label>
      </article>
      <article class="setting-item">
        <label>优先级（priority）</label>
        <input class="ir-basic" data-field="priority" type="number" step="1" value="${esc(String(rule.priority ?? 50))}" />
      </article>
      <article class="setting-item">
        <label>冷却 tick（时间步，cooldown_ticks）</label>
        <input class="ir-basic" data-field="cooldown_ticks" type="number" step="1" value="${esc(String(rule.cooldown_ticks ?? 0))}" />
      </article>
      <article class="setting-item">
        <label>规则阶段（phase）</label>
        <select class="ir-basic" data-field="phase">
          <option value="directives" ${String(rule.phase || "directives") === "directives" ? "selected" : ""}>指令输出（directives）</option>
          <option value="cfs" ${String(rule.phase || "") === "cfs" ? "selected" : ""}>认知感受生成（cfs）</option>
        </select>
        <div class="soft-note">说明：phase=cfs 的规则会在本 tick 更早执行，用于生成认知感受信号；phase=directives 负责输出聚焦/情绪/行动触发等指令。</div>
      </article>
      <article class="setting-item">
        <label>备注（note）</label>
        <textarea class="ir-basic" data-field="note">${esc(rule.note || "")}</textarea>
      </article>
    </div>

    <div class="settings-group">
      <div class="section-head">
        <h4>触发条件（when）</h4>
        <div class="toolbar">
          <select class="ir-when-mode" data-field="mode">
            <option value="any" ${whenModel.mode === "any" ? "selected" : ""}>任一触发（any）</option>
            <option value="all" ${whenModel.mode === "all" ? "selected" : ""}>同时满足（all）</option>
          </select>
          <button class="ghost" id="irAddClauseBtn" type="button">添加条件</button>
        </div>
      </div>
      <div class="stack">${clauseRows}</div>
    </div>

    <div class="settings-group">
      <div class="section-head">
        <h4>执行动作（then）</h4>
        <div class="toolbar">
          <button class="ghost" id="irAddActionCfsEmitBtn" type="button">+ 认知感受生成（cfs_emit）</button>
          <button class="ghost" id="irAddActionFocusBtn" type="button">+ 聚焦指令（focus）</button>
          <button class="ghost" id="irAddActionEmitBtn" type="button">+ 触发记录（emit_script）</button>
          <button class="ghost" id="irAddActionEmotionBtn" type="button">+ 情绪更新（emotion_update）</button>
          <button class="ghost" id="irAddActionTriggerBtn" type="button">+ 行动触发（action_trigger）</button>
          <button class="ghost" id="irAddActionPoolEnergyBtn" type="button">+ 对对象赋能量（ER/EV）（pool_energy）</button>
          <button class="ghost" id="irAddActionBindAttrBtn" type="button">+ 绑定属性（pool_bind_attribute）</button>
          <button class="ghost" id="irAddActionDelayBtn" type="button">+ 延时（delay）</button>
          <button class="ghost" id="irAddActionBranchBtn" type="button">+ 分支（branch）</button>
          <button class="ghost" id="irAddActionLogBtn" type="button">+ 日志（log）</button>
        </div>
      </div>
      <div class="stack">${actionRows}</div>
    </div>
  </section>`;
}

function editorWhenModel(whenExpr) {
  // 规范化编辑器模型（Canonical editor model）：{ mode: "any"|"all", clauses: [ {type, spec} ] }
  const empty = { mode: "any", clauses: [] };
  if (!whenExpr || typeof whenExpr !== "object") return empty;
  const key = Object.keys(whenExpr)[0];
  const val = whenExpr[key];
  if (key === "any" || key === "all") {
    const clauses = a(val).map((child) => unwrapClause(child)).filter(Boolean);
    return { mode: key, clauses };
  }
  return { mode: "all", clauses: [unwrapClause(whenExpr)].filter(Boolean) };
}

function unwrapClause(expr) {
  if (!expr || typeof expr !== "object") return null;
  const key = Object.keys(expr)[0];
  const val = expr[key] || {};
  if (key === "cfs") return { type: "cfs", spec: { kinds: a(val.kinds), min_strength: val.min_strength ?? "", max_strength: val.max_strength ?? "" } };
  if (key === "state_window") return { type: "state_window", spec: { stage: val.stage ?? "any", fast_cp_rise_min: val.fast_cp_rise_min ?? "", fast_cp_drop_min: val.fast_cp_drop_min ?? "", min_candidate_count: val.min_candidate_count ?? "", candidate_hint_any: a(val.candidate_hint_any) } };
  if (key === "timer") return { type: "timer", spec: { every_n_ticks: val.every_n_ticks ?? "", at_tick: val.at_tick ?? "" } };
  if (key === "metric") {
    const sel = val.selector && typeof val.selector === "object" ? deepClone(val.selector) : { mode: "all" };
    return {
      type: "metric",
      spec: {
        preset: val.preset ?? "",
        metric: val.metric ?? "",
        channel: val.channel ?? "",
        mode: val.mode ?? "state",
        op: val.op ?? ">=",
        value: val.value ?? "",
        min: val.min ?? "",
        max: val.max ?? "",
        window_ticks: val.window_ticks ?? "",
        match_policy: val.match_policy ?? "any",
        capture_as: val.capture_as ?? "",
        epsilon: val.epsilon ?? "",
        prev_gate: val.prev_gate && typeof val.prev_gate === "object" ? deepClone(val.prev_gate) : {},
        note: val.note ?? "",
        selector: sel,
      },
    };
  }
  return null;
}

function renderClauseRow(clause, idx) {
  const type = clause.type;
  const spec = clause.spec || {};
  const head = `<div class="section-head">
    <h5>条件 ${idx + 1}</h5>
    <div class="toolbar">
      <select class="ir-clause" data-idx="${idx}" data-field="type">
        <option value="cfs" ${type === "cfs" ? "selected" : ""}>认知感受（CFS）</option>
        <option value="state_window" ${type === "state_window" ? "selected" : ""}>状态窗口</option>
        <option value="timer" ${type === "timer" ? "selected" : ""}>定时器</option>
        <option value="metric" ${type === "metric" ? "selected" : ""}>指标条件（metric）</option>
      </select>
      <button class="ghost danger ir-remove-clause" data-idx="${idx}" type="button">移除</button>
    </div>
  </div>`;

  if (type === "metric") {
    const presets = a(S.innateRulesBundle?.metric_presets);
    const groups = {};
    for (const p of presets) {
      if (!p || typeof p !== "object") continue;
      const g = String(p.group_zh || "其他");
      if (!groups[g]) groups[g] = [];
      groups[g].push(p);
    }
    const groupNames = Object.keys(groups).sort();
    const selectedPreset = presets.find((p) => String(p?.preset || "") === String(spec.preset || "")) || null;
    const needsChannel =
      Boolean(selectedPreset?.needs_channel) || String(selectedPreset?.metric || "").includes("{channel}");
    const presetOptions =
      `<option value="">（不使用预设，手动填写 metric）</option>` +
      (groupNames.length
        ? groupNames
            .map((g) => {
              const opts = a(groups[g])
                .map((p) => {
                  const name = String(p.preset || "");
                  const label = String(p.label_zh || name);
                  const selected = String(spec.preset || "") === name ? "selected" : "";
                  return `<option value="${esc(name)}" ${selected}>${esc(label)}（${esc(name)}）</option>`;
                })
                .join("");
              return `<optgroup label="${esc(g)}">${opts}</optgroup>`;
            })
            .join("")
        : `<optgroup label="常用（内置）">
            <option value="got_er" ${String(spec.preset || "") === "got_er" ? "selected" : ""}>获得实能量（got_er）</option>
            <option value="got_ev" ${String(spec.preset || "") === "got_ev" ? "selected" : ""}>获得虚能量（got_ev）</option>
            <option value="cp_state" ${String(spec.preset || "") === "cp_state" ? "selected" : ""}>认知压状态（cp_state）</option>
            <option value="reward_state" ${String(spec.preset || "") === "reward_state" ? "selected" : ""}>奖励信号状态（reward_state）</option>
          </optgroup>`);

    const sel = spec.selector && typeof spec.selector === "object" ? spec.selector : {};
    const selMode = String(sel.mode || "all");
    const pg = spec.prev_gate && typeof spec.prev_gate === "object" ? spec.prev_gate : {};
    const channelRow = needsChannel
      ? `<article class="setting-item">
          <label>情绪递质通道（channel，必填）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="channel" type="text" value="${esc(String(spec.channel ?? ""))}" />
          <div class="soft-note">示例：<code>DA</code>/<code>多巴胺</code>/<code>COR</code>/<code>皮质醇</code>。该预设会映射到 <code>emotion.nt.{channel}</code>。</div>
        </article>`
      : "";
    return `<section class="detail-card nested">${head}
      <div class="settings-grid">
        <article class="setting-item">
          <label>指标预设（preset，推荐）</label>
          <select class="ir-clause" data-idx="${idx}" data-field="preset">${presetOptions}</select>
          <div class="soft-note">中文别名也可：例如 <code>__获得实能量__</code>。保存时会归一化为稳定 key（例如 got_er）。</div>
        </article>
        ${channelRow}
        <article class="setting-item">
          <label>指标路径（metric，选填/高级）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="metric" type="text" value="${esc(String(spec.metric ?? ""))}" />
          <div class="soft-note">示例：<code>item.er</code> / <code>pool.total_er</code> / <code>emotion.nt.DA</code> / <code>emotion.nt.多巴胺</code> / <code>retrieval.stimulus.match_scores</code></div>
        </article>
        <article class="setting-item">
          <label>取值方式（mode）</label>
          <select class="ir-clause" data-idx="${idx}" data-field="mode">
            <option value="state" ${String(spec.mode || "state") === "state" ? "selected" : ""}>状态（state，当前值）</option>
            <option value="delta" ${String(spec.mode || "") === "delta" ? "selected" : ""}>变化量（delta，近 1 tick）</option>
            <option value="avg_rate" ${String(spec.mode || "") === "avg_rate" ? "selected" : ""}>变化率（avg_rate，近 N tick 平均）</option>
          </select>
        </article>
        <article class="setting-item">
          <label>比较符（op）</label>
          <select class="ir-clause" data-idx="${idx}" data-field="op">
            <option value=">=" ${String(spec.op || ">=") === ">=" ? "selected" : ""}>&gt;=</option>
            <option value=">" ${String(spec.op || "") === ">" ? "selected" : ""}>&gt;</option>
            <option value="<=" ${String(spec.op || "") === "<=" ? "selected" : ""}>&lt;=</option>
            <option value="<" ${String(spec.op || "") === "<" ? "selected" : ""}>&lt;</option>
            <option value="==" ${String(spec.op || "") === "==" ? "selected" : ""}>=</option>
            <option value="!=" ${String(spec.op || "") === "!=" ? "selected" : ""}>!=</option>
            <option value="between" ${String(spec.op || "") === "between" ? "selected" : ""}>between（区间）</option>
            <option value="exists" ${String(spec.op || "") === "exists" ? "selected" : ""}>exists（存在即可）</option>
            <option value="changed" ${String(spec.op || "") === "changed" ? "selected" : ""}>changed（变化了）</option>
          </select>
        </article>
        <article class="setting-item">
          <label>阈值（value，可用模板 {{{var}}}）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="value" type="text" value="${esc(String(spec.value ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>区间最小（min，between 用）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="min" type="text" value="${esc(String(spec.min ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>区间最大（max，between 用）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="max" type="text" value="${esc(String(spec.max ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>窗口 tick（window_ticks，avg_rate 用）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="window_ticks" type="number" step="1" value="${esc(String(spec.window_ticks ?? ""))}" />
          <div class="soft-note">建议 3~4。</div>
        </article>
        <article class="setting-item">
          <label>匹配策略（match_policy，item.* 用）</label>
          <select class="ir-clause" data-idx="${idx}" data-field="match_policy">
            <option value="any" ${String(spec.match_policy || "any") === "any" ? "selected" : ""}>任一命中（any）</option>
            <option value="all" ${String(spec.match_policy || "") === "all" ? "selected" : ""}>全部命中（all）</option>
          </select>
        </article>
        <article class="setting-item">
          <label>变量捕获（capture_as，可选）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="capture_as" type="text" value="${esc(String(spec.capture_as ?? ""))}" />
          <div class="soft-note">命中后可在动作里用 <code>{{{变量名}}}</code> 引用数值；若命中的是 item.*，还会提供 <code>{{{变量名}_item_id}} / {{{变量名}_ref_object_id}} / {{{变量名}_ref_object_type}}</code> 便于把后续动作绑定到同一对象。</div>
        </article>
        <article class="setting-item">
          <label>比较精度（epsilon，可选）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="epsilon" type="number" step="any" value="${esc(String(spec.epsilon ?? ""))}" />
          <div class="soft-note">用于 <code>==</code> / <code>!=</code> 等比较的容差；一般保持默认即可。</div>
        </article>
        <article class="setting-item">
          <label>上一 tick 门控（prev_gate.op，可选）</label>
          <select class="ir-clause" data-idx="${idx}" data-field="prev_gate_op">
            <option value="" ${String(pg.op || "") === "" ? "selected" : ""}>（不启用 prev_gate）</option>
            <option value=">=" ${String(pg.op || "") === ">=" ? "selected" : ""}>&gt;=</option>
            <option value=">" ${String(pg.op || "") === ">" ? "selected" : ""}>&gt;</option>
            <option value="<=" ${String(pg.op || "") === "<=" ? "selected" : ""}>&lt;=</option>
            <option value="<" ${String(pg.op || "") === "<" ? "selected" : ""}>&lt;</option>
            <option value="==" ${String(pg.op || "") === "==" ? "selected" : ""}>=</option>
            <option value="!=" ${String(pg.op || "") === "!=" ? "selected" : ""}>!=</option>
            <option value="between" ${String(pg.op || "") === "between" ? "selected" : ""}>between（区间）</option>
            <option value="exists" ${String(pg.op || "") === "exists" ? "selected" : ""}>exists（存在即可）</option>
            <option value="changed" ${String(pg.op || "") === "changed" ? "selected" : ""}>changed（变化了）</option>
          </select>
          <div class="soft-note">含义：要求“上一 tick 的同一指标值”也满足一个额外条件（用于表达“先处于违和，再下降才算正确事件”等约束）。</div>
        </article>
        <article class="setting-item">
          <label>prev_gate.value（上一 tick 阈值）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="prev_gate_value" type="text" value="${esc(String(pg.value ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>prev_gate.min（between 用）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="prev_gate_min" type="text" value="${esc(String(pg.min ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>prev_gate.max（between 用）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="prev_gate_max" type="text" value="${esc(String(pg.max ?? ""))}" />
        </article>
      </div>

      <div class="settings-group">
        <div class="section-head"><h5>对象选择器（selector，可选，用于 item.* 或 match_scores）</h5></div>
        <div class="settings-grid">
          <article class="setting-item">
            <label>选择模式（selector.mode）</label>
            <select class="ir-clause" data-idx="${idx}" data-field="selector_mode">
              <option value="all" ${selMode === "all" ? "selected" : ""}>全部对象（all）</option>
              <option value="specific_ref" ${selMode === "specific_ref" ? "selected" : ""}>特定对象（specific_ref）</option>
              <option value="specific_item" ${selMode === "specific_item" ? "selected" : ""}>特定条目（specific_item）</option>
              <option value="contains_text" ${selMode === "contains_text" ? "selected" : ""}>包含特征/文本（contains_text）</option>
              <option value="top_n" ${selMode === "top_n" ? "selected" : ""}>能量 Top-N（top_n）</option>
            </select>
            <div class="soft-note">contains_text 会匹配 display/详情/属性/特征/运行态属性展示。</div>
          </article>
          <article class="setting-item"><label>ref_object_id（specific_ref 用）</label><input class="ir-clause" data-idx="${idx}" data-field="selector_ref_object_id" type="text" value="${esc(String(sel.ref_object_id ?? ""))}" /></article>
          <article class="setting-item"><label>ref_object_type（可选）</label><input class="ir-clause" data-idx="${idx}" data-field="selector_ref_object_type" type="text" value="${esc(String(sel.ref_object_type ?? ""))}" /></article>
          <article class="setting-item"><label>item_id（specific_item 用）</label><input class="ir-clause" data-idx="${idx}" data-field="selector_item_id" type="text" value="${esc(String(sel.item_id ?? ""))}" /></article>
          <article class="setting-item"><label>contains_text（contains_text 用）</label><input class="ir-clause" data-idx="${idx}" data-field="selector_contains_text" type="text" value="${esc(String(sel.contains_text ?? ""))}" /></article>
          <article class="setting-item"><label>top_n（top_n 用）</label><input class="ir-clause" data-idx="${idx}" data-field="selector_top_n" type="number" step="1" value="${esc(String(sel.top_n ?? ""))}" /></article>
          <article class="setting-item"><label>ref_object_types（逗号，可选过滤）</label><input class="ir-clause" data-idx="${idx}" data-field="selector_ref_object_types" type="text" value="${esc(a(sel.ref_object_types).join(','))}" /></article>
        </div>
      </div>
    </section>`;
  }

  if (type === "cfs") {
    return `<section class="detail-card nested">${head}
      <div class="settings-grid">
        <article class="setting-item">
          <label>信号类型（kinds，逗号分隔）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="kinds" type="text" value="${esc(a(spec.kinds).join(","))}" />
        </article>
        <article class="setting-item">
          <label>最小强度（min_strength）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="min_strength" type="number" step="any" value="${esc(String(spec.min_strength ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>最大强度（max_strength，可选）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="max_strength" type="number" step="any" value="${esc(String(spec.max_strength ?? ""))}" />
        </article>
      </div>
    </section>`;
  }

  if (type === "state_window") {
    return `<section class="detail-card nested">${head}
      <div class="settings-grid">
        <article class="setting-item">
          <label>阶段（stage）</label>
          <select class="ir-clause" data-idx="${idx}" data-field="stage">
            <option value="any" ${String(spec.stage || "any") === "any" ? "selected" : ""}>任意窗口（any）</option>
            <option value="maintenance" ${String(spec.stage || "") === "maintenance" ? "selected" : ""}>维护窗口（maintenance）</option>
            <option value="pool_apply" ${String(spec.stage || "") === "pool_apply" ? "selected" : ""}>回写窗口（pool_apply）</option>
          </select>
        </article>
        <article class="setting-item">
          <label>认知压强（CP）快速上升次数 >=（fast_cp_rise_min）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="fast_cp_rise_min" type="number" step="1" value="${esc(String(spec.fast_cp_rise_min ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>认知压强（CP）快速下降次数 >=（fast_cp_drop_min）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="fast_cp_drop_min" type="number" step="1" value="${esc(String(spec.fast_cp_drop_min ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>候选数量 >=（min_candidate_count）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="min_candidate_count" type="number" step="1" value="${esc(String(spec.min_candidate_count ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>候选 hint（candidate_hint_any，逗号）</label>
          <input class="ir-clause" data-idx="${idx}" data-field="candidate_hint_any" type="text" value="${esc(a(spec.candidate_hint_any).join(","))}" />
        </article>
      </div>
    </section>`;
  }

  return `<section class="detail-card nested">${head}
    <div class="settings-grid">
      <article class="setting-item">
        <label>每 N tick 触发（every_n_ticks）</label>
        <input class="ir-clause" data-idx="${idx}" data-field="every_n_ticks" type="number" step="1" value="${esc(String(spec.every_n_ticks ?? ""))}" />
      </article>
      <article class="setting-item">
        <label>指定 tick（at_tick，可选）</label>
        <input class="ir-clause" data-idx="${idx}" data-field="at_tick" type="number" step="1" value="${esc(String(spec.at_tick ?? ""))}" />
      </article>
    </div>
  </section>`;
}

function renderActionRow(action, idx) {
  if (!action || typeof action !== "object") return empty("动作格式错误。");
  const key = Object.keys(action)[0];
  const val = action[key] || {};
  const head = `<div class="section-head">
    <h5>动作 ${idx + 1}</h5>
    <div class="toolbar">
      <select class="ir-action" data-idx="${idx}" data-field="type">
        <option value="cfs_emit" ${key === "cfs_emit" ? "selected" : ""}>认知感受生成（cfs_emit）</option>
        <option value="focus" ${key === "focus" ? "selected" : ""}>聚焦指令（focus）</option>
        <option value="emit_script" ${key === "emit_script" ? "selected" : ""}>触发记录（emit_script）</option>
        <option value="emotion_update" ${key === "emotion_update" ? "selected" : ""}>情绪更新（emotion_update）</option>
        <option value="action_trigger" ${key === "action_trigger" ? "selected" : ""}>行动触发（action_trigger）</option>
        <option value="pool_energy" ${key === "pool_energy" ? "selected" : ""}>对对象赋能量（ER/EV）（pool_energy）</option>
        <option value="pool_bind_attribute" ${key === "pool_bind_attribute" ? "selected" : ""}>绑定属性（pool_bind_attribute）</option>
        <option value="delay" ${key === "delay" ? "selected" : ""}>延时（delay）</option>
        <option value="branch" ${key === "branch" ? "selected" : ""}>分支（branch）</option>
        <option value="log" ${key === "log" ? "selected" : ""}>日志（log）</option>
      </select>
      <button class="ghost danger ir-remove-action" data-idx="${idx}" type="button">移除</button>
    </div>
  </div>`;

  if (key === "cfs_emit") {
    const safe = val && typeof val === "object" ? val : {};
    const strength = safe.strength && typeof safe.strength === "object" ? safe.strength : (safe.strength ?? safe.value ?? {});
    const strengthPolicy = String((strength || {}).policy || "linear_clamp");
    const target = safe.target && typeof safe.target === "object" ? safe.target : {};
    const targetFrom = String(target.from || "match");
    const bind = safe.bind_attribute && typeof safe.bind_attribute === "object" ? safe.bind_attribute : null;
    const bindEnabled = bind !== null;

    // strength.policy 的不同策略对应的参数不同。这里做“按策略展示”，避免用户被一堆无关字段淹没。
    // Different strength policies have different knobs; show only what matters for better UX.
    const strengthExtraHtml = (() => {
      if (strengthPolicy === "verify_mix") {
        return `
        <article class="setting-item">
          <label>verify_mix.part（输出哪一侧）</label>
          <select class="ir-action" data-idx="${idx}" data-field="strength_part">
            <option value="verified" ${String((strength || {}).part || "verified") === "verified" ? "selected" : ""}>验证（verified，偏“实”）</option>
            <option value="unverified" ${String((strength || {}).part || "") === "unverified" ? "selected" : ""}>不验（unverified，偏“虚”）</option>
          </select>
          <div class="soft-note">说明：verify_mix 会同时用于“期待验证/期待不验”等成对信号，两条强度之和≈基础强度。</div>
        </article>
        <article class="setting-item"><label>pred_var（预测量变量名）</label><input class="ir-action" data-idx="${idx}" data-field="strength_pred_var" type="text" value="${esc(String((strength || {}).pred_var ?? ""))}" /><small>通常是上一步 metric.capture_as 捕获的 EV，例如 <code>expect_pred_ev</code>。</small></article>
        <article class="setting-item"><label>actual_var（实际量变量名）</label><input class="ir-action" data-idx="${idx}" data-field="strength_actual_var" type="text" value="${esc(String((strength || {}).actual_var ?? ""))}" /><small>通常是 delay 后采样的 ER 变化率/变化量，例如 <code>expect_er_rate</code>。</small></article>
        <article class="setting-item"><label>pred_scale / actual_scale（量纲缩放）</label><input class="ir-action" data-idx="${idx}" data-field="strength_pred_scale" type="number" step="any" value="${esc(String((strength || {}).pred_scale ?? 1.0))}" /><input class="ir-action" data-idx="${idx}" data-field="strength_actual_scale" type="number" step="any" value="${esc(String((strength || {}).actual_scale ?? 1.0))}" /><small>常见用法：actual_scale=window_ticks（把 avg_rate 近似换算为窗口总量）。</small></article>
        <article class="setting-item"><label>gamma（对抗“果断度”）</label><input class="ir-action" data-idx="${idx}" data-field="strength_gamma" type="number" step="any" value="${esc(String((strength || {}).gamma ?? 1.0))}" /><small>gamma&gt;1 更偏二极管，gamma&lt;1 更柔和；建议 0.7~2.0。</small></article>
        <article class="setting-item"><label>eps（数值稳定项）</label><input class="ir-action" data-idx="${idx}" data-field="strength_eps" type="number" step="any" value="${esc(String((strength || {}).eps ?? 1e-6))}" /></article>
        `;
      }
      if (strengthPolicy === "scale_offset") {
        return `<article class="setting-item"><label>scale_offset 参数 scale/offset</label><input class="ir-action" data-idx="${idx}" data-field="strength_scale" type="number" step="any" value="${esc(String((strength || {}).scale ?? 1.0))}" /><input class="ir-action" data-idx="${idx}" data-field="strength_offset" type="number" step="any" value="${esc(String((strength || {}).offset ?? 0.0))}" /></article>`;
      }
      // Default: linear_clamp
      return `
        <article class="setting-item"><label>linear_clamp 输入范围 min/max</label><input class="ir-action" data-idx="${idx}" data-field="strength_min" type="number" step="any" value="${esc(String((strength || {}).min ?? 0.0))}" /><input class="ir-action" data-idx="${idx}" data-field="strength_max" type="number" step="any" value="${esc(String((strength || {}).max ?? 1.0))}" /></article>
        <article class="setting-item"><label>linear_clamp 输出范围 out_min/out_max</label><input class="ir-action" data-idx="${idx}" data-field="strength_out_min" type="number" step="any" value="${esc(String((strength || {}).out_min ?? 0.0))}" /><input class="ir-action" data-idx="${idx}" data-field="strength_out_max" type="number" step="any" value="${esc(String((strength || {}).out_max ?? 1.0))}" /></article>
      `;
    })();

    const strengthInvertHtml = strengthPolicy === "linear_clamp"
      ? `<label class="toggle-row"><input class="ir-action" data-idx="${idx}" data-field="strength_invert" type="checkbox" ${(strength || {}).invert ? "checked" : ""} /><span>invert（输出 1-x，仅 linear_clamp 生效）</span></label>`
      : ``;
    return `<section class="detail-card nested">${head}
      <div class="settings-grid">
        <article class="setting-item">
          <label>感受类型（kind，必填）</label>
          <input class="ir-action" data-idx="${idx}" data-field="kind" type="text" value="${esc(String(safe.kind ?? safe.cfs_kind ?? ""))}" />
          <div class="soft-note">示例：dissonance（违和感）/ correct_event（正确事件）/ expectation（期待）/ pressure（压力）/ grasp（把握感/置信度）等。</div>
        </article>
        <article class="setting-item">
          <label>作用域（scope）</label>
          <select class="ir-action" data-idx="${idx}" data-field="scope">
            <option value="object" ${String(safe.scope || "object") === "object" ? "selected" : ""}>对象级（object，需要目标对象）</option>
            <option value="global" ${String(safe.scope || "") === "global" ? "selected" : ""}>全局（global，不绑定目标）</option>
          </select>
        </article>
        <article class="setting-item">
          <label>来源（from）</label>
          <select class="ir-action" data-idx="${idx}" data-field="from">
            <option value="metric_matches" ${String(safe.from || "metric_matches") === "metric_matches" ? "selected" : ""}>来自命中的指标对象（metric_matches）</option>
            <option value="cfs_matches" ${String(safe.from || "") === "cfs_matches" ? "selected" : ""}>来自命中的认知感受对象（cfs_matches）</option>
            <option value="single" ${String(safe.from || "") === "single" ? "selected" : ""}>单条（single，不依赖命中记录）</option>
          </select>
          <div class="soft-note">提示：from=metric_matches/cfs_matches 时可在 strength 里使用 match_value / match_item_id 等变量口径。</div>
        </article>
        <article class="setting-item">
          <label>最多生成条数（max_signals，可选）</label>
          <input class="ir-action" data-idx="${idx}" data-field="max_signals" type="number" step="1" value="${esc(String(safe.max_signals ?? safe.emit_limit ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>最小强度（min_strength，可选）</label>
          <input class="ir-action" data-idx="${idx}" data-field="min_strength" type="number" step="any" value="${esc(String(safe.min_strength ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>变量捕获（capture_as，可选）</label>
          <input class="ir-action" data-idx="${idx}" data-field="capture_as" type="text" value="${esc(String(safe.capture_as ?? ""))}" />
          <div class="soft-note">说明：可把本次计算得到的 strength 写入变量，供同一条规则后续动作使用（例如延时验证）。</div>
        </article>

        <article class="setting-item">
          <label>强度映射（strength.policy）</label>
          <select class="ir-action" data-idx="${idx}" data-field="strength_policy">
            <option value="linear_clamp" ${strengthPolicy === "linear_clamp" ? "selected" : ""}>线性钳制（linear_clamp）</option>
            <option value="scale_offset" ${strengthPolicy === "scale_offset" ? "selected" : ""}>比例偏移（scale_offset）</option>
            <option value="verify_mix" ${strengthPolicy === "verify_mix" ? "selected" : ""}>渐变验证混合（verify_mix）</option>
          </select>
          <div class="soft-note">说明：strength 最终会钳制到 0~1，保证可审计与安全。</div>
        </article>
        <article class="setting-item"><label>strength.from（来源变量名）</label><input class="ir-action" data-idx="${idx}" data-field="strength_from" type="text" value="${esc(String((strength || {}).from ?? "match_value"))}" /><small>常用：match_value（默认）或某个变量名；当 from="var" 时请填写 strength.var。</small></article>
        <article class="setting-item"><label>strength.var（变量名，from=var 时用）</label><input class="ir-action" data-idx="${idx}" data-field="strength_var" type="text" value="${esc(String((strength || {}).var ?? ""))}" /></article>
        <article class="setting-item">
          <label>strength.abs</label>
          <label class="toggle-row"><input class="ir-action" data-idx="${idx}" data-field="strength_abs" type="checkbox" ${(strength || {}).abs ? "checked" : ""} /><span>abs（先取绝对值）</span></label>
          ${strengthInvertHtml}
        </article>
        ${strengthExtraHtml}

        <article class="setting-item">
          <label>目标选择（target.from，可选）</label>
          <select class="ir-action" data-idx="${idx}" data-field="target_from">
            <option value="match" ${targetFrom === "match" ? "selected" : ""}>来自命中对象（match，默认）</option>
            <option value="specific_ref" ${targetFrom === "specific_ref" ? "selected" : ""}>特定对象（specific_ref）</option>
            <option value="specific_item" ${targetFrom === "specific_item" ? "selected" : ""}>特定条目（specific_item）</option>
          </select>
          <div class="soft-note">默认不填：对象级信号会自动绑定到 match_* 的目标对象。</div>
        </article>
        <article class="setting-item"><label>target.ref_object_id（specific_ref 用）</label><input class="ir-action" data-idx="${idx}" data-field="target_ref_object_id" type="text" value="${esc(String(target.ref_object_id ?? ""))}" /></article>
        <article class="setting-item"><label>target.ref_object_type（specific_ref 用）</label><input class="ir-action" data-idx="${idx}" data-field="target_ref_object_type" type="text" value="${esc(String(target.ref_object_type ?? ""))}" /></article>
        <article class="setting-item"><label>target.item_id（specific_item 用）</label><input class="ir-action" data-idx="${idx}" data-field="target_item_id" type="text" value="${esc(String(target.item_id ?? ""))}" /></article>
        <article class="setting-item"><label>target.display（可选）</label><input class="ir-action" data-idx="${idx}" data-field="target_display" type="text" value="${esc(String(target.display ?? ""))}" /></article>

        <article class="setting-item">
          <label>绑定为属性（bind_attribute，可选）</label>
          <label class="toggle-row"><input class="ir-action" data-idx="${idx}" data-field="bindattr_enabled" type="checkbox" ${bindEnabled ? "checked" : ""} /><span>把该感受作为属性刺激元绑定到目标对象</span></label>
          <small>说明：这是“绑定约束信息”，默认不会把 SA/CSA 作为独立对象写入状态池（避免噪音）。</small>
        </article>
        <article class="setting-item"><label>attribute_name（属性名）</label><input class="ir-action" data-idx="${idx}" data-field="bindattr_attribute_name" type="text" value="${esc(String((bind || {}).attribute_name ?? ""))}" /></article>
        <article class="setting-item">
          <label>value_from（取值来源）</label>
          <select class="ir-action" data-idx="${idx}" data-field="bindattr_value_from">
            <option value="strength" ${String((bind || {}).value_from || "strength") === "strength" ? "selected" : ""}>strength（使用计算后的强度）</option>
            <option value="match_value" ${String((bind || {}).value_from || "") === "match_value" ? "selected" : ""}>match_value（使用命中值）</option>
          </select>
        </article>
        <article class="setting-item"><label>display（展示文本，可用模板 {{{strength}}}）</label><input class="ir-action" data-idx="${idx}" data-field="bindattr_display" type="text" value="${esc(String((bind || {}).display ?? ""))}" /></article>
        <article class="setting-item"><label>raw（原始文本，可选）</label><input class="ir-action" data-idx="${idx}" data-field="bindattr_raw" type="text" value="${esc(String((bind || {}).raw ?? ""))}" /></article>
        <article class="setting-item">
          <label>value_type / modality</label>
          <select class="ir-action" data-idx="${idx}" data-field="bindattr_value_type">
            <option value="numerical" ${String((bind || {}).value_type || "numerical") === "numerical" ? "selected" : ""}>数值（numerical）</option>
            <option value="discrete" ${String((bind || {}).value_type || "") === "discrete" ? "selected" : ""}>离散（discrete）</option>
          </select>
          <select class="ir-action" data-idx="${idx}" data-field="bindattr_modality">
            <option value="internal" ${String((bind || {}).modality || "internal") === "internal" ? "selected" : ""}>内部（internal）</option>
            <option value="external" ${String((bind || {}).modality || "") === "external" ? "selected" : ""}>外部（external）</option>
          </select>
        </article>
        <article class="setting-item"><label>er / ev（可选，属性能量）</label><input class="ir-action" data-idx="${idx}" data-field="bindattr_er" type="number" step="any" value="${esc(String((bind || {}).er ?? 0.0))}" /><input class="ir-action" data-idx="${idx}" data-field="bindattr_ev" type="number" step="any" value="${esc(String((bind || {}).ev ?? 0.0))}" /></article>
        <article class="setting-item"><label>reason（原因，可选）</label><input class="ir-action" data-idx="${idx}" data-field="bindattr_reason" type="text" value="${esc(String((bind || {}).reason ?? ""))}" /></article>
      </div>
      <div class="soft-note">提示：cfs_emit 会把信号加入“本 tick 运行态 CFS 列表”，供同 tick 后续规则、EMgr（情绪递质）、Action/Drive（行动模块）消费。</div>
    </section>`;
  }

  if (key === "focus") {
    return `<section class="detail-card nested">${head}
      <div class="settings-grid">
        <article class="setting-item">
          <label>来源（from）</label>
          <select class="ir-action" data-idx="${idx}" data-field="from">
            <option value="cfs_matches" ${String(val.from || "cfs_matches") === "cfs_matches" ? "selected" : ""}>认知感受命中（cfs_matches）</option>
            <option value="state_window_candidates" ${String(val.from || "") === "state_window_candidates" ? "selected" : ""}>状态窗口候选（state_window_candidates）</option>
          </select>
        </article>
        <article class="setting-item">
          <label>匹配策略（match_policy）</label>
          <select class="ir-action" data-idx="${idx}" data-field="match_policy">
            <option value="all" ${String(val.match_policy || "all") === "all" ? "selected" : ""}>全部匹配（all）</option>
            <option value="strongest" ${String(val.match_policy || "") === "strongest" ? "selected" : ""}>取最强（strongest）</option>
            <option value="first" ${String(val.match_policy || "") === "first" ? "selected" : ""}>取第一个（first）</option>
          </select>
        </article>
        <article class="setting-item">
          <label>存活 tick（ttl_ticks）</label>
          <input class="ir-action" data-idx="${idx}" data-field="ttl_ticks" type="number" step="1" value="${esc(String(val.ttl_ticks ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>聚焦加成（focus_boost）</label>
          <input class="ir-action" data-idx="${idx}" data-field="focus_boost" type="number" step="any" value="${esc(String(val.focus_boost ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>去重键（deduplicate_by）</label>
          <select class="ir-action" data-idx="${idx}" data-field="deduplicate_by">
            <option value="target_ref_object_id" ${String(val.deduplicate_by || "target_ref_object_id") === "target_ref_object_id" ? "selected" : ""}>按目标对象 ID（target_ref_object_id）</option>
            <option value="target_item_id" ${String(val.deduplicate_by || "") === "target_item_id" ? "selected" : ""}>按目标条目 ID（target_item_id）</option>
          </select>
        </article>
        <article class="setting-item">
          <label>最多生成条数（max_directives，可选）</label>
          <input class="ir-action" data-idx="${idx}" data-field="max_directives" type="number" step="1" value="${esc(String(val.max_directives ?? ""))}" />
        </article>
      </div>
    </section>`;
  }

  if (key === "emit_script") {
    return `<section class="detail-card nested">${head}
      <div class="settings-grid">
        <article class="setting-item"><label>脚本ID（script_id）</label><input class="ir-action" data-idx="${idx}" data-field="script_id" type="text" value="${esc(String(val.script_id || ""))}" /></article>
        <article class="setting-item"><label>脚本类型（script_kind）</label><input class="ir-action" data-idx="${idx}" data-field="script_kind" type="text" value="${esc(String(val.script_kind || "window_trigger"))}" /></article>
        <article class="setting-item"><label>优先级（priority）</label><input class="ir-action" data-idx="${idx}" data-field="priority" type="number" step="1" value="${esc(String(val.priority ?? 50))}" /></article>
        <article class="setting-item"><label>触发标签（trigger）</label><input class="ir-action" data-idx="${idx}" data-field="trigger" type="text" value="${esc(String(val.trigger || ""))}" /></article>
      </div>
    </section>`;
  }

  if (key === "emotion_update") {
    const safe = val && typeof val === "object" ? val : {};
    return `<section class="detail-card nested">${head}
      <div class="settings-grid">
        <article class="setting-item">
          <label>通道增量（每行一个通道）</label>
          <div class="soft-note">支持缩写或中文名；数值可为负；可用模板（例如 {{{var}}}）。</div>
          <div class="ir-kv-list">
            ${Object.entries(safe).filter(([k]) => String(k || "").trim()).map(([k, v], r) => `<div class="ir-kv-row" data-row="${r}">
              <input class="ir-action ir-kv-key" data-idx="${idx}" data-field="eu_key" data-row="${r}" data-old-key="${esc(String(k))}" type="text" value="${esc(String(k))}" placeholder="通道名，例如 DA/多巴胺/COR" />
              <input class="ir-action ir-kv-val" data-idx="${idx}" data-field="eu_val" data-row="${r}" type="text" value="${esc(String(v ?? ""))}" placeholder="增量，例如 0.2 或 -0.1 或 {{{var}}}" />
              <button class="ghost danger ir-kv-remove" data-action="eu_remove" data-idx="${idx}" data-row="${r}" type="button">移除</button>
            </div>`).join("") || `<div class="empty-state">当前没有任何通道增量。点击下方「添加通道」开始。</div>`}
          </div>
          <div class="toolbar" style="margin-top:10px;">
            <button class="ghost ir-kv-add" data-action="eu_add" data-idx="${idx}" type="button">+ 添加通道</button>
          </div>
        </article>
      </div>
    </section>`;
  }

  if (key === "action_trigger") {
    const safe = val && typeof val === "object" ? val : {};
    return `<section class="detail-card nested">${head}
      <div class="settings-grid">
        <article class="setting-item">
          <label>行动ID（action_id，必填）</label>
          <input class="ir-action" data-idx="${idx}" data-field="action_id" type="text" value="${esc(String(safe.action_id ?? safe.id ?? ""))}" />
          <div class="soft-note">建议稳定命名，用于行动节点去重与审计。</div>
        </article>
        <article class="setting-item">
          <label>行动类型（action_kind，例如 attention_focus / recall / custom）</label>
          <input class="ir-action" data-idx="${idx}" data-field="action_kind" type="text" value="${esc(String(safe.action_kind ?? safe.kind ?? "custom"))}" />
        </article>
        <article class="setting-item">
          <label>展开来源（from，选填）</label>
          <select class="ir-action" data-idx="${idx}" data-field="from">
            <option value="" ${String(safe.from || "") === "" ? "selected" : ""}>单条触发（不展开）</option>
            <option value="cfs_matches" ${String(safe.from || "") === "cfs_matches" ? "selected" : ""}>对命中的认知感受对象展开（cfs_matches）</option>
            <option value="metric_matches" ${String(safe.from || "") === "metric_matches" ? "selected" : ""}>对命中的指标对象展开（metric_matches）</option>
          </select>
          <div class="soft-note">提示：展开后，一条规则可生成多条行动触发。可在 action_id/params 里使用模板变量：<code>{{{match_ref_object_id}}}</code> / <code>{{{match_item_id}}}</code> / <code>{{{match_value}}}</code>。</div>
        </article>
        <article class="setting-item">
          <label>展开策略（match_policy，选填）</label>
          <select class="ir-action" data-idx="${idx}" data-field="match_policy">
            <option value="all" ${String(safe.match_policy || "all") === "all" ? "selected" : ""}>全部（all）</option>
            <option value="strongest" ${String(safe.match_policy || "") === "strongest" ? "selected" : ""}>最强一个（strongest）</option>
            <option value="first" ${String(safe.match_policy || "") === "first" ? "selected" : ""}>第一个（first）</option>
          </select>
        </article>
        <article class="setting-item">
          <label>最多生成条数（max_triggers，选填）</label>
          <input class="ir-action" data-idx="${idx}" data-field="max_triggers" type="number" step="1" value="${esc(String(safe.max_triggers ?? safe.max ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>驱动力增益（gain 或 drive_gain，可用模板 {{{var}}}）</label>
          <input class="ir-action" data-idx="${idx}" data-field="gain" type="text" value="${esc(String(safe.gain ?? safe.drive_gain ?? 0))}" />
          <div class="soft-note">提示：支持直接数值（例如 0.4），也支持模板（例如 <code>{{{match_value}}}</code>）。</div>
        </article>
        <article class="setting-item">
          <label>阈值（threshold，drive>=threshold 才会尝试执行，可用模板 {{{var}}}）</label>
          <input class="ir-action" data-idx="${idx}" data-field="threshold" type="text" value="${esc(String(safe.threshold ?? 1.0))}" />
        </article>
        <article class="setting-item">
          <label>冷却 tick（cooldown_ticks）</label>
          <input class="ir-action" data-idx="${idx}" data-field="cooldown_ticks" type="number" step="1" value="${esc(String(safe.cooldown_ticks ?? 0))}" />
        </article>
        <article class="setting-item">
          <label>参数（params，可选）</label>
          <div class="soft-note">建议优先用“键值对”编辑，避免写 JSON。对于 attention_focus：只要 params 包含 target_* 字段，行动模块会自动补齐 focus_directive。</div>
          <div class="toolbar">
            <button class="ghost" data-action="at_params_fill_focus" data-idx="${idx}" type="button">填入: 注意力聚焦 target_* + strength</button>
            <button class="ghost" data-action="at_params_fill_recall" data-idx="${idx}" type="button">填入: 回忆 trigger_kind/strength</button>
          </div>
          <div class="ir-kv-list" style="margin-top:10px;">
            ${Object.entries(safe.params && typeof safe.params === "object" ? safe.params : {}).filter(([k]) => String(k || "").trim()).map(([k, v], r) => `<div class="ir-kv-row" data-row="${r}">
              <input class="ir-action ir-kv-key" data-idx="${idx}" data-field="at_param_key" data-row="${r}" data-old-key="${esc(String(k))}" type="text" value="${esc(String(k))}" placeholder="参数名，例如 target_ref_object_id" />
              <input class="ir-action ir-kv-val" data-idx="${idx}" data-field="at_param_val" data-row="${r}" type="text" value="${esc(String(v ?? ""))}" placeholder="参数值，可用模板 {{{var}}}" />
              <button class="ghost danger ir-kv-remove" data-action="at_param_remove" data-idx="${idx}" data-row="${r}" type="button">移除</button>
            </div>`).join("") || `<div class="empty-state">当前没有 params。点击下方按钮添加。</div>`}
          </div>
          <div class="toolbar" style="margin-top:10px;">
            <button class="ghost ir-kv-add" data-action="at_param_add" data-idx="${idx}" type="button">+ 添加参数</button>
          </div>
        </article>
      </div>
      <div class="soft-note">注意：原型阶段行动模块仅内置执行少数 action_kind；未知 kind 会被保留为节点但不会执行（安全）。</div>
    </section>`;
  }

  if (key === "pool_energy") {
    const safe = val && typeof val === "object" ? val : {};
    const sel = safe.selector && typeof safe.selector === "object" ? safe.selector : {};
    const selMode = String(sel.mode || "all");
    return `<section class="detail-card nested">${head}
      <div class="settings-grid">
        <article class="setting-item">
          <label>目标选择（selector.mode）</label>
          <select class="ir-action" data-idx="${idx}" data-field="selector_mode">
            <option value="all" ${selMode === "all" ? "selected" : ""}>全部对象（all）</option>
            <option value="specific_ref" ${selMode === "specific_ref" ? "selected" : ""}>特定对象（specific_ref）</option>
            <option value="specific_item" ${selMode === "specific_item" ? "selected" : ""}>特定条目（specific_item）</option>
            <option value="contains_text" ${selMode === "contains_text" ? "selected" : ""}>包含特征/文本（contains_text）</option>
            <option value="top_n" ${selMode === "top_n" ? "selected" : ""}>能量 Top-N（top_n）</option>
          </select>
          <div class="soft-note">提示：contains_text 会匹配 display/详情/属性/特征/运行态属性展示。</div>
        </article>
        <article class="setting-item"><label>ref_object_id（specific_ref 用）</label><input class="ir-action" data-idx="${idx}" data-field="selector_ref_object_id" type="text" value="${esc(String(sel.ref_object_id ?? ""))}" /></article>
        <article class="setting-item"><label>ref_object_type（可选）</label><input class="ir-action" data-idx="${idx}" data-field="selector_ref_object_type" type="text" value="${esc(String(sel.ref_object_type ?? ""))}" /></article>
        <article class="setting-item"><label>item_id（specific_item 用）</label><input class="ir-action" data-idx="${idx}" data-field="selector_item_id" type="text" value="${esc(String(sel.item_id ?? ""))}" /></article>
        <article class="setting-item"><label>contains_text（contains_text 用）</label><input class="ir-action" data-idx="${idx}" data-field="selector_contains_text" type="text" value="${esc(String(sel.contains_text ?? ""))}" /></article>
        <article class="setting-item"><label>top_n（top_n 用）</label><input class="ir-action" data-idx="${idx}" data-field="selector_top_n" type="number" step="1" value="${esc(String(sel.top_n ?? ""))}" /></article>
        <article class="setting-item"><label>ref_object_types（逗号，可选过滤）</label><input class="ir-action" data-idx="${idx}" data-field="selector_ref_object_types" type="text" value="${esc(a(sel.ref_object_types).join(','))}" /></article>

        <article class="setting-item">
          <label>实能量增量（delta_er，可用模板 {{{var}}}，可为负）</label>
          <input class="ir-action" data-idx="${idx}" data-field="delta_er" type="text" value="${esc(String(safe.delta_er ?? safe.er ?? 0))}" />
        </article>
        <article class="setting-item">
          <label>虚能量增量（delta_ev，可用模板 {{{var}}}，可为负）</label>
          <input class="ir-action" data-idx="${idx}" data-field="delta_ev" type="text" value="${esc(String(safe.delta_ev ?? safe.ev ?? 0))}" />
        </article>
        <article class="setting-item">
          <label>缺失时创建（create_if_missing）</label>
          <label class="toggle-row"><input class="ir-action" data-idx="${idx}" data-field="create_if_missing" type="checkbox" ${safe.create_if_missing ? "checked" : ""} /><span>创建</span></label>
          <div class="soft-note">仅对 specific_ref 生效；且只有增量为正时才会创建（安全）。</div>
        </article>
        <article class="setting-item"><label>创建对象类型（create_ref_object_type，例如 sa/st）</label><input class="ir-action" data-idx="${idx}" data-field="create_ref_object_type" type="text" value="${esc(String(safe.create_ref_object_type ?? ""))}" /></article>
        <article class="setting-item"><label>创建展示（create_display，可选）</label><input class="ir-action" data-idx="${idx}" data-field="create_display" type="text" value="${esc(String(safe.create_display ?? ""))}" /></article>
        <article class="setting-item"><label>原因（reason，可选）</label><input class="ir-action" data-idx="${idx}" data-field="reason" type="text" value="${esc(String(safe.reason ?? ""))}" /></article>
      </div>
      <div class="soft-note">说明：赋能会通过观测台的“安全执行器”落地到状态池（SP），不会在规则引擎里直接修改状态池。</div>
    </section>`;
  }

  if (key === "pool_bind_attribute") {
    const safe = val && typeof val === "object" ? val : {};
    const sel = safe.selector && typeof safe.selector === "object" ? safe.selector : {};
    const selMode = String(sel.mode || "all");
    const attr = safe.attribute && typeof safe.attribute === "object" ? safe.attribute : {};
    return `<section class="detail-card nested">${head}
      <div class="settings-grid">
        <article class="setting-item">
          <label>目标选择（selector.mode）</label>
          <select class="ir-action" data-idx="${idx}" data-field="selector_mode">
            <option value="all" ${selMode === "all" ? "selected" : ""}>全部对象（all）</option>
            <option value="specific_ref" ${selMode === "specific_ref" ? "selected" : ""}>特定对象（specific_ref）</option>
            <option value="specific_item" ${selMode === "specific_item" ? "selected" : ""}>特定条目（specific_item）</option>
            <option value="contains_text" ${selMode === "contains_text" ? "selected" : ""}>包含特征/文本（contains_text）</option>
            <option value="top_n" ${selMode === "top_n" ? "selected" : ""}>能量 Top-N（top_n）</option>
          </select>
        </article>
        <article class="setting-item"><label>ref_object_id（specific_ref 用）</label><input class="ir-action" data-idx="${idx}" data-field="selector_ref_object_id" type="text" value="${esc(String(sel.ref_object_id ?? ""))}" /></article>
        <article class="setting-item"><label>ref_object_type（可选）</label><input class="ir-action" data-idx="${idx}" data-field="selector_ref_object_type" type="text" value="${esc(String(sel.ref_object_type ?? ""))}" /></article>
        <article class="setting-item"><label>item_id（specific_item 用）</label><input class="ir-action" data-idx="${idx}" data-field="selector_item_id" type="text" value="${esc(String(sel.item_id ?? ""))}" /></article>
        <article class="setting-item"><label>contains_text（contains_text 用）</label><input class="ir-action" data-idx="${idx}" data-field="selector_contains_text" type="text" value="${esc(String(sel.contains_text ?? ""))}" /></article>
        <article class="setting-item"><label>top_n（top_n 用）</label><input class="ir-action" data-idx="${idx}" data-field="selector_top_n" type="number" step="1" value="${esc(String(sel.top_n ?? ""))}" /></article>
        <article class="setting-item"><label>ref_object_types（逗号，可选过滤）</label><input class="ir-action" data-idx="${idx}" data-field="selector_ref_object_types" type="text" value="${esc(a(sel.ref_object_types).join(','))}" /></article>

        <article class="setting-item"><label>属性名（attribute.attribute_name）</label><input class="ir-action" data-idx="${idx}" data-field="attr_name" type="text" value="${esc(String(attr.attribute_name ?? ""))}" /></article>
        <article class="setting-item"><label>属性值（attribute.attribute_value，可选）</label><input class="ir-action" data-idx="${idx}" data-field="attr_value" type="text" value="${esc(String(attr.attribute_value ?? ""))}" /></article>
        <article class="setting-item"><label>原始文本（attribute.raw，可选）</label><input class="ir-action" data-idx="${idx}" data-field="attr_raw" type="text" value="${esc(String(attr.raw ?? ""))}" /></article>
        <article class="setting-item"><label>展示文本（attribute.display，可选）</label><input class="ir-action" data-idx="${idx}" data-field="attr_display" type="text" value="${esc(String(attr.display ?? ""))}" /></article>
        <article class="setting-item">
          <label>值类型（attribute.value_type）</label>
          <select class="ir-action" data-idx="${idx}" data-field="attr_value_type">
            <option value="discrete" ${String(attr.value_type || "discrete") === "discrete" ? "selected" : ""}>离散（discrete）</option>
            <option value="numerical" ${String(attr.value_type || "") === "numerical" ? "selected" : ""}>数值（numerical）</option>
          </select>
        </article>
        <article class="setting-item"><label>模态（attribute.modality，例如 internal/external）</label><input class="ir-action" data-idx="${idx}" data-field="attr_modality" type="text" value="${esc(String(attr.modality ?? "internal"))}" /></article>
        <article class="setting-item"><label>属性实能量（attribute.er，可用模板）</label><input class="ir-action" data-idx="${idx}" data-field="attr_er" type="text" value="${esc(String(attr.er ?? 0))}" /></article>
        <article class="setting-item"><label>属性虚能量（attribute.ev，可用模板）</label><input class="ir-action" data-idx="${idx}" data-field="attr_ev" type="text" value="${esc(String(attr.ev ?? 0))}" /></article>
        <article class="setting-item"><label>原因（reason，可选）</label><input class="ir-action" data-idx="${idx}" data-field="reason" type="text" value="${esc(String(safe.reason ?? ""))}" /></article>
      </div>
      <div class="soft-note">说明：属性刺激元不会作为独立对象写入状态池（避免 SA/CSA 噪音），而是以“运行态绑定属性”折叠在锚点对象快照中。</div>
    </section>`;
  }

  if (key === "delay") {
    const safe = val && typeof val === "object" ? val : {};
    if (!Array.isArray(safe.then)) safe.then = [];
    return `<section class="detail-card nested">${head}
      <div class="settings-grid">
        <article class="setting-item"><label>延时 tick（ticks）</label><input class="ir-action" data-idx="${idx}" data-field="ticks" type="number" step="1" value="${esc(String(safe.ticks ?? 1))}" /></article>
      </div>
      <div class="sub-section">
        <div class="sub-title">延时后动作列表（then）</div>
        <div class="soft-note">这里可以直接添加/删除/编辑“延时后子动作”，无需手写 YAML/JSON。</div>
        <div class="ir-flow-editor" data-flow-root="delay" data-aidx="${idx}">
          ${_irFlowRenderActionList(a(safe.then), "then", 0)}
        </div>
      </div>
    </section>`;
  }

  if (key === "branch") {
    const safe = val && typeof val === "object" ? val : {};
    const when = safe.when && typeof safe.when === "object" ? safe.when : {};
    const metric = when.metric && typeof when.metric === "object" ? when.metric : {};
    const sel = metric.selector && typeof metric.selector === "object" ? metric.selector : {};
    const selMode = String(sel.mode || "all");
    const presetOptions = _irFlowMetricPresetOptionsHtml(metric.preset || "");
    // Normalize nested lists so UI is stable and buttons always work.
    // 规范化嵌套动作列表，确保 UI 稳定且按钮可用。
    if (!Array.isArray(safe.then)) safe.then = [];
    if (!Array.isArray(safe.else)) safe.else = [];
    if (!Array.isArray(safe.on_error)) safe.on_error = [];
    return `<section class="detail-card nested">${head}
      <div class="ir-flow-editor" data-flow-root="branch" data-aidx="${idx}">
        <div class="sub-section">
          <div class="sub-title">分支条件（when）</div>
          <div class="soft-note">当前 MVP 仅支持用“指标条件（metric）”做分支判断（满足/不满足/报错）。足以覆盖“期待验证/不验、压力验证/不验”等主流程。</div>
          <div class="settings-grid">
            <article class="setting-item">
              <label>指标预设（preset）</label>
              <select class="ir-branch-when" data-idx="${idx}" data-field="when_preset">${presetOptions}</select>
              <div class="soft-note">建议优先使用预设（中文口径更清楚）；也可手写 metric.path（后续会补 UI）。</div>
            </article>
            <article class="setting-item">
              <label>情绪递质通道（channel，可选）</label>
              <input class="ir-branch-when" data-idx="${idx}" data-field="when_channel" type="text" value="${esc(String(metric.channel ?? ""))}" />
              <div class="soft-note">仅当预设需要通道时填写，例如 DA/多巴胺/COR/皮质醇。</div>
            </article>
            <article class="setting-item">
              <label>比较符（op）</label>
              <select class="ir-branch-when" data-idx="${idx}" data-field="when_op">
                <option value=">=" ${String(metric.op || ">=") === ">=" ? "selected" : ""}>&gt;=</option>
                <option value=">" ${String(metric.op || "") === ">" ? "selected" : ""}>&gt;</option>
                <option value="<=" ${String(metric.op || "") === "<=" ? "selected" : ""}>&lt;=</option>
                <option value="<" ${String(metric.op || "") === "<" ? "selected" : ""}>&lt;</option>
                <option value="==" ${String(metric.op || "") === "==" ? "selected" : ""}>=</option>
                <option value="!=" ${String(metric.op || "") === "!=" ? "selected" : ""}>!=</option>
                <option value="exists" ${String(metric.op || "") === "exists" ? "selected" : ""}>exists（存在）</option>
                <option value="changed" ${String(metric.op || "") === "changed" ? "selected" : ""}>changed（变化了）</option>
              </select>
            </article>
            <article class="setting-item">
              <label>取值方式（mode）</label>
              <select class="ir-branch-when" data-idx="${idx}" data-field="when_mode">
                <option value="state" ${String(metric.mode || "state") === "state" ? "selected" : ""}>state（状态）</option>
                <option value="delta" ${String(metric.mode || "") === "delta" ? "selected" : ""}>delta（变化量）</option>
                <option value="avg_rate" ${String(metric.mode || "") === "avg_rate" ? "selected" : ""}>avg_rate（变化率）</option>
              </select>
            </article>
            <article class="setting-item">
              <label>阈值（value，可用模板 {{{var}}}）</label>
              <input class="ir-branch-when" data-idx="${idx}" data-field="when_value" type="text" value="${esc(String(metric.value ?? ""))}" />
            </article>
            <article class="setting-item">
              <label>window_ticks（变化率用，默认 4）</label>
              <input class="ir-branch-when" data-idx="${idx}" data-field="when_window_ticks" type="number" step="1" value="${esc(String(metric.window_ticks ?? 4))}" />
            </article>
            <article class="setting-item">
              <label>对象选择（selector.mode）</label>
              <select class="ir-branch-when" data-idx="${idx}" data-field="selector_mode">
                <option value="all" ${selMode === "all" ? "selected" : ""}>全部对象（all）</option>
                <option value="specific_item" ${selMode === "specific_item" ? "selected" : ""}>特定条目（specific_item）</option>
                <option value="specific_ref" ${selMode === "specific_ref" ? "selected" : ""}>特定对象（specific_ref）</option>
                <option value="contains_text" ${selMode === "contains_text" ? "selected" : ""}>包含特征/文本（contains_text）</option>
                <option value="top_n" ${selMode === "top_n" ? "selected" : ""}>能量 Top-N（top_n）</option>
              </select>
            </article>
            <article class="setting-item"><label>selector.item_id（specific_item 用）</label><input class="ir-branch-when" data-idx="${idx}" data-field="selector_item_id" type="text" value="${esc(String(sel.item_id ?? ""))}" /></article>
            <article class="setting-item"><label>selector.ref_object_id（specific_ref 用）</label><input class="ir-branch-when" data-idx="${idx}" data-field="selector_ref_object_id" type="text" value="${esc(String(sel.ref_object_id ?? ""))}" /></article>
            <article class="setting-item"><label>selector.ref_object_type（可选）</label><input class="ir-branch-when" data-idx="${idx}" data-field="selector_ref_object_type" type="text" value="${esc(String(sel.ref_object_type ?? ""))}" /></article>
            <article class="setting-item"><label>selector.contains_text（contains_text 用）</label><input class="ir-branch-when" data-idx="${idx}" data-field="selector_contains_text" type="text" value="${esc(String(sel.contains_text ?? ""))}" /></article>
            <article class="setting-item"><label>selector.top_n（top_n 用）</label><input class="ir-branch-when" data-idx="${idx}" data-field="selector_top_n" type="number" step="1" value="${esc(String(sel.top_n ?? ""))}" /></article>
            <article class="setting-item"><label>selector.ref_object_types（逗号，可选过滤）</label><input class="ir-branch-when" data-idx="${idx}" data-field="selector_ref_object_types" type="text" value="${esc(a(sel.ref_object_types).join(','))}" /></article>
          </div>
        </div>

        <div class="sub-section">
          <div class="sub-title">满足（then）</div>
          ${_irFlowRenderActionList(a(safe.then), "then", 0)}
        </div>
        <div class="sub-section">
          <div class="sub-title">不满足（else）</div>
          ${_irFlowRenderActionList(a(safe.else), "else", 0)}
        </div>
        <div class="sub-section">
          <div class="sub-title">报错（on_error）</div>
          ${_irFlowRenderActionList(a(safe.on_error), "on_error", 0)}
        </div>
      </div>
      <div class="soft-note">提示：branch 是“动作内控制流”。如果你只需要“同时/任一”触发，优先用 when.any / when.all 更直观。</div>
    </section>`;
  }

  return `<section class="detail-card nested">${head}
    <article class="setting-item">
      <label>日志内容（log）</label>
      <textarea class="ir-action" data-idx="${idx}" data-field="text">${esc(String(val || ""))}</textarea>
    </article>
  </section>`;
}

function bindRuleEditor(selectedRule) {
  if (!selectedRule) return;
  const doc = rulesDoc();

  const findRuleIndex = () => a(doc.rules).findIndex((r) => r?.id === S.innateRulesSelectedId);

  const markDirty = () => {
    S.innateRulesDirty = true;
  };

  document.querySelectorAll(".ir-basic").forEach((node) => {
    node.addEventListener("input", () => {
      const idx = findRuleIndex();
      if (idx < 0) return;
      const field = node.dataset.field;
      const rule = doc.rules[idx];
      if (!field || !rule) return;
      if (node.type === "checkbox") rule[field] = Boolean(node.checked);
      else if (node.type === "number") rule[field] = node.value === "" ? "" : Number(node.value);
      else rule[field] = node.value;
      markDirty();
    });
  });

  const applyWhenModelToRule = (rule, model) => {
    const clauses = a(model?.clauses).map((c) => clauseToWhen(c)).filter(Boolean);
    if (clauses.length === 1) rule.when = clauses[0];
    else rule.when = { [model.mode || "any"]: clauses };
  };

  document.querySelectorAll(".ir-when-mode").forEach((node) => {
    node.addEventListener("change", () => {
      const idx = findRuleIndex();
      if (idx < 0) return;
      const rule = doc.rules[idx];
      const model = editorWhenModel(rule.when);
      model.mode = node.value || "any";
      applyWhenModelToRule(rule, model);
      markDirty();
      draw();
    });
  });

  document.querySelectorAll(".ir-clause").forEach((node) => {
    node.addEventListener("input", () => {
      const idx = findRuleIndex();
      if (idx < 0) return;
      const rule = doc.rules[idx];
      const model = editorWhenModel(rule.when);
      const cidx = Number(node.dataset.idx || "0");
      const field = node.dataset.field;
      const clause = model.clauses[cidx];
      if (!clause || !field) return;
      if (!clause.spec || typeof clause.spec !== "object") clause.spec = {};

      if (field === "type") {
        clause.type = node.value;
        // Reset spec to reasonable defaults for the new type.
        // 切换条件类型时重置 spec，避免残留字段影响编译。
        if (clause.type === "cfs") clause.spec = { kinds: [], min_strength: 0.3, max_strength: "" };
        else if (clause.type === "state_window") clause.spec = { stage: "any", fast_cp_rise_min: 1, fast_cp_drop_min: "", min_candidate_count: "", candidate_hint_any: [] };
        else if (clause.type === "timer") clause.spec = { every_n_ticks: 1, at_tick: "" };
        else if (clause.type === "metric") clause.spec = { preset: "got_er", metric: "", channel: "", mode: "delta", op: ">=", value: "", min: "", max: "", window_ticks: 4, match_policy: "any", capture_as: "", epsilon: "", prev_gate: {}, note: "", selector: { mode: "all" } };
      } else if (clause.type === "cfs" && field === "kinds") {
        clause.spec.kinds = (node.value || "").split(",").map((x) => x.trim()).filter(Boolean);
      } else if (clause.type === "state_window" && field === "candidate_hint_any") {
        clause.spec.candidate_hint_any = (node.value || "").split(",").map((x) => x.trim()).filter(Boolean);
      } else if (clause.type === "metric" && field.startsWith("prev_gate_")) {
        const pg = clause.spec.prev_gate && typeof clause.spec.prev_gate === "object" ? clause.spec.prev_gate : {};
        const k = field.replace("prev_gate_", "");
        if (k === "op") pg.op = node.value;
        else if (k === "value") pg.value = node.value;
        else if (k === "min") pg.min = node.value;
        else if (k === "max") pg.max = node.value;
        else pg[k] = node.value;
        clause.spec.prev_gate = pg;
      } else if (clause.type === "metric" && field.startsWith("selector_")) {
        const sel = clause.spec.selector && typeof clause.spec.selector === "object" ? clause.spec.selector : {};
        const key = field.replace("selector_", "");
        if (key === "ref_object_types") {
          sel.ref_object_types = (node.value || "").split(",").map((x) => x.trim()).filter(Boolean);
        } else {
          sel[key] = node.type === "number" ? (node.value === "" ? "" : Number(node.value)) : node.value;
        }
        clause.spec.selector = sel;
      } else {
        clause.spec[field] = node.type === "number" ? (node.value === "" ? "" : Number(node.value)) : node.value;
      }
      applyWhenModelToRule(rule, model);
      markDirty();
    });
    node.addEventListener("change", () => node.dispatchEvent(new Event("input")));
  });

  document.querySelectorAll(".ir-remove-clause").forEach((node) => {
    node.addEventListener("click", () => {
      const idx = findRuleIndex();
      if (idx < 0) return;
      const rule = doc.rules[idx];
      const model = editorWhenModel(rule.when);
      const cidx = Number(node.dataset.idx || "0");
      model.clauses.splice(cidx, 1);
      applyWhenModelToRule(rule, model);
      markDirty();
      draw();
    });
  });

  const addClause = () => {
    const idx = findRuleIndex();
    if (idx < 0) return;
    const rule = doc.rules[idx];
    const model = editorWhenModel(rule.when);
    model.clauses.push({ type: "cfs", spec: { kinds: [], min_strength: 0.3, max_strength: "" } });
    applyWhenModelToRule(rule, model);
    markDirty();
    draw();
  };
  const addClauseBtn = document.getElementById("irAddClauseBtn");
  if (addClauseBtn) addClauseBtn.addEventListener("click", addClause);

  // ---- actions ----
  const ensureThen = (rule) => {
    if (!Array.isArray(rule.then)) rule.then = [];
    return rule.then;
  };

  const setActionType = (act, type) => {
    if (type === "cfs_emit") return { cfs_emit: { kind: "dissonance", scope: "object", from: "metric_matches", max_signals: 1, min_strength: 0.0, capture_as: "", strength: { from: "match_value", policy: "linear_clamp", min: 0.0, max: 1.0, out_min: 0.0, out_max: 1.0 } } };
    if (type === "focus") return { focus: { from: "cfs_matches", match_policy: "all", ttl_ticks: 2, focus_boost: 0.9, deduplicate_by: "target_ref_object_id" } };
    if (type === "emit_script") return { emit_script: { script_id: "custom_script", script_kind: "custom", priority: 50, trigger: "" } };
    if (type === "emotion_update") return { emotion_update: { DA: 0.0 } };
    if (type === "action_trigger") return { action_trigger: { action_id: "custom_action", action_kind: "custom", gain: 0.3, threshold: 1.0, cooldown_ticks: 0, params: {} } };
    if (type === "pool_energy") return { pool_energy: { selector: { mode: "all" }, delta_er: 0.0, delta_ev: 0.0, create_if_missing: false, create_ref_object_type: "sa", create_display: "", reason: "" } };
    if (type === "pool_bind_attribute") return { pool_bind_attribute: { selector: { mode: "all" }, attribute: { attribute_name: "", attribute_value: "", raw: "", display: "", value_type: "discrete", modality: "internal", er: 0.0, ev: 0.0 }, reason: "" } };
    if (type === "delay") return { delay: { ticks: 2, then: [{ log: "延时触发（示例）" }] } };
    if (type === "branch") return { branch: { when: { metric: { preset: "reward_state", mode: "state", op: ">", value: 0 } }, then: [{ log: "满足条件（then）" }], else: [{ log: "不满足（else）" }], on_error: [{ log: "条件报错（on_error）" }] } };
    return { log: "" };
  };

  document.querySelectorAll(".ir-action").forEach((node) => {
    node.addEventListener("input", () => {
      const idx = findRuleIndex();
      if (idx < 0) return;
      const rule = doc.rules[idx];
      const actions = ensureThen(rule);
      const aidx = Number(node.dataset.idx || "0");
      const field = node.dataset.field;
      if (aidx < 0 || aidx >= actions.length || !field) return;
      const act = actions[aidx];
      const key = Object.keys(act || {})[0];
      if (field === "type") {
        actions[aidx] = setActionType(act, node.value);
        markDirty();
        draw();
        return;
      }
      if (key === "focus") {
        const spec = act.focus || {};
        spec[field] = node.type === "number" ? (node.value === "" ? "" : Number(node.value)) : node.value;
        act.focus = spec;
      } else if (key === "cfs_emit") {
        const spec = act.cfs_emit || {};
        if (field === "kind") spec.kind = node.value || "";
        else if (field === "scope") spec.scope = node.value || "object";
        else if (field === "from") spec.from = node.value || "metric_matches";
        else if (field === "max_signals") spec.max_signals = node.value === "" ? "" : Number(node.value);
        else if (field === "min_strength") spec.min_strength = node.value === "" ? "" : Number(node.value);
        else if (field === "capture_as") spec.capture_as = node.value || "";
        else if (field.startsWith("strength_")) {
          const st = spec.strength && typeof spec.strength === "object" ? spec.strength : {};
          const k = field.replace("strength_", "");
          if (k === "policy") st.policy = node.value || "linear_clamp";
          else if (k === "from") st.from = node.value || "match_value";
          else if (k === "var") st.var = node.value || "";
          else if (k === "abs") st.abs = Boolean(node.checked);
          else if (k === "invert") st.invert = Boolean(node.checked);
          else if (k === "min") st.min = node.value === "" ? "" : Number(node.value);
          else if (k === "max") st.max = node.value === "" ? "" : Number(node.value);
          else if (k === "out_min") st.out_min = node.value === "" ? "" : Number(node.value);
          else if (k === "out_max") st.out_max = node.value === "" ? "" : Number(node.value);
          else if (k === "scale") st.scale = node.value === "" ? "" : Number(node.value);
          else if (k === "offset") st.offset = node.value === "" ? "" : Number(node.value);
          else if (k === "pred_scale") st.pred_scale = node.value === "" ? "" : Number(node.value);
          else if (k === "actual_scale") st.actual_scale = node.value === "" ? "" : Number(node.value);
          else if (k === "gamma") st.gamma = node.value === "" ? "" : Number(node.value);
          else if (k === "eps") st.eps = node.value === "" ? "" : Number(node.value);
          else st[k] = node.value;
          spec.strength = st;
        } else if (field.startsWith("target_")) {
          const k = field.replace("target_", "");
          const tFrom = k === "from" ? String(node.value || "match") : String((spec.target || {}).from || "match");
          if (k === "from") {
            if (!tFrom || tFrom === "match") delete spec.target;
            else spec.target = { from: tFrom };
          } else {
            const t = spec.target && typeof spec.target === "object" ? spec.target : { from: tFrom };
            if (k === "ref_object_id") t.ref_object_id = node.value || "";
            else if (k === "ref_object_type") t.ref_object_type = node.value || "";
            else if (k === "item_id") t.item_id = node.value || "";
            else if (k === "display") t.display = node.value || "";
            else t[k] = node.value;
            if (String(t.from || "match") === "match") delete spec.target;
            else spec.target = t;
          }
        } else if (field.startsWith("bindattr_")) {
          const k = field.replace("bindattr_", "");
          if (k === "enabled") {
            if (!Boolean(node.checked)) delete spec.bind_attribute;
            else spec.bind_attribute = spec.bind_attribute && typeof spec.bind_attribute === "object" ? spec.bind_attribute : {};
          } else {
            const b = spec.bind_attribute && typeof spec.bind_attribute === "object" ? spec.bind_attribute : {};
            if (k === "attribute_name") b.attribute_name = node.value || "";
            else if (k === "value_from") b.value_from = node.value || "strength";
            else if (k === "display") b.display = node.value || "";
            else if (k === "raw") b.raw = node.value || "";
            else if (k === "value_type") b.value_type = node.value || "numerical";
            else if (k === "modality") b.modality = node.value || "internal";
            else if (k === "er") b.er = node.value === "" ? "" : Number(node.value);
            else if (k === "ev") b.ev = node.value === "" ? "" : Number(node.value);
            else if (k === "reason") b.reason = node.value || "";
            else b[k] = node.value;
            spec.bind_attribute = b;
          }
        } else {
          spec[field] = node.type === "number" ? (node.value === "" ? "" : Number(node.value)) : node.value;
        }
        act.cfs_emit = spec;
      } else if (key === "emit_script") {
        const spec = act.emit_script || {};
        spec[field] = node.type === "number" ? (node.value === "" ? "" : Number(node.value)) : node.value;
        act.emit_script = spec;
      } else if (key === "emotion_update") {
        const payload = act.emotion_update && typeof act.emotion_update === "object" ? act.emotion_update : {};
        const coerceMaybeNumberOrTemplate = (raw) => {
          const s = String(raw ?? "").trim();
          if (!s) return "";
          if (s.includes("{{{")) return s;
          const n = Number(s);
          return Number.isFinite(n) ? n : s;
        };
        if (field === "eu_key" || field === "eu_val") {
          const row = node.closest(".ir-kv-row");
          const keyEl = row?.querySelector(".ir-kv-key");
          const valEl = row?.querySelector(".ir-kv-val");
          if (!keyEl || !valEl) return;
          const newKey = String(keyEl.value || "").trim();
          const oldKey = String(keyEl.dataset.oldKey || "").trim();
          if (!newKey) return;
          if (oldKey && oldKey !== newKey) delete payload[oldKey];
          payload[newKey] = coerceMaybeNumberOrTemplate(valEl.value);
          keyEl.dataset.oldKey = newKey;
          act.emotion_update = payload;
        }
      } else if (key === "action_trigger") {
        const spec = act.action_trigger || {};
        const coerceMaybeNumberOrTemplate = (raw) => {
          const s = String(raw ?? "").trim();
          if (!s) return "";
          // Keep templates as-is (e.g. {{{match_value}}}) so rules remain editable & readable.
          // 保留模板字符串（例如 {{{match_value}}}），避免被 number 输入吞掉。
          if (s.includes("{{{")) return s;
          const n = Number(s);
          return Number.isFinite(n) ? n : s;
        };
        if (field === "at_param_key" || field === "at_param_val") {
          const row = node.closest(".ir-kv-row");
          const keyEl = row?.querySelector(".ir-kv-key");
          const valEl = row?.querySelector(".ir-kv-val");
          if (!keyEl || !valEl) return;
          const newKey = String(keyEl.value || "").trim();
          const oldKey = String(keyEl.dataset.oldKey || "").trim();
          if (!newKey) return;
          const params = spec.params && typeof spec.params === "object" ? spec.params : {};
          if (oldKey && oldKey !== newKey) delete params[oldKey];
          params[newKey] = coerceMaybeNumberOrTemplate(valEl.value);
          spec.params = params;
          keyEl.dataset.oldKey = newKey;
        } else if (field === "action_id") spec.action_id = node.value || "";
        else if (field === "action_kind") spec.action_kind = node.value || "";
        else if (field === "gain") spec.gain = coerceMaybeNumberOrTemplate(node.value);
        else if (field === "threshold") spec.threshold = coerceMaybeNumberOrTemplate(node.value);
        else if (field === "cooldown_ticks") spec.cooldown_ticks = node.value === "" ? "" : Number(node.value);
        else spec[field] = node.type === "number" ? (node.value === "" ? "" : Number(node.value)) : node.value;
        act.action_trigger = spec;
      } else if (key === "pool_energy") {
        const spec = act.pool_energy || {};
        if (field.startsWith("selector_")) {
          const sel = spec.selector && typeof spec.selector === "object" ? spec.selector : {};
          const k = field.replace("selector_", "");
          if (k === "ref_object_types") sel.ref_object_types = (node.value || "").split(",").map((x) => x.trim()).filter(Boolean);
          else sel[k] = node.type === "number" ? (node.value === "" ? "" : Number(node.value)) : node.value;
          spec.selector = sel;
        } else if (field === "create_if_missing") {
          spec.create_if_missing = Boolean(node.checked);
        } else {
          // Keep as string to allow templates like {{{var}}}
          spec[field] = node.value;
        }
        act.pool_energy = spec;
      } else if (key === "pool_bind_attribute") {
        const spec = act.pool_bind_attribute || {};
        if (field.startsWith("selector_")) {
          const sel = spec.selector && typeof spec.selector === "object" ? spec.selector : {};
          const k = field.replace("selector_", "");
          if (k === "ref_object_types") sel.ref_object_types = (node.value || "").split(",").map((x) => x.trim()).filter(Boolean);
          else sel[k] = node.type === "number" ? (node.value === "" ? "" : Number(node.value)) : node.value;
          spec.selector = sel;
        } else if (field.startsWith("attr_")) {
          const attr = spec.attribute && typeof spec.attribute === "object" ? spec.attribute : {};
          const k = field.replace("attr_", "");
          if (k === "name") attr.attribute_name = node.value;
          else if (k === "value") attr.attribute_value = node.value;
          else if (k === "raw") attr.raw = node.value;
          else if (k === "display") attr.display = node.value;
          else if (k === "value_type") attr.value_type = node.value;
          else if (k === "modality") attr.modality = node.value;
          else if (k === "er") attr.er = node.value;
          else if (k === "ev") attr.ev = node.value;
          else attr[k] = node.value;
          spec.attribute = attr;
        } else {
          spec[field] = node.type === "checkbox" ? Boolean(node.checked) : node.value;
        }
        act.pool_bind_attribute = spec;
      } else if (key === "delay") {
        const spec = act.delay || {};
        if (field === "ticks") spec.ticks = node.value === "" ? "" : Number(node.value);
        else spec[field] = node.type === "number" ? (node.value === "" ? "" : Number(node.value)) : node.value;
        act.delay = spec;
      } else if (key === "branch") {
        const spec = act.branch || {};
        spec[field] = node.value;
        act.branch = spec;
      } else if (key === "log") {
        actions[aidx] = { log: node.value };
      }
      markDirty();
    });
    node.addEventListener("change", () => node.dispatchEvent(new Event("input")));
  });

  // Key-value editor buttons inside action rows (no JSON) / 动作行里的键值对按钮（不展示 JSON）
  // Scope to the editor container to avoid interfering with the graph modal.
  // 限定在编辑器容器内，避免影响图形编辑器弹窗。
  (E.innateRulesEditor || document).querySelectorAll("button[data-action]").forEach((btn) => {
    const actName = String(btn.dataset.action || "");
    const aidx = Number(btn.dataset.idx || "0");
    const row = Number(btn.dataset.row || "0");
    const addKey = (obj, base) => {
      const used = new Set(Object.keys(obj || {}));
      if (!used.has(base)) return base;
      for (let i = 2; i < 64; i++) {
        const k = `${base}${i}`;
        if (!used.has(k)) return k;
      }
      return `${base}_${Date.now()}`;
    };

    btn.addEventListener("click", () => {
      const idx = findRuleIndex();
      if (idx < 0) return;
      const rule = doc.rules[idx];
      const actions = ensureThen(rule);
      if (aidx < 0 || aidx >= actions.length) return;
      const action = actions[aidx] || {};
      const k = Object.keys(action || {})[0];

      if (actName === "eu_add" && k === "emotion_update") {
        const payload = action.emotion_update && typeof action.emotion_update === "object" ? action.emotion_update : {};
        const key2 = addKey(payload, "DA");
        payload[key2] = 0.0;
        action.emotion_update = payload;
        actions[aidx] = action;
        markDirty();
        draw();
        return;
      }
      if (actName === "eu_remove" && k === "emotion_update") {
        const payload = action.emotion_update && typeof action.emotion_update === "object" ? action.emotion_update : {};
        const entries = Object.entries(payload).filter(([kk]) => String(kk || "").trim());
        const key2 = entries[row]?.[0];
        if (key2) delete payload[key2];
        action.emotion_update = payload;
        actions[aidx] = action;
        markDirty();
        draw();
        return;
      }

      if (actName === "at_param_add" && k === "action_trigger") {
        const spec = action.action_trigger && typeof action.action_trigger === "object" ? action.action_trigger : {};
        const params = spec.params && typeof spec.params === "object" ? spec.params : {};
        const key2 = addKey(params, "param");
        params[key2] = "";
        spec.params = params;
        action.action_trigger = spec;
        actions[aidx] = action;
        markDirty();
        draw();
        return;
      }
      if (actName === "at_param_remove" && k === "action_trigger") {
        const spec = action.action_trigger && typeof action.action_trigger === "object" ? action.action_trigger : {};
        const params = spec.params && typeof spec.params === "object" ? spec.params : {};
        const entries = Object.entries(params).filter(([kk]) => String(kk || "").trim());
        const key2 = entries[row]?.[0];
        if (key2) delete params[key2];
        spec.params = params;
        action.action_trigger = spec;
        actions[aidx] = action;
        markDirty();
        draw();
        return;
      }

      if (actName === "at_params_fill_focus" && k === "action_trigger") {
        const spec = action.action_trigger && typeof action.action_trigger === "object" ? action.action_trigger : {};
        const params = spec.params && typeof spec.params === "object" ? spec.params : {};
        params.target_ref_object_id = params.target_ref_object_id || "{{{match_ref_object_id}}}";
        params.target_ref_object_type = params.target_ref_object_type || "{{{match_ref_object_type}}}";
        params.target_item_id = params.target_item_id || "{{{match_item_id}}}";
        params.target_display = params.target_display || "{{{match_display}}}";
        params.strength = params.strength || "{{{match_value}}}";
        params.focus_boost = params.focus_boost ?? 0.9;
        params.ttl_ticks = params.ttl_ticks ?? 2;
        spec.params = params;
        action.action_trigger = spec;
        actions[aidx] = action;
        markDirty();
        draw();
        return;
      }
      if (actName === "at_params_fill_recall" && k === "action_trigger") {
        const spec = action.action_trigger && typeof action.action_trigger === "object" ? action.action_trigger : {};
        const params = spec.params && typeof spec.params === "object" ? spec.params : {};
        params.trigger_kind = params.trigger_kind || "{{{match_kind}}}";
        params.trigger_strength = params.trigger_strength || "{{{match_value}}}";
        spec.params = params;
        action.action_trigger = spec;
        actions[aidx] = action;
        markDirty();
        draw();
        return;
      }
    });
  });

  // -------------------------------------------------------------------
  // Branch.when editor (no YAML/JSON) / branch.when 条件编辑器（不需要手写 YAML/JSON）
  // -------------------------------------------------------------------
  (E.innateRulesEditor || document).querySelectorAll(".ir-branch-when").forEach((node) => {
    const handler = () => {
      const idx = findRuleIndex();
      if (idx < 0) return;
      const rule = doc.rules[idx];
      const actions = ensureThen(rule);
      const aidx = Number(node.dataset.idx || "0");
      const field = String(node.dataset.field || "");
      if (!field || aidx < 0 || aidx >= actions.length) return;

      const action = actions[aidx] || {};
      if (!action.branch || typeof action.branch !== "object") action.branch = {};
      const spec = action.branch;
      if (!spec.when || typeof spec.when !== "object") spec.when = {};
      const when = spec.when;
      if (!when.metric || typeof when.metric !== "object") when.metric = {};
      const metric = when.metric;
      if (!metric.selector || typeof metric.selector !== "object") metric.selector = { mode: "all" };
      const sel = metric.selector;

      const v = node.type === "number" ? (node.value === "" ? "" : Number(node.value)) : node.value;

      if (field === "when_preset") metric.preset = String(v || "");
      else if (field === "when_channel") metric.channel = String(v || "");
      else if (field === "when_op") metric.op = String(v || ">=");
      else if (field === "when_mode") metric.mode = String(v || "state");
      else if (field === "when_value") metric.value = String(v ?? "");
      else if (field === "when_window_ticks") metric.window_ticks = v === "" ? "" : Number(v);
      else if (field === "selector_mode") sel.mode = String(v || "all");
      else if (field === "selector_item_id") sel.item_id = String(v || "");
      else if (field === "selector_ref_object_id") sel.ref_object_id = String(v || "");
      else if (field === "selector_ref_object_type") sel.ref_object_type = String(v || "");
      else if (field === "selector_contains_text") sel.contains_text = String(v || "");
      else if (field === "selector_top_n") sel.top_n = v === "" ? "" : Number(v);
      else if (field === "selector_ref_object_types") {
        sel.ref_object_types = String(v || "")
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean);
      } else {
        metric[field] = v;
      }

      metric.selector = sel;
      when.metric = metric;
      spec.when = when;
      action.branch = spec;
      actions[aidx] = action;
      markDirty();
    };

    node.addEventListener(node.tagName === "SELECT" ? "change" : "input", handler);
    node.addEventListener("change", handler);
  });

  // -------------------------------------------------------------------
  // Nested flow editor (delay/branch.then/else/on_error) / 嵌套动作流编辑器（delay/branch）
  // -------------------------------------------------------------------
  const resolveFlowRootCfg = (aidx, rootType) => {
    const idx = findRuleIndex();
    if (idx < 0) return null;
    const rule = doc.rules[idx];
    const actions = ensureThen(rule);
    if (aidx < 0 || aidx >= actions.length) return null;
    const action = actions[aidx] || {};
    if (rootType === "delay") {
      if (!action.delay || typeof action.delay !== "object") action.delay = { ticks: 1, then: [] };
      actions[aidx] = action;
      return action.delay;
    }
    if (rootType === "branch") {
      if (!action.branch || typeof action.branch !== "object") action.branch = { when: { metric: { preset: "reward_state", mode: "state", op: ">", value: 0 } }, then: [], else: [], on_error: [] };
      // Ensure lists exist (renderer stability)
      if (!Array.isArray(action.branch.then)) action.branch.then = [];
      if (!Array.isArray(action.branch.else)) action.branch.else = [];
      if (!Array.isArray(action.branch.on_error)) action.branch.on_error = [];
      actions[aidx] = action;
      return action.branch;
    }
    return null;
  };

  (E.innateRulesEditor || document).querySelectorAll(".ir-flow-prop").forEach((el) => {
    const host = el.closest?.(".ir-flow-editor");
    if (!host) return;
    const rootType = String(host.dataset.flowRoot || "");
    const aidx = Number(host.dataset.aidx || "");
    const apath = String(el.dataset.apath || "");
    const field = String(el.dataset.field || "");
    const isSelect = el.tagName === "SELECT";
    const isTextArea = el.tagName === "TEXTAREA";
    if (!apath || !field) return;

    const onChange = () => {
      const rootCfg = resolveFlowRootCfg(aidx, rootType);
      if (!rootCfg) return;
      const ref = _irFlowResolveActionRef(rootCfg, apath);
      if (!ref) return;

      // Parse value
      let v = isTextArea ? el.value : el.value;
      if (el.type === "checkbox") v = Boolean(el.checked);
      if (el.type === "number") v = el.value === "" ? "" : Number(el.value);

      const coerceMaybeNumberOrTemplate = (raw) => {
        const s = String(raw ?? "").trim();
        if (!s) return "";
        if (s.includes("{{{")) return s;
        const n = Number(s);
        return Number.isFinite(n) ? n : s;
      };

      // type switch
      if (field === "type") {
        ref.list[ref.idx] = _irFlowDefaultAction(String(v || "log"));
        markDirty();
        draw(); // rerender to show new action fields
        return;
      }

      let act = ref.action;
      const k = _irFlowActionKey(act) || "log";

      if (k === "log") {
        ref.list[ref.idx] = { log: String(v || "") };
      } else if (k === "cfs_emit") {
        const spec = act.cfs_emit && typeof act.cfs_emit === "object" ? act.cfs_emit : {};
        if (field === "kind") spec.kind = String(v || "");
        else if (field === "scope") spec.scope = String(v || "object");
        else if (field === "from") spec.from = String(v || "metric_matches");
        else if (field.startsWith("strength_")) {
          const st = spec.strength && typeof spec.strength === "object" ? spec.strength : {};
          const kk = field.replace("strength_", "");
          if (kk === "policy") st.policy = String(v || "linear_clamp");
          else if (kk === "from") st.from = String(v || "match_value");
          else if (kk === "var") st.var = String(v || "");
          else if (kk === "min") st.min = v;
          else if (kk === "max") st.max = v;
          else if (kk === "out_min") st.out_min = v;
          else if (kk === "out_max") st.out_max = v;
          else st[kk] = v;
          spec.strength = st;
        } else if (field.startsWith("bindattr_")) {
          const kk = field.replace("bindattr_", "");
          if (kk === "enabled") {
            if (!Boolean(v)) delete spec.bind_attribute;
            else spec.bind_attribute = spec.bind_attribute && typeof spec.bind_attribute === "object" ? spec.bind_attribute : {};
          } else {
            const b = spec.bind_attribute && typeof spec.bind_attribute === "object" ? spec.bind_attribute : {};
            if (kk === "attribute_name") b.attribute_name = String(v || "");
            else if (kk === "display") b.display = String(v || "");
            else b[kk] = v;
            spec.bind_attribute = b;
          }
        } else {
          spec[field] = v;
        }
        act.cfs_emit = spec;
        ref.list[ref.idx] = act;
      } else if (k === "focus") {
        const spec = act.focus && typeof act.focus === "object" ? act.focus : {};
        spec[field] = v;
        act.focus = spec;
        ref.list[ref.idx] = act;
      } else if (k === "emit_script") {
        const spec = act.emit_script && typeof act.emit_script === "object" ? act.emit_script : {};
        spec[field] = v;
        act.emit_script = spec;
        ref.list[ref.idx] = act;
      } else if (k === "emotion_update" && (field === "eu_key" || field === "eu_val")) {
        const rowEl = el.closest?.(".ir-kv-row");
        const keyEl = rowEl?.querySelector?.(".ir-kv-key");
        const valEl = rowEl?.querySelector?.(".ir-kv-val");
        if (!keyEl || !valEl) return;
        const newKey = String(keyEl.value || "").trim();
        const oldKey = String(keyEl.dataset.oldKey || "").trim();
        if (!newKey) return;
        const payload = act.emotion_update && typeof act.emotion_update === "object" ? act.emotion_update : {};
        if (oldKey && oldKey !== newKey) delete payload[oldKey];
        payload[newKey] = coerceMaybeNumberOrTemplate(valEl.value);
        act.emotion_update = payload;
        keyEl.dataset.oldKey = newKey;
        ref.list[ref.idx] = act;
      } else if (k === "action_trigger" && (field === "at_param_key" || field === "at_param_val")) {
        const rowEl = el.closest?.(".ir-kv-row");
        const keyEl = rowEl?.querySelector?.(".ir-kv-key");
        const valEl = rowEl?.querySelector?.(".ir-kv-val");
        if (!keyEl || !valEl) return;
        const newKey = String(keyEl.value || "").trim();
        const oldKey = String(keyEl.dataset.oldKey || "").trim();
        if (!newKey) return;
        const spec = act.action_trigger && typeof act.action_trigger === "object" ? act.action_trigger : {};
        const params = spec.params && typeof spec.params === "object" ? spec.params : {};
        if (oldKey && oldKey !== newKey) delete params[oldKey];
        params[newKey] = coerceMaybeNumberOrTemplate(valEl.value);
        spec.params = params;
        act.action_trigger = spec;
        keyEl.dataset.oldKey = newKey;
        ref.list[ref.idx] = act;
      } else if (k === "action_trigger") {
        const spec = act.action_trigger && typeof act.action_trigger === "object" ? act.action_trigger : {};
        if (field === "gain" || field === "threshold") spec[field] = coerceMaybeNumberOrTemplate(v);
        else spec[field] = v;
        act.action_trigger = spec;
        ref.list[ref.idx] = act;
      } else if (k === "pool_energy") {
        const spec = act.pool_energy && typeof act.pool_energy === "object" ? act.pool_energy : {};
        if (field.startsWith("selector_")) {
          const sel = spec.selector && typeof spec.selector === "object" ? spec.selector : {};
          const kk = field.replace("selector_", "");
          if (kk === "ref_object_types") {
            sel.ref_object_types = String(v || "").split(",").map((x) => x.trim()).filter(Boolean);
          } else {
            sel[kk] = v;
          }
          spec.selector = sel;
        } else if (field === "create_if_missing") {
          spec.create_if_missing = Boolean(v);
        } else if (field === "delta_er" || field === "delta_ev") {
          spec[field] = coerceMaybeNumberOrTemplate(v);
        } else {
          spec[field] = v;
        }
        act.pool_energy = spec;
        ref.list[ref.idx] = act;
      } else if (k === "pool_bind_attribute") {
        const spec = act.pool_bind_attribute && typeof act.pool_bind_attribute === "object" ? act.pool_bind_attribute : {};
        if (field.startsWith("selector_")) {
          const sel = spec.selector && typeof spec.selector === "object" ? spec.selector : {};
          const kk = field.replace("selector_", "");
          if (kk === "ref_object_types") {
            sel.ref_object_types = String(v || "").split(",").map((x) => x.trim()).filter(Boolean);
          } else {
            sel[kk] = v;
          }
          spec.selector = sel;
        } else if (field.startsWith("attr_")) {
          const attr = spec.attribute && typeof spec.attribute === "object" ? spec.attribute : {};
          const kk = field.replace("attr_", "");
          if (kk === "name") attr.attribute_name = String(v || "");
          else if (kk === "value") attr.attribute_value = v;
          else if (kk === "display") attr.display = String(v || "");
          else attr[kk] = v;
          spec.attribute = attr;
        } else {
          spec[field] = v;
        }
        act.pool_bind_attribute = spec;
        ref.list[ref.idx] = act;
      } else if (k === "delay") {
        const spec = act.delay && typeof act.delay === "object" ? act.delay : {};
        if (field === "ticks") spec.ticks = v;
        act.delay = spec;
        ref.list[ref.idx] = act;
      } else if (k === "branch") {
        const spec = act.branch && typeof act.branch === "object" ? act.branch : {};
        const ensureMetric = () => {
          const w = spec.when && typeof spec.when === "object" ? spec.when : {};
          const m = w.metric && typeof w.metric === "object" ? w.metric : {};
          w.metric = m;
          spec.when = w;
          return m;
        };
        const metric = ensureMetric();
        const sel = metric.selector && typeof metric.selector === "object" ? metric.selector : {};
        if (field === "when_preset") metric.preset = String(v || "");
        else if (field === "when_mode") metric.mode = String(v || "state");
        else if (field === "when_op") metric.op = String(v || ">=");
        else if (field === "when_value") metric.value = coerceMaybeNumberOrTemplate(v);
        else if (field === "when_window_ticks") metric.window_ticks = v;
        else if (field.startsWith("when_selector_")) {
          const kk = field.replace("when_selector_", "");
          if (kk === "ref_object_types") {
            sel.ref_object_types = String(v || "")
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean);
          } else {
            sel[kk] = v;
          }
          metric.selector = sel;
        } else {
          metric[field] = v;
        }
        if (!Array.isArray(spec.then)) spec.then = [];
        if (!Array.isArray(spec.else)) spec.else = [];
        if (!Array.isArray(spec.on_error)) spec.on_error = [];
        act.branch = spec;
        ref.list[ref.idx] = act;
      } else {
        return;
      }

      markDirty();
    };

    el.addEventListener(isSelect ? "change" : "input", onChange);
  });

  (E.innateRulesEditor || document).querySelectorAll(".ir-flow-editor button[data-flow-action]").forEach((btn) => {
    const actName = String(btn.dataset.flowAction || "");
    const host = btn.closest?.(".ir-flow-editor");
    if (!host) return;
    const rootType = String(host.dataset.flowRoot || "");
    const aidx = Number(host.dataset.aidx || "");

    btn.addEventListener("click", () => {
      const rootCfg = resolveFlowRootCfg(aidx, rootType);
      if (!rootCfg) return;

      if (actName === "add_action") {
        const listPath = String(btn.dataset.listPath || "");
        const listRef = _irFlowResolveListRef(rootCfg, listPath);
        if (!listRef) return;
        const sel = host.querySelector?.(`select.ir-flow-add-type[data-list-path=\"${CSS.escape(listPath)}\"]`);
        const t = sel ? String(sel.value || "log") : "log";
        listRef.list.push(_irFlowDefaultAction(t));
        markDirty();
        draw();
        return;
      }
      if (actName === "remove_action") {
        const apath = String(btn.dataset.apath || "");
        const ref = _irFlowResolveActionRef(rootCfg, apath);
        if (!ref) return;
        ref.list.splice(ref.idx, 1);
        markDirty();
        draw();
        return;
      }

      const addKey = (obj, base) => {
        const used = new Set(Object.keys(obj || {}));
        if (!used.has(base)) return base;
        for (let i = 2; i < 64; i++) {
          const k = `${base}${i}`;
          if (!used.has(k)) return k;
        }
        return `${base}_${Date.now()}`;
      };

      if (actName === "eu_add" || actName === "eu_remove") {
        const apath = String(btn.dataset.apath || "");
        const ref = _irFlowResolveActionRef(rootCfg, apath);
        if (!ref) return;
        const action = ref.action;
        if (_irFlowActionKey(action) !== "emotion_update") return;
        const payload = action.emotion_update && typeof action.emotion_update === "object" ? action.emotion_update : {};
        if (actName === "eu_add") {
          const k = addKey(payload, "DA");
          payload[k] = 0.0;
        } else {
          const row = Number(btn.dataset.row || "0");
          const entries = Object.entries(payload).filter(([kk]) => String(kk || "").trim());
          const key = entries[row]?.[0];
          if (key) delete payload[key];
        }
        action.emotion_update = payload;
        ref.list[ref.idx] = action;
        markDirty();
        draw();
        return;
      }

      if (actName === "at_param_add" || actName === "at_param_remove" || actName === "at_params_fill_focus" || actName === "at_params_fill_recall") {
        const apath = String(btn.dataset.apath || "");
        const ref = _irFlowResolveActionRef(rootCfg, apath);
        if (!ref) return;
        const action = ref.action;
        if (_irFlowActionKey(action) !== "action_trigger") return;
        const spec = action.action_trigger && typeof action.action_trigger === "object" ? action.action_trigger : {};
        const params = spec.params && typeof spec.params === "object" ? spec.params : {};

        if (actName === "at_param_add") {
          const k = addKey(params, "param");
          params[k] = "";
        } else if (actName === "at_param_remove") {
          const row = Number(btn.dataset.row || "0");
          const entries = Object.entries(params).filter(([kk]) => String(kk || "").trim());
          const key = entries[row]?.[0];
          if (key) delete params[key];
        } else if (actName === "at_params_fill_focus") {
          params.target_ref_object_id = params.target_ref_object_id || "{{{match_ref_object_id}}}";
          params.target_ref_object_type = params.target_ref_object_type || "{{{match_ref_object_type}}}";
          params.target_item_id = params.target_item_id || "{{{match_item_id}}}";
          params.target_display = params.target_display || "{{{match_display}}}";
          params.strength = params.strength || "{{{match_value}}}";
          params.focus_boost = params.focus_boost ?? 0.9;
          params.ttl_ticks = params.ttl_ticks ?? 2;
        } else if (actName === "at_params_fill_recall") {
          params.trigger_kind = params.trigger_kind || "{{{match_kind}}}";
          params.trigger_strength = params.trigger_strength || "{{{match_value}}}";
        }

        spec.params = params;
        action.action_trigger = spec;
        ref.list[ref.idx] = action;
        markDirty();
        draw();
        return;
      }
    });
  });

  document.querySelectorAll(".ir-remove-action").forEach((node) => {
    node.addEventListener("click", () => {
      const idx = findRuleIndex();
      if (idx < 0) return;
      const rule = doc.rules[idx];
      const actions = ensureThen(rule);
      const aidx = Number(node.dataset.idx || "0");
      actions.splice(aidx, 1);
      markDirty();
      draw();
    });
  });

  const addAction = (type) => {
    const idx = findRuleIndex();
    if (idx < 0) return;
    const rule = doc.rules[idx];
    ensureThen(rule).push(setActionType({}, type));
    markDirty();
    draw();
  };
  document.getElementById("irAddActionCfsEmitBtn")?.addEventListener("click", () => addAction("cfs_emit"));
  document.getElementById("irAddActionFocusBtn")?.addEventListener("click", () => addAction("focus"));
  document.getElementById("irAddActionEmitBtn")?.addEventListener("click", () => addAction("emit_script"));
  document.getElementById("irAddActionEmotionBtn")?.addEventListener("click", () => addAction("emotion_update"));
  document.getElementById("irAddActionTriggerBtn")?.addEventListener("click", () => addAction("action_trigger"));
  document.getElementById("irAddActionPoolEnergyBtn")?.addEventListener("click", () => addAction("pool_energy"));
  document.getElementById("irAddActionBindAttrBtn")?.addEventListener("click", () => addAction("pool_bind_attribute"));
  document.getElementById("irAddActionDelayBtn")?.addEventListener("click", () => addAction("delay"));
  document.getElementById("irAddActionBranchBtn")?.addEventListener("click", () => addAction("branch"));
  document.getElementById("irAddActionLogBtn")?.addEventListener("click", () => addAction("log"));

  // Graph editor / 图形编辑器（Phase B）
  document.getElementById("irGraphOpenBtn")?.addEventListener("click", () => {
    openIrGraphModalForSelectedRule();
  });

  // delete rule
  document.getElementById("irDeleteRuleBtn")?.addEventListener("click", () => {
    const idx = findRuleIndex();
    if (idx < 0) return;
    doc.rules.splice(idx, 1);
    S.innateRulesSelectedId = a(doc.rules)[0]?.id || null;
    markDirty();
    draw();
  });
}

function clauseToWhen(clause) {
  if (!clause || typeof clause !== "object") return null;
  if (clause.type === "cfs") {
    const kinds = a(clause.spec?.kinds);
    const node = { cfs: { kinds } };
    if (clause.spec?.min_strength !== "" && clause.spec?.min_strength !== undefined) node.cfs.min_strength = clause.spec.min_strength;
    if (clause.spec?.max_strength !== "" && clause.spec?.max_strength !== undefined) node.cfs.max_strength = clause.spec.max_strength;
    return node;
  }
  if (clause.type === "state_window") {
    const node = { state_window: {} };
    const spec = clause.spec || {};
    if (spec.stage) node.state_window.stage = spec.stage;
    if (spec.fast_cp_rise_min !== "" && spec.fast_cp_rise_min !== undefined) node.state_window.fast_cp_rise_min = spec.fast_cp_rise_min;
    if (spec.fast_cp_drop_min !== "" && spec.fast_cp_drop_min !== undefined) node.state_window.fast_cp_drop_min = spec.fast_cp_drop_min;
    if (spec.min_candidate_count !== "" && spec.min_candidate_count !== undefined) node.state_window.min_candidate_count = spec.min_candidate_count;
    const hints = a(spec.candidate_hint_any);
    if (hints.length) node.state_window.candidate_hint_any = hints;
    return node;
  }
  if (clause.type === "metric") {
    const spec = clause.spec || {};
    const node = { metric: {} };
    if (spec.preset) node.metric.preset = spec.preset;
    if (spec.metric) node.metric.metric = spec.metric;
    if (spec.channel) node.metric.channel = spec.channel;
    if (spec.mode) node.metric.mode = spec.mode;
    if (spec.op) node.metric.op = spec.op;
    if (spec.match_policy) node.metric.match_policy = spec.match_policy;
    if (spec.window_ticks !== "" && spec.window_ticks !== undefined) node.metric.window_ticks = spec.window_ticks;
    if (spec.value !== "" && spec.value !== undefined) node.metric.value = spec.value;
    if (spec.min !== "" && spec.min !== undefined) node.metric.min = spec.min;
    if (spec.max !== "" && spec.max !== undefined) node.metric.max = spec.max;
    if (spec.capture_as) node.metric.capture_as = spec.capture_as;
    if (spec.epsilon !== "" && spec.epsilon !== undefined) node.metric.epsilon = spec.epsilon;
    if (spec.prev_gate && typeof spec.prev_gate === "object") {
      const pg = spec.prev_gate || {};
      const pgOut = {};
      if (pg.op) pgOut.op = pg.op;
      if (pg.value !== "" && pg.value !== undefined) pgOut.value = pg.value;
      if (pg.min !== "" && pg.min !== undefined) pgOut.min = pg.min;
      if (pg.max !== "" && pg.max !== undefined) pgOut.max = pg.max;
      if (Object.keys(pgOut).length) node.metric.prev_gate = pgOut;
    }
    if (spec.note) node.metric.note = spec.note;
    if (spec.selector && typeof spec.selector === "object") {
      const sel = spec.selector || {};
      const selOut = {};
      if (sel.mode) selOut.mode = sel.mode;
      if (sel.ref_object_id) selOut.ref_object_id = sel.ref_object_id;
      if (sel.ref_object_type) selOut.ref_object_type = sel.ref_object_type;
      if (sel.item_id) selOut.item_id = sel.item_id;
      if (sel.contains_text) selOut.contains_text = sel.contains_text;
      if (sel.top_n !== "" && sel.top_n !== undefined) selOut.top_n = sel.top_n;
      const refTypes = a(sel.ref_object_types);
      if (refTypes.length) selOut.ref_object_types = refTypes;
      if (Object.keys(selOut).length) node.metric.selector = selOut;
    }
    return node;
  }
  const spec = clause.spec || {};
  const node = { timer: {} };
  if (spec.every_n_ticks !== "" && spec.every_n_ticks !== undefined) node.timer.every_n_ticks = spec.every_n_ticks;
  if (spec.at_tick !== "" && spec.at_tick !== undefined) node.timer.at_tick = spec.at_tick;
  return node;
}

// =====================================================================
// Innate Rules Graph Editor (Phase B)
// 先天规则图形编排（B目标）
//
// Design / 设计原则：
// - Graph is only an editor UX. The canonical data is still YAML rules (when/then).
//   图形只是编辑体验，最终仍编译回 YAML 的 when/then。
// - Keep it safe: no code execution, only structured data.
//   保持安全：不执行代码，只处理结构化数据。
// =====================================================================

function openIrGraphModalForSelectedRule() {
  const selected = _getSelectedIrRuleRef();
  if (!selected) {
    fb("请先在左侧选择一条规则。", true);
    return;
  }
  if (!E.irGraphModal || !E.irGraphCanvas || !E.irGraphWorld || !E.irGraphEdges || !E.irGraphNodes || !E.irGraphProps) {
    fb("图形编辑器 UI 缺失（请刷新页面）。", true);
    return;
  }

  // Update viewport vars before showing the modal (stability on first paint).
  // 在显示弹窗前同步视口变量，提升“初次打开布局稳定性”。
  syncViewportVars();

  S.irGraph.open = true;
  S.irGraph.ruleId = selected.rule.id;
  S.irGraph.selectedNodeId = null;
  S.irGraph.selectedEdgeId = null;
  S.irGraph.connectingFrom = null;
  S.irGraph.dirty = false;

  S.irGraph.graph = _loadIrGraphFromRule(selected.rule);
  // Restore view if saved in rule UI / 若规则里保存过视图信息则恢复
  const savedZoom = Number(S.irGraph.graph?.view?.zoom || "");
  if (Number.isFinite(savedZoom) && savedZoom > 0) S.irGraph.view.zoom = savedZoom;
  // Restore panel visibility + fullscreen preference (if saved).
  // 恢复侧栏显隐 + 全屏偏好（若规则里保存过）。
  try {
    const v = S.irGraph.graph?.view;
    if (v && typeof v === "object") {
      if (v.showPalette !== undefined) S.irGraph.view.showPalette = Boolean(v.showPalette);
      if (v.showProps !== undefined) S.irGraph.view.showProps = Boolean(v.showProps);
      if (v.fullscreen !== undefined) S.irGraph.view.fullscreen = Boolean(v.fullscreen);
    }
  } catch {}

  E.irGraphModal.classList.remove("hidden");
  E.irGraphModal.setAttribute("aria-hidden", "false");
  _applyIrGraphFullscreen();

  // Ensure the modal starts at the top so the toolbar is always visible.
  // 确保弹窗打开时处于顶部：避免“小窗口/分屏”时顶部工具栏被挤出可视区。
  try {
    // Reset outer modal scroll as well (some browsers/webviews scroll the container, not the card).
    // 同时重置外层容器滚动：某些浏览器/嵌入式 WebView 会滚动 .modal 本身，而不是 .modal-card。
    E.irGraphModal.scrollTop = 0;
    E.irGraphModal.scrollLeft = 0;
    const card = E.irGraphModal.querySelector?.(".modal-card");
    const body = E.irGraphModal.querySelector?.(".modal-card-body");
    if (card) {
      // Modal-card itself is non-scrollable, but some webviews keep scroll offsets anyway.
      // modal-card 本身不滚动，但部分 WebView 仍会保留滚动偏移，这里做防御性归零。
      card.scrollTop = 0;
      card.scrollLeft = 0;
    }
    if (body) {
      body.scrollTop = 0;
      body.scrollLeft = 0;
      // Some browsers only apply scroll after layout; keep a tiny deferred reset.
      // 有些浏览器需要等布局完成后才生效，因此做一次微延迟归零。
      setTimeout(() => {
        try {
          E.irGraphModal.scrollTop = 0;
          E.irGraphModal.scrollLeft = 0;
          if (card) {
            card.scrollTop = 0;
            card.scrollLeft = 0;
          }
          if (body) {
            body.scrollTop = 0;
            body.scrollLeft = 0;
          }
        } catch {}
      }, 0);
    }
  } catch {}
  _applyIrGraphLayoutVisibility();
  _ensureIrGraphEventBindings();
  renderIrGraph();
  // Restore scroll position if saved; otherwise fit-to-view.
  // 若保存过滚动位置则恢复；否则做一次“适配视图”，避免节点跑出右侧导致看不到。
  setTimeout(() => {
    const wrap = _irGraphWrap();
    const savedLeft = Number(S.irGraph.graph?.view?.scroll_left ?? "");
    const savedTop = Number(S.irGraph.graph?.view?.scroll_top ?? "");
    const hasSavedScroll = wrap && Number.isFinite(savedLeft) && Number.isFinite(savedTop) && (savedLeft > 0 || savedTop > 0);
    if (wrap && hasSavedScroll) {
      wrap.scrollLeft = Math.max(0, savedLeft);
      wrap.scrollTop = Math.max(0, savedTop);
      _setIrGraphHint(`已恢复视图（zoom=${Math.round(_irGraphZoom() * 100)}%，scroll=${Math.round(wrap.scrollLeft)}/${Math.round(wrap.scrollTop)}）`);
    } else if (!Number.isFinite(savedZoom) || savedZoom <= 0) {
      irGraphFitToView();
    } else {
      // If zoom exists but no scroll state, still try a gentle fit-to-view when nodes are likely out of view.
      // 若只有 zoom 没有 scroll：仍尝试做一次温和“适配”，避免用户打开就看不到节点。
      try {
        const b = _irGraphNodeBounds(S.irGraph.graph);
        if (wrap && b && (b.maxX > 1600 || b.maxY > 1200)) {
          irGraphFitToView();
        }
      } catch {}
    }
    _irGraphSyncZoomUi();
    // Best-effort: ensure the header/toolbars are visible after layout.
    // 尽力保证顶部工具栏可见（布局完成后再对齐一次）。
    try {
      const head = E.irGraphModal.querySelector?.(".ir-graph-head");
      head?.scrollIntoView?.({ block: "start", inline: "nearest" });
    } catch {}
    // Force a layout pass in some webviews where flex/range layout updates only after resize/reflow.
    // 在某些 WebView 里，flex/range（缩放滑块）布局需要“类似 resize 的重排”才会稳定显示。
    try {
      syncViewportVars();
      const card = E.irGraphModal.querySelector?.(".modal-card");
      // Touch layout to force reflow / 读取一次布局，触发重排
      card?.getBoundingClientRect?.();
      window.dispatchEvent(new Event("resize"));
      // A second deferred nudge helps stubborn webviews.
      // 再做一次微延迟触发，覆盖更顽固的 WebView。
      setTimeout(() => {
        try {
          syncViewportVars();
          card?.getBoundingClientRect?.();
          window.dispatchEvent(new Event("resize"));
        } catch {}
      }, 50);
    } catch {}
  }, 0);
}

function closeIrGraphModal() {
  if (!E.irGraphModal) return;
  if (S.irGraph.open && S.irGraph.dirty) {
    // Prevent accidental loss: many users assume closing == saving.
    // 防止误关导致丢失：很多用户会下意识认为“关闭=已保存”。
    const ok = confirm("图形编辑器还有未应用到规则的更改。\n\n你确定要直接关闭并丢弃这些更改吗？\n\n提示：点击「应用到规则（Apply）」才会写回规则草稿。");
    if (!ok) return;
  }
  E.irGraphModal.classList.add("hidden");
  E.irGraphModal.setAttribute("aria-hidden", "true");
  S.irGraph.open = false;
  S.irGraph.ruleId = null;
  S.irGraph.graph = null;
  S.irGraph.dirty = false;
  S.irGraph.selectedNodeId = null;
  S.irGraph.selectedEdgeId = null;
  S.irGraph.connectingFrom = null;
  S.irGraph._spaceDown = false;
}

function syncIrGraphFromSelectedRule() {
  if (!S.irGraph.open) {
    fb("请先打开图形编辑器。", true);
    return;
  }
  const selected = _getSelectedIrRuleRef();
  if (!selected) return;
  S.irGraph.graph = _buildIrGraphFromRule(selected.rule);
  S.irGraph.dirty = false;
  S.irGraph.selectedNodeId = null;
  S.irGraph.selectedEdgeId = null;
  S.irGraph.connectingFrom = null;
  irGraphFb("已从规则重新生成图形。", "ok");
  renderIrGraph();
}

function applyIrGraphToSelectedRule() {
  if (!S.irGraph.open || !S.irGraph.graph) {
    fb("图形编辑器未打开。", true);
    return;
  }
  const selected = _getSelectedIrRuleRef();
  if (!selected) return;
  if (String(selected.rule.id || "") !== String(S.irGraph.ruleId || "")) {
    fb("当前选中的规则已变化，请重新打开图形编辑器。", true);
    return;
  }

  const compiled = _compileIrGraphToRule(S.irGraph.graph);
  if (!compiled.ok) {
    irGraphFb(`应用失败：${compiled.message || "unknown error"}`, "err");
    _setIrGraphHint(`应用失败：${compiled.message || "-"}`);
    return;
  }

  selected.rule.when = compiled.when;
  selected.rule.then = compiled.then;
  if (!selected.rule.ui || typeof selected.rule.ui !== "object") selected.rule.ui = {};
  // Persist view zoom for better UX / 保存视图缩放，便于下次打开继续编辑
  if (!S.irGraph.graph.view || typeof S.irGraph.graph.view !== "object") S.irGraph.graph.view = {};
  S.irGraph.graph.view.zoom = Number(S.irGraph.view?.zoom || 1.0) || 1.0;
  // Persist scroll + panel visibility so opening the editor won't “lose the canvas”.
  // 保存滚动位置与侧栏显隐：避免下次打开时节点跑到右侧/下方看不到（误以为无法删除/编辑）。
  try {
    const wrap = _irGraphWrap();
    if (wrap) {
      S.irGraph.graph.view.scroll_left = Math.max(0, Number(wrap.scrollLeft || 0));
      S.irGraph.graph.view.scroll_top = Math.max(0, Number(wrap.scrollTop || 0));
    }
  } catch {}
  S.irGraph.graph.view.showPalette = S.irGraph.view?.showPalette !== false;
  S.irGraph.graph.view.showProps = S.irGraph.view?.showProps !== false;
  S.irGraph.graph.view.fullscreen = Boolean(S.irGraph.view?.fullscreen);
  selected.rule.ui.graph = deepClone(S.irGraph.graph);
  selected.rule.ui.graph_saved_at_ms = Date.now();

  S.innateRulesDirty = true;
  irFb("已将图形应用到规则草稿。下一步：校验 -> 保存并热加载。", "ok");
  fb("已将图形应用到规则草稿。下一步：校验 -> 保存并热加载。");
  closeIrGraphModal();
  draw();
}

function irGraphAddNode(type) {
  if (!S.irGraph.open || !S.irGraph.graph) {
    fb("请先打开图形编辑器。", true);
    return;
  }
  const g = S.irGraph.graph;
  const root = _ensureIrGraphRoot(g);
  const node = _newIrGraphNode(g, type);

  // Position presets / 默认摆放位置
  if (_isIrGraphActionType(type)) {
    node.x = 720;
    node.y = 120 + _countIrGraphNodesByKind(g, "action") * 160;
  } else {
    node.x = 80;
    node.y = 120 + _countIrGraphNodesByKind(g, "condition") * 150;
  }

  g.nodes.push(node);

  // Auto-wire the common pattern / 自动连接常见模式
  if (_isIrGraphConditionNode(node)) {
    _upsertIrGraphEdge(g, { from: node.id, to: root.id });
  } else if (_isIrGraphActionNode(node)) {
    _upsertIrGraphEdge(g, { from: root.id, to: node.id, replaceTo: true });
  }

  S.irGraph.selectedNodeId = node.id;
  S.irGraph.selectedEdgeId = null;
  _markIrGraphDirty();
  renderIrGraph();
}

function deleteSelectedIrGraphNode() {
  if (!S.irGraph.open || !S.irGraph.graph) return;
  const g = S.irGraph.graph;
  const nid = String(S.irGraph.selectedNodeId || "");
  if (!nid) {
    irGraphFb("请先选中一个节点。提示：点击节点可选中；也可先选中连线后按 Del 删除。", "err");
    return;
  }
  const node = _findIrGraphNode(g, nid);
  if (!node) return;
  if (node.type === "root") {
    irGraphFb("条件汇总节点不可删除。", "err");
    return;
  }
  g.nodes = a(g.nodes).filter((n) => n?.id !== nid);
  g.edges = a(g.edges).filter((e) => e?.from !== nid && e?.to !== nid);
  S.irGraph.selectedNodeId = null;
  S.irGraph.selectedEdgeId = null;
  S.irGraph.connectingFrom = null;
  _markIrGraphDirty();
  renderIrGraph();
}

function irGraphDeleteSelectedFromToolbar() {
  if (!S.irGraph.open || !S.irGraph.graph) return;
  const g = S.irGraph.graph;

  // Prefer deleting a selected edge if any.
  // 优先删除被选中的连线（若存在）。
  if (S.irGraph.selectedEdgeId) {
    const ok = confirm("确定删除选中的连线吗？");
    if (!ok) return;
    deleteSelectedIrGraphEdge();
    return;
  }

  const nid = String(S.irGraph.selectedNodeId || "");
  if (!nid) {
    irGraphFb("请先选中一个节点或连线。", "err");
    return;
  }
  const node = _findIrGraphNode(g, nid);
  if (!node) return;
  if (String(node.type || "") === "root") {
    irGraphFb("条件汇总节点不可删除。", "err");
    return;
  }
  const ok = confirm(`确定删除选中的节点「${_irGraphNodeTitle(node)}」吗？\\n\\n说明：将同时删除与它相关的连线。`);
  if (!ok) return;
  deleteSelectedIrGraphNode();
}

function deleteSelectedIrGraphEdge() {
  if (!S.irGraph.open || !S.irGraph.graph) return;
  const g = S.irGraph.graph;
  const eid = String(S.irGraph.selectedEdgeId || "");
  if (!eid) {
    irGraphFb("请先选中一条连线。提示：点击连线即可选中。", "err");
    return;
  }
  g.edges = a(g.edges).filter((e) => String(e?.id || "") !== eid);
  S.irGraph.selectedEdgeId = null;
  S.irGraph.connectingFrom = null;
  _markIrGraphDirty();
  renderIrGraph();
}

function renderIrGraph() {
  if (!S.irGraph.open || !S.irGraph.graph) return;
  const g = S.irGraph.graph;
  if (!E.irGraphCanvas || !E.irGraphWorld || !E.irGraphEdges || !E.irGraphNodes) return;

  // Sync world size + zoom before drawing nodes/edges.
  // 同步“世界尺寸 + 缩放”，确保节点不会被裁掉且可滚动查看。
  _irGraphSyncWorldLayout(g);

  // ---- hint ----
  const root = _ensureIrGraphRoot(g);
  const mode = String(root.config?.mode || "any");
  const dirty = S.irGraph.dirty ? "已修改（未应用）" : "未修改";
  const modeLabel = mode === "all" ? "同时（all）" : "任一（any）";
  const connecting = S.irGraph.connectingFrom ? ` | 正在连线：${S.irGraph.connectingFrom}` : "";
  const selNode = S.irGraph.selectedNodeId ? _findIrGraphNode(g, String(S.irGraph.selectedNodeId)) : null;
  const selNodeText = selNode ? ` | 已选中节点：${_irGraphNodeTitle(selNode)}（${String(selNode.type || "")}）` : "";
  const selEdgeText = S.irGraph.selectedEdgeId ? ` | 已选中连线：${String(S.irGraph.selectedEdgeId || "")}` : "";
  _setIrGraphHint(
    `规则 ${S.irGraph.ruleId || "-"} | 模式 ${modeLabel} | 图形 ${dirty}${connecting}${selNodeText}${selEdgeText} | 快捷键：Del 删除 / Esc 取消连线（或关闭）`,
  );

  // Top toolbar: make deletion discoverable.
  // 顶部工具栏：让删除入口更“显眼可用”，避免用户误以为只能新增不能删除。
  if (E.irGraphDeleteSelectedBtn2) {
    const edgeSelected = Boolean(S.irGraph.selectedEdgeId);
    const nodeSelected = Boolean(S.irGraph.selectedNodeId);
    const nodeIsRoot = selNode && String(selNode.type || "") === "root";
    const enabled = edgeSelected || (nodeSelected && !nodeIsRoot);
    E.irGraphDeleteSelectedBtn2.disabled = !enabled;
    if (edgeSelected) E.irGraphDeleteSelectedBtn2.textContent = "删除连线（Del）";
    else if (nodeSelected && !nodeIsRoot) E.irGraphDeleteSelectedBtn2.textContent = "删除节点（Del）";
    else E.irGraphDeleteSelectedBtn2.textContent = "删除选中（Del）";
  }
  // Left palette delete buttons / 左侧删除按钮也做联动禁用，避免“按了没反应”。
  if (E.irGraphDeleteNodeBtn) {
    const nodeSelected = Boolean(S.irGraph.selectedNodeId);
    const nodeIsRoot = selNode && String(selNode.type || "") === "root";
    E.irGraphDeleteNodeBtn.disabled = !(nodeSelected && !nodeIsRoot);
  }
  if (E.irGraphDeleteEdgeBtn) {
    E.irGraphDeleteEdgeBtn.disabled = !Boolean(S.irGraph.selectedEdgeId);
  }

  // ---- nodes ----
  E.irGraphNodes.innerHTML = a(g.nodes)
    .map((node) => _renderIrGraphNodeHtml(node))
    .join("");

  // bind node events
  E.irGraphNodes.querySelectorAll(".ir-node").forEach((nodeEl) => {
    const nodeId = String(nodeEl.dataset.nodeId || "");
    const head = nodeEl.querySelector(".ir-node-head");
    head?.addEventListener("mousedown", (event) => _startIrGraphDrag(event, nodeId));
    nodeEl.addEventListener("click", (event) => {
      event.stopPropagation();
      _selectIrGraphNode(nodeId);
    });
    // Node-level delete button is more discoverable than the left panel.
    // 节点头部的“删除”按钮更符合常见编辑器习惯，也更不容易被布局挤没。
    const delBtn = nodeEl.querySelector(".ir-node-del");
    delBtn?.addEventListener("mousedown", (event) => {
      // Prevent drag start when clicking delete.
      // 点击删除时不要触发拖拽。
      event.stopPropagation();
    });
    delBtn?.addEventListener("click", (event) => {
      event.stopPropagation();
      if (!S.irGraph.graph) return;
      const node = _findIrGraphNode(S.irGraph.graph, nodeId);
      if (!node) return;
      if (String(node.type || "") === "root") {
        irGraphFb("条件汇总节点不可删除。", "err");
        return;
      }
      S.irGraph.selectedNodeId = nodeId;
      S.irGraph.selectedEdgeId = null;
      const title = _irGraphNodeTitle(node);
      const ok = confirm(`确定删除节点「${title}」吗？\\n\\n说明：将同时删除与它相关的连线。`);
      if (!ok) return;
      deleteSelectedIrGraphNode();
    });
    nodeEl.querySelectorAll(".ir-port").forEach((portEl) => {
      const port = String(portEl.dataset.port || "");
      portEl.addEventListener("click", (event) => {
        event.stopPropagation();
        _handleIrGraphPortClick(nodeId, port);
      });
    });
  });

  // ---- edges ----
  requestAnimationFrame(() => renderIrGraphEdges());

  // ---- props ----
  renderIrGraphProps();
}

function renderIrGraphEdges(mousePos) {
  if (!S.irGraph.open || !S.irGraph.graph) return;
  if (!E.irGraphEdges || !E.irGraphWorld) return;
  const g = S.irGraph.graph;
  const worldW = Number(S.irGraph.world?.width || 0) || 1200;
  const worldH = Number(S.irGraph.world?.height || 0) || 720;
  E.irGraphEdges.setAttribute("width", String(worldW));
  E.irGraphEdges.setAttribute("height", String(worldH));
  E.irGraphEdges.setAttribute("viewBox", `0 0 ${worldW} ${worldH}`);

  const paths = [];
  for (const edge of a(g.edges)) {
    if (!edge || typeof edge !== "object") continue;
    const eid = String(edge.id || "");
    const from = String(edge.from || "");
    const to = String(edge.to || "");
    const p1 = _irGraphPortPos(from, "out");
    const p2 = _irGraphPortPos(to, "in");
    if (!p1 || !p2) continue;
    const active = eid && eid === String(S.irGraph.selectedEdgeId || "");
    paths.push(`<path class="ir-edge-path ${active ? "active" : ""}" data-edge-id="${esc(eid)}" d="${_irGraphCurve(p1, p2)}"></path>`);
  }

  // Preview edge when connecting / 连线预览
  if (S.irGraph.connectingFrom) {
    const p1 = _irGraphPortPos(String(S.irGraph.connectingFrom), "out");
    if (p1 && mousePos && typeof mousePos.x === "number" && typeof mousePos.y === "number") {
      const p2 = { x: mousePos.x, y: mousePos.y };
      paths.push(`<path class="ir-edge-path active" data-edge-id="__preview__" d="${_irGraphCurve(p1, p2)}"></path>`);
    }
  }

  E.irGraphEdges.innerHTML = paths.join("");
  E.irGraphEdges.querySelectorAll(".ir-edge-path").forEach((pathEl) => {
    const eid = String(pathEl.dataset.edgeId || "");
    if (!eid || eid === "__preview__") return;
    pathEl.addEventListener("click", (event) => {
      event.stopPropagation();
      _selectIrGraphEdge(eid);
    });
  });
}

// =====================================================================
// Graph Flow Editor (Nested Actions) / 图形编辑器：动作流（支持 delay/branch 嵌套）
// =====================================================================

function _irFlowActionKey(action) {
  if (!action || typeof action !== "object") return "";
  const k = Object.keys(action)[0];
  return k ? String(k) : "";
}

function _irFlowActionTitle(action) {
  const k = _irFlowActionKey(action);
  const spec = k && action && typeof action === "object" ? action[k] : null;
  if (k === "log") return "日志（log）";
  if (k === "cfs_emit") return `认知感受生成（cfs_emit）:${String(spec?.kind || "-")}`;
  if (k === "focus") return "聚焦指令（focus）";
  if (k === "emit_script") return `触发记录（emit_script）:${String(spec?.script_id || "-")}`;
  if (k === "emotion_update") return "情绪更新（emotion_update）";
  if (k === "action_trigger") return `行动触发（action_trigger）:${String(spec?.action_kind || "-")}`;
  if (k === "pool_energy") return "对对象赋能量（pool_energy）";
  if (k === "pool_bind_attribute") return "绑定属性（pool_bind_attribute）";
  if (k === "delay") return `延时（delay）:${String(spec?.ticks ?? 1)} tick`;
  if (k === "branch") return "分支（branch）";
  return k || "动作";
}

function _irFlowDefaultAction(type) {
  const t = String(type || "log");
  if (t === "cfs_emit") {
    return {
      cfs_emit: {
        kind: "dissonance",
        scope: "object",
        from: "metric_matches",
        max_signals: 1,
        strength: { from: "match_value", policy: "linear_clamp", min: 0.0, max: 1.0, out_min: 0.0, out_max: 1.0 },
        bind_attribute: null,
      },
    };
  }
  if (t === "focus") {
    return {
      focus: {
        from: "cfs_matches",
        match_policy: "all",
        ttl_ticks: 2,
        focus_boost: 0.9,
        deduplicate_by: "target_ref_object_id",
      },
    };
  }
  if (t === "emit_script") return { emit_script: { script_id: "custom_script", script_kind: "custom", priority: 50, trigger: "" } };
  if (t === "emotion_update") return { emotion_update: { DA: 0.0 } };
  if (t === "action_trigger") return { action_trigger: { action_id: "custom_action", action_kind: "custom", gain: 0.3, threshold: 1.0, cooldown_ticks: 0, params: {} } };
  if (t === "pool_energy") return { pool_energy: { selector: { mode: "all" }, delta_er: 0.0, delta_ev: 0.0, create_if_missing: false, create_ref_object_type: "sa", create_display: "", reason: "" } };
  if (t === "pool_bind_attribute") return { pool_bind_attribute: { selector: { mode: "all" }, attribute: { attribute_name: "", attribute_value: "", raw: "", display: "", value_type: "discrete", modality: "internal", er: 0.0, ev: 0.0 }, reason: "" } };
  if (t === "delay") return { delay: { ticks: 2, then: [{ log: "延时触发（示例）" }] } };
  if (t === "branch") {
    return {
      branch: {
        when: { metric: { preset: "reward_state", mode: "state", op: ">", value: 0 } },
        then: [{ log: "满足条件（then）" }],
        else: [{ log: "不满足（else）" }],
        on_error: [{ log: "条件报错（on_error）" }],
      },
    };
  }
  return { log: "" };
}

function _irFlowResolveListRef(rootCfg, listPath) {
  const parts = String(listPath || "").split(".").map((s) => s.trim()).filter(Boolean);
  if (!parts.length || parts.length % 2 === 0) return null; // must end with list name
  let obj = rootCfg;
  for (let i = 0; i < parts.length - 1; i += 2) {
    const listName = parts[i];
    const idx = Number(parts[i + 1] || "");
    if (!listName || !Number.isFinite(idx)) return null;
    if (!Array.isArray(obj[listName])) obj[listName] = [];
    const act = obj[listName][idx];
    const key = _irFlowActionKey(act);
    const spec = key && act && typeof act === "object" ? act[key] : null;
    if (!spec || typeof spec !== "object") return null;
    obj = spec;
  }
  const last = parts[parts.length - 1];
  if (!last) return null;
  if (!Array.isArray(obj[last])) obj[last] = [];
  return { obj, listName: last, list: obj[last] };
}

function _irFlowResolveActionRef(rootCfg, apath) {
  const parts = String(apath || "").split(".").map((s) => s.trim()).filter(Boolean);
  if (parts.length < 2 || parts.length % 2 !== 0) return null; // must end with index
  const listPath = parts.slice(0, -1).join(".");
  const listRef = _irFlowResolveListRef(rootCfg, listPath);
  if (!listRef) return null;
  const idx = Number(parts[parts.length - 1] || "");
  if (!Number.isFinite(idx)) return null;
  if (idx < 0 || idx >= listRef.list.length) return null;
  return { ...listRef, idx, action: listRef.list[idx] };
}

function _irFlowActionTypeOptionsHtml(selectedType) {
  const sel = String(selectedType || "log");
  const opt = (v, label) => `<option value="${esc(v)}" ${sel === v ? "selected" : ""}>${esc(label)}</option>`;
  return [
    opt("cfs_emit", "认知感受生成（cfs_emit）"),
    opt("focus", "聚焦指令（focus）"),
    opt("emit_script", "触发记录（emit_script）"),
    opt("emotion_update", "情绪更新（emotion_update）"),
    opt("action_trigger", "行动触发（action_trigger）"),
    opt("pool_energy", "对对象赋能量（pool_energy）"),
    opt("pool_bind_attribute", "绑定属性（pool_bind_attribute）"),
    opt("delay", "延时（delay）"),
    opt("branch", "分支（branch）"),
    opt("log", "日志（log）"),
  ].join("");
}

function _irFlowMetricPresetOptionsHtml(selectedPreset) {
  const presets = a(S.innateRulesBundle?.metric_presets);
  const groups = {};
  for (const p of presets) {
    if (!p || typeof p !== "object") continue;
    const gName = String(p.group_zh || "其他");
    if (!groups[gName]) groups[gName] = [];
    groups[gName].push(p);
  }
  const groupNames = Object.keys(groups).sort();
  const current = String(selectedPreset || "");
  const optGroups = groupNames
    .map((gName) => {
      const opts = a(groups[gName])
        .map((p) => {
          const name = String(p.preset || "");
          const label = String(p.label_zh || name);
          const selected = current === name ? "selected" : "";
          return `<option value="${esc(name)}" ${selected}>${esc(label)}（${esc(name)}）</option>`;
        })
        .join("");
      return `<optgroup label="${esc(gName)}">${opts}</optgroup>`;
    })
    .join("");
  return `<option value="">（不使用预设）</option>${optGroups}`;
}

function _irFlowRowHtml({ label, apath, field, value, kind = "text", extra = "" }) {
  const safe = value === undefined || value === null ? "" : String(value);
  const attrs = `data-apath="${esc(apath)}" data-field="${esc(field)}"`;
  if (kind === "textarea") {
    return `<article class="setting-item"><label>${esc(label)}</label><textarea class="ir-flow-prop" ${attrs}>${esc(safe)}</textarea>${extra}</article>`;
  }
  if (kind === "checkbox") {
    const checked = value ? "checked" : "";
    return `<article class="setting-item"><label>${esc(label)}</label><label class="toggle-row"><input class="ir-flow-prop" ${attrs} type="checkbox" ${checked} /><span>启用</span></label>${extra}</article>`;
  }
  return `<article class="setting-item"><label>${esc(label)}</label><input class="ir-flow-prop" ${attrs} type="${esc(kind)}" value="${esc(safe)}" />${extra}</article>`;
}

function _irFlowRenderActionFields(action, apath, depth) {
  const k = _irFlowActionKey(action) || "log";
  const spec = k && action && typeof action === "object" ? action[k] : null;

  if (k === "log") {
    return `<div class="settings-grid">${_irFlowRowHtml({ label: "日志内容（log）", apath, field: "log", value: action.log || "", kind: "textarea" })}</div>`;
  }

  if (k === "cfs_emit") {
    const cfg = spec && typeof spec === "object" ? spec : {};
    const st = cfg.strength && typeof cfg.strength === "object" ? cfg.strength : {};
    const b = cfg.bind_attribute && typeof cfg.bind_attribute === "object" ? cfg.bind_attribute : null;
    const bindEnabled = b !== null;
    const stFrom = String(st.from || "match_value");
    const stPolicy = String(st.policy || "linear_clamp");

    const strengthKnobsHtml = (() => {
      if (stPolicy === "verify_mix") {
        return [
          `<article class="setting-item"><label>verify_mix.part</label>`,
          `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="strength_part">`,
          `<option value="verified" ${String(st.part || "verified") === "verified" ? "selected" : ""}>verified（偏实）</option>`,
          `<option value="unverified" ${String(st.part || "") === "unverified" ? "selected" : ""}>unverified（偏虚）</option>`,
          `</select></article>`,
          _irFlowRowHtml({ label: "pred_var（预测量变量名）", apath, field: "strength_pred_var", value: st.pred_var || "", kind: "text" }),
          _irFlowRowHtml({ label: "actual_var（实际量变量名）", apath, field: "strength_actual_var", value: st.actual_var || "", kind: "text" }),
          _irFlowRowHtml({ label: "pred_scale", apath, field: "strength_pred_scale", value: st.pred_scale ?? 1.0, kind: "number" }),
          _irFlowRowHtml({ label: "actual_scale", apath, field: "strength_actual_scale", value: st.actual_scale ?? 1.0, kind: "number" }),
          _irFlowRowHtml({ label: "gamma", apath, field: "strength_gamma", value: st.gamma ?? 1.0, kind: "number" }),
          _irFlowRowHtml({ label: "eps", apath, field: "strength_eps", value: st.eps ?? 1e-6, kind: "number" }),
        ].join("");
      }
      if (stPolicy === "scale_offset") {
        return [
          _irFlowRowHtml({ label: "scale", apath, field: "strength_scale", value: st.scale ?? 1.0, kind: "number" }),
          _irFlowRowHtml({ label: "offset", apath, field: "strength_offset", value: st.offset ?? 0.0, kind: "number" }),
        ].join("");
      }
      return [
        _irFlowRowHtml({ label: "min", apath, field: "strength_min", value: st.min ?? 0.0, kind: "number" }),
        _irFlowRowHtml({ label: "max", apath, field: "strength_max", value: st.max ?? 1.0, kind: "number" }),
        _irFlowRowHtml({ label: "out_min", apath, field: "strength_out_min", value: st.out_min ?? 0.0, kind: "number" }),
        _irFlowRowHtml({ label: "out_max", apath, field: "strength_out_max", value: st.out_max ?? 1.0, kind: "number" }),
      ].join("");
    })();
    return [
      `<div class="settings-grid">`,
      _irFlowRowHtml({ label: "感受类型（kind）", apath, field: "kind", value: cfg.kind || "", kind: "text" }),
      `<article class="setting-item"><label>作用域（scope）</label>`,
      `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="scope">`,
      `<option value="object" ${String(cfg.scope || "object") === "object" ? "selected" : ""}>对象级（object）</option>`,
      `<option value="global" ${String(cfg.scope || "") === "global" ? "selected" : ""}>全局（global）</option>`,
      `</select></article>`,
      `<article class="setting-item"><label>来源（from）</label>`,
      `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="from">`,
      `<option value="metric_matches" ${String(cfg.from || "metric_matches") === "metric_matches" ? "selected" : ""}>metric_matches</option>`,
      `<option value="cfs_matches" ${String(cfg.from || "") === "cfs_matches" ? "selected" : ""}>cfs_matches</option>`,
      `<option value="single" ${String(cfg.from || "") === "single" ? "selected" : ""}>single</option>`,
      `</select></article>`,
      `<div class="sub-section"><div class="sub-title">强度（strength）</div>`,
      `<div class="settings-grid">`,
      `<article class="setting-item"><label>strength.policy</label>`,
      `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="strength_policy">`,
      `<option value="linear_clamp" ${stPolicy === "linear_clamp" ? "selected" : ""}>linear_clamp</option>`,
      `<option value="scale_offset" ${stPolicy === "scale_offset" ? "selected" : ""}>scale_offset</option>`,
      `<option value="verify_mix" ${stPolicy === "verify_mix" ? "selected" : ""}>verify_mix</option>`,
      `</select></article>`,
      `<article class="setting-item"><label>strength.from</label>`,
      `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="strength_from">`,
      `<option value="match_value" ${stFrom === "match_value" ? "selected" : ""}>match_value</option>`,
      `<option value="var" ${stFrom === "var" ? "selected" : ""}>var</option>`,
      `</select></article>`,
      _irFlowRowHtml({ label: "strength.var（from=var 用）", apath, field: "strength_var", value: st.var || "", kind: "text" }),
      strengthKnobsHtml,
      `</div></div>`,
      `<div class="sub-section"><div class="sub-title">绑定属性（bind_attribute）</div>`,
      `<article class="setting-item"><label>启用绑定</label>`,
      `<label class="toggle-row"><input class="ir-flow-prop" data-apath="${esc(apath)}" data-field="bindattr_enabled" type="checkbox" ${bindEnabled ? "checked" : ""} /><span>绑定到目标对象</span></label>`,
      `</article>`,
      _irFlowRowHtml({ label: "attribute_name", apath, field: "bindattr_attribute_name", value: (b || {}).attribute_name || "", kind: "text" }),
      _irFlowRowHtml({ label: "display（可选）", apath, field: "bindattr_display", value: (b || {}).display || "", kind: "text" }),
      `</div>`,
      `</div>`,
    ].join("");
  }

  if (k === "focus") {
    const cfg = spec && typeof spec === "object" ? spec : {};
    return [
      `<div class="settings-grid">`,
      `<article class="setting-item"><label>来源（from）</label>`,
      `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="from">`,
      `<option value="cfs_matches" ${String(cfg.from || "cfs_matches") === "cfs_matches" ? "selected" : ""}>cfs_matches</option>`,
      `<option value="state_window_candidates" ${String(cfg.from || "") === "state_window_candidates" ? "selected" : ""}>state_window_candidates</option>`,
      `</select></article>`,
      _irFlowRowHtml({ label: "ttl_ticks", apath, field: "ttl_ticks", value: cfg.ttl_ticks ?? 2, kind: "number" }),
      _irFlowRowHtml({ label: "focus_boost", apath, field: "focus_boost", value: cfg.focus_boost ?? 0.9, kind: "number" }),
      `</div>`,
    ].join("");
  }

  if (k === "emit_script") {
    const cfg = spec && typeof spec === "object" ? spec : {};
    return [
      `<div class="settings-grid">`,
      _irFlowRowHtml({ label: "script_id", apath, field: "script_id", value: cfg.script_id ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "script_kind", apath, field: "script_kind", value: cfg.script_kind ?? "custom", kind: "text" }),
      _irFlowRowHtml({ label: "priority", apath, field: "priority", value: cfg.priority ?? 50, kind: "number" }),
      _irFlowRowHtml({ label: "trigger（可选）", apath, field: "trigger", value: cfg.trigger ?? "", kind: "text" }),
      `</div>`,
    ].join("");
  }

  if (k === "emotion_update") {
    const cfg = spec && typeof spec === "object" ? spec : {};
    const entries = Object.entries(cfg).filter(([kk]) => String(kk || "").trim());
    const rows = entries.length
      ? entries
          .map(([kk, vv], idx) => {
            const key = String(kk || "");
            const val = vv === undefined || vv === null ? "" : String(vv);
            return [
              `<div class="ir-kv-row" data-row="${idx}">`,
              `<input class="ir-flow-prop ir-kv-key" data-apath="${esc(apath)}" data-field="eu_key" data-row="${idx}" data-old-key="${esc(key)}" type="text" value="${esc(key)}" placeholder="通道名，例如 DA/多巴胺/COR" />`,
              `<input class="ir-flow-prop ir-kv-val" data-apath="${esc(apath)}" data-field="eu_val" data-row="${idx}" type="text" value="${esc(val)}" placeholder="增量，例如 0.2 或 -0.1 或 {{{var}}}" />`,
              `<button class="ghost danger" data-flow-action="eu_remove" data-apath="${esc(apath)}" data-row="${idx}" type="button">移除</button>`,
              `</div>`,
            ].join("");
          })
          .join("")
      : `<div class="empty-state">当前没有任何通道增量。点击下方「添加通道」开始。</div>`;

    return [
      `<div class="sub-section">`,
      `<div class="sub-title">递质通道增量（emotion_update）</div>`,
      `<div class="soft-note">支持缩写或中文名；数值可为负；可用模板（例如 {{{var}}}）。</div>`,
      `<div class="ir-kv-list">`,
      rows,
      `</div>`,
      `<div class="toolbar" style="margin-top:10px;">`,
      `<button class="ghost" data-flow-action="eu_add" data-apath="${esc(apath)}" type="button">+ 添加通道</button>`,
      `</div>`,
      `</div>`,
    ].join("");
  }

  if (k === "action_trigger") {
    const cfg = spec && typeof spec === "object" ? spec : {};
    const params = cfg.params && typeof cfg.params === "object" ? cfg.params : {};
    const entries = Object.entries(params).filter(([kk]) => String(kk || "").trim());
    const rows = entries.length
      ? entries
          .map(([kk, vv], idx) => {
            const key = String(kk || "");
            const val = vv === undefined || vv === null ? "" : String(vv);
            return [
              `<div class="ir-kv-row" data-row="${idx}">`,
              `<input class="ir-flow-prop ir-kv-key" data-apath="${esc(apath)}" data-field="at_param_key" data-row="${idx}" data-old-key="${esc(key)}" type="text" value="${esc(key)}" placeholder="参数名，例如 target_ref_object_id" />`,
              `<input class="ir-flow-prop ir-kv-val" data-apath="${esc(apath)}" data-field="at_param_val" data-row="${idx}" type="text" value="${esc(val)}" placeholder="参数值，可用模板 {{{var}}}" />`,
              `<button class="ghost danger" data-flow-action="at_param_remove" data-apath="${esc(apath)}" data-row="${idx}" type="button">移除</button>`,
              `</div>`,
            ].join("");
          })
          .join("")
      : `<div class="empty-state">当前没有 params。你可以点击下方按钮添加。</div>`;

    return [
      `<div class="settings-grid">`,
      _irFlowRowHtml({ label: "action_id（建议稳定）", apath, field: "action_id", value: cfg.action_id ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "action_kind", apath, field: "action_kind", value: cfg.action_kind ?? "custom", kind: "text" }),
      _irFlowRowHtml({ label: "gain（可用模板）", apath, field: "gain", value: cfg.gain ?? 0.3, kind: "text" }),
      _irFlowRowHtml({ label: "threshold", apath, field: "threshold", value: cfg.threshold ?? 1.0, kind: "text" }),
      _irFlowRowHtml({ label: "cooldown_ticks", apath, field: "cooldown_ticks", value: cfg.cooldown_ticks ?? 0, kind: "number" }),
      `</div>`,
      `<div class="sub-section"><div class="sub-title">params（键值对）</div>`,
      `<div class="toolbar">`,
      `<button class="ghost" data-flow-action="at_params_fill_focus" data-apath="${esc(apath)}" type="button">填入: 注意力聚焦 target_* + strength</button>`,
      `<button class="ghost" data-flow-action="at_params_fill_recall" data-apath="${esc(apath)}" type="button">填入: 回忆 trigger_kind/strength</button>`,
      `</div>`,
      `<div class="ir-kv-list" style="margin-top:10px;">${rows}</div>`,
      `<div class="toolbar" style="margin-top:10px;">`,
      `<button class="ghost" data-flow-action="at_param_add" data-apath="${esc(apath)}" type="button">+ 添加参数</button>`,
      `</div>`,
      `</div>`,
    ].join("");
  }

  if (k === "pool_energy") {
    const cfg = spec && typeof spec === "object" ? spec : {};
    const sel = cfg.selector && typeof cfg.selector === "object" ? cfg.selector : {};
    const selMode = String(sel.mode || "all");
    return [
      `<div class="settings-grid">`,
      `<article class="setting-item"><label>selector.mode</label>`,
      `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="selector_mode">`,
      `<option value="all" ${selMode === "all" ? "selected" : ""}>all</option>`,
      `<option value="specific_ref" ${selMode === "specific_ref" ? "selected" : ""}>specific_ref</option>`,
      `<option value="specific_item" ${selMode === "specific_item" ? "selected" : ""}>specific_item</option>`,
      `<option value="contains_text" ${selMode === "contains_text" ? "selected" : ""}>contains_text</option>`,
      `<option value="top_n" ${selMode === "top_n" ? "selected" : ""}>top_n</option>`,
      `</select></article>`,
      _irFlowRowHtml({ label: "selector.ref_object_id", apath, field: "selector_ref_object_id", value: sel.ref_object_id ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "selector.item_id", apath, field: "selector_item_id", value: sel.item_id ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "selector.contains_text", apath, field: "selector_contains_text", value: sel.contains_text ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "selector.top_n", apath, field: "selector_top_n", value: sel.top_n ?? "", kind: "number" }),
      _irFlowRowHtml({ label: "delta_er（可为负，可用模板）", apath, field: "delta_er", value: cfg.delta_er ?? 0.0, kind: "text" }),
      _irFlowRowHtml({ label: "delta_ev（可为负，可用模板）", apath, field: "delta_ev", value: cfg.delta_ev ?? 0.0, kind: "text" }),
      _irFlowRowHtml({ label: "create_if_missing", apath, field: "create_if_missing", value: Boolean(cfg.create_if_missing), kind: "checkbox" }),
      _irFlowRowHtml({ label: "reason（可选）", apath, field: "reason", value: cfg.reason ?? "", kind: "text" }),
      `</div>`,
    ].join("");
  }

  if (k === "pool_bind_attribute") {
    const cfg = spec && typeof spec === "object" ? spec : {};
    const sel = cfg.selector && typeof cfg.selector === "object" ? cfg.selector : {};
    const selMode = String(sel.mode || "all");
    const attr = cfg.attribute && typeof cfg.attribute === "object" ? cfg.attribute : {};
    return [
      `<div class="settings-grid">`,
      `<article class="setting-item"><label>selector.mode</label>`,
      `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="selector_mode">`,
      `<option value="all" ${selMode === "all" ? "selected" : ""}>all</option>`,
      `<option value="specific_ref" ${selMode === "specific_ref" ? "selected" : ""}>specific_ref</option>`,
      `<option value="specific_item" ${selMode === "specific_item" ? "selected" : ""}>specific_item</option>`,
      `<option value="contains_text" ${selMode === "contains_text" ? "selected" : ""}>contains_text</option>`,
      `<option value="top_n" ${selMode === "top_n" ? "selected" : ""}>top_n</option>`,
      `</select></article>`,
      _irFlowRowHtml({ label: "selector.ref_object_id", apath, field: "selector_ref_object_id", value: sel.ref_object_id ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "selector.item_id", apath, field: "selector_item_id", value: sel.item_id ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "attribute_name", apath, field: "attr_name", value: attr.attribute_name ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "attribute_value（可选）", apath, field: "attr_value", value: attr.attribute_value ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "display（可选）", apath, field: "attr_display", value: attr.display ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "reason（可选）", apath, field: "reason", value: cfg.reason ?? "", kind: "text" }),
      `</div>`,
    ].join("");
  }

  if (k === "delay") {
    const cfg = spec && typeof spec === "object" ? spec : {};
    if (depth >= 4) return `<div class="empty-state">嵌套过深，已折叠。</div>`;
    return [
      `<div class="settings-grid">`,
      _irFlowRowHtml({ label: "延时 tick（ticks）", apath, field: "ticks", value: cfg.ticks ?? 1, kind: "number" }),
      `</div>`,
      `<div class="sub-section"><div class="sub-title">延时后动作（then）</div>`,
      _irFlowRenderActionList(a(cfg.then), `${apath}.then`, depth),
      `</div>`,
    ].join("");
  }

  if (k === "branch") {
    const cfg = spec && typeof spec === "object" ? spec : {};
    if (depth >= 4) return `<div class="empty-state">嵌套过深，已折叠。</div>`;
    const when = cfg.when && typeof cfg.when === "object" ? cfg.when : { metric: { preset: "reward_state", mode: "state", op: ">", value: 0 } };
    const whenSpec = when.metric && typeof when.metric === "object" ? when.metric : {};
    const sel = whenSpec.selector && typeof whenSpec.selector === "object" ? whenSpec.selector : {};
    const selMode = String(sel.mode || "all");
    const presetOptions = _irFlowMetricPresetOptionsHtml(whenSpec.preset || "");
    return [
      `<div class="sub-section"><div class="sub-title">分支条件（when，当前仅支持 metric）</div>`,
      `<div class="settings-grid">`,
      `<article class="setting-item"><label>preset</label>`,
      `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="when_preset">${presetOptions}</select>`,
      `</article>`,
      `<article class="setting-item"><label>mode</label>`,
      `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="when_mode">`,
      `<option value="state" ${String(whenSpec.mode || "state") === "state" ? "selected" : ""}>state</option>`,
      `<option value="delta" ${String(whenSpec.mode || "") === "delta" ? "selected" : ""}>delta</option>`,
      `<option value="avg_rate" ${String(whenSpec.mode || "") === "avg_rate" ? "selected" : ""}>avg_rate</option>`,
      `</select></article>`,
      `<article class="setting-item"><label>op</label>`,
      `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="when_op">`,
      `<option value=">=" ${String(whenSpec.op || ">=") === ">=" ? "selected" : ""}>&gt;=</option>`,
      `<option value=">" ${String(whenSpec.op || "") === ">" ? "selected" : ""}>&gt;</option>`,
      `<option value="<=" ${String(whenSpec.op || "") === "<=" ? "selected" : ""}>&lt;=</option>`,
      `<option value="<" ${String(whenSpec.op || "") === "<" ? "selected" : ""}>&lt;</option>`,
      `<option value="exists" ${String(whenSpec.op || "") === "exists" ? "selected" : ""}>exists</option>`,
      `<option value="changed" ${String(whenSpec.op || "") === "changed" ? "selected" : ""}>changed</option>`,
      `</select></article>`,
      _irFlowRowHtml({ label: "value（阈值，可用模板）", apath, field: "when_value", value: whenSpec.value ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "window_ticks", apath, field: "when_window_ticks", value: whenSpec.window_ticks ?? 2, kind: "number" }),
      `<article class="setting-item"><label>selector.mode</label>`,
      `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="when_selector_mode">`,
      `<option value="all" ${selMode === "all" ? "selected" : ""}>all</option>`,
      `<option value="specific_item" ${selMode === "specific_item" ? "selected" : ""}>specific_item</option>`,
      `<option value="specific_ref" ${selMode === "specific_ref" ? "selected" : ""}>specific_ref</option>`,
      `<option value="contains_text" ${selMode === "contains_text" ? "selected" : ""}>contains_text</option>`,
      `<option value="top_n" ${selMode === "top_n" ? "selected" : ""}>top_n</option>`,
      `</select></article>`,
      _irFlowRowHtml({ label: "selector.item_id", apath, field: "when_selector_item_id", value: sel.item_id ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "selector.ref_object_id", apath, field: "when_selector_ref_object_id", value: sel.ref_object_id ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "selector.contains_text", apath, field: "when_selector_contains_text", value: sel.contains_text ?? "", kind: "text" }),
      _irFlowRowHtml({ label: "selector.top_n", apath, field: "when_selector_top_n", value: sel.top_n ?? "", kind: "number" }),
      `</div></div>`,
      `<div class="sub-section"><div class="sub-title">满足（then）</div>`,
      _irFlowRenderActionList(a(cfg.then), `${apath}.then`, depth),
      `</div>`,
      `<div class="sub-section"><div class="sub-title">不满足（else）</div>`,
      _irFlowRenderActionList(a(cfg.else), `${apath}.else`, depth),
      `</div>`,
      `<div class="sub-section"><div class="sub-title">报错（on_error）</div>`,
      _irFlowRenderActionList(a(cfg.on_error), `${apath}.on_error`, depth),
      `</div>`,
    ].join("");
  }

  return `<div class="empty-state">该动作类型暂未实现子编辑器（${esc(k)}）。</div>`;
}

function _irFlowRenderActionItem(action, apath, depth) {
  const title = _irFlowActionTitle(action);
  const k = _irFlowActionKey(action) || "log";
  const openAttr = depth <= 0 ? "open" : "";
  return [
    `<details class="detail-card nested ir-flow-action" ${openAttr}>`,
    `<summary class="ir-flow-summary">`,
    `<div class="ir-flow-summary-left"><strong>${esc(title)}</strong></div>`,
    `<div class="ir-flow-summary-right">`,
    `<select class="ir-flow-prop" data-apath="${esc(apath)}" data-field="type">`,
    _irFlowActionTypeOptionsHtml(k),
    `</select>`,
    `<button class="ghost danger" data-flow-action="remove_action" data-apath="${esc(apath)}" type="button">删除</button>`,
    `</div></summary>`,
    `<div class="details-body">`,
    _irFlowRenderActionFields(action, apath, depth),
    `</div></details>`,
  ].join("");
}

function _irFlowRenderActionList(actions, listPath, depth) {
  const lp = String(listPath || "then");
  const items = a(actions)
    .map((act, idx) => _irFlowRenderActionItem(act, `${lp}.${idx}`, depth))
    .join("");
  return [
    `<div class="ir-flow-list-wrap" data-list-path="${esc(lp)}">`,
    `<div class="ir-flow-add-row">`,
    `<select class="ir-flow-add-type" data-list-path="${esc(lp)}">`,
    _irFlowActionTypeOptionsHtml("log"),
    `</select>`,
    `<button class="ghost" data-flow-action="add_action" data-list-path="${esc(lp)}" type="button">添加子动作</button>`,
    `</div>`,
    `<div class="ir-flow-list">`,
    items || `<div class="empty-state">当前没有子动作。你可以用上面的“添加子动作”。</div>`,
    `</div></div>`,
  ].join("");
}

function renderIrGraphProps() {
  if (!E.irGraphProps) return;
  if (!S.irGraph.open || !S.irGraph.graph) {
    E.irGraphProps.innerHTML = empty("图形编辑器未打开。");
    return;
  }
  const g = S.irGraph.graph;
  const node = S.irGraph.selectedNodeId ? _findIrGraphNode(g, String(S.irGraph.selectedNodeId)) : null;
  if (!node) {
    E.irGraphProps.innerHTML = empty("请选择一个节点查看/编辑属性。");
    return;
  }
  const title = _irGraphNodeTitle(node);
  const type = String(node.type || "");
  const cfg = node.config || {};

  const renderRow = (label, field, value, kind = "text", extra = "") => {
    const safe = value === undefined || value === null ? "" : String(value);
    if (kind === "textarea") {
      return `<article class="setting-item"><label>${esc(label)}</label><textarea class="ir-graph-prop" data-field="${esc(field)}">${esc(safe)}</textarea>${extra}</article>`;
    }
    return `<article class="setting-item"><label>${esc(label)}</label><input class="ir-graph-prop" data-field="${esc(field)}" type="${esc(kind)}" value="${esc(safe)}" />${extra}</article>`;
  };

  const canDelete = type !== "root";
  let body = `<div class="detail-card nested">
    <div class="section-head"><h5>${esc(title)}</h5><span class="meta">类型（type）${esc(type)} | 节点ID（id）${esc(String(node.id || ""))}</span></div>
    ${canDelete ? `<div class="toolbar" style="margin: 8px 0 12px;">
      <button id="irGraphDeleteSelectedBtn" class="ghost danger" type="button">删除该节点</button>
    </div>` : ""}
    <div class="settings-grid">`;

  if (type === "root") {
    body += `<article class="setting-item">
      <label>触发模式（mode）</label>
      <select class="ir-graph-prop" data-field="mode">
        <option value="any" ${String(cfg.mode || "any") === "any" ? "selected" : ""}>任一触发（any）</option>
        <option value="all" ${String(cfg.mode || "") === "all" ? "selected" : ""}>同时满足（all）</option>
      </select>
    </article>`;
  } else if (type === "cfs") {
    body += renderRow("信号类型（kinds，逗号分隔）", "kinds", a(cfg.kinds).join(","), "text");
    body += renderRow("最小强度（min_strength）", "min_strength", cfg.min_strength ?? "", "number");
    body += renderRow("最大强度（max_strength，可选）", "max_strength", cfg.max_strength ?? "", "number");
  } else if (type === "state_window") {
    body += `<article class="setting-item">
      <label>阶段（stage）</label>
      <select class="ir-graph-prop" data-field="stage">
        <option value="any" ${String(cfg.stage || "any") === "any" ? "selected" : ""}>任意窗口（any）</option>
        <option value="maintenance" ${String(cfg.stage || "") === "maintenance" ? "selected" : ""}>维护窗口（maintenance）</option>
        <option value="pool_apply" ${String(cfg.stage || "") === "pool_apply" ? "selected" : ""}>回写窗口（pool_apply）</option>
      </select>
    </article>`;
    body += renderRow("认知压强（CP）快速上升次数 >=（fast_cp_rise_min）", "fast_cp_rise_min", cfg.fast_cp_rise_min ?? "", "number");
    body += renderRow("认知压强（CP）快速下降次数 >=（fast_cp_drop_min）", "fast_cp_drop_min", cfg.fast_cp_drop_min ?? "", "number");
    body += renderRow("候选数量 >=（min_candidate_count）", "min_candidate_count", cfg.min_candidate_count ?? "", "number");
    body += renderRow("候选 hint（candidate_hint_any，逗号）", "candidate_hint_any", a(cfg.candidate_hint_any).join(","), "text");
  } else if (type === "timer") {
    body += renderRow("每 N tick 触发（every_n_ticks）", "every_n_ticks", cfg.every_n_ticks ?? "", "number");
    body += renderRow("指定 tick（at_tick，可选）", "at_tick", cfg.at_tick ?? "", "number");
  } else if (type === "metric") {
    const presets = a(S.innateRulesBundle?.metric_presets);
    const groups = {};
    for (const p of presets) {
      if (!p || typeof p !== "object") continue;
      const gName = String(p.group_zh || "其他");
      if (!groups[gName]) groups[gName] = [];
      groups[gName].push(p);
    }
    const groupNames = Object.keys(groups).sort();
    const selectedPreset = presets.find((p) => String(p?.preset || "") === String(cfg.preset || "")) || null;
    const needsChannel =
      Boolean(selectedPreset?.needs_channel) || String(selectedPreset?.metric || "").includes("{channel}");
    const presetOptions =
      `<option value="">（不使用预设）</option>` +
      (groupNames.length
        ? groupNames
            .map((gName) => {
              const opts = a(groups[gName])
                .map((p) => {
                  const name = String(p.preset || "");
                  const label = String(p.label_zh || name);
                  const selected = String(cfg.preset || "") === name ? "selected" : "";
                  return `<option value="${esc(name)}" ${selected}>${esc(label)}（${esc(name)}）</option>`;
                })
                .join("");
              return `<optgroup label="${esc(gName)}">${opts}</optgroup>`;
            })
            .join("")
        : `<optgroup label="常用（内置）">
            <option value="got_er" ${String(cfg.preset || "") === "got_er" ? "selected" : ""}>获得实能量（got_er）</option>
            <option value="got_ev" ${String(cfg.preset || "") === "got_ev" ? "selected" : ""}>获得虚能量（got_ev）</option>
            <option value="reward_state" ${String(cfg.preset || "") === "reward_state" ? "selected" : ""}>奖励信号状态（reward_state）</option>
          </optgroup>`);

    const sel = cfg.selector && typeof cfg.selector === "object" ? cfg.selector : {};
    const selMode = String(sel.mode || "all");

    body += `<article class="setting-item">
      <label>指标预设（preset）</label>
      <select class="ir-graph-prop" data-field="preset">${presetOptions}</select>
    </article>`;
    if (needsChannel) {
      body += renderRow(
        "情绪递质通道（channel，nt_* 预设必填）",
        "channel",
        cfg.channel ?? "",
        "text",
        `<div class="soft-note">示例：DA/多巴胺/COR/皮质醇。该预设会映射到 emotion.nt.{channel}</div>`,
      );
    }
    body += renderRow("指标路径（metric，选填）", "metric", cfg.metric ?? "", "text", `<div class="soft-note">例如 item.er / pool.total_er / emotion.nt.DA / retrieval.stimulus.match_scores</div>`);
    body += `<article class="setting-item">
      <label>取值方式（mode）</label>
      <select class="ir-graph-prop" data-field="mode">
        <option value="state" ${String(cfg.mode || "state") === "state" ? "selected" : ""}>state（状态）</option>
        <option value="delta" ${String(cfg.mode || "") === "delta" ? "selected" : ""}>delta（变化量）</option>
        <option value="avg_rate" ${String(cfg.mode || "") === "avg_rate" ? "selected" : ""}>avg_rate（变化率）</option>
      </select>
    </article>`;
    body += `<article class="setting-item">
      <label>比较符（op）</label>
      <select class="ir-graph-prop" data-field="op">
        <option value=">=" ${String(cfg.op || ">=") === ">=" ? "selected" : ""}>&gt;=</option>
        <option value=">" ${String(cfg.op || "") === ">" ? "selected" : ""}>&gt;</option>
        <option value="<=" ${String(cfg.op || "") === "<=" ? "selected" : ""}>&lt;=</option>
        <option value="<" ${String(cfg.op || "") === "<" ? "selected" : ""}>&lt;</option>
        <option value="==" ${String(cfg.op || "") === "==" ? "selected" : ""}>=</option>
        <option value="!=" ${String(cfg.op || "") === "!=" ? "selected" : ""}>!=</option>
        <option value="between" ${String(cfg.op || "") === "between" ? "selected" : ""}>between</option>
        <option value="exists" ${String(cfg.op || "") === "exists" ? "selected" : ""}>exists</option>
        <option value="changed" ${String(cfg.op || "") === "changed" ? "selected" : ""}>changed</option>
      </select>
    </article>`;
    body += renderRow("阈值（value，可用模板 {{{var}}}）", "value", cfg.value ?? "", "text");
    body += renderRow("min（between 用）", "min", cfg.min ?? "", "text");
    body += renderRow("max（between 用）", "max", cfg.max ?? "", "text");
    body += renderRow("window_ticks（avg_rate 用）", "window_ticks", cfg.window_ticks ?? 4, "number");
    body += `<article class="setting-item">
      <label>match_policy（item.* 用）</label>
      <select class="ir-graph-prop" data-field="match_policy">
        <option value="any" ${String(cfg.match_policy || "any") === "any" ? "selected" : ""}>any</option>
        <option value="all" ${String(cfg.match_policy || "") === "all" ? "selected" : ""}>all</option>
      </select>
    </article>`;
    body += renderRow("capture_as（变量捕获，可选）", "capture_as", cfg.capture_as ?? "", "text");

    // selector (flat fields for UI)
    body += `<article class="setting-item">
      <label>selector.mode（对象选择，可选）</label>
      <select class="ir-graph-prop" data-field="selector_mode">
        <option value="all" ${selMode === "all" ? "selected" : ""}>all</option>
        <option value="specific_ref" ${selMode === "specific_ref" ? "selected" : ""}>specific_ref</option>
        <option value="specific_item" ${selMode === "specific_item" ? "selected" : ""}>specific_item</option>
        <option value="contains_text" ${selMode === "contains_text" ? "selected" : ""}>contains_text</option>
        <option value="top_n" ${selMode === "top_n" ? "selected" : ""}>top_n</option>
      </select>
    </article>`;
    body += renderRow("selector.ref_object_id", "selector_ref_object_id", sel.ref_object_id ?? "", "text");
    body += renderRow("selector.ref_object_type", "selector_ref_object_type", sel.ref_object_type ?? "", "text");
    body += renderRow("selector.item_id", "selector_item_id", sel.item_id ?? "", "text");
    body += renderRow("selector.contains_text", "selector_contains_text", sel.contains_text ?? "", "text");
    body += renderRow("selector.top_n", "selector_top_n", sel.top_n ?? "", "number");
    body += renderRow("selector.ref_object_types（逗号）", "selector_ref_object_types", a(sel.ref_object_types).join(","), "text");
  } else if (type === "focus") {
    body += `<article class="setting-item">
      <label>来源（from）</label>
      <select class="ir-graph-prop" data-field="from">
        <option value="cfs_matches" ${String(cfg.from || "cfs_matches") === "cfs_matches" ? "selected" : ""}>认知感受命中（cfs_matches）</option>
        <option value="state_window_candidates" ${String(cfg.from || "") === "state_window_candidates" ? "selected" : ""}>状态窗口候选（state_window_candidates）</option>
      </select>
    </article>`;
    body += `<article class="setting-item">
      <label>匹配策略（match_policy）</label>
      <select class="ir-graph-prop" data-field="match_policy">
        <option value="all" ${String(cfg.match_policy || "all") === "all" ? "selected" : ""}>全部匹配（all）</option>
        <option value="strongest" ${String(cfg.match_policy || "") === "strongest" ? "selected" : ""}>取最强（strongest）</option>
        <option value="first" ${String(cfg.match_policy || "") === "first" ? "selected" : ""}>取第一个（first）</option>
      </select>
    </article>`;
    body += renderRow("存活 tick（ttl_ticks）", "ttl_ticks", cfg.ttl_ticks ?? "", "number");
    body += renderRow("聚焦加成（focus_boost）", "focus_boost", cfg.focus_boost ?? "", "number");
    body += `<article class="setting-item">
      <label>去重键（deduplicate_by）</label>
      <select class="ir-graph-prop" data-field="deduplicate_by">
        <option value="target_ref_object_id" ${String(cfg.deduplicate_by || "target_ref_object_id") === "target_ref_object_id" ? "selected" : ""}>按目标对象 ID（target_ref_object_id）</option>
        <option value="target_item_id" ${String(cfg.deduplicate_by || "") === "target_item_id" ? "selected" : ""}>按目标条目 ID（target_item_id）</option>
      </select>
    </article>`;
    body += renderRow("最多生成条数（max_directives，可选）", "max_directives", cfg.max_directives ?? "", "number");
  } else if (type === "emit_script") {
    body += renderRow("脚本ID（script_id）", "script_id", cfg.script_id ?? "", "text");
    body += renderRow("脚本类型（script_kind）", "script_kind", cfg.script_kind ?? "custom", "text");
    body += renderRow("优先级（priority）", "priority", cfg.priority ?? 50, "number");
    body += renderRow("触发标签（trigger）", "trigger", cfg.trigger ?? "", "text");
  } else if (type === "cfs_emit") {
    const strength = cfg.strength && typeof cfg.strength === "object" ? cfg.strength : {};
    const strengthPolicy = String(strength.policy || "linear_clamp");
    const target = cfg.target && typeof cfg.target === "object" ? cfg.target : {};
    const targetFrom = String(target.from || "match");
    const bind = cfg.bind_attribute && typeof cfg.bind_attribute === "object" ? cfg.bind_attribute : null;
    const bindEnabled = bind !== null;

    const strengthExtraHtml = (() => {
      if (strengthPolicy === "verify_mix") {
        return `
        <article class="setting-item">
          <label>verify_mix.part（输出哪一侧）</label>
          <select class="ir-graph-prop" data-field="strength_part">
            <option value="verified" ${String(strength.part || "verified") === "verified" ? "selected" : ""}>验证（verified，偏“实”）</option>
            <option value="unverified" ${String(strength.part || "") === "unverified" ? "selected" : ""}>不验（unverified，偏“虚”）</option>
          </select>
        </article>
        <article class="setting-item"><label>pred_var（预测量变量名）</label><input class="ir-graph-prop" data-field="strength_pred_var" type="text" value="${esc(String(strength.pred_var ?? ""))}" /></article>
        <article class="setting-item"><label>actual_var（实际量变量名）</label><input class="ir-graph-prop" data-field="strength_actual_var" type="text" value="${esc(String(strength.actual_var ?? ""))}" /></article>
        <article class="setting-item"><label>pred_scale / actual_scale</label><input class="ir-graph-prop" data-field="strength_pred_scale" type="number" step="any" value="${esc(String(strength.pred_scale ?? 1.0))}" /><input class="ir-graph-prop" data-field="strength_actual_scale" type="number" step="any" value="${esc(String(strength.actual_scale ?? 1.0))}" /></article>
        <article class="setting-item"><label>gamma / eps</label><input class="ir-graph-prop" data-field="strength_gamma" type="number" step="any" value="${esc(String(strength.gamma ?? 1.0))}" /><input class="ir-graph-prop" data-field="strength_eps" type="number" step="any" value="${esc(String(strength.eps ?? 1e-6))}" /></article>
        <div class="soft-note">verify_mix：连续、对称的“验证/不验”混合。常见用法：actual_scale=window_ticks。</div>
        `;
      }
      if (strengthPolicy === "scale_offset") {
        return `<article class="setting-item"><label>scale_offset 参数 scale/offset</label><input class="ir-graph-prop" data-field="strength_scale" type="number" step="any" value="${esc(String(strength.scale ?? 1.0))}" /><input class="ir-graph-prop" data-field="strength_offset" type="number" step="any" value="${esc(String(strength.offset ?? 0.0))}" /></article>`;
      }
      return `
        <article class="setting-item"><label>linear_clamp 输入范围 min/max</label><input class="ir-graph-prop" data-field="strength_min" type="number" step="any" value="${esc(String(strength.min ?? 0.0))}" /><input class="ir-graph-prop" data-field="strength_max" type="number" step="any" value="${esc(String(strength.max ?? 1.0))}" /></article>
        <article class="setting-item"><label>linear_clamp 输出范围 out_min/out_max</label><input class="ir-graph-prop" data-field="strength_out_min" type="number" step="any" value="${esc(String(strength.out_min ?? 0.0))}" /><input class="ir-graph-prop" data-field="strength_out_max" type="number" step="any" value="${esc(String(strength.out_max ?? 1.0))}" /></article>
      `;
    })();

    const strengthInvertHtml = strengthPolicy === "linear_clamp"
      ? `<div class="toggle-row"><input class="ir-graph-prop" data-field="strength_invert" type="checkbox" ${strength.invert ? "checked" : ""} /><span>invert（输出 1-x，仅 linear_clamp 生效）</span></div>`
      : ``;

    body += renderRow("感受类型（kind，必填）", "kind", cfg.kind ?? "", "text", `<div class="soft-note">示例：dissonance（违和感）/ correct_event（正确事件）/ expectation（期待）/ pressure（压力）/ grasp（把握感/置信度）等。</div>`);
    body += `<article class="setting-item">
      <label>作用域（scope）</label>
      <select class="ir-graph-prop" data-field="scope">
        <option value="object" ${String(cfg.scope || "object") === "object" ? "selected" : ""}>对象级（object，需要目标对象）</option>
        <option value="global" ${String(cfg.scope || "") === "global" ? "selected" : ""}>全局（global，不绑定目标）</option>
      </select>
    </article>`;
    body += `<article class="setting-item">
      <label>来源（from）</label>
      <select class="ir-graph-prop" data-field="from">
        <option value="metric_matches" ${String(cfg.from || "metric_matches") === "metric_matches" ? "selected" : ""}>来自命中的指标对象（metric_matches）</option>
        <option value="cfs_matches" ${String(cfg.from || "") === "cfs_matches" ? "selected" : ""}>来自命中的认知感受对象（cfs_matches）</option>
        <option value="single" ${String(cfg.from || "") === "single" ? "selected" : ""}>单条（single，不依赖命中记录）</option>
      </select>
      <div class="soft-note">提示：from=metric_matches/cfs_matches 时可用变量：<code>{{{match_value}}}</code> / <code>{{{match_ref_object_id}}}</code> / <code>{{{match_item_id}}}</code>。</div>
    </article>`;
    body += renderRow("最多生成条数（max_signals，可选）", "max_signals", cfg.max_signals ?? "", "number");
    body += renderRow("最小强度（min_strength，可选）", "min_strength", cfg.min_strength ?? "", "number");
    body += renderRow("变量捕获（capture_as，可选）", "capture_as", cfg.capture_as ?? "", "text", `<div class="soft-note">说明：可把本次计算得到的 strength 写入变量，供同一条规则后续动作使用。</div>`);

    body += `<div class="sub-section">
      <div class="sub-title">强度映射（strength）</div>
      <div class="settings-grid">
        <article class="setting-item">
          <label>strength.policy（映射策略）</label>
          <select class="ir-graph-prop" data-field="strength_policy">
            <option value="linear_clamp" ${strengthPolicy === "linear_clamp" ? "selected" : ""}>线性钳制（linear_clamp）</option>
            <option value="scale_offset" ${strengthPolicy === "scale_offset" ? "selected" : ""}>比例偏移（scale_offset）</option>
            <option value="verify_mix" ${strengthPolicy === "verify_mix" ? "selected" : ""}>渐变验证混合（verify_mix）</option>
          </select>
        </article>
        <article class="setting-item"><label>strength.from（来源变量名）</label><input class="ir-graph-prop" data-field="strength_from" type="text" value="${esc(String(strength.from ?? "match_value"))}" /><small>常用：match_value（默认）或某个变量名；当 from="var" 时请填写 strength.var。</small></article>
        <article class="setting-item"><label>strength.var（变量名，from=var 时用）</label><input class="ir-graph-prop" data-field="strength_var" type="text" value="${esc(String(strength.var ?? ""))}" /></article>
        <article class="setting-item">
          <label>strength.abs</label>
          <div class="toggle-row"><input class="ir-graph-prop" data-field="strength_abs" type="checkbox" ${strength.abs ? "checked" : ""} /><span>abs（先取绝对值）</span></div>
          ${strengthInvertHtml}
        </article>
        ${strengthExtraHtml}
      </div>
      <div class="soft-note">说明：strength 始终会被钳制到 0~1，保证可审计与安全。</div>
    </div>`;

    body += `<div class="sub-section">
      <div class="sub-title">目标选择（target，可选）</div>
      <div class="settings-grid">
        <article class="setting-item">
          <label>target.from</label>
          <select class="ir-graph-prop" data-field="target_from">
            <option value="match" ${targetFrom === "match" ? "selected" : ""}>来自命中对象（match，默认）</option>
            <option value="specific_ref" ${targetFrom === "specific_ref" ? "selected" : ""}>特定对象（specific_ref）</option>
            <option value="specific_item" ${targetFrom === "specific_item" ? "selected" : ""}>特定条目（specific_item）</option>
          </select>
        </article>
        <article class="setting-item"><label>target.ref_object_id（specific_ref 用）</label><input class="ir-graph-prop" data-field="target_ref_object_id" type="text" value="${esc(String(target.ref_object_id ?? ""))}" /></article>
        <article class="setting-item"><label>target.ref_object_type（specific_ref 用）</label><input class="ir-graph-prop" data-field="target_ref_object_type" type="text" value="${esc(String(target.ref_object_type ?? ""))}" /></article>
        <article class="setting-item"><label>target.item_id（specific_item 用）</label><input class="ir-graph-prop" data-field="target_item_id" type="text" value="${esc(String(target.item_id ?? ""))}" /></article>
        <article class="setting-item"><label>target.display（可选）</label><input class="ir-graph-prop" data-field="target_display" type="text" value="${esc(String(target.display ?? ""))}" /></article>
      </div>
      <div class="soft-note">默认不填：对象级信号会自动绑定到 match_* 的目标对象。</div>
    </div>`;

    body += `<div class="sub-section">
      <div class="sub-title">绑定为属性（bind_attribute，可选，但推荐用于可观测性）</div>
      <article class="setting-item">
        <label>启用绑定</label>
        <label class="toggle-row"><input class="ir-graph-prop" data-field="bindattr_enabled" type="checkbox" ${bindEnabled ? "checked" : ""} /><span>把该感受作为“属性刺激元（SA）”绑定到目标对象</span></label>
        <small>说明：这是“绑定约束信息”，默认不会把 SA/CSA 作为独立对象写入状态池（避免噪音）。</small>
      </article>
      <div class="settings-grid">
        <article class="setting-item"><label>attribute_name（属性名）</label><input class="ir-graph-prop" data-field="bindattr_attribute_name" type="text" value="${esc(String((bind || {}).attribute_name ?? ""))}" /></article>
        <article class="setting-item">
          <label>value_from（取值来源）</label>
          <select class="ir-graph-prop" data-field="bindattr_value_from">
            <option value="strength" ${String((bind || {}).value_from || "strength") === "strength" ? "selected" : ""}>strength（使用计算后的强度）</option>
            <option value="match_value" ${String((bind || {}).value_from || "") === "match_value" ? "selected" : ""}>match_value（使用命中值）</option>
          </select>
        </article>
        <article class="setting-item"><label>display（展示文本，可用模板 {{{strength}}}）</label><input class="ir-graph-prop" data-field="bindattr_display" type="text" value="${esc(String((bind || {}).display ?? ""))}" /></article>
        <article class="setting-item"><label>raw（原始文本，可选）</label><input class="ir-graph-prop" data-field="bindattr_raw" type="text" value="${esc(String((bind || {}).raw ?? ""))}" /></article>
        <article class="setting-item">
          <label>value_type / modality</label>
          <select class="ir-graph-prop" data-field="bindattr_value_type">
            <option value="numerical" ${String((bind || {}).value_type || "numerical") === "numerical" ? "selected" : ""}>数值（numerical）</option>
            <option value="discrete" ${String((bind || {}).value_type || "") === "discrete" ? "selected" : ""}>离散（discrete）</option>
          </select>
          <select class="ir-graph-prop" data-field="bindattr_modality">
            <option value="internal" ${String((bind || {}).modality || "internal") === "internal" ? "selected" : ""}>内部（internal）</option>
            <option value="external" ${String((bind || {}).modality || "") === "external" ? "selected" : ""}>外部（external）</option>
          </select>
        </article>
        <article class="setting-item"><label>er / ev（可选，属性能量）</label><input class="ir-graph-prop" data-field="bindattr_er" type="number" step="any" value="${esc(String((bind || {}).er ?? 0.0))}" /><input class="ir-graph-prop" data-field="bindattr_ev" type="number" step="any" value="${esc(String((bind || {}).ev ?? 0.0))}" /></article>
        <article class="setting-item"><label>reason（原因，可选）</label><input class="ir-graph-prop" data-field="bindattr_reason" type="text" value="${esc(String((bind || {}).reason ?? ""))}" /></article>
      </div>
    </div>`;
  } else if (type === "emotion_update") {
    const entries = Object.entries(cfg && typeof cfg === "object" ? cfg : {}).filter(([k]) => String(k || "").trim());
    const rowsHtml =
      entries.length
        ? entries
            .map(([k, v], idx) => {
              const key = String(k || "");
              const val = v === undefined || v === null ? "" : String(v);
              return `<div class="ir-kv-row" data-row="${idx}">
                <input class="ir-graph-prop ir-kv-key" data-field="eu_key" data-row="${idx}" data-old-key="${esc(key)}" type="text" value="${esc(key)}" placeholder="通道名，例如 DA/多巴胺/COR" />
                <input class="ir-graph-prop ir-kv-val" data-field="eu_val" data-row="${idx}" type="text" value="${esc(val)}" placeholder="增量，例如 0.2 或 -0.1 或 {{{var}}}" />
                <button class="ghost danger ir-kv-remove" data-action="eu_remove" data-row="${idx}" type="button">移除</button>
              </div>`;
            })
            .join("")
        : `<div class="empty-state">当前没有任何通道增量。点击下方「添加通道」开始。</div>`;
    body += `<div class="sub-section">
      <div class="sub-title">递质通道增量（emotion_update）</div>
      <div class="soft-note">每行表示一个“情绪递质通道（NT 通道）”的增量。支持缩写或中文名；数值可为负。</div>
      <div class="ir-kv-list">${rowsHtml}</div>
      <div class="toolbar" style="margin-top:10px;">
        <button class="ghost ir-kv-add" data-action="eu_add" type="button">+ 添加通道</button>
      </div>
    </div>`;
  } else if (type === "action_trigger") {
    const params = cfg.params && typeof cfg.params === "object" ? cfg.params : {};
    const paramEntries = Object.entries(params).filter(([k]) => String(k || "").trim());
    const paramRows =
      paramEntries.length
        ? paramEntries
            .map(([k, v], idx) => {
              const key = String(k || "");
              const val = v === undefined || v === null ? "" : String(v);
              return `<div class="ir-kv-row" data-row="${idx}">
                <input class="ir-graph-prop ir-kv-key" data-field="at_param_key" data-row="${idx}" data-old-key="${esc(key)}" type="text" value="${esc(key)}" placeholder="参数名，例如 target_ref_object_id" />
                <input class="ir-graph-prop ir-kv-val" data-field="at_param_val" data-row="${idx}" type="text" value="${esc(val)}" placeholder="参数值，可用模板 {{{var}}}" />
                <button class="ghost danger ir-kv-remove" data-action="at_param_remove" data-row="${idx}" type="button">移除</button>
              </div>`;
            })
            .join("")
        : `<div class="empty-state">当前没有 params。你可以直接用下方按钮添加常用目标字段。</div>`;

    body += renderRow("行动ID（action_id，可选；留空会自动生成）", "action_id", cfg.action_id ?? cfg.id ?? "", "text", `<div class="soft-note">建议稳定命名，用于行动节点去重与审计；留空则由规则引擎自动生成。</div>`);
    body += renderRow("行动类型（action_kind，例如 attention_focus / recall / custom）", "action_kind", cfg.action_kind ?? cfg.kind ?? "custom", "text");
    body += `<article class="setting-item">
      <label>展开来源（from，选填）</label>
      <select class="ir-graph-prop" data-field="from">
        <option value="" ${String(cfg.from || "") === "" ? "selected" : ""}>单条触发（不展开）</option>
        <option value="cfs_matches" ${String(cfg.from || "") === "cfs_matches" ? "selected" : ""}>对命中的认知感受对象展开（cfs_matches）</option>
        <option value="metric_matches" ${String(cfg.from || "") === "metric_matches" ? "selected" : ""}>对命中的指标对象展开（metric_matches）</option>
      </select>
      <div class="soft-note">展开后可生成多条行动触发；可用模板变量：<code>{{{match_ref_object_id}}}</code> / <code>{{{match_item_id}}}</code> / <code>{{{match_value}}}</code>。</div>
    </article>`;
    body += `<article class="setting-item">
      <label>展开策略（match_policy，选填）</label>
      <select class="ir-graph-prop" data-field="match_policy">
        <option value="all" ${String(cfg.match_policy || "all") === "all" ? "selected" : ""}>全部（all）</option>
        <option value="strongest" ${String(cfg.match_policy || "") === "strongest" ? "selected" : ""}>最强一个（strongest）</option>
        <option value="first" ${String(cfg.match_policy || "") === "first" ? "selected" : ""}>第一个（first）</option>
      </select>
    </article>`;
    body += renderRow("最多生成条数（max_triggers，可选）", "max_triggers", cfg.max_triggers ?? cfg.max ?? "", "number");
    body += renderRow("驱动力增益（gain，可用模板 {{{var}}}）", "gain", cfg.gain ?? cfg.drive_gain ?? 0.0, "text", `<div class="soft-note">支持数值（0.4）或模板（<code>{{{match_value}}}</code>）。</div>`);
    body += renderRow("阈值（threshold，drive>=threshold 才会尝试执行）", "threshold", cfg.threshold ?? 1.0, "text");
    body += renderRow("冷却 tick（cooldown_ticks）", "cooldown_ticks", cfg.cooldown_ticks ?? 0, "number");

    body += `<div class="sub-section">
      <div class="sub-title">常用参数快捷填充（可选）</div>
      <div class="soft-note">提示：对于 <code>attention_focus</code> 行动，只要 params 中包含 target_* 字段，行动模块会自动补齐 focus_directive（减少冗长配置）。</div>
      <div class="toolbar">
        <button class="ghost" data-action="at_params_fill_focus" type="button">填入: 注意力聚焦 target_* + strength</button>
        <button class="ghost" data-action="at_params_fill_recall" type="button">填入: 回忆 trigger_kind/strength</button>
      </div>
    </div>`;

    body += `<div class="sub-section">
      <div class="sub-title">params（可选参数，键值对）</div>
      <div class="ir-kv-list">${paramRows}</div>
      <div class="toolbar" style="margin-top:10px;">
        <button class="ghost ir-kv-add" data-action="at_param_add" type="button">+ 添加参数</button>
      </div>
    </div>`;
  } else if (type === "pool_energy") {
    const sel = cfg.selector && typeof cfg.selector === "object" ? cfg.selector : {};
    const selMode = String(sel.mode || "all");
    body += `<article class="setting-item">
      <label>目标选择（selector.mode）</label>
      <select class="ir-graph-prop" data-field="selector_mode">
        <option value="all" ${selMode === "all" ? "selected" : ""}>全部对象（all）</option>
        <option value="specific_ref" ${selMode === "specific_ref" ? "selected" : ""}>特定对象（specific_ref）</option>
        <option value="specific_item" ${selMode === "specific_item" ? "selected" : ""}>特定条目（specific_item）</option>
        <option value="contains_text" ${selMode === "contains_text" ? "selected" : ""}>包含特征/文本（contains_text）</option>
        <option value="top_n" ${selMode === "top_n" ? "selected" : ""}>能量 Top-N（top_n）</option>
      </select>
      <div class="soft-note">contains_text 会匹配 display/详情/属性/特征/运行态绑定属性展示。</div>
    </article>`;
    body += renderRow("ref_object_id（specific_ref 用）", "selector_ref_object_id", sel.ref_object_id ?? "", "text");
    body += renderRow("ref_object_type（可选）", "selector_ref_object_type", sel.ref_object_type ?? "", "text");
    body += renderRow("item_id（specific_item 用）", "selector_item_id", sel.item_id ?? "", "text");
    body += renderRow("contains_text（contains_text 用）", "selector_contains_text", sel.contains_text ?? "", "text");
    body += renderRow("top_n（top_n 用）", "selector_top_n", sel.top_n ?? "", "number");
    body += renderRow("ref_object_types（逗号，可选过滤）", "selector_ref_object_types", a(sel.ref_object_types).join(","), "text");
    body += renderRow("实能量增量（delta_er，可为负，支持模板）", "delta_er", cfg.delta_er ?? cfg.er ?? 0.0, "text");
    body += renderRow("虚能量增量（delta_ev，可为负，支持模板）", "delta_ev", cfg.delta_ev ?? cfg.ev ?? 0.0, "text");
    body += `<article class="setting-item">
      <label>缺失时创建（create_if_missing）</label>
      <label class="toggle-row"><input class="ir-graph-prop" data-field="create_if_missing" type="checkbox" ${cfg.create_if_missing ? "checked" : ""} /><span>创建</span></label>
      <small>仅对 specific_ref 生效；且只有增量为正时才会创建（安全）。</small>
    </article>`;
    body += renderRow("创建对象类型（create_ref_object_type，例如 sa/st）", "create_ref_object_type", cfg.create_ref_object_type ?? "", "text");
    body += renderRow("创建展示（create_display，可选）", "create_display", cfg.create_display ?? "", "text");
    body += renderRow("原因（reason，可选）", "reason", cfg.reason ?? "", "text");
  } else if (type === "pool_bind_attribute") {
    const sel = cfg.selector && typeof cfg.selector === "object" ? cfg.selector : {};
    const selMode = String(sel.mode || "all");
    const attr = cfg.attribute && typeof cfg.attribute === "object" ? cfg.attribute : {};
    body += `<article class="setting-item">
      <label>目标选择（selector.mode）</label>
      <select class="ir-graph-prop" data-field="selector_mode">
        <option value="all" ${selMode === "all" ? "selected" : ""}>全部对象（all）</option>
        <option value="specific_ref" ${selMode === "specific_ref" ? "selected" : ""}>特定对象（specific_ref）</option>
        <option value="specific_item" ${selMode === "specific_item" ? "selected" : ""}>特定条目（specific_item）</option>
        <option value="contains_text" ${selMode === "contains_text" ? "selected" : ""}>包含特征/文本（contains_text）</option>
        <option value="top_n" ${selMode === "top_n" ? "selected" : ""}>能量 Top-N（top_n）</option>
      </select>
    </article>`;
    body += renderRow("ref_object_id（specific_ref 用）", "selector_ref_object_id", sel.ref_object_id ?? "", "text");
    body += renderRow("ref_object_type（可选）", "selector_ref_object_type", sel.ref_object_type ?? "", "text");
    body += renderRow("item_id（specific_item 用）", "selector_item_id", sel.item_id ?? "", "text");
    body += renderRow("contains_text（contains_text 用）", "selector_contains_text", sel.contains_text ?? "", "text");
    body += renderRow("top_n（top_n 用）", "selector_top_n", sel.top_n ?? "", "number");
    body += renderRow("ref_object_types（逗号，可选过滤）", "selector_ref_object_types", a(sel.ref_object_types).join(","), "text");

    body += `<div class="sub-section">
      <div class="sub-title">属性字段（attribute.*）</div>
      <div class="settings-grid">
        <article class="setting-item"><label>attribute_name（属性名）</label><input class="ir-graph-prop" data-field="attr_name" type="text" value="${esc(String(attr.attribute_name ?? ""))}" /></article>
        <article class="setting-item"><label>attribute_value（属性值，可选）</label><input class="ir-graph-prop" data-field="attr_value" type="text" value="${esc(String(attr.attribute_value ?? ""))}" /></article>
        <article class="setting-item"><label>raw（原始文本，可选）</label><input class="ir-graph-prop" data-field="attr_raw" type="text" value="${esc(String(attr.raw ?? ""))}" /></article>
        <article class="setting-item"><label>display（展示文本，可选）</label><input class="ir-graph-prop" data-field="attr_display" type="text" value="${esc(String(attr.display ?? ""))}" /></article>
        <article class="setting-item">
          <label>value_type（值类型）</label>
          <select class="ir-graph-prop" data-field="attr_value_type">
            <option value="discrete" ${String(attr.value_type || "discrete") === "discrete" ? "selected" : ""}>离散（discrete）</option>
            <option value="numerical" ${String(attr.value_type || "") === "numerical" ? "selected" : ""}>数值（numerical）</option>
          </select>
        </article>
        <article class="setting-item">
          <label>modality（模态）</label>
          <select class="ir-graph-prop" data-field="attr_modality">
            <option value="internal" ${String(attr.modality || "internal") === "internal" ? "selected" : ""}>内部（internal）</option>
            <option value="external" ${String(attr.modality || "") === "external" ? "selected" : ""}>外部（external）</option>
          </select>
        </article>
        <article class="setting-item"><label>er / ev（可选，属性能量）</label><input class="ir-graph-prop" data-field="attr_er" type="text" value="${esc(String(attr.er ?? 0.0))}" /><input class="ir-graph-prop" data-field="attr_ev" type="text" value="${esc(String(attr.ev ?? 0.0))}" /></article>
      </div>
    </div>`;

    body += renderRow("原因（reason，可选）", "reason", cfg.reason ?? "", "text", `<div class="soft-note">说明：属性刺激元默认折叠绑定在锚点对象上，避免在状态池中出现大量 SA/CSA 噪音。</div>`);
  } else if (type === "delay") {
    body += renderRow("延时 tick（ticks）", "ticks", cfg.ticks ?? 2, "number", `<div class="soft-note">说明：delay（延时）节点内部包含一个 then 动作列表；支持嵌套 branch/delay，用于表达“期待验证/不验”等流程。</div>`);
    body += `<div class="sub-section">
      <div class="sub-title">延时后动作（then）</div>
      ${_irFlowRenderActionList(a(cfg.then), "then", 0)}
    </div>`;
  } else if (type === "branch") {
    // MVP: root branch 目前先提供 metric 条件编辑（满足期待/压力验证等主要用例）。
    const when = cfg.when && typeof cfg.when === "object" ? cfg.when : { metric: { preset: "reward_state", mode: "state", op: ">", value: 0 } };
    const whenType = "metric"; // keep MVP simple
    const whenSpec = when.metric && typeof when.metric === "object" ? when.metric : {};
    const sel = whenSpec.selector && typeof whenSpec.selector === "object" ? whenSpec.selector : {};
    const selMode = String(sel.mode || "all");
    const presetOptions = _irFlowMetricPresetOptionsHtml(whenSpec.preset || "");

    body += `<div class="sub-section">
      <div class="sub-title">分支条件（when，MVP: metric）</div>
      <div class="settings-grid">
        <article class="setting-item">
          <label>指标预设（preset）</label>
          <select class="ir-graph-prop" data-field="when_preset">${presetOptions}</select>
        </article>
        <article class="setting-item">
          <label>取值方式（mode）</label>
          <select class="ir-graph-prop" data-field="when_mode">
            <option value="state" ${String(whenSpec.mode || "state") === "state" ? "selected" : ""}>state（状态）</option>
            <option value="delta" ${String(whenSpec.mode || "") === "delta" ? "selected" : ""}>delta（变化量）</option>
            <option value="avg_rate" ${String(whenSpec.mode || "") === "avg_rate" ? "selected" : ""}>avg_rate（变化率）</option>
          </select>
        </article>
        <article class="setting-item">
          <label>比较符（op）</label>
          <select class="ir-graph-prop" data-field="when_op">
            <option value=">=" ${String(whenSpec.op || ">=") === ">=" ? "selected" : ""}>&gt;=</option>
            <option value=">" ${String(whenSpec.op || "") === ">" ? "selected" : ""}>&gt;</option>
            <option value="<=" ${String(whenSpec.op || "") === "<=" ? "selected" : ""}>&lt;=</option>
            <option value="<" ${String(whenSpec.op || "") === "<" ? "selected" : ""}>&lt;</option>
            <option value="exists" ${String(whenSpec.op || "") === "exists" ? "selected" : ""}>exists</option>
            <option value="changed" ${String(whenSpec.op || "") === "changed" ? "selected" : ""}>changed</option>
          </select>
        </article>
        <article class="setting-item">
          <label>阈值（value，可用模板 {{{var}}}）</label>
          <input class="ir-graph-prop" data-field="when_value" type="text" value="${esc(String(whenSpec.value ?? ""))}" />
        </article>
        <article class="setting-item">
          <label>窗口 tick（window_ticks，avg_rate 用）</label>
          <input class="ir-graph-prop" data-field="when_window_ticks" type="number" step="1" value="${esc(String(whenSpec.window_ticks ?? 2))}" />
        </article>
        <article class="setting-item">
          <label>对象选择（selector.mode）</label>
          <select class="ir-graph-prop" data-field="when_selector_mode">
            <option value="all" ${selMode === "all" ? "selected" : ""}>all</option>
            <option value="specific_item" ${selMode === "specific_item" ? "selected" : ""}>specific_item</option>
            <option value="specific_ref" ${selMode === "specific_ref" ? "selected" : ""}>specific_ref</option>
            <option value="contains_text" ${selMode === "contains_text" ? "selected" : ""}>contains_text</option>
            <option value="top_n" ${selMode === "top_n" ? "selected" : ""}>top_n</option>
          </select>
        </article>
        <article class="setting-item"><label>selector.item_id</label><input class="ir-graph-prop" data-field="when_selector_item_id" type="text" value="${esc(String(sel.item_id ?? ""))}" /></article>
        <article class="setting-item"><label>selector.ref_object_id</label><input class="ir-graph-prop" data-field="when_selector_ref_object_id" type="text" value="${esc(String(sel.ref_object_id ?? ""))}" /></article>
        <article class="setting-item"><label>selector.contains_text</label><input class="ir-graph-prop" data-field="when_selector_contains_text" type="text" value="${esc(String(sel.contains_text ?? ""))}" /></article>
        <article class="setting-item"><label>selector.top_n</label><input class="ir-graph-prop" data-field="when_selector_top_n" type="number" step="1" value="${esc(String(sel.top_n ?? ""))}" /></article>
        <article class="setting-item"><label>selector.ref_object_types（逗号）</label><input class="ir-graph-prop" data-field="when_selector_ref_object_types" type="text" value="${esc(a(sel.ref_object_types).join(','))}" /></article>
      </div>
      <div class="soft-note">提示：更复杂的 when（例如 any/all/not 或 prev_gate）后续会继续补齐；目前可以满足“验证/不验”的主流程。</div>
    </div>`;

    body += `<div class="sub-section">
      <div class="sub-title">满足（then）</div>
      ${_irFlowRenderActionList(a(cfg.then), "then", 0)}
    </div>`;
    body += `<div class="sub-section">
      <div class="sub-title">不满足（else）</div>
      ${_irFlowRenderActionList(a(cfg.else), "else", 0)}
    </div>`;
    body += `<div class="sub-section">
      <div class="sub-title">报错（on_error）</div>
      ${_irFlowRenderActionList(a(cfg.on_error), "on_error", 0)}
    </div>`;
  } else if (type === "log") {
    body += renderRow("日志内容（text）", "text", cfg.text ?? "", "textarea");
  } else {
    body += `<div class="empty-state">该节点类型暂未提供表单编辑器（type=${esc(type)}）。建议回到「先天规则」页使用 YAML 或表单编辑器完成配置，然后再用图形编辑器做布局。</div>`;
  }

  body += `</div>
    <div class="soft-note">提示：修改完后点击「应用到规则」才会写回表单草稿；再通过「校验/保存并热加载」落盘。</div>
  </div>`;

  E.irGraphProps.innerHTML = body;

  // Delete selected node button (extra discoverability) / 删除按钮（增强可发现性）
  const delBtn = E.irGraphProps.querySelector("#irGraphDeleteSelectedBtn");
  delBtn?.addEventListener("click", () => {
    if (!S.irGraph.graph) return;
    const node2 = _findIrGraphNode(S.irGraph.graph, String(S.irGraph.selectedNodeId || ""));
    if (!node2) return;
    if (String(node2.type || "") === "root") {
      irGraphFb("条件汇总节点不可删除。", "err");
      return;
    }
    const ok = confirm(`确定删除节点「${_irGraphNodeTitle(node2)}」吗？\\n\\n说明：将同时删除与它相关的连线。`);
    if (!ok) return;
    deleteSelectedIrGraphNode();
  });

  // Bind prop edits / 绑定属性编辑
  E.irGraphProps.querySelectorAll(".ir-graph-prop").forEach((nodeEl) => {
    const field = String(nodeEl.dataset.field || "");
    const isSelect = nodeEl.tagName === "SELECT";
    const isTextArea = nodeEl.tagName === "TEXTAREA";
    const handler = () => {
      const g2 = S.irGraph.graph;
      if (!g2) return;
      const node2 = _findIrGraphNode(g2, String(S.irGraph.selectedNodeId || ""));
      if (!node2) return;
      if (!node2.config || typeof node2.config !== "object") node2.config = {};

      // Parse field value / 解析字段值
      let v = isTextArea ? nodeEl.value : nodeEl.value;
      if (nodeEl.type === "checkbox") v = Boolean(nodeEl.checked);
      if (nodeEl.type === "number") v = nodeEl.value === "" ? "" : Number(nodeEl.value);
      if (field === "kinds" || field === "candidate_hint_any") {
        v = String(v || "")
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean);
      }

      const coerceMaybeNumberOrTemplate = (raw) => {
        const s = String(raw ?? "").trim();
        if (!s) return "";
        if (s.includes("{{{")) return s;
        const n = Number(s);
        return Number.isFinite(n) ? n : s;
      };

      // Nested editor mapping / 嵌套字段映射
      if ((node2.type === "metric" || node2.type === "pool_energy" || node2.type === "pool_bind_attribute") && field.startsWith("selector_")) {
        // selector is nested: config.selector.*
        // selector 为嵌套字段：config.selector.*
        const sel = node2.config.selector && typeof node2.config.selector === "object" ? node2.config.selector : {};
        const k = field.replace("selector_", "");
        if (k === "ref_object_types") {
          sel.ref_object_types = String(v || "")
            .split(",")
            .map((x) => x.trim())
            .filter(Boolean);
        } else {
          sel[k] = v;
        }
        node2.config.selector = sel;
      } else if (node2.type === "pool_bind_attribute" && field.startsWith("attr_")) {
        // attribute is nested: config.attribute.*
        // attribute 为嵌套字段：config.attribute.*
        const attr = node2.config.attribute && typeof node2.config.attribute === "object" ? node2.config.attribute : {};
        const k = field.replace("attr_", "");
        if (k === "name") attr.attribute_name = String(v || "");
        else if (k === "value") attr.attribute_value = v;
        else if (k === "raw") attr.raw = String(v || "");
        else if (k === "display") attr.display = String(v || "");
        else if (k === "value_type") attr.value_type = String(v || "discrete");
        else if (k === "modality") attr.modality = String(v || "internal");
        else if (k === "er") attr.er = coerceMaybeNumberOrTemplate(v);
        else if (k === "ev") attr.ev = coerceMaybeNumberOrTemplate(v);
        else attr[k] = v;
        node2.config.attribute = attr;
      } else if (node2.type === "cfs_emit" && field.startsWith("strength_")) {
        // strength is nested: config.strength.*
        // strength 为嵌套字段：config.strength.*
        const st = node2.config.strength && typeof node2.config.strength === "object" ? node2.config.strength : {};
        const k = field.replace("strength_", "");
        if (k === "policy") st.policy = String(v || "linear_clamp");
        else if (k === "from") st.from = String(v || "match_value");
        else if (k === "var") st.var = String(v || "");
        else if (k === "abs") st.abs = Boolean(v);
        else if (k === "invert") st.invert = Boolean(v);
        else if (k === "min") st.min = v;
        else if (k === "max") st.max = v;
        else if (k === "out_min") st.out_min = v;
        else if (k === "out_max") st.out_max = v;
        else if (k === "scale") st.scale = v;
        else if (k === "offset") st.offset = v;
        else st[k] = v;
        node2.config.strength = st;
      } else if (node2.type === "cfs_emit" && field.startsWith("target_")) {
        // target is nested: config.target.* (and can be omitted when from=match)
        // target 为嵌套字段：config.target.*（当 from=match 时可省略）
        const k = field.replace("target_", "");
        const tFrom = String((k === "from" ? v : (node2.config.target || {}).from) || "match");
        if (k === "from") {
          if (tFrom === "match" || !tFrom) {
            delete node2.config.target;
          } else {
            node2.config.target = { from: tFrom };
          }
        } else {
          const t = node2.config.target && typeof node2.config.target === "object" ? node2.config.target : { from: tFrom };
          // Map UI fields to engine schema.
          // UI 字段映射到引擎字段。
          if (k === "ref_object_id") t.ref_object_id = String(v || "");
          else if (k === "ref_object_type") t.ref_object_type = String(v || "");
          else if (k === "item_id") t.item_id = String(v || "");
          else if (k === "display") t.display = String(v || "");
          else t[k] = v;
          if (String(t.from || "match") === "match") delete node2.config.target;
          else node2.config.target = t;
        }
      } else if (node2.type === "cfs_emit" && field.startsWith("bindattr_")) {
        // bind_attribute is nested: config.bind_attribute.*
        // bind_attribute 为嵌套字段：config.bind_attribute.*
        const k = field.replace("bindattr_", "");
        if (k === "enabled") {
          if (!Boolean(v)) delete node2.config.bind_attribute;
          else node2.config.bind_attribute = node2.config.bind_attribute && typeof node2.config.bind_attribute === "object" ? node2.config.bind_attribute : {};
        } else {
          const b = node2.config.bind_attribute && typeof node2.config.bind_attribute === "object" ? node2.config.bind_attribute : {};
          if (k === "attribute_name") b.attribute_name = String(v || "");
          else if (k === "value_from") b.value_from = String(v || "strength");
          else if (k === "display") b.display = String(v || "");
          else if (k === "raw") b.raw = String(v || "");
          else if (k === "value_type") b.value_type = String(v || "numerical");
          else if (k === "modality") b.modality = String(v || "internal");
          else if (k === "er") b.er = v;
          else if (k === "ev") b.ev = v;
          else if (k === "reason") b.reason = String(v || "");
          else b[k] = v;
          node2.config.bind_attribute = b;
        }
      } else if (node2.type === "emotion_update" && (field === "eu_key" || field === "eu_val")) {
        // Emotion update payload is a dict: {channel: delta}
        // emotion_update 的 payload 是 dict：{通道: 增量}
        const row = nodeEl.closest(".ir-kv-row");
        const keyEl = row?.querySelector(".ir-kv-key");
        const valEl = row?.querySelector(".ir-kv-val");
        if (!keyEl || !valEl) return;
        const newKey = String(keyEl.value || "").trim();
        const oldKey = String(keyEl.dataset.oldKey || "").trim();
        const rawVal = String(valEl.value ?? "");
        const dv = coerceMaybeNumberOrTemplate(rawVal);
        if (!newKey) {
          _setIrGraphHint("通道名不能为空。");
          return;
        }
        if (oldKey && oldKey !== newKey) {
          delete node2.config[oldKey];
        }
        node2.config[newKey] = dv === "" ? 0.0 : dv;
        keyEl.dataset.oldKey = newKey;
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        _setIrGraphHint(`已修改递质通道：${newKey}`);
        return;
      } else if (node2.type === "action_trigger" && (field === "at_param_key" || field === "at_param_val")) {
        // params is a dict: config.params.{key}=value
        // params 是 dict：config.params.{key}=value
        const row = nodeEl.closest(".ir-kv-row");
        const keyEl = row?.querySelector(".ir-kv-key");
        const valEl = row?.querySelector(".ir-kv-val");
        if (!keyEl || !valEl) return;
        const newKey = String(keyEl.value || "").trim();
        const oldKey = String(keyEl.dataset.oldKey || "").trim();
        const rawVal = String(valEl.value ?? "");
        const params = node2.config.params && typeof node2.config.params === "object" ? node2.config.params : {};
        if (!newKey) {
          _setIrGraphHint("参数名不能为空。");
          return;
        }
        if (oldKey && oldKey !== newKey) {
          delete params[oldKey];
        }
        params[newKey] = coerceMaybeNumberOrTemplate(rawVal);
        node2.config.params = params;
        keyEl.dataset.oldKey = newKey;
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        _setIrGraphHint(`已修改 params：${newKey}`);
        return;
      } else if (node2.type === "branch" && field.startsWith("when_")) {
        // Root branch.when is nested: config.when.metric.* (MVP)
        // 分支节点的 when 为嵌套字段：config.when.metric.*（原型先做 metric 口径）
        const ensureMetric = () => {
          const w = node2.config.when && typeof node2.config.when === "object" ? node2.config.when : {};
          const m = w.metric && typeof w.metric === "object" ? w.metric : {};
          w.metric = m;
          node2.config.when = w;
          return m;
        };
        const metric = ensureMetric();
        const sel = metric.selector && typeof metric.selector === "object" ? metric.selector : {};
        const k = field.replace("when_", "");
        if (k === "preset") metric.preset = String(v || "");
        else if (k === "mode") metric.mode = String(v || "state");
        else if (k === "op") metric.op = String(v || ">=");
        else if (k === "value") metric.value = coerceMaybeNumberOrTemplate(v);
        else if (k === "window_ticks") metric.window_ticks = v;
        else if (k.startsWith("selector_")) {
          const sk = k.replace("selector_", "");
          if (sk === "ref_object_types") {
            sel.ref_object_types = String(v || "")
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean);
          } else {
            sel[sk] = v;
          }
          metric.selector = sel;
        } else {
          metric[k] = v;
        }
        // Ensure lists exist for the flow editor.
        // 确保子动作列表存在，便于动作流编辑器追加/删除。
        if (!Array.isArray(node2.config.then)) node2.config.then = [];
        if (!Array.isArray(node2.config.else)) node2.config.else = [];
        if (!Array.isArray(node2.config.on_error)) node2.config.on_error = [];
      } else {
        // Special numeric-ish text fields: prefer number when possible (but keep templates as string).
        // 部分“数字/模板混用”的字段：能转数字就转，模板保持字符串。
        if (node2.type === "action_trigger" && (field === "gain" || field === "threshold")) node2.config[field] = coerceMaybeNumberOrTemplate(v);
        else if (node2.type === "pool_energy" && (field === "delta_er" || field === "delta_ev")) node2.config[field] = coerceMaybeNumberOrTemplate(v);
        else node2.config[field] = v;
      }

      _markIrGraphDirty();
      _updateIrGraphNodeSummary(node2);
      renderIrGraphEdges();
      _setIrGraphHint(`已修改节点属性：${field}`);
    };
    nodeEl.addEventListener(isSelect ? "change" : "input", handler);
  });

  // Bind key-value editor buttons / 绑定键值对编辑器按钮
  E.irGraphProps.querySelectorAll("button[data-action]").forEach((btn) => {
    const act = String(btn.dataset.action || "");
    btn.addEventListener("click", () => {
      const g2 = S.irGraph.graph;
      if (!g2) return;
      const node2 = _findIrGraphNode(g2, String(S.irGraph.selectedNodeId || ""));
      if (!node2) return;
      if (!node2.config || typeof node2.config !== "object") node2.config = {};

      const addKey = (obj, base) => {
        const used = new Set(Object.keys(obj || {}));
        if (!used.has(base)) return base;
        for (let i = 2; i < 64; i++) {
          const k = `${base}${i}`;
          if (!used.has(k)) return k;
        }
        return `${base}_${Date.now()}`;
      };

      if (act === "eu_add" && node2.type === "emotion_update") {
        const k = addKey(node2.config, "DA");
        node2.config[k] = 0.0;
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        renderIrGraphProps();
        return;
      }
      if (act === "eu_remove" && node2.type === "emotion_update") {
        const row = Number(btn.dataset.row || "0");
        const entries = Object.entries(node2.config || {}).filter(([k]) => String(k || "").trim());
        const key = entries[row]?.[0];
        if (key) delete node2.config[key];
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        renderIrGraphProps();
        return;
      }

      if (act === "at_param_add" && node2.type === "action_trigger") {
        const params = node2.config.params && typeof node2.config.params === "object" ? node2.config.params : {};
        const k = addKey(params, "param");
        params[k] = "";
        node2.config.params = params;
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        renderIrGraphProps();
        return;
      }
      if (act === "at_param_remove" && node2.type === "action_trigger") {
        const row = Number(btn.dataset.row || "0");
        const params = node2.config.params && typeof node2.config.params === "object" ? node2.config.params : {};
        const entries = Object.entries(params).filter(([k]) => String(k || "").trim());
        const key = entries[row]?.[0];
        if (key) delete params[key];
        node2.config.params = params;
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        renderIrGraphProps();
        return;
      }

      if (act === "at_params_fill_focus" && node2.type === "action_trigger") {
        const params = node2.config.params && typeof node2.config.params === "object" ? node2.config.params : {};
        params.target_ref_object_id = params.target_ref_object_id || "{{{match_ref_object_id}}}";
        params.target_ref_object_type = params.target_ref_object_type || "{{{match_ref_object_type}}}";
        params.target_item_id = params.target_item_id || "{{{match_item_id}}}";
        params.target_display = params.target_display || "{{{match_display}}}";
        params.strength = params.strength || "{{{match_value}}}";
        params.focus_boost = params.focus_boost ?? 0.9;
        params.ttl_ticks = params.ttl_ticks ?? 2;
        node2.config.params = params;
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        renderIrGraphProps();
        return;
      }
      if (act === "at_params_fill_recall" && node2.type === "action_trigger") {
        const params = node2.config.params && typeof node2.config.params === "object" ? node2.config.params : {};
        params.trigger_kind = params.trigger_kind || "{{{match_kind}}}";
        params.trigger_strength = params.trigger_strength || "{{{match_value}}}";
        node2.config.params = params;
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        renderIrGraphProps();
        return;
      }
    });
  });

  // -------------------------------------------------------------------
  // Flow editor bindings (nested actions) / 动作流编辑器绑定（delay/branch）
  // -------------------------------------------------------------------

  E.irGraphProps.querySelectorAll(".ir-flow-prop").forEach((el) => {
    const apath = String(el.dataset.apath || "");
    const field = String(el.dataset.field || "");
    const isSelect = el.tagName === "SELECT";
    const isTextArea = el.tagName === "TEXTAREA";
    if (!apath || !field) return;

    const onChange = () => {
      const g2 = S.irGraph.graph;
      if (!g2) return;
      const node2 = _findIrGraphNode(g2, String(S.irGraph.selectedNodeId || ""));
      if (!node2) return;
      if (!node2.config || typeof node2.config !== "object") node2.config = {};

      const ref = _irFlowResolveActionRef(node2.config, apath);
      if (!ref) return;

      // Parse value
      let v = isTextArea ? el.value : el.value;
      if (el.type === "checkbox") v = Boolean(el.checked);
      if (el.type === "number") v = el.value === "" ? "" : Number(el.value);

      const coerceMaybeNumberOrTemplate = (raw) => {
        const s = String(raw ?? "").trim();
        if (!s) return "";
        if (s.includes("{{{")) return s;
        const n = Number(s);
        return Number.isFinite(n) ? n : s;
      };

      // type switch
      if (field === "type") {
        ref.list[ref.idx] = _irFlowDefaultAction(String(v || "log"));
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        renderIrGraphProps();
        return;
      }

      let act = ref.action;
      const k = _irFlowActionKey(act) || "log";

      if (k === "log") {
        ref.list[ref.idx] = { log: String(v || "") };
      } else if (k === "cfs_emit") {
        const spec = act.cfs_emit && typeof act.cfs_emit === "object" ? act.cfs_emit : {};
        if (field === "kind") spec.kind = String(v || "");
        else if (field === "scope") spec.scope = String(v || "object");
        else if (field === "from") spec.from = String(v || "metric_matches");
        else if (field.startsWith("strength_")) {
          const st = spec.strength && typeof spec.strength === "object" ? spec.strength : {};
          const kk = field.replace("strength_", "");
          if (kk === "policy") st.policy = String(v || "linear_clamp");
          else if (kk === "from") st.from = String(v || "match_value");
          else if (kk === "var") st.var = String(v || "");
          else if (kk === "min") st.min = v;
          else if (kk === "max") st.max = v;
          else if (kk === "out_min") st.out_min = v;
          else if (kk === "out_max") st.out_max = v;
          else st[kk] = v;
          spec.strength = st;
        } else if (field.startsWith("bindattr_")) {
          const kk = field.replace("bindattr_", "");
          if (kk === "enabled") {
            if (!Boolean(v)) delete spec.bind_attribute;
            else spec.bind_attribute = spec.bind_attribute && typeof spec.bind_attribute === "object" ? spec.bind_attribute : {};
          } else {
            const b = spec.bind_attribute && typeof spec.bind_attribute === "object" ? spec.bind_attribute : {};
            if (kk === "attribute_name") b.attribute_name = String(v || "");
            else if (kk === "display") b.display = String(v || "");
            else b[kk] = v;
            spec.bind_attribute = b;
          }
        } else {
          spec[field] = v;
        }
        act.cfs_emit = spec;
        ref.list[ref.idx] = act;
      } else if (k === "focus") {
        const spec = act.focus && typeof act.focus === "object" ? act.focus : {};
        spec[field] = v;
        act.focus = spec;
        ref.list[ref.idx] = act;
      } else if (k === "emit_script") {
        const spec = act.emit_script && typeof act.emit_script === "object" ? act.emit_script : {};
        spec[field] = v;
        act.emit_script = spec;
        ref.list[ref.idx] = act;
      } else if (k === "emotion_update" && (field === "eu_key" || field === "eu_val")) {
        const row = el.closest(".ir-kv-row");
        const keyEl = row?.querySelector(".ir-kv-key");
        const valEl = row?.querySelector(".ir-kv-val");
        if (!keyEl || !valEl) return;
        const newKey = String(keyEl.value || "").trim();
        const oldKey = String(keyEl.dataset.oldKey || "").trim();
        if (!newKey) return;
        const payload = act.emotion_update && typeof act.emotion_update === "object" ? act.emotion_update : {};
        if (oldKey && oldKey !== newKey) delete payload[oldKey];
        payload[newKey] = coerceMaybeNumberOrTemplate(valEl.value);
        act.emotion_update = payload;
        keyEl.dataset.oldKey = newKey;
        ref.list[ref.idx] = act;
      } else if (k === "action_trigger" && (field === "at_param_key" || field === "at_param_val")) {
        const row = el.closest(".ir-kv-row");
        const keyEl = row?.querySelector(".ir-kv-key");
        const valEl = row?.querySelector(".ir-kv-val");
        if (!keyEl || !valEl) return;
        const newKey = String(keyEl.value || "").trim();
        const oldKey = String(keyEl.dataset.oldKey || "").trim();
        if (!newKey) return;
        const spec = act.action_trigger && typeof act.action_trigger === "object" ? act.action_trigger : {};
        const params = spec.params && typeof spec.params === "object" ? spec.params : {};
        if (oldKey && oldKey !== newKey) delete params[oldKey];
        params[newKey] = coerceMaybeNumberOrTemplate(valEl.value);
        spec.params = params;
        act.action_trigger = spec;
        keyEl.dataset.oldKey = newKey;
        ref.list[ref.idx] = act;
      } else if (k === "action_trigger") {
        const spec = act.action_trigger && typeof act.action_trigger === "object" ? act.action_trigger : {};
        if (field === "gain" || field === "threshold") spec[field] = coerceMaybeNumberOrTemplate(v);
        else spec[field] = v;
        act.action_trigger = spec;
        ref.list[ref.idx] = act;
      } else if (k === "pool_energy") {
        const spec = act.pool_energy && typeof act.pool_energy === "object" ? act.pool_energy : {};
        if (field.startsWith("selector_")) {
          const sel = spec.selector && typeof spec.selector === "object" ? spec.selector : {};
          const kk = field.replace("selector_", "");
          if (kk === "ref_object_types") {
            sel.ref_object_types = String(v || "").split(",").map((x) => x.trim()).filter(Boolean);
          } else {
            sel[kk] = v;
          }
          spec.selector = sel;
        } else if (field === "create_if_missing") {
          spec.create_if_missing = Boolean(v);
        } else if (field === "delta_er" || field === "delta_ev") {
          spec[field] = coerceMaybeNumberOrTemplate(v);
        } else {
          spec[field] = v;
        }
        act.pool_energy = spec;
        ref.list[ref.idx] = act;
      } else if (k === "pool_bind_attribute") {
        const spec = act.pool_bind_attribute && typeof act.pool_bind_attribute === "object" ? act.pool_bind_attribute : {};
        if (field.startsWith("selector_")) {
          const sel = spec.selector && typeof spec.selector === "object" ? spec.selector : {};
          const kk = field.replace("selector_", "");
          if (kk === "ref_object_types") {
            sel.ref_object_types = String(v || "").split(",").map((x) => x.trim()).filter(Boolean);
          } else {
            sel[kk] = v;
          }
          spec.selector = sel;
        } else if (field.startsWith("attr_")) {
          const attr = spec.attribute && typeof spec.attribute === "object" ? spec.attribute : {};
          const kk = field.replace("attr_", "");
          if (kk === "name") attr.attribute_name = String(v || "");
          else if (kk === "value") attr.attribute_value = v;
          else if (kk === "display") attr.display = String(v || "");
          else attr[kk] = v;
          spec.attribute = attr;
        } else {
          spec[field] = v;
        }
        act.pool_bind_attribute = spec;
        ref.list[ref.idx] = act;
      } else if (k === "delay") {
        const spec = act.delay && typeof act.delay === "object" ? act.delay : {};
        if (field === "ticks") spec.ticks = v;
        act.delay = spec;
        ref.list[ref.idx] = act;
      } else if (k === "branch") {
        const spec = act.branch && typeof act.branch === "object" ? act.branch : {};
        const ensureMetric = () => {
          const w = spec.when && typeof spec.when === "object" ? spec.when : {};
          const m = w.metric && typeof w.metric === "object" ? w.metric : {};
          w.metric = m;
          spec.when = w;
          return m;
        };
        const metric = ensureMetric();
        const sel = metric.selector && typeof metric.selector === "object" ? metric.selector : {};
        if (field === "when_preset") metric.preset = String(v || "");
        else if (field === "when_mode") metric.mode = String(v || "state");
        else if (field === "when_op") metric.op = String(v || ">=");
        else if (field === "when_value") metric.value = coerceMaybeNumberOrTemplate(v);
        else if (field === "when_window_ticks") metric.window_ticks = v;
        else if (field.startsWith("when_selector_")) {
          const kk = field.replace("when_selector_", "");
          if (kk === "ref_object_types") {
            sel.ref_object_types = String(v || "")
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean);
          } else {
            sel[kk] = v;
          }
          metric.selector = sel;
        } else {
          metric[field] = v;
        }
        // Ensure lists exist (for renderer stability)
        if (!Array.isArray(spec.then)) spec.then = [];
        if (!Array.isArray(spec.else)) spec.else = [];
        if (!Array.isArray(spec.on_error)) spec.on_error = [];
        act.branch = spec;
        ref.list[ref.idx] = act;
      } else {
        // Unknown action kind in nested editor: keep stable but do nothing.
        // 未识别的子动作类型：保持不动（安全）。
        return;
      }

      _markIrGraphDirty();
      _updateIrGraphNodeSummary(node2);
      _setIrGraphHint(`已修改子动作字段：${field}`);
    };

    el.addEventListener(isSelect ? "change" : "input", onChange);
  });

  E.irGraphProps.querySelectorAll("button[data-flow-action]").forEach((btn) => {
    const act = String(btn.dataset.flowAction || "");
    btn.addEventListener("click", () => {
      const g2 = S.irGraph.graph;
      if (!g2) return;
      const node2 = _findIrGraphNode(g2, String(S.irGraph.selectedNodeId || ""));
      if (!node2) return;
      if (!node2.config || typeof node2.config !== "object") node2.config = {};

      if (act === "add_action") {
        const listPath = String(btn.dataset.listPath || "");
        const listRef = _irFlowResolveListRef(node2.config, listPath);
        if (!listRef) return;
        const sel = E.irGraphProps.querySelector(`select.ir-flow-add-type[data-list-path=\"${CSS.escape(listPath)}\"]`);
        const t = sel ? String(sel.value || "log") : "log";
        listRef.list.push(_irFlowDefaultAction(t));
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        renderIrGraphProps();
        return;
      }
      if (act === "remove_action") {
        const apath = String(btn.dataset.apath || "");
        const ref = _irFlowResolveActionRef(node2.config, apath);
        if (!ref) return;
        ref.list.splice(ref.idx, 1);
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        renderIrGraphProps();
        return;
      }

      const addKey = (obj, base) => {
        const used = new Set(Object.keys(obj || {}));
        if (!used.has(base)) return base;
        for (let i = 2; i < 64; i++) {
          const k = `${base}${i}`;
          if (!used.has(k)) return k;
        }
        return `${base}_${Date.now()}`;
      };

      if (act === "eu_add" || act === "eu_remove") {
        const apath = String(btn.dataset.apath || "");
        const ref = _irFlowResolveActionRef(node2.config, apath);
        if (!ref) return;
        const action = ref.action;
        if (_irFlowActionKey(action) !== "emotion_update") return;
        const payload = action.emotion_update && typeof action.emotion_update === "object" ? action.emotion_update : {};
        if (act === "eu_add") {
          const k = addKey(payload, "DA");
          payload[k] = 0.0;
        } else {
          const row = Number(btn.dataset.row || "0");
          const entries = Object.entries(payload).filter(([kk]) => String(kk || "").trim());
          const key = entries[row]?.[0];
          if (key) delete payload[key];
        }
        action.emotion_update = payload;
        ref.list[ref.idx] = action;
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        renderIrGraphProps();
        return;
      }

      if (act === "at_param_add" || act === "at_param_remove" || act === "at_params_fill_focus" || act === "at_params_fill_recall") {
        const apath = String(btn.dataset.apath || "");
        const ref = _irFlowResolveActionRef(node2.config, apath);
        if (!ref) return;
        const action = ref.action;
        if (_irFlowActionKey(action) !== "action_trigger") return;
        const spec = action.action_trigger && typeof action.action_trigger === "object" ? action.action_trigger : {};
        const params = spec.params && typeof spec.params === "object" ? spec.params : {};

        if (act === "at_param_add") {
          const k = addKey(params, "param");
          params[k] = "";
        } else if (act === "at_param_remove") {
          const row = Number(btn.dataset.row || "0");
          const entries = Object.entries(params).filter(([kk]) => String(kk || "").trim());
          const key = entries[row]?.[0];
          if (key) delete params[key];
        } else if (act === "at_params_fill_focus") {
          params.target_ref_object_id = params.target_ref_object_id || "{{{match_ref_object_id}}}";
          params.target_ref_object_type = params.target_ref_object_type || "{{{match_ref_object_type}}}";
          params.target_item_id = params.target_item_id || "{{{match_item_id}}}";
          params.target_display = params.target_display || "{{{match_display}}}";
          params.strength = params.strength || "{{{match_value}}}";
          params.focus_boost = params.focus_boost ?? 0.9;
          params.ttl_ticks = params.ttl_ticks ?? 2;
        } else if (act === "at_params_fill_recall") {
          params.trigger_kind = params.trigger_kind || "{{{match_kind}}}";
          params.trigger_strength = params.trigger_strength || "{{{match_value}}}";
        }

        spec.params = params;
        action.action_trigger = spec;
        ref.list[ref.idx] = action;
        _markIrGraphDirty();
        _updateIrGraphNodeSummary(node2);
        renderIrGraphProps();
        return;
      }
    });
  });
}

// ---- internal helpers / 内部工具 ----

function _getSelectedIrRuleRef() {
  const doc = rulesDoc();
  const idx = a(doc.rules).findIndex((r) => r?.id === S.innateRulesSelectedId);
  if (idx < 0) return null;
  return { doc, idx, rule: doc.rules[idx] };
}

function _setIrGraphHint(text) {
  if (E.irGraphHint) E.irGraphHint.textContent = String(text || "");
}

function _markIrGraphDirty() {
  S.irGraph.dirty = true;
}

function _applyIrGraphLayoutVisibility() {
  const layout = E.irGraphLayout || document.getElementById("irGraphLayout");
  if (!layout) return;
  const showPalette = S.irGraph.view?.showPalette !== false;
  const showProps = S.irGraph.view?.showProps !== false;

  layout.classList.toggle("hide-palette", !showPalette);
  layout.classList.toggle("hide-props", !showProps);

  if (E.irGraphTogglePaletteBtn) E.irGraphTogglePaletteBtn.textContent = showPalette ? "隐藏节点库" : "显示节点库";
  if (E.irGraphTogglePropsBtn) E.irGraphTogglePropsBtn.textContent = showProps ? "隐藏属性面板" : "显示属性面板";

  // Layout change affects SVG edge alignment because DOMRects changed.
  // 布局变化会影响端口 DOMRect，因此需要重绘连线。
  setTimeout(() => {
    if (S.irGraph.open) renderIrGraphEdges();
  }, 0);
}

function irGraphToggleSidePanel(which) {
  if (!S.irGraph.open) return;
  const w = String(which || "");
  if (w === "palette") S.irGraph.view.showPalette = !(S.irGraph.view?.showPalette !== false);
  if (w === "props") S.irGraph.view.showProps = !(S.irGraph.view?.showProps !== false);
  _applyIrGraphLayoutVisibility();
}

function _applyIrGraphFullscreen() {
  // Toggle modal fullscreen class / 切换弹窗全屏 CSS 类
  if (!E.irGraphModal) return;
  const on = Boolean(S.irGraph.view?.fullscreen);
  E.irGraphModal.classList.toggle("fullscreen", on);
  if (E.irGraphFullscreenBtn) E.irGraphFullscreenBtn.textContent = on ? "退出全屏" : "全屏";
  // Layout change affects edges because DOMRects changed.
  // 布局变化会影响端口 DOMRect，因此需要重绘连线。
  setTimeout(() => {
    if (S.irGraph.open) renderIrGraphEdges();
  }, 0);
}

function irGraphToggleFullscreen() {
  if (!S.irGraph.open) return;
  if (!S.irGraph.view || typeof S.irGraph.view !== "object") S.irGraph.view = { zoom: 1.0 };
  S.irGraph.view.fullscreen = !Boolean(S.irGraph.view.fullscreen);
  _applyIrGraphFullscreen();
  // Sync viewport vars to improve WebView stability in fullscreen.
  // 全屏切换后同步一次视口变量，增强部分 WebView 的布局稳定性。
  syncViewportVars();
  try {
    window.dispatchEvent(new Event("resize"));
  } catch {}
}

function _irGraphWrap() {
  return E.irGraphCanvas?.parentElement || null;
}

function _irGraphZoom() {
  const z = Number(S.irGraph.view?.zoom || 1.0);
  if (!Number.isFinite(z) || z <= 0) return 1.0;
  return z;
}

function _irGraphClampZoom(z) {
  const minZ = Number(S.irGraph.view?.minZoom || 0.25) || 0.25;
  const maxZ = Number(S.irGraph.view?.maxZoom || 1.75) || 1.75;
  if (!Number.isFinite(z)) return _irGraphZoom();
  return Math.max(minZ, Math.min(maxZ, z));
}

function _irGraphSyncZoomUi() {
  const z = _irGraphZoom();
  if (E.irGraphZoomRange) {
    E.irGraphZoomRange.min = String(Number(S.irGraph.view?.minZoom || 0.25) || 0.25);
    E.irGraphZoomRange.max = String(Number(S.irGraph.view?.maxZoom || 1.75) || 1.75);
    E.irGraphZoomRange.value = String(z);
  }
  if (E.irGraphZoomLabel) {
    E.irGraphZoomLabel.textContent = `${Math.round(z * 100)}%`;
  }
}

function _irGraphMousePosToWorld(event) {
  if (!E.irGraphWorld) return null;
  const r = E.irGraphWorld.getBoundingClientRect();
  const z = _irGraphZoom();
  return { x: (event.clientX - r.left) / z, y: (event.clientY - r.top) / z };
}

function _irGraphNodeBounds(g) {
  const nodes = a(g?.nodes);
  const nodeW = 220;
  const nodeH = 140;
  if (!nodes.length) return { minX: 0, minY: 0, maxX: 720 + nodeW, maxY: 200 + nodeH, nodeW, nodeH };
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const node of nodes) {
    if (!node || typeof node !== "object") continue;
    const x = Number(node.x || 0);
    const y = Number(node.y || 0);
    if (Number.isFinite(x)) {
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x + nodeW);
    }
    if (Number.isFinite(y)) {
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y + nodeH);
    }
  }
  if (!Number.isFinite(minX)) minX = 0;
  if (!Number.isFinite(minY)) minY = 0;
  if (!Number.isFinite(maxX)) maxX = 720 + nodeW;
  if (!Number.isFinite(maxY)) maxY = 200 + nodeH;
  return { minX, minY, maxX, maxY, nodeW, nodeH };
}

function _irGraphSyncWorldLayout(g) {
  if (!E.irGraphCanvas || !E.irGraphWorld) return;
  const zoom = _irGraphZoom();
  const wrap = _irGraphWrap();
  const prevScrollLeft = wrap ? wrap.scrollLeft : 0;
  const prevScrollTop = wrap ? wrap.scrollTop : 0;

  const bounds = _irGraphNodeBounds(g);
  const pad = 260;
  const worldW = Math.max(900, Math.ceil(bounds.maxX + pad));
  const worldH = Math.max(560, Math.ceil(bounds.maxY + pad));
  S.irGraph.world = { width: worldW, height: worldH };

  E.irGraphWorld.style.width = `${worldW}px`;
  E.irGraphWorld.style.height = `${worldH}px`;
  E.irGraphWorld.style.transform = `scale(${zoom})`;

  E.irGraphCanvas.style.width = `${Math.ceil(worldW * zoom)}px`;
  E.irGraphCanvas.style.height = `${Math.ceil(worldH * zoom)}px`;

  // Restore scroll positions (clamped by the browser automatically).
  // 恢复滚动条位置（超界会被浏览器自动钳制）。
  if (wrap) {
    wrap.scrollLeft = prevScrollLeft;
    wrap.scrollTop = prevScrollTop;
  }

  _irGraphSyncZoomUi();
}

function irGraphAdjustZoom(delta) {
  irGraphSetZoom(_irGraphZoom() + Number(delta || 0), { keepCenter: true });
}

function irGraphSetZoom(z, { keepCenter } = {}) {
  if (!S.irGraph.open) return;
  const g = S.irGraph.graph;
  if (!g) return;
  const wrap = _irGraphWrap();
  const oldZoom = _irGraphZoom();
  const newZoom = _irGraphClampZoom(Number(z || 1.0));
  if (Math.abs(newZoom - oldZoom) < 1e-6) {
    _irGraphSyncZoomUi();
    return;
  }

  let centerWorldX = null;
  let centerWorldY = null;
  if (wrap && keepCenter) {
    centerWorldX = (wrap.scrollLeft + wrap.clientWidth / 2) / oldZoom;
    centerWorldY = (wrap.scrollTop + wrap.clientHeight / 2) / oldZoom;
  }

  S.irGraph.view.zoom = newZoom;
  _irGraphSyncWorldLayout(g);

  if (wrap && keepCenter && centerWorldX !== null && centerWorldY !== null) {
    wrap.scrollLeft = Math.max(0, centerWorldX * newZoom - wrap.clientWidth / 2);
    wrap.scrollTop = Math.max(0, centerWorldY * newZoom - wrap.clientHeight / 2);
  }

  renderIrGraphEdges();
  _setIrGraphHint(`缩放已调整为 ${Math.round(newZoom * 100)}%`);
}

function irGraphFitToView() {
  if (!S.irGraph.open) return;
  const g = S.irGraph.graph;
  if (!g) return;
  const wrap = _irGraphWrap();
  if (!wrap) return;
  const bounds = _irGraphNodeBounds(g);
  const margin = 80;
  const fitW = Math.max(200, (bounds.maxX - bounds.minX) + margin * 2);
  const fitH = Math.max(160, (bounds.maxY - bounds.minY) + margin * 2);
  const z = _irGraphClampZoom(Math.min((wrap.clientWidth - 20) / fitW, (wrap.clientHeight - 20) / fitH));
  S.irGraph.view.zoom = z;
  _irGraphSyncWorldLayout(g);
  wrap.scrollLeft = Math.max(0, (bounds.minX - margin) * z);
  wrap.scrollTop = Math.max(0, (bounds.minY - margin) * z);
  renderIrGraphEdges();
  _setIrGraphHint(`已适配视图（zoom=${Math.round(z * 100)}%）`);
}

function _ensureIrGraphEventBindings() {
  if (S.irGraph._bound) return;
  S.irGraph._bound = true;

  // click blank area to clear selection / 点击空白清空选择
  E.irGraphCanvas?.addEventListener("click", () => {
    if (S.irGraph._ignoreNextCanvasClick) {
      S.irGraph._ignoreNextCanvasClick = false;
      return;
    }
    S.irGraph.selectedNodeId = null;
    S.irGraph.selectedEdgeId = null;
    S.irGraph.connectingFrom = null;
    renderIrGraph();
  });

  // mouse move: update preview edge / 鼠标移动：更新连线预览
  E.irGraphCanvas?.addEventListener("mousemove", (event) => {
    if (!S.irGraph.connectingFrom) return;
    const pos = _irGraphMousePosToWorld(event);
    if (pos) renderIrGraphEdges(pos);
  });

  // Ctrl/⌘ + mouse wheel to zoom (common editor gesture)
  // Ctrl/⌘ + 滚轮缩放（常见编辑器手势）。
  // Note: keepCenter=true is a reasonable MVP; future can zoom to cursor.
  // 注：当前 MVP 以“保持视图中心”为准；后续可升级为“以鼠标位置为缩放中心”。
  E.irGraphCanvas?.addEventListener(
    "wheel",
    (event) => {
      if (!S.irGraph.open) return;
      if (!(event.ctrlKey || event.metaKey)) return;
      event.preventDefault();
      const dy = Number(event.deltaY || 0);
      const step = dy > 0 ? -0.08 : 0.08; // wheel down -> zoom out
      irGraphSetZoom(_irGraphZoom() + step, { keepCenter: true });
    },
    { passive: false },
  );

  // keyboard shortcuts / 键盘快捷键
  document.addEventListener("keydown", (event) => {
    if (!S.irGraph.open) return;
    const tag = String(event.target?.tagName || "");
    const inForm = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    if (event.key === " ") {
      if (inForm) return;
      // Space is used for panning in many editors.
      // 空格键进入“拖拽平移”模式（常见编辑器习惯）。
      S.irGraph._spaceDown = true;
      E.irGraphCanvas?.classList.add("pan-mode");
      event.preventDefault();
      return;
    }
    if (event.key === "Escape") {
      if (S.irGraph.connectingFrom) {
        S.irGraph.connectingFrom = null;
        renderIrGraph();
      } else {
        closeIrGraphModal();
      }
      return;
    }
    if (event.key === "Delete" || event.key === "Backspace") {
      if (inForm) return;
      if (S.irGraph.selectedEdgeId) deleteSelectedIrGraphEdge();
      else if (S.irGraph.selectedNodeId) deleteSelectedIrGraphNode();
    }
  });
  document.addEventListener("keyup", (event) => {
    if (!S.irGraph.open) return;
    if (event.key === " ") {
      const tag = String(event.target?.tagName || "");
      const inForm = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
      if (inForm) return;
      S.irGraph._spaceDown = false;
      E.irGraphCanvas?.classList.remove("pan-mode");
      event.preventDefault();
    }
  });

  // Pan by dragging blank canvas (Space optional) / 拖拽空白处平移视图（空格可选）
  // Why: some users may not notice scrollbars or shortcuts; direct drag-panning is more discoverable.
  // 原因：部分用户不会注意到滚动条/快捷键，因此增加“直接拖拽空白处平移”。
  E.irGraphCanvas?.addEventListener("mousedown", (event) => {
    if (!S.irGraph.open) return;
    // Left button only for MVP. (Could extend to middle mouse later.)
    // MVP 先只支持左键拖拽平移（后续可扩展中键）。
    if (event.button !== 0) return;

    // If user clicks on a node/port, don't start panning; those are handled by node drag / linking.
    // 如果点在节点/端口上，则交给节点拖拽/连线逻辑处理。
    const t = event.target;
    if (t && typeof t.closest === "function") {
      if (t.closest(".ir-node") || t.closest(".ir-port")) return;
    }

    const wrap = _irGraphWrap();
    if (!wrap) return;
    // If holding Space, we always pan and prevent default (avoid page scrolling / text selection).
    // 若按住空格，则必然进入平移模式，并阻止默认行为（避免页面滚动/选中文本）。
    const spaceMode = !!S.irGraph._spaceDown;
    if (spaceMode) event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const startLeft = wrap.scrollLeft;
    const startTop = wrap.scrollTop;
    let didPan = false;

    const onMove = (ev) => {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      // Small threshold to distinguish click vs drag.
      // 通过一个小阈值区分“点击清空选择”与“拖拽平移”。
      if (!didPan && (Math.abs(dx) > 3 || Math.abs(dy) > 3)) {
        didPan = true;
        E.irGraphCanvas?.classList.add("pan-mode");
      }
      if (!didPan && !spaceMode) return;
      wrap.scrollLeft = startLeft - (ev.clientX - startX);
      wrap.scrollTop = startTop - (ev.clientY - startY);
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      if (didPan || spaceMode) {
        // avoid click clearing selection after dragging
        // 避免拖拽结束后触发 click 把选择清空。
        S.irGraph._ignoreNextCanvasClick = true;
      }
      if (!S.irGraph._spaceDown) {
        E.irGraphCanvas?.classList.remove("pan-mode");
      }
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });

  // keep edges aligned on resize
  window.addEventListener("resize", () => {
    if (S.irGraph.open) renderIrGraphEdges();
  });
}

function _isValidIrGraphDoc(doc) {
  if (!doc || typeof doc !== "object") return false;
  if (!Array.isArray(doc.nodes) || !Array.isArray(doc.edges)) return false;
  return true;
}

function _loadIrGraphFromRule(rule) {
  const g = rule?.ui?.graph;
  if (_isValidIrGraphDoc(g)) {
    return deepClone(g);
  }
  return _buildIrGraphFromRule(rule);
}

function _buildIrGraphFromRule(rule) {
  const whenModel = editorWhenModel(rule.when);
  const actions = a(rule.then);

  const g = { version: 1, nodes: [], edges: [] };
  const root = { id: "root", type: "root", x: 380, y: 160, config: { mode: whenModel.mode || "any" } };
  g.nodes.push(root);

  // conditions -> root
  a(whenModel.clauses).forEach((clause, idx) => {
    const n = {
      id: `cond_${String(idx + 1).padStart(2, "0")}`,
      type: clause.type,
      x: 90,
      y: 120 + idx * 150,
      config: deepClone(clause.spec || {}),
    };
    g.nodes.push(n);
    g.edges.push({ id: `e_${String(g.edges.length + 1).padStart(3, "0")}`, from: n.id, to: root.id });
  });

  // root -> actions
  actions.forEach((act, idx) => {
    if (!act || typeof act !== "object") return;
    const key = Object.keys(act)[0];
    if (!key) return;
    const n = {
      id: `act_${String(idx + 1).padStart(2, "0")}`,
      type: key,
      x: 720,
      y: 120 + idx * 160,
      config: key === "log" ? { text: String(act.log || "") } : deepClone(act[key] || {}),
    };
    g.nodes.push(n);
    g.edges.push({ id: `e_${String(g.edges.length + 1).padStart(3, "0")}`, from: root.id, to: n.id });
  });

  return g;
}

function _ensureIrGraphRoot(g) {
  const existing = a(g.nodes).find((n) => n?.type === "root") || null;
  if (existing) return existing;
  const root = { id: "root", type: "root", x: 380, y: 160, config: { mode: "any" } };
  g.nodes.unshift(root);
  return root;
}

function _newIrGraphNode(g, type) {
  const prefix = _isIrGraphActionType(type) ? "act" : "cond";
  const id = _nextIrGraphId(a(g.nodes).map((n) => n?.id), `${prefix}_${type}`);
  return { id, type, x: 100, y: 100, config: _defaultIrGraphConfig(type) };
}

function _defaultIrGraphConfig(type) {
  if (type === "root") return { mode: "any" };
  if (type === "cfs") return { kinds: ["dissonance"], min_strength: 0.3, max_strength: "" };
  if (type === "state_window") return { stage: "any", fast_cp_rise_min: 1, fast_cp_drop_min: "", min_candidate_count: "", candidate_hint_any: [] };
  if (type === "timer") return { every_n_ticks: 1, at_tick: "" };
  if (type === "metric") return { preset: "got_er", metric: "", channel: "", mode: "delta", op: ">=", value: 0, min: "", max: "", window_ticks: 4, match_policy: "any", capture_as: "", epsilon: "", prev_gate: {}, note: "", selector: { mode: "all" } };
  if (type === "cfs_emit") return { kind: "dissonance", scope: "object", from: "metric_matches", max_signals: 1, min_strength: 0.0, capture_as: "", strength: { from: "match_value", policy: "linear_clamp", min: 0.0, max: 1.0, out_min: 0.0, out_max: 1.0 }, bind_attribute: {} };
  if (type === "focus") return { from: "cfs_matches", match_policy: "all", ttl_ticks: 2, focus_boost: 0.9, deduplicate_by: "target_ref_object_id", max_directives: "" };
  if (type === "emit_script") return { script_id: "custom_script", script_kind: "custom", priority: 50, trigger: "" };
  if (type === "log") return { text: "" };
  if (type === "emotion_update") return { DA: 0.0 };
  if (type === "action_trigger") return { action_id: "custom_action", action_kind: "custom", gain: 0.3, threshold: 1.0, cooldown_ticks: 0, params: {} };
  if (type === "pool_energy") return { selector: { mode: "all" }, delta_er: 0.0, delta_ev: 0.0, create_if_missing: false, create_ref_object_type: "sa", create_display: "", reason: "" };
  if (type === "pool_bind_attribute") return { selector: { mode: "all" }, attribute: { attribute_name: "", attribute_value: "", raw: "", display: "", value_type: "discrete", modality: "internal", er: 0.0, ev: 0.0 }, reason: "" };
  if (type === "delay") return { ticks: 2, then: [{ log: "延时触发（示例）" }] };
  if (type === "branch") return { when: { metric: { preset: "reward_state", mode: "state", op: ">", value: 0 } }, then: [{ log: "满足条件（then）" }], else: [{ log: "不满足（else）" }], on_error: [{ log: "条件报错（on_error）" }] };
  return {};
}

function _countIrGraphNodesByKind(g, kind) {
  const nodes = a(g.nodes);
  if (kind === "action") return nodes.filter((n) => _isIrGraphActionNode(n)).length;
  if (kind === "condition") return nodes.filter((n) => _isIrGraphConditionNode(n)).length;
  return nodes.length;
}

function _nextIrGraphId(existingIds, prefix) {
  const ids = new Set(a(existingIds).filter(Boolean).map((x) => String(x)));
  let n = 1;
  while (ids.has(`${prefix}_${String(n).padStart(2, "0")}`)) n += 1;
  return `${prefix}_${String(n).padStart(2, "0")}`;
}

function _nextIrGraphEdgeId(g) {
  const ids = new Set(a(g.edges).map((e) => String(e?.id || "")).filter(Boolean));
  let n = 1;
  while (ids.has(`e_${String(n).padStart(3, "0")}`)) n += 1;
  return `e_${String(n).padStart(3, "0")}`;
}

function _upsertIrGraphEdge(g, { from, to, replaceTo }) {
  from = String(from || "");
  to = String(to || "");
  if (!from || !to) return;
  // replaceTo: if true, ensure only one incoming edge to "to" (used for actions).
  if (replaceTo) {
    g.edges = a(g.edges).filter((e) => String(e?.to || "") !== to);
  }
  const exists = a(g.edges).some((e) => String(e?.from || "") === from && String(e?.to || "") === to);
  if (exists) return;
  g.edges.push({ id: _nextIrGraphEdgeId(g), from, to });
}

function _findIrGraphNode(g, id) {
  return a(g.nodes).find((n) => String(n?.id || "") === String(id || "")) || null;
}

function _isIrGraphActionType(type) {
  // Treat anything that is not a condition/root as an "action" node.
  // 这样即使未来新增动作类型（emotion_update/action_trigger/...），也不会在图形编译时丢失。
  const t = String(type || "");
  if (!t || t === "root") return false;
  return !_isIrGraphConditionType(t);
}

function _isIrGraphConditionType(type) {
  return ["cfs", "state_window", "timer", "metric"].includes(String(type || ""));
}

function _isIrGraphActionNode(node) {
  return node && typeof node === "object" && _isIrGraphActionType(node.type);
}

function _isIrGraphConditionNode(node) {
  return node && typeof node === "object" && _isIrGraphConditionType(node.type);
}

function _renderIrGraphNodeHtml(node) {
  const id = String(node.id || "");
  const type = String(node.type || "");
  const selected = id && id === String(S.irGraph.selectedNodeId || "");
  const title = _irGraphNodeTitle(node);
  const summary = _irGraphNodeSummary(node);
  const hasIn = type === "root" || _isIrGraphActionType(type);
  const hasOut = type === "root" || _isIrGraphConditionType(type);
  const canDelete = type !== "root";
  return `<article class="ir-node ${selected ? "selected" : ""}" data-node-id="${esc(id)}" style="left:${Number(node.x || 0)}px; top:${Number(node.y || 0)}px;">
    <div class="ir-node-head">
      <div class="ir-node-head-left">
        <div class="ir-node-title">${esc(title)}</div>
        <div class="ir-node-type">${esc(type)}</div>
      </div>
      <div class="ir-node-head-right">
        <span class="chip ${type === "root" ? "accent" : ""}">${type === "root" ? "条件汇总" : (_isIrGraphConditionType(type) ? "条件" : "动作")}</span>
        ${canDelete ? `<button class="ir-node-del" type="button" title="删除节点（Delete）">删除</button>` : ""}
      </div>
    </div>
    <div class="ir-node-body">
      <div class="ir-node-summary">${esc(summary)}</div>
      <div class="ir-ports">
        <div class="ir-port in ${hasIn ? "" : "disabled"}" data-port="in" title="输入 / In"></div>
        <div class="ir-port out ${hasOut ? "" : "disabled"}" data-port="out" title="输出 / Out"></div>
      </div>
    </div>
  </article>`;
}

function _irGraphNodeTitle(node) {
  const type = String(node?.type || "");
  if (type === "root") return "条件汇总";
  if (type === "cfs") return "认知感受信号";
  if (type === "state_window") return "状态窗口";
  if (type === "timer") return "定时器";
  if (type === "metric") return "指标条件";
  if (type === "cfs_emit") return "认知感受生成";
  if (type === "focus") return "聚焦指令";
  if (type === "emit_script") return "触发记录";
  if (type === "log") return "日志";
  if (type === "emotion_update") return "情绪更新";
  if (type === "action_trigger") return "行动触发";
  if (type === "pool_energy") return "对对象赋能量（ER/EV）";
  if (type === "pool_bind_attribute") return "绑定属性";
  if (type === "delay") return "延时";
  if (type === "branch") return "分支";
  return type || "节点";
}

function _irGraphNodeSummary(node) {
  const type = String(node?.type || "");
  const cfg = node?.config || {};
  const presetLabel = (preset) => {
    const name = String(preset || "");
    if (!name) return "-";
    const list = a(S.innateRulesBundle?.metric_presets);
    const found = list.find((p) => String(p?.preset || "") === name);
    return found ? String(found.label_zh || name) : name;
  };
  if (type === "root") return `触发模式: ${String(cfg.mode || "any") === "all" ? "同时（all）" : "任一（any）"}`;
  if (type === "cfs") return `信号种类: ${a(cfg.kinds).join("，") || "全部"} | 最小强度 >= ${cfg.min_strength ?? "-"}`;
  if (type === "state_window") return `窗口: ${cfg.stage ?? "any"} | CP快速上升 >= ${cfg.fast_cp_rise_min ?? "-"} | CP快速下降 >= ${cfg.fast_cp_drop_min ?? "-"}`;
  if (type === "timer") return `定时: 每 ${cfg.every_n_ticks ?? "-"} tick | 指定 tick=${cfg.at_tick ?? "-"}`;
  if (type === "metric") {
    const ch = cfg.channel ? `, channel=${cfg.channel}` : "";
    const name = cfg.preset ? presetLabel(cfg.preset) : (cfg.metric || "-");
    const op = cfg.op || ">=";
    const value = cfg.value ?? "-";
    return `指标: ${name}${ch} | 条件: ${op} ${value} | 模式: ${cfg.mode || "state"}`;
  }
  if (type === "cfs_emit") return `生成感受: ${cfg.kind || "-"} | 作用域: ${cfg.scope || "object"} | 来源: ${cfg.from || "metric_matches"}`;
  if (type === "focus") return `聚焦来源: ${cfg.from ?? "cfs_matches"} | TTL=${cfg.ttl_ticks ?? "-"} | 加成=${cfg.focus_boost ?? "-"}`;
  if (type === "emit_script") return `记录脚本: ${cfg.script_id ?? "-"} | trigger=${cfg.trigger ?? "-"}`;
  if (type === "log") return String(cfg.text || "").slice(0, 48) || "(empty)";
  if (type === "emotion_update") return `递质通道数: ${Object.keys(cfg || {}).length}`;
  if (type === "action_trigger") return `触发行动: ${cfg.action_kind || "-"} | id=${cfg.action_id || "-"} | gain=${cfg.gain ?? "-"}`;
  if (type === "pool_energy") return `对对象赋能: ΔER=${cfg.delta_er ?? cfg.er ?? 0} | ΔEV=${cfg.delta_ev ?? cfg.ev ?? 0}`;
  if (type === "pool_bind_attribute") return `绑定属性: ${cfg.attribute?.attribute_name || cfg.attribute_name || "-"}`;
  if (type === "delay") return `延时: ${cfg.ticks ?? 1} tick | 子动作=${a(cfg.then).length}`;
  if (type === "branch") return `分支: then=${a(cfg.then).length} | else=${a(cfg.else).length} | on_error=${a(cfg.on_error).length}`;
  return "-";
}

function _updateIrGraphNodeSummary(node) {
  if (!E.irGraphNodes) return;
  const el = E.irGraphNodes.querySelector(`.ir-node[data-node-id=\"${CSS.escape(String(node.id || ""))}\"] .ir-node-summary`);
  if (el) el.textContent = _irGraphNodeSummary(node);
}

function _selectIrGraphNode(nodeId) {
  S.irGraph.selectedNodeId = String(nodeId || "");
  S.irGraph.selectedEdgeId = null;
  renderIrGraph();
}

function _selectIrGraphEdge(edgeId) {
  S.irGraph.selectedEdgeId = String(edgeId || "");
  S.irGraph.selectedNodeId = null;
  S.irGraph.connectingFrom = null;
  renderIrGraph();
}

function _handleIrGraphPortClick(nodeId, port) {
  if (!S.irGraph.graph) return;
  const g = S.irGraph.graph;
  const node = _findIrGraphNode(g, nodeId);
  if (!node) return;
  const type = String(node.type || "");

  if (port === "out") {
    // only condition/root has out
    if (!(_isIrGraphConditionType(type) || type === "root")) return;
    S.irGraph.connectingFrom = nodeId;
    S.irGraph.selectedEdgeId = null;
    _setIrGraphHint(`请选择一个输入端口完成连线（from: ${nodeId}）。`);
    return;
  }

  if (port === "in") {
    if (!S.irGraph.connectingFrom) return;
    const fromId = String(S.irGraph.connectingFrom || "");
    const fromNode = _findIrGraphNode(g, fromId);
    if (!fromNode) return;

    const fromType = String(fromNode.type || "");
    const toType = String(type || "");

    // enforce simple pattern: cond -> root, root -> action
    if (_isIrGraphConditionType(fromType) && toType !== "root") {
      irGraphFb("连线不允许：条件节点只能连接到「条件汇总」节点。", "err");
      return;
    }
    if (fromType === "root" && !_isIrGraphActionType(toType)) {
      irGraphFb("连线不允许：「条件汇总」节点只能连接到动作节点。", "err");
      return;
    }
    if (fromType === "root" && _isIrGraphActionType(toType)) {
      _upsertIrGraphEdge(g, { from: fromId, to: nodeId, replaceTo: true });
    } else if (_isIrGraphConditionType(fromType) && toType === "root") {
      _upsertIrGraphEdge(g, { from: fromId, to: nodeId, replaceTo: false });
    }

    S.irGraph.connectingFrom = null;
    _markIrGraphDirty();
    renderIrGraph();
  }
}

function _startIrGraphDrag(event, nodeId) {
  if (!S.irGraph.open || !S.irGraph.graph) return;
  if (event.button !== 0) return;
  const g = S.irGraph.graph;
  const node = _findIrGraphNode(g, nodeId);
  if (!node) return;

  _selectIrGraphNode(nodeId);

  const startX = event.clientX;
  const startY = event.clientY;
  const originX = Number(node.x || 0);
  const originY = Number(node.y || 0);
  const zoom = _irGraphZoom();

  const onMove = (ev) => {
    const dx = ev.clientX - startX;
    const dy = ev.clientY - startY;
    // dx/dy is in screen pixels; node.x/y is in world units.
    // 鼠标移动是屏幕像素，节点坐标是“世界坐标”，需要除以 zoom。
    node.x = Math.max(0, originX + dx / zoom);
    node.y = Math.max(0, originY + dy / zoom);
    const el = E.irGraphNodes?.querySelector(`.ir-node[data-node-id=\"${CSS.escape(String(nodeId))}\"]`);
    if (el) {
      el.style.left = `${Number(node.x || 0)}px`;
      el.style.top = `${Number(node.y || 0)}px`;
    }
    renderIrGraphEdges();
  };
  const onUp = () => {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    _markIrGraphDirty();
    _irGraphSyncWorldLayout(g);
    renderIrGraphEdges();
  };

  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

function _irGraphPortPos(nodeId, portKind) {
  if (!E.irGraphWorld || !E.irGraphNodes) return null;
  const nodeEl = E.irGraphNodes.querySelector(`.ir-node[data-node-id=\"${CSS.escape(String(nodeId || ""))}\"]`);
  if (!nodeEl) return null;
  const portEl = nodeEl.querySelector(`.ir-port.${portKind}`);
  if (!portEl) return null;
  const r = portEl.getBoundingClientRect();
  const wr = E.irGraphWorld.getBoundingClientRect();
  const zoom = _irGraphZoom();
  // Convert from screen pixels to world coords (unscaled).
  // 将屏幕像素坐标反算回“世界坐标”（未缩放坐标）。
  return {
    x: (r.left - wr.left + r.width / 2) / zoom,
    y: (r.top - wr.top + r.height / 2) / zoom,
  };
}

function _irGraphCurve(p1, p2) {
  const dx = Math.max(80, Math.min(220, Math.abs(p2.x - p1.x) * 0.55));
  const c1x = p1.x + dx;
  const c1y = p1.y;
  const c2x = p2.x - dx;
  const c2y = p2.y;
  return `M ${p1.x.toFixed(1)} ${p1.y.toFixed(1)} C ${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
}

function _compileIrGraphToRule(g) {
  const root = a(g.nodes).find((n) => n?.type === "root") || null;
  if (!root) return { ok: false, message: "缺少条件汇总节点（root）。" };

  const mode = String(root.config?.mode || "any");
  const condNodes = a(g.edges)
    .filter((e) => String(e?.to || "") === String(root.id || ""))
    .map((e) => _findIrGraphNode(g, String(e?.from || "")))
    .filter((n) => n && _isIrGraphConditionNode(n))
    .sort((a1, a2) => Number(a1.y || 0) - Number(a2.y || 0));

  if (!condNodes.length) return { ok: false, message: "没有条件节点连接到条件汇总。" };

  const clauses = condNodes.map((n) => ({ type: n.type, spec: n.config || {} }));
  const whens = clauses.map((c) => clauseToWhen(c)).filter(Boolean);
  const when = whens.length === 1 ? whens[0] : { [mode || "any"]: whens };

  const actionNodes = a(g.edges)
    .filter((e) => String(e?.from || "") === String(root.id || ""))
    .map((e) => _findIrGraphNode(g, String(e?.to || "")))
    .filter((n) => n && _isIrGraphActionNode(n))
    .sort((a1, a2) => Number(a1.y || 0) - Number(a2.y || 0));

  if (!actionNodes.length) return { ok: false, message: "没有动作节点连接到条件汇总输出。" };

  const then = actionNodes
    .map((n) => {
      const t = String(n.type || "");
      if (t === "log") return { log: String((n.config || {}).text || "") };
      if (!t) return null;
      return { [t]: deepClone(n.config || {}) };
    })
    .filter(Boolean);

  return { ok: true, when, then };
}

function addInnateRuleTemplate(kind) {
  const doc = rulesDoc();
  const nextId = (prefix) => {
    const ids = new Set(a(doc.rules).map((r) => r?.id).filter(Boolean));
    let n = 1;
    while (ids.has(`${prefix}_${String(n).padStart(2, "0")}`)) n += 1;
    return `${prefix}_${String(n).padStart(2, "0")}`;
  };
  const rule =
    kind === "window"
      ? {
          id: nextId("window_rule"),
          title: "状态窗口 -> 触发记录",
          enabled: true,
          priority: 50,
          cooldown_ticks: 0,
          when: { state_window: { stage: "any", fast_cp_rise_min: 1 } },
          then: [{ emit_script: { script_id: "innate_state_window_cp_rise", script_kind: "window_trigger", priority: 50, trigger: "fast_cp_rise" } }],
          note: "模板：状态窗口触发 -> 生成触发记录（用于观测/联调）",
        }
      : kind === "timer"
        ? {
            id: nextId("timer_rule"),
            title: "定时器 -> 日志",
            enabled: true,
            priority: 10,
            cooldown_ticks: 0,
            when: { timer: { every_n_ticks: 1 } },
            then: [{ log: "定时触发" }],
            note: "模板：定时触发 -> 写入审计日志（用于测试；建议调整 every_n_ticks/cooldown_ticks）。",
          }
      : {
          id: nextId("focus_rule"),
          title: "认知感受（CFS）-> 聚焦指令",
          enabled: true,
          priority: 60,
          cooldown_ticks: 0,
          when: { cfs: { kinds: ["dissonance", "surprise", "pressure", "expectation"], min_strength: 0.3 } },
          then: [{ focus: { from: "cfs_matches", match_policy: "all", ttl_ticks: 2, focus_boost: 0.9, deduplicate_by: "target_ref_object_id" } }],
          note: "模板：核心认知感受（CFS）-> 注意力聚焦（下一 tick 生效）",
        };
  doc.rules.push(rule);
  S.innateRulesSelectedId = rule.id;
  S.innateRulesDirty = true;
  irFb(`已添加模板规则：${rule.title || rule.id}（草稿未保存）。`, "ok");
  draw();
}

async function validateInnateRules() {
  try {
    setIrBusy(true, "innateRulesValidateBtn", "校验中…");
    irFb("正在校验：检查规则格式并生成规范化 YAML 预览…", "busy");
    irSetResultBoxKind("busy");
    irFlashFeedback();
    const response = await P("/api/innate_rules/validate", { doc: rulesDoc() });
    const data = response.data;
    if (E.innateRulesYaml) E.innateRulesYaml.value = data.yaml_preview || "";
    if (E.innateRulesResult) E.innateRulesResult.textContent = irResultText("validate", data);
    irFlashResultBox();
    setTimeout(() => E.innateRulesResult?.scrollIntoView?.({ behavior: "smooth", block: "start" }), 0);
    if (data.valid) {
      irFb(`规则校验通过。错误 0，警告 ${a(data.warnings).length}。`, "ok");
      irSetResultBoxKind("ok");
      irFlashFeedback();
      fb("规则校验通过。");
    } else {
      const first = a(data.errors)[0] || null;
      const hint = first ? `例如：${first.path || "-"}：${first.message_zh || first.zh || first.message_en || first.en || "-"}` : "";
      irFb(`规则校验失败：${a(data.errors).length} 个错误，${a(data.warnings).length} 个警告。${hint ? "\n" + hint : ""}`, "err");
      irSetResultBoxKind("err");
      irFlashFeedback();
      // 尝试把选择定位到出错的规则（若 path 形如 rules[3].xxx）。
      const m = String(first?.path || "").match(/^rules\\[(\\d+)\\]/);
      if (m) {
        const idx = Number(m[1]);
        const targetRule = a(rulesDoc().rules)[idx] || null;
        if (targetRule?.id) {
          S.innateRulesSelectedId = targetRule.id;
          draw();
          setTimeout(() => E.innateRulesEditor?.scrollIntoView?.({ behavior: "smooth", block: "start" }), 0);
        }
      }
      fb(`规则校验失败：${a(data.errors).length} 个错误。`, true);
    }
  } catch (error) {
    irFb(`校验失败：${error.message}`, "err");
    irSetResultBoxKind("err");
    irFlashFeedback();
    fb(`校验失败: ${error.message}`, true);
  } finally {
    setIrBusy(false);
  }
}

async function exportInnateRulesYaml() {
  await validateInnateRules();
}

async function importInnateRulesYaml() {
  const yamlText = E.innateRulesYaml?.value ?? "";
  try {
    setIrBusy(true, "innateRulesImportYamlBtn", "导入中…");
    irFb("正在导入：先校验 YAML，再写入表单模型…", "busy");
    irSetResultBoxKind("busy");
    irFlashFeedback();
    const response = await P("/api/innate_rules/validate", { yaml: yamlText });
    const data = response.data;
    if (!data.valid) {
      if (E.innateRulesResult) E.innateRulesResult.textContent = irResultText("import_yaml", data);
      irFlashResultBox();
      const first = a(data.errors)[0] || null;
      const hint = first ? `例如：${first.path || "-"}：${first.message_zh || first.zh || first.message_en || first.en || "-"}` : "";
      irFb(`YAML 导入失败：${a(data.errors).length} 个错误。${hint ? "\n" + hint : ""}`, "err");
      irSetResultBoxKind("err");
      irFlashFeedback();
      fb(`YAML 导入失败：${a(data.errors).length} 个错误。`, true);
      return;
    }
    S.innateRulesDoc = deepClone(data.normalized_doc || {});
    S.innateRulesDirty = true;
    if (E.innateRulesYaml) E.innateRulesYaml.value = data.yaml_preview || "";
    if (E.innateRulesResult) E.innateRulesResult.textContent = irResultText("import_yaml", data);
    irFlashResultBox();
    irFb("已从 YAML 导入到表单（草稿已标记为未保存）。", "ok");
    irSetResultBoxKind("ok");
    irFlashFeedback();
    fb("已从 YAML 导入到表单。");
    draw();
  } catch (error) {
    irFb(`YAML 导入失败：${error.message}`, "err");
    irSetResultBoxKind("err");
    irFlashFeedback();
    fb(`YAML 导入失败: ${error.message}`, true);
  } finally {
    setIrBusy(false);
  }
}

async function saveInnateRules() {
  try {
    setIrBusy(true, "innateRulesSaveBtn", "保存中…");
    irFb("正在保存：写入规则文件并触发热加载…", "busy");
    irSetResultBoxKind("busy");
    irFlashFeedback();
    const response = await P("/api/innate_rules/save", { doc: rulesDoc() });
    const data = response.data;
    if (E.innateRulesResult) E.innateRulesResult.textContent = irResultText("save", data);
    if (!data.saved) {
      irFlashResultBox();
      irFb(`保存失败：${data.message || "unknown"}`, "err");
      irSetResultBoxKind("err");
      irFlashFeedback();
      fb(`保存失败: ${data.message || "unknown"}`, true);
      return;
    }
    irFlashResultBox();
    irFb("已保存并热加载先天规则。", "ok");
    irSetResultBoxKind("ok");
    irFlashFeedback();
    fb("已保存并热加载先天规则。");
    await refreshInnateRules(true);
    draw();
  } catch (error) {
    irFb(`保存失败：${error.message}`, "err");
    irSetResultBoxKind("err");
    irFlashFeedback();
    fb(`保存失败: ${error.message}`, true);
  } finally {
    setIrBusy(false);
  }
}

async function simulateInnateRules() {
  try {
    setIrBusy(true, "innateRulesSimulateBtn", "模拟中…");
    irFb("正在模拟：使用最近一轮 cycle 的上下文进行 dry-run（不改变系统状态）…", "busy");
    irSetResultBoxKind("busy");
    irFlashFeedback();
    const response = await P("/api/innate_rules/simulate", {});
    const data = response.data;
    if (E.innateRulesResult) E.innateRulesResult.textContent = irResultText("simulate", data);
    irFlashResultBox();
    if (data.ok) {
      irFb("模拟完成（dry-run）。", "ok");
      irSetResultBoxKind("ok");
      irFlashFeedback();
      fb("模拟完成。");
    } else {
      irFb(`模拟失败：${data.message || "-"}`, "err");
      irSetResultBoxKind("err");
      irFlashFeedback();
      fb(`模拟失败: ${data.message || "-"}`, true);
    }
  } catch (error) {
    irFb(`模拟失败：${error.message}`, "err");
    irSetResultBoxKind("err");
    irFlashFeedback();
    fb(`模拟失败: ${error.message}`, true);
  } finally {
    setIrBusy(false);
  }
}





