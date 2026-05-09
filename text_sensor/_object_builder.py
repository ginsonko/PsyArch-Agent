# -*- coding: utf-8 -*-
"""
Text sensor object builders.
"""

import time
from typing import Any

from . import __module_name__, __schema_version__
from ._id_generator import next_id


def build_feature_sa(
    char_or_token: str,
    unit_kind: str,
    char_type: str,
    position: int,
    er: float,
    trace_id: str,
    tick_id: str,
    source_type: str = "external_user_input",
    source_id: str = "",
    is_punctuation: bool = False,
    is_whitespace: bool = False,
    is_emoji: bool = False,
    global_sequence_index: int = 0,
    group_index: int = 0,
) -> dict:
    now_ms = int(time.time() * 1000)
    sa_id = next_id("sa_txt")
    cp_delta = er
    cp_abs = abs(cp_delta)
    sub_type = f"text_{unit_kind}"
    effective_group_index = group_index if group_index or global_sequence_index <= 0 else global_sequence_index

    return {
        "id": sa_id,
        "object_type": "sa",
        "sub_type": sub_type,
        "schema_version": __schema_version__,
        "content": {
            "raw": char_or_token,
            "normalized": char_or_token,
            "display": char_or_token,
            "value_type": "discrete",
        },
        "stimulus": {
            "modality": "text",
            "role": "feature",
            "is_anchor": True,
            "group_index": effective_group_index,
            "position_in_group": position,
            "global_sequence_index": global_sequence_index,
        },
        "linguistic": {
            "unit_kind": unit_kind,
            "char_type": char_type,
            "is_punctuation": is_punctuation,
            "is_whitespace": is_whitespace,
            "is_emoji": is_emoji,
        },
        "energy": {
            "er": er,
            "ev": 0.0,
            "ownership_level": "sa",
            "computed_from_children": False,
            "fatigue": 0.0,
            "recency_gain": 1.0,
            "salience_score": er,
            "cognitive_pressure_delta": cp_delta,
            "cognitive_pressure_abs": cp_abs,
            "last_decay_tick": 0,
            "last_decay_at": now_ms,
        },
        "source": {
            "module": __module_name__,
            "interface": "ingest_text",
            "origin": source_type,
            "origin_id": source_id or "",
            "parent_ids": [],
        },
        "trace_id": trace_id,
        "tick_id": tick_id,
        "created_at": now_ms,
        "updated_at": now_ms,
        "status": "active",
        "tags": [],
        "ext": {},
        "meta": {
            "confidence": 1.0,
            "field_registry_version": __schema_version__,
            "debug": {},
            "ext": {},
        },
    }


def build_attribute_sa(
    attribute_name: str,
    attribute_value: float,
    parent_feature_sa_id: str,
    trace_id: str,
    tick_id: str,
    source_type: str = "external_user_input",
    source_id: str = "",
    er: float = 0.0,
    ev: float = 0.0,
    group_index: int = 0,
    global_sequence_index: int = 0,
) -> dict:
    now_ms = int(time.time() * 1000)
    sa_id = next_id("sa_attr")
    cp_delta = er - ev
    cp_abs = abs(cp_delta)

    return {
        "id": sa_id,
        "object_type": "sa",
        "sub_type": "attribute_numerical",
        "schema_version": __schema_version__,
        "content": {
            "raw": f"{attribute_name}:{attribute_value}",
            "normalized": f"{attribute_name}:{attribute_value}",
            "display": f"{attribute_name}:{attribute_value}",
            "value_type": "numerical",
            "attribute_name": attribute_name,
            "attribute_value": attribute_value,
        },
        "stimulus": {
            "modality": "text",
            "role": "attribute",
            "is_anchor": False,
            "group_index": group_index,
            "position_in_group": 0,
            "global_sequence_index": global_sequence_index,
        },
        "linguistic": {
            "unit_kind": "attribute",
            "char_type": "attribute",
            "is_punctuation": False,
            "is_whitespace": False,
            "is_emoji": False,
        },
        "energy": {
            "er": er,
            "ev": ev,
            "ownership_level": "sa",
            "computed_from_children": False,
            "fatigue": 0.0,
            "recency_gain": 1.0,
            "salience_score": max(er, ev),
            "cognitive_pressure_delta": cp_delta,
            "cognitive_pressure_abs": cp_abs,
            "last_decay_tick": 0,
            "last_decay_at": now_ms,
        },
        "source": {
            "module": __module_name__,
            "interface": "ingest_text",
            "origin": source_type,
            "origin_id": source_id or "",
            "parent_ids": [parent_feature_sa_id],
        },
        "trace_id": trace_id,
        "tick_id": tick_id,
        "created_at": now_ms,
        "updated_at": now_ms,
        "status": "active",
        "tags": [],
        "ext": {},
        "meta": {
            "confidence": 1.0,
            "field_registry_version": __schema_version__,
            "debug": {},
            "ext": {},
        },
    }


