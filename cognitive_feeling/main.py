# -*- coding: utf-8 -*-
"""
AP 认知感受模块（CFS）— 主模块
==============================

对齐理论（3.8 / 3.12 Step 7）的原型落地要点：
  - 生成结构化 CFS 信号（违和/正确事件/惊/期待/压力/复杂度/重复感/把握感）
  - “正确事件”硬约束：必须依托“违和显著下降/消失”触发；从未违和则不触发
  - 将关键元认知条目写回 StatePool（cfs_signal 运行态对象），让下一 tick 可被注意/脚本消费

术语与缩写 / Glossary
--------------------
  - 认知感受系统（CFS, Cognitive Feeling System）
  - 状态池（StatePool, SP）
  - 当前注意记忆体（CAM, Current Attention Memory）
  - 实能量（ER, energy.er）/ 虚能量（EV, energy.ev）
  - 认知压强（CP, Cognitive Pressure）
"""

from __future__ import annotations

import math
import os
import time
import traceback
from typing import Any

from . import __module_name__, __schema_version__, __version__
from ._logger import ModuleLogger


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
    # enabled / 总开关
    #
    # 注意（非常重要）：
    # - 本模块包含“旧版原型”的硬编码 CFS 触发逻辑（违和/正确/期待/压力等）。
    # - 当前推荐做法是：把 CFS 触发逻辑放到 IESM（先天规则，phase=cfs）中统一脚本化管理，
    #   便于观测、编辑与回滚（符合你在理论核心中的目标）。
    #
    # 因此：本模块默认关闭；只有在对照实验或过渡阶段才建议开启。
    "enabled": False,
    "max_object_signals_per_tick": 12,
    "target_ref_types_for_object_signals": ["st"],
    "write_to_state_pool": True,
    "write_strength_as_ev": True,
    "bind_presence_attribute_to_target": True,
    "attribute_bind_strength_threshold": 0.35,
    # ---- 违和感（dissonance）----
    "dissonance_cp_abs_threshold": 0.5,
    "dissonance_cp_abs_max": 2.0,
    # ---- 正确事件/正确感（correct_event，需要先出现违和并显著下降）----
    "correct_event_min_prior_dissonance_strength": 0.30,
    "correct_event_cp_drop_threshold": 0.50,
    "correct_event_strength_drop_max": 1.20,
    "correct_event_cooldown_ticks": 1,
    # ---- 惊（surprise）----
    "surprise_cp_rise_threshold": 0.50,
    "surprise_strength_rise_max": 1.20,
    "surprise_require_delta_positive": True,
    # ---- 期待/压力（expectation/pressure，当前为关键词 + EV 门控的原型实现）----
    "expectation_ev_threshold": 0.30,
    "pressure_ev_threshold": 0.30,
    # 说明：关键词是原型 fallback。更推荐使用“显式属性刺激元”（reward_signal / punish_signal）
    # 来对齐理论 3.8.2 的“奖励/惩罚嵌入预测结构”语义。
    "reward_keywords": ["reward_signal", "奖励", "reward", "positive_valence"],
    "punish_keywords": ["punish_signal", "惩罚", "punish", "negative_valence"],
    "predicted_ref_types": ["st"],
    # ---- 奖励/惩罚属性绑定（用于期待/压力的工程闭环） ----
    # 将“正确事件/压力/违和”等信号映射为目标对象上的属性刺激元（运行态绑定），
    # 以便后续当该对象被预测（EV 上升）时能触发期待/压力。
    "bind_reward_punish_attribute_to_target": True,
    "reward_attribute_name": "reward_signal",
    "punish_attribute_name": "punish_signal",
    "reward_bind_kinds": ["correct_event"],
    "punish_bind_kinds": ["pressure", "dissonance"],
    # ---- 复杂度（complexity）----
    "complexity_size_max": 24,
    "complexity_entropy_weight": 0.45,
    "complexity_size_weight": 0.55,
    # ---- 重复感/疲劳（repetition）----
    "repetition_fatigue_threshold": 0.60,
    "repetition_max_considered_items": 24,
    # ---- 把握感/置信度（grasp）----
    "grasp_alignment_eps": 1e-6,
    # ---- 日志（log）----
    "log_dir": "",
    "log_max_file_bytes": 5 * 1024 * 1024,
    "stdout_fallback_when_log_fail": True,
}


