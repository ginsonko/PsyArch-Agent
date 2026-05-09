# -*- coding: utf-8 -*-
"""
AP 实虚能量平衡控制器（Energy Balance Controller, EBC）— 主模块
=============================================================

当前定位（2026-04 新口径）
-------------------------
这个模块保留为“可选旧闭环控制器 / optional legacy controller”：
  - 默认关闭；
  - 默认理论口径不再要求直接把全局 `EV_total / ER_total` 收敛到单一目标值；
  - 当前更推荐把 `EV/ER` 当作诊断视角，用来判断“预测链是否整体偏薄”，而不是作为默认硬控制目标。

若手动启用，本模块仍可提供一个受控的回退实验路径，使：
  EV_total / ER_total → target_ratio

保留原因（为什么模块暂时不删）
------------------------------
若用户需要做“旧式虚实比闭环”对照实验，单纯固定参数很难保证
“对任意输入频次都收敛到某个目标比值”，原因包括：
  - 多处阈值（propagation/induction threshold）
  - Top-K 竞争与软上限衰减调制（soft cap）
  - ER/EV 衰减系数不同导致的偏置

因此这里保留一个“可插拔闭环控制器”：
  - 只读观测：读取状态池全局 ER_total/EV_total
  - 输出调制：输出一个正值 scale 因子 g（对数域积分控制）
  - 由 Observatory 在下一 tick 应用到 HDB 传播/诱发系数上

数学形式（对数域积分控制，Integral Control in log-domain）
----------------------------------------------------------
令：
  ratio_t = EV_total / (ER_total + eps)
  e_t = ln(ratio_t / target_ratio)

更新：
  ln(g_{t+1}) = clamp( ln(g_t) - ki * e_t , ln(g_min), ln(g_max) )

优点：
  - g 永远为正
  - 对“输入整体缩放”更鲁棒（log-domain）
  - 可解释、可调参、易审计
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any

from . import __module_name__, __schema_version__, __version__


def _load_yaml_config(path: str) -> dict[str, Any]:
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
    "enabled": False,
    "target_ratio": 1.0,
    "target_ratio_min": 1.08,
    "target_ratio_max": 1.35,
    "eps": 1e-6,
    "window_ticks": 6,
    "ki": 0.04,
    "g_min": 0.2,
    "g_max": 5.0,
    "min_total_energy_to_update": 0.5,
    "neutral_log_g_decay": 0.03,
    "counter_windup_gain": 2.5,
    "error_deadband": 0.03,
    "apply_scales": {
        "ev_propagation_ratio_scale": False,
        "er_induction_ratio_scale": False,
    },
}


class EnergyBalanceController:
    """
    Energy Balance Controller (EBC).
    实虚能量平衡控制器。

    输出：
      - hdb_scales_out: {<scale_key>: g}
        由上层把这些 scale 与其他来源（EMgr/Action）的 scale 相乘合并，作为下一 tick HDB 调制输入。
    """

    def __init__(self, *, config_path: str = "", config_override: dict[str, Any] | None = None):
        self._config_path = config_path or os.path.join(os.path.dirname(__file__), "config", "energy_balance_config.yaml")
        self._config: dict[str, Any] = dict(_DEFAULT_CONFIG)
        self._config.update(_load_yaml_config(self._config_path))
        if config_override and isinstance(config_override, dict):
            self._config.update(dict(config_override))

        # Controller internal state / 控制器内部状态
        self._log_g = 0.0  # ln(g)
        self._ratio_log_history: list[float] = []  # store ln(ratio_t)
        self._tick_counter = 0
        self._last_update_at_ms = 0

    def close(self) -> None:
        """Placeholder for symmetry with other modules. / 占位：与其他模块保持接口一致。"""
        return

    def reload_config(
        self,
        *,
        trace_id: str,
        config_path: str | None = None,
        apply_partial: bool = True,
    ) -> dict[str, Any]:
        """Hot reload config file (best-effort). / 热加载配置（尽力而为）。"""
        start = time.time()
        path = str(config_path or self._config_path)
        raw = _load_yaml_config(path)
        if not raw:
            return {
                "success": False,
                "code": "CONFIG_EMPTY",
                "message": f"配置加载失败或为空: {path}",
                "trace_id": trace_id,
                "elapsed_ms": int((time.time() - start) * 1000),
            }
        # Only accept known keys (keep config stable).
        applied: list[str] = []
        rejected: list[dict[str, Any]] = []
        for k, v in raw.items():
            if k not in _DEFAULT_CONFIG:
                rejected.append({"key": k, "reason": "unknown_key"})
                continue
            expected_type = type(_DEFAULT_CONFIG[k])
            if isinstance(v, expected_type) or (expected_type is float and isinstance(v, (int, float))):
                self._config[k] = v
                applied.append(k)
            else:
                rejected.append(
                    {
                        "key": k,
                        "reason": "type_mismatch",
                        "expected": expected_type.__name__,
                        "got": type(v).__name__,
                    }
                )

        if rejected and not apply_partial:
            return {
                "success": False,
                "code": "CONFIG_ERROR",
                "message": f"Some config items rejected: {len(rejected)}",
                "trace_id": trace_id,
                "elapsed_ms": int((time.time() - start) * 1000),
                "data": {"path": path, "applied": applied, "rejected": rejected},
            }

        return {
            "success": True,
            "code": "OK",
            "message": "配置热加载完成 / Config reloaded",
            "trace_id": trace_id,
            "elapsed_ms": int((time.time() - start) * 1000),
            "data": {"path": path, "applied": applied, "rejected": rejected},
        }

    def reset_state(self) -> None:
        """Reset controller state. / 重置控制器内部状态。"""
        self._log_g = 0.0
        self._ratio_log_history = []
        self._tick_counter = 0
        self._last_update_at_ms = 0

    def get_runtime_snapshot(self, *, trace_id: str = "energy_balance_snapshot") -> dict[str, Any]:
        """Runtime snapshot for UI. / 供前端展示的运行态快照。"""
        g = float(math.exp(self._log_g))
        return {
            "module": __module_name__,
            "version": __version__,
            "schema_version": __schema_version__,
            "trace_id": trace_id,
            "config_path": self._config_path,
            "config": dict(self._config),
            "state": {
                "tick_counter": int(self._tick_counter),
                "g": round(float(g), 8),
                "log_g": round(float(self._log_g), 8),
                "history_len": int(len(self._ratio_log_history)),
                "last_update_at_ms": int(self._last_update_at_ms),
            },
        }

    def update_from_energy_summary(
        self,
        *,
        trace_id: str,
        tick_id: str,
        tick_index: int,
        total_er: float,
        total_ev: float,
    ) -> dict[str, Any]:
        """
        Update controller state from global energy totals.
        基于全局能量总量更新控制器状态，并输出 HDB 调制 scale。
        """
        start = time.time()
        self._tick_counter += 1
        now_ms = int(time.time() * 1000)

        cfg = self._config or {}
        enabled = bool(cfg.get("enabled", False))
        target_ratio = float(cfg.get("target_ratio", 1.0) or 1.0)
        target_ratio_min = float(cfg.get("target_ratio_min", 1.08) or 0.0)
        target_ratio_max = float(cfg.get("target_ratio_max", 1.35) or 0.0)
        eps = float(cfg.get("eps", 1e-6) or 1e-6)
        window_ticks = int(cfg.get("window_ticks", 6) or 6)
        ki = float(cfg.get("ki", 0.04) or 0.04)
        g_min = float(cfg.get("g_min", 0.2) or 0.2)
        g_max = float(cfg.get("g_max", 5.0) or 5.0)
        min_total = float(cfg.get("min_total_energy_to_update", 0.5) or 0.0)
        neutral_log_g_decay = float(cfg.get("neutral_log_g_decay", 0.03) or 0.0)
        counter_windup_gain = float(cfg.get("counter_windup_gain", 2.5) or 1.0)
        error_deadband = float(cfg.get("error_deadband", 0.03) or 0.0)

        window_ticks = max(1, min(128, int(window_ticks)))
        ki = max(0.0, float(ki))
        target_ratio_min = max(eps, float(target_ratio_min))
        target_ratio_max = max(float(target_ratio_min), float(target_ratio_max) if target_ratio_max > 0.0 else float(target_ratio_min))
        target_ratio = max(float(target_ratio_min), min(float(target_ratio_max), max(eps, float(target_ratio))))
        eps = max(1e-12, float(eps))
        g_min = max(eps, float(g_min))
        g_max = max(g_min, float(g_max))
        neutral_log_g_decay = max(0.0, min(0.5, float(neutral_log_g_decay)))
        counter_windup_gain = max(1.0, min(8.0, float(counter_windup_gain)))
        error_deadband = max(0.0, min(2.0, float(error_deadband)))

        total_er = max(0.0, float(total_er))
        total_ev = max(0.0, float(total_ev))
        total_energy = total_er + total_ev

        ratio_raw = total_ev / (total_er + eps)
        ratio_raw = max(eps, float(ratio_raw))
        log_ratio = float(math.log(ratio_raw))

        # Update history even when disabled: keeps observability stable.
        # 即便 disabled，也记录 ratio 历史（便于启用后立即稳定）。
        self._ratio_log_history.append(log_ratio)
        if len(self._ratio_log_history) > window_ticks:
            self._ratio_log_history = self._ratio_log_history[-window_ticks:]

        # Smoothed ratio (geometric mean) / 平滑后的比例（几何均值）
        smoothed_log_ratio = sum(self._ratio_log_history) / max(1, len(self._ratio_log_history))
        ratio_smooth = float(math.exp(smoothed_log_ratio))

        # Error in log domain / 对数域误差
        err_log = float(smoothed_log_ratio - math.log(target_ratio))
        err_log_mag = abs(float(err_log))
        if error_deadband > 0.0 and err_log_mag <= error_deadband:
            err_log_effective = 0.0
        elif error_deadband > 0.0:
            err_log_effective = math.copysign(max(0.0, err_log_mag - error_deadband), float(err_log))
        else:
            err_log_effective = float(err_log)

        g_before = float(math.exp(self._log_g))
        log_g_before = float(self._log_g)
        updated = False
        counter_windup_active = False
        ki_effective = float(ki)
        log_g_after_decay = float(self._log_g)
        neutral_decay_active = False

        if enabled and total_energy >= min_total:
            if abs(log_g_after_decay) > 1e-12 and abs(err_log_effective) > 1e-12 and (log_g_after_decay * err_log_effective) > 0.0:
                counter_windup_active = True
                ki_effective = float(ki_effective * counter_windup_gain)
            if neutral_log_g_decay > 0.0 and abs(log_g_after_decay) > 1e-12 and (counter_windup_active or abs(err_log_effective) <= 1e-12):
                neutral_decay_active = True
                log_g_after_decay = float(log_g_after_decay * (1.0 - neutral_log_g_decay))
            # Integral update / 积分更新（对数域）
            log_g_new = float(log_g_after_decay - ki_effective * err_log_effective)
            log_g_new = max(float(math.log(g_min)), min(float(math.log(g_max)), float(log_g_new)))
            self._log_g = float(log_g_new)
            self._last_update_at_ms = int(now_ms)
            updated = True

        g_after = float(math.exp(self._log_g))
        log_g_after = float(self._log_g)

        # Build scales out / 输出调制 scale（与其他来源相乘合并）
        apply_scales = cfg.get("apply_scales", {}) if isinstance(cfg.get("apply_scales", {}), dict) else {}
        hdb_scales_out: dict[str, float] = {}
        if enabled:
            for k, on in apply_scales.items():
                if not bool(on):
                    continue
                key = str(k or "").strip()
                if not key:
                    continue
                hdb_scales_out[key] = round(float(g_after), 8)

        return {
            "success": True,
            "code": "OK",
            "message": "energy balance updated" if updated else "energy balance skipped",
            "trace_id": trace_id,
            "tick_id": tick_id,
            "elapsed_ms": int((time.time() - start) * 1000),
            "data": {
                "enabled": bool(enabled),
                "tick_index": int(tick_index),
                "window_ticks": int(window_ticks),
                "target_ratio": round(float(target_ratio), 8),
                "target_ratio_min": round(float(target_ratio_min), 8),
                "target_ratio_max": round(float(target_ratio_max), 8),
                "total_er": round(float(total_er), 8),
                "total_ev": round(float(total_ev), 8),
                "total_energy": round(float(total_energy), 8),
                "ratio_raw": round(float(ratio_raw), 8),
                "ratio_smooth": round(float(ratio_smooth), 8),
                "error_log": round(float(err_log), 8),
                "error_log_effective": round(float(err_log_effective), 8),
                "error_deadband": round(float(error_deadband), 8),
                "ki": round(float(ki), 8),
                "ki_effective": round(float(ki_effective), 8),
                "neutral_log_g_decay": round(float(neutral_log_g_decay), 8),
                "neutral_decay_active": bool(neutral_decay_active),
                "counter_windup_gain": round(float(counter_windup_gain), 8),
                "counter_windup_active": bool(counter_windup_active),
                "g_before": round(float(g_before), 8),
                "g_after": round(float(g_after), 8),
                "log_g_before": round(float(log_g_before), 8),
                "log_g_after_decay": round(float(log_g_after_decay), 8),
                "log_g_after": round(float(log_g_after), 8),
                "updated": bool(updated),
                "skipped_reason": "" if updated else ("disabled" if not enabled else ("low_energy" if total_energy < min_total else "unknown")),
                "min_total_energy_to_update": round(float(min_total), 8),
                "hdb_scales_out": dict(hdb_scales_out),
                "built_at_ms": int(now_ms),
            },
        }
