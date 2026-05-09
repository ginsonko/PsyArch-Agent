# -*- coding: utf-8 -*-
"""
Helpers for restoring placeholder-based residual profiles into canonical profiles.
"""

from __future__ import annotations

import re


SELF_PLACEHOLDER_RE = re.compile(r"^SELF\[(?P<owner_id>[^:\]]+):(?P<label>.*)\]$")


def parse_self_placeholder(token: str) -> dict | None:
    match = SELF_PLACEHOLDER_RE.match(str(token or ""))
    if not match:
        return None
    return {
        "owner_id": str(match.group("owner_id") or ""),
        "label": str(match.group("label") or ""),
    }


def restore_structure_profile(
    structure_obj: dict,
    *,
    cut_engine,
    structure_store,
    group_store=None,
    max_depth: int = 12,
    _cache: dict | None = None,
    _visited: set[str] | None = None,
) -> dict:
    if not structure_obj:
        return {
            "display_text": "",
            "flat_tokens": [],
            "sequence_groups": [],
            "member_refs": [],
            "content_signature": "",
            "ext": {},
        }
    base_profile = cut_engine.build_sequence_profile_from_structure(structure_obj)
    return restore_profile(
        base_profile,
        cut_engine=cut_engine,
        structure_store=structure_store,
        group_store=group_store,
        max_depth=max_depth,
        _cache=_cache,
        _visited=_visited,
    )


def restore_group_profile(
    group_obj: dict,
    *,
    cut_engine,
    structure_store,
    group_store=None,
    max_depth: int = 12,
    _cache: dict | None = None,
    _visited: set[str] | None = None,
) -> dict:
    if not group_obj:
        return {
            "display_text": "",
            "flat_tokens": [],
            "sequence_groups": [],
            "member_refs": [],
            "content_signature": "",
            "ext": {},
        }

    cache = _cache if isinstance(_cache, dict) else {}
    visited = set(_visited or set())
    group_id = str(group_obj.get("id", "") or "")
    if group_id:
        visited.add(group_id)
    return _build_group_profile(
        group_obj,
        cut_engine=cut_engine,
        structure_store=structure_store,
        group_store=group_store,
        cache=cache,
        visited=visited,
        depth=0,
        max_depth=max_depth,
    )


def restore_profile(
    profile: dict,
    *,
    cut_engine,
    structure_store,
    group_store=None,
    max_depth: int = 12,
    _cache: dict | None = None,
    _visited: set[str] | None = None,
) -> dict:
    cache = _cache if isinstance(_cache, dict) else {}
    visited = set(_visited or set())
    normalized = cut_engine.build_sequence_profile_from_groups(profile.get("sequence_groups", []))
    merged_ext = dict(normalized.get("ext", {}))
    merged_ext.update(profile.get("ext", {}))

    restored_groups, used_placeholder = _restore_groups(
        list(normalized.get("sequence_groups", [])),
        cut_engine=cut_engine,
        structure_store=structure_store,
        group_store=group_store,
        cache=cache,
        visited=visited,
        depth=0,
        max_depth=max_depth,
    )
    if not used_placeholder:
        normalized["ext"] = merged_ext
        if profile.get("display_text"):
            normalized["display_text"] = str(profile.get("display_text", ""))
        return normalized

    rebuilt_groups = _reindex_groups(restored_groups)
    restored = cut_engine.build_sequence_profile_from_groups(rebuilt_groups)
    restored_ext = dict(restored.get("ext", {}))
    restored_ext.update(merged_ext)
    restored_ext["restored_from_placeholder"] = True
    restored["ext"] = restored_ext
    if profile.get("display_text") and not restored.get("display_text"):
        restored["display_text"] = str(profile.get("display_text", ""))
    return restored


