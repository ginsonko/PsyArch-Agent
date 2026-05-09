# -*- coding: utf-8 -*-
"""


def _semantic_sequence_text(groups: list[dict] | None, *, context: str = "auto") -> str:
    from hdb._sequence_display import format_semantic_sequence_groups

    if not isinstance(groups, list) or not groups:
        return ""
    return format_semantic_sequence_groups(groups, context=context)


def _notation_block() -> str:
    from hdb._sequence_display import semantic_notation_examples, semantic_notation_legend

    legend_items = "".join(
        f"<li><code>{e(item['symbol'])}</code> {e(item['meaning'])}</li>"
        for item in semantic_notation_legend()
    )
    example_items = "".join(
        (
            "<li>"
            f"<strong>{e(item['title'])}</strong>: <code>{e(item['example'])}</code><br/>"
            f"{e(item['explanation'])}"
            "</li>"
        )
        for item in semantic_notation_examples()
    )
    return (
        "<section class='subpanel'>"
        "<h4>记号说明 / Notation</h4>"
        "<div class='round-note'>刺激流是打散后的 SA/CSA，所以没有 <code>[]</code>；结构与记忆保持为 ST，因此会出现 <code>[]</code>。</div>"
        f"<ul>{legend_items}</ul>"
        f"<ul>{example_items}</ul>"
        "</section>"
    )


def _display_text(item: dict) -> str:
    if not isinstance(item, dict):
        return str(item)
    semantic_text = item.get("semantic_grouped_display_text") or item.get("semantic_display_text") or ""
    if semantic_text:
        return str(semantic_text)
    rendered = _semantic_sequence_text(item.get("sequence_groups", []))
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


def _details_block(*, summary: str, body: str) -> str:
    return f"<details class='round' open><summary>{e(summary)}</summary>{body}</details>"


def _storage_summary(summary: dict) -> str:
    if not summary:
        return "无"
    actions = []
    for item in summary.get("actions", [])[:12]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("type", ""))
        if not label:
            continue
        parts = []
        if item.get("storage_table", ""):
            parts.append(f"table={item.get('storage_table', '')}")
        if item.get("group_id", ""):
            parts.append(f"group={item.get('group_id', '')}")
        if item.get("canonical_display_text", ""):
            parts.append(f"canonical={item.get('canonical_display_text', '')}")
        if item.get("raw_display_text", ""):
            parts.append(f"raw={item.get('raw_display_text', '')}")
        if item.get("memory_id", ""):
            parts.append(f"em={item.get('memory_id', '')}")
        actions.append(f"{label}({' | '.join(parts)})" if parts else label)
    return (
        f"{summary.get('owner_display_text', '') or summary.get('owner_id', '')}"
        f"({summary.get('owner_kind', '')}) | db={summary.get('resolved_db_id', '') or '-'} | "
        f"new_groups={','.join(summary.get('new_group_ids', [])) or '无'} | actions={' ; '.join(actions) or '无'}"
    )


def _render_sensor_section(sensor: dict) -> str:
    unit_rows = [
        [
            unit.get("display", unit.get("token", "")),
            unit.get("role", ""),
            unit.get("unit_kind", ""),
            unit.get("source_type", ""),
            f(unit.get("er", 0.0)),
            f(unit.get("ev", 0.0)),
            unit.get("bundle_display", "") or "无",
        ]
        for unit in sensor.get("feature_units", sensor.get("units", []))[:24]
    ]
    group_rows = [
        [
            group.get("group_index", 0),
            group.get("source_type", ""),
            group.get("display_text", ""),
            " / ".join(group.get("tokens", [])),
            group.get("sa_count", 0),
            group.get("csa_count", 0),
            " ; ".join(group.get("csa_bundles", [])) or "无",
        ]
        for group in sensor.get("groups", [])[:20]
    ]
    return _section(
        "sensor",
        "文本感受器 / Text Sensor",
        "".join(
            [
                _metric_card("模式", sensor.get("mode", ""), f"分词后端 {sensor.get('tokenizer_backend', '')}"),
                _metric_card("SA / CSA", f"{sensor.get('sa_count', 0)} / {sensor.get('csa_count', 0)}", f"echo 参与帧 {len(sensor.get('echo_frames_used', []))}"),
                _metric_card("输入", sensor.get("input_text", "") or "空", sensor.get("normalized_text", "") or "-"),
            ]
        )
        + _table("刺激单元", ["显示", "角色", "类型", "来源", "ER", "EV", "CSA"], unit_rows)
        + _table("外源刺激组", ["组", "来源", "文本", "tokens", "SA", "CSA", "bundles"], group_rows),
    )


def _render_stimulus_section(stimulus_level: dict, merged_stimulus: dict) -> str:
    data = stimulus_level.get("result", {})
    debug = data.get("debug", {})
    group_rows = [
        [
            group.get("group_index", 0),
            group.get("source_type", ""),
            group.get("display_text", ""),
            " / ".join(group.get("tokens", [])),
            group.get("sa_count", 0),
            group.get("csa_count", 0),
            " ; ".join(group.get("csa_bundles", [])) or "无",
        ]
        for group in merged_stimulus.get("groups", [])
    ]
    round_blocks = []
    for round_detail in debug.get("round_details", []):
        selected = round_detail.get("selected_match") or {}
        common = round_detail.get("created_common_structure") or {}
        residual = round_detail.get("created_residual_structure") or {}
        fresh = round_detail.get("created_fresh_structure") or {}
        candidate_rows = [
            [
                candidate.get("structure_id", ""),
                _display_text(candidate),
                yn(candidate.get("eligible", False)),
                f(candidate.get("competition_score", 0.0)),
                f(candidate.get("stimulus_match_ratio", candidate.get("coverage_ratio", 0.0))),
                f(candidate.get("structure_match_ratio", 0.0)),
                candidate.get("chain_depth", 0),
                candidate.get("owner_structure_id", "") or "-",
            ]
            for candidate in round_detail.get("candidate_details", [])[:12]
        ]
        round_blocks.append(
            _details_block(
                summary=f"Round {round_detail.get('round_index', 0)} | residual {round_detail.get('remaining_grouped_text_before', '') or '无'}",
                body=(
                    f"<div class='round-note'>命中={e(_display_text(selected) or '无')}[{e(selected.get('structure_id', ''))}] | "
                    f"轮后残余={e(round_detail.get('remaining_grouped_text_after', '') or '无')}</div>"
                    f"<div class='chips'>"
                    f"<span class='chip'>链式路径: {e(_chain(round_detail.get('chain_steps', []), 'stimulus'))}</span>"
                    f"<span class='chip'>共同结构: {e(_display_text(common) or '无')}</span>"
                    f"<span class='chip'>残差结构: {e(_display_text(residual) or '无')}</span>"
                    f"<span class='chip'>扩展结构: {e(_display_text(fresh) or '无')}</span>"
                    f"</div>"
                    + _table(
                        "候选结构",
                        ["结构ID", "内容", "eligible", "score", "stimulus", "structure", "depth", "owner"],
                        candidate_rows,
                    )
                ),
            )
        )
    projection_rows = [
        [
            item.get("projection_kind", "structure"),
            item.get("memory_id", "") or item.get("structure_id", ""),
            _display_text(item),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            item.get("reason", ""),
        ]
        for item in data.get("runtime_projection_structures", [])
    ]
    return _section(
        "stimulus",
        "刺激级查存一体 / Stimulus-level Retrieval-Storage",
        "".join(
            [
                _metric_card("轮次", str(data.get("round_count", 0)), f"剩余 SA {data.get('remaining_stimulus_sa_count', 0)}"),
                _metric_card("命中结构", str(len(data.get("matched_structure_ids", []))), " / ".join(data.get("matched_structure_ids", [])[:6]) or "无"),
                _metric_card("新建结构", str(len(data.get("new_structure_ids", []))), " / ".join(data.get("new_structure_ids", [])[:6]) or "无"),
            ]
        )
        + _table("完整刺激分组", ["组", "来源", "文本", "tokens", "SA", "CSA", "bundles"], group_rows)
        + "".join(round_blocks)
        + _table("运行态投影", ["kind", "target_id", "display", "ER", "EV", "reason"], projection_rows),
    )


def _render_projection_section(pool_apply: dict) -> str:
    apply_result = pool_apply.get("apply_result", {})
    landed = pool_apply.get("landed_packet", {})
    runtime_rows = [
        [
            item.get("projection_kind", "structure"),
            item.get("memory_id", "") or item.get("structure_id", ""),
            _display_text(item),
            item.get("reason", ""),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
        ]
        for item in pool_apply.get("runtime_projection", [])[:16]
    ]
    bias_rows = [
        [
            item.get("structure_id", ""),
            _display_text(item),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
        ]
        for item in pool_apply.get("bias_projection", [])[:16]
    ]
    return _section(
        "projection",
        "状态池回写 / Projection & Pool Apply",
        "".join(
            [
                _metric_card("新建 / 更新", f"{apply_result.get('new_item_count', 0)} / {apply_result.get('updated_item_count', 0)}", f"merged {apply_result.get('merged_item_count', 0)}"),
                _metric_card("落地残余", landed.get("display_text", "") or "空", f"neutralized {apply_result.get('neutralized_item_count', 0)}"),
            ]
        )
        + _table("偏置投影", ["结构ID", "内容", "ER", "EV"], bias_rows)
        + _table("运行态投影", ["kind", "target_id", "display", "reason", "ER", "EV"], runtime_rows),
    )


def _render_induction_section(induction: dict) -> str:
    data = induction.get("result", {})
    debug = data.get("debug", {})
    source_blocks = []
    for source in debug.get("source_details", [])[:10]:
        entry_rows = [
            [
                entry.get("mode", ""),
                entry.get("projection_kind", "structure"),
                entry.get("memory_id", "") or entry.get("target_structure_id", ""),
                entry.get("target_display_text", ""),
                f(entry.get("normalized_share", 0.0)),
                entry.get("entry_count", 0),
                f(entry.get("delta_ev", 0.0)),
                f(entry.get("runtime_weight", 0.0)),
            ]
            for entry in source.get("candidate_entries", [])[:16]
        ]
        source_blocks.append(
            _details_block(
                summary=f"{source.get('source_structure_id', '')}[{_display_text(source)}] | er {f(source.get('source_er', 0.0))} | ev {f(source.get('source_ev', 0.0))}",
                body=_table("赋能目标", ["mode", "kind", "target_id", "display", "share", "entries", "delta_ev", "runtime"], entry_rows),
            )
        )
    applied_rows = [
        [
            item.get("projection_kind", "structure"),
            item.get("memory_id", "") or item.get("structure_id", ""),
            _display_text(item),
            f(item.get("ev", 0.0)),
        ]
        for item in induction.get("applied_targets", [])[:16]
    ]
    return _section(
        "induction",
        "感应赋能 / Induction Propagation",
        "".join(
            [
                _metric_card("感应源对象", str(data.get("source_item_count", 0)), f"fallback {yn(data.get('fallback_used', False))}"),
                _metric_card("EV / ER", f"{data.get('propagated_target_count', 0)} / {data.get('induced_target_count', 0)}", f"ΔEV {f(data.get('total_delta_ev', 0.0))}"),
                _metric_card("EV 消耗", f(data.get("total_ev_consumed", 0.0)), f"updated {data.get('updated_weight_count', 0)}"),
            ]
        )
        + "".join(source_blocks)
        + _table("赋能回写", ["kind", "target_id", "display", "delta_ev"], applied_rows),
    )
HTML exporter for observatory cycle reports.
"""

from __future__ import annotations

import html
from pathlib import Path


