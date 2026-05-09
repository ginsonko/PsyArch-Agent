# -*- coding: utf-8 -*-
"""
Experiment Storage Layout
=========================

We intentionally write experiment artifacts under:
  observatory/outputs/experiment_runs/<run_id>/

Reason:
- `observatory/outputs/` is already gitignored in this repo
- keeps runtime artifacts out of the public GitHub history
- still easy to inspect locally for paper evidence

This module also provides safe path resolution for:
- built-in datasets in repo_root/datasets/
- imported datasets saved under observatory/outputs/datasets_imported/
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ExperimentStorageError(RuntimeError):
    pass


def repo_root() -> Path:
    # observatory/experiment/storage.py -> observatory/experiment -> observatory -> repo root
    return Path(__file__).resolve().parents[2]


def datasets_dir() -> Path:
    return repo_root() / "datasets"


def imported_datasets_dir() -> Path:
    return repo_root() / "observatory" / "outputs" / "datasets_imported"


def experiment_runs_dir() -> Path:
    return repo_root() / "observatory" / "outputs" / "experiment_runs"


def safe_slug(value: str, *, fallback: str = "item") -> str:
    s = str(value or "").strip()
    if not s:
        return fallback
    s = s.replace(" ", "_")
    s = re.sub(r"[^a-zA-Z0-9_\-\.]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or fallback


@dataclass(frozen=True)
class DatasetFileRef:
    source: str  # "built_in" | "imported"
    rel_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "rel_path": self.rel_path}


def _resolve_under(base: Path, rel_path: str) -> Path:
    rel = Path(str(rel_path).lstrip("/\\"))
    p = (base / rel).resolve()
    try:
        p.relative_to(base.resolve())
    except ValueError as exc:
        raise ExperimentStorageError(f"Forbidden path (escape attempt): {rel_path}") from exc
    return p


def resolve_dataset_file(ref: DatasetFileRef) -> Path:
    if ref.source == "built_in":
        return _resolve_under(datasets_dir(), ref.rel_path)
    if ref.source == "imported":
        return _resolve_under(imported_datasets_dir(), ref.rel_path)
    raise ExperimentStorageError(f"Unknown dataset source: {ref.source}")


def list_dataset_files() -> list[DatasetFileRef]:
    out: list[DatasetFileRef] = []
    base = datasets_dir()
    if base.exists():
        for p in sorted(base.glob("**/*.yaml")):
            try:
                rel = p.resolve().relative_to(base.resolve())
            except Exception:
                continue
            out.append(DatasetFileRef(source="built_in", rel_path=str(rel).replace("\\", "/")))
        for p in sorted(base.glob("**/*.yml")):
            try:
                rel = p.resolve().relative_to(base.resolve())
            except Exception:
                continue
            out.append(DatasetFileRef(source="built_in", rel_path=str(rel).replace("\\", "/")))
        for p in sorted(base.glob("**/*.jsonl")):
            try:
                rel = p.resolve().relative_to(base.resolve())
            except Exception:
                continue
            out.append(DatasetFileRef(source="built_in", rel_path=str(rel).replace("\\", "/")))

    imp = imported_datasets_dir()
    if imp.exists():
        for p in sorted(imp.glob("**/*.yaml")):
            try:
                rel = p.resolve().relative_to(imp.resolve())
            except Exception:
                continue
            out.append(DatasetFileRef(source="imported", rel_path=str(rel).replace("\\", "/")))
        for p in sorted(imp.glob("**/*.yml")):
            try:
                rel = p.resolve().relative_to(imp.resolve())
            except Exception:
                continue
            out.append(DatasetFileRef(source="imported", rel_path=str(rel).replace("\\", "/")))
        for p in sorted(imp.glob("**/*.jsonl")):
            try:
                rel = p.resolve().relative_to(imp.resolve())
            except Exception:
                continue
            out.append(DatasetFileRef(source="imported", rel_path=str(rel).replace("\\", "/")))

    # Stable ordering by source then path (readable in UI).
    out.sort(key=lambda r: (r.source, r.rel_path))
    return out


def make_run_dir(run_id: str) -> Path:
    rid = safe_slug(run_id, fallback="run")
    base = experiment_runs_dir()
    base.mkdir(parents=True, exist_ok=True)
    run_dir = (base / rid).resolve()
    try:
        run_dir.relative_to(base.resolve())
    except ValueError as exc:  # pragma: no cover
        raise ExperimentStorageError("Invalid run_id leads to path escape.") from exc
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def list_runs(limit: int = 32) -> list[str]:
    base = experiment_runs_dir()
    if not base.exists():
        return []
    dirs = [p for p in base.iterdir() if p.is_dir()]
    # Most recent by mtime desc
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in dirs[: max(1, int(limit))]]


def resolve_run_dir(run_id: str) -> Path:
    rid = safe_slug(run_id, fallback="run")
    base = experiment_runs_dir()
    p = (base / rid).resolve()
    try:
        p.relative_to(base.resolve())
    except ValueError as exc:
        raise ExperimentStorageError(f"Invalid run_id: {run_id}") from exc
    return p


def read_run_manifest(run_id: str) -> dict[str, Any]:
    run_dir = resolve_run_dir(run_id)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def list_run_infos(limit: int = 32) -> list[dict[str, Any]]:
    base = experiment_runs_dir()
    if not base.exists():
        return []
    dirs = [p for p in base.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for p in dirs[: max(1, int(limit))]:
        manifest = {}
        manifest_path = p / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}
        stat = p.stat()
        out.append(
            {
                "run_id": p.name,
                "status": str(manifest.get("status", "unknown") or "unknown"),
                "dataset_id": str(((manifest.get("dataset") or {}).get("dataset_id", "")) or ""),
                "tick_done": int(manifest.get("tick_done", 0) or 0),
                "tick_planned": manifest.get("tick_planned", None),
                "started_at_ms": int(manifest.get("started_at_ms", 0) or 0),
                "finished_at_ms": int(manifest.get("finished_at_ms", 0) or 0),
                "updated_at_ms": int(stat.st_mtime * 1000),
                "path": str(p),
            }
        )
    return out


def delete_run(run_id: str) -> dict[str, Any]:
    run_dir = resolve_run_dir(run_id)
    if not run_dir.exists():
        raise ExperimentStorageError(f"Run not found: {run_id}")
    shutil.rmtree(run_dir)
    return {"run_id": run_id, "deleted": True}


def clear_runs(*, keep_run_ids: set[str] | None = None) -> dict[str, Any]:
    keep = {safe_slug(x, fallback="run") for x in (keep_run_ids or set())}
    base = experiment_runs_dir()
    if not base.exists():
        return {"deleted_count": 0, "skipped_run_ids": sorted(keep)}
    deleted_count = 0
    skipped_run_ids: list[str] = []
    for p in base.iterdir():
        if not p.is_dir():
            continue
        if p.name in keep:
            skipped_run_ids.append(p.name)
            continue
        shutil.rmtree(p)
        deleted_count += 1
    return {"deleted_count": deleted_count, "skipped_run_ids": skipped_run_ids}

