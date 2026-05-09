# -*- coding: utf-8 -*-
"""
AP 情绪递质模块（情绪管理器 EMgr / 递质通道 NT）— 主模块
=====================================================

语义要点（对齐理论 3.9 / 3.12 Step 8）：
  - EMgr 维护 NT（递质通道）慢变量：可衰减、可上下限约束、可审计。
  - EMgr 不替代结构认知与查存一体；它输出“调制量”，影响下一 tick 的注意力/学习/行动风格。
  - 原型阶段先保证闭环可跑：接入 CFS 信号，更新 NT，并把对注意力的调制真实生效（高收益）。

术语与缩写 / Glossary
--------------------
  - 情绪管理器（EMgr, Emotion Manager）
  - 递质通道（NT, NeuroTransmitter channels）
  - 认知感受信号（CFS, Cognitive Feeling Signals）
  - 注意力过滤器（AF, Attention Filter）
  - 当前注意记忆体（CAM, Current Attention Memory）
"""

from __future__ import annotations

import os
import math
import time
import traceback
from typing import Any

from . import __module_name__, __schema_version__, __version__
from ._logger import ModuleLogger


_NT_CHANNEL_LABELS: dict[str, str] = {
    # 原型阶段先用典型缩写，UI/日志需同时给中文全称，避免只看到简写。
    "DA": "多巴胺（DA）",
    "ADR": "肾上腺素（ADR）",
    "OXY": "催产素（OXY）",
    "SER": "血清素（SER）",
    "END": "内啡肽（END）",
    "COR": "皮质醇（COR）",
    "NOV": "新颖探索（NOV）",
    "FOC": "专注锁定（FOC）",
}

