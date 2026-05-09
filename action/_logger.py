# -*- coding: utf-8 -*-
"""
AP 行动模块 — 模块专属日志管理器
================================
实现 error / brief / detail 三层日志，每层独立文件、按大小轮转。

设计原则：
  - 日志不可用时降级到 stdout/stderr，绝不让日志问题阻塞主流程
  - 每条日志必含 trace_id、模块名、时间戳
  - 文件大小达到阈值自动轮转
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


LEVEL_ERROR = "ERROR"
LEVEL_BRIEF = "BRIEF"
LEVEL_DETAIL = "DETAIL"

_MODULE_NAME = "action"


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

    def error(
        self,
        *,
        trace_id: str,
        interface: str,
        code: str,
        message: str,
        tick_id: str | None = None,
        detail: dict | None = None,
    ) -> None:
        entry = self._build_entry(
            level=LEVEL_ERROR,
            trace_id=trace_id,
            tick_id=tick_id or "",
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
        *,
        trace_id: str,
        interface: str,
        success: bool,
        tick_id: str | None = None,
        input_summary: dict | None = None,
        output_summary: dict | None = None,
        message: str = "",
    ) -> None:
        entry = self._build_entry(
            level=LEVEL_BRIEF,
            trace_id=trace_id,
            tick_id=tick_id or "",
            interface=interface,
            code="OK" if success else "FAIL",
            message=message,
            detail={
                "success": bool(success),
                "input_summary": input_summary or {},
                "output_summary": output_summary or {},
            },
        )
        self._write("brief", entry)
        self._write("detail", entry)

    def detail(
        self,
        *,
        trace_id: str,
        step: str,
        tick_id: str | None = None,
        info: dict | None = None,
    ) -> None:
        entry = self._build_entry(
            level=LEVEL_DETAIL,
            trace_id=trace_id,
            tick_id=tick_id or "",
            interface=step,
            code="",
            message="",
            detail=info or {},
        )
        self._write("detail", entry)

    def update_config(self, *, log_dir: str = "", max_file_bytes: int = 0) -> bool:
        changed = False
        if max_file_bytes and int(max_file_bytes) > 0 and int(max_file_bytes) != self._max_bytes:
            self._max_bytes = int(max_file_bytes)
            changed = True

        if log_dir and str(log_dir) != str(self._base_dir):
            self.close()
            self._base_dir = Path(str(log_dir))
            for level in ("error", "brief", "detail"):
                target = self._base_dir / level
                try:
                    target.mkdir(parents=True, exist_ok=True)
                    self._dirs[level] = target
                except OSError:
                    self._dirs[level] = None
            changed = True

        return changed

    def close(self) -> None:
        for fh in self._handles.values():
            try:
                if fh and not fh.closed:
                    fh.close()
            except OSError:
                pass
        self._handles.clear()

    def _build_entry(
        self,
        *,
        level: str,
        trace_id: str,
        tick_id: str,
        interface: str,
        code: str,
        message: str,
        detail: dict | None,
    ) -> str:
        record: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_ms": int(time.time() * 1000),
            "module": _MODULE_NAME,
            "level": level,
            "trace_id": trace_id,
            "tick_id": tick_id,
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

    def _write(self, level_key: str, line: str) -> None:
        target_dir = self._dirs.get(level_key)
        if target_dir is None:
            if self._stdout_fallback:
                print(line, file=sys.stderr)
            return

        try:
            fh = self._get_or_open(level_key, target_dir)
            fh.write(line + "\n")
            fh.flush()

            if fh.tell() >= self._max_bytes:
                self._rotate(level_key, target_dir)
        except OSError:
            if self._stdout_fallback:
                print(line, file=sys.stderr)

    def _get_or_open(self, level_key: str, target_dir: Path):
        fh = self._handles.get(level_key)
        if fh and not fh.closed:
            return fh
        path = target_dir / f"{level_key}.log"
        fh = open(path, "a", encoding="utf-8")
        self._handles[level_key] = fh
        return fh

    def _rotate(self, level_key: str, target_dir: Path) -> None:
        try:
            fh = self._handles.get(level_key)
            if fh and not fh.closed:
                fh.close()
        except OSError:
            pass
        self._handles.pop(level_key, None)
        base = target_dir / f"{level_key}.log"
        if not base.exists():
            return
        suffix = time.strftime("%Y%m%d_%H%M%S")
        rotated = target_dir / f"{level_key}.{suffix}.log"
        try:
            base.rename(rotated)
        except OSError:
            return

