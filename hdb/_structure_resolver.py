# -*- coding: utf-8 -*-
"""
Shared structure id resolution / materialization helpers for HDB.
统一的“查存一体拿结构 id / 必要时建结构”辅助逻辑。
"""

from __future__ import annotations

from typing import Any

from ._context_metadata import extract_context_metadata, merge_context_metadata
from ._profile_restore import restore_profile


_IDENTITY_CONTEXT_KEYS: tuple[str, ...] = (
    "context_ref_object_id",
    "context_ref_object_type",
    "context_owner_structure_id",
    "context_path_ids",
)


def _strip_identity_context_for_context_free(
    ext: dict,
    *,
    parent_ids: list[str] | None = None,
) -> dict:
    out = dict(ext or {})
    owner_id = str(out.get("owner_structure_id", "") or "").strip()
    if owner_id and not out.get("provenance_owner_structure_id"):
        out["provenance_owner_structure_id"] = owner_id
    provenance_parent_ids = [
        str(parent_id or "").strip()
        for parent_id in list(parent_ids or [])
        if str(parent_id or "").strip()
    ]
    if provenance_parent_ids and not out.get("provenance_parent_ids"):
        out["provenance_parent_ids"] = provenance_parent_ids
    for key in (*_IDENTITY_CONTEXT_KEYS, "owner_structure_id"):
        out.pop(key, None)
    return out


def _build_explicit_canonical_profile(profile: dict, *, cut_engine) -> dict | None:
    canonical_groups = list(profile.get("canonical_sequence_groups", []))
    if not canonical_groups:
        return None
    explicit = cut_engine.build_sequence_profile_from_groups(canonical_groups)
    explicit["display_text"] = str(profile.get("canonical_display_text", explicit.get("display_text", "")))
    explicit["flat_tokens"] = list(profile.get("canonical_flat_tokens", explicit.get("flat_tokens", [])))
    return explicit


def _sequence_groups_signature(cut_engine, sequence_groups: list[dict]) -> str:
    if hasattr(cut_engine, "sequence_groups_to_signature"):
        return str(cut_engine.sequence_groups_to_signature(sequence_groups) or "")
    parts: list[str] = []
    for group in sequence_groups:
        if not isinstance(group, dict):
            continue
        tokens = [str(token) for token in list(group.get("tokens", []) or []) if str(token)]
        if not tokens:
            units = [
                str((unit or {}).get("token", "") or "")
                for unit in list(group.get("units", []) or [])
                if isinstance(unit, dict) and str((unit or {}).get("token", "") or "")
            ]
            tokens = units
        parts.append("|".join(tokens))
    return "||".join(parts)


def canonicalize_profile(*, profile: dict, structure_store, cut_engine) -> dict:
    explicit = _build_explicit_canonical_profile(profile, cut_engine=cut_engine)
    if explicit is not None:
        merged_ext = dict(explicit.get("ext", {}))
        merged_ext.update(profile.get("ext", {}))
        merged_ext["restored_from_placeholder"] = True
        explicit["ext"] = merged_ext
        return explicit
    restored = restore_profile(
        profile,
        cut_engine=cut_engine,
        structure_store=structure_store,
        group_store=None,
    )
    if profile.get("display_text") and not restored.get("display_text"):
        restored["display_text"] = str(profile.get("display_text", ""))
    merged_ext = dict(restored.get("ext", {}))
    merged_ext.update(profile.get("ext", {}))
    restored["ext"] = merged_ext
    return restored


def _build_exact_cache_key(
    *,
    signature: str,
    expected_tokens: list[str],
    expected_sequence_groups: list[dict],
    expected_context: dict,
    required_sub_type: str,
    allow_cs_event_structures: bool,
    strict_context_owner_match: bool,
    strict_context_ref_match: bool,
    require_context_free: bool = False,
) -> str:
    seq_parts: list[str] = []
    for group in expected_sequence_groups:
        if not isinstance(group, dict):
            continue
        part = str(group.get("group_signature", "") or group.get("content_signature", "") or "")
        if not part:
            tokens = [str(token) for token in list(group.get("tokens", []) or []) if str(token)]
            if not tokens:
                tokens = [
                    str((unit or {}).get("token", "") or "")
                    for unit in list(group.get("units", []) or [])
                    if isinstance(unit, dict) and str((unit or {}).get("token", "") or "")
                ]
            part = "|".join(tokens)
        if part:
            seq_parts.append(part)
    seq_signature = "||".join(seq_parts)
    token_signature = "|".join(str(token) for token in expected_tokens if str(token))
    return "||".join(
        [
            str(signature or ""),
            str(token_signature or ""),
            str(seq_signature or ""),
            str(expected_context.get("context_owner_structure_id", "") or ""),
            str(expected_context.get("context_ref_object_id", "") or ""),
            str(expected_context.get("context_ref_object_type", "") or ""),
            str(required_sub_type or ""),
            "1" if allow_cs_event_structures else "0",
            "1" if strict_context_owner_match else "0",
            "1" if strict_context_ref_match else "0",
            "1" if require_context_free else "0",
        ]
    )


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _has_context_value(value: Any) -> bool:
    if isinstance(value, (list, tuple, set)):
        return any(str(item or "").strip() for item in value)
    return bool(str(value or "").strip())


