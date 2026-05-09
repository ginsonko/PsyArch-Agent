# -*- coding: utf-8 -*-
"""
AP 状态池模块 - 属性绑定引擎（清晰实现版）
========================================

旧版文件中存在较重的编码痕迹，本实现保持相同类名与主要行为，
但把运行时属性绑定、展示字段回写和自动创建绑定型 CSA 的逻辑整理为可维护版本。
"""

from __future__ import annotations

import time

from . import __schema_version__
from ._id_generator import next_id


class BindingEngine:
    """负责把属性 SA 绑定到 SA / CSA 类型的状态池对象。"""

    def __init__(self, config: dict):
        self._config = config

    @staticmethod
    def _extract_attribute_name(attribute_sa: dict) -> str:
        content = attribute_sa.get("content", {}) if isinstance(attribute_sa.get("content", {}), dict) else {}
        name = str(content.get("attribute_name", "") or "").strip()
        if name:
            return name
        raw = str(content.get("raw", "") or "")
        if ":" in raw:
            return raw.split(":", 1)[0].strip()
        return ""

    @staticmethod
    def _extract_energy(attribute_sa: dict | None) -> tuple[float, float]:
        if not isinstance(attribute_sa, dict):
            return 0.0, 0.0
        energy = attribute_sa.get("energy", {}) if isinstance(attribute_sa.get("energy", {}), dict) else {}
        try:
            return float(energy.get("er", 0.0) or 0.0), float(energy.get("ev", 0.0) or 0.0)
        except Exception:
            return 0.0, 0.0

    @staticmethod
    def _find_bound_attribute_snapshot_by_id(target_item: dict, attr_id: str) -> dict | None:
        ext = target_item.get("ext", {}) if isinstance(target_item.get("ext", {}), dict) else {}
        attrs = ext.get("bound_attributes", []) if isinstance(ext.get("bound_attributes", []), list) else []
        for a in attrs:
            if isinstance(a, dict) and str(a.get("id", "") or "") == str(attr_id or ""):
                return a
        return None

    @staticmethod
    def _find_bound_attribute_snapshot_by_name(target_item: dict, attr_name: str) -> dict | None:
        """Best-effort: return the newest bound attribute snapshot matching attribute_name."""
        name = str(attr_name or "").strip()
        if not name:
            return None
        ext = target_item.get("ext", {}) if isinstance(target_item.get("ext", {}), dict) else {}
        attrs = ext.get("bound_attributes", []) if isinstance(ext.get("bound_attributes", []), list) else []
        best = None
        best_updated = -1
        for a in attrs:
            if not isinstance(a, dict):
                continue
            content = a.get("content", {}) if isinstance(a.get("content", {}), dict) else {}
            an = str(content.get("attribute_name", "") or "").strip()
            if not an:
                raw = str(content.get("raw", "") or "")
                if ":" in raw:
                    an = raw.split(":", 1)[0].strip()
            if an != name:
                continue
            try:
                u = int(a.get("updated_at", 0) or 0)
            except Exception:
                u = 0
            if u >= best_updated:
                best_updated = u
                best = a
        return best

    def _maybe_transfer_dissonance_to_correctness(
        self,
        *,
        target_item: dict,
        dissonance_before_ev: float,
        dissonance_after_ev: float,
        now_ms: int,
        tick_number: int,
    ) -> None:
        # Conservation-style transform (MVP):
        # when dissonance decreases on the same object, increase correctness by the same amount.
        if not bool(self._config.get("enable_cfs_correctness_transfer", True)):
            return
        drop = float(dissonance_before_ev) - float(dissonance_after_ev)
        if drop <= 1e-12:
            return

        correct_name = str(self._config.get("cfs_correctness_attribute_name", "cfs_correctness") or "cfs_correctness").strip() or "cfs_correctness"
        target_ref_id = str(target_item.get("ref_object_id", "") or target_item.get("id", "") or "").strip()
        correct_id = f"sa_iesm_attr_{correct_name}_{target_ref_id or 'item'}"

        # Ensure binding_state id list contains correctness id (dedup).
        bs = target_item.setdefault("binding_state", {})
        if isinstance(bs, dict):
            ids = bs.setdefault("bound_attribute_sa_ids", [])
            if isinstance(ids, list) and correct_id not in ids:
                ids.append(correct_id)

        correctness_attr = {
            "id": correct_id,
            "object_type": "sa",
            "content": {
                "raw": f"{correct_name}:{round(float(drop), 6)}",
                "display": f"正确感:+{round(float(drop), 3)}",
                "value_type": "numerical",
                "attribute_name": correct_name,
                "attribute_value": float(round(float(drop), 8)),
            },
            "stimulus": {"role": "attribute", "modality": "internal"},
            "energy": {"er": float(round(float(drop), 8)), "ev": 0.0},
            "meta": {
                "ext": {
                    "energy_update_mode": "add",
                    "derived_from": "cfs_dissonance_drop",
                    "created_at_ms": int(now_ms),
                    "tick_number": int(tick_number),
                }
            },
        }
        self._append_bound_attribute_snapshot(target_item, correctness_attr, now_ms=now_ms)

    def validate_attribute_sa(self, attribute_sa: dict) -> str | None:
        if not isinstance(attribute_sa, dict):
            return "attribute_sa 不是 dict / attribute_sa is not a dict"

        if attribute_sa.get("object_type") != "sa":
            actual = attribute_sa.get("object_type", "")
            return (
                f"attribute_sa.object_type 必须为 'sa'，实际为 '{actual}' / "
                f"must be 'sa', got '{actual}'"
            )

        role = attribute_sa.get("stimulus", {}).get("role", "")
        if role != "attribute":
            return (
                f"attribute_sa.stimulus.role 必须为 'attribute'，实际为 '{role}' / "
                f"must be 'attribute', got '{role}'"
            )

        if not attribute_sa.get("id"):
            return "attribute_sa 缺少 id / attribute_sa missing id"

        return None

    def bind_to_sa_item(
        self,
        target_item: dict,
        attribute_sa: dict,
        pool_store,
        trace_id: str,
        tick_id: str,
        tick_number: int,
        source_module: str = "unknown",
    ) -> dict:
        now_ms = int(time.time() * 1000)
        attr_id = attribute_sa["id"]
        attr_name = self._extract_attribute_name(attribute_sa)
        dis_name = str(self._config.get("cfs_dissonance_attribute_name", "cfs_dissonance") or "cfs_dissonance").strip() or "cfs_dissonance"
        track_dissonance = bool(self._config.get("enable_cfs_correctness_transfer", True)) and attr_name == dis_name
        dis_before_ev = 0.0
        if track_dissonance:
            # For dynamic CFS attributes (e.g. cfs_dissonance), attribute ids can be stable
            # (same id updated each tick) or "versioned" (new id per tick). We still want
            # correctness transfer to work in both cases.
            #
            # Prefer exact id match; fallback to latest-by-name snapshot.
            prev = self._find_bound_attribute_snapshot_by_id(target_item, attr_id)
            if prev is None:
                prev = self._find_bound_attribute_snapshot_by_name(target_item, dis_name)
            dis_before_ev = float(self._extract_energy(prev)[1])

        # Dedup-by-id should still allow update semantics, otherwise dynamic attributes
        # (e.g. 违和感强度、期待强度) would become "write once then stale".
        # 按 ID 去重时仍要允许覆盖更新，否则动态属性会变成“一次写入后永远不变”，影响可观测性。
        existing_ids = target_item.get("binding_state", {}).get("bound_attribute_sa_ids", [])
        if (
            self._config.get("attribute_bind_deduplicate_by_id", True)
            and isinstance(existing_ids, list)
            and attr_id in existing_ids
        ):
            target_item["updated_at"] = now_ms
            target_item.setdefault("lifecycle", {})["last_active_tick"] = tick_number
            self._append_bound_attribute_snapshot(target_item, attribute_sa, now_ms=now_ms)
            if track_dissonance:
                curr = self._find_bound_attribute_snapshot_by_id(target_item, attr_id)
                if curr is None:
                    curr = self._find_bound_attribute_snapshot_by_name(target_item, dis_name)
                dis_after_ev = float(self._extract_energy(curr)[1])
                self._maybe_transfer_dissonance_to_correctness(
                    target_item=target_item,
                    dissonance_before_ev=dis_before_ev,
                    dissonance_after_ev=dis_after_ev,
                    now_ms=now_ms,
                    tick_number=tick_number,
                )
            return {
                "created_new_csa": False,
                "deduplicated": True,
                "updated_existing": True,
                "bound_attribute_sa_id": attr_id,
                "bound_csa_item_id": target_item.get("binding_state", {}).get("bound_csa_item_id"),
            }

        if self._config.get("attribute_bind_deduplicate_by_content", False) and self._should_deduplicate(target_item, attr_id, attribute_sa):
            return {
                "created_new_csa": False,
                "deduplicated": True,
                "updated_existing": False,
                "bound_attribute_sa_id": attr_id,
                "bound_csa_item_id": target_item.get("binding_state", {}).get("bound_csa_item_id"),
            }

        target_item.setdefault("binding_state", {}).setdefault("bound_attribute_sa_ids", []).append(attr_id)
        target_item["updated_at"] = now_ms
        target_item.setdefault("lifecycle", {})["last_active_tick"] = tick_number
        self._append_bound_attribute_snapshot(target_item, attribute_sa, now_ms=now_ms)
        if track_dissonance:
            curr = self._find_bound_attribute_snapshot_by_id(target_item, attr_id)
            if curr is None:
                curr = self._find_bound_attribute_snapshot_by_name(target_item, dis_name)
            dis_after_ev = float(self._extract_energy(curr)[1])
            self._maybe_transfer_dissonance_to_correctness(
                target_item=target_item,
                dissonance_before_ev=dis_before_ev,
                dissonance_after_ev=dis_after_ev,
                now_ms=now_ms,
                tick_number=tick_number,
            )

        # 默认不自动创建“绑定型 CSA”：CSA 主要承担匹配约束作用，不一定要以独立对象存在于 SP。
        allow_auto = bool(self._config.get("allow_auto_create_csa_on_attribute_bind", False))
        bound_csa_item_id = target_item.get("binding_state", {}).get("bound_csa_item_id")
        created_new_csa = False
        if allow_auto:
            existing = pool_store.get(bound_csa_item_id) if bound_csa_item_id else None
            if existing is None:
                # 创建绑定型 CSA state_item（synthetic），用于观测与后续脚本/匹配消费。
                anchor_ref_id = str(target_item.get("ref_object_id", "") or "")
                anchor_display = self._extract_target_display(target_item)
                attribute_display = self._extract_attribute_display(attribute_sa)
                csa_spi_id = next_id("spi")
                csa_item = {
                    "id": csa_spi_id,
                    "object_type": "state_item",
                    "sub_type": "csa_binding_item",
                    "schema_version": __schema_version__,
                    "ref_object_type": "csa",
                    "ref_object_id": f"csa_bind_{anchor_ref_id}_{attr_id}",
                    "ref_alias_ids": [],
                    "ref_snapshot": {
                        "content_display": f"BindingCSA[{anchor_display or anchor_ref_id}]",
                        "content_display_detail": f"anchor={anchor_display or anchor_ref_id} | attrs={attribute_display}",
                        "source_module": source_module,
                        "anchor_sa_ref": anchor_ref_id,
                        "attribute_sa_id": attr_id,
                        "anchor_display": anchor_display,
                        "attribute_displays": [attribute_display] if attribute_display else [],
                        "bound_attribute_displays": [attribute_display] if attribute_display else [],
                        "member_count": 2,
                    },
                    "semantic_signature": "",
                    "energy": {
                        "er": float(target_item.get("energy", {}).get("er", 0.0) or 0.0),
                        "ev": float(target_item.get("energy", {}).get("ev", 0.0) or 0.0),
                        "ownership_level": "aggregated_from_sa",
                        "computed_from_children": True,
                        "fatigue": 0.0,
                        "recency_gain": 1.0,
                        "salience_score": float(target_item.get("energy", {}).get("salience_score", 0.0) or 0.0),
                        "cognitive_pressure_delta": float(target_item.get("energy", {}).get("cognitive_pressure_delta", 0.0) or 0.0),
                        "cognitive_pressure_abs": float(target_item.get("energy", {}).get("cognitive_pressure_abs", 0.0) or 0.0),
                        "last_decay_tick": 0,
                        "last_decay_at": now_ms,
                    },
                    "dynamics": {
                        "prev_er": 0.0,
                        "prev_ev": 0.0,
                        "delta_er": float(target_item.get("energy", {}).get("er", 0.0) or 0.0),
                        "delta_ev": float(target_item.get("energy", {}).get("ev", 0.0) or 0.0),
                        "er_change_rate": 0.0,
                        "ev_change_rate": 0.0,
                        "prev_cp_delta": 0.0,
                        "prev_cp_abs": 0.0,
                        "delta_cp_delta": float(target_item.get("energy", {}).get("cognitive_pressure_delta", 0.0) or 0.0),
                        "delta_cp_abs": float(target_item.get("energy", {}).get("cognitive_pressure_abs", 0.0) or 0.0),
                        "cp_delta_rate": 0.0,
                        "cp_abs_rate": 0.0,
                        "last_update_tick": tick_number,
                        "last_update_at": now_ms,
                        "update_count": 1,
                    },
                    "binding_state": {
                        "bound_csa_item_id": None,
                        "bound_attribute_sa_ids": [attr_id],
                    },
                    "lifecycle": {
                        "created_in_tick": tick_number,
                        "last_active_tick": tick_number,
                        "elimination_candidate": False,
                    },
                    "source": {
                        "module": "state_pool",
                        "interface": "bind_attribute_node_to_object",
                        "origin": "attribute_binding",
                        "origin_id": target_item.get("id", ""),
                        "parent_ids": [target_item.get("id", ""), attr_id],
                    },
                    "trace_id": trace_id,
                    "tick_id": tick_id,
                    "created_at": now_ms,
                    "updated_at": now_ms,
                    "status": "active",
                    "ext": {"bound_attributes": [attribute_sa]},
                    "meta": {
                        "confidence": 1.0,
                        "field_registry_version": __schema_version__,
                        "debug": {},
                        "ext": {},
                    },
                }
                pool_store.insert(csa_item)
                target_item["binding_state"]["bound_csa_item_id"] = csa_spi_id
                bound_csa_item_id = csa_spi_id
                created_new_csa = True
            else:
                # 若已有绑定型 CSA，则同步把该属性写入其展示快照，便于观测。
                existing.setdefault("binding_state", {}).setdefault("bound_attribute_sa_ids", []).append(attr_id)
                existing["updated_at"] = now_ms
                existing.setdefault("lifecycle", {})["last_active_tick"] = tick_number
                self._append_bound_attribute_snapshot(existing, attribute_sa)

        return {
            "created_new_csa": created_new_csa,
            "deduplicated": False,
            "bound_attribute_sa_id": attr_id,
            "bound_csa_item_id": bound_csa_item_id,
        }

    def bind_to_csa_item(
        self,
        target_item: dict,
        attribute_sa: dict,
        trace_id: str,
        tick_id: str,
        tick_number: int,
    ) -> dict:
        now_ms = int(time.time() * 1000)
        attr_id = attribute_sa["id"]
        attr_name = self._extract_attribute_name(attribute_sa)
        dis_name = str(self._config.get("cfs_dissonance_attribute_name", "cfs_dissonance") or "cfs_dissonance").strip() or "cfs_dissonance"
        track_dissonance = bool(self._config.get("enable_cfs_correctness_transfer", True)) and attr_name == dis_name
        dis_before_ev = 0.0
        if track_dissonance:
            prev = self._find_bound_attribute_snapshot_by_id(target_item, attr_id)
            if prev is None:
                prev = self._find_bound_attribute_snapshot_by_name(target_item, dis_name)
            dis_before_ev = float(self._extract_energy(prev)[1])

        existing_ids = target_item.get("binding_state", {}).get("bound_attribute_sa_ids", [])
        if (
            self._config.get("attribute_bind_deduplicate_by_id", True)
            and isinstance(existing_ids, list)
            and attr_id in existing_ids
        ):
            target_item["updated_at"] = now_ms
            target_item.setdefault("lifecycle", {})["last_active_tick"] = tick_number
            self._append_bound_attribute_snapshot(target_item, attribute_sa, now_ms=now_ms)
            if track_dissonance:
                curr = self._find_bound_attribute_snapshot_by_id(target_item, attr_id)
                if curr is None:
                    curr = self._find_bound_attribute_snapshot_by_name(target_item, dis_name)
                dis_after_ev = float(self._extract_energy(curr)[1])
                self._maybe_transfer_dissonance_to_correctness(
                    target_item=target_item,
                    dissonance_before_ev=dis_before_ev,
                    dissonance_after_ev=dis_after_ev,
                    now_ms=now_ms,
                    tick_number=tick_number,
                )
            return {
                "created_new_csa": False,
                "deduplicated": True,
                "updated_existing": True,
                "bound_attribute_sa_id": attr_id,
            }

        if self._config.get("attribute_bind_deduplicate_by_content", False) and self._should_deduplicate(target_item, attr_id, attribute_sa):
            return {
                "created_new_csa": False,
                "deduplicated": True,
                "updated_existing": False,
                "bound_attribute_sa_id": attr_id,
            }

        target_item.setdefault("binding_state", {}).setdefault("bound_attribute_sa_ids", []).append(attr_id)
        target_item["updated_at"] = now_ms
        target_item.setdefault("lifecycle", {})["last_active_tick"] = tick_number
        self._append_bound_attribute_snapshot(target_item, attribute_sa, now_ms=now_ms)
        if track_dissonance:
            curr = self._find_bound_attribute_snapshot_by_id(target_item, attr_id)
            if curr is None:
                curr = self._find_bound_attribute_snapshot_by_name(target_item, dis_name)
            dis_after_ev = float(self._extract_energy(curr)[1])
            self._maybe_transfer_dissonance_to_correctness(
                target_item=target_item,
                dissonance_before_ev=dis_before_ev,
                dissonance_after_ev=dis_after_ev,
                now_ms=now_ms,
                tick_number=tick_number,
            )

        return {
            "created_new_csa": False,
            "deduplicated": False,
            "bound_csa_item_id": target_item["id"],
            "bound_attribute_sa_id": attr_id,
        }

    def _should_deduplicate(self, target_item: dict, attr_id: str, attribute_sa: dict) -> bool:
        existing_ids = target_item.get("binding_state", {}).get("bound_attribute_sa_ids", [])
        if self._config.get("attribute_bind_deduplicate_by_id", True) and attr_id in existing_ids:
            return True

        if self._config.get("attribute_bind_deduplicate_by_content", False):
            raw = attribute_sa.get("content", {}).get("raw", "")
            ext_attrs = target_item.get("ext", {}).get("bound_attributes", [])
            for existing_attr in ext_attrs:
                if isinstance(existing_attr, dict) and existing_attr.get("content", {}).get("raw", "") == raw:
                    return True

        return False

    def _append_bound_attribute_snapshot(self, target_item: dict, attribute_sa: dict, *, now_ms: int | None = None):
        """
        Record a lightweight runtime-attribute view on the target item.
        在目标对象上记录一份轻量的运行态属性视图（用于观测与规则匹配）。

        Key design / 关键设计：
        - 按 attribute_id 支持覆盖更新（避免动态属性“写一次就过期”）。
        - 按 attribute_name 维护稳定的展示列表（避免 display 值变化导致 bound_attribute_displays 无限增长）。
        """
        now_ms = int(now_ms or (time.time() * 1000))
        # Determine energy update mode before we snapshot/derive displays.
        update_mode = ""
        try:
            meta = attribute_sa.get("meta", {}) if isinstance(attribute_sa.get("meta", {}), dict) else {}
            extm = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
            update_mode = str(extm.get("energy_update_mode", extm.get("update_mode", "")) or "").strip().lower()
        except Exception:
            update_mode = ""
        if update_mode not in {"", "set", "replace", "add", "max"}:
            update_mode = ""

        # ---- ext.bound_attributes: keep the newest snapshot per id ----
        ext = target_item.setdefault("ext", {})
        ext_attrs = list(ext.get("bound_attributes", []) or [])
        replaced = False
        final_snapshot = attribute_sa
        for i, existing in enumerate(ext_attrs):
            if isinstance(existing, dict) and existing.get("id") == attribute_sa.get("id"):
                if update_mode in {"add", "max"}:
                    old_er, old_ev = self._extract_energy(existing)
                    inc_er, inc_ev = self._extract_energy(attribute_sa)
                    if update_mode == "add":
                        new_er = old_er + inc_er
                        new_ev = old_ev + inc_ev
                    else:
                        new_er = max(old_er, inc_er)
                        new_ev = max(old_ev, inc_ev)
                    new_er = round(float(new_er), 8)
                    new_ev = round(float(new_ev), 8)
                    merged = dict(existing)
                    merged["energy"] = {"er": new_er, "ev": new_ev}
                    merged["updated_at"] = now_ms
                    content = merged.get("content", {}) if isinstance(merged.get("content", {}), dict) else {}
                    attr_name = self._extract_attribute_name(merged) or self._extract_attribute_name(attribute_sa)
                    if attr_name:
                        total = float(new_er) + float(new_ev)
                        content["attribute_value"] = float(round(total, 8))
                        content["raw"] = f"{attr_name}:{round(total, 6)}"
                        label_map = {
                            "cfs_correctness": "正确感",
                            "cfs_dissonance": "违和感",
                            "cfs_pressure": "压力",
                            "cfs_expectation": "期待",
                            "cfs_grasp": "把握感/置信度",
                        }
                        label = label_map.get(attr_name, attr_name)
                        content["display"] = f"{label}:{round(total, 3)}"
                    merged["content"] = content
                    ext_attrs[i] = merged
                    final_snapshot = merged
                else:
                    ext_attrs[i] = attribute_sa
                    final_snapshot = attribute_sa
                replaced = True
                break
        if not replaced:
            ext_attrs.append(attribute_sa)
            final_snapshot = attribute_sa
        ext["bound_attributes"] = ext_attrs

        attribute_display = self._extract_attribute_display(final_snapshot)

        # ---- binding_state.bound_attribute_by_name: stable mapping ----
        content = final_snapshot.get("content", {}) or {}
        attr_name = str(content.get("attribute_name", "") or "").strip()
        if not attr_name:
            raw = str(content.get("raw", "") or "")
            if ":" in raw:
                attr_name = raw.split(":", 1)[0].strip()
            else:
                attr_name = raw.strip()
        if attr_name:
            binding_state = target_item.setdefault("binding_state", {})
            by_name = binding_state.setdefault("bound_attribute_by_name", {})
            if isinstance(by_name, dict):
                by_name[attr_name] = {
                    "attribute_name": attr_name,
                    "display": attribute_display,
                    "sa_id": str(final_snapshot.get("id", "") or ""),
                    "updated_at": now_ms,
                }

        ref_snapshot = target_item.setdefault("ref_snapshot", {})
        # 对绑定型 CSA（以及真实 CSA state_item）同步更新 attribute_displays，便于快照解释与测试。
        if target_item.get("ref_object_type") == "csa" or target_item.get("sub_type") == "csa_binding_item":
            attr_displays = list(ref_snapshot.get("attribute_displays", []))
            if attribute_display and attribute_display not in attr_displays:
                attr_displays.append(attribute_display)
            ref_snapshot["attribute_displays"] = attr_displays

        # ---- ref_snapshot.bound_attribute_displays: stable ordered view ----
        by_name = target_item.get("binding_state", {}).get("bound_attribute_by_name", {})
        if isinstance(by_name, dict) and by_name:
            ordered = sorted(list(by_name.values()), key=lambda row: str(row.get("attribute_name", "")))
            bound_displays = [str(row.get("display", "")) for row in ordered if str(row.get("display", ""))]
            ref_snapshot["bound_attribute_displays"] = bound_displays
        else:
            bound_displays = list(ref_snapshot.get("bound_attribute_displays", []))
            if attribute_display and attribute_display not in bound_displays:
                bound_displays.append(attribute_display)
            ref_snapshot["bound_attribute_displays"] = bound_displays

        detail_parts = []
        if ref_snapshot.get("anchor_display"):
            detail_parts.append(f"anchor={ref_snapshot.get('anchor_display')}")
        if ref_snapshot.get("attribute_displays"):
            detail_parts.append(f"attrs={', '.join(ref_snapshot.get('attribute_displays', [])[:4])}")
        if bound_displays:
            detail_parts.append(f"runtime_attrs={', '.join(bound_displays[:4])}")
        if detail_parts:
            ref_snapshot["content_display_detail"] = " | ".join(detail_parts)

    @staticmethod
    def _extract_attribute_display(attribute_sa: dict) -> str:
        content = attribute_sa.get("content", {})
        return str(content.get("display", content.get("raw", attribute_sa.get("id", ""))))

    @staticmethod
    def _extract_target_display(target_item: dict) -> str:
        ref_snapshot = target_item.get("ref_snapshot", {})
        return str(ref_snapshot.get("content_display", target_item.get("ref_object_id", target_item.get("id", ""))))

    def update_config(self, config: dict):
        self._config = config
