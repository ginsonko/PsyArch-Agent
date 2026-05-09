(function () {
  if (typeof STATE === "undefined" || typeof apiGet !== "function" || typeof apiPost !== "function") {
    return;
  }

  const AT = {
    dom: {},
    ruleDisabled: new Set(),
    ruleProtected: new Set(),
    llmPollTimer: null,
  };

  STATE.autoTunerConfig = null;
  STATE.autoTunerCatalog = null;
  STATE.autoTunerState = null;
  STATE.autoTunerRules = null;
  STATE.autoTunerAudit = null;
  STATE.autoTunerRollbackPoints = null;
  STATE.autoTunerLlmConfig = null;
  STATE.autoTunerLlmJobs = null;

  function q(id) {
    return document.getElementById(id);
  }

  function feedback(id, message, kind = "ok") {
    setFeedback(AT.dom[id], message, kind);
  }

  function boolLabel(value) {
    return value ? "已开启" : "已关闭";
  }

  function formatMaybe(value, digits = 4) {
    return value === null || value === undefined || value === "" ? "-" : formatNumber(value, digits);
  }

  function ruleChip(label, cls = "") {
    return `<span class="chip ${cls}">${esc(label)}</span>`;
  }

  const PARAM_LABELS = {
    "cognitive_stitching.min_candidate_score": "认知拼接最低候选分",
    "cognitive_stitching.min_seed_total_energy": "认知拼接种子最低总能量",
    "cognitive_stitching.min_event_total_energy": "认知拼接事件最低总能量",
    "cognitive_stitching.event_grasp_min_total_energy": "认知拼接叙事把握最低总能量",
    "cognitive_stitching.max_event_component_count": "认知拼接最大组分数",
    "cognitive_stitching.match_strength_weight": "认知拼接匹配强度权重",
    "cognitive_stitching.anchor_distance_penalty": "认知拼接上下文距离惩罚",
    "cognitive_stitching.context_support_weight": "认知拼接上下文支持权重",

    "state_pool.default_er_decay_ratio": "状态池实能量保活比例",
    "state_pool.default_ev_decay_ratio": "状态池虚能量保活比例",
    "state_pool.soft_capacity_start_items": "状态池软容量起压阈值",
    "state_pool.soft_capacity_full_items": "状态池软容量满压阈值",
    "state_pool.pool_max_items": "状态池容量上限",
    "state_pool.priority_neutralization_min_effect_threshold": "状态池优先中和最小效果阈值",
    "state_pool.neutralization_min_effect_threshold": "状态池普通中和最小效果阈值",

    "attention.max_cam_items": "注意力工作集上限",
    "attention.min_total_energy": "注意力最低总能量门槛",

    "hdb.internal_resolution_max_structures_per_tick": "单 Tick 内源结构上限",
    "hdb.internal_resolution_detail_budget_base": "内源基础细节预算",
    "hdb.internal_resolution_detail_budget_adr_gain": "内源肾上腺素细节增益",
    "hdb.stimulus_early_stop_patience_rounds": "刺激级提前停止耐心轮数",
    "hdb.stimulus_early_stop_high_energy_unit_threshold": "刺激级高能单元提前停止阈值",
    "hdb.structure_level_max_rounds": "结构级最大轮次",
    "hdb.stimulus_level_max_rounds": "刺激级最大轮次",
    "hdb.internal_resolution_flat_unit_cap_per_structure": "每结构细节单元上限",

    "time_sensor.max_total_bindings": "时间感受器总绑定数上限",
    "time_sensor.delayed_task_capacity": "时间感受器延迟任务容量",

    "text_sensor.echo_pool_max_frames": "文本感受器回声池帧上限",
    "text_sensor.echo_min_energy_threshold": "文本感受器回声最小能量门槛",

    "cognitive_feeling.expectation_ev_threshold": "期待感虚能门槛",
    "cognitive_feeling.dissonance_cp_abs_threshold": "违和感认知压阈值",
    "cognitive_feeling.dissonance_cp_abs_max": "违和感认知压上限",
    "cognitive_feeling.pressure_ev_threshold": "压力感虚能门槛",
    "cognitive_feeling.correct_event_cp_drop_threshold": "正确事件认知压下降阈值",
  };

  function renamePageChrome() {
    document.title = "长期运行数据观测台";
    const brand = document.querySelector(".sidebar .brand h1");
    if (brand) brand.textContent = "长期运行数据观测台";
    const brandText = document.querySelector(".sidebar .brand p");
    if (brandText) {
      brandText.textContent = "用于观察长期运行指标、管理自适应调参、审计调参历史，并与“单次 tick 数据观测台”区分开。";
    }
    const heroEyebrow = document.querySelector(".hero .eyebrow");
    if (heroEyebrow) heroEyebrow.textContent = "AP Prototype Long-Run Observatory";
    const heroTitle = document.querySelector(".hero h2");
    if (heroTitle) heroTitle.textContent = "长期运行数据观测台";
    const heroDesc = document.querySelector(".hero p");
    if (heroDesc) {
      heroDesc.textContent =
        "这里面向长跑、长期指标、调参闭环与复盘证据。它和主页面的“单次 tick 数据观测台”不同，重点不是看某一轮细节，而是看系统在较长时间内是否稳定、是否贴近理论预期、以及为什么会偏离。";
    }
    const nav = document.querySelector(".sidebar-nav");
    if (nav && !nav.querySelector('a[href="#exp_auto_tuner"]')) {
      const anchor = document.createElement("a");
      anchor.href = "#exp_auto_tuner";
      anchor.textContent = "自适应调参器";
      const ref = nav.querySelector('a[href="#exp_llm_review"]');
      if (ref) {
        nav.insertBefore(anchor, ref);
      } else {
        nav.appendChild(anchor);
      }
    }
  }

  function collectMetricTargets() {
    return Array.from(document.querySelectorAll('[data-at-metric-row]:not([data-diagnostic="true"])')).map((row) => {
      const key = String(row.getAttribute("data-key") || "");
      return {
        key,
        expected_min: asNumber(row.querySelector('[data-field="expected_min"]')?.value, 0),
        expected_max: asNumber(row.querySelector('[data-field="expected_max"]')?.value, 0),
        ideal: asNumber(row.querySelector('[data-field="ideal"]')?.value, 0),
        min_std: asNumber(row.querySelector('[data-field="min_std"]')?.value, 0),
        weight: asNumber(row.querySelector('[data-field="weight"]')?.value, 1),
      };
    });
  }

  function renderOverview() {
    const cfg = STATE.autoTunerConfig?.config || {};
    const state = STATE.autoTunerState?.summary || {};
    const rulesSummary = STATE.autoTunerRules?.catalog?.summary || {};
    const llmCfg = STATE.autoTunerLlmConfig?.config || {};
    if (!AT.dom.expAutoTunerOverviewCards) return;
    AT.dom.expAutoTunerOverviewCards.innerHTML = [
      metricCard("调参器状态", boolLabel(Boolean(cfg.enabled)), `短期：${boolLabel(Boolean(cfg.enable_short_term))} | 长期：${boolLabel(Boolean(cfg.enable_long_term))}`),
      metricCard("持久参数数", formatCount(state.persisted_param_count), `运行时参数：${formatCount(state.runtime_param_count)}`),
      metricCard("活跃试验数", formatCount(state.active_trial_count), `已归档试验：${formatCount(state.trial_history_count)}`),
      metricCard("规则总量", formatCount((rulesSummary.builtin_count || 0) + (rulesSummary.generated_count || 0) + (rulesSummary.custom_count || 0)), `禁用：${formatCount(rulesSummary.disabled_count)} | 白名单：${formatCount(rulesSummary.protected_count)}`),
      metricCard("规则健康记录", formatCount(state.rule_health_count), "用于判断某条规则是长期有效、长期失效，还是经常触发回滚。"),
      metricCard("LLM 分析", boolLabel(Boolean(llmCfg.enabled)), `模型：${llmCfg.model || "-"} | 来源：${STATE.autoTunerLlmConfig?.source || "-"}`),
      metricCard("LLM 候选规则", formatCount(state.llm_candidate_rule_count), `已固化：${formatCount(state.llm_solidified_rule_count)} | 已拒绝：${formatCount(state.llm_rejected_rule_count)}`),
    ].join("");
  }

  function renderMetricTargets() {
    const items = STATE.autoTunerConfig?.metric_targets || [];
    if (!AT.dom.expAtMetricTargets) return;
    if (!items.length) {
      AT.dom.expAtMetricTargets.innerHTML = emptyState("当前没有可编辑的长期指标基线。");
      return;
    }
    const activeItems = items.filter((item) => !item?.diagnostic_only);
    const diagnosticItems = items.filter((item) => item?.diagnostic_only);
    const renderTarget = (item, diagnostic = false) => {
      const rowAttr = diagnostic ? 'data-at-metric-row data-diagnostic="true"' : 'data-at-metric-row';
      return `
        <details class="details-panel" ${rowAttr} data-key="${esc(item.key)}">
          <summary>
            <div class="mini-row">
              <div class="title">${esc(item.title || item.key)}</div>
              <div class="desc">${esc(item.description || "")}</div>
              <div class="chips">
                ${ruleChip(item.group || "未分组")}
                ${diagnostic ? ruleChip("诊断/旧口径，不参与自动调参", "warn") : ""}
                ${ruleChip(`正常范围 ${formatMaybe(item.expected_min)} ~ ${formatMaybe(item.expected_max)}`, "accent")}
                ${ruleChip(`理想值 ${formatMaybe(item.ideal)}`, "warn")}
              </div>
            </div>
          </summary>
          <div class="details-body">
            <div class="settings-grid">
              <article class="setting-item">
                <label>正常范围下限</label>
                <input data-field="expected_min" type="number" step="0.01" value="${esc(item.expected_min)}" ${diagnostic ? "disabled" : ""} />
              </article>
              <article class="setting-item">
                <label>正常范围上限</label>
                <input data-field="expected_max" type="number" step="0.01" value="${esc(item.expected_max)}" ${diagnostic ? "disabled" : ""} />
              </article>
              <article class="setting-item">
                <label>理想值</label>
                <input data-field="ideal" type="number" step="0.01" value="${esc(item.ideal)}" ${diagnostic ? "disabled" : ""} />
              </article>
              <article class="setting-item">
                <label>最小自然波动</label>
                <input data-field="min_std" type="number" step="0.01" value="${esc(item.min_std || 0)}" ${diagnostic ? "disabled" : ""} />
              </article>
              <article class="setting-item">
                <label>规则权重</label>
                <input data-field="weight" type="number" step="0.01" value="${esc(item.weight ?? 1)}" ${diagnostic ? "disabled" : ""} />
                <small>${diagnostic ? "诊断指标保留给审计和回滚对照，不会被保存为自动调参目标。" : "数值越高，表示调参器越重视这个长期指标的偏离。"}</small>
              </article>
            </div>
          </div>
        </details>
      `;
    };
    AT.dom.expAtMetricTargets.innerHTML = [
      activeItems.length
        ? activeItems.map((item) => renderTarget(item, false)).join("")
        : emptyState("当前没有可编辑的主链长期指标。"),
      diagnosticItems.length
        ? `<details class="details-panel"><summary><h4>诊断/旧口径指标（默认折叠）</h4></summary><div class="details-body stack">${diagnosticItems.map((item) => renderTarget(item, true)).join("")}</div></details>`
        : "",
    ].join("");
  }

  function renderParamCatalog() {
    const data = STATE.autoTunerCatalog;
    if (!AT.dom.expAtParamCatalog) return;
    const all = Array.isArray(data?.params) ? data.params : [];
    const keyword = String(AT.dom.expAtParamSearch?.value || "").trim().toLowerCase();
    const rows = all.filter((item) => {
      if (!keyword) return true;
      const hay = [item.param_id, item.module, (item.impacts || []).join(" "), (item.tags || []).join(" ")].join(" ").toLowerCase();
      return hay.includes(keyword);
    });
    if (!rows.length) {
      AT.dom.expAtParamCatalog.innerHTML = emptyState("没有匹配的参数。");
      return;
    }
    AT.dom.expAtParamCatalog.innerHTML = rows.slice(0, 220).map((item) => {
      const bound = data?.param_bounds?.[item.param_id] || null;
      return `
        <details class="details-panel">
          <summary>
            <div class="mini-row">
              <div class="title">${esc(item.param_id)}</div>
              <div class="desc">模块：${esc(item.module)} | 类型：${esc(item.value_type)} | 当前值：${esc(String(item.value))}</div>
              <div class="chips">
                ${ruleChip(item.auto_tune_allowed ? "允许自动调参" : "仅观测", item.auto_tune_allowed ? "accent" : "danger")}
                ${(item.tags || []).slice(0, 5).map((tag) => ruleChip(tag)).join("")}
              </div>
            </div>
          </summary>
          <div class="details-body">
            <div class="stack">
              <div class="mini-row">
                <div class="title">影响的长期指标</div>
                <div class="desc">${esc((item.impacts || []).join("、") || "未识别")}</div>
              </div>
              <div class="mini-row">
                <div class="title">推荐边界</div>
                <div class="desc">${
                  bound
                    ? `范围 ${formatMaybe(bound.min_value)} ~ ${formatMaybe(bound.max_value)}，单步不超过 ${formatMaybe(bound.max_step_abs)}，量化粒度 ${formatMaybe(bound.quantum)}`
                    : "当前没有额外边界说明。"
                }</div>
              </div>
              <div class="mini-row">
                <div class="title">说明</div>
                <div class="desc">${esc(item.note || "这是自动索引得到的参数，可用于建立“参数-指标-规则”的可审计对应关系。")}</div>
              </div>
            </div>
          </div>
        </details>
      `;
    }).join("");
  }

  function renderRules() {
    const rules = STATE.autoTunerRules;
    if (!AT.dom.expAtRuleCatalog) return;
    const builtin = rules?.catalog?.builtin_rules || [];
    const custom = rules?.catalog?.custom_rules || [];
    const generated = rules?.catalog?.generated_rules || [];
    const summary = rules?.catalog?.summary || {};
    if (AT.dom.expAtRuleSummary) {
      AT.dom.expAtRuleSummary.textContent =
        `${formatTime(Date.now())} | 内建规则 ${formatCount(summary.builtin_count)} 条，生成规则 ${formatCount(summary.generated_count)} 条，自定义规则 ${formatCount(summary.custom_count)} 条，禁用 ${formatCount(summary.disabled_count)} 条，白名单 ${formatCount(summary.protected_count)} 条。`;
    }
    const renderRuleBlock = (title, items, limit = items.length) => {
      if (!items.length) return "";
      return `
        <details class="details-panel">
          <summary><h4>${esc(title)}</h4></summary>
          <div class="details-body stack">
            ${items.slice(0, limit).map((rule) => {
              const ruleId = String(rule.rule_id || rule.id || "");
              const disabled = AT.ruleDisabled.has(ruleId);
              const protectedFlag = AT.ruleProtected.has(ruleId);
              return `
                <article class="mini-row rule-row">
                  <div class="title">${esc(rule.title || ruleId)}</div>
                  <div class="desc">
                    指标：${esc(rule.metric_key || "-")} | 模式：${esc(rule.issue_mode || "-")} | 参数：${esc(rule.param_id || "-")}
                  </div>
                  <div class="chips">
                    ${ruleChip(rule.source || "rule")}
                    ${ruleChip(disabled ? "已禁用" : "启用中", disabled ? "danger" : "accent")}
                    ${ruleChip(protectedFlag ? "LLM 白名单" : "允许 LLM 分析", protectedFlag ? "warn" : "")}
                    ${rule.module ? ruleChip(rule.module) : ""}
                  </div>
                  <div class="actions compact-actions exp-auto-rule-actions">
                    <button type="button" class="ghost" data-at-rule-toggle="disable" data-rule-id="${esc(ruleId)}">${disabled ? "恢复规则" : "禁用规则"}</button>
                    <button type="button" class="ghost" data-at-rule-toggle="protect" data-rule-id="${esc(ruleId)}">${protectedFlag ? "移出白名单" : "加入白名单"}</button>
                  </div>
                </article>
              `;
            }).join("")}
          </div>
        </details>
      `;
    };
    AT.dom.expAtRuleCatalog.innerHTML = [
      renderRuleBlock("内建规则", builtin),
      renderRuleBlock("自定义规则", custom),
      renderRuleBlock("生成规则（按参数-指标影响自动展开，已截断展示前 180 条）", generated, 180),
    ].join("");

    AT.dom.expAtRuleCatalog.querySelectorAll("[data-at-rule-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const ruleId = String(btn.getAttribute("data-rule-id") || "");
        const mode = String(btn.getAttribute("data-at-rule-toggle") || "");
        if (!ruleId) return;
        if (mode === "disable") {
          if (AT.ruleDisabled.has(ruleId)) {
            AT.ruleDisabled.delete(ruleId);
          } else {
            AT.ruleDisabled.add(ruleId);
          }
        } else if (mode === "protect") {
          if (AT.ruleProtected.has(ruleId)) {
            AT.ruleProtected.delete(ruleId);
          } else {
            AT.ruleProtected.add(ruleId);
          }
        }
        renderRules();
      });
    });

    if (AT.dom.expAtCustomRulesEditor) {
      AT.dom.expAtCustomRulesEditor.value = JSON.stringify(rules?.rules?.custom_rules || [], null, 2);
    }
  }

  function renderRecentLlmSuggestions() {
    const items = STATE.autoTunerState?.recent_llm_suggestions || [];
    if (!AT.dom.expAtLlmSuggestionList) return;
    if (!items.length) {
      AT.dom.expAtLlmSuggestionList.innerHTML = emptyState("当前还没有自动闭环建议。只有在规则长期失效、回滚偏多或问题持续累积时，才会触发这部分分析。");
      return;
    }
    AT.dom.expAtLlmSuggestionList.innerHTML = items.slice(0, 12).map((item) => {
      const parsed = item.parsed_json || {};
      const counts = item.counts || {};
      const apply = item.auto_apply_result || {};
      const changed = Boolean(apply.changed);
      const applyText = apply.success
        ? (changed
          ? `已自动应用 ${formatCount((apply.applied_rule_changes || []).length)} 条规则动作，加入 ${formatCount((apply.added_experiments || []).length)} 个候选试验。`
          : "已完成分析，但本轮没有满足自动应用条件的变更。")
        : "当前还没有自动应用结果。";
      return `
        <details class="details-panel">
          <summary>
            <div class="mini-row">
              <div class="title">${esc(formatTime(item.created_at_ms))} | run ${esc(item.run_id || "global")}</div>
              <div class="desc">${esc(parsed.summary || "这次建议没有填写额外摘要。")}</div>
              <div class="chips">
                ${ruleChip(`发现 ${formatCount(counts.metric_findings)} 项指标问题`, "accent")}
                ${ruleChip(`规则动作 ${formatCount(counts.rule_changes)}`)}
                ${ruleChip(`候选试验 ${formatCount(counts.experiments)}`, "warn")}
                ${ruleChip(changed ? "本轮已自动应用" : "本轮未自动落地", changed ? "accent" : "")}
              </div>
            </div>
          </summary>
          <div class="details-body stack">
            ${miniRow("自动应用结果", applyText)}
            ${miniRow("重点指标", (item.focus_metrics || []).join("、") || "这次没有显式限定重点指标。")}
            ${miniRow("主要发现", (parsed.metric_findings || []).map((row) => `${row.metric_key} | ${row.status} | ${row.reason || "未写原因"}`).join("\n") || "没有结构化 metric_findings。")}
            ${miniRow("补充说明", (parsed.notes || []).join("\n") || "没有补充说明。")}
            ${miniRow("报告摘录", item.report_excerpt || "没有可展示的报告摘录。")}
          </div>
        </details>
      `;
    }).join("");
  }

  function renderStateAndAudit() {
    const stateWrap = STATE.autoTunerState || {};
    const state = stateWrap.state || {};
    const audit = STATE.autoTunerAudit?.items || [];
    const ruleHealth = state.rule_health || {};
    const healthRows = Object.values(ruleHealth).sort((a, b) => asNumber(b.hit_count, 0) - asNumber(a.hit_count, 0)).slice(0, 16);
    if (AT.dom.expAtStateSummary) {
      AT.dom.expAtStateSummary.innerHTML = [
        miniRow("持久参数", `当前持久参数 ${formatCount(Object.keys(state.persisted_params || {}).length)} 个；活跃试验 ${formatCount((state.active_trials || []).length)} 个；试验历史 ${formatCount((state.trial_history || []).length)} 条。`),
        miniRow(
          "规则健康度 Top",
          healthRows.length
            ? healthRows.map((row) => `${row.rule_id} | 命中 ${formatCount(row.hit_count)} | 成功 ${formatCount(row.success_count)} | 失败 ${formatCount(row.failure_count)} | 回滚 ${formatCount(row.rollback_count)}`).join("\n")
            : "当前还没有规则健康记录。"
        ),
      ].join("");
    }
    if (AT.dom.expAtAuditLog) {
      if (!audit.length) {
        AT.dom.expAtAuditLog.innerHTML = emptyState("当前还没有调参审计日志。");
      } else {
        AT.dom.expAtAuditLog.innerHTML = audit.slice(0, 40).map((item) => {
          return miniRow(
            `${formatTime(item.ts_ms)} | ${item.kind || "event"}`,
            JSON.stringify(item, null, 2)
          );
        }).join("");
      }
    }
    renderRecentLlmSuggestions();
  }

  function renderRollbackPoints() {
    const points = STATE.autoTunerRollbackPoints?.points || [];
    if (!AT.dom.expAtRollbackList) return;
    if (!points.length) {
      AT.dom.expAtRollbackList.innerHTML = emptyState("当前还没有回滚点。");
      return;
    }
    AT.dom.expAtRollbackList.innerHTML = points.map((point) => {
      return `
        <article class="mini-row">
          <div class="title">${esc(point.point_id || "-")}</div>
          <div class="desc">时间：${esc(formatTime(point.created_at_ms))}\n原因：${esc(point.reason || "-")}\n参数数：${formatCount(Object.keys(point.persisted_params || {}).length)}</div>
          <div class="actions compact-actions">
            <button type="button" class="ghost danger" data-at-rollback="${esc(point.point_id)}">恢复到此回滚点</button>
          </div>
        </article>
      `;
    }).join("");
    AT.dom.expAtRollbackList.querySelectorAll("[data-at-rollback]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const pointId = String(btn.getAttribute("data-at-rollback") || "");
        if (!pointId) return;
        if (!window.confirm(`确定要回滚到 ${pointId} 吗？这会恢复当前持久参数并尝试立即热更新运行态。`)) {
          return;
        }
        feedback("expAtConfigFeedback", `正在回滚到 ${pointId}…`, "busy");
        try {
          await apiPost("/api/experiment/auto_tuner/rollback", { point_id: pointId });
          feedback("expAtConfigFeedback", `已回滚到 ${pointId}。`, "ok");
          await refreshAutoTunerAll({ silent: true });
        } catch (error) {
          feedback("expAtConfigFeedback", `回滚失败：${error.message}`, "err");
        }
      });
    });
  }

  function renderLlmConfig() {
    const cfg = STATE.autoTunerLlmConfig?.config || {};
    if (AT.dom.expAtLlmMeta) {
      AT.dom.expAtLlmMeta.textContent = `来源：${STATE.autoTunerLlmConfig?.source || "-"} | Key：${cfg.api_key_masked || "-"}`;
    }
    if (AT.dom.expAtLlmEnabledChk) AT.dom.expAtLlmEnabledChk.checked = Boolean(cfg.enabled);
    if (AT.dom.expAtLlmAutoChk) AT.dom.expAtLlmAutoChk.checked = Boolean(cfg.auto_analyze_on_completion);
    if (AT.dom.expAtLlmBaseUrl) AT.dom.expAtLlmBaseUrl.value = String(cfg.base_url || "");
    if (AT.dom.expAtLlmModel) AT.dom.expAtLlmModel.value = String(cfg.model || "");
    if (AT.dom.expAtLlmMaxPromptChars) AT.dom.expAtLlmMaxPromptChars.value = String(cfg.max_prompt_chars || 900000);
    if (AT.dom.expAtLlmApiKey) AT.dom.expAtLlmApiKey.value = "";
  }

  function renderLlmJobs() {
    const jobs = STATE.autoTunerLlmJobs?.jobs || [];
    if (!AT.dom.expAtLlmJobs) return;
    if (!jobs.length) {
      AT.dom.expAtLlmJobs.innerHTML = emptyState("当前还没有调参器 LLM 分析任务。");
      if (AT.dom.expAtLlmReport) AT.dom.expAtLlmReport.textContent = "等待分析结果…";
      return;
    }
    AT.dom.expAtLlmJobs.innerHTML = jobs.map((job) => {
      return miniRow(
        `${job.job_id} | ${job.status}`,
        `运行记录：${job.run_id || "未指定"}\n开始：${formatTime(job.started_at_ms)}\n结束：${formatTime(job.finished_at_ms)}\n错误：${job.error || "无"}`
      );
    }).join("");
    const latest = jobs[0];
    const text = latest?.result?.report_text || latest?.result?.raw || "";
    if (AT.dom.expAtLlmReport) {
      AT.dom.expAtLlmReport.textContent = text || "最近一次任务还没有返回可展示的结果。";
    }
    const hasRunning = jobs.some((job) => ["queued", "running"].includes(String(job.status || "")));
    if (hasRunning && !AT.llmPollTimer) {
      AT.llmPollTimer = setInterval(() => refreshAutoTunerLlmJobs({ silent: true }), 2500);
    }
    if (!hasRunning && AT.llmPollTimer) {
      clearInterval(AT.llmPollTimer);
      AT.llmPollTimer = null;
    }
  }

  async function refreshAutoTunerConfig({ silent = false } = {}) {
    const res = await apiGet("/api/experiment/auto_tuner/config");
    STATE.autoTunerConfig = res.data || null;
    const cfg = STATE.autoTunerConfig?.config || {};
    if (AT.dom.expAtEnabledChk) AT.dom.expAtEnabledChk.checked = Boolean(cfg.enabled);
    if (AT.dom.expAtShortChk) AT.dom.expAtShortChk.checked = Boolean(cfg.enable_short_term);
    if (AT.dom.expAtLongChk) AT.dom.expAtLongChk.checked = Boolean(cfg.enable_long_term);
    if (AT.dom.expAtLlmAssistChk) AT.dom.expAtLlmAssistChk.checked = Boolean(cfg.llm_assist_enabled);
    if (AT.dom.expAtShortWindow) AT.dom.expAtShortWindow.value = String(cfg.short_window_ticks ?? 10);
    if (AT.dom.expAtLongWindow) AT.dom.expAtLongWindow.value = String(cfg.long_window_ticks ?? 40);
    if (AT.dom.expAtCooldown) AT.dom.expAtCooldown.value = String(cfg.decision_cooldown_ticks ?? 2);
    if (AT.dom.expAtMaxUpdates) AT.dom.expAtMaxUpdates.value = String(cfg.max_param_updates_per_tick ?? 4);
    renderMetricTargets();
    if (!silent) {
      feedback("expAtConfigFeedback", "已刷新调参器配置。", "ok");
    }
  }

  async function refreshAutoTunerCatalog({ silent = false } = {}) {
    const res = await apiGet("/api/experiment/auto_tuner/catalog");
    STATE.autoTunerCatalog = res.data || null;
    renderParamCatalog();
    if (typeof window.renderCharts === "function") {
      try {
        window.renderCharts();
      } catch {}
    }
    if (!silent && AT.dom.expAtConfigMeta) {
      const summary = STATE.autoTunerCatalog?.summary || {};
      AT.dom.expAtConfigMeta.textContent = `参数目录 ${formatCount(summary.param_count)} 项，可自动调参 ${formatCount(summary.auto_tune_allowed_count)} 项。`;
    }
  }

  async function refreshAutoTunerRules({ silent = false } = {}) {
    const res = await apiGet("/api/experiment/auto_tuner/rules");
    STATE.autoTunerRules = res.data || null;
    AT.ruleDisabled = new Set(STATE.autoTunerRules?.rules?.disabled_rule_ids || []);
    AT.ruleProtected = new Set(STATE.autoTunerRules?.rules?.protected_rule_ids || []);
    renderRules();
    if (!silent) feedback("expAtConfigFeedback", "已刷新规则目录。", "ok");
  }

  async function refreshAutoTunerState({ silent = false } = {}) {
    const [stateRes, auditRes, rollbackRes] = await Promise.all([
      apiGet("/api/experiment/auto_tuner/state"),
      apiGet("/api/experiment/auto_tuner/audit?limit=80"),
      apiGet("/api/experiment/auto_tuner/rollback_points?limit=40"),
    ]);
    STATE.autoTunerState = stateRes.data || null;
    STATE.autoTunerAudit = auditRes.data || null;
    STATE.autoTunerRollbackPoints = rollbackRes.data || null;
    renderOverview();
    renderStateAndAudit();
    renderRollbackPoints();
    if (!silent) feedback("expAtConfigFeedback", "已刷新调参器状态。", "ok");
  }

  async function refreshAutoTunerLlmConfig({ silent = false } = {}) {
    const res = await apiGet("/api/experiment/auto_tuner/llm/config");
    STATE.autoTunerLlmConfig = res.data || null;
    renderLlmConfig();
    if (!silent) feedback("expAtLlmFeedback", "已刷新 LLM 配置。", "ok");
  }

  async function refreshAutoTunerLlmJobs({ silent = false } = {}) {
    const res = await apiGet("/api/experiment/auto_tuner/llm/jobs");
    STATE.autoTunerLlmJobs = res.data || { jobs: [] };
    renderLlmJobs();
    if (!silent) feedback("expAtLlmAnalyzeFeedback", "已刷新分析任务。", "ok");
  }

  async function refreshAutoTunerAll({ silent = false } = {}) {
    await Promise.all([
      refreshAutoTunerConfig({ silent: true }),
      refreshAutoTunerCatalog({ silent: true }),
      refreshAutoTunerRules({ silent: true }),
      refreshAutoTunerState({ silent: true }),
      refreshAutoTunerLlmConfig({ silent: true }),
      refreshAutoTunerLlmJobs({ silent: true }),
    ]);
    renderOverview();
    if (!silent) feedback("expAtConfigFeedback", "已刷新全部自适应调参器数据。", "ok");
  }

  async function saveAutoTunerConfig() {
    feedback("expAtConfigFeedback", "正在保存调参器配置…", "busy");
    try {
      const payload = {
        enabled: Boolean(AT.dom.expAtEnabledChk?.checked),
        enable_short_term: Boolean(AT.dom.expAtShortChk?.checked),
        enable_long_term: Boolean(AT.dom.expAtLongChk?.checked),
        llm_assist_enabled: Boolean(AT.dom.expAtLlmAssistChk?.checked),
        short_window_ticks: asNumber(AT.dom.expAtShortWindow?.value, 10),
        long_window_ticks: asNumber(AT.dom.expAtLongWindow?.value, 40),
        decision_cooldown_ticks: asNumber(AT.dom.expAtCooldown?.value, 2),
        max_param_updates_per_tick: asNumber(AT.dom.expAtMaxUpdates?.value, 4),
        metric_targets: collectMetricTargets(),
      };
      const res = await apiPost("/api/experiment/auto_tuner/config/save", { config: payload });
      STATE.autoTunerConfig = res.data || null;
      renderMetricTargets();
      renderOverview();
      feedback("expAtConfigFeedback", "已保存调参器配置。", "ok");
    } catch (error) {
      feedback("expAtConfigFeedback", `保存失败：${error.message}`, "err");
    }
  }

  async function saveRules() {
    feedback("expAtConfigFeedback", "正在保存规则配置…", "busy");
    try {
      let customRules = [];
      if (AT.dom.expAtCustomRulesEditor?.value.trim()) {
        customRules = JSON.parse(AT.dom.expAtCustomRulesEditor.value);
      }
      const res = await apiPost("/api/experiment/auto_tuner/rules/save", {
        rules: {
          disabled_rule_ids: Array.from(AT.ruleDisabled),
          protected_rule_ids: Array.from(AT.ruleProtected),
          custom_rules: Array.isArray(customRules) ? customRules : [],
        },
      });
      STATE.autoTunerRules = res.data || null;
      AT.ruleDisabled = new Set(STATE.autoTunerRules?.rules?.disabled_rule_ids || []);
      AT.ruleProtected = new Set(STATE.autoTunerRules?.rules?.protected_rule_ids || []);
      renderRules();
      renderOverview();
      feedback("expAtConfigFeedback", "已保存规则配置。", "ok");
    } catch (error) {
      feedback("expAtConfigFeedback", `规则保存失败：${error.message}`, "err");
    }
  }

  async function saveLlmConfig() {
    feedback("expAtLlmFeedback", "正在保存 LLM 配置…", "busy");
    try {
      const payload = {
        enabled: Boolean(AT.dom.expAtLlmEnabledChk?.checked),
        auto_analyze_on_completion: Boolean(AT.dom.expAtLlmAutoChk?.checked),
        base_url: String(AT.dom.expAtLlmBaseUrl?.value || "").trim(),
        api_key: String(AT.dom.expAtLlmApiKey?.value || "").trim(),
        model: String(AT.dom.expAtLlmModel?.value || "").trim(),
        max_prompt_chars: asNumber(AT.dom.expAtLlmMaxPromptChars?.value, 900000),
      };
      const res = await apiPost("/api/experiment/auto_tuner/llm/config/save", { config: payload });
      STATE.autoTunerLlmConfig = res.data || null;
      renderLlmConfig();
      renderOverview();
      feedback("expAtLlmFeedback", "已保存 LLM 配置。", "ok");
    } catch (error) {
      feedback("expAtLlmFeedback", `保存失败：${error.message}`, "err");
    }
  }

  async function startLlmAnalyze() {
    feedback("expAtLlmAnalyzeFeedback", "正在提交调参器分析任务…", "busy");
    try {
      const runId = String(STATE.selectedRunId || "").trim();
      const prompt = String(AT.dom.expAtLlmPrompt?.value || "").trim();
      const res = await apiPost("/api/experiment/auto_tuner/llm/analyze", {
        run_id: runId,
        user_prompt: prompt,
        focus_metrics: [],
      });
      feedback("expAtLlmAnalyzeFeedback", `已提交分析任务：${res.data?.job_id || "-"}`, "ok");
      await refreshAutoTunerLlmJobs({ silent: true });
    } catch (error) {
      feedback("expAtLlmAnalyzeFeedback", `提交失败：${error.message}`, "err");
    }
  }

  function renderOverview() {
    const cfg = STATE.autoTunerConfig?.config || {};
    const state = STATE.autoTunerState?.summary || {};
    const rulesSummary = STATE.autoTunerRules?.catalog?.summary || {};
    const llmCfg = STATE.autoTunerLlmConfig?.config || {};
    if (!AT.dom.expAutoTunerOverviewCards) return;
    AT.dom.expAutoTunerOverviewCards.innerHTML = [
      metricCard("调参器状态", boolLabel(Boolean(cfg.enabled)), `短期：${boolLabel(Boolean(cfg.enable_short_term))} | 长期：${boolLabel(Boolean(cfg.enable_long_term))}`),
      metricCard("持久参数数", formatCount(state.persisted_param_count), `运行时参数：${formatCount(state.runtime_param_count)}`),
      metricCard("活跃试验数", formatCount(state.active_trial_count), `已归档试验：${formatCount(state.trial_history_count)}`),
      metricCard("规则总量", formatCount((rulesSummary.builtin_count || 0) + (rulesSummary.generated_count || 0) + (rulesSummary.custom_count || 0)), `禁用：${formatCount(rulesSummary.disabled_count)} | 白名单：${formatCount(rulesSummary.protected_count)}`),
      metricCard("规则健康记录", formatCount(state.rule_health_count), "用于判断某条规则是长期有效、长期失效，还是经常触发回滚。"),
      metricCard("LLM 分析", boolLabel(Boolean(llmCfg.enabled)), `模型：${llmCfg.model || "-"} | 来源：${STATE.autoTunerLlmConfig?.source || "-"}`),
      metricCard("LLM 候选规则", formatCount(state.llm_candidate_rule_count), `已固化：${formatCount(state.llm_solidified_rule_count)} | 已拒绝：${formatCount(state.llm_rejected_rule_count)}`),
      metricCard("观察区", formatCount(state.observation_active_count), `待复审：${formatCount(state.observation_reviewable_count)} | 已归档：${formatCount(state.observation_history_count)}`),
      metricCard("自动验收", boolLabel(Boolean(cfg.llm_auto_validation_enabled)), `最近复审动作：${formatCount(state.last_observation_review_action_count)} | 历史：${formatCount(state.observation_review_history_count)}`),
    ].join("");
  }

  function renderObservationZone() {
    const stateWrap = STATE.autoTunerState || {};
    const state = stateWrap.state || {};
    const summary = stateWrap.summary || {};
    const active = Array.isArray(state.rule_observations) ? state.rule_observations : [];
    const history = Array.isArray(state.observation_history) ? state.observation_history : [];
    const lastReview = state.last_observation_review || {};

    if (AT.dom.expAtObservationSummary) {
      AT.dom.expAtObservationSummary.innerHTML = [
        miniRow("观察区概况", `当前观察区 ${formatCount(summary.observation_active_count)} 条；其中已满足最少观察轮数、可进入自动验收的有 ${formatCount(summary.observation_reviewable_count)} 条。`),
        miniRow("为什么需要观察区", "观察区的目标不是让 LLM 直接永久改规则，而是先让规则带着证据运行几轮，再判断它究竟是有效、无效，还是需要小步修订后继续观察。"),
      ].join("");
    }

    if (AT.dom.expAtObservationZone) {
      if (!active.length) {
        AT.dom.expAtObservationZone.innerHTML = emptyState("当前还没有进入观察区的规则。只有 LLM 自动建议真正落地后，才会在这里开始积累“生效前 / 生效后”的证据。");
      } else {
        AT.dom.expAtObservationZone.innerHTML = active.slice().reverse().map((item) => {
          const observedRuns = Array.isArray(item.observed_runs) ? item.observed_runs : [];
          const baseline = item.baseline_metric_summary || {};
          const latest = observedRuns.length ? observedRuns[observedRuns.length - 1] : null;
          const effect = latest?.effect || {};
          return `
            <details class="details-panel">
              <summary>
                <div class="mini-row">
                  <div class="title">${esc(item.title || item.rule_id || item.observation_id || "观察项")}</div>
                  <div class="desc">${esc(item.rule_id || "-")} | 来源：${esc(item.source_kind || "-")} | 动作：${esc(item.action || "-")}</div>
                  <div class="chips">
                    ${ruleChip(`观察轮数 ${formatCount(observedRuns.length)}`, "accent")}
                    ${ruleChip(`主指标 ${item.metric_key || "-"}`)}
                    ${ruleChip(`最近结论 ${effect.result || "待观察"}`, effect.result === "better" ? "accent" : effect.result === "worse" ? "danger" : "warn")}
                  </div>
                </div>
              </summary>
              <div class="details-body stack">
                ${miniRow("触发原因", item.reason || "本次没有额外填写原因。")}
                ${miniRow("基线摘要", baseline.metric_key ? `${baseline.metric_key} | 均值 ${formatMaybe(baseline.mean)} | 波动 ${formatMaybe(baseline.std)} | 最新 ${formatMaybe(baseline.latest)}` : "当前还没有可用的基线摘要。")}
                ${miniRow("最近一轮观察", latest ? `${latest.run_id || "-"} | 均值 ${formatMaybe(latest.metric_summary?.mean)} | 波动 ${formatMaybe(latest.metric_summary?.std)} | 最新 ${formatMaybe(latest.metric_summary?.latest)} | 改善比例 ${formatMaybe(effect.ratio)}` : "这条规则刚进入观察区，还没有后续运行证据。")}
                ${miniRow("自动验收状态", `已复审 ${formatCount(item.review_count || 0)} 次 | 最近动作：${item.last_review_result?.action || "尚未复审"} | 最近理由：${item.last_review_result?.reason || "暂无"}`)}
              </div>
            </details>
          `;
        }).join("");
      }
    }

    if (AT.dom.expAtObservationHistory) {
      if (!history.length) {
        AT.dom.expAtObservationHistory.innerHTML = emptyState("观察区历史还没有内容。等自动验收真正做出“固化、回退、移除”等结论后，这里会留下完整痕迹。");
      } else {
        AT.dom.expAtObservationHistory.innerHTML = history.slice().reverse().slice(0, 80).map((item) => {
          const observedRuns = Array.isArray(item.observed_runs) ? item.observed_runs : [];
          return miniRow(
            `${formatTime(item.resolved_at_ms || item.last_review_at_ms || item.created_at_ms)} | ${item.title || item.rule_id || item.observation_id}`,
            `状态：${item.status || "-"}\n规则：${item.rule_id || "-"}\n观察轮数：${formatCount(observedRuns.length)}\n最近动作：${item.last_review_result?.action || "-"}\n理由：${item.last_review_result?.reason || item.reason || "暂无"}`
          );
        }).join("");
      }
    }

    if (AT.dom.expAtObservationReview) {
      const decisions = Array.isArray(lastReview.decisions) ? lastReview.decisions : [];
      if (!lastReview.review_id) {
        AT.dom.expAtObservationReview.innerHTML = emptyState("当前还没有自动验收结果。启用自动验收后，观察区里满足最少观察轮数的规则会在 run 结束时自动复审。");
      } else {
        AT.dom.expAtObservationReview.innerHTML = [
          miniRow(`${formatTime(lastReview.reviewed_at_ms)} | ${lastReview.review_id}`, `运行：${lastReview.run_id || "-"}\n摘要：${lastReview.summary || "暂无摘要"}`),
          miniRow("本轮决策", decisions.length ? decisions.map((item) => `${item.rule_id || item.observation_id || "-"} | ${item.action || "-"}${item.status ? ` | ${item.status}` : ""}`).join("\n") : "这次自动验收没有形成可落地的决策。"),
          miniRow("补充说明", (lastReview.notes || []).join("\n") || "没有额外补充说明。"),
          miniRow("报告摘录", lastReview.report_excerpt || "当前没有可展示的报告摘录。"),
        ].join("");
      }
    }
  }

  function paramLabel(paramId) {
    const key = String(paramId || "").trim();
    return PARAM_LABELS[key] || key || "-";
  }

  function paramDisplay(paramId) {
    const key = String(paramId || "").trim();
    if (!key) return "-";
    const label = paramLabel(key);
    return label !== key ? `${label}（${key}）` : label;
  }

  function metricDisplay(metricKey) {
    const key = String(metricKey || "").trim();
    return key ? metricLabel(key) : "-";
  }

  function formatIssueModeLabel(mode) {
    const key = String(mode || "").trim();
    if (key === "high") return "偏高";
    if (key === "low") return "偏低";
    if (key === "flatline") return "过平";
    return key || "未标注";
  }

  function formatTrialResultLabel(result) {
    const key = String(result || "").trim();
    if (key === "success") return "有效";
    if (key === "failure") return "无效";
    if (key === "neutral") return "中性";
    return key || "未评估";
  }

  function formatAutoTunerKindLabel(kind) {
    const key = String(kind || "").trim();
    const mapping = {
      prepare: "准备阶段",
      short_term_update: "短期调参",
      long_term_update: "长期调参",
      endogenous_guard_blocked: "内源保护拦截",
      param_backoff: "参数冷却回退",
      trial_evaluated: "短期试验评估",
      persisted_trial_evaluated: "长期试验评估",
      apply_error: "参数应用失败",
      llm_auto_apply: "LLM 自动落地",
      llm_auto_loop_failed: "LLM 自动分析失败",
      llm_candidate_maintenance: "LLM 候选规则维护",
      observation_run_recorded: "观察区运行记录",
      llm_observation_review_applied: "观察区自动验收",
      llm_observation_review_failed: "观察区验收失败",
    };
    return mapping[key] || key || "事件";
  }

  function formatRuleIdLabel(ruleId) {
    const text = String(ruleId || "").trim();
    if (!text) return "未命名规则";
    if (text.startsWith("builtin.cs.")) return "内建认知拼接规则";
    if (text.startsWith("builtin.endogenous.")) return "内建内源恢复规则";
    if (text.startsWith("builtin.ev_balance.")) return "内建 EV 传播诊断规则";
    if (text.startsWith("builtin.resource.")) return "内建资源保护规则";
    if (text.startsWith("builtin.long_term.")) return "内建长期稳态规则";
    if (text.startsWith("catalog::")) return "参数目录派生规则";
    if (text.startsWith("manual.")) return "人工操作";
    return text;
  }

  function findParamMeta(paramId) {
    const key = String(paramId || "").trim();
    if (!key) return null;
    const items = Array.isArray(STATE.autoTunerCatalog?.params) ? STATE.autoTunerCatalog.params : [];
    return items.find((item) => String(item?.param_id || "").trim() === key) || null;
  }

  function formatParamMetaHint(paramId) {
    const meta = findParamMeta(paramId);
    if (!meta) return "";
    const chunks = [];
    if (meta.module) chunks.push(`模块：${meta.module}`);
    const impacts = Array.isArray(meta.impacts) ? meta.impacts.slice(0, 4).map(metricDisplay).filter(Boolean) : [];
    if (impacts.length) chunks.push(`影响指标：${impacts.join("、")}`);
    if (meta.note) chunks.push(String(meta.note).trim());
    return chunks.join("；");
  }

  function explainReasonText(reason, item = {}) {
    const text = String(reason || "").trim();
    if (!text) {
      return "这条动作没有附带额外说明，通常表示沿用了该规则的默认调节逻辑。";
    }

    let match = text.match(/^catalog_rule metric=([^ ]+) mode=([^ ]+) mean=([-+0-9.]+) std=([-+0-9.]+)/);
    if (match) {
      return `通用目录规则判断“${metricDisplay(match[1])}”在最近窗口内处于“${formatIssueModeLabel(match[2])}”状态，窗口均值 ${formatMaybe(match[3], 4)}、波动 ${formatMaybe(match[4], 4)}，因此做一次小步修正。`;
    }

    match = text.match(/^trial_(success|failure|neutral) metric=(.+)$/);
    if (match) {
      return `这是前一次试验的回看结果：对应指标“${metricDisplay(match[2])}”本轮被判定为“${formatTrialResultLabel(match[1])}”，所以给该参数增加一段冷却期，避免连续误调。`;
    }

    match = text.match(/^cs_low_score_rejections_dominate rejected_low_score=([-+0-9.]+) raw_accepted=([-+0-9.]+)/);
    if (match) {
      return `认知拼接已经能产出原始候选，但更多候选死在最低分门槛；低分淘汰均值 ${formatMaybe(match[1], 3)}，原始可接受候选均值 ${formatMaybe(match[2], 3)}，说明当前更像“阈值偏严”，而不是“根本没候选”。`;
    }

    if (text === "cs_low_score_rejections_dominate_and_raw_accepts_too_few") {
      return "认知拼接不仅低分淘汰占主导，而且连原始可接受候选都偏少，所以除了放松最低分，还需要放松种子进入门槛。";
    }

    match = text.match(/^cs_component_limit_rejections_dominate rejected_component_limit=([-+0-9.]+)/);
    if (match) {
      return `认知拼接候选主要死在组分上限，而不是分数不足；组分上限淘汰均值 ${formatMaybe(match[1], 3)}，所以本次优先放宽最大组分数。`;
    }

    match = text.match(/^cs_candidates_present_but_actions_flat mean_candidates=([-+0-9.]+) mean_actions=([-+0-9.]+)/);
    if (match) {
      return `认知拼接候选已经存在，但几乎没有真正转成动作；候选均值 ${formatMaybe(match[1], 3)}、动作均值 ${formatMaybe(match[2], 3)}，这更像“门槛太严”或“事件成熟门槛太高”。`;
    }

    if (text === "cs_seed_gate_may_be_too_strict") return "当前怀疑种子进入门槛过严，导致候选还没长出来就被刷掉。";
    if (text === "cs_event_gate_may_be_too_strict") return "当前怀疑事件进入门槛过严，候选形成后仍难以落成真正事件对象。";
    if (text === "event_grasp_gate_may_be_too_strict_for_string_mode_bootstrap") return "当前怀疑叙事把握门槛对字符串模式冷启动过严，候选有了，但还不容易成熟为可展示叙事。";
    match = text.match(/^event_grasp_not_emitting_after_post_action_focus actions=([-+0-9.]+) post_focus=([-+0-9.]+) selected=([-+0-9.]+) emitted=([-+0-9.]+)/);
    if (match) {
      return `认知拼接动作已经存在，而且 post-CS 焦点里也确实选到了事件，但 event_grasp 还是几乎没真正发射；动作均值 ${formatMaybe(match[1], 3)}、后拼接焦点均值 ${formatMaybe(match[2], 3)}、入选事件均值 ${formatMaybe(match[3], 3)}、发射均值 ${formatMaybe(match[4], 3)}。这更像 grasp 最低总能量门槛偏严，而不是没有拼接事件。`;
    }

    match = text.match(/^cs_same_signature_competition_hot pressure=([-+0-9.]+) margin=([-+0-9.]+)/);
    if (match) {
      return `同签名候选竞争已经偏热，而且大多数候选离阈值还有余量；竞争压力 ${formatMaybe(match[1], 3)}、阈值余量 ${formatMaybe(match[2], 3)}，所以这次选择收紧门槛，而不是继续放松。`;
    }

    match = text.match(/^cs_actions_too_dense mean_candidates=([-+0-9.]+) mean_actions=([-+0-9.]+)/);
    if (match) {
      return `认知拼接动作已经过密；候选均值 ${formatMaybe(match[1], 3)}、动作均值 ${formatMaybe(match[2], 3)}，此时继续放松会让拼接泛滥，所以需要反向收紧。`;
    }

    if (text === "cs_branching_too_dense_raise_distance_penalty") return "当前分支扩散过多，所以提高上下文距离惩罚，减少跨度太远的拼接。";
    if (text === "cs_candidates_exist_but_conversion_low_raise_match_strength_weight") return "候选已经有，但转化率低；本次提高匹配强度权重，让高匹配候选更容易真正落地。";
    if (text === "cs_candidates_exist_but_conversion_low_reduce_anchor_distance_penalty") return "候选已经有，但距离惩罚可能过强；本次适度放松，让近似上下文也有机会完成拼接。";

    match = text.match(/^cs_timing_hot mean_timing=([-+0-9.]+)/);
    if (match) {
      return `认知拼接耗时已经过热，最近窗口耗时均值 ${formatMaybe(match[1], 1)} ms，所以需要优先收敛 fanout 和上下文扩散。`;
    }

    if (text === "recover_endogenous_sources") return "当前更像上游来源对象不够，先补内源来源，而不是直接抬后段预算。";
    if (text === "recover_endogenous_structure_rounds") return "当前更像结构级查存跟进不够，先增加结构级查存轮次，让已有来源真正走完。";
    if (text === "recover_endogenous_retention") return "当前对象形成后衰减过快，先提高状态池保活，让候选别刚出现就掉光。";
    if (text === "recover_endogenous_softcap") return "当前状态池软容量过早施压，先放宽容量区间，避免对象刚积累就被挤掉。";
    if (text === "recover_endogenous_cam_capacity") return "当前注意力工作集太小，先增加 CAM 容量，让更多完整结构种子和内源重采样材料被保留下来。";
    if (text === "recover_endogenous_capacity") return "当前整体容量偏紧，先放宽容量，而不是盲目加深下游计算。";
    if (text === "recover_endogenous_detail_budget") return "当前内源细节预算确实在压瘦入选 SA，所以这次优先补细节预算。";
    if (text === "recover_endogenous_followthrough") return "当前更像前面已有候选，但后续刺激级跟进行为不够，先补后续轮次和耐心。";

    if (text === "timing_hotspot_hdb_structure_pressure") return "当前真正过热的是结构级查存，而不是总耗时抽象升高；所以这次直接收紧结构级轮次。";
    if (text === "timing_hotspot_hdb_stimulus_pressure") return "当前真正过热的是刺激级查存，所以这次优先收紧刺激级轮次，而不是误伤别的模块。";
    if (text === "timing_hotspot_hdb_flat_unit_pressure") return "当前 HDB 的原始展开过宽，单结构细节单元太多，所以先回收每结构细节上限。";
    if (text === "timing_hotspot_state_pool_cache_pressure") return "当前主要压力在缓存中和链；这次提高最小中和效果阈值，减少低收益中和动作。";
    if (text === "timing_hotspot_state_pool_maintenance_pressure") return "当前主要压力在状态池维护链；这次提前软容量压力，让维护成本先降下来。";
    if (text === "timing_hotspot_attention_fanout_pressure") return "当前注意力真正过热的是候选扇出太大，所以这次先回收 CAM 上限。";
    if (text === "timing_hotspot_attention_candidate_pressure") return "当前注意力低能候选太多，所以这次提高最低总能量门槛，减少低收益候选占位。";
    if (text === "timing_hotspot_time_sensor_binding_pressure") return "当前时间感受器绑定总量过高，所以这次先收紧总绑定上限。";
    if (text === "timing_hotspot_time_sensor_task_pressure") return "当前时间感受器延迟任务表偏热，所以这次适度回收延迟任务容量。";
    if (text === "timing_hotspot_sensor_echo_pressure") return "当前文本感受器更像回声池堆积，而不是用户输入本身出错，所以这次只收紧回声相关容量与门槛。";

    if (text === "no_op_clamped_or_quantized") return "这次实际没有真正改动成功：参数已经贴近边界，或当前量化步长太粗，继续推只会空转。";
    if (text === "timing_spike") return "最近出现明显耗时尖峰，需要先止损，避免继续放大展开规模。";
    if (text === "raw_unit_spike") return "最近原始细节单元激增，说明上游展开过宽，继续放大会先拖垮性能。";
    if (text === "avoid_flatline") return "对应感受或长期指标过于平直，本次是故意稍微放松，避免系统被拉成一条死直线。";
    if (text === "dissonance_spiky") return "违和感虽然高，但更像尖峰抖动，所以本次拉长冷却以抑制瞬时爆发。";
    if (text === "reduce_dissonance_spread") return "违和感扩散过宽，需要减少同时扩散的信号数量。";
    if (text === "punish_signal_sparse") return "惩罚信号偏稀，当前压力过高不应再额外放大惩罚链。";
    if (text === "pressure_high_without_dissonance") return "压力高但违和感并不高，更像压力门槛偏敏感，而不是认知冲突真的很多。";
    if (text === "punish_signal_overhang") return "惩罚信号在状态池里挂得太久，造成整体压力尾巴偏长。";
    if (text === "expectation_high") return "期待感偏高，说明奖励预期门槛可能偏低。";
    if (text === "reward_signal_overhang") return "奖励信号在状态池里拖尾过长，容易把期待感维持在不合理高位。";
    if (text === "correct_event_too_frequent") return "正确事件触发过密，说明正反馈链条太容易自激。";
    if (text === "recall_too_frequent") return "回忆动作触发过于频繁，开始挤占主认知流程。";

    return text.replace(/_/g, " ");
  }

  function summarizeEndogenousBalance(balance) {
    if (!balance || typeof balance !== "object") {
      return "当前事件没有附带额外的内源恢复快照。";
    }
    const notes = [];
    if (balance.source_supply_thin) notes.push("上游完整种子 / 运行态分辨率供给偏薄");
    if (balance.context_branching_thin) notes.push("旧同内容多上下文审计偏薄");
    if (asNumber(balance.internal_deficit, 0) > 0) notes.push(`内源 SA 仍有缺口 ${formatPercent(balance.internal_deficit, 1)}`);
    if (asNumber(balance.ratio_deficit, 0) > 0) notes.push(`内外源比例仍有缺口 ${formatPercent(balance.ratio_deficit, 1)}`);
    if (asNumber(balance.selected_deficit, 0) > 0) notes.push(`入选结构仍有缺口 ${formatPercent(balance.selected_deficit, 1)}`);
    if (balance.dominance_lost) notes.push("内源刺激已经失去相对主导地位");
    if (!notes.length) notes.push("上游供给总体正常，本轮更像局部阈值、预算或性能保护问题");
    return notes.join("；");
  }

  function explainParamAdjustment(update) {
    if (!update || typeof update !== "object") return "没有可展示的参数动作。";
    const toNum = Number(update.to);
    const fromNum = Number(update.from);
    const hasTo = Number.isFinite(toNum);
    const hasFrom = Number.isFinite(fromNum);
    const deltaNum = Number(update.delta);
    let actionText = "进行了调整";
    if (hasFrom && hasTo) {
      if (toNum > fromNum) actionText = `上调为 ${formatMaybe(toNum, 4)}（原 ${formatMaybe(fromNum, 4)}）`;
      else if (toNum < fromNum) actionText = `下调为 ${formatMaybe(toNum, 4)}（原 ${formatMaybe(fromNum, 4)}）`;
      else actionText = `保持为 ${formatMaybe(toNum, 4)}`;
    } else if (Number.isFinite(deltaNum)) {
      actionText = `${deltaNum >= 0 ? "上调" : "下调"}幅度 ${formatMaybe(Math.abs(deltaNum), 4)}`;
    }
    const metricText = metricDisplay(update.metric_key);
    const issueText = formatIssueModeLabel(update.issue_mode);
    const metaHint = formatParamMetaHint(update.param);
    return `${paramDisplay(update.param)}：${actionText}。对应指标“${metricText}”当前判断为“${issueText}”。${explainReasonText(update.reason, update)}${metaHint ? `；补充：${metaHint}` : ""}`;
  }

  function renderUpdateList(updates, limit = 8) {
    const items = Array.isArray(updates) ? updates : [];
    if (!items.length) return emptyState("当前没有已执行参数动作。");
    return items.slice(0, limit).map((item) => {
      const title = `${formatTime(item.ts_ms || item.started_at_ms)} | ${formatRuleIdLabel(item.rule_id)}${item.persist ? " | 已持久化" : " | 仅运行态"}`;
      return miniRow(title, explainParamAdjustment(item));
    }).join("");
  }

  function renderTrialList(items, limit = 8) {
    const rows = Array.isArray(items) ? items : [];
    if (!rows.length) return emptyState("当前没有待评估试验。");
    return rows.slice(0, limit).map((item) => {
      const title = `${formatTime(item.started_at_ms)} | ${formatRuleIdLabel(item.rule_id)} | ${item.persist ? "长期试验" : "短期试验"}`;
      const desc = [
        `参数：${paramDisplay(item.param)}`,
        `指标：${metricDisplay(item.metric_key)} | 问题类型：${formatIssueModeLabel(item.issue_mode)}`,
        `起始值：${Number.isFinite(Number(item.from)) ? formatMaybe(item.from, 4) : "-"} | 当前目标值：${Number.isFinite(Number(item.to)) ? formatMaybe(item.to, 4) : "-"}`,
        `原因：${explainReasonText(item.reason, item)}`
      ].join("\n");
      return miniRow(title, desc);
    }).join("");
  }

  function renderRuleHealthRows(items, limit = 10) {
    const rows = Array.isArray(items) ? items : [];
    if (!rows.length) return emptyState("当前还没有规则健康记录。");
    return rows.slice(0, limit).map((row) => {
      const success = asNumber(row.success_count, 0);
      const failure = asNumber(row.failure_count, 0);
      const neutral = asNumber(row.neutral_count, 0);
      const total = Math.max(1, success + failure + neutral);
      const successRate = success / total;
      const title = `${formatRuleIdLabel(row.rule_id)} | 命中 ${formatCount(row.hit_count)}`;
      const desc = [
        `成功 ${formatCount(success)} | 失败 ${formatCount(failure)} | 中性 ${formatCount(neutral)} | 回滚 ${formatCount(row.rollback_count)}`,
        `成功率 ${formatPercent(successRate, 1)} | 平均改善 ${formatMaybe(row.avg_improvement, 3)} | 最近结果 ${formatTrialResultLabel(row.last_result)}`,
        `最近评估：${formatTime(row.last_evaluated_at_ms)}`
      ].join("\n");
      return miniRow(title, desc);
    }).join("");
  }

  function renderSnapshotDigest(title, bundle) {
    if (!bundle || typeof bundle !== "object" || !Object.keys(bundle).length) {
      return `<details class="details-panel"><summary><h4>${esc(title)}</h4></summary><div class="details-body stack">${emptyState("当前还没有可展示的专项快照。")}</div></details>`;
    }
    const ev = bundle.ev_balance || {};
    const endo = bundle.endogenous_balance || {};
    const cs = bundle.cognitive_stitching || {};
    const timing = bundle.timing_hotspot || {};
    const energyCause = ev.source_supply_thin
      ? "更像上游供给偏薄，当前优先走保活链。"
      : ev.propagation_chain_weak
        ? "更像局部残差传播链偏弱。"
        : ev.induction_chain_weak
          ? "更像 ER→EV 诱发链偏弱。"
          : ev.retention_chain_weak
            ? "更像传播/诱发已在工作，但 EV 留存偏弱。"
            : "当前没有识别到明显的 EV 专项偏差。";
    const csCause = cs.low_score_dominant
      ? "低分淘汰主导"
      : cs.component_limit_dominant
        ? "组分上限主导"
        : cs.non_positive_edge_dominant
          ? "非正边主导"
          : cs.candidate_rich_but_action_starved
            ? "有候选但动作稀薄"
            : "暂无显著异常";
    const timingCause = timing.dominant_group_label || timing.dominant_group_id || "未识别";
    return `<details class="details-panel"><summary><h4>${esc(title)}</h4></summary><div class="details-body stack">${
      [
        miniRow("窗口信息", `tick=${formatCount(bundle.tick_index)} | 窗口大小=${formatCount(bundle.window_size)} | 更新时间=${formatTime(bundle.updated_at_ms)}`),
        miniRow("实虚能量专项", [
          `结论：${energyCause}`,
          `EV / ER 诊断比值：均值 ${formatMaybe(ev.mean_ev_to_er_ratio, 3)} | 最新 ${formatMaybe(ev.latest_ev_to_er_ratio, 3)}`,
          `局部传播目标占比：${formatPercent(asNumber(ev.mean_propagated_target_ratio, 0), 1)} | ER 诱发 EV 占比：${formatPercent(asNumber(ev.mean_ev_from_er_ratio, 0), 1)}`,
        ].join("\n")),
        miniRow("内源供给专项", [
          `供给偏薄：${boolLabel(Boolean(endo.source_supply_thin))} | 供给健康：${boolLabel(Boolean(endo.source_supply_healthy))}`,
          `CAM 均值 ${formatMaybe(endo.mean_cam_items, 2)} | 入选结构均值 ${formatMaybe(endo.mean_selected_structures, 2)}`,
        ].join("\n")),
        miniRow("认知拼接专项", [
          `结论：${csCause}`,
          `候选均值 ${formatMaybe(cs.mean_candidates, 3)} | 动作均值 ${formatMaybe(cs.mean_actions, 3)} | 转化率 ${formatPercent(asNumber(cs.candidate_to_action_ratio, 0), 1)}`,
        ].join("\n")),
        miniRow("耗时热点专项", [
          `主热点：${timingCause}`,
          `总热点标记：${boolLabel(Boolean(timing.total_hot))} | 细分热点数：${formatCount(timing.hot_group_count || 0)}`,
        ].join("\n")),
      ].join("")
    }</div></details>`;
  }

  function renderBlockedUpdateList(updates, limit = 8) {
    const rows = Array.isArray(updates) ? updates : [];
    if (!rows.length) return emptyState("当前没有被保护器拦截的参数动作。");
    return rows.slice(0, limit).map((item) => {
      const delta = Number(item?.delta);
      const title = `${formatRuleIdLabel(item?.rule_id)} | ${delta >= 0 ? "拟上调" : "拟下调"} ${paramDisplay(item?.param)}`;
      const desc = [
        `对应指标：${metricDisplay(item?.metric_key || "") || "-"}`,
        `原始原因：${explainReasonText(item?.reason || "", item)}`
      ].join("\n");
      return miniRow(title, desc);
    }).join("");
  }

  function renderAuditCard(item) {
    if (!item || typeof item !== "object") return "";
    const kind = String(item.kind || "event");
    const title = `${formatTime(item.ts_ms)} | ${formatAutoTunerKindLabel(kind)}`;
    const chips = [];
    const body = [];
    let summary = "当前事件没有额外摘要。";

    if (kind === "short_term_update" || kind === "long_term_update") {
      const applied = Array.isArray(item.applied) ? item.applied : [];
      const isLong = kind === "long_term_update";
      summary = `本轮${isLong ? "长期" : "短期"}调参已执行 ${formatCount(applied.length)} 项参数动作。`;
      chips.push(ruleChip(isLong ? "长期" : "短期", isLong ? "warn" : "accent"));
      chips.push(ruleChip(`已执行 ${formatCount(applied.length)} 项`));
      if (item.window?.n) chips.push(ruleChip(`窗口 ${formatCount(item.window.n)} tick`));
      body.push(miniRow("本轮判断", summarizeEndogenousBalance(item.endogenous_balance)));
      if (item.window) {
        const parts = [
          `总耗时均值 ${formatMaybe(item.window.timing_mean, 1)} ms`,
          item.window.timing_max !== undefined ? `总耗时峰值 ${formatMaybe(item.window.timing_max, 1)} ms` : "",
          item.window.raw_mean !== undefined ? `原始细节均值 ${formatMaybe(item.window.raw_mean, 1)}` : "",
          item.window.dissonance_mean !== undefined ? `违和感均值 ${formatMaybe(item.window.dissonance_mean, 3)}` : "",
          item.window.dissonance_std !== undefined ? `违和感波动 ${formatMaybe(item.window.dissonance_std, 3)}` : ""
        ].filter(Boolean);
        body.push(miniRow("窗口摘要", parts.join(" | ")));
      }
      body.push(`<details class="details-panel"><summary><h4>本轮已执行参数</h4></summary><div class="details-body stack">${renderUpdateList(applied, 12)}</div></details>`);
      if (item.rollback_point?.point_id) {
        body.push(miniRow("回滚保护", `已创建回滚点 ${item.rollback_point.point_id}，如果后续验证失败，可恢复到调参前状态。`));
      }
    } else if (kind === "endogenous_guard_blocked") {
      const blocked = Array.isArray(item.blocked_updates) ? item.blocked_updates : [];
      summary = `本轮拦住了 ${formatCount(blocked.length)} 项“看起来能调、实际上可能错位”的参数动作。`;
      chips.push(ruleChip(`已拦截 ${formatCount(blocked.length)} 项`, "danger"));
      if (item.balance?.source_supply_thin) chips.push(ruleChip("上游供给偏薄", "warn"));
      if (item.balance?.context_branching_thin) chips.push(ruleChip("上下文分流偏薄", "warn"));
      body.push(miniRow("拦截原因", summarizeEndogenousBalance(item.balance)));
      body.push(`<details class="details-panel"><summary><h4>被拦住的参数动作</h4></summary><div class="details-body stack">${renderBlockedUpdateList(blocked, 12)}</div></details>`);
    } else if (kind === "param_backoff") {
      summary = `该参数进入冷却回退，接下来 ${formatCount(item.cooldown_ticks)} 个 tick 内不会被频繁重复推动。`;
      chips.push(ruleChip(`冷却 ${formatCount(item.cooldown_ticks)} tick`, "warn"));
      body.push(miniRow("参数", paramDisplay(item.param)));
      body.push(miniRow("为什么需要冷却", explainReasonText(item.reason, item)));
      body.push(miniRow("当前回退分数", `累积分数 ${formatMaybe(item.score, 2)}。分数越高，冷却越长，用来抑制“同一个参数连续空推”。`));
    } else if (kind === "trial_evaluated" || kind === "persisted_trial_evaluated") {
      const isPersisted = kind === "persisted_trial_evaluated";
      summary = `${isPersisted ? "长期" : "短期"}试验已完成回看：结果为“${formatTrialResultLabel(item.result)}”。`;
      chips.push(ruleChip(isPersisted ? "长期评估" : "短期评估", isPersisted ? "warn" : "accent"));
      chips.push(ruleChip(`结果 ${formatTrialResultLabel(item.result)}`, item.result === "success" ? "accent" : item.result === "failure" ? "danger" : "warn"));
      if (item.rolled_back) chips.push(ruleChip("已回滚", "danger"));
      body.push(miniRow("评估对象", `${paramDisplay(item.param)} | 指标 ${metricDisplay(item.metric_key)} | 规则 ${formatRuleIdLabel(item.rule_id)}`));
      body.push(miniRow("结果解释", `${formatTrialResultLabel(item.result)} | 改善量 ${formatMaybe(item.improvement, 4)} | ${item.rolled_back ? "因为失败已执行回滚。" : "当前保留这次改动结果。"}`));
      if (item.evaluation) {
        body.push(miniRow("窗口结果", `均值 ${formatMaybe(item.evaluation.current_mean, 4)} | 波动 ${formatMaybe(item.evaluation.current_std, 4)} | 最新 ${formatMaybe(item.evaluation.current_latest, 4)} | 相对改善 ${formatMaybe(item.evaluation.ratio, 4)}`));
      }
    } else if (kind === "apply_error") {
      summary = "参数应用阶段发生异常，这条动作没有真正落地。";
      chips.push(ruleChip("应用失败", "danger"));
      body.push(miniRow("失败参数", paramDisplay(item.update?.param || "")));
      body.push(miniRow("错误信息", item.error || "未返回错误详情。"));
    } else {
      summary = explainReasonText(item.reason || item.message || "", item);
      if (item.rule_id) chips.push(ruleChip(formatRuleIdLabel(item.rule_id)));
      if (item.param) chips.push(ruleChip(paramLabel(item.param)));
      if (item.metric_key) chips.push(ruleChip(metricDisplay(item.metric_key)));
      body.push(miniRow("原始事件摘要", JSON.stringify(item, null, 2)));
    }

    return `
      <details class="details-panel">
        <summary>
          <div class="mini-row">
            <div class="title">${esc(title)}</div>
            <div class="desc">${esc(summary)}</div>
            <div class="chips">${chips.join("")}</div>
          </div>
        </summary>
        <div class="details-body stack">
          ${body.join("")}
        </div>
      </details>
    `;
  }

  function getMetricTargetConfig(metricKey) {
    const key = String(metricKey || "").trim();
    const items = Array.isArray(STATE.autoTunerConfig?.metric_targets) ? STATE.autoTunerConfig.metric_targets : [];
    return items.find((item) => String(item?.key || "").trim() === key) || null;
  }

  function summarizeMetricWindow(rows, key, windowSize) {
    const slice = asArray(rows).slice(-Math.max(1, asNumber(windowSize, 40)));
    const values = slice.map((row) => Number(row?.[key])).filter((v) => Number.isFinite(v));
    if (!values.length) return null;
    const sorted = values.slice().sort((a, b) => a - b);
    const latest = values[values.length - 1];
    const first = values[0];
    return {
      key,
      count: values.length,
      mean: values.reduce((sum, value) => sum + value, 0) / values.length,
      min: sorted[0],
      max: sorted[sorted.length - 1],
      median: sorted[Math.floor(sorted.length / 2)],
      latest,
      delta: latest - first,
    };
  }

  function maxPair(a, b) {
    return Math.max(asNumber(a, 0), asNumber(b, 0));
  }

  function formatInsightValue(summary, { ratio = false, digits = 3 } = {}) {
    if (!summary) return "-";
    return ratio ? formatPercent(summary.latest, 1) : formatMaybe(summary.latest, digits);
  }

  function formatInsightNote(summary, { ratio = false, digits = 3 } = {}) {
    if (!summary) return "当前运行记录缺少该指标。";
    const meanText = ratio ? formatPercent(summary.mean, 1) : formatMaybe(summary.mean, digits);
    const deltaText = ratio ? formatSigned(summary.delta * 100, 1) + "%" : formatSigned(summary.delta, digits);
    return `窗口均值 ${meanText} | 首末变化 ${deltaText}`;
  }

  function buildAutoTunerMetricSnapshot(rows, windowSize) {
    const summary = {
      runtimeResolutionDegraded: summarizeMetricWindow(rows, "pool_runtime_resolution_degraded_item_count", windowSize),
      runtimeResolutionActiveComponents: summarizeMetricWindow(rows, "pool_runtime_resolution_active_component_count", windowSize),
      runtimeResolutionDroppedComponents: summarizeMetricWindow(rows, "pool_runtime_resolution_dropped_component_count", windowSize),
      maintenanceRuntimeResolutionRefreshed: summarizeMetricWindow(rows, "maintenance_runtime_resolution_refreshed_item_count", windowSize),
      maintenanceRuntimeResolutionDegraded: summarizeMetricWindow(rows, "maintenance_runtime_resolution_degraded_item_count", windowSize),
      growthTarget: summarizeMetricWindow(rows, "induction_growth_target_count", windowSize),
      growthIdentityHit: summarizeMetricWindow(rows, "induction_growth_identity_hit_count", windowSize),
      growthIdentityCreated: summarizeMetricWindow(rows, "induction_growth_identity_created_count", windowSize),
      growthRuntimeOnly: summarizeMetricWindow(rows, "induction_growth_runtime_only_count", windowSize),
      growthPrunedLowEnergy: summarizeMetricWindow(rows, "induction_growth_pruned_low_energy_count", windowSize),
      growthDeduped: summarizeMetricWindow(rows, "induction_growth_deduped_count", windowSize),
      growthMemoryTerminalPassthrough: summarizeMetricWindow(rows, "induction_growth_memory_terminal_passthrough_count", windowSize),
      growthTotalDeltaEr: summarizeMetricWindow(rows, "induction_growth_total_delta_er", windowSize),
      growthTotalDeltaEv: summarizeMetricWindow(rows, "induction_growth_total_delta_ev", windowSize),
      growthSourceComponentEr: summarizeMetricWindow(rows, "induction_growth_source_component_er_total", windowSize),
      growthResidualComponentEv: summarizeMetricWindow(rows, "induction_growth_residual_component_ev_total", windowSize),
      contextual: summarizeMetricWindow(rows, "pool_contextual_item_ratio", windowSize),
      residualOrigin: summarizeMetricWindow(rows, "pool_residual_origin_item_ratio", windowSize),
      hdbSameContentMultiContext: summarizeMetricWindow(rows, "hdb_same_content_multi_context_ratio", windowSize),
      hdbResidualDiff: summarizeMetricWindow(rows, "hdb_residual_diff_entry_ratio", windowSize),
      poolEvToEr: summarizeMetricWindow(rows, "pool_ev_to_er_ratio", windowSize),
      inductionTotalDeltaEv: summarizeMetricWindow(rows, "induction_total_delta_ev", windowSize),
      inductionPropagatedEv: summarizeMetricWindow(rows, "induction_propagated_ev_total", windowSize),
      inductionEvFromEr: summarizeMetricWindow(rows, "induction_ev_from_er_total", windowSize),
      inductionPropagatedRatio: summarizeMetricWindow(rows, "induction_propagated_target_ratio", windowSize),
      inductionEvFromErRatio: summarizeMetricWindow(rows, "induction_ev_from_er_ratio", windowSize),
      csCandidates: summarizeMetricWindow(rows, "cs_candidate_count", windowSize),
      csActions: summarizeMetricWindow(rows, "cs_action_count", windowSize),
      csLowScoreRejected: summarizeMetricWindow(rows, "cs_candidate_rejected_low_score_count", windowSize),
      csComponentRejected: summarizeMetricWindow(rows, "cs_candidate_rejected_component_limit_count", windowSize),
      csNonPositiveRejected: summarizeMetricWindow(rows, "cs_candidate_rejected_non_positive_edge_count", windowSize),
      csThresholdMargin: summarizeMetricWindow(rows, "cs_candidate_threshold_margin_mean", windowSize),
      csReplacement: summarizeMetricWindow(rows, "cs_candidate_replacement_count", windowSize),
      csKeptExisting: summarizeMetricWindow(rows, "cs_candidate_kept_existing_count", windowSize),
      csRawAccepted: summarizeMetricWindow(rows, "cs_candidate_raw_accepted_count", windowSize),
      csStimulusNewStructures: summarizeMetricWindow(rows, "stimulus_new_structure_count", windowSize),
      csTiming: summarizeMetricWindow(rows, "timing_cognitive_stitching_ms", windowSize),
      csCreated: summarizeMetricWindow(rows, "cs_created_count", windowSize),
      csExtended: summarizeMetricWindow(rows, "cs_extended_count", windowSize),
      csMerged: summarizeMetricWindow(rows, "cs_merged_count", windowSize),
      csReinforced: summarizeMetricWindow(rows, "cs_reinforced_count", windowSize),
      timingTotal: summarizeMetricWindow(rows, "timing_total_logic_ms", windowSize),
      timingStructure: summarizeMetricWindow(rows, "timing_structure_level_ms", windowSize),
      timingStimulus: summarizeMetricWindow(rows, "timing_stimulus_level_ms", windowSize),
      timingCache: summarizeMetricWindow(rows, "timing_cache_neutralization_ms", windowSize),
      timingMaintenance: summarizeMetricWindow(rows, "timing_maintenance_ms", windowSize),
      timingAttention: summarizeMetricWindow(rows, "timing_attention_ms", windowSize),
      timingSensor: summarizeMetricWindow(rows, "timing_sensor_ms", windowSize),
      timingTimeSensor: summarizeMetricWindow(rows, "timing_time_sensor_ms", windowSize),
    };

    const activeResolutionComponents = maxPair(
      summary.runtimeResolutionActiveComponents?.mean,
      summary.runtimeResolutionActiveComponents?.latest
    );
    const droppedResolutionComponents = maxPair(
      summary.runtimeResolutionDroppedComponents?.mean,
      summary.runtimeResolutionDroppedComponents?.latest
    );
    const runtimeResolutionVisibleRatio = activeResolutionComponents / Math.max(1e-6, activeResolutionComponents + droppedResolutionComponents);
    const growthIdentityTotal = Math.max(
      1e-6,
      asNumber(summary.growthIdentityHit?.mean, 0) + asNumber(summary.growthIdentityCreated?.mean, 0)
    );
    const growthIdentityHitRatio = asNumber(summary.growthIdentityHit?.mean, 0) / growthIdentityTotal;
    const sourceSupplyHealthy = Boolean(
      maxPair(summary.growthTarget?.mean, summary.growthTarget?.latest) >= 0.5
      || maxPair(summary.runtimeResolutionDegraded?.mean, summary.runtimeResolutionDegraded?.latest) >= 1.0
      || runtimeResolutionVisibleRatio >= 0.55
      || maxPair(summary.hdbResidualDiff?.mean, summary.hdbResidualDiff?.latest) >= 0.18
    );
    const contextBranchingThin = Boolean(maxPair(summary.hdbSameContentMultiContext?.mean, summary.hdbSameContentMultiContext?.latest) < 0.03);
    const sourceSupplyThin = Boolean(!sourceSupplyHealthy);

    const meanCandidates = asNumber(summary.csCandidates?.mean, 0);
    const meanActions = asNumber(summary.csActions?.mean, 0);
    const meanLowScoreRejected = asNumber(summary.csLowScoreRejected?.mean, 0);
    const meanComponentRejected = asNumber(summary.csComponentRejected?.mean, 0);
    const meanNonPositiveRejected = asNumber(summary.csNonPositiveRejected?.mean, 0);
    const meanReplacements = asNumber(summary.csReplacement?.mean, 0);
    const meanKeptExisting = asNumber(summary.csKeptExisting?.mean, 0);
    const meanRawAccepted = asNumber(summary.csRawAccepted?.mean, 0);
    const meanThresholdMargin = asNumber(summary.csThresholdMargin?.mean, 0);
    const meanTiming = asNumber(summary.csTiming?.mean, 0);
    const meanStimulusNewStructures = asNumber(summary.csStimulusNewStructures?.mean, 0);
    const latestStimulusNewStructures = asNumber(summary.csStimulusNewStructures?.latest, 0);
    const target = getMetricTargetConfig("timing_cognitive_stitching_ms");
    const timingExpectedMax = Math.max(1200, asNumber(target?.expected_max, 1200));
    const candidateToActionRatio = meanCandidates > 1e-6 ? meanActions / meanCandidates : 0;
    const competitionPressure = (meanReplacements + meanKeptExisting) / Math.max(1e-6, Math.max(meanCandidates, meanRawAccepted, 1.0));
    const candidateRichButActionStarved = Boolean(meanCandidates >= 0.8 && meanActions <= 0.05);
    const upstreamStructureAlive = Boolean(meanStimulusNewStructures >= 0.12 || latestStimulusNewStructures > 0.0);
    const lowScoreDominant = Boolean(
      meanLowScoreRejected >= 0.5
      && meanLowScoreRejected >= meanComponentRejected
      && meanLowScoreRejected >= meanNonPositiveRejected
    );
    const componentLimitDominant = Boolean(
      meanComponentRejected >= 0.5
      && meanComponentRejected > meanLowScoreRejected
      && meanComponentRejected >= meanNonPositiveRejected
    );
    const nonPositiveEdgeDominant = Boolean(
      meanNonPositiveRejected >= 0.5
      && meanNonPositiveRejected > meanLowScoreRejected
      && meanNonPositiveRejected >= meanComponentRejected
    );
    const timingHot = Boolean(meanTiming > timingExpectedMax * 0.85);
    const outputTotal = asNumber(summary.csCreated?.mean, 0) + asNumber(summary.csExtended?.mean, 0) + asNumber(summary.csMerged?.mean, 0) + asNumber(summary.csReinforced?.mean, 0);

    const timingTotalMean = asNumber(summary.timingTotal?.mean, 0);
    const timingTotalLatest = asNumber(summary.timingTotal?.latest, 0);
    const timingTotalExpectedMax = Math.max(8000, asNumber(getMetricTargetConfig("timing_total_logic_ms")?.expected_max, 8000));
    const timingTotalHot = Boolean(timingTotalMean > timingTotalExpectedMax * 0.85 || timingTotalLatest > timingTotalExpectedMax);
    const timingExpectedMaxFor = (key, fallback) => Math.max(fallback, asNumber(getMetricTargetConfig(key)?.expected_max, fallback));
    const timingGroups = [
      {
        id: "hdb",
        label: "HDB 主链",
        items: [
          { key: "timingStructure", metricKey: "timing_structure_level_ms", label: "结构级" },
          { key: "timingStimulus", metricKey: "timing_stimulus_level_ms", label: "刺激级" },
        ],
      },
      {
        id: "state_pool",
        label: "状态池与中和",
        items: [
          { key: "timingCache", metricKey: "timing_cache_neutralization_ms", label: "缓存中和" },
          { key: "timingMaintenance", metricKey: "timing_maintenance_ms", label: "状态池维护" },
        ],
      },
      { id: "attention", label: "注意力", items: [{ key: "timingAttention", metricKey: "timing_attention_ms", label: "注意力" }] },
      { id: "sensor", label: "文本感受器", items: [{ key: "timingSensor", metricKey: "timing_sensor_ms", label: "文本感受器" }] },
      { id: "time_sensor", label: "时间感受器", items: [{ key: "timingTimeSensor", metricKey: "timing_time_sensor_ms", label: "时间感受器" }] },
      { id: "cognitive_stitching", label: "认知拼接", items: [{ key: "csTiming", metricKey: "timing_cognitive_stitching_ms", label: "认知拼接" }] },
    ].map((group) => {
      const meanMs = group.items.reduce((sum, item) => sum + asNumber(summary[item.key]?.mean, 0), 0);
      const latestMs = group.items.reduce((sum, item) => sum + asNumber(summary[item.key]?.latest, 0), 0);
      const share = meanMs / Math.max(1e-6, timingTotalMean);
      const pressure = group.items.reduce((best, item) => {
        const expectedMax = timingExpectedMaxFor(item.metricKey, 1);
        return Math.max(best, asNumber(summary[item.key]?.mean, 0) / Math.max(1e-6, expectedMax));
      }, 0);
      const hot = group.items.some((item) => {
        const expectedMax = timingExpectedMaxFor(item.metricKey, 1);
        return asNumber(summary[item.key]?.mean, 0) > expectedMax * 0.85 || asNumber(summary[item.key]?.latest, 0) > expectedMax;
      });
      return {
        ...group,
        meanMs,
        latestMs,
        share,
        pressure,
        hot,
        severity: pressure + share * 0.35 + (hot ? 0.2 : 0),
      };
    });
    timingGroups.sort((a, b) => (b.severity - a.severity) || (b.share - a.share));
    const dominantTimingGroup = timingGroups[0] && (timingGroups[0].hot || timingTotalHot || timingGroups[0].share >= 0.30) ? timingGroups[0] : null;

    const rawUnitPressure = asNumber(summarizeMetricWindow(rows, "internal_resolution_raw_unit_count", windowSize)?.mean, 0) > Math.max(1, asNumber(getMetricTargetConfig("internal_resolution_raw_unit_count")?.expected_max, 350)) * 0.90;
    const mergedPressure = asNumber(summarizeMetricWindow(rows, "merged_flat_token_count", windowSize)?.mean, 0) > Math.max(1, asNumber(getMetricTargetConfig("merged_flat_token_count")?.expected_max, 240)) * 0.95;
    const poolLoadHigh = asNumber(summarizeMetricWindow(rows, "pool_active_item_count", windowSize)?.mean, 0) > Math.max(1, asNumber(getMetricTargetConfig("pool_active_item_count")?.expected_max, 260)) * 0.90;
    const cacheResidualMean = asNumber(summarizeMetricWindow(rows, "cache_residual_flat_token_count", windowSize)?.mean, 0);
    const mergedMean = asNumber(summarizeMetricWindow(rows, "merged_flat_token_count", windowSize)?.mean, 0);
    const cacheResidualHigh = cacheResidualMean >= Math.max(16, mergedMean * 0.08);
    const camMean = asNumber(summarizeMetricWindow(rows, "cam_item_count", windowSize)?.mean, 0);
    const attentionCandidateMean = asNumber(summarizeMetricWindow(rows, "attention_state_pool_candidate_count", windowSize)?.mean, 0);
    const currentMaxCam = Math.max(16, asNumber(STATE.autoTunerState?.state?.runtime_params?.["attention.max_cam_items"], 16));
    const attentionFanoutHigh = camMean > Math.max(16, currentMaxCam * 0.85) || attentionCandidateMean > Math.max(18, camMean * 3, currentMaxCam * 2.5);
    const attentionCandidatePressure = attentionCandidateMean > Math.max(24, camMean * 4, currentMaxCam * 3);
    const delayedTaskTableMean = asNumber(summarizeMetricWindow(rows, "time_sensor_delayed_task_table_size", windowSize)?.mean, 0);
    const delayedRegisteredMean = asNumber(summarizeMetricWindow(rows, "time_sensor_delayed_task_registered_count", windowSize)?.mean, 0);
    const delayedExecutedMean = asNumber(summarizeMetricWindow(rows, "time_sensor_delayed_task_executed_count", windowSize)?.mean, 0);
    const delayedCapacity = Math.max(24, asNumber(STATE.autoTunerState?.state?.runtime_params?.["time_sensor.delayed_task_capacity"], 48));
    const timeSensorTaskPressure = delayedTaskTableMean > Math.max(12, delayedCapacity * 0.70) || (delayedRegisteredMean >= 3 && delayedRegisteredMean > delayedExecutedMean * 1.5);
    const sensorEchoMean = asNumber(summarizeMetricWindow(rows, "sensor_echo_pool_size", windowSize)?.mean, 0);
    const sensorEchoPressure = sensorEchoMean > Math.max(1, asNumber(getMetricTargetConfig("sensor_echo_pool_size")?.expected_max, 24)) * 0.85;

    return {
      windowSize,
      summary,
      sourceSupplyHealthy,
      contextBranchingThin,
      sourceSupplyThin,
      runtimeResolutionVisibleRatio,
      growthIdentityHitRatio,
      candidateToActionRatio,
      competitionPressure,
      candidateRichButActionStarved,
      upstreamStructureAlive,
      lowScoreDominant,
      componentLimitDominant,
      nonPositiveEdgeDominant,
      timingHot,
      outputTotal,
      timingGroups,
      dominantTimingGroup,
      timingTotalHot,
      rawUnitPressure,
      mergedPressure,
      poolLoadHigh,
      cacheResidualHigh,
      attentionFanoutHigh,
      attentionCandidatePressure,
      timeSensorTaskPressure,
      sensorEchoPressure,
    };
  }

  function renderAutoTunerMetricInsights() {
    if (!AT.dom.expAtMetricInsightCards && !AT.dom.expAtMetricInsightNarrative) return;
    const rows = asArray(STATE.lastMetricsRows).filter((row) => row && typeof row === "object");
    if (!rows.length) {
      if (AT.dom.expAtMetricInsightCards) {
        AT.dom.expAtMetricInsightCards.innerHTML = emptyState("请先在“运行记录与摘要”中选中一条运行记录，这里才会出现专项趋势快照。");
      }
      if (AT.dom.expAtMetricInsightNarrative) {
        AT.dom.expAtMetricInsightNarrative.innerHTML = emptyState("当前还没有可用于 AutoTuner 快照分析的 metrics.jsonl 数据。");
      }
      return;
    }

    const windowSize = Math.max(10, asNumber(STATE.autoTunerConfig?.config?.long_window_ticks, 40));
    const snap = buildAutoTunerMetricSnapshot(rows, windowSize);
      const cards = [
        { label: "感应生长目标均值", summary: snap.summary.growthTarget, note: "新版主链核心：A 直接长成 A+B 的完整结构目标数量。" },
        { label: "完整身份命中均值", summary: snap.summary.growthIdentityHit, note: "越高说明重复出现的 A+B 正在汇聚到同一完整结构身份。" },
        { label: "完整身份创建均值", summary: snap.summary.growthIdentityCreated, note: "冷启动或新语料可升高；成熟后应更多转为命中。" },
        { label: "运行态降分辨率对象", summary: snap.summary.runtimeResolutionDegraded, note: "表示状态池里同一完整结构的显示/组件分辨率下降，不是创建新的 HDB 身份。" },
        { label: "活跃组件均值", summary: snap.summary.runtimeResolutionActiveComponents, note: "退化视图中仍保留能量的组件规模。" },
        { label: "淡出组件均值", summary: snap.summary.runtimeResolutionDroppedComponents, note: "已经低于显示/解释阈值的组件规模；用于看退化是否柔和。" },
        { label: "source-side ER 份额", summary: snap.summary.growthSourceComponentEr, note: "用于确认生长对象里的真实证据仍来自来源 A。" },
        { label: "residual-side EV 份额", summary: snap.summary.growthResidualComponentEv, note: "用于确认残差 B 保持预测/想象能量口径。" },
        { label: "EV / ER 诊断比值", summary: snap.summary.poolEvToEr, ratio: false, note: "它主要是诊断口径；若长期偏低，更像预测能量供给、传播或保活链整体偏薄。" },
        { label: "局部传播 EV 均值", summary: snap.summary.inductionPropagatedEv, note: "它更接近“已有预期沿 HDB 残差边继续扩散”的强度。" },
        { label: "ER 诱发 EV 均值", summary: snap.summary.inductionEvFromEr, note: "它更接近“现实证据重新拉起预测”的强度。" },
        { label: "总逻辑耗时均值", summary: snap.summary.timingTotal, note: "它只是总症状，不直接代表某个模块就是元凶。" },
        { label: "刺激级耗时均值", summary: snap.summary.timingStimulus, note: "高时更像刺激级查存链在烧，而不是 HDB 全部都该收紧。" },
      { label: "缓存中和耗时均值", summary: snap.summary.timingCache, note: "高时往往说明中和链与状态池残响在烧。" },
      { label: "状态池维护耗时均值", summary: snap.summary.timingMaintenance, note: "高时优先检查状态池软容量与对象堆积。" },
    ];

    if (AT.dom.expAtMetricInsightCards) {
      AT.dom.expAtMetricInsightCards.innerHTML = cards.map((item) => metricCard(
        item.label,
        formatInsightValue(item.summary, { ratio: Boolean(item.ratio), digits: 3 }),
        `${formatInsightNote(item.summary, { ratio: Boolean(item.ratio), digits: 3 })} | ${item.note}`
      )).join("");
    }

      const sourceSummary = snap.sourceSupplyThin
        ? "当前完整结构种子、生长目标或运行态分辨率证据偏薄。调参器应先保活状态池、观察 growth 目标与内源重采样是否被压瘦，而不是回到旧上下文分流口径。"
        : "当前完整结构种子和运行态分辨率证据总体健康；若内源仍不足，更可能是预算、轮次、注意力容量或后续查存链在中下游卡住。";

      let energySummary = "当前实虚能量关系没有出现特别明显的理论违和。";
      const poolEvToErMean = asNumber(snap.summary.poolEvToEr?.mean, 0);
      const propagatedRatioMean = asNumber(snap.summary.inductionPropagatedRatio?.mean, 0);
      const evFromErRatioMean = asNumber(snap.summary.inductionEvFromErRatio?.mean, 0);
      if (poolEvToErMean < 0.98) {
        if (propagatedRatioMean < 0.35 && evFromErRatioMean < 0.16) {
          energySummary = "当前 EV / ER 诊断比值偏低，而且局部传播与 ER→EV 诱发两条链都偏弱。更像预测链整体没有把现实种子和 HDB 残差边连接起来。";
        } else if (propagatedRatioMean < 0.35) {
          energySummary = "当前 EV / ER 诊断比值偏低，而且“局部传播目标占比”偏低。更像 HDB 残差边续写偏弱，而不是只靠调衰减就能解决。";
        } else if (evFromErRatioMean < 0.16) {
          energySummary = "当前 EV / ER 诊断比值偏低，而且“ER 诱发 EV 占比”偏低。更像现实证据本身没有有效转成新预测。";
        } else {
          energySummary = "当前 EV / ER 诊断比值偏低，但传播与诱发两条链都还在工作。更像 EV 留存偏弱，或状态池保活链太薄。";
        }
      } else if (propagatedRatioMean < 0.35) {
        energySummary = "当前感应赋能更偏现实重新诱发，而不是沿 HDB 残差边续写。若这不是你预期的风格，应优先排查残差局部链接保留和 EV 传播比例。";
      } else if (evFromErRatioMean < 0.12) {
        energySummary = "当前局部续写还在，但“现实证据诱发新预测”的比例偏弱。这更像 ER→EV 诱发链保守，而不是整体 EV 完全消失。";
      }

    let csSummary = "认知拼接当前没有明显异常。";
    if (snap.lowScoreDominant) {
      csSummary = "当前认知拼接更像“低分淘汰主导”：候选已经存在，但大多过不了最低分门槛。调参器应优先考虑放松 `认知拼接最低候选分`，必要时再放松种子门槛。";
    } else if (snap.componentLimitDominant) {
      csSummary = "当前认知拼接更像“组分上限主导”：候选不是没来，而是因为允许的组分数太小而被截断。调参器应优先提高 `认知拼接最大组分数`。";
    } else if (snap.nonPositiveEdgeDominant) {
      csSummary = "当前认知拼接更像“非正边主导”：主要问题不是阈值过高，而是边权本身不给正向支持，这时不应误降最低分门槛。";
    } else if (snap.candidateRichButActionStarved && snap.upstreamStructureAlive && !snap.timingHot) {
      csSummary = "当前认知拼接已经有候选、上游结构也还活着，但几乎没有转成动作。这时更像阈值、种子能量或事件成熟门槛偏严。";
    } else if (snap.competitionPressure >= 0.65 && asNumber(snap.summary.csThresholdMargin?.mean, 0) >= 0.18) {
      csSummary = "当前认知拼接更像“竞争过热”：同签名候选互相挤压，而且大多数离阈值还有余量。此时应适度收紧门槛，而不是继续放松。";
    }

    let timingSummary = "当前没有识别到特别突出的耗时热点。";
    if (snap.dominantTimingGroup?.id === "state_pool") {
      timingSummary = "当前总耗时的主热点更像“状态池与中和”，不是 HDB 主链。也就是说，真正该优先收的是中和阈值与状态池软容量，而不是盲目减少结构来源。";
    } else if (snap.dominantTimingGroup?.id === "hdb") {
      timingSummary = "当前总耗时的主热点更像 HDB 主链，尤其要区分是结构级耗时热，还是刺激级耗时热，再分别收结构级轮次或刺激级轮次。";
    } else if (snap.dominantTimingGroup?.id === "attention") {
      timingSummary = "当前总耗时更像注意力候选扇出过宽，所以优先收 CAM 上限和最低总能量门槛，比误伤 HDB 更合理。";
    } else if (snap.dominantTimingGroup?.id === "time_sensor") {
      timingSummary = "当前总耗时更像时间感受器自身过热，应优先看绑定总量和延迟任务表，不应去压主认知链预算。";
    } else if (snap.dominantTimingGroup?.id === "sensor") {
      timingSummary = "当前更像文本感受器回声池堆积，而不是用户输入本身有问题；因此只应微调回声相关容量和门槛。";
    } else if (snap.dominantTimingGroup?.id === "cognitive_stitching") {
      timingSummary = "当前热点来自 CS 回滚/对照支路；若本轮没有显式开启 CS，这通常意味着指标来自旧 run 或兼容支路，需要先核对 manifest/config，再决定是否调 CS 参数。";
    }

      const narrativeRows = [
        `<details class="details-panel" open><summary><h4>感应生长与运行态分辨率判断</h4></summary><div class="details-body stack">${
        [
          miniRow("窗口范围", `当前使用最近 ${formatCount(snap.windowSize)} 个 tick 作为专项快照窗口。`),
          miniRow("结论", sourceSummary),
          miniRow("关键证据", [
            `感应生长目标：最新 ${formatInsightValue(snap.summary.growthTarget)} | 均值 ${formatMaybe(snap.summary.growthTarget?.mean, 3)}`,
            `完整身份：命中均值 ${formatMaybe(snap.summary.growthIdentityHit?.mean, 3)} | 创建均值 ${formatMaybe(snap.summary.growthIdentityCreated?.mean, 3)} | 命中率 ${formatPercent(snap.growthIdentityHitRatio, 1)}`,
            `运行态分辨率：降分辨率对象最新 ${formatInsightValue(snap.summary.runtimeResolutionDegraded)} | 活跃组件均值 ${formatMaybe(snap.summary.runtimeResolutionActiveComponents?.mean, 3)} | 淡出组件均值 ${formatMaybe(snap.summary.runtimeResolutionDroppedComponents?.mean, 3)} | 可见组件占比 ${formatPercent(snap.runtimeResolutionVisibleRatio, 1)}`,
            `保护/旁路：runtime-only 均值 ${formatMaybe(snap.summary.growthRuntimeOnly?.mean, 3)} | 低能剪枝均值 ${formatMaybe(snap.summary.growthPrunedLowEnergy?.mean, 3)} | 记忆终端旁路均值 ${formatMaybe(snap.summary.growthMemoryTerminalPassthrough?.mean, 3)}`,
          ].join("\n")),
          miniRow("对调参器的真实影响", snap.sourceSupplyThin
            ? "这会触发“先保活 StatePool / EV / CAM，再决定是否补结构预算”的保护逻辑，避免在完整种子不足时盲目扩容下游。"
            : "这意味着主链已经有完整结构种子与运行态分辨率证据，若后续仍不产出，问题更可能在阈值、预算或后续轮次。"),
          ].join("")
        }</div></details>`,
        `<details class="details-panel"><summary><h4>实虚能量与感应赋能判断</h4></summary><div class="details-body stack">${
          [
            miniRow("结论", energySummary),
            miniRow("关键证据", [
              `EV / ER 诊断比值：最新 ${formatMaybe(snap.summary.poolEvToEr?.latest, 3)} | 均值 ${formatMaybe(snap.summary.poolEvToEr?.mean, 3)}`,
              `局部传播 EV：均值 ${formatMaybe(snap.summary.inductionPropagatedEv?.mean, 3)} | ER 诱发 EV：均值 ${formatMaybe(snap.summary.inductionEvFromEr?.mean, 3)}`,
              `局部传播目标占比：${formatPercent(asNumber(snap.summary.inductionPropagatedRatio?.mean, 0), 1)} | ER 诱发 EV 占比：${formatPercent(asNumber(snap.summary.inductionEvFromErRatio?.mean, 0), 1)}`,
              `生长组件审计：source-side ER 均值 ${formatMaybe(snap.summary.growthSourceComponentEr?.mean, 3)} | residual-side EV 均值 ${formatMaybe(snap.summary.growthResidualComponentEv?.mean, 3)}`,
            ].join("\n")),
            miniRow("对调参器的真实影响", poolEvToErMean < 0.98
              ? propagatedRatioMean < 0.35
                ? "这会优先驱动提高 `ev_propagation_ratio`，因为问题更像 HDB 残差边续写太薄，而不是直接去加大任意预算。"
                : evFromErRatioMean < 0.16
                  ? "这会优先驱动提高 `er_induction_ratio`，因为问题更像现实证据没有有效诱发出新预测。"
                  : "这会优先驱动提高 `状态池虚能量保活比例`；若 ER 同时显著过满，才会温和回收 `状态池实能量保活比例`。"
              : "若 EV / ER 已大体正常，但行为仍不对，问题更可能在拼接、注意力、奖惩或行动链，而不是总能量比例本身。"),
          ].join("")
        }</div></details>`,
        `<details class="details-panel"><summary><h4>CS 回滚诊断（默认折叠）</h4></summary><div class="details-body stack">${
        [
          miniRow("结论", csSummary),
          miniRow("关键证据", [
            `候选均值 ${formatMaybe(snap.summary.csCandidates?.mean, 3)} | 动作均值 ${formatMaybe(snap.summary.csActions?.mean, 3)} | 转化率 ${formatPercent(snap.candidateToActionRatio, 1)}`,
            `低分淘汰均值 ${formatMaybe(snap.summary.csLowScoreRejected?.mean, 3)} | 组分淘汰均值 ${formatMaybe(snap.summary.csComponentRejected?.mean, 3)} | 非正边淘汰均值 ${formatMaybe(snap.summary.csNonPositiveRejected?.mean, 3)}`,
            `阈值余量均值 ${formatMaybe(snap.summary.csThresholdMargin?.mean, 3)} | 竞争压力 ${formatMaybe(snap.competitionPressure, 3)} | 产出总量 ${formatMaybe(snap.outputTotal, 3)}`,
          ].join("\n")),
          miniRow("对调参器的真实影响", snap.lowScoreDominant
            ? "仅在 CS 显式开启时，才会优先驱动降低 `认知拼接最低候选分`，而不是乱改组分上限。"
            : snap.componentLimitDominant
              ? "仅在 CS 显式开启时，才会优先驱动提高 `认知拼接最大组分数`，而不是误以为阈值过高。"
              : snap.competitionPressure >= 0.65
                ? "仅在 CS 显式开启时，才会优先驱动收紧候选门槛，避免同签名候选挤成一团。"
                : "默认 growth + CS disabled 下，这组指标为 0 是正常背景；当前更适合作为回滚/对照观察证据。"),
        ].join("")
      }</div></details>`,
      `<details class="details-panel"><summary><h4>耗时热点归因判断</h4></summary><div class="details-body stack">${
        [
          miniRow("结论", timingSummary),
          miniRow("主热点链路", snap.dominantTimingGroup
            ? `${snap.dominantTimingGroup.label} | 均值 ${formatMaybe(snap.dominantTimingGroup.meanMs, 1)} ms | 占总耗时 ${formatPercent(snap.dominantTimingGroup.share, 1)}`
            : "当前没有明显超过阈值的单一热点链路。"),
          miniRow("关键证据", [
            `总逻辑耗时：均值 ${formatMaybe(snap.summary.timingTotal?.mean, 1)} ms | 最新 ${formatMaybe(snap.summary.timingTotal?.latest, 1)} ms`,
            `HDB 主链：结构级 ${formatMaybe(snap.summary.timingStructure?.mean, 1)} ms + 刺激级 ${formatMaybe(snap.summary.timingStimulus?.mean, 1)} ms`,
            `状态池与中和：缓存中和 ${formatMaybe(snap.summary.timingCache?.mean, 1)} ms + 状态池维护 ${formatMaybe(snap.summary.timingMaintenance?.mean, 1)} ms`,
            `注意力 ${formatMaybe(snap.summary.timingAttention?.mean, 1)} ms | 文本感受器 ${formatMaybe(snap.summary.timingSensor?.mean, 1)} ms | 时间感受器 ${formatMaybe(snap.summary.timingTimeSensor?.mean, 1)} ms`,
          ].join("\n")),
          miniRow("对调参器的真实影响",
            snap.dominantTimingGroup?.id === "state_pool"
              ? "会优先推动提高中和最小效果阈值、提前软容量压力，而不是再去错位收 HDB 结构上限。"
              : snap.dominantTimingGroup?.id === "hdb"
                ? "会优先区分结构级热还是刺激级热，再分别收对应轮次；若原始展开过宽，还会回收每结构细节单元上限。"
                : snap.dominantTimingGroup?.id === "attention"
                  ? "会优先回收 `注意力工作集上限`，必要时再提高 `注意力最低总能量门槛`。"
                  : snap.dominantTimingGroup?.id === "time_sensor"
                    ? "会优先回收时间感受器绑定总量或延迟任务容量，不会直接去压主链预算。"
                    : snap.dominantTimingGroup?.id === "sensor"
                      ? "会优先只动文本感受器回声池相关参数，避免把“输入变长”误判成全局预算错误。"
                      : "当前更适合作为继续观测的证据，必要时再结合具体 audit 事件做判断。"),
        ].join("")
      }</div></details>`,
      `<details class="details-panel"><summary><h4>为什么这块值得重点实验</h4></summary><div class="details-body stack">${
        [
          miniRow("理论验证点", "这组专项快照现在直接对应三个核心断言：一是“感应赋能直接生成完整 A+B”，二是“状态池退化只是运行态分辨率下降，不新建退化 HDB 身份”，三是“总耗时只是症状，必须继续分解到真实热点链路”。"),
          miniRow("建议观察方式", "优先同时观察：growth 目标、完整身份命中/创建、组件 ER/EV 审计、运行态分辨率、runtime-only/低能剪枝/记忆终端旁路，以及各分项耗时占总耗时的份额。CS 和旧 context 指标只在回滚/对照时展开。"),
        ].join("")
      }</div></details>`,
    ];

    if (AT.dom.expAtMetricInsightNarrative) {
      AT.dom.expAtMetricInsightNarrative.innerHTML = narrativeRows.join("");
    }
  }

  function renderStateAndAudit() {
    const stateWrap = STATE.autoTunerState || {};
    const state = stateWrap.state || {};
    const audit = STATE.autoTunerAudit?.items || [];
    const ruleHealth = state.rule_health || {};
    const recentApplied = Array.isArray(state.last_applied_updates) ? state.last_applied_updates.slice().reverse() : [];
    const activeTrials = Array.isArray(state.active_trials) ? state.active_trials.slice().reverse() : [];
    const latestAudit = audit.slice().sort((a, b) => asNumber(b?.ts_ms, 0) - asNumber(a?.ts_ms, 0));
    const healthRows = Object.values(ruleHealth).sort((a, b) => asNumber(b.hit_count, 0) - asNumber(a.hit_count, 0)).slice(0, 16);
    if (AT.dom.expAtStateSummary) {
      AT.dom.expAtStateSummary.innerHTML = [
        miniRow("调参器状态总览", `当前持久参数 ${formatCount(Object.keys(state.persisted_params || {}).length)} 个；活跃试验 ${formatCount(activeTrials.length)} 个；试验历史 ${formatCount((state.trial_history || []).length)} 条；最近已执行参数动作 ${formatCount(recentApplied.length)} 条。`),
        `<details class="details-panel"><summary><h4>最近已执行参数动作</h4></summary><div class="details-body stack">${renderUpdateList(recentApplied, 10)}</div></details>`,
        `<details class="details-panel"><summary><h4>当前活跃试验</h4></summary><div class="details-body stack">${renderTrialList(activeTrials, 10)}</div></details>`,
        `<details class="details-panel"><summary><h4>规则健康度 Top</h4></summary><div class="details-body stack">${renderRuleHealthRows(healthRows, 10)}</div></details>`,
        renderSnapshotDigest("最近短期专项快照", state.last_short_term_snapshots || {}),
        renderSnapshotDigest("最近长期专项快照", state.last_long_term_snapshots || {}),
      ].join("");
    }
    if (AT.dom.expAtAuditLog) {
      if (!latestAudit.length) {
        AT.dom.expAtAuditLog.innerHTML = emptyState("当前还没有调参审计日志。");
      } else {
        AT.dom.expAtAuditLog.innerHTML = latestAudit.slice(0, 36).map((item) => renderAuditCard(item)).join("");
      }
    }
    renderRecentLlmSuggestions();
    renderObservationZone();
    renderAutoTunerMetricInsights();
  }

  async function refreshAutoTunerConfig({ silent = false } = {}) {
    const res = await apiGet("/api/experiment/auto_tuner/config");
    STATE.autoTunerConfig = res.data || null;
    const cfg = STATE.autoTunerConfig?.config || {};
    if (AT.dom.expAtEnabledChk) AT.dom.expAtEnabledChk.checked = Boolean(cfg.enabled);
    if (AT.dom.expAtShortChk) AT.dom.expAtShortChk.checked = Boolean(cfg.enable_short_term);
    if (AT.dom.expAtLongChk) AT.dom.expAtLongChk.checked = Boolean(cfg.enable_long_term);
    if (AT.dom.expAtLlmAssistChk) AT.dom.expAtLlmAssistChk.checked = Boolean(cfg.llm_assist_enabled);
    if (AT.dom.expAtAutoValidationChk) AT.dom.expAtAutoValidationChk.checked = Boolean(cfg.llm_auto_validation_enabled);
    if (AT.dom.expAtShortWindow) AT.dom.expAtShortWindow.value = String(cfg.short_window_ticks ?? 10);
    if (AT.dom.expAtLongWindow) AT.dom.expAtLongWindow.value = String(cfg.long_window_ticks ?? 40);
    if (AT.dom.expAtCooldown) AT.dom.expAtCooldown.value = String(cfg.decision_cooldown_ticks ?? 2);
    if (AT.dom.expAtMaxUpdates) AT.dom.expAtMaxUpdates.value = String(cfg.max_param_updates_per_tick ?? 4);
    if (AT.dom.expAtAutoValidationMinRuns) AT.dom.expAtAutoValidationMinRuns.value = String(cfg.llm_auto_validation_min_runs ?? 2);
    if (AT.dom.expAtAutoValidationMaxItems) AT.dom.expAtAutoValidationMaxItems.value = String(cfg.llm_auto_validation_max_observations_per_review ?? 4);
    if (AT.dom.expAtAutoValidationEveryRunChk) AT.dom.expAtAutoValidationEveryRunChk.checked = Boolean(cfg.llm_auto_validation_review_every_run);
    renderMetricTargets();
    renderAutoTunerMetricInsights();
    if (!silent) feedback("expAtConfigFeedback", "已刷新调参器配置。", "ok");
  }

  async function saveAutoTunerConfig() {
    feedback("expAtConfigFeedback", "正在保存调参器配置…", "busy");
    try {
      const payload = {
        enabled: Boolean(AT.dom.expAtEnabledChk?.checked),
        enable_short_term: Boolean(AT.dom.expAtShortChk?.checked),
        enable_long_term: Boolean(AT.dom.expAtLongChk?.checked),
        llm_assist_enabled: Boolean(AT.dom.expAtLlmAssistChk?.checked),
        llm_auto_validation_enabled: Boolean(AT.dom.expAtAutoValidationChk?.checked),
        short_window_ticks: asNumber(AT.dom.expAtShortWindow?.value, 10),
        long_window_ticks: asNumber(AT.dom.expAtLongWindow?.value, 40),
        decision_cooldown_ticks: asNumber(AT.dom.expAtCooldown?.value, 2),
        max_param_updates_per_tick: asNumber(AT.dom.expAtMaxUpdates?.value, 4),
        llm_auto_validation_min_runs: asNumber(AT.dom.expAtAutoValidationMinRuns?.value, 2),
        llm_auto_validation_max_observations_per_review: asNumber(AT.dom.expAtAutoValidationMaxItems?.value, 4),
        llm_auto_validation_review_every_run: Boolean(AT.dom.expAtAutoValidationEveryRunChk?.checked),
        metric_targets: collectMetricTargets(),
      };
      const res = await apiPost("/api/experiment/auto_tuner/config/save", { config: payload });
      STATE.autoTunerConfig = res.data || null;
      renderMetricTargets();
      renderOverview();
      feedback("expAtConfigFeedback", "已保存调参器配置。", "ok");
    } catch (error) {
      feedback("expAtConfigFeedback", `保存失败：${error.message}`, "err");
    }
  }

  const refreshAutoTunerConfigBase = refreshAutoTunerConfig;
  refreshAutoTunerConfig = async function refreshAutoTunerConfigWithRunSync(options = {}) {
    await refreshAutoTunerConfigBase(options);
    const cfg = STATE.autoTunerConfig?.config || null;
    if (typeof window.syncRunAutoTunerDefaultsFromConfig === "function") {
      window.syncRunAutoTunerDefaultsFromConfig(cfg);
    }
  };

  const saveAutoTunerConfigBase = saveAutoTunerConfig;
  saveAutoTunerConfig = async function saveAutoTunerConfigWithRunSync() {
    await saveAutoTunerConfigBase();
    const cfg = STATE.autoTunerConfig?.config || null;
    if (typeof window.syncRunAutoTunerDefaultsFromConfig === "function") {
      window.syncRunAutoTunerDefaultsFromConfig(cfg);
    }
  };

  document.addEventListener("DOMContentLoaded", async () => {
    [
      "expAutoTunerOverviewCards",
      "expAtMetricInsightCards",
      "expAtMetricInsightNarrative",
      "expAtConfigMeta",
      "expAtEnabledChk",
      "expAtShortChk",
      "expAtLongChk",
      "expAtLlmAssistChk",
      "expAtShortWindow",
      "expAtLongWindow",
      "expAtCooldown",
      "expAtMaxUpdates",
      "expAtConfigSaveBtn",
      "expAtRefreshBtn",
      "expAtConfigFeedback",
      "expAtMetricTargets",
      "expAtParamSearch",
      "expAtParamCatalog",
      "expAtRulesSaveBtn",
      "expAtRuleSummary",
      "expAtRuleCatalog",
      "expAtCustomRulesEditor",
      "expAtStateSummary",
      "expAtAuditLog",
      "expAtRollbackList",
      "expAtLlmMeta",
      "expAtLlmEnabledChk",
      "expAtLlmAutoChk",
      "expAtLlmBaseUrl",
      "expAtLlmApiKey",
      "expAtLlmModel",
      "expAtLlmMaxPromptChars",
      "expAtLlmSaveBtn",
      "expAtLlmFeedback",
      "expAtLlmPrompt",
      "expAtLlmAnalyzeBtn",
      "expAtLlmJobsRefreshBtn",
      "expAtLlmAnalyzeFeedback",
      "expAtLlmJobs",
      "expAtLlmReport",
      "expAtLlmSuggestionList",
    ].forEach((id) => {
      AT.dom[id] = q(id);
    });

    [
      "expAtAutoValidationChk",
      "expAtAutoValidationMinRuns",
      "expAtAutoValidationMaxItems",
      "expAtAutoValidationEveryRunChk",
      "expAtObservationSummary",
      "expAtObservationZone",
      "expAtObservationHistory",
      "expAtObservationReview",
    ].forEach((id) => {
      AT.dom[id] = q(id);
    });

    renamePageChrome();

    if (AT.dom.expAtConfigSaveBtn) AT.dom.expAtConfigSaveBtn.addEventListener("click", saveAutoTunerConfig);
    if (AT.dom.expAtRefreshBtn) AT.dom.expAtRefreshBtn.addEventListener("click", () => refreshAutoTunerAll());
    if (AT.dom.expAtRulesSaveBtn) AT.dom.expAtRulesSaveBtn.addEventListener("click", saveRules);
    if (AT.dom.expAtLlmSaveBtn) AT.dom.expAtLlmSaveBtn.addEventListener("click", saveLlmConfig);
    if (AT.dom.expAtLlmAnalyzeBtn) AT.dom.expAtLlmAnalyzeBtn.addEventListener("click", startLlmAnalyze);
    if (AT.dom.expAtLlmJobsRefreshBtn) AT.dom.expAtLlmJobsRefreshBtn.addEventListener("click", () => refreshAutoTunerLlmJobs());
    if (AT.dom.expAtParamSearch) AT.dom.expAtParamSearch.addEventListener("input", () => renderParamCatalog());

    window.renderAutoTunerMetricInsights = renderAutoTunerMetricInsights;

    try {
      await refreshAutoTunerAll({ silent: true });
      feedback("expAtConfigFeedback", "自适应调参器模块已加载。", "ok");
    } catch (error) {
      feedback("expAtConfigFeedback", `加载失败：${error.message}`, "err");
    }
  });
})();
