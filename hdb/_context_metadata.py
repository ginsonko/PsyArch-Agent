from __future__ import annotations

from typing import Any


CONTEXT_FIELD_KEYS: tuple[str, ...] = (
    "context_ref_object_id",
    "context_ref_object_type",
    "context_owner_structure_id",
    "context_path_ids",
)

RESIDUAL_FIELD_KEYS: tuple[str, ...] = (
    "residual_origin_kind",
    "residual_origin_entry_id",
)

_ID_PREFIX_TO_OBJECT_TYPE: tuple[tuple[str, str], ...] = (
    ("sa_", "sa"),
    ("csa_", "csa"),
    ("st_", "st"),
    ("sg_", "sg"),
    ("em_", "em"),
    ("spi_", "state_item"),
    ("diff_", "diff_entry"),
    ("srr_", "raw_residual"),
    ("sgr_", "raw_residual"),
)


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value or "").strip()


def normalize_id_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (list, tuple, set)):
        iterable = values
    else:
        iterable = [values]
    out: list[str] = []
    seen: set[str] = set()
    for raw in iterable:
        text = _as_str(raw)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def infer_object_type_from_id(identifier: Any) -> str:
    text = _as_str(identifier)
    for prefix, object_type in _ID_PREFIX_TO_OBJECT_TYPE:
        if text.startswith(prefix):
            return object_type
    return ""


def build_context_metadata(
    *,
    context_ref_object_id: Any = "",
    context_ref_object_type: Any = "",
    context_owner_structure_id: Any = "",
    context_path_ids: Any = None,
    parent_ids: Any = None,
) -> dict[str, Any]:
    path_ids = normalize_id_list(context_path_ids)
    for parent_id in normalize_id_list(parent_ids):
        if parent_id not in path_ids:
            path_ids.append(parent_id)

    owner_id = _as_str(context_owner_structure_id)
    if owner_id and owner_id not in path_ids:
        path_ids.insert(0, owner_id)

    ref_id = _as_str(context_ref_object_id) or (path_ids[0] if path_ids else "")
    ref_type = _as_str(context_ref_object_type) or infer_object_type_from_id(ref_id)

    if not owner_id:
        for candidate in path_ids:
            if infer_object_type_from_id(candidate) == "st":
                owner_id = candidate
                break

    return {
        "context_ref_object_id": ref_id,
        "context_ref_object_type": ref_type,
        "context_owner_structure_id": owner_id,
        "context_path_ids": path_ids,
    }


def extract_context_metadata(payload: dict | None) -> dict[str, Any]:
    payload = _as_dict(payload)
    source = _as_dict(payload.get("source"))
    meta_ext = _as_dict(_as_dict(payload.get("meta")).get("ext"))
    structure_ext = _as_dict(_as_dict(payload.get("structure")).get("ext"))
    ext = _as_dict(payload.get("ext"))

    candidates = (meta_ext, structure_ext, ext, source, payload)
    ref_id = ""
    ref_type = ""
    owner_id = ""
    path_ids: list[str] = []
    for candidate in candidates:
        if not ref_id:
            ref_id = _as_str(candidate.get("context_ref_object_id"))
        if not ref_type:
            ref_type = _as_str(candidate.get("context_ref_object_type"))
        if not owner_id:
            owner_id = _as_str(candidate.get("context_owner_structure_id"))
        if not path_ids:
            path_ids = normalize_id_list(candidate.get("context_path_ids"))

    parent_ids = normalize_id_list(source.get("parent_ids", payload.get("parent_ids", [])))
    if not ref_id and not ref_type and not owner_id and not path_ids and not parent_ids:
        return {
            "context_ref_object_id": "",
            "context_ref_object_type": "",
            "context_owner_structure_id": "",
            "context_path_ids": [],
        }

    if not path_ids:
        path_ids = list(parent_ids)
    else:
        for parent_id in parent_ids:
            if parent_id not in path_ids:
                path_ids.append(parent_id)

    if owner_id and owner_id not in path_ids:
        path_ids.insert(0, owner_id)

    if not ref_id:
        ref_id = path_ids[0] if path_ids else ""
    if not ref_type:
        ref_type = infer_object_type_from_id(ref_id)

    if not owner_id:
        for candidate_id in path_ids:
            if infer_object_type_from_id(candidate_id) == "st":
                owner_id = candidate_id
                break

    return {
        "context_ref_object_id": ref_id,
        "context_ref_object_type": ref_type,
        "context_owner_structure_id": owner_id,
        "context_path_ids": path_ids,
    }


