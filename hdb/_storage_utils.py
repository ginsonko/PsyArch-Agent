# -*- coding: utf-8 -*-
"""
Filesystem helpers for the HDB prototype.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_ORJSON_MODULE: Any | None = None
_ORJSON_IMPORT_ATTEMPTED = False


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def load_json_file(path: str | Path, default: Any = None) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    try:
        with open(target, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json_file(path: str | Path, payload: Any) -> int:
    target = Path(path)
    ensure_dir(target.parent)
    tmp_path = target.with_suffix(target.suffix + f".{os.getpid()}.{time.time_ns()}.tmp")
    pretty = str(os.environ.get("AP_HDB_PRETTY_JSON", "") or "").strip().lower() in {"1", "true", "yes", "on"}
    used_orjson = False
    try:
        global _ORJSON_MODULE, _ORJSON_IMPORT_ATTEMPTED
        if not _ORJSON_IMPORT_ATTEMPTED:
            try:
                import orjson  # type: ignore

                _ORJSON_MODULE = orjson
            except Exception:
                _ORJSON_MODULE = None
            _ORJSON_IMPORT_ATTEMPTED = True
        if _ORJSON_MODULE is None:
            raise RuntimeError("orjson unavailable")
        option = 0
        if pretty:
            option = _ORJSON_MODULE.OPT_INDENT_2 | _ORJSON_MODULE.OPT_SORT_KEYS
        data = _ORJSON_MODULE.dumps(payload, option=option)
        with open(tmp_path, "wb") as fh:
            fh.write(data)
        written_bytes = len(data)
        used_orjson = True
    except Exception:
        # Keep a safe fallback path if orjson is missing or payload contains
        # non-serializable types.
        with open(tmp_path, "w", encoding="utf-8") as fh:
            if pretty:
                json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            else:
                json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        try:
            written_bytes = int(tmp_path.stat().st_size)
        except Exception:
            written_bytes = 0

    # Windows may transiently lock files (e.g., antivirus / log tailers).
    # Retry a few times before giving up.
    for attempt in range(6):
        try:
            os.replace(tmp_path, target)
            return int(written_bytes)
        except PermissionError:
            if attempt >= 5:
                raise
            time.sleep(0.005 * (attempt + 1))
        except OSError:
            # If the target dir is on a slow filesystem, os.replace can
            # sporadically fail. Retrying keeps the behaviour robust.
            if attempt >= 5:
                raise
            time.sleep(0.005 * (attempt + 1))

    # Defensive: should not reach here, but keep the behaviour explicit.
    if not used_orjson:
        os.replace(tmp_path, target)
    return int(written_bytes)


def dumps_json_bytes(payload: Any) -> bytes:
    global _ORJSON_MODULE, _ORJSON_IMPORT_ATTEMPTED
    try:
        if not _ORJSON_IMPORT_ATTEMPTED:
            try:
                import orjson  # type: ignore

                _ORJSON_MODULE = orjson
            except Exception:
                _ORJSON_MODULE = None
            _ORJSON_IMPORT_ATTEMPTED = True
        if _ORJSON_MODULE is None:
            raise RuntimeError("orjson unavailable")
        return _ORJSON_MODULE.dumps(payload)
    except Exception:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def loads_json_bytes(data: bytes | bytearray | memoryview | str | None, default: Any = None) -> Any:
    if data is None:
        return default
    try:
        global _ORJSON_MODULE, _ORJSON_IMPORT_ATTEMPTED
        if not _ORJSON_IMPORT_ATTEMPTED:
            try:
                import orjson  # type: ignore

                _ORJSON_MODULE = orjson
            except Exception:
                _ORJSON_MODULE = None
            _ORJSON_IMPORT_ATTEMPTED = True
        raw = data.tobytes() if isinstance(data, memoryview) else data
        if _ORJSON_MODULE is not None:
            return _ORJSON_MODULE.loads(raw)
        if isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw).decode("utf-8")
        return json.loads(raw)
    except Exception:
        return default


def list_json_files(path: str | Path) -> list[Path]:
    target = Path(path)
    if not target.exists():
        return []
    return sorted(p for p in target.glob("*.json") if p.is_file())


def remove_file(path: str | Path) -> bool:
    target = Path(path)
    if not target.exists():
        return False
    try:
        target.unlink()
        return True
    except OSError:
        return False
