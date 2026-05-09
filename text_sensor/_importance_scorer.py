# -*- coding: utf-8 -*-
"""
AP 文本感受器 — 重要性评分器
============================
分层可插拔的重要性评分体系：
  Layer 0: none   — 不做评分，所有单位等权
  Layer 1: rule   — 纯规则（字符类型、标点、位置等）
  Layer 2: keyword — 经典关键词算法（jieba TextRank / TF-IDF）
  Layer 3: embedding — 本地轻量 embedding 模型
  Layer 4: api    — 远程 HTTP 评分接口

降级链：每一层失败自动退回上一层，最终兜底为 rule。
"""

import traceback
from typing import Any


class ImportanceScorer:
    """
    重要性评分器。根据配置选择评分策略，失败时自动降级。
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        # 是否启用重要性评分
        self._enabled: bool = cfg.get("enable_importance_scoring", False)
        # 评分模式: "none" | "rule" | "keyword" | "embedding" | "api"
        self._mode: str = cfg.get("importance_mode", "rule")
        # 关键词算法后端: "jieba_tfidf" | "jieba_textrank"
        self._backend: str = cfg.get("importance_backend", "builtin_rule")
        # 降级顺序
        self._fallback_order: list[str] = cfg.get(
            "importance_fallback_order", ["keyword", "rule", "none"]
        )
        # 评分范围限制
        self._score_min: float = cfg.get("importance_score_min", 0.2)
        self._score_max: float = cfg.get("importance_score_max", 1.5)
        # 评分到刺激量的缩放系数
        self._to_er_scale: float = cfg.get("importance_to_er_scale", 1.0)

        # ---- 规则评分参数 ----
        self._rule_config = {
            "han_base": cfg.get("rule_han_base", 1.0),
            "punctuation_ratio": cfg.get("punctuation_er_ratio", 0.35),
            "whitespace_ratio": cfg.get("whitespace_er_ratio", 0.1),
            "emoji_ratio": cfg.get("emoji_er_ratio", 1.2),
            "digit_ratio": cfg.get("digit_er_ratio", 0.8),
            "question_mark_boost": cfg.get("question_mark_boost", 1.1),
            "exclamation_mark_boost": cfg.get("exclamation_mark_boost", 1.1),
            "ascii_letter_ratio": cfg.get("ascii_letter_ratio", 0.9),
        }

        # ---- API 评分参数 ----
        self._api_url: str = cfg.get("importance_api_url", "")
        self._api_timeout_ms: int = cfg.get("importance_api_timeout_ms", 1500)
        self._api_token: str = cfg.get("importance_api_auth_token", "")

    # ------------------------------------------------------------------ #
    #                         公共接口                                     #
    # ------------------------------------------------------------------ #

    def score(
        self,
        text: str,
        units: list[dict],
    ) -> dict:
        """
        对切分后的文本单位列表计算重要性评分。

        参数:
            text: 归一化后的完整文本
            units: 切分器输出的单位列表

        返回:
            {
                "scores": [{"text": "你", "score": 1.0, "unit_index": 0}, ...],
                "mode_used": "rule",
                "backend_used": "builtin_rule",
                "fallback_used": False,
                "fallback_chain": [],
            }
        """
        if not self._enabled or self._mode == "none":
            return self._score_none(units)

        # 按降级链尝试
        chain: list[str] = [self._mode] + [
            m for m in self._fallback_order if m != self._mode
        ]
        fallback_chain: list[str] = []

        for mode in chain:
            try:
                scores = self._dispatch_score(mode, text, units)
                if scores is not None:
                    return {
                        "scores": scores,
                        "mode_used": mode,
                        "backend_used": self._backend if mode == "keyword" else mode,
                        "fallback_used": len(fallback_chain) > 0,
                        "fallback_chain": fallback_chain,
                    }
            except Exception:
                pass
            fallback_chain.append(mode)

        # 全部失败，兜底
        return self._score_none(units)

    # ------------------------------------------------------------------ #
    #                         评分调度                                     #
    # ------------------------------------------------------------------ #

    def _dispatch_score(
        self, mode: str, text: str, units: list[dict]
    ) -> list[dict] | None:
        """根据模式分派到具体评分实现。"""
        if mode == "rule":
            return self._score_rule(units)
        elif mode == "keyword":
            return self._score_keyword(text, units)
        elif mode == "embedding":
            return self._score_embedding(text, units)
        elif mode == "api":
            return self._score_api(text, units)
        elif mode == "none":
            return [
                {"text": u["text"], "score": 1.0, "unit_index": i}
                for i, u in enumerate(units)
            ]
        return None

    # ------------------------------------------------------------------ #
    #                   Layer 0: 无评分                                    #
    # ------------------------------------------------------------------ #

    def _score_none(self, units: list[dict]) -> dict:
        """所有单位等权 1.0。"""
        scores = [
            {"text": u["text"], "score": 1.0, "unit_index": i}
            for i, u in enumerate(units)
        ]
        return {
            "scores": scores,
            "mode_used": "none",
            "backend_used": "none",
            "fallback_used": False,
            "fallback_chain": [],
        }

    # ------------------------------------------------------------------ #
    #                   Layer 1: 规则评分                                  #
    # ------------------------------------------------------------------ #

    def _score_rule(self, units: list[dict]) -> list[dict]:
        """
        基于字符/词元类型的规则评分。
        根据类型分配基础分数，再应用特殊符号增强。
        """
        rc = self._rule_config
        scores = []
        total_units = len(units)

        for i, u in enumerate(units):
            char_type = u.get("char_type", "other")
            text = u["text"]

            # 基础分数
            if char_type == "han":
                base = rc["han_base"]
            elif char_type == "punctuation":
                base = rc["punctuation_ratio"]
            elif char_type == "whitespace":
                base = rc["whitespace_ratio"]
            elif char_type == "emoji":
                base = rc["emoji_ratio"]
            elif char_type == "digit":
                base = rc["digit_ratio"]
            elif char_type == "ascii_letter":
                base = rc["ascii_letter_ratio"]
            else:
                base = rc["han_base"]

            # 特殊符号增强
            if text in ("?", "？"):
                base *= rc["question_mark_boost"]
            elif text in ("!", "！"):
                base *= rc["exclamation_mark_boost"]

            # 位置增益（句首句尾微调）
            if total_units > 2:
                if i == 0 or i == total_units - 1:
                    base *= 1.05  # 句首/句尾轻微增益

            # 词元长度增益（仅对 token 类型）
            if u.get("unit_kind") == "token" and len(text) > 1:
                # 长度适度增益: 2字=1.05, 3字=1.10, 4字+=1.15
                length_gain = min(1.0 + len(text) * 0.05, 1.15)
                base *= length_gain

            # 裁剪到范围
            score = max(self._score_min, min(self._score_max, base))
            scores.append({"text": text, "score": round(score, 4), "unit_index": i})

        return scores

    # ------------------------------------------------------------------ #
    #                   Layer 2: 关键词算法评分                            #
    # ------------------------------------------------------------------ #

    def _score_keyword(
        self, text: str, units: list[dict]
    ) -> list[dict] | None:
        """
        使用 jieba TextRank 或 TF-IDF 提取关键词分数，
        再映射到各切分单位上。
        """
        try:
            import jieba.analyse
        except ImportError:
            return None  # 降级

        # 获取关键词分数
        if self._backend == "jieba_textrank":
            kw_list = jieba.analyse.textrank(
                text, topK=50, withWeight=True
            )
        else:  # jieba_tfidf 或默认
            kw_list = jieba.analyse.extract_tags(
                text, topK=50, withWeight=True
            )

        # 构建关键词→分数映射
        kw_map: dict[str, float] = {}
        for word, weight in kw_list:
            kw_map[word] = weight

        # 归一化到 [0, 1]
        max_w = max(kw_map.values()) if kw_map else 1.0
        if max_w > 0:
            for k in kw_map:
                kw_map[k] /= max_w

        # 映射到 units
        scores = []
        for i, u in enumerate(units):
            unit_text = u["text"]
            # 精确匹配或包含匹配
            if unit_text in kw_map:
                raw = kw_map[unit_text]
            else:
                # 没被提取为关键词的单位给一个基础分
                raw = 0.3 if not u.get("is_punctuation") else 0.15
            # 缩放并裁剪
            score = max(
                self._score_min,
                min(self._score_max, raw * self._score_max),
            )
            scores.append({"text": unit_text, "score": round(score, 4), "unit_index": i})

        return scores

    # ------------------------------------------------------------------ #
    #                   Layer 3: embedding 评分（占位）                    #
    # ------------------------------------------------------------------ #

    def _score_embedding(
        self, text: str, units: list[dict]
    ) -> list[dict] | None:
        """
        本地 embedding 模型评分。
        原型阶段仅预留接口，返回 None 触发降级。
        """
        # TODO: 后续可接入 sentence-transformers 小模型
        return None

    # ------------------------------------------------------------------ #
    #                   Layer 4: API 评分（占位）                          #
    # ------------------------------------------------------------------ #

    def _score_api(
        self, text: str, units: list[dict]
    ) -> list[dict] | None:
        """
        远程 API 评分。
        原型阶段仅预留接口，返回 None 触发降级。
        """
        # TODO: 后续可接入 HTTP 评分服务
        return None

    # ------------------------------------------------------------------ #
    #                         热加载                                       #
    # ------------------------------------------------------------------ #

    def update_config(self, config: dict):
        """热加载时更新评分器配置。"""
        if "enable_importance_scoring" in config:
            self._enabled = bool(config["enable_importance_scoring"])
        if "importance_mode" in config:
            val = config["importance_mode"]
            if val in ("none", "rule", "keyword", "embedding", "api"):
                self._mode = val
        if "importance_backend" in config:
            self._backend = config["importance_backend"]
        if "importance_fallback_order" in config:
            val = config["importance_fallback_order"]
            if isinstance(val, list):
                self._fallback_order = val
        if "importance_score_min" in config:
            self._score_min = float(config["importance_score_min"])
        if "importance_score_max" in config:
            self._score_max = float(config["importance_score_max"])
        if "importance_to_er_scale" in config:
            self._to_er_scale = float(config["importance_to_er_scale"])
        # 规则参数
        for key in self._rule_config:
            cfg_key = key  # 配置中的键名与规则内部键名一致
            if cfg_key in config:
                self._rule_config[key] = float(config[cfg_key])
