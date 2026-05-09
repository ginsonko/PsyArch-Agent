from __future__ import annotations

import copy
import re
import time
from pathlib import Path
import sys
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from innate_script._rules_engine import normalize_rules_doc, render_rules_file

RULES_PATH = REPO_ROOT / "innate_script" / "config" / "innate_rules.yaml"
RUNTIME_TEMPLATE_PATH = REPO_ROOT / "observatory" / "outputs" / "auto_tuner" / "overrides" / "innate_rules.persisted.yaml"


_COMMENT_SWALLOWED_KEY_RE = re.compile(r"^(\s*#.*?)(\s{2,})([A-Za-z_][A-Za-z0-9_\-]*\s*:)")
_PRESSURE_RULE_IDS = {
    "cfs_pressure_from_punish_pred",
    "cfs_pressure_from_teacher_punish_runtime_state_fallback",
    "cfs_pressure_from_runtime_punish_pred_fallback",
}
_MANUAL_TITLES = {
    "cfs_expectation_from_teacher_reward_runtime_state_fallback": "CFS脚本：教师奖励态回落到运行态对象时 -> 期待（渐变验证/不验）",
    "cfs_pressure_from_teacher_punish_runtime_state_fallback": "CFS脚本：教师惩罚态回落到运行态对象时 -> 压力（渐变验证/不验）",
    "cfs_pressure_from_runtime_punish_pred_fallback": "CFS脚本：运行态惩罚预测回落路径 -> 压力（渐变验证/不验）",
    "cfs_simplicity_from_low_complexity": "CFS脚本：低复杂度 -> 简（simplicity）",
    "cfs_relief_from_cp_abs_drop": "CFS脚本：认知压显著回落 -> 释然（relief）",
    "cfs_reassurance_from_settled_relief": "CFS脚本：释然稳定且把握较高 -> 安心（reassurance）",
    "nt_update_from_dissonance": "NT脚本：违和感 -> 递质调制",
    "nt_update_from_correct_event": "NT脚本：正确事件 -> 递质调制",
    "nt_update_from_surprise": "NT脚本：惊 -> 递质调制",
    "nt_update_from_expectation": "NT脚本：期待 -> 递质调制",
    "nt_update_from_pressure": "NT脚本：压力 -> 递质调制",
    "nt_update_from_expectation_verified": "NT脚本：期待验证 -> 递质调制",
    "nt_update_from_expectation_unverified": "NT脚本：期待不验 -> 递质调制",
    "nt_update_from_pressure_verified": "NT脚本：压力验证 -> 递质调制",
    "nt_update_from_pressure_unverified": "NT脚本：压力不验 -> 递质调制",
    "nt_update_from_complexity": "NT脚本：繁/复杂度 -> 递质调制",
    "nt_update_from_repetition": "NT脚本：重复感 -> 递质调制",
    "nt_update_from_grasp": "NT脚本：把握感 -> 递质调制",
    "nt_update_from_simplicity": "NT脚本：简 -> 递质调制",
    "nt_update_from_relief": "NT脚本：释然 -> 递质调制",
    "nt_update_from_reassurance": "NT脚本：安心 -> 递质调制",
    "nt_update_from_reward_state": "NT脚本：奖励信号状态 -> 递质调制",
    "nt_update_from_punish_state": "NT脚本：惩罚信号状态 -> 递质调制",
}


def _salvage_yaml_text(text: str) -> str:
    lines = text.splitlines()
    repaired: list[str] = []
    for line in lines:
        match = _COMMENT_SWALLOWED_KEY_RE.match(line)
        if match:
            repaired.append(match.group(1).rstrip())
            indent = " " * (len(line) - len(line.lstrip(" ")))
            repaired.append(indent + line[match.start(3) :].lstrip())
            continue
        repaired.append(line)

    fixed_quotes: list[str] = []
    for line in repaired:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped.count("'") % 2 == 1:
            fixed_quotes.append(line + "'")
        else:
            fixed_quotes.append(line)
    return "\n".join(fixed_quotes)


