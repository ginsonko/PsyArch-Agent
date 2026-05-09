# -*- coding: utf-8 -*-
"""Terminal renderer for the AP observatory."""

from __future__ import annotations

import json
from typing import Any

from hdb._sequence_display import (
    format_semantic_sequence_groups,
    semantic_notation_examples,
    semantic_notation_legend,
)

LINE = "=" * 108
THIN = "-" * 108


_EVENT_TYPE_LABELS: dict[str, str] = {
    # 状态池/缓存常见事件类型（event_type）中文映射；渲染时会显示“中文（原始键名）”。
    "created": "新建",
    "updated": "更新",
    "neutralization": "中和",
    "priority_stimulus_neutralization": "优先刺激中和",
    "energy_update": "能量更新",
    "decay": "衰减",
    "merge": "合并",
}


def _term_event_type_label(event_type: str) -> str:
    et = str(event_type or "").strip()
    if not et:
        return "-"
    zh = _EVENT_TYPE_LABELS.get(et, "")
    return f"{zh}（{et}）" if zh else et


def format_help() -> str:
    return "\n".join(
        [
            "",
            "可用命令 / Commands:",
            "  text <任意文本>         输入文本并执行一轮完整观察",
            "  tick [n]               无新输入时执行 n 轮 tick",
            "  snap [k|all]           查看状态池快照",
            "  hdb                    查看 HDB 摘要",
            "  st <structure_id>      查看单个结构及局部数据库",
            "  sg <group_id>          查看单个结构组",
            "  em [n]                 查看最近 n 条情景记忆",
            "  check [target]         执行 HDB 自检",
            "  repair <target>        执行局部修复",
            "  repair_all             启动后台全局修复",
            "  stop_repair <job_id>   停止后台修复任务",
            "  idle_consolidate [n]   执行闲时巩固/压缩（可选：仅巩固最近 n 个事件）",
            "  open_report [latest|trace_id] 打开 HTML 观测报告",
            "  clear_hdb              清空 HDB",
            "  clear_all              清空 文本感受器残响（echo）+ 状态池 + HDB（全息深度数据库）",
            "  config                 查看关键配置",
            "  reload                 热加载配置",
            "  help                   查看帮助",
            "  quit / exit            退出",
        ]
    )


def render_header() -> str:
    return "\n".join(
        [
            "",
            LINE,
            "AP 原型研究观测台",
            "文本感受器 -> 状态池（维护）-> 注意力过滤器（AF）-> 结构级查存一体 -> 缓存中和 -> 刺激级查存一体 -> 状态回写 -> 感应赋能 -> 认知感受系统（CFS）-> 情绪递质（NT）-> 先天脚本（IESM）",
            LINE,
            "默认展示细粒度中间过程、局部数据库链路、能量变化和报告导出路径。",
            "",
        ]
    )


def render_cycle_report(report: dict) -> str:
    lines = ["", LINE, f"Cycle / 轮次: {report.get('trace_id', '')}", LINE]
    lines.extend(_render_sensor(report.get("sensor", {})))
    lines.extend(_render_maintenance(report.get("maintenance", {})))
    lines.extend(_render_cognitive_stitching(report.get("cognitive_stitching", {})))
    lines.extend(_render_attention(report.get("attention", {})))
    lines.extend(_render_structure(report.get("structure_level", {})))
    lines.extend(_render_cache(report.get("cache_neutralization", {})))
    lines.extend(_render_stimulus(report.get("stimulus_level", {}), report.get("merged_stimulus", {}), report.get("cache_neutralization", {})))
    lines.extend(_render_projection(report.get("pool_apply", {})))
    lines.extend(_render_induction(report.get("induction", {})))
    lines.extend(_render_cognitive_feeling(report.get("cognitive_feeling", {})))
    lines.extend(_render_emotion(report.get("emotion", {})))
    lines.extend(_render_innate_script(report.get("innate_script", {})))
    lines.extend(_render_action(report.get("action", {})))
    lines.extend(_render_final(report.get("final_state", {}), report.get("exports", {})))
    return "\n".join(lines)


def render_state_snapshot(report: dict, top_k: int | None = None) -> str:
    snapshot = report.get("snapshot", report)
    summary = snapshot.get("summary", {})
    items = list(snapshot.get("top_items", []))
    if top_k is not None:
        items = items[:top_k]
    lines = ["", "状态池快照 / State Pool Snapshot", LINE]
    lines.append(
        f"对象={summary.get('active_item_count', 0)} | 高 ER={summary.get('high_er_item_count', 0)} | "
        f"高 EV={summary.get('high_ev_item_count', 0)} | 高认知压={summary.get('high_cp_item_count', 0)}"
    )
    lines.append(f"类型分布={_j(summary.get('object_type_counts', {}))}")
    if not items:
        lines.append("当前状态池为空。")
    for index, item in enumerate(items, start=1):
        lines.extend(_state_item(index, item))
    return "\n".join(lines)


def render_hdb_snapshot(report: dict) -> str:
    summary = report.get("summary", {})
    lines = ["", "HDB 摘要 / HDB Snapshot", LINE]
    lines.append(
        f"ST={summary.get('structure_count', 0)} | SDB={summary.get('structure_db_count', 0)} | "
        f"SG={summary.get('group_count', 0)} | EM={summary.get('episodic_count', 0)} | "
        f"MAP兼容={summary.get('memory_activation_count', 0)} | "
        f"MAP兼容_ER={_n(summary.get('memory_activation_total_er', 0.0))} | "
        f"MAP兼容_EV={_n(summary.get('memory_activation_total_ev', 0.0))} | "
        f"MAP兼容_Total={_n(summary.get('memory_activation_total_energy', 0.0))} | "
        f"issue={summary.get('issue_count', 0)} | repair={summary.get('active_repair_job_count', 0)}"
    )
    for item in report.get("recent_structures", [])[:12]:
        lines.append(f"- {item.get('structure_id', '')} | {item.get('display_text', '')} | sig={item.get('signature', '')}")
    for item in report.get("recent_memory_activations", [])[:8]:
        lines.append(
            f"- MAP兼容 {item.get('memory_id', '')} | {item.get('display_text', '')} | "
            f"ER={_n(item.get('er', 0.0))} | EV={_n(item.get('ev', 0.0))} | "
            f"Total={_n(item.get('total_energy', 0.0))} | "
            f"last_ER={_n(item.get('last_delta_er', 0.0))} | last_EV={_n(item.get('last_delta_ev', 0.0))}"
        )
    return "\n".join(lines)


def render_structure_report(report: dict) -> str:
    structure = report.get("structure", {})
    struct = structure.get("structure", {})
    db = report.get("structure_db", {})
    lines = ["", "结构详情 / Structure Detail", LINE]
    lines.append(f"ID={structure.get('id', '')} | 内容={struct.get('display_text', '')} | sig={struct.get('content_signature', '')}")
    lines.append(f"flat_tokens={_tokens(struct.get('flat_tokens', [])) or '空'}")
    lines.append(f"局部数据库={db.get('structure_db_id', '')} | diff={len(db.get('diff_table', []))} | group={len(db.get('group_table', []))}")
    for entry in db.get("diff_table", [])[:16]:
        lines.append(
            f"- {entry.get('entry_id', '')} | target={entry.get('target_id', '')} | base={_n(entry.get('base_weight', 0.0))} | "
            f"residual_existing={entry.get('residual_existing_signature', '') or '无'} | residual_incoming={entry.get('residual_incoming_signature', '') or '无'}"
        )
    return "\n".join(lines)


def render_group_report(report: dict) -> str:
    group = report.get("group", {})
    lines = ["", "结构组详情 / Group Detail", LINE]
    lines.append(f"ID={group.get('id', '')}")
    lines.append(f"required={_refs(report.get('required_structures', []), 'structure_id') or '无'}")
    lines.append(f"bias={_refs(report.get('bias_structures', []), 'structure_id') or '无'}")
    lines.append(f"profile={_j(group.get('avg_energy_profile', {}))}")
    return "\n".join(lines)


def render_episodic_report(report: dict) -> str:
    lines = ["", "最近情景记忆 / Recent Episodic", LINE]
    items = report.get("items", [])
    if not items:
        lines.append("当前没有情景记忆。")
        return "\n".join(lines)
    for item in items:
        lines.append(f"- {item.get('id', '')} | {item.get('event_summary', '')}")
    return "\n".join(lines)


def render_check_report(report: dict) -> str:
    lines = ["", "HDB 自检结果 / HDB Self-check", LINE]
    lines.append(
        f"checked_st={report.get('checked_structure_count', 0)} | checked_sg={report.get('checked_group_count', 0)} | "
        f"checked_em={report.get('checked_episodic_count', 0)} | issue={report.get('issue_count', 0)}"
    )
    for issue in report.get("issues", [])[:24]:
        lines.append(f"- {issue.get('type', '')} | target={issue.get('target_id', '')} | suggest={','.join(issue.get('repair_suggestion', []))}")
    return "\n".join(lines)


def render_repair_report(report: dict) -> str:
    lines = ["", "HDB 修复结果 / HDB Repair", LINE]
    for key in ("repair_job_id", "status", "repair_scope", "target_id", "processed_count", "repaired_count", "deleted_count", "issue_count"):
        if key in report:
            lines.append(f"{key}={report.get(key)}")
    for item in report.get("actions_applied", [])[:24]:
        lines.append(f"- {item.get('target_id', '')}: {','.join(item.get('actions', []))}")
    return "\n".join(lines)


def _render_sensor(sensor: dict) -> list[str]:
    lines = ["[1/9] 文本感受器 / Text Sensor", THIN]
    if not sensor:
        return lines + ["本轮无外源输入。"]
    lines.append(f"输入={sensor.get('input_text', '')}")
    lines.append(
        f"模式={sensor.get('mode', '')} | tokenizer={sensor.get('tokenizer_backend', '')} | "
        f"可用={_b(sensor.get('tokenizer_available', False))} | fallback={_b(sensor.get('tokenizer_fallback', False))}"
    )
    lines.append(f"SA={sensor.get('sa_count', 0)} | CSA={sensor.get('csa_count', 0)} | 外源组={len(sensor.get('groups', []))}")
    for unit in sensor.get("units", sensor.get("feature_units", []))[:24]:
        lines.append(f"- {unit.get('display', unit.get('token', ''))} | role={unit.get('role', '')} | ER={_n(unit.get('er', 0.0))} | EV={_n(unit.get('ev', 0.0))}")
    for group in sensor.get("groups", [])[:16]:
        lines.append(
            f"- G{group.get('group_index', 0)} | source={group.get('source_type', '')} | 文本={group.get('display_text', '')} | "
            f"tokens={_tokens(group.get('flat_tokens', group.get('tokens', []))) or '空'} | SA={group.get('sa_count', 0)} | CSA={group.get('csa_count', 0)}"
        )
    return lines


def _render_maintenance(maintenance: dict) -> list[str]:
    before = maintenance.get("before_summary", {})
    after = maintenance.get("after_summary", {})
    summary = maintenance.get("summary", {})
    lines = ["[2/9] 状态池维护 / State Pool Maintenance", THIN]
    lines.append(
        f"对象数 {before.get('active_item_count', 0)} -> {after.get('active_item_count', 0)} | "
        f"衰减={summary.get('decayed_item_count', 0)} | 中和={summary.get('neutralized_item_count', 0)} | "
        f"淘汰={summary.get('pruned_item_count', 0)} | 合并={summary.get('merged_item_count', 0)}"
    )
    for event in maintenance.get("events", [])[:16]:
        et = _term_event_type_label(str(event.get("event_type", "") or ""))
        lines.append(f"- {et} | 目标={event.get('target_display', '')} | 原因={event.get('reason', '')}")
    return lines