def export_cycle_html(report: dict, html_path: str | Path) -> str:
    target = Path(html_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    sections = [
        _render_sensor_section(report.get("sensor", {})),
        _render_maintenance_section(report.get("maintenance", {})),
        _render_cognitive_stitching_section(report.get("cognitive_stitching", {})),
        _render_attention_section(report.get("attention", {})),
        _render_structure_section(report.get("structure_level", {})),
        _render_projection_section(report.get("pool_apply", {})),
        _render_stimulus_section(report.get("stimulus_level", {}), report.get("merged_stimulus", {})),
        _render_induction_section(report.get("induction", {})),
        _render_final_section(report.get("final_state", {})),
    ]

    page = [
        "<!doctype html>",
        "<html lang='zh-CN'>",
        "<head>",
        "<meta charset='utf-8' />",
        "<meta name='viewport' content='width=device-width, initial-scale=1' />",
        f"<title>AP 研究观测报告 {e(report.get('trace_id', ''))}</title>",
        "<style>",
        _CSS,
        "</style>",
        "</head>",
        "<body>",
        _render_shell(report),
        "<main class='layout'>",
        _render_overview(report),
        "".join(sections),
        "</main>",
        "</body>",
        "</html>",
    ]
    target.write_text("".join(page), encoding="utf-8")
    return str(target)


def _render_shell(report: dict) -> str:
    return (
        "<aside class='shell'>"
        "<div class='brand'>"
        "<div class='eyebrow'>Artificial PsyArch</div>"
        "<h1>研究观测台</h1>"
        f"<p>轮次 {e(report.get('trace_id', ''))}</p>"
        "</div>"
        "<nav class='nav'>"
        "<a href='#cognitive_stitching'>Cognitive Stitching</a>"
        "<a href='#overview'>总览</a>"
        "<a href='#sensor'>文本感受器</a>"
        "<a href='#maintenance'>状态池维护</a>"
        "<a href='#attention'>注意力占位</a>"
        "<a href='#structure'>结构级查存</a>"
        "<a href='#projection'>入池与投影</a>"
        "<a href='#stimulus'>刺激级查存</a>"
        "<a href='#induction'>感应赋能</a>"
        "<a href='#final'>最终状态</a>"
        "</nav>"
        "</aside>"
    )


def _render_overview(report: dict) -> str:
    sensor = report.get("sensor", {})
    final_state = report.get("final_state", {})
    hdb_summary = final_state.get("hdb_snapshot", {}).get("summary", {})
    energy_summary = final_state.get("state_energy_summary", {})
    cards = [
        _metric_card("输入文本", sensor.get("input_text", "本轮无外源输入"), sensor.get("normalized_text", "")),
        _metric_card("状态池对象", str(final_state.get("state_snapshot", {}).get("summary", {}).get("active_item_count", 0)), "当前活跃运行态对象"),
        _metric_card("总 ER / EV", f"{f(energy_summary.get('total_er', 0.0))} / {f(energy_summary.get('total_ev', 0.0))}", "最终状态池能量总量"),
        _metric_card("HDB", f"ST {hdb_summary.get('structure_count', 0)} / SG {hdb_summary.get('group_count', 0)}", f"EM {hdb_summary.get('episodic_count', 0)}"),
    ]
    return (
        "<section id='overview' class='hero'>"
        "<div class='hero-copy'>"
        "<div class='eyebrow'>AP Prototype Observatory</div>"
        "<h2>面向实验观察的细粒度观测报告</h2>"
        "<p>这里会同时展示外源刺激、状态池维护、结构级与刺激级查存、赋能路径、结构内容与最终能量分布。</p>"
        "</div>"
        f"<div class='grid cards'>{''.join(cards)}</div>"
        "</section>"
    )


def _render_sensor_section(sensor: dict) -> str:
    feature_rows = [
        [
            unit.get("display", ""),
            unit.get("role", ""),
            unit.get("bundle_display", "") or "无",
            unit.get("sequence_index", 0),
            f(unit.get("er", 0.0)),
            f(unit.get("ev", 0.0)),
        ]
        for unit in sensor.get("units", sensor.get("feature_units", []))[:40]
    ]
    group_rows = [
        [
            f"G{group.get('group_index', 0)}",
            group.get("source_type", ""),
            group.get("display_text", ""),
            " / ".join(group.get("tokens", [])),
            group.get("sa_count", 0),
            group.get("csa_count", 0),
            " ; ".join(group.get("csa_bundles", [])),
        ]
        for group in sensor.get("groups", [])[:20]
    ]
    cards = [
        _metric_card("模式", sensor.get("mode", ""), f"分词后端 {sensor.get('tokenizer_backend', '')}"),
        _metric_card("分词可用", yn(sensor.get("tokenizer_available", False)), f"fallback {yn(sensor.get('tokenizer_fallback', False))}"),
        _metric_card("SA / CSA", f"{sensor.get('sa_count', 0)} / {sensor.get('csa_count', 0)}", f"echo 参与帧 {len(sensor.get('echo_frames_used', []))}"),
        _metric_card("Echo 衰减", e(str(sensor.get("echo_decay_summary", {}))), "感受器残响池本轮变化"),
    ]
    return _section(
        "sensor",
        "文本感受器 / Text Sensor",
        "".join(cards)
        + _table("特征 SA / 分词结果", ["内容", "粒度", "序号", "ER"], feature_rows)
        + _table("外源刺激组", ["组", "来源", "文本", "tokens", "SA", "CSA"], group_rows),
    )


def _render_maintenance_section(maintenance: dict) -> str:
    summary = maintenance.get("summary", {})
    before = maintenance.get("before_summary", {})
    after = maintenance.get("after_summary", {})
    event_rows = [
        [
            event.get("event_type", ""),
            f"{event.get('target_item_id', '')}[{event.get('target_display', '')}]",
            event.get("target_ref_object_type", ""),
            event.get("reason", ""),
            f"{event.get('before', {}).get('er', 0.0):.4f}->{event.get('after', {}).get('er', 0.0):.4f}",
            f"{event.get('before', {}).get('ev', 0.0):.4f}->{event.get('after', {}).get('ev', 0.0):.4f}",
            f"{event.get('before', {}).get('cp_abs', 0.0):.4f}->{event.get('after', {}).get('cp_abs', 0.0):.4f}",
        ]
        for event in maintenance.get("events", [])[:18]
    ]
    cards = [
        _metric_card("对象数", f"{before.get('active_item_count', 0)} -> {after.get('active_item_count', 0)}", "维护前后状态池规模"),
        _metric_card("衰减", str(summary.get("decayed_item_count", 0)), "本轮执行自适应衰减的对象数"),
        _metric_card("中和 / 淘汰", f"{summary.get('neutralized_item_count', 0)} / {summary.get('pruned_item_count', 0)}", "中和与淘汰数量"),
        _metric_card("高认知压", str(after.get("high_cp_item_count", 0)), f"类型分布 {after.get('object_type_counts', {})}"),
    ]
    return _section(
        "maintenance",
        "状态池自适应维护 / State Pool Maintenance",
        "".join(cards)
        + _table("维护事件", ["事件", "目标", "类型", "原因", "ER", "EV", "CP"], event_rows),
    )


def _render_cognitive_stitching_section(cognitive_stitching: dict) -> str:
    candidate_audit = cognitive_stitching.get("candidate_audit", {}) if isinstance(cognitive_stitching.get("candidate_audit", {}), dict) else {}
    rejected_reason_counts = candidate_audit.get("rejected_reason_counts", {}) if isinstance(candidate_audit.get("rejected_reason_counts", {}), dict) else {}
    score_means = candidate_audit.get("score_means", {}) if isinstance(candidate_audit.get("score_means", {}), dict) else {}
    candidate_rows = [
        [
            item.get("action_type", ""),
            item.get("source_display", ""),
            item.get("source_kind", ""),
            item.get("target_display", ""),
            item.get("target_kind", ""),
            item.get("match_mode", ""),
            item.get("context_k", 0),
            item.get("matched_span", 0),
            f(item.get("score", 0.0)),
            f(item.get("edge_weight_ratio", 0.0)),
            f(item.get("match_strength", 0.0)),
            f(item.get("fatigue_before", 0.0)),
        ]
        for item in cognitive_stitching.get("candidate_preview", [])[:12]
    ]
    rejection_rows = [
        [
            item.get("reason", ""),
            item.get("action_type", ""),
            item.get("source_display", ""),
            item.get("target_display", ""),
            f(item.get("score", 0.0)),
            f(item.get("min_candidate_score", 0.0)),
            f(item.get("threshold_margin", 0.0)),
            f(item.get("base_score", 0.0)),
        ]
        for item in candidate_audit.get("rejection_preview", [])[:10]
    ]
    competition_rows = [
        [
            item.get("outcome", ""),
            item.get("candidate_signature", ""),
            item.get("action_type", ""),
            f(item.get("incoming_score", 0.0)),
            f(item.get("existing_score", 0.0)),
            item.get("incoming_source_display", ""),
            item.get("incoming_target_display", ""),
        ]
        for item in candidate_audit.get("competition_preview", [])[:10]
    ]
    action_rows = [
        [
            item.get("action", ""),
            item.get("action_family", ""),
            item.get("event_display", ""),
            item.get("event_component_count", 0),
            item.get("source_display", ""),
            item.get("source_kind", ""),
            item.get("target_display", ""),
            item.get("target_kind", ""),
            item.get("match_mode", ""),
            item.get("context_k", 0),
            item.get("matched_span", 0),
            f(item.get("score", 0.0)),
            f(item.get("absorbed_total", 0.0)),
            f(item.get("fatigue_after", 0.0)),
        ]
        for item in cognitive_stitching.get("actions", [])[:12]
    ]
    narrative_rows = [
        [
            item.get("display", ""),
            item.get("ref_object_id", ""),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            f(item.get("cp_abs", 0.0)),
            f(item.get("event_grasp", 0.0)),
            f(item.get("salience_score", 0.0)),
            item.get("component_count", 0),
            item.get("esdb_parent_depth", 0),
            item.get("esdb_delta_entry_count", 0),
            1 if item.get("esdb_materialized", False) else 0,
            item.get("esdb_update_count", 0),
        ]
        for item in cognitive_stitching.get("narrative_top_items", [])[:12]
    ]
    cards = [
        _metric_card("enabled", yn(cognitive_stitching.get("enabled", False)), cognitive_stitching.get("reason", "")),
        _metric_card("seed / candidate", f"{cognitive_stitching.get('seed_structure_count', 0)} / {cognitive_stitching.get('candidate_count', 0)}", f"stage {cognitive_stitching.get('stage', '')}"),
        _metric_card("plain / event seed", f"{cognitive_stitching.get('seed_plain_structure_count', 0)} / {cognitive_stitching.get('seed_event_count', 0)}", f"actions {cognitive_stitching.get('action_count', 0)}"),
        _metric_card("create / extend / merge", f"{cognitive_stitching.get('created_count', 0)} / {cognitive_stitching.get('extended_count', 0)} / {cognitive_stitching.get('merged_count', 0)}", f"reinforced {cognitive_stitching.get('reinforced_count', 0)}"),
        _metric_card("narrative top", str(len(cognitive_stitching.get("narrative_top_items", []) or [])), f"fatigue states {cognitive_stitching.get('pair_fatigue_state_size', 0)}"),
        _metric_card(
            "ESDB",
            f"events {cognitive_stitching.get('esdb_event_count', 0)}",
            f"mat {cognitive_stitching.get('esdb_materialized_event_count', 0)} | delta {cognitive_stitching.get('esdb_delta_entry_total', 0)}",
        ),
        _metric_card(
            "candidate audit",
            f"raw {candidate_audit.get('raw_accepted_count', 0)} | dedup {candidate_audit.get('deduped_candidate_count', 0)}",
            f"rejected {candidate_audit.get('rejected_count', 0)} | pruned {candidate_audit.get('deduped_pruned_count', 0)}",
        ),
        _metric_card(
            "reject reasons",
            " / ".join(f"{k}:{v}" for k, v in rejected_reason_counts.items()) or "-",
            f"replace {candidate_audit.get('replacement_count', 0)} | keep {candidate_audit.get('kept_existing_count', 0)}",
        ),
        _metric_card(
            "score means",
            f"score {f(score_means.get('score', 0.0))} | margin {f(score_means.get('threshold_margin', 0.0))}",
            f"base {f(score_means.get('base_score', 0.0))} | match {f(score_means.get('match_strength', 0.0))} | context {f(score_means.get('context_ratio', 0.0))}",
        ),
    ]
    return _section(
        "cognitive_stitching",
        "认知拼接 / Cognitive Stitching",
        "".join(cards)
        + _table("CS candidates", ["action", "source", "source_kind", "target", "target_kind", "match", "context_k", "matched_span", "score", "edge_ratio", "match_strength", "fatigue"], candidate_rows)
        + _table("CS rejected candidates", ["reason", "action", "source", "target", "score", "min_score", "margin", "base_score"], rejection_rows)
        + _table("CS competition", ["outcome", "signature", "action", "incoming", "existing", "source", "target"], competition_rows)
        + _table("CS actions", ["action", "family", "event", "components", "source", "source_kind", "target", "target_kind", "match", "context_k", "matched_span", "score", "absorbed", "fatigue_after"], action_rows)
        + _table("CS narrative top", ["display", "ref_id", "ER", "EV", "CP", "grasp", "salience", "components", "es_depth", "delta", "mat", "upd"], narrative_rows),
    )


def _render_attention_section(attention: dict) -> str:
    rows = [
        [
            index,
            item.get("ref_object_type", ""),
            item.get("display", ""),
            item.get("ref_object_id", ""),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            f(item.get("cp_abs", 0.0)),
            f(item.get("fatigue", 0.0)),
            f(item.get("recency_gain", 0.0)),
        ]
        for index, item in enumerate(attention.get("top_items", []), start=1)
    ]
    cards = [
        _metric_card("Top-N 对象", str(attention.get("top_item_count", 0)), "当前注意力占位集合"),
        _metric_card("结构对象 ST", str(len(attention.get("structure_items", []))), "进入结构级查存的主要候选"),
    ]
    return _section(
        "attention",
        "Top-N 占位注意力 / Top-N Attention Stub",
        "".join(cards)
        + _table("注意力对象", ["排名", "类型", "内容", "引用 ID", "ER", "EV", "CP", "疲劳", "近因"], rows),
    )


def _render_structure_section(structure_level: dict) -> str:
    data = structure_level.get("result", {})
    debug = data.get("debug", {})
    cam_rows = [
        [
            item.get("structure_id", ""),
            item.get("display_text", ""),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            f(item.get("total_energy", 0.0)),
            f(item.get("base_weight", 1.0)),
            f(item.get("recent_gain", 1.0)),
            f(item.get("fatigue", 0.0)),
        ]
        for item in debug.get("cam_items", [])
    ]
    round_blocks = []
    for round_detail in debug.get("round_details", []):
        candidate_rows = [
            [
                group.get("group_id", ""),
                _structure_refs(group.get("required_structures", [])),
                _structure_refs(group.get("bias_structures", [])) or "无",
                f(group.get("similarity", 0.0)),
                f(group.get("runtime_weight", 0.0)),
                f(group.get("score", 0.0)),
            ]
            for group in round_detail.get("candidate_groups", [])[:12]
        ]
        fragment_rows = [
            [fragment.get("fragment_id", ""), fragment.get("display_text", ""), f(fragment.get("energy_hint", 0.0))]
            for fragment in round_detail.get("internal_fragments", [])[:12]
        ]
        selected = round_detail.get("selected_group") or {}
        round_blocks.append(
            "<details class='round' open>"
            f"<summary>轮次 {round_detail.get('round_index', 0)} | budget_before {e(str(round_detail.get('budget_before', {})))}</summary>"
            f"<div class='round-note'>命中结构组: {e(selected.get('group_id', '无'))} | 预算后 {e(str(round_detail.get('budget_after', {})))}</div>"
            + _table("候选结构组", ["组 ID", "required", "bias", "similarity", "runtime", "score"], candidate_rows)
            + _table("内源残差片段", ["片段 ID", "内容", "energy_hint"], fragment_rows)
            + "</details>"
        )
    new_group_rows = [
        [
            group.get("group_id", ""),
            _structure_refs(group.get("required_structures", [])),
            _structure_refs(group.get("bias_structures", [])) or "无",
            e(str(group.get("avg_energy_profile", {}))),
        ]
        for group in debug.get("new_group_details", [])
    ]
    cards = [
        _metric_card("CAM 结构数", str(data.get("cam_stub_count", 0)), "本轮结构级输入"),
        _metric_card("轮次", str(data.get("round_count", 0)), f"fallback {yn(data.get('fallback_used', False))}"),
        _metric_card("命中组", str(len(data.get("matched_group_ids", []))), ", ".join(data.get("matched_group_ids", [])[:6])),
        _metric_card("新建组", str(len(data.get("new_group_ids", []))), ", ".join(data.get("new_group_ids", [])[:6])),
    ]
    return _section(
        "structure",
        "结构级查存一体 / Structure-level Retrieval-Storage",
        "".join(cards)
        + _table("当前 CAM 结构", ["结构 ID", "内容", "ER", "EV", "Total", "W", "G", "F"], cam_rows)
        + "".join(round_blocks)
        + _table("本轮新建结构组", ["组 ID", "required", "bias", "avg_profile"], new_group_rows),
    )


def _render_stimulus_section(stimulus_level: dict, merged_stimulus: dict) -> str:
    data = stimulus_level.get("result", {})
    debug = data.get("debug", {})
    group_rows = [
        [
            f"G{group.get('group_index', 0)}",
            group.get("source_type", ""),
            group.get("display_text", ""),
            " / ".join(group.get("tokens", [])),
            group.get("sa_count", 0),
            group.get("csa_count", 0),
            " ; ".join(group.get("csa_bundles", [])),
        ]
        for group in merged_stimulus.get("groups", [])
    ]
    round_blocks = []
    for round_detail in debug.get("round_details", []):
        candidate_rows = [
            [
                candidate.get("structure_id", ""),
                candidate.get("display_text", ""),
                f(candidate.get("match_score", 0.0)),
                f(candidate.get("runtime_weight", 0.0)),
                yn(candidate.get("exact_match", False)),
                candidate.get("common_part", {}).get("common_display", ""),
                candidate.get("common_part", {}).get("residual_existing_signature", "") or "无",
                candidate.get("common_part", {}).get("residual_incoming_signature", "") or "无",
            ]
            for candidate in round_detail.get("candidate_details", [])[:12]
        ]
        selected = round_detail.get("selected_match") or {}
        common = round_detail.get("created_common_structure") or {}
        residual = round_detail.get("created_residual_structure") or {}
        fresh = round_detail.get("created_fresh_structure") or {}
        round_blocks.append(
            "<details class='round' open>"
            f"<summary>轮次 {round_detail.get('round_index', 0)} | remaining {e(''.join(round_detail.get('remaining_tokens_before', [])))} | lookup {e(round_detail.get('candidate_lookup_source', ''))}</summary>"
            f"<div class='round-note'>命中最大结构: {e(selected.get('structure_id', '无'))} | 剩余刺激: {e(''.join(round_detail.get('remaining_tokens_after', [])) or '无')}</div>"
            + _table("候选结构", ["结构 ID", "内容", "score", "runtime", "exact", "common", "res_existing", "res_incoming"], candidate_rows)
            + _inline_notes(
                [
                    f"support_er={f(round_detail.get('support_er', 0.0))}",
                    f"support_ev={f(round_detail.get('support_ev', 0.0))}",
                    f"共同结构={common.get('structure_id', '')}[{common.get('display_text', '')}]" if common else "共同结构=无",
                    f"残差结构={residual.get('structure_id', '')}[{residual.get('display_text', '')}]" if residual else "残差结构=无",
                    f"新建结构={fresh.get('structure_id', '')}[{fresh.get('display_text', '')}]" if fresh else "新建结构=无",
                ]
            )
            + "</details>"
        )
    cards = [
        _metric_card("完整刺激", merged_stimulus.get("display_text", ""), "当前外源 + 内源整合结果"),
        _metric_card("总 ER / EV", f"{f(merged_stimulus.get('total_er', 0.0))} / {f(merged_stimulus.get('total_ev', 0.0))}", "完整刺激能量"),
        _metric_card("轮次", str(data.get("round_count", 0)), f"fallback {yn(data.get('fallback_used', False))}"),
        _metric_card("结构命中 / 新建", f"{len(data.get('matched_structure_ids', []))} / {len(data.get('new_structure_ids', []))}", "刺激级查存结果"),
    ]
    return _section(
        "stimulus",
        "完整刺激展示 + 刺激级查存一体 / Full Stimulus + Stimulus-level Retrieval-Storage",
        "".join(cards)
        + _table("完整刺激分组", ["组", "来源", "文本", "tokens", "SA"], group_rows)
        + "".join(round_blocks),
    )


def _render_projection_section_legacy(pool_apply: dict) -> str:
    apply_result = pool_apply.get("apply_result", {})
    priority_summary = pool_apply.get("priority_summary", {})
    input_packet = pool_apply.get("input_packet", {})
    residual_packet = pool_apply.get("residual_packet", {})
    event_rows = [
        [event.get("event_type", ""), f"{event.get('target_item_id', '')}[{event.get('target_display', '')}]", event.get("reason", "")]
        for event in pool_apply.get("events", [])[:20]
    ]
    priority_rows = [
        [
            event.get("target_display", "") or event.get("target_item_id", ""),
            event.get("matched_structure_signature", "") or "—",
            " / ".join(str(token) for token in (event.get("extra_context", {}) or {}).get("matched_tokens", []) if token) or "—",
            f"{(event.get('extra_context', {}) or {}).get('consumed_energy_key', 'energy')}:{f((event.get('extra_context', {}) or {}).get('consumed_amount', 0.0))}",
            event.get("reason", ""),
        ]
        for event in pool_apply.get("priority_events", [])[:20]
    ]
    packet_rows = [
        [
            "input",
            input_packet.get("display_text", ""),
            f(input_packet.get("total_er", 0.0)),
            f(input_packet.get("total_ev", 0.0)),
            len(input_packet.get("flat_tokens", [])),
        ],
        [
            "residual",
            residual_packet.get("display_text", ""),
            f(residual_packet.get("total_er", 0.0)),
            f(residual_packet.get("total_ev", 0.0)),
            len(residual_packet.get("flat_tokens", [])),
        ],
        [
            "consumed",
            "priority neutralization",
            f(priority_summary.get("consumed_er", 0.0)),
            f(priority_summary.get("consumed_ev", 0.0)),
            max(0, int(priority_summary.get("input_flat_token_count", 0)) - int(priority_summary.get("residual_flat_token_count", 0))),
        ],
    ]
    bias_rows = [
        [item.get("structure_id", ""), item.get("display_text", ""), f(item.get("er", 0.0)), f(item.get("ev", 0.0)), item.get("result", "")]
        for item in pool_apply.get("bias_projection", [])
    ]
    runtime_rows = [
        [item.get("structure_id", ""), item.get("display_text", ""), item.get("reason", ""), f(item.get("er", 0.0)), f(item.get("ev", 0.0)), item.get("result", "")]
        for item in pool_apply.get("runtime_projection", [])
    ]
    cards = [
        _metric_card("new / update", f"{apply_result.get('new_item_count', 0)} / {apply_result.get('updated_item_count', 0)}", "完整刺激入池结果"),
        _metric_card("merge / neutralize", f"{apply_result.get('merged_item_count', 0)} / {apply_result.get('neutralized_item_count', 0)}", "状态池阶段性整理"),
    ]
    return _section(
        "projection",
        "完整刺激入池 + 结构投影 / State Pool Apply + Structure Projection",
        "".join(cards)
        + _table("入池事件", ["事件", "目标", "原因"], event_rows)
        + _table("结构级偏置投影", ["结构 ID", "内容", "ER", "EV", "结果"], bias_rows)
        + _table("刺激级运行时结构投影", ["结构 ID", "内容", "原因", "ER", "EV", "结果"], runtime_rows),
    )


def _render_projection_section(pool_apply: dict) -> str:
    apply_result = pool_apply.get("apply_result", {})
    priority_summary = pool_apply.get("priority_summary", {})
    input_packet = pool_apply.get("input_packet", {})
    residual_packet = pool_apply.get("residual_packet", {})
    priority_events = pool_apply.get("priority_events", [])

    event_rows = [
        [event.get("event_type", ""), f"{event.get('target_item_id', '')}[{event.get('target_display', '')}]", event.get("reason", "")]
        for event in pool_apply.get("events", [])[:20]
    ]
    priority_rows = [
        [
            event.get("target_display", "") or event.get("target_item_id", ""),
            event.get("matched_structure_signature", "") or "—",
            " / ".join(str(token) for token in (event.get("extra_context", {}) or {}).get("matched_tokens", []) if token) or "—",
            f"{(event.get('extra_context', {}) or {}).get('consumed_energy_key', 'energy')}:{f((event.get('extra_context', {}) or {}).get('consumed_amount', 0.0))}",
            event.get("reason", ""),
        ]
        for event in priority_events[:20]
    ]
    packet_rows = [
        ["input", input_packet.get("display_text", ""), f(input_packet.get("total_er", 0.0)), f(input_packet.get("total_ev", 0.0)), len(input_packet.get("flat_tokens", []))],
        ["residual", residual_packet.get("display_text", ""), f(residual_packet.get("total_er", 0.0)), f(residual_packet.get("total_ev", 0.0)), len(residual_packet.get("flat_tokens", []))],
        [
            "consumed",
            "priority neutralization",
            f(priority_summary.get("consumed_er", 0.0)),
            f(priority_summary.get("consumed_ev", 0.0)),
            max(0, int(priority_summary.get("input_flat_token_count", 0)) - int(priority_summary.get("residual_flat_token_count", 0))),
        ],
    ]
    bias_rows = [
        [item.get("structure_id", ""), item.get("display_text", ""), f(item.get("er", 0.0)), f(item.get("ev", 0.0)), item.get("result", "")]
        for item in pool_apply.get("bias_projection", [])
    ]
    runtime_rows = [
        [item.get("structure_id", ""), item.get("display_text", ""), item.get("reason", ""), f(item.get("er", 0.0)), f(item.get("ev", 0.0)), item.get("result", "")]
        for item in pool_apply.get("runtime_projection", [])
    ]
    cards = [
        _metric_card("priority neutralize", str(priority_summary.get("priority_neutralized_item_count", apply_result.get("priority_neutralized_item_count", 0))), f"events {priority_summary.get('priority_event_count', len(priority_events))}"),
        _metric_card("packet delta", f"ER {f(priority_summary.get('consumed_er', 0.0))} / EV {f(priority_summary.get('consumed_ev', 0.0))}", f"tokens {priority_summary.get('input_flat_token_count', 0)} -> {priority_summary.get('residual_flat_token_count', 0)}"),
        _metric_card("new / update", f"{apply_result.get('new_item_count', 0)} / {apply_result.get('updated_item_count', 0)}", "完整刺激入池结果"),
        _metric_card("merge / neutralize", f"{apply_result.get('merged_item_count', 0)} / {apply_result.get('neutralized_item_count', 0)}", "状态池阶段性整理"),
    ]
    return _section(
        "projection",
        "完整刺激入池 + 结构投影 / State Pool Apply + Structure Projection",
        "".join(cards)
        + _table("priority neutralization packet delta", ["stage", "display", "ER", "EV", "tokens"], packet_rows)
        + _table("priority neutralization events", ["target", "matched_signature", "matched_tokens", "consumed", "reason"], priority_rows)
        + _table("入池事件", ["事件", "目标", "原因"], event_rows)
        + _table("结构级偏置投影", ["结构 ID", "内容", "ER", "EV", "结果"], bias_rows)
        + _table("刺激级运行时结构投影", ["结构 ID", "内容", "原因", "ER", "EV", "结果"], runtime_rows),
    )


def _render_induction_section(induction: dict) -> str:
    data = induction.get("result", {})
    debug = data.get("debug", {})
    source_blocks = []
    for source in debug.get("source_details", []):
        rows = [
            [
                entry.get("mode", ""),
                entry.get("target_structure_id", ""),
                entry.get("target_display_text", ""),
                f(entry.get("delta_ev", 0.0)),
                f(entry.get("runtime_weight", 0.0)),
                f(entry.get("base_weight", 1.0)),
                f(entry.get("recent_gain", 1.0)),
                f(entry.get("fatigue", 0.0)),
            ]
            for entry in source.get("candidate_entries", [])[:16]
        ]
        source_blocks.append(
            "<details class='round' open>"
            f"<summary>{e(source.get('source_structure_id', ''))}[{e(source.get('display_text', ''))}] | er {f(source.get('source_er', 0.0))} | ev {f(source.get('source_ev', 0.0))}</summary>"
            + _table("赋能路径", ["模式", "目标 ID", "目标内容", "delta_ev", "runtime", "W", "G", "F"], rows)
            + "</details>"
        )
    applied_rows = [
        [item.get("structure_id", ""), item.get("display_text", ""), f(item.get("ev", 0.0)), item.get("result", "")]
        for item in induction.get("applied_targets", [])
    ]
    cards = [
        _metric_card("感应源对象", str(data.get("source_item_count", 0)), "参与感应赋能的运行态起点"),
        _metric_card("传播 / 诱发", f"{data.get('propagated_target_count', 0)} / {data.get('induced_target_count', 0)}", "目标命中次数"),
        _metric_card("total_delta_ev", f(data.get("total_delta_ev", 0.0)), "赋能总增量"),
        _metric_card("ev 消耗", f(data.get("total_ev_consumed", 0.0)), "虚能量传播预算"),
    ]
    return _section(
        "induction",
        "感应赋能 / Induction Propagation",
        "".join(cards) + "".join(source_blocks) + _table("已回写目标结构", ["结构 ID", "内容", "delta_ev", "结果"], applied_rows),
    )


def _local_modulation_text(local_mod: dict | None) -> str:
    local_mod = dict(local_mod or {}) if isinstance(local_mod, dict) else {}
    if not local_mod:
        return "无"
    detail = local_mod.get("detail", {}) if isinstance(local_mod.get("detail", {}), dict) else {}
    reason = str(detail.get("reason", "") or "").strip().lower()
    status = str(local_mod.get("lookup_status", "") or "").strip().lower()
    if not status:
        if bool(local_mod.get("lookup_hit", False)):
            status = "hit"
        elif reason == "local_feedback_not_found":
            status = "miss"
        else:
            status = "skipped"
    if status == "hit":
        return (
            f"命中 reward {f(local_mod.get('reward', 0.0))} / "
            f"punish {f(local_mod.get('punish', 0.0))} / "
            f"scale {f(local_mod.get('scale_clamped', 1.0))}"
        )
    if status == "miss":
        return "未命中反馈"
    reason_labels = {
        "config_disabled": "全局关闭",
        "node_disabled": "节点关闭",
        "target_required_but_missing": "缺少目标",
        "lookup_target_missing": "无目标可查",
        "non_positive_gain": "gain<=0",
    }
    return f"跳过({reason_labels.get(reason, reason or '未知原因')})"


def _render_action_learning_section(action: dict | None) -> str:
    action = dict(action or {}) if isinstance(action, dict) else {}
    summary = action.get("action_learning_summary", {}) if isinstance(action.get("action_learning_summary", {}), dict) else {}
    nodes = [row for row in (action.get("nodes", []) or []) if isinstance(row, dict)]
    executed = [row for row in (action.get("executed_actions", []) or []) if isinstance(row, dict)]
    if not summary and not nodes and not executed:
        return ""

    cards = [
        _metric_card(
            "人形主路径",
            "开启" if summary.get("humanlike_runtime_sync_enabled", True) else "关闭",
            f"全局信号活跃 {summary.get('runtime_signal_node_active_count', 0)} | 行动节点活跃 {summary.get('runtime_action_node_active_count', 0)}",
        ),
        _metric_card(
            "运行态显影",
            f"{summary.get('runtime_signal_node_count', 0)} / {summary.get('runtime_action_node_count', 0)}",
            f"执行显影 {summary.get('runtime_action_node_executed_count', 0)} | target_ref {summary.get('runtime_action_target_ref_count', 0)} / target_item {summary.get('runtime_action_target_item_count', 0)}",
        ),
        _metric_card("局部塑形开关", "开启" if summary.get("local_drive_modulation_enabled", True) else "关闭", "对象级 reward/punish 是否参与本轮 drive"),
        _metric_card(
            "目标 / 命中",
            f"{summary.get('targeted_node_count', 0)} / {summary.get('local_lookup_hit_count', 0)}",
            f"text_fallback {summary.get('local_lookup_text_fallback_hit_count', 0)} | miss {summary.get('local_lookup_miss_count', 0)} | skipped {summary.get('local_lookup_skipped_count', 0)}",
        ),
        _metric_card(
            "目标缺失 / 关闭",
            f"{summary.get('local_target_missing_count', 0)} / {summary.get('local_modulation_disabled_count', 0)}",
            f"modulated {summary.get('local_modulated_node_count', 0)}",
        ),
        _metric_card(
            "奖励 / 惩罚",
            f"{f(summary.get('local_reward_drive_bonus_total', 0.0))} / {f(summary.get('local_punish_drive_penalty_total', 0.0))}",
            f"scale_mean {f(summary.get('local_drive_scale_mean', 1.0))}",
        ),
    ]
    example_rows = [
        [
            item.get("action_kind", ""),
            item.get("action_id", ""),
            item.get("target_display", "") or item.get("target_ref_object_id", "") or item.get("target_item_id", ""),
            f(item.get("reward", 0.0)),
            f(item.get("punish", 0.0)),
            f(item.get("scale_clamped", 1.0)),
            f(item.get("reward_bonus_gain", 0.0)),
            f(item.get("punish_penalty_gain", 0.0)),
        ]
        for item in (summary.get("examples", []) or [])[:8]
        if isinstance(item, dict)
    ]
    node_rows = [
        [
            row.get("action_kind", ""),
            row.get("action_id", ""),
            row.get("target_display", "") or row.get("target_ref_object_id", "") or row.get("target_item_id", ""),
            f(row.get("drive", 0.0)),
            f(row.get("tick_consumed_drive_total", row.get("last_consumed_drive", 0.0))),
            f(row.get("effective_threshold", row.get("threshold", 0.0))),
            _local_modulation_text(row.get("local_drive_modulation", {})),
        ]
        for row in nodes[:12]
    ]
    executed_rows = [
        [
            row.get("action_kind", ""),
            row.get("action_id", ""),
            row.get("target_display", "") or row.get("target_ref_object_id", "") or row.get("target_item_id", ""),
            yn(row.get("success", False)),
            yn(row.get("attempted", True)),
            f(row.get("consumed_drive", row.get("last_consumed_drive", 0.0))),
            _local_modulation_text(row.get("local_drive_modulation", {})),
        ]
        for row in executed[:12]
    ]
    block = (
        "<section class='subpanel'>"
        "<h4>行动学习摘要 / Action Learning Summary</h4>"
        + "".join(cards)
        + "</section>"
    )
    if example_rows:
        block += _table(
            "局部塑形样例 / Local modulation examples",
            ["action_kind", "action_id", "目标动作 / Action target", "reward", "punish", "scale", "reward_gain", "punish_cost"],
            example_rows,
        )
    if node_rows:
        block += _table(
            "当前行动节点 / Current action nodes",
            ["kind", "action_id", "target", "drive", "tick_consumed", "effective_threshold", "local_modulation"],
            node_rows,
        )
    if executed_rows:
        block += _table(
            "最近执行行动 / Recent executed actions",
            ["kind", "action_id", "target", "success", "attempted", "consumed_drive", "local_modulation"],
            executed_rows,
        )
    return block


def _render_final_section(final_state: dict, action: dict | None = None) -> str:
    state_snapshot = final_state.get("state_snapshot", {})
    energy_summary = final_state.get("state_energy_summary", {})
    hdb_snapshot = final_state.get("hdb_snapshot", {})
    item_rows = [
        [
            index,
            item.get("ref_object_type", ""),
            item.get("display", ""),
            item.get("ref_object_id", ""),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            f(item.get("cp_abs", 0.0)),
            f(item.get("fatigue", 0.0)),
            f(item.get("recency_gain", 0.0)),
        ]
        for index, item in enumerate(state_snapshot.get("top_items", []), start=1)
    ]
    energy_rows = [
        [ref_type, payload.get("count", 0), f(payload.get("total_er", 0.0)), f(payload.get("total_ev", 0.0)), f(payload.get("total_cp", 0.0))]
        for ref_type, payload in energy_summary.get("energy_by_type", {}).items()
    ]
    recent_structure_rows = [
        [item.get("structure_id", ""), item.get("display_text", ""), item.get("signature", ""), f(item.get("base_weight", 1.0)), f(item.get("recent_gain", 1.0)), f(item.get("fatigue", 0.0))]
        for item in hdb_snapshot.get("recent_structures", [])
    ]
    cards = [
        _metric_card("状态池对象", str(state_snapshot.get("summary", {}).get("active_item_count", 0)), "最终运行态规模"),
        _metric_card("总 ER / EV / CP", f"{f(energy_summary.get('total_er', 0.0))} / {f(energy_summary.get('total_ev', 0.0))} / {f(energy_summary.get('total_cp', 0.0))}", "状态池总能量"),
        _metric_card("HDB 结构 / 组", f"{hdb_snapshot.get('summary', {}).get('structure_count', 0)} / {hdb_snapshot.get('summary', {}).get('group_count', 0)}", f"EM {hdb_snapshot.get('summary', {}).get('episodic_count', 0)}"),
        _metric_card("issue / repair", f"{hdb_snapshot.get('summary', {}).get('issue_count', 0)} / {hdb_snapshot.get('summary', {}).get('active_repair_job_count', 0)}", "当前问题与修复任务"),
    ]
    return _section(
        "final",
        "最终状态池 + HDB 摘要 / Final State Pool + HDB Snapshot",
        "".join(cards)
        + _render_action_learning_section(action)
        + _table("分类型能量", ["类型", "count", "total_er", "total_ev", "total_cp"], energy_rows)
        + _table("最终状态池对象", ["排名", "类型", "内容", "引用 ID", "ER", "EV", "CP", "疲劳", "近因"], item_rows)
        + _table("最近结构", ["结构 ID", "内容", "signature", "W", "G", "F"], recent_structure_rows),
    )


def _section(section_id: str, title: str, content: str) -> str:
    return f"<section id='{section_id}' class='panel'><header class='section-head'><h3>{e(title)}</h3></header>{content}</section>"


def _metric_card(title: str, value: str, note: str = "") -> str:
    return (
        "<article class='metric'>"
        f"<div class='metric-title'>{e(title)}</div>"
        f"<div class='metric-value'>{e(value)}</div>"
        f"<div class='metric-note'>{e(note)}</div>"
        "</article>"
    )


def _table(title: str, headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return (
            "<section class='subpanel'>"
            f"<h4>{e(title)}</h4>"
            "<div class='empty'>当前没有可展示数据</div>"
            "</section>"
        )
    head = "".join(f"<th>{e(header)}</th>" for header in headers)
    body = []
    for row in rows:
        body.append("<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>")
    return (
        "<section class='subpanel'>"
        f"<h4>{e(title)}</h4>"
        "<div class='table-wrap'><table>"
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div></section>"
    )


def _inline_notes(items: list[str]) -> str:
    chips = "".join(f"<span class='chip'>{e(item)}</span>" for item in items if item)
    return f"<div class='chips'>{chips}</div>"


def _structure_refs(items: list[dict]) -> str:
    return ", ".join(
        f"{item.get('structure_id', '')}[{item.get('display_text', '')}]"
        for item in items or []
        if isinstance(item, dict)
    )


def e(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


def f(value: object) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def yn(value: object) -> str:
    return "是" if bool(value) else "否"


def export_cycle_html(report: dict, html_path: str | Path) -> str:
    target = Path(html_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    sections = [
        _render_sensor_section(report.get("sensor", {})),
        _render_maintenance_section(report.get("maintenance", {})),
        _render_cognitive_stitching_section(report.get("cognitive_stitching", {})),
        _render_attention_section(report.get("attention", {})),
        _render_structure_section(report.get("structure_level", {})),
        _render_cache_section(report.get("cache_neutralization", {})),
        _render_stimulus_section(report.get("stimulus_level", {}), report.get("merged_stimulus", {})),
        _render_projection_section(report.get("pool_apply", {})),
        _render_induction_section(report.get("induction", {})),
        _render_cognitive_feeling_section(report.get("cognitive_feeling", {})),
        _render_emotion_section(report.get("emotion", {})),
        _render_innate_script_section(report.get("innate_script", {})),
        _render_final_section(report.get("final_state", {}), report.get("action", {})),
    ]

    page = [
        "<!doctype html>",
        "<html lang='zh-CN'>",
        "<head>",
        "<meta charset='utf-8' />",
        "<meta name='viewport' content='width=device-width, initial-scale=1' />",
        f"<title>AP 研究观测报告 {e(report.get('trace_id', ''))}</title>",
        "<style>",
        _CSS,
        "</style>",
        "</head>",
        "<body>",
        _render_shell(report),
        "<main class='layout'>",
        _render_overview(report),
        "".join(sections),
        "</main>",
        "</body>",
        "</html>",
    ]
    target.write_text("".join(page), encoding="utf-8")
    return str(target)


def _render_shell(report: dict) -> str:
    return (
        "<aside class='shell'>"
        "<div class='brand'>"
        "<div class='eyebrow'>Artificial PsyArch</div>"
        "<h1>研究观测台</h1>"
        f"<p>轮次 {e(report.get('trace_id', ''))}</p>"
        "</div>"
        "<nav class='nav'>"
        "<a href='#overview'>总览</a>"
        "<a href='#sensor'>文本感受器</a>"
        "<a href='#maintenance'>状态池维护</a>"
        "<a href='#attention'>记忆体形成</a>"
        "<a href='#structure'>结构级查存</a>"
        "<a href='#cache'>缓存中和</a>"
        "<a href='#stimulus'>刺激级查存</a>"
        "<a href='#projection'>状态池回写</a>"
        "<a href='#induction'>感应赋能</a>"
        "<a href='#cfs'>认知感受</a>"
        "<a href='#emotion'>情绪递质</a>"
        "<a href='#innate_script'>先天脚本</a>"
        "<a href='#final'>最终状态</a>"
        "</nav>"
        "</aside>"
    )


def _render_structure_section(structure_level: dict) -> str:
    data = structure_level.get("result", {})
    debug = data.get("debug", {})
    cam_rows = [
        [
            item.get("structure_id", ""),
            item.get("display_text", ""),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            f(item.get("total_energy", 0.0)),
            f(item.get("base_weight", 1.0)),
            f(item.get("recent_gain", 1.0)),
            f(item.get("fatigue", 0.0)),
        ]
        for item in debug.get("cam_items", [])
    ]
    round_blocks = []
    for round_detail in debug.get("round_details", []):
        candidate_rows = [
            [
                group.get("group_id", ""),
                _structure_refs(group.get("required_structures", [])),
                _structure_refs(group.get("bias_structures", [])) or "无",
                yn(group.get("eligible", False)),
                f(group.get("score", 0.0)),
                f(group.get("base_similarity", 0.0)),
                f(group.get("coverage_ratio", 0.0)),
                f(group.get("structure_ratio", 0.0)),
                f(group.get("wave_similarity", 0.0)),
                f(group.get("path_strength", 0.0)),
                f(group.get("runtime_weight", 0.0)),
                f(group.get("base_weight", 0.0)),
                f(group.get("recent_gain", 0.0)),
                f(group.get("fatigue", 0.0)),
                group.get("chain_depth", 0),
                f"{group.get('owner_kind', '')}/{group.get('owner_id', '')}",
                _common_part_summary(group.get("common_part", {})),
            ]
            for group in round_detail.get("candidate_groups", [])[:12]
        ]
        fragment_rows = [
            [fragment.get("fragment_id", ""), fragment.get("display_text", ""), f(fragment.get("energy_hint", 0.0))]
            for fragment in round_detail.get("internal_fragments", [])[:12]
        ]
        selected = round_detail.get("selected_group") or {}
        round_blocks.append(
            "<details class='round' open>"
            f"<summary>轮次 {round_detail.get('round_index', 0)} | budget_before {e(str(round_detail.get('budget_before', {})))}</summary>"
            f"<div class='round-note'>命中结构组 {e(selected.get('group_id', '无'))} | common {e(_common_part_summary(selected.get('common_part', {})))} | budget_after {e(str(round_detail.get('budget_after', {})))}</div>"
            + _inline_notes(
                [
                    f"chain_steps={_chain_summary(round_detail.get('chain_steps', []), 'structure')}",
                    f"storage={_storage_summary(round_detail.get('storage_summary', {}))}",
                ]
            )
            + _table(
                "候选结构组",
                ["组ID", "required", "bias", "eligible", "score", "base", "coverage", "structure", "wave", "path", "runtime", "W", "G", "F", "depth", "owner", "common"],
                candidate_rows,
            )
            + _table("内源片段", ["片段ID", "内容", "energy_hint"], fragment_rows)
            + "</details>"
        )
    new_group_rows = [
        [
            group.get("group_id", ""),
            _structure_refs(group.get("required_structures", [])),
            _structure_refs(group.get("bias_structures", [])) or "无",
            e(str(group.get("avg_energy_profile", {}))),
        ]
        for group in debug.get("new_group_details", [])
    ]
    cards = [
        _metric_card("CAM 结构数", str(data.get("cam_stub_count", 0)), "本轮进入结构级的 ST"),
        _metric_card("轮次", str(data.get("round_count", 0)), f"fallback {yn(data.get('fallback_used', False))}"),
        _metric_card("命中结构组", str(len(data.get("matched_group_ids", []))), ", ".join(data.get("matched_group_ids", [])[:6])),
        _metric_card("新建结构组", str(len(data.get("new_group_ids", []))), ", ".join(data.get("new_group_ids", [])[:6])),
    ]
    return _section(
        "structure",
        "结构级查存一体 / Structure-level Retrieval-Storage",
        "".join(cards)
        + _table("当前 CAM 结构", ["结构 ID", "内容", "ER", "EV", "Total", "W", "G", "F"], cam_rows)
        + "".join(round_blocks)
        + _table("本轮新建结构组", ["组ID", "required", "bias", "avg_profile"], new_group_rows),
    )


def _render_cache_section(cache_neutralization: dict) -> str:
    summary = cache_neutralization.get("priority_summary", {})
    input_packet = cache_neutralization.get("input_packet", {})
    residual_packet = cache_neutralization.get("residual_packet", {})
    event_rows = [
        [
            event.get("target_display", "") or event.get("target_item_id", ""),
            event.get("matched_structure_signature", "") or "—",
            " / ".join(str(token) for token in (event.get("extra_context", {}) or {}).get("matched_tokens", []) if token) or "—",
            f"{(event.get('extra_context', {}) or {}).get('consumed_energy_key', 'energy')}:{f((event.get('extra_context', {}) or {}).get('consumed_amount', 0.0))}",
            event.get("reason", ""),
        ]
        for event in cache_neutralization.get("priority_events", [])[:20]
    ]
    packet_rows = [
        ["input", input_packet.get("display_text", ""), f(input_packet.get("total_er", 0.0)), f(input_packet.get("total_ev", 0.0)), len(input_packet.get("flat_tokens", []))],
        ["residual", residual_packet.get("display_text", ""), f(residual_packet.get("total_er", 0.0)), f(residual_packet.get("total_ev", 0.0)), len(residual_packet.get("flat_tokens", []))],
        ["consumed", "priority neutralization", f(summary.get("consumed_er", 0.0)), f(summary.get("consumed_ev", 0.0)), max(0, int(summary.get("input_flat_token_count", 0)) - int(summary.get("residual_flat_token_count", 0)))],
    ]
    cards = [
        _metric_card("缓存中和", str(summary.get("priority_neutralized_item_count", 0)), f"events {summary.get('priority_event_count', 0)}"),
        _metric_card("packet delta", f"ER {f(summary.get('consumed_er', 0.0))} / EV {f(summary.get('consumed_ev', 0.0))}", f"tokens {summary.get('input_flat_token_count', len(input_packet.get('flat_tokens', [])))} -> {summary.get('residual_flat_token_count', len(residual_packet.get('flat_tokens', [])))}"),
        _metric_card("input", input_packet.get("display_text", "") or "空", f"ER {f(input_packet.get('total_er', 0.0))} / EV {f(input_packet.get('total_ev', 0.0))}"),
        _metric_card("residual", residual_packet.get("display_text", "") or "空", f"ER {f(residual_packet.get('total_er', 0.0))} / EV {f(residual_packet.get('total_ev', 0.0))}"),
    ]
    return _section(
        "cache",
        "缓存中和 / Cache Neutralization",
        "".join(cards)
        + _table("priority neutralization packet delta", ["stage", "display", "ER", "EV", "tokens"], packet_rows)
        + _table("priority neutralization events", ["target", "matched_signature", "matched_tokens", "consumed", "reason"], event_rows),
    )


def _render_stimulus_section(stimulus_level: dict, merged_stimulus: dict) -> str:
    data = stimulus_level.get("result", {})
    debug = data.get("debug", {})
    group_rows = [
        [
            f"G{group.get('group_index', 0)}",
            group.get("source_type", ""),
            group.get("display_text", ""),
            " / ".join(group.get("tokens", [])),
            group.get("sa_count", 0),
            group.get("csa_count", 0),
            " ; ".join(group.get("csa_bundles", [])),
        ]
        for group in merged_stimulus.get("groups", [])
    ]
    round_blocks = []
    for round_detail in debug.get("round_details", []):
        candidate_rows = [
            [
                candidate.get("structure_id", ""),
                candidate.get("display_text", ""),
                yn(candidate.get("exact_match", False)),
                yn(candidate.get("full_structure_included", False)),
                f(candidate.get("match_score", 0.0)),
                f(candidate.get("coverage_ratio", 0.0)),
                f(candidate.get("structure_match_ratio", 0.0)),
                f(candidate.get("runtime_weight", 0.0)),
                f(candidate.get("entry_runtime_weight", 0.0)),
                candidate.get("chain_depth", 0),
                candidate.get("owner_structure_id", "") or candidate.get("parent_structure_id", ""),
                candidate.get("common_part", {}).get("common_display", ""),
                candidate.get("common_part", {}).get("residual_existing_signature", "") or "无",
                candidate.get("common_part", {}).get("residual_incoming_signature", "") or "无",
            ]
            for candidate in round_detail.get("candidate_details", [])[:12]
        ]
        selected = round_detail.get("selected_match") or {}
        common = round_detail.get("created_common_structure") or {}
        residual = round_detail.get("created_residual_structure") or {}
        fresh = round_detail.get("created_fresh_structure") or {}
        round_blocks.append(
            "<details class='round' open>"
            f"<summary>轮次 {round_detail.get('round_index', 0)} | remaining {e(''.join(round_detail.get('remaining_tokens_before', [])))} | lookup {e(round_detail.get('candidate_lookup_source', ''))}</summary>"
            f"<div class='round-note'>命中最大结构 {e(selected.get('structure_id', '无'))} | 剩余刺激: {e(''.join(round_detail.get('remaining_tokens_after', [])) or '无')}</div>"
            + _inline_notes(
                [
                    f"chain_steps={_chain_summary(round_detail.get('chain_steps', []), 'stimulus')}",
                    f"support_er={f(round_detail.get('support_er', 0.0))}",
                    f"support_ev={f(round_detail.get('support_ev', 0.0))}",
                    f"共同结构={common.get('structure_id', '')}[{common.get('display_text', '')}]" if common else "共同结构=无",
                    f"残差结构={residual.get('structure_id', '')}[{residual.get('display_text', '')}]" if residual else "残差结构=无",
                    f"新建结构={fresh.get('structure_id', '')}[{fresh.get('display_text', '')}]" if fresh else "新建结构=无",
                ]
            )
            + _table("候选结构", ["结构 ID", "内容", "exact", "full", "score", "coverage", "structure", "runtime", "entry_runtime", "depth", "owner", "common", "res_existing", "res_incoming"], candidate_rows)
            + "</details>"
        )
    cards = [
        _metric_card("完整刺激", merged_stimulus.get("display_text", ""), "当前外源 + 内源整合结果"),
        _metric_card("总 ER / EV", f"{f(merged_stimulus.get('total_er', 0.0))} / {f(merged_stimulus.get('total_ev', 0.0))}", "完整刺激能量"),
        _metric_card("轮次", str(data.get("round_count", 0)), f"fallback {yn(data.get('fallback_used', False))}"),
        _metric_card("结构命中 / 新建", f"{len(data.get('matched_structure_ids', []))} / {len(data.get('new_structure_ids', []))}", "刺激级查存结果"),
    ]
    return _section(
        "stimulus",
        "刺激级查存一体 / Stimulus-level Retrieval-Storage",
        "".join(cards)
        + _table("完整刺激分组", ["组", "来源", "文本", "tokens", "SA", "CSA", "bundles"], group_rows)
        + "".join(round_blocks),
    )


def _render_projection_section(pool_apply: dict) -> str:
    apply_result = pool_apply.get("apply_result", {})
    event_rows = [
        [event.get("event_type", ""), f"{event.get('target_item_id', '')}[{event.get('target_display', '')}]", event.get("reason", "")]
        for event in pool_apply.get("events", [])[:20]
    ]
    bias_rows = [
        [item.get("structure_id", ""), item.get("display_text", ""), f(item.get("er", 0.0)), f(item.get("ev", 0.0)), item.get("result", "")]
        for item in pool_apply.get("bias_projection", [])
    ]
    runtime_rows = [
        [item.get("structure_id", ""), item.get("display_text", ""), item.get("reason", ""), f(item.get("er", 0.0)), f(item.get("ev", 0.0)), item.get("result", "")]
        for item in pool_apply.get("runtime_projection", [])
    ]
    cards = [
        _metric_card("new / update", f"{apply_result.get('new_item_count', 0)} / {apply_result.get('updated_item_count', 0)}", "完整刺激入池结果"),
        _metric_card("merge / neutralize", f"{apply_result.get('merged_item_count', 0)} / {apply_result.get('neutralized_item_count', 0)}", "状态池阶段性整理"),
    ]
    return _section(
        "projection",
        "状态池回写 + 结构投影 / State Pool Apply + Structure Projection",
        "".join(cards)
        + _table("入池事件", ["事件", "目标", "原因"], event_rows)
        + _table("结构级偏置投影", ["结构 ID", "内容", "ER", "EV", "结果"], bias_rows)
        + _table("刺激级运行时结构投影", ["结构 ID", "内容", "原因", "ER", "EV", "结果"], runtime_rows),
    )


def _render_induction_section(induction: dict) -> str:
    data = induction.get("result", {})
    debug = data.get("debug", {})
    source_blocks = []
    for source in debug.get("source_details", []):
        rows = [
            [
                entry.get("mode", ""),
                entry.get("target_structure_id", ""),
                entry.get("target_display_text", ""),
                f(entry.get("delta_ev", 0.0)),
                f(entry.get("runtime_weight", 0.0)),
                f(entry.get("normalized_share", 0.0)),
                entry.get("entry_count", 0),
                f(entry.get("base_weight", 1.0)),
                f(entry.get("recent_gain", 1.0)),
                f(entry.get("fatigue", 0.0)),
            ]
            for entry in source.get("candidate_entries", [])[:16]
        ]
        source_blocks.append(
            "<details class='round' open>"
            f"<summary>{e(source.get('source_structure_id', ''))}[{e(source.get('display_text', ''))}] | er {f(source.get('source_er', 0.0))} | ev {f(source.get('source_ev', 0.0))}</summary>"
            + _table("赋能路径", ["模式", "目标 ID", "目标内容", "delta_ev", "runtime", "share", "entries", "W", "G", "F"], rows)
            + "</details>"
        )
    applied_rows = [
        [item.get("structure_id", ""), item.get("display_text", ""), f(item.get("ev", 0.0)), item.get("result", "")]
        for item in induction.get("applied_targets", [])
    ]
    cards = [
        _metric_card("感应源对象", str(data.get("source_item_count", 0)), "参与感应赋能的运行态起点"),
        _metric_card("传播 / 诱发", f"{data.get('propagated_target_count', 0)} / {data.get('induced_target_count', 0)}", "目标命中次数"),
        _metric_card("total_delta_ev", f(data.get("total_delta_ev", 0.0)), "赋能总增量"),
        _metric_card("ev 消耗", f(data.get("total_ev_consumed", 0.0)), "虚能量传播预算"),
    ]
    return _section(
        "induction",
        "感应赋能 / Induction Propagation",
        "".join(cards) + "".join(source_blocks) + _table("已回写目标结构", ["结构 ID", "内容", "delta_ev", "结果"], applied_rows),
    )


def _common_part_summary(common_part: dict) -> str:
    if not common_part:
        return "无"
    common = " / ".join(common_part.get("common_tokens", []) or []) or common_part.get("common_signature", "") or "无"
    residual_existing = common_part.get("residual_existing_signature", "") or "—"
    residual_incoming = common_part.get("residual_incoming_signature", "") or "—"
    return f"{common} | existing {residual_existing} | incoming {residual_incoming}"


def _chain_summary(items: list[dict], mode: str) -> str:
    if not items:
        return "无"
    if mode == "structure":
        return " ; ".join(
            f"{item.get('owner_display_text', '') or item.get('owner_id', '')}({item.get('owner_kind', '')}) -> {item.get('candidate_count', 0)}"
            for item in items[:8]
        )
    return " ; ".join(
        f"{item.get('owner_display_text', '') or item.get('owner_structure_id', '')} -> {item.get('candidate_count', 0)}"
        for item in items[:8]
    )


def _storage_summary(summary: dict) -> str:
    if not summary:
        return "无"
    actions = " -> ".join(
        f"{item.get('type', '')}({item.get('group_id', '') or item.get('owner_id', '')})"
        for item in summary.get("actions", [])[:12]
    ) or "无"
    return (
        f"{summary.get('owner_display_text', '') or summary.get('owner_id', '')}"
        f"({summary.get('owner_kind', '')}) | new_groups={','.join(summary.get('new_group_ids', [])) or '无'} | actions={actions}"
    )


def _render_sensor_section(sensor: dict) -> str:
    unit_rows = [
        [
            unit.get("display", unit.get("token", "")),
            unit.get("role", ""),
            unit.get("unit_kind", ""),
            unit.get("source_type", ""),
            f(unit.get("er", 0.0)),
            f(unit.get("ev", 0.0)),
            unit.get("bundle_display", "") or "无",
        ]
        for unit in sensor.get("feature_units", sensor.get("units", []))[:24]
    ]
    group_rows = [
        [
            group.get("group_index", 0),
            group.get("source_type", ""),
            group.get("display_text", ""),
            " / ".join(group.get("tokens", []) or group.get("flat_tokens", [])),
            group.get("sa_count", 0),
            group.get("csa_count", 0),
            " ; ".join(group.get("csa_bundles", [])) or "无",
        ]
        for group in sensor.get("groups", [])[:20]
    ]
    return _section(
        "sensor",
        "文本感受器 / Text Sensor",
        "".join(
            [
                _metric_card("模式", sensor.get("mode", ""), f"分词后端 {sensor.get('tokenizer_backend', '')}"),
                _metric_card("SA / CSA", f"{sensor.get('sa_count', 0)} / {sensor.get('csa_count', 0)}", f"echo 参与帧 {len(sensor.get('echo_frames_used', []))}"),
                _metric_card("输入", sensor.get("input_text", "") or "空", sensor.get("normalized_text", "") or "-"),
            ]
        )
        + _table("刺激单元", ["显示", "角色", "类型", "来源", "ER", "EV", "CSA"], unit_rows)
        + _table("外源刺激组", ["组", "来源", "文本", "tokens", "SA", "CSA", "bundles"], group_rows),
    )


def _storage_summary(summary: dict) -> str:
    if not summary:
        return "无"
    actions = []
    for item in summary.get("actions", [])[:12]:
        label = str(item.get("type", ""))
        parts = []
        if item.get("storage_table", ""):
            parts.append(f"table={item.get('storage_table', '')}")
        if item.get("canonical_display_text", ""):
            parts.append(f"canonical={item.get('canonical_display_text', '')}")
        if item.get("raw_display_text", ""):
            parts.append(f"raw={item.get('raw_display_text', '')}")
        if item.get("memory_id", ""):
            parts.append(f"em={item.get('memory_id', '')}")
        actions.append(f"{label}({' | '.join(parts)})" if parts else label)
    return (
        f"{summary.get('owner_display_text', '') or summary.get('owner_id', '')}"
        f"({summary.get('owner_kind', '')}) | db={summary.get('resolved_db_id', '') or '-'} | "
        f"new_groups={','.join(summary.get('new_group_ids', [])) or '无'} | actions={' ; '.join(actions) or '无'}"
    )


def _render_stimulus_section(stimulus_level: dict, merged_stimulus: dict) -> str:
    data = stimulus_level.get("result", {})
    group_rows = [
        [
            group.get("group_index", 0),
            group.get("source_type", ""),
            group.get("display_text", ""),
            " / ".join(group.get("tokens", []) or group.get("flat_tokens", [])),
            group.get("sa_count", 0),
            group.get("csa_count", 0),
            " ; ".join(group.get("csa_bundles", [])) or "无",
        ]
        for group in merged_stimulus.get("groups", [])
    ]
    projection_rows = [
        [
            item.get("projection_kind", "structure"),
            item.get("memory_id", "") or item.get("structure_id", ""),
            item.get("display_text", ""),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            item.get("reason", ""),
        ]
        for item in data.get("runtime_projection_structures", [])
    ]
    return _section(
        "stimulus",
        "刺激级查存一体 / Stimulus-level Retrieval-Storage",
        "".join(
            [
                _metric_card("轮次", str(data.get("round_count", 0)), f"剩余 SA {data.get('remaining_stimulus_sa_count', 0)}"),
                _metric_card("命中结构", str(len(data.get("matched_structure_ids", []))), " / ".join(data.get("matched_structure_ids", [])) or "无"),
                _metric_card("新建结构", str(len(data.get("new_structure_ids", []))), " / ".join(data.get("new_structure_ids", [])) or "无"),
            ]
        )
        + _table("完整刺激分组", ["组", "来源", "文本", "tokens", "SA", "CSA", "bundles"], group_rows)
        + _table("运行态投影", ["kind", "target_id", "display", "ER", "EV", "reason"], projection_rows),
    )


def _render_projection_section(pool_apply: dict) -> str:
    apply_result = pool_apply.get("apply_result", {})
    projection_rows = [
        [
            item.get("projection_kind", "structure"),
            item.get("memory_id", "") or item.get("structure_id", ""),
            item.get("display_text", ""),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            item.get("reason", ""),
        ]
        for item in pool_apply.get("runtime_projection", [])
    ]
    return _section(
        "projection",
        "状态池回写 / Projection & Pool Apply",
        "".join(
            [
                _metric_card("新建 / 更新", f"{apply_result.get('new_item_count', 0)} / {apply_result.get('updated_item_count', 0)}", f"合并 {apply_result.get('merged_item_count', 0)}"),
                _metric_card("状态增量", f"ΔER {f(apply_result.get('state_delta_summary', {}).get('total_delta_er', 0.0))}", f"ΔEV {f(apply_result.get('state_delta_summary', {}).get('total_delta_ev', 0.0))}"),
            ]
        )
        + _table("运行态投影", ["kind", "target_id", "display", "ER", "EV", "reason"], projection_rows),
    )


def _render_induction_section(induction: dict) -> str:
    data = induction.get("result", {})
    debug = data.get("debug", {})
    source_blocks = []
    for source in debug.get("source_details", [])[:8]:
        rows = [
            [
                entry.get("mode", ""),
                entry.get("projection_kind", "structure"),
                entry.get("memory_id", "") or entry.get("target_structure_id", ""),
                entry.get("target_display_text", ""),
                f(entry.get("delta_ev", 0.0)),
                f(entry.get("runtime_weight", 0.0)),
            ]
            for entry in source.get("candidate_entries", [])[:12]
        ]
        source_blocks.append(
            _table(
                f"感应源 {source.get('display_text', '')} ({source.get('source_structure_id', '')})",
                ["mode", "kind", "target_id", "display", "delta_ev", "runtime"],
                rows,
            )
        )
    applied_rows = [
        [
            item.get("projection_kind", "structure"),
            item.get("memory_id", "") or item.get("structure_id", ""),
            item.get("display_text", ""),
            f(item.get("ev", 0.0)),
            item.get("result", ""),
        ]
        for item in induction.get("applied_targets", [])
    ]
    return _section(
        "induction",
        "感应赋能 / Induction Propagation",
        "".join(
            [
                _metric_card("感应源对象", str(data.get("source_item_count", 0)), "参与感应赋能的运行态起点"),
                _metric_card("传播 / 诱发", f"{data.get('propagated_target_count', 0)} / {data.get('induced_target_count', 0)}", "目标命中次数"),
                _metric_card("total_delta_ev", f(data.get("total_delta_ev", 0.0)), "赋能总增量"),
                _metric_card("ev 消耗", f(data.get("total_ev_consumed", 0.0)), "虚能量传播预算"),
            ]
        )
        + "".join(source_blocks)
        + _table("已回写目标", ["kind", "target_id", "display", "delta_ev", "result"], applied_rows),
    )


_CSS = """
:root {
  --bg: #f3eee3;
  --bg-2: #fbfaf6;
  --paper: rgba(255, 255, 255, 0.86);
  --paper-strong: rgba(255, 255, 255, 0.94);
  --ink: #1d2a24;
  --muted: #5d6b63;
  --line: rgba(20, 52, 44, 0.12);
  --accent: #14342c;
  --accent-soft: #dbe7dc;
  --highlight: #be6b2f;
  --shadow: 0 18px 40px rgba(26, 38, 32, 0.10);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  color: var(--ink);
  background:
    radial-gradient(circle at top left, rgba(190,107,47,0.12), transparent 28%),
    radial-gradient(circle at bottom right, rgba(20,52,44,0.10), transparent 24%),
    linear-gradient(180deg, var(--bg) 0%, var(--bg-2) 100%);
  font-family: "Source Han Sans SC", "Noto Sans SC", "Microsoft YaHei UI", sans-serif;
}
.shell {
  position: fixed;
  top: 0;
  left: 0;
  width: 268px;
  height: 100vh;
  padding: 28px 24px;
  background: rgba(20, 52, 44, 0.95);
  color: #f6f1e8;
  box-shadow: 24px 0 60px rgba(20, 52, 44, 0.16);
}
.brand h1 { margin: 6px 0 8px; font-size: 30px; }
.brand p, .eyebrow { margin: 0; color: rgba(246,241,232,0.74); }
.nav { display: grid; gap: 10px; margin-top: 28px; }
.nav a {
  color: #f6f1e8;
  text-decoration: none;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255,255,255,0.06);
}
.nav a:hover { background: rgba(255,255,255,0.12); }
.layout {
  margin-left: 292px;
  padding: 28px;
  display: grid;
  gap: 20px;
}
.hero, .panel {
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
}
.hero { padding: 28px; }
.hero h2 { margin: 6px 0 12px; font-size: 36px; }
.hero p { margin: 0; color: var(--muted); max-width: 920px; line-height: 1.7; }
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
  margin-top: 18px;
}
.metric {
  padding: 18px;
  border-radius: 18px;
  background: var(--paper-strong);
  border: 1px solid var(--line);
}
.metric-title { font-size: 12px; letter-spacing: 0.08em; color: var(--muted); text-transform: uppercase; }
.metric-value { margin-top: 10px; font-size: 22px; font-weight: 700; line-height: 1.35; }
.metric-note { margin-top: 8px; color: var(--muted); font-size: 13px; line-height: 1.5; }
.panel { padding: 22px; }
.section-head h3 { margin: 0; font-size: 24px; }
.subpanel { margin-top: 16px; padding: 18px; border-radius: 18px; background: var(--paper-strong); border: 1px solid var(--line); }
.subpanel h4 { margin: 0 0 12px; font-size: 18px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
.round { margin-top: 16px; padding: 16px 18px; border-radius: 18px; background: var(--paper-strong); border: 1px solid var(--line); }
.round summary { cursor: pointer; font-weight: 700; }
.round-note { margin-top: 12px; color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.chip {
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 13px;
}
.empty { color: var(--muted); font-size: 14px; }
@media (max-width: 1080px) {
  .shell { position: static; width: auto; height: auto; }
  .layout { margin-left: 0; }
}
"""


def _obs_html_projection_kind_label(kind: str) -> str:
    mapping = {
        "structure": "结构 / Structure",
        "memory": "残差记忆 / Residual Memory",
    }
    return mapping.get(str(kind or ""), str(kind or "structure"))


def _display_text(item: dict) -> str:
    if not isinstance(item, dict):
        return str(item)
    semantic_text = item.get("semantic_grouped_display_text") or item.get("semantic_display_text") or ""
    if semantic_text:
        return str(semantic_text)
    rendered = _semantic_sequence_text(item.get("sequence_groups", []))
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


def _details_block(*, summary: str, body: str) -> str:
    return f"<details class='round' open><summary>{e(summary)}</summary>{body}</details>"


def _obs_html_group_text(group: dict) -> str:
    if not isinstance(group, dict):
        return str(group)
    semantic_text = str(group.get("semantic_display_text", "") or "")
    if semantic_text:
        return semantic_text
    rendered = _semantic_sequence_text(group.get("sequence_groups", []), context="stimulus")
    if rendered:
        return rendered
    return (
        str(group.get("display_text", "") or "")
        or str(group.get("grouped_display_text", "") or "")
        or " / ".join(group.get("tokens", []) or group.get("flat_tokens", []))
        or "空"
    )


def _obs_html_budget_rows(budget: dict) -> list[list[object]]:
    rows = []
    for key, value in (budget or {}).items():
        if isinstance(value, dict):
            rows.append(
                [
                    key,
                    f(value.get("er", 0.0)),
                    f(value.get("ev", 0.0)),
                    f(value.get("total", 0.0)),
                ]
            )
        else:
            rows.append([key, value, "", ""])
    return rows


def _obs_html_common_text(common_part: dict) -> str:
    if not common_part:
        return "无"
    rendered = _semantic_sequence_text(common_part.get("common_groups", []))
    if rendered:
        return rendered
    return (
        str(common_part.get("common_display", "") or "")
        or " / ".join(common_part.get("common_tokens", []) or [])
        or str(common_part.get("common_signature", "") or "")
        or "无"
    )


def _obs_html_storage_block(summary: dict) -> str:
    # 结构级本地库存储必须直观显示“写到了哪个表、写了什么、关联哪个记忆”。
    if not summary:
        return (
            "<section class='subpanel'>"
            "<h4>局部库动作 / Local DB Action</h4>"
            "<div class='empty'>本轮无写入</div>"
            "</section>"
        )
    owner = summary.get("owner_display_text", "") or summary.get("owner_id", "") or "-"
    owner_kind = summary.get("owner_kind", "") or "-"
    db_id = summary.get("resolved_db_id", "") or "-"
    new_groups = " / ".join(summary.get("new_group_ids", [])) or "无"
    new_structures = " / ".join(summary.get("new_structure_ids", [])) or "无"
    action_rows = []
    for item in summary.get("actions", [])[:12]:
        if not isinstance(item, dict):
            continue
        raw_text = _semantic_sequence_text(item.get("raw_sequence_groups", [])) or item.get("raw_display_text", "") or "—"
        canonical_text = _semantic_sequence_text(item.get("canonical_sequence_groups", [])) or item.get("canonical_display_text", "") or "—"
        action_rows.append(
            [
                f"{item.get('type_zh', '') or item.get('type', '')} / {item.get('type', '') or '-'}",
                f"{item.get('storage_table_zh', '') or item.get('storage_table', '')} ({item.get('storage_table', '') or '-'})",
                item.get("entry_id", "") or "—",
                raw_text,
                canonical_text,
                item.get("memory_id", "") or "—",
            ]
        )
    return (
        "<section class='subpanel'>"
        "<h4>局部库动作 / Local DB Action</h4>"
        f"<div class='round-note'>拥有者 / Owner: {e(owner)} ({e(owner_kind)}) | 数据库 / DB: {e(db_id)} | 新组 / New groups: {e(new_groups)} | 新结构 / New structures: {e(new_structures)}</div>"
        + (
            _table("写入动作 / Write actions", ["动作 / Action", "表 / Table", "条目 ID", "原始残差 / Raw", "还原后 / Canonical", "em_id"], action_rows)
            if action_rows
            else "<div class='empty'>本轮无写入</div>"
        )
        + "</section>"
    )


def _storage_summary(summary: dict) -> str:
    if not summary:
        return "无"
    owner = summary.get("owner_display_text", "") or summary.get("owner_id", "") or "-"
    owner_kind = summary.get("owner_kind", "") or "-"
    db_id = summary.get("resolved_db_id", "") or "-"
    labels = [
        f"{item.get('type_zh', '') or item.get('type', '')}"
        for item in summary.get("actions", [])[:12]
        if isinstance(item, dict) and (item.get("type_zh", "") or item.get("type", ""))
    ]
    return f"{owner}({owner_kind}) | db={db_id} | actions={' ; '.join(labels) or '无'}"


def _render_structure_section(structure_level: dict) -> str:
    data = structure_level.get("result", {})
    debug = data.get("debug", {})
    cam_rows = [
        [
            item.get("structure_id", ""),
            _display_text(item),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            f(item.get("total_energy", 0.0)),
            f(item.get("base_weight", 1.0)),
            f(item.get("recent_gain", 1.0)),
            f(item.get("fatigue", 0.0)),
        ]
        for item in debug.get("cam_items", [])
    ]
    round_blocks = []
    for round_detail in debug.get("round_details", []):
        anchor = round_detail.get("anchor", {}) or {}
        selected = round_detail.get("selected_group") or {}
        candidate_rows = [
            [
                group.get("group_id", ""),
                _display_text(group),
                yn(group.get("eligible", False)),
                f(group.get("score", 0.0)),
                f(group.get("base_similarity", 0.0)),
                f(group.get("coverage_ratio", 0.0)),
                f(group.get("structure_ratio", 0.0)),
                f(group.get("wave_similarity", 0.0)),
                group.get("owner_id", "") or "—",
                _obs_html_common_text(group.get("common_part", {})),
            ]
            for group in round_detail.get("candidate_groups", [])[:12]
        ]
        fragment_rows = [
            [fragment.get("fragment_id", ""), fragment.get("display_text", ""), f(fragment.get("energy_hint", 0.0))]
            for fragment in round_detail.get("internal_fragments", [])[:12]
        ]
        round_blocks.append(
            _details_block(
                summary=f"Round {round_detail.get('round_index', 0)} | 选中结构组 {selected.get('group_id', '无') or '无'}",
                body=(
                    f"<div class='round-note'>锚点结构 / Anchor: {e(_display_text(anchor) or '无')} [{e(anchor.get('structure_id', ''))}] | 选中结构组内容 / Selected profile: {e(_display_text(selected) or '无')}</div>"
                    + _inline_notes(
                        [
                            f"链式打开 / Chain: {_chain_summary(round_detail.get('chain_steps', []), 'structure')}",
                            f"公共部分 / Common: {_obs_html_common_text(selected.get('common_part', {}))}",
                            f"score={f(selected.get('score', 0.0))}",
                            f"coverage={f(selected.get('coverage_ratio', 0.0))}",
                            f"structure={f(selected.get('structure_ratio', 0.0))}",
                            f"wave={f(selected.get('wave_similarity', 0.0))}",
                        ]
                    )
                    + _table("预算前 / Budget before", ["结构 ID", "ER", "EV", "Total"], _obs_html_budget_rows(round_detail.get("budget_before", {})))
                    + _table("预算后 / Budget after", ["结构 ID", "ER", "EV", "Total"], _obs_html_budget_rows(round_detail.get("budget_after", {})))
                    + _obs_html_storage_block(round_detail.get("storage_summary", {}))
                    + _table(
                        "候选结构组 / Candidate groups",
                        ["组 ID", "内容 / Profile", "可参与 / Eligible", "score", "base", "coverage", "structure", "wave", "owner", "common"],
                        candidate_rows,
                    )
                    + _table("内源片段 / Internal fragments", ["片段 ID", "内容", "energy_hint"], fragment_rows)
                ),
            )
        )
    new_group_rows = [
        [
            group.get("group_id", ""),
            _display_text(group),
            _structure_refs(group.get("required_structures", [])) or "无",
            _structure_refs(group.get("bias_structures", [])) or "无",
            e(str(group.get("avg_energy_profile", {}))),
        ]
        for group in debug.get("new_group_details", [])
    ]
    cards = [
        _metric_card("CAM 结构数", str(data.get("cam_stub_count", 0)), "本轮进入结构级的 ST"),
        _metric_card("轮次", str(data.get("round_count", 0)), f"fallback {yn(data.get('fallback_used', False))}"),
        _metric_card("命中结构组", str(len(data.get("matched_group_ids", []))), " / ".join(data.get("matched_group_ids", [])[:6]) or "无"),
        _metric_card("新建结构组", str(len(data.get("new_group_ids", []))), " / ".join(data.get("new_group_ids", [])[:6]) or "无"),
    ]
    return _section(
        "structure",
        "结构级查存一体 / Structure-level Retrieval-Storage",
        "".join(cards)
        + _table("当前 CAM 结构", ["结构 ID", "内容", "ER", "EV", "Total", "W", "G", "F"], cam_rows)
        + "".join(round_blocks)
        + _table("本轮新建结构组", ["组 ID", "内容 / Profile", "required", "bias", "avg_profile"], new_group_rows),
    )


def _render_stimulus_section(stimulus_level: dict, merged_stimulus: dict) -> str:
    data = stimulus_level.get("result", {})
    debug = data.get("debug", {})
    group_rows = [
        [
            f"G{group.get('group_index', 0)}",
            group.get("source_type", ""),
            _obs_html_group_text(group),
            " / ".join(group.get("tokens", []) or group.get("flat_tokens", [])),
            group.get("sa_count", 0),
            group.get("csa_count", 0),
            " ; ".join(group.get("csa_bundles", [])) or "无",
        ]
        for group in merged_stimulus.get("groups", [])
    ]
    round_blocks = []
    for round_detail in debug.get("round_details", []):
        anchor = round_detail.get("anchor", {}) or round_detail.get("anchor_unit", {}) or {}
        selected = round_detail.get("selected_match") or {}
        common = round_detail.get("created_common_structure") or {}
        residual = round_detail.get("created_residual_structure") or {}
        fresh = round_detail.get("created_fresh_structure") or {}
        candidate_rows = [
            [
                candidate.get("structure_id", ""),
                _display_text(candidate),
                yn(candidate.get("eligible", False)),
                yn(candidate.get("exact_match", False)),
                yn(candidate.get("full_structure_included", False)),
                f(candidate.get("competition_score", candidate.get("match_score", 0.0))),
                f(candidate.get("stimulus_match_ratio", candidate.get("coverage_ratio", 0.0))),
                f(candidate.get("structure_match_ratio", 0.0)),
                candidate.get("chain_depth", 0),
                candidate.get("owner_structure_id", "") or candidate.get("parent_structure_id", "") or "—",
                _obs_html_common_text(candidate.get("common_part", {})),
            ]
            for candidate in round_detail.get("candidate_details", [])[:12]
        ]
        round_blocks.append(
            _details_block(
                summary=f"Round {round_detail.get('round_index', 0)} | 轮前残余 {round_detail.get('remaining_grouped_text_before', '') or '无'}",
                body=(
                    f"<div class='round-note'>锚点刺激元 / Anchor: {e(anchor.get('display_text', anchor.get('token', '')) or '无')} | 局部工作组 / Focus group: {e(round_detail.get('focus_group_text_before', '') or '无')}</div>"
                    + _inline_notes(
                        [
                            f"链式打开 / Chain: {_chain_summary(round_detail.get('chain_steps', []), 'stimulus')}",
                            f"命中结构 / Matched: {_display_text(selected) or '无'} [{selected.get('structure_id', '') or ''}]",
                            f"公共部分 / Common: {_obs_html_common_text(selected.get('common_part', {}))}",
                            f"轮后残余 / Remaining after: {round_detail.get('remaining_grouped_text_after', '') or '无'}",
                            f"能量转移 / Transfer: ER {f(round_detail.get('transferred_er', 0.0))} / EV {f(round_detail.get('transferred_ev', 0.0))}",
                            f"新建共同结构 / New common: {_display_text(common) or '无'}",
                            f"新建残差结构 / New residual: {_display_text(residual) or '无'}",
                            f"扩展结构 / Extension: {_display_text(fresh) or '无'}",
                        ]
                    )
                    + _table(
                        "候选结构 / Candidate structures",
                        ["结构 ID", "内容", "可参与", "精确", "完整包含", "score", "stimulus", "structure", "depth", "owner", "common"],
                        candidate_rows,
                    )
                ),
            )
        )
    projection_rows = [
        [
            _obs_html_projection_kind_label(item.get("projection_kind", "structure")),
            item.get("memory_id", "") or item.get("structure_id", ""),
            _display_text(item),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            item.get("reason", ""),
        ]
        for item in data.get("runtime_projection_structures", [])
    ]
    cards = [
        _metric_card("完整刺激", merged_stimulus.get("display_text", "") or "空", "当前外源 + 内源整合结果"),
        _metric_card("总 ER / EV", f"{f(merged_stimulus.get('total_er', 0.0))} / {f(merged_stimulus.get('total_ev', 0.0))}", "完整刺激能量"),
        _metric_card("轮次", str(data.get("round_count", 0)), f"fallback {yn(data.get('fallback_used', False))}"),
        _metric_card("结构命中 / 新建", f"{len(data.get('matched_structure_ids', []))} / {len(data.get('new_structure_ids', []))}", "刺激级查存结果"),
    ]
    return _section(
        "stimulus",
        "刺激级查存一体 / Stimulus-level Retrieval-Storage",
        "".join(cards)
        + _table("完整刺激分组", ["组", "来源", "分组文本 / Grouped text", "flat tokens", "SA", "CSA", "CSA bundles"], group_rows)
        + "".join(round_blocks)
        + _table("运行态投影 / Runtime projections", ["类型 / Kind", "目标 ID", "内容", "ER", "EV", "原因"], projection_rows),
    )


def _render_projection_section(pool_apply: dict) -> str:
    apply_result = pool_apply.get("apply_result", {})
    priority_summary = pool_apply.get("priority_summary", {})
    input_packet = pool_apply.get("input_packet", {})
    residual_packet = pool_apply.get("residual_packet", {})
    priority_events = pool_apply.get("priority_events", [])
    event_rows = [
        [event.get("event_type", ""), f"{event.get('target_item_id', '')}[{event.get('target_display', '')}]", event.get("reason", "")]
        for event in pool_apply.get("events", [])[:20]
    ]
    priority_rows = [
        [
            event.get("target_display", "") or event.get("target_item_id", ""),
            event.get("matched_structure_signature", "") or "—",
            " / ".join(str(token) for token in (event.get("extra_context", {}) or {}).get("matched_tokens", []) if token) or "—",
            f"{(event.get('extra_context', {}) or {}).get('consumed_energy_key', 'energy')}:{f((event.get('extra_context', {}) or {}).get('consumed_amount', 0.0))}",
            event.get("reason", ""),
        ]
        for event in priority_events[:20]
    ]
    packet_rows = [
        ["input", input_packet.get("display_text", ""), f(input_packet.get("total_er", 0.0)), f(input_packet.get("total_ev", 0.0)), len(input_packet.get("flat_tokens", []))],
        ["residual", residual_packet.get("display_text", ""), f(residual_packet.get("total_er", 0.0)), f(residual_packet.get("total_ev", 0.0)), len(residual_packet.get("flat_tokens", []))],
        [
            "consumed",
            "priority neutralization",
            f(priority_summary.get("consumed_er", 0.0)),
            f(priority_summary.get("consumed_ev", 0.0)),
            max(0, int(priority_summary.get("input_flat_token_count", 0)) - int(priority_summary.get("residual_flat_token_count", 0))),
        ],
    ]
    bias_rows = [
        [
            _obs_html_projection_kind_label(item.get("projection_kind", "structure")),
            item.get("memory_id", "") or item.get("structure_id", ""),
            _display_text(item),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            item.get("result", item.get("reason", "")),
        ]
        for item in pool_apply.get("bias_projection", [])
    ]
    runtime_rows = [
        [
            _obs_html_projection_kind_label(item.get("projection_kind", "structure")),
            item.get("memory_id", "") or item.get("structure_id", ""),
            _display_text(item),
            item.get("reason", ""),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            item.get("result", ""),
        ]
        for item in pool_apply.get("runtime_projection", [])
    ]
    cards = [
        _metric_card("优先中和", str(priority_summary.get("priority_neutralized_item_count", apply_result.get("priority_neutralized_item_count", 0))), f"events {priority_summary.get('priority_event_count', len(priority_events))}"),
        _metric_card("packet delta", f"ER {f(priority_summary.get('consumed_er', 0.0))} / EV {f(priority_summary.get('consumed_ev', 0.0))}", f"tokens {priority_summary.get('input_flat_token_count', 0)} -> {priority_summary.get('residual_flat_token_count', 0)}"),
        _metric_card("新建 / 更新", f"{apply_result.get('new_item_count', 0)} / {apply_result.get('updated_item_count', 0)}", f"合并 {apply_result.get('merged_item_count', 0)}"),
        _metric_card("中和 / 状态增量", str(apply_result.get("neutralized_item_count", 0)), f"ΔER {f(apply_result.get('state_delta_summary', {}).get('total_delta_er', 0.0))} / ΔEV {f(apply_result.get('state_delta_summary', {}).get('total_delta_ev', 0.0))}"),
    ]
    return _section(
        "projection",
        "状态池回写 / Projection & Pool Apply",
        "".join(cards)
        + _table("优先中和包变化 / Priority neutralization packet delta", ["stage", "display", "ER", "EV", "tokens"], packet_rows)
        + _table("优先中和事件 / Priority neutralization events", ["target", "matched_signature", "matched_tokens", "consumed", "reason"], priority_rows)
        + _table("入池事件 / Apply events", ["事件", "目标", "原因"], event_rows)
        + _table("偏置投影 / Bias projection", ["类型 / Kind", "目标 ID", "内容", "ER", "EV", "结果"], bias_rows)
        + _table("运行态投影 / Runtime projection", ["类型 / Kind", "目标 ID", "内容", "原因", "ER", "EV", "结果"], runtime_rows),
    )


def _render_induction_section(induction: dict) -> str:
    data = induction.get("result", {})
    debug = data.get("debug", {})
    source_selection = induction.get("source_selection", {}) or data.get("source_selection", {}) or {}
    source_details = list(debug.get("source_details", []) or [])
    source_hit_count = sum(1 for source in source_details if list(source.get("candidate_entries", []) or []))
    source_miss_count = max(0, len(source_details) - source_hit_count)
    source_blocks = []
    for source in source_details[:8]:
        source_id = str(source.get("source_item_id", "") or source.get("source_structure_id", "") or "")
        support_ids = [str(x) for x in (source.get("resolved_support_structure_ids", []) or source.get("support_structure_ids", []) or []) if str(x)]
        pointer_info = source.get("pointer_info", {}) if isinstance(source.get("pointer_info", {}), dict) else {}
        skipped_reason = str(source.get("skipped_reason", "") or "")
        rows = [
            [
                entry.get("mode", ""),
                _obs_html_projection_kind_label(entry.get("projection_kind", "structure")),
                entry.get("memory_id", "") or entry.get("target_structure_id", ""),
                entry.get("target_display_text", ""),
                f(entry.get("normalized_share", 0.0)),
                entry.get("entry_count", 0),
                f(entry.get("delta_ev", 0.0)),
                f(entry.get("runtime_weight", 0.0)),
                f(entry.get("base_weight", 1.0)),
                f(entry.get("recent_gain", 1.0)),
                f(entry.get("fatigue", 0.0)),
            ]
            for entry in source.get("candidate_entries", [])[:16]
        ]
        source_blocks.append(
            _details_block(
                summary=f"源对象 {source.get('display_text', '') or source_id} ({source_id or '-'})",
                body=(
                    f"<div class='round-note'>源类型 {e(str(source.get('source_ref_object_type', '') or '-'))} | ER {f(source.get('source_er', 0.0))} | EV {f(source.get('source_ev', 0.0))}</div>"
                    f"<div class='round-note'>支持结构 {e(' / '.join(support_ids) or '-')} | 局部数据库 {e(str(pointer_info.get('resolved_db_id', '') or '-'))} | fallback {e('是' if pointer_info.get('used_fallback') else '否')}</div>"
                    + (f"<div class='round-note'>未执行原因 {e(skipped_reason)}</div>" if skipped_reason else "")
                    + _table("赋能路径 / Induction paths", ["模式", "类型 / Kind", "目标 ID", "目标内容", "share", "entries", "delta_ev", "runtime", "W", "G", "F"], rows)
                ),
            )
        )
    applied_rows = [
        [
            _obs_html_projection_kind_label(item.get("projection_kind", "structure")),
            item.get("memory_id", "") or item.get("structure_id", ""),
            _display_text(item),
            item.get("target_sa_count", "-"),
            f(item.get("landed_total_ev", item.get("ev", 0.0))),
            item.get("result", ""),
        ]
        for item in induction.get("applied_targets", [])
    ]
    cards = [
        _metric_card(
            "可用源 / 实际参与",
            f"{source_selection.get('induction_source_available_runtime_count', data.get('source_item_count', 0))} / {data.get('source_item_count', 0)}",
            f"ST {source_selection.get('induction_source_selected_st_count', 0)} | 非ST {source_selection.get('induction_source_selected_non_st_count', 0)}",
        ),
        _metric_card(
            "ER 源 / EV 源",
            f"{source_selection.get('induction_source_selected_from_er_count', 0)} / {source_selection.get('induction_source_selected_from_ev_count', 0)}",
            f"ER+EV {source_selection.get('induction_source_selected_from_er_ev_count', 0)} | cap_hit {'是' if source_selection.get('induction_source_selection_cap_hit') else '否'}",
        ),
        _metric_card("命中源 / 无候选", f"{source_hit_count} / {source_miss_count}", f"局部目标提示 {source_selection.get('induction_source_selected_with_local_target_hint_count', 0)}"),
        _metric_card("传播 / 诱发", f"{data.get('propagated_target_count', 0)} / {data.get('induced_target_count', 0)}", "目标命中次数"),
        _metric_card("total_delta_ev", f(data.get("total_delta_ev", 0.0)), "赋能总增量"),
        _metric_card("ev 消耗", f(data.get("total_ev_consumed", 0.0)), "虚能量传播预算"),
    ]
    return _section(
        "induction",
        "感应赋能 / Induction Propagation",
        "".join(cards) + "".join(source_blocks) + _table("已回写目标 / Applied targets", ["类型 / Kind", "目标 ID", "内容", "SA", "落地 EV", "结果"], applied_rows),
    )


def _render_sensor_section(sensor: dict) -> str:
    fatigue = sensor.get("fatigue_summary", {}) or {}
    unit_rows = [
        [
            unit.get("display", unit.get("token", "")),
            unit.get("role", ""),
            unit.get("unit_kind", ""),
            unit.get("source_type", ""),
            f(unit.get("er", 0.0)),
            f(unit.get("ev", 0.0)),
            f(unit.get("suppression_ratio", 0.0)),
            f(unit.get("er_before_fatigue", unit.get("er", 0.0))),
            f(unit.get("er_after_fatigue", unit.get("er", 0.0))),
            f"{unit.get('window_count', 0)}/{unit.get('threshold_count', 0)}",
            unit.get("bundle_display", "") or "无",
        ]
        for unit in sensor.get("feature_units", sensor.get("units", []))[:24]
    ]
    group_rows = [
        [
            group.get("group_index", 0),
            group.get("source_type", ""),
            group.get("display_text", ""),
            " / ".join(group.get("tokens", [])),
            group.get("sa_count", 0),
            group.get("csa_count", 0),
            " ; ".join(group.get("csa_bundles", [])) or "无",
        ]
        for group in sensor.get("groups", [])[:20]
    ]
    return _section(
        "sensor",
        "文本感受器 / Text Sensor",
        "".join(
            [
                _metric_card("模式", sensor.get("mode", ""), f"分词后端 {sensor.get('tokenizer_backend', '')}"),
                _metric_card("SA / CSA", f"{sensor.get('sa_count', 0)} / {sensor.get('csa_count', 0)}", f"echo 参与帧 {len(sensor.get('echo_frames_used', []))}"),
                _metric_card("输入", sensor.get("input_text", "") or "空", sensor.get("normalized_text", "") or "-"),
                _metric_card("刺激疲劳", fatigue.get("suppressed_unit_count", 0), f"suppressed ER {f(fatigue.get('total_er_suppressed', 0.0))}"),
            ]
        )
        + _table("刺激单元", ["显示", "角色", "类型", "来源", "ER", "EV", "suppression", "before", "after", "count", "CSA"], unit_rows)
        + _table("外源刺激组", ["组", "来源", "文本", "tokens", "SA", "CSA", "bundles"], group_rows),
    )


def _semantic_sequence_text(groups: list[dict] | None, *, context: str = "auto") -> str:
    from hdb._sequence_display import format_semantic_sequence_groups

    if not isinstance(groups, list) or not groups:
        return ""
    return format_semantic_sequence_groups(groups, context=context)


def _notation_block() -> str:
    from hdb._sequence_display import semantic_notation_examples, semantic_notation_legend

    legend_items = "".join(
        f"<li><code>{e(item['symbol'])}</code> {e(item['meaning'])}</li>"
        for item in semantic_notation_legend()
    )
    example_items = "".join(
        (
            "<li>"
            f"<strong>{e(item['title'])}</strong>: <code>{e(item['example'])}</code><br/>"
            f"{e(item['explanation'])}"
            "</li>"
        )
        for item in semantic_notation_examples()
    )
    return (
        "<section class='subpanel'>"
        "<h4>记号说明 / Notation</h4>"
        "<div class='round-note'>刺激流是打散后的 SA/CSA，所以没有 <code>[]</code>；结构与记忆保持为 ST，因此会出现 <code>[]</code>。</div>"
        f"<ul>{legend_items}</ul>"
        f"<ul>{example_items}</ul>"
        "</section>"
    )


def _display_text(item: dict) -> str:
    if not isinstance(item, dict):
        return str(item)
    semantic_text = item.get("semantic_grouped_display_text") or item.get("semantic_display_text") or ""
    if semantic_text:
        return str(semantic_text)
    rendered = _semantic_sequence_text(item.get("sequence_groups", []))
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


def _obs_html_group_text(group: dict) -> str:
    if not isinstance(group, dict):
        return str(group)
    semantic_text = str(group.get("semantic_display_text", "") or "")
    if semantic_text:
        return semantic_text
    rendered = _semantic_sequence_text(group.get("sequence_groups", []), context="stimulus")
    if rendered:
        return rendered
    return (
        str(group.get("display_text", "") or "")
        or str(group.get("grouped_display_text", "") or "")
        or " / ".join(group.get("tokens", []) or group.get("flat_tokens", []))
        or "空"
    )


def _obs_html_common_text(common_part: dict) -> str:
    if not common_part:
        return "无"
    rendered = _semantic_sequence_text(common_part.get("common_groups", []))
    if rendered:
        return rendered
    return (
        str(common_part.get("common_display", "") or "")
        or " / ".join(common_part.get("common_tokens", []) or [])
        or str(common_part.get("common_signature", "") or "")
        or "无"
    )


def _obs_html_storage_block(summary: dict) -> str:
    if not summary:
        return (
            "<section class='subpanel'>"
            "<h4>局部库动作 / Local DB Action</h4>"
            "<div class='empty'>本轮无写入</div>"
            "</section>"
        )
    owner = summary.get("owner_display_text", "") or summary.get("owner_id", "") or "-"
    owner_kind = summary.get("owner_kind", "") or "-"
    db_id = summary.get("resolved_db_id", "") or "-"
    new_groups = " / ".join(summary.get("new_group_ids", [])) or "无"
    new_structures = " / ".join(summary.get("new_structure_ids", [])) or "无"
    action_rows = []
    for item in summary.get("actions", [])[:12]:
        if not isinstance(item, dict):
            continue
        raw_text = _semantic_sequence_text(item.get("raw_sequence_groups", [])) or item.get("raw_display_text", "") or "-"
        canonical_text = _semantic_sequence_text(item.get("canonical_sequence_groups", [])) or item.get("canonical_display_text", "") or "-"
        action_rows.append(
            [
                f"{item.get('type_zh', '') or item.get('type', '')} / {item.get('type', '') or '-'}",
                f"{item.get('storage_table_zh', '') or item.get('storage_table', '')} ({item.get('storage_table', '') or '-'})",
                item.get("entry_id", "") or "-",
                raw_text,
                canonical_text,
                item.get("memory_id", "") or "-",
            ]
        )
    return (
        "<section class='subpanel'>"
        "<h4>局部库动作 / Local DB Action</h4>"
        f"<div class='round-note'>拥有者 / Owner: {e(owner)} ({e(owner_kind)}) | 数据库 / DB: {e(db_id)} | 新组 / New groups: {e(new_groups)} | 新结构 / New structures: {e(new_structures)}</div>"
        + (
            _table("写入动作 / Write actions", ["动作 / Action", "表 / Table", "条目 ID", "原始残差 / Raw", "还原后 / Canonical", "em_id"], action_rows)
            if action_rows
            else "<div class='empty'>本轮无写入</div>"
        )
        + "</section>"
    )


def _render_structure_section(structure_level: dict) -> str:
    data = structure_level.get("result", {})
    debug = data.get("debug", {})
    cam_rows = [
        [
            item.get("structure_id", ""),
            _display_text(item),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            f(item.get("total_energy", 0.0)),
            f(item.get("base_weight", 1.0)),
            f(item.get("recent_gain", 1.0)),
            f(item.get("fatigue", 0.0)),
        ]
        for item in debug.get("cam_items", [])
    ]
    round_blocks = []
    for round_detail in debug.get("round_details", []):
        anchor = round_detail.get("anchor", {}) or {}
        selected = round_detail.get("selected_group") or {}
        candidate_rows = [
            [
                group.get("group_id", ""),
                _display_text(group),
                yn(group.get("eligible", False)),
                f(group.get("score", 0.0)),
                f(group.get("base_similarity", 0.0)),
                f(group.get("coverage_ratio", 0.0)),
                f(group.get("structure_ratio", 0.0)),
                f(group.get("wave_similarity", 0.0)),
                group.get("owner_id", "") or "-",
                _obs_html_common_text(group.get("common_part", {})),
            ]
            for group in round_detail.get("candidate_groups", [])[:12]
        ]
        fragment_rows = [
            [fragment.get("fragment_id", ""), _display_text(fragment), f(fragment.get("energy_hint", 0.0))]
            for fragment in round_detail.get("internal_fragments", [])[:12]
        ]
        round_blocks.append(
            _details_block(
                summary=f"Round {round_detail.get('round_index', 0)} | selected {selected.get('group_id', 'none')}",
                body=(
                    f"<div class='round-note'>Anchor: {e(_display_text(anchor) or '-')} [{e(anchor.get('structure_id', ''))}] | Selected profile: {e(_display_text(selected) or '-')}</div>"
                    + _inline_notes(
                        [
                            f"Chain: {_chain_summary(round_detail.get('chain_steps', []), 'structure')}",
                            f"Common: {_obs_html_common_text(selected.get('common_part', {}))}",
                            f"score={f(selected.get('score', 0.0))}",
                            f"coverage={f(selected.get('coverage_ratio', 0.0))}",
                            f"structure={f(selected.get('structure_ratio', 0.0))}",
                            f"wave={f(selected.get('wave_similarity', 0.0))}",
                        ]
                    )
                    + _table("Budget before", ["Structure ID", "ER", "EV", "Total"], _obs_html_budget_rows(round_detail.get("budget_before", {})))
                    + _table("Budget after", ["Structure ID", "ER", "EV", "Total"], _obs_html_budget_rows(round_detail.get("budget_after", {})))
                    + _obs_html_storage_block(round_detail.get("storage_summary", {}))
                    + _table(
                        "Candidate groups",
                        ["Group ID", "Profile", "Eligible", "score", "base", "coverage", "structure", "wave", "owner", "common"],
                        candidate_rows,
                    )
                    + _table("Internal fragments", ["Fragment ID", "Content", "energy_hint"], fragment_rows)
                ),
            )
        )
    new_group_rows = [
        [
            group.get("group_id", ""),
            _display_text(group),
            _structure_refs(group.get("required_structures", [])) or "none",
            _structure_refs(group.get("bias_structures", [])) or "none",
            e(str(group.get("avg_energy_profile", {}))),
        ]
        for group in debug.get("new_group_details", [])
    ]
    cards = [
        _metric_card("CAM 结构数", str(data.get("cam_stub_count", 0)), "本轮进入结构级的 ST"),
        _metric_card("轮次", str(data.get("round_count", 0)), f"fallback {yn(data.get('fallback_used', False))}"),
        _metric_card("命中结构组", str(len(data.get("matched_group_ids", []))), " / ".join(data.get("matched_group_ids", [])[:6]) or "none"),
        _metric_card("新建结构组", str(len(data.get("new_group_ids", []))), " / ".join(data.get("new_group_ids", [])[:6]) or "none"),
    ]
    return _section(
        "structure",
        "结构级查存一体 / Structure-level Retrieval-Storage",
        "".join(cards)
        + _notation_block()
        + _table("当前 CAM 结构", ["结构 ID", "内容", "ER", "EV", "Total", "W", "G", "F"], cam_rows)
        + "".join(round_blocks)
        + _table("本轮新建结构组", ["Group ID", "Profile", "required", "bias", "avg_profile"], new_group_rows),
    )


def _render_stimulus_section(stimulus_level: dict, merged_stimulus: dict) -> str:
    data = stimulus_level.get("result", {})
    debug = data.get("debug", {})
    group_rows = [
        [
            f"G{group.get('group_index', 0)}",
            group.get("source_type", ""),
            _obs_html_group_text(group),
            " / ".join(group.get("tokens", []) or group.get("flat_tokens", [])),
            group.get("sa_count", 0),
            group.get("csa_count", 0),
            " ; ".join(group.get("csa_bundles", [])) or "none",
        ]
        for group in merged_stimulus.get("groups", [])
    ]
    round_blocks = []
    for round_detail in debug.get("round_details", []):
        anchor = round_detail.get("anchor", {}) or round_detail.get("anchor_unit", {}) or {}
        selected = round_detail.get("selected_match") or {}
        common = round_detail.get("created_common_structure") or {}
        residual = round_detail.get("created_residual_structure") or {}
        fresh = round_detail.get("created_fresh_structure") or {}
        remaining_before = _semantic_sequence_text(round_detail.get("remaining_sequence_groups_before", []), context="stimulus") or round_detail.get("remaining_grouped_text_before", "") or "none"
        remaining_after = _semantic_sequence_text(round_detail.get("remaining_sequence_groups_after", []), context="stimulus") or round_detail.get("remaining_grouped_text_after", "") or "none"
        focus_before = _semantic_sequence_text(round_detail.get("focus_group_sequence_groups_before", []), context="stimulus") or round_detail.get("focus_group_text_before", "") or "none"
        candidate_rows = [
            [
                candidate.get("structure_id", ""),
                _display_text(candidate),
                yn(candidate.get("eligible", False)),
                yn(candidate.get("exact_match", False)),
                yn(candidate.get("full_structure_included", False)),
                f(candidate.get("competition_score", candidate.get("match_score", 0.0))),
                f(candidate.get("stimulus_match_ratio", candidate.get("coverage_ratio", 0.0))),
                f(candidate.get("structure_match_ratio", 0.0)),
                candidate.get("chain_depth", 0),
                candidate.get("owner_structure_id", "") or candidate.get("parent_structure_id", "") or "-",
                _obs_html_common_text(candidate.get("common_part", {})),
            ]
            for candidate in round_detail.get("candidate_details", [])[:12]
        ]
        round_blocks.append(
            _details_block(
                summary=f"Round {round_detail.get('round_index', 0)} | remaining before {remaining_before}",
                body=(
                    f"<div class='round-note'>Anchor: {e(anchor.get('display_text', anchor.get('token', '')) or '-')} | Focus group: {e(focus_before)}</div>"
                    + _inline_notes(
                        [
                            f"Chain: {_chain_summary(round_detail.get('chain_steps', []), 'stimulus')}",
                            f"Matched: {_display_text(selected) or '-'} [{selected.get('structure_id', '') or ''}]",
                            f"Common: {_obs_html_common_text(selected.get('common_part', {}))}",
                            f"Remaining after: {remaining_after}",
                            f"Transfer: ER {f(round_detail.get('transferred_er', 0.0))} / EV {f(round_detail.get('transferred_ev', 0.0))}",
                            f"New common: {_display_text(common) or '-'}",
                            f"New residual: {_display_text(residual) or '-'}",
                            f"Extension: {_display_text(fresh) or '-'}",
                        ]
                    )
                    + _table(
                        "Candidate structures",
                        ["Structure ID", "Content", "Eligible", "Exact", "Full", "score", "stimulus", "structure", "depth", "owner", "common"],
                        candidate_rows,
                    )
                ),
            )
        )
    projection_rows = [
        [
            _obs_html_projection_kind_label(item.get("projection_kind", "structure")),
            item.get("memory_id", "") or item.get("structure_id", ""),
            _display_text(item),
            f(item.get("er", 0.0)),
            f(item.get("ev", 0.0)),
            item.get("reason", ""),
        ]
        for item in data.get("runtime_projection_structures", [])
    ]
    full_stimulus_text = _display_text(merged_stimulus) or merged_stimulus.get("display_text", "") or "empty"
    cards = [
        _metric_card("完整刺激", full_stimulus_text, "当前外源 + 内源整合结果"),
        _metric_card("总 ER / EV", f"{f(merged_stimulus.get('total_er', 0.0))} / {f(merged_stimulus.get('total_ev', 0.0))}", "完整刺激能量"),
        _metric_card("轮次", str(data.get("round_count", 0)), f"fallback {yn(data.get('fallback_used', False))}"),
        _metric_card("结构命中 / 新建", f"{len(data.get('matched_structure_ids', []))} / {len(data.get('new_structure_ids', []))}", "刺激级查存结果"),
    ]
    return _section(
        "stimulus",
        "刺激级查存一体 / Stimulus-level Retrieval-Storage",
        "".join(cards)
        + _table("完整刺激分组", ["Group", "source", "Grouped text", "flat tokens", "SA", "CSA", "CSA bundles"], group_rows)
        + "".join(round_blocks)
        + _table("运行态投影", ["Kind", "Target ID", "Content", "ER", "EV", "Reason"], projection_rows),
    )


def _render_cognitive_feeling_section(cognitive_feeling: dict) -> str:
    signals = list(cognitive_feeling.get("cfs_signals", []) or [])
    writes = cognitive_feeling.get("writes", {}) or {}
    meta = cognitive_feeling.get("meta", {}) or {}

    runtime_nodes = list(writes.get("runtime_nodes", []) or [])
    attr_bindings = list(writes.get("attribute_bindings", []) or [])

    cards = [
        _metric_card("tick_number", str(meta.get("tick_number", "-")), "CFS 内部 tick 计数"),
        _metric_card("信号数 / signals", str(len(signals)), "本轮生成的元认知信号数量"),
        _metric_card("写回节点 / runtime_nodes", str(len(runtime_nodes)), "写回 StatePool 的运行态节点数"),
        _metric_card("属性绑定 / attr_bindings", str(len(attr_bindings)), "存在型属性绑定次数"),
    ]

    signal_rows: list[list[object]] = []
    for sig in signals[:64]:
        target = sig.get("target") or {}
        reasons = list(sig.get("reasons", []) or [])
        evidence = str(sig.get("evidence", {}) or "")
        if len(evidence) > 140:
            evidence = evidence[:140] + "..."
        signal_rows.append(
            [
                sig.get("signal_id", ""),
                sig.get("kind", ""),
                sig.get("scope", ""),
                f(sig.get("strength", 0.0)),
                target.get("target_ref_object_type", ""),
                target.get("target_ref_object_id", ""),
                target.get("target_item_id", ""),
                target.get("target_display", ""),
                reasons[0] if reasons else "",
                evidence,
            ]
        )

    bind_rows: list[list[object]] = []
    for item in attr_bindings[:64]:
        bind_rows.append(
            [
                item.get("kind", ""),
                item.get("target_item_id", ""),
                item.get("attribute_sa_id", ""),
                yn(item.get("success", False)),
                item.get("code", ""),
            ]
        )

    return _section(
        "cfs",
        "认知感受系统（CFS）",
        "".join(cards)
        + _table(
            "认知感受信号（CFS）",
            ["signal_id", "kind", "scope", "strength", "ref_type", "ref_id", "item_id", "target_display", "reason", "evidence"],
            signal_rows,
        )
        + _table(
            "属性绑定写回（写回状态池）",
            ["类型（kind）", "目标条目ID（target_item_id）", "属性SA ID（attribute_sa_id）", "成功（success）", "状态码（code）"],
            bind_rows,
        ),
    )


def _render_emotion_section(emotion: dict) -> str:
    before = emotion.get("nt_state_before", {}) or {}
    after = emotion.get("nt_state_after", {}) or {}
    decay = emotion.get("decay", {}) or {}
    deltas = emotion.get("deltas", {}) or {}
    rwd_pun = emotion.get("rwd_pun_snapshot", {}) or {}
    modulation = emotion.get("modulation", {}) or {}
    att_mod = modulation.get("attention", {}) if isinstance(modulation, dict) else {}
    labels = emotion.get("nt_channel_labels", {}) or {}
    from_cfs = deltas.get("from_cfs", {}) if isinstance(deltas.get("from_cfs", {}), dict) else {}
    from_script = deltas.get("from_script", {}) if isinstance(deltas.get("from_script", {}), dict) else {}
    applied = deltas.get("applied", {}) if isinstance(deltas.get("applied", {}), dict) else {}
    keys = sorted({*before.keys(), *after.keys(), *from_cfs.keys(), *from_script.keys(), *applied.keys(), *labels.keys()})

    cards = [
        _metric_card("奖/惩（rwd/pun）", f"{f(rwd_pun.get('rwd', 0.0))} / {f(rwd_pun.get('pun', 0.0))}", "奖惩汇总"),
        _metric_card("全局衰减（global_decay）", f(decay.get("global_decay_ratio", 0.0)), "递质衰减比例"),
        _metric_card("通道数（channels）", str(len(keys)), "NT（递质通道）数量"),
        _metric_card("注意力 Top-N（调制）", str(att_mod.get("top_n", "-")), "下一 tick 注意力 Top-N 调制"),
    ]

    channel_rows: list[list[object]] = []
    for ch in keys:
        ch_display = str(labels.get(ch, "") or ch)
        b = float(before.get(ch, 0.0) or 0.0)
        a = float(after.get(ch, 0.0) or 0.0)
        channel_rows.append(
            [
                ch_display,
                f(b),
                f(a),
                f(a - b),
                f(from_cfs.get(ch, 0.0)),
                f(from_script.get(ch, 0.0)),
                f(applied.get(ch, 0.0)),
            ]
        )

    mod_rows: list[list[object]] = []
    if isinstance(att_mod, dict) and att_mod:
        mod_rows.extend(
            [
                ["top_n", att_mod.get("top_n", "-")],
                ["priority_weight_cp_abs", f(att_mod.get("priority_weight_cp_abs", 0.0))],
                ["priority_weight_fatigue", f(att_mod.get("priority_weight_fatigue", 0.0))],
                ["min_total_energy", f(att_mod.get("min_total_energy", 0.0))],
                ["nt_snapshot", str(att_mod.get("nt_snapshot", {}) or {})],
            ]
        )

    return _section(
        "emotion",
        "情绪递质管理（NT 递质通道）",
        "".join(cards)
        + _table(
            "递质通道变化（NT channels）",
            ["通道（channel）", "更新前（before）", "更新后（after）", "变化量（delta）", "来自认知感受（from_cfs）", "来自脚本（from_script）", "最终应用（applied）"],
            channel_rows,
        )
        + _table("调制输出（注意力）", ["键（key）", "值（value）"], mod_rows),
    )


def _render_innate_script_section(innate_script: dict) -> str:
    active = innate_script.get("active_scripts", {}) or {}
    scripts = list(active.get("scripts", []) or [])
    checks = list(innate_script.get("state_window_checks", []) or [])

    focus = innate_script.get("focus", {}) or {}
    directives = list(focus.get("focus_directives", []) or [])
    audit = focus.get("audit", {}) or {}

    cards = [
        _metric_card("script_version", str(active.get("script_version", "-")), "IESM 脚本版本"),
        _metric_card("active_scripts", str(len(scripts)), "启用脚本数量"),
        _metric_card("window_checks", str(len(checks)), "状态窗口检查次数"),
        _metric_card("new_focus_directives", str(len(directives)), "本轮生成注意力聚焦指令（下一 tick 生效）"),
    ]

    script_rows: list[list[object]] = []
    for sc in scripts[:32]:
        script_rows.append([sc.get("script_id", ""), yn(sc.get("enabled", False)), sc.get("kind", "")])

    check_rows: list[list[object]] = []
    for item in checks[:32]:
        stage = item.get("stage", "") or "-"
        if item.get("error"):
            check_rows.append([stage, "error", item.get("error", ""), "", "", ""])
            continue
        summary = item.get("packet_summary", {}) or {}
        check = item.get("check", {}) or {}
        triggered = list(check.get("triggered_scripts", []) or [])
        trigger_ids = ",".join(sc.get("script_id", "") for sc in triggered if sc.get("script_id")) or "无"
        check_rows.append(
            [
                stage,
                str(len(triggered)),
                trigger_ids,
                str(summary.get("fast_cp_rise_item_count", 0)),
                str(summary.get("fast_cp_drop_item_count", 0)),
                str(summary.get("candidate_count", summary.get("candidate_trigger_count", 0))),
            ]
        )

    directive_rows: list[list[object]] = []
    for d in directives[:64]:
        directive_rows.append(
            [
                d.get("directive_id", ""),
                d.get("source_kind", ""),
                f(d.get("strength", 0.0)),
                f(d.get("focus_boost", 0.0)),
                d.get("ttl_ticks", 0),
                d.get("target_display", ""),
                d.get("target_ref_object_type", ""),
                d.get("target_ref_object_id", ""),
                d.get("target_item_id", ""),
            ]
        )

    audit_rows = [[k, str(v)] for k, v in (audit.items() if isinstance(audit, dict) else [])]

    return _section(
        "innate_script",
        "先天编码脚本管理（IESM）",
        "".join(cards)
        + _table("启用脚本", ["script_id", "enabled", "kind"], script_rows)
        + _table(
            "状态窗口检查",
            ["stage", "triggered_count", "triggered_scripts", "fast_cp_rise", "fast_cp_drop", "candidate_count"],
            check_rows,
        )
        + _table(
            "新生成的聚焦指令",
            ["directive_id", "source_kind", "strength", "boost", "ttl", "target_display", "ref_type", "ref_id", "item_id"],
            directive_rows,
        )
        + _table("聚焦审计", ["key", "value"], audit_rows),
    )
