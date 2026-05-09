# -*- coding: utf-8 -*-

from hdb._sequence_display import format_semantic_sequence_groups


def _sa(unit_id: str, token: str, seq: int, *, role: str = "feature", attribute_name: str = "", attribute_value=None) -> dict:
    return {
        "unit_id": unit_id,
        "token": token,
        "display_text": token,
        "sequence_index": seq,
        "unit_role": role,
        "role": role,
        "attribute_name": attribute_name,
        "attribute_value": attribute_value,
        "object_type": "sa",
    }


def _stimulus_group(group_index: int, units: list[dict], bundles: list[dict] | None = None) -> dict:
    return {
        "group_index": group_index,
        "source_type": "current",
        "origin_frame_id": f"frame_{group_index}",
        "units": units,
        "csa_bundles": bundles or [],
    }


def _structure_unit(structure_id: str, nested_groups: list[dict], seq: int = 0) -> dict:
    return {
        "unit_id": structure_id,
        "object_type": "st",
        "unit_signature": f"ST:{structure_id}",
        "sequence_index": seq,
        "structure_display_text": structure_id,
        "structure_grouped_display_text": "",
        "structure_sequence_groups": nested_groups,
    }


def test_semantic_sequence_display_renders_stimulus_groups_with_csa_relations():
    group0 = _stimulus_group(
        0,
        [
            _sa("u_you", "你", 0),
            _sa("u_intensity", "stimulus_intensity:1.1", 1, role="attribute", attribute_name="stimulus_intensity", attribute_value=1.1),
        ],
        bundles=[
            {
                "bundle_id": "b_you_intensity",
                "anchor_unit_id": "u_you",
                "member_unit_ids": ["u_you", "u_intensity"],
            }
        ],
    )
    group1 = _stimulus_group(1, [_sa("u_is", "是", 0)])

    rendered = format_semantic_sequence_groups([group0, group1], context="stimulus")

    assert rendered == "{你 + stimulus_intensity:1.1 + (你 + stimulus_intensity:1.1)} || {是}"
    assert "[" not in rendered


def test_semantic_sequence_display_renders_structure_groups_without_double_braces():
    who = _structure_unit("st_who", [_stimulus_group(0, [_sa("who", "谁", 0)])], seq=0)
    is_ = _structure_unit("st_is", [_stimulus_group(0, [_sa("is", "是", 0)])], seq=1)
    silver = _structure_unit("st_silver", [_stimulus_group(0, [_sa("silver", "银子", 0)])], seq=0)

    rendered = format_semantic_sequence_groups(
        [
            {
                "group_index": 0,
                "source_type": "group",
                "origin_frame_id": "sg_demo",
                "units": [who, is_],
                "csa_bundles": [],
            },
            {
                "group_index": 1,
                "source_type": "group",
                "origin_frame_id": "sg_demo",
                "units": [silver],
                "csa_bundles": [],
            },
        ],
        context="structure",
    )

    assert rendered == "{[{谁}] / [{是}]} || {[{银子}]}"
    assert "{{" not in rendered
    assert "}}" not in rendered
