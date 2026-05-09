# -*- coding: utf-8 -*-
"""
Parameter Catalog (Auto-Tuner)
==============================

This module builds an explicit, auditable catalog of "tunable parameters" across
the prototype:
- module configs (*/config/*_config.yaml and observatory/config/observatory_config.yaml)
- IESM rules (innate_script/config/innate_rules.yaml) as "rule parameters"

Why:
- Users want a complete "参数-影响对应表" (parameter -> observable impacts).
- The adaptive AutoTuner should be able to tune "almost every" numeric knob,
  but in a safe, explainable way (bounds, small steps, audit logs).

Notes:
- We intentionally avoid semantic hacks. We include most numeric params, but we
  mark high-risk params (strings/enums/large structural lists like time buckets)
  as not-auto-tunable by default.
- This is not a perfect causal model; the mapping is a practical engineering
  index used to pick candidate knobs when a metric drifts.
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import io, storage


# ------------------------------
# Param identifiers / helpers
# ------------------------------


_LIST_INDEX_RE = re.compile(r"^\[(\d+)\]$")


def _path_tokens_to_str(tokens: list[Any]) -> str:
    out: list[str] = []
    for t in tokens:
        if isinstance(t, int):
            if not out:
                out.append(f"[{t}]")
            else:
                out[-1] = f"{out[-1]}[{t}]"
            continue
        s = str(t)
        if not out:
            out.append(s)
        else:
            out.append(s)
    return ".".join(out)


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (bool, int, float, str))


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


DEFAULT_LONG_METRIC_LIBRARY: list[dict[str, Any]] = [
    {
        "key": "timing_total_logic_ms",
        "title": "单 Tick 总逻辑耗时",
        "group": "运行效率",
        "unit": "ms",
        "expected_min": 0.0,
        "expected_max": 8000.0,
        "ideal": 4500.0,
        "min_std": 200.0,
        "description": "整轮主逻辑耗时。它更适合作为全局症状诊断：若过高，应继续分解到具体热点模块，不宜直接把它当成任意参数的通用调节信号。",
    },
    {
        "key": "timing_structure_level_ms",
        "title": "结构级查存耗时",
        "group": "运行效率",
        "unit": "ms",
        "expected_min": 0.0,
        "expected_max": 1400.0,
        "ideal": 450.0,
        "min_std": 60.0,
        "description": "结构级查存与内源分辨率的主要成本。",
    },
    {
        "key": "timing_stimulus_level_ms",
        "title": "刺激级查存耗时",
        "group": "运行效率",
        "unit": "ms",
        "expected_min": 0.0,
        "expected_max": 4200.0,
        "ideal": 2200.0,
        "min_std": 120.0,
        "description": "刺激级查存一体的主耗时，常与 flat token 规模和轮次直接耦合。",
    },
    {
        "key": "timing_cache_neutralization_ms",
        "title": "缓存中和耗时",
        "group": "运行效率",
        "unit": "ms",
        "expected_min": 0.0,
        "expected_max": 2400.0,
        "ideal": 1200.0,
        "min_std": 80.0,
        "description": "残响与状态池优先中和的成本，过高通常说明历史残响或中和空间膨胀。",
    },
    {
        "key": "timing_cognitive_stitching_ms",
        "title": "认知拼接耗时（CS）",
        "group": "运行效率",
        "unit": "ms",
        "expected_min": 0.0,
        "expected_max": 1200.0,
        "ideal": 180.0,
        "min_std": 25.0,
        "diagnostic_only": True,
        "description": "认知拼接模块（CS）的运行耗时。新版默认 growth 主链下 CS 应关闭或接近 0；只有显式 residual/CS 回滚或 A/B 对照时，才把它作为候选空间过大、overlay/弱命中过热的诊断依据。",
    },
    {
        "key": "timing_event_grasp_ms",
        "title": "事件把握感耗时（Event Grasp）",
        "group": "运行效率",
        "unit": "ms",
        "expected_min": 0.0,
        "expected_max": 260.0,
        "ideal": 18.0,
        "min_std": 6.0,
        "description": "对进入 CAM 的 ES 绑定事件把握感（event_grasp）的耗时。应保持很轻，否则会挤压主链路预算。",
    },
    {
        "key": "timing_attention_ms",
        "title": "注意力耗时",
        "group": "运行效率",
        "unit": "ms",
        "expected_min": 0.0,
        "expected_max": 240.0,
        "ideal": 60.0,
        "min_std": 12.0,
        "description": "注意力筛选与 CAM 形成的耗时。若偏高，应优先看候选扇出和 CAM 容量，而不是直接怀疑 HDB。",
    },
    {
        "key": "timing_sensor_ms",
        "title": "文本感受器耗时",
        "group": "运行效率",
        "unit": "ms",
        "expected_min": 0.0,
        "expected_max": 120.0,
        "ideal": 30.0,
        "min_std": 8.0,
        "description": "文本感受器输入解析耗时。它既可能来自真实输入变长，也可能来自回声池堆积，因此更适合作为细分诊断口径。",
    },
    {
        "key": "timing_maintenance_ms",
        "title": "状态池维护耗时",
        "group": "运行效率",
        "unit": "ms",
        "expected_min": 0.0,
        "expected_max": 900.0,
        "ideal": 260.0,
        "min_std": 25.0,
        "description": "状态池维护、衰减、清理与合并维护的耗时。若偏高，应重点看状态池软容量与对象堆积，而不是误收 HDB。",
    },
    {
        "key": "timing_time_sensor_ms",
        "title": "时间感受器耗时",
        "group": "运行效率",
        "unit": "ms",
        "expected_min": 0.0,
        "expected_max": 80.0,
        "ideal": 18.0,
        "min_std": 6.0,
        "description": "时间感受器、延迟任务与绑定更新的耗时。若偏高，应检查绑定总量与延迟任务表，而不是动主认知链预算。",
    },
    {
        "key": "internal_resolution_raw_unit_count",
        "title": "内源原始分辨率单位数",
        "group": "预算控制",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 350.0,
        "ideal": 160.0,
        "min_std": 10.0,
        "description": "结构级内源残差的原始规模。若长期远超预算，说明先生成后截断，成本已发生。",
    },
    {
        "key": "internal_resolution_selected_unit_count",
        "title": "内源入选分辨率单位数",
        "group": "预算控制",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 250.0,
        "ideal": 135.0,
        "min_std": 8.0,
        "description": "在预算内真正进入本轮的分辨率单位数。",
    },
    {
        "key": "internal_sa_count",
        "title": "内源刺激元数量",
        "group": "内源主导",
        "unit": "count",
        "expected_min": 64.0,
        "expected_max": 260.0,
        "ideal": 140.0,
        "min_std": 8.0,
        "description": "结构级内源包真正生成的内源 SA 数量，是判断内源内容是否占主导的主要口径。",
    },
    {
        "key": "internal_to_external_sa_ratio",
        "title": "内源/外源刺激比",
        "group": "内源主导",
        "unit": "ratio",
        "expected_min": 1.25,
        "expected_max": 12.0,
        "ideal": 4.0,
        "min_std": 0.08,
        "description": "内源 SA 数量与外源 SA 数量的比值。它主要用于判断内源是否被压瘦；高值本身不默认视为坏事，必须结合外源是否稀疏、上下文供给是否健康一起判断。",
    },
    {
        "key": "stimulus_transfer_matched_total",
        "title": "刺激级命中赋能总量",
        "group": "刺激赋能",
        "unit": "energy",
        "expected_min": 0.0,
        "expected_max": 240.0,
        "ideal": 24.0,
        "min_std": 1.0,
        "description": "刺激级查存一体中，已被命中结构吸收/强化的 SA 粒度 ER+EV 总量。它用于判断能量是否进入命中对象，而不是多数留在残余尾巴。",
    },
    {
        "key": "stimulus_final_residual_total",
        "title": "刺激级最终残余总量",
        "group": "刺激赋能",
        "unit": "energy",
        "expected_min": 0.0,
        "expected_max": 180.0,
        "ideal": 8.0,
        "min_std": 1.0,
        "description": "刺激级多轮查存后最后还没被命中对象吸收的 ER+EV 尾巴总量。新版默认希望它多数时候低于命中赋能总量。",
    },
    {
        "key": "stimulus_transfer_to_residual_ratio",
        "title": "命中赋能/最终残余比",
        "group": "刺激赋能",
        "unit": "ratio",
        "expected_min": 1.0,
        "expected_max": 40.0,
        "ideal": 3.0,
        "min_std": 0.15,
        "description": "刺激级命中对象得到的总能量与最终残余总能量之比。多数有命中的 source tick 应大于 1；长期小于 1 说明覆盖率曲线、候选命中或输入合流规模需要检查。",
    },
    {
        "key": "stimulus_effective_transfer_fraction_mean",
        "title": "刺激级有效转移比例均值",
        "group": "刺激赋能",
        "unit": "ratio",
        "expected_min": 0.35,
        "expected_max": 1.0,
        "ideal": 0.65,
        "min_std": 0.04,
        "description": "每轮命中后实际用于消费 covered SA 能量的比例均值。它是检查刺激覆盖率缓和曲线和 transfer curve 是否过保守的直接指标。",
    },
    {
        "key": "stimulus_early_stop_object_projection_transfer_ratio_at_stop",
        "title": "对象投影早停时命中赋能/残余比",
        "group": "刺激赋能",
        "unit": "ratio",
        "expected_min": 1.0,
        "expected_max": 80.0,
        "ideal": 2.0,
        "min_std": 0.1,
        "description": "对象投影占优早停真正触发时，逐轮 selected-match 已命中赋能累计量与当时 raw tail 的比值。新版默认要求它达到 1 以上，避免只靠 memory-id 尾巴吸收让图景显得干净。",
    },
    {
        "key": "stimulus_early_stop_object_projection_transfer_guard_blocked_count",
        "title": "对象投影早停被命中赋能保护挡住次数",
        "group": "刺激赋能",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 40.0,
        "ideal": 2.0,
        "min_std": 0.5,
        "description": "对象投影已经压过未处理残余、但逐轮 selected-match 赋能还没压过 raw tail 时，被早停保护继续放行刺激级轮次的次数。它升高通常代表系统在为满足刺激级赋能验收多处理尾巴。",
    },
    {
        "key": "stimulus_anchor_owner_residual_presence_cache_hit_count",
        "title": "锚点 owner 残差存在性缓存命中数",
        "group": "刺激赋能",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 600.0,
        "ideal": 80.0,
        "min_std": 1.0,
        "diagnostic_only": True,
        "description": "刺激级锚点排序时，复用“该 owner DB 是否已有 raw/common residual entry”的本轮缓存次数。它只缓存存在性，不缓存 ER/EV、疲劳或同包重复计数。",
    },
    {
        "key": "stimulus_anchor_owner_residual_presence_scan_count",
        "title": "锚点 owner 残差存在性扫描数",
        "group": "刺激赋能",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 260.0,
        "ideal": 20.0,
        "min_std": 1.0,
        "diagnostic_only": True,
        "description": "刺激级锚点排序时，仍需要扫描 owner DB diff_table 判断是否存在 residual/common entry 的次数。它升高通常代表锚点候选多或缓存命中不足。",
    },
    {
        "key": "stimulus_object_projection_total",
        "title": "刺激级对象投影总量",
        "group": "刺激赋能",
        "unit": "energy",
        "expected_min": 0.0,
        "expected_max": 320.0,
        "ideal": 48.0,
        "min_std": 1.0,
        "description": "新版 growth 口径中，本轮完整结构/字符串种子、逐轮命中结构和残差关系结构实际投影到对象侧的 ER+EV 总量。它比 stimulus_transfer_matched_total 更接近“刺激级过程真正给对象的能量”。",
    },
    {
        "key": "stimulus_unhandled_residual_total",
        "title": "刺激级未处理净残余",
        "group": "刺激赋能",
        "unit": "energy",
        "expected_min": 0.0,
        "expected_max": 80.0,
        "ideal": 0.0,
        "min_std": 0.2,
        "description": "从 raw 最终残余中扣除已经通过 residual tail -> memory_id 并入完整记忆对象的尾巴能量后，仍没有进入对象侧的 ER+EV。新版验收优先看它，而不是把已被记忆吸收的尾巴误判为污染。",
    },
    {
        "key": "stimulus_object_projection_to_unhandled_residual_ratio",
        "title": "对象投影/净残余比",
        "group": "刺激赋能",
        "unit": "ratio",
        "expected_min": 1.0,
        "expected_max": 80.0,
        "ideal": 8.0,
        "min_std": 0.2,
        "description": "刺激级对象侧投影总量与未处理净残余的比值。多数 source tick 应大于 1；长期小于 1 才说明命中、种子投影、记忆尾巴吸收或轮次预算存在真实问题。",
    },
    {
        "key": "stimulus_memory_tail_absorbed_total",
        "title": "记忆尾巴吸收总量",
        "group": "刺激赋能",
        "unit": "energy",
        "expected_min": 0.0,
        "expected_max": 240.0,
        "ideal": 24.0,
        "min_std": 1.0,
        "description": "刺激级 raw residual tail 直接按本轮 episodic memory_id 并入完整记忆对象的 ER+EV。它代表尾巴被新版主链消费，不应再被当作状态池残余污染。",
    },
    {
        "key": "stimulus_early_stop_object_projection_dominance_triggered",
        "title": "刺激级对象占优早停",
        "group": "刺激赋能",
        "unit": "flag",
        "expected_min": 0.0,
        "expected_max": 1.0,
        "ideal": 0.35,
        "min_std": 0.05,
        "description": "当本轮完整对象投影已经明显高于剩余 raw 尾巴时，刺激级循环会停止后续低价值原子 fallback。它是性能护栏，不改变能量归属；若长期为 0，说明没有触发或阈值偏保守。",
    },
    {
        "key": "stimulus_early_stop_object_projection_dominance_ratio",
        "title": "对象占优早停比例",
        "group": "刺激赋能",
        "unit": "ratio",
        "expected_min": 1.0,
        "expected_max": 80.0,
        "ideal": 3.0,
        "min_std": 0.15,
        "description": "触发对象投影占优早停时的 object_projection_total / remaining_raw_tail。应高于配置阈值；用于判断早停是否发生在完整对象已经足够占主导之后。",
    },
    {
        "key": "internal_resolution_structure_count_selected",
        "title": "内源入选结构来源数",
        "group": "内源主导",
        "unit": "count",
        "expected_min": 3.0,
        "expected_max": 12.0,
        "ideal": 5.0,
        "min_std": 0.4,
        "description": "真正进入内源分辨率分配的结构来源数量。若长期只剩 1 到 2 个，内源内容通常会被压得过薄。",
    },
    {
        "key": "merged_flat_token_count",
        "title": "合流后 flat token 数",
        "group": "刺激负载",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 240.0,
        "ideal": 140.0,
        "min_std": 8.0,
        "description": "外源与内源合流后的扁平 token 规模，是刺激级成本的重要上游观察口径；它需要结合外源输入规模、内源供给与缓存命中一起判断，不宜直接等价成预算应当升降。",
    },
    {
        "key": "cache_residual_flat_token_count",
        "title": "中和后 flat token 数",
        "group": "刺激负载",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 220.0,
        "ideal": 120.0,
        "min_std": 8.0,
        "description": "中和之后仍需进入刺激级查存的 token 规模。",
    },
    {
        "key": "landed_flat_token_count",
        "title": "落地 flat token 数",
        "group": "刺激负载",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 220.0,
        "ideal": 120.0,
        "min_std": 8.0,
        "description": "刺激级查存后落地到状态池的 token 规模。",
    },
    {
        "key": "sensor_echo_pool_size",
        "title": "文本残响池大小",
        "group": "短时上下文",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 36.0,
        "ideal": 12.0,
        "min_std": 2.0,
        "description": "文本残响池帧数，过高说明短时上下文残响在堆积。",
    },
    {
        "key": "sensor_echo_frames_used_count",
        "title": "本 Tick 使用的残响帧数",
        "group": "短时上下文",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 4.0,
        "min_std": 1.0,
        "description": "本轮真正混入刺激包的历史残响帧数。",
    },
    {
        "key": "pool_active_item_count",
        "title": "状态池活跃条目数",
        "group": "状态池稳态",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 120.0,
        "ideal": 85.0,
        "min_std": 5.0,
        "description": "状态池的总体活跃规模。过高说明衰减、淘汰、软容量或合并不够。",
    },
    {
        "key": "pool_contextual_item_ratio",
        "title": "状态池旧上下文/来源审计占比",
        "group": "旧上下文审计",
        "unit": "ratio",
        "expected_min": 0.12,
        "expected_max": 0.78,
        "ideal": 0.34,
        "min_std": 0.03,
        "diagnostic_only": True,
        "description": "状态池中仍带 provenance / legacy context 字段的对象占比。新版正式 ST 身份由完整结构 id/root id 决定，owner/context 只作为激活来源审计；该指标不再是主链优化目标。",
    },
    {
        "key": "pool_residual_origin_item_ratio",
        "title": "状态池旧残差来源审计占比",
        "group": "旧上下文审计",
        "unit": "ratio",
        "expected_min": 0.06,
        "expected_max": 0.60,
        "ideal": 0.20,
        "min_std": 0.02,
        "diagnostic_only": True,
        "description": "状态池中仍可追溯到 legacy residual/context 来源的对象占比。默认感应生长会直接投影完整 A+B，不要求 B(context=A) 半成品入池；该指标主要用于发现旧路径残留。",
    },
    {
        "key": "pool_multi_context_item_ratio",
        "title": "状态池旧多上下文对象占比",
        "group": "旧上下文审计",
        "unit": "ratio",
        "expected_min": 0.02,
        "expected_max": 0.36,
        "ideal": 0.10,
        "min_std": 0.01,
        "diagnostic_only": True,
        "description": "状态池中同内容但挂在多个 legacy context/provenance 路径上的对象占比。新版口径下，同一完整结构不应因 owner DB 路径不同而形成多个身份；升高时优先看旧路径残留。",
    },
    {
        "key": "pool_runtime_resolution_degraded_item_count",
        "title": "运行态分辨率下降对象数",
        "group": "状态池运行态分辨率",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 120.0,
        "ideal": 12.0,
        "min_std": 1.0,
        "description": "状态池中完整 ST 身份仍保留、但部分组件能量已低于运行态显示/解释地板的对象数。这是“退化=状态池分辨率下降”的主指标，不代表 HDB 新建了退化身份。",
    },
    {
        "key": "pool_runtime_resolution_active_component_count",
        "title": "运行态仍活跃组件数",
        "group": "状态池运行态分辨率",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 900.0,
        "ideal": 180.0,
        "min_std": 8.0,
        "description": "按组件能量图景统计，当前仍高于运行态分辨率地板的组件总数。它用于解释一个完整结构在状态池里还剩多少可见细节。",
    },
    {
        "key": "pool_runtime_resolution_dropped_component_count",
        "title": "运行态淡出组件数",
        "group": "状态池运行态分辨率",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 900.0,
        "ideal": 40.0,
        "min_std": 5.0,
        "description": "按组件能量图景统计，当前低于运行态分辨率地板、只在状态池视图里淡出的组件总数。它帮助区分“对象真的消失”和“同一完整身份只剩低分辨率视图”。",
    },
    {
        "key": "maintenance_runtime_resolution_refreshed_item_count",
        "title": "维护刷新分辨率对象数",
        "group": "状态池运行态分辨率",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 240.0,
        "ideal": 40.0,
        "min_std": 2.0,
        "description": "维护阶段因衰减后组件能量变化而刷新运行态分辨率元数据的对象数。它是维护成本与退化视图是否被更新的解释指标。",
    },
    {
        "key": "maintenance_runtime_resolution_degraded_item_count",
        "title": "维护后仍降分辨率对象数",
        "group": "状态池运行态分辨率",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 180.0,
        "ideal": 16.0,
        "min_std": 2.0,
        "description": "维护刷新后仍处在降分辨率视图的对象数。它高时说明状态池里有较多完整 ST 正在以低分辨率状态维持，不应误读为 HDB 身份碎裂。",
    },
    {
        "key": "induction_total_delta_ev",
        "title": "感应赋能总虚能量增量",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 36.0,
        "ideal": 10.0,
        "min_std": 1.0,
        "description": "本轮感应赋能最终写入目标对象的总 EV 增量。它是“局部 EV 传播 + ER 诱发 EV”的总和，只看这一个值还不足以判断问题在哪条链。",
    },
    {
        "key": "induction_applied_total_ev",
        "title": "感应赋能结构直投实际落地虚能量",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 36.0,
        "ideal": 10.0,
        "min_std": 1.0,
        "description": "本轮真正成功投进状态池的结构直投 EV 总量。它只统计进入状态池的结构目标，不包含被路由到记忆激活池的 memory 目标。",
    },
    {
        "key": "induction_skipped_target_total_ev",
        "title": "感应赋能结构直投被跳过虚能量",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 0.0,
        "min_std": 0.2,
        "description": "本轮在结构直投阶段被跳过的 EV 总量。它高时，通常表示候选集合里混入了不该入池的结构，例如 CS 事件结构或纯属性结构。",
    },
    {
        "key": "induction_applied_ev_ratio",
        "title": "感应赋能结构直投落地比例",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.70,
        "expected_max": 1.00,
        "ideal": 0.92,
        "min_std": 0.03,
        "description": "实际进入状态池的结构直投 EV 与“计划投给结构目标的 EV”之比。若长期偏低，才说明结构直投阶段真的被挡住了；若 memory 目标占大头，则不应拿它去否定整条 induction 链。",
    },
    {
        "key": "induction_propagated_ev_total",
        "title": "局部传播虚能量总量",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 24.0,
        "ideal": 7.0,
        "min_std": 0.8,
        "description": "已有 EV 沿局部残差链继续扩散的总量。它更接近“旧预期续写旧预期”的传播强度。",
    },
    {
        "key": "induction_propagated_budget_total_ev",
        "title": "分层图景累计传播预算 EV",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 30.0,
        "ideal": 6.0,
        "min_std": 0.45,
        "description": "在分层能量图景 V2 口径下，所有前沿传播步骤累计拿去分配的预算 EV 总量。它高于实际落地增量是正常现象，因为它记录的是图景内所有传播预算，而不是只算最后留在状态池的那一部分。",
    },
    {
        "key": "induction_ev_from_er_total",
        "title": "ER 诱发 EV 总量",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 18.0,
        "ideal": 4.0,
        "min_std": 0.5,
        "description": "现实证据（ER）本轮拿出预算去诱发新 EV 的总量。它更接近“现实正在重新塑造预测对象”的强度。",
    },
    {
        "key": "induction_source_item_count",
        "title": "感应赋能源对象数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 4.0,
        "expected_max": 24.0,
        "ideal": 12.0,
        "min_std": 0.8,
        "description": "本轮实际被选作感应赋能源的结构对象数量。若长期很少，后续 EV 传播和 ER 诱发都会被源头供给卡住。",
    },
    {
        "key": "induction_applied_target_count",
        "title": "感应赋能结构直投实际落地目标数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 2.0,
        "expected_max": 24.0,
        "ideal": 8.0,
        "min_std": 0.6,
        "description": "本轮真正成功投影进状态池的结构目标数。它只和“结构目标数”对照才有意义，不应与 memory 目标混算。",
    },
    {
        "key": "induction_skipped_cs_event_target_count",
        "title": "感应赋能被跳过的 CS 事件目标数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 0.0,
        "ideal": 0.0,
        "min_std": 0.0,
        "description": "本轮因 CS 事件结构而在投影阶段被直接跳过的 induction 目标数。正常实验中它应尽量维持为 0。",
    },
    {
        "key": "induction_source_available_st_count",
        "title": "可用源中的 ST 数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 6.0,
        "expected_max": 36.0,
        "ideal": 16.0,
        "min_std": 1.0,
        "description": "在当前状态池里、已进入感应赋能源集合的可用对象中，其中 `ref_object_type=st` 的数量。它回答的是“本轮参与源里 ST 占多少”，而不是感应前先用 ST 做门控。",
    },
    {
        "key": "induction_source_selected_from_ev_count",
        "title": "含 EV 的参与源数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 2.0,
        "expected_max": 14.0,
        "ideal": 6.0,
        "min_std": 0.6,
        "description": "本轮实际参与感应赋能的源对象里，带有正 EV 的对象数。默认 `all_energetic_runtime` 模式下它不是“先筛出来的 EV 通道名额”，而是对已参与源对象的能量构成统计。",
    },
    {
        "key": "induction_source_selected_from_er_count",
        "title": "含 ER 的参与源数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 2.0,
        "expected_max": 14.0,
        "ideal": 6.0,
        "min_std": 0.6,
        "description": "本轮实际参与感应赋能的源对象里，带有正 ER 的对象数。默认 `all_energetic_runtime` 模式下它也是对已参与源对象的能量构成统计，而不是额外门控。",
    },
    {
        "key": "induction_source_selected_from_cp_abs_count",
        "title": "认知压回退入选源数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 8.0,
        "ideal": 0.5,
        "min_std": 0.4,
        "description": "在 EV/ER 混合选源仍不够时，回退到 `cp_abs` 通道补位的源数。若它长期偏高，说明当前混合选源预算或候选扫描范围仍不足。",
    },
    {
        "key": "induction_source_selection_cap_hit",
        "title": "感应源容量触顶标记",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.0,
        "expected_max": 0.85,
        "ideal": 0.25,
        "min_std": 0.05,
        "description": "本轮是否出现“还有可参与源对象，但感应源名额已经用满”的情况。它主要用于旧混合/限额模式，默认全池参与模式下一般应保持不触顶。",
    },
    {
        "key": "induction_source_available_with_local_target_hint_count",
        "title": "可继续传播源数（提示）",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 2.0,
        "expected_max": 24.0,
        "ideal": 8.0,
        "min_std": 0.6,
        "description": "在当前参与源集合里，背后支持结构数据库确实带着本地可用目标的 source 数量。它能帮助区分“状态池里有很多高能对象”和“这些对象真的能继续沿局部残差链传播”这两件事。",
    },
    {
        "key": "induction_source_selected_with_local_target_hint_count",
        "title": "入选可传播源数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 2.0,
        "expected_max": 16.0,
        "ideal": 6.0,
        "min_std": 0.5,
        "description": "最终被选进感应源集合、且本地候选 hint 不为 0 的 source 数量。它越高，越说明参与源名额真正花在了可继续传播的局部链路上。",
    },
    {
        "key": "induction_source_selected_zero_local_target_hint_count",
        "title": "入选空候选源数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 10.0,
        "ideal": 1.0,
        "min_std": 0.5,
        "description": "最终被选进感应源集合、但本地候选 hint 为 0 的 source 数量。若它长期偏高，说明高能 source 虽多，但不少 source 其实没有可用 diff_table 目标，属于白占名额。",
    },
    {
        "key": "induction_raw_residual_entry_count",
        "title": "原始残差条目数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 18.0,
        "ideal": 4.0,
        "min_std": 0.5,
        "description": "本轮参与感应赋能局部候选聚合的 `stimulus_raw_residual` 条目数。它回答的是“当前 residual/context 局部链本身有没有被看见”。",
    },
    {
        "key": "induction_raw_residual_entry_with_existing_structure_count",
        "title": "原始残差命中已存结构条目数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 2.0,
        "min_std": 0.4,
        "description": "这些原始残差条目里，有多少条的 canonical signature 已经能在 HDB 中找到现成结构。它是判断“是不是其实早就有结构，只是过去没被用上”的核心口径。",
    },
    {
        "key": "induction_raw_residual_entry_routed_to_structure_count",
        "title": "原始残差实际转结构条目数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 2.0,
        "min_std": 0.4,
        "description": "命中现成结构之后，最终真的把一部分权重分流到结构路径的原始残差条目数。若前一项高、这一项低，说明结构分流开关或比例仍太保守。",
    },
    {
        "key": "induction_raw_residual_existing_structure_target_count",
        "title": "原始残差结构候选数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 18.0,
        "ideal": 3.0,
        "min_std": 0.4,
        "description": "原始残差在本轮最终选中的“现成结构目标”总数。它更像 fanout 规模，适合判断 residual->structure 是否过于单薄或过于发散。",
    },
    {
        "key": "induction_raw_residual_entry_with_component_structure_count",
        "title": "原始残差命中组分结构条目数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 18.0,
        "ideal": 2.0,
        "min_std": 0.4,
        "description": "full-signature exact miss 后，仍能在 grouped component 级别命中既有结构的原始残差条目数。它回答的是“整体签名太新，但局部块是否已经沉淀下来”。",
    },
    {
        "key": "induction_raw_residual_entry_routed_to_component_structure_count",
        "title": "原始残差实际转组分结构条目数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 18.0,
        "ideal": 2.0,
        "min_std": 0.4,
        "description": "命中 grouped component 结构后，最终真的把权重分流给组分结构路径的条目数。若前一项高、这一项低，说明 component fallback 没有真正接上预算链。",
    },
    {
        "key": "induction_raw_residual_component_structure_target_count",
        "title": "原始残差组分结构候选数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 24.0,
        "ideal": 4.0,
        "min_std": 0.5,
        "description": "component fallback 最终保留下来的组分结构候选总数。它更像 grouped fanout 规模，用来判断 component path 是否太窄或太散。",
    },
    {
        "key": "induction_target_count",
        "title": "感应赋能目标数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 1.0,
        "expected_max": 36.0,
        "ideal": 9.0,
        "min_std": 0.8,
        "description": "本轮所有感应赋能目标对象的总数。若源很多但目标依旧稀薄，说明局部残差库或 ER 诱发链本身没有打开。",
    },
    {
        "key": "induction_structure_target_count",
        "title": "感应赋能结构目标数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 1.0,
        "expected_max": 18.0,
        "ideal": 4.0,
        "min_std": 0.5,
        "description": "本轮被路由到状态池结构直投路径的目标数。它和 memory 目标数分开看，才能判断当前 induction 更偏“直接入池”还是“先进入记忆激活池”。",
    },
    {
        "key": "induction_memory_target_count",
        "title": "感应赋能记忆目标数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 24.0,
        "ideal": 5.0,
        "min_std": 0.5,
        "description": "本轮被路由到记忆激活池的 memory 目标数。它高并不代表结构直投失败，而是说明本轮 induction 更多沿记忆路径展开。",
    },
    {
        "key": "induction_raw_residual_structure_target_count",
        "title": "原始残差结构目标数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 18.0,
        "ideal": 2.0,
        "min_std": 0.4,
        "description": "本轮真正承接到原始残差贡献的结构目标数。它和上面的 `结构候选数` 不同：这里只统计最后确实拿到了 residual 权重的目标。",
    },
    {
        "key": "induction_raw_residual_memory_target_count",
        "title": "原始残差记忆目标数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 0.0,
        "ideal": 0.0,
        "min_std": 0.0,
        "description": "本轮真正承接到原始残差贡献的记忆目标数。它高而结构目标低，表示原始残差仍主要沿 memory path 回流。",
    },
    {
        "key": "induction_structure_target_total_ev",
        "title": "感应赋能结构目标计划 EV",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 18.0,
        "ideal": 4.0,
        "min_std": 0.5,
        "description": "本轮计划投给结构直投路径的 EV 总量。应与“结构直投实际落地虚能量”对照，不应再和 memory 目标的 EV 混算。",
    },
    {
        "key": "induction_memory_target_total_ev",
        "title": "感应赋能记忆目标计划 EV",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 24.0,
        "ideal": 6.0,
        "min_std": 0.6,
        "description": "本轮计划投给记忆激活池路径的 EV 总量。它高时，往往表示本轮 induction 更偏向先强化记忆对象，而不是直接向状态池投影结构。",
    },
    {
        "key": "induction_raw_residual_structure_target_total_ev",
        "title": "原始残差转结构 EV",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 1.6,
        "min_std": 0.25,
        "description": "在原始残差子路径中，最终被分给现成结构目标的 EV 总量。它直接衡量“原始残差是否真的续写到了已有结构”。",
    },
    {
        "key": "induction_raw_residual_exact_structure_target_total_ev",
        "title": "原始残差完整签名结构 EV",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 10.0,
        "ideal": 1.0,
        "min_std": 0.2,
        "description": "原始残差结构路径里，真正来自 full-signature exact reuse 的 EV。它低而 component EV 高时，通常说明整体 residual 过新，但局部块已经可复用。",
    },
    {
        "key": "induction_raw_residual_component_structure_target_total_ev",
        "title": "原始残差组分回退结构 EV",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 10.0,
        "ideal": 1.0,
        "min_std": 0.2,
        "description": "原始残差结构路径里，来自 grouped-component fallback 的 EV。它升高通常表示局部块沉淀已够，但完整 residual 级别的复用仍偏稀疏。",
    },
    {
        "key": "induction_raw_residual_memory_target_total_ev",
        "title": "原始残差转记忆 EV",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.0,
        "ideal": 0.0,
        "min_std": 0.0,
        "description": "在原始残差子路径中，仍然留在 episodic memory 目标上的 EV 总量。它与 `原始残差转结构 EV` 一起刻画 residual 双路径的真实分流。",
    },
    {
        "key": "induction_structure_target_ev_share",
        "title": "感应赋能结构路径 EV 占比",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.10,
        "expected_max": 0.85,
        "ideal": 0.35,
        "min_std": 0.04,
        "description": "总 induction EV 中，被分配给结构直投路径的占比。它低并不等于出错，而是说明本轮更多在走 memory path。",
    },
    {
        "key": "induction_memory_target_ev_share",
        "title": "感应赋能记忆路径 EV 占比",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.15,
        "expected_max": 0.90,
        "ideal": 0.45,
        "min_std": 0.04,
        "description": "总 induction EV 中，被分配给记忆激活池路径的占比。它和结构路径占比一起看，才能正确解释为何某些 run 的结构直投量看起来不高。",
    },
    {
        "key": "induction_raw_residual_exact_structure_budget_weight",
        "title": "原始残差完整签名结构预算权重",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 1.0,
        "min_std": 0.2,
        "description": "原始残差结构预算中，分给 full-signature exact reuse 的那部分预算权重。",
    },
    {
        "key": "induction_raw_residual_component_structure_budget_weight",
        "title": "原始残差组分回退结构预算权重",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 1.0,
        "min_std": 0.2,
        "description": "原始残差结构预算中，分给 grouped-component fallback 的那部分预算权重。若 component 命中已有数据而这里长期为 0，说明回退命中了但预算没有接上。",
    },
    {
        "key": "induction_raw_residual_entry_materialized_structure_count",
        "title": "原始残差现场补建结构条目数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 1.0,
        "min_std": 0.3,
        "diagnostic_only": True,
        "description": "原始残差未命中现成结构、但通过查存一体现场补建结构 ID 的条目数。它用来确认默认主路是否真的走“纯结构化补建”，而不是回落旧 memory 分流。",
    },
    {
        "key": "induction_raw_residual_materialized_structure_target_count",
        "title": "原始残差现场补建结构目标数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 18.0,
        "ideal": 2.0,
        "min_std": 0.4,
        "diagnostic_only": True,
        "description": "本轮真正承接到 raw residual 预算、且来源于现场补建结构的目标数。它能区分“只是补建了 ID”与“补建后真的进入了赋能链”。",
    },
    {
        "key": "induction_raw_residual_materialized_structure_budget_weight",
        "title": "原始残差现场补建结构预算权重",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 0.8,
        "min_std": 0.2,
        "diagnostic_only": True,
        "description": "分给现场补建结构路径的预算权重总量。它主要用于审计 raw residual 在 exact miss 时，是否把预算转给了新结构主路。",
    },
    {
        "key": "induction_propagated_target_count",
        "title": "局部传播目标数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 24.0,
        "ideal": 5.0,
        "min_std": 0.5,
        "description": "由已有 EV 沿局部残差链直接传播命中的目标数。它偏低时，更可能是局部 residual path 太薄，而不是单纯预算太小。",
    },
    {
        "key": "induction_induced_target_count",
        "title": "ER 诱发目标数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 24.0,
        "ideal": 4.0,
        "min_std": 0.5,
        "description": "由现实证据 ER 直接诱发出来的目标数。它偏高说明系统当前更依赖现实重估，偏低则说明更多沿旧预期链局部续写。",
    },
    {
        "key": "induction_targets_per_source_mean",
        "title": "每源平均目标数",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.20,
        "expected_max": 3.20,
        "ideal": 1.00,
        "min_std": 0.08,
        "description": "平均每个实际参与的感应源对象能在本轮拉起多少目标对象。它适合判断“源是有了，但局部 residual fanout 还是太薄”的情况。",
    },
    {
        "key": "induction_propagated_target_ratio",
        "title": "局部传播目标占比",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.20,
        "expected_max": 0.95,
        "ideal": 0.62,
        "min_std": 0.03,
        "description": "感应赋能目标中，由已有 EV 沿局部残差链传播得到的目标占比。偏高说明系统更依赖局部续写，偏低则说明更多依赖 ER 重新诱发。",
    },
    {
        "key": "induction_ev_from_er_ratio",
        "title": "ER 诱发 EV 占比",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.05,
        "expected_max": 0.80,
        "ideal": 0.32,
        "min_std": 0.03,
        "description": "本轮新增 EV 中，由现实证据 ER 直接诱发出来的占比。它有助于判断系统的预测更新主要来自“现实重估”，还是“旧预测续写”。",
    },
    {
        "key": "induction_energy_graph_v2_enabled",
        "title": "分层能量图景 V2 开关",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 1.0,
        "ideal": 1.0,
        "min_std": 0.01,
        "description": "该 tick 是否启用了分层能量图景 V2 主路径。它为 1 时，后面的轮数、深度、前沿与预算指标才有理论解释意义。",
    },
    {
        "key": "induction_energy_graph_round_count_max",
        "title": "分层能量图景最大轮数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 8.0,
        "ideal": 3.0,
        "min_std": 0.20,
        "description": "本轮所有源对象里，真正展开到的最大轮数。它高说明根源 ER 并非只在首轮起作用，而是能持续再诱发后续轮次。",
    },
    {
        "key": "induction_energy_graph_depth_max",
        "title": "分层能量图景最大深度",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 8.0,
        "ideal": 2.0,
        "min_std": 0.20,
        "description": "本轮图景真正触及的最深残差层级。它偏高时更接近“逐层探索更深结构”的理论图景，而不是只在一层相邻结构上打转。",
    },
    {
        "key": "induction_energy_graph_frontier_generated_count",
        "title": "分层能量图景前沿生成数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 64.0,
        "ideal": 8.0,
        "min_std": 0.50,
        "description": "图景 V2 过程中累计生成的前沿节点数。它高说明递归分形已经展开；若它始终很低，通常是目标 Top-K、最小预算或前沿 EV 门槛太保守。",
    },
    {
        "key": "induction_energy_graph_frontier_pruned_count",
        "title": "分层能量图景前沿剪枝数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 64.0,
        "ideal": 2.0,
        "min_std": 0.40,
        "description": "图景 V2 中因 EV 太低、预算太小或前沿容量受限而被提前剪掉的前沿节点数。它不是越低越好；适度剪枝是防止状态池指数膨胀的必要代价。",
    },
    {
        "key": "induction_energy_graph_terminal_memory_count",
        "title": "分层能量图景终端记忆数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 32.0,
        "ideal": 2.0,
        "min_std": 0.30,
        "description": "图景 V2 中最终落到“没有更深数据库可继续展开”的终端记忆残差节点数量。它上升通常表示图景确实已经钻到了更深层的末梢。",
    },
    {
        "key": "induction_energy_graph_root_reinduction_count",
        "title": "分层能量图景根源再诱发次数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 8.0,
        "ideal": 3.0,
        "min_std": 0.20,
        "description": "图景 V2 中，根源对象在多轮中再次用剩余 ER 去诱发一级结构的次数。它是“同一 ER 根源多轮持续诱发”是否真正发生的最直接证据之一。",
    },
    {
        "key": "induction_energy_graph_layer_count",
        "title": "分层能量图景层数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 8.0,
        "ideal": 2.0,
        "min_std": 0.20,
        "description": "本轮图景中至少出现过一个节点的层数。它与最大深度相近，但更强调“到底有多少层真的长出来了”。",
    },
    {
        "key": "induction_energy_graph_layer_max_width",
        "title": "分层能量图景最大层宽",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 32.0,
        "ideal": 4.0,
        "min_std": 0.35,
        "description": "图景中单层同时存活的最大节点数。它反映分形图景是否形成真正的横向扇出，而不是只做细窄的纵向链式递归。",
    },
    {
        "key": "induction_energy_graph_layer_total_nodes",
        "title": "分层能量图景层节点总数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 96.0,
        "ideal": 12.0,
        "min_std": 0.60,
        "description": "图景 V2 所有层累计出现过的节点总数。它与最大层宽一起看，才能区分“宽而浅”和“窄而深”两种完全不同的图景形态。",
    },
    {
        "key": "induction_energy_graph_round_summary_count",
        "title": "分层能量图景轮摘要数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 8.0,
        "ideal": 3.0,
        "min_std": 0.20,
        "description": "图景 V2 为多少轮生成了可审计的轮摘要。它通常与最大轮数接近，用于快速判断后端是否真的跑完了多轮递归。",
    },
    {
        "key": "induction_energy_graph_frontier_budget_total_ev",
        "title": "分层能量图景前沿预算 EV",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 24.0,
        "ideal": 4.0,
        "min_std": 0.35,
        "description": "图景 V2 中累计分给前沿节点继续向下展开的 EV 预算总量。它高说明递归传播预算充足；低则说明图景大多停在根源再诱发附近。",
    },
    {
        "key": "induction_energy_graph_root_induction_budget_total_ev",
        "title": "分层能量图景根源再诱发预算 EV",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 20.0,
        "ideal": 3.0,
        "min_std": 0.30,
        "description": "图景 V2 中，根源对象在多轮里再次拿出来诱发一级结构的 EV 预算总量。它高说明现实证据 ER 的续航性更强。",
    },
    {
        "key": "induction_energy_graph_round_delta_ev_total",
        "title": "分层能量图景轮增量 EV 总和",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 24.0,
        "ideal": 5.0,
        "min_std": 0.35,
        "description": "图景 V2 所有轮次合计实际拉起的增量 EV。它是理论图景有没有真正“做出工作”的一个直接总量指标。",
    },
    {
        "key": "induction_energy_graph_round_delta_ev_max",
        "title": "分层能量图景单轮最大增量 EV",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 1.5,
        "min_std": 0.20,
        "description": "图景 V2 某一轮内出现过的最大 EV 增量。它高表示至少有某一轮形成了清晰的能量波峰，但也要结合末轮增量看是不是只是一拍爆发。",
    },
    {
        "key": "induction_energy_graph_round_delta_ev_last",
        "title": "分层能量图景末轮增量 EV",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 0.8,
        "min_std": 0.15,
        "description": "图景 V2 最后一轮仍然贡献的 EV 增量。它越高，越说明图景并非在前一两轮就完全熄火。",
    },
    {
        "key": "induction_energy_graph_frontier_in_count_max",
        "title": "分层能量图景单轮最大前沿输入数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 32.0,
        "ideal": 4.0,
        "min_std": 0.30,
        "description": "图景 V2 中单轮收到的最大前沿输入节点数。它适合判断某一层之前已经积累了多少可继续展开的候选。",
    },
    {
        "key": "induction_energy_graph_frontier_out_count_max",
        "title": "分层能量图景单轮最大前沿输出数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 32.0,
        "ideal": 4.0,
        "min_std": 0.30,
        "description": "图景 V2 中单轮实际生成的最大前沿输出节点数。它与前沿输入数配合，可直接看出扇出有没有形成、以及是否被 Top-K 或门槛压扁。",
    },
    {
        "key": "pool_ev_to_er_ratio",
        "title": "虚实能量比（EV/ER，诊断口径）",
        "group": "能量传播（诊断）",
        "unit": "ratio",
        "expected_min": 1.02,
        "expected_max": 1.30,
        "ideal": 1.10,
        "min_std": 0.04,
        "description": "状态池虚能量与实能量的比值。当前默认新口径里，它主要是诊断视角，不再作为必须直接闭环追踪的硬目标；若长期明显偏低，更适合解读为“预测链整体偏薄”，再继续分解到传播、诱发或保活环节。",
    },
    {
        "key": "energy_balance_ratio_smooth",
        "title": "能量平衡平滑虚实比（旧闭环）",
        "group": "能量传播（诊断）",
        "unit": "ratio",
        "expected_min": 1.00,
        "expected_max": 1.30,
        "ideal": 1.10,
        "min_std": 0.03,
        "description": "控制器真正用于调节的平滑 EV/ER 比值。它比即时比值更适合判断闭环是否朝理论预期收敛。",
    },
    {
        "key": "energy_balance_g_after",
        "title": "能量平衡控制增益",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.55,
        "expected_max": 1.80,
        "ideal": 1.00,
        "min_std": 0.04,
        "description": "能量平衡控制器的实际输出增益。长期贴着上限或下限都说明主链与目标之间存在持续张力，可能需要回查基础传播参数而不只是继续积分。",
    },
    {
        "key": "energy_balance_ev_propagation_ratio_scale",
        "title": "能量平衡 EV 传播缩放",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.55,
        "expected_max": 1.80,
        "ideal": 1.00,
        "min_std": 0.04,
        "description": "控制器写回 HDB 的 EV 传播缩放。它高说明系统正在主动拉高预测扩散链，高得过久则可能意味着主链供给仍不足。",
    },
    {
        "key": "energy_balance_er_induction_ratio_scale",
        "title": "能量平衡 ER 诱发缩放",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 0.55,
        "expected_max": 1.80,
        "ideal": 1.00,
        "min_std": 0.04,
        "description": "控制器写回 HDB 的 ER 诱发 EV 缩放。它用于观察控制器是否同时在“现实证据 -> 新预期”这条链上出手。",
    },
    {
        "key": "hdb_requested_ev_propagation_ratio",
        "title": "HDB 请求 EV 传播比例",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.20,
        "expected_max": 1.00,
        "ideal": 0.55,
        "min_std": 0.03,
        "description": "本 tick 准备写入 HDB 的 EV 传播比例（截断前）。若它长期高于实际生效值，说明控制器已把请求推高，但诱发引擎的比例上限正在截断它。",
    },
    {
        "key": "hdb_effective_ev_propagation_ratio",
        "title": "HDB 实际 EV 传播比例",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.20,
        "expected_max": 1.00,
        "ideal": 0.55,
        "min_std": 0.03,
        "description": "本 tick 感应赋能引擎真正吃进去的 EV 传播比例（已考虑运行时截断）。若它贴在 1.0 而虚能量仍起不来，瓶颈就不在控制器是否出手，而在更下游的拓扑、落地或保活链。",
    },
    {
        "key": "hdb_requested_er_induction_ratio",
        "title": "HDB 请求 ER 诱发比例",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.15,
        "expected_max": 1.00,
        "ideal": 0.45,
        "min_std": 0.03,
        "description": "本 tick 准备写入 HDB 的 ER 诱发 EV 比例（截断前）。它高而实际值低，说明控制器请求已撞上运行时上限。",
    },
    {
        "key": "hdb_effective_er_induction_ratio",
        "title": "HDB 实际 ER 诱发比例",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.15,
        "expected_max": 1.00,
        "ideal": 0.45,
        "min_std": 0.03,
        "description": "本 tick 感应赋能引擎真正采用的 ER->EV 诱发比例（已考虑运行时截断）。它回答的是“现实证据究竟有多少被允许转成新预期预算”。",
    },
    {
        "key": "stimulus_new_structure_count",
        "title": "刺激级新结构创建数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.12,
        "expected_max": 6.0,
        "ideal": 1.0,
        "min_std": 0.05,
        "description": "本 tick 在刺激级查存一体中新创建的结构数量。长期为 0 说明学习停滞，长期过高则通常意味着阈值过松、碎片化或噪声被过度固化。",
    },
    {
        "key": "pool_high_cp_item_count",
        "title": "高认知压条目数",
        "group": "状态池稳态",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 48.0,
        "ideal": 24.0,
        "min_std": 3.0,
        "description": "长期高位意味着冲突长期得不到中和。",
    },
    {
        "key": "pool_total_cp",
        "title": "状态池认知压总量",
        "group": "状态池稳态",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 92.0,
        "ideal": 68.0,
        "min_std": 4.0,
        "description": "总体认知压。理论上应随预测-现实中和而起伏，而非长期单边抬升。",
    },
    {
        "key": "pool_total_er",
        "title": "状态池总实能量",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 60.0,
        "expected_max": 260.0,
        "ideal": 130.0,
        "min_std": 3.0,
        "description": "状态池当前实能量总量。它主要反映现实证据在池中的总体维持水平，过低常见于证据保活过弱，过高则常见于衰减或剪枝不够。",
    },
    {
        "key": "pool_total_ev",
        "title": "状态池总虚能量",
        "group": "能量传播",
        "unit": "number",
        "expected_min": 60.0,
        "expected_max": 320.0,
        "ideal": 150.0,
        "min_std": 3.0,
        "description": "状态池当前虚能量总量。它近似表示当前预期图景的总预算，既不应长期压不过实能量，也不应无限喧宾夺主。",
    },
    {
        "key": "pool_energy_injection_throttle_ratio_total",
        "title": "状态池正向赋能节流比例",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.0,
        "expected_max": 0.45,
        "ideal": 0.12,
        "min_std": 0.01,
        "description": "本 tick 正向 ER/EV 注入因对象已有能量和重复注入疲劳而被缩小的比例。长期为 0 说明保护没参与，长期过高说明赋能被压得太狠。",
    },
    {
        "key": "pool_energy_injection_side_hit_count",
        "title": "状态池正向赋能节流侧次数",
        "group": "能量传播",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 80.0,
        "ideal": 8.0,
        "min_std": 0.0,
        "description": "本 tick 有多少个 ER/EV 注入侧被节流，用于判断注入疲劳是否正在参与能量稳定。",
    },
    {
        "key": "pool_energy_injection_min_scale",
        "title": "状态池正向赋能最小应用比例",
        "group": "能量传播",
        "unit": "ratio",
        "expected_min": 0.18,
        "expected_max": 1.0,
        "ideal": 0.72,
        "min_std": 0.02,
        "description": "本 tick 所有正向注入中最低的实际应用比例。接近下限表示某些对象已经明显饱和或重复疲劳。",
    },
    {
        "key": "cam_item_count",
        "title": "当前注意记忆体条目数",
        "group": "注意力负载",
        "unit": "count",
        "expected_min": 1.0,
        "expected_max": 18.0,
        "ideal": 6.0,
        "min_std": 1.0,
        "description": "注意力真正带走的对象数，过低会抽空，过高会放大后续成本。",
    },
    {
        "key": "attention_state_pool_candidate_count",
        "title": "注意力候选条目数",
        "group": "注意力负载",
        "unit": "count",
        "expected_min": 1.0,
        "expected_max": 64.0,
        "ideal": 24.0,
        "min_std": 2.0,
        "description": "进入注意力竞争的候选规模，过大说明前级筛选太松。",
    },
    {
        "key": "attention_consumed_total_energy",
        "title": "注意力抽取消耗",
        "group": "注意力负载",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 20.0,
        "ideal": 12.0,
        "min_std": 1.0,
        "description": "形成 CAM 时从状态池真实抽走的能量。",
    },
    {
        "key": "attention_energy_budget",
        "title": "注意力能量资源预算",
        "group": "注意力负载",
        "unit": "number",
        "expected_min": 3.0,
        "expected_max": 18.0,
        "ideal": 8.0,
        "min_std": 1.4,
        "description": "本 tick 注意力滤波允许的净增能量预算。它应作为有限资源被分配，而不是作为倍率无限放大。",
    },
    {
        "key": "attention_net_delta_energy",
        "title": "注意力滤波净增能量",
        "group": "注意力负载",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 11.0,
        "ideal": 6.5,
        "min_std": 1.2,
        "description": "滤波后 CAM 总能量减去未滤波基础 CAM 能量。长期过高会推高状态池能量，过低则可能无法和半衰期衰减形成平静拮抗。",
    },
    {
        "key": "attention_suppressed_total_energy",
        "title": "注意力抑制能量",
        "group": "注意力负载",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 80.0,
        "ideal": 8.0,
        "min_std": 0.5,
        "description": "注意力滤波从低权重 CAM 对象中抑制掉的能量。它用于解释为什么净增不等于原始预算。",
    },
    {
        "key": "attention_structure_carrier_selected_count",
        "title": "注意力选中承载结构数",
        "group": "注意力负载",
        "unit": "count",
        "expected_min": 0.4,
        "expected_max": 8.0,
        "ideal": 2.0,
        "min_std": 0.20,
        "description": "本 tick 被注意力选中的、携带奖励/惩罚/认知感受等特殊信息的结构对象数量。它应成为注意力把特殊信号带回锚点与上下文的主要通道，而不是让裸属性节点长期霸榜。",
    },
    {
        "key": "attention_standalone_special_selected_count",
        "title": "注意力选中裸特殊节点数",
        "group": "注意力负载",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 1.2,
        "ideal": 0.25,
        "min_std": 0.10,
        "description": "本 tick 被注意力直接选中的裸奖励/惩罚/认知感受/行动等特殊节点数量。允许短时出现，但不应长期高于承载它们的结构对象，否则说明注意力被抽象标签劫持。",
    },
    {
        "key": "attention_repeat_penalty_total",
        "title": "重复注意疲劳总惩罚",
        "group": "注意力负载",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 6.0,
        "ideal": 1.4,
        "min_std": 0.20,
        "description": "本 tick 对重复注意对象累计施加的疲劳惩罚。它不宜长期为 0，否则说明系统难以摆脱短时重复；也不宜长期过高，否则说明系统被过度压制、难以维持必要专注。",
    },
    {
        "key": "cfs_dissonance_max",
        "title": "违和感峰值",
        "group": "认知感受",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.45,
        "ideal": 0.18,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.18,
        "high_band_soft_p95": 0.68,
        "high_band_max_run": 3,
        "description": "违和应存在但不应常驻爆炸。常态宜落在低于半量程的波动带内，0.5 以上高位应只占较小比例，主要留给明确冲突和强外界事件。",
    },
    {
        "key": "cfs_pressure_max",
        "title": "压力峰值",
        "group": "认知感受",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.55,
        "ideal": 0.22,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.22,
        "high_band_soft_p95": 0.72,
        "high_band_max_run": 4,
        "description": "压力应更多由惩罚预测结构驱动，而不是脚本噪声常驻。常态建议保持在半量程以下，仅在强惩罚、强违和或明显失败事件下短时抬高。",
    },
    {
        "key": "cfs_pressure_live_active",
        "title": "压力运行态激活标记",
        "group": "认知感受",
        "unit": "flag",
        "expected_min": 0.0,
        "expected_max": 1.0,
        "ideal": 0.0,
        "min_std": 0.0,
        "description": "1 表示状态池里当前仍存在 pressure 绑定；它描述的是“旧压力是否还在持续”，不是本 tick 是否新触发。",
    },
    {
        "key": "cfs_pressure_decay_only",
        "title": "压力仅持续未新触发标记",
        "group": "认知感受",
        "unit": "flag",
        "expected_min": 0.0,
        "expected_max": 1.0,
        "ideal": 0.0,
        "min_std": 0.0,
        "description": "1 表示本 tick 没有新 pressure 信号，但旧 pressure 仍在运行态中衰减维持；用于区分“没触发”和“仍在持续”。",
    },
    {
        "key": "cfs_expectation_max",
        "title": "期待峰值",
        "group": "认知感受",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.55,
        "ideal": 0.22,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.22,
        "high_band_soft_p95": 0.72,
        "high_band_max_run": 4,
        "description": "期待应来自奖励预测而不是到处贴标签。默认哲学不是把它压成固定点值，而是让常态落在低到中位带，高位主要留给强验证和明确奖励窗口。",
    },
    {
        "key": "cfs_correct_event_count",
        "title": "正确事件计数",
        "group": "认知感受",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 0.35,
        "ideal": 0.10,
        "min_std": 0.02,
        "description": "正确事件应依托违和显著下降而出现，不应早期密集、后期麻木。",
    },
    {
        "key": "cs_narrative_top_grasp",
        "title": "事件把握感（主叙事 ES）",
        "group": "认知拼接",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.70,
        "ideal": 0.32,
        "min_std": 0.05,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.25,
        "high_band_soft_p95": 0.78,
        "high_band_max_run": 4,
        "diagnostic_only": True,
        "description": "对旧 CS 叙事事件绑定的 event_grasp 数值。默认 growth 主链下叙事连续性优先看状态池 Top、感应生长 A+B 和内源刺激重采样；该项只服务 residual/CS 回滚诊断。",
    },
    {
        "key": "cs_event_grasp_emitted_count",
        "title": "事件把握感发射次数",
        "group": "认知拼接",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 1.8,
        "ideal": 0.45,
        "min_std": 0.05,
        "diagnostic_only": True,
        "description": "旧 CS 事件真正完成 event_grasp 绑定的数量。默认 growth 主链不追求该项非零，只有显式开启 CS 时才用于区分候选、动作与叙事把握是否接通。",
    },
    {
        "key": "cs_event_grasp_selected_event_count",
        "title": "事件把握感入选事件数",
        "group": "认知拼接",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 2.2,
        "ideal": 0.70,
        "min_std": 0.06,
        "diagnostic_only": True,
        "description": "进入旧 CS event_grasp 最终评估的事件对象数。新版默认只把它当回滚/对照诊断，不用它判断 growth 叙事是否失败。",
    },
    {
        "key": "cs_event_grasp_cam_seed_count",
        "title": "事件把握感 CAM 焦点种子数",
        "group": "认知拼接",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 2.5,
        "ideal": 0.60,
        "min_std": 0.05,
        "diagnostic_only": True,
        "description": "来自旧 CAM 的 CS 事件把握感候选种子数。默认 growth 主链下可为 0，不代表内源刺激重采样或状态池长对象叙事缺失。",
    },
    {
        "key": "cs_event_grasp_post_action_seed_count",
        "title": "事件把握感后拼接焦点种子数",
        "group": "认知拼接",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 2.5,
        "ideal": 0.55,
        "min_std": 0.05,
        "diagnostic_only": True,
        "description": "来自本 tick 旧 CS 新建/强化事件动作的 grasp 焦点种子数。只用于 residual/CS 对照，不再是默认主链的叙事验收目标。",
    },
    {
        "key": "cs_event_grasp_cam_selected_event_count",
        "title": "事件把握感 CAM 实际入选数",
        "group": "认知拼接",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 1.8,
        "ideal": 0.35,
        "min_std": 0.04,
        "diagnostic_only": True,
        "description": "真正来自旧 CAM 且通过事件识别、能量阈值筛选的 CS grasp 入选事件数。默认主链下它是折叠诊断。",
    },
    {
        "key": "cs_event_grasp_post_action_selected_event_count",
        "title": "事件把握感后拼接实际入选数",
        "group": "认知拼接",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 1.8,
        "ideal": 0.35,
        "min_std": 0.04,
        "diagnostic_only": True,
        "description": "真正来自 post-CS action focus 且通过事件识别、能量阈值筛选的 CS grasp 入选事件数。默认主链不要求 post-CS action focus 存在。",
    },
    {
        "key": "cs_candidate_count",
        "title": "认知拼接候选数",
        "group": "认知拼接",
        "unit": "count",
        "expected_min": 0.8,
        "expected_max": 10.0,
        "ideal": 3.5,
        "min_std": 0.20,
        "diagnostic_only": True,
        "description": "本 tick 进入旧 CS 评分阶段的候选总数。默认 growth 主链下 CS 关闭时它为 0 是正常状态，不应驱动调参器去打开候选供给。",
    },
    {
        "key": "cs_action_count",
        "title": "认知拼接动作数",
        "group": "认知拼接",
        "unit": "count",
        "expected_min": 1.0,
        "expected_max": 3.4,
        "ideal": 2.2,
        "min_std": 0.18,
        "diagnostic_only": True,
        "description": "本 tick 真正落地的旧 CS 动作数量。当前默认哲学不再要求每 tick 保持 CS 动作，整体化联想应通过内源刺激重新进入刺激级查存一体完成。",
    },
    {
        "key": "cs_candidate_rejected_low_score_count",
        "title": "认知拼接低分淘汰数",
        "group": "认知拼接",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 6.0,
        "ideal": 1.8,
        "min_std": 0.15,
        "diagnostic_only": True,
        "description": "旧 CS 候选通过基础合法性检查后，因总分低于最低阈值而被刷掉的数量。只在显式开启 CS 时用于诊断门槛，不作为默认 growth 主链目标。",
    },
    {
        "key": "cs_candidate_rejected_v2_low_score_count",
        "title": "认知拼接 V2 低分淘汰数",
        "group": "认知拼接",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 6.0,
        "ideal": 1.4,
        "min_std": 0.10,
        "diagnostic_only": True,
        "description": "当旧 `context_match_v2` 参与 CS 执行时，候选因 V2 综合分数低于阈值而被淘汰的数量。默认 growth 主链不靠它做组合。",
    },
    {
        "key": "cs_candidate_threshold_margin_mean",
        "title": "认知拼接平均阈值余量",
        "group": "认知拼接",
        "unit": "score",
        "expected_min": 0.02,
        "expected_max": 0.40,
        "ideal": 0.16,
        "min_std": 0.02,
        "diagnostic_only": True,
        "description": "旧 CS 通过候选相对于最低阈值多出来的平均分差。默认 growth 主链下它只是回滚/对照口径，不用于追求 CS 活跃。",
    },
    {
        "key": "rwd_pun_rwd",
        "title": "系统奖励信号",
        "group": "奖惩调制",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.60,
        "ideal": 0.24,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.20,
        "high_band_soft_p95": 0.72,
        "high_band_max_run": 3,
        "description": "系统内部奖励汇总。大多数时候应停留在低于半量程的常态带内，0.5 以上的高位主要保留给外界明确奖励、教师强化和强验证后的短时峰值。",
    },
    {
        "key": "rwd_pun_pun",
        "title": "系统惩罚信号",
        "group": "奖惩调制",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.60,
        "ideal": 0.20,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.18,
        "high_band_soft_p95": 0.70,
        "high_band_max_run": 3,
        "description": "系统内部惩罚汇总。默认应保持稀疏而可分层，不应长期贴在高位；高位区主要保留给明显错误、失败反馈和强违和事件。",
    },
    {
        "key": "nt_DA",
        "title": "多巴胺通道强度",
        "group": "情绪递质",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.70,
        "ideal": 0.28,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.30,
        "high_band_soft_p95": 0.80,
        "high_band_max_run": 5,
        "description": "DA 允许比纯奖惩信号稍宽的活动带，但常态仍宜低于半量程。高位区应更多服务于明显正向驱动、强验证和高显著性机会。",
    },
    {
        "key": "nt_ADR",
        "title": "肾上腺素通道强度",
        "group": "情绪递质",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.55,
        "ideal": 0.18,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.16,
        "high_band_soft_p95": 0.68,
        "high_band_max_run": 3,
        "description": "ADR 适合低基线、较短脉冲。常态应明显低于半量程，仅在突发外界压力、紧迫行动或教师性强刺激下短时抬升。",
    },
    {
        "key": "nt_COR",
        "title": "皮质醇通道强度",
        "group": "情绪递质",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.55,
        "ideal": 0.16,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.16,
        "high_band_soft_p95": 0.68,
        "high_band_max_run": 3,
        "description": "COR 主要反映压力和耗竭侧背景。默认不应长期高位，否则会压缩系统区分一般波动与强事件的能力。",
    },
    {
        "key": "nt_SER",
        "title": "血清素通道强度",
        "group": "情绪递质",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.70,
        "ideal": 0.30,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.35,
        "high_band_soft_p95": 0.82,
        "high_band_max_run": 6,
        "description": "SER 可允许比压力型通道更宽、更慢的稳态带，但仍不建议把高位常态化；高位区应保留给明显稳定、修复或满足后的持续窗口。",
    },
    {
        "key": "nt_OXY",
        "title": "催产素通道强度",
        "group": "情绪递质",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.70,
        "ideal": 0.26,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.28,
        "high_band_soft_p95": 0.80,
        "high_band_max_run": 5,
        "description": "OXY 代表亲和和联结侧增强。默认应在低到中位带活动，高位区适合留给强关系线索、信任验证和高质量互动回合。",
    },
    {
        "key": "nt_END",
        "title": "内啡肽通道强度",
        "group": "情绪递质",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.65,
        "ideal": 0.22,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.22,
        "high_band_soft_p95": 0.76,
        "high_band_max_run": 4,
        "description": "END 更适合作为中低基线、有限持续的舒缓与缓冲信号。若长期高位，往往意味着缓和链路过宽，削弱系统对真实强刺激的分辨。",
    },
    {
        "key": "nt_NOV",
        "title": "新颖探索通道强度",
        "group": "情绪递质",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.65,
        "ideal": 0.20,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.22,
        "high_band_soft_p95": 0.76,
        "high_band_max_run": 4,
        "description": "NOV 主要反映对新线索、意外变化和未证实路径的探索倾向。默认应保持中低基线，只有在明显新颖/意外窗口中短时抬升。",
    },
    {
        "key": "nt_FOC",
        "title": "专注锁定通道强度",
        "group": "情绪递质",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 0.70,
        "ideal": 0.24,
        "min_std": 0.03,
        "high_band_threshold": 0.50,
        "high_band_max_ratio": 0.28,
        "high_band_soft_p95": 0.80,
        "high_band_max_run": 5,
        "description": "FOC 主要反映持续聚焦与路径锁定倾向。中位活动带有助于稳定聚焦，但长期高位会让系统过度收窄、削弱泛化探索。",
    },
    {
        "key": "action_executed_recall",
        "title": "回忆动作执行率",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 0.40,
        "ideal": 0.10,
        "min_std": 0.02,
        "description": "回忆动作应稀疏且有意义，而不是一触即发。",
    },
    {
        "key": "action_executed_attention_focus",
        "title": "聚焦动作执行率",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 0.80,
        "ideal": 0.35,
        "min_std": 0.03,
        "description": "聚焦动作过少会抽空 CAM，过多会造成模式僵死。",
    },
    {
        "key": "iesm_triggered_rule_count",
        "title": "IESM 命中规则数",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 8.0,
        "ideal": 2.0,
        "min_std": 0.3,
        "description": "每 tick 真正命中的先天规则数。它高说明前段感知与规则条件确实在工作；若它低而行动又为 0，问题首先在规则命中前段，而不是行动器后段。",
    },
    {
        "key": "iesm_action_trigger_count",
        "title": "IESM 行动触发数",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 4.0,
        "ideal": 0.8,
        "min_std": 0.15,
        "description": "IESM 最终吐出的 action_trigger 数量。它位于“规则命中”与“行动尝试/执行”之间，是定位触发链断点的关键中间口径。",
    },
    {
        "key": "iesm_action_trigger_weather_stub_count",
        "title": "IESM 天气查询触发数",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 1.20,
        "ideal": 0.10,
        "min_std": 0.03,
        "description": "天气相关规则真正吐出的 weather_stub 触发数。它升高只说明“该考虑天气动作”，不等于动作已经越过驱动力阈值并执行。",
    },
    {
        "key": "iesm_triggered_rule_innate_action_weather_stub_from_query_weather_count",
        "title": "IESM 强天气规则命中数",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 0.60,
        "ideal": 0.06,
        "min_std": 0.02,
        "description": "只统计“明确请求查询天气”的强规则命中数。它抬头后若仍长期没有执行，应优先检查天气动作驱动力阈值与异步调度。",
    },
    {
        "key": "iesm_triggered_rule_innate_action_weather_stub_from_weather_question_count",
        "title": "IESM 隐式天气问句命中数",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 0.80,
        "ideal": 0.08,
        "min_std": 0.02,
        "description": "只统计“天气会不会凉 / 风大不大 / 要不要带伞”这类隐式求助问句的命中数。它代表介于显式查询与纯弱提及之间的中强天气求助。",
    },
    {
        "key": "iesm_triggered_rule_innate_action_weather_stub_from_weather_only_count",
        "title": "IESM 弱天气规则命中数",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 1.20,
        "ideal": 0.10,
        "min_std": 0.03,
        "description": "只统计“提到天气但未明确要求查询”的弱规则命中数。它可以抬头而不执行，这有助于区分“弱触发不过阈值”与“行动链本身失效”。",
    },
    {
        "key": "action_executed_weather_stub_source_visible",
        "title": "天气查询执行次数（契约可见）",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 0.50,
        "ideal": 0.08,
        "min_std": 0.02,
        "description": "只统计 source tick 上对期望契约真正可见的天气查询执行次数，用于区分“总执行”与“契约窗口内可见执行”。",
    },
    {
        "key": "action_executed_weather_stub_synthetic_only",
        "title": "天气查询执行次数（仅反馈 tick）",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 0.30,
        "ideal": 0.0,
        "min_std": 0.01,
        "description": "只统计 synthetic feedback tick 上发生的天气查询执行次数。它升高不代表契约窗口内已经满足，反而更可能提示异步调度与反馈回合混读风险。",
    },
    {
        "key": "action_executed_count_source_visible",
        "title": "行动执行总数（契约可见）",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 1.20,
        "ideal": 0.30,
        "min_std": 0.03,
        "description": "source tick 上对外部监督与期望契约真正可见的执行总数。它更适合拿来和契约结果对照，而不是看全部执行总数。",
    },
    {
        "key": "action_executed_count_synthetic_only",
        "title": "行动执行总数（仅反馈 tick）",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 0.60,
        "ideal": 0.0,
        "min_std": 0.02,
        "description": "只统计 synthetic feedback tick 上的执行总数。若它长期高于契约可见执行数，应优先检查异步动作落点与契约窗口设计。",
    },
    {
        "key": "action_drive_max",
        "title": "行动驱动力峰值",
        "group": "行动驱动力",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 1.60,
        "ideal": 0.80,
        "min_std": 0.05,
        "description": "驱动力峰值过高说明触发太猛，过低说明动作总被压住。",
    },
    {
        "key": "action_drive_weather_stub_max",
        "title": "天气查询驱动力峰值",
        "group": "行动驱动力",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 1.20,
        "ideal": 0.55,
        "min_std": 0.04,
        "description": "当前 tick 中 weather_stub 行动节点的最高驱动力。它用于判断天气意图是否真的把天气行动节点推起来。",
    },
    {
        "key": "action_effective_threshold_weather_stub_mean",
        "title": "天气查询平均实时阈值",
        "group": "行动驱动力",
        "unit": "number",
        "expected_min": 0.20,
        "expected_max": 1.10,
        "ideal": 0.55,
        "min_std": 0.03,
        "description": "weather_stub 节点当前实际执行阈值的平均值。它已经包含 NT 调制与疲劳，而不是单纯的规则基准阈值。",
    },
    {
        "key": "action_drive_margin_weather_stub_max",
        "title": "天气查询最大驱动裕量",
        "group": "行动驱动力",
        "unit": "number",
        "expected_min": -0.60,
        "expected_max": 0.60,
        "ideal": 0.05,
        "min_std": 0.03,
        "description": "weather_stub 节点里最大的 `drive - effective_threshold`。长期为负说明经常是“想到天气但不过线”。",
    },
    {
        "key": "action_node_weather_stub_count",
        "title": "天气查询行动节点数",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 3.0,
        "ideal": 1.0,
        "min_std": 0.03,
        "description": "当前 tick 中 weather_stub 行动节点总数。若 IESM 已多次触发天气，这里却长期为 0，问题在节点创建/保活而不在阈值。",
    },
    {
        "key": "action_active_weather_stub_count",
        "title": "天气查询活跃节点数",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 3.0,
        "ideal": 1.0,
        "min_std": 0.03,
        "description": "drive 高于轻微活化阈值的 weather_stub 节点数量。它表示天气节点是否已被唤醒，但还不等于能执行。",
    },
    {
        "key": "action_ready_weather_stub_count",
        "title": "天气查询就绪节点数",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 2.0,
        "ideal": 0.4,
        "min_std": 0.02,
        "description": "drive 已达到实时执行阈值的 weather_stub 节点数。它直接回答“弱触发不过阈值”还是“已经过阈值但后面没调度/没执行”。",
    },
    {
        "key": "action_drive_active_count",
        "title": "活跃行动节点数",
        "group": "行动驱动力",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 10.0,
        "ideal": 4.0,
        "min_std": 1.0,
        "description": "并存行动意图数。过多会造成驱动竞争混乱。",
    },
    {
        "key": "time_sensor_bucket_energy_sum",
        "title": "时间感受桶总能量",
        "group": "时间感受",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 1.50,
        "ideal": 0.70,
        "min_std": 0.08,
        "description": "时间感受整体强度，过高易误触回忆，过低则时间信息失真。",
    },
    {
        "key": "time_sensor_attribute_binding_count",
        "title": "时间感受属性绑定数",
        "group": "时间感受",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 4.0,
        "min_std": 1.0,
        "description": "本 tick 把时间感受绑定到多少个锚点对象上。",
    },
    {
        "key": "hdb_contextual_structure_ratio",
        "title": "HDB 上下文化结构占比",
        "group": "上下文与残差",
        "unit": "ratio",
        "expected_min": 0.08,
        "expected_max": 0.92,
        "ideal": 0.40,
        "min_std": 0.03,
        "diagnostic_only": True,
        "description": "HDB 中带有 legacy context/provenance 元信息的结构占比。新版正式身份由完整结构特征/root id 决定；该项只用于审计旧上下文残留，不再作为主链调参目标。",
    },
    {
        "key": "hdb_multi_context_structure_ratio",
        "title": "HDB 多上下文结构占比",
        "group": "上下文与残差",
        "unit": "ratio",
        "expected_min": 0.02,
        "expected_max": 0.42,
        "ideal": 0.12,
        "min_std": 0.01,
        "diagnostic_only": True,
        "description": "HDB 中同内容但挂在多个 legacy context/provenance 路径上的结构占比。新版同一完整结构不应因 owner/source 路径不同而分裂身份；该项用于旧口径残留审计。",
    },
    {
        "key": "hdb_same_content_multi_context_ratio",
        "title": "同内容多上下文占比",
        "group": "上下文与残差",
        "unit": "ratio",
        "expected_min": 0.02,
        "expected_max": 0.36,
        "ideal": 0.10,
        "min_std": 0.01,
        "diagnostic_only": True,
        "description": "相同内容在不同 legacy context/provenance 下并存的比例。新版 growth 主链下，同一完整内容应优先汇聚到同一完整身份；该项不再表示主链必须制造多上下文身份。",
    },
    {
        "key": "hdb_residual_diff_entry_ratio",
        "title": "残差局部链接占比",
        "group": "上下文与残差",
        "unit": "ratio",
        "expected_min": 0.18,
        "expected_max": 0.92,
        "ideal": 0.48,
        "min_std": 0.02,
        "description": "HDB diff 链接中由残差链路贡献的占比。它近似反映感应赋能和内源展开是否主要沿局部残差路径传播，而不是退化成全局散射。",
    },
    {
        "key": "hdb_primary_pointer_count",
        "title": "HDB 主指针条目数",
        "group": "HDB索引与缓存",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 200000.0,
        "ideal": 10000.0,
        "min_std": 100.0,
        "diagnostic_only": True,
        "description": "主指针索引中的条目总数。它主要用于观测数据库规模与主链索引密度，不直接作为自动调参目标。",
    },
    {
        "key": "hdb_fallback_pointer_count",
        "title": "HDB 回退指针条目数",
        "group": "HDB索引与缓存",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 120000.0,
        "ideal": 6000.0,
        "min_std": 80.0,
        "diagnostic_only": True,
        "description": "component / fallback 级索引条目数，用于观察回退链路的沉淀规模。",
    },
    {
        "key": "hdb_signature_index_count",
        "title": "HDB 完整签名索引条目数",
        "group": "HDB索引与缓存",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 120000.0,
        "ideal": 8000.0,
        "min_std": 80.0,
        "diagnostic_only": True,
        "description": "canonical signature 到结构对象的精确索引规模，用于确认 exact reuse 主路是否正常沉淀。",
    },
    {
        "key": "hdb_recent_cache_count",
        "title": "HDB 近期解析缓存条目数",
        "group": "HDB索引与缓存",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 24000.0,
        "ideal": 2000.0,
        "min_std": 40.0,
        "diagnostic_only": True,
        "description": "近期 profile / 解析缓存条目数，用于判断短期重复查存是否被缓存吸收。",
    },
    {
        "key": "hdb_exact_lookup_cache_count",
        "title": "HDB 精确命中缓存条目数",
        "group": "HDB索引与缓存",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 24000.0,
        "ideal": 2000.0,
        "min_std": 40.0,
        "diagnostic_only": True,
        "description": "exact lookup cache 条目数，用于审计短期内重复拿结构 ID 是否真的走缓存而不是重复全局扫描。",
    },
    {
        "key": "hdb_numeric_bucket_family_count",
        "title": "HDB 数值族数量",
        "group": "HDB索引与缓存",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 256.0,
        "ideal": 24.0,
        "min_std": 2.0,
        "diagnostic_only": True,
        "description": "数值匹配索引里当前存在的数值 family 数，用于检查统一数值软匹配链是否建好。",
    },
    {
        "key": "hdb_numeric_bucket_count",
        "title": "HDB 数值桶数量",
        "group": "HDB索引与缓存",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 4000.0,
        "ideal": 240.0,
        "min_std": 10.0,
        "diagnostic_only": True,
        "description": "数值匹配索引里的总桶数，用于观察时间感受、压力、期待等数值 SA 的离散化负载。",
    },
    {
        "key": "time_sensor_delayed_task_table_size",
        "title": "时间感受延迟任务表大小",
        "group": "时间感受",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 24.0,
        "ideal": 8.0,
        "min_std": 1.0,
        "description": "时间感受派生的延迟任务规模。",
    },
    {
        "key": "time_sensor_delayed_task_executed_count",
        "title": "时间感受延迟任务执行数",
        "group": "时间感受",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 0.40,
        "ideal": 0.08,
        "min_std": 0.02,
        "description": "到期延迟任务的执行频率，过高说明节奏控制过松。",
    },
    {
        "key": "map_count",
        "title": "MAP 兼容池条目数",
        "group": "记忆回响",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 56.0,
        "ideal": 28.0,
        "min_std": 2.0,
        "description": "旧 MAP 兼容池当前规模。长期抬升通常与兼容回忆触发过密有关；默认新口径主路径并不依赖这条链路。",
    },
    {
        "key": "map_feedback_total_ev",
        "title": "MAP 兼容反馈总虚能量",
        "group": "记忆回响",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 4.5,
        "min_std": 0.4,
        "description": "旧 MAP 兼容反馈给回状态池的总虚能量。",
    },
    {
        "key": "memory_feedback_applied_count",
        "title": "记忆反馈落地次数",
        "group": "记忆回响",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 10.0,
        "ideal": 2.5,
        "min_std": 0.25,
        "description": "本轮真正执行了多少次记忆反馈落地。它是 stimulus packet 回放与结构直投两条反馈支路的总入口数量。",
    },
    {
        "key": "memory_feedback_total_ev",
        "title": "记忆反馈总虚能量",
        "group": "记忆回响",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 12.0,
        "ideal": 4.5,
        "min_std": 0.4,
        "description": "本轮记忆反馈实际回注到系统中的总虚能量。它把 packet 回放与结构直投两条链的 EV 汇总在一起。",
    },
    {
        "key": "memory_feedback_packet_count",
        "title": "记忆包回放次数",
        "group": "记忆回响",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 8.0,
        "ideal": 2.0,
        "min_std": 0.2,
        "description": "以 stimulus packet 形式直接回放到状态池的记忆反馈次数。偏高说明系统更像在复现整包经历，而不是把结构性预测拆出来继续传播。",
    },
    {
        "key": "memory_feedback_packet_total_ev",
        "title": "记忆包回放虚能量",
        "group": "记忆回响",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 8.0,
        "ideal": 2.4,
        "min_std": 0.25,
        "description": "分配给 stimulus packet 整包回放支路的虚能量。它更接近“整段回响回到状态池”的反馈份额。",
    },
    {
        "key": "memory_feedback_packet_applied_total_ev",
        "title": "记忆包实际落池虚能量",
        "group": "记忆回响",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 8.0,
        "ideal": 2.0,
        "min_std": 0.25,
        "description": "记忆包回放支路最终真正写进 StatePool 的虚能量。它比 budget 更接近“这条回响链到底有没有把 EV 留在当前认知现场”。",
    },
    {
        "key": "memory_feedback_packet_apply_efficiency_ev",
        "title": "记忆包落池效率",
        "group": "记忆回响",
        "unit": "ratio",
        "expected_min": 0.20,
        "expected_max": 1.0,
        "ideal": 0.62,
        "min_std": 0.04,
        "description": "记忆包实际落池 EV / 记忆包分配 EV。它低时，说明很多回放预算没有真正留下来，可能被合并、过散或在后续落地里耗掉了。",
    },
    {
        "key": "memory_feedback_structure_projection_count",
        "title": "结构直投次数",
        "group": "记忆回响",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 16.0,
        "ideal": 4.0,
        "min_std": 0.3,
        "description": "本轮从记忆反馈中拆出并直接投向结构引用对象的次数。它更接近沿残差结构链继续扩散预测的局部反馈强度。",
    },
    {
        "key": "memory_feedback_structure_projection_attempted_count",
        "title": "结构直投尝试次数",
        "group": "记忆回响",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 64.0,
        "ideal": 8.0,
        "min_std": 0.5,
        "description": "结构直投在疲劳裁剪前一共尝试了多少个结构引用目标。它高而有效次数低，通常说明反馈预算被分得太散或单目标能量过薄。",
    },
    {
        "key": "memory_feedback_structure_projection_skipped_count",
        "title": "结构直投被裁掉次数",
        "group": "记忆回响",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 48.0,
        "ideal": 2.0,
        "min_std": 0.4,
        "description": "结构直投在运行前因投影疲劳或最小有效能量阈值而被裁掉的目标数。它高时，说明结构引用目标过多、过散，或当前疲劳过重。",
    },
    {
        "key": "memory_feedback_structure_projection_effective_ratio",
        "title": "结构直投有效率",
        "group": "记忆回响",
        "unit": "ratio",
        "expected_min": 0.25,
        "expected_max": 1.0,
        "ideal": 0.62,
        "min_std": 0.04,
        "description": "结构直投有效次数 / 尝试次数。它直接反映记忆反馈的结构引用是否被分得过散，以及疲劳裁剪是否过强。",
    },
    {
        "key": "memory_feedback_structure_projection_total_ev",
        "title": "结构直投虚能量",
        "group": "记忆回响",
        "unit": "number",
        "expected_min": 0.0,
        "expected_max": 9.0,
        "ideal": 3.0,
        "min_std": 0.25,
        "description": "分配给结构直投支路的虚能量。若这项长期接近 0，而 packet 回放很高，说明反馈仍偏整包重放，未充分利用结构引用继续局部传播。",
    },
    {
        "key": "memory_feedback_structure_projection_ratio_used",
        "title": "记忆反馈结构分流比例",
        "group": "记忆回响",
        "unit": "ratio",
        "expected_min": 0.10,
        "expected_max": 0.80,
        "ideal": 0.32,
        "min_std": 0.03,
        "description": "当前 tick 实际用于“包体回放 vs 结构直投”的结构分流比例。它可以是固定配置，也可以因池内 EV/ER 失衡而被自适应收缩。",
    },
    {
        "key": "hdb_structure_count",
        "title": "结构总数",
        "group": "结构增长",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 260.0,
        "ideal": 150.0,
        "min_std": 4.0,
        "description": "HDB 结构数量，用于观测是否在稳定积累而不是无序膨胀。",
    },
    {
        "key": "hdb_episodic_count",
        "title": "情节记忆总数",
        "group": "结构增长",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 140.0,
        "ideal": 78.0,
        "min_std": 3.0,
        "description": "情节记忆数量，用于观察是否形成真正积累。",
    },
    {
        "key": "stimulus_round_count",
        "title": "刺激级查存轮次",
        "group": "检索复杂度",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 5.0,
        "ideal": 3.0,
        "min_std": 0.2,
        "description": "刺激级轮次长期跑满，通常说明停止条件和预算没有真正生效。",
    },
    {
        "key": "structure_round_count",
        "title": "结构级查存轮次",
        "group": "检索复杂度",
        "unit": "count",
        "expected_min": 0.0,
        "expected_max": 3.0,
        "ideal": 2.0,
        "min_std": 0.2,
        "description": "结构级轮次长期跑满，通常说明候选空间过大或阈值过松。",
    },
]


def list_metric_definitions() -> list[dict[str, Any]]:
    return [dict(item) for item in DEFAULT_LONG_METRIC_LIBRARY]


# ------------------------------
# Data structures
# ------------------------------


@dataclass(frozen=True)
class ParamBound:
    min_value: float
    max_value: float
    max_step_abs: float
    quantum: float = 0.0


@dataclass(frozen=True)
class ParamSpec:
    param_id: str
    source_kind: str  # module_config | observatory_config | iesm_rule
    module: str
    # For module configs: tokens point to a leaf, like ["threshold_scale_by_nt", "DA"]
    # For IESM rules: tokens point within a single rule dict.
    path_tokens: list[Any]
    value: Any
    value_type: str  # int | float | bool | str | none | other
    auto_tune_allowed: bool
    tags: list[str]
    impacts: list[str]
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "param_id": self.param_id,
            "source_kind": self.source_kind,
            "module": self.module,
            "path": _path_tokens_to_str(self.path_tokens),
            "path_tokens": list(self.path_tokens),
            "value": self.value,
            "value_type": self.value_type,
            "auto_tune_allowed": bool(self.auto_tune_allowed),
            "tags": list(self.tags),
            "impacts": list(self.impacts),
            "note": self.note,
        }


# ------------------------------
# Catalog builders
# ------------------------------


def _flatten_yaml_tree(*, node: Any, prefix: list[Any] | None = None) -> Iterable[tuple[list[Any], Any]]:
    """Yield (path_tokens, leaf_value) for scalar leaves in a YAML structure."""
    prefix = list(prefix or [])
    if _is_scalar(node):
        yield (prefix, node)
        return
    if isinstance(node, dict):
        for k, v in node.items():
            if not isinstance(k, str):
                k = str(k)
            yield from _flatten_yaml_tree(node=v, prefix=prefix + [k])
        return
    if isinstance(node, list):
        for idx, v in enumerate(node):
            yield from _flatten_yaml_tree(node=v, prefix=prefix + [idx])
        return
    # Unknown object: do not recurse
    yield (prefix, node)


def _value_type(v: Any) -> str:
    if v is None:
        return "none"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int) and not isinstance(v, bool):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    return "other"


def _default_ignore_paths_for_module(module: str) -> list[str]:
    """Top-level keys we do not auto-tune (still catalogued)."""
    m = str(module or "").strip().lower()
    if m in {"time_sensor"}:
        # Buckets define the discretization lattice; auto-tuning them is too risky.
        return ["buckets", "tick_buckets"]
    if m in {"observatory"}:
        # Web host/port etc should never be auto tuned.
        return [
            "web_host",
            "web_port",
            "default_launch_mode",
            "snapshot_top_k",
            "history_limit",
            "export_html",
            "export_json",
            "auto_open_html_report",
            "web_auto_open_browser",
        ]
    if m in {"text_sensor"}:
        # Tokenizer backends and paths are semantic/dependency knobs.
        return ["tokenizer_backend", "custom_tokenizer_module_path", "user_dict_path", "importance_backend"]
    return []


def _guess_tags(*, module: str, path_tokens: list[Any], source_kind: str) -> list[str]:
    m = str(module or "").strip().lower()
    leaf = str(path_tokens[-1]) if path_tokens else ""
    top = str(path_tokens[0]) if path_tokens else ""
    name = f"{top}.{leaf}".lower() if top else leaf.lower()

    tags: list[str] = []
    if source_kind == "iesm_rule":
        tags.append("iesm")
        if str(path_tokens[0] if path_tokens else "").startswith("cfs_") or "cfs" in name:
            tags.append("cfs_rules")
        if "action" in name or "action_trigger" in name:
            tags.append("action_rules")
    else:
        tags.append(m)

    # Common patterns
    if "echo" in name:
        tags.append("echo")
    if "fatigue" in name or "habituation" in name:
        tags.append("fatigue")
    if "decay" in name or "half_life" in name or "retention" in name:
        tags.append("decay")
    if any(x in name for x in ["top_n", "max_", "cap", "budget", "round", "window", "history", "capacity"]):
        tags.append("performance")
    if "threshold" in name or name.endswith("_min") or name.endswith("_max"):
        tags.append("gating")
    return sorted(set(tags))


def _guess_impacts(*, module: str, param_id: str, tags: list[str], source_kind: str) -> list[str]:
    """Return a richer list of metric keys likely impacted (best-effort)."""
    m = str(module or "").strip().lower()
    pid = str(param_id or "")
    name = pid.lower()
    impacts: set[str] = set()

    def _add(*keys: str) -> None:
        for key in keys:
            k = str(key or "").strip()
            if k:
                impacts.add(k)

    # IESM rules: try map by rule id name.
    if source_kind == "iesm_rule":
        if "cfs_dissonance" in name:
            _add("cfs_dissonance_max", "cfs_dissonance_count", "pool_high_cp_item_count", "rwd_pun_pun")
        if "cfs_pressure" in name:
            _add("cfs_pressure_max", "cfs_pressure_count", "cfs_pressure_live_active", "cfs_pressure_decay_only", "rwd_pun_pun", "action_drive_max")
        if "cfs_expectation" in name:
            _add("cfs_expectation_max", "cfs_expectation_count", "rwd_pun_rwd", "action_drive_max")
        if "cfs_correct_event" in name:
            _add("cfs_correct_event_count", "cfs_correct_event_max", "rwd_pun_rwd")
        if "surprise" in name:
            _add("cfs_surprise_max", "cfs_signal_count", "pool_total_er")
        if "complexity" in name:
            _add("cfs_complexity_max", "action_executed_focus_mode", "action_executed_diverge_mode")
        if "action_recall" in name:
            _add(
                "action_executed_recall",
                "action_drive_max",
                "action_drive_active_count",
                "map_count",
                "map_feedback_total_ev",
                "timing_total_logic_ms",
                "time_sensor_bucket_energy_sum",
            )
        if "action_attention_focus" in name:
            _add("action_executed_attention_focus", "action_drive_max", "cam_item_count", "attention_consumed_total_energy")
        if "attention_focus_mode" in name or "attention_diverge_mode" in name:
            _add("action_executed_focus_mode", "action_executed_diverge_mode", "cam_item_count")
        if not impacts:
            _add("cfs_signal_count")
        return sorted(impacts)

    # Module configs
    if m == "hdb":
        _add(
            "internal_sa_count",
            "internal_to_external_sa_ratio",
            "internal_resolution_structure_count_selected",
            "internal_resolution_raw_unit_count",
            "internal_resolution_selected_unit_count",
            "structure_round_count",
            "stimulus_round_count",
            "timing_structure_level_ms",
            "timing_stimulus_level_ms",
            "hdb_contextual_structure_ratio",
            "hdb_multi_context_structure_ratio",
            "hdb_same_content_multi_context_ratio",
            "hdb_residual_diff_entry_ratio",
        )
        if any(x in name for x in ["internal_resolution", "flat_unit", "detail_budget", "structures_per_tick", "resolution"]):
            _add(
                "internal_resolution_detail_budget",
                "internal_sa_count",
                "internal_flat_token_count",
                "internal_to_external_sa_ratio",
                "internal_resolution_structure_count_selected",
                "timing_total_logic_ms",
                "merged_flat_token_count",
            )
        if any(x in name for x in ["stimulus_level", "stimulus_match", "cut", "diff_table", "group_table", "residual"]):
            _add(
                "stimulus_transfer_matched_total",
                "stimulus_final_residual_total",
                "stimulus_transfer_to_residual_ratio",
                "stimulus_transfer_dominates_residual",
                "stimulus_effective_transfer_fraction_mean",
                "stimulus_object_projection_total",
                "stimulus_memory_tail_absorbed_total",
                "stimulus_unhandled_residual_total",
                "stimulus_object_projection_to_unhandled_residual_ratio",
                "stimulus_object_projection_dominates_unhandled_residual",
                "stimulus_early_stop_object_projection_dominance_triggered",
                "stimulus_early_stop_object_projection_dominance_ratio",
                "stimulus_early_stop_object_projection_transfer_guard_blocked_count",
                "stimulus_early_stop_object_projection_transfer_ratio_at_stop",
                "stimulus_anchor_owner_residual_presence_cache_hit_count",
                "stimulus_anchor_owner_residual_presence_scan_count",
                "landed_flat_token_count",
                "cache_residual_flat_token_count",
                "cache_priority_theoretical_match_fast_reject_count",
                "pool_apply_merged_item_count",
                "pool_residual_origin_item_ratio",
                "hdb_residual_diff_entry_ratio",
                "induction_propagated_target_ratio",
                "induction_raw_residual_entry_materialized_structure_count",
                "induction_raw_residual_materialized_structure_target_count",
                "induction_raw_residual_materialized_structure_budget_weight",
            )
        if any(x in name for x in ["structure_level", "group", "fallback"]):
            _add("hdb_group_count", "timing_structure_level_ms")
        if any(x in name for x in ["memory_activation", "map", "feedback", "induction"]):
            _add(
                "map_count",
                "map_feedback_total_ev",
                "hdb_episodic_count",
                "induction_total_delta_ev",
                "induction_source_item_count",
                "induction_source_available_st_count",
                "induction_source_selected_from_ev_count",
                "induction_source_selected_from_er_count",
                "induction_source_selected_from_cp_abs_count",
                "induction_source_available_with_local_target_hint_count",
                "induction_source_selected_with_local_target_hint_count",
                "induction_source_selected_zero_local_target_hint_count",
                "induction_raw_residual_entry_count",
                "induction_raw_residual_entry_with_existing_structure_count",
                "induction_raw_residual_entry_routed_to_structure_count",
                "induction_raw_residual_existing_structure_target_count",
                "induction_raw_residual_entry_materialized_structure_count",
                "induction_raw_residual_materialized_structure_target_count",
                "induction_source_selection_cap_hit",
                "induction_target_count",
                "induction_raw_residual_structure_target_count",
                "induction_raw_residual_memory_target_count",
                "induction_propagated_target_count",
                "induction_induced_target_count",
                "induction_targets_per_source_mean",
                "induction_propagated_budget_total_ev",
                "induction_propagated_ev_total",
                "induction_ev_from_er_total",
                "induction_raw_residual_structure_target_total_ev",
                "induction_raw_residual_memory_target_total_ev",
                "induction_raw_residual_materialized_structure_budget_weight",
                "induction_propagated_target_ratio",
                "induction_ev_from_er_ratio",
                "induction_energy_graph_v2_enabled",
                "induction_energy_graph_round_count_max",
                "induction_energy_graph_depth_max",
                "induction_energy_graph_frontier_generated_count",
                "induction_energy_graph_frontier_pruned_count",
                "induction_energy_graph_terminal_memory_count",
                "induction_energy_graph_root_reinduction_count",
                "induction_energy_graph_layer_count",
                "induction_energy_graph_layer_max_width",
                "induction_energy_graph_layer_total_nodes",
                "induction_energy_graph_round_summary_count",
                "induction_energy_graph_frontier_budget_total_ev",
                "induction_energy_graph_root_induction_budget_total_ev",
                "induction_energy_graph_round_delta_ev_total",
                "induction_energy_graph_round_delta_ev_max",
                "induction_energy_graph_round_delta_ev_last",
                "induction_energy_graph_frontier_in_count_max",
                "induction_energy_graph_frontier_out_count_max",
            )
        return sorted(impacts)
    if m == "cognitive_stitching":
        _add(
            "cs_candidate_count",
            "cs_action_count",
            "cs_created_count",
            "cs_extended_count",
            "cs_merged_count",
            "cs_reinforced_count",
            "stimulus_new_structure_count",
            "timing_cognitive_stitching_ms",
            "timing_event_grasp_ms",
        )
        if any(x in name for x in ["min_candidate_score", "min_seed_total_energy", "min_event_total_energy", "event_grasp_min_total_energy"]):
            _add(
                "cs_candidate_count",
                "cs_action_count",
                "cs_created_count",
                "cs_extended_count",
                "cs_merged_count",
                "cs_reinforced_count",
                "stimulus_new_structure_count",
            )
        if any(x in name for x in ["weight", "penalty", "scale", "temperature", "bias"]):
            _add(
                "cs_candidate_count",
                "cs_action_count",
                "cs_created_count",
                "cs_extended_count",
                "cs_merged_count",
                "cs_reinforced_count",
                "timing_cognitive_stitching_ms",
            )
        if any(x in name for x in ["max_seed_items", "max_outgoing_edges_per_seed", "max_events_per_tick", "max_context_k", "top_k", "overlay"]):
            _add(
                "cs_candidate_count",
                "cs_action_count",
                "timing_cognitive_stitching_ms",
                "timing_event_grasp_ms",
            )
        return sorted(impacts)
    if m == "action" and "mode_attention_energy_budget" in name:
        _add("attention_energy_budget", "attention_net_delta_energy", "pool_total_er", "pool_total_ev")
        return sorted(impacts)
    if m == "attention" or pid.startswith("observatory.attention_"):
        _add(
            "cam_item_count",
            "attention_memory_item_count",
            "attention_consumed_total_energy",
            "attention_energy_budget",
            "attention_net_delta_energy",
            "attention_suppressed_total_energy",
            "attention_state_pool_candidate_count",
            "timing_attention_ms",
        )
        if any(x in name for x in ["top_n", "max_cam_items", "cap"]):
            _add("attention_cam_item_cap", "cam_item_count", "attention_skipped_memory_item_count")
        if any(x in name for x in ["ratio", "consume_energy", "memory_energy"]):
            _add("pool_total_er", "pool_total_ev", "attention_consumed_total_energy")
        if "attention_energy_budget" in name:
            _add("pool_total_er", "pool_total_ev", "attention_energy_budget", "attention_net_delta_energy")
        if any(x in name for x in ["threshold", "suppression", "gate", "keep"]):
            _add("cam_item_count", "attention_skipped_memory_item_count")
        return sorted(impacts)
    if m == "state_pool":
        _add(
            "pool_active_item_count",
            "pool_high_cp_item_count",
            "pool_total_cp",
            "timing_maintenance_ms",
            "maintenance_delta_active_item_count",
        )
        if "energy_injection_fatigue" in name:
            _add(
                "pool_total_er",
                "pool_total_ev",
                "pool_total_cp",
                "energy_concentration",
                "effective_peak_count",
                "pool_energy_injection_throttle_ratio_total",
                "pool_energy_injection_side_hit_count",
                "pool_energy_injection_min_scale",
            )
        if any(x in name for x in ["pool_max_items", "soft_capacity", "overflow", "prune"]):
            _add("timing_total_logic_ms", "maintenance_after_active_item_count", "maintenance_delta_active_item_count")
        if any(x in name for x in ["default_er_decay", "er_elimination", "recency_gain"]):
            _add("pool_total_er", "pool_total_cp")
        if any(x in name for x in ["default_ev_decay", "ev_elimination"]):
            _add("pool_total_ev", "pool_total_cp", "cfs_expectation_max", "cfs_pressure_max")
        if any(x in name for x in ["fatigue", "cp_elimination", "fast_cp", "rate_smoothing"]):
            _add("pool_high_cp_item_count", "cfs_dissonance_max", "pool_total_cp")
        if "neutralization" in name:
            _add("cache_residual_flat_token_count", "cache_priority_consumed_er", "cache_priority_consumed_ev", "pool_apply_total_delta_cp")
        if "merge" in name or "semantic_same_object" in name:
            _add("pool_apply_merged_item_count", "pool_active_item_count", "timing_maintenance_ms")
        if "runtime_structure_root_identity" in name or "runtime_structure_resolution" in name:
            _add(
                "pool_apply_merged_item_count",
                "pool_active_item_count",
                "pool_runtime_resolution_degraded_item_count",
                "timing_maintenance_ms",
            )
        if "attribute_bind" in name:
            _add("time_sensor_attribute_binding_count", "pool_active_item_count")
        return sorted(impacts)
    if m == "text_sensor":
        _add(
            "external_sa_count",
            "merged_flat_token_count",
            "timing_sensor_ms",
            "sensor_echo_pool_size",
            "sensor_echo_current_round",
        )
        if "echo" in name:
            _add("sensor_echo_frames_used_count", "timing_cache_neutralization_ms", "cache_residual_flat_token_count")
        if any(x in name for x in ["char_output", "token_output", "csa_output", "tokenizer", "importance"]):
            _add("sensor_feature_sa_count", "sensor_attribute_sa_count", "sensor_csa_bundle_count", "external_sa_count")
        if any(x in name for x in ["base_er", "attribute_er_ratio", "attribute_ev_ratio", "importance"]):
            _add("pool_total_er", "pool_total_ev", "external_sa_count")
        if "fatigue" in name:
            _add("external_sa_count", "merged_flat_token_count", "pool_total_er")
        return sorted(impacts)
    if m == "time_sensor":
        _add(
            "timing_time_sensor_ms",
            "time_sensor_bucket_update_count",
            "time_sensor_bucket_energy_sum",
            "time_sensor_bucket_energy_max",
            "time_sensor_attribute_binding_count",
            "time_sensor_projection_binding_count",
        )
        if any(x in name for x in ["memory_top_k", "source_mode", "time_basis", "tick_interval"]):
            _add(
                "time_sensor_memory_used_count",
                "time_sensor_bucket_energy_sum",
                "time_sensor_projection_binding_count",
                "action_executed_recall",
            )
        if any(x in name for x in ["energy_gain_ratio", "base_energy_source", "energy_key", "min_bucket_energy"]):
            _add("time_sensor_bucket_energy_sum", "time_sensor_bucket_energy_max", "time_sensor_attribute_binding_count")
        if any(x in name for x in ["bind", "attribute_name", "peak_keep_ratio", "max_total_bindings"]):
            _add("time_sensor_attribute_binding_count", "time_sensor_projection_binding_count", "action_executed_recall")
        if any(x in name for x in ["projection_target_keep_ratio", "max_projection_bind_targets_per_memory", "runtime_snapshot_target_bindings"]):
            _add(
                "time_sensor_projection_binding_count",
                "time_sensor_delayed_task_registered_count",
                "time_sensor_delayed_task_executed_count",
                "action_executed_recall",
            )
        if "delayed_task" in name:
            _add(
                "time_sensor_delayed_task_table_size",
                "time_sensor_delayed_task_registered_count",
                "time_sensor_delayed_task_executed_count",
                "time_sensor_projection_binding_count",
                "timing_time_sensor_ms",
            )
        return sorted(impacts)
    if m == "action":
        _add(
            "action_executed_count",
            "action_executed_count_source_visible",
            "action_node_count",
            "action_drive_max",
            "action_drive_mean",
            "action_drive_active_count",
            "timing_action_ms",
        )
        if any(x in name for x in ["drive_decay", "drive_max", "max_action_nodes", "node_idle"]):
            _add("action_node_count", "action_drive_active_count", "timing_action_ms")
        if any(x in name for x in ["threshold_scale", "fatigue"]):
            _add("action_executed_count", "action_executed_count_source_visible", "action_drive_max", "action_drive_active_count")
        if any(x in name for x in ["focus_threshold", "focus_gain", "attention_focus"]):
            _add("action_executed_attention_focus", "cam_item_count", "attention_consumed_total_energy")
        if any(x in name for x in ["mode_threshold", "mode_drive_gain", "focus_mode", "diverge_mode", "attention_mode"]):
            _add("action_executed_focus_mode", "action_executed_diverge_mode", "cam_item_count")
        if "recall" in name:
            _add("action_executed_recall", "map_count", "map_feedback_total_ev", "time_sensor_bucket_energy_sum")
        if "weather" in name:
            _add("action_executed_weather_stub_source_visible", "action_executed_weather_stub_synthetic_only", "action_scheduled_weather_stub")
        return sorted(impacts)
    if m == "emotion":
        _add("rwd_pun_rwd", "rwd_pun_pun", "nt_DA", "nt_COR", "nt_ADR", "nt_SER", "nt_OXY", "nt_END", "nt_NOV", "nt_FOC")
        if any(x in name for x in ["ev_propagation", "er_induction", "propagation_ratio", "induction_ratio"]):
            _add(
                "induction_total_delta_ev",
                "induction_structure_target_total_ev",
                "induction_memory_target_total_ev",
                "induction_raw_residual_structure_target_total_ev",
                "induction_raw_residual_memory_target_total_ev",
                "induction_structure_target_ev_share",
                "induction_memory_target_ev_share",
                "induction_applied_total_ev",
                "induction_skipped_target_total_ev",
                "induction_applied_ev_ratio",
                "induction_total_ev_consumed",
                "induction_propagated_budget_total_ev",
                "induction_propagated_ev_total",
                "induction_ev_from_er_total",
                "induction_propagated_target_ratio",
                "induction_ev_from_er_ratio",
                "induction_energy_graph_round_count_max",
                "induction_energy_graph_depth_max",
                "induction_energy_graph_frontier_generated_count",
                "induction_energy_graph_terminal_memory_count",
                "induction_energy_graph_root_reinduction_count",
                "induction_energy_graph_frontier_budget_total_ev",
                "induction_energy_graph_root_induction_budget_total_ev",
                "induction_energy_graph_round_delta_ev_total",
                "induction_energy_graph_round_delta_ev_last",
                "pool_total_ev",
                "pool_ev_to_er_ratio",
            )
        if "da" in name:
            _add("nt_DA", "action_drive_max", "cfs_expectation_max")
        if "cor" in name:
            _add("nt_COR", "cfs_pressure_max", "timing_total_logic_ms")
        if "adr" in name:
            _add("nt_ADR", "action_drive_max", "cfs_pressure_max")
        if "ser" in name:
            _add("nt_SER", "action_executed_count")
        if "oxy" in name:
            _add("nt_OXY", "action_executed_attention_focus")
        if "end" in name:
            _add("nt_END", "action_executed_recall")
        if "nov" in name:
            _add("nt_NOV", "attention_cam_item_cap", "attention_mod_priority_weight_recency_gain")
        if "foc" in name:
            _add("nt_FOC", "cam_item_count", "attention_mod_focus_boost_weight", "attention_mod_min_total_energy")
        return sorted(impacts)
    if m == "cognitive_feeling":
        _add("cfs_signal_count", "cfs_dissonance_max", "cfs_pressure_max", "cfs_expectation_max")
        if "dissonance" in name:
            _add("cfs_dissonance_max", "rwd_pun_pun")
        if "pressure" in name:
            _add("cfs_pressure_max", "cfs_pressure_live_active", "cfs_pressure_decay_only", "rwd_pun_pun")
        if "expectation" in name:
            _add("cfs_expectation_max", "rwd_pun_rwd")
        if "correct" in name:
            _add("cfs_correct_event_count", "rwd_pun_rwd")
        if "complexity" in name:
            _add("cfs_complexity_max", "action_executed_focus_mode")
        if "grasp" in name:
            _add("cfs_grasp_max", "action_executed_attention_focus")
        return sorted(impacts)
    if m == "energy_balance":
        _add(
            "pool_total_er",
            "pool_total_ev",
            "pool_total_cp",
            "pool_ev_to_er_ratio",
            "energy_balance_ratio_smooth",
            "energy_balance_target_ratio",
            "energy_balance_g_after",
            "energy_balance_ev_propagation_ratio_scale",
            "energy_balance_er_induction_ratio_scale",
            "hdb_requested_ev_propagation_ratio",
            "hdb_effective_ev_propagation_ratio",
            "hdb_requested_er_induction_ratio",
            "hdb_effective_er_induction_ratio",
            "rwd_pun_rwd",
            "rwd_pun_pun",
            "induction_total_delta_ev",
            "induction_propagated_budget_total_ev",
            "induction_propagated_ev_total",
            "induction_ev_from_er_total",
            "induction_ev_from_er_ratio",
            "induction_energy_graph_round_count_max",
            "induction_energy_graph_depth_max",
            "induction_energy_graph_frontier_generated_count",
            "induction_energy_graph_terminal_memory_count",
            "induction_energy_graph_frontier_budget_total_ev",
            "induction_energy_graph_root_induction_budget_total_ev",
            "induction_energy_graph_round_delta_ev_total",
            "induction_energy_graph_round_delta_ev_last",
        )
        return sorted(impacts)
    if m == "observatory":
        _add("timing_total_logic_ms")
        if "input_chunk" in name or "chunking" in name:
            _add(
                "input_queue_queued_from_new_input_count",
                "input_queue_pending_count_after_dequeue",
                "external_sa_count",
                "merged_flat_token_count",
                "timing_sensor_ms",
            )
        if "attention_" in name:
            _add("cam_item_count", "attention_consumed_total_energy")
        if "sensor_" in name:
            _add("external_sa_count", "merged_flat_token_count", "sensor_echo_pool_size")
        if "state_pool_" in name:
            _add("pool_active_item_count", "pool_high_cp_item_count")
        if "hdb_" in name:
            _add("internal_resolution_raw_unit_count", "stimulus_round_count", "structure_round_count")
        if "induction_source_" in name:
            _add(
                "induction_source_item_count",
                "induction_source_available_st_count",
                "induction_source_selected_from_ev_count",
                "induction_source_selected_from_er_count",
                "induction_source_selected_from_cp_abs_count",
                "induction_source_available_with_local_target_hint_count",
                "induction_source_selected_with_local_target_hint_count",
                "induction_source_selected_zero_local_target_hint_count",
                "induction_raw_residual_entry_count",
                "induction_raw_residual_entry_with_existing_structure_count",
                "induction_raw_residual_entry_routed_to_structure_count",
                "induction_source_selection_cap_hit",
                "induction_target_count",
                "induction_structure_target_count",
                "induction_memory_target_count",
                "induction_raw_residual_structure_target_count",
                "induction_raw_residual_memory_target_count",
                "induction_applied_target_count",
                "induction_skipped_cs_event_target_count",
                "induction_targets_per_source_mean",
                "induction_energy_graph_round_count_max",
                "induction_energy_graph_depth_max",
                "induction_energy_graph_frontier_generated_count",
                "induction_energy_graph_frontier_pruned_count",
                "induction_energy_graph_layer_total_nodes",
                "induction_energy_graph_terminal_memory_count",
                "induction_energy_graph_frontier_budget_total_ev",
                "pool_ev_to_er_ratio",
            )
        if "memory_feedback" in name or "structure_projection" in name:
            _add(
                "map_feedback_total_ev",
                "memory_feedback_applied_count",
                "memory_feedback_total_ev",
                "memory_feedback_packet_count",
                "memory_feedback_packet_total_ev",
                "memory_feedback_packet_applied_total_ev",
                "memory_feedback_packet_apply_efficiency_ev",
                "memory_feedback_structure_projection_ratio_used",
                "memory_feedback_structure_projection_attempted_count",
                "memory_feedback_structure_projection_skipped_count",
                "memory_feedback_structure_projection_count",
                "memory_feedback_structure_projection_effective_ratio",
                "memory_feedback_structure_projection_total_ev",
                "induction_propagated_ev_total",
                "pool_ev_to_er_ratio",
            )
        return sorted(impacts)
    if m == "innate_script":
        _add("cfs_signal_count", "action_drive_max", "action_executed_count")
        return sorted(impacts)
    return sorted(impacts)


def _is_auto_tunable_scalar(*, module: str, path_tokens: list[Any], value: Any) -> bool:
    # Numeric scalars only (by default). Bool/string are kept in the catalog but not tuned automatically.
    if not _is_number(value):
        return False

    # Exclude risky structural lattice knobs
    ignore_top = set(_default_ignore_paths_for_module(module))
    if path_tokens and isinstance(path_tokens[0], str) and str(path_tokens[0]) in ignore_top:
        return False

    return True


def build_module_param_specs(*, module: str, yaml_path: Path, runtime_config: dict[str, Any] | None, source_kind: str) -> list[ParamSpec]:
    raw = {}
    try:
        raw = io.load_yaml_file(yaml_path) if yaml_path.exists() else {}
    except Exception:
        raw = {}

    # Prefer runtime_config values if provided (effective config).
    root = runtime_config if isinstance(runtime_config, dict) and runtime_config else raw
    if not isinstance(root, dict):
        root = raw if isinstance(raw, dict) else {}

    specs: list[ParamSpec] = []
    for path_tokens, leaf in _flatten_yaml_tree(node=root, prefix=[]):
        # Skip empty path (root)
        if not path_tokens:
            continue
        pid = f"{module}.{_path_tokens_to_str(path_tokens)}"
        vtype = _value_type(leaf)
        tags = _guess_tags(module=module, path_tokens=path_tokens, source_kind=source_kind)
        impacts = _guess_impacts(module=module, param_id=pid, tags=tags, source_kind=source_kind)
        allow = _is_auto_tunable_scalar(module=module, path_tokens=path_tokens, value=leaf)
        specs.append(
            ParamSpec(
                param_id=pid,
                source_kind=source_kind,
                module=module,
                path_tokens=list(path_tokens),
                value=leaf,
                value_type=vtype,
                auto_tune_allowed=bool(allow),
                tags=tags,
                impacts=impacts,
            )
        )
    return specs


def build_iesm_rule_param_specs(*, rules_doc: dict[str, Any]) -> list[ParamSpec]:
    """Extract numeric tunables from IESM rules doc (best-effort)."""
    rules = rules_doc.get("rules") if isinstance(rules_doc, dict) else None
    rules = rules if isinstance(rules, list) else []

    specs: list[ParamSpec] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id", "") or "").strip()
        if not rule_id:
            continue

        # We only index a conservative subset of numeric leaves to avoid tuning UI text, IDs, etc.
        # Allowed leaf keys (heuristic).
        allowed_leaf_names = {
            "priority",
            "cooldown_ticks",
            "window_ticks",
            "top_n",
            "value",
            "min_strength",
            "max_signals",
            "max_triggers",
            "gain",
            "threshold",
            "min_delta",
            "min_interval_ticks",
            "out_min",
            "out_max",
            "min",
            "max",
            "attribute_value",
            "er",
            "ev",
        }

        def _walk(node: Any, prefix: list[Any]) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    kk = str(k) if not isinstance(k, str) else k
                    if kk in {"ui", "note", "title", "id", "display", "raw", "message"}:
                        continue
                    _walk(v, prefix + [kk])
                return
            if isinstance(node, list):
                for idx, v in enumerate(node):
                    _walk(v, prefix + [idx])
                return
            # leaf
            if not _is_number(node):
                return
            leaf_name = str(prefix[-1]) if prefix else ""
            if leaf_name not in allowed_leaf_names:
                return

            path_tokens = list(prefix)
            pid = f"iesm.rules.{rule_id}.{_path_tokens_to_str(path_tokens)}"
            tags = _guess_tags(module="iesm", path_tokens=[rule_id] + path_tokens, source_kind="iesm_rule")
            impacts = _guess_impacts(module="iesm", param_id=pid, tags=tags, source_kind="iesm_rule")
            specs.append(
                ParamSpec(
                    param_id=pid,
                    source_kind="iesm_rule",
                    module="iesm",
                    path_tokens=[rule_id] + path_tokens,  # first token is rule_id for patching
                    value=node,
                    value_type=_value_type(node),
                    auto_tune_allowed=True,
                    tags=tags,
                    impacts=impacts,
                    note="auto-indexed from innate_rules.yaml",
                )
            )

        _walk(rule, [])

    return specs


def build_param_catalog(*, app: Any | None = None) -> list[ParamSpec]:
    root = storage.repo_root()

    # Module configs
    configs: list[tuple[str, Path, str]] = [
        ("observatory", root / "observatory" / "config" / "observatory_config.yaml", "observatory_config"),
        ("action", root / "action" / "config" / "action_config.yaml", "module_config"),
        ("attention", root / "attention" / "config" / "attention_config.yaml", "module_config"),
        ("cognitive_stitching", root / "cognitive_stitching" / "config" / "cognitive_stitching_config.yaml", "module_config"),
        ("cognitive_feeling", root / "cognitive_feeling" / "config" / "cognitive_feeling_config.yaml", "module_config"),
        ("emotion", root / "emotion" / "config" / "emotion_config.yaml", "module_config"),
        ("energy_balance", root / "energy_balance" / "config" / "energy_balance_config.yaml", "module_config"),
        ("hdb", root / "hdb" / "config" / "hdb_config.yaml", "module_config"),
        ("innate_script", root / "innate_script" / "config" / "innate_script_config.yaml", "module_config"),
        ("state_pool", root / "state_pool" / "config" / "state_pool_config.yaml", "module_config"),
        ("text_sensor", root / "text_sensor" / "config" / "text_sensor_config.yaml", "module_config"),
        ("time_sensor", root / "time_sensor" / "config" / "time_sensor_config.yaml", "module_config"),
    ]

    def _runtime_cfg(mod: str) -> dict[str, Any] | None:
        if app is None:
            return None
        try:
            if mod == "observatory":
                return dict(getattr(app, "_config", {}) or {})
            if mod == "action":
                return dict(getattr(getattr(app, "action", None), "_config", {}) or {})
            if mod == "attention":
                return dict(getattr(getattr(app, "attention", None), "_config", {}) or {})
            if mod == "cognitive_stitching":
                return dict(getattr(getattr(app, "cognitive_stitching", None), "_config", {}) or {})
            if mod == "cognitive_feeling":
                return dict(getattr(getattr(app, "cfs", None), "_config", {}) or {})
            if mod == "emotion":
                return dict(getattr(getattr(app, "emotion", None), "_config", {}) or {})
            if mod == "energy_balance":
                return dict(getattr(getattr(app, "energy_balance", None), "_config", {}) or {})
            if mod == "hdb":
                return dict(getattr(getattr(app, "hdb", None), "_config", {}) or {})
            if mod == "innate_script":
                return dict(getattr(getattr(app, "iesm", None), "_config", {}) or {})
            if mod == "state_pool":
                return dict(getattr(getattr(app, "pool", None), "_config", {}) or {})
            if mod == "text_sensor":
                return dict(getattr(getattr(app, "sensor", None), "_config", {}) or {})
            if mod == "time_sensor":
                return dict(getattr(getattr(app, "time_sensor", None), "_config", {}) or {})
        except Exception:
            return None
        return None

    specs: list[ParamSpec] = []
    for mod, path, kind in configs:
        runtime = _runtime_cfg(mod)
        specs.extend(build_module_param_specs(module=mod, yaml_path=path, runtime_config=runtime, source_kind=kind))

    # IESM rules doc:
    # Prefer the *effective* runtime rules path when an app is provided, so the catalog
    # matches the actual rule graph currently in use (e.g. persisted overrides).
    rules_path = root / "innate_script" / "config" / "innate_rules.yaml"
    try:
        if app is not None:
            p = getattr(getattr(app, "iesm", None), "_rules_path", None)
            if isinstance(p, str) and p.strip():
                candidate = Path(p).resolve()
                if candidate.exists():
                    rules_path = candidate
    except Exception:
        pass

    try:
        rules_doc = io.load_yaml_file(rules_path)
    except Exception:
        rules_doc = {}
    if isinstance(rules_doc, dict):
        specs.extend(build_iesm_rule_param_specs(rules_doc=rules_doc))

    # De-duplicate by param_id (keep first)
    seen: set[str] = set()
    out: list[ParamSpec] = []
    for s in specs:
        if s.param_id in seen:
            continue
        seen.add(s.param_id)
        out.append(s)
    return out


# ------------------------------
# Bounds heuristics
# ------------------------------


def guess_bound_for_param(spec: ParamSpec) -> ParamBound | None:
    """Best-effort bounds. Users can override via outputs/auto_tuner/config.json."""
    if not spec.auto_tune_allowed:
        return None
    if not _is_number(spec.value):
        return None

    name = spec.param_id.lower()
    v = float(spec.value)

    # Integer-like leaves
    is_int_like = spec.value_type == "int"

    if name == "text_sensor.echo_round_decay_factor":
        return ParamBound(0.12, 0.70, 0.03, quantum=0.01)
    if name == "text_sensor.echo_min_energy_threshold":
        return ParamBound(0.04, 0.30, 0.02, quantum=0.01)
    if name == "text_sensor.echo_pool_max_frames":
        return ParamBound(3.0, 20.0, 1.0, quantum=1.0)
    if name == "observatory.input_chunk_soft_limit":
        return ParamBound(8.0, 64.0, 4.0, quantum=1.0)
    if name == "observatory.input_chunk_hard_limit":
        return ParamBound(16.0, 128.0, 4.0, quantum=1.0)
    if name == "hdb.stimulus_round_debug_full_text_rounds":
        return ParamBound(0.0, 24.0, 2.0, quantum=1.0)
    if name == "hdb.stimulus_round_debug_token_preview_limit":
        return ParamBound(0.0, 96.0, 8.0, quantum=1.0)
    if name in {
        "hdb.stimulus_round_debug_candidate_detail_limit",
        "hdb.stimulus_round_debug_shadow_candidate_detail_limit",
    }:
        return ParamBound(0.0, 64.0, 4.0, quantum=1.0)

    if name == "time_sensor.memory_top_k":
        return ParamBound(4.0, 24.0, 2.0, quantum=1.0)
    if name == "time_sensor.max_total_bindings":
        return ParamBound(4.0, 24.0, 2.0, quantum=1.0)
    if name == "time_sensor.delayed_task_capacity":
        return ParamBound(12.0, 96.0, 8.0, quantum=1.0)
    if name == "time_sensor.max_projection_bind_targets_per_memory":
        return ParamBound(1.0, 4.0, 1.0, quantum=1.0)
    if name == "time_sensor.projection_target_keep_ratio":
        return ParamBound(0.45, 0.90, 0.04, quantum=0.01)
    if name == "time_sensor.delayed_task_register_min_delta_energy":
        return ParamBound(0.08, 0.80, 0.04, quantum=0.01)
    if name == "time_sensor.delayed_task_energy_ratio":
        return ParamBound(0.35, 0.85, 0.03, quantum=0.01)
    if name == "time_sensor.delayed_task_energy_min":
        return ParamBound(0.02, 0.20, 0.01, quantum=0.005)
    if name == "time_sensor.delayed_task_energy_max":
        return ParamBound(0.20, 1.20, 0.04, quantum=0.01)

    if name.startswith("emotion.nt_channels.") and name.endswith(".base"):
        return ParamBound(0.0, 0.35, 0.02, quantum=0.01)
    if name.startswith("emotion.nt_channels.") and name.endswith(".soft_cap_k"):
        return ParamBound(0.18, 0.60, 0.02, quantum=0.01)
    if name.startswith("emotion.nt_channels.") and name.endswith(".decay_ratio"):
        return ParamBound(0.80, 0.97, 0.01, quantum=0.001)
    if name.startswith("emotion.cfs_to_nt_gains.") or name.startswith("emotion.rwd_pun_to_nt_gains."):
        return ParamBound(-0.18, 0.28, 0.02, quantum=0.01)
    if name.startswith("emotion.modulation.hdb.scales.") and name.endswith(".base"):
        return ParamBound(0.55, 1.45, 0.04, quantum=0.01)
    if name == "action.mode_attention_energy_budget_base":
        return ParamBound(0.0, 8.0, 1.0, quantum=1.0)
    if name == "action.mode_attention_energy_budget_min":
        return ParamBound(0.0, 2.0, 0.25, quantum=0.01)
    if name == "action.mode_attention_energy_budget_max":
        return ParamBound(10.0, 24.0, 1.0, quantum=1.0)
    if name == "attention.attention_energy_budget_base":
        return ParamBound(0.0, 8.0, 1.0, quantum=1.0)
    if name == "attention.attention_energy_budget_min":
        return ParamBound(0.0, 2.0, 0.25, quantum=0.01)
    if name == "attention.attention_energy_budget_max":
        return ParamBound(10.0, 32.0, 1.0, quantum=1.0)
    if name == "state_pool.energy_injection_fatigue_same_side_knee_er":
        return ParamBound(1.0, 12.0, 0.50, quantum=0.05)
    if name == "state_pool.energy_injection_fatigue_same_side_knee_ev":
        return ParamBound(0.8, 10.0, 0.50, quantum=0.05)
    if name == "state_pool.energy_injection_fatigue_total_knee":
        return ParamBound(2.0, 24.0, 0.80, quantum=0.05)
    if name == "state_pool.energy_injection_fatigue_saturation_power":
        return ParamBound(0.60, 2.80, 0.10, quantum=0.01)
    if name == "state_pool.energy_injection_fatigue_total_weight":
        return ParamBound(0.0, 0.80, 0.05, quantum=0.01)
    if name == "state_pool.energy_injection_fatigue_min_scale":
        return ParamBound(0.05, 0.55, 0.04, quantum=0.01)
    if name == "state_pool.energy_injection_repeat_fatigue_step":
        return ParamBound(0.05, 1.20, 0.06, quantum=0.01)
    if name == "state_pool.energy_injection_repeat_fatigue_decay_per_tick":
        return ParamBound(0.70, 0.98, 0.02, quantum=0.001)
    if name == "state_pool.energy_injection_repeat_fatigue_floor_scale":
        return ParamBound(0.10, 0.80, 0.04, quantum=0.01)
    if name.startswith("emotion.modulation.attention.field_specs."):
        leaf_name = str(spec.path_tokens[-1]).lower() if spec.path_tokens else ""
        field_name = str(spec.path_tokens[-2]).lower() if len(spec.path_tokens) >= 2 else ""
        if field_name == "attention_energy_budget":
            if leaf_name == "base":
                return ParamBound(0.0, 8.0, 1.0, quantum=1.0)
            if leaf_name == "min":
                return ParamBound(0.0, 2.0, 0.25, quantum=0.01)
            if leaf_name == "max":
                return ParamBound(10.0, 32.0, 1.0, quantum=1.0)
            if leaf_name.endswith("_gain") or leaf_name.endswith("_suppress"):
                return ParamBound(0.0, 8.0, 0.25, quantum=0.01)
        if leaf_name.endswith("_gain") or leaf_name.endswith("_suppress"):
            return ParamBound(0.0, 0.85, 0.02, quantum=0.01)
        if leaf_name == "base":
            if field_name == "top_n":
                return ParamBound(4.0, 64.0, 2.0, quantum=1.0)
            if field_name == "min_cam_items":
                return ParamBound(1.0, 12.0, 1.0, quantum=1.0)
            if is_int_like:
                hi = max(4.0, math.ceil(v * 1.75 + 2.0))
                return ParamBound(0.0, hi, 1.0, quantum=1.0)
            hi = max(1.2, min(4.0, v * 1.8 + 0.4))
            step = 0.05 if v <= 1.5 else 0.10
            return ParamBound(0.0, hi, step, quantum=0.01)

    # Heuristics by name patterns
    if name.endswith("_ms") or "timeout" in name or "sleep_ms" in name:
        lo, hi = 0.0, max(10.0, v * 4.0 + 100.0)
        step = max(10.0, abs(v) * 0.05)
        return ParamBound(lo, hi, step, quantum=1.0 if is_int_like else 1.0)

    if any(k in name for k in ["_ticks", "_rounds", "window", "top_n", "max_", "capacity", "history_keep", "max_items"]):
        if is_int_like:
            base = max(1.0, float(v))
            lo, hi = 0.0, max(8.0, math.ceil(base * 3.0 + 8.0))
            step = 1.0
            return ParamBound(lo, hi, step, quantum=1.0)
        base = max(0.0, float(v))
        lo, hi = 0.0, max(1.0, base * 3.0 + 1.0)
        step = max(0.05, abs(base) * 0.08)
        return ParamBound(lo, hi, step, quantum=0.01)

    if "decay_ratio" in name or "retention" in name:
        # Ratios close to 1.0 are extremely sensitive; use tiny steps.
        lo = 0.0
        hi = 0.9999999 if v > 0.99 else 1.2
        if v > 0.99:
            return ParamBound(lo, hi, max_step_abs=5e-6, quantum=1e-6)
        return ParamBound(lo, hi, max_step_abs=0.01, quantum=0.001)

    if "half_life" in name:
        lo, hi = 0.05, max(1.0, v * 5.0 + 1.0)
        step = 0.2 if v < 3.0 else 0.5
        return ParamBound(lo, hi, step, quantum=0.05)

    if "threshold" in name or name.endswith("_min") or name.endswith("_max"):
        lo, hi = 0.0, max(1.0, v * 2.5 + 0.2)
        step = 0.02 if v <= 2.0 else 0.05
        return ParamBound(lo, hi, step, quantum=0.01)

    if "ratio" in name or "scale" in name or "gain" in name:
        lo, hi = 0.0, max(1.5, v * 3.0 + 0.3)
        step = 0.02 if v < 1.0 else 0.05
        return ParamBound(lo, hi, step, quantum=0.01)

    # Generic numeric
    lo, hi = (0.0, max(1.0, v * 3.0 + 1.0)) if v >= 0.0 else (v * 3.0 - 1.0, max(0.0, v * -1.0 + 1.0))
    step = max(0.01, abs(v) * 0.05)
    quantum = 1.0 if is_int_like else 0.01
    return ParamBound(lo, hi, step, quantum=quantum)


def build_default_param_bounds(specs: Iterable[ParamSpec]) -> dict[str, ParamBound]:
    out: dict[str, ParamBound] = {}
    for spec in specs:
        b = guess_bound_for_param(spec)
        if b is None:
            continue
        out[spec.param_id] = b
    return out


# ------------------------------
# Output helpers (gitignored)
# ------------------------------


def auto_tuner_dir() -> Path:
    return storage.repo_root() / "observatory" / "outputs" / "auto_tuner"


def write_catalog_outputs(*, specs: Iterable[ParamSpec], bounds: dict[str, ParamBound] | None = None) -> dict[str, Any]:
    """
    Write catalog + bounds summary under outputs/auto_tuner/ (gitignored).
    Returns a small summary dict for auditing.
    """
    specs_list = list(specs)
    bounds = bounds or {}

    out_dir = auto_tuner_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog_path = out_dir / "param_catalog.json"
    bounds_path = out_dir / "param_bounds.guessed.json"
    md_path = out_dir / "param_impact_table.md"

    catalog_payload = {
        "generated_at_ms": int(time.time() * 1000),
        "count": len(specs_list),
        "params": [s.to_dict() for s in specs_list],
    }
    catalog_path.write_text(json.dumps(catalog_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    bounds_payload = {
        "generated_at_ms": int(time.time() * 1000),
        "count": len(bounds),
        "bounds": {k: dataclasses.asdict(v) for k, v in bounds.items()},
    }
    bounds_path.write_text(json.dumps(bounds_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Human-friendly table (compact but searchable)
    lines: list[str] = []
    lines.append("# AutoTuner 参数-影响对应表（自动生成）")
    lines.append("")
    lines.append("说明：这是一个工程级“索引表”。`impacts` 是基于模块/命名启发式推断的“可能影响的长期指标”，用于调参器选参，不是论文级因果证明。")
    lines.append("")
    lines.append("| param_id | type | auto_tune | tags | impacts | bound |")
    lines.append("|---|---:|:---:|---|---|---|")
    for s in specs_list:
        b = bounds.get(s.param_id)
        bound_s = "-"
        if b is not None:
            bound_s = f"[{b.min_value:g},{b.max_value:g}] step<= {b.max_step_abs:g}"
        lines.append(
            f"| `{s.param_id}` | {s.value_type} | {'Y' if s.auto_tune_allowed else 'N'} | {', '.join(s.tags) or '-'} | {', '.join(s.impacts) or '-'} | {bound_s} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "catalog_path": str(catalog_path),
        "bounds_path": str(bounds_path),
        "impact_table_path": str(md_path),
        "param_count": len(specs_list),
        "bound_count": len(bounds),
    }
