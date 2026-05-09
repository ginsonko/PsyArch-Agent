# -*- coding: utf-8 -*-
"""
AP 先天编码脚本管理模块（IESM）— 主模块
=====================================

说明
----
原型阶段 IESM 不实现复杂 DSL/沙箱，而以“YAML 参数化规则集”的方式落地：
  - 可加载/热加载脚本配置（版本化、可审计字段）
  - 可执行 state_window 检查（对接 StatePool 的 script_check_packet）
  - 可基于 CFS 结果生成 directives（例如注意力聚焦指令），并提供 TTL

核心目标：让系统能在冷启动阶段具备可控、可观测的先天规则闭环，而非占位接口。

术语与缩写 / Glossary
--------------------
  - 先天编码脚本管理器（IESM, Innate Encoded Script Manager）
  - 认知感受系统（CFS, Cognitive Feeling System）
  - 注意力过滤器（AF, Attention Filter）
  - 状态池（StatePool, SP）
"""

from __future__ import annotations

import os
import time
import traceback
import copy
from typing import Any

from . import __module_name__, __schema_version__, __version__
from ._logger import ModuleLogger
from ._rules_engine import (
    default_backup_dir,
    default_rules_path,
    dump_rules_yaml,
    evaluate_rules,
    load_rules_yaml,
    metric_preset_catalog,
    normalize_rules_doc,
    render_rules_file,
    save_rules_file,
)


def _load_yaml_config(path: str) -> dict:
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except ImportError:
        return {}
    except Exception:
        return {}


_DEFAULT_CONFIG: dict[str, Any] = {
    # ---- 基础 ----
    "script_version": "0.1",
    "enabled": True,

    # ---- 规则引擎 / Declarative rules engine ----
    # rules_engine_enable: 是否启用“规则文件 innate_rules.yaml”的声明式规则系统。
    # - 启用后：优先使用 rules 文件驱动触发/指令输出；
    # - 禁用后：回退到本文件内的旧版参数化规则（state_window_rules / focus_rules）。
    "rules_engine_enable": True,
    # rules_path: 规则文件路径。为空则使用模块默认路径 innate_script/config/innate_rules.yaml
    "rules_path": "",
    # rules_backup_dir: 保存规则时的备份目录。为空则使用 innate_script/config/rules_history
    "rules_backup_dir": "",
    # rules_backup_keep: 备份保留数量（最近 N 份）
    "rules_backup_keep": 20,

    # ---- state_window 检查规则（MVP）----
    "state_window_rules": {
        "enable": True,
        "trigger_on_fast_cp_rise": True,
        "trigger_on_fast_cp_drop": True,
        "min_candidate_count": 1,
    },

    # ---- 注意力聚焦 directives（由 CFS 触发）----
    "focus_rules": {
        "enable": True,
        "from_cfs_kinds": ["dissonance", "surprise", "pressure", "expectation"],
        "min_strength": 0.3,
        "default_ttl_ticks": 2,
        "focus_boost": 0.9,
        "deduplicate_by": "target_ref_object_id",
    },

    # ---- 日志 ----
    "log_dir": "",
    "log_max_file_bytes": 5 * 1024 * 1024,
    "stdout_fallback_when_log_fail": True,
}