def _render_attention(attention: dict) -> list[str]:
    lines = ["[3/9] 记忆体形成 / Attention Memory", THIN]
    candidate_count = attention.get("state_pool_candidate_count", attention.get("candidate_item_count", 0))
    skipped_count = attention.get("skipped_memory_item_count", 0)
    lines.append(
        f"候选={candidate_count} | 排除={skipped_count} | 入选={attention.get('memory_item_count', 0)} | "
        f"Top-N={attention.get('top_n', attention.get('top_item_count', 0))} | ST={len(attention.get('structure_items', []))} | "
        f"focus={attention.get('focus_directive_count', 0)}"
    )
    lines.append(
        f"ER消耗={_n(attention.get('consumed_total_er', 0.0))} | EV消耗={_n(attention.get('consumed_total_ev', 0.0))} | "
        f"总消耗={_n(attention.get('consumed_total_energy', 0.0))}"
    )
    for index, item in enumerate(attention.get("top_items", [])[:16], start=1):
        lines.extend(_state_item(index, item))
    return lines


def _render_cognitive_stitching(cognitive_stitching: dict) -> list[str]:
    lines = ["[CS] 认知拼接 / Cognitive Stitching", THIN]
    enabled = bool(cognitive_stitching.get("enabled", False))
    candidate_audit = cognitive_stitching.get("candidate_audit", {}) if isinstance(cognitive_stitching.get("candidate_audit", {}), dict) else {}
    rejected_reason_counts = candidate_audit.get("rejected_reason_counts", {}) if isinstance(candidate_audit.get("rejected_reason_counts", {}), dict) else {}
    score_means = candidate_audit.get("score_means", {}) if isinstance(candidate_audit.get("score_means", {}), dict) else {}
    lines.append(
        f"enabled={_b(enabled)} | stage={cognitive_stitching.get('stage', '')} | "
        f"seed={cognitive_stitching.get('seed_structure_count', 0)} | "
        f"candidate={cognitive_stitching.get('candidate_count', 0)} | "
        f"action={cognitive_stitching.get('action_count', 0)}"
    )
    lines.append(
        f"plain/event seed={cognitive_stitching.get('seed_plain_structure_count', 0)}/{cognitive_stitching.get('seed_event_count', 0)} | "
        f"create/extend/merge={cognitive_stitching.get('created_count', 0)}/{cognitive_stitching.get('extended_count', 0)}/{cognitive_stitching.get('merged_count', 0)} | "
        f"reinforced={cognitive_stitching.get('reinforced_count', 0)}"
    )
    lines.append(
        f"esdb events={cognitive_stitching.get('esdb_event_count', 0)} | "
        f"mat={cognitive_stitching.get('esdb_materialized_event_count', 0)} | "
        f"delta={cognitive_stitching.get('esdb_delta_entry_total', 0)}"
    )
    lines.append(
        f"audit raw/dedup/reject={candidate_audit.get('raw_accepted_count', 0)}/{candidate_audit.get('deduped_candidate_count', 0)}/{candidate_audit.get('rejected_count', 0)} | "
        f"pruned={candidate_audit.get('deduped_pruned_count', 0)} | replace/keep={candidate_audit.get('replacement_count', 0)}/{candidate_audit.get('kept_existing_count', 0)}"
    )
    lines.append(
        f"audit mean score={_n(score_means.get('score', 0.0))} | margin={_n(score_means.get('threshold_margin', 0.0))} | "
        f"match={_n(score_means.get('match_strength', 0.0))} | context={_n(score_means.get('context_ratio', 0.0))}"
    )
    if rejected_reason_counts:
        lines.append("reject reasons: " + " | ".join(f"{k}={v}" for k, v in rejected_reason_counts.items()))
    if not enabled:
        lines.append(f"reason={cognitive_stitching.get('reason', 'disabled')}")
        return lines
    for item in cognitive_stitching.get("actions", [])[:12]:
        lines.append(
            f"- {item.get('action', '')} | {item.get('event_display', '')} | "
            f"score={_n(item.get('score', 0.0))} | absorb={_n(item.get('absorbed_total', 0.0))} | "
            f"match={item.get('match_mode', '')} | context_k={item.get('context_k', 0)} | "
            f"matched_span={item.get('matched_span', 0)} | family={item.get('action_family', '')}"
        )
    top_items = cognitive_stitching.get("narrative_top_items", [])[:8]
    if top_items:
        lines.append("narrative top:")
    for item in top_items:
        lines.append(
            f"- {item.get('display', '')} | ER={_n(item.get('er', 0.0))} | "
            f"EV={_n(item.get('ev', 0.0))} | CP={_n(item.get('cp_abs', 0.0))} | "
            f"grasp={_n(item.get('event_grasp', 0.0))} | components={item.get('component_count', 0)} | "
            f"es_depth={item.get('esdb_parent_depth', 0)} | delta={item.get('esdb_delta_entry_count', 0)} | "
            f"mat={1 if item.get('esdb_materialized', False) else 0} | upd={item.get('esdb_update_count', 0)}"
        )
    return lines


def _render_structure(structure_level: dict) -> list[str]:
    data = structure_level.get("result", {})
    debug = data.get("debug", {})
    lines = ["[4/9] 结构级查存一体 / Structure-level Retrieval-Storage", THIN]
    lines.append(
        f"CAM={data.get('cam_stub_count', 0)} | 轮次={data.get('round_count', 0)} | "
        f"命中组={len(data.get('matched_group_ids', []))} | 新建组={len(data.get('new_group_ids', []))} | fallback={_b(data.get('fallback_used', False))}"
    )
    for item in debug.get("cam_items", [])[:16]:
        lines.append(f"- {item.get('display_text', '')}[{item.get('structure_id', '')}] | ER={_n(item.get('er', 0.0))} EV={_n(item.get('ev', 0.0))} Total={_n(item.get('total_energy', 0.0))}")
    for round_detail in debug.get("round_details", []):
        anchor = round_detail.get("anchor", {})
        lines.append(f"结构级 Round {round_detail.get('round_index', 0)}")
        if anchor:
            lines.append(f"  Anchor={anchor.get('display_text', '')}[{anchor.get('structure_id', '')}] | score={_n(anchor.get('anchor_score', 0.0))}")
        lines.append(f"  预算前={_budget(round_detail.get('budget_before', {}))}")
        lines.append(f"  预算后={_budget(round_detail.get('budget_after', {}))}")
        lines.append(f"  链式路径={_chain(round_detail.get('chain_steps', []), 'structure')}")
        lines.append(f"  存储摘要={_storage(round_detail.get('storage_summary', {}))}")
        selected = round_detail.get("selected_group")
        if selected:
            lines.append(
                f"  命中={selected.get('group_id', '')} | score={_n(selected.get('score', 0.0))} | base={_n(selected.get('base_similarity', 0.0))} | "
                f"coverage={_n(selected.get('coverage_ratio', 0.0))} | structure={_n(selected.get('structure_ratio', 0.0))} | wave={_n(selected.get('wave_similarity', 0.0))}"
            )
        for candidate in round_detail.get("candidate_groups", [])[:8]:
            lines.append(
                f"  - {candidate.get('group_id', '')} | eligible={_b(candidate.get('eligible', False))} | score={_n(candidate.get('score', 0.0))} | "
                f"runtime={_n(candidate.get('runtime_weight', 1.0))} | common={_common(candidate.get('common_part', {}))}"
            )
    for group in debug.get("new_group_details", [])[:12]:
        lines.append(f"- 新组 {group.get('group_id', '')} | required={_refs(group.get('required_structures', []), 'structure_id') or '无'}")
    return lines


def _render_cache(cache: dict) -> list[str]:
    summary = cache.get("priority_summary", {})
    component_count = int(summary.get("event_component_neutralization_count", 0) or 0)
    component_cp_drop = float(summary.get("event_component_cp_drop_sum", 0.0) or 0.0)
    lines = ["[5/9] 缓存中和 / Cache Neutralization", THIN]
    lines.append(
        f"中和对象={summary.get('priority_neutralized_item_count', 0)} | 事件={summary.get('priority_event_count', 0)} | "
        f"consumed_er={_n(summary.get('consumed_er', 0.0))} | consumed_ev={_n(summary.get('consumed_ev', 0.0))}"
    )
    lines.append(f"输入包={cache.get('input_packet', {}).get('display_text', '') or '空'}")
    lines.append(f"剩余包={cache.get('residual_packet', {}).get('display_text', '') or '空'}")
    if component_count or component_cp_drop:
        lines.append(f"event_components={component_count} | cp_drop={_n(component_cp_drop)}")
    for event in cache.get("priority_events", [])[:16]:
        extra = event.get("extra_context", {}) or {}
        et = _term_event_type_label(str(event.get("event_type", "") or "priority_stimulus_neutralization"))
        lines.append(
            f"- {et} | "
            f"{event.get('target_display', '') or event.get('target_item_id', '')} | "
            f"matched_sig={event.get('matched_structure_signature', '') or '无'} | "
            f"{extra.get('consumed_energy_key', 'energy')}={_n(extra.get('consumed_amount', 0.0))} | "
            f"matched_tokens={_tokens(extra.get('matched_tokens', [])) or '无'} | "
            f"reason={event.get('reason', '') or 'priority_match'}"
        )
    return lines


def _render_stimulus(stimulus_level: dict, merged_stimulus: dict, cache: dict) -> list[str]:
    data = stimulus_level.get("result", {})
    debug = data.get("debug", {})
    residual_packet = cache.get("residual_packet", {})
    lines = ["[6/9] 刺激级查存一体 / Stimulus-level Retrieval-Storage", THIN]
    lines.append(f"完整刺激={merged_stimulus.get('display_text', '') or '空'}")
    lines.append(f"中和后剩余={residual_packet.get('display_text', '') or '空'}")
    lines.append(
        f"轮次={data.get('round_count', 0)} | 命中结构={len(data.get('matched_structure_ids', []))} | "
        f"新建结构={len(data.get('new_structure_ids', []))} | 剩余SA={data.get('remaining_stimulus_sa_count', 0)} | fallback={_b(data.get('fallback_used', False))}"
    )
    for group in merged_stimulus.get("groups", [])[:16]:
        lines.append(
            f"- G{group.get('group_index', 0)} | source={group.get('source_type', '')} | 文本={group.get('display_text', '')} | "
            f"tokens={_tokens(group.get('flat_tokens', group.get('tokens', []))) or '空'} | SA={group.get('sa_count', 0)} | CSA={group.get('csa_count', 0)}"
        )
    for round_detail in debug.get("round_details", []):
        anchor = round_detail.get("anchor", {})
        lines.append(f"刺激级 Round {round_detail.get('round_index', 0)}")
        if anchor:
            lines.append(
                f"  Anchor={anchor.get('display_text', '')} | source={anchor.get('source_type', '')} | group={anchor.get('group_index', 0)} | "
                f"ER={_n(anchor.get('er', 0.0))} EV={_n(anchor.get('ev', 0.0))}"
            )
        lines.append(f"  轮前残余={_tokens(round_detail.get('remaining_tokens_before', [])) or '空'}")
        lines.append(f"  链式路径={_chain(round_detail.get('chain_steps', []), 'stimulus')}")
        selected = round_detail.get("selected_match")
        if selected:
            lines.append(
                f"  命中={selected.get('display_text', '')}[{selected.get('structure_id', '')}] | score={_n(selected.get('competition_score', selected.get('match_score', 0.0)))} | "
                f"coverage={_n(selected.get('coverage_ratio', 0.0))} | structure={_n(selected.get('structure_match_ratio', 0.0))} | common={_common(selected.get('common_part', {}))}"
            )
        else:
            lines.append("  本轮未命中已有结构。")
        for candidate in round_detail.get("candidate_details", [])[:8]:
            lines.append(
                f"  - {candidate.get('display_text', '')}[{candidate.get('structure_id', '')}] | eligible={_b(candidate.get('eligible', False))} | "
                f"score={_n(candidate.get('competition_score', 0.0))} | stimulus={_n(candidate.get('stimulus_match_ratio', candidate.get('coverage_ratio', 0.0)))} | "
                f"structure={_n(candidate.get('structure_match_ratio', 0.0))} | depth={candidate.get('chain_depth', 0)} | owner={candidate.get('owner_structure_id', '') or '—'}"
            )
        lines.append(
            f"  能量转移 actual={_n(round_detail.get('effective_transfer_fraction', 0.0))} | "
            f"ER={_n(round_detail.get('transferred_er', 0.0))} EV={_n(round_detail.get('transferred_ev', 0.0))}"
        )
        if round_detail.get("created_common_structure"):
            created = round_detail.get("created_common_structure", {})
            lines.append(f"  共同结构={created.get('display_text', '')}[{created.get('structure_id', '')}]")
        if round_detail.get("created_residual_structure"):
            created = round_detail.get("created_residual_structure", {})
            lines.append(f"  残差结构={created.get('display_text', '')}[{created.get('structure_id', '')}]")
        if round_detail.get("created_fresh_structure"):
            created = round_detail.get("created_fresh_structure", {})
            lines.append(f"  扩展结构={created.get('display_text', '')}[{created.get('structure_id', '')}]")
        lines.append(f"  轮后残余={_tokens(round_detail.get('remaining_tokens_after', [])) or '空'}")
    return lines


