# -*- coding: utf-8 -*-
"""
Expectation contracts for delayed training supervision.

This module keeps the first implementation intentionally conservative:
- contracts are registered from source dataset ticks only
- matching windows are counted on later source ticks only
- synthetic feedback ticks never consume or satisfy the window
- settlement produces new audit-friendly feedback ticks instead of mutating history
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ExpectationContractError(ValueError):
    pass


def _as_dict(v: Any) -> dict[str, Any]:
    return dict(v) if isinstance(v, dict) else {}


def _as_list(v: Any) -> list[Any]:
    return list(v) if isinstance(v, list) else []


def _as_str(v: Any) -> str:
    return str(v) if v is not None else ""


def _as_int(v: Any, *, where: str, default: int | None = None) -> int:
    try:
        return int(v)
    except Exception as exc:
        if default is not None:
            return int(default)
        raise ExpectationContractError(f"{where} must be int, got: {v!r}") from exc


def _as_bool(v: Any, *, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return bool(default)
    if isinstance(v, (int, float)):
        return bool(v)
    s = _as_str(v).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off", ""}:
        return False
    return bool(default)


def _clamp01(v: Any, *, where: str) -> float:
    try:
        num = float(v)
    except Exception as exc:
        raise ExpectationContractError(f"{where} must be float-compatible, got: {v!r}") from exc
    return max(0.0, min(1.0, float(num)))


def _normalize_condition_item(raw: Any, *, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ExpectationContractError(f"{where} must be a mapping.")
    item = dict(raw)
    kind = _as_str(item.get("kind", "")).strip()
    if not kind:
        raise ExpectationContractError(f"{where}.kind is required.")

    if kind in {"metric_gte", "metric_lte", "metric_eq"}:
        metric = _as_str(item.get("metric", "")).strip()
        if not metric:
            raise ExpectationContractError(f"{where}.metric is required for {kind}.")
        return {"kind": kind, "metric": metric, "value": float(item.get("value", 0.0) or 0.0)}

    if kind == "action_executed_kind_min":
        action_kind = _as_str(item.get("action_kind", "")).strip()
        if not action_kind:
            raise ExpectationContractError(f"{where}.action_kind is required for action_executed_kind_min.")
        min_count = _as_int(item.get("min_count", item.get("value", 1)), where=f"{where}.min_count", default=1)
        return {"kind": kind, "action_kind": action_kind, "min_count": max(0, int(min_count))}

    if kind in {"report_path_truthy", "report_path_equals"}:
        path = _as_str(item.get("path", "")).strip()
        if not path:
            raise ExpectationContractError(f"{where}.path is required for {kind}.")
        out = {"kind": kind, "path": path}
        if kind == "report_path_equals":
            out["value"] = item.get("value")
        return out

    raise ExpectationContractError(f"{where}.kind unsupported: {kind}")


def _normalize_condition_group(raw: Any, *, where: str) -> dict[str, Any]:
    if raw is None:
        return {"mode": "all", "items": []}
    if isinstance(raw, dict):
        if "mode" in raw and "items" in raw:
            mode = str(raw.get("mode", "all") or "all")
            items = [_normalize_condition_item(x, where=f"{where}.items[{i}]") for i, x in enumerate(_as_list(raw.get("items")))]
            return {"mode": "any" if mode == "any" else "all", "items": items}
        if "all" in raw:
            return {
                "mode": "all",
                "items": [_normalize_condition_item(x, where=f"{where}.all[{i}]") for i, x in enumerate(_as_list(raw.get("all")))],
            }
        if "any" in raw:
            return {
                "mode": "any",
                "items": [_normalize_condition_item(x, where=f"{where}.any[{i}]") for i, x in enumerate(_as_list(raw.get("any")))],
            }
        return {"mode": "all", "items": [_normalize_condition_item(raw, where=f"{where}[0]")]}
    if isinstance(raw, list):
        return {"mode": "all", "items": [_normalize_condition_item(x, where=f"{where}[{i}]") for i, x in enumerate(raw)]}
    raise ExpectationContractError(f"{where} must be a dict or list.")


def _normalize_outcome(raw: Any, *, where: str, default_text: str) -> dict[str, Any]:
    if raw is None:
        return {
            "teacher_rwd": 0.0,
            "teacher_pun": 0.0,
            "feedback_text": default_text,
            "feedback_note": "",
            "feedback_tags": [],
            "labels": {},
            "emit_feedback_tick": True,
        }
    if not isinstance(raw, dict):
        raise ExpectationContractError(f"{where} must be a mapping.")
    item = dict(raw)
    labels = _as_dict(item.get("labels"))
    feedback_tags = [str(x).strip() for x in _as_list(item.get("feedback_tags")) if str(x).strip()]
    return {
        "teacher_rwd": _clamp01(item.get("teacher_rwd", 0.0), where=f"{where}.teacher_rwd"),
        "teacher_pun": _clamp01(item.get("teacher_pun", 0.0), where=f"{where}.teacher_pun"),
        "feedback_text": _as_str(item.get("feedback_text", default_text)).strip() or default_text,
        "feedback_note": _as_str(item.get("feedback_note", item.get("teacher_note", ""))).strip(),
        "feedback_tags": feedback_tags,
        "labels": labels,
        "emit_feedback_tick": _as_bool(item.get("emit_feedback_tick", True), default=True),
    }


def _normalize_anchor_policy(raw: Any, *, where: str) -> dict[str, Any]:
    if raw is None:
        return {"mode": "pool_top1_total", "ref_object_types": ["st"]}
    if isinstance(raw, str):
        return {"mode": str(raw).strip() or "pool_top1_total", "ref_object_types": ["st"]}
    if not isinstance(raw, dict):
        raise ExpectationContractError(f"{where} must be a string or mapping.")
    item = dict(raw)
    mode = _as_str(item.get("mode", item.get("anchor", "pool_top1_total"))).strip() or "pool_top1_total"
    ref_types = [str(x).strip() for x in _as_list(item.get("ref_object_types")) if str(x).strip()]
    return {
        "mode": mode,
        "ref_object_types": ref_types or ["st"],
        "item_id": _as_str(item.get("item_id", "")).strip(),
        "ref_object_id": _as_str(item.get("ref_object_id", "")).strip(),
        "ref_object_type": _as_str(item.get("ref_object_type", "")).strip(),
        "contains_text": _as_str(item.get("contains_text", "")).strip(),
    }


def normalize_expectation_contract_spec(raw: Any, *, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ExpectationContractError(f"{where} must be a mapping.")
    item = dict(raw)
    within_ticks = _as_int(item.get("within_ticks", 1), where=f"{where}.within_ticks", default=1)
    if within_ticks <= 0:
        raise ExpectationContractError(f"{where}.within_ticks must be >= 1.")

    success_conditions = _normalize_condition_group(item.get("success_conditions"), where=f"{where}.success_conditions")
    failure_conditions = _normalize_condition_group(item.get("failure_conditions"), where=f"{where}.failure_conditions")
    if not success_conditions["items"] and not failure_conditions["items"]:
        raise ExpectationContractError(f"{where} must define success_conditions or failure_conditions.")

    return {
        "id": _as_str(item.get("id", "")).strip(),
        "within_ticks": int(within_ticks),
        "success_conditions": success_conditions,
        "failure_conditions": failure_conditions,
        "on_success": _normalize_outcome(item.get("on_success"), where=f"{where}.on_success", default_text="系统反馈：执行成功"),
        "on_failure": _normalize_outcome(item.get("on_failure"), where=f"{where}.on_failure", default_text="系统反馈：没有执行"),
        "anchor_policy": _normalize_anchor_policy(item.get("anchor_policy"), where=f"{where}.anchor_policy"),
        "emit_feedback_tick": _as_bool(item.get("emit_feedback_tick", True), default=True),
        "fail_on_run_end": _as_bool(item.get("fail_on_run_end", True), default=True),
    }


def normalize_expectation_contracts_from_labels(labels: dict[str, Any] | None, *, where: str = "labels") -> list[dict[str, Any]]:
    labels = labels if isinstance(labels, dict) else {}
    raws: list[Any] = []
    if "expectation_contract" in labels and labels.get("expectation_contract") is not None:
        raws.append(labels.get("expectation_contract"))
    if "expectation_contracts" in labels and labels.get("expectation_contracts") is not None:
        contracts = labels.get("expectation_contracts")
        if not isinstance(contracts, list):
            raise ExpectationContractError(f"{where}.expectation_contracts must be a list.")
        raws.extend(list(contracts))
    return [normalize_expectation_contract_spec(raw, where=f"{where}.expectation_contracts[{i}]") for i, raw in enumerate(raws)]


def _get_path_value(obj: Any, path: str) -> Any:
    cur = obj
    for token in [p for p in str(path or "").split(".") if p]:
        if isinstance(cur, dict):
            cur = cur.get(token)
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(token)]
                continue
            except Exception:
                return None
        return None
    return cur


def _evaluate_condition_item(item: dict[str, Any], *, report: dict[str, Any], metrics: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    kind = str(item.get("kind", "") or "")
    if kind == "metric_gte":
        metric = str(item.get("metric", "") or "")
        cur = float(metrics.get(metric, 0.0) or 0.0)
        target = float(item.get("value", 0.0) or 0.0)
        return cur >= target, {"metric": metric, "current": cur, "target": target}
    if kind == "metric_lte":
        metric = str(item.get("metric", "") or "")
        cur = float(metrics.get(metric, 0.0) or 0.0)
        target = float(item.get("value", 0.0) or 0.0)
        return cur <= target, {"metric": metric, "current": cur, "target": target}
    if kind == "metric_eq":
        metric = str(item.get("metric", "") or "")
        target = item.get("value")
        if metric.startswith("action_"):
            cur = int(metrics.get(metric, 0) or 0)
            try:
                target = int(target or 0)
            except Exception:
                target = 0
        else:
            cur = metrics.get(metric)
        return cur == target, {"metric": metric, "current": cur, "target": target}
    if kind == "action_executed_kind_min":
        action_kind = str(item.get("action_kind", "") or "").strip()
        metric_key = f"action_executed_{action_kind}_source_visible"
        if metric_key not in metrics:
            metric_key = f"action_executed_{action_kind}"
        cur = int(metrics.get(metric_key, 0) or 0)
        target = int(item.get("min_count", 1) or 1)
        return cur >= target, {"metric": metric_key, "current": cur, "target": target}
    if kind == "report_path_truthy":
        path = str(item.get("path", "") or "")
        cur = _get_path_value(report, path)
        return bool(cur), {"path": path, "current": cur}
    if kind == "report_path_equals":
        path = str(item.get("path", "") or "")
        cur = _get_path_value(report, path)
        target = item.get("value")
        return cur == target, {"path": path, "current": cur, "target": target}
    return False, {"unsupported": kind}


def _evaluate_condition_group(group: dict[str, Any], *, report: dict[str, Any], metrics: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    items = [x for x in _as_list(group.get("items")) if isinstance(x, dict)]
    if not items:
        return False, []
    results: list[dict[str, Any]] = []
    for item in items:
        matched, detail = _evaluate_condition_item(item, report=report, metrics=metrics)
        results.append({"kind": item.get("kind", ""), "matched": bool(matched), "detail": detail})
    mode = str(group.get("mode", "all") or "all")
    if mode == "any":
        return any(bool(r.get("matched", False)) for r in results), results
    return all(bool(r.get("matched", False)) for r in results), results


def _pick_anchor_candidate(rows: list[dict[str, Any]], *, ref_object_types: list[str]) -> dict[str, Any]:
    allow = {str(x) for x in ref_object_types if str(x)}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if allow and str(row.get("ref_object_type", "") or "") not in allow:
            continue
        return dict(row)
    return {}


def freeze_anchor_from_report(anchor_policy: dict[str, Any], *, report: dict[str, Any]) -> dict[str, Any]:
    policy = _normalize_anchor_policy(anchor_policy, where="anchor_policy")
    mode = str(policy.get("mode", "pool_top1_total") or "pool_top1_total")
    if mode in {"none", "off", "disabled"}:
        return {"mode": "none"}

    if mode == "specific_ref" and str(policy.get("ref_object_id", "") or "").strip():
        return {
            "mode": "specific_ref",
            "teacher_anchor": "specific_ref",
            "teacher_anchor_ref_object_id": str(policy.get("ref_object_id", "") or "").strip(),
            "teacher_anchor_ref_object_type": str(policy.get("ref_object_type", "") or "").strip(),
        }

    if mode == "specific_item" and str(policy.get("item_id", "") or "").strip():
        return {
            "mode": "specific_item",
            "teacher_anchor": "specific_item",
            "teacher_anchor_item_id": str(policy.get("item_id", "") or "").strip(),
        }

    rows: list[dict[str, Any]] = []
    if mode == "cam_top1":
        rows = _as_list(_as_dict(report.get("attention")).get("top_items"))
    else:
        rows = _as_list(_as_dict(_as_dict(report.get("final_state")).get("state_snapshot")).get("top_items"))

    picked = _pick_anchor_candidate(rows, ref_object_types=[str(x) for x in _as_list(policy.get("ref_object_types")) if str(x)])
    if not picked:
        return {"mode": mode, "teacher_anchor": mode}

    ref_id = _as_str(picked.get("ref_object_id", "")).strip()
    ref_type = _as_str(picked.get("ref_object_type", "")).strip()
    item_id = _as_str(picked.get("item_id", "")).strip()
    if ref_id:
        return {
            "mode": "specific_ref",
            "teacher_anchor": "specific_ref",
            "teacher_anchor_ref_object_id": ref_id,
            "teacher_anchor_ref_object_type": ref_type,
            "teacher_anchor_item_id": item_id,
        }
    if item_id:
        return {
            "mode": "specific_item",
            "teacher_anchor": "specific_item",
            "teacher_anchor_item_id": item_id,
        }
    return {"mode": mode, "teacher_anchor": mode}


@dataclass
class ExpectationContractEngine:
    _pending: list[dict[str, Any]] | None = None
    _contract_seq: int = 0
    _registered_count: int = 0
    _success_count: int = 0
    _failure_count: int = 0
    _synthetic_tick_count: int = 0

    def __post_init__(self) -> None:
        if self._pending is None:
            self._pending = []

    @property
    def pending_count(self) -> int:
        return len(self._pending or [])

    def snapshot(self) -> dict[str, Any]:
        return {
            "registered_count": int(self._registered_count),
            "success_count": int(self._success_count),
            "failure_count": int(self._failure_count),
            "synthetic_tick_count": int(self._synthetic_tick_count),
            "pending_count": int(self.pending_count),
        }

    def _make_contract_id(self, *, spec_id: str, source_tick_index: Any) -> str:
        self._contract_seq += 1
        suffix = spec_id or f"tick_{source_tick_index}"
        return f"exp_contract::{suffix}::{self._contract_seq:04d}"

    def _build_runtime_contract(
        self,
        *,
        spec: dict[str, Any],
        tick: dict[str, Any],
        report: dict[str, Any],
        source_tick_cursor: int,
    ) -> dict[str, Any]:
        contract_id = self._make_contract_id(spec_id=str(spec.get("id", "") or ""), source_tick_index=tick.get("tick_index"))
        anchor = freeze_anchor_from_report(_as_dict(spec.get("anchor_policy")), report=report)
        return {
            "contract_id": contract_id,
            "spec_id": str(spec.get("id", "") or ""),
            "created_source_tick_cursor": int(source_tick_cursor),
            "deadline_source_tick_cursor": int(source_tick_cursor + int(spec.get("within_ticks", 1) or 1)),
            "source_dataset_id": tick.get("dataset_id"),
            "source_dataset_tick_index": tick.get("tick_index"),
            "source_episode_id": tick.get("episode_id"),
            "source_text": _as_str(tick.get("input_text", "")).strip(),
            "source_tags": [str(x).strip() for x in _as_list(tick.get("tags")) if str(x).strip()],
            "anchor_policy": _as_dict(spec.get("anchor_policy")),
            "frozen_anchor": anchor,
            "within_ticks": int(spec.get("within_ticks", 1) or 1),
            "success_conditions": _as_dict(spec.get("success_conditions")),
            "failure_conditions": _as_dict(spec.get("failure_conditions")),
            "on_success": _as_dict(spec.get("on_success")),
            "on_failure": _as_dict(spec.get("on_failure")),
            "emit_feedback_tick": bool(spec.get("emit_feedback_tick", True)),
            "fail_on_run_end": bool(spec.get("fail_on_run_end", True)),
        }

    def _build_feedback_tick(
        self,
        *,
        contract: dict[str, Any],
        outcome: str,
        reason: str,
        matched_detail: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        cfg = _as_dict(contract.get("on_success" if outcome == "success" else "on_failure"))
        emit_tick = bool(cfg.get("emit_feedback_tick", contract.get("emit_feedback_tick", True)))
        text = _as_str(cfg.get("feedback_text", "")).strip()
        extra_labels = _as_dict(cfg.get("labels"))
        teacher_rwd = float(cfg.get("teacher_rwd", 0.0) or 0.0)
        teacher_pun = float(cfg.get("teacher_pun", 0.0) or 0.0)
        if not emit_tick and teacher_rwd <= 0.0 and teacher_pun <= 0.0:
            return None

        labels = dict(extra_labels)
        if teacher_rwd > 0.0:
            labels["teacher_rwd"] = round(float(teacher_rwd), 8)
        if teacher_pun > 0.0:
            labels["teacher_pun"] = round(float(teacher_pun), 8)
        feedback_note = _as_str(cfg.get("feedback_note", "")).strip()
        if feedback_note:
            labels["teacher_note"] = feedback_note
        frozen_anchor = _as_dict(contract.get("frozen_anchor"))
        if labels.get("teacher_anchor") is None and frozen_anchor:
            for key in (
                "teacher_anchor",
                "teacher_anchor_item_id",
                "teacher_anchor_ref_object_id",
                "teacher_anchor_ref_object_type",
            ):
                if key in frozen_anchor and frozen_anchor.get(key) not in {None, ""}:
                    labels[key] = frozen_anchor.get(key)

        tags = list(dict.fromkeys(
            [
                *[str(x).strip() for x in _as_list(contract.get("source_tags")) if str(x).strip()],
                "expectation_contract",
                f"contract_{outcome}",
                *[str(x).strip() for x in _as_list(cfg.get("feedback_tags")) if str(x).strip()],
            ]
        ))

        note_bits = [
            f"contract_id={contract.get('contract_id', '')}",
            f"outcome={outcome}",
            f"reason={reason}",
        ]
        if feedback_note:
            note_bits.append(feedback_note)

        tick: dict[str, Any] = {
            "dataset_id": contract.get("source_dataset_id"),
            "episode_id": contract.get("source_episode_id"),
            "tags": tags,
            "input_text": text,
            "input_is_empty": not bool(text),
            "labels": labels,
            "note": " | ".join([x for x in note_bits if x]),
            "tick_source": "expectation_contract_feedback",
            "synthetic_tick": True,
            "expectation_contract_id": contract.get("contract_id"),
            "expectation_contract_outcome": outcome,
            "expectation_contract_reason": reason,
            "expectation_contract_match_detail": matched_detail,
            "source_dataset_tick_index": contract.get("source_dataset_tick_index"),
        }
        self._synthetic_tick_count += 1
        return tick

    def _settle_contract(
        self,
        *,
        contract: dict[str, Any],
        outcome: str,
        reason: str,
        source_tick_cursor: int | None,
        matched_detail: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if outcome == "success":
            self._success_count += 1
        else:
            self._failure_count += 1
        event = {
            "event": "settled",
            "contract_id": contract.get("contract_id"),
            "spec_id": contract.get("spec_id"),
            "outcome": outcome,
            "reason": reason,
            "created_source_tick_cursor": contract.get("created_source_tick_cursor"),
            "deadline_source_tick_cursor": contract.get("deadline_source_tick_cursor"),
            "settled_source_tick_cursor": source_tick_cursor,
            "source_dataset_tick_index": contract.get("source_dataset_tick_index"),
            "matched_detail": matched_detail,
            "frozen_anchor": _as_dict(contract.get("frozen_anchor")),
        }
        tick = self._build_feedback_tick(contract=contract, outcome=outcome, reason=reason, matched_detail=matched_detail)
        return event, tick

    def on_source_tick(
        self,
        *,
        tick: dict[str, Any],
        report: dict[str, Any],
        metrics: dict[str, Any],
        source_tick_cursor: int,
    ) -> dict[str, Any]:
        synthetic_ticks: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        kept: list[dict[str, Any]] = []

        for contract in list(self._pending or []):
            matched_detail: list[dict[str, Any]] = []
            outcome: str | None = None
            reason = ""

            failure_group = _as_dict(contract.get("failure_conditions"))
            success_group = _as_dict(contract.get("success_conditions"))

            fail_matched, fail_detail = _evaluate_condition_group(failure_group, report=report, metrics=metrics)
            if fail_matched:
                outcome = "failure"
                reason = "failure_condition"
                matched_detail = fail_detail
            else:
                ok_matched, ok_detail = _evaluate_condition_group(success_group, report=report, metrics=metrics)
                if ok_matched:
                    outcome = "success"
                    reason = "success_condition"
                    matched_detail = ok_detail
                elif int(source_tick_cursor) >= int(contract.get("deadline_source_tick_cursor", 0) or 0):
                    outcome = "failure"
                    reason = "timeout"

            if outcome is None:
                kept.append(contract)
                continue

            event, synthetic = self._settle_contract(
                contract=contract,
                outcome=outcome,
                reason=reason,
                source_tick_cursor=source_tick_cursor,
                matched_detail=matched_detail,
            )
            events.append(event)
            if synthetic is not None:
                synthetic_ticks.append(synthetic)

        self._pending = kept

        labels = tick.get("labels") if isinstance(tick.get("labels"), dict) else {}
        specs = normalize_expectation_contracts_from_labels(labels, where="labels")
        for index, spec in enumerate(specs):
            runtime = self._build_runtime_contract(spec=spec, tick=tick, report=report, source_tick_cursor=source_tick_cursor)
            self._pending.append(runtime)
            self._registered_count += 1
            events.append(
                {
                    "event": "registered",
                    "contract_id": runtime.get("contract_id"),
                    "spec_id": runtime.get("spec_id"),
                    "index_in_tick": index,
                    "source_tick_cursor": source_tick_cursor,
                    "source_dataset_tick_index": tick.get("tick_index"),
                    "deadline_source_tick_cursor": runtime.get("deadline_source_tick_cursor"),
                    "frozen_anchor": _as_dict(runtime.get("frozen_anchor")),
                }
            )

        return {"events": events, "synthetic_ticks": synthetic_ticks}

    def settle_on_run_end(self) -> dict[str, Any]:
        synthetic_ticks: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        kept: list[dict[str, Any]] = []
        for contract in list(self._pending or []):
            if not bool(contract.get("fail_on_run_end", True)):
                kept.append(contract)
                continue
            event, synthetic = self._settle_contract(
                contract=contract,
                outcome="failure",
                reason="run_end",
                source_tick_cursor=None,
                matched_detail=[],
            )
            events.append(event)
            if synthetic is not None:
                synthetic_ticks.append(synthetic)
        self._pending = kept
        return {"events": events, "synthetic_ticks": synthetic_ticks}
