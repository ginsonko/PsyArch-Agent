# -*- coding: utf-8 -*-
"""
AP 原型“严苛验收 / 找茬式”检查脚本
=================================

目标
----
在不引入外部依赖的前提下，用脚本自动跑若干轮 cycle/tick，并对关键不变量做检查：
  - 先天规则引擎（IESM）输出结构是否自洽
  - 行动模块（Action/Drive）Drive/阈值/来源标签是否符合预期口径
  - 观测台 report 是否包含验收必需字段（trace_id/tick_id 等）

为什么需要它
-----------
前端观测台非常适合“人眼验收”，但很多回归问题属于“细小字段漏写/计数不一致/边界值出错”，
用脚本做“找茬式”自动检查能更早发现 bug，避免靠肉眼慢慢对日志。

使用方式
--------
1) 在仓库根目录执行：
   python tools/strict_acceptance_check.py

2) 如需减少运行轮数，可设置环境变量：
   $env:AP_QA_CYCLES=8; python tools/strict_acceptance_check.py

输出
----
脚本会打印一个 JSON 结果：
  - ok: bool
  - issues: [{level, where, message_zh, hint}]
若 issues 非空，脚本会以非 0 退出码结束（方便 CI/手工验收脚本链路集成）。

说明（中英文缩写）
---------------
  - IESM: 先天编码脚本管理器（Innate Encoding Script Manager）
  - CFS: 认知感受信号（Cognitive Feeling Signals）
  - NT: 情绪递质通道（NeuroTransmitter channels）
  - SP: 状态池（StatePool）
  - Drive: 驱动力（行动触发资源）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import time
import traceback
from typing import Any


def _as_list(v: Any) -> list:
    return list(v) if isinstance(v, list) else []


def _issue(*, level: str, where: str, message_zh: str, hint: str = "") -> dict[str, Any]:
    return {"level": level, "where": where, "message_zh": message_zh, "hint": hint}


def _check_report(report: dict[str, Any], *, index: int) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    where = f"report[{index}]"

    trace_id = str(report.get("trace_id", "") or "")
    tick_id = str(report.get("tick_id", "") or "")
    if not trace_id:
        issues.append(_issue(level="error", where=where, message_zh="缺少 trace_id。", hint="观测台每轮 cycle 必须有 trace_id。"))
    if not tick_id:
        issues.append(_issue(level="error", where=where, message_zh="缺少 tick_id。", hint="tick_id 用于跨模块对齐本轮 tick；应与 trace_id 一致（当前原型口径）。"))
    if trace_id and tick_id and trace_id != tick_id:
        issues.append(_issue(level="warning", where=where, message_zh=f"tick_id({tick_id}) 与 trace_id({trace_id}) 不一致。", hint="当前原型默认相同；若未来并行子流程需要不同，可在验收标准里明确。"))

    # 基本结构：这些 key 缺失会让前端验收非常难进行。
    must_keys = ["sensor", "attention", "innate_script", "emotion", "action", "final_state"]
    for k in must_keys:
        if k not in report:
            issues.append(_issue(level="error", where=where, message_zh=f"report 缺少关键字段：{k}", hint="run_cycle() 应回填各模块输出到 report。"))

    # IESM 输出自洽检查（计数一致）
    iesm = report.get("innate_script") if isinstance(report.get("innate_script"), dict) else {}
    focus = iesm.get("focus") if isinstance(iesm.get("focus"), dict) else {}
    tick_rules = iesm.get("tick_rules") if isinstance(iesm.get("tick_rules"), dict) else {}
    if tick_rules:
        trig_rules = _as_list(focus.get("triggered_rules"))
        action_triggers = _as_list(focus.get("action_triggers"))
        focus_directives = _as_list(focus.get("focus_directives"))
        pool_effects = _as_list(focus.get("pool_effects"))
        if int(tick_rules.get("triggered_rule_count", len(trig_rules)) or 0) != len(trig_rules):
            issues.append(_issue(level="warning", where=where, message_zh="IESM triggered_rule_count 与 triggered_rules 长度不一致。", hint="建议统一以列表长度为准，避免前端显示误导。"))
        if int(tick_rules.get("action_trigger_count", len(action_triggers)) or 0) != len(action_triggers):
            issues.append(_issue(level="warning", where=where, message_zh="IESM action_trigger_count 与 action_triggers 长度不一致。", hint="建议统一以列表长度为准。"))
        if int(tick_rules.get("focus_directive_count", len(focus_directives)) or 0) != len(focus_directives):
            issues.append(_issue(level="warning", where=where, message_zh="IESM focus_directive_count 与 focus_directives 长度不一致。", hint="建议统一以列表长度为准。"))
        if int(tick_rules.get("pool_effect_count", len(pool_effects)) or 0) != len(pool_effects):
            issues.append(_issue(level="warning", where=where, message_zh="IESM pool_effect_count 与 pool_effects 长度不一致。", hint="建议统一以列表长度为准。"))

    # 行动模块基本不变量
    action = report.get("action") if isinstance(report.get("action"), dict) else {}
    executed = _as_list(action.get("executed_actions"))
    tm = action.get("threshold_modulation") if isinstance(action.get("threshold_modulation"), dict) else {}
    scale_min = float(tm.get("threshold_scale_min", 0.0) or 0.0)
    scale_max = float(tm.get("threshold_scale_max", 1e9) or 1e9)
    for j, ex in enumerate(executed[:64]):
        if not isinstance(ex, dict):
            issues.append(_issue(level="warning", where=f"{where}.action.executed_actions[{j}]", message_zh="executed_actions 条目不是 dict。"))
            continue
        ok = bool(ex.get("success", True))
        drive_before = float(ex.get("drive_before", 0.0) or 0.0)
        drive_after = float(ex.get("drive_after", 0.0) or 0.0)
        eff_th = float(ex.get("effective_threshold", 0.0) or 0.0)

        if drive_before < -1e-9 or drive_after < -1e-9:
            issues.append(_issue(level="error", where=f"{where}.action.executed_actions[{j}]", message_zh="drive 出现负数（不符合默认口径）。", hint="如需允许负 drive，请在理论/实现层显式打开 allow_negative。"))

        if ok:
            # 规则：成功执行应当满足 drive_before >= effective_threshold（留一点容差）
            if drive_before + 1e-6 < eff_th:
                issues.append(_issue(level="warning", where=f"{where}.action.executed_actions[{j}]", message_zh="成功执行但 drive_before < effective_threshold。", hint="可能是阈值更新/消耗顺序错误，或阈值字段写错。"))
            # 成功执行后 drive 应减少（按阈值消耗），但不应增加。
            if drive_after - drive_before > 1e-6:
                issues.append(_issue(level="warning", where=f"{where}.action.executed_actions[{j}]", message_zh="成功执行后 drive_after 反而大于 drive_before。", hint="理论口径一般是消耗/衰减，不应凭空增加。"))
        else:
            # 规则：失败不应消耗 drive（原型口径：失败不消耗，便于后续反馈学习）
            if abs(drive_after - drive_before) > 1e-6:
                issues.append(_issue(level="warning", where=f"{where}.action.executed_actions[{j}]", message_zh="执行失败但 drive 发生了变化（疑似被消耗）。", hint="建议：失败不消耗 drive；仅记录 failure_reason。"))
            if not str(ex.get("failure_reason", "") or ""):
                issues.append(_issue(level="warning", where=f"{where}.action.executed_actions[{j}]", message_zh="执行失败但未给出 failure_reason。", hint="前端验收需要失败原因以定位规则/阈值/候选缺失等问题。"))

        origin = ex.get("origin") if isinstance(ex.get("origin"), dict) else {}
        if "passive_iesm" not in origin and "active_internal" not in origin:
            issues.append(_issue(level="info", where=f"{where}.action.executed_actions[{j}]", message_zh="executed_actions 未包含来源标签 origin（被动IESM/主动内驱）。", hint="建议补齐，方便验收“被动/主动”。"))

        # 阈值缩放（threshold_scale）范围检查：应落在模块配置的 min/max 之间（除非未来显式放开）。
        try:
            scale = float(ex.get("threshold_scale", 1.0) or 1.0)
            if scale < scale_min - 1e-6 or scale > scale_max + 1e-6:
                issues.append(
                    _issue(
                        level="warning",
                        where=f"{where}.action.executed_actions[{j}]",
                        message_zh=f"threshold_scale 超出范围：{scale}（期望 {scale_min}~{scale_max}）",
                        hint="可能是阈值调制计算未做 clamp；会影响行动稳定性与可解释性。",
                    )
                )
        except Exception:
            pass

    return issues


def _check_action_runtime_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(snapshot, dict):
        return [_issue(level="error", where="action_runtime", message_zh="行动运行态快照不是 dict。")]

    cfg = snapshot.get("config_summary") if isinstance(snapshot.get("config_summary"), dict) else {}
    try:
        scale_min = float(cfg.get("threshold_scale_min", 0.0) or 0.0)
        scale_max = float(cfg.get("threshold_scale_max", 1e9) or 1e9)
    except Exception:
        scale_min, scale_max = 0.0, 1e9

    nodes = _as_list(snapshot.get("nodes"))
    for i, node in enumerate(nodes[:128]):
        if not isinstance(node, dict):
            issues.append(_issue(level="warning", where=f"action_runtime.nodes[{i}]", message_zh="nodes 条目不是 dict。"))
            continue
        drive = float(node.get("drive", 0.0) or 0.0)
        th = float(node.get("effective_threshold", 0.0) or 0.0)
        try:
            scale = float(node.get("threshold_scale", 1.0) or 1.0)
        except Exception:
            scale = 1.0
        if drive < -1e-9:
            issues.append(_issue(level="error", where=f"action_runtime.nodes[{i}]", message_zh="行动节点 drive 为负数。"))
        if th < 0.0:
            issues.append(_issue(level="warning", where=f"action_runtime.nodes[{i}]", message_zh="行动节点 effective_threshold 为负数（通常不合理）。"))
        if scale < scale_min - 1e-6 or scale > scale_max + 1e-6:
            issues.append(_issue(level="warning", where=f"action_runtime.nodes[{i}]", message_zh=f"行动节点 threshold_scale 超出范围：{scale}（期望 {scale_min}~{scale_max}）。"))
    return issues


def main() -> int:
    # Ensure repo root is importable.
    # 确保“仓库根目录”在 sys.path 中：
    # - 直接运行子目录脚本（python tools/xxx.py）时，sys.path[0] 会变成 tools/，
    #   这会导致无法 import observatory/state_pool 等顶层包。
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    verbose = str(os.environ.get("AP_QA_VERBOSE", "") or "").strip() in {"1", "true", "True", "yes", "Y"}
    strict_warnings = str(os.environ.get("AP_QA_STRICT_WARN", "") or "").strip() in {"1", "true", "True", "yes", "Y"}

    # cycles: 默认跑 6 轮（原型下跑太多轮会受 HDB 增长影响变慢）；可通过环境变量调大。
    try:
        cycles = int(os.environ.get("AP_QA_CYCLES", "6"))
    except Exception:
        cycles = 6
    cycles = max(1, min(80, cycles))

    # 样例输入：覆盖常见边界（重复、标点、空字符串、混合语言）
    texts = [
        "你好呀!",
        "你好呀!",  # 重复：用于触发 fatigue/repetition 等
        "我想测试一下：期待/压力/违和感/正确事件。",
        "???!",
        "1+1=2",
        "",  # 空输入
        "Hello 你好 mixed",  # 混合输入
        "（括号）与，标点。",  # 中文标点
    ]

    # 运行与检查
    issues: list[dict[str, Any]] = []
    cycle_ms: list[int] = []
    try:
        from observatory._app import ObservatoryApp

        app = ObservatoryApp()
        for i in range(cycles):
            text = texts[i % len(texts)]
            t0 = time.time()
            report = app.run_cycle(text=text)
            dt_ms = int((time.time() - t0) * 1000)
            cycle_ms.append(dt_ms)
            if not isinstance(report, dict):
                issues.append(_issue(level="error", where=f"report[{i}]", message_zh="run_cycle 返回值不是 dict。"))
                continue
            issues.extend(_check_report(report, index=i))

            # 每隔几轮拉一次行动运行态快照，检查基本不变量（不修改状态）。
            if i in {0, 2, 4, cycles - 1}:
                snap = app.get_action_runtime_data()
                issues.extend(_check_action_runtime_snapshot(snap))

            # 性能“找茬”：原型阶段先用一个保守阈值，超过就提示可能存在算法/数据增长问题。
            # 说明：这里不是硬错误，只是提醒你重点关注哪些输入让流程变慢。
            if dt_ms >= 8000:
                timing = report.get("timing") if isinstance(report.get("timing"), dict) else {}
                steps = timing.get("steps_ms") if isinstance(timing.get("steps_ms"), dict) else {}
                # 找出最慢的“步骤耗时”（排除 total_logic_ms 这种聚合字段）
                slow_step = ""
                slow_ms = 0
                try:
                    for k, v in steps.items():
                        if str(k) == "total_logic_ms":
                            continue
                        ms = int(v or 0)
                        if ms > slow_ms:
                            slow_ms, slow_step = ms, str(k)
                except Exception:
                    slow_step, slow_ms = "", 0
                issues.append(
                    _issue(
                        level="warning",
                        where=f"report[{i}]",
                        message_zh=f"本轮 run_cycle 用时偏长：{dt_ms}ms（输入长度 {len(text)}；最慢步骤 {slow_step or '-'}={slow_ms}ms）",
                        hint="建议查看 report.timing.steps_ms，并重点排查 stimulus_level/structure_level/induction 等过程的 round_details。",
                    )
                )
            if verbose:
                print(f"[qa] cycle {i+1}/{cycles} trace_id={report.get('trace_id')} ms={dt_ms} sensor_ok={(report.get('sensor') or {}).get('success', True)}")
        app.close()
    except Exception as exc:
        issues.append(
            _issue(
                level="error",
                where="runner",
                message_zh=f"脚本运行异常：{exc}",
                hint=traceback.format_exc(),
            )
        )

    has_error = any(it.get("level") == "error" for it in issues)
    has_warning = any(it.get("level") == "warning" for it in issues)
    ok = (not has_error) and (not has_warning if strict_warnings else True)
    timing = {
        "cycle_ms": cycle_ms,
        "total_ms": int(sum(cycle_ms)),
        "avg_ms": int(sum(cycle_ms) / max(1, len(cycle_ms))) if cycle_ms else 0,
        "max_ms": int(max(cycle_ms)) if cycle_ms else 0,
    }
    out = {"ok": ok, "cycle_count": cycles, "timing": timing, "issue_count": len(issues), "issues": issues}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
