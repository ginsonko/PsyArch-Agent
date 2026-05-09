# -*- coding: utf-8 -*-
"""
Shared numeric fuzzy-match helpers for HDB.
"""

from __future__ import annotations

import math
from typing import Any


DEFAULT_NUMERIC_MATCH_ABS_TOLERANCE = 0.2
DEFAULT_NUMERIC_MATCH_REL_TOLERANCE = 0.35
DEFAULT_NUMERIC_MATCH_MIN_SIMILARITY = 0.4


def coerce_numeric_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric_value = float(value)
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            numeric_value = float(text)
        except (TypeError, ValueError):
            return None
    if not math.isfinite(numeric_value):
        return None
    return float(numeric_value)


def numeric_match_tolerance(
    left_value: float,
    right_value: float,
    *,
    abs_tolerance: float = DEFAULT_NUMERIC_MATCH_ABS_TOLERANCE,
    rel_tolerance: float = DEFAULT_NUMERIC_MATCH_REL_TOLERANCE,
) -> float:
    left = float(left_value)
    right = float(right_value)
    average_value = (left + right) / 2.0
    scale = max(1e-9, abs(left), abs(right), abs(average_value))
    return max(
        0.0,
        float(abs_tolerance),
        max(0.0, float(rel_tolerance)) * scale,
    )


def describe_numeric_match(
    *,
    left_value: Any,
    right_value: Any,
    abs_tolerance: float = DEFAULT_NUMERIC_MATCH_ABS_TOLERANCE,
    rel_tolerance: float = DEFAULT_NUMERIC_MATCH_REL_TOLERANCE,
    min_similarity: float = DEFAULT_NUMERIC_MATCH_MIN_SIMILARITY,
    family: str = "",
    allow_cross_zero: bool = False,
) -> dict[str, float | str] | None:
    left = coerce_numeric_value(left_value)
    right = coerce_numeric_value(right_value)
    if left is None or right is None:
        return None

    if not allow_cross_zero and ((left < 0.0 <= right) or (right < 0.0 <= left)):
        return None

    distance = abs(float(left) - float(right))
    tolerance = numeric_match_tolerance(
        float(left),
        float(right),
        abs_tolerance=abs_tolerance,
        rel_tolerance=rel_tolerance,
    )
    if distance <= 0.0:
        similarity = 1.0
    elif tolerance <= 0.0:
        similarity = 0.0
    else:
        similarity = max(0.0, 1.0 - (distance / tolerance))

    similarity_floor = max(0.0, min(1.0, float(min_similarity)))
    if similarity < similarity_floor:
        return None

    average_value = (float(left) + float(right)) / 2.0
    return {
        "family": str(family or ""),
        "left_value": round(float(left), 8),
        "right_value": round(float(right), 8),
        "average_value": round(average_value, 8),
        "distance": round(distance, 8),
        "tolerance": round(tolerance, 8),
        "similarity": round(float(similarity), 8),
    }