def _candidate_has_explicit_context(candidate: dict) -> bool:
    """Return true only for explicit identity context, not source provenance.

    `extract_context_metadata()` deliberately treats `source.parent_ids` as a
    fallback context for older callers. Growth identity resolution needs a
    narrower test: a complete A+B object should be considered context-free when
    it only has provenance parents, and contextual only when one of the actual
    context_* fields is populated.
    """
    if not isinstance(candidate, dict):
        return False
    meta_ext = _as_dict(_as_dict(candidate.get("meta")).get("ext"))
    structure_ext = _as_dict(_as_dict(candidate.get("structure")).get("ext"))
    ext = _as_dict(candidate.get("ext"))
    source = _as_dict(candidate.get("source"))
    for container in (meta_ext, structure_ext, ext, source, candidate):
        if not isinstance(container, dict):
            continue
        if (
            _has_context_value(container.get("context_ref_object_id"))
            or _has_context_value(container.get("context_owner_structure_id"))
            or _has_context_value(container.get("context_path_ids"))
        ):
            return True
    return False


def _candidate_matches_expected_context(
    *,
    candidate: dict,
    expected_context: dict,
    strict_context_owner_match: bool,
    strict_context_ref_match: bool,
    require_context_free: bool = False,
) -> bool:
    if require_context_free:
        return not _candidate_has_explicit_context(candidate)
    if not expected_context:
        return True
    candidate_context = extract_context_metadata(candidate)
    expected_owner = str(expected_context.get("context_owner_structure_id", "") or "")
    candidate_owner = str(candidate_context.get("context_owner_structure_id", "") or "")
    if expected_owner:
        if strict_context_owner_match:
            if candidate_owner != expected_owner:
                return False
        elif candidate_owner and candidate_owner != expected_owner:
            return False

    expected_ref_id = str(expected_context.get("context_ref_object_id", "") or "")
    candidate_ref_id = str(candidate_context.get("context_ref_object_id", "") or "")
    if expected_ref_id:
        if strict_context_ref_match:
            if candidate_ref_id != expected_ref_id:
                return False
        elif candidate_ref_id and candidate_ref_id != expected_ref_id:
            return False

    expected_ref_type = str(expected_context.get("context_ref_object_type", "") or "")
    candidate_ref_type = str(candidate_context.get("context_ref_object_type", "") or "")
    if expected_ref_type:
        if strict_context_ref_match:
            if candidate_ref_type != expected_ref_type:
                return False
        elif candidate_ref_type and candidate_ref_type != expected_ref_type:
            return False
    return True


