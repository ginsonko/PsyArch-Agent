# -*- coding: utf-8 -*-
"""
输入文本完整性预检
================

目标：
1. 尽量自动修复常见的 UTF-8 / latin-1(cp1252) 轮转乱码；
2. 无法修复时，尽早拒绝明显不可读/占位符型输入，避免污染后续数据库。
"""

from __future__ import annotations

import unicodedata
from typing import Any

_PLACEHOLDER_CHARS = frozenset({"?", "？", "\ufffd", "□", "■"})
_ROUNDTRIP_ENCODINGS = ("latin-1", "cp1252")


def sanitize_text_input(text: str) -> dict[str, Any]:
    raw = str(text or "")
    if not raw:
        return {
            "ok": True,
            "text": raw,
            "status": "clean",
            "detail": {"reason": "empty"},
        }

    repair = _best_roundtrip_repair(raw)
    candidate = str(repair.get("text") or raw) if repair else raw

    replacement_issue = _replacement_char_issue(candidate)
    if replacement_issue:
        return {
            "ok": False,
            "text": "",
            "status": "rejected",
            "detail": replacement_issue,
        }

    placeholder_issue = _placeholder_run_issue(candidate)
    if placeholder_issue:
        return {
            "ok": False,
            "text": "",
            "status": "rejected",
            "detail": placeholder_issue,
        }

    if repair:
        return {
            "ok": True,
            "text": candidate,
            "status": "repaired",
            "detail": repair,
        }

    return {
        "ok": True,
        "text": raw,
        "status": "clean",
        "detail": {"reason": "ok"},
    }


def _replacement_char_issue(text: str) -> dict[str, Any] | None:
    count = text.count("\ufffd")
    if count <= 0:
        return None
    return {
        "reason": "replacement_char",
        "message": "输入文本包含 Unicode replacement char，疑似上游解码已丢失原始字符。",
        "replacement_count": count,
    }


def _placeholder_run_issue(text: str) -> dict[str, Any] | None:
    visible = [ch for ch in str(text or "") if not ch.isspace()]
    if len(visible) < 4:
        return None
    placeholder_count = sum(1 for ch in visible if ch in _PLACEHOLDER_CHARS)
    if placeholder_count <= 0:
        return None
    placeholder_ratio = float(placeholder_count) / float(len(visible))
    readable_count = _readable_count("".join(visible))
    longest_same_run, run_char = _longest_same_placeholder_run(visible)
    if readable_count == 0 and placeholder_ratio >= 0.85 and longest_same_run >= 4:
        return {
            "reason": "placeholder_run",
            "message": "输入文本主要由无法识别的占位符构成，疑似编码丢失后的不可恢复文本。",
            "placeholder_ratio": round(placeholder_ratio, 6),
            "longest_same_placeholder_run": longest_same_run,
            "placeholder_char": run_char,
        }
    return None


def _longest_same_placeholder_run(chars: list[str]) -> tuple[int, str]:
    best_len = 0
    best_char = ""
    current_char = ""
    current_len = 0
    for ch in chars:
        if ch in _PLACEHOLDER_CHARS and ch == current_char:
            current_len += 1
        elif ch in _PLACEHOLDER_CHARS:
            current_char = ch
            current_len = 1
        else:
            current_char = ""
            current_len = 0
        if current_len > best_len:
            best_len = current_len
            best_char = current_char
    return best_len, best_char


def _best_roundtrip_repair(text: str) -> dict[str, Any] | None:
    raw = str(text or "")
    raw_quality = _quality_score(raw)
    raw_readable = _readable_count(raw)
    raw_suspicious = _suspicious_count(raw)
    best: dict[str, Any] | None = None
    best_delta = 0
    for encoding in _ROUNDTRIP_ENCODINGS:
        try:
            repaired = raw.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        repaired = str(repaired or "")
        if not repaired or repaired == raw:
            continue
        repaired_quality = _quality_score(repaired)
        repaired_readable = _readable_count(repaired)
        repaired_suspicious = _suspicious_count(repaired)
        quality_delta = repaired_quality - raw_quality
        if quality_delta < 3:
            continue
        if repaired_readable < max(1, raw_readable):
            continue
        if repaired_suspicious > max(0, raw_suspicious - 1):
            continue
        candidate = {
            "reason": "roundtrip_utf8_repair",
            "source_encoding": encoding,
            "quality_delta": quality_delta,
            "text": repaired,
        }
        if best is None or quality_delta > best_delta:
            best = candidate
            best_delta = quality_delta
    return best


def _quality_score(text: str) -> int:
    return _readable_count(text) * 3 - _suspicious_count(text)


def _readable_count(text: str) -> int:
    count = 0
    for ch in str(text or ""):
        if ch.isspace():
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("L") or cat == "Nd" or _looks_like_emoji(ch):
            count += 1
    return count


def _suspicious_count(text: str) -> int:
    count = 0
    for ch in str(text or ""):
        if ch.isspace():
            continue
        code = ord(ch)
        if ch in _PLACEHOLDER_CHARS:
            count += 4
            continue
        if 0x0080 <= code <= 0x009F:
            count += 3
            continue
        if 0x00A0 <= code <= 0x00FF:
            count += 2
    return count


def _looks_like_emoji(ch: str) -> bool:
    code = ord(ch)
    return 0x1F300 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF
