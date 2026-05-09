# -*- coding: utf-8 -*-
"""
AP 文本感受器 -> 状态池 增强联动演示
==================================

目标：
1. 让用户清楚看到文本刺激如何从 TextSensor 落到 StatePool。
2. 明确区分“感受器残响”与“状态池维护”的边界。
3. 让状态池的 8 个主要接口都能在交互中体现。
4. 强化 CSA / 绑定对象的可解释展示，至少显示锚点和属性摘要。

运行方式：
    python state_pool/tests/run_integration.py
或：
    python state_pool/tests/run_integration_enhanced.py
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from text_sensor import TextSensor
from state_pool.main import StatePool
from state_pool._id_generator import reset_id_generator as reset_spm_ids


MODE_LABELS = {
    "simple": "简易模式（按字符切分）",
    "advanced": "高级模式（按词元切分）",
    "hybrid": "混合模式（字符+词元）",
}

SOURCE_TYPE_LABELS = {
    "current": "当前输入组",
    "echo": "残响组",
}

EVENT_LABELS = {
    "created": "新建",
    "energy_update": "能量更新",
    "decay": "衰减",
    "neutralization": "中和",
    "pruned": "淘汰",
    "merged": "合并",
    "bind_attribute": "属性绑定",
}

REF_TYPE_LABELS = {
    "sa": "基础刺激元(SA)",
    "csa": "组合刺激元(CSA)",
    "st": "结构节点(ST)",
    "action_node": "行动节点(action_node)",
    "cfs_signal": "认知感受信号(cfs_signal)",
}

DECAY_MODE_LABELS = {
    "round_factor": "固定轮次系数衰减(round_factor)",
    "round_half_life": "半衰期衰减(round_half_life)",
}


def print_divider(char: str = "=", width: int = 96):
    print(char * width)


def print_header():
    print(f"\n{'=' * 96}")
    print("  AP 文本感受器 -> 状态池 增强联动演示")
    print("  AP TextSensor -> StatePool Enhanced Integration Console")
    print(f"{'=' * 96}\n")
    print("  术语说明 / Glossary:")
    print("  - SA（基础刺激元 / Stimulus Atom）：最小刺激单元，也是最小能量拥有单位")
    print("  - CSA（组合刺激元 / Composite Stimulus Atom）：由特征 SA 与属性 SA 绑定形成")
    print("  - 实能量（er）：当前现实侧激活强度")
    print("  - 虚能量（ev）：当前预测侧或内部侧激活强度")
    print("  - 认知压幅值（cp）：|er - ev|，用于观察现实与预测之间的偏差大小\n")


def print_help():
    print("  说明 / Instructions:")
    print("  - 直接输入任意文本：文本感受器（TextSensor）生成刺激包（stimulus_packet）并写入状态池")
    print("  - `tick [n]`：执行 1~n 轮状态池维护，展示衰减 / 中和 / 淘汰 / 脚本抄送")
    print("  - `autotick [on|off|ask]`：设置“处理下一条文本前”是否先自动执行一轮状态池维护")
    print("  - `packet [groups|trails|full]`：查看最近一次刺激包的时序分组与跨组重现轨迹")
    print("  - `snap [k]`：查看状态池快照与 Top-K（按认知压排序）")
    print("  - `inspect [rank|item_id]`：查看单个状态池项的完整细节")
    print("  - `history [n]`：查看最近 n 条状态变化事件")
    print("  - `bind [rank|item_id] [attribute]`：绑定属性，默认 `correctness:high`")
    print("  - `energy [rank|item_id] [delta_er] [delta_ev]`：定向能量更新")
    print("  - `insert [kind] [label] [er] [ev]`：插入运行态节点，kind 支持 cfs/action/st/sa")
    print("  - `attention [k]`：生成注意力快照并调用占位注意力接口")
    print("  - `reload`：热加载状态池配置")
    print("  - `config`：查看关键配置")
    print("  - `clear`：清空状态池")
    print("  - `help`：再次查看帮助")
    print("  - `quit` / `exit`：退出\n")


def shorten(text: str, limit: int = 32) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_cli_token(value: str | None, default: str = "") -> str:
    token = str(value or default).strip().lower()
    while token and token[0] in "[({<" and token[-1] in "])}>":
        token = token[1:-1].strip().lower()
    return token


def describe_mode(mode: str) -> str:
    return MODE_LABELS.get(mode, mode)


def describe_source_type(source_type: str) -> str:
    return SOURCE_TYPE_LABELS.get(source_type, source_type or "未知来源组")


def describe_event_type(event_type: str) -> str:
    return EVENT_LABELS.get(event_type, event_type or "未知事件")


def describe_ref_type(ref_type: str) -> str:
    return REF_TYPE_LABELS.get(ref_type, ref_type or "未知类型")


def describe_decay_mode(mode: str) -> str:
    return DECAY_MODE_LABELS.get(mode, mode or "未知衰减模式")


def get_snapshot(pool: StatePool, trace_id: str, top_k: int = 10, sort_by: str = "cp_abs") -> dict:
    return pool.get_state_snapshot(trace_id=trace_id, top_k=top_k, sort_by=sort_by)["data"]["snapshot"]


def get_top_items(pool: StatePool, top_k: int = 10, sort_by: str = "cp_abs") -> list[dict]:
    return get_snapshot(pool, trace_id=f"top_{int(time.time() * 1000)}", top_k=top_k, sort_by=sort_by)["top_items"]


def resolve_item_id(pool: StatePool, spec: str | None) -> tuple[str | None, dict | None]:
    items = get_top_items(pool, top_k=20)
    if not items:
        return None, None

    if not spec:
        return items[0]["item_id"], items[0]

    if spec.isdigit():
        rank = max(1, int(spec))
        if rank <= len(items):
            return items[rank - 1]["item_id"], items[rank - 1]
        return None, None

    item = pool._store.get(spec)  # 测试脚本允许读取内部对象以获得完整细节
    if not item:
        return None, None

    summary = None
    for candidate in items:
        if candidate["item_id"] == spec:
            summary = candidate
            break
    if summary is None:
        summary = pool._snapshot._build_top_item_summary(item)
    return spec, summary


def get_new_events(pool: StatePool, before_total_recorded: int) -> list[dict]:
    after_total_recorded = pool._history.total_recorded
    new_count = max(0, after_total_recorded - before_total_recorded)
    if new_count <= 0:
        return []
    return pool._history.get_recent(new_count)


def build_script_packet_preview(pool: StatePool, events: list[dict], trace_id: str) -> dict | None:
    if not events:
        return None
    return pool._snapshot.build_script_check_packet(
        events=events,
        pool_store=pool._store,
        trace_id=trace_id,
        tick_id=trace_id,
    )


def _build_packet_object_index(packet: dict, key: str) -> dict[str, dict]:
    return {
        obj["id"]: obj
        for obj in packet.get(key, [])
        if isinstance(obj, dict) and obj.get("id")
    }


def _extract_packet_object_display(obj: dict) -> str:
    if not isinstance(obj, dict):
        return ""
    content = obj.get("content", {})
    return str(content.get("display") or content.get("raw") or content.get("normalized") or obj.get("id", ""))


def _extract_packet_object_semantic_key(obj: dict) -> str:
    object_type = obj.get("object_type", "")
    if object_type == "sa":
        stimulus = obj.get("stimulus", {})
        role = stimulus.get("role", "")
        content = obj.get("content", {})
        if role == "attribute":
            attribute_name = content.get("attribute_name")
            if not attribute_name:
                raw = str(content.get("normalized") or content.get("display") or content.get("raw") or "")
                attribute_name = raw.split(":", 1)[0] if ":" in raw else raw
            parent_id = obj.get("source", {}).get("parent_ids", [""])
            parent_id = parent_id[0] if parent_id else ""
            return f"sa|attribute|{attribute_name}|parent={parent_id}"
        return f"sa|feature|{_extract_packet_object_display(obj)}"

    if object_type == "csa":
        return f"csa|{_extract_packet_object_display(obj)}"

    return f"{object_type}|{_extract_packet_object_display(obj)}"


def build_packet_group_summaries(packet: dict, max_samples_per_type: int = 4) -> list[dict]:
    """
    从 stimulus_packet 中提取“顺序敏感的分组结构”摘要。

    这层摘要用于交互演示和后续 HDB 对接前的结构核对，
    重点强调：
    1. 每个 group 的 source_type（echo/current）
    2. 每组承载了哪些 SA / CSA
    3. 每组当前能量是多少
    4. 组内有哪些代表性对象
    """
    sa_index = _build_packet_object_index(packet, "sa_items")
    csa_index = _build_packet_object_index(packet, "csa_items")
    summaries: list[dict] = []

    for order_index, group in enumerate(packet.get("grouped_sa_sequences", []), start=1):
        group_sa = [sa_index[sid] for sid in group.get("sa_ids", []) if sid in sa_index]
        group_csa = [csa_index[cid] for cid in group.get("csa_ids", []) if cid in csa_index]
        feature_samples = [
            _extract_packet_object_display(sa)
            for sa in group_sa
            if sa.get("stimulus", {}).get("role") != "attribute"
        ][:max_samples_per_type]
        attribute_samples = [
            _extract_packet_object_display(sa)
            for sa in group_sa
            if sa.get("stimulus", {}).get("role") == "attribute"
        ][:max_samples_per_type]
        csa_samples = [_extract_packet_object_display(csa) for csa in group_csa][:max_samples_per_type]

        packet_context = None
        if group_sa:
            packet_context = group_sa[0].get("ext", {}).get("packet_context", {})
        elif group_csa:
            packet_context = group_csa[0].get("ext", {}).get("packet_context", {})
        else:
            packet_context = {}

        summaries.append(
            {
                "order_index": order_index,
                "group_index": group.get("group_index", order_index - 1),
                "source_type": group.get("source_type", ""),
                "origin_frame_id": group.get("origin_frame_id", ""),
                "echo_depth": packet_context.get("echo_depth", 0),
                "decay_count": packet_context.get("decay_count", 0),
                "round_created": packet_context.get("round_created", 0),
                "sa_count": len(group_sa),
                "csa_count": len(group_csa),
                "total_sa_er": round(sum(sa.get("energy", {}).get("er", 0.0) for sa in group_sa), 6),
                "total_csa_er": round(sum(csa.get("energy", {}).get("er", 0.0) for csa in group_csa), 6),
                "feature_samples": feature_samples,
                "attribute_samples": attribute_samples,
                "csa_samples": csa_samples,
            }
        )

    return summaries


def build_packet_semantic_trails(packet: dict, max_occurrences: int = 6) -> list[dict]:
    """
    提取跨 group 重复出现的对象轨迹，用于观察 echo -> current 的时序组合。
    """
    grouped_members: dict[str, dict] = {}
    for obj in packet.get("sa_items", []):
        grouped_members[obj["id"]] = obj
    for obj in packet.get("csa_items", []):
        grouped_members[obj["id"]] = obj

    trails: dict[str, dict] = {}
    for group in packet.get("grouped_sa_sequences", []):
        member_ids = list(group.get("sa_ids", [])) + list(group.get("csa_ids", []))
        for member_id in member_ids:
            obj = grouped_members.get(member_id)
            if not obj:
                continue
            semantic_key = _extract_packet_object_semantic_key(obj)
            display = _extract_packet_object_display(obj)
            packet_context = obj.get("ext", {}).get("packet_context", {})
            appearance = {
                "group_index": group.get("group_index", 0),
                "source_type": packet_context.get("source_type", group.get("source_type", "")),
                "echo_depth": packet_context.get("echo_depth", 0),
                "decay_count": packet_context.get("decay_count", 0),
                "er": round(obj.get("energy", {}).get("er", 0.0), 6),
                "object_id": obj.get("id", ""),
            }
            trail = trails.setdefault(
                semantic_key,
                {
                    "semantic_key": semantic_key,
                    "display": display,
                    "object_type": obj.get("object_type", ""),
                    "appearances": [],
                },
            )
            trail["appearances"].append(appearance)

    repeated = [trail for trail in trails.values() if len(trail["appearances"]) >= 2]
    repeated.sort(key=lambda trail: (-len(trail["appearances"]), trail["display"]))

    for trail in repeated:
        trail["appearances"] = trail["appearances"][:max_occurrences]

    return repeated


def print_packet_groups(group_summaries: list[dict], max_groups: int = 8):
    print("  分组视图（刺激包内部时序分组）/ Grouped packet view:")
    print("    字段说明：SA=基础刺激元数量，CSA=组合刺激元数量，实能量合计=本组对象当前 er 总和")
    for summary in group_summaries[:max_groups]:
        group_label = f"第{summary['order_index'] - 1}组"
        source_text = describe_source_type(summary["source_type"])
        if summary["source_type"] == "echo":
            source_text = (
                f"{source_text}，距当前 {summary['echo_depth']} 轮，"
                f"已衰减 {summary['decay_count']} 次"
            )

        print(
            f"    {group_label}（{source_text}） "
            f"基础刺激元(SA)={summary['sa_count']}  "
            f"组合刺激元(CSA)={summary['csa_count']}  "
            f"SA 实能量合计={summary['total_sa_er']:.4f}  "
            f"CSA 实能量合计={summary['total_csa_er']:.4f}"
        )
        if summary["feature_samples"]:
            print(f"         特征刺激元（features）: {', '.join(summary['feature_samples'])}")
        if summary["attribute_samples"]:
            print(f"         属性刺激元（attributes）: {', '.join(summary['attribute_samples'])}")
        if summary["csa_samples"]:
            print(f"         组合刺激元（CSAs）: {', '.join(summary['csa_samples'])}")
        if summary["origin_frame_id"]:
            print(f"         来源帧ID（origin）: {shorten(summary['origin_frame_id'], 64)}")


def print_packet_trails(trails: list[dict], max_trails: int = 8):
    print("\n  跨组重现轨迹（同一语义对象在不同组中的出现路径）/ Cross-group semantic trails:")
    if not trails:
        print("    无跨组重现对象 / No cross-group trails")
        return

    for trail in trails[:max_trails]:
        appearance_parts = []
        for appearance in trail["appearances"]:
            source_text = describe_source_type(appearance["source_type"])
            if appearance["source_type"] == "echo":
                part = (
                    f"{source_text}#组{appearance['group_index']} "
                    f"(er={appearance['er']:.4f}, 已衰减{appearance['decay_count']}次)"
                )
            else:
                part = f"{source_text}#组{appearance['group_index']} (er={appearance['er']:.4f})"
            appearance_parts.append(part)
        print(f"    {shorten(trail['display'], 24):<24} {' -> '.join(appearance_parts)}")


def print_packet_structure(packet: dict, max_groups: int = 8, max_trails: int = 8):
    print("\n  [2/4] 刺激包时序结构 / Packet temporal structure")
    print_divider("-", 112)

    group_summaries = build_packet_group_summaries(packet)
    if not group_summaries:
        print("  无分组信息 / No grouped sequence data")
        return

    print_packet_groups(group_summaries, max_groups=max_groups)
    print_packet_trails(build_packet_semantic_trails(packet), max_trails=max_trails)


def print_pool_summary(snapshot: dict):
    summary = snapshot["summary"]
    type_counts = summary.get("object_type_counts", {})
    type_summary = ", ".join(f"{key}:{value}" for key, value in sorted(type_counts.items())) or "none"
    print("  当前状态池概览 / Current StatePool overview:")
    print(
        f"    活跃对象 / Active: {summary['active_item_count']}  |  "
        f"高认知压 / High-CP: {summary['high_cp_item_count']}  |  "
        f"绑定属性对象 / Attribute-bound: {summary.get('bound_attribute_item_count', 0)}"
    )
    print(f"    类型分布 / Type counts: {type_summary}")
    if "history_window_ref" in snapshot:
        history = snapshot["history_window_ref"]
        print(
            f"    历史窗口 / History window: 当前窗口事件数={history.get('current_size', 0)}  "
            f"累计记录事件数={history.get('total_recorded', 0)}"
        )


def print_top_items(items: list[dict], max_show: int = 8):
    if not items:
        print("  （状态池为空 / StatePool is empty）")
        return

    print("\n  高关注对象（默认按认知压幅值排序）/ Top items:")
    print("  字段说明：实能量(er) | 虚能量(ev) | 认知压幅值(cp) | 本轮认知压变化(dCp) | 认知压变化率(rate)")
    print_divider("-", 112)
    for index, item in enumerate(items[:max_show], start=1):
        label = shorten(item.get("display", "?"), 24)
        ref_type = shorten(describe_ref_type(item.get("ref_object_type", "?")), 18)
        print(
            f"  {index:>2}. {label:<24} 类型={ref_type:<18} "
            f"实能量(er)={item.get('er', 0):>7.4f}  虚能量(ev)={item.get('ev', 0):>7.4f}  "
            f"认知压(cp)={item.get('cp_abs', 0):>7.4f}  本轮变化(dCp)={item.get('delta_cp_abs', 0):>+7.4f}  "
            f"变化率(rate)={item.get('cp_abs_rate', 0):>+9.4f}  更新次数={item.get('update_count', 0):>3}"
        )
        detail = item.get("display_detail", "")
        if detail:
            print(f"      -> {shorten(detail, 96)}")
    if len(items) > max_show:
        print(f"  ... 其余 {len(items) - max_show} 个对象未展开 / {len(items) - max_show} more items omitted")


def print_sensor_summary(ts_result: dict):
    data = ts_result["data"]
    stats = data["stats"]
    packet = data["stimulus_packet"]
    token_summary = data["tokenization_summary"]
    echo_decay = data["echo_decay_summary"]
    echo_frames = packet.get("echo_frames", [])
    echo_sa_count = sum(len(frame.get("sa_items", [])) for frame in echo_frames)
    echo_csa_count = sum(len(frame.get("csa_items", [])) for frame in echo_frames)

    print("  [1/4] 文本感受器处理结果 / TextSensor processing result")
    print(
        f"        -> 本轮特征刺激元（Feature SA）: {stats['feature_sa_count']}  "
        f"本轮属性刺激元（Attribute SA）: {stats['attribute_sa_count']}  "
        f"本轮组合刺激元（CSA）: {stats['csa_count']}"
    )
    print(
        f"        -> 切分模式 / Mode: {describe_mode(token_summary['mode'])}  "
        f"本次引用的历史残响帧数: {len(data.get('echo_frames_used', []))}  "
        f"刺激包中的时序组数: {len(packet.get('grouped_sa_sequences', []))}"
    )
    print(
        f"        -> 刺激包对象汇总 / Packet objects: 基础刺激元(SA)={len(packet.get('sa_items', []))}  "
        f"组合刺激元(CSA)={len(packet.get('csa_items', []))}  "
        f"其中历史残响贡献: 帧={len(echo_frames)} / SA={echo_sa_count} / CSA={echo_csa_count}"
    )
    print(
        f"        -> 残响衰减 / Echo decay: 模式={describe_decay_mode(echo_decay.get('decay_mode', ''))}  "
        f"系数={echo_decay.get('decay_factor', 0):.4f}  "
        f"处理前帧数={echo_decay.get('frames_before', 0)}  "
        f"处理后帧数={echo_decay.get('frames_after', 0)}  "
        f"被淘汰 SA={echo_decay.get('sa_eliminated_count', 0)}  "
        f"被淘汰帧={echo_decay.get('frames_eliminated_count', 0)}"
    )


def print_state_apply_summary(result: dict):
    data = result["data"]
    delta_summary = data.get("state_delta_summary", {})
    print("  [3/4] 状态池接收刺激包 / StatePool applying stimulus packet")
    print(
        f"        -> 新建对象={data['new_item_count']}  "
        f"更新对象={data['updated_item_count']}  "
        f"合并次数={data['merged_item_count']}  "
        f"中和次数={data['neutralized_item_count']}  "
        f"拒绝对象={data['rejected_object_count']}"
    )
    print(
        f"        -> 总实能量变化(dEr)={delta_summary.get('total_delta_er', 0):.4f}  "
        f"总虚能量变化(dEv)={delta_summary.get('total_delta_ev', 0):.4f}  "
        f"高认知压对象数={delta_summary.get('high_cp_item_count', 0)}"
    )
    print(
        f"        -> 脚本检查抄送 / Script broadcast: "
        f"{'已发送 / sent' if data.get('script_broadcast_sent') else '已跳过 / skipped'}"
    )


def print_event_summary(pool: StatePool, events: list[dict], title_zh: str, title_en: str, max_show: int = 8):
    print(f"\n  {title_zh} / {title_en}:")
    if not events:
        print("    无新增事件 / No new events")
        return

    counts = Counter(event.get("event_type", "unknown") for event in events)
    print("    事件分布 / Event breakdown: " + ", ".join(f"{describe_event_type(k)}({k}):{v}" for k, v in sorted(counts.items())))

    for event in events[-max_show:]:
        event_type = event.get("event_type", "unknown")
        item_id = event.get("target_item_id", "")
        item = pool._store.get(item_id)
        display = item.get("ref_snapshot", {}).get("content_display", item_id) if item else item_id
        delta = event.get("delta", {})
        rate = event.get("rate", {})
        print(
            f"    - {describe_event_type(event_type):<8}({event_type}) {shorten(display, 24):<24} "
            f"实能量变化(dEr)={delta.get('delta_er', 0):>+7.4f}  "
            f"虚能量变化(dEv)={delta.get('delta_ev', 0):>+7.4f}  "
            f"认知压变化(dCp)={delta.get('delta_cp_abs', 0):>+7.4f}  "
            f"变化率(rate)={rate.get('cp_abs_rate', 0):>+9.4f}  "
            f"原因(reason)={event.get('reason', '')}"
        )


def print_script_packet(packet: dict | None):
    print("\n  脚本检查窗口（供后续脚本模块判断）/ Script-check window:")
    if not packet:
        print("    无事件，不生成脚本抄送包 / No events, no packet generated")
        return

    summary = packet["summary"]
    print(
        f"    活跃对象数={summary['active_item_count']}  新建对象数={summary['new_item_count']}  "
        f"更新对象数={summary['updated_item_count']}  高认知压对象数={summary['high_cp_item_count']}  "
        f"认知压快速上升对象数={summary['fast_cp_rise_item_count']}  认知压快速下降对象数={summary['fast_cp_drop_item_count']}"
    )
    candidates = packet.get("candidate_triggers", [])
    if not candidates:
        print("    候选触发为空 / No candidate triggers")
        return
    for candidate in candidates[:6]:
        display = shorten(candidate.get("display") or candidate.get("item_id", ""), 24)
        print(
            f"    - {display:<24} 触发提示(hint)={candidate.get('trigger_hint', ''):<16} "
            f"值(value)={candidate.get('value', 0):>+7.4f}"
        )


def print_attention_snapshot(snapshot: dict, placeholder_receive: dict | None = None, placeholder_filter: dict | None = None):
    print("\n  注意力输入快照 / Attention snapshot:")
    print(
        f"    状态池总对象数={snapshot['total_pool_size']}  注意力候选上限(top_k)={snapshot['top_k']}  "
        f"实际候选数={len(snapshot['items'])}"
    )
    for item in snapshot["items"][:6]:
        print(
            f"    - {shorten(item.get('display', item['item_id']), 24):<24} "
            f"类型={shorten(describe_ref_type(item.get('ref_object_type', '')), 18):<18} "
            f"认知压(cp)={item['cp_abs']:.4f}  显著性(salience)={item['salience']:.4f}"
        )
    if placeholder_receive:
        print(
            f"    receive_state_snapshot（接收状态快照） -> {placeholder_receive.get('code', '')}  "
            f"success={placeholder_receive.get('success', False)}"
        )
    if placeholder_filter:
        print(
            f"    apply_attention_filter（执行注意力过滤） -> {placeholder_filter.get('code', '')}  "
            f"预算(budget)={placeholder_filter.get('data', {}).get('budget', 0)}  "
            f"输入数(input_count)={placeholder_filter.get('data', {}).get('input_count', 0)}"
        )


def print_item_detail(pool: StatePool, item_id: str):
    item = pool._store.get(item_id)
    if not item:
        print("  未找到目标对象 / Target item not found")
        return

    summary = pool._snapshot._build_top_item_summary(item)
    print(f"\n  详细对象检查 / Item inspection: {item_id}")
    print_divider("-", 112)
    print(f"  展示 / Display: {summary.get('display', '')}")
    if summary.get("display_detail"):
        print(f"  摘要 / Detail: {summary['display_detail']}")
    print(f"  引用类型 / Ref type: {describe_ref_type(item.get('ref_object_type', ''))}")
    print(f"  引用ID / Ref id: {item.get('ref_object_id', '')}")
    print(f"  引用别名 / Ref aliases: {item.get('ref_alias_ids', [])}")
    print(f"  子类型 / Sub type: {item.get('sub_type', '')}")
    print(f"  语义签名 / Semantic signature: {item.get('semantic_signature', '')}")
    print(f"  状态 / Status: {item.get('status', '')}")

    energy = item["energy"]
    dynamics = item["dynamics"]
    print("\n  能量 / Energy:")
    print(
        f"    er={energy['er']:.6f}  ev={energy['ev']:.6f}  "
        f"cp_delta={energy['cognitive_pressure_delta']:.6f}  cp_abs={energy['cognitive_pressure_abs']:.6f}"
    )
    print(
        f"    salience={energy.get('salience_score', 0):.6f}  fatigue={energy.get('fatigue', 0):.6f}  "
        f"recency_gain={energy.get('recency_gain', 0):.6f}"
    )

    print("\n  动态 / Dynamics:")
    print(
        f"    prev_er={dynamics.get('prev_er', 0):.6f}  prev_ev={dynamics.get('prev_ev', 0):.6f}  "
        f"delta_er={dynamics.get('delta_er', 0):+.6f}  delta_ev={dynamics.get('delta_ev', 0):+.6f}"
    )
    print(
        f"    prev_cp_abs={dynamics.get('prev_cp_abs', 0):.6f}  delta_cp_abs={dynamics.get('delta_cp_abs', 0):+.6f}  "
        f"cp_abs_rate={dynamics.get('cp_abs_rate', 0):+.6f}"
    )
    print(
        f"    er_rate={dynamics.get('er_change_rate', 0):+.6f}  ev_rate={dynamics.get('ev_change_rate', 0):+.6f}  "
        f"update_count={dynamics.get('update_count', 0)}  last_update_tick={dynamics.get('last_update_tick', 0)}"
    )

    print("\n  绑定 / Binding:")
    print(
        f"    bound_csa_item_id={item.get('binding_state', {}).get('bound_csa_item_id')}  "
        f"bound_attribute_ids={item.get('binding_state', {}).get('bound_attribute_sa_ids', [])}"
    )
    print(
        f"    bound_attribute_displays={summary.get('bound_attribute_displays', [])}  "
        f"attribute_displays={summary.get('attribute_displays', [])}"
    )

    print("\n  生命周期 / Lifecycle:")
    lifecycle = item.get("lifecycle", {})
    print(
        f"    created_in_tick={lifecycle.get('created_in_tick', 0)}  "
        f"last_active_tick={lifecycle.get('last_active_tick', 0)}  "
        f"elimination_candidate={lifecycle.get('elimination_candidate', False)}"
    )

    print("\n  引用快照 / Ref snapshot:")
    print("    " + json.dumps(item.get("ref_snapshot", {}), ensure_ascii=False, indent=2).replace("\n", "\n    "))


def print_config(pool: StatePool):
    labels = {
        "pool_max_items": "状态池容量上限",
        "default_er_decay_ratio": "每轮实能量衰减系数",
        "default_ev_decay_ratio": "每轮虚能量衰减系数",
        "enable_neutralization": "是否启用中和",
        "neutralization_mode": "中和策略",
        "neutralization_apply_stage": "中和执行阶段",
        "er_elimination_threshold": "实能量淘汰阈值",
        "ev_elimination_threshold": "虚能量淘汰阈值",
        "fast_cp_rise_threshold": "认知压快速上升阈值",
        "fast_cp_drop_threshold": "认知压快速下降阈值",
        "history_window_max_events": "历史窗口最大事件数",
        "enable_semantic_same_object_merge": "是否启用语义同一对象合并",
        "sensor_input_reconcile_mode": "感受器输入对齐策略",
        "enable_script_broadcast": "是否启用脚本抄送",
    }
    print("\n  状态池关键配置 / StatePool key config:")
    for key, label in labels.items():
        print(f"    {label:<24} ({key}) = {pool._config.get(key)}")


def build_runtime_object(kind: str, label: str, er: float, ev: float) -> dict:
    millis = int(time.time() * 1000)
    label = label or f"{kind}:demo"
    energy = {"er": er, "ev": ev}

    if kind == "cfs":
        return {
            "id": f"cfs_{millis}",
            "object_type": "cfs_signal",
            "sub_type": "demo_cfs_signal",
            "content": {"raw": label, "display": label},
            "energy": energy,
        }
    if kind == "action":
        return {
            "id": f"action_{millis}",
            "object_type": "action_node",
            "sub_type": "demo_action_node",
            "content": {"raw": label, "display": label},
            "energy": energy,
        }
    if kind == "st":
        return {
            "id": f"st_{millis}",
            "object_type": "st",
            "content": {"raw": label, "display": label},
            "energy": energy,
        }
    if kind == "sa":
        return {
            "id": f"sa_runtime_{millis}",
            "object_type": "sa",
            "content": {"raw": label, "display": label, "value_type": "discrete"},
            "stimulus": {"role": "feature", "modality": "internal"},
            "energy": energy,
        }
    raise ValueError(f"unsupported kind: {kind}")


def handle_autotick_command(settings: dict, args: list[str]):
    mode = normalize_cli_token(args[0] if args else settings.get("auto_tick_mode", "ask"))
    if mode not in {"on", "off", "ask"}:
        print("  autotick 仅支持 on/off/ask，可写成 `autotick on` 或 `autotick [on]`\n")
        return
    settings["auto_tick_mode"] = mode
    print("\n  自动维护模式 / Auto maintenance mode")
    print_divider("-", 96)
    print(f"  当前模式 / Current mode: {mode}")
    print("  说明：该设置会在“处理下一条文本之前”决定是否先执行 1 轮状态池维护\n")


def maybe_run_pre_input_auto_tick(pool: StatePool, settings: dict, trace_index: int):
    mode = settings.get("auto_tick_mode", "ask")
    if mode == "off":
        return

    if pool._store.size <= 0:
        return

    if mode == "on":
        print("\n  自动维护：在处理新文本前先执行 1 轮状态池维护 / Auto maintenance before new input")
        handle_tick(pool, 1, trace_index)
        return

    try:
        choice = input(
            "  在处理这条新文本之前，是否先执行 1 轮状态池维护? / Run 1 maintenance tick before new text? [y/N/always/off] > "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if choice in {"y", "yes"}:
        handle_tick(pool, 1, trace_index)
    elif choice in {"always", "a"}:
        settings["auto_tick_mode"] = "on"
        handle_tick(pool, 1, trace_index)
    elif choice in {"off", "never"}:
        settings["auto_tick_mode"] = "off"
        print("  自动维护已关闭 / Auto maintenance disabled\n")


def handle_text_input(pool: StatePool, sensor: TextSensor, text: str, trace_index: int, settings: dict):
    trace_id = f"text_{trace_index}"

    print(f"\n  输入文本 / Input text: {text!r}")
    print_divider("-", 96)
    maybe_run_pre_input_auto_tick(pool, settings, trace_index)
    history_before = pool._history.total_recorded
    ts_result = sensor.ingest_text(
        text=text,
        trace_id=trace_id,
        tick_id=trace_id,
        source_type="external_user_input",
    )
    if not ts_result.get("success"):
        print(f"  文本感受器失败 / TextSensor failed: {ts_result.get('message', '')}")
        return

    print_sensor_summary(ts_result)

    packet = ts_result["data"]["stimulus_packet"]
    settings["last_packet"] = packet
    settings["last_packet_trace_id"] = trace_id
    print_packet_structure(packet)
    apply_result = pool.apply_stimulus_packet(
        stimulus_packet=packet,
        trace_id=trace_id,
        tick_id=trace_id,
        source_module="text_sensor",
    )
    if not apply_result.get("success"):
        print(f"  状态池写入失败 / StatePool apply failed: {apply_result.get('message', '')}")
        return

    print_state_apply_summary(apply_result)

    snapshot = get_snapshot(pool, trace_id=f"{trace_id}_snapshot", top_k=8)
    print("\n  [4/4] 状态池写入后的运行态 / Post-apply runtime view")
    print_pool_summary(snapshot)
    print_top_items(snapshot["top_items"], max_show=8)

    events = get_new_events(pool, history_before)
    print_event_summary(pool, events, "本次新增事件", "New events for this input")
    print_script_packet(build_script_packet_preview(pool, events, trace_id=f"{trace_id}_script"))
    print()


def handle_tick(pool: StatePool, tick_rounds: int, trace_index: int):
    for offset in range(tick_rounds):
        round_trace = f"tick_{trace_index}_{offset + 1}"
        history_before = pool._history.total_recorded
        before = get_snapshot(pool, trace_id=f"{round_trace}_before", top_k=5)
        result = pool.tick_maintain_state_pool(
            trace_id=round_trace,
            tick_id=round_trace,
            emit_attention_snapshot=True,
        )
        after = get_snapshot(pool, trace_id=f"{round_trace}_after", top_k=5)
        events = get_new_events(pool, history_before)

        print(f"\n  Tick 维护 / Tick maintenance: {round_trace}")
        print_divider("-", 96)
        if not result.get("success"):
            print(f"  维护失败 / Maintenance failed: {result.get('message', '')}")
            continue

        data = result["data"]
        print(
            f"  已衰减对象数={data['decayed_item_count']}  已中和对象数={data['neutralized_item_count']}  "
            f"已淘汰对象数={data['pruned_item_count']}  已合并对象数={data['merged_item_count']}"
        )
        print(
            f"  维护前对象数={data['before_item_count']}  维护后对象数={data['after_item_count']}  "
            f"高认知压对象数={data['high_cp_item_count']}  认知压快速上升对象数={data['fast_cp_rise_item_count']}  "
            f"认知压快速下降对象数={data['fast_cp_drop_item_count']}"
        )
        print(
            f"  脚本抄送已发送={data.get('script_broadcast_sent')}  "
            f"维护前最高对象={before['top_items'][0]['display'] if before['top_items'] else 'none'}  "
            f"维护后最高对象={after['top_items'][0]['display'] if after['top_items'] else 'none'}"
        )

        print_event_summary(pool, events, "本轮维护事件", "Maintenance events")
        print_script_packet(build_script_packet_preview(pool, events, trace_id=f"{round_trace}_script"))

        print("\n  维护后 Top-5 / Post-maintenance Top-5:")
        print_top_items(after["top_items"], max_show=5)
        print()


def handle_bind(pool: StatePool, args: list[str], trace_index: int):
    target_spec = args[0] if args else None
    attribute_text = args[1] if len(args) >= 2 else "correctness:high"
    target_item_id, summary = resolve_item_id(pool, target_spec)
    if not target_item_id or not summary:
        print("  未找到可绑定目标 / No bind target found")
        return

    attr_sa = {
        "id": f"sa_attr_bind_{int(time.time() * 1000)}",
        "object_type": "sa",
        "content": {
            "raw": attribute_text,
            "normalized": attribute_text,
            "display": attribute_text,
            "value_type": "discrete",
        },
        "stimulus": {"role": "attribute", "modality": "internal"},
        "energy": {"er": 0.0, "ev": 0.0},
    }

    result = pool.bind_attribute_node_to_object(
        target_item_id=target_item_id,
        attribute_sa=attr_sa,
        trace_id=f"bind_{trace_index}",
        tick_id=f"bind_{trace_index}",
        source_module="integration_console",
        reason="interactive_demo_binding",
    )
    print("\n  属性绑定 / Attribute binding")
    print_divider("-", 96)
    print(f"  目标对象 / Target: {summary['display']} ({target_item_id})")
    print(f"  属性 / Attribute: {attribute_text}")
    print(f"  结果 / Result: {result['code']}  success={result['success']}")
    if result.get("data"):
        print("  返回数据 / Response data:")
        print("    " + json.dumps(result["data"], ensure_ascii=False, indent=2).replace("\n", "\n    "))
    if result.get("success"):
        inspect_id = result["data"].get("bound_csa_item_id") or target_item_id
        print_item_detail(pool, inspect_id)
    print()


def handle_energy(pool: StatePool, args: list[str], trace_index: int):
    target_spec = args[0] if args else None
    delta_er = safe_float(args[1], 1.0) if len(args) >= 2 else 1.0
    delta_ev = safe_float(args[2], 0.5) if len(args) >= 3 else 0.5
    target_item_id, summary = resolve_item_id(pool, target_spec)
    if not target_item_id or not summary:
        print("  未找到可更新目标 / No energy-update target found")
        return

    result = pool.apply_energy_update(
        target_item_id=target_item_id,
        delta_er=delta_er,
        delta_ev=delta_ev,
        trace_id=f"energy_{trace_index}",
        tick_id=f"energy_{trace_index}",
        reason="interactive_demo_energy_update",
        source_module="integration_console",
    )

    print("\n  定向能量更新 / Directed energy update")
    print_divider("-", 96)
    print(f"  目标对象 / Target: {summary['display']} ({target_item_id})")
    print(f"  请求变化 / Requested delta: dEr={delta_er:+.4f}  dEv={delta_ev:+.4f}")
    print(f"  结果 / Result: {result['code']}  success={result['success']}")
    if result.get("data"):
        print("  返回数据 / Response data:")
        print("    " + json.dumps(result["data"], ensure_ascii=False, indent=2).replace("\n", "\n    "))
    if result.get("success"):
        print_item_detail(pool, target_item_id)
    print()


def handle_insert(pool: StatePool, args: list[str], trace_index: int):
    kind = (args[0] if args else "cfs").lower()
    label = args[1] if len(args) >= 2 else f"{kind}:demo"
    er = safe_float(args[2], 0.8) if len(args) >= 3 else 0.8
    ev = safe_float(args[3], 0.0) if len(args) >= 4 else 0.0

    try:
        runtime_object = build_runtime_object(kind=kind, label=label, er=er, ev=ev)
    except ValueError:
        print("  insert 仅支持 kind = cfs/action/st/sa / insert supports kind = cfs/action/st/sa")
        return

    result = pool.insert_runtime_node(
        runtime_object=runtime_object,
        trace_id=f"insert_{trace_index}",
        tick_id=f"insert_{trace_index}",
        source_module="integration_console",
        reason="interactive_demo_insert",
    )

    print("\n  运行态节点插入 / Runtime node insertion")
    print_divider("-", 96)
    print(f"  kind={kind}  label={label}  er={er:.4f}  ev={ev:.4f}")
    print(f"  结果 / Result: {result['code']}  success={result['success']}")
    if result.get("data"):
        print("  返回数据 / Response data:")
        print("    " + json.dumps(result["data"], ensure_ascii=False, indent=2).replace("\n", "\n    "))
    if result.get("success"):
        print_item_detail(pool, result["data"]["item_id"])
    print()


def handle_snapshot(pool: StatePool, args: list[str], trace_index: int):
    top_k = safe_int(args[0], 12) if args else 12
    snapshot = get_snapshot(pool, trace_id=f"snap_{trace_index}", top_k=top_k)
    print("\n  状态池快照 / StatePool snapshot")
    print_divider("-", 96)
    print_pool_summary(snapshot)
    print_top_items(snapshot["top_items"], max_show=top_k)
    print()


def handle_history(pool: StatePool, args: list[str]):
    count = safe_int(args[0], 12) if args else 12
    events = pool._history.get_recent(count)
    print("\n  历史事件窗口 / History window")
    print_divider("-", 96)
    print_event_summary(pool, events, f"最近 {count} 条事件", f"Recent {count} events", max_show=count)
    print()


def handle_attention(pool: StatePool, args: list[str], trace_index: int):
    top_k = safe_int(args[0], 8) if args else 8
    snapshot = pool._snapshot.build_attention_snapshot(
        pool_store=pool._store,
        trace_id=f"attention_{trace_index}",
        tick_id=f"attention_{trace_index}",
        top_k=top_k,
    )

    placeholder_receive = None
    placeholder_filter = None
    try:
        from interfaces.attention.placeholder_attention_api import (
            apply_attention_filter,
            receive_state_snapshot,
        )

        placeholder_receive = receive_state_snapshot(snapshot, trace_id=f"attention_recv_{trace_index}")
        placeholder_filter = apply_attention_filter(
            snapshot["items"],
            budget=top_k,
            trace_id=f"attention_filter_{trace_index}",
        )
    except Exception as exc:  # pragma: no cover - 演示脚本以打印为主
        print(f"  注意力占位接口不可用 / Attention placeholder unavailable: {exc}")

    print_attention_snapshot(snapshot, placeholder_receive, placeholder_filter)
    print()


def handle_packet_command(settings: dict, args: list[str]):
    packet = settings.get("last_packet")
    trace_id = settings.get("last_packet_trace_id", "")
    if not packet:
        print("  暂无最近刺激包 / No recent stimulus packet available\n")
        return

    mode = normalize_cli_token(args[0] if args else "full")
    if mode not in {"groups", "trails", "full"}:
        print("  packet 仅支持 groups/trails/full / packet supports groups/trails/full only\n")
        return

    print(f"\n  最近刺激包 / Last stimulus packet: {trace_id or packet.get('id', '')}")
    print_divider("-", 112)
    if mode in {"groups", "full"}:
        print_packet_groups(build_packet_group_summaries(packet), max_groups=99)

    if mode in {"trails", "full"}:
        print_packet_trails(build_packet_semantic_trails(packet), max_trails=99)
    print()


def run_interactive():
    print_header()
    print_help()

    print("  正在初始化文本感受器（首次加载分词字典可能需要 10~30 秒，请耐心等待）...")
    print("     Initializing TextSensor (first-time dictionary loading may take 10~30s)...")
    sensor = TextSensor()
    print("  文本感受器初始化完成 / TextSensor initialized")

    reset_spm_ids()
    pool = StatePool(
        config_override={
            "pool_max_items": 500,
            "enable_placeholder_interfaces": True,
            "enable_script_broadcast": True,
        }
    )
    print("  状态池初始化完成 / StatePool initialized\n")

    trace_index = 0
    settings = {"auto_tick_mode": "ask", "last_packet": None, "last_packet_trace_id": ""}

    try:
        while True:
            try:
                user_input = input("  请输入文本或命令 / Enter text or command > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  再见 / Goodbye!")
                break

            if not user_input:
                continue

            lowered = user_input.lower()
            if lowered in {"quit", "exit", "q"}:
                print("  再见 / Goodbye!")
                break

            if lowered in {"help", "h", "?"}:
                print()
                print_help()
                continue

            try:
                tokens = shlex.split(user_input)
            except ValueError:
                tokens = [user_input]

            command = tokens[0].lower()
            args = tokens[1:]
            trace_index += 1

            if command == "tick":
                rounds = max(1, safe_int(args[0], 1)) if args else 1
                handle_tick(pool, rounds, trace_index)
            elif command == "autotick":
                handle_autotick_command(settings, args)
            elif command == "packet":
                handle_packet_command(settings, args)
            elif command == "snap":
                handle_snapshot(pool, args, trace_index)
            elif command == "inspect":
                target_item_id, _ = resolve_item_id(pool, args[0] if args else None)
                if not target_item_id:
                    print("  未找到目标对象 / Target item not found\n")
                else:
                    print_item_detail(pool, target_item_id)
                    print()
            elif command == "history":
                handle_history(pool, args)
            elif command == "bind":
                handle_bind(pool, args, trace_index)
            elif command == "energy":
                handle_energy(pool, args, trace_index)
            elif command == "insert":
                handle_insert(pool, args, trace_index)
            elif command == "attention":
                handle_attention(pool, args, trace_index)
            elif command == "reload":
                result = pool.reload_config(trace_id=f"reload_{trace_index}")
                print("\n  热加载配置 / Reload config")
                print_divider("-", 96)
                print(f"  结果 / Result: {result['code']}  success={result['success']}")
                if result.get("data"):
                    print("  返回数据 / Response data:")
                    print("    " + json.dumps(result["data"], ensure_ascii=False, indent=2).replace("\n", "\n    "))
                print()
            elif command == "config":
                print_config(pool)
                print()
            elif command == "clear":
                result = pool.clear_state_pool(
                    trace_id=f"clear_{trace_index}",
                    reason="interactive_demo_reset",
                    operator="integration_console",
                )
                print("\n  清空状态池 / Clear state pool")
                print_divider("-", 96)
                print(f"  结果 / Result: {result['code']}  success={result['success']}")
                print(
                    f"  cleared_item_count={result['data']['cleared_item_count']}  "
                    f"cleared_event_count={result['data']['cleared_event_count']}\n"
                )
            else:
                handle_text_input(pool, sensor, user_input, trace_index, settings)
    finally:
        pool._logger.close()
        sensor._logger.close()


if __name__ == "__main__":
    run_interactive()
