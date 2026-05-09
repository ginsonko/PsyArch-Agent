# -*- coding: utf-8 -*-
"""
AP 文本感受器 — 文本归一化处理器
================================
负责将原始文本做标准化预处理：
  - 去除不可见控制字符
  - 全角→半角统一（可选）
  - 英文大小写规范化（可选）
  - 去首尾空白
  - 重复空白压缩（可选）
"""

import re
import unicodedata


class TextNormalizer:
    """
    文本归一化器。
    所有策略均可通过配置开关控制，保证灵活性。
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        # --- 可配置开关 ---
        # 是否去除不可见控制字符（推荐开启）
        self._strip_control_chars: bool = cfg.get("strip_control_chars", True)
        # 是否做全角→半角转换
        self._fullwidth_to_halfwidth: bool = cfg.get("fullwidth_to_halfwidth", False)
        # 英文大小写策略: "none" | "lower" | "upper"
        self._case_policy: str = cfg.get("case_policy", "none")
        # 是否压缩连续空白为单个空格
        self._compress_whitespace: bool = cfg.get("compress_whitespace", False)
        # 是否去首尾空白
        self._strip_edges: bool = cfg.get("strip_edges", True)

    def normalize(self, text: str) -> str:
        """
        执行归一化流程，返回处理后的文本。
        顺序：控制字符 → 全半角 → 大小写 → 首尾空白 → 空白压缩
        """
        if not text:
            return text

        result = text

        # Step 1: 去除不可见控制字符（保留换行/Tab/空格等常用空白）
        if self._strip_control_chars:
            result = self._remove_control_chars(result)

        # Step 2: 全角→半角
        if self._fullwidth_to_halfwidth:
            result = self._convert_fullwidth(result)

        # Step 3: 大小写
        if self._case_policy == "lower":
            result = result.lower()
        elif self._case_policy == "upper":
            result = result.upper()

        # Step 4: 去首尾空白
        if self._strip_edges:
            result = result.strip()

        # Step 5: 压缩连续空白
        if self._compress_whitespace:
            result = re.sub(r"[ \t]+", " ", result)

        return result

    # ------------------------------------------------------------------ #
    #                         内部方法                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _remove_control_chars(text: str) -> str:
        """
        移除 Unicode 控制字符（Cc 类别），但保留常用空白字符。
        保留: \\n (0x0A), \\r (0x0D), \\t (0x09), 空格 (0x20)
        """
        result = []
        for ch in text:
            if unicodedata.category(ch) == "Cc":
                # 保留换行、回车、制表符
                if ch in ("\n", "\r", "\t"):
                    result.append(ch)
                # 其他控制字符丢弃
            else:
                result.append(ch)
        return "".join(result)

    @staticmethod
    def _convert_fullwidth(text: str) -> str:
        """
        将全角 ASCII 字符转换为半角。
        全角范围: U+FF01 ~ U+FF5E → 半角: U+0021 ~ U+007E
        全角空格: U+3000 → 半角空格 U+0020
        注意：不转换中文标点（它们不在全角 ASCII 范围内）。
        """
        result = []
        for ch in text:
            code = ord(ch)
            if 0xFF01 <= code <= 0xFF5E:
                # 全角 ASCII → 半角
                result.append(chr(code - 0xFEE0))
            elif code == 0x3000:
                # 全角空格 → 半角空格
                result.append(" ")
            else:
                result.append(ch)
        return "".join(result)

    def update_config(self, config: dict):
        """热加载时更新归一化配置。"""
        if "strip_control_chars" in config:
            self._strip_control_chars = bool(config["strip_control_chars"])
        if "fullwidth_to_halfwidth" in config:
            self._fullwidth_to_halfwidth = bool(config["fullwidth_to_halfwidth"])
        if "case_policy" in config:
            val = config["case_policy"]
            if val in ("none", "lower", "upper"):
                self._case_policy = val
        if "compress_whitespace" in config:
            self._compress_whitespace = bool(config["compress_whitespace"])
        if "strip_edges" in config:
            self._strip_edges = bool(config["strip_edges"])
