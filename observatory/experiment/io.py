# -*- coding: utf-8 -*-
"""
Experiment IO Helpers
=====================

This module contains small helpers for:
- loading YAML datasets (episode template protocol)
- reading/writing JSONL streams (expanded ticks, metrics)

Keep it dependency-light and auditable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


class ExperimentIOError(RuntimeError):
    pass


def sha256_text(text: str) -> str:
    h = hashlib.sha256()
    h.update(text.encode("utf-8", errors="strict"))
    return h.hexdigest()


def sha256_file(path: str | Path) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_yaml_text(text: str) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise ExperimentIOError("Missing dependency: PyYAML (pip install PyYAML)") from exc
    try:
        data = yaml.safe_load(text)
    except Exception as exc:
        raise ExperimentIOError("Failed to parse YAML text.") from exc
    if not isinstance(data, dict):
        raise ExperimentIOError("Dataset YAML root must be a mapping (dict).")
    return data


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as exc:
        raise ExperimentIOError(f"Failed to read YAML file: {p}") from exc
    return load_yaml_text(text)


def dump_yaml(data: dict[str, Any]) -> str:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise ExperimentIOError("Missing dependency: PyYAML (pip install PyYAML)") from exc
    try:
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    except Exception as exc:
        raise ExperimentIOError("Failed to dump YAML.") from exc


def iter_jsonl(path: str | Path) -> Iterable[dict[str, Any]]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            s = raw.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception as exc:
                raise ExperimentIOError(f"Invalid JSONL at line {line_no}: {p}") from exc
            if not isinstance(obj, dict):
                raise ExperimentIOError(f"JSONL item must be an object(dict) at line {line_no}: {p}")
            yield obj


def write_jsonl(path: str | Path, items: Iterable[dict[str, Any]]) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("w", encoding="utf-8") as f:
        for obj in items:
            f.write(json.dumps(obj, ensure_ascii=False))
            f.write("\n")
            n += 1
    return n

