# -*- coding: utf-8 -*-
"""
AP 原型行动模块（Action / Drive）
=================================

职责：
  - 维护 Action Node / Drive 运行态；
  - 接收来自先天脚本、CFS、记忆激活等来源的触发；
  - 在每个 tick 内完成驱动衰减、触发增益、竞争裁决与执行；
  - 输出新的注意力指令、调制信号与回忆请求。

当前定位：
  - 属于 MVP / 原型阶段实现；
  - 强调“可观察、可审计、可调参”，不追求复杂行动规划。

术语：
  - Action Node：行动节点
  - Drive：行动驱动力
  - StatePool：状态池
  - CFS：Cognitive Feeling Signals，认知感受信号
  - EMgr / NT：情绪管理器 / 神经递质调制
  - MAP：Memory Activation Pool，记忆激活池
"""

from __future__ import annotations

import os
import re
import math
import time
import traceback
import difflib
from typing import Any

from . import __module_name__, __schema_version__, __version__
from ._logger import ModuleLogger


def _load_yaml_config(path: str) -> dict:
    try:
        import yaml  # type: ignore

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else {}
    except ImportError:
        return {}
    except Exception:
        return {}


_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    # ---- Drive / 驱动力 ----
    "drive_decay_ratio": 0.85,
    "drive_max": 3.0,
    "node_idle_prune_ticks": 18,
    "max_action_nodes": 64,
    # ---- Execution limits / 执行预算 ----
    # 理论口径：每个行动器（可粗略映射为 action_kind）都应有每 tick 的执行预算。
    # 同一 tick 内不能无上限执行同类行动，否则容易出现无穷聚焦、无穷回忆等失控现象。
    #
    # 当前工程口径：
    # - 用 action_kind 表示行动器的粗粒度类别，例如 attention_focus / recall；
    # - 同类行动是否互斥，主要由 mutex_key / mutex_keys 决定；
    # - 数量上限主要作为安全刹车，而不是硬编码行为逻辑。
    "max_actions_per_kind_per_tick_default": 1,
    "max_actions_per_kind_per_tick": {},
    "max_total_actions_per_tick": 8,
    # ---- Conflict / 冲突仲裁 ----
    # ---- Conflict / Conflict mutex keys ----
    # Default conflict domains by action_kind.
    "default_mutex_keys_by_action_kind": {
        "attention_focus": ["attention_focus"],
        # 注意力模式：聚焦 / 发散属于同一资源 attention_mode，因此互斥。
        "attention_focus_mode": ["attention_mode"],
        "attention_diverge_mode": ["attention_mode"],
        # 回忆：默认互斥，同一 tick 只允许一个 recall 动作胜出。
        "recall": ["recall"],
        # 停止 / 取消：默认互斥，避免 stop_action 自己被重复刷屏。
        "stop_action": ["stop_action"],
    },
    # ---- Threshold modulation / 阈值调制（对齐理论 4.2.1.4）----
    # 璇存槑锛?    # - base_threshold锛氳鍒?瑙﹀彂婧愮粰鍑虹殑鈥滃厛澶╁熀鍑嗛槇鍊尖€?    # - effective_threshold锛氭湰 tick 瀹為檯鐢ㄤ簬鍒ゅ畾 drive>=threshold 鐨勯槇鍊?    # - effective_threshold = base_threshold * threshold_scale
    #
    # threshold_scale 鐨勬潵婧愶紙鍘熷瀷瀹炵幇锛夛細
    # 1) 鎯呯华閫掕川 NT锛堜緥濡?DA 闄嶄綆闃堝€笺€丆OR 鎻愰珮闃堝€硷級
    # 2) 琛屽姩鐤插姵锛堥噸澶嶆墽琛屼細鎻愰珮闃堝€硷紝闃叉姝诲惊鐜級
    "threshold_scale_by_nt": {
        # key: NT channel code; value: linear coefficient.
        # 绾挎€х郴鏁帮細scale = 1 + 危(nt[ch] * coef)
        "DA": -0.25,
        "ADR": -0.06,
        "OXY": -0.05,
        "SER": +0.06,
        "END": -0.03,
        "COR": +0.30,
        "NOV": -0.08,
        "FOC": -0.10,
    },
    "threshold_scale_by_rwd_pun_enabled": True,
    "threshold_scale_by_rwd_pun_reward_coef": -0.28,
    "threshold_scale_by_rwd_pun_punish_coef": +0.34,
    "threshold_scale_by_rwd_pun_min": 0.60,
    "threshold_scale_by_rwd_pun_max": 1.45,
    "threshold_scale_min": 0.55,
    "threshold_scale_max": 1.75,
    "local_drive_modulation_by_rwd_pun_enabled": True,
    "local_drive_modulation_require_target": True,
    "local_drive_reward_bonus_coef": 0.45,
    "local_drive_punish_penalty_coef": 0.55,
    "local_drive_scale_min": 0.20,
    "local_drive_scale_max": 1.80,
    "local_drive_feedback_ev_min": 0.0,
    "local_drive_feedback_k_pred": 1.0,
    "local_drive_feedback_k_got": 0.5,
    "local_drive_feedback_w_pred": 0.7,
    "local_drive_feedback_w_got": 0.3,
    "local_drive_feedback_drop_zero_signal_enabled": True,
    "local_drive_feedback_min_signal": 1e-9,
    "local_drive_reward_attribute_names": ["reward_signal", "teacher_reward_signal"],
    "local_drive_punish_attribute_names": ["punish_signal", "teacher_punish_signal"],
    "local_drive_teacher_feedback_override_enabled": True,
    "local_drive_teacher_feedback_floor_scale": 1.0,
    "local_drive_teacher_feedback_cross_suppress_scale": 0.35,
    "local_drive_feedback_text_fallback_enabled": True,
    "local_drive_feedback_text_fallback_target_types": ["input"],
    "local_drive_feedback_text_fallback_min_score": 0.55,
    "local_drive_feedback_text_fallback_min_chars": 6,
    "local_drive_feedback_text_fallback_max_candidates": 96,
    "action_fatigue_enabled": True,
    "action_fatigue_decay_ratio": 0.92,
    "action_fatigue_increase_on_execute": 0.35,
    "action_fatigue_threshold_gain": 0.55,  # effective_threshold *= (1 + fatigue*gain)
    # ---- Attention focus directives / 注意力聚焦（带参数）----
    "focus_threshold": 0.30,
    "focus_gain_base": 1.00,
    # ---- Attention focus/diverge mode / 注意力聚焦-发散模式 ----
    "mode_threshold": 0.55,
    "mode_drive_gain": 0.60,
    "focus_mode_complexity_threshold": 0.65,
    "diverge_mode_complexity_threshold": 0.25,
    "mode_focus_top_n_scale": 0.70,
    "mode_diverge_top_n_scale": 1.30,
    # Attention mode changes redistribute a bounded energy resource; they do not
    # create unlimited multiplicative amplification.
    "mode_focus_attention_energy_budget_scale": 1.25,
    "mode_diverge_attention_energy_budget_scale": 0.75,
    "mode_attention_energy_budget_base": 8.0,
    "mode_attention_energy_budget_min": 0.0,
    "mode_attention_energy_budget_max": 24.0,
    "mode_cooldown_ticks": 2,
    # ---- Recall / 回忆行动 ----
    "recall_threshold": 0.40,
    "recall_gain_base": 0.90,
    "recall_trigger_kinds": ["expectation", "pressure"],
    "recall_min_strength": 0.45,
    "recall_focus_boost": 0.65,
    "recall_ttl_ticks": 2,
    # Recall candidate competition (parameterized recall) / 鍥炲繂鍊欓€夌珵浜夛紙甯﹀弬鍥炲繂锛屽亸鐞嗚鍙ｅ緞锛?    # - 鐤插姵锛氱煭鏈熷唴琚€変腑杩囩殑璁板繂浼氳鎯╃綒锛屼績杩涘娆″洖蹇嗗懡涓洿澶氫笉鍚岃蹇?    "recall_memory_fatigue_window_ticks": 4,
    "recall_memory_fatigue_penalty": 0.60,
    # - 鏃堕棿/鏂伴矞搴﹀奖鍝嶏細鏇存帴杩戠洰鏍囨椂闂淬€佷笖璁板繂鏈韩鏇粹€滄柊鈥濈殑鍊欓€夋洿鍗犱紭
    "recall_recency_scale_sec": 30.0,
    # recall -> MAP锛堣蹇嗚祴鑳芥睜锛夌殑璧嬭兘閲忥紙MVP 鏄犲皠锛?    #
    # 璇存槑锛堥噸瑕侊級锛?    # - Drive锛堥┍鍔ㄥ姏锛変笉鏄?ER/EV锛堝弻鑳介噺锛夛紝浜岃€呭崟浣嶄笉鍚屻€?    # - 浣嗕负浜嗚鈥滃洖蹇嗚鍔ㄢ€濊兘鍦ㄥ師鍨嬮樁娈靛舰鎴愰棴鐜紙瀵归綈鐞嗚 4.2.7.2锛氬洖蹇?>璁板繂杩涘叆 MAP->璁板繂鍙嶅摵鍥炲埌鐘舵€佹睜锛夛紝
    #   鎴戜滑闇€瑕佷竴涓€淒rive 娑堣€?-> MAP 鑳介噺璧嬭兘鈥濈殑鏄犲皠銆?    # - 杩欓噷鐢ㄤ竴涓彲閰嶇疆鐨勭嚎鎬ф槧灏勶細delta_ev 鈮?effective_threshold * per_threshold * strength
    #   骞惰缃?min/max锛岄伩鍏嶅洖蹇嗕竴瑙﹀彂灏辨妸 MAP/鐘舵€佹睜鐏岀垎銆?    "recall_map_delta_ev_per_threshold": 0.90,
    "recall_map_delta_ev_min": 0.08,
    "recall_map_delta_ev_max": 0.85,
    "recall_map_mode_tag": "recall_action",
    # ---- Built-in triggers (legacy fallback) / 鍐呯疆瑙﹀彂婧愶紙鏃ч€昏緫鍥為€€锛?---
    # 璇存槑锛?    # - 涓轰簡婊¤冻楠屾敹鍙ｅ緞锛氣€滃厛澶╄鍔ㄨЕ鍙戣鍒欏簲鍙湪 IESM 鍏堝ぉ瑙勫垯閲岃瀵熶笌缂栬緫鈥濓紝
    #   澶嶆潅搴?鍥炲繂杩欑被瑙﹀彂婧愬缓璁敱 IESM 閫氳繃 action_trigger 杈撳嚭锛岃€屼笉鏄鍔ㄦā鍧楀唴閮ㄧ‖缂栫爜銆?    # - 鍥犳榛樿鍏抽棴鍐呯疆瑙﹀彂锛涘闇€蹇€熼獙璇佹垨鍥為€€锛屽彲鎵嬪姩鎵撳紑銆?    "enable_builtin_triggers_complexity": False,
    "enable_builtin_triggers_recall": False,
    # ---- Observability / 可观测性 ----
    # executed_history_keep / 鏈€杩戞墽琛屽巻鍙蹭繚鐣欐潯鏁?    # 浣滅敤锛氬墠绔€滆鍔ㄧ洃鎺р€濋〉闇€瑕佺湅鍒版渶杩戞墽琛岃繃鍝簺琛屽姩銆佹潵婧愭槸鍏堝ぉ瑙﹀彂杩樻槸鍐呴┍瑙﹀彂銆?    # 璇存槑锛氫粎鐢ㄤ簬瑙傛祴涓庤皟璇曪紱涓嶄細褰卞搷琛屽姩閫昏緫銆?    "executed_history_keep": 200,
    # ---- 鏃ュ織 ----
    "log_dir": "",
    "log_max_file_bytes": 5 * 1024 * 1024,
    "stdout_fallback_when_log_fail": True,
}