def build_csa(
    feature_sa: dict,
    attribute_sas: list[dict],
    trace_id: str,
    tick_id: str,
    source_type: str = "external_user_input",
    source_id: str = "",
) -> dict:
    now_ms = int(time.time() * 1000)
    csa_id = next_id("csa_txt")
    all_members = [feature_sa] + attribute_sas
    member_ids = [sa["id"] for sa in all_members]
    unit_kind = feature_sa.get("linguistic", {}).get("unit_kind", "char")
    sub_type = f"text_{unit_kind}_bundle"

    total_er = round(sum(float(sa.get("energy", {}).get("er", 0.0) or 0.0) for sa in all_members), 6)
    total_ev = round(sum(float(sa.get("energy", {}).get("ev", 0.0) or 0.0) for sa in all_members), 6)
    cp_delta = round(total_er - total_ev, 6)
    cp_abs = round(abs(cp_delta), 6)
    ownership_map = [
        {
            "sa_id": sa.get("id", ""),
            "er": round(float(sa.get("energy", {}).get("er", 0.0) or 0.0), 6),
            "ev": round(float(sa.get("energy", {}).get("ev", 0.0) or 0.0), 6),
        }
        for sa in all_members
        if isinstance(sa, dict) and sa.get("id")
    ]

    return {
        "id": csa_id,
        "object_type": "csa",
        "sub_type": sub_type,
        "schema_version": __schema_version__,
        "anchor_sa_id": feature_sa["id"],
        "member_sa_ids": member_ids,
        "content": {
            "display": f"CSA[{feature_sa.get('content', {}).get('display', '?')}]",
            "raw": feature_sa.get("content", {}).get("raw", ""),
        },
        "binding": {
            "binding_type": "same_object_attribute_bundle",
            "match_rule": "full_bundle_match",
            "allow_partial_match": False,
        },
        # CSA 的能量不是独立私有能量，而是成员 SA 的聚合视图（见 通用字段标准.md）。
        "energy": {
            "er": total_er,
            "ev": total_ev,
            "ownership_level": "aggregated_from_sa",
            "computed_from_children": True,
            "fatigue": 0.0,
            "recency_gain": 1.0,
            "salience_score": round(max(total_er, total_ev), 6),
            "cognitive_pressure_delta": cp_delta,
            "cognitive_pressure_abs": cp_abs,
            "last_decay_tick": 0,
            "last_decay_at": now_ms,
        },
        "energy_ownership_map": ownership_map,
        "bundle_summary": {
            "member_count": len(member_ids),
            "display_total_er": total_er,
            "display_total_ev": total_ev,
        },
        "source": {
            "module": __module_name__,
            "interface": "ingest_text",
            "origin": source_type,
            "origin_id": source_id or "",
            "parent_ids": member_ids,
        },
        "trace_id": trace_id,
        "tick_id": tick_id,
        "created_at": now_ms,
        "updated_at": now_ms,
        "status": "active",
        "tags": [],
        "ext": {},
        "meta": {
            "confidence": 1.0,
            "field_registry_version": __schema_version__,
            "debug": {},
            "ext": {},
        },
    }


def build_sensor_frame(
    input_text: str,
    normalized_text: str,
    segmentation_mode: str,
    sa_list: list[dict],
    csa_list: list[dict],
    trace_id: str,
    tick_id: str,
    source_type: str = "external_user_input",
    source_id: str = "",
    frame_no: int = 0,
) -> dict:
    now_ms = int(time.time() * 1000)
    sf_id = next_id("sf_text")

    return {
        "id": sf_id,
        "object_type": "sensor_frame",
        "sub_type": "text_sensor_frame",
        "schema_version": __schema_version__,
        "frame_no": frame_no,
        "input_text": input_text,
        "normalized_text": normalized_text,
        "segmentation_mode": segmentation_mode,
        "sa_ids": [sa["id"] for sa in sa_list],
        "csa_ids": [csa["id"] for csa in csa_list],
        "trace_id": trace_id,
        "tick_id": tick_id,
        "created_at": now_ms,
        "updated_at": now_ms,
        "source": {
            "module": __module_name__,
            "interface": "ingest_text",
            "origin": source_type,
            "origin_id": source_id or "",
            "parent_ids": [],
        },
        "status": "active",
        "ext": {},
        "meta": {
            "confidence": 1.0,
            "field_registry_version": __schema_version__,
            "debug": {},
            "ext": {},
        },
    }