# NT 通道说明（中文优先，便于前端展示与验收）
# 注：这不是“生物真实性”宣称，而是对齐理论核心的“功能性调制变量”口径。
_NT_CHANNEL_META: dict[str, dict[str, str]] = {
    "DA": {
        "name_zh": "多巴胺（DA）",
        "desc_zh": "奖励驱动：期待增强、奖励验证、正确事件带来的正反馈。常用于降低行动阈值、提高探索与巩固倾向。",
    },
    "ADR": {
        "name_zh": "肾上腺素（ADR）",
        "desc_zh": "警觉唤醒：惊增强、强意外输入、风险线索上升、压力增加。常用于提高注意力预算与切换速度。",
    },
    "OXY": {
        "name_zh": "催产素（OXY）",
        "desc_zh": "亲和连接：正确事件、社交正反馈、信任建立。常用于降低结构间能量转移损耗、提升相关召回与更温和的表达倾向。",
    },
    "SER": {
        "name_zh": "血清素（SER）",
        "desc_zh": "稳定满足：长期低冲突、总体平稳。常用于降低情绪放大系数、提高耐心与一致性，并抑制无谓探索。",
    },
    "END": {
        "name_zh": "内啡肽（END）",
        "desc_zh": "止痛舒缓：痛苦缓冲与恢复通道。常用于削弱惩罚尖峰的冲击、减少过度核对，并推动恢复/整理倾向。",
    },
    "COR": {
        "name_zh": "皮质醇（COR）",
        "desc_zh": "长期警戒：违和长期偏高、未知环境高频。常用于提高保守性与压力通道敏感度。",
    },
    "NOV": {
        "name_zh": "新颖探索（NOV）",
        "desc_zh": "新颖探索：用于表示系统当前对新线索、意外变化与未证实预测的探索倾向。主要影响新信息优先级、近因偏置与发散扩展强度。",
    },
    "FOC": {
        "name_zh": "专注锁定（FOC）",
        "desc_zh": "专注锁定：用于表示系统当前对单一目标或局部路径的持续聚焦倾向。主要影响注意力收窄、聚焦增益、传播收束与执行果断性。",
    },
}


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
    "enabled": True,
    # soft cap / 软上限极限算法（无限逼近上限但不达到）
    "soft_cap_enabled": True,
    "soft_cap_eps": 1e-6,
    "soft_cap_k_default": 0.35,
    "nt_channels": {
        # base: baseline / 基线值（衰减回归到 base，而不是回归到 0）
        # soft_cap_k: per-channel soft cap strength / 每通道软上限强度参数（可选覆盖默认）
        "DA": {"min": 0.0, "max": 1.0, "decay_ratio": 0.91, "base": 0.12, "soft_cap_k": 0.35},
        "ADR": {"min": 0.0, "max": 1.0, "decay_ratio": 0.85, "base": 0.05, "soft_cap_k": 0.35},
        "OXY": {"min": 0.0, "max": 1.0, "decay_ratio": 0.93, "base": 0.12, "soft_cap_k": 0.35},
        "SER": {"min": 0.0, "max": 1.0, "decay_ratio": 0.94, "base": 0.18, "soft_cap_k": 0.35},
        "END": {"min": 0.0, "max": 1.0, "decay_ratio": 0.91, "base": 0.10, "soft_cap_k": 0.35},
        "COR": {"min": 0.0, "max": 1.0, "decay_ratio": 0.86, "base": 0.06, "soft_cap_k": 0.35},
        "NOV": {"min": 0.0, "max": 1.0, "decay_ratio": 0.89, "base": 0.08, "soft_cap_k": 0.33},
        "FOC": {"min": 0.0, "max": 1.0, "decay_ratio": 0.92, "base": 0.10, "soft_cap_k": 0.34},
    },
    "global_decay_ratio": 0.92,
    # cfs_to_nt_source_mode / CFS -> NT 来源模式
    # - builtin: 仅使用本配置里的 cfs_to_nt_gains（旧口径/回退）
    # - iesm_rules: 默认使用 IESM emotion_update 外显驱动（新口径）
    # - hybrid: 两者同时启用（调试/过渡）
    "cfs_to_nt_source_mode": "iesm_rules",
    "cfs_to_nt_gains": {
        "dissonance": {"COR": 0.09, "ADR": 0.03, "FOC": 0.02},
        "correct_event": {"DA": 0.12, "OXY": 0.08, "SER": 0.05, "FOC": 0.03},
        "surprise": {"ADR": 0.07, "NOV": 0.10, "COR": 0.015, "FOC": -0.02},
        "expectation": {"DA": 0.06, "NOV": 0.025},
        "pressure": {"COR": 0.11, "END": 0.04, "ADR": 0.04, "FOC": 0.06, "NOV": -0.02},
        # Verification states (continuous, non-binary) / 验证态（连续渐变，非二极管）
        "expectation_verified": {"DA": 0.09, "SER": 0.04, "OXY": 0.03, "FOC": 0.03},
        "expectation_unverified": {"COR": 0.04, "ADR": 0.02, "NOV": 0.05, "SER": -0.015},
        "pressure_verified": {"COR": 0.07, "ADR": 0.04, "END": 0.03, "FOC": 0.04},
        "pressure_unverified": {"END": 0.05, "COR": -0.02, "SER": 0.02, "NOV": 0.03, "FOC": -0.015},
        "complexity": {"ADR": 0.015, "FOC": 0.04, "COR": 0.015, "NOV": 0.02},
        "repetition": {"COR": 0.02, "SER": -0.015, "NOV": -0.05, "END": 0.025},
        "grasp": {"SER": 0.05, "FOC": 0.08, "COR": -0.02, "NOV": -0.015},
        "simplicity": {"SER": 0.04, "END": 0.035, "DA": 0.02, "COR": -0.02, "ADR": -0.015},
        "relief": {"END": 0.07, "SER": 0.045, "OXY": 0.025, "COR": -0.04, "ADR": -0.025, "FOC": -0.01},
        "reassurance": {"SER": 0.06, "OXY": 0.05, "END": 0.03, "DA": 0.025, "FOC": 0.02, "COR": -0.035, "ADR": -0.02},
    },
    "cfs_to_rwd_pun": {
        "correct_event": {"rwd": 1.0, "pun": 0.0},
        "pressure": {"rwd": 0.0, "pun": 0.8},
        "dissonance": {"rwd": 0.0, "pun": 0.3},
        "simplicity": {"rwd": 0.15, "pun": 0.0},
        "relief": {"rwd": 0.08, "pun": 0.0},
        "reassurance": {"rwd": 0.12, "pun": 0.0},
    },
    # rwd_pun_source_mode / 奖励-惩罚信号（Rwd/Pun）来源模式
    # 说明：
    # - "pool"（推荐）：从状态池对象的“绑定属性 + EV/ER 关系”自然汇总（对齐理论 3.8.2/3.9）
    # - "cfs"（过渡/对照）：从 CFS(kind) 做硬映射汇总（cfs_to_rwd_pun）
    #
    # 注意：EMgr 本身不直接读取 StatePool；若使用 "pool"，需要上层（Observatory）把 rwd_pun_override 传入。
    "rwd_pun_source_mode": "pool",
    # rwd_pun_pool_aggregation / pool 汇总参数（由上层计算时使用，EMgr 只透传/展示）
    "rwd_pun_pool_aggregation": {
        "reward_attr_name": "reward_signal",
        "punish_attr_name": "punish_signal",
        "ev_min": 0.0,
        # When runtime-bound reward/punish attributes carry a numeric value,
        # use that value as the per-row weighting factor instead of presence=1.
        "attribute_value_weight_enabled": True,
        "attribute_value_fallback": 1.0,
        # softcap parameters / 软饱和参数
        "k_pred": 1.0,
        "k_got": 0.5,
        # blend weights / 混合权重（归一化后使用）
        "w_pred": 0.7,
        "w_got": 0.3,
    },
    # rwd_pun_to_nt_gains / Rwd/Pun -> NT gains
    # 对齐理论 3.9.3：reward_signal 获得 ER（现实验证）应推动 DA 等通道变化；
    # pun 同理推动 COR/ADR 等“警戒/唤醒”通道变化。
    # rwd_pun_to_nt_source_mode / Rwd/Pun -> NT 来源模式
    # - builtin: 仅使用本配置里的 rwd_pun_to_nt_gains（旧口径/回退）
    # - iesm_rules: 默认使用 IESM emotion_post 规则外显驱动（新口径）
    # - hybrid: 两者同时启用（调试/过渡）
    "rwd_pun_to_nt_source_mode": "iesm_rules",
    "rwd_pun_to_nt_gains": {
        "rwd": {"DA": 0.09, "OXY": 0.04, "SER": 0.03, "FOC": 0.02, "NOV": 0.01},
        "pun": {"COR": 0.08, "ADR": 0.04, "END": 0.05, "FOC": 0.02, "NOV": -0.02, "OXY": -0.01},
    },
    "modulation": {
        "attention": {
            "base_top_n": 16,
            "adr_topn_gain": 6,
            "cor_topn_suppress": 2,
            "base_priority_weight_cp_abs": 0.35,
            "cor_cp_weight_gain": 0.20,
            "ser_cp_weight_suppress": 0.10,
            "base_priority_weight_fatigue": 0.00,
            "cor_fatigue_weight_gain": 0.25,
            "base_min_total_energy": 0.0,
            "field_specs": {
                "top_n": {
                    "base": 16,
                    "min": 4,
                    "max": 64,
                    "round_to_int": True,
                    "adr_gain": 5.5,
                    "nov_gain": 4.0,
                    "da_gain": 1.0,
                    "cor_suppress": 3.0,
                    "ser_suppress": 1.2,
                    "foc_suppress": 4.0,
                },
                "min_cam_items": {
                    "base": 2,
                    "min": 1,
                    "max": 12,
                    "round_to_int": True,
                    "adr_gain": 1.0,
                    "nov_gain": 1.0,
                    "foc_suppress": 1.0,
                },
                "priority_weight_total_energy": {
                    "base": 1.25,
                    "min": 0.0,
                    "max": 4.0,
                    "foc_gain": 0.55,
                    "oxy_gain": 0.25,
                    "cor_gain": 0.18,
                    "da_gain": 0.10,
                    "nov_suppress": 0.18,
                },
                "priority_weight_cp_abs": {
                    "base": 0.35,
                    "min": 0.0,
                    "max": 2.0,
                    "cor_gain": 0.28,
                    "adr_gain": 0.10,
                    "foc_gain": 0.08,
                    "ser_suppress": 0.12,
                    "end_suppress": 0.08,
                    "oxy_suppress": 0.04,
                },
                "priority_weight_salience": {
                    "base": 0.15,
                    "min": 0.0,
                    "max": 2.0,
                    "adr_gain": 0.32,
                    "nov_gain": 0.24,
                    "cor_gain": 0.06,
                    "ser_suppress": 0.05,
                },
                "priority_weight_fatigue": {
                    "base": 0.0,
                    "min": 0.0,
                    "max": 2.0,
                    "cor_gain": 0.25,
                    "ser_gain": 0.06,
                    "end_suppress": 0.16,
                    "da_suppress": 0.05,
                },
                "priority_weight_recency_gain": {
                    "base": 0.0,
                    "min": 0.0,
                    "max": 2.0,
                    "nov_gain": 0.40,
                    "da_gain": 0.14,
                    "adr_gain": 0.08,
                    "ser_suppress": 0.10,
                    "foc_suppress": 0.12,
                    "cor_suppress": 0.08,
                },
                "focus_boost_weight": {
                    "base": 1.0,
                    "min": 0.0,
                    "max": 4.0,
                    "foc_gain": 0.65,
                    "adr_gain": 0.22,
                    "oxy_gain": 0.18,
                    "ser_suppress": 0.06,
                },
                "attention_energy_budget": {
                    "base": 8.0,
                    "min": 0.0,
                    "max": 26.0,
                    "adr_gain": 6.5,
                    "foc_gain": 3.0,
                    "nov_gain": 3.0,
                    "da_gain": 2.2,
                    "oxy_gain": 1.4,
                    "cor_suppress": 2.4,
                    "ser_suppress": 2.0,
                    "end_suppress": 1.25,
                },
                "min_total_energy": {
                    "base": 0.0,
                    "min": 0.0,
                    "max": 1.0,
                    "cor_gain": 0.18,
                    "foc_gain": 0.08,
                    "end_suppress": 0.08,
                    "oxy_suppress": 0.05,
                },
                "keep_score_ratio_base": {
                    "base": 0.28,
                    "min": 0.12,
                    "max": 0.85,
                    "foc_gain": 0.14,
                    "cor_gain": 0.10,
                    "ser_gain": 0.08,
                    "nov_suppress": 0.10,
                    "adr_suppress": 0.04,
                },
                "keep_score_ratio_concentration_gain": {
                    "base": 0.22,
                    "min": 0.0,
                    "max": 0.6,
                    "foc_gain": 0.08,
                    "cor_gain": 0.05,
                    "nov_suppress": 0.05,
                },
                "keep_score_ratio_min": {
                    "base": 0.18,
                    "min": 0.05,
                    "max": 0.6,
                    "foc_gain": 0.04,
                    "nov_suppress": 0.03,
                },
                "keep_score_ratio_max": {
                    "base": 0.72,
                    "min": 0.3,
                    "max": 0.95,
                    "foc_gain": 0.08,
                    "ser_gain": 0.05,
                    "nov_suppress": 0.05,
                },
            },
        },
        # HDB modulation output (scales) / HDB 调制输出（缩放系数）
        # 上层（Observatory）会在下一 tick 把 scale 应用到 HDB 配置：
        #   effective_value = base_value * scale
        "hdb": {
            "clamp_min": 0.40,
            "clamp_max": 2.50,
            "scales": {
                "base_weight_er_gain": {
                    "base": 1.00,
                    "da_gain": 0.85,
                    "oxy_gain": 0.35,
                    "foc_gain": 0.18,
                    "cor_suppress": 0.35,
                    "ser_suppress": 0.18,
                    "end_suppress": 0.08,
                },
                "base_weight_ev_wear": {
                    "base": 1.00,
                    "cor_gain": 0.75,
                    "foc_gain": 0.18,
                    "ser_gain": 0.12,
                    "da_suppress": 0.18,
                    "oxy_suppress": 0.12,
                    "nov_suppress": 0.08,
                },
                "ev_propagation_ratio": {
                    "base": 1.00,
                    "da_gain": 0.45,
                    "adr_gain": 0.30,
                    "oxy_gain": 0.40,
                    "nov_gain": 0.45,
                    "cor_suppress": 0.35,
                    "ser_suppress": 0.20,
                    "foc_suppress": 0.35,
                },
                "ev_propagation_threshold": {
                    "base": 1.00,
                    "cor_gain": 0.55,
                    "foc_gain": 0.45,
                    "ser_gain": 0.18,
                    "da_suppress": 0.25,
                    "oxy_suppress": 0.22,
                    "nov_suppress": 0.30,
                },
                "er_induction_ratio": {
                    "base": 1.00,
                    "adr_gain": 0.40,
                    "da_gain": 0.18,
                    "oxy_gain": 0.28,
                    "foc_gain": 0.22,
                    "cor_suppress": 0.15,
                },
            },
        },
    },
    "log_dir": "",
    "log_max_file_bytes": 5 * 1024 * 1024,
    "stdout_fallback_when_log_fail": True,
}