class ActionManager:
    """Action manager for Drive-based action execution in the current prototype."""

    def __init__(self, config_path: str = "", config_override: dict | None = None):
        self._config_path = config_path or os.path.join(os.path.dirname(__file__), "config", "action_config.yaml")
        self._config = self._build_config(config_override)
        self._logger = ModuleLogger(
            log_dir=str(self._config.get("log_dir", "")),
            max_file_bytes=int(self._config.get("log_max_file_bytes", 0) or 0),
            enable_stdout_fallback=bool(self._config.get("stdout_fallback_when_log_fail", True)),
        )

        self._tick_counter = 0
        # action_id -> node dict
        self._nodes: dict[str, dict[str, Any]] = {}
        # Built-in executor registry for observability and audit.
        self._executor_registry: list[dict[str, Any]] = self._build_executor_registry()
        # Recent executed actions ring buffer for observatory display.
        self._executed_history: list[dict[str, Any]] = []
        # Pending async completions used to simulate delayed action results.
        # This is important for expectation-contract experiments where an
        # action may be triggered now but only complete in a later tick.
        # Each entry has the form:
        #     {
        #       "action_id": "...",
        #       "action_kind": "...",
        #       "due_tick_number": 123,
        #       "completion_record": { ... executed_actions row ... },
        #     }
        # This queue is runtime-only and is not persisted.
        self._pending_async_completions: list[dict[str, Any]] = []
        # Recall memory fatigue (short-term).
        # - key: memory_id
        # - value: last picked tick_index (from run_action_cycle input), used for diversification
        self._recall_memory_last_picked_tick: dict[str, int] = {}

    def _build_executor_registry(self) -> list[dict[str, Any]]:
        """Build the built-in executor registry used by the observatory and IESM."""
        return [
            {
                "action_kind": "attention_focus",
                "title_zh": "注意力聚焦（内在行动器，带参）",
                "desc_zh": "输出 focus_directive，并在下一 tick 影响注意力筛选顺序；该行动不会直接修改状态池能量。",
                "params_schema": {
                    "focus_directive": {
                        "directive_type": "attention_focus",
                        "target_ref_object_id": "st_* 等",
                        "target_ref_object_type": "st/sa/cfs_signal 等",
                        "strength": "0~1",
                        "focus_boost": ">=0",
                        "ttl_ticks": ">=1",
                    }
                },
                "sources_zh": ["先天规则 IESM focus_directives", "先天规则 IESM action_trigger(kind=attention_focus)"],
            },
            {
                "action_kind": "attention_focus_mode",
                "title_zh": "注意力模式切换：聚焦模式（不带参）",
                "desc_zh": "输出 modulation_out.attention.top_n（更聚焦：更少对象进入 CAM）。",
                "params_schema": {"complexity": "0~1"},
                "sources_zh": ["认知感受 CFS: complexity（繁）", "先天规则 IESM action_trigger"],
            },
            {
                "action_kind": "attention_diverge_mode",
                "title_zh": "注意力模式切换：发散模式（不带参）",
                "desc_zh": "输出 modulation_out.attention.top_n（更发散：更多对象进入 CAM）。",
                "params_schema": {"complexity": "0~1"},
                "sources_zh": ["认知感受 CFS: complexity（简）", "先天规则 IESM action_trigger"],
            },
            {
                "action_kind": "recall",
                "title_zh": "回忆行动（内在行动器）",
                "desc_zh": "从记忆赋能池（MAP）选择一个候选，生成聚焦指令，引导下一 tick 的注意力回到相关记忆结构。",
                "params_schema": {
                    "trigger_kind": "expectation/pressure 等",
                    "trigger_strength": "0~1",
                    "trigger_target": "可选：目标对象信息",
                },
                "sources_zh": ["认知感受 CFS: expectation/pressure", "先天规则 IESM action_trigger(kind=recall)"],
            },
            {
                "action_kind": "llm_think_wake",
                "title_zh": "主动触发大模型思考",
                "desc_zh": "用于 PA 后台主观能动性：让 AP 内部学习何时应该主动唤醒大模型继续生成 thought。",
                "params_schema": {
                    "reason": "触发原因",
                    "role": "judge | wake_candidate | feedback",
                    "background_packet_hint": "短摘要",
                },
                "sources_zh": ["PA 后台主观能动性桥接", "教师门控反馈"],
            },
            {
                "action_kind": "active_reply",
                "title_zh": "主动回复行动",
                "desc_zh": "用于 PA/QQ 群聊全量 AP 门控：普通群消息先进入 AP，只有该行动节点竞争成功后才进入 LLM 是否参与回复的教师门控。",
                "params_schema": {
                    "reason": "触发原因",
                    "role": "group_gate | reply_candidate | reply_committed | feedback",
                    "conversation_id": "QQ 私聊/群聊对象 id",
                    "reply_target": "可选：目标私聊/群聊对象",
                    "background_packet_hint": "短摘要",
                },
                "sources_zh": ["PA 群聊全量 AP 门控", "LLM 回复回灌", "教师门控反馈"],
            },
            {
                "action_kind": "weather_stub",
                "title_zh": "工具行动：天气查询（Stub 占位实现）",
                "desc_zh": (
                    "用于数据集与元学习实验的占位行动器：不真的查询天气，只模拟“被先天规则触发 -> 消耗 drive -> 下一 tick 完成并产出可审计执行记录”。"
                    "该行动器的目标是验证 if 条件训练样本（成功 / 失败）与教师奖励闭环，而不是提供真实工具能力。"
                ),
                "params_schema": {
                    "disable_threshold_modulation": "true/false（是否禁用阈值调制，便于实验稳定复现）",
                    "explicit_input_drive_scale": ">=1（明确外源输入目标时，对 drive 增益做额外放大）",
                    "async_delay_ticks": ">=1（异步完成延迟的 tick 数，默认 1）",
                    "feedback_text": "可选：完成时的系统反馈文本（仅用于审计展示）",
                },
                "sources_zh": ["先天规则 IESM action_trigger(kind=weather_stub)"],
            },
        ]

    def close(self) -> None:
        try:
            self._logger.close()
        except Exception:
            pass

    def clear_runtime_state(self, *, trace_id: str = "", reason: str = "runtime_reset") -> dict[str, Any]:
        start_time = time.time()
        result = {
            "cleared_node_count": len(self._nodes),
            "cleared_executed_history_count": len(self._executed_history),
            "cleared_pending_async_count": len(self._pending_async_completions),
            "cleared_recall_memory_fatigue_count": len(self._recall_memory_last_picked_tick),
            "tick_counter_before": int(self._tick_counter),
        }
        self._tick_counter = 0
        self._nodes.clear()
        self._executed_history.clear()
        self._pending_async_completions.clear()
        self._recall_memory_last_picked_tick.clear()
        return self._make_response(
            True,
            "OK",
            f"行动模块运行态已清空 / Action runtime cleared ({reason})",
            data=result,
            trace_id=trace_id,
            tick_id="",
            elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    # Main interface                                                      #
    # ================================================================== #

    def run_action_cycle(
        self,
        *,
        trace_id: str,
        tick_id: str,
        tick_index: int,
        cfs_signals: list[dict] | None = None,
        emotion_state: dict | None = None,
        innate_focus_directives: list[dict] | None = None,
        innate_action_triggers: list[dict] | None = None,
        memory_activation_snapshot: dict | None = None,
        local_reward_punish_map: dict | None = None,
    ) -> dict:
        start_time = time.time()

        cfs_signals = list(cfs_signals or [])
        emotion_state = emotion_state or {}
        innate_focus_directives = list(innate_focus_directives or [])
        innate_action_triggers = list(innate_action_triggers or [])
        memory_activation_snapshot = memory_activation_snapshot or {}

        tick_number = int(tick_index)
        current_tick_number = tick_number

        if not self._config.get("enabled", True):
            return self._make_response(
                True,
                "OK_DISABLED",
                "琛屽姩妯″潡宸茬鐢?/ Action module disabled",
                data={
                    "executed_actions": [],
                    "focus_directives_out": [],
                    "modulation_out": {},
                    "nodes": [],
                    "triggers": [],
                },
                trace_id=trace_id,
                tick_id=tick_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        # ---- Step 1: build triggers / 鏋勯€犺Е鍙戞簮 ----
        triggers: list[dict[str, Any]] = []
        triggers.extend(self._triggers_from_focus_directives(innate_focus_directives))
        triggers.extend(self._triggers_from_action_triggers(innate_action_triggers))
        # NOTE:
        # Built-in complexity/recall triggers are legacy fallback paths. Prefer IESM action_trigger outputs when available.
        if bool(self._config.get("enable_builtin_triggers_complexity", False)):
            triggers.extend(self._triggers_from_complexity(cfs_signals))
        if bool(self._config.get("enable_builtin_triggers_recall", False)):
            triggers.extend(self._triggers_from_recall(cfs_signals, memory_activation_snapshot))

        # ---- Step 2: decay drives / 椹卞姩鍔涜“鍑?----
        decay = float(self._config.get("drive_decay_ratio", 0.85))
        drive_max = float(self._config.get("drive_max", 3.0))
        for node in self._nodes.values():
            node["drive"] = max(0.0, min(drive_max, float(node.get("drive", 0.0)) * decay))
            # Reset per-tick trigger summary.
            node["tick_gain_total"] = 0.0
            node["tick_gain_raw_total"] = 0.0
            node["tick_gain_by_source_kind"] = {}
            node["tick_sources"] = []
            node["tick_local_gain_base_total"] = 0.0
            node["tick_local_gain_applied_total"] = 0.0
            node["tick_local_reward_bonus_total"] = 0.0
            node["tick_local_punish_penalty_total"] = 0.0
            node["tick_local_modulated_count"] = 0
            node["tick_local_lookup_hit_count"] = 0
            node["tick_local_lookup_miss_count"] = 0
            node["tick_local_lookup_skipped_count"] = 0
            node["tick_local_target_missing_count"] = 0
            node["tick_local_disabled_count"] = 0
            node["tick_consumed_drive_total"] = 0.0

            # Local fatigue decay (if enabled) / 行动疲劳衰减
            if bool(self._config.get("action_fatigue_enabled", True)):
                fr = float(self._config.get("action_fatigue_decay_ratio", 0.92))
                node["fatigue"] = max(0.0, min(1.0, float(node.get("fatigue", 0.0) or 0.0) * fr))

        # Free capacity before applying new triggers. Idle nodes should not be
        # allowed to crowd out fresh IESM/tool action triggers.
        self._prune_idle_nodes(tick_number=current_tick_number)

        # ---- Step 3: apply triggers / 搴旂敤瑙﹀彂澧炵泭锛堥┍鍔ㄥ姏澧炲姞锛?----
        for trig in triggers:
            self._apply_trigger(
                trig,
                tick_number=current_tick_number,
                local_reward_punish_map=local_reward_punish_map or {},
            )

        # ---- Step 4: prune nodes / 娣樻卑闀挎湡闂茬疆鑺傜偣 ----
        self._prune_idle_nodes(tick_number=current_tick_number)

        # ---- Step 4.5: async completions / ?????? ----
        # ????????? drive ???????????????? tick ????
        # ?? expectation-contract ??? stub ??????????????????
        async_completed: list[dict[str, Any]] = []
        if self._pending_async_completions:
            kept_pending: list[dict[str, Any]] = []
            for entry in list(self._pending_async_completions):
                if not isinstance(entry, dict):
                    continue
                try:
                    due_tick = int(entry.get("due_tick_number", -1) or -1)
                except Exception:
                    due_tick = -1
                if due_tick >= 0 and current_tick_number >= due_tick:
                    rec = entry.get("completion_record")
                    if isinstance(rec, dict):
                        async_completed.append(dict(rec))
                    action_id = str(entry.get("action_id", "") or "").strip()
                    if action_id and action_id in self._nodes and isinstance(self._nodes.get(action_id), dict):
                        # Clear the pending gate so the node can be scheduled again after completion.
                        self._nodes[action_id].pop("pending_async_until_tick", None)
                else:
                    kept_pending.append(entry)
            self._pending_async_completions = kept_pending

        # ---- Step 5: competition + execution / 绔炰簤涓庢墽琛?----
        executed: list[dict[str, Any]] = list(async_completed)
        focus_out: list[dict[str, Any]] = []
        modulation_out: dict[str, Any] = {}
        # recall_requests_out: structured recall requests emitted by recall actions.
        # The upper observatory layer is responsible for recall lookup -> MAP activation -> memory feedback side effects.
        recall_requests_out: list[dict[str, Any]] = []

        # Compute effective thresholds for all nodes once per tick.
        # This threshold is used for ordering and execution gating in the current tick.
        for node in self._nodes.values():
            eff = self._compute_effective_threshold(node=node, emotion_state=emotion_state)
            node["base_threshold"] = float(eff.get("base_threshold", node.get("threshold", 1.0) or 1.0))
            node["threshold_scale"] = float(eff.get("threshold_scale", 1.0))
            node["effective_threshold"] = float(eff.get("effective_threshold", node.get("threshold", 1.0) or 1.0))
            node["threshold_components"] = eff.get("components", {})

        # Candidate selection (budget + conflict arbitration) / 鍊欓€夐€夋嫨锛堥绠?+ 鍐茬獊浠茶锛?        #
        # 瀵归綈鐞嗚 + 浣犵殑楠屾敹鍙ｅ緞锛?        # 1) 琛屽姩鍣ㄩ绠楋紙Budget锛夛細鍚屼竴琛屽姩鍣紙绮楃矑搴︾敤 action_kind 琛ㄧず锛夊湪鍚屼竴涓?tick 鍐呯殑鎵ц鏁伴噺搴旀湁闄愶紝
        #    榛樿姣?tick 鍙墽琛?1 涓紙鍙厤缃笂璋冿級銆?        # 2) 鍐茬獊浠茶锛圕onflict锛夛細鍚屼竴琛屽姩鍣ㄥ唴鈥滀笉鍐茬獊鈥濈殑琛屽姩鍙互骞惰鎵ц锛涒€滃啿绐佲€濈殑琛屽姩鍚?tick 鍙兘涓€涓儨鍑恒€?        #    - 鍐茬獊鍩熺敤 mutex_key/mutex_keys 琛ㄧず锛堜簰鏂ヨ祫婧?key锛夈€?        #    - 榛樿鐢辫鍔ㄥ櫒娉ㄥ唽琛紙default_mutex_keys_by_action_kind锛夌粰鍑猴紱
        #    - 涔熷厑璁歌Е鍙戞簮/瑙勫垯鍦?params 涓鐩?mutex_key/mutex_keys 浠ョ粏鍒嗗啿绐佸煙銆?        #
        # 绔炰簤鎺掑簭锛堢敤浜庢寫鑳滆€咃級锛?        #   1) 鏈?tick 澧炵泭 tick_gain_total锛堝彲杩戜技鐞嗚В涓衡€滄湰杞祴鑳芥洿寮衡€濓級
        #   2) 椹卞姩鍔?drive锛堣鍔ㄦ剰鍥炬洿寮猴級
        #   3) 瑙勫垯浼樺厛绾?rule_priority锛堝畨鍏?缁堟绫昏鍒欏彲鏇撮珮锛?        #   4) action_id锛堢ǔ瀹氭墦鐮村钩灞€锛?
        def _max_actions_per_kind(kind: str) -> int:
            """Get per-kind execution budget for this tick."""
            default_n = int(self._config.get("max_actions_per_kind_per_tick_default", 1) or 1)
            override = self._config.get("max_actions_per_kind_per_tick", {}) or {}
            if isinstance(override, dict) and str(kind or "") in override:
                try:
                    return max(0, min(64, int(override.get(str(kind or ""), default_n) or 0)))
                except Exception:
                    return max(0, min(64, default_n))
            return max(0, min(64, default_n))

        def _tick_max_rule_priority(node: dict[str, Any]) -> int:
            """Best-effort: read the max rule_priority from current tick trigger sources."""
            best = 0
            for src in (node.get("tick_sources", []) or []):
                if not isinstance(src, dict):
                    continue
                try:
                    best = max(best, int(src.get("rule_priority", src.get("priority", 0)) or 0))
                except Exception:
                    continue
            return int(best)

        def _rank_key(node: dict[str, Any]) -> tuple[float, float, int, str]:
            """Sort key for competition within the same action_kind."""
            energy_score = float(node.get("tick_gain_total", 0.0) or 0.0)
            drive_score = float(node.get("drive", 0.0) or 0.0)
            pri_score = _tick_max_rule_priority(node)
            aid = str(node.get("action_id", "") or "")
            # Descending for first three fields; action_id ascending for stable tie-break.
            return (energy_score, drive_score, pri_score, aid)

        def _node_mutex_keys(node: dict[str, Any]) -> list[str]:
            """Compute mutex keys for a node."""
            kind2 = str(node.get("action_kind", "") or "").strip()
            params2 = node.get("params") if isinstance(node.get("params"), dict) else {}

            # 1) Explicit override from params / 浼樺厛浣跨敤瑙勫垯/瑙﹀彂婧愭樉寮忔寚瀹氱殑浜掓枼 key
            raw_keys = None
            for k in ("mutex_keys", "mutex_key", "conflict_keys", "conflict_key"):
                if k in params2:
                    raw_keys = params2.get(k)
                    break
            if raw_keys is None and "mutex_keys" in node:
                raw_keys = node.get("mutex_keys")
            if raw_keys is None and "mutex_key" in node:
                raw_keys = node.get("mutex_key")

            keys: list[str] = []
            if isinstance(raw_keys, str) and raw_keys.strip():
                keys = [raw_keys.strip()]
            elif isinstance(raw_keys, list):
                keys = [str(x).strip() for x in raw_keys if str(x).strip()]

            # 2) Default registration by action_kind.
            if not keys:
                dm = self._config.get("default_mutex_keys_by_action_kind", {}) or {}
                if isinstance(dm, dict) and kind2 in dm:
                    raw = dm.get(kind2) or []
                    if isinstance(raw, str) and raw.strip():
                        keys = [raw.strip()]
                    elif isinstance(raw, list):
                        keys = [str(x).strip() for x in raw if str(x).strip()]

            # 3) Fallback to action_kind itself.
            if not keys and kind2:
                keys = [kind2]

            # Dedupe while keeping order / 鍘婚噸锛堜繚鎸侀『搴忥級
            deduped: list[str] = []
            seen = set()
            for key in keys:
                if not key or key in seen:
                    continue
                seen.add(key)
                deduped.append(key)
            return deduped

        # Build executable candidates.
        candidates: list[dict[str, Any]] = []
        for node in self._nodes.values():
            if not self._should_execute(node, tick_number=tick_number):
                continue
            if not str(node.get("action_kind", "") or "").strip():
                continue
            candidates.append(node)

        # Greedy selection with mutex + per-kind budget / 浜掓枼璧勬簮 + 琛屽姩鍣ㄩ绠楃殑璐┆閫夋嫨
        exec_cap = int(self._config.get("max_total_actions_per_tick", 8) or 8)
        exec_cap = max(0, min(128, exec_cap))
        kind_counts: dict[str, int] = {}
        used_mutex_keys: set[str] = set()
        ranked = sorted(candidates, key=_rank_key, reverse=True)

        selected: list[dict[str, Any]] = []
        for node in ranked:
            if len(selected) >= exec_cap:
                break
            kind2 = str(node.get("action_kind", "") or "").strip()
            limit2 = _max_actions_per_kind(kind2)
            if limit2 <= 0:
                continue
            if int(kind_counts.get(kind2, 0) or 0) >= int(limit2):
                continue

            mutex_keys = _node_mutex_keys(node)
            if mutex_keys and any(k in used_mutex_keys for k in mutex_keys):
                continue

            selected.append(node)
            kind_counts[kind2] = int(kind_counts.get(kind2, 0) or 0) + 1
            for k in mutex_keys:
                used_mutex_keys.add(k)

        for node in selected:
            kind = str(node.get("action_kind", "") or "")
            ok = True
            produced = {"focus_directives": [], "modulation": {}}
            failure_reason = ""
            consume_drive = False
            async_completion_due_tick: int | None = None

            if kind == "attention_focus":
                params = (node.get("params", {}) or {}) if isinstance(node.get("params", {}), dict) else {}
                directive = dict(params.get("focus_directive", {}) or {}) if isinstance(params.get("focus_directive", {}), dict) else {}
                if not directive:
                    # Convenience path: accept lightweight target_* fields and
                    # normalize them into a standard focus_directive structure.
                    target_ref_id = str(params.get("target_ref_object_id", "") or params.get("ref_object_id", "") or "").strip()
                    target_ref_type = str(params.get("target_ref_object_type", "") or params.get("ref_object_type", "") or "").strip()
                    target_item_id = str(params.get("target_item_id", "") or params.get("item_id", "") or "").strip()
                    target_display = str(params.get("target_display", "") or params.get("display", "") or target_ref_id or target_item_id).strip()
                    if target_ref_id or target_item_id:
                        try:
                            strength = self._clamp01(float(params.get("strength", params.get("match_value", 1.0)) or 1.0))
                        except Exception:
                            strength = 1.0
                        try:
                            focus_boost = float(params.get("focus_boost", 0.9) or 0.9)
                        except Exception:
                            focus_boost = 0.9
                        try:
                            ttl_ticks = int(params.get("ttl_ticks", 2) or 2)
                        except Exception:
                            ttl_ticks = 2
                        ttl_ticks = max(1, min(64, ttl_ticks))

                        now_ms = int(time.time() * 1000)
                        directive = {
                            "directive_id": f"focus_action_{node.get('action_id', 'unknown')}_{tick_id}",
                            "directive_type": "attention_focus",
                            "source_kind": str(params.get("source_kind", "action_trigger") or "action_trigger"),
                            "strength": round(float(strength), 6),
                            "focus_boost": round(max(0.0, float(focus_boost)), 6),
                            "ttl_ticks": int(ttl_ticks),
                            "target_ref_object_id": target_ref_id,
                            "target_ref_object_type": target_ref_type,
                            "target_item_id": target_item_id,
                            "target_display": target_display,
                            "created_at": now_ms,
                            "reasons": [
                                "action:attention_focus",
                                f"action_id:{node.get('action_id', '')}",
                                "from:action_trigger_params",
                            ],
                        }

                if directive:
                    produced["focus_directives"].append(directive)
            elif kind in {"attention_focus_mode", "attention_diverge_mode"}:
                params = (node.get("params", {}) or {}) if isinstance(node.get("params", {}), dict) else {}
                base_top_n = int(params.get("top_n", 16) or 16)
                if kind == "attention_focus_mode":
                    scale = float(self._config.get("mode_focus_top_n_scale", 0.70))
                    budget_scale = float(self._config.get("mode_focus_attention_energy_budget_scale", 1.25))
                else:
                    scale = float(self._config.get("mode_diverge_top_n_scale", 1.30))
                    budget_scale = float(self._config.get("mode_diverge_attention_energy_budget_scale", 0.75))
                top_n = int(round(base_top_n * max(0.1, scale)))
                top_n = max(4, min(64, top_n))
                base_budget = float(
                    params.get(
                        "attention_energy_budget",
                        self._config.get("mode_attention_energy_budget_base", 8.0),
                    )
                    or 8.0
                )
                budget_min = float(self._config.get("mode_attention_energy_budget_min", 0.0) or 0.0)
                budget_max = float(self._config.get("mode_attention_energy_budget_max", 24.0) or 24.0)
                if budget_max < budget_min:
                    budget_max = budget_min
                attention_energy_budget = max(budget_min, min(budget_max, base_budget * max(0.0, budget_scale)))
                produced["modulation"] = {
                    "attention": {
                        "top_n": top_n,
                        "attention_energy_budget": round(float(attention_energy_budget), 8),
                        "reason": kind,
                    }
                }
            elif kind == "recall":
                directive = self._build_recall_focus_directive(
                    node=node,
                    tick_id=tick_id,
                    tick_index=int(tick_index),
                    now_ms=int(time.time() * 1000),
                    memory_activation_snapshot=memory_activation_snapshot,
                )
                if directive:
                    produced["focus_directives"].append(directive)
                else:
                    ok = False
                    failure_reason = "no_recall_candidate"
            elif kind == "weather_stub":
                # Stub executor for tool-like action (no real tool call).
                #
                # 鍏抽敭璁捐鐐癸紙瀵归綈浣犵殑瀹為獙鍙ｅ緞锛夛細
                # - 鈥滃紑濮嬫墽琛屸€濆彂鐢熷湪鏈?tick锛氭秷鑰?drive锛屽苟鎶婅鍔ㄦ爣璁颁负 pending锛?                # - 鈥滄墽琛屽畬鎴愶紙success=true锛夆€濆欢杩熷埌鍚庣画 tick锛氱敱 async completion 闃熷垪浜у嚭璁板綍锛?                #   浠ヤ究 expectation_contract锛堟湡鏈涘绾︼級鑳藉湪鈥滃悗缁?tick鈥濊瀵熷埌鎵ц缁撴灉骞剁敓鎴愬鎯╁弽棣?tick銆?                params = (node.get("params", {}) or {}) if isinstance(node.get("params", {}), dict) else {}
                delay = 1
                try:
                    delay = int(params.get("async_delay_ticks", 1) or 1)
                except Exception:
                    delay = 1
                delay = max(1, min(8, int(delay)))
                async_completion_due_tick = int(tick_number + delay)
                node["pending_async_until_tick"] = int(async_completion_due_tick)
                produced["async_completion"] = {"delay_ticks": int(delay), "due_tick_number": int(async_completion_due_tick)}
                ok = False
                failure_reason = "async_pending_completion"
                consume_drive = True
            elif kind == "llm_think_wake":
                params = (node.get("params", {}) or {}) if isinstance(node.get("params", {}), dict) else {}
                produced["system_feedback"] = {
                    "kind": "llm_think_wake",
                    "reason": str(params.get("reason", "") or ""),
                    "role": str(params.get("role", "") or ""),
                    "background_packet_hint": str(params.get("background_packet_hint", "") or ""),
                }
                consume_drive = True
            elif kind == "active_reply":
                params = (node.get("params", {}) or {}) if isinstance(node.get("params", {}), dict) else {}
                produced["system_feedback"] = {
                    "kind": "active_reply",
                    "reason": str(params.get("reason", "") or ""),
                    "role": str(params.get("role", "") or ""),
                    "conversation_id": str(params.get("conversation_id", "") or ""),
                    "target_label": str(params.get("target_label", "") or ""),
                    "background_packet_hint": str(params.get("background_packet_hint", "") or ""),
                    "reply_target": params.get("reply_target", {}) if isinstance(params.get("reply_target", {}), dict) else {},
                }
                consume_drive = True
            else:
                ok = False
                failure_reason = "unknown_action_kind"

            # Always record an attempt for observability, even when execution fails.
            # Always record an attempt for observability, even when execution fails.
            eff_threshold = float(node.get("effective_threshold", node.get("threshold", 0.0) or 0.0) or 0.0)
            drive_before = round(float(node.get("drive", 0.0) or 0.0), 8)
            node["last_attempt_tick"] = tick_number

            if not consume_drive:
                consume_drive = bool(ok)

            consumed_drive = 0.0
            if consume_drive:
                # Consume drive by threshold (not clear).
                # Consume drive by effective threshold (not clear-to-zero).
                consumed_drive = max(0.0, float(eff_threshold))
                node["drive"] = max(0.0, float(node.get("drive", 0.0)) - float(consumed_drive))
                node["last_trigger_tick"] = tick_number
                node["last_consumed_drive"] = round(float(consumed_drive), 8)
                node["tick_consumed_drive_total"] = float(node.get("tick_consumed_drive_total", 0.0) or 0.0) + float(consumed_drive)
                # Fatigue bump on execute to avoid endless loops.
                if bool(self._config.get("action_fatigue_enabled", True)):
                    inc = float(self._config.get("action_fatigue_increase_on_execute", 0.35))
                    node["fatigue"] = max(0.0, min(1.0, float(node.get("fatigue", 0.0) or 0.0) + max(0.0, inc)))

            # Derive origin tags (passive vs active) from current and historical sources.
            source_kinds = [str(s.get("kind", "") or "") for s in (node.get("tick_sources", []) or []) if isinstance(s, dict)]
            passive = any(k.startswith("iesm_") for k in source_kinds)
            active = any((k and not k.startswith("iesm_")) for k in source_kinds)

            rec = {
                "action_id": node.get("action_id", ""),
                "action_kind": kind,
                "attempted": True,
                "success": bool(ok),
                "drive_before": drive_before,
                "drive_after": round(float(node.get("drive", 0.0)), 8),
                "base_threshold": round(float(node.get("base_threshold", node.get("threshold", 0.0) or 0.0)), 8),
                "threshold_scale": round(float(node.get("threshold_scale", 1.0) or 1.0), 8),
                "effective_threshold": round(float(eff_threshold), 8),
                "consumed_drive": round(float(consumed_drive), 8),
                "fatigue": round(float(node.get("fatigue", 0.0) or 0.0), 8),
                "produced": produced,
                "trigger_sources": list(node.get("trigger_sources", []) or [])[:6],
                "tick_gain_total": round(float(node.get("tick_gain_total", 0.0) or 0.0), 8),
                "tick_gain_raw_total": round(float(node.get("tick_gain_raw_total", 0.0) or 0.0), 8),
                "tick_gain_by_source_kind": dict(node.get("tick_gain_by_source_kind", {}) or {}),
                "target_ref_object_id": str(node.get("target_ref_object_id", "") or ""),
                "target_ref_object_type": str(node.get("target_ref_object_type", "") or ""),
                "target_item_id": str(node.get("target_item_id", "") or ""),
                "target_display": str(node.get("target_display", "") or ""),
                "local_drive_modulation": dict(node.get("last_local_drive_modulation", {}) or {}) if isinstance(node.get("last_local_drive_modulation", {}), dict) else {},
                "origin": {
                    "passive_iesm": bool(passive),
                    "active_internal": bool(active),
                },
            }

            # If a recall action executes successfully, emit a structured recall request for the upper layer.
            if ok and kind == "recall":
                req = self._build_recall_request(
                    node=node,
                    tick_id=tick_id,
                    tick_index=int(tick_index),
                    now_ms=int(time.time() * 1000),
                    drive_before=float(drive_before),
                    effective_threshold=float(eff_threshold),
                    memory_activation_snapshot=memory_activation_snapshot,
                )
                rec["recall_request"] = dict(req)
                recall_requests_out.append(dict(req))

            if not ok and failure_reason:
                rec["failure_reason"] = str(failure_reason)
            executed.append(rec)

            # If this action is async, enqueue a completion record for later ticks.
            if async_completion_due_tick is not None:
                feedback_text = ""
                try:
                    feedback_text = str(((node.get("params", {}) or {}) if isinstance(node.get("params", {}), dict) else {}).get("feedback_text", "") or "")
                except Exception:
                    feedback_text = ""
                completion_record = {
                    "action_id": node.get("action_id", ""),
                    "action_kind": kind,
                    "attempted": False,
                    "success": True,
                    "drive_before": drive_before,
                    "drive_after": round(float(node.get("drive", 0.0)), 8),
                    "base_threshold": round(float(node.get("base_threshold", node.get("threshold", 0.0) or 0.0)), 8),
                    "threshold_scale": round(float(node.get("threshold_scale", 1.0) or 1.0), 8),
                    "effective_threshold": round(float(eff_threshold), 8),
                    "consumed_drive": round(float(consumed_drive), 8),
                    "fatigue": round(float(node.get("fatigue", 0.0) or 0.0), 8),
                    "produced": {
                        "system_feedback": {
                            "text": feedback_text.strip() or "绯荤粺鍙嶉锛氬ぉ姘旀煡璇㈣鍔ㄥ凡瀹屾垚锛圫tub锛屽崰浣嶅疄鐜帮級",
                            "kind": "weather_stub",
                        },
                        "async_completion": {
                            "scheduled_tick_number": int(tick_number),
                            "due_tick_number": int(async_completion_due_tick),
                        },
                    },
                    "origin": {"passive_iesm": bool(passive), "active_internal": bool(active)},
                    "async_completion": {
                        "scheduled_tick_number": int(tick_number),
                        "due_tick_number": int(async_completion_due_tick),
                    },
                }
                # Keep pending list bounded.
                if len(self._pending_async_completions) < 64:
                    self._pending_async_completions.append(
                        {
                            "action_id": str(node.get("action_id", "") or ""),
                            "action_kind": str(kind or ""),
                            "due_tick_number": int(async_completion_due_tick),
                            "completion_record": completion_record,
                        }
                    )
            if ok:
                focus_out.extend(produced.get("focus_directives", []) or [])
                modulation_out = self._merge_modulation(modulation_out, produced.get("modulation", {}) or {})

        focus_out = self._dedup_focus_directives(focus_out)

        # Node snapshot for UI: show the strongest current nodes, not only the nodes selected this tick.
        nodes_ranked_for_snapshot = sorted(
            self._nodes.values(),
            key=lambda n: float(n.get("drive", 0.0) or 0.0),
            reverse=True,
        )
        nodes_snapshot = [
            {
                "action_id": node.get("action_id", ""),
                "action_kind": node.get("action_kind", ""),
                "drive": round(float(node.get("drive", 0.0)), 8),
                "base_threshold": round(float(node.get("base_threshold", node.get("threshold", 0.0) or 0.0)), 8),
                "threshold_scale": round(float(node.get("threshold_scale", 1.0) or 1.0), 8),
                "effective_threshold": round(float(node.get("effective_threshold", node.get("threshold", 0.0) or 0.0)), 8),
                "threshold_components": dict(node.get("threshold_components", {}) or {}) if isinstance(node.get("threshold_components", {}), dict) else {},
                "target_ref_object_id": str(node.get("target_ref_object_id", "") or ""),
                "target_ref_object_type": str(node.get("target_ref_object_type", "") or ""),
                "target_item_id": str(node.get("target_item_id", "") or ""),
                "target_display": str(node.get("target_display", "") or ""),
                "params": dict(node.get("params", {}) or {}) if isinstance(node.get("params", {}), dict) else {},
                "trigger_sources": list(node.get("trigger_sources", []) or [])[:8],
                "tick_sources": list(node.get("tick_sources", []) or [])[:8],
                "target_binding_strategy": str(node.get("target_binding_strategy", "") or ""),
                "target_binding_requested_from": str(node.get("target_binding_requested_from", "") or ""),
                "target_binding_applied": bool(node.get("target_binding_applied", False)),
                "target_binding_reason": str(node.get("target_binding_reason", "") or ""),
                "target_binding_match_source": str(node.get("target_binding_match_source", "") or ""),
                "target_binding_match_ref_object_id": str(node.get("target_binding_match_ref_object_id", "") or ""),
                "target_binding_match_ref_object_type": str(node.get("target_binding_match_ref_object_type", "") or ""),
                "target_binding_match_item_id": str(node.get("target_binding_match_item_id", "") or ""),
                "target_binding_match_display": str(node.get("target_binding_match_display", "") or ""),
                "local_drive_modulation": dict(node.get("last_local_drive_modulation", {}) or {}) if isinstance(node.get("last_local_drive_modulation", {}), dict) else {},
                "fatigue": round(float(node.get("fatigue", 0.0) or 0.0), 8),
                "last_consumed_drive": round(float(node.get("last_consumed_drive", 0.0) or 0.0), 8),
                "tick_consumed_drive_total": round(float(node.get("tick_consumed_drive_total", 0.0) or 0.0), 8),
                "cooldown_ticks": int(node.get("cooldown_ticks", 0) or 0),
                "last_trigger_tick": int(node.get("last_trigger_tick", -1) or -1),
                "last_update_tick": int(node.get("last_update_tick", -1) or -1),
                "tick_gain_total": round(float(node.get("tick_gain_total", 0.0) or 0.0), 8),
                "tick_gain_raw_total": round(float(node.get("tick_gain_raw_total", 0.0) or 0.0), 8),
            }
            for node in nodes_ranked_for_snapshot[:24]
        ]
        action_learning_summary = self._build_action_learning_summary(nodes_ranked_for_snapshot)

        self._logger.brief(
            trace_id=trace_id,
            tick_id=tick_id,
            interface="run_action_cycle",
            success=True,
            message="琛屽姩妯″潡宸茶绠?Drive 骞跺皾璇曟墽琛屽姩浣?/ Drive updated and actions attempted",
            input_summary={
                "tick_index": int(tick_index),
                "cfs_signal_count": len(cfs_signals),
                "innate_focus_directive_count": len(innate_focus_directives),
                "innate_action_trigger_count": len(innate_action_triggers),
                "memory_activation_item_count": len(memory_activation_snapshot.get("items", []) or []),
            },
            output_summary={
                "trigger_count": len(triggers),
                "node_count": len(self._nodes),
                "executed_action_count": len(executed),
                "focus_directives_out": len(focus_out),
            },
        )
        self._logger.detail(
            trace_id=trace_id,
            tick_id=tick_id,
            step="action_cycle_detail",
            info={
                "tick_number": tick_number,
                "triggers": triggers,
                "executed": executed,
                "modulation_out": modulation_out,
                "focus_directives_out": focus_out,
                "nodes": nodes_snapshot,
            },
        )

        # Record executed history for the observatory UI (ring buffer).
        self._append_executed_history(tick_id=tick_id, tick_number=tick_number, executed=executed)

        return self._make_response(
            True,
            "OK",
            "琛屽姩妯″潡鎵ц瀹屾垚 / Action cycle finished",
            data={
                "executed_actions": executed,
                "focus_directives_out": focus_out,
                "modulation_out": modulation_out,
                "recall_requests_out": recall_requests_out,
                "nodes": nodes_snapshot,
                "triggers": triggers[:64],
                "executors_registry": list(self._executor_registry),
                "action_learning_summary": action_learning_summary,
                "threshold_modulation": {
                    "threshold_scale_by_nt": dict(self._config.get("threshold_scale_by_nt", {}) or {}),
                    "threshold_scale_by_rwd_pun_enabled": bool(self._config.get("threshold_scale_by_rwd_pun_enabled", True)),
                    "threshold_scale_by_rwd_pun_reward_coef": float(self._config.get("threshold_scale_by_rwd_pun_reward_coef", -0.28) or -0.28),
                    "threshold_scale_by_rwd_pun_punish_coef": float(self._config.get("threshold_scale_by_rwd_pun_punish_coef", 0.34) or 0.34),
                    "threshold_scale_by_rwd_pun_min": float(self._config.get("threshold_scale_by_rwd_pun_min", 0.60) or 0.60),
                    "threshold_scale_by_rwd_pun_max": float(self._config.get("threshold_scale_by_rwd_pun_max", 1.45) or 1.45),
                    "threshold_scale_min": float(self._config.get("threshold_scale_min", 0.55) or 0.55),
                    "threshold_scale_max": float(self._config.get("threshold_scale_max", 1.75) or 1.75),
                    "action_fatigue_enabled": bool(self._config.get("action_fatigue_enabled", True)),
                    "rwd_pun_snapshot": dict(emotion_state.get("rwd_pun_snapshot", {}) or {}) if isinstance(emotion_state.get("rwd_pun_snapshot", {}), dict) else {},
                    "local_drive_modulation_by_rwd_pun_enabled": bool(self._config.get("local_drive_modulation_by_rwd_pun_enabled", True)),
                    "local_drive_reward_bonus_coef": float(self._config.get("local_drive_reward_bonus_coef", 0.45) or 0.45),
                    "local_drive_punish_penalty_coef": float(self._config.get("local_drive_punish_penalty_coef", 0.55) or 0.55),
                    "local_drive_scale_min": float(self._config.get("local_drive_scale_min", 0.20) or 0.20),
                    "local_drive_scale_max": float(self._config.get("local_drive_scale_max", 1.80) or 1.80),
                },
                "meta": {
                    "version": __version__,
                    "schema_version": __schema_version__,
                    "tick_number": tick_number,
                },
            },
            trace_id=trace_id,
            tick_id=tick_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    def _append_executed_history(self, *, tick_id: str, tick_number: int, executed: list[dict[str, Any]]) -> None:
        """Append executed actions into a bounded history buffer.

        Used only for observation and debugging. This history must not feed back into
        action selection logic.
        """
        try:
            keep = int(self._config.get("executed_history_keep", 200) or 200)
        except Exception:
            keep = 200
        keep = max(0, min(5000, keep))
        if keep <= 0:
            return
        if not executed:
            return

        now_ms = int(time.time() * 1000)
        for row in executed:
            if not isinstance(row, dict):
                continue
            rec = dict(row)
            rec["tick_id"] = str(tick_id or "")
            rec["tick_number"] = int(tick_number)
            rec["recorded_at_ms"] = int(now_ms)
            self._executed_history.append(rec)

        if len(self._executed_history) > keep:
            self._executed_history = self._executed_history[-keep:]

    # ================================================================== #
    # Triggers / 瑙﹀彂婧?                                                  #
    # ================================================================== #

    def _triggers_from_focus_directives(self, directives: list[dict]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        gain_base = float(self._config.get("focus_gain_base", 0.70))
        threshold = float(self._config.get("focus_threshold", 0.40))
        for d in directives:
            if not isinstance(d, dict):
                continue
            strength = self._clamp01(float(d.get("strength", 1.0) or 1.0))
            gain = max(0.0, gain_base) * strength
            action_id = self._focus_action_id(d)
            if not action_id:
                continue
            out.append(
                {
                    "action_id": action_id,
                    "action_kind": "attention_focus",
                    "gain": round(gain, 8),
                    "threshold": threshold,
                    "cooldown_ticks": 0,
                    "params": {"focus_directive": dict(d)},
                    "source": {"kind": "iesm_focus_directive", "strength": strength},
                }
            )
        return out

    def _triggers_from_action_triggers(self, items: list[dict]) -> list[dict[str, Any]]:
        """Convert IESM action_triggers into internal trigger records.

        Contract:
        - IESM action_trigger is a structured trigger, not direct code execution.
        - This method maps it into the ActionManager trigger schema.
        - Unknown or incomplete triggers are ignored for safety and auditability.
        """
        out: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            action_id = str(item.get("action_id", "") or item.get("id", "") or "").strip()
            if not action_id:
                continue

            action_kind = str(item.get("action_kind", "") or item.get("kind", "") or "custom").strip() or "custom"
            try:
                gain = float(item.get("gain", item.get("drive_gain", 0.0)) or 0.0)
            except Exception:
                gain = 0.0
            try:
                threshold = float(item.get("threshold", 1.0) or 1.0)
            except Exception:
                threshold = 1.0
            try:
                cooldown = int(item.get("cooldown_ticks", 0) or 0)
            except Exception:
                cooldown = 0

            params = item.get("params") or {}
            if not isinstance(params, dict):
                params = {"raw": params}
            else:
                params = dict(params)
            for key in [
                "target_ref_object_id",
                "target_ref_object_type",
                "target_item_id",
                "target_display",
                "trigger_target_ref",
                "trigger_target_display",
                "ref_object_id",
                "ref_object_type",
                "item_id",
            ]:
                if str(params.get(key, "") or "").strip():
                    continue
                value = item.get(key, "")
                if isinstance(value, str):
                    value = value.strip()
                if value not in (None, ""):
                    params[key] = value
            # Allow conflict keys to be declared at the top level for readability.
            # 鍏佽鎶婁簰鏂?key锛坢utex_key/mutex_keys锛夊啓鍦?action_trigger 椤跺眰锛堟洿鐩磋锛夛紝
            # 杩欓噷缁熶竴鎶樺彔鍒?params 涓紝渚?ActionManager 鐨勫啿绐佷徊瑁佽鍙栥€?            if "mutex_key" not in params and isinstance(item.get("mutex_key"), str) and str(item.get("mutex_key") or "").strip():
                params["mutex_key"] = str(item.get("mutex_key") or "").strip()
            if "mutex_keys" not in params and isinstance(item.get("mutex_keys"), list):
                params["mutex_keys"] = [str(x).strip() for x in (item.get("mutex_keys") or []) if str(x).strip()]
            source = {
                "kind": "iesm_action_trigger",
                "rule_id": str(item.get("rule_id", "") or ""),
                "rule_title": str(item.get("rule_title", "") or ""),
                "rule_phase": str(item.get("rule_phase", "") or ""),
                "rule_priority": int(item.get("rule_priority", item.get("rule_pri", item.get("priority", 0))) or 0),
            }
            for key in [
                "target_binding_strategy",
                "target_binding_requested_from",
                "target_binding_reason",
                "target_binding_match_source",
                "target_binding_match_ref_object_id",
                "target_binding_match_ref_object_type",
                "target_binding_match_item_id",
                "target_binding_match_display",
                "target_ref_object_id",
                "target_ref_object_type",
                "target_item_id",
                "target_display",
                "trigger_target_ref",
                "trigger_target_display",
            ]:
                value = item.get(key, None)
                if isinstance(value, str):
                    value = value.strip()
                if value not in (None, ""):
                    source[key] = value
            if "target_binding_applied" in item:
                source["target_binding_applied"] = bool(item.get("target_binding_applied", False))

            out.append(
                {
                    "action_id": action_id,
                    "action_kind": action_kind,
                    "gain": round(max(0.0, gain), 8),
                    "threshold": float(threshold),
                    "cooldown_ticks": int(cooldown),
                    "params": dict(params),
                    "source": source,
                }
            )
        return out

    def _triggers_from_complexity(self, cfs_signals: list[dict]) -> list[dict[str, Any]]:
        complexity = self._best_global_signal_strength(cfs_signals, kind="complexity")
        if complexity <= 0.0:
            return []

        out: list[dict[str, Any]] = []
        gain_base = float(self._config.get("mode_drive_gain", 0.60))
        threshold = float(self._config.get("mode_threshold", 0.55))
        cooldown = int(self._config.get("mode_cooldown_ticks", 2) or 0)
        focus_th = float(self._config.get("focus_mode_complexity_threshold", 0.65))
        diverge_th = float(self._config.get("diverge_mode_complexity_threshold", 0.25))

        if complexity >= focus_th:
            out.append(
                {
                    "action_id": "attention_focus_mode",
                    "action_kind": "attention_focus_mode",
                    "gain": round(gain_base * complexity, 8),
                    "threshold": threshold,
                    "cooldown_ticks": cooldown,
                    "params": {"complexity": complexity},
                    "source": {"kind": "cfs_complexity", "strength": complexity},
                }
            )
        elif complexity <= diverge_th:
            # When complexity is very low ("simple"), try to diverge.
            # 澶嶆潅搴﹀緢浣庯紙寰堚€滅畝鈥濓級鏃讹紝灏濊瘯鍙戞暎銆?            score = self._clamp01((diverge_th - complexity) / max(1e-6, diverge_th))
            out.append(
                {
                    "action_id": "attention_diverge_mode",
                    "action_kind": "attention_diverge_mode",
                    "gain": round(gain_base * score, 8),
                    "threshold": threshold,
                    "cooldown_ticks": cooldown,
                    "params": {"complexity": complexity},
                    "source": {"kind": "cfs_complexity", "strength": score},
                }
            )
        return out

    def _triggers_from_recall(self, cfs_signals: list[dict], memory_activation_snapshot: dict) -> list[dict[str, Any]]:
        items = memory_activation_snapshot.get("items", []) or []
        if not items:
            return []

        kinds = [str(x) for x in (self._config.get("recall_trigger_kinds") or []) if str(x)]
        min_strength = float(self._config.get("recall_min_strength", 0.45))
        best = 0.0
        best_kind = ""
        best_target = {}
        for sig in cfs_signals:
            if not isinstance(sig, dict):
                continue
            if str(sig.get("scope", "")) != "object":
                continue
            kind = str(sig.get("kind", "") or "")
            if kinds and kind not in kinds:
                continue
            strength = float(sig.get("strength", 0.0) or 0.0)
            if strength > best:
                best = strength
                best_kind = kind
                best_target = dict(sig.get("target", {}) or {}) if isinstance(sig.get("target", {}), dict) else {}

        if best < min_strength:
            return []

        gain_base = float(self._config.get("recall_gain_base", 0.55))
        threshold = float(self._config.get("recall_threshold", 0.55))
        return [
            {
                "action_id": "recall_top_memory",
                "action_kind": "recall",
                "gain": round(gain_base * self._clamp01(best), 8),
                "threshold": threshold,
                "cooldown_ticks": 0,
                "params": {"trigger_kind": best_kind, "trigger_strength": best, "trigger_target": best_target},
                "source": {"kind": f"cfs_{best_kind}", "strength": best},
            }
        ]

    @staticmethod
    def _extract_action_target_from_params(params: dict[str, Any] | None) -> dict[str, str]:
        params = params or {}
        target_ref_object_id = str(
            params.get("target_ref_object_id", params.get("ref_object_id", "")) or ""
        ).strip()
        target_ref_object_type = str(
            params.get("target_ref_object_type", params.get("ref_object_type", "")) or ""
        ).strip()
        target_item_id = str(params.get("target_item_id", params.get("item_id", "")) or "").strip()
        target_display = str(
            params.get(
                "target_display",
                params.get("display", params.get("trigger_target_display", "")),
            )
            or ""
        ).strip()
        trigger_target_ref = str(
            params.get(
                "trigger_target_ref",
                params.get("trigger_target", params.get("target_ref", params.get("anchor_ref", ""))),
            )
            or ""
        ).strip()
        if not target_ref_object_id and trigger_target_ref:
            if ":" in trigger_target_ref:
                target_ref_object_type, target_ref_object_id = [x.strip() for x in trigger_target_ref.split(":", 1)]
            else:
                target_ref_object_id = trigger_target_ref
        if not target_display:
            target_display = target_ref_object_id or target_item_id
        return {
            "target_ref_object_id": str(target_ref_object_id or ""),
            "target_ref_object_type": str(target_ref_object_type or ""),
            "target_item_id": str(target_item_id or ""),
            "target_display": str(target_display or ""),
        }

    @staticmethod
    def _normalize_local_feedback_text(text: Any) -> str:
        raw = str(text or "").strip().lower()
        if not raw:
            return ""
        raw = re.sub(r"[a-z_][a-z0-9_\-]*:[0-9.]+", "", raw)
        fragments = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", raw)
        if fragments:
            return "".join(fragments).strip()
        raw = re.sub(r"[{}\[\]()<>【】《》「」『』\s]+", "", raw)
        return raw.strip()

    def _score_local_feedback_text_similarity(self, *, target_display: str, candidate_display: str) -> float:
        target_norm = self._normalize_local_feedback_text(target_display)
        candidate_norm = self._normalize_local_feedback_text(candidate_display)
        if not target_norm or not candidate_norm:
            return 0.0
        if target_norm == candidate_norm:
            return 1.0
        if target_norm in candidate_norm or candidate_norm in target_norm:
            return 1.0
        try:
            longest = difflib.SequenceMatcher(None, target_norm, candidate_norm).find_longest_match(
                0,
                len(target_norm),
                0,
                len(candidate_norm),
            ).size
        except Exception:
            longest = 0
        return self._clamp01(float(longest) / float(max(1, len(target_norm))))

    def _find_local_feedback_text_fallback(
        self,
        *,
        target_ref_object_type: str,
        target_display: str,
        by_ref: dict[str, Any],
        by_item: dict[str, Any],
    ) -> dict[str, Any]:
        fallback_enabled = bool(self._config.get("local_drive_feedback_text_fallback_enabled", True))
        detail: dict[str, Any] = {
            "text_fallback_attempted": False,
            "text_fallback_best_score": 0.0,
            "text_fallback_candidate_count": 0,
        }
        if not fallback_enabled:
            detail["text_fallback_reason"] = "config_disabled"
            return {"local_feedback": None, "lookup_key": "", "lookup_mode": "", "detail": detail}

        allow_target_types = {
            str(x or "").strip().lower()
            for x in (self._config.get("local_drive_feedback_text_fallback_target_types") or [])
            if str(x or "").strip()
        }
        target_type_norm = str(target_ref_object_type or "").strip().lower()
        if allow_target_types and target_type_norm not in allow_target_types:
            detail["text_fallback_reason"] = "target_type_filtered"
            return {"local_feedback": None, "lookup_key": "", "lookup_mode": "", "detail": detail}

        target_norm = self._normalize_local_feedback_text(target_display)
        try:
            min_chars = int(self._config.get("local_drive_feedback_text_fallback_min_chars", 6) or 6)
        except Exception:
            min_chars = 6
        if len(target_norm) < max(1, min_chars):
            detail["text_fallback_reason"] = "target_text_too_short"
            return {"local_feedback": None, "lookup_key": "", "lookup_mode": "", "detail": detail}

        try:
            min_score = float(self._config.get("local_drive_feedback_text_fallback_min_score", 0.55) or 0.55)
        except Exception:
            min_score = 0.55
        min_score = self._clamp01(min_score)
        try:
            max_candidates = int(self._config.get("local_drive_feedback_text_fallback_max_candidates", 96) or 96)
        except Exception:
            max_candidates = 96
        max_candidates = max(1, min(512, max_candidates))

        detail["text_fallback_attempted"] = True
        best_payload: dict[str, Any] | None = None
        best_lookup_key = ""
        best_lookup_mode = ""
        best_score = 0.0
        best_signal_mag = -1.0
        best_len_penalty = 10**9
        candidate_count = 0
        seen_keys: set[str] = set()

        for lookup_mode, bucket in (("ref", by_ref), ("item", by_item)):
            if not isinstance(bucket, dict):
                continue
            for raw_key, payload in bucket.items():
                if candidate_count >= max_candidates:
                    break
                if not isinstance(payload, dict):
                    continue
                key = f"{lookup_mode}::{str(raw_key or '').strip()}"
                if not str(raw_key or "").strip() or key in seen_keys:
                    continue
                seen_keys.add(key)
                candidate_count += 1
                candidate_display = str(payload.get("display", "") or "").strip()
                score = self._score_local_feedback_text_similarity(
                    target_display=str(target_display or ""),
                    candidate_display=candidate_display,
                )
                if score <= 0.0:
                    continue
                signal_mag = max(0.0, float(payload.get("rwd", 0.0) or 0.0)) + max(0.0, float(payload.get("pun", 0.0) or 0.0))
                candidate_norm = self._normalize_local_feedback_text(candidate_display)
                len_penalty = abs(len(candidate_norm) - len(target_norm))
                if (
                    score > best_score
                    or (abs(score - best_score) <= 1e-12 and signal_mag > best_signal_mag)
                    or (abs(score - best_score) <= 1e-12 and abs(signal_mag - best_signal_mag) <= 1e-12 and len_penalty < best_len_penalty)
                ):
                    best_payload = dict(payload)
                    best_lookup_key = key
                    best_lookup_mode = "text_fallback"
                    best_score = score
                    best_signal_mag = signal_mag
                    best_len_penalty = len_penalty
            if candidate_count >= max_candidates:
                break

        detail["text_fallback_candidate_count"] = int(candidate_count)
        detail["text_fallback_best_score"] = round(float(best_score), 8)
        if best_lookup_key:
            detail["text_fallback_best_lookup_key"] = str(best_lookup_key)
        if not isinstance(best_payload, dict) or best_score < min_score:
            detail["text_fallback_reason"] = "no_candidate_above_threshold"
            return {"local_feedback": None, "lookup_key": "", "lookup_mode": "", "detail": detail}

        detail["reason"] = "local_feedback_text_fallback"
        detail["text_fallback_lookup_key"] = str(best_lookup_key)
        return {
            "local_feedback": best_payload,
            "lookup_key": f"text::{best_lookup_key}",
            "lookup_mode": best_lookup_mode,
            "detail": detail,
        }

    def _compute_local_drive_modulation(
        self,
        *,
        gain: float,
        params: dict[str, Any] | None,
        local_reward_punish_map: dict[str, Any] | None,
    ) -> dict[str, Any]:
        base_gain_raw = max(0.0, float(gain or 0.0))
        target = self._extract_action_target_from_params(params)
        params = params or {}
        input_drive_scale = 1.0
        input_drive_boost_applied = False
        target_ref_object_type = str(target.get("target_ref_object_type", "") or "").strip().lower()
        if target_ref_object_type == "input":
            try:
                input_drive_scale = float(params.get("explicit_input_drive_scale", 1.0) or 1.0)
            except Exception:
                input_drive_scale = 1.0
            input_drive_scale = max(1.0, min(3.0, float(input_drive_scale)))
            input_drive_boost_applied = abs(input_drive_scale - 1.0) > 1e-12
        base_gain = float(base_gain_raw) * float(input_drive_scale)
        result = {
            "enabled": bool(self._config.get("local_drive_modulation_by_rwd_pun_enabled", True)),
            "target_ref_object_id": str(target.get("target_ref_object_id", "") or ""),
            "target_ref_object_type": str(target.get("target_ref_object_type", "") or ""),
            "target_item_id": str(target.get("target_item_id", "") or ""),
            "target_display": str(target.get("target_display", "") or ""),
            "base_gain_raw": float(base_gain_raw),
            "lookup_key": "",
            "lookup_attempted": False,
            "lookup_hit": False,
            "lookup_status": "skipped",
            "lookup_mode": "",
            "applied": False,
            "scale_raw": 1.0,
            "scale_clamped": 1.0,
            "input_drive_scale": float(input_drive_scale),
            "input_drive_boost_applied": bool(input_drive_boost_applied),
            "input_drive_boost_gain": max(0.0, float(base_gain - base_gain_raw)),
            "reward_bonus_scale": 0.0,
            "punish_penalty_scale": 0.0,
            "reward": 0.0,
            "punish": 0.0,
            "base_gain": float(base_gain),
            "gain_after": float(base_gain),
            "reward_bonus_gain": 0.0,
            "punish_penalty_gain": 0.0,
            "sensitivity": 1.0,
            "detail": {},
        }
        if base_gain <= 0.0:
            result["detail"] = {"reason": "non_positive_gain"}
            return result

        if not bool(self._config.get("local_drive_modulation_by_rwd_pun_enabled", True)):
            result["detail"] = {"reason": "config_disabled", "input_drive_boost_applied": bool(input_drive_boost_applied)}
            return result
        if bool(params.get("disable_local_reward_punish_drive_modulation", False)):
            result["detail"] = {"reason": "node_disabled", "input_drive_boost_applied": bool(input_drive_boost_applied)}
            return result

        try:
            sensitivity = float(params.get("local_rwd_pun_drive_sensitivity", 1.0) or 1.0)
        except Exception:
            sensitivity = 1.0
        sensitivity = max(0.0, min(3.0, float(sensitivity)))
        result["sensitivity"] = float(sensitivity)

        require_target = bool(self._config.get("local_drive_modulation_require_target", True))
        target_ref_object_id = str(target.get("target_ref_object_id", "") or "")
        target_item_id = str(target.get("target_item_id", "") or "")
        if require_target and not target_ref_object_id and not target_item_id:
            result["detail"] = {"reason": "target_required_but_missing", "input_drive_boost_applied": bool(input_drive_boost_applied)}
            return result
        if not target_ref_object_id and not target_item_id:
            result["detail"] = {"reason": "lookup_target_missing", "input_drive_boost_applied": bool(input_drive_boost_applied)}
            return result

        by_ref = {}
        by_item = {}
        if isinstance(local_reward_punish_map, dict):
            by_ref = local_reward_punish_map.get("by_ref", {}) if isinstance(local_reward_punish_map.get("by_ref", {}), dict) else {}
            by_item = local_reward_punish_map.get("by_item", {}) if isinstance(local_reward_punish_map.get("by_item", {}), dict) else {}

        local_feedback = None
        lookup_key = ""
        lookup_mode = ""
        result["lookup_attempted"] = True
        if target_ref_object_id and target_ref_object_id in by_ref:
            local_feedback = by_ref.get(target_ref_object_id)
            lookup_key = f"ref::{target_ref_object_id}"
            lookup_mode = "direct_ref"
        elif target_item_id and target_item_id in by_item:
            local_feedback = by_item.get(target_item_id)
            lookup_key = f"item::{target_item_id}"
            lookup_mode = "direct_item"
        fallback_probe = {"local_feedback": None, "lookup_key": "", "lookup_mode": "", "detail": {}}
        if not isinstance(local_feedback, dict):
            fallback_probe = self._find_local_feedback_text_fallback(
                target_ref_object_type=str(target.get("target_ref_object_type", "") or ""),
                target_display=str(target.get("target_display", "") or ""),
                by_ref=by_ref,
                by_item=by_item,
            )
            if isinstance(fallback_probe.get("local_feedback"), dict):
                local_feedback = dict(fallback_probe.get("local_feedback") or {})
                lookup_key = str(fallback_probe.get("lookup_key", "") or "")
                lookup_mode = str(fallback_probe.get("lookup_mode", "") or "")

        result["lookup_key"] = str(lookup_key or "")
        result["lookup_mode"] = str(lookup_mode or "")
        result["lookup_hit"] = isinstance(local_feedback, dict)
        if not isinstance(local_feedback, dict):
            result["lookup_status"] = "miss"
            detail = {"reason": "local_feedback_not_found", "input_drive_boost_applied": bool(input_drive_boost_applied)}
            if isinstance(fallback_probe.get("detail"), dict):
                detail.update(dict(fallback_probe.get("detail") or {}))
            result["detail"] = detail
            return result

        reward = max(0.0, float(local_feedback.get("rwd", 0.0) or 0.0))
        punish = max(0.0, float(local_feedback.get("pun", 0.0) or 0.0))
        reward_coef = max(0.0, float(self._config.get("local_drive_reward_bonus_coef", 0.45) or 0.45))
        punish_coef = max(0.0, float(self._config.get("local_drive_punish_penalty_coef", 0.55) or 0.55))
        scale_min = max(0.0, float(self._config.get("local_drive_scale_min", 0.20) or 0.20))
        scale_max = max(scale_min, float(self._config.get("local_drive_scale_max", 1.80) or 1.80))

        reward_bonus_scale = float(reward) * float(reward_coef) * float(sensitivity)
        punish_penalty_scale = float(punish) * float(punish_coef) * float(sensitivity)
        scale_raw = 1.0 + reward_bonus_scale - punish_penalty_scale
        scale_clamped = max(scale_min, min(scale_max, float(scale_raw)))
        gain_after = float(base_gain) * float(scale_clamped)
        detail = dict(local_feedback.get("detail", {}) or {}) if isinstance(local_feedback.get("detail", {}), dict) else {}
        if isinstance(fallback_probe.get("detail"), dict) and lookup_mode == "text_fallback":
            detail.update(dict(fallback_probe.get("detail") or {}))

        result.update(
            {
                "lookup_hit": True,
                "lookup_status": "hit",
                "applied": abs(gain_after - base_gain) > 1e-12,
                "scale_raw": float(scale_raw),
                "scale_clamped": float(scale_clamped),
                "reward_bonus_scale": float(reward_bonus_scale),
                "punish_penalty_scale": float(punish_penalty_scale),
                "reward": float(reward),
                "punish": float(punish),
                "gain_after": float(gain_after),
                "reward_bonus_gain": max(0.0, float(gain_after - base_gain)),
                "punish_penalty_gain": max(0.0, float(base_gain - gain_after)),
                "detail": detail,
            }
        )
        return result

    # ================================================================== #
    # Node ops / 鑺傜偣缁存姢                                                 #
    # ================================================================== #

    def _apply_trigger(self, trig: dict[str, Any], *, tick_number: int, local_reward_punish_map: dict[str, Any] | None = None) -> None:
        action_id = str(trig.get("action_id", "") or "")
        if not action_id:
            return
        action_kind = str(trig.get("action_kind", "") or "")
        gain = max(0.0, float(trig.get("gain", 0.0) or 0.0))
        threshold = float(trig.get("threshold", 1.0) or 1.0)
        cooldown = int(trig.get("cooldown_ticks", 0) or 0)
        drive_max = float(self._config.get("drive_max", 3.0))

        node = self._nodes.get(action_id)
        if node is None:
            if len(self._nodes) >= int(self._config.get("max_action_nodes", 64) or 64):
                return
            node = {
                "action_id": action_id,
                "action_kind": action_kind,
                "drive": 0.0,
                "threshold": float(threshold),
                "cooldown_ticks": cooldown,
                "params": {},
                "trigger_sources": [],
                "created_at": int(time.time() * 1000),
                "last_update_tick": tick_number,
                "last_trigger_tick": -999999,
            }
            self._nodes[action_id] = node

        node["action_kind"] = action_kind or node.get("action_kind", "")
        # Store baseline threshold on node; effective threshold is computed per tick.
        # 鑺傜偣鍐呭瓨鏀锯€滃熀鍑嗛槇鍊尖€濓紝瀹炴椂闃堝€煎湪姣?tick 鏍规嵁璋冨埗鍐嶈绠椼€?        node["threshold"] = float(threshold)
        node["cooldown_ticks"] = cooldown
        node["params"] = dict(trig.get("params", {}) or {})
        target = self._extract_action_target_from_params(node.get("params", {}))
        node["target_ref_object_id"] = str(target.get("target_ref_object_id", "") or node.get("target_ref_object_id", "") or "")
        node["target_ref_object_type"] = str(target.get("target_ref_object_type", "") or node.get("target_ref_object_type", "") or "")
        node["target_item_id"] = str(target.get("target_item_id", "") or node.get("target_item_id", "") or "")
        node["target_display"] = str(target.get("target_display", "") or node.get("target_display", "") or "")
        source_meta = trig.get("source", {}) if isinstance(trig.get("source", {}), dict) else {}
        node["target_binding_strategy"] = str(source_meta.get("target_binding_strategy", node.get("target_binding_strategy", "")) or "")
        node["target_binding_requested_from"] = str(
            source_meta.get("target_binding_requested_from", node.get("target_binding_requested_from", "")) or ""
        )
        node["target_binding_reason"] = str(source_meta.get("target_binding_reason", node.get("target_binding_reason", "")) or "")
        node["target_binding_match_source"] = str(
            source_meta.get("target_binding_match_source", node.get("target_binding_match_source", "")) or ""
        )
        node["target_binding_match_ref_object_id"] = str(
            source_meta.get("target_binding_match_ref_object_id", node.get("target_binding_match_ref_object_id", "")) or ""
        )
        node["target_binding_match_ref_object_type"] = str(
            source_meta.get("target_binding_match_ref_object_type", node.get("target_binding_match_ref_object_type", "")) or ""
        )
        node["target_binding_match_item_id"] = str(
            source_meta.get("target_binding_match_item_id", node.get("target_binding_match_item_id", "")) or ""
        )
        node["target_binding_match_display"] = str(
            source_meta.get("target_binding_match_display", node.get("target_binding_match_display", "")) or ""
        )
        if "target_binding_applied" in source_meta:
            node["target_binding_applied"] = bool(source_meta.get("target_binding_applied", False))
        local_mod = self._compute_local_drive_modulation(
            gain=float(gain),
            params=node.get("params", {}),
            local_reward_punish_map=local_reward_punish_map or {},
        )
        applied_gain = max(0.0, float(local_mod.get("gain_after", gain) or gain))
        node["last_local_drive_modulation"] = dict(local_mod)
        node["drive"] = max(0.0, min(drive_max, float(node.get("drive", 0.0)) + applied_gain))
        node["last_update_tick"] = tick_number
        node.setdefault("trigger_sources", []).append(trig.get("source", {}))
        # Per-tick trigger summary (for observability).
        # 鏈?tick 瑙﹀彂婧愭憳瑕侊紙鐢ㄤ簬瑙傛祴鈥滆鍔?涓诲姩鍘熷洜鈥濓級銆?        node["tick_gain_total"] = float(node.get("tick_gain_total", 0.0) or 0.0) + float(gain)
        node["tick_gain_raw_total"] = float(node.get("tick_gain_raw_total", 0.0) or 0.0) + float(gain)
        node["tick_gain_total"] = float(node.get("tick_gain_total", 0.0) or 0.0) - float(gain) + float(applied_gain)
        node["tick_local_gain_base_total"] = float(node.get("tick_local_gain_base_total", 0.0) or 0.0) + float(gain)
        node["tick_local_gain_applied_total"] = float(node.get("tick_local_gain_applied_total", 0.0) or 0.0) + float(applied_gain)
        node["tick_local_reward_bonus_total"] = float(node.get("tick_local_reward_bonus_total", 0.0) or 0.0) + float(local_mod.get("reward_bonus_gain", 0.0) or 0.0)
        node["tick_local_punish_penalty_total"] = float(node.get("tick_local_punish_penalty_total", 0.0) or 0.0) + float(local_mod.get("punish_penalty_gain", 0.0) or 0.0)
        lookup_status = str(local_mod.get("lookup_status", "") or "").strip().lower()
        detail_payload = local_mod.get("detail", {})
        lookup_reason = str(detail_payload.get("reason", "") or "").strip().lower() if isinstance(detail_payload, dict) else ""
        if lookup_status == "hit" or bool(local_mod.get("lookup_hit", False)):
            node["tick_local_lookup_hit_count"] = int(node.get("tick_local_lookup_hit_count", 0) or 0) + 1
        elif lookup_status == "miss" or lookup_reason == "local_feedback_not_found":
            node["tick_local_lookup_miss_count"] = int(node.get("tick_local_lookup_miss_count", 0) or 0) + 1
        else:
            node["tick_local_lookup_skipped_count"] = int(node.get("tick_local_lookup_skipped_count", 0) or 0) + 1
            if lookup_reason in {"target_required_but_missing", "lookup_target_missing"}:
                node["tick_local_target_missing_count"] = int(node.get("tick_local_target_missing_count", 0) or 0) + 1
            if lookup_reason in {"config_disabled", "node_disabled"}:
                node["tick_local_disabled_count"] = int(node.get("tick_local_disabled_count", 0) or 0) + 1
        if bool(local_mod.get("applied", False)):
            node["tick_local_modulated_count"] = int(node.get("tick_local_modulated_count", 0) or 0) + 1
        sk = str((trig.get("source", {}) or {}).get("kind", "") or "unknown")
        by = node.get("tick_gain_by_source_kind", {}) if isinstance(node.get("tick_gain_by_source_kind", {}), dict) else {}
        by[sk] = round(float(by.get(sk, 0.0) or 0.0) + float(applied_gain), 8)
        node["tick_gain_by_source_kind"] = by
        node.setdefault("tick_sources", []).append(trig.get("source", {}) or {})
        # Trim sources to keep memory bounded.
        if len(node["trigger_sources"]) > 12:
            node["trigger_sources"] = node["trigger_sources"][-12:]

    def _should_execute(self, node: dict, *, tick_number: int) -> bool:
        # Stop/hold gate: when a node is explicitly stopped, prevent execution for a while.
        try:
            stop_until = int(node.get("stop_until_tick", -1) or -1)
        except Exception:
            stop_until = -1
        if stop_until >= 0 and tick_number <= stop_until:
            return False

        # Async pending gate: if an async action is already scheduled, do not schedule it
        # again until the completion tick arrives.
        try:
            pending_until = int(node.get("pending_async_until_tick", -1) or -1)
        except Exception:
            pending_until = -1
        if pending_until >= 0 and tick_number <= pending_until:
            return False

        drive = float(node.get("drive", 0.0) or 0.0)
        threshold = float(node.get("effective_threshold", node.get("threshold", 1.0) or 1.0) or 1.0)
        if drive < threshold:
            return False

        cooldown = int(node.get("cooldown_ticks", 0) or 0)
        if cooldown <= 0:
            return True
        last = int(node.get("last_trigger_tick", -999999) or -999999)
        return (tick_number - last) > cooldown

    def _compute_effective_threshold(self, *, node: dict[str, Any], emotion_state: dict) -> dict[str, Any]:
        """Compute the effective execution threshold for the current tick.

        It combines base threshold, NT modulation, reward/punish modulation,
        and local action fatigue.
        Returns base_threshold, threshold_scale, effective_threshold, and component details.
        """
        base_threshold = float(node.get("threshold", 1.0) or 1.0)

        # Optional: disable threshold modulation for specific nodes.
        # This is useful for expectation-contract experiments where we want the
        # action threshold to remain stable across different NT / fatigue states.
        params = (node.get("params", {}) or {}) if isinstance(node.get("params", {}), dict) else {}
        if bool(params.get("disable_threshold_modulation", False)):
            return {
                "base_threshold": float(base_threshold),
                "threshold_scale": 1.0,
                "effective_threshold": float(base_threshold),
                "components": {
                    "mode": "fixed_base_threshold",
                    "nt_scale_raw": 1.0,
                    "nt_scale_clamped": 1.0,
                    "combined_scale_pre_fatigue": 1.0,
                    "rwd_pun_enabled": False,
                    "rwd_pun_scale_raw": 1.0,
                    "rwd_pun_scale_clamped": 1.0,
                    "rwd_pun_reward_delta_scale": 0.0,
                    "rwd_pun_punish_delta_scale": 0.0,
                    "rwd_pun_reward_threshold_delta": 0.0,
                    "rwd_pun_punish_threshold_delta": 0.0,
                    "rwd_pun_sensitivity": 0.0,
                    "rwd_pun_snapshot": {},
                    "fatigue_scale": 1.0,
                    "fatigue": float(node.get("fatigue", 0.0) or 0.0),
                    "nt_snapshot": {},
                    "threshold_delta": 0.0,
                },
            }
        # 1) NT scaling
        nt = {}
        # emotion_state 鏉ヨ嚜 EmotionManager.update_emotion_state 鐨?data 瀛楁
        # 甯歌瀛楁锛歯t_state_after / nt_state_snapshot / modulation
        if isinstance(emotion_state.get("nt_state_after"), dict):
            nt = dict(emotion_state.get("nt_state_after") or {})
        elif isinstance(emotion_state.get("nt_state_before"), dict):
            nt = dict(emotion_state.get("nt_state_before") or {})
        elif isinstance(emotion_state.get("nt_state_snapshot"), dict):
            channels = (emotion_state.get("nt_state_snapshot", {}) or {}).get("channels", {})
            if isinstance(channels, dict):
                nt = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in channels.items()}

        nt_scale_map = self._config.get("threshold_scale_by_nt", {}) or {}
        nt_scale = 1.0
        if isinstance(nt_scale_map, dict) and isinstance(nt, dict):
            for ch, coef in nt_scale_map.items():
                try:
                    nt_scale += float(nt.get(ch, 0.0) or 0.0) * float(coef or 0.0)
                except Exception:
                    continue

        zmin = float(self._config.get("threshold_scale_min", 0.55) or 0.55)
        zmax = float(self._config.get("threshold_scale_max", 1.75) or 1.75)
        nt_scale_clamped = max(zmin, min(zmax, float(nt_scale)))

        # 2) Reward / punish scaling
        rwd_pun_snapshot_raw = emotion_state.get("rwd_pun_snapshot", {})
        rwd_pun_snapshot = dict(rwd_pun_snapshot_raw or {}) if isinstance(rwd_pun_snapshot_raw, dict) else {}
        try:
            rwd = max(0.0, float(rwd_pun_snapshot.get("rwd", 0.0) or 0.0))
        except Exception:
            rwd = 0.0
        try:
            pun = max(0.0, float(rwd_pun_snapshot.get("pun", 0.0) or 0.0))
        except Exception:
            pun = 0.0

        rwd_pun_enabled = bool(self._config.get("threshold_scale_by_rwd_pun_enabled", True))
        disable_rwd_pun = bool(params.get("disable_rwd_pun_threshold_modulation", False))
        try:
            rwd_pun_sensitivity = float(params.get("rwd_pun_threshold_sensitivity", 1.0) or 1.0)
        except Exception:
            rwd_pun_sensitivity = 1.0
        rwd_pun_sensitivity = max(0.0, min(3.0, float(rwd_pun_sensitivity)))

        reward_coef = float(self._config.get("threshold_scale_by_rwd_pun_reward_coef", -0.28) or -0.28)
        punish_coef = float(self._config.get("threshold_scale_by_rwd_pun_punish_coef", 0.34) or 0.34)
        rwd_pun_min = float(self._config.get("threshold_scale_by_rwd_pun_min", 0.60) or 0.60)
        rwd_pun_max = float(self._config.get("threshold_scale_by_rwd_pun_max", 1.45) or 1.45)

        reward_delta_scale = 0.0
        punish_delta_scale = 0.0
        rwd_pun_scale = 1.0
        if rwd_pun_enabled and not disable_rwd_pun:
            reward_delta_scale = float(rwd) * float(reward_coef) * float(rwd_pun_sensitivity)
            punish_delta_scale = float(pun) * float(punish_coef) * float(rwd_pun_sensitivity)
            rwd_pun_scale += reward_delta_scale + punish_delta_scale
        rwd_pun_scale_clamped = max(rwd_pun_min, min(rwd_pun_max, float(rwd_pun_scale)))

        combined_scale_pre_fatigue = max(zmin, min(zmax, float(nt_scale_clamped) * float(rwd_pun_scale_clamped)))

        # 3) Local action fatigue scaling
        fatigue = float(node.get("fatigue", 0.0) or 0.0)
        fatigue_gain = float(self._config.get("action_fatigue_threshold_gain", 0.55) or 0.55)
        fatigue_scale = 1.0 + max(0.0, min(1.0, fatigue)) * max(0.0, fatigue_gain)

        threshold_scale = float(combined_scale_pre_fatigue) * float(fatigue_scale)
        effective = base_threshold * threshold_scale
        reward_threshold_delta = float(base_threshold) * float(min(0.0, reward_delta_scale))
        punish_threshold_delta = float(base_threshold) * float(max(0.0, punish_delta_scale))
        return {
            "base_threshold": float(base_threshold),
            "threshold_scale": float(threshold_scale),
            "effective_threshold": float(effective),
            "components": {
                "nt_scale_raw": float(nt_scale),
                "nt_scale_clamped": float(nt_scale_clamped),
                "combined_scale_pre_fatigue": float(combined_scale_pre_fatigue),
                "rwd_pun_enabled": bool(rwd_pun_enabled and not disable_rwd_pun),
                "rwd_pun_scale_raw": float(rwd_pun_scale),
                "rwd_pun_scale_clamped": float(rwd_pun_scale_clamped),
                "rwd_pun_reward_delta_scale": float(reward_delta_scale),
                "rwd_pun_punish_delta_scale": float(punish_delta_scale),
                "rwd_pun_reward_threshold_delta": float(reward_threshold_delta),
                "rwd_pun_punish_threshold_delta": float(punish_threshold_delta),
                "rwd_pun_sensitivity": float(rwd_pun_sensitivity),
                "rwd_pun_snapshot": {"rwd": float(rwd), "pun": float(pun)},
                "fatigue_scale": float(fatigue_scale),
                "fatigue": float(fatigue),
                "nt_snapshot": {str(k): float(v or 0.0) for k, v in (nt or {}).items() if str(k)},
                "threshold_delta": float(effective - base_threshold),
            },
        }

    def _build_action_learning_summary(self, nodes: list[dict[str, Any]] | None) -> dict[str, Any]:
        rows = [row for row in (nodes or []) if isinstance(row, dict)]
        local_scale_vals: list[float] = []
        targeted_node_count = 0
        local_modulated_node_count = 0
        local_lookup_hit_count = 0
        local_lookup_text_fallback_hit_count = 0
        local_lookup_miss_count = 0
        local_lookup_skipped_count = 0
        local_target_missing_count = 0
        local_modulation_disabled_count = 0
        local_reward_bonus_total = 0.0
        local_punish_penalty_total = 0.0
        local_gain_base_total = 0.0
        local_gain_applied_total = 0.0
        examples: list[dict[str, Any]] = []

        for row in rows:
            target_ref_object_id = str(row.get("target_ref_object_id", "") or "")
            target_item_id = str(row.get("target_item_id", "") or "")
            if target_ref_object_id or target_item_id:
                targeted_node_count += 1
            local_mod = row.get("last_local_drive_modulation", row.get("local_drive_modulation", {}))
            local_mod = dict(local_mod or {}) if isinstance(local_mod, dict) else {}
            detail_payload = local_mod.get("detail", {})
            local_reason = str(detail_payload.get("reason", "") or "").strip().lower() if isinstance(detail_payload, dict) else ""
            local_status = str(local_mod.get("lookup_status", "") or "").strip().lower()
            local_lookup_mode = str(local_mod.get("lookup_mode", "") or "").strip().lower()
            if not local_status:
                if bool(local_mod.get("lookup_hit", False)):
                    local_status = "hit"
                elif local_reason == "local_feedback_not_found":
                    local_status = "miss"
                else:
                    local_status = "skipped"
            if local_status == "hit":
                local_lookup_hit_count += 1
                if local_lookup_mode == "text_fallback":
                    local_lookup_text_fallback_hit_count += 1
            elif local_status == "miss":
                local_lookup_miss_count += 1
            else:
                local_lookup_skipped_count += 1
                if local_reason in {"target_required_but_missing", "lookup_target_missing"}:
                    local_target_missing_count += 1
                if local_reason in {"config_disabled", "node_disabled"}:
                    local_modulation_disabled_count += 1
            if bool(local_mod.get("applied", False)):
                local_modulated_node_count += 1
                local_scale_vals.append(float(local_mod.get("scale_clamped", 1.0) or 1.0))
                examples.append(
                    {
                        "action_id": str(row.get("action_id", "") or ""),
                        "action_kind": str(row.get("action_kind", "") or ""),
                        "target_ref_object_id": target_ref_object_id,
                        "target_item_id": target_item_id,
                        "target_display": str(row.get("target_display", "") or ""),
                        "reward": round(float(local_mod.get("reward", 0.0) or 0.0), 8),
                        "punish": round(float(local_mod.get("punish", 0.0) or 0.0), 8),
                        "lookup_mode": str(local_lookup_mode or ""),
                        "scale_clamped": round(float(local_mod.get("scale_clamped", 1.0) or 1.0), 8),
                        "reward_bonus_gain": round(float(local_mod.get("reward_bonus_gain", 0.0) or 0.0), 8),
                        "punish_penalty_gain": round(float(local_mod.get("punish_penalty_gain", 0.0) or 0.0), 8),
                    }
                )
            local_reward_bonus_total += max(0.0, float(row.get("tick_local_reward_bonus_total", 0.0) or 0.0))
            local_punish_penalty_total += max(0.0, float(row.get("tick_local_punish_penalty_total", 0.0) or 0.0))
            local_gain_base_total += max(0.0, float(row.get("tick_local_gain_base_total", row.get("tick_gain_raw_total", 0.0)) or 0.0))
            local_gain_applied_total += max(0.0, float(row.get("tick_local_gain_applied_total", row.get("tick_gain_total", 0.0)) or 0.0))

        examples.sort(key=lambda row: abs(float(row.get("scale_clamped", 1.0) or 1.0) - 1.0), reverse=True)
        return {
            "local_drive_modulation_enabled": bool(self._config.get("local_drive_modulation_by_rwd_pun_enabled", True)),
            "targeted_node_count": int(targeted_node_count),
            "local_modulated_node_count": int(local_modulated_node_count),
            "local_lookup_hit_count": int(local_lookup_hit_count),
            "local_lookup_text_fallback_hit_count": int(local_lookup_text_fallback_hit_count),
            "local_lookup_miss_count": int(local_lookup_miss_count),
            "local_lookup_skipped_count": int(local_lookup_skipped_count),
            "local_target_missing_count": int(local_target_missing_count),
            "local_modulation_disabled_count": int(local_modulation_disabled_count),
            "local_drive_scale_mean": round(float(sum(local_scale_vals) / len(local_scale_vals)) if local_scale_vals else 1.0, 8),
            "local_reward_drive_bonus_total": round(float(local_reward_bonus_total), 8),
            "local_punish_drive_penalty_total": round(float(local_punish_penalty_total), 8),
            "local_gain_base_total": round(float(local_gain_base_total), 8),
            "local_gain_applied_total": round(float(local_gain_applied_total), 8),
            "local_gain_net_delta_total": round(float(local_gain_applied_total - local_gain_base_total), 8),
            "examples": examples[:8],
        }

    def _prune_idle_nodes(self, *, tick_number: int) -> None:
        idle = int(self._config.get("node_idle_prune_ticks", 18) or 0)
        if idle <= 0:
            return
        to_delete = []
        for action_id, node in self._nodes.items():
            last_update = int(node.get("last_update_tick", tick_number) or tick_number)
            last_trigger = int(node.get("last_trigger_tick", -999999) or -999999)
            if (tick_number - max(last_update, last_trigger)) > idle:
                to_delete.append(action_id)
        for action_id in to_delete:
            self._nodes.pop(action_id, None)

    # ================================================================== #
    # Builders / 鏋勯€犲櫒                                                   #
    # ================================================================== #

    @staticmethod
    def _focus_action_id(directive: dict) -> str:
        ref_id = str(directive.get("target_ref_object_id", "") or "")
        ref_type = str(directive.get("target_ref_object_type", "") or "")
        item_id = str(directive.get("target_item_id", "") or "")
        if ref_id:
            return f"focus::{ref_type or 'ref'}::{ref_id}"
        if item_id:
            return f"focus::item::{item_id}"
        return ""

    def _build_recall_focus_directive(
        self,
        *,
        node: dict,
        tick_id: str,
        tick_index: int,
        now_ms: int,
        memory_activation_snapshot: dict,
    ) -> dict | None:
        """Pick one target from the memory activation pool and emit a focus directive.

        This is the current MVP implementation of recall action. It can be extended later
        into richer retrieval and planning behavior.
        """
        params = (node.get("params", {}) or {}) if isinstance(node.get("params", {}), dict) else {}
        trigger_kind = str(params.get("trigger_kind", params.get("kind", "")) or "").strip()
        trigger_target_ref = str(
            params.get("target_ref", params.get("anchor_ref", params.get("target_ref_object_id", ""))) or ""
        ).strip()
        anchor_ref_object_type = ""
        anchor_ref_object_id = ""
        if ":" in trigger_target_ref:
            anchor_ref_object_type, anchor_ref_object_id = [x.strip() for x in trigger_target_ref.split(":", 1)]
        else:
            anchor_ref_object_id = trigger_target_ref

        time_basis = str(params.get("time_basis", params.get("time_base", "wallclock")) or "wallclock").strip().lower() or "wallclock"
        if time_basis in {"tick", "ticks"}:
            time_basis = "tick"
        else:
            time_basis = "wallclock"

        target_ts_ms: int | None = None
        target_tick_index: int | None = None
        try:
            if time_basis == "tick":
                iv = None
                if "target_interval_ticks" in params and params.get("target_interval_ticks") not in (None, "", "null"):
                    iv = float(params.get("target_interval_ticks"))
                elif "target_interval_sec" in params and params.get("target_interval_sec") not in (None, "", "null"):
                    iv = float(params.get("target_interval_sec"))
                if iv is not None and float(iv) > 0:
                    iv_int = max(1, int(round(float(iv))))
                    target_tick_index = int(tick_index) - int(iv_int)
            else:
                if "target_interval_sec" in params and params.get("target_interval_sec") not in (None, "", "null"):
                    iv = float(params.get("target_interval_sec"))
                    if iv > 0:
                        target_ts_ms = int(now_ms - iv * 1000.0)
                elif str(params.get("time_bucket_ref_object_id", "") or "").strip():
                    center = self._parse_time_bucket_center_sec(str(params.get("time_bucket_ref_object_id", "") or ""))
                    if center is not None and center > 0:
                        target_ts_ms = int(now_ms - float(center) * 1000.0)
        except Exception:
            target_ts_ms = None
            target_tick_index = None

        require_anchor = bool(trigger_kind == "time_feeling" and anchor_ref_object_type == "st" and anchor_ref_object_id.startswith("st_"))
        item = self._pick_memory_activation_item(
            memory_activation_snapshot,
            now_ms=int(now_ms),
            current_tick_index=int(tick_index),
            target_ts_ms=target_ts_ms,
            target_tick_index=target_tick_index,
            anchor_ref_object_id=anchor_ref_object_id if require_anchor else "",
            require_anchor=bool(require_anchor),
        )
        if not item:
            return None

        # Prefer first structure ref.
        # 优先聚焦到该记忆关联的第一个结构引用。
        structure_id = ""
        display = ""
        refs = list(item.get("structure_ref_items", []) or [])
        if refs:
            structure_id = str(refs[0].get("structure_id", "") or "")
            display = str(refs[0].get("display_text", "") or "")
        if not structure_id:
            structure_refs = list(item.get("structure_refs", []) or [])
            if structure_refs:
                structure_id = str(structure_refs[0])
        if not structure_id:
            return None

        boost = float(self._config.get("recall_focus_boost", 0.65))
        ttl = int(self._config.get("recall_ttl_ticks", 2) or 2)
        strength = self._clamp01(float(params.get("trigger_strength", 0.6) or 0.6))

        reasons = [f"tick:{tick_id}", "action:recall"]
        if target_ts_ms is not None:
            reasons.append(f"bias:time_target_ts:{target_ts_ms}")
        if target_tick_index is not None:
            reasons.append(f"bias:time_target_tick:{target_tick_index}")
        if str(params.get("time_bucket_ref_object_id", "") or ""):
            reasons.append(f"time_bucket:{str(params.get('time_bucket_ref_object_id', '') or '')}")
        if require_anchor and anchor_ref_object_id:
            reasons.append(f"anchor:{anchor_ref_object_id}")

        return {
            "directive_id": f"recall_focus_{structure_id}_{now_ms}",
            "directive_type": "attention_focus",
            "source_kind": "recall",
            "strength": round(strength, 6),
            "focus_boost": round(max(0.0, boost), 6),
            "ttl_ticks": int(max(1, ttl)),
            "target_ref_object_id": structure_id,
            "target_ref_object_type": "st",
            "target_item_id": "",
            "target_display": display or structure_id,
            "created_at": int(now_ms),
            "reasons": reasons,
        }

    def _build_recall_request(
        self,
        *,
        node: dict,
        tick_id: str,
        tick_index: int,
        now_ms: int,
        drive_before: float,
        effective_threshold: float,
        memory_activation_snapshot: dict,
    ) -> dict[str, Any]:
        """Build a structured recall request for the upper layer (Observatory).

        The ActionManager itself should not directly mutate HDB or StatePool.
        The upper layer receives this request and performs recall-related side effects.
        """
        params = (node.get("params", {}) or {}) if isinstance(node.get("params", {}), dict) else {}
        memory_activation_snapshot = memory_activation_snapshot or {}

        trigger_kind = str(params.get("trigger_kind", params.get("kind", "")) or "").strip()
        trigger_target_ref = str(params.get("trigger_target_ref", params.get("trigger_target", "")) or "").strip()
        anchor_ref_object_type = ""
        anchor_ref_object_id = ""
        if ":" in trigger_target_ref:
            anchor_ref_object_type, anchor_ref_object_id = [x.strip() for x in trigger_target_ref.split(":", 1)]
        else:
            anchor_ref_object_id = trigger_target_ref

        # ---- 1) Resolve time target (optional) / 瑙ｆ瀽鏃堕棿鐩爣锛堝彲閫夛級 ----
        time_basis = str(params.get("time_basis", params.get("time_base", "wallclock")) or "wallclock").strip().lower() or "wallclock"
        if time_basis in {"tick", "ticks"}:
            time_basis = "tick"
        else:
            time_basis = "wallclock"

        time_bucket_ref_object_id = str(params.get("time_bucket_ref_object_id", "") or "").strip()
        target_interval_sec: float | None = None
        target_ts_ms: int | None = None
        target_interval_ticks: float | None = None
        target_tick_index: int | None = None
        try:
            if time_basis == "tick":
                # Tick-based recall: use target_interval_ticks if provided.
                if "target_interval_ticks" in params and params.get("target_interval_ticks") not in (None, "", "null"):
                    iv = float(params.get("target_interval_ticks"))
                    if iv > 0:
                        target_interval_ticks = float(iv)
                # Best-effort fallback: allow reusing target_interval_sec field as ticks (caller may pass only one).
                if target_interval_ticks is None and "target_interval_sec" in params and params.get("target_interval_sec") not in (None, "", "null"):
                    iv = float(params.get("target_interval_sec"))
                    if iv > 0:
                        target_interval_ticks = float(iv)
                if target_interval_ticks is not None and float(target_interval_ticks) > 0:
                    # Clamp: at least 1 tick back.
                    iv_int = max(1, int(round(float(target_interval_ticks))))
                    target_interval_ticks = float(iv_int)
                    target_tick_index = int(tick_index) - int(iv_int)
            else:
                if "target_interval_sec" in params and params.get("target_interval_sec") not in (None, "", "null"):
                    iv = float(params.get("target_interval_sec"))
                    if iv > 0:
                        target_interval_sec = float(iv)
                        target_ts_ms = int(now_ms - target_interval_sec * 1000.0)
                elif time_bucket_ref_object_id:
                    center = self._parse_time_bucket_center_sec(time_bucket_ref_object_id)
                    if center is not None and float(center) > 0:
                        target_interval_sec = float(center)
                        target_ts_ms = int(now_ms - float(center) * 1000.0)
        except Exception:
            target_interval_sec = None
            target_ts_ms = None
            target_interval_ticks = None
            target_tick_index = None

        # ---- 2) Pick a memory candidate (competition) / 浠?MAP锛堣蹇嗚祴鑳芥睜锛夋寫涓€涓€欓€夛紙绔炰簤锛?----
        #
        # Theory alignment (4.2.7):
        # - Parameterized recall from time-feeling attributes should only consider memories that contain the anchor.
        # 中文说明：如果是 time_feeling 触发的带锚点回忆，只考虑包含该锚点结构的候选记忆。
        require_anchor = bool(trigger_kind == "time_feeling" and anchor_ref_object_type == "st" and anchor_ref_object_id.startswith("st_"))
        picked = self._pick_memory_activation_item(
            memory_activation_snapshot,
            now_ms=int(now_ms),
            current_tick_index=int(tick_index),
            target_ts_ms=target_ts_ms,
            target_tick_index=target_tick_index,
            anchor_ref_object_id=anchor_ref_object_id if require_anchor else "",
            require_anchor=bool(require_anchor),
        )
        memory_id = str((picked or {}).get("memory_id", (picked or {}).get("id", "")) or "").strip()
        display_text = str((picked or {}).get("display_text", "") or (picked or {}).get("event_summary", "") or "") or memory_id
        try:
            # Prefer episodic memory timestamp if present in MAP snapshot.
            created_at = int((picked or {}).get("memory_created_at", (picked or {}).get("created_at", 0)) or 0)
        except Exception:
            created_at = 0
        try:
            memory_tick_index = int((picked or {}).get("memory_tick_index", 0) or 0)
        except Exception:
            memory_tick_index = 0
        try:
            total_energy = float((picked or {}).get("total_energy", 0.0) or 0.0)
        except Exception:
            total_energy = 0.0

        # Try best-effort structure_id for observability / 灏濊瘯鎻愬彇缁撴瀯 id锛堜究浜庤娴嬶級
        structure_id = ""
        try:
            refs = list((picked or {}).get("structure_ref_items", []) or [])
            if refs:
                structure_id = str((refs[0] or {}).get("structure_id", "") or "")
            if not structure_id:
                srefs = list((picked or {}).get("structure_refs", []) or [])
                if srefs:
                    structure_id = str(srefs[0] or "")
        except Exception:
            structure_id = ""

        # ---- 3) Map Drive consumption to MAP activation delta (MVP) ----
        # 说明：这里只是把当前 recall action 的驱动强度映射到 MAP 的一次赋能增量。
        strength = self._clamp01(float(params.get("trigger_strength", 0.6) or 0.6))
        per_th = float(self._config.get("recall_map_delta_ev_per_threshold", 0.90) or 0.90)
        min_ev = float(self._config.get("recall_map_delta_ev_min", 0.08) or 0.08)
        max_ev = float(self._config.get("recall_map_delta_ev_max", 0.85) or 0.85)
        raw_ev = max(0.0, float(effective_threshold)) * max(0.0, per_th) * max(0.25, float(strength))
        # clamp + round
        delta_ev = 0.0
        if raw_ev > 0.0:
            delta_ev = float(max(min_ev, min(max_ev, raw_ev)))
        delta_ev = round(float(delta_ev), 8)

        mode_tag = str(self._config.get("recall_map_mode_tag", "recall_action") or "recall_action").strip() or "recall_action"

        map_targets: list[dict[str, Any]] = []
        if memory_id and delta_ev > 0.0:
            # Register short-term recall fatigue for diversification (best-effort).
            self._recall_memory_last_picked_tick[str(memory_id)] = int(tick_index)
            map_targets.append(
                {
                    "projection_kind": "memory",
                    "memory_id": memory_id,
                    "backing_structure_id": structure_id,
                    "target_display_text": display_text or memory_id,
                    # Recall is mostly 鈥渧irtual鈥?activation in our current semantics.
                    # 鍘熷瀷璇箟锛氬洖蹇嗕富瑕佹槸鈥滆櫄鑳介噺锛圗V锛夎祴鑳解€濓紝璁╄蹇嗕綔涓哄€欓€夊洖鍒?SP銆?                    "delta_er": 0.0,
                    "delta_ev": float(delta_ev),
                    "sources": [structure_id] if structure_id else [],
                    "modes": [mode_tag],
                }
            )

        # ---- 4) Best-effort rule source info for UI / 灏藉姏鎻愪緵瑙勫垯鏉ユ簮淇℃伅锛堢敤浜庡墠绔樉绀衡€滃洜涓轰粈涔堣鍒欌€濓級 ----
        best_src: dict[str, Any] = {}
        try:
            srcs = [s for s in (node.get("tick_sources", []) or []) if isinstance(s, dict)]
            # Prefer IESM sources that contain rule_id; pick the highest rule_priority.
            scored = []
            for s in srcs:
                try:
                    pri = int(s.get("rule_priority", s.get("priority", 0)) or 0)
                except Exception:
                    pri = 0
                rid = str(s.get("rule_id", "") or "").strip()
                kind = str(s.get("kind", "") or "").strip()
                # IESM sources first; then any kind; then stable.
                is_iesm = 1 if kind.startswith("iesm_") else 0
                scored.append((is_iesm, pri, rid, s))
            if scored:
                scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
                best_src = dict(scored[0][3] or {})
        except Exception:
            best_src = {}

        return {
            "request_id": f"recall_req_{str(node.get('action_id','recall'))}_{tick_id}_{now_ms}",
            "request_kind": "recall_request",
            "created_at": int(now_ms),
            "tick_id": str(tick_id or ""),
            "action_id": str(node.get("action_id", "") or ""),
            "action_kind": "recall",
            "drive_before": round(float(drive_before), 8),
            "effective_threshold": round(float(effective_threshold), 8),
            "trigger_strength": round(float(strength), 6),
            "time_bucket_ref_object_id": time_bucket_ref_object_id,
            "target_interval_sec": None if target_interval_sec is None else round(float(target_interval_sec), 6),
            "target_ts_ms": None if target_ts_ms is None else int(target_ts_ms),
            "target_interval_ticks": None if target_interval_ticks is None else round(float(target_interval_ticks), 6),
            "target_tick_index": None if target_tick_index is None else int(target_tick_index),
            "anchor_ref_object_type": anchor_ref_object_type,
            "anchor_ref_object_id": anchor_ref_object_id,
            "selected_memory": {
                "memory_id": memory_id,
                "display_text": display_text,
                "created_at": int(created_at),
                "tick_id": str((picked or {}).get("memory_tick_id", "") or (picked or {}).get("tick_id", "") or ""),
                "tick_index": int(memory_tick_index),
                "total_energy": round(float(total_energy), 8),
                "structure_id": structure_id,
            },
            "map_targets": map_targets,
            "source": {
                "kind": str(best_src.get("kind", "") or ""),
                "rule_id": str(best_src.get("rule_id", "") or ""),
                "rule_title": str(best_src.get("rule_title", "") or ""),
                "rule_phase": str(best_src.get("rule_phase", "") or ""),
                "rule_priority": int(best_src.get("rule_priority", 0) or 0),
            },
            # Keep a small tail for audit; UI can choose to show/hide.
            # 淇濈暀灏戦噺鏉ユ簮灏惧反鐢ㄤ簬瀹¤锛涘墠绔彲閫夋嫨鎶樺彔鏄剧ず銆?            "tick_sources": [dict(s) for s in (node.get("tick_sources", []) or []) if isinstance(s, dict)][:8],
        }

    def _pick_memory_activation_item(
        self,
        snapshot: dict,
        *,
        now_ms: int,
        current_tick_index: int,
        target_ts_ms: int | None = None,
        target_tick_index: int | None = None,
        anchor_ref_object_id: str = "",
        require_anchor: bool = False,
    ) -> dict | None:
        """Pick one recall candidate from MAP (memory_activation_snapshot).

        Selection considers anchor constraints, recency, energy, and short-term
        recall fatigue. Returns at most one candidate.
        """
        items = list(snapshot.get("items", snapshot.get("memory_items", [])) or []) if isinstance(snapshot, dict) else []
        rows = [it for it in items if isinstance(it, dict)]
        if not rows:
            return None

        anchor_id = str(anchor_ref_object_id or "").strip()
        require_anchor = bool(require_anchor and anchor_id)

        def _has_anchor(it: dict) -> bool:
            if not anchor_id:
                return False
            # Prefer explicit structure_refs (episodic enriched fields).
            try:
                srefs = list(it.get("structure_refs", []) or [])
            except Exception:
                srefs = []
            if anchor_id in [str(x) for x in srefs if str(x)]:
                return True
            # Optional richer refs (if present).
            try:
                sitems = list(it.get("structure_ref_items", []) or [])
            except Exception:
                sitems = []
            for si in sitems:
                if not isinstance(si, dict):
                    continue
                if str(si.get("structure_id", "") or "") == anchor_id:
                    return True
                if str(si.get("ref_object_id", "") or "") == anchor_id and str(si.get("ref_object_type", "") or "").lower() == "st":
                    return True
            return False

        if require_anchor:
            rows = [it for it in rows if _has_anchor(it)]
            if not rows:
                return None

        # Config knobs
        try:
            recency_scale_sec = float(self._config.get("recall_recency_scale_sec", 30.0) or 30.0)
        except Exception:
            recency_scale_sec = 30.0
        recency_scale_sec = max(0.1, min(3600.0, float(recency_scale_sec)))

        try:
            fatigue_window_ticks = int(self._config.get("recall_memory_fatigue_window_ticks", 4) or 4)
        except Exception:
            fatigue_window_ticks = 4
        fatigue_window_ticks = max(0, min(10_000, int(fatigue_window_ticks)))

        try:
            fatigue_penalty = float(self._config.get("recall_memory_fatigue_penalty", 0.60) or 0.60)
        except Exception:
            fatigue_penalty = 0.60
        fatigue_penalty = max(0.0, min(0.95, float(fatigue_penalty)))

        def _parse_int_suffix(text: str) -> int:
            s = str(text or "")
            if not s:
                return 0
            digits = ""
            for ch in reversed(s):
                if ch.isdigit():
                    digits = ch + digits
                elif digits:
                    break
            try:
                return int(digits) if digits else 0
            except Exception:
                return 0

        def _get_memory_id(it: dict) -> str:
            return str(it.get("memory_id", it.get("id", "")) or "").strip()

        def _get_memory_created_at(it: dict) -> int:
            try:
                v = int(it.get("memory_created_at", it.get("created_at", 0)) or 0)
            except Exception:
                v = 0
            return int(v)

        def _get_memory_fresh_at(it: dict) -> int:
            """A freshness timestamp used for recency bias.

            Prefer MAP last_updated_at when available, because it better reflects
            recent activation or re-contact.
            """
            try:
                upd_ts = int(it.get("last_updated_at", 0) or 0)
            except Exception:
                upd_ts = 0
            try:
                mem_ts = int(it.get("memory_created_at", it.get("created_at", 0)) or 0)
            except Exception:
                mem_ts = 0
            return int(max(int(mem_ts), int(upd_ts)))

        def _get_memory_tick_index(it: dict) -> int:
            try:
                v = int(it.get("memory_tick_index", 0) or 0)
            except Exception:
                v = 0
            if v > 0:
                return int(v)
            tid = str(it.get("memory_tick_id", it.get("tick_id", "")) or "")
            return int(_parse_int_suffix(tid))

        def _target_score(it: dict) -> float:
            # Tick target has higher precedence when provided.
            if target_tick_index is not None:
                mem_tick = _get_memory_tick_index(it)
                if mem_tick > 0:
                    dist = abs(int(mem_tick) - int(target_tick_index))
                    interval = abs(int(current_tick_index) - int(target_tick_index))
                    interval = max(1, int(interval))
                    ratio = float(dist) / float(interval)
                    return float(math.exp(-ratio))
                return 0.0

            if target_ts_ms is not None:
                mem_ts = _get_memory_created_at(it)
                if mem_ts > 0:
                    dist_sec = abs(int(mem_ts) - int(target_ts_ms)) / 1000.0
                    interval_sec = abs(int(now_ms) - int(target_ts_ms)) / 1000.0
                    interval_sec = max(1.0, float(interval_sec))
                    ratio = float(dist_sec) / float(interval_sec)
                    return float(math.exp(-ratio))
                return 0.0

            return 0.0

        def _recency_score(it: dict) -> float:
            fresh_ts = _get_memory_fresh_at(it)
            if fresh_ts <= 0:
                return 0.0
            age_sec = max(0.0, float(int(now_ms) - int(fresh_ts)) / 1000.0)
            return float(math.exp(-age_sec / float(recency_scale_sec)))

        def _energy_term(it: dict) -> float:
            try:
                e = float(it.get("total_energy", 0.0) or 0.0)
            except Exception:
                e = 0.0
            e = max(0.0, float(e))
            # log1p keeps this term bounded and less dominant than time/recency.
            return float(math.log1p(e))

        best: dict | None = None
        best_key: tuple[float, float, float, int, str] | None = None

        for it in rows:
            memory_id = _get_memory_id(it)
            if not memory_id:
                continue

            tscore = _target_score(it)
            rscore = _recency_score(it)
            eterm = _energy_term(it)

            # Weighted score (MVP): time target > recency > energy.
            score = 1.20 * float(tscore) + 0.55 * float(rscore) + 0.15 * float(eterm)

            # Short-term fatigue (diversification): penalize recently picked memories.
            if fatigue_window_ticks > 0:
                last_picked = self._recall_memory_last_picked_tick.get(str(memory_id))
                if last_picked is not None:
                    try:
                        if int(current_tick_index) - int(last_picked) <= int(fatigue_window_ticks):
                            score *= max(0.0, 1.0 - float(fatigue_penalty))
                    except Exception:
                        pass

            mem_created_at = _get_memory_created_at(it)
            try:
                te = float(it.get("total_energy", 0.0) or 0.0)
            except Exception:
                te = 0.0

            # Sort key: score desc, then energy desc, then recency desc.
            key = (float(score), float(te), float(rscore), int(mem_created_at), str(memory_id))
            if best_key is None or key > best_key:
                best_key = key
                best = it

        return best

    @staticmethod
    def _parse_time_bucket_center_sec(ref_object_id: str) -> float | None:
        """Parse time bucket center seconds from a StatePool time bucket ref id.

        Example: "sa_time_bucket_37_5s" -> 37.5
        """
        s = str(ref_object_id or "").strip()
        if not s:
            return None
        # strip common prefix
        for p in ("sa_time_bucket_", "time_bucket_", "sa_time_", "tb_"):
            if s.startswith(p):
                s = s[len(p):]
                break
        # strip suffix
        if s.endswith("s"):
            s = s[:-1]
        if not s:
            return None
        # "0_25" -> "0.25"
        # NOTE: bucket ids may contain multiple "_" (e.g. "3_25"); join as a single decimal is safe for our presets.
        if "_" in s and s.count("_") >= 1:
            parts = s.split("_")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                s2 = f"{parts[0]}.{parts[1]}"
            else:
                # fallback: treat last "_" as decimal point, keep others
                head = "_".join(parts[:-1])
                tail = parts[-1]
                s2 = f"{head}.{tail}".replace("_", "")
            s = s2
        try:
            return float(s)
        except Exception:
            return None

    # ================================================================== #
    # Helpers / 宸ュ叿鍑芥暟                                                   #
    # ================================================================== #

    def _build_config(self, config_override: dict | None) -> dict:
        cfg = dict(_DEFAULT_CONFIG)
        cfg.update(_load_yaml_config(self._config_path))
        if config_override:
            cfg.update(config_override)
        return cfg

    @staticmethod
    def _merge_modulation(left: dict, right: dict) -> dict:
        if not isinstance(left, dict):
            left = {}
        if not isinstance(right, dict):
            return dict(left)
        merged = dict(left)
        for k, v in right.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = ActionManager._merge_modulation(dict(merged.get(k)), v)
            else:
                merged[k] = v
        return merged

    @staticmethod
    def _dedup_focus_directives(items: list[dict]) -> list[dict]:
        """Deduplicate directives by directive_id, then by target, keeping the last one."""
        by_id: dict[str, dict] = {}
        for d in items:
            if not isinstance(d, dict):
                continue
            did = str(d.get("directive_id", "") or "")
            if not did:
                continue
            by_id[did] = d
        deduped = list(by_id.values())

        by_target: dict[str, dict] = {}
        for d in deduped:
            key = str(d.get("target_ref_object_id", "") or "") or str(d.get("target_item_id", "") or "")
            if not key:
                continue
            by_target[key] = d
        return list(by_target.values())

    @staticmethod
    def _best_global_signal_strength(cfs_signals: list[dict], *, kind: str) -> float:
        best = 0.0
        for sig in cfs_signals:
            if not isinstance(sig, dict):
                continue
            if str(sig.get("scope", "")) != "global":
                continue
            if str(sig.get("kind", "")) != str(kind):
                continue
            best = max(best, float(sig.get("strength", 0.0) or 0.0))
        return best

    @staticmethod
    def _clamp01(v: float) -> float:
        try:
            x = float(v)
        except (TypeError, ValueError):
            return 0.0
        if x < 0.0:
            return 0.0
        if x > 1.0:
            return 1.0
        return x

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
        error: dict | None = None,
        trace_id: str = "",
        tick_id: str = "",
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
                "version": __version__,
                "schema_version": __schema_version__,
                "trace_id": trace_id,
                "tick_id": tick_id,
                "elapsed_ms": int(elapsed_ms),
            },
        }

    # ================================================================== #
    # reload / snapshot                                                   #
    # ================================================================== #

    def stop_actions(
        self,
        *,
        trace_id: str,
        mode: str,
        value: Any = None,
        hold_ticks: int = 2,
        reason: str = "manual_stop",
    ) -> dict:
        """Stop or cancel action nodes.

        In the current prototype, most actions are short-lived products such as
        focus directives or modulation outputs. Stopping mainly clears drive and
        prevents execution for a short hold window.
        """
        mode = str(mode or "").strip().lower() or "action_id"
        hold_ticks = max(0, min(10_000, int(hold_ticks or 0)))
        tick_number = int(self._tick_counter)

        # Normalize value to a set of strings / 褰掍竴鍖?value 涓?set[str]
        values: set[str] = set()
        if isinstance(value, str) and value.strip():
            values.add(value.strip())
        elif isinstance(value, list):
            for it in value:
                s = str(it or "").strip()
                if s:
                    values.add(s)

        stopped_ids: list[str] = []
        now_ms = int(time.time() * 1000)

        if mode not in {"action_id", "action_kind", "all"}:
            return self._make_response(
                False,
                "INPUT_VALIDATION_ERROR",
                f"Unknown stop mode: {mode}",
                data={"supported_modes": ["action_id", "action_kind", "all"]},
                trace_id=trace_id,
                tick_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        for action_id, node in list(self._nodes.items()):
            if not isinstance(node, dict):
                continue

            if mode == "all":
                matched = True
            elif mode == "action_kind":
                matched = (str(node.get("action_kind", "") or "").strip() in values) if values else False
            else:
                matched = (str(action_id or "").strip() in values) if values else False

            if not matched:
                continue

            node["drive"] = 0.0
            node["tick_gain_total"] = 0.0
            node["tick_gain_by_source_kind"] = {}
            node["tick_sources"] = []
            node["last_stop_tick"] = tick_number
            node["stop_until_tick"] = tick_number + int(hold_ticks)
            node["last_stop_reason"] = str(reason or "manual_stop")
            node["last_stop_at_ms"] = int(now_ms)
            stopped_ids.append(str(action_id))

        stopped_ids = sorted(list(dict.fromkeys([s for s in stopped_ids if s])))
        self._logger.brief(
            trace_id=trace_id,
            tick_id=trace_id,
            interface="stop_actions",
            success=True,
            message="琛屽姩鑺傜偣宸插仠姝?/ action nodes stopped",
            input_summary={"mode": mode, "value_count": len(values), "hold_ticks": hold_ticks},
            output_summary={"stopped_count": len(stopped_ids)},
        )

        return self._make_response(
            True,
            "OK",
            "琛屽姩鑺傜偣宸插仠姝?/ action nodes stopped",
            data={
                "mode": mode,
                "values": sorted(list(values)),
                "hold_ticks": int(hold_ticks),
                "reason": str(reason or ""),
                "tick_counter": tick_number,
                "stopped_count": len(stopped_ids),
                "stopped_action_ids": stopped_ids,
            },
            trace_id=trace_id,
            tick_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    def get_runtime_snapshot(self, *, trace_id: str = "action_runtime") -> dict:
        start_time = time.time()

        # Provide a detailed node snapshot for real-time observability.
        # 提供更完整的行动节点快照，便于前端查看行动器/行动接口运行态。
        nodes = list(self._nodes.values())
        nodes.sort(key=lambda n: float(n.get("drive", 0.0) or 0.0), reverse=True)
        nodes_snapshot = [
            {
                "action_id": str(n.get("action_id", "") or ""),
                "action_kind": str(n.get("action_kind", "") or ""),
                "drive": round(float(n.get("drive", 0.0) or 0.0), 8),
                "base_threshold": round(float(n.get("base_threshold", n.get("threshold", 0.0) or 0.0) or 0.0), 8),
                "threshold_scale": round(float(n.get("threshold_scale", 1.0) or 1.0), 8),
                "effective_threshold": round(float(n.get("effective_threshold", n.get("threshold", 0.0) or 0.0) or 0.0), 8),
                "threshold_components": dict(n.get("threshold_components", {}) or {}) if isinstance(n.get("threshold_components", {}), dict) else {},
                "target_ref_object_id": str(n.get("target_ref_object_id", "") or ""),
                "target_ref_object_type": str(n.get("target_ref_object_type", "") or ""),
                "target_item_id": str(n.get("target_item_id", "") or ""),
                "target_display": str(n.get("target_display", "") or ""),
                "params": dict(n.get("params", {}) or {}) if isinstance(n.get("params", {}), dict) else {},
                "target_binding_strategy": str(n.get("target_binding_strategy", "") or ""),
                "target_binding_requested_from": str(n.get("target_binding_requested_from", "") or ""),
                "target_binding_applied": bool(n.get("target_binding_applied", False)),
                "target_binding_reason": str(n.get("target_binding_reason", "") or ""),
                "target_binding_match_source": str(n.get("target_binding_match_source", "") or ""),
                "target_binding_match_ref_object_id": str(n.get("target_binding_match_ref_object_id", "") or ""),
                "target_binding_match_ref_object_type": str(n.get("target_binding_match_ref_object_type", "") or ""),
                "target_binding_match_item_id": str(n.get("target_binding_match_item_id", "") or ""),
                "target_binding_match_display": str(n.get("target_binding_match_display", "") or ""),
                "local_drive_modulation": dict(n.get("last_local_drive_modulation", {}) or {}) if isinstance(n.get("last_local_drive_modulation", {}), dict) else {},
                "fatigue": round(float(n.get("fatigue", 0.0) or 0.0), 8),
                "cooldown_ticks": int(n.get("cooldown_ticks", 0) or 0),
                "last_attempt_tick": int(n.get("last_attempt_tick", -1) or -1),
                "last_trigger_tick": int(n.get("last_trigger_tick", -1) or -1),
                "last_update_tick": int(n.get("last_update_tick", -1) or -1),
                "tick_gain_total": round(float(n.get("tick_gain_total", 0.0) or 0.0), 8),
                "tick_gain_raw_total": round(float(n.get("tick_gain_raw_total", 0.0) or 0.0), 8),
                "tick_gain_by_source_kind": dict(n.get("tick_gain_by_source_kind", {}) or {}) if isinstance(n.get("tick_gain_by_source_kind", {}), dict) else {},
                "trigger_sources": list(n.get("trigger_sources", []) or [])[:8],
                "tick_sources": list(n.get("tick_sources", []) or [])[:8],
                "last_stop_tick": int(n.get("last_stop_tick", -1) or -1),
                "stop_until_tick": int(n.get("stop_until_tick", -1) or -1),
                "last_stop_reason": str(n.get("last_stop_reason", "") or ""),
                "created_at": int(n.get("created_at", 0) or 0),
            }
            for n in nodes[:64]
        ]
        return self._make_response(
            True,
            "OK",
            "琛屽姩妯″潡杩愯鎬佸揩鐓?/ action runtime snapshot",
            data={
                "module": __module_name__,
                "version": __version__,
                "schema_version": __schema_version__,
                "config_summary": dict(self._config),
                "executors_registry": list(self._executor_registry),
                "stats": {
                    "tick_counter": int(self._tick_counter),
                    "node_count": len(self._nodes),
                    "executed_history_count": len(self._executed_history),
                },
                "action_learning_summary": self._build_action_learning_summary(nodes),
                "nodes": nodes_snapshot,
                "recent_executed_actions": list(self._executed_history)[-80:],
                "stop_interface": {
                    "supported_modes": ["action_id", "action_kind", "all"],
                    "default_hold_ticks": 2,
                },
            },
            trace_id=trace_id,
            tick_id=trace_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    def reload_config(self, *, trace_id: str, config_path: str | None = None, apply_partial: bool = True) -> dict:
        start_time = time.time()
        path = config_path or self._config_path
        try:
            new_raw = _load_yaml_config(path)
            if not new_raw:
                return self._make_response(False, "CONFIG_ERROR", f"Config empty: {path}", trace_id=trace_id, tick_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))
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
                return self._make_response(False, "CONFIG_ERROR", "Some items rejected", data={"applied": applied, "rejected": rejected}, trace_id=trace_id, tick_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))
            return self._make_response(True, "OK", "hot reload done", data={"applied": applied, "rejected": rejected}, trace_id=trace_id, tick_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))
        except Exception as exc:
            self._logger.error(
                trace_id=trace_id,
                tick_id=trace_id,
                interface="reload_config",
                code="CONFIG_ERROR",
                message=str(exc),
                detail={"traceback": traceback.format_exc()},
            )
            return self._make_response(False, "CONFIG_ERROR", f"Hot reload failed: {exc}", trace_id=trace_id, tick_id=trace_id, elapsed_ms=self._elapsed_ms(start_time))