def _restore_groups(
    groups: list[dict],
    *,
    cut_engine,
    structure_store,
    group_store,
    cache: dict,
    visited: set[str],
    depth: int,
    max_depth: int,
) -> tuple[list[dict], bool]:
    if depth >= max_depth:
        return _clone_groups(groups), False

    restored_groups: list[dict] = []
    used_placeholder = False

    for group in groups:
        units = sorted(
            [dict(unit) for unit in group.get("units", []) if isinstance(unit, dict)],
            key=lambda item: int(item.get("sequence_index", 0)),
        )
        buffer_units: list[dict] = []

        for unit in units:
            placeholder = parse_self_placeholder(str(unit.get("token", "")))
            if not placeholder:
                buffer_units.append(dict(unit))
                continue

            owner_groups = _resolve_owner_groups(
                owner_id=placeholder.get("owner_id", ""),
                label=placeholder.get("label", ""),
                cut_engine=cut_engine,
                structure_store=structure_store,
                group_store=group_store,
                cache=cache,
                visited=visited,
                depth=depth + 1,
                max_depth=max_depth,
                fallback_unit=unit,
            )
            if buffer_units:
                restored_groups.append(_make_buffer_group(group, buffer_units))
                buffer_units = []
            restored_groups.extend(owner_groups)
            used_placeholder = True

        if buffer_units:
            restored_groups.append(_make_buffer_group(group, buffer_units))

    return restored_groups, used_placeholder


def _resolve_owner_groups(
    *,
    owner_id: str,
    label: str,
    cut_engine,
    structure_store,
    group_store,
    cache: dict,
    visited: set[str],
    depth: int,
    max_depth: int,
    fallback_unit: dict,
) -> list[dict]:
    if not owner_id:
        return [_make_fallback_group(fallback_unit, label)]
    if owner_id in cache:
        return _clone_groups(cache[owner_id])
    if owner_id in visited or depth >= max_depth:
        return [_make_fallback_group(fallback_unit, label or owner_id)]

    next_visited = set(visited)
    next_visited.add(owner_id)

    profile = None
    if owner_id.startswith("st_"):
        structure_obj = structure_store.get(owner_id) if structure_store is not None else None
        if structure_obj:
            profile = restore_structure_profile(
                structure_obj,
                cut_engine=cut_engine,
                structure_store=structure_store,
                group_store=group_store,
                max_depth=max_depth,
                _cache=cache,
                _visited=next_visited,
            )
    elif owner_id.startswith("sg"):
        group_obj = group_store.get(owner_id) if group_store is not None else None
        if group_obj:
            profile = _build_group_profile(
                group_obj,
                cut_engine=cut_engine,
                structure_store=structure_store,
                group_store=group_store,
                cache=cache,
                visited=next_visited,
                depth=depth,
                max_depth=max_depth,
            )

    if not profile or not profile.get("sequence_groups"):
        return [_make_fallback_group(fallback_unit, label or owner_id)]

    owner_groups = _clone_groups(profile.get("sequence_groups", []))
    cache[owner_id] = owner_groups
    return _clone_groups(owner_groups)


def _build_group_profile(
    group_obj: dict,
    *,
    cut_engine,
    structure_store,
    group_store,
    cache: dict,
    visited: set[str],
    depth: int,
    max_depth: int,
) -> dict:
    group_structure = group_obj.get("group_structure", {})
    if group_structure.get("sequence_groups"):
        return restore_profile(
            {
                "display_text": group_structure.get("display_text", ""),
                "flat_tokens": list(group_structure.get("flat_tokens", [])),
                "sequence_groups": list(group_structure.get("sequence_groups", [])),
                "member_refs": [],
                "ext": dict(group_structure.get("ext", {})),
            },
            cut_engine=cut_engine,
            structure_store=structure_store,
            group_store=group_store,
            max_depth=max_depth,
            _cache=cache,
            _visited=visited,
        )

    combined_groups: list[dict] = []
    for structure_id in group_obj.get("required_structure_ids", []):
        structure_obj = structure_store.get(str(structure_id)) if structure_store is not None else None
        if not structure_obj:
            continue
        child_profile = restore_structure_profile(
            structure_obj,
            cut_engine=cut_engine,
            structure_store=structure_store,
            group_store=group_store,
            max_depth=max_depth,
            _cache=cache,
            _visited=visited,
        )
        combined_groups.extend(_clone_groups(child_profile.get("sequence_groups", [])))

    if not combined_groups:
        return {
            "display_text": str(group_obj.get("id", "")),
            "flat_tokens": [],
            "sequence_groups": [],
            "member_refs": [],
            "content_signature": "",
            "ext": {},
        }

    restored_groups = _reindex_groups(combined_groups)
    profile = cut_engine.build_sequence_profile_from_groups(restored_groups)
    profile["ext"] = {
        **dict(profile.get("ext", {})),
        "restored_from_placeholder": True,
        "group_id": str(group_obj.get("id", "")),
    }
    return profile