class EmotionManager:
    """
    情绪管理器（EMgr）主类。

    接口与占位接口保持兼容：
      - update_emotion_state(state_data)
      - get_emotion_snapshot()
    """

    def __init__(self, config_path: str = "", config_override: dict | None = None):
        self._config_path = config_path or os.path.join(os.path.dirname(__file__), "config", "emotion_config.yaml")
        self._config = self._build_config(config_override)
        self._logger = ModuleLogger(
            log_dir=self._config.get("log_dir", ""),
            max_file_bytes=int(self._config.get("log_max_file_bytes", 5 * 1024 * 1024)),
            enable_stdout_fallback=bool(self._config.get("stdout_fallback_when_log_fail", True)),
        )
        self._total_calls = 0
        self._nt_state: dict[str, float] = {}
        self._last_updated_at_ms = 0
        self._last_tick_id = ""

        self._ensure_channels_initialized()

    def close(self) -> None:
        self._logger.close()

    # ================================================================== #
    # 接口一：update_emotion_state                                       #
    # ================================================================== #

    def update_emotion_state(self, state_data: dict, trace_id: str = "", tick_id: str | None = None) -> dict:
        start_time = time.time()
        self._total_calls += 1

        if not isinstance(state_data, dict):
            return self._make_response(
                success=False,
                code="INPUT_VALIDATION_ERROR",
                message="state_data 必须是 dict / state_data must be dict",
                error={"code": "state_data_type_error"},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        if not self._config.get("enabled", True):
            snapshot = self._build_snapshot()
            return self._make_response(
                success=True,
                code="OK_DISABLED",
                message="情绪递质管理器（EMgr/NT）已禁用 / Emotion manager disabled",
                data={
                    "nt_state_snapshot": snapshot,
                    "nt_channel_labels": dict(_NT_CHANNEL_LABELS),
                    "modulation": {},
                    "rwd_pun_snapshot": {"rwd": 0.0, "pun": 0.0},
                    "audit": {"disabled": True},
                },
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        tick_id = tick_id or str(state_data.get("tick_id") or trace_id or "")
        cfs_signals = list(state_data.get("cfs_signals", [])) if isinstance(state_data.get("cfs_signals", []), list) else []
        script_updates = state_data.get("emotion_updates") or {}

        before = dict(self._nt_state)

        # 1) 衰减
        decay_report = self._apply_decay()

        # 2) 奖惩汇总（Rwd/Pun）+ NT 映射
        # Reward/Punish（Rwd/Pun）/ 奖励-惩罚信号汇总
        # ------------------------------------------------
        # 理论口径：更推荐由“对象级 reward_signal/punish_signal + EV/ER 关系”自然汇总出来，
        # 而不是仅依赖 CFS(kind) 做硬映射。
        #
        # 工程约束：EMgr 不持有 StatePool，因此当 rwd_pun_source_mode="pool" 时，
        # 需要上层传入 rwd_pun_override（Observatory 会在 IESM/TimeSensor 写入属性后计算）。
        rwd_pun_mode = str(self._config.get("rwd_pun_source_mode", "pool") or "pool").strip().lower() or "pool"
        override = state_data.get("rwd_pun_override")
        if rwd_pun_mode in {"pool", "pool_items", "pool_pred"} and isinstance(override, dict):
            rwd_pun = {
                "rwd": round(max(0.0, float(override.get("rwd", 0.0) or 0.0)), 8),
                "pun": round(max(0.0, float(override.get("pun", 0.0) or 0.0)), 8),
            }
            rwd_pun_source = str(override.get("source", "") or "pool_override")
            rwd_pun_detail = dict(override.get("detail", {}) or {}) if isinstance(override.get("detail", {}), dict) else {}
        else:
            rwd_pun = self._compute_rwd_pun_from_cfs(cfs_signals)
            rwd_pun_source = "cfs_mapping"
            rwd_pun_detail = {}

        # 3) 基于 CFS 的增量
        cfs_to_nt_source_mode = str(self._config.get("cfs_to_nt_source_mode", "iesm_rules") or "iesm_rules").strip().lower() or "iesm_rules"
        if cfs_to_nt_source_mode in {"builtin", "config", "legacy", "hybrid", "both"}:
            nt_deltas_from_cfs = self._compute_deltas_from_cfs(cfs_signals)
        else:
            nt_deltas_from_cfs = {}

        # 4) 基于 Rwd/Pun 的增量（对齐理论 3.9.3：reward/pun 应真实影响递质通道）
        rwd_pun_to_nt_source_mode = (
            str(self._config.get("rwd_pun_to_nt_source_mode", "iesm_rules") or "iesm_rules").strip().lower()
            or "iesm_rules"
        )
        if rwd_pun_to_nt_source_mode in {"builtin", "config", "legacy", "hybrid", "both"}:
            nt_deltas_from_rwd_pun = self._compute_deltas_from_rwd_pun(rwd_pun)
        else:
            nt_deltas_from_rwd_pun = {}

        # 5) 额外脚本更新（可选）
        nt_deltas_from_script = self._coerce_channel_delta_dict(script_updates)

        # 6) 合并并应用
        merged_deltas: dict[str, float] = {}
        for key in set(nt_deltas_from_cfs) | set(nt_deltas_from_rwd_pun) | set(nt_deltas_from_script):
            merged_deltas[key] = round(
                float(nt_deltas_from_cfs.get(key, 0.0))
                + float(nt_deltas_from_rwd_pun.get(key, 0.0))
                + float(nt_deltas_from_script.get(key, 0.0)),
                8,
            )
        applied = self._apply_channel_deltas(merged_deltas)

        # 7) 调制输出（基于更新后的 NT 状态）
        modulation = self._compute_modulation()

        self._last_updated_at_ms = int(time.time() * 1000)
        self._last_tick_id = tick_id

        after = dict(self._nt_state)
        snapshot = self._build_snapshot()

        self._logger.brief(
            trace_id=trace_id or tick_id or "emotion",
            tick_id=tick_id,
            interface="update_emotion_state",
            success=True,
            input_summary={"cfs_signal_count": len(cfs_signals)},
            output_summary={"channels": dict(after), "rwd": rwd_pun.get("rwd", 0.0), "pun": rwd_pun.get("pun", 0.0)},
            message="情绪递质已更新 / Emotion updated",
        )

        return self._make_response(
            success=True,
            code="OK",
            message="情绪递质已更新 / Emotion updated",
            data={
                "nt_state_before": before,
                "nt_state_after": after,
                "nt_state_snapshot": snapshot,
                "nt_channel_labels": dict(_NT_CHANNEL_LABELS),
                "nt_channel_meta": dict(_NT_CHANNEL_META),
                "decay": decay_report,
                "deltas": {
                    "from_cfs": nt_deltas_from_cfs,
                    "from_rwd_pun": nt_deltas_from_rwd_pun,
                    "from_script": nt_deltas_from_script,
                    "merged": merged_deltas,
                    "applied": applied,
                },
                "rwd_pun_snapshot": rwd_pun,
                "rwd_pun_source": rwd_pun_source,
                "rwd_pun_detail": rwd_pun_detail,
                "modulation": modulation,
                "audit": {
                    "tick_id": tick_id,
                    "channel_count": len(after),
                    "cfs_to_nt_source_mode": cfs_to_nt_source_mode,
                    "rwd_pun_to_nt_source_mode": rwd_pun_to_nt_source_mode,
                },
            },
            trace_id=trace_id or tick_id,
            elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    # 接口二：get_emotion_snapshot                                       #
    # ================================================================== #

    def get_emotion_snapshot(self, trace_id: str = "") -> dict:
        start_time = time.time()
        self._total_calls += 1
        return self._make_response(
            success=True,
            code="OK",
            message="情绪递质快照 / Emotion snapshot",
            data={
                "nt_state_snapshot": self._build_snapshot(),
                "nt_channel_labels": dict(_NT_CHANNEL_LABELS),
                "nt_channel_meta": dict(_NT_CHANNEL_META),
                "last_updated_at_ms": self._last_updated_at_ms,
                "last_tick_id": self._last_tick_id,
            },
            trace_id=trace_id or "emotion_snapshot",
            elapsed_ms=self._elapsed_ms(start_time),
        )

    # ================================================================== #
    # 接口三：reload_config / runtime snapshot                             #
    # ================================================================== #

    def get_runtime_snapshot(self, *, trace_id: str = "emotion_runtime") -> dict:
        start_time = time.time()
        return self._make_response(
            success=True,
            code="OK",
            message="情绪递质运行态快照 / Emotion runtime snapshot",
            data={
                "module": __module_name__,
                "version": __version__,
                "schema_version": __schema_version__,
                "config_summary": dict(self._config),
                "stats": {"total_calls": int(self._total_calls)},
                "nt_state": dict(self._nt_state),
                "nt_channel_labels": dict(_NT_CHANNEL_LABELS),
                "nt_channel_meta": dict(_NT_CHANNEL_META),
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

            self._ensure_channels_initialized()

            self._logger.brief(
                trace_id=trace_id,
                interface="reload_config",
                success=True,
                input_summary={"path": path},
                output_summary={"applied_count": len(applied), "rejected_count": len(rejected)},
                message="热加载完成 / Hot reload done",
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
    # 内部逻辑                                                           #
    # ================================================================== #

    def _ensure_channels_initialized(self) -> None:
        channels = self._config.get("nt_channels", {}) or {}
        for ch, spec in channels.items():
            if ch not in self._nt_state:
                try:
                    base = float((spec or {}).get("base", 0.0) or 0.0)
                except Exception:
                    base = 0.0
                self._nt_state[ch] = self._clamp(base, spec or {})

        # 清理不存在的通道（防配置删通道后残留）
        for ch in list(self._nt_state.keys()):
            if ch not in channels:
                self._nt_state.pop(ch, None)

    def _apply_decay(self) -> dict:
        channels = self._config.get("nt_channels", {}) or {}
        global_decay = float(self._config.get("global_decay_ratio", 0.94))

        before = dict(self._nt_state)
        for ch, spec in channels.items():
            ratio = float(spec.get("decay_ratio", global_decay))
            try:
                base = float(spec.get("base", 0.0) or 0.0)
            except Exception:
                base = 0.0
            value = float(self._nt_state.get(ch, base))
            # Decay towards baseline instead of 0.
            # 衰减回归到 baseline（base），而不是一律回归到 0。
            decayed = base + (value - base) * ratio
            self._nt_state[ch] = self._clamp(decayed, spec)
        after = dict(self._nt_state)
        return {"before": before, "after": after, "global_decay_ratio": global_decay}

    def _compute_deltas_from_cfs(self, cfs_signals: list[dict]) -> dict[str, float]:
        gains = self._config.get("cfs_to_nt_gains", {}) or {}
        deltas: dict[str, float] = {}
        for sig in cfs_signals or []:
            kind = str(sig.get("kind", ""))
            strength = float(sig.get("strength", 0.0) or 0.0)
            mapping = gains.get(kind) or {}
            if not isinstance(mapping, dict) or strength <= 0.0:
                continue
            for ch, coef in mapping.items():
                deltas[ch] = round(float(deltas.get(ch, 0.0)) + strength * float(coef), 8)
        return deltas

    def _compute_rwd_pun_from_cfs(self, cfs_signals: list[dict]) -> dict[str, float]:
        mapping = self._config.get("cfs_to_rwd_pun", {}) or {}
        rwd = 0.0
        pun = 0.0
        for sig in cfs_signals or []:
            kind = str(sig.get("kind", ""))
            strength = float(sig.get("strength", 0.0) or 0.0)
            m = mapping.get(kind) or {}
            if not isinstance(m, dict) or strength <= 0.0:
                continue
            rwd += float(m.get("rwd", 0.0)) * strength
            pun += float(m.get("pun", 0.0)) * strength
        return {"rwd": round(max(0.0, rwd), 8), "pun": round(max(0.0, pun), 8)}

    def _compute_deltas_from_rwd_pun(self, rwd_pun: dict[str, float]) -> dict[str, float]:
        """
        Map global reward/punish snapshot to NT deltas.
        把全局奖励/惩罚快照映射为 NT（递质通道）增量。

        理论口径（对齐 3.9.3）强调：
        - reward_signal 获得实能量、奖励验证等不仅是“标签”，应真实影响 DA 等通道；
        - pun 同理影响 COR/ADR 等通道。

        设计约束：
        - rwd/pun 通常已在上层被软饱和到 0~1，因此这里系数无需过大。
        - 允许出现负系数（表示抑制/下降），但建议保持小幅，避免震荡。
        """
        mapping = self._config.get("rwd_pun_to_nt_gains", {}) or {}
        if not isinstance(mapping, dict):
            return {}

        rwd = float(rwd_pun.get("rwd", 0.0) or 0.0)
        pun = float(rwd_pun.get("pun", 0.0) or 0.0)
        deltas: dict[str, float] = {}

        def add_from(key: str, value: float) -> None:
            m = mapping.get(key) or {}
            if not isinstance(m, dict) or value <= 0.0:
                return
            for ch, coef in m.items():
                try:
                    deltas[str(ch)] = round(float(deltas.get(str(ch), 0.0)) + float(value) * float(coef), 8)
                except Exception:
                    continue

        add_from("rwd", rwd)
        add_from("pun", pun)
        return deltas

    def _compute_modulation(self) -> dict:
        mod = self._config.get("modulation", {}) or {}
        att = mod.get("attention", {}) or {}

        hdb = mod.get("hdb", {}) or {}

        nt_state = {str(ch): float(val) for ch, val in self._nt_state.items()}
        da = float(nt_state.get("DA", 0.0))
        adr = float(nt_state.get("ADR", 0.0))
        oxy = float(nt_state.get("OXY", 0.0))
        ser = float(nt_state.get("SER", 0.0))
        end = float(nt_state.get("END", 0.0))
        cor = float(nt_state.get("COR", 0.0))

        def build_linear_value(spec: dict[str, Any]) -> float:
            base = float(spec.get("base", 0.0) or 0.0)
            value = base
            for ch, channel_value in nt_state.items():
                key = str(ch).strip().lower()
                if not key or not (channel_value > 0.0):
                    continue
                value += float(channel_value) * float(spec.get(f"{key}_gain", 0.0) or 0.0)
                value -= float(channel_value) * float(spec.get(f"{key}_suppress", 0.0) or 0.0)
            if "min" in spec:
                value = max(float(spec.get("min", value) or value), value)
            if "max" in spec:
                value = min(float(spec.get("max", value) or value), value)
            return float(value)

        attention_field_specs = att.get("field_specs", {}) if isinstance(att.get("field_specs", {}), dict) else {}
        if attention_field_specs:
            attention_out: dict[str, Any] = {}
            for field_name, spec in attention_field_specs.items():
                if not isinstance(spec, dict):
                    continue
                raw_value = build_linear_value(spec)
                if bool(spec.get("round_to_int", False)):
                    attention_out[str(field_name)] = int(round(raw_value))
                else:
                    attention_out[str(field_name)] = round(float(raw_value), 8)

            top_n = int(attention_out.get("top_n", 16) or 16)
            top_n = max(1, min(64, top_n))
            attention_out["top_n"] = top_n
            if "min_cam_items" in attention_out:
                attention_out["min_cam_items"] = max(1, min(top_n, int(attention_out.get("min_cam_items", 1) or 1)))
            attention_out["nt_snapshot"] = dict(nt_state)
            out = {"attention": attention_out}
        else:
            base_top_n = int(att.get("base_top_n", 16))
            top_n = base_top_n + int(round(adr * float(att.get("adr_topn_gain", 0.0))))
            top_n -= int(round(cor * float(att.get("cor_topn_suppress", 0.0))))
            top_n = max(4, min(64, top_n))

            base_cp_w = float(att.get("base_priority_weight_cp_abs", 0.35))
            cp_w = base_cp_w + cor * float(att.get("cor_cp_weight_gain", 0.0)) - ser * float(att.get("ser_cp_weight_suppress", 0.0))
            cp_w = round(max(0.0, cp_w), 8)

            base_fatigue_w = float(att.get("base_priority_weight_fatigue", 0.0))
            fatigue_w = round(max(0.0, base_fatigue_w + cor * float(att.get("cor_fatigue_weight_gain", 0.0))), 8)

            base_min_energy = float(att.get("base_min_total_energy", 0.0))

            out = {
                "attention": {
                    "top_n": int(top_n),
                    "priority_weight_cp_abs": float(cp_w),
                    "priority_weight_fatigue": float(fatigue_w),
                    "min_total_energy": float(base_min_energy),
                    "nt_snapshot": dict(nt_state),
                }
            }

        # HDB modulation (scales) / HDB 调制（缩放系数）
        # ------------------------------------------------
        # 对齐理论 3.9.2：情绪递质应调制学习力度与能量传播系数。
        # 这里输出 scale（缩放系数），由 Observatory 在下一 tick 应用到 HDB 配置：
        #   effective_value = base_value * scale
        if isinstance(hdb, dict) and isinstance(hdb.get("scales", {}), dict) and hdb.get("scales"):
            clamp_min = float(hdb.get("clamp_min", 0.4) or 0.4)
            clamp_max = float(hdb.get("clamp_max", 2.5) or 2.5)
            if clamp_max < clamp_min:
                clamp_min, clamp_max = clamp_max, clamp_min
            clamp_min = max(0.01, clamp_min)
            clamp_max = max(clamp_min, clamp_max)

            scales_cfg = hdb.get("scales", {}) if isinstance(hdb.get("scales", {}), dict) else {}
            out_scales: dict[str, float] = {}

            def build_scale(spec: dict[str, Any]) -> float:
                base = float(spec.get("base", 1.0) or 1.0)
                s = base
                for ch, channel_value in nt_state.items():
                    key = str(ch).strip().lower()
                    if not key or not (channel_value > 0.0):
                        continue
                    s += float(channel_value) * float(spec.get(f"{key}_gain", 0.0) or 0.0)
                    s -= float(channel_value) * float(spec.get(f"{key}_suppress", 0.0) or 0.0)
                # Clamp / 限制
                if s < clamp_min:
                    s = clamp_min
                if s > clamp_max:
                    s = clamp_max
                return float(s)

            for key, spec in scales_cfg.items():
                if not isinstance(spec, dict):
                    continue
                try:
                    out_scales[f"{str(key)}_scale"] = round(build_scale(spec), 8)
                except Exception:
                    continue

            if out_scales:
                out["hdb"] = {
                    **out_scales,
                    "clamp_min": float(clamp_min),
                    "clamp_max": float(clamp_max),
                    "nt_snapshot": dict(nt_state),
                }

        return out

    def _apply_channel_deltas(self, deltas: dict[str, float]) -> dict[str, float]:
        channels = self._config.get("nt_channels", {}) or {}
        applied: dict[str, float] = {}
        for ch, delta in deltas.items():
            if ch not in channels:
                continue
            spec = channels.get(ch) or {}
            before = float(self._nt_state.get(ch, 0.0))
            after = self._apply_soft_capped_delta(before=before, delta=float(delta), spec=spec)
            self._nt_state[ch] = after
            applied[ch] = round(after - before, 8)
        return applied

    def _apply_soft_capped_delta(self, *, before: float, delta: float, spec: dict) -> float:
        """
        Apply delta with a soft upper cap (asymptotic to max).
        使用“软上限”应用增量：正向增量会渐近逼近 max，但不会达到 max。

        设计目标：
          - 可解释、可调参、可审计（不是黑箱）
          - 避免通道轻易打满（max），否则调制信号失去区分度

        公式（正向 delta）：
          gap = max - before
          after = max - gap * exp(-delta / k)
        """
        lo = float(spec.get("min", 0.0))
        hi = float(spec.get("max", 1.0))
        if hi <= lo:
            return lo

        # Hard clamp negative deltas (downwards) to keep MVP simple and stable.
        # 负向增量先用硬钳制（向下），保持 MVP 简单稳定；后续可按需要升级为对 min 的渐近。
        if delta <= 0.0:
            return max(lo, min(hi, float(before) + float(delta)))

        if not bool(self._config.get("soft_cap_enabled", True)):
            return max(lo, min(hi, float(before) + float(delta)))

        # Soft-cap params
        eps = float(self._config.get("soft_cap_eps", 1e-6) or 1e-6)
        k_default = float(self._config.get("soft_cap_k_default", 0.35) or 0.35)
        try:
            k = float(spec.get("soft_cap_k", k_default) or k_default)
        except Exception:
            k = k_default
        k = max(1e-9, float(k))

        v0 = max(lo, min(hi, float(before)))
        # Treat max as open interval: never reach hi exactly.
        # 把 max 视为开区间：永远不达到 hi。
        hi_open = hi - max(0.0, eps)
        if hi_open <= lo:
            hi_open = hi

        gap = max(0.0, hi_open - v0)
        if gap <= 0.0:
            return hi_open

        # Exponential saturation towards hi_open.
        after = hi_open - gap * math.exp(-float(delta) / float(k))
        # Safety clamp (numerical).
        if after > hi_open:
            after = hi_open
        if after < lo:
            after = lo
        return float(after)

    def _build_snapshot(self) -> dict:
        channels = self._config.get("nt_channels", {}) or {}
        return {
            "schema_version": __schema_version__,
            "module": __module_name__,
            "version": __version__,
            "channels": {
                ch: {
                    "value": round(float(self._nt_state.get(ch, 0.0)), 8),
                    "min": float(spec.get("min", 0.0)),
                    "max": float(spec.get("max", 1.0)),
                    "decay_ratio": float(spec.get("decay_ratio", self._config.get("global_decay_ratio", 0.94))),
                    "base": float(spec.get("base", 0.0) or 0.0),
                    "soft_cap_k": float(spec.get("soft_cap_k", self._config.get("soft_cap_k_default", 0.35)) or 0.35),
                }
                for ch, spec in channels.items()
            },
            "soft_cap": {
                "enabled": bool(self._config.get("soft_cap_enabled", True)),
                "eps": float(self._config.get("soft_cap_eps", 1e-6) or 1e-6),
                "k_default": float(self._config.get("soft_cap_k_default", 0.35) or 0.35),
                "formula_zh": "gap=max-before; after=max-gap*exp(-delta/k)（正向增量）",
            },
        }

    @staticmethod
    def _coerce_channel_delta_dict(payload: Any) -> dict[str, float]:
        if not isinstance(payload, dict):
            return {}

        # Allow Chinese channel names for developer friendliness.
        # 允许用中文通道名写脚本增量（更符合中文开发者习惯）：
        #   {"多巴胺":0.2} / {"多巴胺（DA）":0.2} / {"DA":0.2}
        # 最终都会归一化为稳定缩写（DA/ADR/...），以便与配置 nt_channels 对齐。
        alias_to_code: dict[str, str] = {}
        for code, label in _NT_CHANNEL_LABELS.items():
            c = str(code).strip()
            lab = str(label).strip()
            if not c:
                continue
            if lab:
                alias_to_code[lab] = c
                short = lab.split("（", 1)[0].split("(", 1)[0].strip()
                if short:
                    alias_to_code[short] = c

        out: dict[str, float] = {}
        for key, val in payload.items():
            k = str(key).strip()
            if not k:
                continue
            # Normalize parentheses variants to improve matching robustness.
            # 归一化括号：提升匹配鲁棒性。
            k2 = k.replace("(", "（").replace(")", "）").strip()
            k2 = alias_to_code.get(k2, k2)
            try:
                out[k2] = float(out.get(k2, 0.0) or 0.0) + float(val)
            except (TypeError, ValueError):
                continue
        return out

    @staticmethod
    def _clamp(value: float, spec: dict) -> float:
        v = float(value)
        lo = float(spec.get("min", 0.0))
        hi = float(spec.get("max", 1.0))
        if v < lo:
            return lo
        if v > hi:
            return hi
        return v

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
