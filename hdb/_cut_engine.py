# -*- coding: utf-8 -*-
"""
Cut engine and sequence helpers for HDB.
"""

from __future__ import annotations

import copy
import time
from collections import Counter, OrderedDict

from ._display_semantics import is_display_only_token
from ._id_generator import next_id
from ._numeric_match import coerce_numeric_value, describe_numeric_match as build_numeric_match
from ._sequence_display import format_group_display, format_sequence_groups


class CutEngine:
    def __init__(self, config: dict | None = None):
        self._config = dict(config or {})
        self._pointer_index = None
        self._normalize_groups_cache: OrderedDict[tuple, list[dict]] = OrderedDict()
        self._common_group_length_cache: OrderedDict[tuple, int] = OrderedDict()
        self._maximum_common_part_cache: OrderedDict[tuple, dict] = OrderedDict()
        self._runtime_metrics: dict[str, int] = {}

    def set_pointer_index(self, pointer_index) -> None:
        self._pointer_index = pointer_index

    def reset_runtime_metrics(self) -> None:
        self._runtime_metrics.clear()

    def update_config(self, config: dict) -> None:
        self._config = dict(config or {})
        self._normalize_groups_cache.clear()
        self._common_group_length_cache.clear()
        self._maximum_common_part_cache.clear()
        self._runtime_metrics.clear()

    def _internal_single_cooccurrence_group_enabled(self) -> bool:
        return bool(self._config.get("internal_stimulus_flatten_to_single_cooccurrence_group_enabled", True))

    def build_sequence_profile_from_stimulus_packet(self, stimulus_packet: dict) -> dict:
        sa_index = {
            item.get("id", ""): item
            for item in stimulus_packet.get("sa_items", [])
            if isinstance(item, dict) and item.get("id")
        }
        csa_index = {
            item.get("id", ""): item
            for item in stimulus_packet.get("csa_items", [])
            if isinstance(item, dict) and item.get("id")
        }

        # Best-effort grouping recovery:
        # Some upstream builders only list anchor SA ids in grouped_sa_sequences, while
        # attribute SA may only carry packet_context metadata (source_type/origin/source_group_index).
        # If we don't include them here, attribute SA will silently disappear from profiles,
        # which breaks "属性刺激元可被最大共同结构切分并脱锚成为长期结构" 的理论预期。
        sa_ids_by_ctx: dict[tuple[str, str, int], list[str]] = {}
        for sa_id, obj in sa_index.items():
            try:
                ctx = (obj.get("ext", {}) or {}).get("packet_context", {})
                if not isinstance(ctx, dict):
                    continue
                ctx_source_type = str(ctx.get("source_type", "") or "")
                ctx_origin = str(ctx.get("origin_frame_id", "") or "")
                try:
                    ctx_sgi = int(ctx.get("source_group_index", ctx.get("group_index", -1)))
                except Exception:
                    ctx_sgi = -1
                if not ctx_source_type and not ctx_origin and ctx_sgi < 0:
                    continue
                sa_ids_by_ctx.setdefault((ctx_source_type, ctx_origin, ctx_sgi), []).append(str(sa_id))
            except Exception:
                continue

        groups = []
        member_refs: list[str] = []

        for order_index, group in enumerate(stimulus_packet.get("grouped_sa_sequences", [])):
            source_type = str(group.get("source_type", "current"))
            origin_frame_id = str(group.get("origin_frame_id", ""))
            source_group_index = int(group.get("source_group_index", group.get("group_index", order_index)))
            group_ext = group.get("ext", {}) if isinstance(group.get("ext", {}), dict) else {}

            legacy_string_groups = []
            embedded_string_groups = []
            if bool(self._config.get("enable_goal_b_char_sa_string_mode", False)):
                if isinstance(group_ext.get("internal_string_groups", []), list):
                    embedded_string_groups = [
                        dict(row)
                        for row in group_ext.get("internal_string_groups", [])
                        if isinstance(row, dict)
                    ]
                if isinstance(group_ext.get("string_groups", []), list):
                    legacy_string_groups = [
                        dict(row)
                        for row in group_ext.get("string_groups", [])
                        if isinstance(row, dict)
                    ]
                    if not embedded_string_groups:
                        embedded_string_groups = [dict(row) for row in legacy_string_groups]

            if (
                bool(self._config.get("enable_goal_b_char_sa_string_mode", False))
                and source_type == "internal"
                and bool(group_ext.get("contains_string_groups", False))
                and legacy_string_groups
            ):
                for restored_index, restored_group in enumerate(legacy_string_groups):
                    if not isinstance(restored_group, dict):
                        continue
                    if not (bool(restored_group.get("order_sensitive", False)) and str(restored_group.get("string_unit_kind", "") or "") == "char_sequence"):
                        continue
                    restored_source_type = str(restored_group.get("source_type", "internal") or "internal")
                    restored_origin = str(restored_group.get("origin_frame_id", origin_frame_id) or origin_frame_id)
                    restored_sgi = int(restored_group.get("source_group_index", restored_group.get("group_index", restored_index)))
                    restored_sa_ids = [str(sa_id) for sa_id in restored_group.get("sa_ids", []) if str(sa_id)]
                    restored_csa_members = [csa_index.get(csa_id) for csa_id in restored_group.get("csa_ids", []) if csa_index.get(csa_id)]
                    restored_csa_members.sort(key=lambda item: item.get("ext", {}).get("packet_context", {}).get("sequence_index", 0))
                    for csa in restored_csa_members:
                        for member_id in csa.get("member_sa_ids", []):
                            member_text = str(member_id)
                            if member_text:
                                restored_sa_ids.append(member_text)
                    restored_ordered_sa_ids = self._dedupe_preserve_order(restored_sa_ids)
                    restored_sa_members = [sa_index.get(sa_id) for sa_id in restored_ordered_sa_ids if sa_index.get(sa_id)]
                    restored_sa_members.sort(key=lambda item: item.get("ext", {}).get("packet_context", {}).get("sequence_index", 0))
                    restored_units = [
                        self._build_unit_from_packet_object(
                            obj=sa,
                            group_index=len(groups),
                            source_group_index=restored_sgi,
                            source_type=restored_source_type,
                            origin_frame_id=restored_origin,
                        )
                        for sa in restored_sa_members
                    ]
                    restored_units = [unit for unit in restored_units if unit]
                    if not restored_units:
                        continue
                    raw_restored_group = {
                        "group_index": len(groups),
                        "source_type": restored_source_type,
                        "origin_frame_id": restored_origin,
                        "source_group_index": restored_sgi,
                        "units": restored_units,
                        "csa_bundles": [],
                        "order_sensitive": bool(restored_group.get("order_sensitive", False)),
                        "string_unit_kind": str(restored_group.get("string_unit_kind", "") or ""),
                        "string_token_text": str(restored_group.get("string_token_text", "") or ""),
                    }
                    normalized_restored = self._normalize_sequence_group(raw_restored_group, order_index=len(groups))
                    if not normalized_restored.get("units"):
                        continue
                    groups.append(normalized_restored)
                    member_refs.extend(str(unit.get("unit_id", "")) for unit in normalized_restored.get("units", []) if str(unit.get("unit_id", "")))
                continue

            referenced_sa_ids: list[str] = [str(sa_id) for sa_id in group.get("sa_ids", []) if str(sa_id)]
            # Include implicit members that belong to the same packet-context group.
            # 说明：这让 “attribute SA 不在 sa_ids 列表里” 仍能被 profile 收集到。
            implicit = sa_ids_by_ctx.get((source_type, origin_frame_id, int(source_group_index)), [])
            if implicit:
                referenced_sa_ids.extend(implicit)
            csa_members = [csa_index.get(csa_id) for csa_id in group.get("csa_ids", []) if csa_index.get(csa_id)]
            csa_members.sort(key=lambda item: item.get("ext", {}).get("packet_context", {}).get("sequence_index", 0))
            for csa in csa_members:
                for member_id in csa.get("member_sa_ids", []):
                    member_text = str(member_id)
                    if member_text:
                        referenced_sa_ids.append(member_text)

            ordered_sa_ids = self._dedupe_preserve_order(referenced_sa_ids)
            sa_members = [sa_index.get(sa_id) for sa_id in ordered_sa_ids if sa_index.get(sa_id)]
            sa_members.sort(key=lambda item: item.get("ext", {}).get("packet_context", {}).get("sequence_index", 0))

            units = [
                self._build_unit_from_packet_object(
                    obj=sa,
                    group_index=order_index,
                    source_group_index=source_group_index,
                    source_type=source_type,
                    origin_frame_id=origin_frame_id,
                )
                for sa in sa_members
            ]
            units = [unit for unit in units if unit]

            csa_bundles = []
            for csa in csa_members:
                bundle = self._build_bundle_from_csa(csa, units)
                if bundle:
                    csa_bundles.append(bundle)

            if not units and csa_members:
                for csa in csa_members:
                    synthetic = self._build_synthetic_unit_from_csa(
                        csa=csa,
                        group_index=order_index,
                        source_group_index=source_group_index,
                        source_type=source_type,
                        origin_frame_id=origin_frame_id,
                    )
                    if synthetic:
                        units.append(synthetic)

            raw_group = {
                "group_index": order_index,
                "source_type": source_type,
                "origin_frame_id": origin_frame_id,
                "source_group_index": source_group_index,
                "units": units,
                "csa_bundles": csa_bundles,
                "ext": group_ext,
            }
            if bool(self._config.get("enable_goal_b_char_sa_string_mode", False)):
                group_order_sensitive = bool(group.get("order_sensitive", source_type in {"current", "echo"}))
                group_string_text = str(group.get("string_token_text", "") or "")
                group_string_kind = str(group.get("string_unit_kind", "") or "")
                if (
                    not group_order_sensitive
                    and embedded_string_groups
                    and len(embedded_string_groups) == 1
                    and bool(embedded_string_groups[0].get("order_sensitive", False))
                    and str(embedded_string_groups[0].get("string_unit_kind", "") or "") == "char_sequence"
                ):
                    group_order_sensitive = True
                raw_group["order_sensitive"] = group_order_sensitive
                raw_group["string_token_text"] = group_string_text
                raw_group["string_unit_kind"] = group_string_kind
            normalized_group = self._normalize_sequence_group(
                raw_group,
                order_index=order_index,
            )
            if not normalized_group.get("units"):
                continue
            groups.append(normalized_group)
            member_refs.extend(str(unit.get("unit_id", "")) for unit in normalized_group.get("units", []) if str(unit.get("unit_id", "")))

        return self._build_profile(groups=groups, member_refs=member_refs)

    def build_sequence_profile_from_structure(self, structure_obj: dict) -> dict:
        structure = structure_obj.get("structure", {})
        groups = self._normalize_sequence_groups(structure.get("sequence_groups", []))
        if not groups:
            groups = self._normalize_sequence_groups(
                [
                    {
                        "group_index": 0,
                        "source_type": "structure",
                        "origin_frame_id": structure_obj.get("id", ""),
                        "tokens": list(structure.get("flat_tokens", [])),
                    }
                ]
            )
        member_refs = list(structure.get("member_refs", []))
        profile = self._build_profile(groups=groups, member_refs=member_refs)
        if structure.get("display_text"):
            profile["display_text"] = structure.get("display_text", profile["display_text"])
        if structure.get("content_signature"):
            profile["legacy_content_signature"] = structure.get("content_signature", "")
        if structure.get("semantic_signature"):
            profile["legacy_semantic_signature"] = structure.get("semantic_signature", "")
        return profile

    def build_sequence_profile_from_groups(self, groups: list[dict]) -> dict:
        normalized_groups = self._normalize_sequence_groups(groups)
        member_refs = [
            str(unit.get("unit_id", ""))
            for group in normalized_groups
            for unit in group.get("units", [])
            if str(unit.get("unit_id", ""))
        ]
        return self._build_profile(groups=normalized_groups, member_refs=member_refs)

    def maximum_common_part(self, existing_groups: list[dict], incoming_groups: list[dict]) -> dict:
        normalized_existing = self._normalize_sequence_groups(existing_groups)
        normalized_incoming = self._normalize_sequence_groups(incoming_groups)
        if not normalized_existing or not normalized_incoming:
            return self._empty_common_part(normalized_existing, normalized_incoming)
        if bool(self._config.get("maximum_common_part_exact_fast_path_enabled", True)):
            exact_result = self._try_exact_same_common_part_fast_path(normalized_existing, normalized_incoming)
            if exact_result is not None:
                self._increment_runtime_metric("maximum_common_part_exact_fast_path_hit_count")
                return exact_result
        if bool(self._config.get("maximum_common_part_full_inclusion_fast_path_enabled", True)):
            inclusion_result = self._try_full_inclusion_common_part_fast_path(normalized_existing, normalized_incoming)
            if inclusion_result is not None:
                self._increment_runtime_metric("maximum_common_part_full_inclusion_fast_path_hit_count")
                return inclusion_result
        if (
            bool(self._config.get("maximum_common_part_single_group_fast_path_enabled", True))
            and len(normalized_existing) == 1
            and len(normalized_incoming) == 1
        ):
            single_group_result = self._try_single_group_common_part_fast_path(
                normalized_existing,
                normalized_incoming,
            )
            if single_group_result is not None:
                self._increment_runtime_metric("maximum_common_part_single_group_fast_path_hit_count")
                return single_group_result

        # PERF: Fast paths above are intentionally cheaper than building the full
        # nested cache key. Only pay that key cost for comparisons that really need
        # the DP fallback, where cache hits can avoid the expensive cut itself.
        cache_key = self._maximum_common_part_cache_key(normalized_existing, normalized_incoming)
        if cache_key is not None:
            cached = self._maximum_common_part_cache.get(cache_key)
            if isinstance(cached, dict):
                self._maximum_common_part_cache.pop(cache_key, None)
                self._maximum_common_part_cache[cache_key] = cached
                self._increment_runtime_metric("maximum_common_part_cache_hit_count")
                if bool(self._config.get("maximum_common_part_cache_deepcopy_enabled", False)):
                    self._increment_runtime_metric("maximum_common_part_cache_deepcopy_count")
                    return copy.deepcopy(cached)
                self._increment_runtime_metric("maximum_common_part_cache_zero_copy_hit_count")
                return cached

        rows = len(normalized_existing) + 1
        cols = len(normalized_incoming) + 1
        # The stimulus/structure theory is group-first: keep cross-group temporal order
        # stable before maximizing per-group token richness. We therefore rank DP paths by:
        # 1) matched group count, 2) earlier incoming alignment, 3) earlier existing alignment,
        # 4) total matched unit count.
        zero = (0, 0, 0, 0)
        dp: list[list[tuple[int, int, int, int]]] = [[zero for _ in range(cols)] for _ in range(rows)]
        action: list[list[str | None]] = [[None for _ in range(cols)] for _ in range(rows)]

        for i in range(1, rows):
            for j in range(1, cols):
                best_value = dp[i - 1][j]
                best_action: str | None = "up"
                if dp[i][j - 1] > best_value:
                    best_value = dp[i][j - 1]
                    best_action = "left"

                common_length = self._maximum_common_group_length(
                    existing_group=normalized_existing[i - 1],
                    incoming_group=normalized_incoming[j - 1],
                )
                if common_length > 0:
                    candidate_value = (
                        dp[i - 1][j - 1][0] + 1,
                        dp[i - 1][j - 1][1] - (j - 1),
                        dp[i - 1][j - 1][2] - (i - 1),
                        dp[i - 1][j - 1][3] + common_length,
                    )
                    if candidate_value > best_value:
                        best_value = candidate_value
                        best_action = "diag"

                dp[i][j] = best_value
                action[i][j] = best_action

        matched_pairs = []
        matched_pairs_indices: list[dict] = []
        i = len(normalized_existing)
        j = len(normalized_incoming)
        while i > 0 and j > 0:
            move = action[i][j]
            if move is None:
                break
            if move == "diag":
                matched_pairs_indices.append(
                    {
                        "existing_group_index": i - 1,
                        "incoming_group_index": j - 1,
                    }
                )
                i -= 1
                j -= 1
            elif move == "up":
                i -= 1
            else:
                j -= 1

        matched_pairs_indices.reverse()
        if not matched_pairs_indices:
            return self._empty_common_part(normalized_existing, normalized_incoming)

        for pair in matched_pairs_indices:
            existing_group_index = int(pair.get("existing_group_index", 0))
            incoming_group_index = int(pair.get("incoming_group_index", 0))
            group_match = self._maximum_common_group(
                existing_group=normalized_existing[existing_group_index],
                incoming_group=normalized_incoming[incoming_group_index],
            )
            matched_pairs.append(
                {
                    "existing_group_index": existing_group_index,
                    "incoming_group_index": incoming_group_index,
                    "common_tokens": list(group_match.get("common_group", {}).get("tokens", [])),
                    "common_unit_signatures": list(group_match.get("common_group", {}).get("unit_signatures", [])),
                    "incoming_unit_refs": list(group_match.get("matched_incoming_unit_ids", [])),
                    "existing_unit_refs": list(group_match.get("matched_existing_unit_ids", [])),
                    "matched_existing_unit_similarities": dict(group_match.get("matched_existing_unit_similarities", {})),
                    "matched_incoming_unit_similarities": dict(group_match.get("matched_incoming_unit_similarities", {})),
                    "common_bundle_signatures": list(group_match.get("common_group", {}).get("bundle_signatures", [])),
                    # CSA/bundle gate / CSA 门控结果（用于“完全包含/完全匹配”判断）
                    "bundle_constraints_ok_existing_included": bool(group_match.get("bundle_constraints_ok_existing_included", True)),
                    "bundle_constraints_ok_incoming_included": bool(group_match.get("bundle_constraints_ok_incoming_included", True)),
                    "bundle_constraints_ok_exact": bool(group_match.get("bundle_constraints_ok_exact", True)),
                    "bundle_constraints": dict(group_match.get("bundle_constraints", {}) or {}),
                    "common_group": dict(group_match.get("common_group", {})),
                    "residual_existing_group": dict(group_match.get("residual_existing_group", {})),
                    "residual_incoming_group": dict(group_match.get("residual_incoming_group", {})),
                }
            )

        common_groups = []
        common_tokens: list[str] = []
        matched_existing_group_indices = []
        matched_incoming_group_indices = []
        existing_residual_by_index = {}
        incoming_residual_by_index = {}
        matched_existing_unit_similarities: dict[str, float] = {}
        matched_incoming_unit_similarities: dict[str, float] = {}

        for order_index, pair in enumerate(matched_pairs):
            common_group = self._reindex_group(pair.get("common_group", {}), order_index=order_index)
            if common_group.get("units"):
                common_groups.append(common_group)
                common_tokens.extend(common_group.get("tokens", []))
            matched_existing_group_indices.append(int(pair.get("existing_group_index", 0)))
            matched_incoming_group_indices.append(int(pair.get("incoming_group_index", 0)))
            existing_residual_by_index[int(pair.get("existing_group_index", 0))] = dict(pair.get("residual_existing_group", {}))
            incoming_residual_by_index[int(pair.get("incoming_group_index", 0))] = dict(pair.get("residual_incoming_group", {}))
            matched_existing_unit_similarities.update(
                {
                    str(unit_id): float(similarity)
                    for unit_id, similarity in pair.get("matched_existing_unit_similarities", {}).items()
                    if str(unit_id)
                }
            )
            matched_incoming_unit_similarities.update(
                {
                    str(unit_id): float(similarity)
                    for unit_id, similarity in pair.get("matched_incoming_unit_similarities", {}).items()
                    if str(unit_id)
                }
            )

        residual_existing_groups = []
        residual_incoming_groups = []
        for order_index, group in enumerate(normalized_existing):
            residual_group = existing_residual_by_index.get(order_index, group)
            residual_group = self._reindex_group(residual_group, order_index=len(residual_existing_groups))
            if residual_group.get("units"):
                residual_existing_groups.append(residual_group)
        for order_index, group in enumerate(normalized_incoming):
            residual_group = incoming_residual_by_index.get(order_index, group)
            residual_group = self._reindex_group(residual_group, order_index=len(residual_incoming_groups))
            if residual_group.get("units"):
                residual_incoming_groups.append(residual_group)

        incoming_span = [matched_incoming_group_indices[0], matched_incoming_group_indices[-1] + 1]
        existing_span = [matched_existing_group_indices[0], matched_existing_group_indices[-1] + 1]
        common_display = format_sequence_groups(common_groups)

        # CSA/bundle gate aggregation / CSA 门控汇总：逐组 AND。
        bundle_ok_existing_included = all(bool(pair.get("bundle_constraints_ok_existing_included", True)) for pair in matched_pairs)
        bundle_ok_incoming_included = all(bool(pair.get("bundle_constraints_ok_incoming_included", True)) for pair in matched_pairs)
        bundle_ok_exact = bool(bundle_ok_existing_included and bundle_ok_incoming_included)

        # Flatten diagnostics for the UI/debug (keep it bounded).
        # 扁平化诊断信息（用于 UI/调试；做长度上限避免爆炸）。
        existing_gate_items = [dict((pair.get("bundle_constraints", {}) or {}).get("existing_included_in_incoming", {}) or {}) for pair in matched_pairs]
        incoming_gate_items = [dict((pair.get("bundle_constraints", {}) or {}).get("incoming_included_in_existing", {}) or {}) for pair in matched_pairs]
        existing_unmatched = [u for item in existing_gate_items for u in list(item.get("unmatched", []) or [])]
        incoming_unmatched = [u for item in incoming_gate_items for u in list(item.get("unmatched", []) or [])]

        result = {
            "common_tokens": common_tokens,
            "common_length": sum(len(group.get("units", [])) for group in common_groups),
            "common_group_count": len(common_groups),
            "matched_existing_unit_count": sum(len(pair.get("existing_unit_refs", [])) for pair in matched_pairs),
            "matched_incoming_unit_count": sum(len(pair.get("incoming_unit_refs", [])) for pair in matched_pairs),
            "common_signature": self.sequence_groups_to_signature(common_groups),
            "common_display": common_display or "".join(common_tokens),
            "common_groups": common_groups,
            "matched_pairs": matched_pairs,
            "matched_existing_unit_similarities": matched_existing_unit_similarities,
            "matched_incoming_unit_similarities": matched_incoming_unit_similarities,
            # Bundle gate / CSA 门控：下游“完全包含/完全匹配”需额外检查这些布尔值。
            "bundle_constraints_ok_existing_included": bundle_ok_existing_included,
            "bundle_constraints_ok_incoming_included": bundle_ok_incoming_included,
            "bundle_constraints_ok_exact": bundle_ok_exact,
            "bundle_constraints": {
                "existing_included_in_incoming": {
                    "ok": bundle_ok_existing_included,
                    "required_count": sum(int(item.get("required_count", 0) or 0) for item in existing_gate_items),
                    "matched_count": sum(int(item.get("matched_count", 0) or 0) for item in existing_gate_items),
                    "unmatched": existing_unmatched[:48],
                },
                "incoming_included_in_existing": {
                    "ok": bundle_ok_incoming_included,
                    "required_count": sum(int(item.get("required_count", 0) or 0) for item in incoming_gate_items),
                    "matched_count": sum(int(item.get("matched_count", 0) or 0) for item in incoming_gate_items),
                    "unmatched": incoming_unmatched[:48],
                },
            },
            "existing_range": existing_span,
            "incoming_range": incoming_span,
            "matched_existing_group_indices": matched_existing_group_indices,
            "matched_incoming_group_indices": matched_incoming_group_indices,
            "residual_existing_tokens": [token for group in residual_existing_groups for token in group.get("tokens", [])],
            "residual_incoming_tokens": [token for group in residual_incoming_groups for token in group.get("tokens", [])],
            "residual_existing_groups": residual_existing_groups,
            "residual_incoming_groups": residual_incoming_groups,
            "residual_existing_signature": self.sequence_groups_to_signature(residual_existing_groups),
            "residual_incoming_signature": self.sequence_groups_to_signature(residual_incoming_groups),
        }
        if cache_key is not None:
            self._remember_maximum_common_part(cache_key, result)
        return result

    def _maximum_common_part_cache_key(self, existing_groups: list[dict], incoming_groups: list[dict]) -> tuple | None:
        if not bool(self._config.get("maximum_common_part_cache_enabled", True)):
            return None

        def _group_key(group: dict) -> tuple:
            units = []
            for unit in list(group.get("units", []) or []):
                if not isinstance(unit, dict):
                    continue
                units.append(
                    (
                        str(unit.get("unit_id", "") or ""),
                        str(unit.get("unit_signature", "") or ""),
                        str(unit.get("token", "") or ""),
                        str(unit.get("unit_role", unit.get("role", "")) or ""),
                        str(unit.get("attribute_name", "") or ""),
                        repr(unit.get("attribute_value", None)),
                    )
                )
            return (
                bool(group.get("order_sensitive", False)),
                str(group.get("string_unit_kind", "") or ""),
                str(group.get("group_signature", "") or ""),
                tuple(units),
            )

        return (
            tuple(_group_key(group) for group in existing_groups if isinstance(group, dict)),
            tuple(_group_key(group) for group in incoming_groups if isinstance(group, dict)),
        )

    def _remember_maximum_common_part(self, key: tuple, result: dict) -> None:
        max_entries = int(self._config.get("maximum_common_part_cache_max_entries", 4096) or 4096)
        if max_entries <= 0:
            return
        cache = self._maximum_common_part_cache
        if key in cache:
            cache.pop(key, None)
        while len(cache) >= max_entries:
            try:
                cache.popitem(last=False)
            except KeyError:
                break
        self._increment_runtime_metric("maximum_common_part_cache_store_count")
        if bool(self._config.get("maximum_common_part_cache_deepcopy_enabled", False)):
            self._increment_runtime_metric("maximum_common_part_cache_deepcopy_count")
            cache[key] = copy.deepcopy(result)
        else:
            cache[key] = result

    def pop_runtime_metrics(self) -> dict[str, int]:
        metrics = dict(self._runtime_metrics)
        self._runtime_metrics.clear()
        return metrics

    def _increment_runtime_metric(self, key: str, amount: int = 1) -> None:
        if not key:
            return
        self._runtime_metrics[key] = int(self._runtime_metrics.get(key, 0) or 0) + int(amount)

    def _try_exact_same_common_part_fast_path(self, normalized_existing: list[dict], normalized_incoming: list[dict]) -> dict | None:
        existing_signature = self._signature_from_normalized_groups(normalized_existing)
        incoming_signature = self._signature_from_normalized_groups(normalized_incoming)
        if not existing_signature or existing_signature != incoming_signature:
            return None
        if len(normalized_existing) != len(normalized_incoming):
            return None
        for existing_group, incoming_group in zip(normalized_existing, normalized_incoming):
            if not self._groups_have_same_stable_signature(existing_group, incoming_group):
                return None

        common_groups = [
            self._reuse_group_with_order_index(group, order_index=index)
            for index, group in enumerate(normalized_incoming)
        ]
        common_tokens = [token for group in common_groups for token in group.get("tokens", [])]
        matched_pairs = []
        matched_existing_unit_similarities: dict[str, float] = {}
        matched_incoming_unit_similarities: dict[str, float] = {}
        for index, (existing_group, incoming_group, common_group) in enumerate(
            zip(normalized_existing, normalized_incoming, common_groups)
        ):
            existing_units = [unit for unit in existing_group.get("units", []) if isinstance(unit, dict)]
            incoming_units = [unit for unit in incoming_group.get("units", []) if isinstance(unit, dict)]
            existing_ids = [str(unit.get("unit_id", "")) for unit in existing_units if str(unit.get("unit_id", ""))]
            incoming_ids = [str(unit.get("unit_id", "")) for unit in incoming_units if str(unit.get("unit_id", ""))]
            matched_existing_unit_similarities.update({unit_id: 1.0 for unit_id in existing_ids})
            matched_incoming_unit_similarities.update({unit_id: 1.0 for unit_id in incoming_ids})
            matched_pairs.append(
                {
                    "existing_group_index": index,
                    "incoming_group_index": index,
                    "common_tokens": list(common_group.get("tokens", [])),
                    "common_unit_signatures": list(common_group.get("unit_signatures", [])),
                    "incoming_unit_refs": incoming_ids,
                    "existing_unit_refs": existing_ids,
                    "matched_existing_unit_similarities": {unit_id: 1.0 for unit_id in existing_ids},
                    "matched_incoming_unit_similarities": {unit_id: 1.0 for unit_id in incoming_ids},
                    "common_bundle_signatures": list(common_group.get("bundle_signatures", [])),
                    "bundle_constraints_ok_existing_included": True,
                    "bundle_constraints_ok_incoming_included": True,
                    "bundle_constraints_ok_exact": True,
                    "bundle_constraints": {
                        "existing_included_in_incoming": {
                            "ok": True,
                            "required_count": len(existing_ids),
                            "matched_count": len(existing_ids),
                            "unmatched": [],
                        },
                        "incoming_included_in_existing": {
                            "ok": True,
                            "required_count": len(incoming_ids),
                            "matched_count": len(incoming_ids),
                            "unmatched": [],
                        },
                    },
                    "common_group": dict(common_group),
                    "residual_existing_group": self._build_group_from_units(
                        template_group=existing_group,
                        units=[],
                        order_index=index,
                    ),
                    "residual_incoming_group": self._build_group_from_units(
                        template_group=incoming_group,
                        units=[],
                        order_index=index,
                    ),
                }
            )

        common_length = sum(len(group.get("units", [])) for group in common_groups)
        return {
            "common_tokens": common_tokens,
            "common_length": common_length,
            "common_group_count": len(common_groups),
            "matched_existing_unit_count": common_length,
            "matched_incoming_unit_count": common_length,
            "common_signature": existing_signature,
            "common_display": format_sequence_groups(common_groups) or "".join(common_tokens),
            "common_groups": common_groups,
            "matched_pairs": matched_pairs,
            "matched_existing_unit_similarities": matched_existing_unit_similarities,
            "matched_incoming_unit_similarities": matched_incoming_unit_similarities,
            "bundle_constraints_ok_existing_included": True,
            "bundle_constraints_ok_incoming_included": True,
            "bundle_constraints_ok_exact": True,
            "bundle_constraints": {
                "existing_included_in_incoming": {
                    "ok": True,
                    "required_count": common_length,
                    "matched_count": common_length,
                    "unmatched": [],
                },
                "incoming_included_in_existing": {
                    "ok": True,
                    "required_count": common_length,
                    "matched_count": common_length,
                    "unmatched": [],
                },
            },
            "existing_range": [0, len(normalized_existing)],
            "incoming_range": [0, len(normalized_incoming)],
            "matched_existing_group_indices": list(range(len(normalized_existing))),
            "matched_incoming_group_indices": list(range(len(normalized_incoming))),
            "residual_existing_tokens": [],
            "residual_incoming_tokens": [],
            "residual_existing_groups": [],
            "residual_incoming_groups": [],
            "residual_existing_signature": "",
            "residual_incoming_signature": "",
        }

    def _try_full_inclusion_common_part_fast_path(
        self,
        normalized_existing: list[dict],
        normalized_incoming: list[dict],
    ) -> dict | None:
        existing_in_incoming = self._find_stable_group_subsequence_indices(
            required_groups=normalized_existing,
            container_groups=normalized_incoming,
        )
        if existing_in_incoming and self._stable_subsequence_can_skip_groups(
            required_groups=normalized_existing,
            container_groups=normalized_incoming,
            matched_indices=existing_in_incoming,
        ):
            return self._build_full_inclusion_common_part(
                normalized_existing=normalized_existing,
                normalized_incoming=normalized_incoming,
                matched_incoming_indices=existing_in_incoming,
            )
        incoming_in_existing = self._find_stable_group_subsequence_indices(
            required_groups=normalized_incoming,
            container_groups=normalized_existing,
        )
        if incoming_in_existing and self._stable_subsequence_can_skip_groups(
            required_groups=normalized_incoming,
            container_groups=normalized_existing,
            matched_indices=incoming_in_existing,
        ):
            return self._build_full_inclusion_common_part(
                normalized_existing=normalized_existing,
                normalized_incoming=normalized_incoming,
                matched_existing_indices=incoming_in_existing,
            )
        return None

    @staticmethod
    def _visible_feature_token_set(group: dict) -> set[str]:
        tokens: set[str] = set()
        for unit in list(group.get("units", []) or []):
            if not isinstance(unit, dict):
                continue
            if str(unit.get("unit_role", unit.get("role", "")) or "") == "attribute":
                continue
            if not bool(unit.get("display_visible", True)):
                continue
            token = str(unit.get("token", "") or "")
            if token:
                tokens.add(token)
        if tokens:
            return tokens
        return {str(token) for token in list(group.get("tokens", []) or []) if str(token)}

    def _stable_subsequence_can_skip_groups(
        self,
        *,
        required_groups: list[dict],
        container_groups: list[dict],
        matched_indices: list[int],
    ) -> bool:
        if not required_groups or len(matched_indices) != len(required_groups):
            return False
        previous_index = -1
        for required_group, matched_index in zip(required_groups, matched_indices):
            try:
                matched_index = int(matched_index)
            except Exception:
                return False
            if matched_index <= previous_index:
                return False
            required_visible_tokens = self._visible_feature_token_set(required_group)
            for skipped_index in range(previous_index + 1, matched_index):
                if skipped_index < 0 or skipped_index >= len(container_groups):
                    continue
                skipped_visible_tokens = self._visible_feature_token_set(container_groups[skipped_index])
                if required_visible_tokens and skipped_visible_tokens and required_visible_tokens & skipped_visible_tokens:
                    return False
            previous_index = matched_index
        return True

    def _find_stable_group_subsequence_indices(
        self,
        *,
        required_groups: list[dict],
        container_groups: list[dict],
    ) -> list[int]:
        if not required_groups or not container_groups or len(required_groups) > len(container_groups):
            return []
        matched_indices: list[int] = []
        search_start = 0
        for required_group in required_groups:
            found_index = -1
            for container_index in range(search_start, len(container_groups)):
                if self._groups_have_same_stable_signature(required_group, container_groups[container_index]):
                    found_index = container_index
                    break
            if found_index < 0:
                return []
            matched_indices.append(found_index)
            search_start = found_index + 1
        return matched_indices

    def _try_single_group_common_part_fast_path(
        self,
        normalized_existing: list[dict],
        normalized_incoming: list[dict],
    ) -> dict | None:
        if len(normalized_existing) != 1 or len(normalized_incoming) != 1:
            return None
        group_match = self._maximum_common_group(
            existing_group=normalized_existing[0],
            incoming_group=normalized_incoming[0],
        )
        common_length = int(group_match.get("common_length", 0) or 0)
        if common_length <= 0:
            return self._empty_common_part(normalized_existing, normalized_incoming)

        common_group = self._reindex_group(dict(group_match.get("common_group", {}) or {}), order_index=0)
        common_groups = [common_group] if common_group.get("units") else []
        residual_existing_group = self._reindex_group(
            dict(group_match.get("residual_existing_group", {}) or {}),
            order_index=0,
        )
        residual_incoming_group = self._reindex_group(
            dict(group_match.get("residual_incoming_group", {}) or {}),
            order_index=0,
        )
        residual_existing_groups = [residual_existing_group] if residual_existing_group.get("units") else []
        residual_incoming_groups = [residual_incoming_group] if residual_incoming_group.get("units") else []
        existing_ids = [
            str(unit_id)
            for unit_id in list(group_match.get("matched_existing_unit_ids", []) or [])
            if str(unit_id)
        ]
        incoming_ids = [
            str(unit_id)
            for unit_id in list(group_match.get("matched_incoming_unit_ids", []) or [])
            if str(unit_id)
        ]
        common_tokens = [token for group in common_groups for token in group.get("tokens", [])]
        bundle_ok_existing_included = bool(group_match.get("bundle_constraints_ok_existing_included", True))
        bundle_ok_incoming_included = bool(group_match.get("bundle_constraints_ok_incoming_included", True))
        bundle_ok_exact = bool(bundle_ok_existing_included and bundle_ok_incoming_included)
        bundle_constraints = dict(group_match.get("bundle_constraints", {}) or {})
        return {
            "common_tokens": common_tokens,
            "common_length": sum(len(group.get("units", [])) for group in common_groups),
            "common_group_count": len(common_groups),
            "matched_existing_unit_count": int(group_match.get("matched_existing_unit_count", len(existing_ids)) or 0),
            "matched_incoming_unit_count": int(group_match.get("matched_incoming_unit_count", len(incoming_ids)) or 0),
            "common_signature": self.sequence_groups_to_signature(common_groups),
            "common_display": format_sequence_groups(common_groups) or "".join(common_tokens),
            "common_groups": common_groups,
            "matched_pairs": [
                {
                    "existing_group_index": 0,
                    "incoming_group_index": 0,
                    "common_tokens": list(common_group.get("tokens", [])),
                    "common_unit_signatures": list(common_group.get("unit_signatures", [])),
                    "incoming_unit_refs": incoming_ids,
                    "existing_unit_refs": existing_ids,
                    "matched_existing_unit_similarities": dict(group_match.get("matched_existing_unit_similarities", {})),
                    "matched_incoming_unit_similarities": dict(group_match.get("matched_incoming_unit_similarities", {})),
                    "common_bundle_signatures": list(common_group.get("bundle_signatures", [])),
                    "bundle_constraints_ok_existing_included": bundle_ok_existing_included,
                    "bundle_constraints_ok_incoming_included": bundle_ok_incoming_included,
                    "bundle_constraints_ok_exact": bundle_ok_exact,
                    "bundle_constraints": bundle_constraints,
                    "common_group": dict(common_group),
                    "residual_existing_group": dict(residual_existing_group),
                    "residual_incoming_group": dict(residual_incoming_group),
                }
            ],
            "matched_existing_unit_similarities": dict(group_match.get("matched_existing_unit_similarities", {})),
            "matched_incoming_unit_similarities": dict(group_match.get("matched_incoming_unit_similarities", {})),
            "bundle_constraints_ok_existing_included": bundle_ok_existing_included,
            "bundle_constraints_ok_incoming_included": bundle_ok_incoming_included,
            "bundle_constraints_ok_exact": bundle_ok_exact,
            "bundle_constraints": {
                "existing_included_in_incoming": dict(bundle_constraints.get("existing_included_in_incoming", {}) or {}),
                "incoming_included_in_existing": dict(bundle_constraints.get("incoming_included_in_existing", {}) or {}),
            },
            "existing_range": [0, 1],
            "incoming_range": [0, 1],
            "matched_existing_group_indices": [0],
            "matched_incoming_group_indices": [0],
            "residual_existing_tokens": [token for group in residual_existing_groups for token in group.get("tokens", [])],
            "residual_incoming_tokens": [token for group in residual_incoming_groups for token in group.get("tokens", [])],
            "residual_existing_groups": residual_existing_groups,
            "residual_incoming_groups": residual_incoming_groups,
            "residual_existing_signature": self.sequence_groups_to_signature(residual_existing_groups),
            "residual_incoming_signature": self.sequence_groups_to_signature(residual_incoming_groups),
        }

    def _build_full_inclusion_common_part(
        self,
        *,
        normalized_existing: list[dict],
        normalized_incoming: list[dict],
        matched_existing_indices: list[int] | None = None,
        matched_incoming_indices: list[int] | None = None,
    ) -> dict:
        existing_full_match = matched_incoming_indices is not None
        if existing_full_match:
            matched_existing_indices = list(range(len(normalized_existing)))
            matched_incoming_indices = list(matched_incoming_indices or [])
        else:
            matched_existing_indices = list(matched_existing_indices or [])
            matched_incoming_indices = list(range(len(normalized_incoming)))

        matched_pairs = []
        matched_existing_unit_similarities: dict[str, float] = {}
        matched_incoming_unit_similarities: dict[str, float] = {}
        common_groups = []
        common_tokens: list[str] = []

        for order_index, (existing_index, incoming_index) in enumerate(zip(matched_existing_indices, matched_incoming_indices)):
            existing_group = normalized_existing[int(existing_index)]
            incoming_group = normalized_incoming[int(incoming_index)]
            common_group = self._reuse_group_with_order_index(incoming_group, order_index=order_index)
            common_groups.append(common_group)
            common_tokens.extend(common_group.get("tokens", []))
            existing_units = [unit for unit in existing_group.get("units", []) if isinstance(unit, dict)]
            incoming_units = [unit for unit in incoming_group.get("units", []) if isinstance(unit, dict)]
            existing_ids = [str(unit.get("unit_id", "")) for unit in existing_units if str(unit.get("unit_id", ""))]
            incoming_ids = [str(unit.get("unit_id", "")) for unit in incoming_units if str(unit.get("unit_id", ""))]
            matched_existing_unit_similarities.update({unit_id: 1.0 for unit_id in existing_ids})
            matched_incoming_unit_similarities.update({unit_id: 1.0 for unit_id in incoming_ids})
            matched_pairs.append(
                {
                    "existing_group_index": int(existing_index),
                    "incoming_group_index": int(incoming_index),
                    "common_tokens": list(common_group.get("tokens", [])),
                    "common_unit_signatures": list(common_group.get("unit_signatures", [])),
                    "incoming_unit_refs": incoming_ids,
                    "existing_unit_refs": existing_ids,
                    "matched_existing_unit_similarities": {unit_id: 1.0 for unit_id in existing_ids},
                    "matched_incoming_unit_similarities": {unit_id: 1.0 for unit_id in incoming_ids},
                    "common_bundle_signatures": list(common_group.get("bundle_signatures", [])),
                    "bundle_constraints_ok_existing_included": True,
                    "bundle_constraints_ok_incoming_included": True,
                    "bundle_constraints_ok_exact": True,
                    "bundle_constraints": {
                        "existing_included_in_incoming": {
                            "ok": True,
                            "required_count": len(existing_ids),
                            "matched_count": len(existing_ids),
                            "unmatched": [],
                        },
                        "incoming_included_in_existing": {
                            "ok": True,
                            "required_count": len(incoming_ids),
                            "matched_count": len(incoming_ids),
                            "unmatched": [],
                        },
                    },
                    "common_group": dict(common_group),
                    "residual_existing_group": self._build_group_from_units(
                        template_group=existing_group,
                        units=[],
                        order_index=int(existing_group.get("group_index", 0)),
                    ),
                    "residual_incoming_group": self._build_group_from_units(
                        template_group=incoming_group,
                        units=[],
                        order_index=int(incoming_group.get("group_index", 0)),
                    ),
                }
            )

        matched_existing_set = {int(index) for index in matched_existing_indices}
        matched_incoming_set = {int(index) for index in matched_incoming_indices}
        residual_existing_groups = [
            self._reindex_group(group, order_index=order_index)
            for order_index, group in self._iter_unmatched_groups(normalized_existing, matched_existing_set)
        ]
        residual_incoming_groups = [
            self._reindex_group(group, order_index=order_index)
            for order_index, group in self._iter_unmatched_groups(normalized_incoming, matched_incoming_set)
        ]
        common_length = sum(len(group.get("units", [])) for group in common_groups)
        existing_span = [
            min(matched_existing_indices) if matched_existing_indices else 0,
            (max(matched_existing_indices) + 1) if matched_existing_indices else 0,
        ]
        incoming_span = [
            min(matched_incoming_indices) if matched_incoming_indices else 0,
            (max(matched_incoming_indices) + 1) if matched_incoming_indices else 0,
        ]
        return {
            "common_tokens": common_tokens,
            "common_length": common_length,
            "common_group_count": len(common_groups),
            "matched_existing_unit_count": sum(len(pair.get("existing_unit_refs", [])) for pair in matched_pairs),
            "matched_incoming_unit_count": sum(len(pair.get("incoming_unit_refs", [])) for pair in matched_pairs),
            "common_signature": self.sequence_groups_to_signature(common_groups),
            "common_display": format_sequence_groups(common_groups) or "".join(common_tokens),
            "common_groups": common_groups,
            "matched_pairs": matched_pairs,
            "matched_existing_unit_similarities": matched_existing_unit_similarities,
            "matched_incoming_unit_similarities": matched_incoming_unit_similarities,
            "bundle_constraints_ok_existing_included": True,
            "bundle_constraints_ok_incoming_included": True,
            "bundle_constraints_ok_exact": True,
            "bundle_constraints": {
                "existing_included_in_incoming": {
                    "ok": True,
                    "required_count": sum(len(pair.get("existing_unit_refs", [])) for pair in matched_pairs),
                    "matched_count": sum(len(pair.get("existing_unit_refs", [])) for pair in matched_pairs),
                    "unmatched": [],
                },
                "incoming_included_in_existing": {
                    "ok": True,
                    "required_count": sum(len(pair.get("incoming_unit_refs", [])) for pair in matched_pairs),
                    "matched_count": sum(len(pair.get("incoming_unit_refs", [])) for pair in matched_pairs),
                    "unmatched": [],
                },
            },
            "existing_range": existing_span,
            "incoming_range": incoming_span,
            "matched_existing_group_indices": [int(index) for index in matched_existing_indices],
            "matched_incoming_group_indices": [int(index) for index in matched_incoming_indices],
            "residual_existing_tokens": [token for group in residual_existing_groups for token in group.get("tokens", [])],
            "residual_incoming_tokens": [token for group in residual_incoming_groups for token in group.get("tokens", [])],
            "residual_existing_groups": residual_existing_groups,
            "residual_incoming_groups": residual_incoming_groups,
            "residual_existing_signature": self.sequence_groups_to_signature(residual_existing_groups),
            "residual_incoming_signature": self.sequence_groups_to_signature(residual_incoming_groups),
        }

    @staticmethod
    def _iter_unmatched_groups(groups: list[dict], matched_indices: set[int]):
        order_index = 0
        for index, group in enumerate(groups):
            if int(index) in matched_indices:
                continue
            yield order_index, group
            order_index += 1

    def _maximum_common_group_length(self, *, existing_group: dict, incoming_group: dict) -> int:
        cache_key = self._common_group_length_cache_key(existing_group, incoming_group)
        if cache_key is not None:
            cached = self._common_group_length_cache.get(cache_key)
            if cached is not None:
                self._common_group_length_cache.pop(cache_key, None)
                self._common_group_length_cache[cache_key] = int(cached)
                return int(cached)

        existing_units = list(existing_group.get("units", []))
        incoming_units = list(incoming_group.get("units", []))
        if not existing_units or not incoming_units:
            return self._remember_common_group_length(cache_key, 0)
        if self._groups_have_same_stable_signature(existing_group, incoming_group):
            return self._remember_common_group_length(cache_key, min(len(existing_units), len(incoming_units)))

        if self._group_requires_order_sensitive_match(existing_group) or self._group_requires_order_sensitive_match(incoming_group):
            subsequence_length = self._ordered_full_subsequence_pair_length(
                existing_units=existing_units,
                incoming_units=incoming_units,
            )
            if subsequence_length is not None:
                self._increment_runtime_metric("maximum_common_group_ordered_subsequence_fast_path_hit_count")
                return self._remember_common_group_length(cache_key, subsequence_length)
            return self._remember_common_group_length(
                cache_key,
                self._ordered_exact_pair_length(existing_units=existing_units, incoming_units=incoming_units),
            )

        available_existing: dict[str, list[dict]] = {}
        for unit in existing_units:
            available_existing.setdefault(str(unit.get("unit_signature", "")), []).append(unit)

        common_length = 0
        matched_existing_ids: set[str] = set()
        matched_incoming_ids: set[str] = set()

        for incoming_unit in incoming_units:
            signature = str(incoming_unit.get("unit_signature", ""))
            bucket = available_existing.get(signature, [])
            if not bucket:
                continue
            matched_existing = bucket.pop(0)
            existing_id = str(matched_existing.get("unit_id", ""))
            incoming_id = str(incoming_unit.get("unit_id", ""))
            if existing_id:
                matched_existing_ids.add(existing_id)
            if incoming_id:
                matched_incoming_ids.add(incoming_id)
            common_length += 1

        residual_existing = [unit for unit in existing_units if str(unit.get("unit_id", "")) not in matched_existing_ids]
        residual_incoming = [unit for unit in incoming_units if str(unit.get("unit_id", "")) not in matched_incoming_ids]

        still_existing = [unit for unit in residual_existing]
        remaining_incoming: list[dict] = []
        has_numeric_candidates = any(
            str(unit.get("unit_role", "")) == "attribute" and str(unit.get("attribute_name", "") or "")
            for unit in still_existing
        ) and any(
            str(unit.get("unit_role", "")) == "attribute" and str(unit.get("attribute_name", "") or "")
            for unit in residual_incoming
        )
        if has_numeric_candidates:
            for incoming_unit in residual_incoming:
                incoming_family = str(incoming_unit.get("attribute_name", "") or "")
                if str(incoming_unit.get("unit_role", "")) != "attribute" or not incoming_family:
                    remaining_incoming.append(incoming_unit)
                    continue
                best_index = -1
                best_key = None
                for index, existing_unit in enumerate(still_existing):
                    if (
                        str(existing_unit.get("unit_role", "")) != "attribute"
                        or str(existing_unit.get("attribute_name", "") or "") != incoming_family
                    ):
                        continue
                    numeric_match = self._numeric_unit_match(existing_unit=existing_unit, incoming_unit=incoming_unit)
                    if not numeric_match:
                        continue
                    candidate_key = (
                        float(numeric_match.get("similarity", 0.0)),
                        -float(numeric_match.get("distance", 0.0)),
                        -abs(int(existing_unit.get("sequence_index", 0)) - int(incoming_unit.get("sequence_index", 0))),
                    )
                    if best_key is None or candidate_key > best_key:
                        best_key = candidate_key
                        best_index = index
                if best_index < 0:
                    remaining_incoming.append(incoming_unit)
                    continue
                common_length += 1
                still_existing.pop(best_index)
        else:
            remaining_incoming = residual_incoming

        remaining_existing = [unit for unit in still_existing]
        has_structure_candidates = any(
            str(unit.get("object_type", "")) == "st" and str(unit.get("structure_fuzzy_signature", "") or "")
            for unit in remaining_existing
        ) and any(
            str(unit.get("object_type", "")) == "st" and str(unit.get("structure_fuzzy_signature", "") or "")
            for unit in remaining_incoming
        )
        if has_structure_candidates:
            for incoming_unit in remaining_incoming:
                incoming_signature = str(incoming_unit.get("structure_fuzzy_signature", "") or "")
                if str(incoming_unit.get("object_type", "")) != "st" or not incoming_signature:
                    continue
                best_index = -1
                best_key = None
                for index, existing_unit in enumerate(remaining_existing):
                    if (
                        str(existing_unit.get("object_type", "")) != "st"
                        or str(existing_unit.get("structure_fuzzy_signature", "") or "") != incoming_signature
                    ):
                        continue
                    structure_match = self._structure_unit_match(existing_unit=existing_unit, incoming_unit=incoming_unit)
                    if not structure_match:
                        continue
                    candidate_key = (
                        float(structure_match.get("similarity", 0.0)),
                        -abs(int(existing_unit.get("sequence_index", 0)) - int(incoming_unit.get("sequence_index", 0))),
                    )
                    if best_key is None or candidate_key > best_key:
                        best_key = candidate_key
                        best_index = index
                if best_index < 0:
                    continue
                common_length += 1
                remaining_existing.pop(best_index)

        return self._remember_common_group_length(cache_key, common_length)

    def make_structure_payload_from_profile(self, profile: dict, *, confidence: float = 0.8, ext: dict | None = None) -> dict:
        groups = self._normalize_sequence_groups(profile.get("sequence_groups", []))
        merged_ext = dict(profile.get("ext", {}))
        merged_ext.update(ext or {})
        merged_ext.setdefault("sequence_mode", "group_relaxed")
        merged_ext.setdefault("temporal_signature", self.sequence_groups_to_signature(groups))
        rebuilt_profile = self._build_profile(groups=groups, member_refs=list(profile.get("member_refs", [])))
        return {
            "display_text": profile.get("display_text", "") or rebuilt_profile.get("display_text", ""),
            "member_refs": list(profile.get("member_refs", [])),
            "sequence_groups": groups,
            "flat_tokens": list(rebuilt_profile.get("flat_tokens", [])),
            "content_signature": self.sequence_groups_to_signature(groups),
            "semantic_signature": self.sequence_groups_to_signature(groups),
            "confidence": confidence,
            "ext": merged_ext,
        }

    def make_structure_payload_from_tokens(self, tokens: list[str], *, confidence: float = 0.8, ext: dict | None = None) -> dict:
        tokens = [str(token) for token in tokens if str(token)]
        group = self._normalize_sequence_group(
            {
                "group_index": 0,
                "source_type": "cut",
                "origin_frame_id": "",
                "tokens": tokens,
            },
            order_index=0,
        )
        groups = [group] if group.get("units") else []
        merged_ext = dict(ext or {})
        merged_ext.setdefault("sequence_mode", "group_relaxed")
        merged_ext.setdefault("temporal_signature", self.sequence_groups_to_signature(groups))
        return {
            "display_text": format_sequence_groups(groups) or "".join(tokens),
            "member_refs": [],
            "sequence_groups": groups,
            "flat_tokens": [token for group in groups for token in group.get("tokens", [])],
            "content_signature": self.sequence_groups_to_signature(groups),
            "semantic_signature": self.sequence_groups_to_signature(groups),
            "confidence": confidence,
            "ext": merged_ext,
        }

    def make_structure_payload_from_units(
        self,
        units: list[dict],
        *,
        confidence: float = 0.8,
        ext: dict | None = None,
        force_strict_order: bool | None = None,
    ) -> dict:
        valid_units = [dict(unit) for unit in units if isinstance(unit, dict) and str(unit.get("token", ""))]
        if not valid_units:
            return self.make_structure_payload_from_tokens([], confidence=confidence, ext=ext)

        member_refs = [str(unit.get("unit_id", "")) for unit in valid_units if str(unit.get("unit_id", ""))]
        source_types = {str(unit.get("source_type", "")) for unit in valid_units if str(unit.get("source_type", ""))}
        strict_order = bool(force_strict_order)
        if strict_order:
            raw_groups = [
                {
                    "group_index": order_index,
                    "source_type": str(unit.get("source_type", "")),
                    "origin_frame_id": str(unit.get("origin_frame_id", "")),
                    "units": [dict(unit)],
                    "source_group_index": int(unit.get("source_group_index", unit.get("group_index", order_index))),
                    "source_sequence_index": int(unit.get("sequence_index", 0)),
                }
                for order_index, unit in enumerate(valid_units)
            ]
        else:
            grouped_map: dict[tuple[int, str, str], list[dict]] = {}
            group_keys: list[tuple[int, str, str]] = []
            for unit in valid_units:
                key = (
                    int(unit.get("group_index", 0)),
                    str(unit.get("source_type", "")),
                    str(unit.get("origin_frame_id", "")),
                )
                if key not in grouped_map:
                    grouped_map[key] = []
                    group_keys.append(key)
                grouped_map[key].append(dict(unit))
            raw_groups = []
            for order_index, key in enumerate(group_keys):
                members = sorted(grouped_map[key], key=lambda item: int(item.get("sequence_index", 0)))
                if not members:
                    continue
                raw_groups.append(
                    {
                        "group_index": order_index,
                        "source_type": key[1],
                        "origin_frame_id": key[2],
                        "units": members,
                        "source_group_index": int(members[0].get("source_group_index", key[0])),
                        "source_sequence_index": int(members[0].get("sequence_index", 0)),
                    }
                )

        sequence_groups = self._normalize_sequence_groups(raw_groups)
        temporal_signature = self.sequence_groups_to_signature(sequence_groups)
        merged_ext = dict(ext or {})
        merged_ext.setdefault("sequence_mode", "strict_order" if strict_order else "group_relaxed")
        merged_ext.setdefault("temporal_signature", temporal_signature)
        merged_ext.setdefault("source_types", sorted(source_types))

        flat_tokens = [token for group in sequence_groups for token in group.get("tokens", [])]
        display_text = format_sequence_groups(sequence_groups) or "".join(flat_tokens)
        return {
            "display_text": display_text,
            "member_refs": member_refs,
            "sequence_groups": sequence_groups,
            "flat_tokens": flat_tokens,
            "content_signature": temporal_signature,
            "semantic_signature": temporal_signature,
            "confidence": confidence,
            "ext": merged_ext,
        }

    def build_internal_stimulus_packet(self, fragments: list[dict], trace_id: str, tick_id: str = "") -> dict:
        now_ms = int(time.time() * 1000)
        packet_id = next_id("ispkt")
        sa_items = []
        csa_items = []
        grouped_sequences = []
        flatten_internal_group = self._internal_single_cooccurrence_group_enabled()
        flattened_group_sa_ids: list[str] = []
        flattened_group_csa_ids: list[str] = []
        flattened_source_groups: list[dict] = []
        flattened_string_groups: list[dict] = []
        packet_sequence_index = 0

        for fragment in fragments:
            fragment_ext = fragment.get("ext", {}) if isinstance(fragment.get("ext", {}), dict) else {}
            skip_display_only_tokens = bool(fragment_ext.get("display_fallback_char_split", False))
            sequence_groups = fragment.get("sequence_groups") or [
                {
                    "group_index": 0,
                    "source_type": "internal",
                    "origin_frame_id": fragment.get("fragment_id", ""),
                    "tokens": list(fragment.get("flat_tokens", [])),
                }
            ]
            normalized_groups = self._normalize_sequence_groups(sequence_groups)
            if skip_display_only_tokens:
                filtered_groups: list[dict] = []
                for group in normalized_groups:
                    allowed_units = [
                        dict(unit)
                        for unit in (group.get("units", []) or [])
                        if not is_display_only_token(str(unit.get("token", "")))
                    ]
                    if not allowed_units:
                        continue
                    allowed_unit_ids = {
                        str(unit.get("unit_id", ""))
                        for unit in allowed_units
                        if str(unit.get("unit_id", ""))
                    }
                    filtered_bundles = []
                    for bundle in group.get("csa_bundles", []) or []:
                        if not isinstance(bundle, dict):
                            continue
                        anchor_unit_id = str(bundle.get("anchor_unit_id", ""))
                        member_unit_ids = [
                            str(member_id)
                            for member_id in bundle.get("member_unit_ids", []) or []
                            if str(member_id) in allowed_unit_ids
                        ]
                        if anchor_unit_id not in allowed_unit_ids or len(member_unit_ids) < 2:
                            continue
                        filtered_bundle = dict(bundle)
                        filtered_bundle["member_unit_ids"] = member_unit_ids
                        filtered_bundles.append(filtered_bundle)

                    filtered_group = dict(group)
                    filtered_group["units"] = allowed_units
                    filtered_group["csa_bundles"] = filtered_bundles
                    filtered_group["tokens"] = [
                        str(unit.get("token", ""))
                        for unit in allowed_units
                        if str(unit.get("token", ""))
                    ]
                    filtered_groups.append(filtered_group)
                normalized_groups = filtered_groups

            unit_count = sum(len(group.get("units", [])) for group in normalized_groups)
            if unit_count <= 0:
                continue
            fragment_total_er = round(float(fragment.get("er_hint", fragment.get("energy_hint", 0.0))), 6)
            fragment_total_ev = round(float(fragment.get("ev_hint", fragment.get("energy_hint", 0.0))), 6)
            per_unit_er = round(fragment_total_er / unit_count, 6)
            per_unit_ev = round(fragment_total_ev / unit_count, 6)

            for source_group in normalized_groups:
                units = list(source_group.get("units", []))
                if not units:
                    continue
                group_unit_id_map: dict[str, str] = {}
                created_sa_items: list[dict] = []
                created_csa_items: list[dict] = []

                for unit in units:
                    if bool(self._config.get("enable_goal_b_char_sa_string_mode", False)):
                        token_preview = str(unit.get("token", "") or unit.get("display_text", "") or "")
                        if str(unit.get("object_type", "sa") or "sa") in {"st", "sg"}:
                            continue
                        if bool(unit.get("is_placeholder", False)) or token_preview.startswith("SELF["):
                            continue
                    sa_id = next_id("sa_internal")
                    token = str(unit.get("token", ""))
                    attribute_name = str(unit.get("attribute_name", ""))
                    attribute_value = unit.get("attribute_value")
                    value_type = str(unit.get("value_type", "discrete") or "discrete")
                    if attribute_name:
                        content = {
                            "raw": token,
                            "display": token,
                            "normalized": token,
                            "value_type": "numerical" if attribute_value is not None else value_type,
                            "attribute_name": attribute_name,
                            "attribute_value": attribute_value,
                        }
                    else:
                        content = {
                            "raw": token,
                            "display": token,
                            "normalized": token,
                            "value_type": value_type,
                        }
                    packet_context = {
                        "source_type": "internal",
                        "group_index": 0,
                        "source_group_index": int(source_group.get("source_group_index", source_group.get("group_index", 0))),
                        "origin_frame_id": source_group.get("origin_frame_id", fragment.get("fragment_id", "")),
                        "echo_depth": 0,
                        "round_created": 0,
                        "decay_count": 0,
                        "sequence_index": packet_sequence_index,
                        "order_sensitive": bool(unit.get("order_sensitive", source_group.get("order_sensitive", False))),
                        "string_unit_kind": str(unit.get("string_unit_kind", source_group.get("string_unit_kind", "")) or ""),
                        "string_token_text": str(unit.get("string_token_text", source_group.get("string_token_text", "")) or ""),
                    }
                    role = str(unit.get("unit_role", "feature"))
                    sa_obj = {
                        "id": sa_id,
                        "object_type": "sa",
                        "content": content,
                        "stimulus": {"role": role, "modality": "internal_text"},
                        "energy": {"er": per_unit_er, "ev": per_unit_ev},
                        "source": {
                            "module": "hdb",
                            "interface": "build_internal_stimulus_packet",
                            "origin": "internal_fragments",
                            "origin_id": fragment.get("fragment_id", ""),
                            "parent_ids": [],
                        },
                        "ext": {"packet_context": packet_context},
                        "created_at": now_ms,
                        "updated_at": now_ms,
                    }
                    group_unit_id_map[str(unit.get("unit_id", ""))] = sa_id
                    created_sa_items.append(sa_obj)
                    sa_items.append(sa_obj)
                    packet_sequence_index += 1

                created_sa_by_id = {item["id"]: item for item in created_sa_items}
                for bundle in source_group.get("csa_bundles", []):
                    anchor_id = group_unit_id_map.get(str(bundle.get("anchor_unit_id", "")), "")
                    member_ids = [
                        group_unit_id_map.get(str(member_id), "")
                        for member_id in bundle.get("member_unit_ids", [])
                        if group_unit_id_map.get(str(member_id), "")
                    ]
                    member_ids = self._dedupe_preserve_order(member_ids)
                    if not anchor_id or len(member_ids) < 2:
                        continue
                    csa_id = next_id("csa_internal")
                    csa_obj = {
                        "id": csa_id,
                        "object_type": "csa",
                        "anchor_sa_id": anchor_id,
                        "member_sa_ids": member_ids,
                        "content": {
                            "display": f"CSA[{created_sa_by_id.get(anchor_id, {}).get('content', {}).get('display', '')}]",
                            "raw": created_sa_by_id.get(anchor_id, {}).get("content", {}).get("raw", ""),
                        },
                        "bundle_summary": {
                            "member_count": len(member_ids),
                            "display_total_er": round(
                                sum(float(created_sa_by_id.get(member_id, {}).get("energy", {}).get("er", 0.0)) for member_id in member_ids),
                                6,
                            ),
                            "display_total_ev": round(
                                sum(float(created_sa_by_id.get(member_id, {}).get("energy", {}).get("ev", 0.0)) for member_id in member_ids),
                                6,
                            ),
                        },
                        "ext": {
                            "packet_context": {
                                "group_index": 0,
                                "source_group_index": int(source_group.get("source_group_index", source_group.get("group_index", 0))),
                                "origin_frame_id": source_group.get("origin_frame_id", fragment.get("fragment_id", "")),
                                "source_type": "internal",
                                "sequence_index": int(
                                    created_sa_by_id.get(anchor_id, {}).get("ext", {}).get("packet_context", {}).get("sequence_index", 0)
                                ),
                            },
                            "source_bundle_id": str(bundle.get("bundle_id", "")),
                        },
                        "created_at": now_ms,
                        "updated_at": now_ms,
                    }
                    csa_items.append(csa_obj)
                    created_csa_items.append(csa_obj)
                    for member_id in member_ids:
                        sa_obj = created_sa_by_id.get(member_id)
                        if not sa_obj:
                            continue
                        if member_id != anchor_id and sa_obj.get("stimulus", {}).get("role") == "attribute":
                            sa_obj.setdefault("source", {}).setdefault("parent_ids", [])
                            sa_obj["source"]["parent_ids"] = [anchor_id]

                created_group = {
                    "group_index": len(grouped_sequences),
                    "source_type": "internal",
                    "origin_frame_id": source_group.get("origin_frame_id", fragment.get("fragment_id", packet_id)),
                    "sa_ids": self._dedupe_preserve_order([item.get("id", "") for item in created_sa_items if item.get("id")]),
                    "csa_ids": self._dedupe_preserve_order([item.get("id", "") for item in created_csa_items if item.get("id")]),
                    "source_group_index": int(source_group.get("source_group_index", source_group.get("group_index", len(grouped_sequences)))),
                    "order_sensitive": bool(source_group.get("order_sensitive", False)),
                    "string_unit_kind": str(source_group.get("string_unit_kind", "") or ""),
                    "string_token_text": str(source_group.get("string_token_text", "") or ""),
                }
                if flatten_internal_group:
                    flattened_group_sa_ids.extend(list(created_group.get("sa_ids", []) or []))
                    flattened_group_csa_ids.extend(list(created_group.get("csa_ids", []) or []))
                    flattened_source_groups.append(
                        {
                            "fragment_id": str(fragment.get("fragment_id", "") or ""),
                            "origin_frame_id": str(created_group.get("origin_frame_id", "") or ""),
                            "group_index": int(source_group.get("group_index", len(flattened_source_groups)) or len(flattened_source_groups)),
                            "source_group_index": int(created_group.get("source_group_index", created_group.get("group_index", 0)) or 0),
                            "order_sensitive": bool(created_group.get("order_sensitive", False)),
                            "string_unit_kind": str(created_group.get("string_unit_kind", "") or ""),
                            "string_token_text": str(created_group.get("string_token_text", "") or ""),
                            "sa_count": len(list(created_group.get("sa_ids", []) or [])),
                            "csa_count": len(list(created_group.get("csa_ids", []) or [])),
                        }
                    )
                    if bool(created_group.get("order_sensitive", False)) or str(created_group.get("string_token_text", "") or ""):
                        string_group_payload = dict(created_group)
                        string_group_payload["group_index"] = int(
                            source_group.get("group_index", len(flattened_string_groups)) or len(flattened_string_groups)
                        )
                        flattened_string_groups.append(string_group_payload)
                else:
                    grouped_sequences.append(created_group)

        if flatten_internal_group and (flattened_group_sa_ids or flattened_group_csa_ids):
            flattened_ext = {
                "flattened_internal_single_group": True,
                "flattened_source_group_count": len(flattened_source_groups),
                "flattened_source_groups": [dict(row) for row in flattened_source_groups if isinstance(row, dict)],
            }
            if flattened_string_groups:
                flattened_ext["internal_string_groups"] = [dict(group) for group in flattened_string_groups if isinstance(group, dict)]
            grouped_sequences = [
                {
                    "group_index": 0,
                    "source_type": "internal",
                    "origin_frame_id": packet_id,
                    "sa_ids": self._dedupe_preserve_order(flattened_group_sa_ids),
                    "csa_ids": self._dedupe_preserve_order(flattened_group_csa_ids),
                    "source_group_index": 0,
                    "order_sensitive": False,
                    "string_unit_kind": "",
                    "string_token_text": "",
                    "ext": flattened_ext,
                }
            ]

        total_er = round(sum(item.get("energy", {}).get("er", 0.0) for item in sa_items), 6)
        total_ev = round(sum(item.get("energy", {}).get("ev", 0.0) for item in sa_items), 6)
        return {
            "id": packet_id,
            "object_type": "stimulus_packet",
            "sub_type": "internal_residual_stimulus_packet",
            "schema_version": "1.1",
            "packet_type": "internal",
            "current_frame_id": packet_id,
            "echo_frame_ids": [],
            "sa_items": sa_items,
            "csa_items": csa_items,
            "echo_frames": [],
            "grouped_sa_sequences": grouped_sequences,
            "energy_summary": {
                "total_er": total_er,
                "total_ev": total_ev,
                "current_total_er": total_er,
                "current_total_ev": total_ev,
                "echo_total_er": 0.0,
                "echo_total_ev": 0.0,
                "combined_context_er": total_er,
                "combined_context_ev": total_ev,
                "ownership_level": "sa",
                "echo_merged_into_objects": False,
            },
            "trace_id": trace_id,
            "tick_id": tick_id or trace_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "source": {
                "module": "hdb",
                "interface": "build_internal_stimulus_packet",
                "origin": "internal_fragments",
                "origin_id": packet_id,
                "parent_ids": [fragment.get("fragment_id", "") for fragment in fragments],
            },
            "status": "active",
            "ext": {},
            "meta": {"confidence": 0.7, "field_registry_version": "1.1", "debug": {}, "ext": {}},
        }

    def merge_stimulus_packets(self, external_packet: dict | None, internal_packet: dict | None, trace_id: str, tick_id: str = "") -> dict:
        external_packet = external_packet if isinstance(external_packet, dict) and external_packet else None
        internal_packet = internal_packet if isinstance(internal_packet, dict) and internal_packet else None
        if external_packet and not internal_packet:
            return external_packet
        if not external_packet and not internal_packet:
            return self.build_internal_stimulus_packet([], trace_id=trace_id, tick_id=tick_id)

        now_ms = int(time.time() * 1000)

        # When we merge "internal co-occurrence stimulus" into the last external sequence group,
        # we must ensure the internal units do not interleave with external units in display/order.
        #
        # Important:
        # - Internal stimulus is order-relaxed (bag/co-occurrence) by design.
        # - External stimulus keeps strict group order.
        # - In our profile builder, units within a group are sorted by packet_context.sequence_index.
        #   If internal items keep sequence_index starting from 0, they may appear *before* external tokens
        #   in the merged last group, which looks like "时序结构混乱" in the UI.
        #
        # Fix (best-effort, low-risk):
        # - Rebase internal SA/CSA packet_context.sequence_index to (max external sequence_index + 1),
        #   so merged ordering is stable and external-first.
        def _extract_seq(obj: dict) -> int:
            ctx = (obj.get("ext", {}) or {}).get("packet_context", {})
            if isinstance(ctx, dict):
                try:
                    if ctx.get("sequence_index", None) is not None:
                        return int(ctx.get("sequence_index", 0))
                except Exception:
                    pass
            try:
                return int((obj.get("stimulus", {}) or {}).get("global_sequence_index", 0) or 0)
            except Exception:
                return 0

        external_max_seq = 0
        try:
            for item in list((external_packet or {}).get("sa_items", []) or []):
                if not isinstance(item, dict):
                    continue
                external_max_seq = max(external_max_seq, _extract_seq(item))
            for item in list((external_packet or {}).get("csa_items", []) or []):
                if not isinstance(item, dict):
                    continue
                external_max_seq = max(external_max_seq, _extract_seq(item))
        except Exception:
            external_max_seq = 0

        def _rebase_internal_obj(obj: dict) -> dict:
            cloned = dict(obj)
            ext = dict(cloned.get("ext", {}) or {})
            ctx = dict(ext.get("packet_context", {}) or {})
            ctx["sequence_index"] = int(external_max_seq) + 1
            ext["packet_context"] = ctx
            cloned["ext"] = ext
            return cloned

        should_rebase_internal = bool(external_packet)
        external_sa_items = [item for item in list((external_packet or {}).get("sa_items", []) or []) if isinstance(item, dict)]
        external_csa_items = [item for item in list((external_packet or {}).get("csa_items", []) or []) if isinstance(item, dict)]
        internal_sa_items = [
            (_rebase_internal_obj(item) if should_rebase_internal else dict(item))
            for item in list((internal_packet or {}).get("sa_items", []) or [])
            if isinstance(item, dict)
        ]
        internal_csa_items = [
            (_rebase_internal_obj(item) if should_rebase_internal else dict(item))
            for item in list((internal_packet or {}).get("csa_items", []) or [])
            if isinstance(item, dict)
        ]

        merged_origin = "external_plus_internal" if external_packet and internal_packet else "internal_only_packet"
        merged_current_frame_id = (
            (external_packet or {}).get("current_frame_id")
            or (external_packet or {}).get("id")
            or (internal_packet or {}).get("current_frame_id")
            or (internal_packet or {}).get("id", "")
        )
        merged_parent_ids = [
            parent_id
            for parent_id in (
                (external_packet or {}).get("id", ""),
                (internal_packet or {}).get("id", ""),
            )
            if str(parent_id)
        ]

        merged = {
            "id": next_id("spkt_merge"),
            "object_type": "stimulus_packet",
            "sub_type": "merged_stimulus_packet",
            "schema_version": "1.1",
            "packet_type": "merged",
            "current_frame_id": merged_current_frame_id,
            "echo_frame_ids": list((external_packet or {}).get("echo_frame_ids", [])),
            "sa_items": list(external_sa_items) + list(internal_sa_items),
            "csa_items": list(external_csa_items) + list(internal_csa_items),
            "echo_frames": list((external_packet or {}).get("echo_frames", [])),
            "grouped_sa_sequences": [],
            "trace_id": trace_id,
            "tick_id": tick_id or trace_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "source": {
                "module": "hdb",
                "interface": "merge_stimulus_packets",
                "origin": merged_origin,
                "origin_id": str((external_packet or {}).get("id", "") or (internal_packet or {}).get("id", "")),
                "parent_ids": merged_parent_ids,
            },
            "status": "active",
            "ext": {},
            "meta": {"confidence": 0.8, "field_registry_version": "1.1", "debug": {}, "ext": {}},
        }

        external_groups = [dict(group) for group in (external_packet or {}).get("grouped_sa_sequences", []) if isinstance(group, dict)]
        internal_groups = [dict(group) for group in (internal_packet or {}).get("grouped_sa_sequences", []) if isinstance(group, dict)]
        internal_sa_ids = [
            str(sa_id)
            for group in internal_groups
            for sa_id in group.get("sa_ids", [])
            if str(sa_id)
        ]
        internal_csa_ids = [
            str(csa_id)
            for group in internal_groups
            for csa_id in group.get("csa_ids", [])
            if str(csa_id)
        ]
        if not internal_sa_ids:
            internal_sa_ids = [str(item.get("id", "")) for item in (internal_packet or {}).get("sa_items", []) if str(item.get("id", ""))]
        if not internal_csa_ids:
            internal_csa_ids = [str(item.get("id", "")) for item in (internal_packet or {}).get("csa_items", []) if str(item.get("id", ""))]

        if bool(self._config.get("enable_goal_b_char_sa_string_mode", False)) and internal_groups:
            string_texts = {
                str(group.get("string_token_text", "") or "").strip()
                for group in internal_groups
                if isinstance(group, dict)
                and bool(group.get("order_sensitive", False))
                and str(group.get("string_unit_kind", "") or "") == "char_sequence"
                and str(group.get("string_token_text", "") or "").strip()
            }
            filtered_internal_sa_ids = []
            for sa_id in self._dedupe_preserve_order(internal_sa_ids):
                sa_obj = next((item for item in internal_sa_items if str(item.get("id", "")) == str(sa_id)), None)
                if not isinstance(sa_obj, dict):
                    filtered_internal_sa_ids.append(sa_id)
                    continue
                ctx = ((sa_obj.get("ext", {}) or {}).get("packet_context", {}) or {})
                token_text = str(((sa_obj.get("content", {}) or {}).get("raw", (sa_obj.get("content", {}) or {}).get("display", "")) or "").strip())
                if (
                    token_text in string_texts
                    and not bool(ctx.get("order_sensitive", False))
                    and str(ctx.get("string_unit_kind", "") or "") != "char_sequence"
                ):
                    continue
                filtered_internal_sa_ids.append(sa_id)
            string_group_payload: list[dict] = []
            for group in internal_groups:
                if not isinstance(group, dict):
                    continue
                group_ext = dict(group.get("ext", {}) or {}) if isinstance(group.get("ext", {}), dict) else {}
                embedded_groups = group_ext.get("internal_string_groups", []) if isinstance(group_ext.get("internal_string_groups", []), list) else []
                if embedded_groups:
                    string_group_payload.extend(dict(row) for row in embedded_groups if isinstance(row, dict))
                else:
                    string_group_payload.append(dict(group))
            if external_groups:
                merged_groups = [dict(group) for group in external_groups]
                last_group = dict(merged_groups[-1])
                last_group["sa_ids"] = self._dedupe_preserve_order(
                    list(last_group.get("sa_ids", []) or []) + list(filtered_internal_sa_ids)
                )
                last_group["csa_ids"] = self._dedupe_preserve_order(
                    list(last_group.get("csa_ids", []) or []) + list(internal_csa_ids)
                )
                last_ext = dict(last_group.get("ext", {}) or {})
                last_ext["contains_internal_group"] = True
                last_ext["internal_merge_mode"] = "append_to_last_external_group"
                last_ext["internal_source_packet_id"] = str((internal_packet or {}).get("id", "") or "")
                last_ext["internal_string_groups"] = string_group_payload
                last_group["ext"] = last_ext
                merged_groups[-1] = last_group
            else:
                merged_internal_group = {
                    "group_index": 0,
                    "source_type": "internal",
                    "origin_frame_id": (internal_packet or {}).get("id", ""),
                    "sa_ids": filtered_internal_sa_ids,
                    "csa_ids": self._dedupe_preserve_order(internal_csa_ids),
                    "source_group_index": 0,
                    "order_sensitive": False,
                    "string_unit_kind": "",
                    "string_token_text": "",
                    "ext": {
                        "contains_string_groups": True,
                        "contains_internal_group": True,
                        "internal_merge_mode": "internal_only_packet",
                        "internal_string_groups": string_group_payload,
                    },
                }
                merged_groups = [merged_internal_group]
        elif internal_groups:
            if external_groups:
                merged_groups = [dict(group) for group in external_groups]
                last_group = dict(merged_groups[-1])
                appended_sa_ids = [
                    str(sa_id) for group in internal_groups for sa_id in (group.get("sa_ids", []) or []) if str(sa_id)
                ]
                appended_csa_ids = [
                    str(csa_id) for group in internal_groups for csa_id in (group.get("csa_ids", []) or []) if str(csa_id)
                ]
                last_group["sa_ids"] = self._dedupe_preserve_order(
                    list(last_group.get("sa_ids", []) or []) + appended_sa_ids
                )
                last_group["csa_ids"] = self._dedupe_preserve_order(
                    list(last_group.get("csa_ids", []) or []) + appended_csa_ids
                )
                last_ext = dict(last_group.get("ext", {}) or {})
                last_ext["contains_internal_group"] = True
                last_ext["internal_merge_mode"] = "append_to_last_external_group"
                last_ext["internal_groups"] = [dict(group) for group in internal_groups if isinstance(group, dict)]
                last_group["ext"] = last_ext
                merged_groups[-1] = last_group
            else:
                merged_groups = [dict(group) for group in internal_groups]
                if merged_groups:
                    first_group = dict(merged_groups[0])
                    first_ext = dict(first_group.get("ext", {}) or {})
                    first_ext["contains_internal_group"] = True
                    first_ext["internal_merge_mode"] = "internal_only_packet"
                    first_ext["internal_source_packet_id"] = str((internal_packet or {}).get("id", "") or "")
                    first_group["ext"] = first_ext
                    merged_groups[0] = first_group
        elif internal_sa_ids or internal_csa_ids:
            if external_groups:
                merged_groups = [dict(group) for group in external_groups]
                last_group = dict(merged_groups[-1])
                last_group["sa_ids"] = self._dedupe_preserve_order(
                    list(last_group.get("sa_ids", []) or []) + list(internal_sa_ids)
                )
                last_group["csa_ids"] = self._dedupe_preserve_order(
                    list(last_group.get("csa_ids", []) or []) + list(internal_csa_ids)
                )
                last_ext = dict(last_group.get("ext", {}) or {})
                last_ext["contains_internal_group"] = True
                last_ext["internal_merge_mode"] = "append_to_last_external_group"
                last_ext["internal_source_packet_id"] = str((internal_packet or {}).get("id", "") or "")
                last_group["ext"] = last_ext
                merged_groups[-1] = last_group
            else:
                merged_groups = [
                    {
                        "group_index": 0,
                        "source_type": "internal",
                        "origin_frame_id": (internal_packet or {}).get("id", ""),
                        "sa_ids": self._dedupe_preserve_order(internal_sa_ids),
                        "csa_ids": self._dedupe_preserve_order(internal_csa_ids),
                        "source_group_index": 0,
                        "ext": {
                            "contains_internal_group": True,
                            "internal_merge_mode": "internal_only_packet",
                        },
                    }
                ]
        else:
            merged_groups = list(external_groups)

        if bool(self._config.get("enable_goal_b_char_sa_string_mode", False)):
            string_group_signatures: list[tuple[str, ...]] = []
            for group in merged_groups:
                if not isinstance(group, dict):
                    continue
                if not bool(group.get("order_sensitive", False)):
                    continue
                if str(group.get("string_unit_kind", "") or "") != "char_sequence":
                    continue
                group_sa = [
                    item for item in merged.get("sa_items", [])
                    if isinstance(item, dict) and str(((item.get("ext", {}) or {}).get("packet_context", {}) or {}).get("group_index", "")) == str(group.get("group_index", ""))
                ]
                tokens = [
                    str(((item.get("content", {}) or {}).get("raw", (item.get("content", {}) or {}).get("display", "")) or ""))
                    for item in group_sa
                    if str(((item.get("stimulus", {}) or {}).get("role", "feature") or "feature")) == "feature"
                ]
                tokens = [t for t in tokens if t]
                if len(tokens) >= 2:
                    string_group_signatures.append(tuple(tokens))
            if string_group_signatures:
                filtered_groups = []
                for group in merged_groups:
                    if not isinstance(group, dict):
                        continue
                    if bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence":
                        filtered_groups.append(group)
                        continue
                    group_sa = [
                        item for item in merged.get("sa_items", [])
                        if isinstance(item, dict) and str(((item.get("ext", {}) or {}).get("packet_context", {}) or {}).get("group_index", "")) == str(group.get("group_index", ""))
                    ]
                    feature_tokens = [
                        str(((item.get("content", {}) or {}).get("raw", (item.get("content", {}) or {}).get("display", "")) or ""))
                        for item in group_sa
                        if str(((item.get("stimulus", {}) or {}).get("role", "feature") or "feature")) == "feature"
                    ]
                    feature_tokens = [t for t in feature_tokens if t]
                    if len(feature_tokens) == 1 and any(feature_tokens[0] in sig for sig in string_group_signatures):
                        continue
                    filtered_groups.append(group)
                merged_groups = filtered_groups
        for index, group in enumerate(merged_groups):
            group["group_index"] = index
        merged["grouped_sa_sequences"] = merged_groups

        total_er = sum(item.get("energy", {}).get("er", 0.0) for item in merged["sa_items"])
        total_ev = sum(item.get("energy", {}).get("ev", 0.0) for item in merged["sa_items"])
        merged["energy_summary"] = {
            "total_er": round(total_er, 6),
            "total_ev": round(total_ev, 6),
            "current_total_er": round(total_er, 6),
            "current_total_ev": round(total_ev, 6),
            "echo_total_er": round(sum(item.get("energy", {}).get("er", 0.0) for item in (internal_packet or {}).get("sa_items", [])), 6),
            "echo_total_ev": round(sum(item.get("energy", {}).get("ev", 0.0) for item in (internal_packet or {}).get("sa_items", [])), 6),
            "combined_context_er": round(total_er, 6),
            "combined_context_ev": round(total_ev, 6),
            "ownership_level": "sa",
            "echo_merged_into_objects": True,
        }
        return merged

    def tokens_to_signature(self, tokens: list[str]) -> str:
        return "|".join(str(token) for token in tokens if str(token))

    def group_tokens_to_signature(self, tokens: list[str]) -> str:
        normalized = [str(token) for token in tokens if str(token)]
        normalized.sort()
        return self.tokens_to_signature(normalized)

    def sequence_groups_to_signature(self, groups: list[dict]) -> str:
        if groups and isinstance(groups, list):
            reusable_groups: list[dict] = []
            all_reusable = True
            for order_index, group in enumerate(groups):
                if not isinstance(group, dict) or not self._is_reusable_normalized_group(group, order_index=order_index):
                    all_reusable = False
                    break
                reusable_groups.append(group)
            if all_reusable:
                self._increment_runtime_metric("sequence_groups_signature_fast_path_hit_count")
                return self._signature_from_normalized_groups(reusable_groups)
        normalized_groups = self._normalize_sequence_groups(groups)
        return self._signature_from_normalized_groups(normalized_groups)

    def profile_equals(self, left_profile: dict, right_profile: dict) -> bool:
        return self.sequence_groups_to_signature(left_profile.get("sequence_groups", [])) == self.sequence_groups_to_signature(
            right_profile.get("sequence_groups", [])
        )

    def _build_profile(self, *, groups: list[dict], member_refs: list[str]) -> dict:
        flat_units = [
            unit
            for group in groups
            for unit in group.get("units", [])
            if isinstance(unit, dict)
        ]
        flat_tokens = [token for group in groups for token in group.get("tokens", [])]
        flat_unit_signatures = [
            str(unit.get("unit_signature", ""))
            for unit in flat_units
            if str(unit.get("unit_signature", ""))
        ]
        all_unit_token_counts: dict[str, int] = {}
        for unit in flat_units:
            token = str(unit.get("token", "") or "")
            if not token:
                continue
            all_unit_token_counts[token] = int(all_unit_token_counts.get(token, 0)) + 1
        content_signature = self._signature_from_normalized_groups(groups)
        display_text = self._display_from_normalized_groups(groups) or "".join(flat_tokens)
        return {
            "display_text": display_text,
            "flat_tokens": flat_tokens,
            "flat_unit_signatures": flat_unit_signatures,
            "all_units": flat_units,
            "all_unit_token_counts": all_unit_token_counts,
            "member_refs": [ref for ref in member_refs if ref],
            "sequence_groups": groups,
            "content_signature": content_signature,
            "semantic_signature": content_signature,
            "token_count": len(flat_tokens),
            "unit_count": len(flat_units),
        }

    @staticmethod
    def _copy_normalized_groups(groups: list[dict]) -> list[dict]:
        copied: list[dict] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            row = dict(group)
            row["tokens"] = list(group.get("tokens", []) or [])
            row["units"] = [dict(unit) for unit in (group.get("units", []) or []) if isinstance(unit, dict)]
            row["unit_signatures"] = list(group.get("unit_signatures", []) or [])
            row["csa_bundles"] = [dict(bundle) for bundle in (group.get("csa_bundles", []) or []) if isinstance(bundle, dict)]
            row["bundle_signatures"] = list(group.get("bundle_signatures", []) or [])
            copied.append(row)
        return copied

    def _copy_cached_normalized_groups(self, groups: list[dict]) -> list[dict]:
        if bool(self._config.get("normalize_sequence_groups_cache_zero_copy_enabled", False)):
            self._increment_runtime_metric("normalize_sequence_groups_cache_zero_copy_hit_count")
            return groups
        if bool(self._config.get("normalize_sequence_groups_cache_shallow_copy_enabled", True)):
            copied: list[dict] = []
            for group in groups:
                if not isinstance(group, dict):
                    continue
                row = dict(group)
                row["tokens"] = list(group.get("tokens", []) or [])
                row["units"] = list(group.get("units", []) or [])
                row["unit_signatures"] = list(group.get("unit_signatures", []) or [])
                row["csa_bundles"] = list(group.get("csa_bundles", []) or [])
                row["bundle_signatures"] = list(group.get("bundle_signatures", []) or [])
                copied.append(row)
            return copied
        return self._copy_normalized_groups(groups)

    def _remember_common_group_length(self, key: tuple | None, value: int) -> int:
        if key is None:
            return int(value)
        try:
            limit = int(self._config.get("common_group_length_cache_max_entries", 4096) or 4096)
        except Exception:
            limit = 4096
        if limit <= 0:
            return int(value)
        cache = self._common_group_length_cache
        if key in cache:
            cache.pop(key, None)
        cache[key] = int(value)
        while len(cache) > limit:
            cache.popitem(last=False)
        return int(value)

    @staticmethod
    def _common_group_length_cache_key(existing_group: dict, incoming_group: dict) -> tuple | None:
        existing_signature = str(existing_group.get("group_signature", "") or "")
        incoming_signature = str(incoming_group.get("group_signature", "") or "")
        if not existing_signature or not incoming_signature:
            return None
        return (
            existing_signature,
            incoming_signature,
            int(len(existing_group.get("units", []) or [])),
            int(len(incoming_group.get("units", []) or [])),
            bool(existing_group.get("order_sensitive", False)),
            bool(incoming_group.get("order_sensitive", False)),
        )

    @staticmethod
    def _normalize_sequence_groups_cache_key(groups: list[dict]) -> tuple | None:
        if not isinstance(groups, list):
            return None
        has_stable_signature = False
        for group in groups:
            if not isinstance(group, dict):
                continue
            if str(group.get("group_signature", "") or ""):
                has_stable_signature = True
                break
            unit_signatures = group.get("unit_signatures", [])
            if isinstance(unit_signatures, list) and any(str(sig) for sig in unit_signatures):
                has_stable_signature = True
                break
            for unit in list(group.get("units", []) or [])[:8]:
                if isinstance(unit, dict) and str(unit.get("unit_signature", "") or ""):
                    has_stable_signature = True
                    break
            if has_stable_signature:
                break
        if not has_stable_signature:
            return None
        key_parts: list[tuple] = []
        for order_index, group in enumerate(groups):
            if not isinstance(group, dict):
                key_parts.append(("legacy", order_index, str(group)))
                continue
            units = group.get("units", []) if isinstance(group.get("units", []), list) else []
            unit_parts = []
            for unit in units:
                if not isinstance(unit, dict):
                    continue
                unit_parts.append(
                    (
                        str(unit.get("unit_id", "") or ""),
                        str(unit.get("unit_signature", "") or ""),
                        str(unit.get("token", unit.get("display_text", "")) or ""),
                        str(unit.get("unit_role", unit.get("role", "feature")) or "feature"),
                        str(unit.get("attribute_name", "") or ""),
                        repr(unit.get("attribute_value", None)),
                        str(unit.get("value_type", "") or ""),
                        int(unit.get("sequence_index", order_index) or 0),
                        bool(unit.get("display_visible", False)),
                        bool(unit.get("is_placeholder", False)),
                    )
                )
            bundles = group.get("csa_bundles", []) if isinstance(group.get("csa_bundles", []), list) else []
            bundle_parts = []
            for bundle in bundles:
                if not isinstance(bundle, dict):
                    continue
                bundle_parts.append(
                    (
                        str(bundle.get("bundle_signature", "") or ""),
                        str(bundle.get("anchor_unit_id", "") or ""),
                        tuple(str(x) for x in (bundle.get("member_unit_ids", []) or []) if str(x)),
                    )
                )
            key_parts.append(
                (
                    "group",
                    order_index,
                    int(group.get("group_index", order_index) or order_index),
                    str(group.get("source_type", "") or ""),
                    str(group.get("origin_frame_id", "") or ""),
                    int(group.get("source_group_index", group.get("group_index", order_index)) or order_index),
                    int(group.get("source_sequence_index", 0) or 0),
                    bool(group.get("order_sensitive", False)),
                    str(group.get("string_unit_kind", "") or ""),
                    str(group.get("string_token_text", "") or ""),
                    tuple(str(token) for token in (group.get("tokens", []) or []) if str(token)),
                    str(group.get("group_signature", "") or ""),
                    tuple(unit_parts),
                    tuple(bundle_parts),
                )
            )
        return tuple(key_parts)

    def _remember_normalized_groups(self, key: tuple, groups: list[dict]) -> None:
        try:
            limit = int(self._config.get("normalize_sequence_groups_cache_max_entries", 4096) or 4096)
        except Exception:
            limit = 4096
        if limit <= 0:
            return
        cache = self._normalize_groups_cache
        if key in cache:
            cache.pop(key, None)
        cache[key] = self._copy_normalized_groups(groups)
        while len(cache) > limit:
            cache.popitem(last=False)

    def _normalize_sequence_groups(self, groups: list[dict]) -> list[dict]:
        if groups and isinstance(groups, list):
            reusable_groups: list[dict] = []
            all_reusable = True
            for order_index, group in enumerate(groups):
                if not isinstance(group, dict) or not self._is_reusable_normalized_group(group, order_index=order_index):
                    all_reusable = False
                    break
                reusable_groups.append(
                    self._reuse_normalized_group(group, order_index=order_index)
                )
            if all_reusable:
                self._increment_runtime_metric("normalize_sequence_groups_reusable_hit_count")
                self._increment_runtime_metric("normalize_sequence_groups_reusable_group_count", len(reusable_groups))
                return reusable_groups
        cache_key = self._normalize_sequence_groups_cache_key(groups)
        if cache_key is not None:
            cached = self._normalize_groups_cache.get(cache_key)
            if isinstance(cached, list):
                self._normalize_groups_cache.pop(cache_key, None)
                self._normalize_groups_cache[cache_key] = cached
                self._increment_runtime_metric("normalize_sequence_groups_cache_hit_count")
                return self._copy_cached_normalized_groups(cached)
        normalized = []
        for order_index, group in enumerate(groups):
            if isinstance(group, dict):
                raw_group = group
            else:
                raw_group = {
                    "group_index": order_index,
                    "source_type": "legacy",
                    "origin_frame_id": "",
                    "tokens": [str(group)],
                }
            if isinstance(raw_group, dict) and self._is_reusable_normalized_group(raw_group, order_index=order_index):
                normalized.append(self._reuse_normalized_group(raw_group, order_index=order_index))
                continue
            normalized_group = self._normalize_sequence_group(raw_group, order_index=order_index)
            if normalized_group.get("units"):
                normalized.append(normalized_group)
        if cache_key is not None and normalized:
            self._remember_normalized_groups(cache_key, normalized)
        return normalized

    @staticmethod
    def _signature_from_normalized_groups(groups: list[dict]) -> str:
        return "||".join(str(group.get("group_signature", "")) for group in groups if str(group.get("group_signature", "")))

    @staticmethod
    def _display_from_normalized_groups(groups: list[dict]) -> str:
        parts = []
        for group in groups:
            text = str(group.get("display_text", "") or "")
            if not text:
                return format_sequence_groups(groups)
            parts.append(text)
        return " / ".join(parts)

    @staticmethod
    def _is_reusable_normalized_unit(unit: dict, *, order_index: int, last_sequence_index: int | None) -> tuple[bool, int | None]:
        if not isinstance(unit, dict):
            return False, last_sequence_index
        unit_signature = str(unit.get("unit_signature", "") or "")
        if not unit_signature:
            return False, last_sequence_index
        try:
            group_index = int(unit.get("group_index", order_index))
        except Exception:
            return False, last_sequence_index
        if group_index != order_index:
            return False, last_sequence_index
        try:
            sequence_index = int(unit.get("sequence_index", 0))
        except Exception:
            return False, last_sequence_index
        if last_sequence_index is not None and sequence_index < last_sequence_index:
            return False, last_sequence_index
        token = str(unit.get("token", "") or unit.get("display_text", "") or "")
        if (not token) and not bool(unit.get("is_placeholder", False)):
            return False, last_sequence_index
        return True, sequence_index

    def _is_reusable_normalized_group(self, group: dict, *, order_index: int) -> bool:
        try:
            group_index = int(group.get("group_index", order_index))
        except Exception:
            return False
        if group_index != order_index:
            return False
        units = group.get("units", [])
        if not isinstance(units, list) or not units:
            return False
        if not str(group.get("group_signature", "") or ""):
            return False
        if "display_text" not in group:
            return False
        if not isinstance(group.get("tokens", []), list):
            return False
        if not isinstance(group.get("csa_bundles", []), list):
            return False
        if not isinstance(group.get("unit_signatures", []), list):
            return False
        if bool(group.get("_cut_engine_normalized", False)):
            return True
        last_sequence_index = None
        for unit in units:
            reusable, last_sequence_index = self._is_reusable_normalized_unit(
                unit,
                order_index=order_index,
                last_sequence_index=last_sequence_index,
            )
            if not reusable:
                return False
        return True

    @staticmethod
    def _reuse_normalized_group(group: dict, *, order_index: int) -> dict:
        if (
            bool(group.get("_cut_engine_normalized", False))
            and int(group.get("group_index", order_index) or order_index) == int(order_index)
        ):
            return group
        return {
            **dict(group),
            "group_index": order_index,
            "tokens": list(group.get("tokens", [])),
            "units": list(group.get("units", [])),
            "unit_signatures": list(group.get("unit_signatures", [])),
            "csa_bundles": list(group.get("csa_bundles", [])),
            "bundle_signatures": list(group.get("bundle_signatures", [])),
        }

    def _normalize_sequence_group(self, group: dict, *, order_index: int) -> dict:
        raw_units = group.get("units", [])
        if raw_units:
            units = [
                self._normalize_unit(
                    unit,
                    order_index=order_index,
                    fallback_sequence_index=index,
                    source_type=str(group.get("source_type", "")),
                    origin_frame_id=str(group.get("origin_frame_id", "")),
                    source_group_index=int(group.get("source_group_index", group.get("group_index", order_index))),
                    group_order_sensitive=bool(group.get("order_sensitive", False)),
                    group_string_kind=str(group.get("string_unit_kind", "") or ""),
                    group_string_text=str(group.get("string_token_text", "") or ""),
                )
                for index, unit in enumerate(raw_units)
            ]
        else:
            units = [
                self._normalize_unit(
                    {
                        "unit_id": f"legacy_{order_index}_{index}",
                        "token": str(token),
                        "display_text": str(token),
                        "unit_role": "feature",
                        "display_visible": True,
                    },
                    order_index=order_index,
                    fallback_sequence_index=index,
                    source_type=str(group.get("source_type", "")),
                    origin_frame_id=str(group.get("origin_frame_id", "")),
                    source_group_index=int(group.get("source_group_index", group.get("group_index", order_index))),
                    group_order_sensitive=bool(group.get("order_sensitive", False)),
                    group_string_kind=str(group.get("string_unit_kind", "") or ""),
                    group_string_text=str(group.get("string_token_text", "") or ""),
                )
                for index, token in enumerate(group.get("tokens", []))
                if str(token)
            ]

        units = [unit for unit in units if unit]
        units.sort(key=lambda item: (int(item.get("sequence_index", 0)), str(item.get("unit_id", "")), str(item.get("unit_signature", ""))))

        units_by_id = {str(unit.get("unit_id", "")): dict(unit) for unit in units if str(unit.get("unit_id", ""))}
        raw_bundles = group.get("csa_bundles", []) if isinstance(group.get("csa_bundles", []), list) else []
        if not raw_bundles:
            raw_bundles = self._infer_raw_bundles_from_units(units)
        bundles = self._normalize_csa_bundles(raw_bundles, units_by_id) if raw_bundles else []
        if bundles:
            units = self._apply_bundles_to_units(units, bundles)

        tokens = [
            str(unit.get("token", ""))
            for unit in units
            if str(unit.get("token", "")) and (bool(unit.get("display_visible", False)) or bool(unit.get("is_placeholder", False)))
        ]
        if not tokens:
            tokens = [str(unit.get("token", "")) for unit in units if str(unit.get("token", ""))]

        order_sensitive = bool(group.get("order_sensitive", False))
        string_token_text = str(group.get("string_token_text", "") or "")
        if order_sensitive and not string_token_text:
            string_token_text = "".join(tokens)
        display_text = self._fast_normalized_group_display(
            tokens=tokens,
            units=units,
            bundles=bundles,
            order_sensitive=order_sensitive,
            string_unit_kind=str(group.get("string_unit_kind", "") or ""),
        )
        if not display_text:
            display_text = str(group.get("display_text", "") or group.get("content_display", "") or "").strip()
        if not display_text:
            display_text = format_group_display({**group, "units": units, "csa_bundles": bundles}) or "".join(tokens)

        normalized_group = {
            "group_index": order_index,
            "source_type": str(group.get("source_type", "")),
            "origin_frame_id": str(group.get("origin_frame_id", "")),
            "tokens": tokens,
            "display_text": display_text,
            "group_signature": self._compose_group_signature(units, bundles, order_sensitive=order_sensitive),
            "source_group_index": int(group.get("source_group_index", group.get("group_index", order_index))),
            "source_sequence_index": int(group.get("source_sequence_index", 0)),
            "order_sensitive": order_sensitive,
            "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
            "string_token_text": string_token_text,
            "units": units,
            "unit_signatures": [str(unit.get("unit_signature", "")) for unit in units if str(unit.get("unit_signature", ""))],
            "csa_bundles": bundles,
            "bundle_signatures": [str(bundle.get("bundle_signature", "")) for bundle in bundles if str(bundle.get("bundle_signature", ""))],
            "_cut_engine_normalized": True,
        }
        group_ext = group.get("ext", {}) if isinstance(group.get("ext", {}), dict) else {}
        if group_ext:
            normalized_group["ext"] = dict(group_ext)
        return normalized_group

    @staticmethod
    def _fast_normalized_group_display(
        *,
        tokens: list[str],
        units: list[dict],
        bundles: list[dict],
        order_sensitive: bool,
        string_unit_kind: str,
    ) -> str:
        if not tokens and not units:
            return ""
        if bundles:
            if order_sensitive and str(string_unit_kind or "") == "char_sequence":
                return ""
            units_by_id = {
                str(unit.get("unit_id", "") or ""): unit
                for unit in units
                if isinstance(unit, dict) and str(unit.get("unit_id", "") or "")
            }
            bundle_by_id = {
                str(bundle.get("bundle_id", "") or ""): bundle
                for bundle in bundles
                if isinstance(bundle, dict) and str(bundle.get("bundle_id", "") or "")
            }
            emitted_bundle_ids: set[str] = set()
            covered_unit_ids: set[str] = set()
            seen_segments: set[str] = set()
            segments: list[str] = []
            for unit in units:
                if not isinstance(unit, dict):
                    continue
                unit_id = str(unit.get("unit_id", "") or "")
                if unit_id and unit_id in covered_unit_ids:
                    continue
                bundle_id = str(unit.get("bundle_id", "") or "")
                bundle = bundle_by_id.get(bundle_id) if bundle_id else None
                segment = ""
                if (
                    isinstance(bundle, dict)
                    and bundle_id
                    and bundle_id not in emitted_bundle_ids
                    and unit_id
                    and unit_id == str(bundle.get("anchor_unit_id", "") or "")
                ):
                    member_tokens = [
                        str(units_by_id.get(str(member_id), {}).get("token", "") or units_by_id.get(str(member_id), {}).get("display_text", "") or "").strip()
                        for member_id in (bundle.get("member_unit_ids", []) or [])
                    ]
                    member_tokens = [text for text in member_tokens if text]
                    if member_tokens:
                        segment = "(" + " + ".join(member_tokens) + ")"
                        emitted_bundle_ids.add(bundle_id)
                        covered_unit_ids.update(
                            str(member_id)
                            for member_id in (bundle.get("member_unit_ids", []) or [])
                            if str(member_id)
                        )
                if not segment:
                    segment = str(unit.get("token", "") or unit.get("display_text", "") or "").strip()
                    if unit_id:
                        covered_unit_ids.add(unit_id)
                if segment and segment not in seen_segments:
                    seen_segments.add(segment)
                    segments.append(segment)
            return "{" + " + ".join(segments) + "}" if segments else ""
        if order_sensitive and str(string_unit_kind or "") == "char_sequence":
            string_keys = {
                (
                    str(unit.get("source_type", "") or ""),
                    str(unit.get("origin_frame_id", "") or ""),
                    int(unit.get("source_group_index", unit.get("group_index", 0)) or 0),
                    bool(unit.get("order_sensitive", order_sensitive)),
                    str(unit.get("string_unit_kind", string_unit_kind) or ""),
                    str(unit.get("string_token_text", "") or ""),
                )
                for unit in units
                if isinstance(unit, dict)
            }
            if len(string_keys) > 1:
                return ""
            return "{" + "".join(tokens) + "}"
        seen: set[str] = set()
        segments: list[str] = []
        index = 0
        while index < len(units):
            unit = units[index]
            if not isinstance(unit, dict):
                index += 1
                continue
            text = str(unit.get("token", "") or unit.get("display_text", "") or "").strip()
            if not text:
                index += 1
                continue
            if (
                bool(unit.get("order_sensitive", order_sensitive))
                and str(unit.get("string_unit_kind", string_unit_kind) or "") == "char_sequence"
            ):
                string_key = (
                    str(unit.get("source_type", "") or ""),
                    str(unit.get("origin_frame_id", "") or ""),
                    int(unit.get("source_group_index", unit.get("group_index", 0)) or 0),
                    bool(unit.get("order_sensitive", order_sensitive)),
                    str(unit.get("string_unit_kind", string_unit_kind) or ""),
                    str(unit.get("string_token_text", "") or ""),
                )
                chars = [text]
                index += 1
                while index < len(units):
                    next_unit = units[index]
                    if not isinstance(next_unit, dict):
                        break
                    next_text = str(next_unit.get("token", "") or next_unit.get("display_text", "") or "").strip()
                    next_key = (
                        str(next_unit.get("source_type", "") or ""),
                        str(next_unit.get("origin_frame_id", "") or ""),
                        int(next_unit.get("source_group_index", next_unit.get("group_index", 0)) or 0),
                        bool(next_unit.get("order_sensitive", order_sensitive)),
                        str(next_unit.get("string_unit_kind", string_unit_kind) or ""),
                        str(next_unit.get("string_token_text", "") or ""),
                    )
                    if next_key != string_key:
                        break
                    if next_text:
                        chars.append(next_text)
                    index += 1
                text = "".join(chars)
            else:
                index += 1
            if text in seen:
                continue
            seen.add(text)
            segments.append(text)
        return "{" + " + ".join(segments) + "}" if segments else ""

    def _group_requires_order_sensitive_match(self, group: dict) -> bool:
        return bool(group.get("order_sensitive", False))

    def _ordered_exact_pair_records(self, *, existing_units: list[dict], incoming_units: list[dict]) -> list[dict]:
        """Return exact-signature LCS pairs for groups whose internal SA order is semantic."""
        if bool(self._config.get("maximum_common_group_ordered_subsequence_fast_path_enabled", True)):
            subsequence_records = self._ordered_full_subsequence_pair_records(
                existing_units=existing_units,
                incoming_units=incoming_units,
            )
            if subsequence_records is not None:
                self._increment_runtime_metric("maximum_common_group_ordered_subsequence_fast_path_hit_count")
                return subsequence_records
        rows = len(existing_units) + 1
        cols = len(incoming_units) + 1
        dp = [[0 for _ in range(cols)] for _ in range(rows)]
        for i in range(1, rows):
            existing_signature = str(existing_units[i - 1].get("unit_signature", ""))
            for j in range(1, cols):
                incoming_signature = str(incoming_units[j - 1].get("unit_signature", ""))
                if existing_signature and existing_signature == incoming_signature:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

        pair_records: list[dict] = []
        i = len(existing_units)
        j = len(incoming_units)
        while i > 0 and j > 0:
            existing_unit = existing_units[i - 1]
            incoming_unit = incoming_units[j - 1]
            existing_signature = str(existing_unit.get("unit_signature", ""))
            incoming_signature = str(incoming_unit.get("unit_signature", ""))
            if existing_signature and existing_signature == incoming_signature:
                pair_records.append(
                    {
                        "existing_unit": dict(existing_unit),
                        "incoming_unit": dict(incoming_unit),
                        "common_unit": dict(incoming_unit),
                        "similarity": 1.0,
                    }
                )
                i -= 1
                j -= 1
            elif dp[i - 1][j] >= dp[i][j - 1]:
                i -= 1
            else:
                j -= 1
        pair_records.reverse()
        return pair_records

    @staticmethod
    def _ordered_signature_subsequence_indices(required_units: list[dict], container_units: list[dict]) -> list[int]:
        if not required_units or not container_units or len(required_units) > len(container_units):
            return []
        matched_indices: list[int] = []
        search_start = 0
        for required_unit in required_units:
            required_signature = str(required_unit.get("unit_signature", "") or "")
            if not required_signature:
                return []
            found_index = -1
            for container_index in range(search_start, len(container_units)):
                if required_signature == str(container_units[container_index].get("unit_signature", "") or ""):
                    found_index = container_index
                    break
            if found_index < 0:
                return []
            matched_indices.append(found_index)
            search_start = found_index + 1
        return matched_indices

    @staticmethod
    def _unit_signature_counts(units: list[dict]) -> Counter:
        return Counter(
            str(unit.get("unit_signature", "") or "")
            for unit in units
            if isinstance(unit, dict) and str(unit.get("unit_signature", "") or "")
        )

    def _ordered_subsequence_pair_records_are_safe(
        self,
        *,
        required_units: list[dict],
        container_units: list[dict],
        matched_container_indices: list[int],
    ) -> bool:
        if len(required_units) != len(matched_container_indices):
            return False
        required_counts = self._unit_signature_counts(required_units)
        container_counts = self._unit_signature_counts(container_units)
        for signature, count in required_counts.items():
            if count > 1:
                return False
            if int(container_counts.get(signature, 0) or 0) > 1:
                return False
        return True

    def _ordered_full_subsequence_pair_length(
        self,
        *,
        existing_units: list[dict],
        incoming_units: list[dict],
    ) -> int | None:
        if not bool(self._config.get("maximum_common_group_ordered_subsequence_fast_path_enabled", True)):
            return None
        if not existing_units or not incoming_units:
            return 0
        if len(existing_units) <= len(incoming_units):
            matched_incoming = self._ordered_signature_subsequence_indices(existing_units, incoming_units)
            if matched_incoming:
                return len(existing_units)
        if len(incoming_units) <= len(existing_units):
            matched_existing = self._ordered_signature_subsequence_indices(incoming_units, existing_units)
            if matched_existing:
                return len(incoming_units)
        return None

    def _ordered_full_subsequence_pair_records(
        self,
        *,
        existing_units: list[dict],
        incoming_units: list[dict],
    ) -> list[dict] | None:
        if not existing_units or not incoming_units:
            return []
        if len(existing_units) <= len(incoming_units):
            matched_incoming = self._ordered_signature_subsequence_indices(existing_units, incoming_units)
            if matched_incoming and self._ordered_subsequence_pair_records_are_safe(
                required_units=existing_units,
                container_units=incoming_units,
                matched_container_indices=matched_incoming,
            ):
                return [
                    {
                        "existing_unit": dict(existing_unit),
                        "incoming_unit": dict(incoming_units[incoming_index]),
                        "common_unit": dict(incoming_units[incoming_index]),
                        "similarity": 1.0,
                    }
                    for existing_unit, incoming_index in zip(existing_units, matched_incoming)
                ]
        if len(incoming_units) <= len(existing_units):
            matched_existing = self._ordered_signature_subsequence_indices(incoming_units, existing_units)
            if matched_existing and self._ordered_subsequence_pair_records_are_safe(
                required_units=incoming_units,
                container_units=existing_units,
                matched_container_indices=matched_existing,
            ):
                return [
                    {
                        "existing_unit": dict(existing_units[existing_index]),
                        "incoming_unit": dict(incoming_unit),
                        "common_unit": dict(incoming_unit),
                        "similarity": 1.0,
                    }
                    for incoming_unit, existing_index in zip(incoming_units, matched_existing)
                ]
        return None

    @staticmethod
    def _ordered_exact_pair_length(*, existing_units: list[dict], incoming_units: list[dict]) -> int:
        """Return exact-signature LCS length without allocating full pair records."""
        if not existing_units or not incoming_units:
            return 0
        cols = len(incoming_units) + 1
        previous = [0 for _ in range(cols)]
        for existing_unit in existing_units:
            current = [0 for _ in range(cols)]
            existing_signature = str(existing_unit.get("unit_signature", ""))
            for j, incoming_unit in enumerate(incoming_units, start=1):
                incoming_signature = str(incoming_unit.get("unit_signature", ""))
                if existing_signature and existing_signature == incoming_signature:
                    current[j] = previous[j - 1] + 1
                else:
                    current[j] = max(previous[j], current[j - 1])
            previous = current
        return int(previous[-1])

    def _maximum_common_group(self, *, existing_group: dict, incoming_group: dict) -> dict:
        existing_units = list(existing_group.get("units", []))
        incoming_units = list(incoming_group.get("units", []))
        if not existing_units or not incoming_units:
            return {
                "common_length": 0,
                "common_group": self._build_group_from_units(template_group=incoming_group, units=[], order_index=int(incoming_group.get("group_index", 0))),
                "residual_existing_group": self._build_group_from_units(template_group=existing_group, units=existing_units, order_index=int(existing_group.get("group_index", 0))),
                "residual_incoming_group": self._build_group_from_units(template_group=incoming_group, units=incoming_units, order_index=int(incoming_group.get("group_index", 0))),
                "matched_existing_unit_ids": [],
                "matched_incoming_unit_ids": [],
                "matched_existing_unit_count": 0,
                "matched_incoming_unit_count": 0,
            }
        if self._groups_have_same_stable_signature(existing_group, incoming_group):
            common_group = self._reuse_group_with_order_index(
                incoming_group,
                order_index=int(incoming_group.get("group_index", 0)),
            )
            return {
                "common_length": len(common_group.get("units", [])),
                "common_group": common_group,
                "residual_existing_group": self._build_group_from_units(
                    template_group=existing_group,
                    units=[],
                    order_index=int(existing_group.get("group_index", 0)),
                ),
                "residual_incoming_group": self._build_group_from_units(
                    template_group=incoming_group,
                    units=[],
                    order_index=int(incoming_group.get("group_index", 0)),
                ),
                "matched_existing_unit_ids": [
                    str(unit.get("unit_id", "")) for unit in existing_units if str(unit.get("unit_id", ""))
                ],
                "matched_incoming_unit_ids": [
                    str(unit.get("unit_id", "")) for unit in incoming_units if str(unit.get("unit_id", ""))
                ],
                "matched_existing_unit_count": len(existing_units),
                "matched_incoming_unit_count": len(incoming_units),
                "bundle_constraints_ok_existing_included": True,
                "bundle_constraints_ok_incoming_included": True,
                "bundle_constraints_ok_exact": True,
                "bundle_constraints": {
                    "existing_included_in_incoming": {"ok": True, "missing": []},
                    "incoming_included_in_existing": {"ok": True, "missing": []},
                },
                "matched_existing_unit_similarities": {
                    str(unit.get("unit_id", "")): 1.0 for unit in existing_units if str(unit.get("unit_id", ""))
                },
                "matched_incoming_unit_similarities": {
                    str(unit.get("unit_id", "")): 1.0 for unit in incoming_units if str(unit.get("unit_id", ""))
                },
            }

        order_sensitive_match = bool(
            self._group_requires_order_sensitive_match(existing_group)
            or self._group_requires_order_sensitive_match(incoming_group)
        )

        if order_sensitive_match:
            pair_records = self._ordered_exact_pair_records(existing_units=existing_units, incoming_units=incoming_units)
        else:
            available_existing: dict[str, list[dict]] = {}
            for unit in existing_units:
                available_existing.setdefault(str(unit.get("unit_signature", "")), []).append(dict(unit))

            pair_records = []
            for incoming_unit in incoming_units:
                signature = str(incoming_unit.get("unit_signature", ""))
                bucket = available_existing.get(signature, [])
                if not bucket:
                    continue
                matched_existing = bucket.pop(0)
                pair_records.append(
                    {
                        "existing_unit": matched_existing,
                        "incoming_unit": dict(incoming_unit),
                        "common_unit": dict(incoming_unit),
                        "similarity": 1.0,
                    }
                )

        matched_existing_units = [dict(item.get("existing_unit", {})) for item in pair_records]
        matched_incoming_units = [dict(item.get("incoming_unit", {})) for item in pair_records]
        common_units = [dict(item.get("common_unit", {})) for item in pair_records]

        matched_existing_ids = {str(unit.get("unit_id", "")) for unit in matched_existing_units if str(unit.get("unit_id", ""))}
        matched_incoming_ids = {str(unit.get("unit_id", "")) for unit in matched_incoming_units if str(unit.get("unit_id", ""))}
        residual_existing_units = [dict(unit) for unit in existing_units if str(unit.get("unit_id", "")) not in matched_existing_ids]
        residual_incoming_units = [dict(unit) for unit in incoming_units if str(unit.get("unit_id", "")) not in matched_incoming_ids]

        if not order_sensitive_match:
            still_existing = [dict(unit) for unit in residual_existing_units]
            still_incoming = [dict(unit) for unit in residual_incoming_units]
            residual_existing_units = []
            residual_incoming_units = []
            has_numeric_candidates = any(
                str(unit.get("unit_role", "")) == "attribute" and str(unit.get("attribute_name", "") or "")
                for unit in still_existing
            ) and any(
                str(unit.get("unit_role", "")) == "attribute" and str(unit.get("attribute_name", "") or "")
                for unit in still_incoming
            )
            if has_numeric_candidates:
                for incoming_unit in still_incoming:
                    incoming_family = str(incoming_unit.get("attribute_name", "") or "")
                    if str(incoming_unit.get("unit_role", "")) != "attribute" or not incoming_family:
                        residual_incoming_units.append(dict(incoming_unit))
                        continue
                    best_index = -1
                    best_existing = None
                    best_match = None
                    best_key = None
                    for index, existing_unit in enumerate(still_existing):
                        if (
                            str(existing_unit.get("unit_role", "")) != "attribute"
                            or str(existing_unit.get("attribute_name", "") or "") != incoming_family
                        ):
                            continue
                        numeric_match = self._numeric_unit_match(existing_unit=existing_unit, incoming_unit=incoming_unit)
                        if not numeric_match:
                            continue
                        candidate_key = (
                            float(numeric_match.get("similarity", 0.0)),
                            -float(numeric_match.get("distance", 0.0)),
                            -abs(int(existing_unit.get("sequence_index", 0)) - int(incoming_unit.get("sequence_index", 0))),
                        )
                        if best_key is None or candidate_key > best_key:
                            best_key = candidate_key
                            best_index = index
                            best_existing = dict(existing_unit)
                            best_match = dict(numeric_match)
                    if best_index < 0 or best_existing is None or best_match is None:
                        residual_incoming_units.append(dict(incoming_unit))
                        continue
                    common_unit = self._generalize_numeric_common_unit(
                        existing_unit=best_existing,
                        incoming_unit=incoming_unit,
                        numeric_match=best_match,
                    )
                    matched_existing_units.append(best_existing)
                    matched_incoming_units.append(dict(incoming_unit))
                    common_units.append(common_unit)
                    pair_records.append(
                        {
                            "existing_unit": best_existing,
                            "incoming_unit": dict(incoming_unit),
                            "common_unit": dict(common_unit),
                            "similarity": float(best_match.get("similarity", 1.0)),
                        }
                    )
                    still_existing.pop(best_index)
            else:
                residual_incoming_units = [dict(unit) for unit in still_incoming]

            remaining_existing = [dict(unit) for unit in still_existing]
            still_incoming = [dict(unit) for unit in residual_incoming_units]
            residual_incoming_units = []
            has_structure_candidates = any(
                str(unit.get("object_type", "")) == "st" and str(unit.get("structure_fuzzy_signature", "") or "")
                for unit in remaining_existing
            ) and any(
                str(unit.get("object_type", "")) == "st" and str(unit.get("structure_fuzzy_signature", "") or "")
                for unit in still_incoming
            )
            if has_structure_candidates:
                for incoming_unit in still_incoming:
                    incoming_signature = str(incoming_unit.get("structure_fuzzy_signature", "") or "")
                    if str(incoming_unit.get("object_type", "")) != "st" or not incoming_signature:
                        residual_incoming_units.append(dict(incoming_unit))
                        continue
                    best_index = -1
                    best_existing = None
                    best_match = None
                    best_key = None
                    for index, existing_unit in enumerate(remaining_existing):
                        if (
                            str(existing_unit.get("object_type", "")) != "st"
                            or str(existing_unit.get("structure_fuzzy_signature", "") or "") != incoming_signature
                        ):
                            continue
                        structure_match = self._structure_unit_match(existing_unit=existing_unit, incoming_unit=incoming_unit)
                        if not structure_match:
                            continue
                        candidate_key = (
                            float(structure_match.get("similarity", 0.0)),
                            -abs(int(existing_unit.get("sequence_index", 0)) - int(incoming_unit.get("sequence_index", 0))),
                        )
                        if best_key is None or candidate_key > best_key:
                            best_key = candidate_key
                            best_index = index
                            best_existing = dict(existing_unit)
                            best_match = dict(structure_match)
                    if best_index < 0 or best_existing is None or best_match is None:
                        residual_incoming_units.append(dict(incoming_unit))
                        continue
                    common_unit = self._generalize_structure_common_unit(
                        existing_unit=best_existing,
                        incoming_unit=incoming_unit,
                        structure_match=best_match,
                    )
                    matched_existing_units.append(best_existing)
                    matched_incoming_units.append(dict(incoming_unit))
                    common_units.append(common_unit)
                    pair_records.append(
                        {
                            "existing_unit": best_existing,
                            "incoming_unit": dict(incoming_unit),
                            "common_unit": dict(common_unit),
                            "similarity": float(best_match.get("similarity", 1.0)),
                        }
                    )
                    remaining_existing.pop(best_index)
            else:
                residual_incoming_units = [dict(unit) for unit in still_incoming]
            residual_existing_units.extend(dict(unit) for unit in remaining_existing)

        common_bundles = self._build_common_raw_bundles(
            existing_group=existing_group,
            incoming_group=incoming_group,
            pair_records=pair_records,
        )
        common_group = self._build_group_from_units(
            template_group=incoming_group,
            units=common_units,
            order_index=int(incoming_group.get("group_index", 0)),
            raw_bundles=common_bundles,
        )
        residual_existing_group = self._build_group_from_units(
            template_group=existing_group,
            units=residual_existing_units,
            order_index=int(existing_group.get("group_index", 0)),
        )
        residual_incoming_group = self._build_group_from_units(
            template_group=incoming_group,
            units=residual_incoming_units,
            order_index=int(incoming_group.get("group_index", 0)),
        )

        # ---- CSA/bundle gate check (directional) / CSA 门控检查（有方向） ----
        # existing_incoming_ok: "existing side bundles" must be fully covered by ONE incoming bundle each.
        # incoming_existing_ok: symmetric check, mainly used for exact match.
        existing_to_incoming, incoming_to_existing = self._build_unit_id_mapping(pair_records)
        gate_existing_included = self._bundle_gate_report(
            required_group=existing_group,
            container_group=incoming_group,
            required_to_container_unit_id=existing_to_incoming,
        )
        gate_incoming_included = self._bundle_gate_report(
            required_group=incoming_group,
            container_group=existing_group,
            required_to_container_unit_id=incoming_to_existing,
        )
        gate_ok_existing_included = bool(gate_existing_included.get("ok", True))
        gate_ok_incoming_included = bool(gate_incoming_included.get("ok", True))

        return {
            "common_length": len(common_group.get("units", [])),
            "common_group": common_group,
            "residual_existing_group": residual_existing_group,
            "residual_incoming_group": residual_incoming_group,
            "matched_existing_unit_ids": [str(unit.get("unit_id", "")) for unit in matched_existing_units if str(unit.get("unit_id", ""))],
            "matched_incoming_unit_ids": [str(unit.get("unit_id", "")) for unit in matched_incoming_units if str(unit.get("unit_id", ""))],
            "matched_existing_unit_count": len(matched_existing_units),
            "matched_incoming_unit_count": len(matched_incoming_units),
            "bundle_constraints_ok_existing_included": gate_ok_existing_included,
            "bundle_constraints_ok_incoming_included": gate_ok_incoming_included,
            "bundle_constraints_ok_exact": bool(gate_ok_existing_included and gate_ok_incoming_included),
            "bundle_constraints": {
                "existing_included_in_incoming": gate_existing_included,
                "incoming_included_in_existing": gate_incoming_included,
            },
            "matched_existing_unit_similarities": {
                str(item.get("existing_unit", {}).get("unit_id", "")): round(float(item.get("similarity", 1.0)), 8)
                for item in pair_records
                if str(item.get("existing_unit", {}).get("unit_id", ""))
            },
            "matched_incoming_unit_similarities": {
                str(item.get("incoming_unit", {}).get("unit_id", "")): round(float(item.get("similarity", 1.0)), 8)
                for item in pair_records
                if str(item.get("incoming_unit", {}).get("unit_id", ""))
            },
        }

    def _build_group_from_units(
        self,
        *,
        template_group: dict,
        units: list[dict],
        order_index: int,
        raw_bundles: list[dict] | None = None,
        bundle_signature_whitelist: list[str] | None = None,
    ) -> dict:
        if (
            bundle_signature_whitelist is None
            and not units
            and raw_bundles is None
            and isinstance(template_group, dict)
            and self._is_reusable_normalized_group(
                template_group,
                order_index=int(template_group.get("group_index", order_index) or order_index),
            )
        ):
            self._increment_runtime_metric("empty_group_from_normalized_template_fast_path_hit_count")
            return {
                "group_index": int(order_index),
                "source_type": template_group.get("source_type", ""),
                "origin_frame_id": template_group.get("origin_frame_id", ""),
                "tokens": [],
                "display_text": "",
                "group_signature": "",
                "source_group_index": int(template_group.get("source_group_index", template_group.get("group_index", order_index))),
                "source_sequence_index": int(template_group.get("source_sequence_index", 0)),
                "order_sensitive": bool(template_group.get("order_sensitive", False)),
                "string_unit_kind": str(template_group.get("string_unit_kind", "") or ""),
                "string_token_text": str(template_group.get("string_token_text", "") or ""),
                "units": [],
                "unit_signatures": [],
                "csa_bundles": [],
                "bundle_signatures": [],
                "_cut_engine_normalized": True,
            }
        if (
            bundle_signature_whitelist is None
            and raw_bundles is None
            and isinstance(template_group, dict)
            and self._is_reusable_normalized_group(
                template_group,
                order_index=int(template_group.get("group_index", order_index) or order_index),
            )
        ):
            template_units = [unit for unit in template_group.get("units", []) if isinstance(unit, dict)]
            if units and len(units) == len(template_units):
                expected_ids = [str(unit.get("unit_id", "")) for unit in template_units]
                incoming_ids = [str(unit.get("unit_id", "")) for unit in units if isinstance(unit, dict)]
                if incoming_ids == expected_ids:
                    self._increment_runtime_metric("full_group_from_normalized_template_fast_path_hit_count")
                    return self._reuse_group_with_order_index(template_group, order_index=order_index)
            fast_subset = self._build_group_from_normalized_unit_subset(
                template_group=template_group,
                units=units,
                order_index=order_index,
            )
            if fast_subset is not None:
                self._increment_runtime_metric("normalized_unit_subset_group_fast_path_hit_count")
                return fast_subset
        raw_group = {
            "group_index": order_index,
            "source_type": template_group.get("source_type", ""),
            "origin_frame_id": template_group.get("origin_frame_id", ""),
            "source_group_index": int(template_group.get("source_group_index", template_group.get("group_index", order_index))),
            "source_sequence_index": int(template_group.get("source_sequence_index", 0)),
            "order_sensitive": bool(template_group.get("order_sensitive", False)),
            "string_unit_kind": str(template_group.get("string_unit_kind", "") or ""),
            "string_token_text": str(template_group.get("string_token_text", "") or ""),
            "units": [dict(unit) for unit in units if isinstance(unit, dict)],
        }
        if raw_bundles is not None:
            raw_group["csa_bundles"] = [dict(bundle) for bundle in raw_bundles if isinstance(bundle, dict)]
        normalized = self._normalize_sequence_group(raw_group, order_index=order_index)
        if bundle_signature_whitelist is None:
            return normalized

        allowed = Counter(str(signature) for signature in bundle_signature_whitelist if str(signature))
        selected_bundles = []
        for bundle in normalized.get("csa_bundles", []):
            signature = str(bundle.get("bundle_signature", ""))
            if allowed.get(signature, 0) <= 0:
                continue
            allowed[signature] -= 1
            selected_bundles.append(dict(bundle))

        stripped_units = [self._clear_unit_bundle_fields(unit) for unit in normalized.get("units", [])]
        filtered_group = {
            "group_index": order_index,
            "source_type": normalized.get("source_type", ""),
            "origin_frame_id": normalized.get("origin_frame_id", ""),
            "source_group_index": int(normalized.get("source_group_index", order_index)),
            "source_sequence_index": int(normalized.get("source_sequence_index", 0)),
            "order_sensitive": bool(normalized.get("order_sensitive", False)),
            "string_unit_kind": str(normalized.get("string_unit_kind", "") or ""),
            "string_token_text": str(normalized.get("string_token_text", "") or ""),
            "units": stripped_units,
            "csa_bundles": [
                {
                    "bundle_id": bundle.get("bundle_id", ""),
                    "anchor_unit_id": bundle.get("anchor_unit_id", ""),
                    "member_unit_ids": list(bundle.get("member_unit_ids", [])),
                    "anchor_unit_signature": bundle.get("anchor_unit_signature", ""),
                    "member_unit_signatures": list(bundle.get("member_unit_signatures", [])),
                    "bundle_signature": bundle.get("bundle_signature", ""),
                }
                for bundle in selected_bundles
            ],
        }
        return self._normalize_sequence_group(filtered_group, order_index=order_index)

    def _build_group_from_normalized_unit_subset(
        self,
        *,
        template_group: dict,
        units: list[dict],
        order_index: int,
    ) -> dict | None:
        if not units:
            return None
        source_type = str(template_group.get("source_type", ""))
        origin_frame_id = str(template_group.get("origin_frame_id", ""))
        try:
            source_group_index = int(template_group.get("source_group_index", template_group.get("group_index", order_index)))
        except Exception:
            source_group_index = int(order_index)
        order_sensitive = bool(template_group.get("order_sensitive", False))
        string_unit_kind = str(template_group.get("string_unit_kind", "") or "")
        string_token_text = str(template_group.get("string_token_text", "") or "")

        normalized_units: list[dict] = []
        for fallback_index, unit in enumerate(units):
            if not isinstance(unit, dict):
                return None
            if not (
                bool(unit.get("_cut_engine_unit_normalized", False))
                or (
                    str(unit.get("unit_signature", "") or "")
                    and str(unit.get("unit_id", "") or "")
                    and ("token" in unit or "display_text" in unit)
                    and "unit_role" in unit
                    and "sequence_index" in unit
                )
            ):
                return None
            token = str(unit.get("token", "") or unit.get("display_text", "") or "")
            if not token and not bool(unit.get("is_placeholder", False)):
                return None
            row = dict(unit)
            row["group_index"] = int(order_index)
            try:
                row["sequence_index"] = int(row.get("sequence_index", fallback_index))
            except Exception:
                row["sequence_index"] = int(fallback_index)
            try:
                row["source_group_index"] = int(row.get("source_group_index", source_group_index))
            except Exception:
                row["source_group_index"] = int(source_group_index)
            row["source_type"] = str(row.get("source_type", source_type))
            row["origin_frame_id"] = str(row.get("origin_frame_id", origin_frame_id))
            raw_order_sensitive = row.get("order_sensitive")
            row["order_sensitive"] = bool(order_sensitive if raw_order_sensitive is None else raw_order_sensitive)
            row["string_unit_kind"] = str(row.get("string_unit_kind", string_unit_kind) or "")
            row["string_token_text"] = str(row.get("string_token_text", string_token_text) or "")
            if isinstance(row.get("sensor_fatigue"), dict):
                row["sensor_fatigue"] = dict(row.get("sensor_fatigue") or {})
            if isinstance(row.get("structure_numeric_slots"), list):
                row["structure_numeric_slots"] = [
                    dict(slot) for slot in row.get("structure_numeric_slots", []) if isinstance(slot, dict)
                ]
            if isinstance(row.get("average_numeric_slots"), list):
                row["average_numeric_slots"] = [
                    dict(slot) for slot in row.get("average_numeric_slots", []) if isinstance(slot, dict)
                ]
            for key in ("bundle_member_unit_ids", "bundle_member_signatures"):
                if isinstance(row.get(key), list):
                    row[key] = list(row.get(key) or [])
            row["_cut_engine_unit_normalized"] = True
            normalized_units.append(row)

        normalized_units.sort(
            key=lambda item: (
                int(item.get("sequence_index", 0)),
                str(item.get("unit_id", "")),
                str(item.get("unit_signature", "")),
            )
        )
        units_by_id = {
            str(unit.get("unit_id", "")): unit
            for unit in normalized_units
            if str(unit.get("unit_id", ""))
        }
        raw_bundles = self._infer_raw_bundles_from_units(normalized_units)
        bundles = self._normalize_csa_bundles(raw_bundles, units_by_id) if raw_bundles else []
        if bundles:
            normalized_units = self._apply_bundles_to_units(normalized_units, bundles)

        tokens = [
            str(unit.get("token", ""))
            for unit in normalized_units
            if str(unit.get("token", "")) and (bool(unit.get("display_visible", False)) or bool(unit.get("is_placeholder", False)))
        ]
        if not tokens:
            tokens = [str(unit.get("token", "")) for unit in normalized_units if str(unit.get("token", ""))]
        if order_sensitive and not string_token_text:
            string_token_text = "".join(tokens)
        display_text = self._fast_normalized_group_display(
            tokens=tokens,
            units=normalized_units,
            bundles=bundles,
            order_sensitive=order_sensitive,
            string_unit_kind=string_unit_kind,
        )
        if not display_text:
            display_text = (
                format_group_display({**template_group, "units": normalized_units, "csa_bundles": bundles})
                or "".join(tokens)
            )
        normalized_group = {
            "group_index": int(order_index),
            "source_type": source_type,
            "origin_frame_id": origin_frame_id,
            "tokens": tokens,
            "display_text": display_text,
            "group_signature": self._compose_group_signature(normalized_units, bundles, order_sensitive=order_sensitive),
            "source_group_index": source_group_index,
            "source_sequence_index": int(template_group.get("source_sequence_index", 0)),
            "order_sensitive": order_sensitive,
            "string_unit_kind": string_unit_kind,
            "string_token_text": string_token_text,
            "units": normalized_units,
            "unit_signatures": [
                str(unit.get("unit_signature", "")) for unit in normalized_units if str(unit.get("unit_signature", ""))
            ],
            "csa_bundles": bundles,
            "bundle_signatures": [
                str(bundle.get("bundle_signature", "")) for bundle in bundles if str(bundle.get("bundle_signature", ""))
            ],
            "_cut_engine_normalized": True,
        }
        group_ext = template_group.get("ext", {}) if isinstance(template_group.get("ext", {}), dict) else {}
        if group_ext:
            normalized_group["ext"] = dict(group_ext)
        return normalized_group

    def _normalize_unit(
        self,
        unit: dict,
        *,
        order_index: int,
        fallback_sequence_index: int,
        source_type: str,
        origin_frame_id: str,
        source_group_index: int,
        group_order_sensitive: bool = False,
        group_string_kind: str = "",
        group_string_text: str = "",
    ) -> dict | None:
        if bool(unit.get("_cut_engine_unit_normalized", False)):
            token = str(unit.get("token", "") or unit.get("display_text", ""))
            if (not token) and not bool(unit.get("is_placeholder", False)):
                return None
            try:
                unit_group_index = int(unit.get("group_index", order_index))
                unit_source_group_index = int(unit.get("source_group_index", source_group_index))
            except Exception:
                unit_group_index = -1
                unit_source_group_index = -1
            if (
                unit_group_index == int(order_index)
                and unit_source_group_index == int(source_group_index)
                and str(unit.get("source_type", source_type)) == str(source_type)
                and str(unit.get("origin_frame_id", origin_frame_id)) == str(origin_frame_id)
                and str(unit.get("unit_signature", "") or "")
                and "unit_role" in unit
                and "sequence_index" in unit
            ):
                return dict(unit)

        if (
            bool(unit.get("_cut_engine_unit_normalized", False))
            or (
                str(unit.get("unit_signature", "") or "")
                and str(unit.get("unit_id", "") or "")
                and ("token" in unit or "display_text" in unit)
                and "unit_role" in unit
                and "sequence_index" in unit
            )
        ):
            token = str(unit.get("token", "") or unit.get("display_text", ""))
            if not token:
                return None
            row = dict(unit)
            row["group_index"] = order_index
            try:
                row["sequence_index"] = int(row.get("sequence_index", fallback_sequence_index))
            except Exception:
                row["sequence_index"] = int(fallback_sequence_index)
            try:
                row["source_group_index"] = int(row.get("source_group_index", source_group_index))
            except Exception:
                row["source_group_index"] = int(source_group_index)
            row["source_type"] = str(row.get("source_type", source_type))
            row["origin_frame_id"] = str(row.get("origin_frame_id", origin_frame_id))
            raw_order_sensitive = row.get("order_sensitive")
            row["order_sensitive"] = bool(group_order_sensitive if raw_order_sensitive is None else raw_order_sensitive)
            row["string_unit_kind"] = str(row.get("string_unit_kind", group_string_kind) or "")
            row["string_token_text"] = str(row.get("string_token_text", group_string_text) or "")
            if isinstance(row.get("sensor_fatigue"), dict):
                row["sensor_fatigue"] = dict(row.get("sensor_fatigue") or {})
            if isinstance(row.get("structure_numeric_slots"), list):
                row["structure_numeric_slots"] = [
                    dict(slot) for slot in row.get("structure_numeric_slots", []) if isinstance(slot, dict)
                ]
            if isinstance(row.get("average_numeric_slots"), list):
                row["average_numeric_slots"] = [
                    dict(slot) for slot in row.get("average_numeric_slots", []) if isinstance(slot, dict)
                ]
            for key in ("bundle_member_unit_ids", "bundle_member_signatures"):
                if isinstance(row.get(key), list):
                    row[key] = list(row.get(key) or [])
            row["_cut_engine_unit_normalized"] = True
            return row

        token = str(unit.get("token", unit.get("display_text", unit.get("content", {}).get("display", ""))))
        if not token:
            return None
        unit_role = str(unit.get("unit_role", unit.get("stimulus_role", unit.get("role", "feature")) or "feature"))
        is_placeholder = bool(unit.get("is_placeholder", False) or token.startswith("SELF["))
        if is_placeholder and unit_role == "feature":
            unit_role = "placeholder"
        display_visible = unit.get("display_visible")
        if display_visible is None:
            display_visible = unit_role != "attribute"
        sequence_index = int(unit.get("sequence_index", fallback_sequence_index))
        unit_id = str(unit.get("unit_id", unit.get("id", f"unit_{order_index}_{fallback_sequence_index}")))
        signature = str(unit.get("unit_signature", "")) or self._default_unit_signature(token=token, unit_role=unit_role)
        attribute_name = str(unit.get("attribute_name", unit.get("content", {}).get("attribute_name", "")))
        attribute_value = unit.get("attribute_value", unit.get("content", {}).get("attribute_value"))
        er = round(float(unit.get("er", unit.get("energy", {}).get("er", 0.0))), 8)
        ev = round(float(unit.get("ev", unit.get("energy", {}).get("ev", 0.0))), 8)
        sensor_fatigue = dict(unit.get("sensor_fatigue", {}) or {})
        raw_order_sensitive = unit.get("order_sensitive")
        packet_order_sensitive = bool(group_order_sensitive if raw_order_sensitive is None else raw_order_sensitive)
        packet_string_unit_kind = str(unit.get("string_unit_kind", group_string_kind) or "")
        packet_string_token_text = str(unit.get("string_token_text", group_string_text) or "")
        structure_numeric_slots = [
            dict(slot)
            for slot in unit.get("structure_numeric_slots", [])
            if isinstance(slot, dict)
        ] if isinstance(unit.get("structure_numeric_slots", []), list) else []
        average_numeric_slots = [
            dict(slot)
            for slot in unit.get("average_numeric_slots", [])
            if isinstance(slot, dict)
        ] if isinstance(unit.get("average_numeric_slots", []), list) else []
        return {
            "unit_id": unit_id,
            "object_type": str(unit.get("object_type", "sa")),
            "token": token,
            "display_text": str(unit.get("display_text", token)),
            "unit_role": unit_role,
            "unit_signature": signature,
            "sequence_index": sequence_index,
            "group_index": order_index,
            "source_group_index": int(unit.get("source_group_index", source_group_index)),
            "source_type": str(unit.get("source_type", source_type)),
            "origin_frame_id": str(unit.get("origin_frame_id", origin_frame_id)),
            "order_sensitive": packet_order_sensitive,
            "string_unit_kind": packet_string_unit_kind,
            "string_token_text": packet_string_token_text,
            "er": er,
            "ev": ev,
            "total_energy": round(er + ev, 8),
            "is_punctuation": bool(unit.get("is_punctuation", self._is_punctuation_token(token))),
            "display_visible": bool(display_visible),
            "is_placeholder": is_placeholder,
            "attribute_name": attribute_name,
            "attribute_value": attribute_value,
            "fatigue": round(float(unit.get("fatigue", 0.0)), 8),
            "sensor_fatigue": sensor_fatigue,
            "suppression_ratio": round(float(unit.get("suppression_ratio", sensor_fatigue.get("suppression_ratio", 0.0))), 6),
            "er_before_fatigue": round(float(unit.get("er_before_fatigue", sensor_fatigue.get("er_before_fatigue", er))), 8),
            "er_after_fatigue": round(float(unit.get("er_after_fatigue", sensor_fatigue.get("er_after_fatigue", er))), 8),
            "window_count": int(unit.get("window_count", sensor_fatigue.get("window_count", 0)) or 0),
            "threshold_count": int(unit.get("threshold_count", sensor_fatigue.get("threshold_count", 0)) or 0),
            "window_rounds": int(unit.get("window_rounds", sensor_fatigue.get("window_rounds", 0)) or 0),
            "sensor_round": int(unit.get("sensor_round", sensor_fatigue.get("sensor_round", 0)) or 0),
            "bundle_id": str(unit.get("bundle_id", "")),
            "bundle_anchor_unit_id": str(unit.get("bundle_anchor_unit_id", "")),
            "bundle_anchor_signature": str(unit.get("bundle_anchor_signature", "")),
            "bundle_signature": str(unit.get("bundle_signature", "")),
            "bundle_member_unit_ids": list(unit.get("bundle_member_unit_ids", [])),
            "bundle_member_signatures": list(unit.get("bundle_member_signatures", [])),
            "structure_display_text": str(unit.get("structure_display_text", "")),
            "structure_grouped_display_text": str(unit.get("structure_grouped_display_text", "")),
            "structure_display_template": str(unit.get("structure_display_template", "")),
            "structure_fuzzy_signature": str(unit.get("structure_fuzzy_signature", "")),
            "structure_numeric_slots": structure_numeric_slots,
            "average_numeric_slots": average_numeric_slots,
            "_cut_engine_unit_normalized": True,
        }

    @staticmethod
    def _groups_have_same_stable_signature(existing_group: dict, incoming_group: dict) -> bool:
        existing_signature = str(existing_group.get("group_signature", "") or "")
        incoming_signature = str(incoming_group.get("group_signature", "") or "")
        if not existing_signature or existing_signature != incoming_signature:
            return False
        existing_units = existing_group.get("units", []) if isinstance(existing_group.get("units", []), list) else []
        incoming_units = incoming_group.get("units", []) if isinstance(incoming_group.get("units", []), list) else []
        if len(existing_units) != len(incoming_units):
            return False
        existing_bundles = existing_group.get("bundle_signatures", [])
        incoming_bundles = incoming_group.get("bundle_signatures", [])
        if isinstance(existing_bundles, list) or isinstance(incoming_bundles, list):
            if sorted(str(value) for value in (existing_bundles or []) if str(value)) != sorted(
                str(value) for value in (incoming_bundles or []) if str(value)
            ):
                return False
        return True

    def _reuse_group_with_order_index(self, group: dict, *, order_index: int) -> dict:
        if self._is_reusable_normalized_group(group, order_index=order_index):
            self._increment_runtime_metric("reindex_reusable_group_fast_path_hit_count")
            return self._reuse_normalized_group(group, order_index=order_index)
        return {
            **dict(group),
            "group_index": order_index,
            "tokens": list(group.get("tokens", []) or []),
            "units": [dict(unit) for unit in (group.get("units", []) or []) if isinstance(unit, dict)],
            "unit_signatures": list(group.get("unit_signatures", []) or []),
            "csa_bundles": [dict(bundle) for bundle in (group.get("csa_bundles", []) or []) if isinstance(bundle, dict)],
            "bundle_signatures": list(group.get("bundle_signatures", []) or []),
        }

    def _compose_group_signature(self, units: list[dict], bundles: list[dict], *, order_sensitive: bool = False) -> str:
        unit_signatures = [str(unit.get("unit_signature", "")) for unit in units if str(unit.get("unit_signature", ""))]
        if order_sensitive:
            unit_part = self.tokens_to_signature(unit_signatures)
        else:
            unit_part = self.tokens_to_signature(sorted(unit_signatures))
        bundle_part = self.tokens_to_signature(sorted(str(bundle.get("bundle_signature", "")) for bundle in bundles if str(bundle.get("bundle_signature", ""))))
        prefix = "OS" if order_sensitive else "U"
        if unit_part and bundle_part:
            return f"{prefix}[{unit_part}]#B[{bundle_part}]"
        if bundle_part:
            return f"B[{bundle_part}]"
        if unit_part:
            return f"{prefix}[{unit_part}]"
        return ""

    def _infer_raw_bundles_from_units(self, units: list[dict]) -> list[dict]:
        bundles = {}
        for unit in units:
            bundle_id = str(unit.get("bundle_id", ""))
            anchor_unit_id = str(unit.get("bundle_anchor_unit_id", ""))
            anchor_signature = str(unit.get("bundle_anchor_signature", ""))
            if not bundle_id and not anchor_unit_id and not anchor_signature:
                continue
            key = bundle_id or anchor_unit_id or anchor_signature
            current = bundles.setdefault(
                key,
                {
                    "bundle_id": bundle_id or key,
                    "anchor_unit_id": anchor_unit_id,
                    "anchor_unit_signature": anchor_signature,
                    "member_unit_ids": [],
                },
            )
            current["member_unit_ids"].append(str(unit.get("unit_id", "")))
            if not current.get("anchor_unit_id") and anchor_unit_id:
                current["anchor_unit_id"] = anchor_unit_id
            if not current.get("anchor_unit_signature") and anchor_signature:
                current["anchor_unit_signature"] = anchor_signature
        return list(bundles.values())

    def _normalize_csa_bundles(self, raw_bundles: list[dict], units_by_id: dict[str, dict]) -> list[dict]:
        normalized = []
        for index, raw_bundle in enumerate(raw_bundles):
            member_unit_ids = [
                str(member_id)
                for member_id in raw_bundle.get("member_unit_ids", [])
                if str(member_id) in units_by_id
            ]
            member_unit_ids = self._dedupe_preserve_order(member_unit_ids)
            if not member_unit_ids:
                continue
            anchor_unit_id = str(raw_bundle.get("anchor_unit_id", ""))
            if anchor_unit_id not in units_by_id:
                anchor_unit_id = ""
            if not anchor_unit_id:
                anchor_signature = str(raw_bundle.get("anchor_unit_signature", ""))
                for member_id in member_unit_ids:
                    member = units_by_id.get(member_id, {})
                    if anchor_signature and str(member.get("unit_signature", "")) == anchor_signature:
                        anchor_unit_id = member_id
                        break
                if not anchor_unit_id:
                    for member_id in member_unit_ids:
                        member = units_by_id.get(member_id, {})
                        if str(member.get("unit_role", "")) != "attribute":
                            anchor_unit_id = member_id
                            break
            if not anchor_unit_id:
                continue
            ordered_member_ids = sorted(
                member_unit_ids,
                key=lambda member_id: (
                    int(units_by_id.get(member_id, {}).get("sequence_index", 0)),
                    str(member_id),
                ),
            )
            if anchor_unit_id not in ordered_member_ids:
                ordered_member_ids.insert(0, anchor_unit_id)
            attribute_member_ids = [member_id for member_id in ordered_member_ids if member_id != anchor_unit_id]
            if not attribute_member_ids:
                continue
            anchor_signature = str(units_by_id.get(anchor_unit_id, {}).get("unit_signature", ""))
            member_signatures = [str(units_by_id.get(member_id, {}).get("unit_signature", "")) for member_id in ordered_member_ids if str(units_by_id.get(member_id, {}).get("unit_signature", ""))]
            bundle_signature = str(raw_bundle.get("bundle_signature", "")) or self._bundle_signature(anchor_signature, member_signatures[1:])
            normalized.append(
                {
                    "bundle_id": str(raw_bundle.get("bundle_id", "")) or f"bundle_{index}",
                    "anchor_unit_id": anchor_unit_id,
                    "member_unit_ids": ordered_member_ids,
                    "anchor_unit_signature": anchor_signature,
                    "member_unit_signatures": member_signatures,
                    "bundle_signature": bundle_signature,
                }
            )
        normalized.sort(
            key=lambda bundle: (
                int(units_by_id.get(str(bundle.get("anchor_unit_id", "")), {}).get("sequence_index", 0)),
                str(bundle.get("bundle_id", "")),
            )
        )
        return normalized

    def _apply_bundles_to_units(self, units: list[dict], bundles: list[dict]) -> list[dict]:
        cloned_units = [self._clear_unit_bundle_fields(unit) for unit in units]
        units_by_id = {str(unit.get("unit_id", "")): unit for unit in cloned_units if str(unit.get("unit_id", ""))}
        for bundle in bundles:
            anchor_unit_id = str(bundle.get("anchor_unit_id", ""))
            member_unit_ids = [str(member_id) for member_id in bundle.get("member_unit_ids", []) if str(member_id) in units_by_id]
            member_signatures = [
                str(units_by_id.get(member_id, {}).get("unit_signature", ""))
                for member_id in member_unit_ids
                if str(units_by_id.get(member_id, {}).get("unit_signature", ""))
            ]
            for member_id in member_unit_ids:
                member = units_by_id.get(member_id)
                if not member:
                    continue
                member["bundle_id"] = str(bundle.get("bundle_id", ""))
                member["bundle_anchor_unit_id"] = anchor_unit_id
                member["bundle_anchor_signature"] = str(bundle.get("anchor_unit_signature", ""))
                member["bundle_signature"] = str(bundle.get("bundle_signature", ""))
                member["bundle_member_unit_ids"] = list(member_unit_ids)
                member["bundle_member_signatures"] = list(member_signatures)
        cloned_units.sort(key=lambda item: (int(item.get("sequence_index", 0)), str(item.get("unit_id", "")), str(item.get("unit_signature", ""))))
        return cloned_units

    def _clear_unit_bundle_fields(self, unit: dict) -> dict:
        cloned = dict(unit)
        cloned["bundle_id"] = ""
        cloned["bundle_anchor_unit_id"] = ""
        cloned["bundle_anchor_signature"] = ""
        cloned["bundle_signature"] = ""
        cloned["bundle_member_unit_ids"] = []
        cloned["bundle_member_signatures"] = []
        return cloned

    def _default_unit_signature(self, *, token: str, unit_role: str) -> str:
        role = str(unit_role or "feature")
        if role == "attribute":
            prefix = "A"
        elif role == "placeholder":
            prefix = "P"
        else:
            prefix = "F"
        return f"{prefix}:{token}"

    def _bundle_signature(self, anchor_signature: str, attribute_signatures: list[str]) -> str:
        normalized_attrs = sorted(str(item) for item in attribute_signatures if str(item))
        return f"CSA[{anchor_signature}=>{'|'.join(normalized_attrs)}]"

    def _intersect_multiset(self, left_items: list[str], right_items: list[str]) -> list[str]:
        right_counter = Counter(str(item) for item in right_items if str(item))
        common = []
        for item in left_items:
            text = str(item)
            if not text:
                continue
            if right_counter.get(text, 0) <= 0:
                continue
            right_counter[text] -= 1
            common.append(text)
        return common

    @staticmethod
    def _coerce_numeric_value(value) -> float | None:
        return coerce_numeric_value(value)

    def _describe_numeric_match(self, *, family: str, left_value, right_value) -> dict | None:
        return build_numeric_match(
            family=family,
            left_value=left_value,
            right_value=right_value,
            abs_tolerance=float(self._config.get("numeric_match_abs_tolerance", 0.2)),
            rel_tolerance=float(self._config.get("numeric_match_rel_tolerance", 0.35)),
            min_similarity=float(self._config.get("numeric_match_min_similarity", 0.4)),
        )

    def _numeric_unit_match(self, *, existing_unit: dict, incoming_unit: dict) -> dict | None:
        if str(existing_unit.get("unit_role", "")) != "attribute":
            return None
        if str(incoming_unit.get("unit_role", "")) != "attribute":
            return None
        family = str(existing_unit.get("attribute_name", "") or incoming_unit.get("attribute_name", ""))
        if not family or family != str(incoming_unit.get("attribute_name", "") or family):
            return None
        return self._describe_numeric_match(
            family=family,
            left_value=existing_unit.get("attribute_value"),
            right_value=incoming_unit.get("attribute_value"),
        )

    @staticmethod
    def _format_generalized_numeric_token(attribute_name: str, numeric_match: dict) -> str:
        text = CutEngine._format_numeric_value_text(numeric_match.get("average_value", 0.0))
        return f"{attribute_name}:~{text}"

    def _generalize_numeric_common_unit(self, *, existing_unit: dict, incoming_unit: dict, numeric_match: dict) -> dict:
        family = str(incoming_unit.get("attribute_name", "") or existing_unit.get("attribute_name", ""))
        average_value = float(numeric_match.get("average_value", 0.0))
        token = f"{family}:{self._format_numeric_value_text(average_value)}"
        sequence_index = min(
            int(existing_unit.get("sequence_index", 0)),
            int(incoming_unit.get("sequence_index", 0)),
        )
        return {
            **dict(incoming_unit),
            "unit_id": "numeric_common::"
            + family
            + "::"
            + str(existing_unit.get("unit_id", ""))
            + "::"
            + str(incoming_unit.get("unit_id", "")),
            "token": token,
            "display_text": token,
            "unit_signature": f"AN:{family}:{self._format_numeric_value_text(average_value)}",
            "sequence_index": sequence_index,
            "attribute_name": family,
            "attribute_value": average_value,
            "display_visible": False,
            "numeric_match_similarity": float(numeric_match.get("similarity", 0.0)),
            "match_similarity": float(numeric_match.get("similarity", 0.0)),
        }

    def _structure_unit_match(self, *, existing_unit: dict, incoming_unit: dict) -> dict | None:
        if str(existing_unit.get("object_type", "")) != "st":
            return None
        if str(incoming_unit.get("object_type", "")) != "st":
            return None
        existing_signature = str(existing_unit.get("structure_fuzzy_signature", ""))
        incoming_signature = str(incoming_unit.get("structure_fuzzy_signature", ""))
        if not existing_signature or existing_signature != incoming_signature:
            return None
        existing_slots = list(existing_unit.get("structure_numeric_slots", []))
        incoming_slots = list(incoming_unit.get("structure_numeric_slots", []))
        if len(existing_slots) != len(incoming_slots):
            return None
        averaged_slots = []
        similarities = []
        for existing_slot, incoming_slot in zip(existing_slots, incoming_slots):
            existing_family = str(existing_slot.get("family", ""))
            incoming_family = str(incoming_slot.get("family", ""))
            if not existing_family or existing_family != incoming_family:
                return None
            numeric_match = self._describe_numeric_match(
                family=existing_family,
                left_value=existing_slot.get("value"),
                right_value=incoming_slot.get("value"),
            )
            if not numeric_match:
                return None
            similarities.append(float(numeric_match.get("similarity", 0.0)))
            semantic_kind = str(existing_slot.get("semantic_kind", "") or incoming_slot.get("semantic_kind", "")).strip()
            averaged_slots.append(
                {
                    "family": existing_family,
                    "value": round(float(numeric_match.get("average_value", 0.0)), 8),
                    **({"semantic_kind": semantic_kind} if semantic_kind else {}),
                }
            )
        similarity = round(sum(similarities) / len(similarities), 8) if similarities else 1.0
        template = str(incoming_unit.get("structure_display_template", "") or existing_unit.get("structure_display_template", ""))
        common_display = self._format_structure_common_display(
            template=template,
            averaged_slots=averaged_slots,
            fallback_display=str(incoming_unit.get("display_text", "") or existing_unit.get("display_text", "")),
        )
        return {
            "similarity": similarity,
            "average_numeric_slots": averaged_slots,
            "common_display_text": common_display,
            "common_unit_signature": existing_signature,
        }

    def _generalize_structure_common_unit(self, *, existing_unit: dict, incoming_unit: dict, structure_match: dict) -> dict:
        return {
            **dict(incoming_unit),
            "token": str(structure_match.get("common_display_text", "")) or str(incoming_unit.get("token", "")),
            "display_text": str(structure_match.get("common_display_text", "")) or str(incoming_unit.get("display_text", "")),
            "unit_signature": str(structure_match.get("common_unit_signature", "")) or str(incoming_unit.get("unit_signature", "")),
            "structure_fuzzy_signature": str(structure_match.get("common_unit_signature", "")) or str(incoming_unit.get("structure_fuzzy_signature", "")),
            "structure_numeric_slots": list(structure_match.get("average_numeric_slots", [])),
            "average_numeric_slots": list(structure_match.get("average_numeric_slots", [])),
            "structure_display_text": str(structure_match.get("common_display_text", "")) or str(incoming_unit.get("structure_display_text", "")),
            "structure_display_template": str(incoming_unit.get("structure_display_template", "") or existing_unit.get("structure_display_template", "")),
            "match_similarity": float(structure_match.get("similarity", 1.0)),
        }

    @staticmethod
    def _format_numeric_value_text(value: float | int | str) -> str:
        try:
            text = f"{float(value):.4f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            text = str(value)
        return text or "0"

    @classmethod
    def _format_structure_common_display(cls, *, template: str, averaged_slots: list[dict], fallback_display: str) -> str:
        text = str(template or "")
        if not text:
            return fallback_display
        for index, slot in enumerate(averaged_slots):
            token = cls._format_numeric_value_text(slot.get("value", 0.0))
            text = text.replace(f"{{{{NUM{index}}}}}", token)
        return text or fallback_display

    def _build_common_raw_bundles(self, *, existing_group: dict, incoming_group: dict, pair_records: list[dict]) -> list[dict]:
        incoming_to_common = {
            str(item.get("incoming_unit", {}).get("unit_id", "")): str(item.get("common_unit", {}).get("unit_id", ""))
            for item in pair_records
            if str(item.get("incoming_unit", {}).get("unit_id", "")) and str(item.get("common_unit", {}).get("unit_id", ""))
        }
        existing_to_common = {
            str(item.get("existing_unit", {}).get("unit_id", "")): str(item.get("common_unit", {}).get("unit_id", ""))
            for item in pair_records
            if str(item.get("existing_unit", {}).get("unit_id", "")) and str(item.get("common_unit", {}).get("unit_id", ""))
        }
        existing_bundle_keys = set()
        for bundle in existing_group.get("csa_bundles", []):
            existing_attr_ids = [
                str(member_id)
                for member_id in bundle.get("member_unit_ids", [])
                if str(member_id) and str(member_id) != str(bundle.get("anchor_unit_id", ""))
            ]
            mapped_anchor = existing_to_common.get(str(bundle.get("anchor_unit_id", "")), "")
            mapped_attrs = [
                existing_to_common.get(str(member_id), "")
                for member_id in bundle.get("member_unit_ids", [])
                if str(member_id) != str(bundle.get("anchor_unit_id", ""))
            ]
            mapped_attrs = [member_id for member_id in mapped_attrs if member_id]
            # Only treat a bundle as "common candidate" when ALL required attribute members are mapped.
            # 仅当该 bundle 的全部属性成员都被映射（匹配）到 common 单位时，才认为它可能进入“共同部分”。
            if not mapped_anchor or not mapped_attrs or len(mapped_attrs) < len(existing_attr_ids):
                continue
            existing_bundle_keys.add((mapped_anchor, tuple(sorted(mapped_attrs))))

        common_bundles = []
        for index, bundle in enumerate(incoming_group.get("csa_bundles", [])):
            mapped_anchor = incoming_to_common.get(str(bundle.get("anchor_unit_id", "")), "")
            mapped_attrs = [
                incoming_to_common.get(str(member_id), "")
                for member_id in bundle.get("member_unit_ids", [])
                if str(member_id) != str(bundle.get("anchor_unit_id", ""))
            ]
            mapped_attrs = [member_id for member_id in mapped_attrs if member_id]
            if not mapped_anchor or not mapped_attrs:
                continue
            bundle_key = (mapped_anchor, tuple(sorted(mapped_attrs)))
            if bundle_key not in existing_bundle_keys:
                continue
            common_bundles.append(
                {
                    "bundle_id": f"common_bundle_{index}",
                    "anchor_unit_id": mapped_anchor,
                    "member_unit_ids": [mapped_anchor, *mapped_attrs],
                }
            )
        return common_bundles

    # ================================================================== #
    # CSA/Bundle Gate (核心门控语义)                                       #
    # ================================================================== #
    #
    # Theory alignment / 理论对齐（见《理论核心》3.3.3）:
    # - If the "structure side" contains a CSA bundle (anchor + attributes),
    #   the "matching side" must provide ONE bundle that fully contains it.
    #   若结构侧包含某个 CSA（锚点 + 属性集合），匹配侧必须提供一个能够完全包含它的 CSA；
    #   不能用两个 CSA 分别拼接来匹配一个结构 CSA。
    #
    # Why this is needed / 为什么需要这一步：
    # - Unit matching alone ("A:属性token") may accidentally cross-bind attributes
    #   across different anchors (objects).
    #   仅靠属性 unit 的 token 匹配容易发生“跨对象拼接”，导致误匹配与错误触发。
    #
    # Engineering choice / 工程取舍：
    # - Keep the DP token matching logic stable (MVP friendly), and add an
    #   explicit CSA/bundle gate check here. Downstream "full included" checks
    #   must additionally require this gate to pass.
    #   维持现有 DP/单位匹配逻辑稳定，在这里增加显式门控检查；下游判断“完全包含”时必须同时满足门控。

    @staticmethod
    def _build_unit_id_mapping(pair_records: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
        """Build matched unit_id mapping between existing <-> incoming.

        构造单位 id 的匹配映射：existing_unit_id -> incoming_unit_id 以及反向映射。
        """
        existing_to_incoming: dict[str, str] = {}
        incoming_to_existing: dict[str, str] = {}
        for rec in pair_records:
            eu = rec.get("existing_unit", {}) or {}
            iu = rec.get("incoming_unit", {}) or {}
            e_id = str(eu.get("unit_id", "") or "")
            i_id = str(iu.get("unit_id", "") or "")
            if not e_id or not i_id:
                continue
            existing_to_incoming[e_id] = i_id
            incoming_to_existing[i_id] = e_id
        return existing_to_incoming, incoming_to_existing

    def _bundle_gate_report(
        self,
        *,
        required_group: dict,
        container_group: dict,
        required_to_container_unit_id: dict[str, str],
    ) -> dict:
        """Check: each required CSA bundle is covered by ONE container bundle.

        检查：required_group 的每个 CSA bundle 是否都能被 container_group 中“某一个”bundle 完全包含。
        """
        required_bundles = [b for b in (required_group.get("csa_bundles", []) or []) if isinstance(b, dict)]
        container_bundles = [b for b in (container_group.get("csa_bundles", []) or []) if isinstance(b, dict)]

        bundles_by_anchor: dict[str, list[dict]] = {}
        for bundle in container_bundles:
            anchor_id = str(bundle.get("anchor_unit_id", "") or "")
            if not anchor_id:
                continue
            bundles_by_anchor.setdefault(anchor_id, []).append(bundle)

        required_count = 0
        matched_count = 0
        unmatched: list[dict] = []
        matched: list[dict] = []

        for rb in required_bundles:
            anchor_id = str(rb.get("anchor_unit_id", "") or "")
            member_ids = [str(mid) for mid in rb.get("member_unit_ids", []) if str(mid)]
            attr_ids = [mid for mid in member_ids if mid and mid != anchor_id]
            if not anchor_id or not attr_ids:
                # Not a valid gate bundle (no anchor or no attrs) -> ignore in the gate.
                # 非有效门控 bundle（无锚点或无属性）-> 原型阶段先不纳入门控统计。
                continue

            required_count += 1
            mapped_anchor = str(required_to_container_unit_id.get(anchor_id, "") or "")
            if not mapped_anchor:
                unmatched.append(
                    {
                        "bundle_signature": str(rb.get("bundle_signature", "")),
                        "reason": "anchor_not_matched",
                        "anchor_unit_id": anchor_id,
                        "anchor_unit_signature": str(rb.get("anchor_unit_signature", "")),
                    }
                )
                continue

            mapped_attrs: list[str] = []
            missing_attr_ids: list[str] = []
            for attr_id in attr_ids:
                mapped = str(required_to_container_unit_id.get(attr_id, "") or "")
                if not mapped:
                    missing_attr_ids.append(attr_id)
                else:
                    mapped_attrs.append(mapped)

            if missing_attr_ids:
                unmatched.append(
                    {
                        "bundle_signature": str(rb.get("bundle_signature", "")),
                        "reason": "attribute_not_matched",
                        "anchor_unit_id": anchor_id,
                        "anchor_unit_signature": str(rb.get("anchor_unit_signature", "")),
                        "missing_attribute_unit_ids": missing_attr_ids[:12],
                        "missing_attribute_count": len(missing_attr_ids),
                    }
                )
                continue

            required_attr_set = set(mapped_attrs)
            candidates = bundles_by_anchor.get(mapped_anchor, [])
            found = None
            for cb in candidates:
                container_member_ids = {str(mid) for mid in (cb.get("member_unit_ids", []) or []) if str(mid)}
                if required_attr_set.issubset(container_member_ids):
                    found = cb
                    break

            if not found:
                unmatched.append(
                    {
                        "bundle_signature": str(rb.get("bundle_signature", "")),
                        "reason": "no_single_container_bundle_covers_all_attributes",
                        "anchor_unit_id": anchor_id,
                        "anchor_unit_signature": str(rb.get("anchor_unit_signature", "")),
                        "mapped_anchor_unit_id": mapped_anchor,
                        "required_attribute_count": len(mapped_attrs),
                    }
                )
                continue

            matched_count += 1
            matched.append(
                {
                    "required_bundle_signature": str(rb.get("bundle_signature", "")),
                    "container_bundle_signature": str(found.get("bundle_signature", "")),
                    "mapped_anchor_unit_id": mapped_anchor,
                    "required_attribute_count": len(mapped_attrs),
                    "container_attribute_count": max(0, len(list(found.get("member_unit_ids", []) or [])) - 1),
                }
            )

        ok = bool(required_count == matched_count)
        return {
            "required_count": int(required_count),
            "matched_count": int(matched_count),
            "ok": ok,
            "unmatched": unmatched,
            "matched": matched,
        }

    def _reindex_group(self, group: dict, *, order_index: int) -> dict:
        if not isinstance(group, dict):
            return self._normalize_sequence_group({"group_index": order_index, "tokens": []}, order_index=order_index)
        if self._is_reusable_normalized_group(group, order_index=order_index):
            self._increment_runtime_metric("reindex_reusable_group_fast_path_hit_count")
            return self._reuse_normalized_group(group, order_index=order_index)
        raw = {
            "group_index": order_index,
            "source_type": group.get("source_type", ""),
            "origin_frame_id": group.get("origin_frame_id", ""),
            "source_group_index": int(group.get("source_group_index", group.get("group_index", order_index))),
            "source_sequence_index": int(group.get("source_sequence_index", 0)),
            "order_sensitive": bool(group.get("order_sensitive", False)),
            "string_unit_kind": str(group.get("string_unit_kind", "") or ""),
            "string_token_text": str(group.get("string_token_text", "") or ""),
            "units": [dict(unit) for unit in group.get("units", [])],
            "csa_bundles": [dict(bundle) for bundle in group.get("csa_bundles", [])],
        }
        return self._normalize_sequence_group(raw, order_index=order_index)

    def _build_unit_from_packet_object(
        self,
        *,
        obj: dict,
        group_index: int,
        source_group_index: int,
        source_type: str,
        origin_frame_id: str,
    ) -> dict | None:
        token = self._display_text(obj)
        if not token:
            return None
        packet_context = obj.get("ext", {}).get("packet_context", {})
        sequence_index = int(packet_context.get("sequence_index", obj.get("stimulus", {}).get("global_sequence_index", 0)))
        effective_source_type = str(packet_context.get("source_type", source_type))
        effective_source_group_index = int(packet_context.get("source_group_index", source_group_index))
        packet_order_sensitive = bool(packet_context.get("order_sensitive", False))
        packet_string_unit_kind = str(packet_context.get("string_unit_kind", "") or "")
        packet_string_token_text = str(packet_context.get("string_token_text", "") or "")
        effective_origin_frame_id = str(packet_context.get("origin_frame_id", origin_frame_id))
        role = str(obj.get("stimulus", {}).get("role", "feature") or "feature")
        unit_signature = self._default_unit_signature(token=token, unit_role=role)
        parent_ids = list((obj.get("source", {}) or {}).get("parent_ids", []))
        attribute_name = str(obj.get("content", {}).get("attribute_name", ""))
        attribute_value = obj.get("content", {}).get("attribute_value")
        er = round(float(obj.get("energy", {}).get("er", 0.0)), 8)
        ev = round(float(obj.get("energy", {}).get("ev", 0.0)), 8)
        sensor_fatigue = dict(obj.get("ext", {}).get("sensor_fatigue", {}) or {})
        return {
            "unit_id": obj.get("id", ""),
            "object_type": str(obj.get("object_type", "sa")),
            "token": token,
            "display_text": token,
            "unit_role": role,
            "unit_signature": unit_signature,
            "sequence_index": sequence_index,
            "group_index": group_index,
            "source_group_index": effective_source_group_index,
            "source_type": effective_source_type,
            "origin_frame_id": effective_origin_frame_id,
            "order_sensitive": packet_order_sensitive,
            "string_unit_kind": packet_string_unit_kind,
            "string_token_text": packet_string_token_text,
            "er": er,
            "ev": ev,
            "total_energy": round(er + ev, 8),
            "display_visible": role != "attribute",
            "is_placeholder": False,
            "is_punctuation": bool(obj.get("linguistic", {}).get("is_punctuation", self._is_punctuation_token(token))),
            "attribute_name": attribute_name,
            "attribute_value": attribute_value,
            "bundle_anchor_unit_id": str(parent_ids[0]) if role == "attribute" and parent_ids else "",
            "fatigue": round(float(obj.get("energy", {}).get("fatigue", 0.0)), 8),
            "sensor_fatigue": sensor_fatigue,
            "suppression_ratio": round(float(sensor_fatigue.get("suppression_ratio", 0.0)), 6),
            "er_before_fatigue": round(float(sensor_fatigue.get("er_before_fatigue", er)), 8),
            "er_after_fatigue": round(float(sensor_fatigue.get("er_after_fatigue", er)), 8),
            "window_count": int(sensor_fatigue.get("window_count", 0) or 0),
            "threshold_count": int(sensor_fatigue.get("threshold_count", 0) or 0),
            "window_rounds": int(sensor_fatigue.get("window_rounds", 0) or 0),
            "sensor_round": int(sensor_fatigue.get("sensor_round", 0) or 0),
            "_cut_engine_unit_normalized": True,
        }

    def _build_bundle_from_csa(self, csa: dict, units: list[dict]) -> dict | None:
        units_by_id = {str(unit.get("unit_id", "")): unit for unit in units if str(unit.get("unit_id", ""))}
        for unit in units_by_id.values():
            if str(unit.get("unit_signature", "")):
                continue
            unit["unit_signature"] = self._default_unit_signature(
                token=str(unit.get("token", "")),
                unit_role=str(unit.get("unit_role", "feature") or "feature"),
            )
        member_ids = [
            str(member_id)
            for member_id in csa.get("member_sa_ids", [])
            if str(member_id) in units_by_id
        ]
        if not member_ids:
            return None
        anchor_unit_id = str(csa.get("anchor_sa_id", ""))
        if anchor_unit_id not in units_by_id:
            return None
        raw_bundle = {
            "bundle_id": str(csa.get("id", "")),
            "anchor_unit_id": anchor_unit_id,
            "member_unit_ids": member_ids,
        }
        normalized = self._normalize_csa_bundles([raw_bundle], units_by_id)
        return normalized[0] if normalized else None

    def _build_synthetic_unit_from_csa(
        self,
        *,
        csa: dict,
        group_index: int,
        source_group_index: int,
        source_type: str,
        origin_frame_id: str,
    ) -> dict | None:
        token = str(csa.get("content", {}).get("raw", "") or csa.get("content", {}).get("display", ""))
        if not token:
            return None
        summary = csa.get("bundle_summary", {}) or {}
        er = round(float(summary.get("display_total_er", 0.0)), 8)
        ev = round(float(summary.get("display_total_ev", 0.0)), 8)
        unit_signature = self._default_unit_signature(token=token, unit_role="feature")
        return {
            "unit_id": str(csa.get("anchor_sa_id", csa.get("id", ""))) or str(csa.get("id", "")),
            "object_type": "sa",
            "token": token,
            "display_text": token,
            "unit_role": "feature",
            "unit_signature": unit_signature,
            "sequence_index": int(csa.get("ext", {}).get("packet_context", {}).get("sequence_index", 0)),
            "group_index": group_index,
            "source_group_index": source_group_index,
            "source_type": source_type,
            "origin_frame_id": origin_frame_id,
            "er": er,
            "ev": ev,
            "total_energy": round(er + ev, 8),
            "display_visible": True,
            "is_placeholder": False,
            "is_punctuation": self._is_punctuation_token(token),
            "_cut_engine_unit_normalized": True,
        }

    def _empty_common_part(self, existing_groups: list[dict], incoming_groups: list[dict]) -> dict:
        normalized_existing = self._reuse_or_normalize_groups(existing_groups)
        normalized_incoming = self._reuse_or_normalize_groups(incoming_groups)
        return {
            "common_tokens": [],
            "common_length": 0,
            "common_group_count": 0,
            "matched_existing_unit_count": 0,
            "matched_incoming_unit_count": 0,
            "common_signature": "",
            "common_display": "",
            "common_groups": [],
            "matched_pairs": [],
            "matched_existing_unit_similarities": {},
            "matched_incoming_unit_similarities": {},
            "existing_range": [0, 0],
            "incoming_range": [0, 0],
            "matched_existing_group_indices": [],
            "matched_incoming_group_indices": [],
            "residual_existing_tokens": [token for group in normalized_existing for token in group.get("tokens", [])],
            "residual_incoming_tokens": [token for group in normalized_incoming for token in group.get("tokens", [])],
            "residual_existing_groups": normalized_existing,
            "residual_incoming_groups": normalized_incoming,
            "residual_existing_signature": self.sequence_groups_to_signature(normalized_existing),
            "residual_incoming_signature": self.sequence_groups_to_signature(normalized_incoming),
        }

    def _reuse_or_normalize_groups(self, groups: list[dict]) -> list[dict]:
        if isinstance(groups, list) and groups:
            reusable_groups: list[dict] = []
            all_reusable = True
            for order_index, group in enumerate(groups):
                if not isinstance(group, dict) or not self._is_reusable_normalized_group(group, order_index=order_index):
                    all_reusable = False
                    break
                reusable_groups.append(self._reuse_normalized_group(group, order_index=order_index))
            if all_reusable:
                self._increment_runtime_metric("empty_common_part_reuse_normalized_groups_hit_count")
                return reusable_groups
        return self._normalize_sequence_groups(groups)

    def _display_text(self, obj: dict) -> str:
        content = obj.get("content", {})
        if isinstance(content, dict):
            display = content.get("display") or content.get("normalized") or content.get("raw")
            if display is not None:
                return str(display)
        return str(obj.get("id", ""))

    @staticmethod
    def _dedupe_preserve_order(items: list[str]) -> list[str]:
        seen = set()
        ordered = []
        for item in items:
            text = str(item)
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return ordered

    @staticmethod
    def _is_punctuation_token(token: str) -> bool:
        text = str(token or "").strip()
        if not text:
            return True
        for char in text:
            if char.isalnum() or "\u4e00" <= char <= "\u9fff":
                return False
        return True