def _make_buffer_group(source_group: dict, units: list[dict]) -> dict:
    member_ids = {str(unit.get("unit_id", "")) for unit in units if str(unit.get("unit_id", ""))}
    bundles = []
    for bundle in source_group.get("csa_bundles", []):
        bundle_members = {str(member_id) for member_id in bundle.get("member_unit_ids", []) if str(member_id)}
        if bundle_members and bundle_members.issubset(member_ids):
            bundles.append(dict(bundle))
    return {
        "group_index": int(source_group.get("group_index", 0)),
        "source_type": str(source_group.get("source_type", "")),
        "origin_frame_id": str(source_group.get("origin_frame_id", "")),
        "source_group_index": int(source_group.get("source_group_index", source_group.get("group_index", 0))),
        "units": [dict(unit) for unit in units],
        "csa_bundles": bundles,
    }


def _make_fallback_group(unit: dict, label: str) -> dict:
    fallback_unit = dict(unit)
    fallback_unit["token"] = str(label or unit.get("display_text", "") or unit.get("token", ""))
    fallback_unit["display_text"] = str(fallback_unit.get("token", ""))
    fallback_unit["unit_role"] = "feature"
    fallback_unit["is_placeholder"] = False
    fallback_unit["display_visible"] = True
    fallback_unit["unit_signature"] = f"R:{fallback_unit.get('token', '')}"
    return {
        "group_index": int(unit.get("group_index", 0)),
        "source_type": str(unit.get("source_type", "")),
        "origin_frame_id": str(unit.get("origin_frame_id", "")),
        "source_group_index": int(unit.get("source_group_index", unit.get("group_index", 0))),
        "units": [fallback_unit],
        "csa_bundles": [],
    }


def _reindex_groups(groups: list[dict]) -> list[dict]:
    reindexed = []
    for order_index, group in enumerate(groups):
        units = []
        for sequence_index, unit in enumerate(group.get("units", [])):
            normalized_unit = dict(unit)
            normalized_unit["group_index"] = order_index
            normalized_unit["sequence_index"] = sequence_index
            normalized_unit["source_group_index"] = int(
                normalized_unit.get("source_group_index", group.get("source_group_index", order_index))
            )
            units.append(normalized_unit)
        reindexed.append(
            {
                "group_index": order_index,
                "source_type": str(group.get("source_type", "")),
                "origin_frame_id": str(group.get("origin_frame_id", "")),
                "source_group_index": int(group.get("source_group_index", group.get("group_index", order_index))),
                "units": units,
                "csa_bundles": [dict(bundle) for bundle in group.get("csa_bundles", [])],
            }
        )
    return reindexed


def _clone_groups(groups: list[dict]) -> list[dict]:
    return [
        {
            "group_index": int(group.get("group_index", 0)),
            "source_type": str(group.get("source_type", "")),
            "origin_frame_id": str(group.get("origin_frame_id", "")),
            "source_group_index": int(group.get("source_group_index", group.get("group_index", 0))),
            "units": [dict(unit) for unit in group.get("units", []) if isinstance(unit, dict)],
            "csa_bundles": [dict(bundle) for bundle in group.get("csa_bundles", [])],
        }
        for group in groups
        if isinstance(group, dict)
    ]
