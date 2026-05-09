from __future__ import annotations


def is_attribute_only_structure(structure_obj: dict | None) -> bool:
    if not isinstance(structure_obj, dict):
        return False
    structure_block = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
    if not isinstance(structure_block, dict):
        return False
    groups = structure_block.get("sequence_groups", [])
    tokens_seen = 0
    feature_seen = 0
    if not isinstance(groups, list) or not groups:
        return False
    for group in groups:
        if not isinstance(group, dict):
            continue
        units = group.get("units", [])
        if not isinstance(units, list) or not units:
            return False
        for unit in units:
            if not isinstance(unit, dict):
                continue
            token = str(unit.get("token", "") or "")
            if not token:
                continue
            tokens_seen += 1
            if str(unit.get("unit_role", "") or "") != "attribute":
                feature_seen += 1
    return tokens_seen > 0 and feature_seen == 0


def is_cognitive_stitching_event_structure(structure_obj: dict | None) -> bool:
    if not isinstance(structure_obj, dict):
        return False
    sub_type = str(structure_obj.get("sub_type", "") or "")
    structure_block = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
    signature = str(structure_block.get("content_signature", "") or "")
    return sub_type == "cognitive_stitching_event_structure" or signature.startswith("cs_event::")


def classify_runtime_projection_block_reason(
    structure_obj: dict | None,
    *,
    allow_cs_event_structures: bool = False,
    allow_attribute_only_structures: bool = False,
) -> str:
    if not allow_attribute_only_structures and is_attribute_only_structure(structure_obj):
        return "attribute_only_structure"
    if not allow_cs_event_structures and is_cognitive_stitching_event_structure(structure_obj):
        return "cognitive_stitching_event_structure"
    return ""

