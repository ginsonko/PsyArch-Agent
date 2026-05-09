# -*- coding: utf-8 -*-
"""
AP 状态池模块 — 模块专属日志管理器
====================================
增强版三层日志器，基于 text_sensor 日志器模式，扩展以下能力：
  1. 日志字段含 message_zh / message_en 分离（设计文档 13.3 节）
  2. 日志字段含 tick_id（状态池核心标识）
  3. error 事件同时写入 error + brief + detail 三层
  4. 日志不可用时降级到 stdout，绝不阻塞主流程
  5. 按文件大小自动轮转
"""

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

# ----- 日志级别常量 -----
LEVEL_ERROR = "ERROR"
LEVEL_BRIEF = "BRIEF"
LEVEL_DETAIL = "DETAIL"

_MODULE_NAME = "state_pool"


class ModuleLogger:
    """
    状态池模块专属日志器。

    增强点（相对于 text_sensor 版本）：
      - 每条日志含 message_zh + message_en 双语字段
      - 支持 tick_id 字段
      - detail 日志支持高粒度状态变化记录
    """

    def __init__(
        self,
        log_dir: str = "",
        max_file_bytes: int = 5 * 1024 * 1024,
        archive_keep_per_level: int | dict[str, int] | None = None,
        enable_stdout_fallback: bool = True,
    ):
        self._max_bytes = max_file_bytes
        self._archive_keep_per_level = self._normalize_archive_keep_per_level(archive_keep_per_level)
        self._stdout_fallback = enable_stdout_fallback

        if not log_dir:
            log_dir = os.path.join(os.path.dirname(__file__), "logs")
        self._base_dir = Path(log_dir)

        self._dirs: dict[str, Path | None] = {}
        for level in ("error", "brief", "detail"):
            d = self._base_dir / level
            try:
                d.mkdir(parents=True, exist_ok=True)
                self._dirs[level] = d
            except OSError:
                self._dirs[level] = None

        self._handles: dict[str, Any] = {}
        self._file_sizes: dict[str, int] = {}
        self._dirty_write_counts: dict[str, int] = {}
        self._last_flush_at: dict[str, float] = {}
        self._active_paths: dict[str, Path] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    #                         公共写入方法                                 #
    # ------------------------------------------------------------------ #

    def error(
        self,
        trace_id: str,
        interface: str,
        code: str,
        message_zh: str,
        message_en: str,
        tick_id: str = "",
        detail: dict | None = None,
    ):
        """
        写入错误日志。错误事件同时记录到 error + brief + detail 三层。
        """
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
    ):
        """
        写入精简运行日志。普通调用记录到 brief + detail 两层。
        """
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
    ):
        """
        写入详细运行日志。仅写 detail 层。
        """
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

    # ------------------------------------------------------------------ #
    #                         内部实现                                     #
    # ------------------------------------------------------------------ #

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
        """构建一条结构化日志行（JSON 单行格式）。"""
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
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        return target_dir / f"{level_key}_current_{ts}_{os.getpid()}_{time.time_ns()}.log"

    def _next_path_after_rotation(self, level_key: str, target_dir: Path, current_path: Path) -> Path:
        default_path = self._default_current_path(level_key, target_dir)
        if current_path == default_path:
            return default_path
        return self._spill_current_path(level_key, target_dir)

    @staticmethod
    def _normalize_archive_keep_per_level(
        archive_keep_per_level: int | dict[str, int] | None,
    ) -> dict[str, int]:
        normalized = {"error": 0, "brief": 0, "detail": 0}
        if isinstance(archive_keep_per_level, int):
            keep = max(0, int(archive_keep_per_level))
            return {level: keep for level in normalized}
        if not isinstance(archive_keep_per_level, dict):
            return normalized
        for level in normalized:
            value = archive_keep_per_level.get(level, 0)
            try:
                normalized[level] = max(0, int(value))
            except (TypeError, ValueError):
                normalized[level] = 0
        return normalized

    def _prune_archived_logs(self, level_key: str, target_dir: Path) -> None:
        keep = int(self._archive_keep_per_level.get(level_key, 0) or 0)
        if keep <= 0:
            return
        default_current_path = self._default_current_path(level_key, target_dir)
        active_path = self._active_paths.get(level_key)
        candidates: list[Path] = []
        for path in target_dir.glob(f"{level_key}*.log"):
            if path == default_current_path or path == active_path:
                continue
            if not path.is_file():
                continue
            candidates.append(path)
        if len(candidates) <= keep:
            return
        candidates.sort(
            key=lambda p: (
                p.stat().st_mtime if p.exists() else 0.0,
                p.name,
            ),
            reverse=True,
        )
        for path in candidates[keep:]:
            try:
                path.unlink()
            except OSError:
                continue

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
        self._prune_archived_logs(level_key, filepath.parent)
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
        """向对应级别的日志文件追加一行。"""
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
        """获取或延迟打开日志文件句柄。"""
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
        """日志轮转：关闭当前文件，重命名为带时间戳归档名。"""
        try:
            old_fh = self._handles.pop(level_key, None)
            if old_fh and not old_fh.closed:
                self._flush_if_needed(level_key, old_fh, force=True)
                old_fh.close()
            current_path = self._active_paths.get(level_key, self._default_current_path(level_key, target_dir))
            self._archive_current_path(level_key, target_dir, current_path)
            self._open_handle_for_path(level_key, self._next_path_after_rotation(level_key, target_dir, current_path))
        except OSError:
            # Do not spam stderr on transient rotation failures.
            # Fall back to a unique spill current file so oversized/locked current logs
            # do not trigger a rotation attempt on every subsequent write.
            try:
                self._open_handle_for_path(level_key, self._spill_current_path(level_key, target_dir))
            except OSError:
                pass

    def close(self):
        """关闭所有打开的日志文件句柄。"""
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

    def update_config(
        self,
        log_dir: str = "",
        max_file_bytes: int = 0,
        archive_keep_per_level: int | dict[str, int] | None = None,
        enable_stdout_fallback: bool | None = None,
    ):
        """热加载时更新日志配置。"""
        with self._lock:
            changed = False
            if max_file_bytes > 0 and max_file_bytes != self._max_bytes:
                self._max_bytes = max_file_bytes
                changed = True
            if archive_keep_per_level is not None:
                normalized_keep = self._normalize_archive_keep_per_level(archive_keep_per_level)
                if normalized_keep != self._archive_keep_per_level:
                    self._archive_keep_per_level = normalized_keep
                    changed = True
            if enable_stdout_fallback is not None and bool(enable_stdout_fallback) != self._stdout_fallback:
                self._stdout_fallback = bool(enable_stdout_fallback)
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
                        self._dirs[level] = None
                changed = True
            for level, target_dir in self._dirs.items():
                if target_dir is None:
                    continue
                self._prune_archived_logs(level, target_dir)
            return changed