def find_exact_structure_by_signature(
    *,
    signature: str,
    structure_store,
    pointer_index,
    cut_engine,
    expected_tokens: list[str] | None = None,
    expected_sequence_groups: list[dict] | None = None,
    expected_context: dict | None = None,
    required_sub_type: str = "",
    allow_cs_event_structures: bool = False,
    strict_context_owner_match: bool = False,
    strict_context_ref_match: bool = False,
    require_context_free: bool = False,
) -> dict | None:
    if not signature:
        return None

    tokens = list(expected_tokens or [])
    sequence_groups = list(expected_sequence_groups or [])
    context = dict(expected_context or {})
    cache_key = _build_exact_cache_key(
        signature=signature,
        expected_tokens=tokens,
        expected_sequence_groups=sequence_groups,
        expected_context=context,
        required_sub_type=required_sub_type,
        allow_cs_event_structures=allow_cs_event_structures,
        strict_context_owner_match=strict_context_owner_match,
        strict_context_ref_match=strict_context_ref_match,
        require_context_free=require_context_free,
    )
    cached_id = ""
    if pointer_index is not None and hasattr(pointer_index, "resolve_exact_structure_id"):
        try:
            cached_id = str(pointer_index.resolve_exact_structure_id(cache_key) or "")
        except Exception:
            cached_id = ""
    if cached_id:
        cached_candidate = structure_store.get(cached_id)
        if isinstance(cached_candidate, dict):
            cached_structure = cached_candidate.get("structure", {}) if isinstance(cached_candidate.get("structure", {}), dict) else {}
            if (
                str(cached_structure.get("content_signature", "") or "") == str(signature or "")
                and _candidate_matches_expected_context(
                    candidate=cached_candidate,
                    expected_context=context,
                    strict_context_owner_match=strict_context_owner_match,
                    strict_context_ref_match=strict_context_ref_match,
                    require_context_free=require_context_free,
                )
            ):
                if (not required_sub_type) or str(cached_candidate.get("sub_type", "") or "") == str(required_sub_type or ""):
                    return cached_candidate

    signatures_to_try = [signature]
    if tokens:
        legacy_signature = cut_engine.tokens_to_signature(tokens)
        if legacy_signature and legacy_signature not in signatures_to_try:
            signatures_to_try.append(legacy_signature)
    expected_groups_signature = _sequence_groups_signature(cut_engine, sequence_groups) if sequence_groups else ""
    seen_ids = set()
    for current_signature in signatures_to_try:
        for candidate_id in pointer_index.query_candidates_by_signature(current_signature):
            if candidate_id in seen_ids:
                continue
            seen_ids.add(candidate_id)
            candidate = structure_store.get(candidate_id)
            if not candidate:
                continue
            if required_sub_type and str(candidate.get("sub_type", "") or "") != str(required_sub_type or ""):
                continue
            if (
                (not allow_cs_event_structures)
                and str(candidate.get("sub_type", "") or "") == "cognitive_stitching_event_structure"
            ):
                continue
            structure = candidate.get("structure", {}) if isinstance(candidate.get("structure", {}), dict) else {}
            if str(structure.get("content_signature", "") or "") != str(signature or ""):
                continue
            if tokens and list(structure.get("flat_tokens", [])) != tokens:
                continue
            if expected_groups_signature:
                if hasattr(cut_engine, "build_sequence_profile_from_structure"):
                    candidate_profile = canonicalize_profile(
                        profile=cut_engine.build_sequence_profile_from_structure(candidate),
                        structure_store=structure_store,
                        cut_engine=cut_engine,
                    )
                    candidate_groups = list(candidate_profile.get("sequence_groups", []))
                else:
                    candidate_groups = list(structure.get("sequence_groups", []) or [])
                if _sequence_groups_signature(cut_engine, candidate_groups) != expected_groups_signature:
                    continue
            if not _candidate_matches_expected_context(
                candidate=candidate,
                expected_context=context,
                strict_context_owner_match=strict_context_owner_match,
                strict_context_ref_match=strict_context_ref_match,
                require_context_free=require_context_free,
            ):
                continue
            if pointer_index is not None and hasattr(pointer_index, "cache_exact_structure_id"):
                try:
                    pointer_index.cache_exact_structure_id(cache_key, str(candidate_id))
                except Exception:
                    pass
            return candidate
    return None


