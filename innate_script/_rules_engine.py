# -*- coding: utf-8 -*-
"""
AP 先天规则引擎（先天编码脚本管理器 IESM 的规则引擎）
===================================================

目标（原型阶段）
--------------
1) 声明式规则（Declarative Rules）
   - 规则是纯数据（YAML），不允许执行 Python 代码（安全、可审计）。

2) 可审计、可热加载（Auditable & Reloadable）
   - 校验 -> 保存（自动备份）-> 热加载 -> 执行。

3) 原型优先（MVP First）
   - 先提供少量但可扩展的谓词与动作，保证闭环可跑、可观测、可验证。

当前支持（MVP）
-------------
when（触发条件）谓词：
  - any / all / not（任一/同时/取反）
  - cfs：kinds + min_strength / max_strength（认知感受信号）
  - state_window：stage + fast_cp_rise_min / fast_cp_drop_min / min_candidate_count / candidate_hint_any（状态窗口）
  - timer：every_n_ticks / at_tick（定时器）
  - metric：统一数值指标条件（状态池/对象能量/情绪递质/奖励惩罚/查存过程指标）
    - 通过 preset 或 metric 字段指定要比较的指标
    - 支持 mode=state/delta/avg_rate（状态/变化量/近 N tick 平均变化率）

then（动作）动作：
  - cfs_emit：生成/扩展 CFS（认知感受信号）列表（供同 tick 后续规则/EMgr/行动模块消费）
  - focus：from cfs_matches / state_window_candidates（注意力聚焦指令）
  - emit_script：产出 triggered_scripts（用于观测/联调）
  - emotion_update：产出递质通道增量（先展示，后续接入行动/学习）
  - action_trigger：结构化行动触发输出（先展示，后续由行动模块执行）
  - log：追加审计日志
  - pool_energy：输出“状态池能量更新”效果（由观测台应用到 StatePool）
  - pool_bind_attribute：输出“属性刺激元绑定”效果（由观测台应用到 StatePool）
  - delay：延时调度一组动作（在 rules runtime_state 内部记账）
  - branch：分支动作（if/else/on_error），用于“条件不满足/报错”分支

规则阶段（phase）/ Rule phase
---------------------------
为了更贴合理论 3.10 的“CFS 脚本 + 先天行动触发脚本”的分层，本引擎支持按规则阶段排序执行：
  - phase: cfs（先执行，负责生成认知感受信号）
  - phase: directives（后执行，负责输出 focus/emotion_update/action_trigger/pool_effect 等指令）
  - phase: emotion_post（可选后置阶段，供“同 tick 池内状态汇总后”再做一次递质调制）

注意：
  - 默认 phase 为 directives。
  - 引擎会按 (phase -> priority) 排序，而不是完全依赖 YAML 文件书写顺序。
"""

from __future__ import annotations

import copy
import os
import re
import time
from pathlib import Path
from typing import Any


try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


RULES_SCHEMA_VERSION = "1.0"

# Rule id should be stable for auditing and UI references.
# 规则 id 需要稳定，用于审计与前端引用。
RULE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,80}$")
_EMOTION_UPDATE_META_KEYS = {"from", "match_policy", "max_updates", "max_matches", "channels"}
_SELECTOR_CACHE_KEY = "_iesm_selector_cache"
_SELECTOR_CACHE_STATS_KEY = "_iesm_selector_cache_stats"


DEFAULT_DOC: dict[str, Any] = {
    "rules_schema_version": RULES_SCHEMA_VERSION,
    "rules_version": "0.0",
    "enabled": True,
    "defaults": {
        "focus_directive": {
            "ttl_ticks": 2,
            "focus_boost": 0.9,
            "deduplicate_by": "target_ref_object_id",
            "max_directives_per_rule": 8,
        },
        "habituation": {
            "enabled": True,
            "window_ticks": 10,
            "start_total": 6.0,
            "full_total": 18.0,
            "min_scale": 0.0,
        },
    },
    "rules": [],
}


# ======================================================================
# IO / 输入输出（加载/保存/备份）
# ======================================================================


def load_rules_yaml(path: str) -> tuple[dict[str, Any] | None, str | None]:
    """Load rules YAML from disk / 从磁盘加载规则 YAML。"""
    if not path:
        return None, "rules_path is empty"
    p = Path(path)
    if not p.exists():
        return None, f"rules file not found: {path}"
    try:
        raw_text = p.read_text(encoding="utf-8")
        if yaml is not None:
            data = yaml.safe_load(raw_text)
            if not isinstance(data, dict):
                return None, "rules file must be a YAML mapping (dict)"
            return data, None

        # Fallback when PyYAML is not installed:
        # - Accept JSON (YAML 1.2 is a superset of JSON).
        # - Strip comment lines starting with '#', so a header comment won't break JSON parsing.
        #
        # 当环境缺少 PyYAML 时的降级策略：
        # - 允许规则文件为 JSON（YAML 1.2 超集包含 JSON）。
        # - 先剥离以 '#' 开头的注释行，避免头部注释导致 JSON 解析失败。
        import json

        body_lines = [line for line in raw_text.splitlines() if not line.lstrip().startswith("#")]
        body = "\n".join(body_lines).strip()
        if not body:
            return {}, None
        try:
            data = json.loads(body)
        except Exception as exc:
            return None, f"PyYAML not available; JSON fallback parse failed: {exc}"
        if not isinstance(data, dict):
            return None, "rules file must be a mapping/dict (JSON fallback)"
        return data, None
    except Exception as exc:
        return None, f"failed to load rules yaml: {exc}"


def dump_rules_yaml(doc: dict[str, Any]) -> str:
    """Dump normalized rules doc to YAML text / 输出 YAML 文本。"""
    # Prefer YAML when PyYAML is installed.
    # 若可用则优先输出 YAML（更利于人类编辑）。
    if yaml is not None:
        text = yaml.safe_dump(
            doc,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )
        return text.rstrip() + "\n"

    # JSON fallback (also valid YAML 1.2).
    # JSON 降级输出（同时也是合法 YAML 1.2），保证系统在缺少 PyYAML 时仍可运行。
    import json

    return json.dumps(doc, ensure_ascii=False, indent=2).rstrip() + "\n"


def render_rules_file(doc: dict[str, Any]) -> str:
    """Render the rules file content (header + yaml) / 生成规则文件内容（含头部注释）。"""
    header = [
        "# ======================================================================",
        "# AP Innate Rules (IESM Rules)",
        "# AP 先天规则（先天编码脚本管理器 IESM 的规则文件）",
        "#",
        "# This file is generated/updated by the Observatory UI or tools.",
        "# 本文件可由观测台前端或工具生成/更新。",
        "#",
        "# Quick Start / 快速开始：",
        "# 1) 运行 `python -m observatory` 启动观测台",
        "# 2) 打开浏览器侧边栏「先天规则 / Innate Rules」",
        "# 3) 校验 / Validate -> 保存并热加载 / Save + Reload",
        "# 4) 用最近一轮模拟 / Simulate 查看触发结果",
        "#",
        "# Schema / 结构提示：",
        "# - Top-level: rules_schema_version, rules_version, enabled, defaults, rules",
        "# - Rule item: id, title, enabled, phase, priority, cooldown_ticks, when, then, note",
        "# - Optional: ui (editor metadata, ignored by the engine)",
        "#   可选：ui（编辑器元信息，规则引擎会忽略）",
        "# - when supports: any/all/not + cfs/state_window/timer",
        "# - then supports: cfs_emit/focus/emit_script/emotion_update/action_trigger/pool_energy/pool_bind_attribute/delay/branch/log",
        "#",
        "# Tips / 提示：",
        "# - Keep rule ids stable for auditing.",
        "#   规则 id 请保持稳定，便于审计与回滚。",
        "# - Rules are pure data, no Python code execution.",
        "#   规则是纯数据，不执行 Python 代码。",
        "# ======================================================================",
        "",
    ]
    return "\n".join(header) + dump_rules_yaml(doc)


