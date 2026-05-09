# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from pathlib import Path

from state_pool._logger import ModuleLogger


def test_state_pool_logger_rotation_uses_unique_archive_names_and_stays_quiet(capsys, tmp_path: Path):
    logger = ModuleLogger(log_dir=str(tmp_path / "logs"), max_file_bytes=32, enable_stdout_fallback=True)
    try:
        for idx in range(6):
            logger.detail(
                trace_id=f"trace_{idx}",
                step="rotation_probe",
                tick_id=f"tick_{idx}",
                info={"payload": "x" * 80, "index": idx},
                message_zh="旋转探针",
                message_en="rotation probe",
            )
        logger.detail(
            trace_id="trace_final",
            step="rotation_probe",
            tick_id="tick_final",
            info={"payload": "tail"},
            message_zh="旋转收尾",
            message_en="rotation tail",
        )
    finally:
        logger.close()

    detail_dir = tmp_path / "logs" / "detail"
    archived = sorted(detail_dir.glob("detail_*.log"))

    assert len(archived) >= 2
    assert len({path.name for path in archived}) == len(archived)
    assert any(path.stat().st_size > 0 for path in archived)

    captured = capsys.readouterr()
    assert "log rotate failed" not in captured.err


def test_state_pool_logger_uses_spill_current_file_when_archive_of_current_fails(monkeypatch, tmp_path: Path):
    logger = ModuleLogger(log_dir=str(tmp_path / "logs"), max_file_bytes=1024, enable_stdout_fallback=False)
    detail_dir = tmp_path / "logs" / "detail"
    current_path = detail_dir / "detail_current.log"
    current_path.write_text("x" * 2048, encoding="utf-8")

    original_rename = Path.rename
    rename_failures = {"count": 0}

    def fail_current_rename(self: Path, target: Path):
        if self.name == "detail_current.log":
            rename_failures["count"] += 1
            raise OSError("locked current log")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_current_rename)
    try:
        for idx in range(20):
            logger.detail(
                trace_id=f"trace_spill_{idx}",
                step="rotation_probe",
                tick_id="tick_spill",
                info={"payload": "tail", "index": idx},
                message_zh="旋转收尾",
                message_en="rotation tail",
            )
    finally:
        logger.close()

    spill_files = sorted(detail_dir.glob("detail_current_*.log"))
    non_default_detail_logs = [path for path in detail_dir.glob("detail*.log") if path.name != "detail_current.log"]
    assert current_path.exists()
    assert current_path.stat().st_size == 2048
    assert spill_files
    assert any(path.stat().st_size > 0 for path in non_default_detail_logs)
    assert rename_failures["count"] == 1


def test_state_pool_logger_prunes_old_archives_and_spill_files(tmp_path: Path):
    detail_dir = tmp_path / "logs" / "detail"
    detail_dir.mkdir(parents=True, exist_ok=True)

    stale_paths = []
    for idx in range(5):
        name = (
            f"detail_2026-04-28_00-00-0{idx}_{idx}.log"
            if idx % 2 == 0
            else f"detail_current_2026-04-28_00-00-0{idx}_{idx}.log"
        )
        path = detail_dir / name
        path.write_text(f"stale-{idx}", encoding="utf-8")
        stale_paths.append(path)

    for idx, path in enumerate(stale_paths):
        ts = 1_700_000_000 + idx
        path.touch()
        os.utime(path, (ts, ts))

    logger = ModuleLogger(
        log_dir=str(tmp_path / "logs"),
        max_file_bytes=1024 * 1024,
        archive_keep_per_level={"detail": 2, "brief": 0, "error": 0},
        enable_stdout_fallback=False,
    )
    try:
        logger.detail(
            trace_id="trace_prune",
            step="prune_probe",
            tick_id="tick_prune",
            info={"payload": "hello"},
            message_zh="清理探针",
            message_en="prune probe",
        )
    finally:
        logger.close()

    remaining_history = sorted(
        [
            path.name
            for path in detail_dir.glob("detail*.log")
            if path.name != "detail_current.log"
        ]
    )

    assert len(remaining_history) == 2
    assert set(remaining_history) == {stale_paths[3].name, stale_paths[4].name}
    assert (detail_dir / "detail_current.log").exists()
