# -*- coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

from text_sensor._logger import ModuleLogger


def test_logger_rotation_uses_collision_safe_archive_names(tmp_path):
    logger = ModuleLogger(log_dir=str(tmp_path / "logs"), max_file_bytes=1, enable_stdout_fallback=False)
    try:
        for idx in range(3):
            logger.detail(trace_id=f"trace_{idx}", step="rotation_test", info={"i": idx, "payload": "x" * 128})
        detail_dir = tmp_path / "logs" / "detail"
        archives = list(detail_dir.glob("detail_*.log"))
        assert len(archives) >= 1
        assert (detail_dir / "detail_current.log").exists()
        assert len({p.name for p in archives}) == len(archives)
    finally:
        logger.close()


def test_logger_uses_spill_current_file_when_archive_of_current_fails(monkeypatch, tmp_path):
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
            logger.detail(trace_id=f"trace_spill_{idx}", step="rotation_test", info={"payload": "tail", "index": idx})
    finally:
        logger.close()

    spill_files = sorted(detail_dir.glob("detail_current_*.log"))
    non_default_detail_logs = [path for path in detail_dir.glob("detail*.log") if path.name != "detail_current.log"]
    assert current_path.exists()
    assert current_path.stat().st_size == 2048
    assert spill_files
    assert any(path.stat().st_size > 0 for path in non_default_detail_logs)
    assert rename_failures["count"] == 1
