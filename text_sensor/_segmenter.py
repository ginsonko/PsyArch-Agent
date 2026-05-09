# -*- coding: utf-8 -*-
"""
AP 文本感受器 — 切分器
======================
支持字符级和词元级两种切分粒度：
  - 字符级切分：每个 Unicode 字符（含标点、空白）独立为一个单位
  - 词元级切分：通过可选分词器（jieba 等）进行词元切分

设计要点：
  - 分词器为弱依赖，缺失时自动降级到字符级
  - 所有切分结果都是"特征SA"的候选内容，粒度不同但类型相同
"""

import re
import traceback
from typing import Any


class TextSegmenter:
    """
    统一切分器。根据配置返回字符列表和/或词元列表。
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        # 分词器后端: "none" | "jieba" | "pkuseg" | "thulac" | "custom"
        self._backend: str = cfg.get("tokenizer_backend", "none")
        # Keep the originally requested backend for observability.
        # 保留用户配置中“请求的后端”，用于可观测性与调试。
        self._requested_backend: str = str(self._backend or "none")
        # 分词器不可用时是否降级到字符切分
        self._fallback_to_char: bool = cfg.get("tokenizer_fallback_to_char", True)
        # 自定义分词器模块路径
        self._custom_module_path: str = cfg.get("custom_tokenizer_module_path", "")
        # 用户自定义词典
        self._enable_user_dict: bool = cfg.get("enable_user_dict", False)
        self._user_dict_path: str = cfg.get("user_dict_path", "")

        # 分词器实例（延迟加载）
        self._tokenizer: Any = None
        self._tokenizer_ready: bool = False
        self._fallback_used: bool = False
        # Missing dependency hint (best-effort) / 缺失依赖提示（尽力而为）
        self._missing_backend: str = ""

        # 如果后端不是 none，尝试加载
        if self._backend != "none":
            self._try_load_tokenizer()

    # ------------------------------------------------------------------ #
    #                         公共接口                                     #
    # ------------------------------------------------------------------ #

    def segment_chars(self, text: str) -> list[dict]:
        """
        字符级切分。每个字符生成一个切分单元。

        返回列表，每项:
            {
                "text": "你",
                "unit_kind": "char",
                "char_type": "han" | "ascii_letter" | "digit" | "punctuation"
                             | "whitespace" | "emoji" | "other",
                "position": 0,       # 在原始文本中的位置
                "is_punctuation": False,
                "is_whitespace": False,
                "is_emoji": False,
            }
        """
        units = []
        for i, ch in enumerate(text):
            units.append(
                {
                    "text": ch,
                    "unit_kind": "char",
                    "char_type": self._classify_char(ch),
                    "position": i,
                    "is_punctuation": self._is_punctuation(ch),
                    "is_whitespace": ch.isspace(),
                    "is_emoji": self._is_emoji(ch),
                }
            )
        return units

    def segment_tokens(self, text: str) -> tuple[list[dict], bool]:
        """
        词元级切分。如果分词器可用则返回词元列表，否则降级到字符列表。

        返回:
            (units_list, fallback_used)

        每项格式同 segment_chars，但 unit_kind 为 "token"。
        """
        if not self._tokenizer_ready:
            if self._fallback_to_char:
                self._fallback_used = True
                return self.segment_chars(text), True
            else:
                self._fallback_used = False
                return [], True

        try:
            tokens = self._do_tokenize(text)
            units = []
            pos = 0
            for token_text in tokens:
                # 跳过空白 token（某些分词器可能产生）
                if not token_text:
                    continue
                units.append(
                    {
                        "text": token_text,
                        "unit_kind": "token",
                        "char_type": self._classify_token(token_text),
                        "position": pos,
                        "is_punctuation": self._is_punctuation_token(token_text),
                        "is_whitespace": token_text.isspace(),
                        "is_emoji": self._is_emoji(token_text[0]) if len(token_text) == 1 else False,
                    }
                )
                pos += len(token_text)
            self._fallback_used = False
            return units, False
        except Exception:
            # 分词器运行时异常，降级
            if self._fallback_to_char:
                self._fallback_used = True
                return self.segment_chars(text), True
            self._fallback_used = False
            return [], True

    @property
    def tokenizer_available(self) -> bool:
        """分词能力是否可用（包含字符级兜底）。"""
        # 字符切分总是可用；外部分词器不可用时，若允许回退也视为可用（对外“不报错”）。
        if str(self._backend or "none") == "none":
            return True
        if self._tokenizer_ready:
            return True
        return bool(self._fallback_to_char)

    @property
    def backend_name(self) -> str:
        """当前实际使用的后端名称。"""
        if self._tokenizer_ready:
            return self._backend
        # If tokenizer isn't ready, but we can fall back, expose "char" as effective backend.
        # 如果外部分词器不可用但允许回退，则对外暴露为 “char”（避免把依赖缺失当成错误）。
        if self._fallback_to_char:
            return "char"
        return "none"

    @property
    def requested_backend(self) -> str:
        """用户配置中请求的后端名称（用于调试/观测）。"""
        return str(self._requested_backend or "none")

    @property
    def missing_backend(self) -> str:
        """缺失依赖的后端名（若有）。"""
        return str(self._missing_backend or "")

    # ------------------------------------------------------------------ #
    #                         分词器加载                                   #
    # ------------------------------------------------------------------ #

    def _try_load_tokenizer(self):
        """
        尝试加载分词器。加载失败不抛异常，仅标记不可用。
        """
        self._tokenizer_ready = False
        self._missing_backend = ""
        try:
            if self._backend == "jieba":
                import jieba
                # 加载用户自定义词典
                if self._enable_user_dict and self._user_dict_path:
                    jieba.load_userdict(self._user_dict_path)
                self._tokenizer = jieba
                self._tokenizer_ready = True
            # 其他分词器后端可在此扩展
            # elif self._backend == "pkuseg": ...
        except ImportError:
            self._tokenizer_ready = False
            self._missing_backend = str(self._backend or "")
            # 自动关闭缺失依赖的分词后端（对齐验收口径：不要报错，直接回退）。
            # We keep requested_backend for observability.
            self._backend = "none"
        except Exception:
            self._tokenizer_ready = False

    def _do_tokenize(self, text: str) -> list[str]:
        """
        使用已加载的分词器执行分词。

        返回:
            词元文本列表
        """
        if self._backend == "jieba":
            # jieba.lcut 返回精确模式分词列表
            return self._tokenizer.lcut(text)
        return list(text)  # 兜底字符列表

    # ------------------------------------------------------------------ #
    #                         字符和词元分类                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _classify_char(ch: str) -> str:
        """
        对单个字符进行类型分类。
        返回: "han" | "ascii_letter" | "digit" | "punctuation"
              | "whitespace" | "emoji" | "other"
        """
        if ch.isspace():
            return "whitespace"
        # 中文字符（CJK 统一表意文字主要区段）
        code = ord(ch)
        if (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF
                or 0x20000 <= code <= 0x2A6DF):
            return "han"
        if ch.isascii() and ch.isalpha():
            return "ascii_letter"
        if ch.isdigit():
            return "digit"
        # Emoji 检测（简化版：Emoji 通常在高码点区域）
        if TextSegmenter._is_emoji(ch):
            return "emoji"
        # 标点检测
        if TextSegmenter._is_punctuation(ch):
            return "punctuation"
        return "other"

    @staticmethod
    def _classify_token(token_text: str) -> str:
        """对词元进行类型分类（以首字符为主要依据）。"""
        if not token_text:
            return "other"
        if token_text.isspace():
            return "whitespace"
        if all(TextSegmenter._is_punctuation(c) for c in token_text):
            return "punctuation"
        if all(c.isdigit() for c in token_text):
            return "digit"
        first = token_text[0]
        code = ord(first)
        if (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF
                or 0x20000 <= code <= 0x2A6DF):
            return "han"
        if first.isascii() and first.isalpha():
            return "ascii_letter"
        return "other"

    @staticmethod
    def _is_punctuation(ch: str) -> bool:
        """判断字符是否为标点（中英文标点均覆盖）。"""
        import unicodedata
        cat = unicodedata.category(ch)
        # Po=Other punctuation, Ps=Open punctuation, Pe=Close punctuation
        # Pi=Initial quote, Pf=Final quote, Pd=Dash, Pc=Connector
        return cat.startswith("P")

    @staticmethod
    def _is_punctuation_token(token: str) -> bool:
        """判断整个词元是否全为标点。"""
        return all(TextSegmenter._is_punctuation(c) for c in token)

    @staticmethod
    def _is_emoji(ch: str) -> bool:
        """
        简化版 Emoji 检测。
        覆盖主要 Emoji 码点范围。
        """
        code = ord(ch)
        return (
            0x1F600 <= code <= 0x1F64F  # Emoticons
            or 0x1F300 <= code <= 0x1F5FF  # Misc Symbols & Pictographs
            or 0x1F680 <= code <= 0x1F6FF  # Transport & Map
            or 0x1F1E0 <= code <= 0x1F1FF  # Flags
            or 0x2600 <= code <= 0x26FF  # Misc Symbols
            or 0x2700 <= code <= 0x27BF  # Dingbats
            or 0xFE00 <= code <= 0xFE0F  # Variation Selectors
            or 0x1F900 <= code <= 0x1F9FF  # Supplemental Symbols
            or 0x1FA00 <= code <= 0x1FA6F  # Chess Symbols
            or 0x1FA70 <= code <= 0x1FAFF  # Symbols & Pictographs Ext-A
        )

    def update_config(self, config: dict):
        """热加载时更新切分器配置。若后端变更则重新加载。"""
        # Keep requested backend in sync with config for observability.
        # 将“请求的后端”与配置保持一致（用于观测与调试）。
        if "tokenizer_backend" in config:
            self._requested_backend = str(config.get("tokenizer_backend", "none") or "none")
        new_backend = config.get("tokenizer_backend", self._requested_backend or self._backend)
        need_reload = False

        if new_backend != self._backend:
            self._backend = new_backend
            need_reload = True
        if "tokenizer_fallback_to_char" in config:
            self._fallback_to_char = bool(config["tokenizer_fallback_to_char"])
        if "custom_tokenizer_module_path" in config:
            self._custom_module_path = config["custom_tokenizer_module_path"]
        if "enable_user_dict" in config:
            self._enable_user_dict = bool(config["enable_user_dict"])
        if "user_dict_path" in config:
            self._user_dict_path = config["user_dict_path"]
            need_reload = True

        if need_reload:
            if self._backend != "none":
                self._try_load_tokenizer()
            else:
                self._tokenizer_ready = False
                self._tokenizer = None