def ensure_parent_dir(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def rotate_backups(*, source_path: str, backup_dir: str, keep: int = 20) -> tuple[bool, str]:
    """
    Backup current rules file into backup_dir and keep last N.
    备份当前规则文件到 backup_dir，并保留最近 N 份。
    """
    try:
        src = Path(source_path)
        if not src.exists():
            return True, "no source to backup"
        if not backup_dir:
            return True, "backup_dir is empty"
        bd = Path(backup_dir)
        bd.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        target = bd / f"{src.stem}_{ts}{src.suffix}"
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        keep = max(1, int(keep))
        pattern = f"{src.stem}_*{src.suffix}"
        backups = [p for p in bd.glob(pattern) if p.is_file()]
        backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[keep:]:
            try:
                old.unlink()
            except OSError:
                pass
        return True, f"backup created: {target.name}"
    except Exception as exc:
        return False, f"backup failed: {exc}"


def save_rules_file(*, path: str, doc: dict[str, Any], backup_dir: str, backup_keep: int) -> tuple[bool, str]:
    """Save rules file with backup / 保存规则文件（带备份）。"""
    ensure_parent_dir(path)
    ok, msg = rotate_backups(source_path=path, backup_dir=backup_dir, keep=backup_keep)
    if not ok:
        return False, msg
    Path(path).write_text(render_rules_file(doc), encoding="utf-8")
    return True, msg


def default_rules_path(module_dir: str) -> str:
    return os.path.join(module_dir, "config", "innate_rules.yaml")


def default_backup_dir(module_dir: str) -> str:
    return os.path.join(module_dir, "config", "rules_history")


# ======================================================================
# Validation & normalization / 校验与规范化
# ======================================================================


def normalize_rules_doc(raw: dict[str, Any] | None) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Normalize and validate rules doc.
    规则文件规范化与校验。

    Returns:
      (normalized_doc, errors, warnings)
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    base = copy.deepcopy(DEFAULT_DOC)
    if not raw:
        warnings.append(_warn("$", "empty rules doc, using defaults", "规则文件为空，已使用默认结构"))
        return base, errors, warnings
    if not isinstance(raw, dict):
        errors.append(_err("$", "rules doc must be a dict", "规则文件顶层必须是 dict"))
        return base, errors, warnings

    for key in raw.keys():
        if key not in base:
            warnings.append(_warn(f"$.{key}", f"unknown top-level key: {key}", f"未知顶层字段：{key}"))

    schema = str(raw.get("rules_schema_version", base["rules_schema_version"]) or "").strip()
    base["rules_schema_version"] = schema or RULES_SCHEMA_VERSION
    if base["rules_schema_version"] != RULES_SCHEMA_VERSION:
        warnings.append(
            _warn(
                "$.rules_schema_version",
                f"schema mismatch: expected {RULES_SCHEMA_VERSION}, got {base['rules_schema_version']}",
                f"结构版本不匹配：期望 {RULES_SCHEMA_VERSION}，实际 {base['rules_schema_version']}",
            )
        )

    base["rules_version"] = str(raw.get("rules_version", base["rules_version"]) or "0.0").strip() or "0.0"
    base["enabled"] = bool(raw.get("enabled", base["enabled"]))

    defaults = raw.get("defaults", base.get("defaults"))
    if isinstance(defaults, dict):
        base["defaults"] = copy.deepcopy(defaults)
    else:
        warnings.append(_warn("$.defaults", "defaults should be a dict", "defaults 应为 dict"))

    rules_raw = raw.get("rules", [])
    if not isinstance(rules_raw, list):
        errors.append(_err("$.rules", "rules must be a list", "rules 必须是 list"))
        rules_raw = []

    normalized_rules: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(rules_raw):
        rule_path = f"$.rules[{idx}]"
        if not isinstance(item, dict):
            errors.append(_err(rule_path, "rule must be a dict", "单条规则必须是 dict"))
            continue
        nr, r_errors, r_warnings = _normalize_rule(item, rule_path=rule_path)
        errors.extend(r_errors)
        warnings.extend(r_warnings)
        rid = str(nr.get("id", "") or "")
        if rid:
            if rid in seen_ids:
                errors.append(_err(f"{rule_path}.id", f"duplicate rule id: {rid}", f"规则 id 重复：{rid}"))
            seen_ids.add(rid)
        normalized_rules.append(nr)

    base["rules"] = normalized_rules
    return base, errors, warnings


def _normalize_rule(raw_rule: dict[str, Any], *, rule_path: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    # "ui" is reserved for editor metadata (graph layout, etc.). It is ignored by the engine.
    # "ui" 字段用于前端编辑器元信息（例如图形布局），规则引擎会忽略它。
    # "habituation" is rule-local habituation/attenuation config (optional).
    # "habituation" 是规则级“习惯化/疲劳衰减”配置（可选）。
    allowed = {"id", "title", "enabled", "phase", "priority", "cooldown_ticks", "when", "then", "note", "ui", "habituation"}
    for key in raw_rule.keys():
        if key not in allowed:
            warnings.append(_warn(f"{rule_path}.{key}", f"unknown rule key: {key}", f"未知规则字段：{key}"))

    rid = str(raw_rule.get("id", "") or "").strip()
    if not rid:
        errors.append(_err(f"{rule_path}.id", "rule id is required", "规则 id 必填"))
        rid = f"rule_{int(time.time())}"
    elif not RULE_ID_PATTERN.match(rid):
        warnings.append(
            _warn(
                f"{rule_path}.id",
                f"rule id format not recommended: {rid}",
                f"规则 id 格式不推荐：{rid}（建议 a-z 开头，仅含 a-z0-9_）",
            )
        )

    title = str(raw_rule.get("title", "") or "").strip()
    enabled = bool(raw_rule.get("enabled", True))

    # phase / 阶段：用于控制规则执行顺序（cfs -> directives -> emotion_post）
    phase = str(raw_rule.get("phase", "directives") or "directives").strip() or "directives"
    allowed_phases = {"cfs", "directives", "emotion_post"}
    if phase not in allowed_phases:
        warnings.append(
            _warn(
                f"{rule_path}.phase",
                f"unknown phase: {phase}",
                f"未知 phase：{phase}（建议 cfs / directives / emotion_post；已回退为 directives）",
            )
        )
        phase = "directives"
    priority = _as_int(raw_rule.get("priority", 50), default=50, errors=errors, path=f"{rule_path}.priority")
    cooldown = _as_int(raw_rule.get("cooldown_ticks", 0), default=0, errors=errors, path=f"{rule_path}.cooldown_ticks")
    note = str(raw_rule.get("note", "") or "").strip()

    ui_raw = raw_rule.get("ui")
    ui: dict[str, Any] | None = None
    if ui_raw is not None:
        if isinstance(ui_raw, dict):
            # Avoid persisting empty ui blocks to keep YAML readable.
            # 空 ui 不写回，保持 YAML 可读性。
            ui = copy.deepcopy(ui_raw) if ui_raw else None
        else:
            warnings.append(_warn(f"{rule_path}.ui", "ui should be a dict", "ui 应为 dict"))

    when_norm, w_errors, w_warnings = normalize_when(raw_rule.get("when"), path=f"{rule_path}.when")
    errors.extend(w_errors)
    warnings.extend(w_warnings)

    then_norm, a_errors, a_warnings = normalize_actions(raw_rule.get("then"), path=f"{rule_path}.then")
    errors.extend(a_errors)
    warnings.extend(a_warnings)

    hab_raw = raw_rule.get("habituation")
    hab: dict[str, Any] | None = None
    if hab_raw is not None:
        if isinstance(hab_raw, dict):
            hab = copy.deepcopy(hab_raw) if hab_raw else None
        else:
            warnings.append(_warn(f"{rule_path}.habituation", "habituation should be a dict", "habituation 应为 dict"))

    normalized: dict[str, Any] = {
        "id": rid,
        "title": title,
        "enabled": enabled,
        "phase": phase,
        "priority": int(priority),
        "cooldown_ticks": int(max(0, cooldown)),
        "when": when_norm,
        "then": then_norm,
        "note": note,
    }
    if ui is not None:
        normalized["ui"] = ui
    if hab is not None:
        normalized["habituation"] = hab

    return (normalized, errors, warnings)


def normalize_when(raw: Any, *, path: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Normalize when-expression / 规范化 when 表达式。

    Supported / 支持：
    - {"any": [<when>, ...]}
    - {"all": [<when>, ...]}
    - {"not": <when>}
    - {"cfs": {...}}
    - {"state_window": {...}}
    - {"timer": {...}}
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if raw is None:
        errors.append(_err(path, "when is required", "when 必填"))
        return {"timer": {"every_n_ticks": 999999}}, errors, warnings
    if not isinstance(raw, dict):
        errors.append(_err(path, "when must be a dict", "when 必须是 dict"))
        return {"timer": {"every_n_ticks": 999999}}, errors, warnings
    if not raw:
        errors.append(_err(path, "when is empty", "when 为空"))
        return {"timer": {"every_n_ticks": 999999}}, errors, warnings

    keys = [k for k in raw.keys() if isinstance(k, str)]
    if len(keys) != 1:
        warnings.append(_warn(path, f"when should have 1 root key, got {keys}", f"when 建议只有 1 个根键：当前 {keys}"))
    key = keys[0]
    val = raw.get(key)

    if key in {"any", "all"}:
        if not isinstance(val, list):
            errors.append(_err(f"{path}.{key}", f"{key} must be a list", f"{key} 必须是 list"))
            return {key: []}, errors, warnings
        children = []
        for idx, child in enumerate(val):
            cn, ce, cw = normalize_when(child, path=f"{path}.{key}[{idx}]")
            errors.extend(ce)
            warnings.extend(cw)
            children.append(cn)
        return {key: children}, errors, warnings

    if key == "not":
        cn, ce, cw = normalize_when(val, path=f"{path}.not")
        errors.extend(ce)
        warnings.extend(cw)
        return {"not": cn}, errors, warnings

    if key == "cfs":
        if not isinstance(val, dict):
            errors.append(_err(f"{path}.cfs", "cfs must be a dict", "cfs 必须是 dict"))
            return {"cfs": {}}, errors, warnings
        norm: dict[str, Any] = {}
        kinds = val.get("kinds")
        if kinds is not None:
            if isinstance(kinds, list):
                norm["kinds"] = [str(x) for x in kinds if str(x)]
            else:
                warnings.append(_warn(f"{path}.cfs.kinds", "kinds should be a list", "kinds 应为 list"))
        if "min_strength" in val:
            norm["min_strength"] = _as_float(val.get("min_strength"), default=0.0, errors=errors, path=f"{path}.cfs.min_strength")
        if "max_strength" in val:
            norm["max_strength"] = _as_float(val.get("max_strength"), default=1.0, errors=errors, path=f"{path}.cfs.max_strength")
        return {"cfs": norm}, errors, warnings

    if key == "state_window":
        if not isinstance(val, dict):
            errors.append(_err(f"{path}.state_window", "state_window must be a dict", "state_window 必须是 dict"))
            return {"state_window": {}}, errors, warnings
        norm: dict[str, Any] = {}
        stage = val.get("stage")
        if stage is not None:
            if isinstance(stage, str):
                norm["stage"] = stage.strip() or "any"
            elif isinstance(stage, list):
                norm["stage"] = [str(x).strip() for x in stage if str(x).strip()]
            else:
                warnings.append(_warn(f"{path}.state_window.stage", "stage should be string or list", "stage 应为 string 或 list"))
        if "fast_cp_rise_min" in val:
            norm["fast_cp_rise_min"] = _as_int(val.get("fast_cp_rise_min"), default=1, errors=errors, path=f"{path}.state_window.fast_cp_rise_min")
        if "fast_cp_drop_min" in val:
            norm["fast_cp_drop_min"] = _as_int(val.get("fast_cp_drop_min"), default=1, errors=errors, path=f"{path}.state_window.fast_cp_drop_min")
        if "min_candidate_count" in val:
            norm["min_candidate_count"] = _as_int(val.get("min_candidate_count"), default=0, errors=errors, path=f"{path}.state_window.min_candidate_count")
        if "candidate_hint_any" in val:
            hints = val.get("candidate_hint_any")
            if isinstance(hints, list):
                norm["candidate_hint_any"] = [str(x) for x in hints if str(x)]
            else:
                warnings.append(_warn(f"{path}.state_window.candidate_hint_any", "candidate_hint_any should be list", "candidate_hint_any 应为 list"))
        return {"state_window": norm}, errors, warnings

    if key == "metric":
        if not isinstance(val, dict):
            errors.append(_err(f"{path}.metric", "metric must be a dict", "metric 必须是 dict"))
            return {"metric": {}}, errors, warnings
        norm, me, mw = _normalize_metric_spec(val, path=f"{path}.metric")
        errors.extend(me)
        warnings.extend(mw)
        return {"metric": norm}, errors, warnings

    if key == "timer":
        if not isinstance(val, dict):
            errors.append(_err(f"{path}.timer", "timer must be a dict", "timer 必须是 dict"))
            return {"timer": {}}, errors, warnings
        norm: dict[str, Any] = {}
        if "every_n_ticks" in val:
            norm["every_n_ticks"] = _as_int(val.get("every_n_ticks"), default=1, errors=errors, path=f"{path}.timer.every_n_ticks")
        if "at_tick" in val:
            norm["at_tick"] = _as_int(val.get("at_tick"), default=0, errors=errors, path=f"{path}.timer.at_tick")
        return {"timer": norm}, errors, warnings

    warnings.append(_warn(path, f"unknown when root key: {key}", f"未知 when 根键：{key}"))
    return {"timer": {"every_n_ticks": 999999}}, errors, warnings


def _normalize_metric_spec(raw: dict[str, Any], *, path: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Normalize metric spec.
    规范化 metric（指标条件）配置。

    核心字段（原型阶段，保持可扩展）：
      - preset: 预设指标名（中文 UI 可用），例如 got_er / pool_er_total / nt_state 等
      - metric: 指标路径，例如 item.er / pool.total_er / emotion.nt.DA / stimulus.residual_ratio
      - channel: 参数字段（用于 nt_* 这类带通道参数的预设），例如 channel: "DA" / "多巴胺"
      - mode: state/prev_state/delta/avg_rate（状态/上一 tick 状态/变化量/近 N tick 平均变化率）
      - op: 比较操作符：>=, >, <=, <, ==, !=, between, exists, changed
      - value/min/max: 阈值
      - window_ticks: avg_rate 使用的窗口 tick 数（例如 3~4）
      - selector: 对象选择器（用于 item.* 指标）：
          mode: all/specific_ref/specific_item/contains_text/top_n
          ref_object_id/ref_object_type/item_id/contains_text/top_n/ref_object_types 等
      - capture_as: 变量名（用于动作模板 {{{var}}}）
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    allowed = {
        "preset",
        "metric",
        "channel",
        "mode",
        "op",
        "value",
        "min",
        "max",
        "prev_gate",
        "window_ticks",
        "selector",
        "match_policy",
        "capture_as",
        "epsilon",
        "note",
    }
    for k in raw.keys():
        if k not in allowed:
            warnings.append(_warn(f"{path}.{k}", f"unknown metric field: {k}", f"未知 metric 字段：{k}"))

    preset = resolve_metric_preset_name(str(raw.get("preset", "") or ""))
    metric = str(raw.get("metric", "") or "").strip()
    # channel：用于 emotion.nt.{channel} 这类“带参数”的预设（例如 nt_state/nt_rate）。
    # - 通道名可以是缩写（DA/ADR/...）或中文名（多巴胺/皮质醇...）。
    channel = str(raw.get("channel", "") or "").strip()
    mode = str(raw.get("mode", "state") or "state").strip()
    op = str(raw.get("op", ">=") or ">=").strip()
    match_policy = str(raw.get("match_policy", "any") or "any").strip()
    capture_as = str(raw.get("capture_as", "") or "").strip()

    # window_ticks: only meaningful for avg_rate
    window_ticks = _as_int(raw.get("window_ticks", 4), default=4, errors=errors, path=f"{path}.window_ticks")
    window_ticks = max(1, int(window_ticks))

    epsilon = _as_float(raw.get("epsilon", 1e-9), default=1e-9, errors=errors, path=f"{path}.epsilon")
    epsilon = max(0.0, float(epsilon))

    selector_raw = raw.get("selector")
    selector: dict[str, Any] | None = None
    if selector_raw is not None:
        if isinstance(selector_raw, dict):
            selector = copy.deepcopy(selector_raw)
        else:
            warnings.append(_warn(f"{path}.selector", "selector should be a dict", "selector 应为 dict"))

    # value/min/max can be number or template string; keep as-is, runtime will coerce.
    value = raw.get("value")
    vmin = raw.get("min")
    vmax = raw.get("max")

    # prev_gate: optional extra constraint on previous tick value (same metric series).
    # prev_gate：可选，对“上一 tick 的指标值”再加一个条件约束（用于表达正确事件等硬约束）。
    prev_gate_raw = raw.get("prev_gate")
    prev_gate: dict[str, Any] | None = None
    if prev_gate_raw is not None:
        if isinstance(prev_gate_raw, dict):
            pg: dict[str, Any] = {}
            if "op" in prev_gate_raw:
                pg_op = str(prev_gate_raw.get("op", ">=") or ">=").strip()
                pg_op_alias = {"ge": ">=", "gt": ">", "le": "<=", "lt": "<", "eq": "==", "ne": "!="}
                pg["op"] = pg_op_alias.get(pg_op, pg_op)
            else:
                pg["op"] = ">="
            if "value" in prev_gate_raw:
                pg["value"] = prev_gate_raw.get("value")
            if "min" in prev_gate_raw:
                pg["min"] = prev_gate_raw.get("min")
            if "max" in prev_gate_raw:
                pg["max"] = prev_gate_raw.get("max")
            prev_gate = pg
        else:
            warnings.append(_warn(f"{path}.prev_gate", "prev_gate should be a dict", "prev_gate 应为 dict"))

    if not preset and not metric:
        errors.append(_err(path, "metric.preset or metric.metric is required", "metric.preset 或 metric.metric 至少一个必填"))

    if mode not in {"state", "prev_state", "delta", "avg_rate"}:
        warnings.append(_warn(f"{path}.mode", f"unknown mode: {mode}", f"未知 mode：{mode}（建议 state/prev_state/delta/avg_rate）"))

    if match_policy not in {"any", "all"}:
        warnings.append(_warn(f"{path}.match_policy", f"unknown match_policy: {match_policy}", f"未知 match_policy：{match_policy}（建议 any/all）"))

    # Normalize common operator aliases.
    # 归一化常见操作符别名。
    op_alias = {"ge": ">=", "gt": ">", "le": "<=", "lt": "<", "eq": "==", "ne": "!="}
    op = op_alias.get(op, op)

    return (
        {
            "preset": preset,
            "metric": metric,
            "channel": channel,
            "mode": mode,
            "op": op,
            "match_policy": match_policy,
            "value": value,
            "min": vmin,
            "max": vmax,
            "prev_gate": prev_gate,
            "window_ticks": int(window_ticks),
            "selector": selector,
            "capture_as": capture_as,
            "epsilon": float(epsilon),
            "note": str(raw.get("note", "") or "").strip(),
        },
        errors,
        warnings,
    )


def normalize_actions(raw: Any, *, path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize then-actions list / 规范化 then 动作列表。"""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if raw is None:
        errors.append(_err(path, "then is required", "then 必填"))
        return [], errors, warnings
    if not isinstance(raw, list):
        errors.append(_err(path, "then must be a list", "then 必须是 list"))
        return [], errors, warnings

    actions: list[dict[str, Any]] = []
    for idx, item in enumerate(raw):
        item_path = f"{path}[{idx}]"
        if not isinstance(item, dict):
            errors.append(_err(item_path, "action must be a dict", "动作必须是 dict"))
            continue
        keys = [k for k in item.keys() if isinstance(k, str)]
        if not keys:
            errors.append(_err(item_path, "action is empty", "动作为空"))
            continue
        if len(keys) != 1:
            warnings.append(_warn(item_path, f"action should have 1 root key, got {keys}", f"动作建议只有 1 个根键：当前 {keys}"))
        key = keys[0]
        val = item.get(key)

        if key == "focus":
            if not isinstance(val, dict):
                errors.append(_err(f"{item_path}.focus", "focus must be a dict", "focus 必须是 dict"))
                actions.append({"focus": {}})
                continue
            norm: dict[str, Any] = {
                "from": str(val.get("from", "cfs_matches") or "cfs_matches"),
                "match_policy": str(val.get("match_policy", "all") or "all"),
            }
            if "ttl_ticks" in val:
                norm["ttl_ticks"] = _as_int(val.get("ttl_ticks"), default=2, errors=errors, path=f"{item_path}.focus.ttl_ticks")
            if "focus_boost" in val:
                norm["focus_boost"] = _as_float(val.get("focus_boost"), default=0.9, errors=errors, path=f"{item_path}.focus.focus_boost")
            if "deduplicate_by" in val:
                norm["deduplicate_by"] = str(val.get("deduplicate_by") or "")
            if "max_directives" in val:
                norm["max_directives"] = _as_int(val.get("max_directives"), default=0, errors=errors, path=f"{item_path}.focus.max_directives")
            actions.append({"focus": norm})
            continue

        if key == "emit_script":
            if not isinstance(val, dict):
                errors.append(_err(f"{item_path}.emit_script", "emit_script must be a dict", "emit_script 必须是 dict"))
                actions.append({"emit_script": {}})
                continue
            norm = {
                "script_id": str(val.get("script_id", "") or "").strip(),
                "script_kind": str(val.get("script_kind", "custom") or "custom").strip(),
                "priority": _as_int(val.get("priority", 50), default=50, errors=errors, path=f"{item_path}.emit_script.priority"),
                "trigger": str(val.get("trigger", "") or "").strip(),
            }
            if not norm["script_id"]:
                warnings.append(_warn(f"{item_path}.emit_script.script_id", "script_id is empty", "script_id 为空"))
            actions.append({"emit_script": norm})
            continue

        if key == "emotion_update":
            if not isinstance(val, dict):
                errors.append(_err(f"{item_path}.emotion_update", "emotion_update must be a dict", "emotion_update 必须是 dict"))
                actions.append({"emotion_update": {}})
                continue
            # NOTE:
            # - 原型阶段允许 value 为模板字符串（例如 "{{{match_value}}}"），因此这里不强制转 float。
            # - 真实转数值发生在执行阶段（模板先渲染，再 _coerce_float_maybe）。
            # 说明：
            # - 通道名可用缩写（DA/ADR/...）或中文名（多巴胺/皮质醇...）；最终由 EMgr 做归一化与应用。
            payload = copy.deepcopy(val)
            channel_payload = payload.get("channels") if isinstance(payload.get("channels"), dict) else None
            if channel_payload is None:
                if any(str(k) in _EMOTION_UPDATE_META_KEYS for k in payload.keys()):
                    channel_payload = {str(k): v for k, v in payload.items() if str(k) not in _EMOTION_UPDATE_META_KEYS}
                else:
                    channel_payload = payload
            for ch, delta in (channel_payload or {}).items():
                if not str(ch):
                    continue
                # Best-effort warn for obviously invalid values (not a number, not a template).
                # 尽力给出提示：若既不是数值也不像模板，则给 warning。
                if isinstance(delta, str):
                    s = delta.strip()
                    if s.startswith("{{{") and s.endswith("}}}"):
                        continue
                elif isinstance(delta, dict):
                    continue
                if _coerce_float_maybe(delta) is None:
                    warnings.append(_warn(f"{item_path}.emotion_update.{ch}", "delta should be float or template", "delta 建议为浮点数或模板字符串"))
            actions.append({"emotion_update": payload})
            continue

        if key == "action_trigger":
            if not isinstance(val, dict):
                errors.append(_err(f"{item_path}.action_trigger", "action_trigger must be a dict", "action_trigger 必须是 dict"))
                actions.append({"action_trigger": {}})
                continue
            actions.append({"action_trigger": copy.deepcopy(val)})
            continue

        if key == "cfs_emit":
            if not isinstance(val, dict):
                errors.append(_err(f"{item_path}.cfs_emit", "cfs_emit must be a dict", "cfs_emit 必须是 dict"))
                actions.append({"cfs_emit": {}})
                continue
            actions.append({"cfs_emit": copy.deepcopy(val)})
            continue

        if key == "pool_energy":
            # NOTE: numeric fields may be templates (e.g. "{{{var}}}"), so we do not coerce here.
            # 注意：数值字段可能是模板字符串（例如 "{{{var}}}"），因此校验阶段不强制转 float。
            if not isinstance(val, dict):
                errors.append(_err(f"{item_path}.pool_energy", "pool_energy must be a dict", "pool_energy 必须是 dict"))
                actions.append({"pool_energy": {}})
                continue
            actions.append({"pool_energy": copy.deepcopy(val)})
            continue

        if key == "pool_bind_attribute":
            if not isinstance(val, dict):
                errors.append(_err(f"{item_path}.pool_bind_attribute", "pool_bind_attribute must be a dict", "pool_bind_attribute 必须是 dict"))
                actions.append({"pool_bind_attribute": {}})
                continue
            actions.append({"pool_bind_attribute": copy.deepcopy(val)})
            continue

        if key == "delay":
            if not isinstance(val, dict):
                errors.append(_err(f"{item_path}.delay", "delay must be a dict", "delay 必须是 dict"))
                actions.append({"delay": {}})
                continue
            ticks = _as_int(val.get("ticks", 1), default=1, errors=errors, path=f"{item_path}.delay.ticks")
            ticks = max(1, int(ticks))
            then_raw = val.get("then", [])
            then_norm, te, tw = normalize_actions(then_raw, path=f"{item_path}.delay.then")
            errors.extend(te)
            warnings.extend(tw)
            actions.append({"delay": {"ticks": ticks, "then": then_norm}})
            continue

        if key == "branch":
            if not isinstance(val, dict):
                errors.append(_err(f"{item_path}.branch", "branch must be a dict", "branch 必须是 dict"))
                actions.append({"branch": {}})
                continue
            when_norm, we, ww = normalize_when(val.get("when"), path=f"{item_path}.branch.when")
            errors.extend(we)
            warnings.extend(ww)
            then_norm, te, tw = normalize_actions(val.get("then", []), path=f"{item_path}.branch.then")
            errors.extend(te)
            warnings.extend(tw)
            else_norm, ee, ew = normalize_actions(val.get("else", []), path=f"{item_path}.branch.else")
            errors.extend(ee)
            warnings.extend(ew)
            on_error_norm, oe, ow = normalize_actions(val.get("on_error", []), path=f"{item_path}.branch.on_error")
            errors.extend(oe)
            warnings.extend(ow)
            actions.append(
                {
                    "branch": {
                        "when": when_norm,
                        "then": then_norm,
                        "else": else_norm,
                        "on_error": on_error_norm,
                        "note": str(val.get("note", "") or "").strip(),
                    }
                }
            )
            continue

        if key == "log":
            actions.append({"log": str(val or "").strip()})
            continue

        warnings.append(_warn(item_path, f"unknown action type: {key}", f"未知动作类型：{key}"))
        actions.append({key: copy.deepcopy(val)})

    return actions, errors, warnings


def _as_int(value: Any, *, default: int, errors: list[dict[str, Any]], path: str) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError("bool is not int")
        if value is None or value == "":
            return int(default)
        return int(value)
    except Exception:
        errors.append(_err(path, f"invalid int: {value}", f"非法整数：{value}"))
        return int(default)


def _as_float(value: Any, *, default: float, errors: list[dict[str, Any]], path: str) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError("bool is not float")
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        errors.append(_err(path, f"invalid float: {value}", f"非法浮点数：{value}"))
        return float(default)


def _err(path: str, en: str, zh: str) -> dict[str, Any]:
    return {"level": "error", "path": path, "message_en": en, "message_zh": zh}


def _warn(path: str, en: str, zh: str) -> dict[str, Any]:
    return {"level": "warning", "path": path, "message_en": en, "message_zh": zh}


# ======================================================================
# Metric & Template Helpers / 指标与模板工具
# ======================================================================


# Metric presets / 指标预设
# ------------------------
# 说明：
# - preset 用于把“更偏中文口径”的条件名映射到 engine 内部稳定的 metric 路径与 mode。
# - UI 可以优先展示中文（例如“获得实能量”），而规则引擎仍保持统一实现。
#
# 命名约定（建议）:
# - 规则文件里优先使用“稳定英文键”（例如 got_er / pool_er_total），便于版本管理与跨语言协作。
# - 同时允许中文别名（例如 "__获得实能量__"），引擎会在 normalize 阶段归一化为稳定键。
_METRIC_PRESET_MAP: dict[str, dict[str, Any]] = {
    # ------------------------------------------------------------
    # Item-level presets (object metrics) / 对象级指标预设
    # ------------------------------------------------------------
    "got_er": {
        "metric": "item.er",
        "mode": "delta",
        "label_zh": "获得实能量（ER 变化量）",
        "label_en": "Got real energy (ER delta)",
        "group_zh": "对象能量（Item Energy）",
    },
    "got_ev": {
        "metric": "item.ev",
        "mode": "delta",
        "label_zh": "获得虚能量（EV 变化量）",
        "label_en": "Got virtual energy (EV delta)",
        "group_zh": "对象能量（Item Energy）",
    },
    "er_rate": {
        "metric": "item.er",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "实能量变化率（ER 近 N tick 平均）",
        "label_en": "ER avg rate (last N ticks)",
        "group_zh": "对象能量（Item Energy）",
    },
    "ev_rate": {
        "metric": "item.ev",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "虚能量变化率（EV 近 N tick 平均）",
        "label_en": "EV avg rate (last N ticks)",
        "group_zh": "对象能量（Item Energy）",
    },
    "er_state": {
        "metric": "item.er",
        "mode": "state",
        "label_zh": "实能量状态（ER 当前值）",
        "label_en": "ER state (current value)",
        "group_zh": "对象能量（Item Energy）",
    },
    "ev_state": {
        "metric": "item.ev",
        "mode": "state",
        "label_zh": "虚能量状态（EV 当前值）",
        "label_en": "EV state (current value)",
        "group_zh": "对象能量（Item Energy）",
    },
    "total_energy_state": {
        "metric": "item.total_energy",
        "mode": "state",
        "label_zh": "对象总能量状态（ER+EV 当前值）",
        "label_en": "Item total energy state (ER+EV)",
        "group_zh": "对象能量（Item Energy）",
    },
    "got_total_energy": {
        "metric": "item.total_energy",
        "mode": "delta",
        "label_zh": "获得总能量（ER+EV 变化量）",
        "label_en": "Got total energy (ER+EV delta)",
        "group_zh": "对象能量（Item Energy）",
    },
    "total_energy_rate": {
        "metric": "item.total_energy",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "总能量变化率（ER+EV 近 N tick 平均）",
        "label_en": "Total energy avg rate (last N ticks)",
        "group_zh": "对象能量（Item Energy）",
    },
    "cp_state": {
        "metric": "item.cp_delta",
        "mode": "state",
        "label_zh": "认知压状态（CP 带符号，ER-EV）",
        "label_en": "Cognitive pressure state (signed ER-EV)",
        "group_zh": "对象能量（Item Energy）",
    },
    "cp_abs_state": {
        "metric": "item.cp_abs",
        "mode": "state",
        "label_zh": "认知压大小状态（|CP|）",
        "label_en": "Cognitive pressure magnitude (abs)",
        "group_zh": "对象能量（Item Energy）",
    },
    "got_cp_abs": {
        "metric": "item.cp_abs",
        "mode": "delta",
        "label_zh": "获得认知压大小（|CP| 变化量）",
        "label_en": "Got |CP| (delta)",
        "group_zh": "对象能量（Item Energy）",
    },
    "got_cp": {
        "metric": "item.cp_delta",
        "mode": "delta",
        "label_zh": "获得认知压（CP 变化量，可正可负）",
        "label_en": "Got CP (delta, signed)",
        "group_zh": "对象能量（Item Energy）",
    },
    "cp_rate": {
        "metric": "item.cp_delta",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "认知压变化率（CP 近 N tick 平均）",
        "label_en": "CP avg rate (last N ticks)",
        "group_zh": "对象能量（Item Energy）",
    },
    "cp_abs_rate": {
        "metric": "item.cp_abs",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "认知压大小变化率（|CP| 近 N tick 平均）",
        "label_en": "|CP| avg rate (last N ticks)",
        "group_zh": "对象能量（Item Energy）",
    },
    "recency_state": {
        "metric": "item.recency_gain",
        "mode": "state",
        "label_zh": "近因增益状态（Recency Gain）",
        "label_en": "Recency gain state",
        "group_zh": "对象能量（Item Energy）",
    },
    "fatigue_state": {
        "metric": "item.fatigue",
        "mode": "state",
        "label_zh": "疲劳度状态（Fatigue）",
        "label_en": "Fatigue state",
        "group_zh": "对象能量（Item Energy）",
    },

    # ------------------------------------------------------------
    # Pool-level presets / 状态池级指标预设
    # ------------------------------------------------------------
    "pool_er_total": {
        "metric": "pool.total_er",
        "mode": "state",
        "label_zh": "状态池实能量总量（ΣER）",
        "label_en": "Pool total ER",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_ev_total": {
        "metric": "pool.total_ev",
        "mode": "state",
        "label_zh": "状态池虚能量总量（ΣEV）",
        "label_en": "Pool total EV",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_total_energy": {
        "metric": "pool.total_energy",
        "mode": "state",
        "label_zh": "状态池总能量（ΣER+ΣEV）",
        "label_en": "Pool total energy (ER+EV)",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_total_energy_got": {
        "metric": "pool.total_energy",
        "mode": "delta",
        "label_zh": "状态池获得总能量（ΣER+ΣEV 变化量）",
        "label_en": "Pool total energy delta",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_total_energy_rate": {
        "metric": "pool.total_energy",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "状态池总能量变化率（ΣER+ΣEV 近 N tick 平均）",
        "label_en": "Pool total energy avg rate",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_item_count": {
        "metric": "pool.item_count",
        "mode": "state",
        "label_zh": "状态池对象数量（SP item_count）",
        "label_en": "Pool item count",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_er_rate": {
        "metric": "pool.total_er",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "状态池实能量变化率（ΣER 近 N tick 平均）",
        "label_en": "Pool total ER avg rate",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_ev_rate": {
        "metric": "pool.total_ev",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "状态池虚能量变化率（ΣEV 近 N tick 平均）",
        "label_en": "Pool total EV avg rate",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_cp_rate": {
        "metric": "pool.total_cp_delta",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "状态池认知压变化率（ΣCP 近 N tick 平均，带符号）",
        "label_en": "Pool total CP avg rate (signed)",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_cp_abs_rate": {
        "metric": "pool.total_cp_abs",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "状态池认知压大小变化率（Σ|CP| 近 N tick 平均）",
        "label_en": "Pool total |CP| avg rate",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_concentration_rate": {
        "metric": "pool.energy_concentration",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "状态池能量聚集度变化率（Herfindahl 指数 近 N tick 平均）",
        "label_en": "Pool energy concentration avg rate",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_cp_total": {
        "metric": "pool.total_cp_delta",
        "mode": "state",
        "label_zh": "状态池认知压总量（ΣCP，带符号）",
        "label_en": "Pool total CP (signed)",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_cp_abs_total": {
        "metric": "pool.total_cp_abs",
        "mode": "state",
        "label_zh": "状态池认知压大小总量（Σ|CP|）",
        "label_en": "Pool total |CP|",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_concentration": {
        "metric": "pool.energy_concentration",
        "mode": "state",
        "label_zh": "状态池能量聚集度（Herfindahl 指数）",
        "label_en": "Pool energy concentration (Herfindahl index)",
        "group_zh": "状态池（StatePool / SP）",
    },
    "pool_effective_peak_count": {
        "metric": "pool.effective_peak_count",
        "mode": "state",
        "label_zh": "状态池有效波峰数量（≈1/聚集度）",
        "label_en": "Pool effective peak count (~1/HHI)",
        "group_zh": "状态池（StatePool / SP）",
    },
    "complexity_score": {
        "metric": "pool.complexity_score",
        "mode": "state",
        "label_zh": "繁/简综合复杂度（complexity_score，0~1）",
        "label_en": "Complexity score (0~1)",
        "group_zh": "全局指标（Global）",
    },
    "core_complexity_score": {
        "metric": "pool.core_complexity_score",
        "mode": "state",
        "label_zh": "核心繁/简复杂度（core_complexity_score，0~1）",
        "label_en": "Core complexity score (0~1)",
        "group_zh": "全局指标（Global）",
    },

    # ------------------------------------------------------------
    # CAM (Current Attention Memory) / 当前注意记忆体指标预设
    # ------------------------------------------------------------
    "cam_size": {
        "metric": "cam.size",
        "mode": "state",
        "label_zh": "当前注意记忆体大小（CAM 条目数）",
        "label_en": "CAM size (item count)",
        "group_zh": "注意力记忆体（CAM）",
    },
    "cam_concentration": {
        "metric": "cam.energy_concentration",
        "mode": "state",
        "label_zh": "CAM 能量聚集度（Herfindahl 指数）",
        "label_en": "CAM energy concentration (Herfindahl index)",
        "group_zh": "注意力记忆体（CAM）",
    },

    # ------------------------------------------------------------
    # Memory Activation Pool (MAP) / 记忆赋能池指标预设
    # ------------------------------------------------------------
    "map_item_count": {
        "metric": "memory_activation.item_count",
        "mode": "state",
        "label_zh": "记忆赋能池条目数（MAP item_count）",
        "label_en": "Memory activation item count (MAP)",
        "group_zh": "记忆赋能池（MAP）",
    },
    "map_total_ev": {
        "metric": "memory_activation.total_ev",
        "mode": "state",
        "label_zh": "记忆赋能池总虚能量（MAP ΣEV）",
        "label_en": "Memory activation total EV (MAP)",
        "group_zh": "记忆赋能池（MAP）",
    },

    # ------------------------------------------------------------
    # Reward / Punish (Rwd/Pun) / 奖励惩罚信号预设
    # ------------------------------------------------------------
    "reward_state": {
        "metric": "emotion.rwd",
        "mode": "state",
        "label_zh": "奖励信号状态（RWD 当前值）",
        "label_en": "Reward state (RWD)",
        "group_zh": "奖励/惩罚（Rwd/Pun）",
    },
    "punish_state": {
        "metric": "emotion.pun",
        "mode": "state",
        "label_zh": "惩罚信号状态（PUN 当前值）",
        "label_en": "Punish state (PUN)",
        "group_zh": "奖励/惩罚（Rwd/Pun）",
    },
    "reward_got": {
        "metric": "emotion.rwd",
        "mode": "delta",
        "label_zh": "奖励信号增加（RWD 变化量）",
        "label_en": "Reward delta (RWD)",
        "group_zh": "奖励/惩罚（Rwd/Pun）",
    },
    "punish_got": {
        "metric": "emotion.pun",
        "mode": "delta",
        "label_zh": "惩罚信号增加（PUN 变化量）",
        "label_en": "Punish delta (PUN)",
        "group_zh": "奖励/惩罚（Rwd/Pun）",
    },
    "reward_rate": {
        "metric": "emotion.rwd",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "奖励信号变化率（RWD 近 N tick 平均）",
        "label_en": "Reward avg rate",
        "group_zh": "奖励/惩罚（Rwd/Pun）",
    },
    "punish_rate": {
        "metric": "emotion.pun",
        "mode": "avg_rate",
        "window_ticks": 4,
        "label_zh": "惩罚信号变化率（PUN 近 N tick 平均）",
        "label_en": "Punish avg rate",
        "group_zh": "奖励/惩罚（Rwd/Pun）",
    },

    # ------------------------------------------------------------
    # NeuroTransmitter (NT) / 情绪递质通道预设（带 channel 参数）
    # ------------------------------------------------------------
    # 说明：
    # - 这类预设需要额外填写 metric.channel（通道名），最终会映射到 emotion.nt.{channel}
    # - 通道名可以是缩写（DA/ADR/...）也可以是中文名（多巴胺/皮质醇...），由上下文/EMgr 提供别名扩展
    "nt_state": {
        "metric": "emotion.nt.{channel}",
        "mode": "state",
        "needs_channel": True,
        "label_zh": "情绪递质状态（NT，需填写 channel）",
        "label_en": "NT state (channel required)",
        "group_zh": "情绪递质（NT）",
    },
    "nt_delta": {
        "metric": "emotion.nt.{channel}",
        "mode": "delta",
        "needs_channel": True,
        "label_zh": "情绪递质变化量（NT，需填写 channel）",
        "label_en": "NT delta (channel required)",
        "group_zh": "情绪递质（NT）",
    },
    "nt_rate": {
        "metric": "emotion.nt.{channel}",
        "mode": "avg_rate",
        "window_ticks": 4,
        "needs_channel": True,
        "label_zh": "情绪递质变化率（NT，近 N tick 平均，需填写 channel）",
        "label_en": "NT avg rate (channel required)",
        "group_zh": "情绪递质（NT）",
    },
    "nt_changed": {
        "metric": "emotion.nt.{channel}",
        "mode": "delta",
        "op": "changed",
        "needs_channel": True,
        "label_zh": "情绪递质变化了（NT，需填写 channel）",
        "label_en": "NT changed (channel required)",
        "group_zh": "情绪递质（NT）",
    },

    # ------------------------------------------------------------
    # Stimulus process / 刺激级过程指标预设
    # ------------------------------------------------------------
    "stimulus_residual_ratio": {
        "metric": "stimulus.residual_ratio",
        "mode": "state",
        "label_zh": "刺激级剩余能量比例（Residual Ratio）",
        "label_en": "Stimulus residual energy ratio",
        "group_zh": "刺激级过程（Stimulus Process）",
    },

    # ------------------------------------------------------------
    # Retrieval match score / 匹配分数预设（当前优先支持刺激级）
    # ------------------------------------------------------------
    "stimulus_match_score": {
        "metric": "retrieval.stimulus.best_match_score",
        "mode": "state",
        "label_zh": "查存一体匹配分数（刺激级，best_match_score）",
        "label_en": "Stimulus retrieval match score (best)",
        "group_zh": "查存一体（Retrieval）",
    },
    "grasp_score": {
        "metric": "retrieval.stimulus.grasp_score",
        "mode": "state",
        "label_zh": "把握感/置信度综合得分（grasp_score，0~1）",
        "label_en": "Grasp/confidence score (0~1)",
        "group_zh": "查存一体（Retrieval）",
    },
    "stimulus_match_score_target": {
        "metric": "retrieval.stimulus.match_scores",
        "mode": "state",
        "label_zh": "查存一体匹配分数（刺激级，按目标 structure_id）",
        "label_en": "Stimulus retrieval match score (by target)",
        "group_zh": "查存一体（Retrieval）",
    },
    "structure_match_score": {
        "metric": "retrieval.structure.best_match_score",
        "mode": "state",
        "label_zh": "查存一体匹配分数（结构级，best_match_score）",
        "label_en": "Structure-level retrieval match score (best)",
        "group_zh": "查存一体（Retrieval）",
    },
    "structure_match_score_target": {
        "metric": "retrieval.structure.match_scores",
        "mode": "state",
        "label_zh": "查存一体匹配分数（结构级，按目标 group_id）",
        "label_en": "Structure-level retrieval match score (by target)",
        "group_zh": "查存一体（Retrieval）",
    },
}


def _normalize_preset_key(name: str) -> str:
    """Normalize a preset key for alias matching / 归一化 preset 名称（用于别名匹配）。"""
    s = str(name or "").strip()
    # Common user habit: wrap with __ like "__获得实能量__"
    # 常见习惯：用 __ 包裹，例如 "__获得实能量__"
    s = s.strip("_").strip()
    return s


# Metric preset aliases / 指标预设别名（中文/便捷写法 -> 稳定英文键）
# ------------------------------------------------------------------
# 说明：
# - 这里列的是“用户更愿意写的中文口径”，会在 normalize 阶段自动归一化到稳定 key。
# - 你可以在规则文件里写 "__获得实能量__" 或 "获得实能量"，最终都会变成 got_er。
_METRIC_PRESET_ALIASES: dict[str, str] = {
    # 对象能量（ER/EV/CP）
    "获得实能量": "got_er",
    "获得虚能量": "got_ev",
    "实能量变化速率": "er_rate",
    "实能量变化率": "er_rate",
    "虚能量变化速率": "ev_rate",
    "虚能量变化率": "ev_rate",
    "实能量状态": "er_state",
    "虚能量状态": "ev_state",
    "对象总能量状态": "total_energy_state",
    "总能量状态": "total_energy_state",
    "获得总能量": "got_total_energy",
    "总能量变化率": "total_energy_rate",
    "总能量变化速率": "total_energy_rate",
    "认知压状态": "cp_state",
    "认知压大小状态": "cp_abs_state",
    "认知压的大小": "cp_abs_state",
    "获得认知压大小": "got_cp_abs",
    "认知压大小变化量": "got_cp_abs",
    "获得认知压": "got_cp",
    "认知压变化率": "cp_rate",
    "认知压大小变化率": "cp_abs_rate",
    "近因增益状态": "recency_state",
    "疲劳度状态": "fatigue_state",

    # 状态池
    "状态池实能量总量": "pool_er_total",
    "状态池虚能量总量": "pool_ev_total",
    "状态池总能量": "pool_total_energy",
    "状态池总能量状态": "pool_total_energy",
    "状态池获得总能量": "pool_total_energy_got",
    "状态池总能量变化量": "pool_total_energy_got",
    "状态池总能量变化率": "pool_total_energy_rate",
    "状态池总能量变化速率": "pool_total_energy_rate",
    "状态池对象数量": "pool_item_count",
    "状态池条目数": "pool_item_count",
    "状态池实能量变化率": "pool_er_rate",
    "状态池实能量变化速率": "pool_er_rate",
    "状态池虚能量变化率": "pool_ev_rate",
    "状态池虚能量变化速率": "pool_ev_rate",
    "状态池认知压变化率": "pool_cp_rate",
    "状态池认知压变化速率": "pool_cp_rate",
    "状态池认知压大小变化率": "pool_cp_abs_rate",
    "状态池认知压大小变化速率": "pool_cp_abs_rate",
    "状态池认知压总量": "pool_cp_total",
    "状态池认知压大小总量": "pool_cp_abs_total",
    "状态池能量聚集度": "pool_concentration",
    "状态池能量聚集度变化率": "pool_concentration_rate",
    "状态池有效波峰数量": "pool_effective_peak_count",
    "有效波峰数量": "pool_effective_peak_count",
    "繁简综合复杂度": "complexity_score",
    "繁简综合得分": "complexity_score",
    "核心繁简复杂度": "core_complexity_score",
    "核心繁简得分": "core_complexity_score",

    # CAM（当前注意记忆体）
    "当前注意记忆体大小": "cam_size",
    "CAM大小": "cam_size",
    "CAM能量聚集度": "cam_concentration",

    # MAP（记忆赋能池）
    "记忆赋能池条目数": "map_item_count",
    "记忆赋能池总虚能量": "map_total_ev",

    # 奖励/惩罚
    "奖励信号状态": "reward_state",
    "惩罚信号状态": "punish_state",
    "奖励信号增加": "reward_got",
    "惩罚信号增加": "punish_got",
    "奖励信号变化率": "reward_rate",
    "惩罚信号变化率": "punish_rate",
    "奖励信号变化速率": "reward_rate",
    "惩罚信号变化速率": "punish_rate",

    # 情绪递质（NT）
    # 说明：
    # - 你提出的典型口径：“情绪递质__状态__ / 情绪递质__变化了__ / 情绪递质__变化率__”
    #   这里统一归一化到带 channel 参数的预设（nt_state/nt_changed/nt_rate）。
    # - 通道名通过 metric.channel 字段填写，例如 channel: "DA" 或 "多巴胺"。
    "情绪递质状态": "nt_state",
    "情绪递质变化量": "nt_delta",
    "情绪递质变化率": "nt_rate",
    "情绪递质变化了": "nt_changed",
    "情绪递质__状态": "nt_state",
    "情绪递质__变化量": "nt_delta",
    "情绪递质__变化率": "nt_rate",
    "情绪递质__变化了": "nt_changed",

    # 刺激级过程 / 查存一体
    "刺激级查存一体结束时的剩余能量比例": "stimulus_residual_ratio",
    "查存一体过程匹配分数": "stimulus_match_score",
    "把握感综合得分": "grasp_score",
    "置信度综合得分": "grasp_score",
    "把握感得分": "grasp_score",
    "查存一体过程匹配分数（按目标）": "stimulus_match_score_target",
    "查存一体过程匹配分数（结构级）": "structure_match_score",
    "查存一体过程匹配分数（结构级按目标）": "structure_match_score_target",
    "结构级查存一体匹配分数": "structure_match_score",
    "结构级查存一体匹配分数（按目标）": "structure_match_score_target",
}


def resolve_metric_preset_name(preset: str) -> str:
    """
    Resolve preset name to a canonical key (if known).
    将 preset 名称解析为规范 key（如果可识别）。

    Returns the canonical key if resolvable; otherwise returns the input (trimmed).
    若可解析则返回规范 key，否则返回原字符串（已去首尾空白）。
    """
    raw = str(preset or "").strip()
    key = _normalize_preset_key(raw)
    if key in _METRIC_PRESET_MAP:
        return key
    # try lower for ASCII keys
    low = key.lower()
    if low in _METRIC_PRESET_MAP:
        return low
    if key in _METRIC_PRESET_ALIASES:
        return str(_METRIC_PRESET_ALIASES[key])
    if low in _METRIC_PRESET_ALIASES:
        return str(_METRIC_PRESET_ALIASES[low])
    return raw


def metric_preset_catalog() -> list[dict[str, Any]]:
    """
    Return a small catalog for UI dropdowns.
    返回给 UI 用的预设目录（用于下拉框与提示）。
    """
    out: list[dict[str, Any]] = []
    for name, spec in _METRIC_PRESET_MAP.items():
        if not isinstance(spec, dict):
            continue
        out.append(
            {
                "preset": str(name),
                "metric": str(spec.get("metric", "") or ""),
                "mode": str(spec.get("mode", "") or ""),
                "window_ticks": int(spec.get("window_ticks", 0) or 0),
                "needs_channel": bool(spec.get("needs_channel", False)),
                "label_zh": str(spec.get("label_zh", "") or ""),
                "label_en": str(spec.get("label_en", "") or ""),
                "group_zh": str(spec.get("group_zh", "") or ""),
            }
        )
    out.sort(key=lambda r: (str(r.get("group_zh", "") or ""), str(r.get("label_zh", "") or ""), str(r.get("preset", "") or "")))
    return out


def _render_template_value(value: Any, *, vars_ctx: dict[str, Any]) -> Any:
    """
    Resolve template strings like '{{{var}}}'.
    解析模板字符串 '{{{变量名}}}'。

    Safety / 安全性：
    - 仅做字符串替换，不执行表达式、不调用 eval。
    - 若整个字符串就是单一模板，则返回变量原值（数值保持数值）。
    """
    if not isinstance(vars_ctx, dict):
        vars_ctx = {}
    if not isinstance(value, str):
        return value

    text = value
    # NOTE:
    # - Python regex uses "\{" to match a literal "{", so the correct pattern is r"\{\{\{...\}\}\}".
    # - Avoid over-escaping (e.g. r"\\{") which would match a literal backslash and break templates.
    # 注意：
    # - 正确匹配字面量 "{" 需要使用 "\{"，因此模式应为 r"\{\{\{...\}\}\}"。
    # - 避免过度转义（例如 r"\\{"），否则会匹配到反斜杠并导致模板无法工作。
    m = re.fullmatch(r"\{\{\{([a-zA-Z0-9_]{1,64})\}\}\}", text.strip())
    if m:
        name = m.group(1)
        return vars_ctx.get(name, "")

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        v = vars_ctx.get(name, "")
        return str(v)

    return re.sub(r"\{\{\{([a-zA-Z0-9_]{1,64})\}\}\}", repl, text)


def _render_templates_in_data(value: Any, *, vars_ctx: dict[str, Any]) -> Any:
    """
    Recursively render templates in nested structures.
    在嵌套结构（dict/list）中递归渲染模板字符串。

    Safety / 安全性：
    - 仅对字符串值做模板替换，不对 dict 的 key 做替换（避免破坏结构/注入风险）。
    - 仅支持 {{{var}}} 形式，不支持表达式。
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[str(k)] = _render_templates_in_data(v, vars_ctx=vars_ctx)
        return out
    if isinstance(value, list):
        return [_render_templates_in_data(v, vars_ctx=vars_ctx) for v in value]
    return _render_template_value(value, vars_ctx=vars_ctx)


# ======================================================================
# Action execution / 动作执行
# ======================================================================


_MAX_ACTION_EXEC_DEPTH = 16
_MAX_SCHEDULED_ACTIONS = 256


def _scheduled_actions_list(runtime_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Get the scheduled actions list from runtime_state / 获取运行态延时动作列表。"""
    lst = runtime_state.setdefault("scheduled_actions", [])
    if not isinstance(lst, list):
        lst = []
        runtime_state["scheduled_actions"] = lst
    # Ensure items are dicts; keep it loose to be forward-compatible.
    # 保持宽松：只过滤掉明显非法的项，便于后续扩展兼容。
    return [x for x in lst if isinstance(x, dict)]


def _set_scheduled_actions_list(runtime_state: dict[str, Any], lst: list[dict[str, Any]]) -> None:
    runtime_state["scheduled_actions"] = [x for x in (lst or []) if isinstance(x, dict)]


def _clamp01(x: float) -> float:
    """Clamp a float to [0,1] / 将数值截断到 [0,1]。"""
    try:
        v = float(x)
    except Exception:
        v = 0.0
    return max(0.0, min(1.0, v))


def _resolve_cfs_strength(strength_spec: Any, *, vars_ctx: dict[str, Any]) -> float:
    """
    Resolve CFS strength (0~1) from a spec.
    从配置中解析 CFS 强度（0~1）。

    Supported shapes / 支持形态：
      1) number / string-number: 直接作为强度
      2) dict: 轻量安全的“线性映射”描述（不执行表达式）
         - from: "match_value" | "var" | <var_name>
         - var: 变量名（当 from="var" 时使用）
         - policy: "linear_clamp" | "scale_offset" | "verify_mix"
         - min/max: linear_clamp 的输入范围
         - out_min/out_max: linear_clamp 的输出范围（默认 0~1）
         - scale/offset: scale_offset 的线性变换
         - abs: bool（先取绝对值）
         - invert: bool（对 linear_clamp 输出做 1-x）

         verify_mix（期待/压力验证的“渐变混合”策略）:
         - 目标：把“验证/不验”从二极管变成连续渐变，并且具有对称性。
           直觉：把“实际获得”与“预测强度”看作两股对抗力量，按占比分配强度。

         - 用法示例（验证强度）:
             strength:
               from: var
               var: expect_strength          # base ∈ [0,1]
               policy: verify_mix
               part: verified                # verified / unverified
               pred_var: expect_pred_ev       # 预测量（通常取 EV）
               actual_var: expect_er_rate     # 实际量（通常取 ER 变化率或变化量）
               pred_scale: 1.0               # 可选：缩放到同一量纲
               actual_scale: 2.0             # 可选：例如 window_ticks
               gamma: 1.0                    # >1 更“果断”，<1 更“柔和”
               eps: 1e-6

    注意：
      - 本函数只做简单数值变换，保证规则系统可审计与安全。
      - 若解析失败，返回 0。
    """
    if strength_spec is None or strength_spec == "":
        return 0.0

    if isinstance(strength_spec, (int, float)):
        return _clamp01(float(strength_spec))

    if isinstance(strength_spec, str):
        v = _coerce_float_maybe(strength_spec)
        return _clamp01(float(v or 0.0))

    if not isinstance(strength_spec, dict):
        v = _coerce_float_maybe(strength_spec)
        return _clamp01(float(v or 0.0))

    src = strength_spec.get("from")
    if src in {None, "", "match_value"}:
        base = vars_ctx.get("match_value", 0.0)
    elif src == "var":
        base = vars_ctx.get(str(strength_spec.get("var", "") or "").strip(), 0.0)
    else:
        base = vars_ctx.get(str(src).strip(), 0.0)

    v0 = _coerce_float_maybe(base)
    v = float(v0 or 0.0)
    if bool(strength_spec.get("abs", False)):
        v = abs(v)

    policy = str(strength_spec.get("policy", "linear_clamp") or "linear_clamp").strip()

    if policy in {"verify_mix", "verification_mix", "verify_ratio_mix"}:
        # verify_mix: continuous, symmetric mix between "verified" and "unverified".
        # verify_mix：连续、对称的“验证/不验”混合。
        #
        # Definitions / 定义：
        #   pred >= 0   : 预测量（通常用 EV 或其映射后的强度）
        #   actual >= 0 : 实际量（通常用 got_er / er_rate 等）
        #
        # Mix ratio / 混合占比：
        #   v = actual^gamma / (actual^gamma + pred^gamma + eps)
        #   u = pred^gamma   / (actual^gamma + pred^gamma + eps)
        #
        # Output strength / 输出：
        #   out = base_strength * (v or u)
        part = str(strength_spec.get("part", "verified") or "verified").strip() or "verified"
        pred_var = str(strength_spec.get("pred_var", strength_spec.get("pred", "")) or "").strip()
        actual_var = str(strength_spec.get("actual_var", strength_spec.get("actual", "")) or "").strip()

        eps = _coerce_float_maybe(strength_spec.get("eps", strength_spec.get("epsilon", 1e-6)))
        eps_f = float(eps if eps is not None else 1e-6)
        eps_f = max(0.0, eps_f)

        gamma = _coerce_float_maybe(strength_spec.get("gamma", 1.0))
        gamma_f = float(gamma if gamma is not None else 1.0)
        # Keep gamma sane / 控制 gamma 合理范围，避免 NaN/爆炸。
        if not (gamma_f > 0.0):
            gamma_f = 1.0
        gamma_f = min(8.0, max(0.25, gamma_f))

        pred_scale = _coerce_float_maybe(strength_spec.get("pred_scale", 1.0))
        actual_scale = _coerce_float_maybe(strength_spec.get("actual_scale", 1.0))
        pred_scale_f = float(pred_scale if pred_scale is not None else 1.0)
        actual_scale_f = float(actual_scale if actual_scale is not None else 1.0)
        pred_scale_f = max(0.0, pred_scale_f)
        actual_scale_f = max(0.0, actual_scale_f)

        pred_raw = _coerce_float_maybe(vars_ctx.get(pred_var, 0.0)) if pred_var else 0.0
        actual_raw = _coerce_float_maybe(vars_ctx.get(actual_var, 0.0)) if actual_var else 0.0
        pred_v = max(0.0, float(pred_raw or 0.0) * pred_scale_f)
        actual_v = max(0.0, float(actual_raw or 0.0) * actual_scale_f)

        # Power transform / 幂变换（gamma）
        if abs(gamma_f - 1.0) < 1e-12:
            p = pred_v
            a = actual_v
        else:
            p = float(pow(pred_v, gamma_f)) if pred_v > 0.0 else 0.0
            a = float(pow(actual_v, gamma_f)) if actual_v > 0.0 else 0.0

        denom = a + p + eps_f
        if denom <= 0.0:
            ratio = 0.0
        else:
            if part in {"verified", "v", "actual"}:
                ratio = a / denom
            else:
                ratio = p / denom

        return _clamp01(float(v) * _clamp01(float(ratio)))

    if policy == "scale_offset":
        scale = _coerce_float_maybe(strength_spec.get("scale", 1.0))
        offset = _coerce_float_maybe(strength_spec.get("offset", 0.0))
        return _clamp01(v * float(scale or 1.0) + float(offset or 0.0))

    # Default: linear_clamp
    lo = _coerce_float_maybe(strength_spec.get("min", 0.0))
    hi = _coerce_float_maybe(strength_spec.get("max", 1.0))
    lo_f = float(lo or 0.0)
    hi_f = float(hi or 1.0)
    if hi_f <= lo_f + 1e-12:
        return 0.0
    t = (v - lo_f) / (hi_f - lo_f)
    t = _clamp01(t)
    if bool(strength_spec.get("invert", False)):
        t = 1.0 - t

    out_min = _coerce_float_maybe(strength_spec.get("out_min", 0.0))
    out_max = _coerce_float_maybe(strength_spec.get("out_max", 1.0))
    out_lo = float(out_min or 0.0)
    out_hi = float(out_max or 1.0)
    return _clamp01(out_lo + t * (out_hi - out_lo))


def _resolve_numeric_delta_spec(delta_spec: Any, *, vars_ctx: dict[str, Any]) -> float:
    """
    Resolve a numeric delta spec for emotion_update.
    解析 emotion_update 的数值增量描述。

    Supported shapes / 支持形态：
      1) number / string-number: 直接作为增量
      2) dict:
         - from: "match_value" | "var" | <var_name>
         - var: 变量名（当 from="var" 时使用）
         - policy: "scale_offset" | "linear_clamp" | "passthrough"
         - scale / offset: 线性变换（允许负系数）
         - min / max / out_min / out_max: linear_clamp 输入输出范围
         - clamp_min / clamp_max: 对最终输出做额外钳制
         - abs: bool
    """
    if delta_spec is None or delta_spec == "":
        return 0.0

    if isinstance(delta_spec, (int, float)):
        return float(delta_spec)

    if isinstance(delta_spec, str):
        v = _coerce_float_maybe(delta_spec)
        return float(v or 0.0)

    if not isinstance(delta_spec, dict):
        v = _coerce_float_maybe(delta_spec)
        return float(v or 0.0)

    src = delta_spec.get("from")
    if src in {None, "", "match_value"}:
        base = vars_ctx.get("match_value", 0.0)
    elif src == "var":
        base = vars_ctx.get(str(delta_spec.get("var", "") or "").strip(), 0.0)
    else:
        base = vars_ctx.get(str(src).strip(), 0.0)

    v0 = _coerce_float_maybe(base)
    v = float(v0 or 0.0)
    if bool(delta_spec.get("abs", False)):
        v = abs(v)

    policy = str(delta_spec.get("policy", "scale_offset") or "scale_offset").strip().lower() or "scale_offset"
    out = v

    if policy in {"scale_offset", "scale", "affine", "linear"}:
        scale = _coerce_float_maybe(delta_spec.get("scale", 1.0))
        offset = _coerce_float_maybe(delta_spec.get("offset", 0.0))
        out = v * float(scale if scale is not None else 1.0) + float(offset if offset is not None else 0.0)
    elif policy in {"linear_clamp", "normalized_linear"}:
        lo = _coerce_float_maybe(delta_spec.get("min", 0.0))
        hi = _coerce_float_maybe(delta_spec.get("max", 1.0))
        lo_f = float(lo if lo is not None else 0.0)
        hi_f = float(hi if hi is not None else 1.0)
        if hi_f <= lo_f + 1e-12:
            out = 0.0
        else:
            t = (v - lo_f) / (hi_f - lo_f)
            t = _clamp01(t)
            out_min = _coerce_float_maybe(delta_spec.get("out_min", 0.0))
            out_max = _coerce_float_maybe(delta_spec.get("out_max", 1.0))
            out_lo = float(out_min if out_min is not None else 0.0)
            out_hi = float(out_max if out_max is not None else 1.0)
            out = out_lo + t * (out_hi - out_lo)

    clamp_min = _coerce_float_maybe(delta_spec.get("clamp_min", None))
    clamp_max = _coerce_float_maybe(delta_spec.get("clamp_max", None))
    if clamp_min is not None:
        out = max(float(clamp_min), out)
    if clamp_max is not None:
        out = min(float(clamp_max), out)
    return float(out)


def _execute_due_scheduled_actions(
    *,
    runtime_state: dict[str, Any],
    tick_index: int,
    trace_id: str,
    tick_id: str,
    now_ms: int,
    context: dict[str, Any],
    focus_defaults: dict[str, Any],
    habituation_defaults: dict[str, Any],
    allow_timer: bool,
    runtime_cfs_signals: list[dict[str, Any]],
    out_emitted_cfs_signals: list[dict[str, Any]],
    out_triggered_scripts: list[dict[str, Any]],
    out_focus_directives: list[dict[str, Any]],
    out_emotion_updates: dict[str, float],
    out_action_triggers: list[dict[str, Any]],
    out_pool_effects: list[dict[str, Any]],
    out_audit_notes: list[str],
) -> None:
    """
    Execute scheduled actions whose due_tick <= current tick_index.
    执行到期的延时动作（due_tick <= 当前 tick_index）。

    Scheduling is stored in runtime_state["scheduled_actions"].
    延时队列存放在 runtime_state["scheduled_actions"]。
    """
    scheduled = _scheduled_actions_list(runtime_state)
    if not scheduled:
        return

    due: list[dict[str, Any]] = []
    future: list[dict[str, Any]] = []
    for entry in scheduled:
        try:
            due_tick = int(entry.get("due_tick", 0) or 0)
        except Exception:
            due_tick = 0
        if due_tick <= int(tick_index):
            due.append(entry)
        else:
            future.append(entry)

    # Keep future schedule only (due entries will be executed now).
    _set_scheduled_actions_list(runtime_state, future)

    if not due:
        return

    # Stable order: earliest due_tick first; then created_at.
    # 稳定执行顺序：先 due_tick，再 created_at。
    due.sort(key=lambda e: (int(e.get("due_tick", 0) or 0), int(e.get("created_at", 0) or 0)))

    for entry in due[:_MAX_SCHEDULED_ACTIONS]:
        try:
            rid = str(entry.get("rule_id", "scheduled") or "scheduled")
            actions = list(entry.get("actions", []) or [])
            vars_ctx = entry.get("vars_ctx", {}) if isinstance(entry.get("vars_ctx"), dict) else {}
            # A scheduled block is not tied to fresh matches; it only carries captured vars.
            # 延时块没有新的 matches，仅携带当时捕获的 vars。
            matches = _empty_matches()
            matches["vars"] = dict(vars_ctx)
            hab_cfg = _resolve_habituation_config(defaults=habituation_defaults, rule={})
            hab_enabled = bool(hab_cfg.get("enabled", True))
            hab_scale, hab_hist_sum = _habituation_scale(
                runtime_state=runtime_state,
                rule_id=rid,
                tick_index=int(tick_index),
                config=hab_cfg,
                enabled=hab_enabled,
            )

            out_audit_notes.append(
                f"[IESM] execute scheduled actions: rule_id={rid} due_tick={entry.get('due_tick')} hab_scale={round(float(hab_scale), 4)} hist_sum={round(float(hab_hist_sum), 4)}"
            )
            raw_energy = _execute_actions(
                actions=actions,
                rule_id=rid,
                rule_title=str(entry.get("rule_title", "") or ""),
                rule_phase=str(entry.get("rule_phase", "directives") or "directives"),
                rule_priority=int(entry.get("rule_priority", 0) or 0),
                trace_id=trace_id,
                tick_id=tick_id,
                tick_index=int(tick_index),
                now_ms=int(now_ms),
                context=context,
                runtime_state=runtime_state,
                provided_tick_index=True,
                allow_timer=allow_timer,
                matches=matches,
                vars_ctx=dict(vars_ctx),
                focus_defaults=focus_defaults,
                runtime_cfs_signals=runtime_cfs_signals,
                out_emitted_cfs_signals=out_emitted_cfs_signals,
                out_triggered_scripts=out_triggered_scripts,
                out_focus_directives=out_focus_directives,
                out_emotion_updates=out_emotion_updates,
                out_action_triggers=out_action_triggers,
                out_pool_effects=out_pool_effects,
                out_audit_notes=out_audit_notes,
                depth=0,
                effect_scale=float(hab_scale),
            )
            _habituation_record_energy(runtime_state=runtime_state, rule_id=rid, tick_index=int(tick_index), raw_energy=float(raw_energy or 0.0))
        except Exception as exc:
            out_audit_notes.append(f"[IESM] scheduled action execution error: {exc}")


def _execute_actions(
    *,
    actions: list[dict[str, Any]],
    rule_id: str,
    rule_title: str,
    rule_phase: str,
    rule_priority: int,
    trace_id: str,
    tick_id: str,
    tick_index: int,
    now_ms: int,
    context: dict[str, Any],
    runtime_state: dict[str, Any],
    provided_tick_index: bool,
    allow_timer: bool,
    matches: dict[str, Any],
    vars_ctx: dict[str, Any],
    focus_defaults: dict[str, Any],
    runtime_cfs_signals: list[dict[str, Any]],
    out_emitted_cfs_signals: list[dict[str, Any]],
    out_triggered_scripts: list[dict[str, Any]],
    out_focus_directives: list[dict[str, Any]],
    out_emotion_updates: dict[str, float],
    out_action_triggers: list[dict[str, Any]],
    out_pool_effects: list[dict[str, Any]],
    out_audit_notes: list[str],
    depth: int,
    effect_scale: float = 1.0,
) -> float:
    """
    Execute normalized actions list.
    执行规范化后的动作列表。

    IMPORTANT / 重要：
    - This function must be deterministic and side-effect free on external systems.
      它不应直接修改外部系统（例如 StatePool），只产出 directives/effects 给上层应用。
    - Delay scheduling is stored in runtime_state only (internal bookkeeping).
      delay 仅写入 runtime_state（内部记账），不触碰外部模块。
    """
    if depth > _MAX_ACTION_EXEC_DEPTH:
        out_audit_notes.append(f"[IESM] action depth overflow: rule_id={rule_id} depth={depth}")
        return 0.0

    if not isinstance(vars_ctx, dict):
        vars_ctx = {}
    if not isinstance(matches, dict):
        matches = _empty_matches()
    if not isinstance(runtime_cfs_signals, list):
        runtime_cfs_signals = []
    if not isinstance(out_emitted_cfs_signals, list):
        out_emitted_cfs_signals = []

    try:
        scale = float(effect_scale)
    except Exception:
        scale = 1.0
    # Soft clamp: allow 0~1 only.
    scale = max(0.0, min(1.0, float(scale)))
    raw_energy_total = 0.0

    for idx, action in enumerate(list(actions or [])):
        if not isinstance(action, dict) or not action:
            continue
        key = next(iter(action.keys()))
        raw_spec = action.get(key)

        # Render templates in the action spec before execution.
        # 执行动作前先渲染模板变量。
        spec = _render_templates_in_data(raw_spec, vars_ctx=vars_ctx)

        try:
            if key == "focus":
                focus_spec = spec if isinstance(spec, dict) else {}
                out_focus_directives.extend(
                    _build_focus_directives_from_action(
                        rule_id=rule_id,
                        rule_title=rule_title,
                        spec=focus_spec,
                        matches=matches,
                        now_ms=now_ms,
                        defaults=focus_defaults,
                    )
                )
                continue

            if key == "emit_script":
                s = spec if isinstance(spec, dict) else {}
                script_id = str(s.get("script_id", "") or "").strip()
                if not script_id:
                    out_audit_notes.append(f"[IESM] emit_script skipped (empty script_id): rule_id={rule_id}")
                    continue
                out_triggered_scripts.append(
                    {
                        "script_id": script_id,
                        "script_kind": str(s.get("script_kind", "custom") or "custom"),
                        "priority": int(s.get("priority", rule_priority) or rule_priority),
                        "trigger": str(s.get("trigger", "") or ""),
                        "created_at": int(now_ms),
                        "trace_id": str(trace_id or ""),
                        "tick_id": str(tick_id or ""),
                        "rule_id": str(rule_id or ""),
                        "rule_title": str(rule_title or ""),
                        "rule_phase": str(rule_phase or ""),
                    }
                )
                continue

            if key == "emotion_update":
                payload = spec if isinstance(spec, dict) else {}
                raw_payload = raw_spec if isinstance(raw_spec, dict) else {}
                structured = bool(raw_payload) and (
                    isinstance(raw_payload.get("channels"), dict) or any(str(k) in _EMOTION_UPDATE_META_KEYS for k in raw_payload.keys())
                )
                if not structured:
                    for ch, delta_raw in payload.items():
                        ch_name = str(ch or "").strip()
                        if not ch_name:
                            continue
                        dv = _coerce_float_maybe(delta_raw)
                        if dv is None:
                            out_audit_notes.append(f"[IESM] emotion_update invalid delta: ch={ch_name} value={delta_raw}")
                            continue
                        raw_energy_total += abs(float(dv))
                        dv2 = float(dv) * float(scale)
                        if abs(dv2) < 1e-12:
                            continue
                        out_emotion_updates[ch_name] = float(out_emotion_updates.get(ch_name, 0.0) or 0.0) + float(dv2)
                    continue

                source = str(payload.get("from", "single") or "single").strip().lower() or "single"
                match_policy = str(payload.get("match_policy", "all") or "all").strip().lower() or "all"
                max_updates = _coerce_int_maybe(payload.get("max_updates", payload.get("max_matches", 12)))
                max_updates = max(1, min(64, int(max_updates or 12)))

                rendered_channels = payload.get("channels") if isinstance(payload.get("channels"), dict) else None
                if rendered_channels is None:
                    rendered_channels = {str(k): v for k, v in payload.items() if str(k) not in _EMOTION_UPDATE_META_KEYS}
                raw_channels = raw_payload.get("channels") if isinstance(raw_payload.get("channels"), dict) else None
                if raw_channels is None:
                    raw_channels = {str(k): v for k, v in raw_payload.items() if str(k) not in _EMOTION_UPDATE_META_KEYS}

                records: list[dict[str, Any]] = []
                if source == "metric_matches":
                    records = [r for r in (matches.get("metric", []) or []) if isinstance(r, dict)]
                    if match_policy == "strongest":
                        records = sorted(records, key=lambda r: abs(float(r.get("value", 0.0) or 0.0)), reverse=True)[:1]
                    elif match_policy == "first":
                        records = records[:1]
                    else:
                        records = records[:max_updates]
                elif source == "cfs_matches":
                    records = [r for r in (matches.get("cfs", []) or []) if isinstance(r, dict)]
                    if match_policy == "strongest":
                        records = sorted(records, key=lambda r: abs(float(r.get("strength", 0.0) or 0.0)), reverse=True)[:1]
                    elif match_policy == "first":
                        records = records[:1]
                    else:
                        records = records[:max_updates]
                else:
                    records = [{}]

                for rec in records:
                    local_vars = dict(vars_ctx)
                    if source == "metric_matches":
                        local_vars["match_value"] = float(rec.get("value", local_vars.get("match_value", 0.0)) or 0.0)
                        local_vars["match_item_id"] = str(rec.get("item_id", local_vars.get("match_item_id", "")) or "")
                        local_vars["match_ref_object_id"] = str(rec.get("ref_object_id", local_vars.get("match_ref_object_id", "")) or "")
                        local_vars["match_ref_object_type"] = str(rec.get("ref_object_type", local_vars.get("match_ref_object_type", "")) or "")
                        local_vars["match_display"] = str(rec.get("display", local_vars.get("match_display", "")) or "")
                        local_vars["match_metric"] = str(rec.get("metric", local_vars.get("match_metric", "")) or "")
                    elif source == "cfs_matches":
                        local_vars["match_value"] = float(rec.get("strength", local_vars.get("match_value", 0.0)) or 0.0)
                        local_vars["match_kind"] = str(rec.get("kind", local_vars.get("match_kind", "")) or "")
                        local_vars["match_cfs_kind"] = str(rec.get("kind", local_vars.get("match_cfs_kind", "")) or "")
                        target = rec.get("target") if isinstance(rec.get("target"), dict) else {}
                        local_vars["match_item_id"] = str(target.get("target_item_id", local_vars.get("match_item_id", "")) or "")
                        local_vars["match_ref_object_id"] = str(target.get("target_ref_object_id", local_vars.get("match_ref_object_id", "")) or "")
                        local_vars["match_ref_object_type"] = str(target.get("target_ref_object_type", local_vars.get("match_ref_object_type", "")) or "")
                        local_vars["match_display"] = str(target.get("target_display", local_vars.get("match_display", "")) or rec.get("target_display", "") or "")

                    payload2 = _render_templates_in_data(raw_channels, vars_ctx=local_vars)
                    payload2 = payload2 if isinstance(payload2, dict) else dict(rendered_channels or {})
                    for ch, delta_raw in payload2.items():
                        ch_name = str(ch or "").strip()
                        if not ch_name:
                            continue
                        dv = _resolve_numeric_delta_spec(delta_raw, vars_ctx=local_vars)
                        raw_energy_total += abs(float(dv))
                        dv2 = float(dv) * float(scale)
                        if abs(dv2) < 1e-12:
                            continue
                        out_emotion_updates[ch_name] = float(out_emotion_updates.get(ch_name, 0.0) or 0.0) + float(dv2)
                continue

            if key == "action_trigger":
                # Enhanced action_trigger:
                # - Default: emit a single trigger (legacy behavior).
                # - Optional: expand from matched records ("metric_matches" / "cfs_matches"),
                #   so one rule can generate multiple action nodes (e.g. "对所有违和对象聚焦")。
                #
                # 加强版 action_trigger：
                # - 默认：输出单条触发（兼容旧行为）。
                # - 可选：从命中记录展开（metric_matches / cfs_matches），一条规则可生成多条行动触发，
                #   便于表达“对所有命中对象都触发行动”的先天脚本。
                raw_payload = raw_spec if isinstance(raw_spec, dict) else {}
                from_src = str(raw_payload.get("from", "") or "").strip()

                def _normalize_target_from(v: Any) -> str:
                    raw = str(v or "").strip().lower()
                    if raw in {"match", "auto", "metric_match", "cfs_match", "metric_matches", "cfs_matches"}:
                        return "match"
                    return ""

                def _extract_match_target_binding(
                    local_vars_for_target: dict[str, Any] | None,
                    *,
                    match_source: str,
                ) -> dict[str, str]:
                    local_vars2 = local_vars_for_target if isinstance(local_vars_for_target, dict) else {}
                    target_ref_object_id = str(local_vars2.get("match_ref_object_id", "") or "").strip()
                    target_ref_object_type = str(local_vars2.get("match_ref_object_type", "") or "").strip()
                    target_item_id = str(local_vars2.get("match_item_id", "") or "").strip()
                    target_display = str(local_vars2.get("match_display", "") or "").strip()
                    trigger_target_ref = ""
                    if target_ref_object_id and target_ref_object_type:
                        trigger_target_ref = f"{target_ref_object_type}:{target_ref_object_id}"
                    elif target_ref_object_id:
                        trigger_target_ref = target_ref_object_id
                    if not target_display:
                        target_display = target_ref_object_id or target_item_id
                    return {
                        "target_ref_object_id": str(target_ref_object_id or ""),
                        "target_ref_object_type": str(target_ref_object_type or ""),
                        "target_item_id": str(target_item_id or ""),
                        "target_display": str(target_display or ""),
                        "trigger_target_ref": str(trigger_target_ref or ""),
                        "trigger_target_display": str(target_display or ""),
                        "target_binding_match_source": str(match_source or ""),
                    }

                def _payload_has_explicit_target(payload: dict[str, Any]) -> bool:
                    params_payload = payload.get("params") if isinstance(payload.get("params"), dict) else {}
                    candidate_values = [
                        params_payload.get("target_ref_object_id"),
                        params_payload.get("ref_object_id"),
                        params_payload.get("target_item_id"),
                        params_payload.get("item_id"),
                        params_payload.get("trigger_target_ref"),
                        params_payload.get("trigger_target"),
                        params_payload.get("target_ref"),
                        params_payload.get("anchor_ref"),
                        payload.get("target_ref_object_id"),
                        payload.get("ref_object_id"),
                        payload.get("target_item_id"),
                        payload.get("item_id"),
                        payload.get("trigger_target_ref"),
                        payload.get("trigger_target"),
                        payload.get("target_ref"),
                        payload.get("anchor_ref"),
                    ]
                    return any(str(v or "").strip() for v in candidate_values)

                def _apply_target_binding(
                    payload: dict[str, Any],
                    *,
                    local_vars_for_target: dict[str, Any] | None,
                    match_source: str,
                ) -> None:
                    requested_from = _normalize_target_from(payload.get("target_from", raw_payload.get("target_from", "")))
                    params_payload = payload.get("params") if isinstance(payload.get("params"), dict) else {}
                    if not isinstance(params_payload, dict):
                        params_payload = {}
                    else:
                        params_payload = dict(params_payload)
                    payload["params"] = params_payload

                    explicit_target_present = _payload_has_explicit_target(payload)
                    match_binding = _extract_match_target_binding(
                        local_vars_for_target,
                        match_source=str(match_source or from_src or ""),
                    )
                    binding_applied = False
                    binding_strategy = "explicit" if explicit_target_present else "none"
                    binding_reason = "explicit_target_preserved" if explicit_target_present else "not_requested"

                    if requested_from == "match":
                        binding_strategy = "match"
                        if explicit_target_present:
                            binding_reason = "explicit_target_preserved"
                        else:
                            if any(
                                str(match_binding.get(key, "") or "").strip()
                                for key in ("target_ref_object_id", "target_item_id", "trigger_target_ref")
                            ):
                                for key in (
                                    "target_ref_object_id",
                                    "target_ref_object_type",
                                    "target_item_id",
                                    "target_display",
                                    "trigger_target_ref",
                                    "trigger_target_display",
                                ):
                                    value = match_binding.get(key, "")
                                    if str(value or "").strip():
                                        if not str(params_payload.get(key, "") or "").strip():
                                            params_payload[key] = value
                                        if not str(payload.get(key, "") or "").strip():
                                            payload[key] = value
                                binding_applied = True
                                binding_reason = "match_target_bound"
                            else:
                                binding_reason = "match_target_unavailable"

                    payload["params"] = params_payload
                    payload["target_binding_strategy"] = str(binding_strategy or "")
                    payload["target_binding_requested_from"] = str(requested_from or "")
                    payload["target_binding_applied"] = bool(binding_applied)
                    payload["target_binding_reason"] = str(binding_reason or "")
                    payload["target_binding_match_source"] = str(match_binding.get("target_binding_match_source", "") or "")
                    payload["target_binding_match_ref_object_id"] = str(match_binding.get("target_ref_object_id", "") or "")
                    payload["target_binding_match_ref_object_type"] = str(match_binding.get("target_ref_object_type", "") or "")
                    payload["target_binding_match_item_id"] = str(match_binding.get("target_item_id", "") or "")
                    payload["target_binding_match_display"] = str(match_binding.get("target_display", "") or "")

                def _emit_one_trigger(
                    rendered_payload: dict[str, Any],
                    *,
                    fallback_suffix: str,
                    local_vars_for_target: dict[str, Any] | None = None,
                    match_source: str = "",
                ) -> None:
                    payload2 = dict(rendered_payload)
                    _apply_target_binding(
                        payload2,
                        local_vars_for_target=local_vars_for_target,
                        match_source=match_source,
                    )
                    # Remove control fields so downstream consumers only see the actual trigger schema.
                    # 去掉控制字段，避免下游把它们当作行动参数。
                    for k in ["from", "match_policy", "max_triggers", "max", "policy", "target_from"]:
                        payload2.pop(k, None)

                    # Habituation: scale the action drive gain (soft attenuation).
                    raw_gain = _coerce_float_maybe(payload2.get("gain"))
                    if raw_gain is not None:
                        raw_energy_total_local = abs(float(raw_gain))
                        # update outer scope accumulator
                        nonlocal raw_energy_total
                        raw_energy_total += raw_energy_total_local
                        scaled_gain = float(raw_gain) * float(scale)
                        if abs(float(scaled_gain)) < 1e-12:
                            return
                        payload2["gain"] = round(float(scaled_gain), 8)

                    action_id = str(payload2.get("action_id", "") or payload2.get("id", "") or "").strip()
                    if not action_id:
                        action_kind = str(payload2.get("action_kind", "") or payload2.get("kind", "") or "custom").strip() or "custom"
                        action_id = f"{rule_id}_{action_kind}_{fallback_suffix}".strip("_") or f"{rule_id}_action_{idx}"

                    out_action_triggers.append(
                        {
                            **payload2,
                            "action_id": action_id,
                            "created_at": int(now_ms),
                            "trace_id": str(trace_id or ""),
                            "tick_id": str(tick_id or ""),
                            "rule_id": str(rule_id or ""),
                            "rule_title": str(rule_title or ""),
                            "rule_phase": str(rule_phase or ""),
                            "rule_priority": int(rule_priority),
                        }
                    )

                if from_src in {"metric_matches", "cfs_matches"}:
                    match_policy2 = str(raw_payload.get("match_policy", raw_payload.get("policy", "all")) or "all").strip() or "all"
                    max_triggers = _coerce_int_maybe(raw_payload.get("max_triggers", raw_payload.get("max", 8)))
                    max_triggers = max(1, min(64, int(max_triggers or 8)))

                    records: list[dict[str, Any]] = []
                    if from_src == "metric_matches":
                        records = [r for r in (matches.get("metric", []) or []) if isinstance(r, dict)]
                        # Ensure strongest-first order for "strongest"/cap.
                        # 确保按强度排序，便于 strongest/截断。
                        records.sort(key=lambda r: float(r.get("value", 0.0) or 0.0), reverse=True)
                    else:
                        records = [r for r in (matches.get("cfs", []) or []) if isinstance(r, dict)]
                        records.sort(key=lambda r: float(r.get("strength", 0.0) or 0.0), reverse=True)

                    if match_policy2 == "strongest":
                        records = records[:1]
                    elif match_policy2 == "first":
                        records = records[:1]
                    else:
                        records = records[:max_triggers]

                    if not records:
                        out_audit_notes.append(f"[IESM] action_trigger expand skipped (no records): rule_id={rule_id} from={from_src}")
                        continue

                    emitted = 0
                    for rec in records:
                        if emitted >= max_triggers:
                            break

                        local_vars = dict(vars_ctx)
                        fallback_suffix = ""

                        if from_src == "metric_matches":
                            local_vars["match_value"] = float(rec.get("value", local_vars.get("match_value", 0.0)) or 0.0)
                            local_vars["match_metric"] = str(rec.get("metric", local_vars.get("match_metric", "")) or "")
                            local_vars["match_item_id"] = str(rec.get("item_id", local_vars.get("match_item_id", "")) or "")
                            local_vars["match_ref_object_id"] = str(rec.get("ref_object_id", local_vars.get("match_ref_object_id", "")) or "")
                            local_vars["match_ref_object_type"] = str(rec.get("ref_object_type", local_vars.get("match_ref_object_type", "")) or "")
                            local_vars["match_display"] = str(rec.get("display", local_vars.get("match_display", "")) or "")
                            fallback_suffix = str(local_vars.get("match_ref_object_id", "") or local_vars.get("match_item_id", "") or emitted)
                        else:
                            local_vars["match_value"] = float(rec.get("strength", local_vars.get("match_value", 0.0)) or 0.0)
                            local_vars["match_strength"] = float(local_vars.get("match_value", 0.0) or 0.0)
                            local_vars["match_kind"] = str(rec.get("kind", local_vars.get("match_kind", "")) or "")
                            local_vars["match_scope"] = str(rec.get("scope", local_vars.get("match_scope", "")) or "")
                            target = rec.get("target") if isinstance(rec.get("target"), dict) else {}
                            local_vars["match_item_id"] = str(target.get("target_item_id", local_vars.get("match_item_id", "")) or "")
                            local_vars["match_ref_object_id"] = str(target.get("target_ref_object_id", local_vars.get("match_ref_object_id", "")) or "")
                            local_vars["match_ref_object_type"] = str(target.get("target_ref_object_type", local_vars.get("match_ref_object_type", "")) or "")
                            local_vars["match_display"] = str(target.get("target_display", local_vars.get("match_display", "")) or "")
                            fallback_suffix = str(local_vars.get("match_ref_object_id", "") or local_vars.get("match_item_id", "") or local_vars.get("match_kind", "") or emitted)

                        # Render templates per-record, so action_id/gain/params can bind to the correct target.
                        # 按记录逐条渲染模板：让 action_id/gain/params 能绑定到正确对象。
                        rendered = _render_templates_in_data(raw_payload, vars_ctx=local_vars)
                        rendered = rendered if isinstance(rendered, dict) else {}
                        _emit_one_trigger(
                            rendered,
                            fallback_suffix=fallback_suffix,
                            local_vars_for_target=local_vars,
                            match_source=from_src,
                        )
                        emitted += 1

                    continue

                # Legacy single-trigger behavior (templates already rendered by spec above).
                payload = spec if isinstance(spec, dict) else {}
                _emit_one_trigger(
                    payload,
                    fallback_suffix=str(idx),
                    local_vars_for_target=vars_ctx,
                    match_source=from_src,
                )
                continue

            if key == "cfs_emit":
                payload = spec if isinstance(spec, dict) else {}
                kind = str(payload.get("kind", "") or payload.get("cfs_kind", "") or "").strip()
                if not kind:
                    out_audit_notes.append(f"[IESM] cfs_emit skipped (empty kind): rule_id={rule_id}")
                    continue

                scope = str(payload.get("scope", "object") or "object").strip() or "object"
                source = str(payload.get("from", "metric_matches") or "metric_matches").strip() or "metric_matches"
                max_signals = _coerce_int_maybe(payload.get("max_signals", payload.get("emit_limit", 12)))
                max_signals = max(1, min(64, int(max_signals or 12)))
                min_strength = _coerce_float_maybe(payload.get("min_strength", 0.0))
                min_strength = float(min_strength or 0.0)
                capture_as = str(payload.get("capture_as", "") or "").strip()

                # reasons / evidence are optional; keep them small and auditable.
                # reasons / evidence 可选：保持小而可审计。
                reasons_raw = payload.get("reasons", payload.get("reason", []))
                reasons: list[str] = []
                if isinstance(reasons_raw, str) and reasons_raw.strip():
                    reasons = [reasons_raw.strip()]
                elif isinstance(reasons_raw, list):
                    reasons = [str(x) for x in reasons_raw if str(x)]
                # Always include the rule title as the first reason for better UX in the observatory UI.
                # 总是把规则标题放在 reasons 的第一个：前端默认只展示第一条原因，这样人类最易读。
                reasons = [f"先天规则:{str(rule_title or rule_id)}"] + reasons

                evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}

                strength_spec = payload.get("strength", payload.get("value", 1.0))

                # Optional: bind the emitted feeling as an attribute SA to its target object.
                # 可选：把该认知感受以“属性刺激元（SA）”绑定到目标对象上（对齐理论 3.8.1）。
                # 注意：这是“绑定约束信息”，不会额外把 SA/CSA 作为独立对象写入状态池（由 StatePool 配置控制）。
                #
                # IMPORTANT / 重要：
                # - We must read bind_attribute from the *raw_spec*, not from the pre-rendered `payload`.
                #   Because the action pre-render step uses only rule-level vars_ctx; it does not contain
                #   per-record vars like `strength`. If we render too early, templates like
                #   "违和感:{{{strength}}}" become "违和感:" and lose the placeholder forever.
                # - Therefore we keep the original bind_attribute dict here, and render it later with lv
                #   (which includes match_* + strength + cfs_kind).
                # - 必须从 raw_spec 读取 bind_attribute（而不是从已经渲染过模板的 payload 读取），
                #   否则会把 {{{strength}}} 过早替换成空字符串，导致前端只能看到“违和感:”。
                raw_payload = raw_spec if isinstance(raw_spec, dict) else {}
                bind_attr_raw = raw_payload.get("bind_attributes", raw_payload.get("bind_attribute", raw_payload.get("bind_attr", None)))
                bind_attr_specs: list[dict[str, Any]] = []
                if isinstance(bind_attr_raw, list):
                    bind_attr_specs = [dict(x) for x in bind_attr_raw if isinstance(x, dict)]
                elif isinstance(bind_attr_raw, dict):
                    bind_attr_specs = [dict(bind_attr_raw)]
                elif bool(bind_attr_raw) is True:
                    bind_attr_specs = [{}]

                # Determine emission records / 选择输出记录集合
                records: list[dict[str, Any]] = []
                if source == "metric_matches":
                    records = [r for r in (matches.get("metric", []) or []) if isinstance(r, dict)]
                elif source == "cfs_matches":
                    # Treat each matched cfs signal as a record, using its strength and target as match vars.
                    # 把命中的 CFS 信号当作记录：其 strength/target 会作为 match_* 变量来源。
                    records = [r for r in (matches.get("cfs", []) or []) if isinstance(r, dict)]
                else:
                    records = [{}]

                emitted = 0
                for rec in records:
                    if emitted >= max_signals:
                        break

                    local_vars = dict(vars_ctx)

                    # Fill match_* vars from record
                    if source == "metric_matches":
                        local_vars["match_value"] = float(rec.get("value", local_vars.get("match_value", 0.0)) or 0.0)
                        local_vars["match_item_id"] = str(rec.get("item_id", local_vars.get("match_item_id", "")) or "")
                        local_vars["match_ref_object_id"] = str(rec.get("ref_object_id", local_vars.get("match_ref_object_id", "")) or "")
                        local_vars["match_ref_object_type"] = str(rec.get("ref_object_type", local_vars.get("match_ref_object_type", "")) or "")
                        local_vars["match_display"] = str(rec.get("display", local_vars.get("match_display", "")) or "")
                    elif source == "cfs_matches":
                        local_vars["match_value"] = float(rec.get("strength", local_vars.get("match_value", 0.0)) or 0.0)
                        target = rec.get("target") if isinstance(rec.get("target"), dict) else {}
                        local_vars["match_item_id"] = str(target.get("target_item_id", local_vars.get("match_item_id", "")) or "")
                        local_vars["match_ref_object_id"] = str(target.get("target_ref_object_id", local_vars.get("match_ref_object_id", "")) or "")
                        local_vars["match_ref_object_type"] = str(target.get("target_ref_object_type", local_vars.get("match_ref_object_type", "")) or "")
                        local_vars["match_display"] = str(target.get("target_display", local_vars.get("match_display", "")) or "")

                strength = _resolve_cfs_strength(strength_spec, vars_ctx=local_vars)
                # Raw energy record first (pre-habituation).
                raw_energy_total += float(strength)
                strength = float(strength) * float(scale)
                if abs(float(strength)) < 1e-12:
                    # Fully suppressed by habituation: skip both emit + bind.
                    if capture_as:
                        vars_ctx[capture_as] = float(0.0)
                    continue
                target_obj: dict[str, Any] = {}
                if scope != "global":
                    t = payload.get("target") if isinstance(payload.get("target"), dict) else {}
                    t_from = str(t.get("from", "match") or "match").strip() or "match"
                    if t_from in {"match", "metric_match", "cfs_match"}:
                        target_obj = {
                            "target_ref_object_id": str(local_vars.get("match_ref_object_id", "") or ""),
                            "target_ref_object_type": str(local_vars.get("match_ref_object_type", "") or ""),
                            "target_item_id": str(local_vars.get("match_item_id", "") or ""),
                            "target_display": str(local_vars.get("match_display", "") or ""),
                        }
                    elif t_from == "specific_ref":
                        target_obj = {
                            "target_ref_object_id": str(t.get("ref_object_id", "") or ""),
                            "target_ref_object_type": str(t.get("ref_object_type", "") or ""),
                            "target_item_id": "",
                            "target_display": str(t.get("display", "") or ""),
                        }
                    elif t_from == "specific_item":
                        target_obj = {
                            "target_ref_object_id": "",
                            "target_ref_object_type": "",
                            "target_item_id": str(t.get("item_id", "") or ""),
                            "target_display": str(t.get("display", "") or ""),
                        }

                    # Best-effort: resolve a human-readable target_display from context.pool_items.
                    # 尽力从上下文 pool_items 中补全可读的 target_display（避免前端只看到 st_000123 这种 ID）。
                    try:
                        td = str(target_obj.get("target_display", "") or "").strip()
                        rid2 = str(target_obj.get("target_ref_object_id", "") or "").strip()
                        rty2 = str(target_obj.get("target_ref_object_type", "") or "").strip()
                        iid2 = str(target_obj.get("target_item_id", "") or "").strip()
                        if not td and (rid2 or iid2):
                            for it in list(context.get("pool_items", []) or []):
                                if not isinstance(it, dict):
                                    continue
                                if rid2:
                                    ref_id3 = str(it.get("ref_object_id", "") or "")
                                    ref_ty3 = str(it.get("ref_object_type", "") or "")
                                    aliases = [str(x) for x in (it.get("ref_alias_ids", []) or []) if str(x)]
                                    # Match by primary ref_id or any alias ref_id.
                                    # 同时支持主 ref_id 与别名 ref_id（语义合并后 SA/ST 可能互为别名）。
                                    hit_primary = (ref_id3 == rid2)
                                    hit_alias = (rid2 in aliases)
                                    if hit_primary:
                                        # If the target specifies a type, respect it for primary-id match.
                                        # 若目标指定了 type，则主 id 命中时仍尊重 type（防止误配）。
                                        if rty2 and ref_ty3 != rty2:
                                            continue
                                    elif not hit_alias:
                                        pass
                                    else:
                                        # Alias hit: accept even if type differs (it is the same semantic object).
                                        # 别名命中：即便 type 不同也接受（它们是同一语义对象）。
                                        pass

                                    if hit_primary or hit_alias:
                                        # Prefer real object content display, not debug detail.
                                        # 优先展示对象内容（display），不要优先用 display_detail（往往是 runtime_attrs 摘要）。
                                        td2 = str(it.get("display", "") or it.get("display_detail", "") or "").strip()
                                        if td2:
                                            target_obj["target_display"] = td2
                                            break
                                if iid2 and str(it.get("item_id", "") or "") == iid2:
                                    # Prefer real object content display, not debug detail.
                                    # 优先展示对象内容（display），不要优先用 display_detail（往往是 runtime_attrs 摘要）。
                                    td2 = str(it.get("display", "") or it.get("display_detail", "") or "").strip()
                                    if td2:
                                        target_obj["target_display"] = td2
                                        break
                            # Final fallback: use id as display (still better than empty string).
                            if not str(target_obj.get("target_display", "") or "").strip():
                                target_obj["target_display"] = rid2 or iid2
                    except Exception:
                        pass

                    if not str(target_obj.get("target_ref_object_id", "") or "") and not str(target_obj.get("target_item_id", "") or ""):
                        # Object-scoped signals need a target; skip if missing.
                        # 对象型信号必须有目标，否则跳过。
                        continue

                # Helper: bind as attribute SA (optional).
                # 帮助函数：把该认知感受以“属性刺激元（attribute SA）”绑定到目标对象上（可选）。
                def _emit_bind_attribute(*, strength_value: float) -> None:
                    if not bind_attr_specs or scope == "global":
                        return
                    # Render templates inside bind_attr_spec using local_vars.
                    # ? bind_attribute ?????????? {{{match_display}}} / {{{strength}}}??
                    lv = dict(local_vars)
                    lv["strength"] = float(strength_value)
                    lv["cfs_kind"] = str(kind)
                    for bind_index, bind_attr_spec in enumerate(bind_attr_specs):
                        rendered = _render_templates_in_data(bind_attr_spec, vars_ctx=lv)
                        rendered = rendered if isinstance(rendered, dict) else {}

                        attr_name = str(rendered.get("attribute_name", rendered.get("name", "")) or f"cfs_{kind}").strip() or f"cfs_{kind}"
                        value_from = str(rendered.get("value_from", "") or "").strip() or "strength"
                        if value_from == "match_value":
                            attr_value = float(_coerce_float_maybe(lv.get("match_value")) or 0.0)
                        else:
                            attr_value = float(strength_value)

                        raw_text = str(rendered.get("raw", "") or f"{attr_name}:{round(attr_value, 6)}")
                        display_text = str(rendered.get("display", "") or f"绑定CFS属性:{kind}:{round(attr_value, 3)}")
                        value_type = str(rendered.get("value_type", "") or "numerical")
                        modality = str(rendered.get("modality", "") or "internal")
                        er = _coerce_float_maybe(rendered.get("er", 0.0))
                        ev = _coerce_float_maybe(rendered.get("ev", 0.0))
                        reason_text = str(rendered.get("reason", "") or f"iesm_cfs_bind:{kind}:{rule_id}").strip()

                        out_pool_effects.append(
                            {
                                "effect_type": "pool_bind_attribute",
                                "effect_id": f"pba_cfs_{rule_id}_{now_ms}_{idx}_{emitted}_{bind_index}",
                                "created_at": int(now_ms),
                                "trace_id": str(trace_id or ""),
                                "tick_id": str(tick_id or ""),
                                "rule_id": str(rule_id or ""),
                                "rule_title": str(rule_title or ""),
                                "rule_phase": str(rule_phase or ""),
                                "rule_priority": int(rule_priority),
                                "spec": {
                                    "target_item_id": str(target_obj.get("target_item_id", "") or ""),
                                    "ref_object_id": str(target_obj.get("target_ref_object_id", "") or ""),
                                    "ref_object_type": str(target_obj.get("target_ref_object_type", "") or ""),
                                    "attribute": {
                                        "attribute_name": attr_name,
                                        "attribute_value": float(attr_value),
                                        "raw": raw_text,
                                        "display": display_text,
                                        "value_type": value_type,
                                        "modality": modality,
                                        "er": float(er or 0.0),
                                        "ev": float(ev or 0.0),
                                    },
                                    "reason": reason_text,
                                },
                            }
                        )

                if strength < float(min_strength):
                    # Softly suppressed: keep the bound attribute (if any) refreshed, but skip event emission.
                    if bind_attr_specs and scope != "global":
                        _emit_bind_attribute(strength_value=float(strength))
                    if capture_as:
                        vars_ctx[capture_as] = float(strength)
                    continue

                # Emit gating / 输出门控（避免每 tick 重复刷屏）
                # ------------------------------------------------
                # 设计目标（对齐理论与可用性需求）：我们可以“每 tick 都计算”，但不必“每 tick 都输出一条 CFS 事件”。
                # - 对人类验收：减少前端刷屏，突出真正变化
                # - 对系统：仍保持持续检测（强度变化会推动输出；绑定属性可持续刷新）
                raw_payload = raw_spec if isinstance(raw_spec, dict) else {}
                emit_gate_raw = raw_payload.get("emit_gate", raw_payload.get("gate"))
                emit_gate = dict(emit_gate_raw) if isinstance(emit_gate_raw, dict) else None
                skip_emit = False
                if emit_gate:
                    mode2 = str(emit_gate.get("mode", "strength_delta") or "strength_delta").strip() or "strength_delta"
                    min_delta2 = _coerce_float_maybe(emit_gate.get("min_delta", emit_gate.get("epsilon", 0.0)))
                    min_delta2_f = float(min_delta2 or 0.0)
                    min_interval2 = _coerce_int_maybe(emit_gate.get("min_interval_ticks", emit_gate.get("min_interval", 0)))
                    min_interval2_i = max(0, int(min_interval2 or 0))
                    key_by2 = str(emit_gate.get("key_by", "rule_kind_target") or "rule_kind_target").strip() or "rule_kind_target"
                    also_bind = bool(emit_gate.get("bind_attribute_even_when_skipped", emit_gate.get("also_bind_attribute", True)))

                    # Build a stable gate key.
                    # 构造稳定 gate key：默认按 rule+kind+target 去重。
                    tkey = "global"
                    if scope != "global":
                        tkey = str(target_obj.get("target_ref_object_id", "") or target_obj.get("target_item_id", "") or "")
                    if key_by2 in {"rule_kind", "rule+kind"}:
                        gate_key = f"{rule_id}::{kind}"
                    elif key_by2 in {"kind_target", "kind+target"}:
                        gate_key = f"{kind}::{tkey}"
                    elif key_by2 in {"kind"}:
                        gate_key = f"{kind}"
                    else:
                        gate_key = f"{rule_id}::{kind}::{tkey}"

                    gate_store = runtime_state.setdefault("cfs_emit_gate", {})
                    if not isinstance(gate_store, dict):
                        gate_store = {}
                        runtime_state["cfs_emit_gate"] = gate_store

                    last = gate_store.get(gate_key) if isinstance(gate_store.get(gate_key), dict) else None
                    if last:
                        last_tick = int(last.get("tick_index", -999999) or -999999)
                        last_strength = float(_coerce_float_maybe(last.get("strength", 0.0)) or 0.0)
                        if min_interval2_i > 0 and (int(tick_index) - last_tick) < min_interval2_i:
                            skip_emit = True
                        elif mode2 in {"strength_delta", "delta", "strength_change", "changed"}:
                            if abs(float(strength) - float(last_strength)) < float(min_delta2_f):
                                skip_emit = True

                    if skip_emit:
                        # Even when gated, we can still refresh the bound attribute to keep the state "alive".
                        # 即便门控跳过事件输出，也可以继续刷新绑定属性，保持“感受存在”的运行态语义。
                        if also_bind:
                            _emit_bind_attribute(strength_value=float(strength))
                        # Optional: still expose computed strength as a variable.
                        if capture_as:
                            vars_ctx[capture_as] = float(strength)
                        continue

                sig = {
                    "kind": kind,
                    "scope": "global" if scope == "global" else "object",
                    "strength": round(float(strength), 8),
                    "target": target_obj,
                    "created_at": int(now_ms),
                    "trace_id": str(trace_id or ""),
                    "tick_id": str(tick_id or ""),
                    "rule_id": str(rule_id or ""),
                    "rule_title": str(rule_title or ""),
                    "rule_phase": str(rule_phase or ""),
                    "rule_priority": int(rule_priority),
                    "reasons": reasons,
                    "evidence": dict(evidence) if isinstance(evidence, dict) else {},
                }

                runtime_cfs_signals.append(sig)
                out_emitted_cfs_signals.append(sig)
                emitted += 1

                # Bind as attribute SA (optional).
                # 绑定为属性刺激元（可选）。
                _emit_bind_attribute(strength_value=float(strength))

                # Update gate store only when actually emitted.
                # 仅在真正输出事件时更新 gate store（否则无法累积变化触发下一次输出）。
                if emit_gate:
                    try:
                        gate_store[gate_key] = {"tick_index": int(tick_index), "strength": float(strength)}
                    except Exception:
                        pass

                # Optional: expose computed strength as a variable for subsequent actions.
                # 可选：把计算后的强度注册为变量，供同一条规则后续动作使用。
                if capture_as:
                    vars_ctx[capture_as] = float(strength)

                continue

            if key == "pool_energy":
                payload = spec if isinstance(spec, dict) else {}
                # Try to scale common numeric delta fields only (do not touch selectors/text).
                for k in ["delta_er", "delta_ev", "delta_energy", "delta_cp", "delta_cp_abs"]:
                    if k in payload:
                        v0 = _coerce_float_maybe(payload.get(k))
                        if v0 is None:
                            continue
                        raw_energy_total += abs(float(v0))
                        payload[k] = round(float(v0) * float(scale), 8)
                out_pool_effects.append(
                    {
                        "effect_type": "pool_energy",
                        "effect_id": f"pe_{rule_id}_{now_ms}_{idx}",
                        "created_at": int(now_ms),
                        "trace_id": str(trace_id or ""),
                        "tick_id": str(tick_id or ""),
                        "rule_id": str(rule_id or ""),
                        "rule_title": str(rule_title or ""),
                        "rule_phase": str(rule_phase or ""),
                        "rule_priority": int(rule_priority),
                        "spec": dict(payload),
                    }
                )
                continue

            if key == "pool_bind_attribute":
                payload = spec if isinstance(spec, dict) else {}
                # Scale attribute_value if present (soft attenuation).
                try:
                    attr = payload.get("attribute") if isinstance(payload.get("attribute"), dict) else None
                    if attr is not None:
                        attr2 = dict(attr)
                        if "attribute_value" in attr2:
                            v0 = _coerce_float_maybe(attr2.get("attribute_value"))
                            if v0 is not None:
                                raw_energy_total += abs(float(v0))
                                attr2["attribute_value"] = round(float(v0) * float(scale), 8)
                        if "er" in attr2:
                            v0 = _coerce_float_maybe(attr2.get("er"))
                            if v0 is not None:
                                attr2["er"] = round(float(v0) * float(scale), 8)
                        if "ev" in attr2:
                            v0 = _coerce_float_maybe(attr2.get("ev"))
                            if v0 is not None:
                                attr2["ev"] = round(float(v0) * float(scale), 8)
                        payload["attribute"] = attr2
                except Exception:
                    pass
                out_pool_effects.append(
                    {
                        "effect_type": "pool_bind_attribute",
                        "effect_id": f"pba_{rule_id}_{now_ms}_{idx}",
                        "created_at": int(now_ms),
                        "trace_id": str(trace_id or ""),
                        "tick_id": str(tick_id or ""),
                        "rule_id": str(rule_id or ""),
                        "rule_title": str(rule_title or ""),
                        "rule_phase": str(rule_phase or ""),
                        "rule_priority": int(rule_priority),
                        "spec": dict(payload),
                    }
                )
                continue

            if key == "delay":
                d = spec if isinstance(spec, dict) else {}
                ticks = _coerce_int_maybe(d.get("ticks"))
                ticks = int(ticks or 1)
                ticks = max(1, min(10_000, ticks))
                then_actions = list(d.get("then", []) or [])
                then_actions = then_actions if all(isinstance(x, dict) for x in then_actions) else []

                if not provided_tick_index:
                    out_audit_notes.append(f"[IESM] delay ignored (tick_index not provided): rule_id={rule_id}")
                    continue

                # Capture current variables by rendering templates now.
                # 延时动作捕获当前变量：此处先把模板渲染为确定值再入队，避免后续 tick 值漂移。
                captured_then = _render_templates_in_data(then_actions, vars_ctx=vars_ctx)
                if not isinstance(captured_then, list):
                    captured_then = []

                due_tick = int(tick_index) + int(ticks)
                scheduled = _scheduled_actions_list(runtime_state)
                scheduled.append(
                    {
                        "due_tick": due_tick,
                        "created_at": int(now_ms),
                        "rule_id": str(rule_id or ""),
                        "rule_title": str(rule_title or ""),
                        "rule_phase": str(rule_phase or ""),
                        "rule_priority": int(rule_priority),
                        "actions": captured_then,
                        "vars_ctx": dict(vars_ctx),
                    }
                )
                # Bound schedule size.
                # 控制队列规模：避免规则误配置导致内存膨胀。
                if len(scheduled) > _MAX_SCHEDULED_ACTIONS:
                    scheduled.sort(key=lambda e: (int(e.get("due_tick", 0) or 0), int(e.get("created_at", 0) or 0)))
                    dropped = len(scheduled) - _MAX_SCHEDULED_ACTIONS
                    scheduled = scheduled[-_MAX_SCHEDULED_ACTIONS :]
                    out_audit_notes.append(f"[IESM] scheduled_actions pruned: dropped={dropped}")
                _set_scheduled_actions_list(runtime_state, scheduled)
                out_audit_notes.append(f"[IESM] delay scheduled: rule_id={rule_id} ticks={ticks} due_tick={due_tick}")
                continue

            if key == "branch":
                # IMPORTANT / 重要：
                # - branch 的 then/else/on_error 动作列表必须使用“原始 raw_spec”，不能使用已经模板渲染过的 spec。
                #   原因：branch 外层会先对整个动作 dict 做一次模板渲染（spec=_render_templates_in_data），
                #   但 branch 内部的动作（尤其是 cfs_emit.bind_attribute.display 里的 {{{strength}}}）需要在
                #   “每条记录/每次计算”时再渲染，否则会把 {{{strength}}} 过早替换成空字符串，导致前端出现：
                #     "压力不验:"（没有数值）
                #
                # - 因此：branch 的条件 when_expr 使用 spec（允许引用当前 vars_ctx 的模板），
                #   但动作列表本身必须用 raw_b 中的原始结构，交给递归 _execute_actions 在执行时再渲染。
                raw_b = raw_spec if isinstance(raw_spec, dict) else {}
                b = spec if isinstance(spec, dict) else {}
                when_expr = b.get("when") or raw_b.get("when") or {}
                then_actions = list(raw_b.get("then", []) or [])
                else_actions = list(raw_b.get("else", []) or [])
                on_error_actions = list(raw_b.get("on_error", []) or [])

                try:
                    ok, m2, _reasons = _eval_when(
                        when_expr,
                        # Use the current runtime CFS list so branches can observe newly emitted signals.
                        # 使用当前运行态 CFS 列表：让 branch 能看到本 tick 新生成的感受信号。
                        cfs_signals=runtime_cfs_signals,
                        state_windows=list(matches.get("state_window", []) or []) if isinstance(matches.get("state_window"), list) else [],
                        tick_index=int(tick_index),
                        allow_timer=bool(allow_timer),
                        context=context,
                        runtime_state=runtime_state,
                        provided_tick_index=provided_tick_index,
                    )
                except Exception as exc:
                    out_audit_notes.append(f"[IESM] branch when error: {exc}")
                    raw_energy_total += _execute_actions(
                        actions=on_error_actions,
                        rule_id=rule_id,
                        rule_title=rule_title,
                        rule_phase=rule_phase,
                        rule_priority=rule_priority,
                        trace_id=trace_id,
                        tick_id=tick_id,
                        tick_index=tick_index,
                        now_ms=now_ms,
                        context=context,
                        runtime_state=runtime_state,
                        provided_tick_index=provided_tick_index,
                        allow_timer=allow_timer,
                        matches=matches,
                        vars_ctx=vars_ctx,
                        focus_defaults=focus_defaults,
                        runtime_cfs_signals=runtime_cfs_signals,
                        out_emitted_cfs_signals=out_emitted_cfs_signals,
                        out_triggered_scripts=out_triggered_scripts,
                        out_focus_directives=out_focus_directives,
                        out_emotion_updates=out_emotion_updates,
                        out_action_triggers=out_action_triggers,
                        out_pool_effects=out_pool_effects,
                        out_audit_notes=out_audit_notes,
                        depth=depth + 1,
                        effect_scale=float(scale),
                    )
                    continue

                if ok:
                    merged = _empty_matches()
                    _merge_matches(merged, matches)
                    _merge_matches(merged, m2)
                    merged_vars = merged.get("vars", {}) if isinstance(merged.get("vars"), dict) else dict(vars_ctx)
                    raw_energy_total += _execute_actions(
                        actions=then_actions,
                        rule_id=rule_id,
                        rule_title=rule_title,
                        rule_phase=rule_phase,
                        rule_priority=rule_priority,
                        trace_id=trace_id,
                        tick_id=tick_id,
                        tick_index=tick_index,
                        now_ms=now_ms,
                        context=context,
                        runtime_state=runtime_state,
                        provided_tick_index=provided_tick_index,
                        allow_timer=allow_timer,
                        matches=merged,
                        vars_ctx=dict(merged_vars),
                        focus_defaults=focus_defaults,
                        runtime_cfs_signals=runtime_cfs_signals,
                        out_emitted_cfs_signals=out_emitted_cfs_signals,
                        out_triggered_scripts=out_triggered_scripts,
                        out_focus_directives=out_focus_directives,
                        out_emotion_updates=out_emotion_updates,
                        out_action_triggers=out_action_triggers,
                        out_pool_effects=out_pool_effects,
                        out_audit_notes=out_audit_notes,
                        depth=depth + 1,
                        effect_scale=float(scale),
                    )
                else:
                    raw_energy_total += _execute_actions(
                        actions=else_actions,
                        rule_id=rule_id,
                        rule_title=rule_title,
                        rule_phase=rule_phase,
                        rule_priority=rule_priority,
                        trace_id=trace_id,
                        tick_id=tick_id,
                        tick_index=tick_index,
                        now_ms=now_ms,
                        context=context,
                        runtime_state=runtime_state,
                        provided_tick_index=provided_tick_index,
                        allow_timer=allow_timer,
                        matches=matches,
                        vars_ctx=vars_ctx,
                        focus_defaults=focus_defaults,
                        runtime_cfs_signals=runtime_cfs_signals,
                        out_emitted_cfs_signals=out_emitted_cfs_signals,
                        out_triggered_scripts=out_triggered_scripts,
                        out_focus_directives=out_focus_directives,
                        out_emotion_updates=out_emotion_updates,
                        out_action_triggers=out_action_triggers,
                        out_pool_effects=out_pool_effects,
                        out_audit_notes=out_audit_notes,
                        depth=depth + 1,
                        effect_scale=float(scale),
                    )
                continue

            if key == "log":
                msg = str(spec or "").strip()
                if msg:
                    out_audit_notes.append(f"[IESM:{rule_id}] {msg}")
                continue

            # Unknown action type: keep it as an audit note only.
            # 未知动作：仅记录审计信息（不执行）。
            out_audit_notes.append(f"[IESM] unknown action type ignored: {key} (rule_id={rule_id})")
        except Exception as exc:
            out_audit_notes.append(f"[IESM] action error: key={key} rule_id={rule_id} err={exc}")

    return float(raw_energy_total)


def _coerce_float_maybe(value: Any) -> float | None:
    """Try coerce to float; return None if not possible / 尝试转 float，失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _coerce_int_maybe(value: Any) -> int | None:
    """Try coerce to int; return None if not possible / 尝试转 int，失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if abs(value - round(value)) < 1e-9:
            return int(round(value))
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(s)
        except Exception:
            return None
    return None


def _numeric_compare(
    *,
    value: float,
    op: str,
    threshold: Any = None,
    vmin: Any = None,
    vmax: Any = None,
    epsilon: float = 1e-9,
) -> bool:
    """Numeric comparison helper / 数值比较工具。"""
    op = str(op or ">=").strip()
    if op == "exists":
        return True
    if op == "changed":
        return abs(float(value)) > float(epsilon or 0.0)

    if op == "between":
        lo = _coerce_float_maybe(vmin)
        hi = _coerce_float_maybe(vmax)
        if lo is None or hi is None:
            return False
        return float(lo) <= float(value) <= float(hi)

    th = _coerce_float_maybe(threshold)
    if th is None:
        return False
    th = float(th)
    v = float(value)

    if op == ">=":
        return v >= th
    if op == ">":
        return v > th
    if op == "<=":
        return v <= th
    if op == "<":
        return v < th
    if op == "==":
        return abs(v - th) <= float(epsilon or 0.0)
    if op == "!=":
        return abs(v - th) > float(epsilon or 0.0)
    return False


def _freeze_for_cache(value: Any) -> Any:
    """Convert nested selector data into a hashable cache key fragment."""
    if isinstance(value, dict):
        return tuple((str(k), _freeze_for_cache(v)) for k, v in sorted(value.items(), key=lambda kv: str(kv[0])))
    if isinstance(value, (list, tuple, set)):
        return tuple(_freeze_for_cache(v) for v in value)
    if isinstance(value, float):
        return round(float(value), 12)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return repr(value)


def _selector_cache_stats(context: dict[str, Any]) -> dict[str, int]:
    stats = context.get(_SELECTOR_CACHE_STATS_KEY)
    if not isinstance(stats, dict):
        stats = {"hit": 0, "miss": 0}
        context[_SELECTOR_CACHE_STATS_KEY] = stats
    return stats  # type: ignore[return-value]


def _selector_cache_token(context: dict[str, Any], items_raw: Any) -> tuple[Any, ...]:
    if isinstance(items_raw, list):
        try:
            first = ""
            last = ""
            if items_raw:
                first0 = items_raw[0]
                last0 = items_raw[-1]
                if isinstance(first0, dict):
                    first = str(first0.get("item_id", "") or "")
                if isinstance(last0, dict):
                    last = str(last0.get("item_id", "") or "")
            return (id(items_raw), len(items_raw), first, last)
        except Exception:
            return (id(items_raw), len(items_raw))
    return (id(items_raw), 0)


# ----------------------------------------------------------------------
# Selector / 选择器
# ----------------------------------------------------------------------


def _select_pool_items(*, context: dict[str, Any], selector: dict[str, Any] | None) -> list[dict[str, Any]]:
    """
    Select items from context.pool_items.
    从 context.pool_items 里按 selector 选取对象列表。

    selector 约定（原型）：
      - mode: all/specific_ref/specific_item/contains_text/top_n
      - ref_object_id/ref_object_type/item_id/contains_text/top_n/ref_object_types(list)
      - mode: has_attribute / has_packet_attribute / has_runtime_attribute / has_bound_attribute
        - attribute_name: 单个属性名（例如 "reward_signal" / "punish_signal" / "cfs_dissonance"）
        - attribute_names: 多个属性名（默认满足“任一”即可命中）
        - scope: runtime/packet/all（属性来源口径）
          - runtime: 运行态绑定属性（IESM/time_sensor 等绑定到对象上的属性）
          - packet: 记忆/结构侧属性（来自 stimulus_packet / memory_feedback / 结构投影中携带的属性）
          - all: 二者并集（用于“既看体验也看记忆”的规则）
        - require_all: true/false（可选；true 表示必须全部属性都存在）
    """
    raw_items = context.get("pool_items", []) or []
    cache_key = (
        _selector_cache_token(context, raw_items),
        _freeze_for_cache(selector) if isinstance(selector, dict) else None,
    )
    cache = context.get(_SELECTOR_CACHE_KEY)
    if isinstance(cache, dict) and cache_key in cache:
        _selector_cache_stats(context)["hit"] = int(_selector_cache_stats(context).get("hit", 0) or 0) + 1
        return list(cache.get(cache_key) or [])

    _selector_cache_stats(context)["miss"] = int(_selector_cache_stats(context).get("miss", 0) or 0) + 1

    items = list(raw_items)
    items = [it for it in items if isinstance(it, dict)]

    # Context-only pseudo types should be opt-in; otherwise they can accidentally match
    # unrelated selector.contains_text rules.
    # 上下文伪类型默认不参与 selector 匹配，必须显式 ref_object_types 才允许。
    context_only_types = {"input"}

    def _store_result(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cache2 = context.get(_SELECTOR_CACHE_KEY)
        if isinstance(cache2, dict):
            if len(cache2) > 256:
                cache2.clear()
            cache2[cache_key] = list(rows)
        return rows

    if not selector or not isinstance(selector, dict):
        return _store_result([it for it in items if str(it.get("ref_object_type", "")) not in context_only_types])

    mode = str(selector.get("mode", "all") or "all").strip()

    # Optional type filter / 可选类型过滤
    ref_types = selector.get("ref_object_types")
    if isinstance(ref_types, list):
        allow_types = {str(x) for x in ref_types if str(x)}
        if allow_types:
            items = [it for it in items if str(it.get("ref_object_type", "")) in allow_types]
        else:
            # Explicitly provided an empty list: keep default behavior (exclude context-only).
            items = [it for it in items if str(it.get("ref_object_type", "")) not in context_only_types]
    else:
        # No type filter: exclude context-only types by default.
        items = [it for it in items if str(it.get("ref_object_type", "")) not in context_only_types]

    # Optional numeric filters / 可选数值过滤（selector.where）
    # ---------------------------------------------------------
    # Motivation / 动机：
    # - 规则 when.metric 本身一次只能对“一个指标”做阈值判断；
    # - 但实际工程里我们经常需要在“选对象”时加入额外约束，例如：
    #     - 惊（surprise）必须满足 CP>0（ER>EV），否则 EV 侧突增会误报
    # - 因此 selector 提供轻量 where 过滤：它不改变 metric 的 value，只缩小候选对象集合。
    #
    # Shape / 形态：
    #   selector:
    #     mode: top_n
    #     where:
    #       cp_delta: {op: '>=', value: 0.3}
    #       delta_er: {op: '>=', value: 0.5}
    where = selector.get("where", selector.get("filters"))
    if isinstance(where, dict) and where:
        filtered: list[dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            ok = True
            for field, cond in where.items():
                f = str(field or "").strip()
                if not f:
                    continue
                if isinstance(cond, dict):
                    op = str(cond.get("op", ">=") or ">=").strip()
                    thr = cond.get("value")
                    vmin = cond.get("min")
                    vmax = cond.get("max")
                    eps = _coerce_float_maybe(cond.get("epsilon", 1e-9))
                    eps_f = float(eps if eps is not None else 1e-9)
                else:
                    # Shorthand: where: {cp_delta: 0.3} means cp_delta >= 0.3
                    # 便捷写法：where: {cp_delta: 0.3} 等价于 cp_delta >= 0.3
                    op = ">="
                    thr = cond
                    vmin = None
                    vmax = None
                    eps_f = 1e-9

                v = _coerce_float_maybe(it.get(f))
                if v is None:
                    ok = False
                    break
                if not _numeric_compare(value=float(v), op=op, threshold=thr, vmin=vmin, vmax=vmax, epsilon=eps_f):
                    ok = False
                    break
            if ok:
                filtered.append(it)
        items = filtered

    if mode in {"all", "any"}:
        return _store_result(items)

    if mode == "specific_item":
        item_id = str(selector.get("item_id", "") or "").strip()
        if not item_id:
            return []
        return _store_result([it for it in items if str(it.get("item_id", "")) == item_id])

    if mode == "specific_ref":
        ref_id = str(selector.get("ref_object_id", "") or "").strip()
        ref_type = str(selector.get("ref_object_type", "") or "").strip()
        if not ref_id:
            return []
        out = [it for it in items if str(it.get("ref_object_id", "")) == ref_id]
        if ref_type:
            out = [it for it in out if str(it.get("ref_object_type", "")) == ref_type]
        return _store_result(out)

    if mode == "contains_text":
        needle = str(selector.get("contains_text", "") or "").strip()
        if not needle:
            return []
        needle_low = needle.lower()
        out: list[dict[str, Any]] = []
        for it in items:
            hay = " ".join(
                [
                    str(it.get("display", "") or ""),
                    str(it.get("display_detail", "") or ""),
                    " ".join(str(x) for x in (it.get("attribute_displays", []) or []) if str(x)),
                    " ".join(str(x) for x in (it.get("feature_displays", []) or []) if str(x)),
                    " ".join(str(x) for x in (it.get("bound_attribute_displays", []) or []) if str(x)),
                ]
            )
            if needle in hay or needle_low in hay.lower():
                out.append(it)
        return _store_result(out)

    if mode in {
        "has_bound_attribute",
        "has_bound_attr",
        "has_attr",
        "has_attribute",
        "has_packet_attribute",
        "has_runtime_attribute",
        "has_any_attribute",
    }:
        # Prefer stable key lists (attribute_names), NOT display text.
        # 优先使用稳定键列表（*_attribute_names），不要用 display 文本（翻译/格式变化会让规则变脆）。
        names = selector.get("attribute_names", selector.get("names"))
        if isinstance(names, list):
            want = [str(x).strip() for x in names if str(x).strip()]
        else:
            one = str(selector.get("attribute_name", selector.get("name", "")) or "").strip()
            want = [one] if one else []
        want = [x for x in want if x]
        if not want:
            return []

        # scope / 口径：
        # - legacy: has_bound_attribute / has_attr 默认 = runtime（历史兼容）
        # - has_packet_attribute 默认 = packet
        # - has_any_attribute 默认 = all
        scope = str(selector.get("scope", "") or "").strip().lower()
        if not scope:
            if mode == "has_packet_attribute":
                scope = "packet"
            elif mode == "has_any_attribute":
                scope = "all"
            else:
                scope = "runtime"
        if scope in {"learned", "memory", "structure"}:
            # 方便写法：learned/memory/structure 都视作 packet 口径
            scope = "packet"

        # require_all / 是否必须全部存在
        require_all = bool(selector.get("require_all", False) or selector.get("all", False))

        def _get_name_list(row: dict[str, Any]) -> list[str]:
            if not isinstance(row, dict):
                return []
            if scope == "packet":
                lst = row.get("packet_attribute_names", [])
                return lst if isinstance(lst, list) else []
            if scope == "all":
                lst = row.get("all_attribute_names", [])
                if isinstance(lst, list) and lst:
                    return lst
                # Fallback / 兜底：没有 all_attribute_names 时，用 packet+runtime 拼起来
                a = row.get("packet_attribute_names", [])
                b = row.get("runtime_attribute_names", row.get("bound_attribute_names", []))
                a = a if isinstance(a, list) else []
                b = b if isinstance(b, list) else []
                return list(dict.fromkeys([*(str(x) for x in a if str(x)), *(str(x) for x in b if str(x))]))
            # runtime (default)
            lst = row.get("runtime_attribute_names", row.get("bound_attribute_names", []))
            return lst if isinstance(lst, list) else []

        out: list[dict[str, Any]] = []
        want_set = {str(x) for x in want if str(x)}
        for it in items:
            have_list = _get_name_list(it)
            have_set = {str(x).strip() for x in have_list if str(x).strip()}
            if require_all:
                if want_set.issubset(have_set):
                    out.append(it)
            else:
                if have_set & want_set:
                    out.append(it)
        return _store_result(out)

    if mode == "top_n":
        top_n = _coerce_int_maybe(selector.get("top_n", 8))
        top_n = max(1, int(top_n or 8))
        rows = list(items)
        rows.sort(key=lambda it: float(it.get("total_energy", 0.0) or 0.0), reverse=True)
        return _store_result(rows[:top_n])

    return _store_result(items)


# ----------------------------------------------------------------------
# History / 历史记账（用于变化量/变化率）
# ----------------------------------------------------------------------


def _metric_history_store(runtime_state: dict[str, Any]) -> dict[str, dict[int, float]]:
    """
    Return the metric history store.

    Storage format (memory friendly, O(1) lookup):
      metric_history: { series_key: {tick_index: value} }
    """
    store = runtime_state.setdefault("metric_history", {})
    if not isinstance(store, dict):
        store = {}
        runtime_state["metric_history"] = store
    return store  # type: ignore[return-value]


def _update_metric_history(*, runtime_state: dict[str, Any], tick_index: int, context: dict[str, Any]) -> None:
    """
    Record a subset of metrics each tick for delta/avg_rate.
    每 tick 记录一部分指标，用于 delta/avg_rate 的计算。

    NOTE:
    - Keep it bounded by pruning old ticks.
    - 控制体积：按 tick 维度裁剪历史。
    """
    store = _metric_history_store(runtime_state)
    max_keep = 12  # 原型默认保留最近 N tick，可后续做成可配置
    min_tick = int(tick_index) - int(max_keep)

    def put(series_key: str, value: float) -> None:
        if not series_key:
            return
        series = store.get(series_key)
        if not isinstance(series, dict):
            series = {}
            store[series_key] = series
        series[int(tick_index)] = float(value)
        # prune old ticks
        for t in list(series.keys()):
            try:
                if int(t) < min_tick:
                    series.pop(t, None)
            except Exception:
                series.pop(t, None)

    pool = context.get("pool", {}) if isinstance(context.get("pool", {}), dict) else {}
    put("pool.total_er", float(pool.get("total_er", 0.0) or 0.0))
    put("pool.total_ev", float(pool.get("total_ev", 0.0) or 0.0))
    put("pool.total_energy", float(pool.get("total_energy", 0.0) or 0.0))
    put("pool.item_count", float(pool.get("item_count", 0.0) or 0.0))
    put("pool.total_cp_delta", float(pool.get("total_cp_delta", 0.0) or 0.0))
    put("pool.total_cp_abs", float(pool.get("total_cp_abs", 0.0) or 0.0))
    put("pool.energy_concentration", float(pool.get("energy_concentration", 0.0) or 0.0))

    cam = context.get("cam", {}) if isinstance(context.get("cam", {}), dict) else {}
    if "size" in cam:
        put("cam.size", float(cam.get("size", 0.0) or 0.0))
    if "energy_concentration" in cam:
        put("cam.energy_concentration", float(cam.get("energy_concentration", 0.0) or 0.0))

    ma = context.get("memory_activation", {}) if isinstance(context.get("memory_activation", {}), dict) else {}
    if "item_count" in ma:
        put("memory_activation.item_count", float(ma.get("item_count", 0.0) or 0.0))
    if "total_ev" in ma:
        put("memory_activation.total_ev", float(ma.get("total_ev", 0.0) or 0.0))

    emotion = context.get("emotion", {}) if isinstance(context.get("emotion", {}), dict) else {}
    nt = emotion.get("nt", {}) if isinstance(emotion.get("nt", {}), dict) else {}
    for ch, v in nt.items():
        try:
            put(f"emotion.nt.{str(ch)}", float(v))
        except Exception:
            continue
    if "rwd" in emotion:
        put("emotion.rwd", float(emotion.get("rwd", 0.0) or 0.0))
    if "pun" in emotion:
        put("emotion.pun", float(emotion.get("pun", 0.0) or 0.0))

    stimulus = context.get("stimulus", {}) if isinstance(context.get("stimulus", {}), dict) else {}
    for key, raw_value in stimulus.items():
        metric_key = str(key or "").strip()
        if not metric_key:
            continue
        value = _coerce_float_maybe(raw_value)
        if value is None:
            continue
        put(f"stimulus.{metric_key}", float(value))

    retrieval = context.get("retrieval", {}) if isinstance(context.get("retrieval", {}), dict) else {}
    stim = retrieval.get("stimulus", {}) if isinstance(retrieval.get("stimulus", {}), dict) else {}
    if "best_match_score" in stim:
        put("retrieval.stimulus.best_match_score", float(stim.get("best_match_score", 0.0) or 0.0))
    struct = retrieval.get("structure", {}) if isinstance(retrieval.get("structure", {}), dict) else {}
    if "best_match_score" in struct:
        put("retrieval.structure.best_match_score", float(struct.get("best_match_score", 0.0) or 0.0))

    # item-level values
    for it in list(context.get("pool_items", []) or []):
        if not isinstance(it, dict):
            continue
        item_id = str(it.get("item_id", "") or "")
        if not item_id:
            continue
        try:
            put(f"item::{item_id}::er", float(it.get("er", 0.0) or 0.0))
            put(f"item::{item_id}::ev", float(it.get("ev", 0.0) or 0.0))
            put(f"item::{item_id}::total_energy", float(it.get("total_energy", 0.0) or 0.0))
            put(f"item::{item_id}::cp_delta", float(it.get("cp_delta", 0.0) or 0.0))
            put(f"item::{item_id}::cp_abs", float(it.get("cp_abs", 0.0) or 0.0))
            put(f"item::{item_id}::fatigue", float(it.get("fatigue", 0.0) or 0.0))
            put(f"item::{item_id}::recency_gain", float(it.get("recency_gain", 0.0) or 0.0))
        except Exception:
            continue


def _history_value_at(store: dict[str, dict[int, float]], *, series_key: str, tick: int) -> float | None:
    series = store.get(series_key)
    if not isinstance(series, dict):
        return None
    v = series.get(int(tick))
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _series_delta(*, store: dict[str, dict[int, float]], series_key: str, tick_index: int, window_ticks: int) -> float | None:
    """Return delta between current tick and tick-window back / 返回当前与 N tick 前的差值。"""
    cur = _history_value_at(store, series_key=series_key, tick=tick_index)
    prev = _history_value_at(store, series_key=series_key, tick=tick_index - int(window_ticks))
    if cur is None or prev is None:
        return None
    return float(cur) - float(prev)


def _series_delta_with_recent_span(
    *,
    store: dict[str, dict[int, float]],
    series_key: str,
    tick_index: int,
    window_ticks: int,
) -> tuple[float | None, int]:
    """
    Best-effort delta using the widest available span inside the recent window.
    在最近窗口内尽量使用“可获得的最宽时间跨度”计算 delta。

    Why / 目的：
    - item 级对象在真实运行中可能不会每一拍都存在；
    - expectation/pressure 的 verified 分支更适合读取“最近几拍内可见的平均变化率”，
      而不是强依赖“恰好 N tick 前必须有样本”。
    """
    span = max(1, int(window_ticks or 1))
    cur = _history_value_at(store, series_key=series_key, tick=tick_index)
    if cur is None:
        return None, span
    prev = _history_value_at(store, series_key=series_key, tick=tick_index - span)
    if prev is not None:
        return float(cur) - float(prev), span
    series = store.get(series_key)
    if not isinstance(series, dict) or not series:
        return None, span
    lower_tick = int(tick_index) - span
    candidate_ticks: list[int] = []
    for raw_tick in series.keys():
        try:
            parsed = int(raw_tick)
        except Exception:
            continue
        if lower_tick <= parsed < int(tick_index):
            candidate_ticks.append(parsed)
    if not candidate_ticks:
        return None, span
    prev_tick = min(candidate_ticks)
    prev2 = _history_value_at(store, series_key=series_key, tick=prev_tick)
    if prev2 is None:
        return None, span
    actual_span = max(1, int(tick_index) - int(prev_tick))
    return float(cur) - float(prev2), actual_span


def _metric_series_key_for_item(item_id: str, metric_tail: str) -> str:
    tail = str(metric_tail or "").strip()
    return f"item::{str(item_id)}::{tail}"


def _eval_metric_when(
    *,
    spec: dict[str, Any],
    tick_index: int,
    context: dict[str, Any],
    runtime_state: dict[str, Any],
    provided_tick_index: bool,
) -> tuple[bool, dict[str, Any], list[dict[str, str]]]:
    """Evaluate metric when / 执行 metric 条件。"""
    store = _metric_history_store(runtime_state)

    preset = resolve_metric_preset_name(str(spec.get("preset", "") or ""))
    metric = str(spec.get("metric", "") or "").strip()
    mode = str(spec.get("mode", "state") or "state").strip()
    op = str(spec.get("op", ">=") or ">=").strip()
    match_policy = str(spec.get("match_policy", "any") or "any").strip()
    window_ticks = int(spec.get("window_ticks", 4) or 4)
    window_ticks = max(1, window_ticks)
    epsilon = float(spec.get("epsilon", 1e-9) or 1e-9)
    selector = spec.get("selector") if isinstance(spec.get("selector"), dict) else None
    capture_as = str(spec.get("capture_as", "") or "").strip()
    prev_gate = spec.get("prev_gate") if isinstance(spec.get("prev_gate"), dict) else None

    # Apply preset mapping / 应用预设映射
    if preset:
        mapped = _METRIC_PRESET_MAP.get(preset)
        if not mapped:
            return False, {}, [{"zh": f"metric: 未知 preset={preset}", "en": f"metric: unknown preset={preset}"}]
        metric = str(mapped.get("metric", metric) or metric)
        mode = str(mapped.get("mode", mode) or mode)
        if "window_ticks" in mapped and not spec.get("window_ticks"):
            window_ticks = int(mapped.get("window_ticks", window_ticks) or window_ticks)
        # Some presets provide a better default operator (e.g. nt_changed -> op=changed).
        # 某些预设提供更贴合语义的默认操作符（例如 nt_changed 默认 op=changed）。
        if "op" in mapped:
            # Heuristic: only override when user didn't specify a threshold.
            # 启发式：仅在用户没有填写阈值/区间时覆盖，避免误伤。
            if (spec.get("value") is None or spec.get("value") == "") and (spec.get("min") is None or spec.get("min") == "") and (spec.get("max") is None or spec.get("max") == ""):
                op = str(mapped.get("op", op) or op)

    # Parameterized presets: emotion.nt.{channel}
    # 带参数的预设：例如 emotion.nt.{channel}
    if "{channel}" in metric:
        ch = str(spec.get("channel", "") or "").strip()
        if not ch:
            return False, {}, [{"zh": f"metric: preset={preset} 需要填写 channel", "en": f"metric: preset={preset} requires channel"}]
        metric = metric.replace("{channel}", ch)

    if not metric:
        return False, {}, [{"zh": "metric: 缺少 metric 字段", "en": "metric: missing metric"}]

    op_alias = {"ge": ">=", "gt": ">", "le": "<=", "lt": "<", "eq": "==", "ne": "!="}
    op = op_alias.get(op, op)

    threshold = spec.get("value")
    vmin = spec.get("min")
    vmax = spec.get("max")

    # pool.*
    if metric.startswith("pool."):
        pool = context.get("pool", {}) if isinstance(context.get("pool", {}), dict) else {}
        key = metric.split(".", 1)[1]
        cur = _coerce_float_maybe(pool.get(key))
        if cur is None:
            return False, {}, [{"zh": f"pool 指标不存在: {metric}", "en": f"pool metric missing: {metric}"}]
        value = float(cur)
        if mode == "prev_state" and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"pool 上一 tick 指标缺失: {metric}", "en": f"pool prev_state missing: {metric}"}]
            value = float(pv)
        if mode == "delta" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            value = float(d or 0.0)
        if mode == "avg_rate" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=window_ticks)
            value = float(d or 0.0) / float(window_ticks)
        # Optional prev_gate: require previous state to match an extra condition.
        # 可选 prev_gate：要求同一指标在“上一 tick”也满足一个额外条件（用于表达“先…再…”等逻辑约束）。
        if prev_gate and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"pool prev_gate 缺失上一 tick: {metric}", "en": f"pool prev_gate missing: {metric}"}]
            prev_ok = _numeric_compare(
                value=float(pv),
                op=str(prev_gate.get("op", ">=") or ">=").strip(),
                threshold=prev_gate.get("value"),
                vmin=prev_gate.get("min"),
                vmax=prev_gate.get("max"),
                epsilon=epsilon,
            )
            if not prev_ok:
                return False, {}, [{"zh": f"pool prev_gate 未满足: prev({metric})={round(float(pv), 6)}", "en": f"pool prev_gate not matched: prev({metric})={pv}"}]

        # Special op=changed semantics:
        # - If mode=state, interpret "changed" as "current state differs from previous tick".
        # - Internally we compare delta (current - prev), and expose match_value as that delta.
        #
        # op=changed 的语义增强：
        # - 当 mode=state 时，把 “变化了” 解释为“与上一 tick 的状态不同”。
        # - 内部用 delta（当前-上一 tick）来比较，并把 match_value 暴露为该 delta。
        if op == "changed" and mode == "state":
            if not provided_tick_index:
                return False, {}, [{"zh": f"pool changed 需要 tick_index: {metric}", "en": f"pool changed requires tick_index: {metric}"}]
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            if d is None:
                return False, {}, [{"zh": f"pool changed 缺失上一 tick: {metric}", "en": f"pool changed missing prev tick: {metric}"}]
            value = float(d)

        ok = _numeric_compare(value=value, op=op, threshold=threshold, vmin=vmin, vmax=vmax, epsilon=epsilon)
        if not ok:
            return False, {}, [{"zh": f"pool 未满足: {metric}={round(value, 6)}", "en": f"pool not matched: {metric}={value}"}]
        m = _empty_matches()
        m["metric"] = [{"metric": metric, "mode": mode, "value": value}]
        m["vars"]["match_metric"] = metric
        m["vars"]["match_value"] = value
        if capture_as:
            m["vars"][capture_as] = value
        return True, m, [{"zh": f"pool 命中: {metric}={round(value, 6)}", "en": f"pool matched: {metric}={value}"}]

    # cam.* (Current Attention Memory) / CAM（当前注意记忆体）指标
    if metric.startswith("cam."):
        cam = context.get("cam", {}) if isinstance(context.get("cam", {}), dict) else {}
        key = metric.split(".", 1)[1]
        cur = _coerce_float_maybe(cam.get(key))
        if cur is None:
            return False, {}, [{"zh": f"cam 指标不存在: {metric}", "en": f"cam metric missing: {metric}"}]
        value = float(cur)
        if mode == "prev_state" and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"cam 上一 tick 指标缺失: {metric}", "en": f"cam prev_state missing: {metric}"}]
            value = float(pv)
        if mode == "delta" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            value = float(d or 0.0)
        if mode == "avg_rate" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=window_ticks)
            value = float(d or 0.0) / float(window_ticks)
        if prev_gate and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"cam prev_gate 缺失上一 tick: {metric}", "en": f"cam prev_gate missing: {metric}"}]
            prev_ok = _numeric_compare(
                value=float(pv),
                op=str(prev_gate.get("op", ">=") or ">=").strip(),
                threshold=prev_gate.get("value"),
                vmin=prev_gate.get("min"),
                vmax=prev_gate.get("max"),
                epsilon=epsilon,
            )
            if not prev_ok:
                return False, {}, [{"zh": f"cam prev_gate 未满足: prev({metric})={round(float(pv), 6)}", "en": f"cam prev_gate not matched: prev({metric})={pv}"}]

        if op == "changed" and mode == "state":
            if not provided_tick_index:
                return False, {}, [{"zh": f"cam changed 需要 tick_index: {metric}", "en": f"cam changed requires tick_index: {metric}"}]
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            if d is None:
                return False, {}, [{"zh": f"cam changed 缺失上一 tick: {metric}", "en": f"cam changed missing prev tick: {metric}"}]
            value = float(d)

        ok = _numeric_compare(value=value, op=op, threshold=threshold, vmin=vmin, vmax=vmax, epsilon=epsilon)
        if not ok:
            return False, {}, [{"zh": f"cam 未满足: {metric}={round(value, 6)}", "en": f"cam not matched: {metric}={value}"}]
        m = _empty_matches()
        m["metric"] = [{"metric": metric, "mode": mode, "value": value}]
        m["vars"]["match_metric"] = metric
        m["vars"]["match_value"] = value
        if capture_as:
            m["vars"][capture_as] = value
        return True, m, [{"zh": f"cam 命中: {metric}={round(value, 6)}", "en": f"cam matched: {metric}={value}"}]

    # memory_activation.* / 记忆赋能池（MAP）指标（原型：只提供少量摘要字段）
    if metric.startswith("memory_activation."):
        ma = context.get("memory_activation", {}) if isinstance(context.get("memory_activation", {}), dict) else {}
        key = metric.split(".", 1)[1]
        cur = _coerce_float_maybe(ma.get(key))
        if cur is None:
            return False, {}, [{"zh": f"memory_activation 指标不存在: {metric}", "en": f"memory_activation metric missing: {metric}"}]
        value = float(cur)
        if mode == "prev_state" and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"memory_activation 上一 tick 指标缺失: {metric}", "en": f"memory_activation prev_state missing: {metric}"}]
            value = float(pv)
        if mode == "delta" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            value = float(d or 0.0)
        if mode == "avg_rate" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=window_ticks)
            value = float(d or 0.0) / float(window_ticks)
        if prev_gate and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"memory_activation prev_gate 缺失上一 tick: {metric}", "en": f"memory_activation prev_gate missing: {metric}"}]
            prev_ok = _numeric_compare(
                value=float(pv),
                op=str(prev_gate.get("op", ">=") or ">=").strip(),
                threshold=prev_gate.get("value"),
                vmin=prev_gate.get("min"),
                vmax=prev_gate.get("max"),
                epsilon=epsilon,
            )
            if not prev_ok:
                return False, {}, [{"zh": f"memory_activation prev_gate 未满足: prev({metric})={round(float(pv), 6)}", "en": f"memory_activation prev_gate not matched: prev({metric})={pv}"}]

        if op == "changed" and mode == "state":
            if not provided_tick_index:
                return False, {}, [{"zh": f"memory_activation changed 需要 tick_index: {metric}", "en": f"memory_activation changed requires tick_index: {metric}"}]
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            if d is None:
                return False, {}, [{"zh": f"memory_activation changed 缺失上一 tick: {metric}", "en": f"memory_activation changed missing prev tick: {metric}"}]
            value = float(d)

        ok = _numeric_compare(value=value, op=op, threshold=threshold, vmin=vmin, vmax=vmax, epsilon=epsilon)
        if not ok:
            return False, {}, [{"zh": f"memory_activation 未满足: {metric}={round(value, 6)}", "en": f"memory_activation not matched: {metric}={value}"}]
        m = _empty_matches()
        m["metric"] = [{"metric": metric, "mode": mode, "value": value}]
        m["vars"]["match_metric"] = metric
        m["vars"]["match_value"] = value
        if capture_as:
            m["vars"][capture_as] = value
        return True, m, [{"zh": f"memory_activation 命中: {metric}={round(value, 6)}", "en": f"memory_activation matched: {metric}={value}"}]

    # stimulus.*
    if metric.startswith("stimulus."):
        stim = context.get("stimulus", {}) if isinstance(context.get("stimulus", {}), dict) else {}
        key = metric.split(".", 1)[1]
        cur = _coerce_float_maybe(stim.get(key))
        if cur is None:
            return False, {}, [{"zh": f"stimulus 指标不存在: {metric}", "en": f"stimulus metric missing: {metric}"}]
        value = float(cur)
        if mode == "prev_state" and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"stimulus 上一 tick 指标缺失: {metric}", "en": f"stimulus prev_state missing: {metric}"}]
            value = float(pv)
        if mode == "delta" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            value = float(d or 0.0)
        if mode == "avg_rate" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=window_ticks)
            value = float(d or 0.0) / float(window_ticks)
        if prev_gate and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"stimulus prev_gate 缺失上一 tick: {metric}", "en": f"stimulus prev_gate missing: {metric}"}]
            prev_ok = _numeric_compare(
                value=float(pv),
                op=str(prev_gate.get("op", ">=") or ">=").strip(),
                threshold=prev_gate.get("value"),
                vmin=prev_gate.get("min"),
                vmax=prev_gate.get("max"),
                epsilon=epsilon,
            )
            if not prev_ok:
                return False, {}, [{"zh": f"stimulus prev_gate 未满足: prev({metric})={round(float(pv), 6)}", "en": f"stimulus prev_gate not matched: prev({metric})={pv}"}]

        if op == "changed" and mode == "state":
            if not provided_tick_index:
                return False, {}, [{"zh": f"stimulus changed 需要 tick_index: {metric}", "en": f"stimulus changed requires tick_index: {metric}"}]
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            if d is None:
                return False, {}, [{"zh": f"stimulus changed 缺失上一 tick: {metric}", "en": f"stimulus changed missing prev tick: {metric}"}]
            value = float(d)

        ok = _numeric_compare(value=value, op=op, threshold=threshold, vmin=vmin, vmax=vmax, epsilon=epsilon)
        if not ok:
            return False, {}, [{"zh": f"stimulus 未满足: {metric}={round(value, 6)}", "en": f"stimulus not matched: {metric}={value}"}]
        m = _empty_matches()
        m["metric"] = [{"metric": metric, "mode": mode, "value": value}]
        m["vars"]["match_metric"] = metric
        m["vars"]["match_value"] = value
        if capture_as:
            m["vars"][capture_as] = value
        return True, m, [{"zh": f"stimulus 命中: {metric}={round(value, 6)}", "en": f"stimulus matched: {metric}={value}"}]

    # retrieval.*
    if metric.startswith("retrieval."):
        retrieval = context.get("retrieval", {}) if isinstance(context.get("retrieval", {}), dict) else {}
        parts = metric.split(".")
        if len(parts) < 3:
            return False, {}, [{"zh": f"retrieval 指标格式错误: {metric}", "en": f"retrieval metric invalid: {metric}"}]
        stage = parts[1]
        sub = ".".join(parts[2:])
        stage_obj = retrieval.get(stage, {}) if isinstance(retrieval.get(stage, {}), dict) else {}

        cur: float | None = None
        sid = ""
        if sub.startswith("match_scores") and selector and isinstance(selector, dict):
            sid = str(selector.get("ref_object_id", "") or "").strip()
            scores = stage_obj.get("match_scores", {}) if isinstance(stage_obj.get("match_scores", {}), dict) else {}
            cur = _coerce_float_maybe(scores.get(sid))
        if cur is None:
            cur = _coerce_float_maybe(stage_obj.get(sub))
        if cur is None:
            return False, {}, [{"zh": f"retrieval 指标不存在: {metric}", "en": f"retrieval metric missing: {metric}"}]
        value = float(cur)
        if mode == "prev_state" and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"retrieval 上一 tick 指标缺失: {metric}", "en": f"retrieval prev_state missing: {metric}"}]
            value = float(pv)
        if mode == "delta" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            value = float(d or 0.0)
        if mode == "avg_rate" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=window_ticks)
            value = float(d or 0.0) / float(window_ticks)
        if prev_gate and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"retrieval prev_gate 缺失上一 tick: {metric}", "en": f"retrieval prev_gate missing: {metric}"}]
            prev_ok = _numeric_compare(
                value=float(pv),
                op=str(prev_gate.get("op", ">=") or ">=").strip(),
                threshold=prev_gate.get("value"),
                vmin=prev_gate.get("min"),
                vmax=prev_gate.get("max"),
                epsilon=epsilon,
            )
            if not prev_ok:
                return False, {}, [{"zh": f"retrieval prev_gate 未满足: prev({metric})={round(float(pv), 6)}", "en": f"retrieval prev_gate not matched: prev({metric})={pv}"}]

        if op == "changed" and mode == "state":
            if not provided_tick_index:
                return False, {}, [{"zh": f"retrieval changed 需要 tick_index: {metric}", "en": f"retrieval changed requires tick_index: {metric}"}]
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            if d is None:
                return False, {}, [{"zh": f"retrieval changed 缺失上一 tick: {metric}", "en": f"retrieval changed missing prev tick: {metric}"}]
            value = float(d)

        ok = _numeric_compare(value=value, op=op, threshold=threshold, vmin=vmin, vmax=vmax, epsilon=epsilon)
        if not ok:
            return False, {}, [{"zh": f"retrieval 未满足: {metric}={round(value, 6)}", "en": f"retrieval not matched: {metric}={value}"}]
        m = _empty_matches()
        m["metric"] = [{"metric": metric, "mode": mode, "value": value}]
        m["vars"]["match_metric"] = metric
        m["vars"]["match_value"] = value
        # Capture target id if available (best-effort).
        # 目标ID捕获（尽力而为）：用于把后续动作绑定到同一“被匹配目标”。
        target_id = ""
        if sub.startswith("match_scores") and sid:
            target_id = sid
        else:
            target_id = str(stage_obj.get("best_match_target_id", "") or "").strip()
        if target_id:
            m["vars"]["match_ref_object_id"] = target_id
            # Best-effort type inference / 目标类型尽力推断：
            # - st_* -> st（结构）
            # - sg_* -> sg（结构组）
            tid2 = str(target_id)
            if tid2.startswith("st_"):
                m["vars"]["match_ref_object_type"] = "st"
            elif tid2.startswith("sg_"):
                m["vars"]["match_ref_object_type"] = "sg"
            else:
                m["vars"]["match_ref_object_type"] = ""

            # Best-effort: also capture a human-readable display for the target.
            # 尽力补全目标展示文本：避免前端只看到 st_000123 / sg_000123 这种 ID。
            try:
                disp = ""
                if sub.startswith("match_scores") and sid:
                    md = stage_obj.get("match_displays", {}) if isinstance(stage_obj.get("match_displays", {}), dict) else {}
                    disp = str(md.get(target_id, "") or "").strip()
                if not disp:
                    disp = str(stage_obj.get("best_match_target_display", "") or "").strip()
                if disp:
                    m["vars"]["match_display"] = disp
            except Exception:
                pass
        if capture_as:
            m["vars"][capture_as] = value
            if target_id:
                m["vars"][f"{capture_as}_ref_object_id"] = target_id
                m["vars"][f"{capture_as}_ref_object_type"] = m["vars"].get("match_ref_object_type", "")
        return True, m, [{"zh": f"retrieval 命中: {metric}={round(value, 6)}", "en": f"retrieval matched: {metric}={value}"}]

    # emotion.*
    if metric.startswith("emotion."):
        emo = context.get("emotion", {}) if isinstance(context.get("emotion", {}), dict) else {}

        if metric.startswith("emotion.nt."):
            ch = metric.split(".", 2)[2]
            nt = emo.get("nt", {}) if isinstance(emo.get("nt", {}), dict) else {}
            if ch not in nt:
                return False, {}, [{"zh": f"情绪递质通道不存在: {ch}", "en": f"emotion channel missing: {ch}"}]
            cur = _coerce_float_maybe(nt.get(ch))
            if cur is None:
                return False, {}, [{"zh": f"情绪递质值非法: {ch}", "en": f"emotion channel invalid: {ch}"}]
            value = float(cur)
            if mode == "prev_state" and provided_tick_index:
                pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
                if pv is None:
                    return False, {}, [{"zh": f"情绪递质上一 tick 缺失: {ch}", "en": f"emotion nt prev_state missing: {ch}"}]
                value = float(pv)
            if mode == "delta" and provided_tick_index:
                d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
                value = float(d or 0.0)
            if mode == "avg_rate" and provided_tick_index:
                d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=window_ticks)
                value = float(d or 0.0) / float(window_ticks)
            if prev_gate and provided_tick_index:
                pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
                if pv is None:
                    return False, {}, [{"zh": f"情绪递质 prev_gate 缺失上一 tick: {ch}", "en": f"emotion nt prev_gate missing: {ch}"}]
                prev_ok = _numeric_compare(
                    value=float(pv),
                    op=str(prev_gate.get("op", ">=") or ">=").strip(),
                    threshold=prev_gate.get("value"),
                    vmin=prev_gate.get("min"),
                    vmax=prev_gate.get("max"),
                    epsilon=epsilon,
                )
                if not prev_ok:
                    return False, {}, [{"zh": f"情绪递质 prev_gate 未满足: prev({ch})={round(float(pv), 6)}", "en": f"emotion nt prev_gate not matched: prev({ch})={pv}"}]

            if op == "changed" and mode == "state":
                if not provided_tick_index:
                    return False, {}, [{"zh": f"情绪递质 changed 需要 tick_index: {ch}", "en": f"emotion nt changed requires tick_index: {ch}"}]
                d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
                if d is None:
                    return False, {}, [{"zh": f"情绪递质 changed 缺失上一 tick: {ch}", "en": f"emotion nt changed missing prev tick: {ch}"}]
                value = float(d)

            ok = _numeric_compare(value=value, op=op, threshold=threshold, vmin=vmin, vmax=vmax, epsilon=epsilon)
            if not ok:
                return False, {}, [{"zh": f"情绪递质未满足: {ch}={round(value, 6)}", "en": f"emotion nt not matched: {ch}={value}"}]
            m = _empty_matches()
            m["metric"] = [{"metric": metric, "mode": mode, "value": value}]
            m["vars"]["match_metric"] = metric
            m["vars"]["match_value"] = value
            m["vars"]["match_emotion_channel"] = ch
            if capture_as:
                m["vars"][capture_as] = value
            return True, m, [{"zh": f"情绪递质命中: {ch}={round(value, 6)}", "en": f"emotion nt matched: {ch}={value}"}]

        key = metric.split(".", 1)[1]
        cur = _coerce_float_maybe(emo.get(key))
        if cur is None:
            return False, {}, [{"zh": f"情绪指标不存在: {metric}", "en": f"emotion metric missing: {metric}"}]
        value = float(cur)
        if mode == "prev_state" and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"情绪指标上一 tick 缺失: {metric}", "en": f"emotion prev_state missing: {metric}"}]
            value = float(pv)
        if mode == "delta" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            value = float(d or 0.0)
        if mode == "avg_rate" and provided_tick_index:
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=window_ticks)
            value = float(d or 0.0) / float(window_ticks)
        if prev_gate and provided_tick_index:
            pv = _history_value_at(store, series_key=metric, tick=tick_index - 1)
            if pv is None:
                return False, {}, [{"zh": f"情绪 prev_gate 缺失上一 tick: {metric}", "en": f"emotion prev_gate missing: {metric}"}]
            prev_ok = _numeric_compare(
                value=float(pv),
                op=str(prev_gate.get("op", ">=") or ">=").strip(),
                threshold=prev_gate.get("value"),
                vmin=prev_gate.get("min"),
                vmax=prev_gate.get("max"),
                epsilon=epsilon,
            )
            if not prev_ok:
                return False, {}, [{"zh": f"情绪 prev_gate 未满足: prev({metric})={round(float(pv), 6)}", "en": f"emotion prev_gate not matched: prev({metric})={pv}"}]

        if op == "changed" and mode == "state":
            if not provided_tick_index:
                return False, {}, [{"zh": f"emotion changed 需要 tick_index: {metric}", "en": f"emotion changed requires tick_index: {metric}"}]
            d = _series_delta(store=store, series_key=metric, tick_index=tick_index, window_ticks=1)
            if d is None:
                return False, {}, [{"zh": f"emotion changed 缺失上一 tick: {metric}", "en": f"emotion changed missing prev tick: {metric}"}]
            value = float(d)

        ok = _numeric_compare(value=value, op=op, threshold=threshold, vmin=vmin, vmax=vmax, epsilon=epsilon)
        if not ok:
            return False, {}, [{"zh": f"情绪指标未满足: {metric}={round(value, 6)}", "en": f"emotion not matched: {metric}={value}"}]
        m = _empty_matches()
        m["metric"] = [{"metric": metric, "mode": mode, "value": value}]
        m["vars"]["match_metric"] = metric
        m["vars"]["match_value"] = value
        if capture_as:
            m["vars"][capture_as] = value
        return True, m, [{"zh": f"情绪指标命中: {metric}={round(value, 6)}", "en": f"emotion matched: {metric}={value}"}]

    # item.*
    if metric.startswith("item."):
        tail = metric.split(".", 1)[1]
        items = _select_pool_items(context=context, selector=selector)
        if not items:
            return False, {}, [{"zh": "item 指标：选择器无对象", "en": "item metric: empty selector"}]

        if tail in {"exists", "presence", "present"}:
            matched_records = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                item_id = str(it.get("item_id", "") or "")
                if not item_id:
                    continue
                matched_records.append(
                    {
                        "metric": metric,
                        "mode": mode,
                        "value": 1.0,
                        "item_id": item_id,
                        "ref_object_id": str(it.get("ref_object_id", "") or ""),
                        "ref_object_type": str(it.get("ref_object_type", "") or ""),
                        "display": str(it.get("display", "") or ""),
                        "time_bucket_ref_object_id": str(it.get("time_bucket_ref_object_id", "") or ""),
                        "time_bucket_center_sec": it.get("time_bucket_center_sec", None),
                        "time_basis": str(it.get("time_basis", "") or ""),
                        "time_bucket_unit": str(it.get("time_bucket_unit", "") or ""),
                        "verification_anchor_item_id": str(it.get("verification_anchor_item_id", "") or ""),
                        "verification_anchor_ref_object_id": str(it.get("verification_anchor_ref_object_id", "") or ""),
                        "verification_anchor_ref_object_type": str(it.get("verification_anchor_ref_object_type", "") or ""),
                        "verification_anchor_display": str(it.get("verification_anchor_display", "") or ""),
                    }
                )
            ok = _numeric_compare(value=float(len(matched_records)), op=op, threshold=threshold, vmin=vmin, vmax=vmax, epsilon=epsilon)
            if not ok:
                return False, {}, [{"zh": f"item presence ???: {metric}", "en": f"item presence not matched: {metric}"}]
            primary = matched_records[0]
            m = _empty_matches()
            m["metric"] = matched_records[:24]
            m["vars"]["match_metric"] = metric
            m["vars"]["match_value"] = float(len(matched_records))
            m["vars"]["match_item_id"] = str(primary.get("item_id", "") or "")
            m["vars"]["match_ref_object_id"] = str(primary.get("ref_object_id", "") or "")
            m["vars"]["match_ref_object_type"] = str(primary.get("ref_object_type", "") or "")
            m["vars"]["match_display"] = str(primary.get("display", "") or "")
            m["vars"]["match_verification_anchor_item_id"] = str(primary.get("verification_anchor_item_id", "") or "")
            m["vars"]["match_verification_anchor_ref_object_id"] = str(primary.get("verification_anchor_ref_object_id", "") or "")
            m["vars"]["match_verification_anchor_ref_object_type"] = str(primary.get("verification_anchor_ref_object_type", "") or "")
            m["vars"]["match_verification_anchor_display"] = str(primary.get("verification_anchor_display", "") or "")
            if capture_as:
                m["vars"][capture_as] = m["vars"]["match_value"]
                m["vars"][f"{capture_as}_item_id"] = m["vars"]["match_item_id"]
                m["vars"][f"{capture_as}_ref_object_id"] = m["vars"]["match_ref_object_id"]
                m["vars"][f"{capture_as}_ref_object_type"] = m["vars"]["match_ref_object_type"]
            return True, m, [{"zh": f"item presence ??: {metric} x{len(matched_records)}", "en": f"item presence matched: {metric} x{len(matched_records)}"}]

        matched_records: list[dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            item_id = str(it.get("item_id", "") or "")
            if not item_id:
                continue
            base = _coerce_float_maybe(it.get(tail))
            if base is None:
                continue
            value = float(base)

            # Optional prev_gate: apply to the same item series.
            # 可选 prev_gate：应用到同一个对象（item）的“上一 tick 指标值”。
            if prev_gate and provided_tick_index:
                pv = _history_value_at(store, series_key=_metric_series_key_for_item(item_id, tail), tick=tick_index - 1)
                if pv is None:
                    continue
                prev_ok = _numeric_compare(
                    value=float(pv),
                    op=str(prev_gate.get("op", ">=") or ">=").strip(),
                    threshold=prev_gate.get("value"),
                    vmin=prev_gate.get("min"),
                    vmax=prev_gate.get("max"),
                    epsilon=epsilon,
                )
                if not prev_ok:
                    continue

            if mode == "prev_state" and provided_tick_index:
                pv = _history_value_at(
                    store,
                    series_key=_metric_series_key_for_item(item_id, tail),
                    tick=tick_index - 1,
                )
                if pv is None:
                    continue
                value = float(pv)

            if mode == "delta":
                d = (
                    _series_delta(
                        store=store,
                        series_key=_metric_series_key_for_item(item_id, tail),
                        tick_index=tick_index,
                        window_ticks=1,
                    )
                    if provided_tick_index
                    else None
                )
                if d is not None:
                    value = float(d)
                else:
                    if tail == "er":
                        value = float(it.get("delta_er", 0.0) or 0.0)
                    elif tail == "ev":
                        value = float(it.get("delta_ev", 0.0) or 0.0)
                    elif tail == "cp_delta":
                        # Fallback: cp_delta = er-ev, so delta_cp_delta ~= delta_er - delta_ev.
                        # 回退：cp_delta = er-ev，因此 delta_cp_delta ~= delta_er - delta_ev。
                        if "delta_cp_delta" in it:
                            value = float(it.get("delta_cp_delta", 0.0) or 0.0)
                        else:
                            value = float(it.get("delta_er", 0.0) or 0.0) - float(it.get("delta_ev", 0.0) or 0.0)
                    elif tail == "cp_abs":
                        value = float(it.get("delta_cp_abs", 0.0) or 0.0)
                    else:
                        value = 0.0

            if mode == "avg_rate":
                d = None
                span = max(1, int(window_ticks))
                if provided_tick_index:
                    d, span = _series_delta_with_recent_span(
                        store=store,
                        series_key=_metric_series_key_for_item(item_id, tail),
                        tick_index=tick_index,
                        window_ticks=window_ticks,
                    )
                value = float(d or 0.0) / float(span or window_ticks or 1)

            if op == "changed" and mode == "state":
                # Interpret "changed" as "state differs from previous tick" (delta != 0).
                # 把 “变化了” 解释为“与上一 tick 状态不同”（delta != 0）。
                if provided_tick_index:
                    d2 = _series_delta(
                        store=store,
                        series_key=_metric_series_key_for_item(item_id, tail),
                        tick_index=tick_index,
                        window_ticks=1,
                    )
                    if d2 is not None:
                        value = float(d2)
                    else:
                        # Fallback to per-item delta fields when history is not available.
                        # 若历史缺失，则回退到条目自带的 delta_* 字段（尽力而为）。
                        if tail == "er":
                            value = float(it.get("delta_er", 0.0) or 0.0)
                        elif tail == "ev":
                            value = float(it.get("delta_ev", 0.0) or 0.0)
                        elif tail == "cp_delta":
                            if "delta_cp_delta" in it:
                                value = float(it.get("delta_cp_delta", 0.0) or 0.0)
                            else:
                                value = float(it.get("delta_er", 0.0) or 0.0) - float(it.get("delta_ev", 0.0) or 0.0)
                        elif tail == "cp_abs":
                            value = float(it.get("delta_cp_abs", 0.0) or 0.0)
                        else:
                            value = 0.0
                else:
                    # Without tick_index we cannot compare to previous tick.
                    # 没有 tick_index 时无法和上一 tick 比较，因此视为不命中。
                    continue

            ok = _numeric_compare(value=value, op=op, threshold=threshold, vmin=vmin, vmax=vmax, epsilon=epsilon)
            if not ok:
                continue

            matched_records.append(
                {
                    "metric": metric,
                    "mode": mode,
                    "value": float(value),
                    "item_id": item_id,
                    "ref_object_id": str(it.get("ref_object_id", "") or ""),
                    "ref_object_type": str(it.get("ref_object_type", "") or ""),
                    "display": str(it.get("display", "") or ""),
                    # Optional time-bucket info (best-effort) / 可选时间桶信息（尽力而为）
                    "time_bucket_ref_object_id": str(it.get("time_bucket_ref_object_id", "") or ""),
                    "time_bucket_center_sec": it.get("time_bucket_center_sec", None),
                    "time_basis": str(it.get("time_basis", "") or ""),
                    "time_bucket_unit": str(it.get("time_bucket_unit", "") or ""),
                    "verification_anchor_item_id": str(it.get("verification_anchor_item_id", "") or ""),
                    "verification_anchor_ref_object_id": str(it.get("verification_anchor_ref_object_id", "") or ""),
                    "verification_anchor_ref_object_type": str(it.get("verification_anchor_ref_object_type", "") or ""),
                    "verification_anchor_display": str(it.get("verification_anchor_display", "") or ""),
                }
            )

        if not matched_records:
            return False, {}, [{"zh": f"item 指标未命中: {metric}", "en": f"item metric not matched: {metric}"}]

        if match_policy == "all":
            if len(matched_records) < len([x for x in items if isinstance(x, dict)]):
                return False, {}, [{"zh": f"item 指标未满足 all: {metric}", "en": f"item metric not matched for all: {metric}"}]

        # Sort records by value desc so downstream actions (e.g. cfs_emit max_signals)
        # get the strongest matches first.
        # 按 value 降序排序：让下游动作（例如 cfs_emit 的 max_signals）优先处理最强命中对象。
        matched_records.sort(key=lambda r: float(r.get("value", 0.0) or 0.0), reverse=True)
        primary = matched_records[0]
        m = _empty_matches()
        m["metric"] = matched_records[:24]
        m["vars"]["match_metric"] = metric
        m["vars"]["match_value"] = float(primary.get("value", 0.0) or 0.0)
        m["vars"]["match_item_id"] = str(primary.get("item_id", "") or "")
        m["vars"]["match_ref_object_id"] = str(primary.get("ref_object_id", "") or "")
        m["vars"]["match_ref_object_type"] = str(primary.get("ref_object_type", "") or "")
        m["vars"]["match_display"] = str(primary.get("display", "") or "")
        m["vars"]["match_verification_anchor_item_id"] = str(primary.get("verification_anchor_item_id", "") or "")
        m["vars"]["match_verification_anchor_ref_object_id"] = str(primary.get("verification_anchor_ref_object_id", "") or "")
        m["vars"]["match_verification_anchor_ref_object_type"] = str(primary.get("verification_anchor_ref_object_type", "") or "")
        m["vars"]["match_verification_anchor_display"] = str(primary.get("verification_anchor_display", "") or "")
        # Make time-bucket vars available for action_trigger templates (e.g. recall from time-feeling).
        # 让时间桶信息可用于 action_trigger 模板（例如时间感受触发回忆时透传目标时间间隔）。
        tb_ref = str(primary.get("time_bucket_ref_object_id", "") or "").strip()
        if tb_ref:
            m["vars"]["match_time_bucket_ref_object_id"] = tb_ref
        try:
            if primary.get("time_bucket_center_sec", None) is not None:
                m["vars"]["match_time_bucket_center_sec"] = float(primary.get("time_bucket_center_sec"))
        except Exception:
            pass
        tb_basis = str(primary.get("time_basis", "") or "").strip()
        if tb_basis:
            m["vars"]["match_time_basis"] = tb_basis
        tb_unit = str(primary.get("time_bucket_unit", "") or "").strip()
        if tb_unit:
            m["vars"]["match_time_bucket_unit"] = tb_unit
        if capture_as:
            m["vars"][capture_as] = m["vars"]["match_value"]
            m["vars"][f"{capture_as}_item_id"] = m["vars"]["match_item_id"]
            m["vars"][f"{capture_as}_ref_object_id"] = m["vars"]["match_ref_object_id"]
            m["vars"][f"{capture_as}_ref_object_type"] = m["vars"]["match_ref_object_type"]
        return True, m, [{"zh": f"item 指标命中: {metric} x{len(matched_records)}", "en": f"item metric matched: {metric} x{len(matched_records)}"}]

    return False, {}, [{"zh": f"metric: 未支持的 metric={metric}", "en": f"metric: unsupported metric={metric}"}]


# ======================================================================
# Evaluation / 执行
# ======================================================================


def parse_tick_index(tick_id: str) -> int | None:
    """
    Best-effort parse tick_index from tick_id string.
    尝试从 tick_id 中解析 tick_index（尽力而为）。

    Example / 示例:
      "cycle_0001" -> 1
    """
    if not tick_id:
        return None
    # NOTE:
    # - Use \d (digit class), not \\d (literal "\d").
    # - 使用 \\d 会匹配字面量“\\d”，导致无法从 "cycle_0001" 解析出数字。
    m = re.search(r"(\d+)$", str(tick_id))
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _resolve_habituation_config(*, defaults: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    """
    Resolve habituation config for a rule.

    Design intent:
    - No hard-coded word/punctuation hacks.
    - A generic, learnable "resource attenuation" mechanism: repeated strong outputs
      from the same innate rule will gradually weaken (habit), then recover when
      the rule stops firing.

    Supported shape:
      - defaults["habituation"]: global defaults for all rules
      - rule["habituation"]: optional per-rule override
    """
    base = defaults.get("habituation", {}) if isinstance(defaults.get("habituation", {}), dict) else {}
    override = rule.get("habituation", {}) if isinstance(rule.get("habituation", {}), dict) else {}
    merged = dict(base)
    merged.update(override)

    # Normalize minimal fields (keep extra keys for forward-compatibility).
    enabled = bool(merged.get("enabled", True))
    try:
        window_ticks = int(merged.get("window_ticks", 10) or 10)
    except Exception:
        window_ticks = 10
    window_ticks = max(1, min(10_000, window_ticks))
    try:
        start_total = float(merged.get("start_total", 6.0))
    except Exception:
        start_total = 6.0
    try:
        full_total = float(merged.get("full_total", 18.0))
    except Exception:
        full_total = 18.0
    try:
        min_scale = float(merged.get("min_scale", 0.0))
    except Exception:
        min_scale = 0.0
    min_scale = max(0.0, min(1.0, min_scale))
    if full_total <= start_total + 1e-9:
        full_total = start_total + 1.0

    merged["enabled"] = enabled
    merged["window_ticks"] = window_ticks
    merged["start_total"] = float(start_total)
    merged["full_total"] = float(full_total)
    merged["min_scale"] = float(min_scale)
    return merged


def _habituation_get_rule_store(runtime_state: dict[str, Any]) -> dict[str, Any]:
    st = runtime_state.setdefault("habituation", {})
    if not isinstance(st, dict):
        st = {}
        runtime_state["habituation"] = st
    rules = st.setdefault("rules", {})
    if not isinstance(rules, dict):
        rules = {}
        st["rules"] = rules
    return rules


def _habituation_window_sum(
    *,
    runtime_state: dict[str, Any],
    rule_id: str,
    tick_index: int,
    window_ticks: int,
) -> float:
    rules = _habituation_get_rule_store(runtime_state)
    entry = rules.get(rule_id) if isinstance(rules.get(rule_id), dict) else {}
    events = entry.get("events") if isinstance(entry.get("events"), list) else []

    s = 0.0
    kept: list[dict[str, Any]] = []
    # Keep a little more than the active window to avoid unbounded growth.
    prune_before = int(tick_index) - max(int(window_ticks) * 6, 64)
    for ev in events:
        if not isinstance(ev, dict):
            continue
        try:
            t = int(ev.get("tick_index", -999999) or -999999)
        except Exception:
            t = -999999
        if t < prune_before:
            continue
        kept.append(ev)
        if (int(tick_index) - t) < int(window_ticks):
            try:
                s += max(0.0, float(ev.get("energy", 0.0) or 0.0))
            except Exception:
                pass

    # Persist pruned list back (best-effort).
    try:
        entry = dict(entry) if isinstance(entry, dict) else {}
        entry["events"] = kept[-2000:]
        rules[rule_id] = entry
    except Exception:
        pass
    return float(s)


def _habituation_scale(
    *,
    runtime_state: dict[str, Any],
    rule_id: str,
    tick_index: int,
    config: dict[str, Any],
    enabled: bool,
) -> tuple[float, float]:
    if not enabled:
        return 1.0, 0.0
    window_ticks = int(config.get("window_ticks", 10) or 10)
    start_total = float(config.get("start_total", 6.0) or 6.0)
    full_total = float(config.get("full_total", 18.0) or 18.0)
    min_scale = float(config.get("min_scale", 0.0) or 0.0)

    hist_sum = _habituation_window_sum(runtime_state=runtime_state, rule_id=rule_id, tick_index=tick_index, window_ticks=window_ticks)

    if hist_sum <= start_total:
        return 1.0, float(hist_sum)
    if hist_sum >= full_total:
        return float(min_scale), float(hist_sum)

    # Linear attenuation between thresholds (soft limit).
    ratio = (hist_sum - start_total) / max(1e-9, (full_total - start_total))
    scale = 1.0 - max(0.0, min(1.0, ratio))
    scale = max(float(min_scale), min(1.0, float(scale)))
    return float(scale), float(hist_sum)


def _habituation_record_energy(
    *,
    runtime_state: dict[str, Any],
    rule_id: str,
    tick_index: int,
    raw_energy: float,
) -> None:
    rules = _habituation_get_rule_store(runtime_state)
    entry = rules.get(rule_id) if isinstance(rules.get(rule_id), dict) else {}
    events = entry.get("events") if isinstance(entry.get("events"), list) else []
    try:
        events.append({"tick_index": int(tick_index), "energy": float(max(0.0, raw_energy))})
    except Exception:
        return
    # prune (same policy as window_sum)
    prune_before = int(tick_index) - 512
    kept: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        try:
            t = int(ev.get("tick_index", -999999) or -999999)
        except Exception:
            t = -999999
        if t < prune_before:
            continue
        kept.append(ev)
    entry2 = dict(entry) if isinstance(entry, dict) else {}
    entry2["events"] = kept[-2000:]
    entry2["last_tick_index"] = int(tick_index)
    entry2["last_raw_energy"] = float(max(0.0, raw_energy))
    rules[rule_id] = entry2


def evaluate_rules(
    *,
    doc: dict[str, Any],
    trace_id: str,
    tick_id: str,
    tick_index: int | None,
    cfs_signals: list[dict] | None,
    state_windows: list[dict[str, Any]] | None,
    context: dict[str, Any] | None = None,
    now_ms: int | None,
    runtime_state: dict[str, Any],
    allow_timer: bool = True,
    allowed_phases: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:
    """
    Evaluate rules against a single tick context.
    对单次 tick 上下文执行规则。

    runtime_state is mutable and stores cooldown bookkeeping.
    runtime_state 会被更新，用于冷却与后续扩展的运行态记账。
    """
    start = time.time()
    now_ms = int(now_ms or (time.time() * 1000))
    provided_tick_index = tick_index is not None
    tick_index = int(tick_index) if tick_index is not None else (parse_tick_index(tick_id) or 0)

    enabled = bool(doc.get("enabled", True))
    defaults = doc.get("defaults", {}) if isinstance(doc.get("defaults", {}), dict) else {}
    focus_defaults = defaults.get("focus_directive", {}) if isinstance(defaults.get("focus_directive", {}), dict) else {}
    habituation_defaults = defaults

    # Runtime CFS list / 运行态 CFS 列表：规则可通过 cfs_emit 扩展它，供同 tick 后续规则消费。
    cfs_signals = list(cfs_signals or [])
    cfs_input_count = len(cfs_signals)
    emitted_cfs_signals: list[dict[str, Any]] = []
    windows = list(state_windows or [])
    context = context if isinstance(context, dict) else {}
    phase_filter: set[str] | None = None
    if isinstance(allowed_phases, (list, tuple, set)):
        normalized = {str(x).strip() for x in allowed_phases if str(x).strip()}
        phase_filter = normalized or None

    triggered_rules: list[dict[str, Any]] = []
    triggered_scripts: list[dict[str, Any]] = []
    focus_directives: list[dict[str, Any]] = []
    emotion_updates: dict[str, float] = {}
    action_triggers: list[dict[str, Any]] = []
    pool_effects: list[dict[str, Any]] = []
    audit_notes: list[str] = []

    if not enabled:
        return {
            "enabled": False,
            "tick_index": tick_index,
            "triggered_rules": [],
            "triggered_scripts": [],
            "directives": {"cfs_signals": list(cfs_signals or []), "focus_directives": [], "emotion_updates": {}, "action_triggers": [], "pool_effects": []},
            "audit": {"disabled": True, "elapsed_ms": int((time.time() - start) * 1000)},
        }

    selector_cache_had_prev = _SELECTOR_CACHE_KEY in context
    selector_stats_had_prev = _SELECTOR_CACHE_STATS_KEY in context
    selector_cache_prev = context.get(_SELECTOR_CACHE_KEY)
    selector_stats_prev = context.get(_SELECTOR_CACHE_STATS_KEY)
    context[_SELECTOR_CACHE_KEY] = {}
    context[_SELECTOR_CACHE_STATS_KEY] = {"hit": 0, "miss": 0}

    last_fired = runtime_state.setdefault("last_fired_tick", {})
    if not isinstance(last_fired, dict):
        last_fired = {}
        runtime_state["last_fired_tick"] = last_fired

    # ---- metric history bookkeeping / 指标历史记账（用于变化量/变化率）----
    # Only record when a real tick_index is provided by the caller (run_tick_rules).
    # 仅在调用方明确提供 tick_index（run_tick_rules）时记账；避免 check_state_window 等接口污染历史。
    if provided_tick_index:
        _update_metric_history(runtime_state=runtime_state, tick_index=tick_index, context=context)

    # ---- scheduled actions / 延时调度动作 ----
    # Execute due scheduled actions before evaluating normal rules.
    # 在正常规则评估前，先执行到期的延时动作。
    if provided_tick_index:
        _execute_due_scheduled_actions(
            runtime_state=runtime_state,
            tick_index=tick_index,
            trace_id=trace_id,
            tick_id=tick_id,
            now_ms=now_ms,
            context=context,
            focus_defaults=focus_defaults,
            habituation_defaults=habituation_defaults,
            allow_timer=bool(allow_timer),
            runtime_cfs_signals=cfs_signals,
            out_emitted_cfs_signals=emitted_cfs_signals,
            out_triggered_scripts=triggered_scripts,
            out_focus_directives=focus_directives,
            out_emotion_updates=emotion_updates,
            out_action_triggers=action_triggers,
            out_pool_effects=pool_effects,
            out_audit_notes=audit_notes,
        )

    # Phase ordering / 阶段排序：先执行 cfs，再执行 directives，再执行 emotion_post。
    phase_rank = {"cfs": 0, "directives": 1, "emotion_post": 2}

    def rule_sort_key(r: dict[str, Any]) -> tuple[int, int, str]:
        phase = str(r.get("phase", "directives") or "directives").strip() or "directives"
        pr = int(r.get("priority", 0) or 0)
        rid = str(r.get("id", "") or "")
        return (int(phase_rank.get(phase, 99)), int(-pr), rid)

    rule_candidates = [r for r in (doc.get("rules") or []) if isinstance(r, dict)]
    if phase_filter is not None:
        rule_candidates = [
            r
            for r in rule_candidates
            if str(r.get("phase", "directives") or "directives").strip() in phase_filter
        ]
    rules_sorted = sorted(rule_candidates, key=rule_sort_key)

    for rule in rules_sorted:
        if not bool(rule.get("enabled", True)):
            continue
        rid = str(rule.get("id", "") or "").strip()
        if not rid:
            continue
        rule_phase = str(rule.get("phase", "directives") or "directives").strip() or "directives"

        hab_cfg = _resolve_habituation_config(defaults=habituation_defaults, rule=rule)
        hab_enabled = bool(hab_cfg.get("enabled", True)) and bool(provided_tick_index)
        hab_scale, hab_hist_sum = _habituation_scale(
            runtime_state=runtime_state,
            rule_id=rid,
            tick_index=tick_index,
            config=hab_cfg,
            enabled=hab_enabled,
        )

        cooldown_ticks = int(rule.get("cooldown_ticks", 0) or 0)
        if cooldown_ticks > 0:
            prev = last_fired.get(rid)
            if isinstance(prev, int) and (tick_index - prev) < cooldown_ticks:
                continue

        matched, matches, reasons = _eval_when(
            rule.get("when") or {},
            cfs_signals=cfs_signals,
            state_windows=windows,
            tick_index=tick_index,
            allow_timer=bool(allow_timer),
            context=context,
            runtime_state=runtime_state,
            provided_tick_index=provided_tick_index,
        )
        if not matched:
            continue

        last_fired[rid] = tick_index
        triggered_rules.append(
            {
                "rule_id": rid,
                "title": str(rule.get("title", "") or ""),
                "phase": rule_phase,
                "priority": int(rule.get("priority", 0) or 0),
                "note": str(rule.get("note", "") or ""),
                "matched_at": now_ms,
                "habituation_scale": round(float(hab_scale), 6),
                "habituation_hist_sum": round(float(hab_hist_sum), 6),
                "reasons": reasons,
                "match_summary": _summarize_matches(matches),
            }
        )

        # Execute actions with template variables.
        # 执行动作（支持模板变量 {{{var}}}）。
        vars_ctx = matches.get("vars", {}) if isinstance(matches.get("vars"), dict) else {}
        raw_energy = _execute_actions(
            actions=list(rule.get("then") or []),
            rule_id=rid,
            rule_title=str(rule.get("title", "") or ""),
            rule_phase=rule_phase,
            rule_priority=int(rule.get("priority", 0) or 0),
            trace_id=trace_id,
            tick_id=tick_id,
            tick_index=tick_index,
            now_ms=now_ms,
            context=context,
            runtime_state=runtime_state,
            provided_tick_index=provided_tick_index,
            allow_timer=bool(allow_timer),
            matches=matches,
            vars_ctx=vars_ctx,
            focus_defaults=focus_defaults,
            runtime_cfs_signals=cfs_signals,
            out_emitted_cfs_signals=emitted_cfs_signals,
            out_triggered_scripts=triggered_scripts,
            out_focus_directives=focus_directives,
            out_emotion_updates=emotion_updates,
            out_action_triggers=action_triggers,
            out_pool_effects=pool_effects,
            out_audit_notes=audit_notes,
            depth=0,
            effect_scale=float(hab_scale),
        )
        if hab_enabled:
            _habituation_record_energy(runtime_state=runtime_state, rule_id=rid, tick_index=tick_index, raw_energy=float(raw_energy or 0.0))

    merged_by_id: dict[str, dict[str, Any]] = {}
    for d in focus_directives:
        if not isinstance(d, dict):
            continue
        did = str(d.get("directive_id", "") or "")
        if not did:
            continue
        merged_by_id[did] = d
    focus_directives = list(merged_by_id.values())

    selector_cache = context.get(_SELECTOR_CACHE_KEY)
    selector_stats = context.get(_SELECTOR_CACHE_STATS_KEY)
    selector_cache_size = len(selector_cache) if isinstance(selector_cache, dict) else 0
    selector_cache_hit = int(selector_stats.get("hit", 0) or 0) if isinstance(selector_stats, dict) else 0
    selector_cache_miss = int(selector_stats.get("miss", 0) or 0) if isinstance(selector_stats, dict) else 0

    if selector_cache_had_prev:
        context[_SELECTOR_CACHE_KEY] = selector_cache_prev
    else:
        context.pop(_SELECTOR_CACHE_KEY, None)
    if selector_stats_had_prev:
        context[_SELECTOR_CACHE_STATS_KEY] = selector_stats_prev
    else:
        context.pop(_SELECTOR_CACHE_STATS_KEY, None)

    return {
        "enabled": True,
        "tick_index": tick_index,
        "triggered_rules": triggered_rules,
        "triggered_scripts": triggered_scripts,
        "directives": {
            "cfs_signals": cfs_signals,
            "focus_directives": focus_directives,
            "emotion_updates": emotion_updates,
            "action_triggers": action_triggers,
            "pool_effects": pool_effects,
        },
        "audit": {
            "elapsed_ms": int((time.time() - start) * 1000),
            "rule_count": len(rules_sorted),
            "allowed_phases": sorted(list(phase_filter)) if phase_filter else [],
            "triggered_rule_count": len(triggered_rules),
            "triggered_script_count": len(triggered_scripts),
            "cfs_signal_input_count": int(cfs_input_count),
            "cfs_signal_emitted_count": int(len(emitted_cfs_signals)),
            "cfs_signal_output_count": int(len(cfs_signals)),
            "focus_directive_count": len(focus_directives),
            "emotion_update_key_count": len(emotion_updates.keys()),
            "action_trigger_count": len(action_triggers),
            "pool_effect_count": len(pool_effects),
            "selector_cache_hit": selector_cache_hit,
            "selector_cache_miss": selector_cache_miss,
            "selector_cache_size": selector_cache_size,
            "notes": audit_notes,
            "trace_id": trace_id,
            "tick_id": tick_id,
        },
    }


def _eval_when(
    expr: Any,
    *,
    cfs_signals: list[dict],
    state_windows: list[dict[str, Any]],
    tick_index: int,
    allow_timer: bool,
    context: dict[str, Any],
    runtime_state: dict[str, Any],
    provided_tick_index: bool,
) -> tuple[bool, dict[str, Any], list[dict[str, str]]]:
    """Evaluate normalized when-expression / 执行规范化后的 when 表达式。"""
    if not isinstance(expr, dict) or not expr:
        return False, {}, [{"zh": "when 为空", "en": "when is empty"}]

    key = next(iter(expr.keys()))
    val = expr.get(key)

    if key == "any":
        merged = _empty_matches()
        reasons: list[dict[str, str]] = []
        for child in (val or []):
            ok, m, r = _eval_when(
                child,
                cfs_signals=cfs_signals,
                state_windows=state_windows,
                tick_index=tick_index,
                allow_timer=allow_timer,
                context=context,
                runtime_state=runtime_state,
                provided_tick_index=provided_tick_index,
            )
            if ok:
                _merge_matches(merged, m)
                reasons.extend(r)
                return True, merged, reasons or [{"zh": "any 命中", "en": "any matched"}]
        return False, {}, [{"zh": "any 未命中", "en": "any not matched"}]

    if key == "all":
        merged = _empty_matches()
        reasons: list[dict[str, str]] = []
        for child in (val or []):
            ok, m, r = _eval_when(
                child,
                cfs_signals=cfs_signals,
                state_windows=state_windows,
                tick_index=tick_index,
                allow_timer=allow_timer,
                context=context,
                runtime_state=runtime_state,
                provided_tick_index=provided_tick_index,
            )
            reasons.extend(r)
            if not ok:
                return False, {}, reasons or [{"zh": "all 未命中", "en": "all not matched"}]
            _merge_matches(merged, m)
        return True, merged, reasons or [{"zh": "all 命中", "en": "all matched"}]

    if key == "not":
        ok, _m, r = _eval_when(
            val,
            cfs_signals=cfs_signals,
            state_windows=state_windows,
            tick_index=tick_index,
            allow_timer=allow_timer,
            context=context,
            runtime_state=runtime_state,
            provided_tick_index=provided_tick_index,
        )
        if ok:
            return False, {}, [{"zh": "not: 子条件命中，因此 not 失败", "en": "not: child matched, so not failed"}] + r
        return True, _empty_matches(), [{"zh": "not 命中", "en": "not matched"}] + r

    if key == "cfs":
        spec = val if isinstance(val, dict) else {}
        kinds = set(str(x) for x in (spec.get("kinds") or []) if str(x))
        min_strength = float(spec.get("min_strength", 0.0) or 0.0)
        max_strength = float(spec.get("max_strength", 1.0) or 1.0)
        matched = []
        for sig in cfs_signals or []:
            if not isinstance(sig, dict):
                continue
            kind = str(sig.get("kind", "") or "")
            strength = float(sig.get("strength", 0.0) or 0.0)
            if kinds and kind not in kinds:
                continue
            if strength < min_strength or strength > max_strength:
                continue
            matched.append(sig)
        if not matched:
            return False, {}, [{"zh": "cfs: 没有匹配信号", "en": "cfs: no matched signals"}]
        return True, {"cfs": matched, "state_window": [], "timer": []}, [{"zh": f"cfs: 命中 {len(matched)} 条信号", "en": f"cfs: matched {len(matched)} signals"}]

    if key == "state_window":
        spec = val if isinstance(val, dict) else {}
        stage_filter = spec.get("stage", "any")
        stages: set[str]
        if isinstance(stage_filter, list):
            stages = {str(x) for x in stage_filter if str(x)}
        else:
            stages = {str(stage_filter or "any")}
        if "any" in stages:
            stages = {"any"}

        rise_min = int(spec.get("fast_cp_rise_min", 0) or 0)
        drop_min = int(spec.get("fast_cp_drop_min", 0) or 0)
        min_candidates = int(spec.get("min_candidate_count", 0) or 0)
        hint_any = set(str(x) for x in (spec.get("candidate_hint_any") or []) if str(x))

        matched_windows: list[dict[str, Any]] = []
        for win in state_windows or []:
            if not isinstance(win, dict):
                continue
            stage = str(win.get("stage", "any") or "any")
            if stages and ("any" not in stages) and stage not in stages:
                continue
            packet = win.get("packet") or {}
            if not isinstance(packet, dict):
                continue
            summary = packet.get("summary", {}) or {}
            candidates = list(packet.get("candidate_triggers", []) or [])
            fast_rise = int(summary.get("fast_cp_rise_item_count", 0) or 0)
            fast_drop = int(summary.get("fast_cp_drop_item_count", 0) or 0)

            if rise_min and fast_rise < rise_min:
                continue
            if drop_min and fast_drop < drop_min:
                continue
            if min_candidates and len(candidates) < min_candidates:
                continue
            if hint_any:
                if not any(str(c.get("trigger_hint", "")) in hint_any for c in candidates if isinstance(c, dict)):
                    continue

            matched_windows.append(
                {
                    "stage": stage,
                    "packet_summary": dict(summary),
                    "candidate_triggers": [c for c in candidates if isinstance(c, dict)],
                }
            )

        if not matched_windows:
            return False, {}, [{"zh": "state_window: 未命中窗口条件", "en": "state_window: no matched windows"}]
        return True, {"cfs": [], "state_window": matched_windows, "timer": []}, [{"zh": f"state_window: 命中 {len(matched_windows)} 个窗口", "en": f"state_window: matched {len(matched_windows)} windows"}]

    if key == "timer":
        if not allow_timer:
            return False, {}, [{"zh": "timer: 本接口已禁用 timer 条件", "en": "timer: disabled in this context"}]
        spec = val if isinstance(val, dict) else {}
        every_n = int(spec.get("every_n_ticks", 0) or 0)
        at_tick = int(spec.get("at_tick", 0) or 0)
        if at_tick and tick_index == at_tick:
            return True, {"cfs": [], "state_window": [], "timer": [{"at_tick": at_tick}]}, [{"zh": f"timer: tick=={at_tick}", "en": f"timer: tick=={at_tick}"}]
        if every_n and every_n > 0 and tick_index % every_n == 0:
            return True, {"cfs": [], "state_window": [], "timer": [{"every_n_ticks": every_n}]}, [{"zh": f"timer: every {every_n}", "en": f"timer: every {every_n}"}]
        return False, {}, [{"zh": "timer: 未命中", "en": "timer: not matched"}]

    if key == "metric":
        spec = val if isinstance(val, dict) else {}
        ok, metric_matches, reasons = _eval_metric_when(
            spec=spec,
            tick_index=tick_index,
            context=context,
            runtime_state=runtime_state,
            provided_tick_index=provided_tick_index,
        )
        if not ok:
            return False, {}, reasons
        return True, metric_matches, reasons

    return False, {}, [{"zh": f"未知 when 类型: {key}", "en": f"unknown when type: {key}"}]


def _empty_matches() -> dict[str, Any]:
    return {"cfs": [], "state_window": [], "timer": [], "metric": [], "vars": {}}


def _merge_matches(dst: dict[str, Any], src: dict[str, Any]) -> None:
    if not isinstance(dst, dict) or not isinstance(src, dict):
        return
    if isinstance(src.get("cfs"), list):
        dst.setdefault("cfs", [])
        dst["cfs"].extend(src.get("cfs", []))
    if isinstance(src.get("state_window"), list):
        dst.setdefault("state_window", [])
        dst["state_window"].extend(src.get("state_window", []))
    if isinstance(src.get("timer"), list):
        dst.setdefault("timer", [])
        dst["timer"].extend(src.get("timer", []))
    if isinstance(src.get("metric"), list):
        dst.setdefault("metric", [])
        dst["metric"].extend(src.get("metric", []))
    if isinstance(src.get("vars"), dict):
        dst.setdefault("vars", {})
        if isinstance(dst.get("vars"), dict):
            dst["vars"].update(src.get("vars", {}))


def _summarize_matches(matches: dict[str, Any]) -> dict[str, Any]:
    cfs_count = len(matches.get("cfs", []) or []) if isinstance(matches.get("cfs"), list) else 0
    win_count = len(matches.get("state_window", []) or []) if isinstance(matches.get("state_window"), list) else 0
    timer_count = len(matches.get("timer", []) or []) if isinstance(matches.get("timer"), list) else 0
    metric_count = len(matches.get("metric", []) or []) if isinstance(matches.get("metric"), list) else 0
    var_count = len(matches.get("vars", {}) or {}) if isinstance(matches.get("vars"), dict) else 0
    return {
        "cfs_match_count": cfs_count,
        "state_window_match_count": win_count,
        "timer_match_count": timer_count,
        "metric_match_count": metric_count,
        "var_count": var_count,
    }


def _build_focus_directives_from_action(
    *,
    rule_id: str,
    rule_title: str,
    spec: dict[str, Any],
    matches: dict[str, Any],
    now_ms: int,
    defaults: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Build focus directives from a focus action spec.
    从 focus 动作生成聚焦指令。
    """
    source = str(spec.get("from", "cfs_matches") or "cfs_matches")
    match_policy = str(spec.get("match_policy", "all") or "all")

    ttl_ticks = int(spec.get("ttl_ticks", defaults.get("ttl_ticks", 2)) or defaults.get("ttl_ticks", 2))
    focus_boost = float(spec.get("focus_boost", defaults.get("focus_boost", 0.9)) or defaults.get("focus_boost", 0.9))
    dedup_by = str(spec.get("deduplicate_by", defaults.get("deduplicate_by", "target_ref_object_id")) or defaults.get("deduplicate_by", "target_ref_object_id"))
    max_directives = int(spec.get("max_directives", 0) or 0) or int(defaults.get("max_directives_per_rule", 8) or 8)
    max_directives = max(1, min(64, max_directives))

    directives: list[dict[str, Any]] = []

    if source == "state_window_candidates":
        windows = matches.get("state_window", []) if isinstance(matches.get("state_window"), list) else []
        candidates: list[dict[str, Any]] = []
        for win in windows:
            if not isinstance(win, dict):
                continue
            for c in (win.get("candidate_triggers", []) or []):
                if isinstance(c, dict):
                    candidates.append(c)
        candidates = candidates[:max_directives]
        for idx, c in enumerate(candidates):
            item_id = str(c.get("item_id", "") or "")
            if not item_id:
                continue
            strength = float(c.get("value", 1.0) or 1.0)
            strength = max(0.0, min(1.0, abs(strength)))
            directives.append(
                {
                    "directive_id": f"focus_{rule_id}_sw_{item_id}_{idx}",
                    "directive_type": "attention_focus",
                    "source_kind": str(c.get("trigger_hint", "state_window") or "state_window"),
                    "strength": round(strength, 6),
                    "focus_boost": round(max(0.0, focus_boost), 6),
                    "ttl_ticks": int(max(1, ttl_ticks)),
                    "target_ref_object_id": "",
                    "target_ref_object_type": "",
                    "target_item_id": item_id,
                    "target_display": str(c.get("display", "") or ""),
                    "created_at": int(now_ms),
                    "rule_id": str(rule_id or ""),
                    "rule_title": str(rule_title or ""),
                    "reasons": [f"先天规则:{rule_title or rule_id}", f"rule_id:{rule_id}", "from:state_window_candidates"],
                }
            )
        return _dedup_focus_directives_by_target(directives, dedup_by=dedup_by)

    # Default: from cfs matches
    signals = matches.get("cfs", []) if isinstance(matches.get("cfs"), list) else []
    typed = [s for s in signals if isinstance(s, dict)]
    if not typed:
        return []

    if match_policy == "strongest":
        typed.sort(key=lambda s: float(s.get("strength", 0.0) or 0.0), reverse=True)
        typed = typed[:1]
    elif match_policy == "first":
        typed = typed[:1]
    else:
        typed = typed[:max_directives]

    for sig in typed:
        kind = str(sig.get("kind", "") or "")
        strength = float(sig.get("strength", 0.0) or 0.0)
        strength = max(0.0, min(1.0, strength))

        target = sig.get("target") if isinstance(sig.get("target"), dict) else {}
        target_ref_id = str(target.get("target_ref_object_id", "") or "")
        target_ref_type = str(target.get("target_ref_object_type", "") or "")
        target_item_id = str(target.get("target_item_id", "") or "")
        target_display = str(target.get("target_display", "") or sig.get("target_display", "") or "")
        if not target_ref_id and not target_item_id:
            continue

        if dedup_by == "target_item_id":
            dedup_key = target_item_id or target_ref_id
        else:
            dedup_key = target_ref_id or target_item_id
        dedup_key = dedup_key or target_item_id or target_ref_id

        directives.append(
            {
                "directive_id": f"focus_{rule_id}_{kind}_{dedup_key}",
                "directive_type": "attention_focus",
                "source_kind": kind,
                "strength": round(strength, 6),
                "focus_boost": round(max(0.0, focus_boost), 6),
                "ttl_ticks": int(max(1, ttl_ticks)),
                "target_ref_object_id": target_ref_id,
                "target_ref_object_type": target_ref_type,
                "target_item_id": target_item_id,
                "target_display": target_display,
                "created_at": int(now_ms),
                "rule_id": str(rule_id or ""),
                "rule_title": str(rule_title or ""),
                "reasons": [f"先天规则:{rule_title or rule_id}"] + list(sig.get("reasons", []) or []) + [f"rule_id:{rule_id}", "from:cfs_matches"],
            }
        )

    return _dedup_focus_directives_by_target(directives, dedup_by=dedup_by)


def _dedup_focus_directives_by_target(directives: list[dict[str, Any]], *, dedup_by: str) -> list[dict[str, Any]]:
    """Deduplicate focus directives by target key (keep last) / 按目标去重（保留最后一个）。"""
    if not directives:
        return []
    by_key: dict[str, dict[str, Any]] = {}
    for d in directives:
        if not isinstance(d, dict):
            continue
        if dedup_by == "target_item_id":
            key = str(d.get("target_item_id", "") or "")
        else:
            key = str(d.get("target_ref_object_id", "") or "") or str(d.get("target_item_id", "") or "")
        if not key:
            continue
        by_key[key] = d
    return list(by_key.values())
