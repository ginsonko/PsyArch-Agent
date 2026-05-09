# -*- coding: utf-8 -*-
"""
观测台（Observatory）设置页：带注释的配置解析与渲染工具
====================================================

核心目标：
  - 以 YAML 配置文件为“单一事实来源”（Single Source of Truth）
  - 保留字段顺序、分组标题与注释（中文为主，必要时附英文）
  - 保存时不破坏注释与布局：按“注释布局”重建 YAML，而不是直接 dump dict

说明：
  - “注释布局”指配置文件里以 `# ----` 等格式标记的分组与字段说明。
  - 本模块输出会被前端 Settings（设置）面板直接渲染。
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any


try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - fallback handled below
    yaml = None


SECTION_PATTERN = re.compile(r"^#\s*-{2,}\s*(.+?)\s*-{2,}\s*$")
TOP_LEVEL_KEY_PATTERN = re.compile(r"^([A-Za-z0-9_]+):(?:\s*.*)?$")


MODULE_TITLES: dict[str, str] = {
    # Note / 说明：
    # - 尽可能用中文描述；若出现简写（AF/CFS/NT/IESM/HDB），必须有中文全称陪同，方便理解。
    # - Keep Chinese first. If an abbreviation appears, pair it with a Chinese name.
    "observatory": "观测台",
    "text_sensor": "文本感受器",
    "time_sensor": "时间感受器（TS 时间感受器）",
    "state_pool": "状态池",
    "hdb": "全息深度数据库（HDB）",
    "attention": "注意力过滤器（AF 注意力滤波器）",
    "cognitive_feeling": "认知感受系统（CFS 认知感受信号）",
    "emotion": "情绪管理器（EMgr）与递质通道（NT）",
    "innate_script": "先天编码脚本管理器（IESM）",
    "action": "行动管理模块（Drive 驱动力）",
    "energy_balance": "实虚能量平衡控制器（EBC）",
}


def load_yaml_dict(path: str | Path) -> dict[str, Any]:
    path = str(path)
    if yaml is None:
        return _load_simple_yaml_config(path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return data if isinstance(data, dict) else _load_simple_yaml_config(path)
    except Exception:
        return _load_simple_yaml_config(path)


def parse_annotated_layout(path: str | Path) -> dict[str, Any]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, Any]] = []
    prologue: list[str] = []
    pending_comments: list[str] = []
    current_section = ""
    seen_section = False
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        is_top_level_key = bool(
            stripped
            and not line.startswith((" ", "\t"))
            and TOP_LEVEL_KEY_PATTERN.match(line)
        )
        if is_top_level_key:
            key = TOP_LEVEL_KEY_PATTERN.match(line).group(1)  # type: ignore[union-attr]
            value_lines = [line]
            index += 1
            while index < len(lines):
                next_line = lines[index]
                next_stripped = next_line.strip()
                next_is_top_level_key = bool(
                    next_stripped
                    and not next_line.startswith((" ", "\t"))
                    and TOP_LEVEL_KEY_PATTERN.match(next_line)
                )
                if next_is_top_level_key:
                    break
                if next_stripped.startswith("#") and not next_line.startswith((" ", "\t")):
                    break
                value_lines.append(next_line)
                index += 1

            entries.append(
                {
                    "key": key,
                    "leading_comments": list(pending_comments),
                    "value_lines": value_lines,
                    "section_title": current_section,
                }
            )
            pending_comments = []
            continue

        if stripped.startswith("#"):
            section = _extract_section_title(line)
            if section:
                current_section = section
                seen_section = True
            if not seen_section and not entries:
                prologue.append(line)
            else:
                pending_comments.append(line)
            index += 1
            continue

        if not stripped:
            if not seen_section and not entries:
                prologue.append(line)
            else:
                pending_comments.append(line)
            index += 1
            continue

        if not seen_section and not entries:
            prologue.append(line)
        else:
            pending_comments.append(line)
        index += 1

    return {
        "prologue": prologue,
        "entries": entries,
    }


def build_config_view(
    *,
    module_name: str,
    path: str,
    defaults: dict[str, Any],
    file_values: dict[str, Any],
    effective: dict[str, Any],
    runtime_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    layout = parse_annotated_layout(path)
    runtime_override = runtime_override or {}
    section_order: list[str] = []
    sections: dict[str, dict[str, Any]] = {}

    for entry in layout["entries"]:
        key = entry["key"]
        section_title = entry["section_title"] or "未分组 / Ungrouped"
        if section_title not in sections:
            sections[section_title] = {
                "title": section_title,
                "fields": [],
            }
            section_order.append(section_title)
        default_value = copy.deepcopy(defaults.get(key))
        file_value = copy.deepcopy(file_values.get(key, default_value))
        effective_value = copy.deepcopy(effective.get(key, file_value))
        override_value = copy.deepcopy(runtime_override.get(key))
        comment_lines = _clean_comment_lines(entry["leading_comments"])
        sections[section_title]["fields"].append(
            {
                "key": key,
                "type": _infer_value_type(default_value),
                "default_value": default_value,
                "file_value": file_value,
                "effective_value": effective_value,
                "override_value": override_value,
                "has_override": key in runtime_override,
                "hot_reload_supported": True,
                "comment_lines": comment_lines,
                "comment_text": "\n".join(comment_lines).strip(),
            }
        )

    return {
        "module": module_name,
        "title": MODULE_TITLES.get(module_name, module_name),
        "path": path,
        "defaults": copy.deepcopy(defaults),
        "file_values": copy.deepcopy(file_values),
        "runtime_override": copy.deepcopy(runtime_override),
        "effective": copy.deepcopy(effective),
        "sections": [sections[title] for title in section_order],
    }


def save_annotated_config(
    *,
    path: str,
    defaults: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    layout = parse_annotated_layout(path)
    existing = load_yaml_dict(path)
    merged = dict(defaults)
    merged.update(existing)
    merged.update(updates or {})

    keys_in_layout = [entry["key"] for entry in layout["entries"]]
    missing_keys = [key for key in defaults.keys() if key not in keys_in_layout]
    if missing_keys:
        raise ValueError(
            f"配置文件缺少注释布局字段，无法安全保存 / Missing annotated layout keys: {missing_keys}"
        )

    output_lines = list(layout["prologue"])
    if output_lines and output_lines[-1].strip():
        output_lines.append("")

    for index, entry in enumerate(layout["entries"]):
        if entry["leading_comments"]:
            output_lines.extend(entry["leading_comments"])
        output_lines.extend(_dump_yaml_entry(entry["key"], merged.get(entry["key"])))
        if index != len(layout["entries"]) - 1:
            output_lines.append("")

    content = "\n".join(output_lines).rstrip() + "\n"
    Path(path).write_text(content, encoding="utf-8")
    return merged


def coerce_updates_by_defaults(
    defaults: dict[str, Any],
    updates: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    coerced: dict[str, Any] = {}
    rejected: list[dict[str, Any]] = []
    for key, value in (updates or {}).items():
        if key not in defaults:
            rejected.append(
                {
                    "key": key,
                    "reason": "未知配置项 / Unknown config key",
                }
            )
            continue
        try:
            coerced[key] = _coerce_value(value, defaults[key])
        except Exception as exc:
            rejected.append(
                {
                    "key": key,
                    "reason": str(exc),
                }
            )
    return coerced, rejected


def _extract_section_title(line: str) -> str:
    matched = SECTION_PATTERN.match(line.strip())
    return matched.group(1).strip() if matched else ""


def _clean_comment_lines(lines: list[str]) -> list[str]:
    clean: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            if clean and clean[-1] != "":
                clean.append("")
            continue
        if not stripped.startswith("#"):
            continue
        if SECTION_PATTERN.match(stripped):
            continue
        content = stripped[1:].strip()
        if not content:
            if clean and clean[-1] != "":
                clean.append("")
            continue
        if set(content) <= {"=", "-", " "}:
            continue
        clean.append(content)
    while clean and clean[-1] == "":
        clean.pop()
    return clean


def _infer_value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if value is None:
        return "null"
    return "str"


def _coerce_value(value: Any, default: Any) -> Any:
    expected_type = _infer_value_type(default)
    if expected_type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        raise ValueError("布尔值无效 / Invalid boolean value")
    if expected_type == "int":
        if isinstance(value, bool):
            raise ValueError("整数值无效 / Invalid integer value")
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            return int(value.strip())
        raise ValueError("整数值无效 / Invalid integer value")
    if expected_type == "float":
        if isinstance(value, bool):
            raise ValueError("浮点值无效 / Invalid float value")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(value.strip())
        raise ValueError("浮点值无效 / Invalid float value")
    if expected_type == "list":
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if yaml is not None:
                parsed = yaml.safe_load(text)
                if isinstance(parsed, list):
                    return parsed
            raise ValueError("列表值无效，请使用 JSON/YAML 数组格式 / Invalid list value")
        raise ValueError("列表值无效 / Invalid list value")
    if expected_type == "dict":
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            if yaml is not None:
                parsed = yaml.safe_load(text)
                if isinstance(parsed, dict):
                    return parsed
            raise ValueError("字典值无效，请使用 JSON/YAML 对象格式 / Invalid dict value")
        raise ValueError("字典值无效 / Invalid dict value")
    if value is None:
        return ""
    return str(value)


def _dump_yaml_entry(key: str, value: Any) -> list[str]:
    payload = {key: value}
    if yaml is not None:
        text = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        ).strip()
        return text.splitlines()
    return _dump_simple_yaml(payload).strip().splitlines()


def _parse_simple_yaml_scalar(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"\"", "'"}:
        return text[1:-1]
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None
    try:
        if any(marker in text for marker in (".", "e", "E")):
            return float(text)
        return int(text)
    except ValueError:
        return text


def _load_simple_yaml_config(path: str) -> dict[str, Any]:
    if not Path(path).exists():
        return {}
    data: dict[str, Any] = {}
    current_key: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current_key, buffer
        if not current_key:
            return
        raw = "\n".join(buffer).strip()
        if not raw:
            data[current_key] = None
        else:
            data[current_key] = _parse_simple_yaml_scalar(raw)
        current_key = None
        buffer = []

    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line.startswith((" ", "\t")) and ":" in raw_line:
            flush()
            key, raw_value = raw_line.split(":", 1)
            current_key = key.strip()
            value_text = raw_value.split("#", 1)[0].strip()
            if value_text:
                buffer = [value_text]
            else:
                buffer = []
            continue
        if current_key:
            buffer.append(raw_line)
    flush()
    return data


def _serialize_simple_yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f"\"{escaped}\""


def _dump_simple_yaml(data: dict[str, Any], indent: int = 0) -> str:
    lines: list[str] = []
    prefix = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            if value:
                lines.append(_dump_simple_yaml(value, indent + 2))
            else:
                lines.append(f"{prefix}  {{}}")
        elif isinstance(value, list):
            if not value:
                lines.append(f"{prefix}{key}: []")
                continue
            lines.append(f"{prefix}{key}:")
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"{prefix}  -")
                    lines.append(_dump_simple_yaml(item, indent + 4))
                else:
                    lines.append(f"{prefix}  - {_serialize_simple_yaml_scalar(item)}")
        else:
            lines.append(f"{prefix}{key}: {_serialize_simple_yaml_scalar(value)}")
    return "\n".join(lines)
