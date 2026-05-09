# -*- coding: utf-8 -*-
"""
Module logger for HDB.
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

_MODULE_NAME = "hdb"


class ModuleLogger:
    def __init__(
        self,
        log_dir: str = "",
        max_file_bytes: int = 5 * 1024 * 1024,
        enable_stdout_fallback: bool = True,
    ):
        self._max_bytes = max_file_bytes
        self._stdout_fallback = enable_stdout_fallback

        if not log_dir:
            log_dir = os.path.join(os.path.dirname(__file__), "logs")
        self._base_dir = Path(log_dir)
        self._dirs: dict[str, Path | None] = {}
        self._handles: dict[str, Any] = {}
        self._file_sizes: dict[str, int] = {}
        self._dirty_write_counts: dict[str, int] = {}
        self._last_flush_at: dict[str, float] = {}
        self._active_paths: dict[str, Path] = {}
        self._lock = threading.RLock()

        for level in ("error", "brief", "detail"):
            directory = self._base_dir / level
            try:
                directory.mkdir(parents=True, exist_ok=True)
                self._dirs[level] = directory
            except OSError:
                self._dirs[level] = None

    def error(
        self,
        trace_id: str,
        interface: str,
        code: str,
        message_zh: str,
        message_en: str,
        tick_id: str = "",
        detail: dict | None = None,
    ) -> None:
        entry = self._build_entry(
            level=LEVEL_ERROR,
            trace_id=trace_id,
            tick_id=tick_id,
            interface=interface,
            code=code,
            message_zh=message_zh,
            message_en=message_en,
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
        message_zh: str = "",
        message_en: str = "",
        tick_id: str = "",
        input_summary: dict | None = None,
        output_summary: dict | None = None,
    ) -> None:
        entry = self._build_entry(
            level=LEVEL_BRIEF,
            trace_id=trace_id,
            tick_id=tick_id,
            interface=interface,
            code="OK" if success else "FAIL",
            message_zh=message_zh,
            message_en=message_en,
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
        tick_id: str = "",
        message_zh: str = "",
        message_en: str = "",
    ) -> None:
        entry = self._build_entry(
            level=LEVEL_DETAIL,
            trace_id=trace_id,
            tick_id=tick_id,
            interface=step,
            code="",
            message_zh=message_zh,
            message_en=message_en,
            detail=info or {},
        )
        self._write("detail", entry)

    def update_config(self, log_dir: str = "", max_file_bytes: int = 0) -> bool:
        with self._lock:
            changed = False
            if max_file_bytes > 0 and max_file_bytes != self._max_bytes:
                self._max_bytes = max_file_bytes
                changed = True
            if log_dir and log_dir != str(self._base_dir):
                self.close()
                self._base_dir = Path(log_dir)
                for level in ("error", "brief", "detail"):
                    directory = self._base_dir / level
                    try:
                        directory.mkdir(parents=True, exist_ok=True)
                        self._dirs[level] = directory
                    except OSError:
                        self._dirs[level] = None
                changed = True
            return changed

    def close(self) -> None:
        with self._lock:
            for handle in self._handles.values():
                try:
                    if handle and not handle.closed:
                        handle.flush()
                        handle.close()
                except OSError:
                    pass
            self._handles.clear()
            self._file_sizes.clear()
            self._dirty_write_counts.clear()
            self._last_flush_at.clear()
            self._active_paths.clear()

    def _build_entry(
        self,
        level: str,
        trace_id: str,
        tick_id: str,
        interface: str,
        code: str,
        message_zh: str,
        message_en: str,
        detail: dict | None,
    ) -> str:
        record = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_ms": int(time.time() * 1000),
            "module": _MODULE_NAME,
            "level": level,
            "trace_id": trace_id,
            "tick_id": tick_id,
            "interface": interface,
            "code": code,
            "message_zh": message_zh,
            "message_en": message_en,
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
        suffix = time.strftime("%Y-%m-%d_%H-%M-%S")
        return target_dir / f"{level_key}_current_{suffix}_{os.getpid()}_{time.time_ns()}.log"

    def _next_path_after_rotation(self, level_key: str, target_dir: Path, current_path: Path) -> Path:
        default_path = self._default_current_path(level_key, target_dir)
        if current_path == default_path:
            return default_path
        return self._spill_current_path(level_key, target_dir)

    def _open_handle_for_path(self, level_key: str, filepath: Path):
        handle = open(filepath, "a", encoding="utf-8")
        self._handles[level_key] = handle
        self._active_paths[level_key] = filepath
        try:
            self._file_sizes[level_key] = int(filepath.stat().st_size)
        except OSError:
            self._file_sizes[level_key] = 0
        self._dirty_write_counts[level_key] = 0
        self._last_flush_at[level_key] = time.monotonic()
        return handle

    def _archive_current_path(self, level_key: str, target_dir: Path, current_path: Path) -> None:
        size = int(self._file_sizes.get(level_key, 0) or 0)
        if size <= 0:
            try:
                size = int(current_path.stat().st_size)
            except OSError:
                size = 0
        if not current_path.exists() or size <= 0:
            return
        suffix = time.strftime("%Y-%m-%d_%H-%M-%S")
        archive_path = target_dir / f"{level_key}_{suffix}_{os.getpid()}_{time.time_ns()}.log"
        current_path.rename(archive_path)

    def _flush_if_needed(self, level_key: str, handle, *, force: bool = False) -> None:
        now = time.monotonic()
        pending = int(self._dirty_write_counts.get(level_key, 0) or 0)
        threshold = 1 if level_key != "detail" else 32
        interval_sec = 0.0 if level_key != "detail" else 1.5
        last_flush = float(self._last_flush_at.get(level_key, 0.0) or 0.0)
        if (not force) and pending < threshold and (now - last_flush) < interval_sec:
            return
        handle.flush()
        self._dirty_write_counts[level_key] = 0
        self._last_flush_at[level_key] = now

    def _write(self, level_key: str, line: str) -> None:
        with self._lock:
            target_dir = self._dirs.get(level_key)
            if target_dir is None:
                if self._stdout_fallback:
                    print(line, file=sys.stderr)
                return
            try:
                handle = self._get_or_open(level_key, target_dir)
                handle.write(line + "\n")
                self._file_sizes[level_key] = int(self._file_sizes.get(level_key, 0) or 0) + self._estimate_line_bytes(line)
                self._dirty_write_counts[level_key] = int(self._dirty_write_counts.get(level_key, 0) or 0) + 1
                if int(self._file_sizes.get(level_key, 0) or 0) >= self._max_bytes:
                    self._rotate(level_key, target_dir)
                else:
                    self._flush_if_needed(level_key, handle)
            except OSError:
                if self._stdout_fallback:
                    print(line, file=sys.stderr)

    def _get_or_open(self, level_key: str, target_dir: Path):
        handle = self._handles.get(level_key)
        if handle is None or handle.closed:
            default_path = self._default_current_path(level_key, target_dir)
            path = self._active_paths.get(level_key, default_path)
            if path == default_path and path.exists():
                try:
                    current_size = int(path.stat().st_size)
                except OSError:
                    current_size = 0
                if current_size >= self._max_bytes:
                    try:
                        self._file_sizes[level_key] = current_size
                        self._archive_current_path(level_key, target_dir, path)
                    except OSError:
                        path = self._spill_current_path(level_key, target_dir)
            handle = self._open_handle_for_path(level_key, path)
        return handle

    def _rotate(self, level_key: str, target_dir: Path) -> None:
        try:
            current = self._handles.pop(level_key, None)
            if current and not current.closed:
                self._flush_if_needed(level_key, current, force=True)
                current.close()
            current_path = self._active_paths.get(level_key, self._default_current_path(level_key, target_dir))
            self._archive_current_path(level_key, target_dir, current_path)
            self._open_handle_for_path(level_key, self._next_path_after_rotation(level_key, target_dir, current_path))
        except OSError:
            # Avoid reusing a locked oversized current file and failing on every write.
            try:
                self._open_handle_for_path(level_key, self._spill_current_path(level_key, target_dir))
            except OSError:
                pass
