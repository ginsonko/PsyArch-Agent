# -*- coding: utf-8 -*-
"""
Module logger for text_sensor.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any


LEVEL_ERROR = "ERROR"
LEVEL_BRIEF = "BRIEF"
LEVEL_DETAIL = "DETAIL"

_MODULE_NAME = "text_sensor"


class ModuleLogger:
    def __init__(
        self,
        log_dir: str = "",
        max_file_bytes: int = 5 * 1024 * 1024,
        enable_stdout_fallback: bool = True,
    ):
        self._max_bytes = int(max_file_bytes) if max_file_bytes else 5 * 1024 * 1024
        self._stdout_fallback = bool(enable_stdout_fallback)

        if not log_dir:
            log_dir = os.path.join(os.path.dirname(__file__), "logs")
        self._base_dir = Path(log_dir)

        self._dirs: dict[str, Path | None] = {}
        for level in ("error", "brief", "detail"):
            target = self._base_dir / level
            try:
                target.mkdir(parents=True, exist_ok=True)
                self._dirs[level] = target
            except OSError:
                self._dirs[level] = None

        self._handles: dict[str, Any] = {}
        self._file_sizes: dict[str, int] = {}
        self._dirty_write_counts: dict[str, int] = {}
        self._last_flush_at: dict[str, float] = {}
        self._active_paths: dict[str, Path] = {}
        self._lock = threading.RLock()

    def error(
        self,
        trace_id: str,
        interface: str,
        code: str,
        message: str,
        detail: dict | None = None,
    ):
        entry = self._build_entry(
            level=LEVEL_ERROR,
            trace_id=trace_id,
            interface=interface,
            code=code,
            message=message,
            detail=detail,
        )
        self._write("error", entry)
        self._write("brief", entry)
        self._write("detail", entry)

    def brief(
        self,
        trace_id: str,
        interface: str,
        success: bool,
        input_summary: dict | None = None,
        output_summary: dict | None = None,
        message: str = "",
    ):
        entry = self._build_entry(
            level=LEVEL_BRIEF,
            trace_id=trace_id,
            interface=interface,
            code="OK" if success else "FAIL",
            message=message,
            detail={
                "success": success,
                "input_summary": input_summary or {},
                "output_summary": output_summary or {},
            },
        )
        self._write("brief", entry)
        self._write("detail", entry)

    def detail(
        self,
        trace_id: str,
        step: str,
        info: dict | None = None,
    ):
        entry = self._build_entry(
            level=LEVEL_DETAIL,
            trace_id=trace_id,
            interface=step,
            code="",
            message="",
            detail=info or {},
        )
        self._write("detail", entry)

    def _build_entry(
        self,
        level: str,
        trace_id: str,
        interface: str,
        code: str,
        message: str,
        detail: dict | None,
    ) -> str:
        record = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_ms": int(time.time() * 1000),
            "module": _MODULE_NAME,
            "level": level,
            "trace_id": trace_id,
            "interface": interface,
            "code": code,
            "message": message,
        }
        if detail:
            record["detail"] = detail
        try:
            return json.dumps(record, ensure_ascii=False)
        except (TypeError, ValueError):
            record["detail"] = str(detail)
            return json.dumps(record, ensure_ascii=False)

    @staticmethod
    def _estimate_line_bytes(line: str) -> int:
        try:
            return len((line + "\n").encode("utf-8"))
        except Exception:
            return len(line) + 1

    def _default_current_path(self, level_key: str, target_dir: Path) -> Path:
        return target_dir / f"{level_key}_current.log"

    def _spill_current_path(self, level_key: str, target_dir: Path) -> Path:
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        return target_dir / f"{level_key}_current_{ts}_{os.getpid()}_{time.time_ns()}.log"

    def _next_path_after_rotation(self, level_key: str, target_dir: Path, current_path: Path) -> Path:
        default_path = self._default_current_path(level_key, target_dir)
        if current_path == default_path:
            return default_path
        return self._spill_current_path(level_key, target_dir)

    def _open_handle_for_path(self, level_key: str, filepath: Path):
        fh = open(filepath, "a", encoding="utf-8")
        self._handles[level_key] = fh
        self._active_paths[level_key] = filepath
        try:
            self._file_sizes[level_key] = int(filepath.stat().st_size)
        except OSError:
            self._file_sizes[level_key] = 0
        self._dirty_write_counts[level_key] = 0
        self._last_flush_at[level_key] = time.monotonic()
        return fh

    def _archive_current_path(self, level_key: str, target_dir: Path, current_path: Path) -> None:
        size = int(self._file_sizes.get(level_key, 0) or 0)
        if size <= 0:
            try:
                size = int(current_path.stat().st_size)
            except OSError:
                size = 0
        if not current_path.exists() or size <= 0:
            return
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        archive_path = target_dir / f"{level_key}_{ts}_{os.getpid()}_{time.time_ns()}.log"
        current_path.rename(archive_path)

    def _flush_if_needed(self, level_key: str, fh, *, force: bool = False):
        now = time.monotonic()
        pending = int(self._dirty_write_counts.get(level_key, 0) or 0)
        threshold = 1 if level_key != "detail" else 32
        interval_sec = 0.0 if level_key != "detail" else 1.5
        last_flush = float(self._last_flush_at.get(level_key, 0.0) or 0.0)
        if (not force) and pending < threshold and (now - last_flush) < interval_sec:
            return
        fh.flush()
        self._dirty_write_counts[level_key] = 0
        self._last_flush_at[level_key] = now

    def _write(self, level_key: str, line: str):
        with self._lock:
            target_dir = self._dirs.get(level_key)
            if target_dir is None:
                if self._stdout_fallback:
                    print(line, file=sys.stderr)
                return

            try:
                fh = self._get_or_open(level_key, target_dir)
                fh.write(line + "\n")
                self._file_sizes[level_key] = int(self._file_sizes.get(level_key, 0) or 0) + self._estimate_line_bytes(line)
                self._dirty_write_counts[level_key] = int(self._dirty_write_counts.get(level_key, 0) or 0) + 1
                if int(self._file_sizes.get(level_key, 0) or 0) >= self._max_bytes:
                    self._rotate(level_key, target_dir)
                else:
                    self._flush_if_needed(level_key, fh)
            except OSError:
                if self._stdout_fallback:
                    print(line, file=sys.stderr)

    def _get_or_open(self, level_key: str, target_dir: Path):
        fh = self._handles.get(level_key)
        if fh is None or fh.closed:
            default_path = self._default_current_path(level_key, target_dir)
            filepath = self._active_paths.get(level_key, default_path)
            if filepath == default_path and filepath.exists():
                try:
                    current_size = int(filepath.stat().st_size)
                except OSError:
                    current_size = 0
                if current_size >= self._max_bytes:
                    try:
                        self._file_sizes[level_key] = current_size
                        self._archive_current_path(level_key, target_dir, filepath)
                    except OSError:
                        filepath = self._spill_current_path(level_key, target_dir)
            fh = self._open_handle_for_path(level_key, filepath)
        return fh

    def _rotate(self, level_key: str, target_dir: Path):
        try:
            old_fh = self._handles.pop(level_key, None)
            if old_fh and not old_fh.closed:
                self._flush_if_needed(level_key, old_fh, force=True)
                old_fh.close()

            current_path = self._active_paths.get(level_key, self._default_current_path(level_key, target_dir))
            self._archive_current_path(level_key, target_dir, current_path)
            self._open_handle_for_path(level_key, self._next_path_after_rotation(level_key, target_dir, current_path))
        except OSError:
            try:
                self._open_handle_for_path(level_key, self._spill_current_path(level_key, target_dir))
            except OSError:
                pass

    def close(self):
        with self._lock:
            for fh in self._handles.values():
                try:
                    if fh and not fh.closed:
                        fh.flush()
                        fh.close()
                except OSError:
                    pass
            self._handles.clear()
            self._file_sizes.clear()
            self._dirty_write_counts.clear()
            self._last_flush_at.clear()
            self._active_paths.clear()

    def update_config(self, log_dir: str = "", max_file_bytes: int = 0):
        with self._lock:
            changed = False
            if max_file_bytes > 0 and max_file_bytes != self._max_bytes:
                self._max_bytes = max_file_bytes
                changed = True

            if log_dir and log_dir != str(self._base_dir):
                self.close()
                self._base_dir = Path(log_dir)
                for level in ("error", "brief", "detail"):
                    d = self._base_dir / level
                    try:
                        d.mkdir(parents=True, exist_ok=True)
                        self._dirs[level] = d
                    except OSError:
                        self._dirs[level] = None  # type: ignore
                changed = True

            return changed