def _load_yaml_doc(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _extract_clean_titles(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        doc = _load_yaml_doc(path)
    except Exception:
        return {}
    titles: dict[str, str] = {}
    for rule in doc.get("rules", []) or []:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id", "") or "").strip()
        title = str(rule.get("title", "") or "").strip()
        if rid and title:
            titles[rid] = title
    return titles


def _clean_branch_action_ev(rule: dict[str, Any]) -> None:
    for action in rule.get("then", []) or []:
        if not isinstance(action, dict):
            continue
        branch = action.get("branch")
        if not isinstance(branch, dict):
            continue
        for bucket in ("then", "else"):
            actions = branch.get(bucket, []) or []
            for sub in actions:
                if not isinstance(sub, dict) or "cfs_emit" not in sub:
                    continue
                extra_ev = sub.pop("ev", None)
                bind_attribute = sub.get("cfs_emit", {}).get("bind_attribute")
                if isinstance(bind_attribute, dict) and "ev" not in bind_attribute:
                    bind_attribute["ev"] = 0.0 if extra_ev is None else extra_ev


def _fix_expectation_rule(rule: dict[str, Any]) -> None:
    actions = rule.get("then", []) or []
    if not actions:
        return
    first = actions[0]
    if not isinstance(first, dict) or "cfs_emit" not in first:
        return
    cfs_emit = first.get("cfs_emit")
    if not isinstance(cfs_emit, dict):
        return
    if "when" not in cfs_emit or "then" not in cfs_emit or "else" not in cfs_emit:
        return

    branch = {
        "branch": {
            "when": copy.deepcopy(cfs_emit.pop("when", {})),
            "then": copy.deepcopy(cfs_emit.pop("then", [])),
            "else": copy.deepcopy(cfs_emit.pop("else", [])),
            "on_error": copy.deepcopy(cfs_emit.pop("on_error", [])),
            "note": "",
        }
    }

    for bucket in ("then", "else"):
        sub_actions = branch["branch"].get(bucket, []) or []
        for sub in sub_actions:
            if not isinstance(sub, dict) or "cfs_emit" not in sub:
                continue
            bind_attribute = sub.get("cfs_emit", {}).get("bind_attribute")
            if isinstance(bind_attribute, dict) and "ev" not in bind_attribute:
                bind_attribute["ev"] = 0.0

    if len(actions) == 1:
        actions.append(branch)
    else:
        actions[1] = branch
    rule["then"] = actions


def _repair_doc(doc: dict[str, Any]) -> dict[str, Any]:
    clean_titles = _extract_clean_titles(RUNTIME_TEMPLATE_PATH)
    rules = doc.get("rules", []) or []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id", "") or "").strip()
        if not rid:
            continue
        if rid in clean_titles:
            rule["title"] = clean_titles[rid]
        elif rid in _MANUAL_TITLES:
            rule["title"] = _MANUAL_TITLES[rid]

        if rid == "cfs_expectation_from_reward_pred":
            _fix_expectation_rule(rule)
        if rid in _PRESSURE_RULE_IDS:
            _clean_branch_action_ev(rule)
    return doc


def main() -> int:
    raw_text = RULES_PATH.read_text(encoding="utf-8")
    salvaged_text = _salvage_yaml_text(raw_text)
    raw_doc = yaml.safe_load(salvaged_text)
    if not isinstance(raw_doc, dict):
        raise RuntimeError("salvaged innate rules is not a dict")

    repaired_doc = _repair_doc(raw_doc)
    normalized_doc, errors, _warnings = normalize_rules_doc(repaired_doc)
    if errors:
        raise RuntimeError(f"normalized repaired doc still has errors: {errors[:8]}")

    backup_path = RULES_PATH.with_name(f"{RULES_PATH.name}.repair_backup_{time.strftime('%Y%m%d_%H%M%S')}")
    backup_path.write_text(raw_text, encoding="utf-8")
    RULES_PATH.write_text(render_rules_file(normalized_doc), encoding="utf-8")
    print(f"repaired {RULES_PATH}")
    print(f"backup {backup_path}")
    print(f"rules={len(normalized_doc.get('rules', []) or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
