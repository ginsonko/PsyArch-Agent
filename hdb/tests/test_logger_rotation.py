# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

from hdb._logger import ModuleLogger


def test_hdb_logger_rotation_uses_unique_archive_names_and_stays_quiet(capsys, tmp_path: Path):
    logger = ModuleLogger(log_dir=str(tmp_path / "logs"), max_file_bytes=32, enable_stdout_fallback=True)
    try:
        for idx in range(6):
            logger.detail(
                trace_id=f"trace_{idx}",
                tick_id=f"tick_{idx}",
                step="rotation_probe",
                info={"payload": "x" * 80, "index": idx},
                message_zh="旋转探针",
                message_en="rotation probe",
            )
        logger.detail(
            trace_id="trace_final",
            tick_id="tick_final",
            step="rotation_probe",
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
    assert "log rotation failed" not in captured.err


def test_hdb_logger_uses_spill_current_file_when_archive_of_current_fails(monkeypatch, tmp_path: Path):
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
                tick_id="tick_spill",
                step="rotation_probe",
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
