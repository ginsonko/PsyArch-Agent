# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest

from hdb import HDB


class TestCSEventPersist(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="hdb_cs_event_persist_")
        self.hdb = HDB(config_override={"data_dir": self.temp_dir, "enable_background_repair": False})

    def tearDown(self):
        try:
            self.hdb.close()
        finally:
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _mk_structure(self, text: str) -> str:
        store = self.hdb._structure_store
        obj, _db = store.create_structure(
            structure_payload={
                "sub_type": "stimulus_sequence_structure",
                "unit_type": "sa_csa_sequence",
                "display_text": text,
                "member_refs": [],
                "sequence_groups": [
                    {
                        "group_index": 0,
                        "tokens": [text],
                        "units": [{"token": text}],
                        "group_signature": text,
                    }
                ],
                "flat_tokens": [text],
                "content_signature": text,
                "semantic_signature": text,
            },
            trace_id="mk_st",
            tick_id="mk_st",
            source_interface="test",
            origin="test",
            origin_id=text,
            parent_ids=[],
        )
        try:
            self.hdb._pointer_index.register_structure(obj)
        except Exception:
            pass
        return str(obj.get("id", "") or "")

    def _find_cs_event_structure_id(self, event_ref_id: str) -> str:
        signature = str(event_ref_id or "").strip()
        if not signature:
            return ""
        store = self.hdb._structure_store
        index = self.hdb._pointer_index
        try:
            for candidate_id in index.query_candidates_by_signature(signature):
                obj = store.get(candidate_id) or {}
                if str(obj.get("sub_type", "") or "") != "cognitive_stitching_event_structure":
                    continue
                struct = obj.get("structure", {}) or {}
                if str(struct.get("content_signature", "") or "") != signature:
                    continue
                return str(candidate_id)
        except Exception:
            return ""
        return ""

    def test_upsert_event_structure_creates_and_updates_in_place(self):
        st_a = self._mk_structure("A")
        st_b = self._mk_structure("B")
        st_c = self._mk_structure("C")
        st_d = self._mk_structure("D")

        event_ref_id = f"cs_event::{st_a}::{st_b}"

        res1 = self.hdb.upsert_cognitive_stitching_event_structure(
            event_ref_id=event_ref_id,
            member_refs=[st_a, st_b],
            display_text="A -> B",
            diff_rows=[
                {"target_id": st_c, "base_weight": 1.2, "entry_type": "structure_ref", "ext": {"support_hits": 2}},
            ],
            trace_id="cs_persist_1",
            tick_id="cs_persist_1",
            reason="test",
            max_diff_entries=8,
        )
        assert res1["success"] is True
        sid = str((res1.get("data", {}) or {}).get("structure_id", "") or "")
        assert sid
        assert bool((res1.get("data", {}) or {}).get("created", False)) is True
        assert int((res1.get("data", {}) or {}).get("member_link_upserted_count", 0) or 0) >= 1

        obj = self.hdb._structure_store.get(sid) or {}
        assert str(obj.get("sub_type", "") or "") == "cognitive_stitching_event_structure"
        struct = obj.get("structure", {}) or {}
        assert str(struct.get("content_signature", "") or "") == event_ref_id
        assert list(struct.get("member_refs", []) or []) == [st_a, st_b]
        seq_groups = list(struct.get("sequence_groups", []) or [])
        flat_tokens = [str(t) for t in (struct.get("flat_tokens", []) or []) if str(t)]
        assert seq_groups, "事件结构必须具备可用于索引/匹配的序列内容（不能是空壳）。"
        assert flat_tokens, "事件结构必须具备 flat_tokens（用于指针索引与展示）。"
        assert "A" in flat_tokens
        assert "B" in flat_tokens
        assert any("A" in [str(t) for t in (g.get("tokens", []) or [])] for g in seq_groups)
        assert any("B" in [str(t) for t in (g.get("tokens", []) or [])] for g in seq_groups)

        # Member -> Event links must exist so the event can be discovered via diff-table traversal.
        db_a = self.hdb._structure_store.get_db_by_owner(st_a) or {}
        db_b = self.hdb._structure_store.get_db_by_owner(st_b) or {}
        assert any(
            str(e.get("target_id", "") or "") == sid
            and str((e.get("ext", {}) or {}).get("relation_type", "") or "") == "cs_event_member"
            and str((e.get("ext", {}) or {}).get("cs_event_ref_id", "") or "") == event_ref_id
            for e in list(db_a.get("diff_table", []) or [])
        )
        assert any(
            str(e.get("target_id", "") or "") == sid
            and str((e.get("ext", {}) or {}).get("relation_type", "") or "") == "cs_event_member"
            and str((e.get("ext", {}) or {}).get("cs_event_ref_id", "") or "") == event_ref_id
            for e in list(db_b.get("diff_table", []) or [])
        )

        db = self.hdb._structure_store.get_db_by_owner(sid) or {}
        diff_table = list(db.get("diff_table", []) or [])
        assert len(diff_table) == 1
        assert str(diff_table[0].get("target_id", "") or "") == st_c
        assert str((diff_table[0].get("ext", {}) or {}).get("relation_type", "") or "") == "cs_event_outgoing"
        assert str((diff_table[0].get("ext", {}) or {}).get("cs_event_ref_id", "") or "") == event_ref_id

        # Update with a new diff set, old should be removed.
        res2 = self.hdb.upsert_cognitive_stitching_event_structure(
            event_ref_id=event_ref_id,
            member_refs=[st_a, st_b],
            display_text="A -> B",
            diff_rows=[
                {"target_id": st_d, "base_weight": 2.2, "entry_type": "structure_ref", "ext": {"support_hits": 3}},
            ],
            trace_id="cs_persist_2",
            tick_id="cs_persist_2",
            reason="test",
            max_diff_entries=8,
        )
        assert res2["success"] is True
        sid2 = str((res2.get("data", {}) or {}).get("structure_id", "") or "")
        assert sid2 == sid
        assert int((res2.get("data", {}) or {}).get("diff_removed_count", 0) or 0) >= 1
        assert int((res2.get("data", {}) or {}).get("diff_upserted_count", 0) or 0) == 1

        db2 = self.hdb._structure_store.get_db_by_owner(sid) or {}
        diff_table2 = list(db2.get("diff_table", []) or [])
        assert len(diff_table2) == 1
        assert str(diff_table2[0].get("target_id", "") or "") == st_d

    def test_component_chain_index_supports_degenerated_event(self):
        st_a = self._mk_structure("A")
        st_b = self._mk_structure("B")
        st_c = self._mk_structure("C")
        st_d = self._mk_structure("D")

        # Full event: A -> B -> C -> D
        full_ref = f"cs_event::{st_a}::{st_b}::{st_c}::{st_d}"
        res_full = self.hdb.upsert_cognitive_stitching_event_structure(
            event_ref_id=full_ref,
            member_refs=[st_a, st_b, st_c, st_d],
            display_text="A -> B -> C -> D",
            diff_rows=None,
            trace_id="cs_persist_full",
            tick_id="cs_persist_full",
            reason="test_component_chain",
            max_diff_entries=8,
        )
        assert res_full["success"] is True
        sid_full = str((res_full.get("data", {}) or {}).get("structure_id", "") or "")
        assert sid_full

        # Prefix structures should exist (created via ensure_component_chain_index).
        sid_ab = self._find_cs_event_structure_id(f"cs_event::{st_a}::{st_b}")
        assert sid_ab, "Prefix event structure [A,B] must exist"
        sid_abc = self._find_cs_event_structure_id(f"cs_event::{st_a}::{st_b}::{st_c}")
        assert sid_abc, "Prefix event structure [A,B,C] must exist"

        # Chain edge 1: A DB should have A -> [A,B] with residual=B
        db_a = self.hdb._structure_store.get_db_by_owner(st_a) or {}
        assert any(
            str(e.get("target_id", "") or "") == sid_ab
            and str(e.get("content_signature", "") or "") == st_b
            and str((e.get("ext", {}) or {}).get("relation_type", "") or "") == "cs_event_component_step"
            and int((e.get("ext", {}) or {}).get("cs_target_prefix_len", 0) or 0) == 2
            for e in list(db_a.get("diff_table", []) or [])
        )

        # Chain edge 2: [A,B] -> [A,B,C] residual=C
        db_ab = self.hdb._structure_store.get_db_by_owner(sid_ab) or {}
        assert any(
            str(e.get("target_id", "") or "") == sid_abc
            and str(e.get("content_signature", "") or "") == st_c
            and str((e.get("ext", {}) or {}).get("relation_type", "") or "") == "cs_event_component_step"
            and int((e.get("ext", {}) or {}).get("cs_target_prefix_len", 0) or 0) == 3
            for e in list(db_ab.get("diff_table", []) or [])
        )

        # Chain edge 3: [A,B,C] -> [A,B,C,D] residual=D
        db_abc = self.hdb._structure_store.get_db_by_owner(sid_abc) or {}
        assert any(
            str(e.get("target_id", "") or "") == sid_full
            and str(e.get("content_signature", "") or "") == st_d
            and str((e.get("ext", {}) or {}).get("relation_type", "") or "") == "cs_event_component_step"
            and int((e.get("ext", {}) or {}).get("cs_target_prefix_len", 0) or 0) == 4
            for e in list(db_abc.get("diff_table", []) or [])
        )

        # Degenerated event: remove C => [A,B,D]
        deg_ref = f"cs_event::{st_a}::{st_b}::{st_d}"
        res_deg = self.hdb.upsert_cognitive_stitching_event_structure(
            event_ref_id=deg_ref,
            member_refs=[st_a, st_b, st_d],
            display_text="A -> B -> D",
            diff_rows=None,
            trace_id="cs_persist_deg",
            tick_id="cs_persist_deg",
            reason="test_component_chain_degenerated",
            max_diff_entries=8,
        )
        assert res_deg["success"] is True
        sid_deg = str((res_deg.get("data", {}) or {}).get("structure_id", "") or "")
        assert sid_deg

        # Existence check path: open [A,B] DB and find residual D -> [A,B,D]
        db_ab2 = self.hdb._structure_store.get_db_by_owner(sid_ab) or {}
        assert any(
            str(e.get("target_id", "") or "") == sid_deg
            and str(e.get("content_signature", "") or "") == st_d
            and str((e.get("ext", {}) or {}).get("relation_type", "") or "") == "cs_event_component_step"
            and int((e.get("ext", {}) or {}).get("cs_target_prefix_len", 0) or 0) == 3
            for e in list(db_ab2.get("diff_table", []) or [])
        )