def merge_context_metadata(
    ext: dict | None,
    *,
    context_ref_object_id: Any = "",
    context_ref_object_type: Any = "",
    context_owner_structure_id: Any = "",
    context_path_ids: Any = None,
    parent_ids: Any = None,
) -> dict[str, Any]:
    base = dict(ext or {})
    existing = extract_context_metadata(base)
    context = build_context_metadata(
        context_ref_object_id=_as_str(context_ref_object_id) or existing.get("context_ref_object_id", ""),
        context_ref_object_type=_as_str(context_ref_object_type) or existing.get("context_ref_object_type", ""),
        context_owner_structure_id=_as_str(context_owner_structure_id) or existing.get("context_owner_structure_id", ""),
        context_path_ids=context_path_ids if context_path_ids is not None else existing.get("context_path_ids", []),
        parent_ids=parent_ids if parent_ids is not None else existing.get("context_path_ids", []),
    )
    base.update(context)
    return base


def has_context_metadata(payload: dict | None) -> bool:
    context = extract_context_metadata(payload)
    return bool(
        context.get("context_ref_object_id")
        or context.get("context_owner_structure_id")
        or context.get("context_path_ids")
    )


def context_path_depth(payload: dict | None) -> int:
    context = extract_context_metadata(payload)
    path_ids = normalize_id_list(context.get("context_path_ids", []))
    if path_ids:
        return len(path_ids)
    if context.get("context_ref_object_id") or context.get("context_owner_structure_id"):
        return 1
    return 0


def _infer_residual_kind(*, residual_origin_kind: Any = "", relation_type: Any = "") -> str:
    kind = _as_str(residual_origin_kind)
    if kind:
        return kind
    relation = _as_str(relation_type)
    return relation if "residual" in relation else ""


def build_residual_metadata(
    *,
    residual_origin_kind: Any = "",
    residual_origin_entry_id: Any = "",
    relation_type: Any = "",
) -> dict[str, Any]:
    return {
        "residual_origin_kind": _infer_residual_kind(
            residual_origin_kind=residual_origin_kind,
            relation_type=relation_type,
        ),
        "residual_origin_entry_id": _as_str(residual_origin_entry_id),
    }


def extract_residual_metadata(payload: dict | None) -> dict[str, Any]:
    payload = _as_dict(payload)
    if not payload:
        return {
            "residual_origin_kind": "",
            "residual_origin_entry_id": "",
        }
    meta = payload.get("meta")
    structure = payload.get("structure")
    ext_raw = payload.get("ext")
    meta_ext = _as_dict(_as_dict(meta).get("ext")) if isinstance(meta, dict) else {}
    structure_ext = _as_dict(_as_dict(structure).get("ext")) if isinstance(structure, dict) else {}
    ext = _as_dict(ext_raw) if isinstance(ext_raw, dict) else {}

    residual_origin_kind = ""
    residual_origin_entry_id = ""
    relation_type = ""
    for candidate in (meta_ext, structure_ext, ext, payload):
        if not residual_origin_kind:
            residual_origin_kind = _as_str(candidate.get("residual_origin_kind"))
        if not residual_origin_entry_id:
            residual_origin_entry_id = _as_str(candidate.get("residual_origin_entry_id"))
        if not relation_type:
            relation_type = _as_str(candidate.get("relation_type"))
        if residual_origin_kind and residual_origin_entry_id:
            break

    return {
        "residual_origin_kind": _infer_residual_kind(
            residual_origin_kind=residual_origin_kind,
            relation_type=relation_type,
        ),
        "residual_origin_entry_id": residual_origin_entry_id,
    }


def merge_residual_metadata(
    ext: dict | None,
    *,
    residual_origin_kind: Any = "",
    residual_origin_entry_id: Any = "",
) -> dict[str, Any]:
    base = dict(ext or {})
    existing = extract_residual_metadata(base)
    relation_type = _as_str(base.get("relation_type"))
    residual = build_residual_metadata(
        residual_origin_kind=_as_str(residual_origin_kind) or existing.get("residual_origin_kind", ""),
        residual_origin_entry_id=_as_str(residual_origin_entry_id) or existing.get("residual_origin_entry_id", ""),
        relation_type=relation_type,
    )
    base.update(residual)
    return base


def has_residual_metadata(payload: dict | None) -> bool:
    residual = extract_residual_metadata(payload)
    return bool(residual.get("residual_origin_kind") or residual.get("residual_origin_entry_id"))
