# -*- coding: utf-8 -*-
"""
Pointer index and bounded fallback lookup for HDB.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict, defaultdict
from typing import Any

from ._numeric_match import (
    coerce_numeric_value,
    describe_numeric_match as build_numeric_match,
    numeric_match_tolerance,
)


class PointerIndex:
    def __init__(self, config: dict):
        self._config = config
        self._primary_map: dict[str, str] = {}
        self._fallback_map: dict[str, str] = {}
        self._signature_index: defaultdict[str, list[str]] = defaultdict(list)
        self._recent_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._exact_lookup_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._numeric_families: dict[str, dict[str, Any]] = {}
        self._numeric_dirty_families: set[str] = set()

    def update_config(self, config: dict) -> None:
        self._config = config
        self._trim_recent_cache()
        self._trim_exact_lookup_cache()
        for family in list(self._numeric_families):
            self._rebuild_numeric_family(family)

    def register_structure(self, structure_obj: dict) -> None:
        structure_id = structure_obj.get("id", "")
        if not structure_id:
            return
        structure_db_id = structure_obj.get("db_pointer", {}).get("structure_db_id", "")
        if structure_db_id:
            self._primary_map[structure_id] = structure_db_id
            self._fallback_map[structure_id] = structure_db_id
        structure = structure_obj.get("structure", {})
        signature = structure.get("content_signature", "")
        if signature:
            self.register_signature(signature, structure_id)
        legacy_flat_tokens = [str(token) for token in structure.get("flat_tokens", []) if str(token)]
        if legacy_flat_tokens:
            self.register_signature("|".join(legacy_flat_tokens), structure_id)
        for group in structure.get("sequence_groups", []):
            if not isinstance(group, dict):
                continue
            group_signature = str(group.get("group_signature", ""))
            if not group_signature:
                tokens = [str(token) for token in group.get("tokens", []) if str(token)]
                tokens.sort()
                group_signature = "|".join(tokens)
            if group_signature:
                self.register_signature(group_signature, structure_id)
            for token in group.get("tokens", []):
                token_text = str(token)
                if token_text:
                    self.register_signature(token_text, structure_id)
            for unit in group.get("units", []):
                if not isinstance(unit, dict):
                    continue
                token_text = str(unit.get("token", ""))
                if token_text:
                    self.register_signature(token_text, structure_id)
        self._observe_numeric_structure(structure_obj)

    def register_signature(self, signature: str, structure_id: str) -> None:
        if not signature or not structure_id:
            return
        bucket = [item for item in self._signature_index.get(signature, []) if item != structure_id]
        bucket.insert(0, structure_id)
        hard_limit = int(self._config.get("fallback_lookup_max_candidates", 32))
        self._signature_index[signature] = bucket[:hard_limit]

    def unregister_structure(self, structure_id: str, signature: str = "") -> None:
        self._primary_map.pop(structure_id, None)
        self._fallback_map.pop(structure_id, None)
        self._recent_cache.pop(structure_id, None)
        self._exact_lookup_cache = OrderedDict(
            (key, value)
            for key, value in self._exact_lookup_cache.items()
            if str(value.get("structure_id", "") or "") != str(structure_id or "")
        )
        if signature and signature in self._signature_index:
            self._signature_index[signature] = [item for item in self._signature_index[signature] if item != structure_id]
        affected = []
        for family, state in self._numeric_families.items():
            observations = state.setdefault("observations", {})
            if observations.pop(structure_id, None) is not None:
                affected.append(family)
        for family in affected:
            self._rebuild_numeric_family(family)

    def cache_structure_db(self, structure_id: str, structure_db: dict) -> None:
        if not structure_id or not structure_db:
            return
        self._recent_cache[structure_id] = {
            "structure_db_id": structure_db.get("structure_db_id", ""),
            "owner_structure_id": structure_db.get("owner_structure_id", ""),
            "cached_at": int(time.time() * 1000),
            "handle": structure_db,
        }
        self._recent_cache.move_to_end(structure_id)
        self._trim_recent_cache()

    def cache_exact_structure_id(self, cache_key: str, structure_id: str) -> None:
        if not cache_key or not structure_id:
            return
        self._exact_lookup_cache[cache_key] = {
            "structure_id": str(structure_id),
            "cached_at": int(time.time() * 1000),
        }
        self._exact_lookup_cache.move_to_end(cache_key)
        self._trim_exact_lookup_cache()

    def resolve_exact_structure_id(self, cache_key: str) -> str:
        if not cache_key:
            return ""
        payload = self._exact_lookup_cache.get(cache_key)
        if not isinstance(payload, dict):
            return ""
        self._exact_lookup_cache.move_to_end(cache_key)
        return str(payload.get("structure_id", "") or "")

    def resolve_db(self, *, structure_obj: dict, structure_store, logger=None, trace_id: str = "", tick_id: str = "") -> tuple[dict | None, dict]:
        structure_id = structure_obj.get("id", "")
        pointer = structure_obj.get("db_pointer", {})
        primary_db_id = pointer.get("structure_db_id", "") or self._primary_map.get(structure_id, "")
        primary_db = structure_store.get_db(primary_db_id) if primary_db_id else None
        if primary_db is not None:
            self._primary_map[structure_id] = primary_db_id
            self.cache_structure_db(structure_id, primary_db)
            return primary_db, {"used_fallback": False, "fallback_mode": "", "primary_db_id": primary_db_id, "resolved_db_id": primary_db_id}

        fallback_db_id = self._fallback_map.get(structure_id, "")
        fallback_db = structure_store.get_db(fallback_db_id) if fallback_db_id else None
        if fallback_db is not None:
            self._primary_map[structure_id] = fallback_db_id
            self.cache_structure_db(structure_id, fallback_db)
            self._log_fallback(logger, trace_id, tick_id, structure_id, primary_db_id, fallback_db_id, "fallback_map")
            return fallback_db, {"used_fallback": True, "fallback_mode": "fallback_map", "primary_db_id": primary_db_id, "resolved_db_id": fallback_db_id}

        recent = self._recent_cache.get(structure_id)
        if recent:
            cached_db = recent.get("handle")
            cached_db_id = recent.get("structure_db_id", "")
            if isinstance(cached_db, dict) and cached_db.get("owner_structure_id") == structure_id:
                self._primary_map[structure_id] = cached_db_id
                self._fallback_map[structure_id] = cached_db_id
                self._log_fallback(logger, trace_id, tick_id, structure_id, primary_db_id, cached_db_id, "recent_cache")
                return cached_db, {"used_fallback": True, "fallback_mode": "recent_cache", "primary_db_id": primary_db_id, "resolved_db_id": cached_db_id}

        signature = structure_obj.get("structure", {}).get("content_signature", "")
        if signature and self._config.get("enable_pointer_fallback", True):
            for candidate_id in self.query_candidates_by_signature(signature):
                candidate_structure = structure_store.get(candidate_id)
                if candidate_structure is None:
                    continue
                candidate_db = structure_store.get_db_by_owner(candidate_id)
                if candidate_db is None:
                    continue
                if candidate_id == structure_id:
                    resolved_db_id = candidate_db.get("structure_db_id", "")
                    self._primary_map[structure_id] = resolved_db_id
                    self._fallback_map[structure_id] = resolved_db_id
                    self.cache_structure_db(structure_id, candidate_db)
                    self._log_fallback(logger, trace_id, tick_id, structure_id, primary_db_id, resolved_db_id, "signature_index")
                    return candidate_db, {"used_fallback": True, "fallback_mode": "signature_index", "primary_db_id": primary_db_id, "resolved_db_id": resolved_db_id}

        parent_ids = list(structure_obj.get("source", {}).get("parent_ids", []))
        limit = int(self._config.get("fallback_scan_hard_limit", 200))
        for parent_id in parent_ids[:limit]:
            parent_db = structure_store.get_db_by_owner(parent_id)
            if parent_db is None:
                continue
            child_refs = [entry.get("target_id", "") for entry in parent_db.get("diff_table", []) if isinstance(entry, dict)]
            if structure_id in child_refs:
                resolved_db_id = parent_db.get("structure_db_id", "")
                self._fallback_map[structure_id] = resolved_db_id
                self._log_fallback(logger, trace_id, tick_id, structure_id, primary_db_id, resolved_db_id, "parent_chain")
                return parent_db, {"used_fallback": True, "fallback_mode": "parent_chain", "primary_db_id": primary_db_id, "resolved_db_id": resolved_db_id}

        return None, {"used_fallback": False, "fallback_mode": "unresolved", "primary_db_id": primary_db_id, "resolved_db_id": ""}

    def query_candidates_by_signature(self, signature: str) -> list[str]:
        if not signature:
            return []
        hard_limit = int(self._config.get("fallback_lookup_max_candidates", 32))
        return list(self._signature_index.get(signature, []))[:hard_limit]

    def export_snapshot(self) -> dict:
        return {
            "primary_pointer_count": len(self._primary_map),
            "fallback_pointer_count": len(self._fallback_map),
            "signature_index_count": len(self._signature_index),
            "recent_cache_count": len(self._recent_cache),
            "exact_lookup_cache_count": len(self._exact_lookup_cache),
            "numeric_bucket_family_count": len(self._numeric_families),
            "numeric_bucket_count": sum(len(state.get("buckets", [])) for state in self._numeric_families.values()),
        }

    def rebuild_from_store(self, structure_store) -> None:
        self._primary_map.clear()
        self._fallback_map.clear()
        self._signature_index.clear()
        self._recent_cache.clear()
        self._exact_lookup_cache.clear()
        self._numeric_families.clear()
        for structure_obj in structure_store.iter_structures():
            self.register_structure(structure_obj)

    def _trim_recent_cache(self) -> None:
        limit = max(8, int(self._config.get("lru_db_cache_size", 64)))
        while len(self._recent_cache) > limit:
            self._recent_cache.popitem(last=False)

    def _trim_exact_lookup_cache(self) -> None:
        limit = max(16, int(self._config.get("exact_lookup_cache_size", 256)))
        while len(self._exact_lookup_cache) > limit:
            self._exact_lookup_cache.popitem(last=False)

    def _log_fallback(self, logger, trace_id: str, tick_id: str, structure_id: str, primary_db_id: str, resolved_db_id: str, mode: str) -> None:
        if logger is None or not self._config.get("detail_log_dump_pointer_fallback", True):
            return
        logger.detail(
            trace_id=trace_id,
            tick_id=tick_id,
            step="pointer_fallback",
            message_zh="主指针失效，已使用备用路径回退",
            message_en="Primary pointer invalid, fallback path used",
            info={
                "structure_id": structure_id,
                "broken_pointer": primary_db_id,
                "resolved_db_id": resolved_db_id,
                "fallback_mode": mode,
            },
        )

    @staticmethod
    def _coerce_numeric(value: Any) -> float | None:
        return coerce_numeric_value(value)

    def _numeric_bucket_display(self, *, family: str, center: float, lower: float, upper: float) -> str:
        return f"{family}≈{center:.4f}[{lower:.4f},{upper:.4f}]"

    @staticmethod
    def _numeric_bucket_signature(*, family: str, bucket_id: str) -> str:
        return f"AN:{family}:{bucket_id}"

    def _bucket_creation_gap(self, *, family: str, value: float, nearest_center: float | None = None) -> float:
        scale = max(
            1.0,
            abs(float(value)),
            abs(float(nearest_center if nearest_center is not None else value)),
        )
        return max(
            float(self._config.get("numeric_bucket_creation_abs_gap", 0.2)),
            float(self._config.get("numeric_bucket_creation_rel_gap", 0.35)) * scale,
        )

    def _bucket_split_gap(self, *, family: str, lower: float, upper: float) -> float:
        scale = max(1.0, abs(float(lower)), abs(float(upper)))
        return max(
            float(self._config.get("numeric_bucket_split_abs_gap", 0.45)),
            float(self._config.get("numeric_bucket_split_rel_gap", 0.5)) * scale,
        )

    def _bucket_merge_gap(self, *, family: str, left: float, right: float) -> float:
        scale = max(1.0, abs(float(left)), abs(float(right)))
        return max(
            float(self._config.get("numeric_bucket_merge_abs_gap", 0.1)),
            float(self._config.get("numeric_bucket_merge_rel_gap", 0.12)) * scale,
        )

    def _numeric_match_gap(self, *, left: float, right: float) -> float:
        return numeric_match_tolerance(
            float(left),
            float(right),
            abs_tolerance=float(self._config.get("numeric_match_abs_tolerance", 0.2)),
            rel_tolerance=float(self._config.get("numeric_match_rel_tolerance", 0.35)),
        )

    def _family_state(self, family: str) -> dict[str, Any]:
        state = self._numeric_families.setdefault(
            family,
            {
                "buckets": [],
                "bucket_members": {},
                "observations": {},
                "next_bucket_index": 1,
            },
        )
        state.setdefault("buckets", [])
        state.setdefault("bucket_members", {})
        state.setdefault("observations", {})
        state.setdefault("next_bucket_index", 1)
        return state

    def _observe_numeric_structure(self, structure_obj: dict) -> None:
        structure_id = str(structure_obj.get("id", ""))
        if not structure_id:
            return
        family_values: dict[str, set[float]] = {}
        for group in structure_obj.get("structure", {}).get("sequence_groups", []):
            if not isinstance(group, dict):
                continue
            for unit in group.get("units", []):
                if not isinstance(unit, dict):
                    continue
                if str(unit.get("unit_role", "")) != "attribute":
                    continue
                family = str(unit.get("attribute_name", ""))
                value = self._coerce_numeric(unit.get("attribute_value"))
                if not family or value is None:
                    continue
                family_values.setdefault(family, set()).add(round(value, 8))
        if not family_values:
            return
        for family, values in family_values.items():
            state = self._family_state(family)
            observations = state.setdefault("observations", {})
            sorted_values = sorted(values)
            if observations.get(structure_id) == sorted_values:
                continue
            observations[structure_id] = sorted_values
            if bool(self._config.get("numeric_bucket_lazy_rebuild_enabled", True)):
                self._numeric_dirty_families.add(family)
            else:
                self._rebuild_numeric_family(family)

    def _ensure_numeric_family_rebuilt(self, family: str) -> None:
        if family not in self._numeric_dirty_families:
            return
        self._rebuild_numeric_family(family)

    def _rebuild_numeric_family(self, family: str) -> None:
        state = self._family_state(family)
        self._numeric_dirty_families.discard(family)
        observations = state.get("observations", {})
        observed_values = [
            float(value)
            for values in observations.values()
            for value in values
        ]
        if not observed_values:
            state["buckets"] = []
            state["bucket_members"] = {}
            return

        unique_values = sorted(set(round(value, 8) for value in observed_values))
        max_buckets = max(1, int(self._config.get("numeric_bucket_max_per_family", 16)))
        centers: list[float] = []
        for value in unique_values:
            if not centers:
                centers.append(value)
                continue
            nearest = min(centers, key=lambda item: abs(item - value))
            if (
                abs(value - nearest) > self._bucket_creation_gap(family=family, value=value, nearest_center=nearest)
                and len(centers) < max_buckets
            ):
                centers.append(value)
        centers = sorted(centers)
        centers = self._refine_numeric_centers(centers=centers, observed_values=observed_values)
        centers = self._split_dense_centers(
            family=family,
            centers=centers,
            observed_values=observed_values,
            max_buckets=max_buckets,
        )
        centers = self._merge_sparse_centers(
            family=family,
            centers=centers,
            observed_values=observed_values,
        )
        centers = self._refine_numeric_centers(centers=centers, observed_values=observed_values)

        sorted_centers = sorted((round(float(center), 8), index) for index, center in enumerate(centers))
        old_buckets = list(state.get("buckets", []))
        reused_ids: set[str] = set()
        new_buckets = []
        for position, (center, source_index) in enumerate(sorted_centers):
            lower = -math.inf if position <= 0 else round((sorted_centers[position - 1][0] + center) / 2.0, 8)
            upper = math.inf if position >= len(sorted_centers) - 1 else round((center + sorted_centers[position + 1][0]) / 2.0, 8)
            matched_old = None
            if old_buckets:
                unmatched = [bucket for bucket in old_buckets if str(bucket.get("bucket_id", "")) not in reused_ids]
                if unmatched:
                    matched_old = min(
                        unmatched,
                        key=lambda bucket: abs(float(bucket.get("center", 0.0)) - center),
                    )
            if matched_old is not None and abs(float(matched_old.get("center", 0.0)) - center) <= self._bucket_creation_gap(
                family=family,
                value=center,
                nearest_center=float(matched_old.get("center", 0.0)),
            ):
                bucket_id = str(matched_old.get("bucket_id", ""))
                reused_ids.add(bucket_id)
            else:
                bucket_id = f"nbkt_{family}_{int(state.get('next_bucket_index', 1)):04d}"
                state["next_bucket_index"] = int(state.get("next_bucket_index", 1)) + 1
            new_buckets.append(
                {
                    "bucket_id": bucket_id,
                    "family": family,
                    "center": center,
                    "lower_bound": lower,
                    "upper_bound": upper,
                    "sample_count": 0,
                    "display_text": self._numeric_bucket_display(
                        family=family,
                        center=center,
                        lower=lower if math.isfinite(lower) else center,
                        upper=upper if math.isfinite(upper) else center,
                    ),
                }
            )

        bucket_members: dict[str, list[str]] = {str(bucket.get("bucket_id", "")): [] for bucket in new_buckets}
        bucket_sample_counts: dict[str, int] = {str(bucket.get("bucket_id", "")): 0 for bucket in new_buckets}
        for structure_id, values in observations.items():
            structure_bucket_ids = []
            for value in values:
                target_bucket = min(
                    new_buckets,
                    key=lambda bucket: (
                        abs(float(bucket.get("center", 0.0)) - float(value)),
                        str(bucket.get("bucket_id", "")),
                    ),
                )
                bucket_id = str(target_bucket.get("bucket_id", ""))
                if bucket_id:
                    bucket_sample_counts[bucket_id] = int(bucket_sample_counts.get(bucket_id, 0)) + 1
                if bucket_id and bucket_id not in structure_bucket_ids:
                    structure_bucket_ids.append(bucket_id)
            for bucket_id in structure_bucket_ids:
                bucket_members.setdefault(bucket_id, [])
                if structure_id not in bucket_members[bucket_id]:
                    bucket_members[bucket_id].append(structure_id)
        for bucket in new_buckets:
            bucket_id = str(bucket.get("bucket_id", ""))
            bucket["sample_count"] = int(bucket_sample_counts.get(bucket_id, 0))
        state["buckets"] = new_buckets
        state["bucket_members"] = bucket_members

    def _assign_numeric_values(self, *, centers: list[float], observed_values: list[float]) -> dict[int, list[float]]:
        assignments: dict[int, list[float]] = {index: [] for index in range(len(centers))}
        for value in observed_values:
            target_index = min(
                range(len(centers)),
                key=lambda index: (abs(float(centers[index]) - float(value)), index),
            )
            assignments[target_index].append(float(value))
        return assignments

    def _refine_numeric_centers(self, *, centers: list[float], observed_values: list[float]) -> list[float]:
        refined = [round(float(center), 8) for center in centers if center is not None]
        if not refined:
            return refined
        for _ in range(3):
            assignments = self._assign_numeric_values(centers=refined, observed_values=observed_values)
            refined = [
                round(sum(bucket_values) / len(bucket_values), 8) if bucket_values else round(float(refined[index]), 8)
                for index, bucket_values in assignments.items()
            ]
        return refined

    def _split_dense_centers(
        self,
        *,
        family: str,
        centers: list[float],
        observed_values: list[float],
        max_buckets: int,
    ) -> list[float]:
        refined = list(centers)
        split_min_samples = max(4, int(self._config.get("numeric_bucket_split_min_samples", 8)))
        while len(refined) < max_buckets:
            assignments = self._assign_numeric_values(centers=refined, observed_values=observed_values)
            best_index = -1
            best_payload = None
            for index, bucket_values in assignments.items():
                if len(bucket_values) < split_min_samples:
                    continue
                span = max(bucket_values) - min(bucket_values)
                if span <= self._bucket_split_gap(family=family, lower=min(bucket_values), upper=max(bucket_values)):
                    continue
                candidate_key = (span, len(bucket_values))
                if best_payload is None or candidate_key > best_payload:
                    best_payload = candidate_key
                    best_index = index
            if best_index < 0:
                break
            bucket_values = sorted(assignments.get(best_index, []))
            midpoint = max(1, len(bucket_values) // 2)
            lower_values = bucket_values[:midpoint]
            upper_values = bucket_values[midpoint:]
            if not lower_values or not upper_values:
                break
            lower_center = round(sum(lower_values) / len(lower_values), 8)
            upper_center = round(sum(upper_values) / len(upper_values), 8)
            if lower_center == upper_center:
                break
            next_centers = []
            for index, center in enumerate(refined):
                if index != best_index:
                    next_centers.append(round(float(center), 8))
                    continue
                next_centers.extend([lower_center, upper_center])
            refined = self._refine_numeric_centers(centers=next_centers, observed_values=observed_values)
        return refined

    def _merge_sparse_centers(self, *, family: str, centers: list[float], observed_values: list[float]) -> list[float]:
        refined = sorted(round(float(center), 8) for center in centers)
        merge_max_samples = max(1, int(self._config.get("numeric_bucket_merge_max_samples", 3)))
        changed = True
        while changed and len(refined) > 1:
            changed = False
            assignments = self._assign_numeric_values(centers=refined, observed_values=observed_values)
            next_centers = []
            index = 0
            while index < len(refined):
                if index >= len(refined) - 1:
                    next_centers.append(refined[index])
                    break
                left_center = refined[index]
                right_center = refined[index + 1]
                left_count = len(assignments.get(index, []))
                right_count = len(assignments.get(index + 1, []))
                gap = abs(float(right_center) - float(left_center))
                if (
                    left_count <= merge_max_samples
                    and right_count <= merge_max_samples
                    and gap <= self._bucket_merge_gap(family=family, left=left_center, right=right_center)
                ):
                    merged_values = assignments.get(index, []) + assignments.get(index + 1, [])
                    merged_center = round(sum(merged_values) / len(merged_values), 8) if merged_values else round((left_center + right_center) / 2.0, 8)
                    next_centers.append(merged_center)
                    changed = True
                    index += 2
                    continue
                next_centers.append(left_center)
                index += 1
            refined = sorted(dict.fromkeys(next_centers))
        return refined

    def resolve_numeric_buckets(
        self,
        *,
        attribute_name: str,
        value: float,
        create_if_missing: bool = False,
        neighbor_count: int | None = None,
    ) -> list[dict[str, Any]]:
        family = str(attribute_name or "")
        numeric_value = self._coerce_numeric(value)
        if not family or numeric_value is None:
            return []
        state = self._family_state(family)
        self._ensure_numeric_family_rebuilt(family)
        if create_if_missing and bool(self._config.get("numeric_bucket_synthetic_lookup_rebuild_enabled", False)):
            observations = state.setdefault("observations", {})
            synthetic_id = f"__lookup__::{family}::{round(float(numeric_value), 8)}"
            observations[synthetic_id] = [round(float(numeric_value), 8)]
            self._rebuild_numeric_family(family)
            observations.pop(synthetic_id, None)
            self._rebuild_numeric_family(family)
        buckets = list(state.get("buckets", []))
        if not buckets:
            return []
        results = []
        for bucket in buckets:
            center = float(bucket.get("center", 0.0))
            gap = self._bucket_creation_gap(family=family, value=float(numeric_value), nearest_center=center)
            closeness = max(0.0, 1.0 - (abs(float(numeric_value) - center) / max(gap, 1e-6)))
            results.append(
                {
                    **bucket,
                    "distance": round(abs(float(numeric_value) - center), 8),
                    "closeness": round(closeness, 8),
                    "bucket_signature": self._numeric_bucket_signature(
                        family=family,
                        bucket_id=str(bucket.get("bucket_id", "")),
                    ),
                    "candidate_ids": list(state.get("bucket_members", {}).get(str(bucket.get("bucket_id", "")), [])),
                }
            )
        results.sort(key=lambda item: (float(item.get("distance", 0.0)), str(item.get("bucket_id", ""))))
        limit = max(1, int(neighbor_count or self._config.get("numeric_bucket_neighbor_count", 2)))
        return results[:limit]

    def describe_numeric_match(self, *, attribute_name: str, left_value: float, right_value: float) -> dict[str, Any] | None:
        family = str(attribute_name or "")
        if not family:
            return None
        numeric_match = build_numeric_match(
            family=family,
            left_value=left_value,
            right_value=right_value,
            abs_tolerance=float(self._config.get("numeric_match_abs_tolerance", 0.2)),
            rel_tolerance=float(self._config.get("numeric_match_rel_tolerance", 0.35)),
            min_similarity=float(self._config.get("numeric_match_min_similarity", 0.4)),
        )
        if not numeric_match:
            return None
        midpoint = round(float(numeric_match.get("average_value", 0.0)), 8)
        buckets = self.resolve_numeric_buckets(
            attribute_name=family,
            value=midpoint,
            create_if_missing=True,
            neighbor_count=1,
        )
        bucket = buckets[0] if buckets else {
            "bucket_id": f"nbkt_{family}_virtual",
            "center": midpoint,
            "lower_bound": midpoint,
            "upper_bound": midpoint,
            "display_text": self._numeric_bucket_display(
                family=family,
                center=midpoint,
                lower=midpoint,
                upper=midpoint,
            ),
        }
        bucket_id = str(bucket.get("bucket_id", ""))
        return {
            **numeric_match,
            "bucket_id": bucket_id,
            "bucket_center": round(float(bucket.get("center", midpoint)), 8),
            "bucket_lower_bound": round(float(bucket.get("lower_bound", midpoint)), 8),
            "bucket_upper_bound": round(float(bucket.get("upper_bound", midpoint)), 8),
            "bucket_display_text": str(bucket.get("display_text", "")),
            "bucket_signature": self._numeric_bucket_signature(family=family, bucket_id=bucket_id),
        }