def build_echo_frame(
    origin_frame: dict,
    sa_items: list[dict],
    csa_items: list[dict],
    round_created: int,
    trace_id: str,
    tick_id: str,
) -> dict:
    now_ms = int(time.time() * 1000)
    echo_id = next_id("echo_text")
    total_er = sum(sa["energy"]["er"] for sa in sa_items)
    total_ev = sum(sa["energy"]["ev"] for sa in sa_items)

    return {
        "id": echo_id,
        "object_type": "sensor_frame",
        "sub_type": "text_echo_frame",
        "schema_version": __schema_version__,
        "origin_frame_id": origin_frame["id"],
        "round_created": round_created,
        "round_last_updated": round_created,
        "remaining_rounds_hint": 0,
        "decay_count": 0,
        "sa_items": sa_items,
        "csa_items": csa_items,
        "energy_summary": {
            "total_er": total_er,
            "total_ev": total_ev,
            "ownership_level": "aggregated_from_sa",
        },
        "source": {
            "module": __module_name__,
            "interface": "ingest_text",
            "origin": "sensor_echo",
            "origin_id": origin_frame["id"],
            "parent_ids": [origin_frame["id"]],
        },
        "trace_id": trace_id,
        "tick_id": tick_id,
        "created_at": now_ms,
        "updated_at": now_ms,
        "status": "active",
        "ext": {},
        "meta": {
            "confidence": 1.0,
            "field_registry_version": __schema_version__,
            "debug": {},
            "ext": {},
        },
    }


