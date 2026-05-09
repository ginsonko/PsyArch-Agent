# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from state_pool._id_generator import reset_id_generator
from state_pool.main import StatePool


def test_default_runtime_uses_context_guarded_semantic_merge() -> None:
    reset_id_generator()
    pool = StatePool(
        config_override={
            "pool_max_items": 64,
            "enable_placeholder_interfaces": False,
            "enable_script_broadcast": False,
        }
    )
    try:
        assert pool._config.get("enable_semantic_same_object_merge") is True
        assert pool._config.get("enable_semantic_context_same_object_merge") is True
        assert pool._config.get("allow_global_semantic_fallback_merge") is False
        assert pool._config.get("aggregate_same_semantic_incoming_objects") is True
    finally:
        pool._logger.close()


def _runtime_feature_sa(*, sa_id: str, text: str, context_id: str = "") -> dict:
    source = {"parent_ids": []}
    ext = {}
    if context_id:
        source = {
            "parent_ids": [context_id],
            "context_ref_object_id": context_id,
            "context_ref_object_type": "st",
            "context_owner_structure_id": context_id,
            "context_path_ids": [context_id],
        }
        ext = {
            "context_ref_object_id": context_id,
            "context_ref_object_type": "st",
            "context_owner_structure_id": context_id,
            "context_path_ids": [context_id],
            "context_text": context_id,
        }
    return {
        "id": sa_id,
        "object_type": "sa",
        "content": {"raw": text, "display": text, "value_type": "discrete"},
        "stimulus": {"role": "feature", "modality": "text"},
        "energy": {"er": 1.0, "ev": 0.0},
        "source": source,
        "ext": ext,
    }


def test_semantic_context_merge_collapses_same_empty_context() -> None:
    reset_id_generator()
    pool = StatePool(
        config_override={
            "pool_max_items": 64,
            "enable_placeholder_interfaces": False,
            "enable_script_broadcast": False,
            "enable_semantic_same_object_merge": True,
            "enable_semantic_context_same_object_merge": True,
            "allow_global_semantic_fallback_merge": False,
        }
    )
    try:
        first = pool.insert_runtime_node(
            _runtime_feature_sa(sa_id="sa_question_a", text="问"),
            trace_id="semctx_empty_a",
            source_module="pytest",
        )
        second = pool.insert_runtime_node(
            _runtime_feature_sa(sa_id="sa_question_b", text="问"),
            trace_id="semctx_empty_b",
            source_module="pytest",
        )
        assert first["success"] is True
        assert second["success"] is True
        assert pool._store.size == 1
        item = pool._store.get_all()[0]
        assert "sa_question_a" in item["ref_alias_ids"]
        assert "sa_question_b" in item["ref_alias_ids"]
        assert "ref=<none>" in item["semantic_context_key"]
        assert "owner=<none>" in item["semantic_context_key"]
    finally:
        pool._logger.close()


def test_semantic_context_merge_keeps_different_contexts_separate() -> None:
    reset_id_generator()
    pool = StatePool(
        config_override={
            "pool_max_items": 64,
            "enable_placeholder_interfaces": False,
            "enable_script_broadcast": False,
            "enable_semantic_same_object_merge": True,
            "enable_semantic_context_same_object_merge": True,
            "allow_global_semantic_fallback_merge": False,
        }
    )
    try:
        pool.insert_runtime_node(
            _runtime_feature_sa(sa_id="sa_same_ctx_a", text="问", context_id="st_ctx_a"),
            trace_id="semctx_a",
            source_module="pytest",
        )
        pool.insert_runtime_node(
            _runtime_feature_sa(sa_id="sa_same_ctx_b", text="问", context_id="st_ctx_b"),
            trace_id="semctx_b",
            source_module="pytest",
        )
        assert pool._store.size == 2
        keys = {item["semantic_context_key"] for item in pool._store.get_all()}
        assert len(keys) == 2
        assert any("owner=st_ctx_a" in key for key in keys)
        assert any("owner=st_ctx_b" in key for key in keys)
    finally:
        pool._logger.close()


def test_default_runtime_uses_new_attribute_state_item_route() -> None:
    reset_id_generator()
    pool = StatePool(
        config_override={
            "pool_max_items": 64,
            "enable_placeholder_interfaces": False,
            "enable_script_broadcast": False,
        }
    )
    try:
        assert pool._config.get("insert_csa_as_state_item") is False
        assert pool._config.get("insert_attribute_sa_as_state_item") is True
        assert pool._config.get("attribute_binding_runtime_mode") == "state_item"
        assert pool._config.get("allow_auto_create_csa_on_attribute_bind") is False
    finally:
        pool._logger.close()