def resolve_or_create_structure_from_profile(
    *,
    profile: dict,
    canonical_profile: dict | None = None,
    structure_store,
    pointer_index,
    cut_engine,
    trace_id: str,
    tick_id: str,
    confidence: float,
    origin: str,
    origin_id: str,
    parent_ids: list[str],
    base_weight: float | None = None,
    ext: dict | None = None,
    source_interface: str = "",
    required_sub_type: str = "",
    allow_cs_event_structures: bool = False,
    strict_context_owner_match: bool = False,
    strict_context_ref_match: bool = False,
    require_context_free: bool = False,
    skip_exact_lookup: bool = False,
) -> dict[str, Any]:
    if isinstance(canonical_profile, dict) and canonical_profile.get("sequence_groups"):
        canonical_profile = dict(canonical_profile)
    else:
        canonical_profile = canonicalize_profile(
            profile=profile,
            structure_store=structure_store,
            cut_engine=cut_engine,
        )
    merged_ext = dict(canonical_profile.get("ext", {}))
    merged_ext.update(ext or {})
    effective_parent_ids = list(parent_ids or [])
    if require_context_free:
        merged_ext = _strip_identity_context_for_context_free(
            merged_ext,
            parent_ids=effective_parent_ids,
        )
        effective_parent_ids = []
    else:
        merged_ext = merge_context_metadata(
            merged_ext,
            context_ref_object_id=merged_ext.get("context_ref_object_id", ""),
            context_ref_object_type=merged_ext.get("context_ref_object_type", ""),
            context_owner_structure_id=merged_ext.get("context_owner_structure_id", "") or merged_ext.get("owner_structure_id", ""),
            parent_ids=effective_parent_ids,
        )
    payload = cut_engine.make_structure_payload_from_profile(
        {**dict(canonical_profile), "ext": merged_ext},
        confidence=confidence,
        ext=merged_ext,
    )
    if base_weight is not None:
        payload["base_weight"] = round(float(base_weight), 8)
    signature = str(payload.get("content_signature", "") or "")
    if not bool(skip_exact_lookup):
        existing = find_exact_structure_by_signature(
            signature=signature,
            structure_store=structure_store,
            pointer_index=pointer_index,
            cut_engine=cut_engine,
            expected_tokens=list(payload.get("flat_tokens", [])),
            expected_sequence_groups=list(payload.get("sequence_groups", [])),
            expected_context=extract_context_metadata({"ext": merged_ext}),
            required_sub_type=required_sub_type,
            allow_cs_event_structures=allow_cs_event_structures,
            strict_context_owner_match=strict_context_owner_match,
            strict_context_ref_match=strict_context_ref_match,
            require_context_free=require_context_free,
        )
        if existing:
            return {"created": False, "structure": existing, "canonical_profile": canonical_profile}

    create_kwargs = {
        "structure_payload": payload,
        "trace_id": trace_id,
        "tick_id": tick_id,
        "origin": origin,
        "origin_id": origin_id,
        "parent_ids": effective_parent_ids,
    }
    if source_interface:
        create_kwargs["source_interface"] = source_interface
    structure_obj, _ = structure_store.create_structure(**create_kwargs)
    pointer_index.register_structure(structure_obj)
    exact_context = extract_context_metadata({"ext": merged_ext})
    cache_key = _build_exact_cache_key(
        signature=signature,
        expected_tokens=list(payload.get("flat_tokens", [])),
        expected_sequence_groups=list(payload.get("sequence_groups", [])),
        expected_context=exact_context,
        required_sub_type=required_sub_type,
        allow_cs_event_structures=allow_cs_event_structures,
        strict_context_owner_match=strict_context_owner_match,
        strict_context_ref_match=strict_context_ref_match,
        require_context_free=require_context_free,
    )
    if hasattr(pointer_index, "cache_exact_structure_id"):
        try:
            pointer_index.cache_exact_structure_id(cache_key, str(structure_obj.get("id", "") or ""))
        except Exception:
            pass
    return {"created": True, "structure": structure_obj, "canonical_profile": canonical_profile}


def resolve_or_create_structure_from_units(
    *,
    units: list[dict],
    structure_store,
    pointer_index,
    cut_engine,
    trace_id: str,
    tick_id: str,
    confidence: float,
    origin: str,
    origin_id: str,
    parent_ids: list[str],
    base_weight: float | None = None,
    ext: dict | None = None,
    source_interface: str = "",
    required_sub_type: str = "",
    allow_cs_event_structures: bool = False,
    strict_context_owner_match: bool = False,
    strict_context_ref_match: bool = False,
    require_context_free: bool = False,
    skip_exact_lookup: bool = False,
) -> dict[str, Any]:
    raw_profile = cut_engine.build_sequence_profile_from_groups(
        [
            {
                "group_index": int(group_index),
                "source_type": str(group.get("source_type", "") or ""),
                "origin_frame_id": str(group.get("origin_frame_id", "") or ""),
                "order_sensitive": bool(group.get("order_sensitive", False)),
                "units": [
                    dict(unit)
                    for unit in group.get("units", [])
                    if isinstance(unit, dict)
                ],
            }
            for group_index, group in enumerate(
                [
                    {
                        "group_index": 0,
                        "source_type": "shared_structure_resolver",
                        "origin_frame_id": str(origin_id or trace_id or ""),
                        "units": [dict(unit) for unit in units if isinstance(unit, dict)],
                    }
                ]
            )
        ]
    )
    return resolve_or_create_structure_from_profile(
        profile=raw_profile,
        structure_store=structure_store,
        pointer_index=pointer_index,
        cut_engine=cut_engine,
        trace_id=trace_id,
        tick_id=tick_id,
        confidence=confidence,
        origin=origin,
        origin_id=origin_id,
        parent_ids=parent_ids,
        base_weight=base_weight,
        ext=ext,
        source_interface=source_interface,
        required_sub_type=required_sub_type,
        allow_cs_event_structures=allow_cs_event_structures,
        strict_context_owner_match=strict_context_owner_match,
        strict_context_ref_match=strict_context_ref_match,
        require_context_free=require_context_free,
        skip_exact_lookup=skip_exact_lookup,
    )
