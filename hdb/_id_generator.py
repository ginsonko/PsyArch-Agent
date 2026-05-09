# -*- coding: utf-8 -*-
"""
Simple in-process id generator for the HDB prototype.
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock


_COUNTERS: defaultdict[str, int] = defaultdict(int)
_LOCK = Lock()


def next_id(prefix: str) -> str:
    with _LOCK:
        _COUNTERS[prefix] += 1
        return f"{prefix}_{_COUNTERS[prefix]:06d}"


def ensure_counter(prefix: str, numeric_value: int) -> None:
    with _LOCK:
        if numeric_value > _COUNTERS[prefix]:
            _COUNTERS[prefix] = numeric_value


def reset_id_generator() -> None:
    with _LOCK:
        _COUNTERS.clear()
