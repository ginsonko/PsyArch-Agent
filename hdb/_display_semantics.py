# -*- coding: utf-8 -*-
"""
Display-only structural glyph helpers.

These symbols are used by the frontend / debug notation to explain temporal or
co-occurrence structure. They are not real semantic atoms by themselves and
must not be introduced into backend feature tokens through display-derived
fallback paths.
"""

from __future__ import annotations


DISPLAY_ONLY_TOKENS = frozenset(
    {
        "+",
        "/",
        "{",
        "}",
        "[",
        "]",
        "(",
        ")",
        "||",
        "->",
        "·",
        "|",
    }
)

_DISPLAY_ONLY_MULTI_CHAR_TOKENS = ("->", "||")
_DISPLAY_ONLY_SINGLE_CHAR_GLYPHS = "{}[]()+/|·"


def is_display_only_token(token: str) -> bool:
    return str(token or "").strip() in DISPLAY_ONLY_TOKENS


def strip_display_only_glyphs(text: str) -> str:
    cleaned = str(text or "")
    if not cleaned:
        return ""
    for marker in _DISPLAY_ONLY_MULTI_CHAR_TOKENS:
        cleaned = cleaned.replace(marker, " ")
    for ch in _DISPLAY_ONLY_SINGLE_CHAR_GLYPHS:
        cleaned = cleaned.replace(ch, " ")
    return " ".join(cleaned.split())