class InnateScriptManager:
    """
    先天脚本管理器（IESM）主类。

    对外最小接口：
      - check_state_window(packet) -> triggered_scripts, audit
      - get_active_scripts() -> scripts metadata
      - build_focus_directives(cfs_signals) -> directives for next tick attention
    """

    def __init__(self, config_path: str = "", config_override: dict | None = None):
        self._config_path = config_path or os.path.join(os.path.dirname(__file__), "config", "innate_script_config.yaml")
        self._config = self._build_config(config_override)
        self._logger = ModuleLogger(
            log_dir=self._config.get("log_dir", ""),
            max_file_bytes=int(self._config.get("log_max_file_bytes", 5 * 1024 * 1024)),
            enable_stdout_fallback=bool(self._config.get("stdout_fallback_when_log_fail", True)),
        )
        self._total_calls = 0

        # ---- Declarative rules engine / 声明式规则引擎（innate_rules.yaml）----
        self._rules_engine_enable = bool(self._config.get("rules_engine_enable", True))
        module_dir = os.path.dirname(__file__)
        self._rules_path = os.path.abspath(str(self._config.get("rules_path", "") or "").strip() or default_rules_path(module_dir))
        self._rules_backup_dir = os.path.abspath(str(self._config.get("rules_backup_dir", "") or "").strip() or default_backup_dir(module_dir))
        self._rules_backup_keep = int(self._config.get("rules_backup_keep", 20) or 20)
        self._rules_doc: dict[str, Any] = {}
        self._rules_errors: list[dict[str, Any]] = []
        self._rules_warnings: list[dict[str, Any]] = []
        self._rules_loaded_at_ms = 0
        self._rules_raw_yaml: str = ""
        self._rules_runtime_state: dict[str, Any] = {}
        self._reload_rules_internal(trace_id="iesm_init")

    def close(self) -> None:
        self._logger.close()

    # ================================================================== #
    # 接口一：check_state_window                                          #
    # ================================================================== #

    def check_state_window(self, packet: dict, trace_id: str = "") -> dict:
        start_time = time.time()
        self._total_calls += 1

        tid = str(packet.get("trace_id") or trace_id or "")
        tick_id = str(packet.get("tick_id") or tid)

        if not self._config.get("enabled", True):
            return self._make_response(
                success=True,
                code="OK_DISABLED",
                message="先天编码脚本管理器（IESM）已禁用 / IESM disabled",
                data={
                    "script_version": self._config.get("script_version", ""),
                    "triggered_scripts": [],
                    "directives": {},
                    "audit": {"disabled": True},
                },
                trace_id=tid,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        if not isinstance(packet, dict):
            return self._make_response(
                success=False,
                code="INPUT_VALIDATION_ERROR",
                message="packet 必须是 dict / packet must be dict",
                error={"code": "packet_type_error"},
                trace_id=tid,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        # ---- Rules engine path (preferred) / 声明式规则引擎优先 ----
        if self._rules_engine_enable and self._rules_doc and not self._rules_errors:
            engine = evaluate_rules(
                doc=self._rules_doc,
                trace_id=tid,
                tick_id=tick_id,
                tick_index=None,
                cfs_signals=[],
                state_windows=[{"stage": "any", "packet": packet}],
                now_ms=None,
                # dry-run: do not mutate cooldown bookkeeping in this helper API
                runtime_state=copy.deepcopy(self._rules_runtime_state),
                # check_state_window is a window check API; timer predicates should be evaluated in run_tick_rules.
                # check_state_window 是“状态窗口检查”接口；timer 条件应在 run_tick_rules 中评估。
                allow_timer=False,
            )
            data_directives = engine.get("directives", {}) if isinstance(engine, dict) else {}
            return self._make_response(
                success=True,
                code="OK",
                message="状态窗口检查完成（规则引擎） / state window checked (rules engine)",
                data={
                    "script_version": self._config.get("script_version", ""),
                    "triggered_scripts": list(engine.get("triggered_scripts", []) or []),
                    "directives": dict(data_directives) if isinstance(data_directives, dict) else {},
                    "audit": engine.get("audit", {}),
                    "triggered_rules": engine.get("triggered_rules", []),
                },
                trace_id=tid,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        rules = self._config.get("state_window_rules", {}) or {}
        if not rules.get("enable", True):
            return self._make_response(
                success=True,
                code="OK_RULE_DISABLED",
                message="状态窗口规则已禁用 / state_window rules disabled",
                data={
                    "script_version": self._config.get("script_version", ""),
                    "triggered_scripts": [],
                    "directives": {},
                    "audit": {"rules_disabled": True},
                },
                trace_id=tid,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        summary = packet.get("summary", {}) or {}
        candidates = list(packet.get("candidate_triggers", []))
        triggered_scripts: list[dict] = []

        try:
            min_candidates = max(0, int(rules.get("min_candidate_count", 1)))
            if min_candidates and len(candidates) < min_candidates:
                pass
            else:
                if rules.get("trigger_on_fast_cp_rise", True) and int(summary.get("fast_cp_rise_item_count", 0) or 0) > 0:
                    triggered_scripts.append(
                        {
                            "script_id": "innate_state_window_cp_rise",
                            "script_kind": "window_trigger",
                            "priority": 50,
                            "trigger": "fast_cp_rise",
                            "trigger_count": int(summary.get("fast_cp_rise_item_count", 0) or 0),
                            "created_at": int(time.time() * 1000),
                        }
                    )
                if rules.get("trigger_on_fast_cp_drop", True) and int(summary.get("fast_cp_drop_item_count", 0) or 0) > 0:
                    triggered_scripts.append(
                        {
                            "script_id": "innate_state_window_cp_drop",
                            "script_kind": "window_trigger",
                            "priority": 50,
                            "trigger": "fast_cp_drop",
                            "trigger_count": int(summary.get("fast_cp_drop_item_count", 0) or 0),
                            "created_at": int(time.time() * 1000),
                        }
                    )

            audit = {
                "packet_id": packet.get("packet_id", ""),
                "window_start_ms": packet.get("window_start_ms"),
                "window_end_ms": packet.get("window_end_ms"),
                "candidate_count": len(candidates),
                "summary": dict(summary),
            }

            self._logger.brief(
                trace_id=tid,
                tick_id=tick_id,
                interface="check_state_window",
                success=True,
                input_summary={"candidate_count": len(candidates)},
                output_summary={"triggered_script_count": len(triggered_scripts)},
                message="状态窗口检查完成 / state window checked",
            )

            return self._make_response(
                success=True,
                code="OK",
                message="状态窗口检查完成 / state window checked",
                data={
                    "script_version": self._config.get("script_version", ""),
                    "triggered_scripts": triggered_scripts,
                    "directives": {},
                    "audit": audit,
                },
                trace_id=tid,
                elapsed_ms=self._elapsed_ms(start_time),
            )
        except Exception as exc:
            self._logger.error(
                trace_id=tid,
                tick_id=tick_id,
                interface="check_state_window",
                code="RUNTIME_ERROR",
                message=f"状态窗口检查失败 / check_state_window failed: {exc}",
                detail={"traceback": traceback.format_exc()},
            )
            return self._make_response(
                success=False,
                code="RUNTIME_ERROR",
                message=f"状态窗口检查失败 / check_state_window failed: {exc}",
                error={"code": "runtime_error", "message": str(exc)},
                trace_id=tid,
                elapsed_ms=self._elapsed_ms(start_time),
            )

    # ================================================================== #
    # 接口二：get_active_scripts                                          #
    # ================================================================== #

    def get_active_scripts(self, trace_id: str = "") -> dict:
        start_time = time.time()
        self._total_calls += 1
        tid = trace_id or "iesm_snapshot"

        focus = self._config.get("focus_rules", {}) or {}
        window = self._config.get("state_window_rules", {}) or {}
        rules_enabled = bool(self._rules_engine_enable and self._rules_doc and not self._rules_errors and bool(self._rules_doc.get("enabled", True)))
        rule_count = len(self._rules_doc.get("rules", []) or []) if isinstance(self._rules_doc, dict) else 0
        scripts = [
            {
                "script_id": "rules_engine",
                "enabled": bool(rules_enabled),
                "kind": "declarative_rules",
                "detail": {
                    "rules_path": self._rules_path,
                    "rules_version": str(self._rules_doc.get("rules_version", "")) if isinstance(self._rules_doc, dict) else "",
                    "rule_count": int(rule_count),
                    "error_count": int(len(self._rules_errors)),
                    "warning_count": int(len(self._rules_warnings)),
                },
            },
            {
                "script_id": "state_window_rules",
                "enabled": bool(window.get("enable", True)),
                "kind": "window_trigger",
            },
            {
                "script_id": "focus_rules",
                "enabled": bool(focus.get("enable", True)),
                "kind": "directive_builder",
            },
        ]
        return self._make_response(
            success=True,
            code="OK",
            message="活跃脚本列表 / active scripts",
            data={
                "script_version": self._config.get("script_version", ""),
                "scripts": scripts,
            },
            trace_id=tid,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    # 接口三：build_focus_directives                                     #
    # ================================================================== #

    def build_focus_directives(
        self,
        cfs_signals: list[dict],
        *,
        trace_id: str,
        tick_id: str | None = None,
    ) -> dict:
        start_time = time.time()
        self._total_calls += 1
        tick_id = tick_id or trace_id

        # ---- Rules engine path (preferred) / 声明式规则引擎优先 ----
        if self._rules_engine_enable and self._rules_doc and not self._rules_errors:
            engine = evaluate_rules(
                doc=self._rules_doc,
                trace_id=trace_id,
                tick_id=tick_id,
                tick_index=None,
                cfs_signals=list(cfs_signals or []),
                state_windows=[],
                now_ms=None,
                # dry-run: do not mutate cooldown bookkeeping in this helper API
                runtime_state=copy.deepcopy(self._rules_runtime_state),
            )
            data = engine.get("directives", {}) if isinstance(engine, dict) else {}
            directives = list(data.get("focus_directives", []) or []) if isinstance(data, dict) else []
            return self._make_response(
                success=True,
                code="OK",
                message="注意力聚焦指令已生成（规则引擎） / focus directives built (rules engine)",
                data={
                    "focus_directives": directives,
                    "audit": engine.get("audit", {}),
                    "triggered_rules": engine.get("triggered_rules", []),
                },
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        rules = self._config.get("focus_rules", {}) or {}
        if not self._config.get("enabled", True) or not rules.get("enable", True):
            return self._make_response(
                success=True,
                code="OK_DISABLED",
                message="聚焦规则已禁用 / focus rules disabled",
                data={"focus_directives": [], "audit": {"disabled": True}},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        kinds_allow = {str(x) for x in (rules.get("from_cfs_kinds") or []) if str(x)}
        min_strength = float(rules.get("min_strength", 0.3))
        ttl_ticks = max(1, int(rules.get("default_ttl_ticks", 2)))
        focus_boost = float(rules.get("focus_boost", 0.9))
        dedup_by = str(rules.get("deduplicate_by", "target_ref_object_id") or "target_ref_object_id")

        directives: list[dict] = []
        seen: set[str] = set()
        now_ms = int(time.time() * 1000)

        for sig in cfs_signals or []:
            kind = str(sig.get("kind", ""))
            strength = float(sig.get("strength", 0.0) or 0.0)
            if kinds_allow and kind not in kinds_allow:
                continue
            if strength < min_strength:
                continue

            target = sig.get("target") or {}
            target_ref_id = str(target.get("target_ref_object_id", "") or "")
            target_ref_type = str(target.get("target_ref_object_type", "") or "")
            target_item_id = str(target.get("target_item_id", "") or "")

            if not target_ref_id and not target_item_id:
                continue

            if dedup_by == "target_item_id":
                dedup_key = target_item_id
            else:
                dedup_key = target_ref_id or target_item_id

            if dedup_key and dedup_key in seen:
                continue
            if dedup_key:
                seen.add(dedup_key)

            directives.append(
                {
                    "directive_id": f"focus_{kind}_{dedup_key or len(directives)}",
                    "directive_type": "attention_focus",
                    "source_kind": kind,
                    "strength": round(max(0.0, min(1.0, strength)), 6),
                    "focus_boost": round(max(0.0, focus_boost), 6),
                    "ttl_ticks": ttl_ticks,
                    "target_ref_object_id": target_ref_id,
                    "target_ref_object_type": target_ref_type,
                    "target_item_id": target_item_id,
                    "target_display": str(target.get("target_display", "") or sig.get("target_display", "") or ""),
                    "created_at": now_ms,
                    "reasons": list(sig.get("reasons", []) or []),
                }
            )

        self._logger.brief(
            trace_id=trace_id,
            tick_id=tick_id,
            interface="build_focus_directives",
            success=True,
            input_summary={"signal_count": len(cfs_signals or [])},
            output_summary={"directive_count": len(directives)},
            message="注意力聚焦指令已生成 / focus directives built",
        )

        return self._make_response(
            success=True,
            code="OK",
            message="注意力聚焦指令已生成 / focus directives built",
            data={
                "focus_directives": directives,
                "audit": {
                    "kinds_allow": sorted(kinds_allow),
                    "min_strength": min_strength,
                    "ttl_ticks": ttl_ticks,
                    "deduplicated_count": max(0, (len(cfs_signals or []) - len(directives))),
                },
            },
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    # 新接口：run_tick_rules（推荐）                                       #
    # ================================================================== #

    def run_tick_rules(
        self,
        *,
        trace_id: str,
        tick_id: str,
        tick_index: int | None = None,
        cfs_signals: list[dict] | None = None,
        state_windows: list[dict[str, Any]] | None = None,
        context: dict[str, Any] | None = None,
        dry_run: bool = False,
        allowed_phases: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> dict:
        """
        对完整 tick 上下文执行 IESM 规则（推荐使用）。
        Evaluate IESM rules for a full tick context.

        Parameters / 参数：
          - cfs_signals: CFS 输出信号列表
          - state_windows: [{"stage": "...", "packet": <script_check_packet>}, ...]
          - context: 规则上下文（指标/状态池/情绪/查存过程等运行态数据），用于 metric 条件与脚本变量
          - dry_run: True 时不修改冷却/记账状态（用于前端模拟）
          - allowed_phases: 只执行指定 phase（如 ["cfs", "directives"] / ["emotion_post"]）
        """
        start_time = time.time()
        self._total_calls += 1

        if not self._config.get("enabled", True):
            return self._make_response(
                success=True,
                code="OK_DISABLED",
                message="先天编码脚本管理器（IESM）已禁用 / IESM disabled",
                data={
                    "script_version": self._config.get("script_version", ""),
                    "rules_engine_enable": bool(self._rules_engine_enable),
                    "rules_path": self._rules_path,
                    "triggered_rules": [],
                    "triggered_scripts": [],
                    "directives": {"focus_directives": [], "emotion_updates": {}, "action_triggers": []},
                    "audit": {"disabled": True},
                },
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        # Prefer rules engine if enabled and valid.
        if self._rules_engine_enable and self._rules_doc and not self._rules_errors:
            runtime_state = copy.deepcopy(self._rules_runtime_state) if dry_run else self._rules_runtime_state
            engine = evaluate_rules(
                doc=self._rules_doc,
                trace_id=trace_id,
                tick_id=tick_id,
                tick_index=tick_index,
                cfs_signals=list(cfs_signals or []),
                state_windows=list(state_windows or []),
                context=context if isinstance(context, dict) else {},
                now_ms=None,
                runtime_state=runtime_state,
                allowed_phases=allowed_phases,
            )
            return self._make_response(
                success=True,
                code="OK",
                message="tick 规则评估完成 / tick rules evaluated",
                data={
                    "script_version": self._config.get("script_version", ""),
                    "rules_engine_enable": bool(self._rules_engine_enable),
                    "rules_path": self._rules_path,
                    "rules_version": str(self._rules_doc.get("rules_version", "")),
                    "rules_schema_version": str(self._rules_doc.get("rules_schema_version", "")),
                    "triggered_rules": engine.get("triggered_rules", []),
                    "triggered_scripts": engine.get("triggered_scripts", []),
                    "directives": engine.get("directives", {}),
                    "audit": engine.get("audit", {}),
                    "validation": {
                        "error_count": len(self._rules_errors),
                        "warning_count": len(self._rules_warnings),
                    },
                },
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        # Legacy fallback / 旧逻辑回退：仅保证闭环可跑
        focus = self.build_focus_directives(list(cfs_signals or []), trace_id=trace_id, tick_id=tick_id).get("data", {}) or {}
        directives = {"focus_directives": list(focus.get("focus_directives", []) or []), "emotion_updates": {}, "action_triggers": []}
        return self._make_response(
            success=True,
            code="OK_FALLBACK",
            message="tick 规则评估完成（旧逻辑回退） / tick rules evaluated (legacy fallback)",
            data={
                "script_version": self._config.get("script_version", ""),
                "rules_engine_enable": bool(self._rules_engine_enable),
                "rules_path": self._rules_path,
                "triggered_rules": [],
                "triggered_scripts": [],
                "directives": directives,
                "audit": {"fallback": True, "reason": "rules engine disabled or invalid"},
                "validation": {
                    "error_count": len(self._rules_errors),
                    "warning_count": len(self._rules_warnings),
                },
            },
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    # 规则文件管理：读取/校验/保存/热加载                                 #
    # ================================================================== #

    def get_rules_bundle(self, *, trace_id: str = "iesm_rules_bundle", include_file_yaml: bool = True) -> dict:
        """Return rules file bundle for UI / 返回规则文件信息（供前端 UI）。"""
        start_time = time.time()
        data = {
            "rules_engine_enable": bool(self._rules_engine_enable),
            "rules_path": self._rules_path,
            "rules_backup_dir": self._rules_backup_dir,
            "rules_backup_keep": int(self._rules_backup_keep),
            "loaded_at_ms": int(self._rules_loaded_at_ms),
            "normalized_doc": copy.deepcopy(self._rules_doc) if isinstance(self._rules_doc, dict) else {},
            "normalized_yaml": dump_rules_yaml(self._rules_doc) if isinstance(self._rules_doc, dict) else "",
            "errors": list(self._rules_errors),
            "warnings": list(self._rules_warnings),
            "rule_count": len(self._rules_doc.get("rules", []) or []) if isinstance(self._rules_doc, dict) else 0,
            # UI helper catalogs / 前端辅助目录
            # - metric_presets: 指标预设下拉列表（中文优先）
            "metric_presets": metric_preset_catalog(),
        }
        if include_file_yaml:
            data["file_yaml"] = str(self._rules_raw_yaml or "")
        return self._make_response(
            success=True,
            code="OK",
            message="rules bundle",
            data=data,
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    def validate_rules(
        self,
        *,
        trace_id: str,
        doc: dict[str, Any] | None = None,
        yaml_text: str | None = None,
    ) -> dict:
        """Validate a rules doc or yaml text / 校验规则（doc 或 yaml）。"""
        start_time = time.time()
        self._total_calls += 1

        raw: dict[str, Any] | None = None
        parse_error: str | None = None
        if yaml_text is not None:
            try:
                import yaml as _yaml  # local import
                loaded = _yaml.safe_load(str(yaml_text))
                raw = loaded if isinstance(loaded, dict) else None
                if raw is None:
                    parse_error = "yaml must be a mapping/dict"
            except Exception as exc:
                parse_error = str(exc)
        elif doc is not None:
            raw = doc if isinstance(doc, dict) else None
            if raw is None:
                parse_error = "doc must be dict"
        else:
            parse_error = "missing doc/yaml_text"

        if parse_error:
            return self._make_response(
                success=False,
                code="VALIDATION_ERROR",
                message=f"rules parse failed: {parse_error}",
                error={"code": "rules_parse_error", "message": parse_error},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        normalized, errors, warnings = normalize_rules_doc(raw)
        return self._make_response(
            success=(len(errors) == 0),
            code="OK" if not errors else "RULES_INVALID",
            message="rules validated" if not errors else f"rules invalid: {len(errors)} errors",
            data={
                "normalized_doc": normalized,
                "yaml_preview": render_rules_file(normalized),
                "errors": errors,
                "warnings": warnings,
            },
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    def save_rules(
        self,
        *,
        trace_id: str,
        doc: dict[str, Any] | None = None,
        yaml_text: str | None = None,
    ) -> dict:
        """Validate + save + hot reload rules / 校验+保存+热加载规则。"""
        start_time = time.time()
        self._total_calls += 1

        validate = self.validate_rules(trace_id=f"{trace_id}_validate", doc=doc, yaml_text=yaml_text)
        if not validate.get("success"):
            return self._make_response(
                success=False,
                code="RULES_INVALID",
                message=validate.get("message", "rules invalid"),
                data=validate.get("data", {}),
                error=validate.get("error", {}),
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        normalized = (validate.get("data", {}) or {}).get("normalized_doc", {}) or {}
        ok, msg = save_rules_file(
            path=self._rules_path,
            doc=normalized,
            backup_dir=self._rules_backup_dir,
            backup_keep=int(self._rules_backup_keep),
        )
        if not ok:
            return self._make_response(
                success=False,
                code="RULES_SAVE_ERROR",
                message=f"rules save failed: {msg}",
                error={"code": "rules_save_failed", "message": msg},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        self._reload_rules_internal(trace_id=f"{trace_id}_reload")
        bundle = self.get_rules_bundle(trace_id=f"{trace_id}_bundle").get("data", {}) or {}
        bundle["save_message"] = msg
        return self._make_response(
            success=True,
            code="OK",
            message="rules saved and reloaded",
            data=bundle,
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    def reload_rules(self, *, trace_id: str) -> dict:
        """Reload rules from disk / 从磁盘热加载规则文件。"""
        start_time = time.time()
        self._total_calls += 1
        ok = self._reload_rules_internal(trace_id=trace_id)
        bundle = self.get_rules_bundle(trace_id=f"{trace_id}_bundle").get("data", {}) or {}
        return self._make_response(
            success=bool(ok),
            code="OK" if ok else "RULES_INVALID",
            message="rules reloaded" if ok else "rules reloaded with errors",
            data=bundle,
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    def _reload_rules_internal(self, *, trace_id: str) -> bool:
        """Internal load+normalize. Never throws. / 内部加载+规范化，不抛异常。"""
        self._rules_loaded_at_ms = int(time.time() * 1000)
        try:
            # keep raw file text for UI display
            if os.path.exists(self._rules_path):
                with open(self._rules_path, "r", encoding="utf-8") as fh:
                    self._rules_raw_yaml = fh.read()
            else:
                self._rules_raw_yaml = ""

            raw, err = load_rules_yaml(self._rules_path)
            if err:
                self._rules_doc = {}
                self._rules_errors = [{"level": "error", "path": "$", "message_en": err, "message_zh": f"规则文件加载失败：{err}"}]
                self._rules_warnings = []
                self._logger.error(
                    trace_id=trace_id,
                    interface="reload_rules",
                    code="RULES_LOAD_ERROR",
                    message=err,
                    detail={"rules_path": self._rules_path},
                )
                return False

            normalized, errors, warnings = normalize_rules_doc(raw)
            self._rules_doc = normalized
            self._rules_errors = errors
            self._rules_warnings = warnings

            self._logger.brief(
                trace_id=trace_id,
                interface="reload_rules",
                success=(len(errors) == 0),
                input_summary={"path": self._rules_path},
                output_summary={"rule_count": len(normalized.get("rules", []) or []), "error_count": len(errors), "warning_count": len(warnings)},
                message="rules loaded",
            )
            return len(errors) == 0
        except Exception as exc:
            self._rules_doc = {}
            self._rules_errors = [{"level": "error", "path": "$", "message_en": str(exc), "message_zh": f"规则文件异常：{exc}"}]
            self._rules_warnings = []
            self._logger.error(
                trace_id=trace_id,
                interface="reload_rules",
                code="RULES_LOAD_ERROR",
                message=f"rules load failed: {exc}",
                detail={"traceback": traceback.format_exc()},
            )
            return False

    # ================================================================== #
    # 接口四：reload_config / runtime snapshot                             #
    # ================================================================== #

    def get_runtime_snapshot(self, *, trace_id: str = "iesm_runtime") -> dict:
        start_time = time.time()
        return self._make_response(
            success=True,
            code="OK",
            message="innate_script runtime snapshot",
            data={
                "module": __module_name__,
                "version": __version__,
                "schema_version": __schema_version__,
                "config_summary": dict(self._config),
                "rules_summary": {
                    "rules_engine_enable": bool(self._rules_engine_enable),
                    "rules_path": self._rules_path,
                    "loaded_at_ms": int(self._rules_loaded_at_ms),
                    "rules_version": str(self._rules_doc.get("rules_version", "")) if isinstance(self._rules_doc, dict) else "",
                    "rules_schema_version": str(self._rules_doc.get("rules_schema_version", "")) if isinstance(self._rules_doc, dict) else "",
                    "rule_count": len(self._rules_doc.get("rules", []) or []) if isinstance(self._rules_doc, dict) else 0,
                    "error_count": len(self._rules_errors),
                    "warning_count": len(self._rules_warnings),
                },
                "stats": {"total_calls": int(self._total_calls)},
            },
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    def reload_config(
        self,
        *,
        trace_id: str,
        config_path: str | None = None,
        apply_partial: bool = True,
    ) -> dict:
        start_time = time.time()
        path = config_path or self._config_path

        try:
            new_raw = _load_yaml_config(path)
            if not new_raw:
                return self._make_response(
                    success=False,
                    code="CONFIG_ERROR",
                    message=f"配置文件加载失败或为空 / Config file failed to load or empty: {path}",
                    trace_id=trace_id,
                    elapsed_ms=self._elapsed_ms(start_time),
                )

            applied: list[str] = []
            rejected: list[dict] = []
            for key, val in new_raw.items():
                if key not in _DEFAULT_CONFIG:
                    rejected.append({"key": key, "reason": "未知配置项 / Unknown config key"})
                    continue
                expected_type = type(_DEFAULT_CONFIG[key])
                if isinstance(val, expected_type) or (expected_type is float and isinstance(val, (int, float))):
                    self._config[key] = val
                    applied.append(key)
                else:
                    rejected.append(
                        {
                            "key": key,
                            "reason": f"类型不匹配 / Type mismatch: expected {expected_type.__name__}, got {type(val).__name__}",
                        }
                    )

            self._logger.update_config(
                log_dir=str(self._config.get("log_dir", "")),
                max_file_bytes=int(self._config.get("log_max_file_bytes", 0) or 0),
            )

            # ---- Rules engine config sync / 同步规则引擎配置 ----
            prev_rules_path = self._rules_path
            prev_backup_dir = self._rules_backup_dir
            prev_engine_enable = bool(self._rules_engine_enable)
            module_dir = os.path.dirname(__file__)
            self._rules_engine_enable = bool(self._config.get("rules_engine_enable", True))
            self._rules_path = os.path.abspath(str(self._config.get("rules_path", "") or "").strip() or default_rules_path(module_dir))
            self._rules_backup_dir = os.path.abspath(str(self._config.get("rules_backup_dir", "") or "").strip() or default_backup_dir(module_dir))
            self._rules_backup_keep = int(self._config.get("rules_backup_keep", 20) or 20)
            if self._rules_path != prev_rules_path or self._rules_backup_dir != prev_backup_dir or bool(self._rules_engine_enable) != prev_engine_enable:
                self._reload_rules_internal(trace_id=trace_id)

            self._logger.brief(
                trace_id=trace_id,
                interface="reload_config",
                success=True,
                input_summary={"path": path},
                output_summary={"applied_count": len(applied), "rejected_count": len(rejected)},
                message="hot reload done",
            )

            if rejected and not apply_partial:
                return self._make_response(
                    success=False,
                    code="CONFIG_ERROR",
                    message=f"部分配置项被拒绝 / Some config items rejected: {len(rejected)}",
                    data={"applied": applied, "rejected": rejected},
                    trace_id=trace_id,
                    elapsed_ms=self._elapsed_ms(start_time),
                )

            return self._make_response(
                success=True,
                code="OK",
                message=f"热加载完成 / Hot reload done: {len(applied)} applied, {len(rejected)} rejected",
                data={"applied": applied, "rejected": rejected},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )
        except Exception as exc:
            self._logger.error(
                trace_id=trace_id,
                interface="reload_config",
                code="CONFIG_ERROR",
                message=f"热加载失败: {exc}",
                detail={"traceback": traceback.format_exc()},
            )
            return self._make_response(
                success=False,
                code="CONFIG_ERROR",
                message=f"热加载失败 / Hot reload failed: {exc}",
                error={"code": "config_error", "message": str(exc)},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

    # ================================================================== #
    # 内部工具                                                           #
    # ================================================================== #

    def _build_config(self, config_override: dict | None) -> dict:
        config = dict(_DEFAULT_CONFIG)
        config.update(_load_yaml_config(self._config_path))
        if config_override:
            config.update(config_override)
        return config

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.time() - start) * 1000)

    @staticmethod
    def _make_response(
        success: bool,
        code: str,
        message: str,
        *,
        data: Any = None,
        error: Any = None,
        trace_id: str = "",
        elapsed_ms: int = 0,
    ) -> dict:
        return {
            "success": bool(success),
            "code": str(code),
            "message": str(message),
            "data": data,
            "error": error,
            "meta": {
                "module": __module_name__,
                "interface": "",
                "trace_id": trace_id,
                "elapsed_ms": int(elapsed_ms),
                "logged": True,
            },
        }