def build_stimulus_packet(
    current_frame: dict,
    current_sa_items: list[dict],
    current_csa_items: list[dict],
    echo_frames: list[dict],
    trace_id: str,
    tick_id: str,
    include_echo_in_objects: bool = True,
    goal_b_char_sa_string_mode: bool = False,
) -> dict:
    now_ms = int(time.time() * 1000)
    pkt_id = next_id("spkt")

    current_all_sa = list(current_sa_items)
    current_all_csa = list(current_csa_items)
    echo_all_sa: list[dict] = []
    echo_all_csa: list[dict] = []
    grouped_sequences: list[dict] = []

    def annotate_member(
        member: dict,
        *,
        source_type: str,
        group_index: int,
        source_group_index: int,
        origin_frame_id: str,
        echo_depth: int,
        round_created: int,
        decay_count: int,
        sequence_index: int,
        order_sensitive: bool = False,
        string_unit_kind: str = "",
        string_token_text: str = "",
    ) -> None:
        ext = member.setdefault("ext", {})
        ext["packet_context"] = {
            "source_type": source_type,
            "group_index": group_index,
            "source_group_index": source_group_index,
            "origin_frame_id": origin_frame_id,
            "echo_depth": echo_depth,
            "round_created": round_created,
            "decay_count": decay_count,
            "sequence_index": sequence_index,
            "order_sensitive": bool(order_sensitive),
            "string_unit_kind": str(string_unit_kind or ""),
            "string_token_text": str(string_token_text or ""),
        }

    def build_frame_groups(
        *,
        sa_items: list[dict],
        csa_items: list[dict],
        source_type: str,
        origin_frame_id: str,
        echo_depth: int,
        round_created: int,
        decay_count: int,
        start_group_index: int,
    ) -> list[dict]:
        feature_sas = [
            sa for sa in sa_items
            if sa.get("stimulus", {}).get("role") == "feature"
        ]
        feature_sas.sort(
            key=lambda sa: (
                int(sa.get("stimulus", {}).get("group_index", 0)),
                int(sa.get("stimulus", {}).get("global_sequence_index", 0)),
                int(sa.get("stimulus", {}).get("position_in_group", 0)),
            )
        )

        attribute_map: dict[str, list[dict]] = {}
        for sa in sa_items:
            if sa.get("stimulus", {}).get("role") != "attribute":
                continue
            parent_ids = list((sa.get("source", {}) or {}).get("parent_ids", []))
            if not parent_ids:
                continue
            attribute_map.setdefault(str(parent_ids[0]), []).append(sa)

        csa_map: dict[str, list[dict]] = {}
        for csa in csa_items:
            anchor_id = str(csa.get("anchor_sa_id", "") or "")
            if not anchor_id:
                continue
            csa_map.setdefault(anchor_id, []).append(csa)

        frame_groups = []
        packet_group_index = start_group_index

        if goal_b_char_sa_string_mode and feature_sas:
            group_feature_sas = list(feature_sas)
            string_token_text = "".join(
                str(sa.get("content", {}).get("raw", sa.get("content", {}).get("display", "")) or "")
                for sa in group_feature_sas
            )
            grouped_sa_ids: list[str] = []
            grouped_csa_ids: list[str] = []
            for seq_index, feature_sa in enumerate(group_feature_sas):
                anchor_id = str(feature_sa.get("id", ""))
                if not anchor_id:
                    continue
                grouped_sa_ids.append(anchor_id)
                annotate_member(
                    feature_sa,
                    source_type=source_type,
                    group_index=packet_group_index,
                    source_group_index=0,
                    origin_frame_id=origin_frame_id,
                    echo_depth=echo_depth,
                    round_created=round_created,
                    decay_count=decay_count,
                    sequence_index=seq_index,
                    order_sensitive=True,
                    string_unit_kind="char_sequence",
                    string_token_text=string_token_text,
                )
                group_attrs = sorted(
                    attribute_map.get(anchor_id, []),
                    key=lambda sa: (
                        int(sa.get("stimulus", {}).get("global_sequence_index", 0)),
                        int(sa.get("created_at", 0)),
                    ),
                )
                for attr_offset, attr_sa in enumerate(group_attrs, start=1):
                    grouped_sa_ids.append(str(attr_sa.get("id", "")))
                    annotate_member(
                        attr_sa,
                        source_type=source_type,
                        group_index=packet_group_index,
                        source_group_index=0,
                        origin_frame_id=origin_frame_id,
                        echo_depth=echo_depth,
                        round_created=round_created,
                        decay_count=decay_count,
                        sequence_index=seq_index * 1000 + attr_offset,
                        order_sensitive=True,
                        string_unit_kind="char_sequence",
                        string_token_text=string_token_text,
                    )
                group_csas = sorted(csa_map.get(anchor_id, []), key=lambda csa: int(csa.get("created_at", 0)))
                for csa_offset, csa in enumerate(group_csas, start=1):
                    grouped_csa_ids.append(str(csa.get("id", "")))
                    annotate_member(
                        csa,
                        source_type=source_type,
                        group_index=packet_group_index,
                        source_group_index=0,
                        origin_frame_id=origin_frame_id,
                        echo_depth=echo_depth,
                        round_created=round_created,
                        decay_count=decay_count,
                        sequence_index=seq_index * 1000 + 500 + csa_offset,
                        order_sensitive=True,
                        string_unit_kind="char_sequence",
                        string_token_text=string_token_text,
                    )
            frame_groups.append(
                {
                    "group_index": packet_group_index,
                    "source_type": source_type,
                    "origin_frame_id": origin_frame_id,
                    "source_group_index": 0,
                    "sa_ids": [sid for sid in grouped_sa_ids if sid],
                    "csa_ids": [cid for cid in grouped_csa_ids if cid],
                    "order_sensitive": True,
                    "string_unit_kind": "char_sequence",
                    "string_token_text": string_token_text,
                }
            )
            return frame_groups

        for feature_sa in feature_sas:
            anchor_id = str(feature_sa.get("id", ""))
            source_group_index = int(feature_sa.get("stimulus", {}).get("group_index", 0))
            group_attrs = sorted(
                attribute_map.get(anchor_id, []),
                key=lambda sa: (
                    int(sa.get("stimulus", {}).get("global_sequence_index", 0)),
                    int(sa.get("created_at", 0)),
                ),
            )
            group_csas = sorted(
                csa_map.get(anchor_id, []),
                key=lambda csa: int(csa.get("created_at", 0)),
            )

            annotate_member(
                feature_sa,
                source_type=source_type,
                group_index=packet_group_index,
                source_group_index=source_group_index,
                origin_frame_id=origin_frame_id,
                echo_depth=echo_depth,
                round_created=round_created,
                decay_count=decay_count,
                sequence_index=0,
            )
            for attr_index, attr_sa in enumerate(group_attrs, start=1):
                annotate_member(
                    attr_sa,
                    source_type=source_type,
                    group_index=packet_group_index,
                    source_group_index=source_group_index,
                    origin_frame_id=origin_frame_id,
                    echo_depth=echo_depth,
                    round_created=round_created,
                    decay_count=decay_count,
                    sequence_index=attr_index,
                )
            for csa_index, csa in enumerate(group_csas, start=1 + len(group_attrs)):
                annotate_member(
                    csa,
                    source_type=source_type,
                    group_index=packet_group_index,
                    source_group_index=source_group_index,
                    origin_frame_id=origin_frame_id,
                    echo_depth=echo_depth,
                    round_created=round_created,
                    decay_count=decay_count,
                    sequence_index=csa_index,
                )

            frame_groups.append(
                {
                    "group_index": packet_group_index,
                    "source_type": source_type,
                    "origin_frame_id": origin_frame_id,
                    "source_group_index": source_group_index,
                    "sa_ids": [anchor_id],
                    "csa_ids": [csa.get("id", "") for csa in group_csas if csa.get("id")],
                }
            )
            packet_group_index += 1

        return frame_groups

    echo_frame_ids = []
    next_group_index = 0
    for echo_depth, echo_frame in enumerate(echo_frames, start=1):
        echo_frame_ids.append(echo_frame["id"])
        frame_groups = build_frame_groups(
            sa_items=echo_frame.get("sa_items", []),
            csa_items=echo_frame.get("csa_items", []),
            source_type="echo",
            origin_frame_id=echo_frame["id"],
            echo_depth=echo_depth,
            round_created=int(echo_frame.get("round_created", 0)),
            decay_count=int(echo_frame.get("decay_count", 0)),
            start_group_index=next_group_index,
        )
        grouped_sequences.extend(frame_groups)
        next_group_index += len(frame_groups)
        echo_all_sa.extend(echo_frame.get("sa_items", []))
        echo_all_csa.extend(echo_frame.get("csa_items", []))

    current_groups = build_frame_groups(
        sa_items=current_sa_items,
        csa_items=current_csa_items,
        source_type="current",
        origin_frame_id=current_frame["id"],
        echo_depth=0,
        round_created=int(current_frame.get("frame_no", 0)),
        decay_count=0,
        start_group_index=next_group_index,
    )
    grouped_sequences.extend(current_groups)

    packet_sa_items = echo_all_sa + current_all_sa if include_echo_in_objects else current_all_sa
    packet_csa_items = echo_all_csa + current_all_csa if include_echo_in_objects else current_all_csa
    current_total_er = sum(sa["energy"]["er"] for sa in current_all_sa)
    current_total_ev = sum(sa["energy"]["ev"] for sa in current_all_sa)
    echo_total_er = sum(sa["energy"]["er"] for sa in echo_all_sa)
    echo_total_ev = sum(sa["energy"]["ev"] for sa in echo_all_sa)
    parent_ids = [current_frame["id"]] + echo_frame_ids

    return {
        "id": pkt_id,
        "object_type": "stimulus_packet",
        "sub_type": "text_external_stimulus_packet",
        "schema_version": __schema_version__,
        "packet_type": "external_text",
        "current_frame_id": current_frame["id"],
        "echo_frame_ids": echo_frame_ids,
        "sa_items": packet_sa_items,
        "csa_items": packet_csa_items,
        "echo_frames": echo_frames,
        "grouped_sa_sequences": grouped_sequences,
        "energy_summary": {
            "total_er": round(current_total_er, 6),
            "total_ev": round(current_total_ev, 6),
            "current_total_er": round(current_total_er, 6),
            "current_total_ev": round(current_total_ev, 6),
            "echo_total_er": round(echo_total_er, 6),
            "echo_total_ev": round(echo_total_ev, 6),
            "combined_context_er": round(current_total_er + echo_total_er, 6),
            "combined_context_ev": round(current_total_ev + echo_total_ev, 6),
            "ownership_level": "sa",
            "echo_merged_into_objects": include_echo_in_objects,
        },
        "trace_id": trace_id,
        "tick_id": tick_id,
        "created_at": now_ms,
        "updated_at": now_ms,
        "source": {
            "module": __module_name__,
            "interface": "build_stimulus_packet",
            "origin": "sensor_frame_and_echo",
            "origin_id": current_frame["id"],
            "parent_ids": parent_ids,
        },
        "status": "active",
        "ext": {},
        "meta": {
            "confidence": 1.0,
            "field_registry_version": __schema_version__,
            "debug": {},
            "ext": {},
        },
    }
