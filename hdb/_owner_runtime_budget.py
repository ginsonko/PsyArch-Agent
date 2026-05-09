# -*- coding: utf-8 -*-
"""
Owner-local runtime candidate budgeting helpers.

These helpers keep full owner DB payloads available in persistence, while
constructing bounded per-tick working sets for expensive retrieval / induction
paths.
"""

from __future__ import annotations

import hashlib
from typing import Any


def owner_runtime_budget_enabled(config: dict) -> bool:
    return bool(config.get("owner_db_runtime_budget_enabled", False))


def owner_persistence_trim_enabled(config: dict) -> bool:
    return bool(config.get("owner_db_persistence_trim_enabled", False))


def build_owner_runtime_candidate_view(
    *,
    entries: list[dict],
    config: dict,
    owner_structure_id: str = "",
    path_kind: str = "",
    tick_id: str = "",
    runtime_salt: str = "",
) -> tuple[list[dict], dict[str, Any]]:
    rows = [entry for entry in list(entries or []) if isinstance(entry, dict)]
    total_count = len(rows)
    if not owner_runtime_budget_enabled(config) or total_count <= 1:
        return rows, {
            "enabled": False,
            "total_count": total_count,
            "selected_count": total_count,
            "recent_selected_count": 0,
            "strong_selected_count": 0,
            "explore_selected_count": 0,
            "dedup_overlap_count": 0,
        }

    recent_budget = _safe_non_negative_int(config.get("owner_db_runtime_recent_budget", 50), 50)
    strong_budget = _safe_non_negative_int(config.get("owner_db_runtime_strong_budget", 28), 28)
    explore_budget = _safe_non_negative_int(config.get("owner_db_runtime_explore_budget", 50), 50)
    if recent_budget <= 0 and strong_budget <= 0 and explore_budget <= 0:
        return rows, {
            "enabled": True,
            "total_count": total_count,
            "selected_count": total_count,
            "recent_selected_count": 0,
            "strong_selected_count": 0,
            "explore_selected_count": 0,
            "dedup_overlap_count": 0,
        }

    selected_ids: set[str] = set()
    selected_rows: list[dict] = []
    selected_sources: dict[str, str] = {}

    def _append(source_name: str, items: list[dict], limit: int) -> int:
        appended = 0
        if limit <= 0:
            return appended
        for entry in items:
            if appended >= limit:
                break
            entry_id = _entry_identity(entry)
            if entry_id in selected_ids:
                continue
            selected_ids.add(entry_id)
            selected_rows.append(entry)
            selected_sources[entry_id] = source_name
            appended += 1
        return appended

    recent_rows = sorted(
        rows,
        key=lambda entry: (
            -_entry_recency_key(entry),
            -_entry_runtime_strength(entry),
            str(entry.get("entry_id", "") or ""),
        ),
    )
    recent_selected = _append("recent", recent_rows, recent_budget)

    remaining_after_recent = [entry for entry in rows if _entry_identity(entry) not in selected_ids]
    strong_rows = sorted(
        remaining_after_recent,
        key=lambda entry: (
            -float(entry.get("base_weight", 0.0) or 0.0),
            -float(entry.get("recent_gain", 1.0) or 1.0),
            float(entry.get("fatigue", 0.0) or 0.0),
            -_entry_recency_key(entry),
            str(entry.get("entry_id", "") or ""),
        ),
    )
    strong_selected = _append("strong", strong_rows, strong_budget)

    remaining_after_strong = [entry for entry in rows if _entry_identity(entry) not in selected_ids]
    explore_rows = _sorted_explore_rows(
        rows=remaining_after_strong,
        owner_structure_id=owner_structure_id,
        path_kind=path_kind,
        tick_id=tick_id,
        runtime_salt=runtime_salt,
    )
    explore_selected = _append("explore", explore_rows, explore_budget)

    if not selected_rows:
        selected_rows = rows

    selected_count = len(selected_rows)
    budget_total = max(0, recent_budget) + max(0, strong_budget) + max(0, explore_budget)
    dedup_overlap_count = max(0, recent_selected + strong_selected + explore_selected - selected_count)
    return selected_rows, {
        "enabled": True,
        "total_count": total_count,
        "selected_count": selected_count,
        "budget_total": budget_total,
        "recent_selected_count": recent_selected,
        "strong_selected_count": strong_selected,
        "explore_selected_count": explore_selected,
        "dedup_overlap_count": dedup_overlap_count,
        "owner_structure_id": str(owner_structure_id or ""),
        "path_kind": str(path_kind or ""),
    }


def _sorted_explore_rows(
    *,
    rows: list[dict],
    owner_structure_id: str,
    path_kind: str,
    tick_id: str,
    runtime_salt: str,
) -> list[dict]:
    seed_prefix = "||".join(
        [
            str(owner_structure_id or ""),
            str(path_kind or ""),
            str(tick_id or ""),
            str(runtime_salt or ""),
        ]
    ).encode("utf-8", errors="ignore")
    seeded_rows: list[tuple[int, str, dict]] = []
    for entry in rows:
        entry_id = str(entry.get("entry_id", "") or "")
        noise = _seeded_order_key(seed_prefix=seed_prefix, entry_id=entry_id)
        seeded_rows.append(
            (
                noise,
                entry_id,
                entry,
            )
        )
    seeded_rows.sort(key=lambda row: (row[0], row[1]))
    return [entry for _, _, entry in seeded_rows]


def _entry_identity(entry: dict) -> str:
    entry_id = str(entry.get("entry_id", "") or "")
    if entry_id:
        return entry_id
    return str(id(entry))


def _entry_runtime_strength(entry: dict) -> float:
    base_weight = float(entry.get("base_weight", 0.0) or 0.0)
    recent_gain = float(entry.get("recent_gain", 1.0) or 1.0)
    fatigue = float(entry.get("fatigue", 0.0) or 0.0)
    return base_weight * recent_gain / (1.0 + max(0.0, fatigue))


def _entry_recency_key(entry: dict) -> int:
    try:
        updated = int(entry.get("last_updated_at", 0) or 0)
    except Exception:
        updated = 0
    try:
        matched = int(entry.get("last_matched_at", 0) or 0)
    except Exception:
        matched = 0
    return max(updated, matched)


def _seeded_order_key(*, seed_prefix: bytes, entry_id: str) -> int:
    entry_bytes = str(entry_id or "").encode("utf-8", errors="ignore")
    digest = hashlib.blake2b(seed_prefix + b"||" + entry_bytes, digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False)


def _safe_non_negative_int(raw_value: Any, fallback: int) -> int:
    try:
        value = int(raw_value or 0)
    except Exception:
        value = int(fallback)
    return max(0, int(value))