def _render_projection(pool_apply: dict) -> list[str]:
    apply_result = pool_apply.get("apply_result", {})
    lines = ["[7/9] 状态池回写 / Projection & Pool Apply", THIN]
    if not apply_result:
        return lines + ["本轮没有状态池回写。"]
    lines.append(
        f"新建={apply_result.get('new_item_count', 0)} | 更新={apply_result.get('updated_item_count', 0)} | "
        f"合并={apply_result.get('merged_item_count', 0)} | 中和={apply_result.get('neutralized_item_count', 0)}"
    )
    landed = pool_apply.get("landed_packet", {})
    if landed:
        lines.append(f"落地剩余包={landed.get('display_text', '') or '空'}")
    for item in pool_apply.get("bias_projection", [])[:12]:
        lines.append(f"- 偏置 {item.get('display_text', '')}[{item.get('structure_id', '')}] | ER={_n(item.get('er', 0.0))} | EV={_n(item.get('ev', 0.0))}")
    for item in pool_apply.get("runtime_projection", [])[:12]:
        lines.append(f"- 投影 {item.get('display_text', '')}[{item.get('structure_id', '')}] | reason={item.get('reason', '')} | ER={_n(item.get('er', 0.0))} | EV={_n(item.get('ev', 0.0))}")
    return lines


def _render_induction(induction: dict) -> list[str]:
    data = induction.get("result", {})
    debug = data.get("debug", {})
    lines = ["[8/9] 感应赋能 / Induction Propagation", THIN]
    lines.append(
        f"感应源={data.get('source_item_count', 0)} | ev传播={data.get('propagated_target_count', 0)} | "
        f"er诱发={data.get('induced_target_count', 0)} | total_delta_ev={_n(data.get('total_delta_ev', 0.0))} | total_ev_consumed={_n(data.get('total_ev_consumed', 0.0))}"
    )
    for source in debug.get("source_details", [])[:8]:
        lines.append(f"源 {source.get('display_text', '')}[{source.get('source_structure_id', '')}] | ER={_n(source.get('source_er', 0.0))} EV={_n(source.get('source_ev', 0.0))}")
        for entry in source.get("candidate_entries", [])[:12]:
            lines.append(
                f"- {entry.get('mode', '')} -> {entry.get('target_display_text', '')}[{entry.get('target_structure_id', '')}] | "
                f"share={_n(entry.get('normalized_share', 0.0))} | entries={entry.get('entry_count', 0)} | delta_ev={_n(entry.get('delta_ev', 0.0))} | "
                f"runtime={_n(entry.get('runtime_weight', 1.0))} | W={_n(entry.get('base_weight', 1.0))} G={_n(entry.get('recent_gain', 1.0))} F={_n(entry.get('fatigue', 0.0))}"
            )
    for item in induction.get("applied_targets", [])[:16]:
        lines.append(f"- 回写 {item.get('display_text', '')}[{item.get('structure_id', '')}] | delta_ev={_n(item.get('ev', 0.0))}")
    return lines


def _render_final(final_state: dict, exports: dict) -> list[str]:
    snapshot = final_state.get("state_snapshot", {})
    summary = snapshot.get("summary", {})
    hdb_summary = final_state.get("hdb_snapshot", {}).get("summary", {})
    energy = final_state.get("state_energy_summary", {})
    lines = ["[9/9] 最终状态 / Final State", THIN]
    lines.append(
        f"状态池对象={summary.get('active_item_count', 0)} | 高ER={summary.get('high_er_item_count', 0)} | "
        f"高EV={summary.get('high_ev_item_count', 0)} | 高认知压={summary.get('high_cp_item_count', 0)}"
    )
    lines.append(f"类型分布={_j(summary.get('object_type_counts', {}))}")
    if energy:
        lines.append(f"总能量 ER={_n(energy.get('total_er', 0.0))} | EV={_n(energy.get('total_ev', 0.0))} | CP={_n(energy.get('total_cp', 0.0))}")
    lines.append(
        f"HDB: ST={hdb_summary.get('structure_count', 0)} | SG={hdb_summary.get('group_count', 0)} | "
        f"EM={hdb_summary.get('episodic_count', 0)} | issue={hdb_summary.get('issue_count', 0)}"
    )
    for index, item in enumerate(snapshot.get("top_items", [])[:16], start=1):
        lines.extend(_state_item(index, item))
    if exports:
        lines.append(THIN)
        lines.append(f"JSON 报告: {exports.get('json_path', '')}")
        lines.append(f"HTML 报告: {exports.get('html_path', '')}")
    return lines


def _state_item(index: int, item: dict) -> list[str]:
    display = (
        item.get("content_display")
        or item.get("ref_object_display")
        or item.get("display_text")
        or item.get("ref_object_id")
        or item.get("id", "")
    )
    item_id = item.get("id") or item.get("ref_object_id", "")
    item_type = item.get("ref_object_type", item.get("object_type", ""))
    lines = [
        f"{index}. {display} | id={item_id} | type={item_type}:{item.get('ref_object_id', '')}",
        f"   ER={_n(item.get('er', item.get('energy', {}).get('er', 0.0)))} | EV={_n(item.get('ev', item.get('energy', {}).get('ev', 0.0)))} | CP={_n(item.get('cp_abs', item.get('energy', {}).get('cognitive_pressure_abs', 0.0)))}",
    ]
    if any(k in item for k in ("attention_priority", "attention_priority_base", "reward_action_bonus")):
        lines.append(
            f"   ATTN={_n(item.get('attention_priority', 0.0))} | "
            f"base={_n(item.get('attention_priority_base', 0.0))} | "
            f"reward_action_bonus={_n(item.get('reward_action_bonus', 0.0))}"
        )
    snap = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
    if item_type == "action_node" or snap:
        target = (
            snap.get("target_display")
            or snap.get("target_ref_object_id")
            or snap.get("target_item_id")
            or item.get("target_display")
            or item.get("target_ref_object_id")
            or item.get("target_item_id")
            or ""
        )
        if target:
            lines.append(
                f"   target={target} | drive={_n(item.get('drive', snap.get('drive', 0.0)))} | "
                f"threshold={_n(item.get('effective_threshold', snap.get('effective_threshold', 0.0)))} | "
                f"consumed={_n(item.get('tick_consumed_drive_total', snap.get('tick_consumed_drive_total', snap.get('last_consumed_drive', 0.0))))}"
            )
    return lines


def _render_action(action: dict) -> list[str]:
    action = dict(action or {}) if isinstance(action, dict) else {}
    summary = action.get("action_learning_summary", {}) if isinstance(action.get("action_learning_summary", {}), dict) else {}
    nodes = [row for row in (action.get("nodes", []) or []) if isinstance(row, dict)]
    executed = [row for row in (action.get("executed_actions", []) or []) if isinstance(row, dict)]
    if not summary and not nodes and not executed:
        return []

    lines = ["[8.5/9] 行动模块 / Action Runtime", THIN]
    lines.append(
        f"人形主路径={_b(summary.get('humanlike_runtime_sync_enabled', True))} | "
        f"运行态信号节点={summary.get('runtime_signal_node_active_count', 0)}/{summary.get('runtime_signal_node_count', 0)} | "
        f"运行态行动节点={summary.get('runtime_action_node_active_count', 0)}/{summary.get('runtime_action_node_count', 0)} | "
        f"执行显影={summary.get('runtime_action_node_executed_count', 0)}"
    )
    lines.append(
        f"局部塑形开关={_b(summary.get('local_drive_modulation_enabled', True))} | "
        f"targeted={summary.get('targeted_node_count', 0)} | hit={summary.get('local_lookup_hit_count', 0)} | "
        f"text_fallback={summary.get('local_lookup_text_fallback_hit_count', 0)} | miss={summary.get('local_lookup_miss_count', 0)} | "
        f"skipped={summary.get('local_lookup_skipped_count', 0)}"
    )
    lines.append(
        f"奖励增益={_n(summary.get('local_reward_drive_bonus_total', 0.0))} | "
        f"惩罚扣减={_n(summary.get('local_punish_drive_penalty_total', 0.0))} | "
        f"scale_mean={_n(summary.get('local_drive_scale_mean', 1.0))}"
    )
    for row in nodes[:10]:
        target = row.get("target_display", "") or row.get("target_ref_object_id", "") or row.get("target_item_id", "") or "—"
        local_mod = row.get("local_drive_modulation", {}) if isinstance(row.get("local_drive_modulation", {}), dict) else {}
        lines.append(
            f"- 节点 {row.get('action_kind', '')}/{row.get('action_id', '')} | target={target} | "
            f"drive={_n(row.get('drive', 0.0))} | consumed={_n(row.get('tick_consumed_drive_total', row.get('last_consumed_drive', 0.0)))} | "
            f"threshold={_n(row.get('effective_threshold', row.get('threshold', 0.0)))} | lookup={local_mod.get('lookup_status', '-')}"
        )
    for row in executed[:10]:
        target = row.get("target_display", "") or row.get("target_ref_object_id", "") or row.get("target_item_id", "") or "—"
        local_mod = row.get("local_drive_modulation", {}) if isinstance(row.get("local_drive_modulation", {}), dict) else {}
        lines.append(
            f"- 执行 {row.get('action_kind', '')}/{row.get('action_id', '')} | target={target} | "
            f"success={_b(row.get('success', False))} | attempted={_b(row.get('attempted', True))} | "
            f"consumed={_n(row.get('consumed_drive', 0.0))} | lookup={local_mod.get('lookup_status', '-')}"
        )
    return lines


