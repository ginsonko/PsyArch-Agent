# -*- coding: utf-8 -*-
"""Stable semantic identity helpers shared by runtime modules."""

from __future__ import annotations

from typing import Any


def normalize_identity_fragment(value: Any) -> str:
    text = "" if value is None else str(value)
    return " ".join(text.strip().split())


def semantic_context_key_from_parts(
    *,
    semantic_signature: Any = "",
    context_ref_object_id: Any = "",
    context_ref_object_type: Any = "",
    context_owner_id: Any = "",
    context_text: Any = "",
    role: Any = "",
    attribute_name: Any = "",
) -> str:
    """Return an identity key for "same feature under same context".

    Empty context is intentional state, so it is encoded as <none> rather than
    omitted. This lets context-free duplicated SA merge while preserving
    different contextual objects.
    """
    signature = normalize_identity_fragment(semantic_signature)
    if not signature:
        return ""
    ctx_ref = normalize_identity_fragment(context_ref_object_id)
    ctx_type = normalize_identity_fragment(context_ref_object_type)
    ctx_owner = normalize_identity_fragment(context_owner_id)
    ctx_text = normalize_identity_fragment(context_text)
    role_text = normalize_identity_fragment(role)
    attr_text = normalize_identity_fragment(attribute_name)
    context_part = "|".join(
        [
            f"ref_type={ctx_type or '<none>'}",
            f"ref={ctx_ref or '<none>'}",
            f"owner={ctx_owner or '<none>'}",
            f"text={ctx_text or '<none>'}",
        ]
    )
    role_part = f"role={role_text or '<none>'}|attr={attr_text or '<none>'}"
    return f"semctx|{signature}|{context_part}|{role_part}"


def semantic_context_key_from_item(item: dict | None) -> str:
    if not isinstance(item, dict):
        return ""
    ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
    return semantic_context_key_from_parts(
        semantic_signature=item.get("semantic_signature", ""),
        context_ref_object_id=(
            item.get("context_ref_object_id", "")
            or ref_snapshot.get("context_ref_object_id", "")
        ),
        context_ref_object_type=(
            item.get("context_ref_object_type", "")
            or ref_snapshot.get("context_ref_object_type", "")
        ),
        context_owner_id=(
            item.get("context_owner_structure_id", "")
            or item.get("context_owner_id", "")
            or ref_snapshot.get("context_owner_id", "")
        ),
        context_text=item.get("context_text", "") or ref_snapshot.get("context_text", ""),
        role=item.get("role", "") or ref_snapshot.get("role", ""),
        attribute_name=item.get("attribute_name", "") or ref_snapshot.get("attribute_name", ""),
    )