class CognitiveFeelingSystem:
    def __init__(self, config_path: str = "", config_override: dict | None = None):
        self._config_path = config_path or os.path.join(os.path.dirname(__file__), "config", "cognitive_feeling_config.yaml")
        self._config = self._build_config(config_override)
        self._logger = ModuleLogger(
            log_dir=self._config.get("log_dir", ""),
            max_file_bytes=int(self._config.get("log_max_file_bytes", 5 * 1024 * 1024)),
            enable_stdout_fallback=bool(self._config.get("stdout_fallback_when_log_fail", True)),
        )
        self._total_calls = 0
        self._tick_counter = 0

        # ref_object_id -> last dissonance strength
        self._last_dissonance_strength: dict[str, float] = {}
        self._last_correct_tick: dict[str, int] = {}

    def close(self) -> None:
        self._logger.close()

    # ================================================================== #
    # Main interface                                                      #
    # ================================================================== #

    def run_cfs(
        self,
        *,
        pool: Any,
        state_snapshot: dict,
        cam_snapshot: dict | None,
        attention_report: dict | None,
        trace_id: str,
        tick_id: str | None = None,
        context: dict | None = None,
    ) -> dict:
        start_time = time.time()
        self._total_calls += 1
        self._tick_counter += 1
        tick_number = self._tick_counter
        tick_id = tick_id or trace_id
        context = context or {}

        if not self._config.get("enabled", True):
            return self._make_response(
                True,
                "OK_DISABLED",
                "认知感受系统（CFS）已禁用 / CFS disabled",
                data={"cfs_signals": [], "writes": {"runtime_nodes": [], "attribute_bindings": []}},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        if pool is None or not hasattr(pool, "insert_runtime_node") or not hasattr(pool, "apply_energy_update"):
            return self._make_response(
                False,
                "VALIDATION_ERROR",
                "状态池（StatePool, SP）需要实现 insert_runtime_node/apply_energy_update 接口 / pool must implement insert_runtime_node/apply_energy_update",
                error={"code": "pool_invalid"},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        if not isinstance(state_snapshot, dict):
            return self._make_response(
                False,
                "INPUT_VALIDATION_ERROR",
                "state_snapshot 必须是 dict / state_snapshot must be dict",
                error={"code": "state_snapshot_type_error"},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        snapshot_items = list(state_snapshot.get("top_items", []))
        target_types = {str(x) for x in (self._config.get("target_ref_types_for_object_signals") or []) if str(x)}
        object_candidates = [
            it for it in snapshot_items
            if (not target_types or str(it.get("ref_object_type", "")) in target_types)
        ]
        ordered = sorted(object_candidates, key=lambda it: float(it.get("cp_abs", 0.0) or 0.0), reverse=True)

        cfs_signals: list[dict] = []
        cfs_signals.extend(self._compute_dissonance_signals(ordered, trace_id=trace_id, tick_id=tick_id))
        cfs_signals.extend(self._compute_correct_events(ordered, tick_number=tick_number, trace_id=trace_id, tick_id=tick_id))
        cfs_signals.extend(self._compute_surprise_events(ordered, trace_id=trace_id, tick_id=tick_id))
        cfs_signals.extend(self._compute_expectation_pressure_events(ordered, trace_id=trace_id, tick_id=tick_id))
        cfs_signals.extend(self._compute_global_signals(attention_report or {}, snapshot_items, trace_id=trace_id, tick_id=tick_id))

        # Cap object signals
        obj = [s for s in cfs_signals if s.get("scope") == "object"]
        glob = [s for s in cfs_signals if s.get("scope") != "object"]
        max_obj = max(0, int(self._config.get("max_object_signals_per_tick", 12)))
        if max_obj and len(obj) > max_obj:
            obj = sorted(obj, key=lambda s: float(s.get("strength", 0.0)), reverse=True)[:max_obj]
        cfs_signals = obj + glob

        writes = {"runtime_nodes": [], "attribute_bindings": []}
        if self._config.get("write_to_state_pool", True):
            writes = self._write_signals_to_pool(pool=pool, cfs_signals=cfs_signals, trace_id=trace_id, tick_id=tick_id)

        self._logger.brief(
            trace_id=trace_id,
            tick_id=tick_id,
            interface="run_cfs",
            success=True,
            input_summary={"snapshot_item_count": len(snapshot_items)},
            output_summary={"signal_count": len(cfs_signals), "written_nodes": len(writes.get("runtime_nodes", []))},
            message="已生成认知感受信号（CFS） / CFS signals generated",
        )
        self._logger.detail(
            trace_id=trace_id,
            tick_id=tick_id,
            step="cfs_signals",
            info={"signals": cfs_signals, "writes": writes, "context_keys": sorted(context.keys())},
        )

        return self._make_response(
            True,
            "OK",
            "已生成认知感受信号（CFS） / CFS signals generated",
            data={
                "cfs_signals": cfs_signals,
                "writes": writes,
                "meta": {"version": __version__, "schema_version": __schema_version__, "tick_number": tick_number},
            },
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    # Object signals                                                      #
    # ================================================================== #

    def _compute_dissonance_signals(self, ordered: list[dict], *, trace_id: str, tick_id: str) -> list[dict]:
        th = float(self._config.get("dissonance_cp_abs_threshold", 0.5))
        max_cp = max(th + 1e-6, float(self._config.get("dissonance_cp_abs_max", 2.0)))
        out: list[dict] = []
        for item in ordered[: max(8, int(self._config.get("max_object_signals_per_tick", 12))) ]:
            cp_abs = float(item.get("cp_abs", 0.0) or 0.0)
            if cp_abs < th:
                continue
            strength = self._clamp01((cp_abs - th) / (max_cp - th))
            if strength <= 0.0:
                continue
            sig = self._make_object_signal(
                kind="dissonance",
                strength=strength,
                item=item,
                trace_id=trace_id,
                tick_id=tick_id,
                reasons=[f"cp_abs={round(cp_abs, 6)}>=threshold({th})"],
                evidence={"cp_abs": round(cp_abs, 8), "cp_delta": round(float(item.get("cp_delta", 0.0) or 0.0), 8)},
            )
            out.append(sig)
            ref_id = str(sig.get("target", {}).get("target_ref_object_id", ""))
            if ref_id:
                self._last_dissonance_strength[ref_id] = float(sig.get("strength", 0.0))
        return out

    def _compute_correct_events(self, ordered: list[dict], *, tick_number: int, trace_id: str, tick_id: str) -> list[dict]:
        # Hard constraint: must be triggered by dissonance drop and require prior dissonance
        min_prior = float(self._config.get("correct_event_min_prior_dissonance_strength", 0.30))
        drop_th = float(self._config.get("correct_event_cp_drop_threshold", 0.50))
        drop_max = max(drop_th + 1e-6, float(self._config.get("correct_event_strength_drop_max", 1.20)))
        cooldown = max(0, int(self._config.get("correct_event_cooldown_ticks", 1)))

        items_by_ref = {str(it.get("ref_object_id", "")): it for it in ordered if str(it.get("ref_object_id", ""))}
        out: list[dict] = []
        now_ms = int(time.time() * 1000)

        for ref_id, item in items_by_ref.items():
            prior = float(self._last_dissonance_strength.get(ref_id, 0.0))
            if prior < min_prior:
                continue
            last_tick = int(self._last_correct_tick.get(ref_id, -999999))
            if cooldown and (tick_number - last_tick) <= cooldown:
                continue
            delta_cp_abs = float(item.get("delta_cp_abs", 0.0) or 0.0)
            if delta_cp_abs > -drop_th:
                continue
            strength = self._clamp01((-delta_cp_abs - drop_th) / (drop_max - drop_th))
            if strength <= 0.0:
                continue
            out.append(
                self._make_object_signal(
                    kind="correct_event",
                    strength=strength,
                    item=item,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    reasons=[
                        f"prior_dissonance={round(prior, 6)}>=min_prior({min_prior})",
                        f"delta_cp_abs={round(delta_cp_abs, 6)}<=-{drop_th}",
                    ],
                    evidence={"prior_dissonance_strength": round(prior, 8), "delta_cp_abs": round(delta_cp_abs, 8)},
                    created_at=now_ms,
                )
            )
            self._last_correct_tick[ref_id] = tick_number
            self._last_dissonance_strength[ref_id] = 0.0
        return out

    def _compute_surprise_events(self, ordered: list[dict], *, trace_id: str, tick_id: str) -> list[dict]:
        rise_th = float(self._config.get("surprise_cp_rise_threshold", 0.50))
        rise_max = max(rise_th + 1e-6, float(self._config.get("surprise_strength_rise_max", 1.20)))
        require_pos = bool(self._config.get("surprise_require_delta_positive", True))
        out: list[dict] = []
        for item in ordered[:16]:
            rise = float(item.get("delta_cp_abs", 0.0) or 0.0)
            if rise < rise_th:
                continue
            cp_delta = float(item.get("cp_delta", 0.0) or 0.0)
            if require_pos and cp_delta <= 0.0:
                continue
            strength = self._clamp01((rise - rise_th) / (rise_max - rise_th))
            if strength <= 0.0:
                continue
            out.append(
                self._make_object_signal(
                    kind="surprise",
                    strength=strength,
                    item=item,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    reasons=[f"delta_cp_abs={round(rise, 6)}>=threshold({rise_th})"],
                    evidence={"delta_cp_abs": round(rise, 8), "cp_delta": round(cp_delta, 8)},
                )
            )
        return out

    def _compute_expectation_pressure_events(self, ordered: list[dict], *, trace_id: str, tick_id: str) -> list[dict]:
        predicted_types = {str(x) for x in (self._config.get("predicted_ref_types") or []) if str(x)}
        ev_th_exp = float(self._config.get("expectation_ev_threshold", 0.30))
        ev_th_pr = float(self._config.get("pressure_ev_threshold", 0.30))
        reward_keys = [str(x) for x in (self._config.get("reward_keywords") or []) if str(x)]
        punish_keys = [str(x) for x in (self._config.get("punish_keywords") or []) if str(x)]

        out: list[dict] = []
        for item in ordered[:24]:
            if predicted_types and str(item.get("ref_object_type", "")) not in predicted_types:
                continue
            ev = float(item.get("ev", 0.0) or 0.0)
            if ev <= 0.0:
                continue

            # Reward / punish markers can be encoded in multiple places:
            # - display text of the object (e.g. "奖励信号:轻度正向")
            # - attribute displays (packet attributes or runtime bound attributes)
            #   例如：attrs=[奖励信号:存在]、runtime_attrs=[punish]
            # This keeps the MVP usable even before "reward/punish as explicit SA" is fully implemented.
            # 奖励/惩罚的判断尽量“不依赖唯一字段”，以便在原型阶段就能工作。
            display = str(item.get("display", "") or "")
            detail = str(item.get("display_detail", "") or "")
            attr_text = " ".join(str(x) for x in (item.get("attribute_displays") or []) if str(x))
            bound_attr_text = " ".join(str(x) for x in (item.get("bound_attribute_displays") or []) if str(x))
            haystack = " ".join([display, detail, attr_text, bound_attr_text]).lower()
            is_reward = any(str(k).lower() in haystack for k in reward_keys)
            is_punish = any(str(k).lower() in haystack for k in punish_keys)
            if is_reward and ev >= ev_th_exp:
                out.append(
                    self._make_object_signal(
                        kind="expectation",
                        strength=self._clamp01(ev),
                        item=item,
                        trace_id=trace_id,
                        tick_id=tick_id,
                        reasons=["reward_marker_hit", f"ev>={ev_th_exp}"],
                        evidence={
                            "ev": round(ev, 8),
                            "delta_ev": round(float(item.get("delta_ev", 0.0) or 0.0), 8),
                            "marker_sources": {
                                "display": bool(display),
                                "attributes": bool(attr_text),
                                "bound_attributes": bool(bound_attr_text),
                            },
                        },
                    )
                )
            if is_punish and ev >= ev_th_pr:
                out.append(
                    self._make_object_signal(
                        kind="pressure",
                        strength=self._clamp01(ev),
                        item=item,
                        trace_id=trace_id,
                        tick_id=tick_id,
                        reasons=["punish_marker_hit", f"ev>={ev_th_pr}"],
                        evidence={
                            "ev": round(ev, 8),
                            "delta_ev": round(float(item.get("delta_ev", 0.0) or 0.0), 8),
                            "marker_sources": {
                                "display": bool(display),
                                "attributes": bool(attr_text),
                                "bound_attributes": bool(bound_attr_text),
                            },
                        },
                    )
                )
        return out

    # ================================================================== #
    # Global signals + write-back (implemented in later section)          #
    # ================================================================== #

    def _compute_global_signals(self, attention_report: dict, snapshot_items: list[dict], *, trace_id: str, tick_id: str) -> list[dict]:
        now_ms = int(time.time() * 1000)
        out: list[dict] = []

        complexity, entropy = self._compute_complexity(attention_report)
        if complexity > 0.0:
            out.append(
                self._make_global_signal(
                    kind="complexity",
                    strength=complexity,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    reasons=["cam_size+entropy"],
                    evidence={
                        "cam_size": int(attention_report.get("memory_item_count", attention_report.get("top_item_count", 0)) or 0),
                        "entropy": round(entropy, 8),
                    },
                    created_at=now_ms,
                )
            )

        repetition = self._compute_repetition(snapshot_items)
        if repetition > 0.0:
            out.append(
                self._make_global_signal(
                    kind="repetition",
                    strength=repetition,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    reasons=["fatigue_high"],
                    evidence={"repetition_strength": round(repetition, 8)},
                    created_at=now_ms,
                )
            )

        grasp = self._compute_grasp(attention_report)
        if grasp > 0.0:
            out.append(
                self._make_global_signal(
                    kind="grasp",
                    strength=grasp,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    reasons=["alignment_high"],
                    evidence={"grasp_strength": round(grasp, 8)},
                    created_at=now_ms,
                )
            )

        return out

    def _write_signals_to_pool(self, *, pool: Any, cfs_signals: list[dict], trace_id: str, tick_id: str) -> dict:
        runtime_nodes: list[dict] = []
        attribute_bindings: list[dict] = []
        bind_threshold = float(self._config.get("attribute_bind_strength_threshold", 0.35))

        for sig in cfs_signals:
            signal_id = str(sig.get("signal_id", ""))
            if not signal_id:
                continue
            strength = float(sig.get("strength", 0.0) or 0.0)
            if strength <= 0.0:
                continue

            runtime_nodes.append(self._upsert_cfs_runtime_node(pool=pool, signal=sig, trace_id=trace_id, tick_id=tick_id))

            if sig.get("scope") == "object" and self._config.get("bind_presence_attribute_to_target", True) and strength >= bind_threshold:
                target_item_id = str(sig.get("target", {}).get("target_item_id", "") or "")
                if not target_item_id:
                    continue
                attr = self._build_presence_attribute_sa(sig, trace_id=trace_id, tick_id=tick_id)
                try:
                    result = pool.bind_attribute_node_to_object(
                        target_item_id=target_item_id,
                        attribute_sa=attr,
                        trace_id=f"{trace_id}_cfs_bind",
                        tick_id=tick_id,
                        source_module=__module_name__,
                        reason=f"cfs_{sig.get('kind', '')}_presence",
                    )
                    attribute_bindings.append(
                        {
                            "target_item_id": target_item_id,
                            "attribute_sa_id": attr.get("id", ""),
                            "kind": sig.get("kind", ""),
                            "success": bool(result.get("success", False)),
                            "code": result.get("code", ""),
                        }
                    )
                except Exception:
                    attribute_bindings.append(
                        {
                            "target_item_id": target_item_id,
                            "attribute_sa_id": attr.get("id", ""),
                            "kind": sig.get("kind", ""),
                            "success": False,
                            "code": "BIND_EXCEPTION",
                        }
                    )

                # 奖励/惩罚属性绑定（对齐理论 3.8.2 的“预测结构包含奖惩信号”）
                # 注意：这是运行态绑定（不额外创建 state_item），用于让后续 tick 能产生期待/压力。
                if self._config.get("bind_reward_punish_attribute_to_target", True):
                    kind = str(sig.get("kind", "") or "")
                    reward_kinds = {str(x) for x in (self._config.get("reward_bind_kinds") or []) if str(x)}
                    punish_kinds = {str(x) for x in (self._config.get("punish_bind_kinds") or []) if str(x)}
                    if kind in reward_kinds or kind in punish_kinds:
                        attr_name = str(self._config.get("reward_attribute_name" if kind in reward_kinds else "punish_attribute_name", "") or "").strip()
                        if attr_name:
                            attr2 = self._build_named_marker_attribute_sa(
                                attribute_name=attr_name,
                                attribute_value=self._clamp01(float(strength)),
                                signal=sig,
                                trace_id=trace_id,
                                tick_id=tick_id,
                            )
                            try:
                                result2 = pool.bind_attribute_node_to_object(
                                    target_item_id=target_item_id,
                                    attribute_sa=attr2,
                                    trace_id=f"{trace_id}_cfs_bind",
                                    tick_id=tick_id,
                                    source_module=__module_name__,
                                    reason=f"cfs_{kind}_marker:{attr_name}",
                                )
                                attribute_bindings.append(
                                    {
                                        "target_item_id": target_item_id,
                                        "attribute_sa_id": attr2.get("id", ""),
                                        "kind": f"{kind}->{attr_name}",
                                        "success": bool(result2.get("success", False)),
                                        "code": result2.get("code", ""),
                                    }
                                )
                            except Exception:
                                attribute_bindings.append(
                                    {
                                        "target_item_id": target_item_id,
                                        "attribute_sa_id": attr2.get("id", ""),
                                        "kind": f"{kind}->{attr_name}",
                                        "success": False,
                                        "code": "BIND_EXCEPTION",
                                    }
                                )

        return {"runtime_nodes": runtime_nodes, "attribute_bindings": attribute_bindings}

    def _upsert_cfs_runtime_node(self, *, pool: Any, signal: dict, trace_id: str, tick_id: str) -> dict:
        """
        确保 cfs_signal 节点存在，并把强度写入能量（默认 EV）。

        注意：StatePool 的 insert_runtime_node(allow_merge=True) 合并时会“叠加能量”，
        因此已存在节点需要用 apply_energy_update 做“设值”（delta=target-current），避免无限累积。
        """
        signal_id = str(signal.get("signal_id", ""))
        kind = str(signal.get("kind", "cfs"))
        desired = self._clamp01(float(signal.get("strength", 0.0) or 0.0))

        existing = None
        try:
            existing = pool._store.get_by_ref(signal_id) if hasattr(pool, "_store") else None
        except Exception:
            existing = None

        if existing is None:
            obj = self._build_cfs_runtime_object(signal, trace_id=trace_id, tick_id=tick_id)
            insert = pool.insert_runtime_node(
                runtime_object=obj,
                trace_id=f"{trace_id}_cfs_insert",
                tick_id=tick_id,
                allow_merge=True,
                source_module=__module_name__,
                reason="cfs_signal_insert",
            )
            return {"signal_id": signal_id, "kind": kind, "operation": "insert", "success": bool(insert.get("success", False)), "code": insert.get("code", "")}

        before_er = float(existing.get("energy", {}).get("er", 0.0) or 0.0)
        before_ev = float(existing.get("energy", {}).get("ev", 0.0) or 0.0)
        if self._config.get("write_strength_as_ev", True):
            target_er, target_ev = 0.0, desired
        else:
            target_er, target_ev = desired, 0.0

        update = pool.apply_energy_update(
            target_item_id=existing.get("id", ""),
            delta_er=round(target_er - before_er, 8),
            delta_ev=round(target_ev - before_ev, 8),
            trace_id=f"{trace_id}_cfs_update",
            tick_id=tick_id,
            reason=f"cfs_signal_update:{kind}",
            source_module=__module_name__,
        )
        return {"signal_id": signal_id, "kind": kind, "operation": "set", "success": bool(update.get("success", False)), "code": update.get("code", "")}

    def _build_cfs_runtime_object(self, signal: dict, *, trace_id: str, tick_id: str) -> dict:
        now_ms = int(time.time() * 1000)
        kind = str(signal.get("kind", "cfs"))
        signal_id = str(signal.get("signal_id", ""))
        scope = str(signal.get("scope", "global"))
        strength = self._clamp01(float(signal.get("strength", 0.0) or 0.0))
        target = signal.get("target") or {}

        token = signal_id or f"cfs_{kind}_{scope}"
        display = f"认知感受信号（CFS）:{kind}"
        if scope == "object":
            display = f"认知感受信号（CFS）:{kind}@{target.get('target_ref_object_id', '') or target.get('target_item_id', '')}"

        if self._config.get("write_strength_as_ev", True):
            er, ev = 0.0, strength
        else:
            er, ev = strength, 0.0

        return {
            "id": token,
            "object_type": "cfs_signal",
            "sub_type": kind,
            "schema_version": __schema_version__,
            "content": {"raw": token, "normalized": token, "display": display, "value_type": "discrete"},
            "energy": {"er": float(round(er, 8)), "ev": float(round(ev, 8))},
            "source": {"module": __module_name__, "interface": "run_cfs", "origin": "meta_cognitive_signal", "origin_id": tick_id, "parent_ids": []},
            "trace_id": trace_id,
            "tick_id": tick_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "status": "active",
            "tags": ["cfs"],
            "ext": {
                "kind": kind,
                "scope": scope,
                "strength": float(round(strength, 8)),
                "target": dict(target) if isinstance(target, dict) else {},
                "reasons": list(signal.get("reasons", []) or []),
                "evidence": dict(signal.get("evidence", {}) or {}),
            },
            "meta": {"confidence": 0.8, "field_registry_version": __schema_version__, "debug": {}, "ext": {}},
        }

    def _build_presence_attribute_sa(self, signal: dict, *, trace_id: str, tick_id: str) -> dict:
        now_ms = int(time.time() * 1000)
        kind = str(signal.get("kind", "cfs"))
        target = signal.get("target") or {}
        target_ref_id = str(target.get("target_ref_object_id", "") or target.get("target_item_id", "") or "")
        attr_id = f"sa_cfs_attr_{kind}_{target_ref_id or 'global'}"
        raw = f"cfs:{kind}"
        display = f"认知感受属性（CFS）:{kind}"
        return {
            "id": attr_id,
            "object_type": "sa",
            "sub_type": "cfs_attribute_presence",
            "schema_version": __schema_version__,
            "content": {
                "raw": raw,
                "normalized": raw,
                "display": display,
                "value_type": "discrete",
                "attribute_name": f"cfs_{kind}",
                "attribute_value": 1.0,
            },
            "stimulus": {"modality": "meta", "role": "attribute", "is_anchor": False, "group_index": 0, "position_in_group": 0, "global_sequence_index": 0},
            "energy": {
                "er": 0.0,
                "ev": 0.0,
                "ownership_level": "sa",
                "computed_from_children": False,
                "fatigue": 0.0,
                "recency_gain": 1.0,
                "salience_score": 0.0,
                "cognitive_pressure_delta": 0.0,
                "cognitive_pressure_abs": 0.0,
                "last_decay_tick": 0,
                "last_decay_at": now_ms,
            },
            "source": {"module": __module_name__, "interface": "run_cfs", "origin": "cfs_attribute_binding", "origin_id": tick_id, "parent_ids": []},
            "trace_id": trace_id,
            "tick_id": tick_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "status": "active",
            "tags": ["cfs", "attribute"],
            "ext": {"cfs_kind": kind, "target_ref_object_id": target.get("target_ref_object_id", "")},
            "meta": {"confidence": 0.7, "field_registry_version": __schema_version__, "debug": {}, "ext": {}},
        }

    def _build_named_marker_attribute_sa(
        self,
        *,
        attribute_name: str,
        attribute_value: float,
        signal: dict,
        trace_id: str,
        tick_id: str,
    ) -> dict:
        """Build a generic marker attribute SA for runtime binding.

        构造“标记型属性刺激元”用于运行态绑定（不会作为独立对象进入状态池）。

        典型用途：把 reward_signal / punish_signal 绑定到结构对象上，
        让后续 tick 在 EV 上升时产生期待/压力（对齐理论 3.8.2）。
        """
        now_ms = int(time.time() * 1000)
        name = str(attribute_name or "").strip()
        value = float(attribute_value or 0.0)
        kind = str(signal.get("kind", "cfs"))
        target = signal.get("target") or {}
        target_ref_id = str(target.get("target_ref_object_id", "") or target.get("target_item_id", "") or "")

        label_map = {
            "reward_signal": "奖励信号",
            "punish_signal": "惩罚信号",
        }
        label_zh = label_map.get(name, "标记属性")

        # Stable id for deduplication: name + target
        # 稳定 id：同名属性对同一目标重复绑定会被去重（避免 runtime_attrs 爆炸）。
        attr_id = f"sa_marker_attr_{name}_{target_ref_id or 'global'}"
        raw = f"{name}:{round(value, 6)}"
        display = f"{label_zh}（{name}）:{round(value, 3)}"
        return {
            "id": attr_id,
            "object_type": "sa",
            "sub_type": "marker_attribute_presence",
            "schema_version": __schema_version__,
            "content": {
                "raw": raw,
                "normalized": raw,
                "display": display,
                "value_type": "numerical",
                "attribute_name": name,
                "attribute_value": round(value, 8),
            },
            "stimulus": {"modality": "meta", "role": "attribute", "is_anchor": False, "group_index": 0, "position_in_group": 0, "global_sequence_index": 0},
            "energy": {
                "er": 0.0,
                "ev": 0.0,
                "ownership_level": "sa",
                "computed_from_children": False,
                "fatigue": 0.0,
                "recency_gain": 1.0,
                "salience_score": 0.0,
                "cognitive_pressure_delta": 0.0,
                "cognitive_pressure_abs": 0.0,
                "last_decay_tick": 0,
                "last_decay_at": now_ms,
            },
            "source": {"module": __module_name__, "interface": "run_cfs", "origin": "marker_attribute_binding", "origin_id": tick_id, "parent_ids": []},
            "trace_id": trace_id,
            "tick_id": tick_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "status": "active",
            "tags": ["cfs", "attribute", "marker"],
            "ext": {
                "attribute_name": name,
                "attribute_value": round(value, 8),
                "source_cfs_kind": kind,
                "target_ref_object_id": target.get("target_ref_object_id", ""),
            },
            "meta": {"confidence": 0.65, "field_registry_version": __schema_version__, "debug": {}, "ext": {}},
        }

    # ================================================================== #
    # Signal builders + utilities (implemented in later section)          #
    # ================================================================== #

    def _make_object_signal(
        self,
        *,
        kind: str,
        strength: float,
        item: dict,
        trace_id: str,
        tick_id: str,
        reasons: list[str] | None = None,
        evidence: dict | None = None,
        created_at: int | None = None,
    ) -> dict:
        created_at = created_at or int(time.time() * 1000)
        ref_id = str(item.get("ref_object_id", "") or "")
        ref_type = str(item.get("ref_object_type", "") or "")
        item_id = str(item.get("item_id", "") or "")
        display = str(item.get("display", "") or "")
        signal_id = f"cfs_{kind}_{ref_type}_{ref_id}" if ref_id else f"cfs_{kind}_item_{item_id}"
        return {
            "signal_id": signal_id,
            "kind": str(kind),
            "scope": "object",
            "strength": round(self._clamp01(float(strength)), 8),
            "target": {
                "target_item_id": item_id,
                "target_ref_object_id": ref_id,
                "target_ref_object_type": ref_type,
                "target_display": display,
            },
            "reasons": list(reasons or []),
            "evidence": dict(evidence or {}),
            "trace_id": trace_id,
            "tick_id": tick_id,
            "created_at": created_at,
        }

    def _make_global_signal(
        self,
        *,
        kind: str,
        strength: float,
        trace_id: str,
        tick_id: str,
        reasons: list[str] | None = None,
        evidence: dict | None = None,
        created_at: int | None = None,
    ) -> dict:
        created_at = created_at or int(time.time() * 1000)
        return {
            "signal_id": f"cfs_{kind}_global",
            "kind": str(kind),
            "scope": "global",
            "strength": round(self._clamp01(float(strength)), 8),
            "target": {},
            "reasons": list(reasons or []),
            "evidence": dict(evidence or {}),
            "trace_id": trace_id,
            "tick_id": tick_id,
            "created_at": created_at,
        }

    def _compute_grasp(self, attention_report: dict) -> float:
        eps = float(self._config.get("grasp_alignment_eps", 1e-6))
        er = float(attention_report.get("memory_total_er", 0.0) or 0.0)
        ev = float(attention_report.get("memory_total_ev", 0.0) or 0.0)
        total = er + ev
        if total <= eps:
            return 0.0
        return self._clamp01(1.0 - abs(er - ev) / (total + eps))

    def _compute_complexity(self, attention_report: dict) -> tuple[float, float]:
        cam_size = int(attention_report.get("memory_item_count", attention_report.get("top_item_count", 0)) or 0)
        size_max = max(1, int(self._config.get("complexity_size_max", 24)))
        size_score = self._clamp01(cam_size / float(size_max))

        items = list(attention_report.get("top_items", []) or [])
        totals: list[float] = []
        for it in items:
            memory_total = it.get("memory_total")
            if memory_total is None:
                memory_total = float(it.get("memory_er", 0.0) or 0.0) + float(it.get("memory_ev", 0.0) or 0.0)
            totals.append(max(0.0, float(memory_total or 0.0)))
        total_energy = sum(totals)

        entropy = 0.0
        if total_energy > 1e-9 and len(totals) >= 2:
            probs = [x / total_energy for x in totals if x > 1e-12]
            if probs:
                raw = -sum(p * math.log(max(p, 1e-12)) for p in probs)
                entropy = self._clamp01(raw / max(1e-6, math.log(float(len(probs)))))

        attention_report["cam_energy_entropy"] = round(entropy, 8)

        w_e = float(self._config.get("complexity_entropy_weight", 0.45))
        w_s = float(self._config.get("complexity_size_weight", 0.55))
        return self._clamp01(size_score * w_s + entropy * w_e), entropy

    def _compute_repetition(self, snapshot_items: list[dict]) -> float:
        th = float(self._config.get("repetition_fatigue_threshold", 0.60))
        limit = max(1, int(self._config.get("repetition_max_considered_items", 24)))
        items = snapshot_items[:limit]
        if not items:
            return 0.0

        fatigues = [float(it.get("fatigue", 0.0) or 0.0) for it in items]
        high = [f for f in fatigues if f >= th]
        if not high:
            return 0.0

        ratio = len(high) / float(len(items))
        avg = sum(high) / float(len(high))
        return self._clamp01(ratio * avg)

    # ================================================================== #
    # reload / snapshot                                                   #
    # ================================================================== #

    def get_runtime_snapshot(self, *, trace_id: str = "cfs_runtime") -> dict:
        start_time = time.time()
        return self._make_response(
            True,
            "OK",
            "cfs runtime snapshot",
            data={
                "module": __module_name__,
                "version": __version__,
                "schema_version": __schema_version__,
                "config_summary": dict(self._config),
                "stats": {"total_calls": int(self._total_calls), "tick_counter": int(self._tick_counter)},
            },
            trace_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    def reload_config(self, *, trace_id: str, config_path: str | None = None, apply_partial: bool = True) -> dict:
        start_time = time.time()
        path = config_path or self._config_path
        try:
            new_raw = _load_yaml_config(path)
            if not new_raw:
                return self._make_response(False, "CONFIG_ERROR", f"Config empty: {path}", trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))
            applied, rejected = [], []
            for key, val in new_raw.items():
                if key not in _DEFAULT_CONFIG:
                    rejected.append({"key": key, "reason": "unknown key"})
                    continue
                expected = type(_DEFAULT_CONFIG[key])
                if isinstance(val, expected) or (expected is float and isinstance(val, (int, float))):
                    self._config[key] = val
                    applied.append(key)
                else:
                    rejected.append({"key": key, "reason": f"type mismatch expected {expected.__name__}, got {type(val).__name__}"})
            self._logger.update_config(
                log_dir=str(self._config.get("log_dir", "")),
                max_file_bytes=int(self._config.get("log_max_file_bytes", 0) or 0),
            )
            if rejected and not apply_partial:
                return self._make_response(False, "CONFIG_ERROR", "Some items rejected", data={"applied": applied, "rejected": rejected}, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))
            return self._make_response(True, "OK", "hot reload done", data={"applied": applied, "rejected": rejected}, trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))
        except Exception as exc:
            self._logger.error(trace_id=trace_id, tick_id=trace_id, interface="reload_config", code="CONFIG_ERROR", message=str(exc), detail={"traceback": traceback.format_exc()})
            return self._make_response(False, "CONFIG_ERROR", f"Hot reload failed: {exc}", trace_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))

    # ================================================================== #
    # helpers                                                             #
    # ================================================================== #

    def _build_config(self, config_override: dict | None) -> dict:
        cfg = dict(_DEFAULT_CONFIG)
        cfg.update(_load_yaml_config(self._config_path))
        if config_override:
            cfg.update(config_override)
        return cfg

    @staticmethod
    def _clamp01(value: float) -> float:
        v = float(value)
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v

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
            "meta": {"module": __module_name__, "interface": "", "trace_id": trace_id, "elapsed_ms": int(elapsed_ms), "logged": True},
        }