def _n(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except Exception:
        return str(value)


def _j(data: Any) -> str:
    if not data:
        return "{}"
    try:
        return json.dumps(data, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(data)


def _b(value: Any) -> str:
    return "是" if bool(value) else "否"


def _tokens(values: list[Any]) -> str:
    return " / ".join(str(v) for v in values or [] if str(v))


def _refs(items: list[dict], key: str) -> str:
    return "，".join(f"{item.get('display_text', item.get(key, ''))}({item.get(key, '')})" for item in items or [])


def _budget(budget: dict) -> str:
    if not budget:
        return "空"
    parts = []
    for key, value in budget.items():
        if isinstance(value, dict):
            parts.append(f"{key}:ER {_n(value.get('er', 0.0))}/EV {_n(value.get('ev', 0.0))}/T {_n(value.get('total', 0.0))}")
        else:
            parts.append(f"{key}:{value}")
    return " | ".join(parts)


def _chain(steps: list[dict], kind: str) -> str:
    if not steps:
        return "无"
    parts = []
    for step in steps:
        if kind == "structure":
            owner = step.get("owner_display_text", "") or step.get("owner_id", "")
            parts.append(f"{step.get('owner_kind', '')}:{owner}->{step.get('candidate_count', 0)}")
        else:
            owner = step.get("owner_display_text", "") or step.get("owner_structure_id", "")
            parts.append(f"{owner}->{step.get('candidate_count', 0)}")
    return " | ".join(parts)


def _common(common_part: dict) -> str:
    return common_part.get("common_display", "") or _tokens(common_part.get("common_tokens", [])) or "无"


def _storage(summary: dict) -> str:
    if not summary:
        return "无"
    actions = [str(item.get("type", "")) for item in summary.get("actions", []) if item.get("type", "")]
    if summary.get("new_group_ids"):
        actions.append("new_group=" + ",".join(str(x) for x in summary.get("new_group_ids", [])))
    if summary.get("new_structure_ids"):
        actions.append("new_structure=" + ",".join(str(x) for x in summary.get("new_structure_ids", [])))
    return " | ".join(actions) if actions else _j(summary)


def _display_text(item: dict) -> str:
    if not isinstance(item, dict):
        return str(item)
    semantic_text = str(item.get("semantic_grouped_display_text", "") or item.get("semantic_display_text", "") or "")
    if semantic_text:
        return semantic_text
    sequence_groups = item.get("sequence_groups", [])
    if isinstance(sequence_groups, list) and sequence_groups:
        rendered = format_semantic_sequence_groups(sequence_groups)
        if rendered:
            return rendered
    return (
        item.get("grouped_display_text")
        or item.get("display_text")
        or item.get("target_display_text")
        or item.get("content_display")
        or item.get("ref_object_display")
        or item.get("id", "")
    )


def _storage(summary: dict) -> str:
    if not summary:
        return "无"
    actions = []
    for item in summary.get("actions", []):
        if not isinstance(item, dict):
            continue
        action_type = str(item.get("type", ""))
        if not action_type:
            continue
        details = []
        if item.get("storage_table", ""):
            details.append(f"table={item.get('storage_table', '')}")
        if item.get("group_id", ""):
            details.append(f"group={item.get('group_id', '')}")
        if item.get("canonical_display_text", ""):
            details.append(f"canonical={item.get('canonical_display_text', '')}")
        if item.get("raw_display_text", ""):
            details.append(f"raw={item.get('raw_display_text', '')}")
        if item.get("memory_id", ""):
            details.append(f"em={item.get('memory_id', '')}")
        actions.append(f"{action_type}({', '.join(details)})" if details else action_type)
    if summary.get("new_group_ids"):
        actions.append("new_group=" + ",".join(str(x) for x in summary.get("new_group_ids", [])))
    if summary.get("new_structure_ids"):
        actions.append("new_structure=" + ",".join(str(x) for x in summary.get("new_structure_ids", [])))
    owner = summary.get("owner_display_text", "") or summary.get("owner_id", "")
    owner_kind = summary.get("owner_kind", "")
    db_id = summary.get("resolved_db_id", "") or "-"
    return f"{owner}({owner_kind}) | db={db_id} | {' | '.join(actions) if actions else '无'}"


def _render_sensor(sensor: dict) -> list[str]:
    lines = ["[1/9] 文本感受器 / Text Sensor", THIN]
    if not sensor:
        return lines + ["本轮无外源输入。"]
    lines.append(f"输入={sensor.get('input_text', '')}")
    lines.append(
        f"模式={sensor.get('mode', '')} | tokenizer={sensor.get('tokenizer_backend', '')} | "
        f"可用={_b(sensor.get('tokenizer_available', False))} | fallback={_b(sensor.get('tokenizer_fallback', False))}"
    )
    lines.append(f"SA={sensor.get('sa_count', 0)} | CSA={sensor.get('csa_count', 0)} | 外源组={len(sensor.get('groups', []))}")
    for unit in sensor.get("units", sensor.get("feature_units", []))[:24]:
        lines.append(
            f"- {unit.get('display', unit.get('token', ''))} | role={unit.get('role', '')} | "
            f"ER={_n(unit.get('er', 0.0))} | EV={_n(unit.get('ev', 0.0))} | CSA={unit.get('bundle_display', '') or '无'}"
        )
    for group in sensor.get("groups", [])[:16]:
        lines.append(
            f"- G{group.get('group_index', 0)} | source={group.get('source_type', '')} | 组={group.get('display_text', '')} | "
            f"tokens={_tokens(group.get('tokens', [])) or '空'} | SA={group.get('sa_count', 0)} | "
            f"CSA={group.get('csa_count', 0)} | bundles={_tokens(group.get('csa_bundles', [])) or '无'}"
        )
    return lines


def _render_structure(structure_level: dict) -> list[str]:
    data = structure_level.get("result", {})
    debug = data.get("debug", {})
    lines = ["[4/9] 结构级查存一体 / Structure-level Retrieval-Storage", THIN]
    lines.append(
        f"CAM={data.get('cam_stub_count', 0)} | 轮次={data.get('round_count', 0)} | "
        f"命中组={len(data.get('matched_group_ids', []))} | 新建组={len(data.get('new_group_ids', []))} | fallback={_b(data.get('fallback_used', False))}"
    )
    for item in debug.get("cam_items", [])[:16]:
        lines.append(
            f"- {_display_text(item)}[{item.get('structure_id', '')}] | ER={_n(item.get('er', 0.0))} "
            f"EV={_n(item.get('ev', 0.0))} Total={_n(item.get('total_energy', 0.0))}"
        )
    for round_detail in debug.get("round_details", []):
        anchor = round_detail.get("anchor", {})
        lines.append(f"结构级 Round {round_detail.get('round_index', 0)}")
        if anchor:
            lines.append(f"  Anchor={_display_text(anchor)}[{anchor.get('structure_id', '')}] | score={_n(anchor.get('anchor_score', 0.0))}")
        lines.append(f"  预算前={_budget(round_detail.get('budget_before', {}))}")
        lines.append(f"  预算后={_budget(round_detail.get('budget_after', {}))}")
        lines.append(f"  链式路径={_chain(round_detail.get('chain_steps', []), 'structure')}")
        lines.append(f"  局部库动作={_storage(round_detail.get('storage_summary', {}))}")
        selected = round_detail.get("selected_group")
        if selected:
            lines.append(
                f"  命中={selected.get('group_id', '')} | score={_n(selected.get('score', 0.0))} | "
                f"base={_n(selected.get('base_similarity', 0.0))} | coverage={_n(selected.get('coverage_ratio', 0.0))} | "
                f"structure={_n(selected.get('structure_ratio', 0.0))} | wave={_n(selected.get('wave_similarity', 0.0))}"
            )
        for candidate in round_detail.get("candidate_groups", [])[:8]:
            lines.append(
                f"  - {candidate.get('group_id', '')} | eligible={_b(candidate.get('eligible', False))} | "
                f"score={_n(candidate.get('score', 0.0))} | runtime={_n(candidate.get('runtime_weight', 1.0))} | "
                f"common={_common(candidate.get('common_part', {}))}"
            )
    for group in debug.get("new_group_details", [])[:12]:
        lines.append(f"- 新组 {group.get('group_id', '')} | required={_refs(group.get('required_structures', []), 'structure_id') or '无'}")
    return lines


def _render_stimulus(stimulus_level: dict, merged_stimulus: dict, cache: dict) -> list[str]:
    data = stimulus_level.get("result", {})
    debug = data.get("debug", {})
    residual_packet = cache.get("residual_packet", {})
    lines = ["[6/9] 刺激级查存一体 / Stimulus-level Retrieval-Storage", THIN]
    lines.append(f"完整刺激={merged_stimulus.get('display_text', '') or '空'}")
    lines.append(f"中和后残余={residual_packet.get('display_text', '') or '空'}")
    lines.append(
        f"轮次={data.get('round_count', 0)} | 命中结构={len(data.get('matched_structure_ids', []))} | "
        f"新建结构={len(data.get('new_structure_ids', []))} | 剩余SA={data.get('remaining_stimulus_sa_count', 0)} | fallback={_b(data.get('fallback_used', False))}"
    )
    for group in merged_stimulus.get("groups", [])[:16]:
        lines.append(
            f"- G{group.get('group_index', 0)} | source={group.get('source_type', '')} | 组={group.get('display_text', '')} | "
            f"tokens={_tokens(group.get('tokens', [])) or '空'} | SA={group.get('sa_count', 0)} | "
            f"CSA={group.get('csa_count', 0)} | bundles={_tokens(group.get('csa_bundles', [])) or '无'}"
        )
    for round_detail in debug.get("round_details", []):
        anchor = round_detail.get("anchor", {})
        lines.append(f"刺激级 Round {round_detail.get('round_index', 0)}")
        if anchor:
            lines.append(
                f"  Anchor={anchor.get('display_text', '')} | source={anchor.get('source_type', '')} | group={anchor.get('group_index', 0)} | "
                f"ER={_n(anchor.get('er', 0.0))} EV={_n(anchor.get('ev', 0.0))}"
            )
        lines.append(f"  轮前残余={round_detail.get('remaining_grouped_text_before', '') or _tokens(round_detail.get('remaining_tokens_before', [])) or '空'}")
        lines.append(f"  链式路径={_chain(round_detail.get('chain_steps', []), 'stimulus')}")
        selected = round_detail.get("selected_match")
        if selected:
            lines.append(
                f"  命中={_display_text(selected)}[{selected.get('structure_id', '')}] | "
                f"score={_n(selected.get('competition_score', selected.get('match_score', 0.0)))} | "
                f"coverage={_n(selected.get('coverage_ratio', 0.0))} | structure={_n(selected.get('structure_match_ratio', 0.0))} | "
                f"common={_common(selected.get('common_part', {}))}"
            )
        else:
            lines.append("  本轮未命中已有结构。")
        for candidate in round_detail.get("candidate_details", [])[:8]:
            lines.append(
                f"  - {_display_text(candidate)}[{candidate.get('structure_id', '')}] | eligible={_b(candidate.get('eligible', False))} | "
                f"score={_n(candidate.get('competition_score', 0.0))} | stimulus={_n(candidate.get('stimulus_match_ratio', candidate.get('coverage_ratio', 0.0)))} | "
                f"structure={_n(candidate.get('structure_match_ratio', 0.0))} | depth={candidate.get('chain_depth', 0)} | "
                f"owner={candidate.get('owner_structure_id', '') or '-'}"
            )
        lines.append(
            f"  能量转移 actual={_n(round_detail.get('effective_transfer_fraction', 0.0))} | "
            f"ER={_n(round_detail.get('transferred_er', 0.0))} EV={_n(round_detail.get('transferred_ev', 0.0))}"
        )
        if round_detail.get("created_common_structure"):
            created = round_detail.get("created_common_structure", {})
            lines.append(f"  共同结构={_display_text(created)}[{created.get('structure_id', '')}]")
        if round_detail.get("created_residual_structure"):
            created = round_detail.get("created_residual_structure", {})
            lines.append(f"  残差结构={_display_text(created)}[{created.get('structure_id', '')}]")
        if round_detail.get("created_fresh_structure"):
            created = round_detail.get("created_fresh_structure", {})
            lines.append(f"  扩展结构={_display_text(created)}[{created.get('structure_id', '')}]")
        lines.append(f"  轮后残余={round_detail.get('remaining_grouped_text_after', '') or _tokens(round_detail.get('remaining_tokens_after', [])) or '空'}")
    return lines


def _render_projection(pool_apply: dict) -> list[str]:
    apply_result = pool_apply.get("apply_result", {})
    lines = ["[7/9] 状态池回写 / Projection & Pool Apply", THIN]
    if not apply_result:
        return lines + ["本轮没有状态池回写。"]
    lines.append(
        f"新建={apply_result.get('new_item_count', 0)} | 更新={apply_result.get('updated_item_count', 0)} | "
        f"合并={apply_result.get('merged_item_count', 0)} | 中和={apply_result.get('neutralized_item_count', 0)}"
    )
    landed = pool_apply.get("landed_packet", {})
    if landed:
        lines.append(f"落地残余包={landed.get('display_text', '') or '空'}")
    for item in pool_apply.get("bias_projection", [])[:12]:
        lines.append(f"- 偏置 {_display_text(item)}[{item.get('structure_id', '')}] | ER={_n(item.get('er', 0.0))} | EV={_n(item.get('ev', 0.0))}")
    for item in pool_apply.get("runtime_projection", [])[:12]:
        target_id = item.get("memory_id", "") or item.get("structure_id", "")
        lines.append(
            f"- 投影 {_display_text(item)}[{target_id}] | kind={item.get('projection_kind', 'structure')} | "
            f"reason={item.get('reason', '')} | ER={_n(item.get('er', 0.0))} | EV={_n(item.get('ev', 0.0))}"
        )
    return lines


def _render_induction(induction: dict) -> list[str]:
    data = induction.get("result", {})
    debug = data.get("debug", {})
    lines = ["[8/9] 感应赋能 / Induction Propagation", THIN]
    lines.append(
        f"感应源={data.get('source_item_count', 0)} | ev传播={data.get('propagated_target_count', 0)} | "
        f"er诱发={data.get('induced_target_count', 0)} | total_delta_ev={_n(data.get('total_delta_ev', 0.0))} | "
        f"total_ev_consumed={_n(data.get('total_ev_consumed', 0.0))}"
    )
    for source in debug.get("source_details", [])[:8]:
        lines.append(
            f"源={_display_text(source)}[{source.get('source_structure_id', '')}] | "
            f"ER={_n(source.get('source_er', 0.0))} EV={_n(source.get('source_ev', 0.0))}"
        )
        for entry in source.get("candidate_entries", [])[:12]:
            target_id = entry.get("memory_id", "") or entry.get("target_structure_id", "")
            lines.append(
                f"- {entry.get('mode', '')} -> {entry.get('target_display_text', '')}[{target_id}] | "
                f"kind={entry.get('projection_kind', 'structure')} | share={_n(entry.get('normalized_share', 0.0))} | "
                f"entries={entry.get('entry_count', 0)} | delta_ev={_n(entry.get('delta_ev', 0.0))} | "
                f"runtime={_n(entry.get('runtime_weight', 1.0))} | W={_n(entry.get('base_weight', 1.0))} "
                f"G={_n(entry.get('recent_gain', 1.0))} F={_n(entry.get('fatigue', 0.0))}"
            )
    for item in induction.get("applied_targets", [])[:16]:
        target_id = item.get("memory_id", "") or item.get("structure_id", "")
        lines.append(
            f"- 回写 {_display_text(item)}[{target_id}] | kind={item.get('projection_kind', 'structure')} | delta_ev={_n(item.get('ev', 0.0))}"
        )
    return lines


def _render_sensor(sensor: dict) -> list[str]:
    lines = ["[1/9] 文本感受器 / Text Sensor", THIN]
    if not sensor:
        return lines + ["本轮无外源输入。"]
    lines.append(f"输入={sensor.get('input_text', '')}")
    lines.append(
        f"模式={sensor.get('mode', '')} | tokenizer={sensor.get('tokenizer_backend', '')} | "
        f"可用={_b(sensor.get('tokenizer_available', False))} | fallback={_b(sensor.get('tokenizer_fallback', False))}"
    )
    lines.append(f"SA={sensor.get('sa_count', 0)} | CSA={sensor.get('csa_count', 0)} | 外源组={len(sensor.get('groups', []))}")
    for unit in sensor.get("units", sensor.get("feature_units", []))[:24]:
        lines.append(
            f"- {unit.get('display', unit.get('token', ''))} | role={unit.get('role', '')} | "
            f"ER={_n(unit.get('er', 0.0))} | EV={_n(unit.get('ev', 0.0))} | CSA={unit.get('bundle_display', '') or '无'}"
        )
    for group in sensor.get("groups", [])[:16]:
        lines.append(
            f"- G{group.get('group_index', 0)} | source={group.get('source_type', '')} | 文本={group.get('display_text', '')} | "
            f"tokens={_tokens(group.get('flat_tokens', group.get('tokens', []))) or '空'} | SA={group.get('sa_count', 0)} | "
            f"CSA={group.get('csa_count', 0)} | bundles={_tokens(group.get('csa_bundles', [])) or '无'}"
        )
    return lines


def _render_cognitive_feeling(cognitive_feeling: dict) -> list[str]:
    lines = ["[认知感受系统（CFS）] 认知感受输出", THIN]
    if not cognitive_feeling:
        return lines + ["本轮没有认知感受系统（CFS）输出。"]

    signals = list(cognitive_feeling.get("cfs_signals", []) or [])
    writes = cognitive_feeling.get("writes", {}) or {}
    meta = cognitive_feeling.get("meta", {}) or {}

    tick_number = meta.get("tick_number")
    runtime_nodes = list(writes.get("runtime_nodes", []) or [])
    attr_bindings = list(writes.get("attribute_bindings", []) or [])
    lines.append(
        f"tick_number={tick_number if tick_number is not None else '-'} | "
        f"signals={len(signals)} | runtime_nodes={len(runtime_nodes)} | attr_bindings={len(attr_bindings)}"
    )

    if attr_bindings:
        ok = sum(1 for item in attr_bindings if bool(item.get("success", False)))
        lines.append(f"属性绑定成功率 / Attr binding success={ok}/{len(attr_bindings)}")

    if not signals:
        lines.append("本轮未生成任何认知感受系统（CFS）信号。")
        return lines

    ordered = sorted(signals, key=lambda s: float(s.get("strength", 0.0) or 0.0), reverse=True)
    for sig in ordered[:16]:
        kind = str(sig.get("kind", ""))
        scope = str(sig.get("scope", ""))
        strength = _n(sig.get("strength", 0.0))
        target = sig.get("target") or {}
        target_display = str(target.get("target_display", "") or "")
        target_ref_id = str(target.get("target_ref_object_id", "") or "")
        target_ref_type = str(target.get("target_ref_object_type", "") or "")
        target_item_id = str(target.get("target_item_id", "") or "")
        target_label = target_display or target_ref_id or target_item_id or "—"
        ref_label = f"{target_ref_type}:{target_ref_id}" if (target_ref_type or target_ref_id) else ""
        if ref_label and target_item_id:
            ref_label = f"{ref_label} | item={target_item_id}"
        elif target_item_id:
            ref_label = f"item={target_item_id}"

        lines.append(f"- {kind}({scope}) | strength={strength} | target={target_label} | {ref_label or '-'}")
        reasons = list(sig.get("reasons", []) or [])
        if reasons:
            lines.append(f"  reason={reasons[0]}")

    return lines


def _render_emotion(emotion: dict) -> list[str]:
    lines = ["[情绪递质管理（NT 递质通道）] 情绪递质输出", THIN]
    if not emotion:
        return lines + ["本轮没有情绪递质输出。"]

    rwd_pun = emotion.get("rwd_pun_snapshot", {}) or {}
    decay = emotion.get("decay", {}) or {}
    before = emotion.get("nt_state_before", {}) or {}
    after = emotion.get("nt_state_after", {}) or {}
    deltas = emotion.get("deltas", {}) or {}
    modulation = emotion.get("modulation", {}) or {}

    lines.append(
        f"rwd={_n(rwd_pun.get('rwd', 0.0))} | pun={_n(rwd_pun.get('pun', 0.0))} | "
        f"global_decay={_n(decay.get('global_decay_ratio', 0.0))}"
    )

    def _fmt_channels(state: dict) -> str:
        if not isinstance(state, dict) or not state:
            return "空"
        parts = []
        for key in sorted(state.keys()):
            parts.append(f"{key}={_n(state.get(key, 0.0))}")
        return " ".join(parts)

    lines.append(f"NT(before) { _fmt_channels(before) }")
    lines.append(f"NT(after)  { _fmt_channels(after) }")

    applied = deltas.get("applied") or {}
    if isinstance(applied, dict) and applied:
        lines.append(f"applied_deltas { _fmt_channels(applied) }")

    att_mod = modulation.get("attention") if isinstance(modulation, dict) else None
    if isinstance(att_mod, dict) and att_mod:
        nt_snapshot = att_mod.get("nt_snapshot") or {}
        lines.append(
            f"调制(注意力) top_n={att_mod.get('top_n', '-') } | "
            f"cp_w={_n(att_mod.get('priority_weight_cp_abs', 0.0))} | "
            f"fatigue_w={_n(att_mod.get('priority_weight_fatigue', 0.0))} | "
            f"min_energy={_n(att_mod.get('min_total_energy', 0.0))} | nt={_fmt_channels(nt_snapshot)}"
        )

    return lines


def _render_innate_script(innate_script: dict) -> list[str]:
    lines = ["[先天编码脚本管理（IESM）] 先天规则输出", THIN]
    if not innate_script:
        return lines + ["本轮没有先天编码脚本管理（IESM）输出。"]

    active = innate_script.get("active_scripts", {}) or {}
    scripts = list(active.get("scripts", []) or [])
    version = active.get("script_version", "") or "-"
    lines.append(f"script_version={version} | active_scripts={len(scripts)}")
    for sc in scripts[:8]:
        lines.append(f"- {sc.get('script_id', '')} | enabled={_b(sc.get('enabled', False))} | kind={sc.get('kind', '')}")

    checks = list(innate_script.get("state_window_checks", []) or [])
    if checks:
        lines.append("state_window_checks")
        for chk in checks[:8]:
            stage = chk.get("stage", "") or "-"
            if chk.get("error"):
                lines.append(f"- {stage}: error={chk.get('error')}")
                continue
            check_data = chk.get("check", {}) or {}
            triggered = list(check_data.get("triggered_scripts", []) or [])
            summary = chk.get("packet_summary", {}) or {}
            lines.append(
                f"- {stage}: triggered={len(triggered)} | fast_cp_rise={summary.get('fast_cp_rise_item_count', 0)} | fast_cp_drop={summary.get('fast_cp_drop_item_count', 0)}"
            )
            for item in triggered[:6]:
                lines.append(f"  script={item.get('script_id', '')} | trigger={item.get('trigger', '')} | count={item.get('trigger_count', 0)}")

    focus = innate_script.get("focus", {}) or {}
    directives = list(focus.get("focus_directives", []) or [])
    audit = focus.get("audit", {}) or {}
    lines.append(
        f"focus_directives={len(directives)} | ttl={audit.get('ttl_ticks', '-') } | min_strength={audit.get('min_strength', '-') } | dedup_drop={audit.get('deduplicated_count', 0)}"
    )
    for d in directives[:12]:
        tgt = d.get("target_display", "") or d.get("target_ref_object_id", "") or d.get("target_item_id", "") or "—"
        lines.append(
            f"- {d.get('directive_id', '')} | kind={d.get('source_kind', '')} | strength={_n(d.get('strength', 0.0))} | boost={_n(d.get('focus_boost', 0.0))} | ttl={d.get('ttl_ticks', 0)} | target={tgt}"
        )

    return lines


def _render_stimulus(stimulus_level: dict, merged_stimulus: dict, cache: dict) -> list[str]:
    data = stimulus_level.get("result", {})
    debug = data.get("debug", {})
    residual_packet = cache.get("residual_packet", {})
    lines = ["[6/9] 刺激级查存一体 / Stimulus-level Retrieval-Storage", THIN]
    lines.append(f"完整刺激={merged_stimulus.get('display_text', '') or '空'}")
    lines.append(f"中和后残余={residual_packet.get('display_text', '') or '空'}")
    lines.append(
        f"轮次={data.get('round_count', 0)} | 命中结构={len(data.get('matched_structure_ids', []))} | "
        f"新建结构={len(data.get('new_structure_ids', []))} | 剩余SA={data.get('remaining_stimulus_sa_count', 0)} | fallback={_b(data.get('fallback_used', False))}"
    )
    for group in merged_stimulus.get("groups", [])[:16]:
        lines.append(
            f"- G{group.get('group_index', 0)} | source={group.get('source_type', '')} | 文本={group.get('display_text', '')} | "
            f"tokens={_tokens(group.get('flat_tokens', group.get('tokens', []))) or '空'} | SA={group.get('sa_count', 0)} | "
            f"CSA={group.get('csa_count', 0)} | bundles={_tokens(group.get('csa_bundles', [])) or '无'}"
        )
    for round_detail in debug.get("round_details", []):
        anchor = round_detail.get("anchor", {})
        lines.append(f"刺激级 Round {round_detail.get('round_index', 0)}")
        if anchor:
            lines.append(
                f"  Anchor={anchor.get('display_text', '')} | source={anchor.get('source_type', '')} | group={anchor.get('group_index', 0)} | "
                f"ER={_n(anchor.get('er', 0.0))} EV={_n(anchor.get('ev', 0.0))}"
            )
        lines.append(f"  轮前残余={_tokens(round_detail.get('remaining_tokens_before', [])) or '空'}")
        lines.append(f"  链式路径={_chain(round_detail.get('chain_steps', []), 'stimulus')}")
        selected = round_detail.get("selected_match")
        if selected:
            lines.append(
                f"  命中={selected.get('display_text', '')}[{selected.get('structure_id', '')}] | score={_n(selected.get('competition_score', selected.get('match_score', 0.0)))} | "
                f"coverage={_n(selected.get('coverage_ratio', 0.0))} | structure={_n(selected.get('structure_match_ratio', 0.0))} | common={_common(selected.get('common_part', {}))}"
            )
        else:
            lines.append("  本轮未命中已有结构。")
        for candidate in round_detail.get("candidate_details", [])[:8]:
            lines.append(
                f"  - {candidate.get('display_text', '')}[{candidate.get('structure_id', '')}] | eligible={_b(candidate.get('eligible', False))} | "
                f"score={_n(candidate.get('competition_score', 0.0))} | stimulus={_n(candidate.get('stimulus_match_ratio', candidate.get('coverage_ratio', 0.0)))} | "
                f"structure={_n(candidate.get('structure_match_ratio', 0.0))} | depth={candidate.get('chain_depth', 0)} | owner={candidate.get('owner_structure_id', '') or '-'}"
            )
        lines.append(
            f"  能量转移 actual={_n(round_detail.get('effective_transfer_fraction', 0.0))} | "
            f"ER={_n(round_detail.get('transferred_er', 0.0))} EV={_n(round_detail.get('transferred_ev', 0.0))}"
        )
        if round_detail.get("created_common_structure"):
            created = round_detail.get("created_common_structure", {})
            lines.append(f"  新建共同结构={created.get('display_text', '')}[{created.get('structure_id', '')}]")
        if round_detail.get("created_residual_structure"):
            created = round_detail.get("created_residual_structure", {})
            lines.append(f"  新建残差结构={created.get('display_text', '')}[{created.get('structure_id', '')}]")
        if round_detail.get("created_fresh_structure"):
            created = round_detail.get("created_fresh_structure", {})
            lines.append(f"  扩展结构={created.get('display_text', '')}[{created.get('structure_id', '')}]")
        lines.append(f"  轮后残余={_tokens(round_detail.get('remaining_tokens_after', [])) or '空'}")
    return lines


def _render_projection(pool_apply: dict) -> list[str]:
    apply_result = pool_apply.get("apply_result", {})
    lines = ["[7/9] 状态池回写 / Projection & Pool Apply", THIN]
    if not apply_result:
        return lines + ["本轮没有状态池回写。"]
    lines.append(
        f"新建={apply_result.get('new_item_count', 0)} | 更新={apply_result.get('updated_item_count', 0)} | "
        f"合并={apply_result.get('merged_item_count', 0)} | 中和={apply_result.get('neutralized_item_count', 0)}"
    )
    landed = pool_apply.get("landed_packet", {})
    if landed:
        lines.append(f"落地残余包={landed.get('display_text', '') or '空'}")
    for item in pool_apply.get("bias_projection", [])[:12]:
        lines.append(f"- 偏置 {item.get('display_text', '')}[{item.get('structure_id', '')}] | ER={_n(item.get('er', 0.0))} | EV={_n(item.get('ev', 0.0))}")
    for item in pool_apply.get("runtime_projection", [])[:12]:
        target_id = item.get("memory_id", "") or item.get("structure_id", "")
        lines.append(
            f"- 投影 {item.get('display_text', '')}[{target_id}] | kind={item.get('projection_kind', 'structure')} | "
            f"reason={item.get('reason', '')} | ER={_n(item.get('er', 0.0))} | EV={_n(item.get('ev', 0.0))}"
        )
    return lines


def _render_induction(induction: dict) -> list[str]:
    data = induction.get("result", {})
    debug = data.get("debug", {})
    lines = ["[8/9] 感应赋能 / Induction Propagation", THIN]
    lines.append(
        f"感应源={data.get('source_item_count', 0)} | ev传播={data.get('propagated_target_count', 0)} | "
        f"er诱发={data.get('induced_target_count', 0)} | total_delta_ev={_n(data.get('total_delta_ev', 0.0))} | total_ev_consumed={_n(data.get('total_ev_consumed', 0.0))}"
    )
    for source in debug.get("source_details", [])[:8]:
        lines.append(f"源={source.get('display_text', '')}[{source.get('source_structure_id', '')}] | ER={_n(source.get('source_er', 0.0))} EV={_n(source.get('source_ev', 0.0))}")
        for entry in source.get("candidate_entries", [])[:12]:
            target_id = entry.get("memory_id", "") or entry.get("target_structure_id", "")
            lines.append(
                f"- {entry.get('mode', '')} -> {entry.get('target_display_text', '')}[{target_id}] | kind={entry.get('projection_kind', 'structure')} | "
                f"share={_n(entry.get('normalized_share', 0.0))} | entries={entry.get('entry_count', 0)} | delta_ev={_n(entry.get('delta_ev', 0.0))} | "
                f"runtime={_n(entry.get('runtime_weight', 1.0))} | W={_n(entry.get('base_weight', 1.0))} G={_n(entry.get('recent_gain', 1.0))} F={_n(entry.get('fatigue', 0.0))}"
            )
    for item in induction.get("applied_targets", [])[:16]:
        target_id = item.get("memory_id", "") or item.get("structure_id", "")
        lines.append(
            f"- 回写 {item.get('display_text', '')}[{target_id}] | kind={item.get('projection_kind', 'structure')} | delta_ev={_n(item.get('ev', 0.0))}"
        )
    return lines


def _storage(summary: dict) -> str:
    if not summary:
        return "无"
    actions = []
    for item in summary.get("actions", []):
        action_type = str(item.get("type", ""))
        if not action_type:
            continue
        details = []
        if item.get("storage_table", ""):
            details.append(str(item.get("storage_table", "")))
        if item.get("group_id", ""):
            details.append(str(item.get("group_id", "")))
        if item.get("canonical_display_text", ""):
            details.append(f"canon={item.get('canonical_display_text', '')}")
        if item.get("raw_display_text", ""):
            details.append(f"raw={item.get('raw_display_text', '')}")
        if item.get("memory_id", ""):
            details.append(f"em={item.get('memory_id', '')}")
        actions.append(f"{action_type}({', '.join(details)})" if details else action_type)
    if summary.get("new_group_ids"):
        actions.append("new_group=" + ",".join(str(x) for x in summary.get("new_group_ids", [])))
    if summary.get("new_structure_ids"):
        actions.append("new_structure=" + ",".join(str(x) for x in summary.get("new_structure_ids", [])))
    return " | ".join(actions) if actions else _j(summary)


def _term_projection_kind_label(kind: str) -> str:
    mapping = {
        "structure": "结构 / Structure",
        "memory": "残差记忆 / Residual Memory",
    }
    return mapping.get(str(kind or ""), str(kind or "structure"))


def _term_notation_lines(*, indent: str = "") -> list[str]:
    lines = [f"{indent}记号说明 / Notation"]
    for item in semantic_notation_legend():
        lines.append(f"{indent}  {item['symbol']} = {item['meaning']}")
    lines.append(f"{indent}  读法提示: 刺激流是打散后的 SA/CSA，所以没有 []；结构与记忆保持为 ST，因此会出现 [].")
    lines.append(f"{indent}示例 / Examples")
    for item in semantic_notation_examples():
        lines.append(f"{indent}  {item['title']}: {item['example']}")
        lines.append(f"{indent}    {item['explanation']}")
    return lines


def _term_semantic_common_text(common_part: dict) -> str:
    if not common_part:
        return "无"
    groups = common_part.get("common_groups", [])
    if isinstance(groups, list) and groups:
        rendered = format_semantic_sequence_groups(groups)
        if rendered:
            return rendered
    return common_part.get("common_display", "") or _tokens(common_part.get("common_tokens", [])) or "无"


def _term_group_text(group: dict) -> str:
    if not isinstance(group, dict):
        return str(group)
    semantic_text = str(group.get("semantic_display_text", "") or "")
    if semantic_text:
        return semantic_text
    sequence_groups = group.get("sequence_groups", [])
    if isinstance(sequence_groups, list) and sequence_groups:
        rendered = format_semantic_sequence_groups(sequence_groups, context="stimulus")
        if rendered:
            return rendered
    units = group.get("units", [])
    if isinstance(units, list) and units:
        rendered = format_semantic_sequence_groups(
            [
                {
                    "group_index": group.get("group_index", 0),
                    "source_type": group.get("source_type", ""),
                    "origin_frame_id": group.get("origin_frame_id", ""),
                    "units": [dict(unit) for unit in units if isinstance(unit, dict)],
                    "csa_bundles": [dict(bundle) for bundle in group.get("csa_bundle_defs", []) if isinstance(bundle, dict)],
                    "tokens": list(group.get("tokens", [])),
                }
            ],
            context="stimulus",
        )
        if rendered:
            return rendered
    return (
        str(group.get("display_text", "") or "")
        or str(group.get("grouped_display_text", "") or "")
        or _tokens(group.get("tokens", []) or group.get("flat_tokens", []))
        or "空"
    )


def _term_group_rows(groups: list[dict], *, limit: int = 12) -> list[str]:
    rows: list[str] = []
    for group in (groups or [])[:limit]:
        if not isinstance(group, dict):
            continue
        text = _term_group_text(group)
        tokens = _tokens(group.get("tokens", []) or group.get("flat_tokens", [])) or "空"
        bundles = _tokens(group.get("csa_bundles", [])) or "无"
        rows.append(
            f"- G{group.get('group_index', 0)} | 来源/source={group.get('source_type', '') or '-'} | 分组/group={text}"
        )
        rows.append(
            f"  SA={group.get('sa_count', 0)} | CSA={group.get('csa_count', 0)} | 扁平 tokens/flat={tokens} | CSA 细节/bundles={bundles}"
        )
    if not rows:
        rows.append("- 无")
    return rows


def _term_budget_lines(title: str, budget: dict, *, indent: str = "  ") -> list[str]:
    lines = [f"{indent}{title}"]
    if not budget:
        lines.append(f"{indent}  无")
        return lines
    for key, value in (budget or {}).items():
        if isinstance(value, dict):
            lines.append(
                f"{indent}  {key}: ER={_n(value.get('er', 0.0))} | EV={_n(value.get('ev', 0.0))} | Total={_n(value.get('total', 0.0))}"
            )
        else:
            lines.append(f"{indent}  {key}: {value}")
    return lines


def _term_common_lines(common_part: dict, *, indent: str = "  ") -> list[str]:
    if not common_part:
        return [f"{indent}公共部分/Common=无"]
    lines = [f"{indent}公共部分/Common={_term_semantic_common_text(common_part)}"]
    if common_part.get("residual_existing_signature", ""):
        residual_existing = format_semantic_sequence_groups(common_part.get("residual_existing_groups", [])) or common_part.get("residual_existing_signature", "")
        lines.append(f"{indent}已有残余/Existing residual={residual_existing}")
    if common_part.get("residual_incoming_signature", ""):
        residual_incoming = format_semantic_sequence_groups(common_part.get("residual_incoming_groups", []), context="stimulus") or common_part.get("residual_incoming_signature", "")
        lines.append(f"{indent}输入残余/Incoming residual={residual_incoming}")
    return lines


def _term_storage_lines(summary: dict, *, indent: str = "  ") -> list[str]:
    # 结构级观测台必须把“写到了哪里、写了什么、关联哪个记忆”完整展示出来。
    lines = [f"{indent}局部库动作 / Local DB Action"]
    if not summary:
        lines.append(f"{indent}  无")
        return lines
    owner = summary.get("owner_display_text", "") or summary.get("owner_id", "") or "-"
    owner_kind = summary.get("owner_kind", "") or "-"
    db_id = summary.get("resolved_db_id", "") or "-"
    new_groups = " / ".join(str(item) for item in summary.get("new_group_ids", [])) or "无"
    new_structures = " / ".join(str(item) for item in summary.get("new_structure_ids", [])) or "无"
    lines.append(f"{indent}  拥有者/Owner={owner} ({owner_kind})")
    lines.append(f"{indent}  数据库/DB={db_id} | 新组/New groups={new_groups} | 新结构/New structures={new_structures}")
    actions = summary.get("actions", []) or []
    if not actions:
        lines.append(f"{indent}  本轮无写入 / No write this round")
        return lines
    for action in actions[:10]:
        if not isinstance(action, dict):
            continue
        label_zh = action.get("type_zh", "") or action.get("type", "") or "未命名动作"
        label_en = action.get("type", "") or "-"
        lines.append(f"{indent}  - 动作/Action={label_zh} | {label_en}")
        table_zh = action.get("storage_table_zh", "") or action.get("storage_table", "") or "-"
        table_en = action.get("storage_table", "") or "-"
        lines.append(f"{indent}    记录位置/Table={table_zh} ({table_en})")
        if action.get("entry_id", ""):
            lines.append(f"{indent}    记录 ID/Entry={action.get('entry_id', '')}")
        if action.get("group_id", ""):
            lines.append(f"{indent}    结构组/Group={action.get('group_id', '')}")
        if action.get("raw_display_text", ""):
            raw_text = format_semantic_sequence_groups(action.get("raw_sequence_groups", [])) or action.get("raw_display_text", "")
            lines.append(f"{indent}    原始残差/Raw={raw_text}")
        if action.get("canonical_display_text", ""):
            canonical_text = format_semantic_sequence_groups(action.get("canonical_sequence_groups", [])) or action.get("canonical_display_text", "")
            lines.append(f"{indent}    还原后/Canonical={canonical_text}")
        if action.get("memory_id", ""):
            lines.append(f"{indent}    关联记忆/em_id={action.get('memory_id', '')}")
    return lines


def _term_selected_group_lines(selected: dict, *, indent: str = "  ") -> list[str]:
    if not selected:
        return [f"{indent}选中结构组 / Selected group=无"]
    required = _refs(selected.get("required_structures", []), "structure_id") or "无"
    bias = _refs(selected.get("bias_structures", []), "structure_id") or "无"
    lines = [
        f"{indent}选中结构组 / Selected group",
        f"{indent}  ID={selected.get('group_id', '')} | 内容/Profile={_display_text(selected) or '无'}",
        f"{indent}  score={_n(selected.get('score', 0.0))} | base={_n(selected.get('base_similarity', 0.0))} | coverage={_n(selected.get('coverage_ratio', 0.0))} | structure={_n(selected.get('structure_ratio', 0.0))} | wave={_n(selected.get('wave_similarity', 0.0))}",
        f"{indent}  必要结构/Required={required}",
        f"{indent}  偏置结构/Bias={bias}",
    ]
    lines.extend(_term_common_lines(selected.get("common_part", {}), indent=f"{indent}  "))
    return lines


def _term_candidate_group_lines(groups: list[dict], *, indent: str = "  ") -> list[str]:
    lines = [f"{indent}候选结构组 / Candidate groups"]
    if not groups:
        lines.append(f"{indent}  本轮没有候选结构组。")
        return lines
    for group in groups[:8]:
        lines.append(
            f"{indent}  - {group.get('group_id', '')} | eligible={_b(group.get('eligible', False))} | score={_n(group.get('score', 0.0))} | runtime={_n(group.get('runtime_weight', 1.0))}"
        )
        lines.append(f"{indent}    内容/Profile={_display_text(group) or '无'}")
        lines.extend(_term_common_lines(group.get("common_part", {}), indent=f"{indent}    "))
    return lines


def _term_candidate_structure_lines(candidates: list[dict], *, indent: str = "  ") -> list[str]:
    lines = [f"{indent}候选结构 / Candidate structures"]
    if not candidates:
        lines.append(f"{indent}  本轮没有候选结构。")
        return lines
    for candidate in candidates[:8]:
        lines.append(
            f"{indent}  - {_display_text(candidate)}[{candidate.get('structure_id', '')}] | eligible={_b(candidate.get('eligible', False))} | score={_n(candidate.get('competition_score', candidate.get('match_score', 0.0)))} | exact={_b(candidate.get('exact_match', False))} | full={_b(candidate.get('full_structure_included', False))}"
        )
        lines.append(
            f"{indent}    stimulus={_n(candidate.get('stimulus_match_ratio', candidate.get('coverage_ratio', 0.0)))} | structure={_n(candidate.get('structure_match_ratio', 0.0))} | depth={candidate.get('chain_depth', 0)} | owner={candidate.get('owner_structure_id', '') or candidate.get('parent_structure_id', '') or '—'} | mode={candidate.get('match_mode', '-')}"
        )
        lines.extend(_term_common_lines(candidate.get("common_part", {}), indent=f"{indent}    "))
    return lines


def _term_projection_lines(items: list[dict], *, title: str, indent: str = "") -> list[str]:
    lines = [f"{indent}{title}"]
    if not items:
        lines.append(f"{indent}  无")
        return lines
    for item in items[:12]:
        target_id = item.get("memory_id", "") or item.get("structure_id", "") or item.get("target_structure_id", "")
        lines.append(
            f"{indent}  - {_display_text(item)}[{target_id}] | 类型/Kind={_term_projection_kind_label(item.get('projection_kind', 'structure'))} | 原因/Reason={item.get('reason', item.get('mode', '')) or '-'} | ER={_n(item.get('er', 0.0))} | EV={_n(item.get('ev', 0.0))}"
        )
    return lines


def _render_structure(structure_level: dict) -> list[str]:
    data = structure_level.get("result", {})
    debug = data.get("debug", {})
    lines = ["[4/9] 结构级查存一体 / Structure-level Retrieval-Storage", THIN]
    lines.append(
        f"CAM={data.get('cam_stub_count', 0)} | 轮次/Rounds={data.get('round_count', 0)} | 命中组/Matched groups={len(data.get('matched_group_ids', []))} | 新建组/New groups={len(data.get('new_group_ids', []))} | fallback={_b(data.get('fallback_used', False))}"
    )
    lines.extend(_term_notation_lines(indent=""))
    if debug.get("cam_items"):
        lines.append("当前 CAM 结构 / CAM structures")
        for item in debug.get("cam_items", [])[:16]:
            lines.append(
                f"- {_display_text(item)}[{item.get('structure_id', '')}] | ER={_n(item.get('er', 0.0))} | EV={_n(item.get('ev', 0.0))} | Total={_n(item.get('total_energy', 0.0))}"
            )
    for round_detail in debug.get("round_details", []):
        anchor = round_detail.get("anchor", {}) or {}
        lines.append(f"结构级 Round {round_detail.get('round_index', 0)}")
        if anchor:
            lines.append(
                f"  锚点结构 / Anchor={_display_text(anchor)}[{anchor.get('structure_id', '')}] | score={_n(anchor.get('anchor_score', 0.0))}"
            )
        lines.extend(_term_budget_lines("预算前 / Budget before", round_detail.get("budget_before", {}), indent="  "))
        lines.extend(_term_budget_lines("预算后 / Budget after", round_detail.get("budget_after", {}), indent="  "))
        lines.append(f"  链式打开 / Chain={_chain(round_detail.get('chain_steps', []), 'structure')}")
        lines.extend(_term_selected_group_lines(round_detail.get("selected_group") or {}, indent="  "))
        lines.extend(_term_storage_lines(round_detail.get("storage_summary", {}), indent="  "))
        if round_detail.get("internal_fragments"):
            lines.append("  内源片段 / Internal fragments")
            for fragment in round_detail.get("internal_fragments", [])[:8]:
                lines.append(
                    f"    - {fragment.get('display_text', '')} [{fragment.get('fragment_id', '')}] | energy_hint={_n(fragment.get('energy_hint', 0.0))}"
                )
        lines.extend(_term_candidate_group_lines(round_detail.get("candidate_groups", []), indent="  "))
    if debug.get("new_group_details"):
        lines.append("新建结构组 / New groups")
        for group in debug.get("new_group_details", [])[:12]:
            lines.append(
                f"- {group.get('group_id', '')} | 内容/Profile={_display_text(group) or '无'} | required={_refs(group.get('required_structures', []), 'structure_id') or '无'}"
            )
    return lines


def _render_stimulus(stimulus_level: dict, merged_stimulus: dict, cache: dict) -> list[str]:
    data = stimulus_level.get("result", {})
    debug = data.get("debug", {})
    residual_packet = cache.get("residual_packet", {})
    lines = ["[6/9] 刺激级查存一体 / Stimulus-level Retrieval-Storage", THIN]
    lines.append(f"完整刺激 / Full stimulus={_display_text(merged_stimulus) or merged_stimulus.get('display_text', '') or '空'}")
    lines.append(f"中和后残余 / Residual after neutralization={_display_text(residual_packet) or residual_packet.get('display_text', '') or '空'}")
    lines.append(
        f"轮次/Rounds={data.get('round_count', 0)} | 命中结构/Matched={len(data.get('matched_structure_ids', []))} | 新建结构/New={len(data.get('new_structure_ids', []))} | 剩余 SA/Remaining SA={data.get('remaining_stimulus_sa_count', 0)} | fallback={_b(data.get('fallback_used', False))}"
    )
    lines.append("完整刺激分组 / Full stimulus groups")
    lines.extend(_term_group_rows(merged_stimulus.get("groups", []), limit=16))
    for round_detail in debug.get("round_details", []):
        anchor = round_detail.get("anchor", {}) or round_detail.get("anchor_unit", {}) or {}
        lines.append(f"刺激级 Round {round_detail.get('round_index', 0)}")
        if anchor:
            lines.append(
                f"  锚点刺激元 / Anchor={anchor.get('display_text', anchor.get('token', ''))} | 来源/source={anchor.get('source_type', '') or '-'} | group={anchor.get('group_index', 0)} | seq={anchor.get('sequence_index', anchor.get('seq_index', 0))}"
            )
            lines.append(f"  锚点能量 / Anchor energy: ER={_n(anchor.get('er', 0.0))} | EV={_n(anchor.get('ev', 0.0))}")
        focus_group_text = format_semantic_sequence_groups(round_detail.get("focus_group_sequence_groups_before", []), context="stimulus") or round_detail.get("focus_group_text_before", "") or ""
        if focus_group_text:
            lines.append(f"  局部工作组 / Focus group={focus_group_text}")
        remaining_before = format_semantic_sequence_groups(round_detail.get("remaining_sequence_groups_before", []), context="stimulus") or round_detail.get("remaining_grouped_text_before", "") or "空"
        lines.append(f"  轮前残余 / Remaining before={remaining_before}")
        lines.append(f"  链式打开 / Chain={_chain(round_detail.get('chain_steps', []), 'stimulus')}")
        selected = round_detail.get("selected_match")
        if selected:
            lines.append(
                f"  命中结构 / Matched={_display_text(selected)}[{selected.get('structure_id', '')}] | score={_n(selected.get('competition_score', selected.get('match_score', 0.0)))} | exact={_b(selected.get('exact_match', False))} | full={_b(selected.get('full_structure_included', False))}"
            )
            lines.append(
                f"  覆盖/结构匹配 = { _n(selected.get('coverage_ratio', 0.0)) } / { _n(selected.get('structure_match_ratio', 0.0)) } | 模式/mode={selected.get('match_mode', '-')}"
            )
            lines.extend(_term_common_lines(selected.get("common_part", {}), indent="  "))
        else:
            lines.append("  本轮未命中已有结构。")
        lines.extend(_term_candidate_structure_lines(round_detail.get("candidate_details", []), indent="  "))
        lines.append(
            f"  能量转移 / Energy transfer: actual={_n(round_detail.get('effective_transfer_fraction', 0.0))} | ER={_n(round_detail.get('transferred_er', 0.0))} | EV={_n(round_detail.get('transferred_ev', 0.0))}"
        )
        if round_detail.get("created_common_structure"):
            created = round_detail.get("created_common_structure", {})
            lines.append(f"  新建共同结构 / New common structure={_display_text(created)}[{created.get('structure_id', '')}]")
        if round_detail.get("created_residual_structure"):
            created = round_detail.get("created_residual_structure", {})
            lines.append(f"  新建残差结构 / New residual structure={_display_text(created)}[{created.get('structure_id', '')}]")
        if round_detail.get("created_fresh_structure"):
            created = round_detail.get("created_fresh_structure", {})
            lines.append(f"  扩展结构 / Extension structure={_display_text(created)}[{created.get('structure_id', '')}]")
        remaining_after = format_semantic_sequence_groups(round_detail.get("remaining_sequence_groups_after", []), context="stimulus") or round_detail.get("remaining_grouped_text_after", "") or "空"
        lines.append(f"  轮后残余 / Remaining after={remaining_after}")
    if data.get("runtime_projection_structures"):
        lines.extend(_term_projection_lines(data.get("runtime_projection_structures", []), title="运行态投影 / Runtime projections"))
    return lines


def _render_projection(pool_apply: dict) -> list[str]:
    apply_result = pool_apply.get("apply_result", {})
    lines = ["[7/9] 状态池回写 / Projection & Pool Apply", THIN]
    if not apply_result:
        return lines + ["本轮没有状态池回写。"]
    lines.append(
        f"新建/New={apply_result.get('new_item_count', 0)} | 更新/Update={apply_result.get('updated_item_count', 0)} | 合并/Merge={apply_result.get('merged_item_count', 0)} | 中和/Neutralize={apply_result.get('neutralized_item_count', 0)}"
    )
    landed = pool_apply.get("landed_packet", {})
    if landed:
        lines.append(f"落地残余包 / Landed residual={landed.get('display_text', '') or '空'}")
    priority_summary = pool_apply.get("priority_summary", {})
    if priority_summary:
        lines.append(
            f"优先中和 / Priority neutralization: count={priority_summary.get('priority_neutralized_item_count', 0)} | ER={_n(priority_summary.get('consumed_er', 0.0))} | EV={_n(priority_summary.get('consumed_ev', 0.0))}"
        )
    if pool_apply.get("priority_events"):
        lines.append("优先中和事件 / Priority neutralization events")
        for event in pool_apply.get("priority_events", [])[:12]:
            extra = event.get("extra_context", {}) or {}
            et = _term_event_type_label(str(event.get("event_type", "") or "priority_stimulus_neutralization"))
            lines.append(
                f"- {et} | 目标={event.get('target_display', '') or event.get('target_item_id', '')} | matched_sig={event.get('matched_structure_signature', '') or '无'} | matched_tokens={_tokens(extra.get('matched_tokens', [])) or '无'} | {extra.get('consumed_energy_key', 'energy')}={_n(extra.get('consumed_amount', 0.0))}"
            )
    lines.extend(_term_projection_lines(pool_apply.get("bias_projection", []), title="偏置投影 / Bias projection"))
    lines.extend(_term_projection_lines(pool_apply.get("runtime_projection", []), title="运行态投影 / Runtime projection"))
    return lines


def _render_induction(induction: dict) -> list[str]:
    data = induction.get("result", {})
    debug = data.get("debug", {})
    source_selection = induction.get("source_selection", {}) or data.get("source_selection", {}) or {}
    source_details = list(debug.get("source_details", []) or [])
    source_hit_count = sum(1 for source in source_details if list(source.get("candidate_entries", []) or []))
    source_miss_count = max(0, len(source_details) - source_hit_count)
    lines = ["[8/9] 感应赋能 / Induction Propagation", THIN]
    lines.append(
        f"可用源/参与={source_selection.get('induction_source_available_runtime_count', data.get('source_item_count', 0))}/{data.get('source_item_count', 0)} | "
        f"ER源={source_selection.get('induction_source_selected_from_er_count', 0)} | EV源={source_selection.get('induction_source_selected_from_ev_count', 0)} | "
        f"命中源={source_hit_count} | 无候选={source_miss_count} | "
        f"EV传播={data.get('propagated_target_count', 0)} | ER诱发={data.get('induced_target_count', 0)} | "
        f"total_delta_ev={_n(data.get('total_delta_ev', 0.0))} | total_ev_consumed={_n(data.get('total_ev_consumed', 0.0))}"
    )
    for source in source_details[:8]:
        source_id = str(source.get("source_item_id", "") or source.get("source_structure_id", "") or "")
        support_ids = [str(x) for x in (source.get("resolved_support_structure_ids", []) or source.get("support_structure_ids", []) or []) if str(x)]
        pointer_info = source.get("pointer_info", {}) if isinstance(source.get("pointer_info", {}), dict) else {}
        lines.append(
            f"源对象 / Source={source.get('display_text', '')}[{source_id}] | type={source.get('source_ref_object_type', '') or '-'} | ER={_n(source.get('source_er', 0.0))} | EV={_n(source.get('source_ev', 0.0))}"
        )
        lines.append(
            f"  support={','.join(support_ids) if support_ids else '-'} | db={pointer_info.get('resolved_db_id', '-') or '-'} | fallback={_b(pointer_info.get('used_fallback', False))}"
        )
        entries = source.get("candidate_entries", []) or []
        if not entries:
            skipped_reason = str(source.get("skipped_reason", "") or "")
            if skipped_reason:
                lines.append(f"  本轮未执行有效赋能：{skipped_reason}")
            else:
                lines.append("  该源对象本轮没有命中可赋能目标。")
            continue
        for entry in entries[:12]:
            target_id = entry.get("memory_id", "") or entry.get("target_structure_id", "")
            lines.append(
                f"  - {entry.get('mode', '')} -> {entry.get('target_display_text', '')}[{target_id}] | 类型/Kind={_term_projection_kind_label(entry.get('projection_kind', 'structure'))} | share={_n(entry.get('normalized_share', 0.0))} | entries={entry.get('entry_count', 0)} | delta_ev={_n(entry.get('delta_ev', 0.0))}"
            )
            lines.append(
                f"    runtime={_n(entry.get('runtime_weight', 1.0))} | W={_n(entry.get('base_weight', 1.0))} | G={_n(entry.get('recent_gain', 1.0))} | F={_n(entry.get('fatigue', 0.0))}"
            )
    lines.extend(_term_projection_lines(induction.get("applied_targets", []), title="赋能回写 / Applied targets"))
    return lines


def _storage(summary: dict) -> str:
    lines = _term_storage_lines(summary, indent="")
    return " | ".join(line.strip() for line in lines if line.strip())


def _render_sensor(sensor: dict) -> list[str]:
    lines = ["[1/9] 文本感受器 / Text Sensor", THIN]
    if not sensor:
        return lines + ["本轮无外源输入。"]
    lines.append(f"输入={sensor.get('input_text', '')}")
    lines.append(
        f"模式={sensor.get('mode', '')} | tokenizer={sensor.get('tokenizer_backend', '')} | "
        f"可用={_b(sensor.get('tokenizer_available', False))} | fallback={_b(sensor.get('tokenizer_fallback', False))}"
    )
    lines.append(f"SA={sensor.get('sa_count', 0)} | CSA={sensor.get('csa_count', 0)} | 外源组={len(sensor.get('groups', []))}")
    fatigue = sensor.get("fatigue_summary", {}) or {}
    if fatigue:
        lines.append(
            f"刺激疲劳 suppressed={fatigue.get('suppressed_unit_count', 0)} | zero_er={fatigue.get('zero_er_unit_count', 0)} | "
            f"before={_n(fatigue.get('total_er_before_fatigue', 0.0))} | after={_n(fatigue.get('total_er_after_fatigue', 0.0))} | "
            f"suppressed_er={_n(fatigue.get('total_er_suppressed', 0.0))}"
        )
    for unit in sensor.get("units", sensor.get("feature_units", []))[:24]:
        fatigue_suffix = ""
        if float(unit.get("suppression_ratio", 0.0)) > 0.0 or int(unit.get("window_count", 0)) > 0:
            fatigue_suffix = (
                f" | suppression={_n(unit.get('suppression_ratio', 0.0))}"
                f" | ER { _n(unit.get('er_before_fatigue', unit.get('er', 0.0))) }->{ _n(unit.get('er_after_fatigue', unit.get('er', 0.0))) }"
                f" | count={unit.get('window_count', 0)}/{unit.get('threshold_count', 0)}"
            )
        lines.append(
            f"- {unit.get('display', unit.get('token', ''))} | role={unit.get('role', '')} | "
            f"ER={_n(unit.get('er', 0.0))} | EV={_n(unit.get('ev', 0.0))} | CSA={unit.get('bundle_display', '') or '无'}{fatigue_suffix}"
        )
    for group in sensor.get("groups", [])[:16]:
        lines.append(
            f"- G{group.get('group_index', 0)} | source={group.get('source_type', '')} | 文本={group.get('display_text', '')} | "
            f"tokens={_tokens(group.get('flat_tokens', group.get('tokens', []))) or '空'} | SA={group.get('sa_count', 0)} | "
            f"CSA={group.get('csa_count', 0)} | bundles={_tokens(group.get('csa_bundles', [])) or '无'}"
        )
    return lines
