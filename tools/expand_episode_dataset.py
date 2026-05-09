# -*- coding: utf-8 -*-
"""
Episode Dataset Expander (YAML -> expanded_ticks.jsonl)
======================================================

This CLI tool expands a compact episode-template YAML dataset into a per-tick JSONL stream.

It is a thin wrapper around the shared library code under `observatory/experiment/`,
so the web UI and CLI stay consistent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _ensure_repo_root_on_syspath() -> None:
    # tools/expand_episode_dataset.py -> tools -> repo root
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_ensure_repo_root_on_syspath()

from observatory.experiment.dataset import (  # noqa: E402
    DatasetValidationError,
    expand_dataset,
    validate_and_normalize_dataset,
)
from observatory.experiment.io import load_yaml_file  # noqa: E402


def _count_lines(path: Path) -> int:
    n = 0
    with path.open("r", encoding="utf-8") as f:
        for _ in f:
            n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Expand episode dataset YAML to expanded_ticks.jsonl")
    parser.add_argument("--in", dest="in_path", required=True, help="Input dataset YAML path")
    parser.add_argument("--out", dest="out_path", required=True, help="Output expanded JSONL path")
    parser.add_argument("--stats", action="store_true", help="Print basic stats to stdout")
    args = parser.parse_args(argv)

    in_path = Path(args.in_path).resolve()
    out_path = Path(args.out_path).resolve()
    if not in_path.exists():
        raise SystemExit(f"Input not found: {in_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    raw: dict[str, Any] = load_yaml_file(in_path)
    ds = validate_and_normalize_dataset(raw)
    items = list(expand_dataset(ds))

    with out_path.open("w", encoding="utf-8") as f:
        for obj in items:
            f.write(json.dumps(obj, ensure_ascii=False))
            f.write("\n")

    if args.stats:
        print(
            json.dumps(
                {
                    "dataset_id": ds.get("dataset_id", ""),
                    "time_basis": ds.get("time_basis", ""),
                    "tick_dt_ms": ds.get("tick_dt_ms", None),
                    "tick_count": _count_lines(out_path),
                    "out_path": str(out_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

