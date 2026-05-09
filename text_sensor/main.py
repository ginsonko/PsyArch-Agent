# -*- coding: utf-8 -*-
"""
AP 文本感受器（Text Sensor, TS）— 主模块
=========================================
AP 接口层第一入口。负责将原始文本转化为 SA/CSA 并输出统一刺激包。

对外接口:
  1. ingest_text()         — 核心输入接口
  2. reload_config()       — 热加载配置
  3. get_runtime_snapshot() — 查看运行态快照
  4. clear_echo_pool()     — 清空残响池（高风险）

职责边界:
  ✓ 文本接收、归一化、切分、SA/CSA 生成、初始刺激赋能、残响管理、输出刺激包
  ✗ 不负责状态池维护、结构生成、行动选择、情绪调制、语义理解
"""

import copy
from collections import deque
import os
import time
import traceback
from pathlib import Path
from typing import Any

# ---- 子模块 ----
from ._normalizer import TextNormalizer
from ._segmenter import TextSegmenter
from ._importance_scorer import ImportanceScorer
from ._echo_manager import EchoManager
from ._object_builder import (
    build_feature_sa,
    build_attribute_sa,
    build_csa,
    build_sensor_frame,
    build_echo_frame,
    build_stimulus_packet,
)
from ._logger import ModuleLogger
from ._text_integrity import sanitize_text_input
from . import __version__, __schema_version__, __module_name__


# ====================================================================== #
#                          配置加载工具                                    #
# ====================================================================== #


def _load_yaml_config(path: str) -> dict:
    """
    加载 YAML 配置文件。加载失败返回空 dict。
    PyYAML 是本模块唯一强依赖。
    """
    try:
        import yaml

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except ImportError:
        # PyYAML 未安装时用空配置（所有参数用代码内默认值）
        return {}
    except Exception:
        return {}


# ====================================================================== #
#                          默认配置                                       #
# ====================================================================== #

_DEFAULT_CONFIG = {
    # ---- 模式控制 ----
    "default_mode": "simple",           # simple | advanced | hybrid
    "enable_char_output": True,
    "enable_token_output": False,
    "enable_csa_output": True,

    # ---- 分词 ----
    "tokenizer_backend": "none",
    "tokenizer_fallback_to_char": True,
    "custom_tokenizer_module_path": "",
    "enable_user_dict": False,
    "user_dict_path": "",

    # ---- 重要性评分 ----
    "enable_importance_scoring": False,
    "importance_mode": "rule",
    "importance_backend": "builtin_rule",
    "importance_score_min": 0.2,
    "importance_score_max": 1.5,
    "importance_to_er_scale": 1.0,
    "importance_fallback_order": ["keyword", "rule", "none"],
    "attribute_er_ratio": 0.25,
    "attribute_ev_ratio": 0.0,
    # ---- 属性刺激元开关（stimulus_intensity）----
    # 中文: 是否为每个特征 SA 自动生成一个数值属性刺激元 stimulus_intensity:*（也称“强度属性 SA”）。
    # English: When enabled, emit an attribute SA `stimulus_intensity:<value>` for each feature SA.
    #
    # 说明:
    # - 关闭时: 仍会输出 CSA（如果 enable_csa_output=true），但 CSA 仅包含 1 个成员（锚点特征 SA）。
    # - 打开时: 行为回到旧逻辑（每个特征 SA 额外绑定 1 个 stimulus_intensity 属性 SA）。
    #
    # 为什么要提供这个开关:
    # - 可读性/验收: 关闭后不会在状态池与结构中出现大量 `stimulus_intensity:0.4235` 之类的属性 token，
    #   更方便观察其它模块的行为。
    "enable_stimulus_intensity_attribute_sa": False,
    # 中文: 只有当特征 SA 的 ER 不低于该阈值时，才生成 stimulus_intensity 属性 SA。
    # English: Only emit `stimulus_intensity:*` attribute SA when the feature SA ER reaches this threshold.
    #
    # 说明:
    # - 默认 0.0 表示保持旧行为：只要开关打开，就对每个特征 SA 生成数值属性 SA。
    # - 提高该值可以抑制弱标点/弱噪音带来的属性 SA 膨胀，是后续性能-效果折中的低风险抓手。
    "stimulus_intensity_attribute_min_er": 0.0,

    # ---- 刺激量参数 ----
    "char_base_er": 1.0,
    "token_base_er": 1.1,
    "punctuation_er_ratio": 0.35,
    "whitespace_er_ratio": 0.1,
    "emoji_er_ratio": 1.2,
    "digit_er_ratio": 0.8,
    "question_mark_boost": 1.1,
    "exclamation_mark_boost": 1.1,

    # ---- 残响 ----
    "enable_echo": True,
    "echo_decay_mode": "round_factor",
    "echo_round_decay_factor": 0.4,
    "echo_half_life_rounds": 2.0,
    "echo_min_energy_threshold": 0.08,
    "echo_pool_max_frames": 10,
    "echo_frame_elimination_strategy": "oldest_lowest_energy",
    "include_echoes_in_stimulus_packet_objects": True,

    # ---- 刺激疲劳 ----
    "enable_stimulus_fatigue": True,
    "stimulus_fatigue_window_rounds": 100,
    "stimulus_fatigue_threshold_count": 10,
    "stimulus_fatigue_max_suppression": 1.0,

    # ---- 文本处理 ----
    "max_text_length": 10000,
    "allow_empty_text": False,
    "reject_suspect_encoding_text": True,

    # ---- 归一化 ----
    "strip_control_chars": True,
    "fullwidth_to_halfwidth": False,
    "case_policy": "none",
    "compress_whitespace": False,
    "strip_edges": True,

    # ---- 日志 ----
    "log_dir": "",
    "log_max_file_bytes": 5 * 1024 * 1024,
}


# ====================================================================== #
#                       TextSensor 主类                                   #
# ====================================================================== #


class TextSensor:
    """
    AP 文本感受器主类。

    使用示例:
        sensor = TextSensor()
        result = sensor.ingest_text(text="你好呀！", trace_id="tick_001")
    """

    def __init__(self, config_path: str = "", config_override: dict | None = None):
        """
        初始化文本感受器。

        参数:
            config_path: YAML 配置文件路径；为空则使用默认路径
            config_override: 直接传入配置 dict（优先级高于文件）
        """
        # Step 1: 合并配置
        self._config_path = config_path or os.path.join(
            os.path.dirname(__file__), "config", "text_sensor_config.yaml"
        )
        self._config = self._build_config(config_override)

        # Step 2: 初始化子模块
        self._logger = ModuleLogger(
            log_dir=self._config.get("log_dir", ""),
            max_file_bytes=self._config.get("log_max_file_bytes", 5 * 1024 * 1024),
        )
        self._normalizer = TextNormalizer(self._config)
        self._segmenter = TextSegmenter(self._config)
        self._scorer = ImportanceScorer(self._config)
        self._echo_mgr = EchoManager(self._config)

        # Step 3: 运行统计
        self._frame_counter: int = 0     # 帧计数器
        self._total_calls: int = 0       # 总调用次数
        self._total_sa_created: int = 0  # 累计创建 SA 数
        self._ingest_round: int = 0      # 输入轮次计数
        self._stimulus_round_history: dict[str, deque[int]] = {}

    # ================================================================== #
    #         接口一: ingest_text — 核心输入接口                           #
    # ================================================================== #

    def ingest_text(
        self,
        text: str,
        trace_id: str,
        tick_id: str | None = None,
        source_type: str = "external_user_input",
        source_id: str | None = None,
        timestamp_ms: int | None = None,
        mode_override: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """
        接收文本并输出本轮文本刺激结果。

        完整处理流程:
          1. 参数校验
          2. 衰减感受器残响池
          3. 文本归一化
          4. 切分（字符级 / 词元级 / 混合）
          5. 重要性评分
          6. 刺激量映射 → 生成特征SA
          7. （可选）为每个特征SA 生成属性SA（stimulus_intensity 数值刺激元）
          8. 构建 CSA（特征SA + 可选属性SA）
          9. 构建 sensor_frame
          10. 注册残响帧
          11. 构建 stimulus_packet
          12. 日志 & 返回

        返回:
            AP 标准统一返回结构
        """
        start_time = time.time()
        tick_id = tick_id or trace_id
        self._ingest_round += 1
        sensor_round = self._ingest_round

        # ---- Step 1: 参数校验 ----
        prepared_text, validation_error, input_integrity = self._prepare_input_text(
            text, trace_id, mode_override
        )
        if validation_error:
            self._logger.error(
                trace_id=trace_id,
                interface="ingest_text",
                code=validation_error["code"],
                message=validation_error["message"],
                detail=validation_error.get("detail"),
            )
            return self._make_response(
                success=False,
                code=validation_error["code"],
                message=validation_error["message"],
                error=validation_error,
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )
        text = str(prepared_text or "")
        if (input_integrity or {}).get("status") == "repaired":
            self._logger.detail(
                trace_id=trace_id,
                step="text_integrity_repair",
                info=input_integrity,
            )

        # ---- Step 2: 衰减感受器残响池 ----
        decay_summary = self._echo_mgr.decay_and_clean()

        self._logger.detail(
            trace_id=trace_id,
            step="echo_decay",
            info=decay_summary,
        )

        # ---- Step 3: 文本归一化 ----
        normalized = self._normalizer.normalize(text)

        # ---- 确定运行模式 ----
        mode = mode_override or self._config.get("default_mode", "simple")

        # ---- Step 4: 切分 ----
        char_units: list[dict] = []
        token_units: list[dict] = []
        tokenizer_fallback = False

        if mode == "simple":
            char_units = self._segmenter.segment_chars(normalized)
        elif mode == "advanced":
            token_units, tokenizer_fallback = self._segmenter.segment_tokens(normalized)
            if tokenizer_fallback:
                # 分词器缺失/不可用时自动回退到字符切分：不应作为“错误”阻断或误导观测。
                # 对齐验收口径：检测不到 jieba 等依赖时，自动关闭分词并继续运行。
                requested = str(getattr(self._segmenter, "requested_backend", self._config.get("tokenizer_backend", "none")) or "none")
                missing = str(getattr(self._segmenter, "missing_backend", "") or "")
                # 仅当用户“明确请求了外部分词后端”时才记录提示；tokenizer_backend=none 属于正常字符模式。
                if requested not in ("none", "char", "chars", ""):
                    note = "分词器不可用，已自动回退到字符切分 / Tokenizer unavailable, auto-fell back to char mode"
                    if missing:
                        note = f"未检测到依赖 {missing}，已自动关闭分词并回退到字符切分 / Missing {missing}, tokenizer disabled (char fallback)"
                    self._logger.detail(
                        trace_id=trace_id,
                        step="tokenizer_fallback",
                        info={
                            "mode": mode,
                            "requested_backend": requested,
                            "missing_backend": missing,
                            "fallback_to_char": True,
                            "note": note,
                        },
                    )
                # 降级后 token_units 已经是字符列表
        elif mode == "hybrid":
            char_units = self._segmenter.segment_chars(normalized)
            token_units, tokenizer_fallback = self._segmenter.segment_tokens(normalized)
            if tokenizer_fallback:
                requested = str(getattr(self._segmenter, "requested_backend", self._config.get("tokenizer_backend", "none")) or "none")
                missing = str(getattr(self._segmenter, "missing_backend", "") or "")
                if requested not in ("none", "char", "chars", ""):
                    note = "混合模式下分词器不可用，词元级已关闭（保留字符级） / Tokenizer unavailable in hybrid mode; token-level disabled"
                    if missing:
                        note = f"未检测到依赖 {missing}，已自动关闭分词（保留字符级） / Missing {missing}, tokenizer disabled (hybrid keeps char)"
                    self._logger.detail(
                        trace_id=trace_id,
                        step="tokenizer_fallback",
                        info={
                            "mode": mode,
                            "requested_backend": requested,
                            "missing_backend": missing,
                            "fallback_to_char": True,
                            "note": note,
                        },
                    )
                token_units = []  # 混合模式下降级则只保留字符

        # 合并为统一的"工作单位列表"
        # 字符和词元是不同粒度的特征SA，各自生成独立的 SA/CSA
        all_units = []
        if mode == "simple" or (mode == "hybrid" and char_units):
            all_units.extend(("char", u) for u in char_units)
        if mode in ("advanced", "hybrid") and token_units:
            all_units.extend(("token", u) for u in token_units)

        # ---- Step 5: 重要性评分 ----
        # 分别对字符组和词元组评分
        importance_summaries = []
        char_scores_map: dict[int, float] = {}
        token_scores_map: dict[int, float] = {}

        if char_units:
            char_imp = self._scorer.score(normalized, char_units)
            importance_summaries.append({"group": "char", **char_imp})
            for s in char_imp.get("scores", []):
                char_scores_map[s["unit_index"]] = s["score"]

        if token_units:
            token_imp = self._scorer.score(normalized, token_units)
            importance_summaries.append({"group": "token", **token_imp})
            for s in token_imp.get("scores", []):
                token_scores_map[s["unit_index"]] = s["score"]

        # ---- Step 6~8: 生成 SA → 属性SA → CSA ----
        all_feature_sas: list[dict] = []
        all_attribute_sas: list[dict] = []
        all_csas: list[dict] = []
        enable_intensity_attr_sa = bool(self._config.get("enable_stimulus_intensity_attribute_sa", False))
        intensity_attr_min_er = max(0.0, float(self._config.get("stimulus_intensity_attribute_min_er", 0.0) or 0.0))
        fatigue_history_keys: list[str] = []
        fatigue_records: list[dict] = []
        total_er_before_fatigue = 0.0
        total_er_after_fatigue = 0.0
        global_seq = 0

        for kind, unit in all_units:
            if kind == "char":
                base_er = self._config.get("char_base_er", 1.0)
                score = char_scores_map.get(unit["position"], 1.0)
            else:
                base_er = self._config.get("token_base_er", 1.1)
                score = token_scores_map.get(unit["position"], 1.0)

            type_ratio = self._get_type_ratio(unit)
            importance_scale = self._config.get("importance_to_er_scale", 1.0)
            er_before_fatigue = round(base_er * type_ratio * score * importance_scale, 6)
            fatigue_key = self._build_stimulus_fatigue_key(kind=kind, unit=unit)
            fatigue_state = self._compute_stimulus_fatigue(
                fatigue_key=fatigue_key,
                current_round=sensor_round,
            )
            er = round(max(0.0, er_before_fatigue * (1.0 - fatigue_state["suppression_ratio"])), 6)
            attribute_er = 0.0
            attribute_ev = 0.0
            should_emit_intensity_attr = enable_intensity_attr_sa and er >= intensity_attr_min_er
            if should_emit_intensity_attr:
                attribute_er = round(er * self._config.get("attribute_er_ratio", 0.25), 6)
                attribute_ev = round(er * self._config.get("attribute_ev_ratio", 0.0), 6)

            feature_sa = build_feature_sa(
                char_or_token=unit["text"],
                unit_kind=kind,
                char_type=unit.get("char_type", "other"),
                position=unit.get("position", 0),
                er=er,
                trace_id=trace_id,
                tick_id=tick_id,
                source_type=source_type,
                source_id=source_id or "",
                is_punctuation=unit.get("is_punctuation", False),
                is_whitespace=unit.get("is_whitespace", False),
                is_emoji=unit.get("is_emoji", False),
                global_sequence_index=global_seq,
                group_index=0,
            )
            self._attach_sensor_fatigue_debug(
                sa_obj=feature_sa,
                fatigue_state=fatigue_state,
                fatigue_key=fatigue_key,
                er_before_fatigue=er_before_fatigue,
                er_after_fatigue=er,
                sensor_round=sensor_round,
            )
            all_feature_sas.append(feature_sa)

            attr_sa = None
            if should_emit_intensity_attr:
                attr_sa = build_attribute_sa(
                    attribute_name="stimulus_intensity",
                    attribute_value=er,
                    parent_feature_sa_id=feature_sa["id"],
                    trace_id=trace_id,
                    tick_id=tick_id,
                    source_type=source_type,
                    source_id=source_id or "",
                    er=attribute_er,
                    ev=attribute_ev,
                )
                self._attach_sensor_fatigue_debug(
                    sa_obj=attr_sa,
                    fatigue_state=fatigue_state,
                    fatigue_key=f"{fatigue_key}::attribute",
                    er_before_fatigue=round(er_before_fatigue * self._config.get("attribute_er_ratio", 0.25), 6),
                    er_after_fatigue=attribute_er,
                    sensor_round=sensor_round,
                )
                all_attribute_sas.append(attr_sa)

            if self._config.get("enable_csa_output", True):
                attribute_sas_for_csa: list[dict] = []
                if attr_sa is not None:
                    attribute_sas_for_csa = [attr_sa]

                csa = build_csa(
                    feature_sa=feature_sa,
                    attribute_sas=attribute_sas_for_csa,
                    trace_id=trace_id,
                    tick_id=tick_id,
                    source_type=source_type,
                    source_id=source_id or "",
                )
                all_csas.append(csa)

            fatigue_history_keys.append(fatigue_key)
            fatigue_records.append(
                {
                    "key": fatigue_key,
                    "display": unit.get("text", ""),
                    "suppression_ratio": fatigue_state["suppression_ratio"],
                    "window_count": fatigue_state["window_count"],
                    "threshold_count": fatigue_state["threshold_count"],
                    "er_before_fatigue": er_before_fatigue,
                    "er_after_fatigue": er,
                }
            )
            total_er_before_fatigue += er_before_fatigue
            total_er_after_fatigue += er
            global_seq += 1

        self._register_stimulus_history(fatigue_history_keys, sensor_round)
        fatigue_summary = {
            "enabled": bool(self._config.get("enable_stimulus_fatigue", True)),
            "current_round": sensor_round,
            "tracked_key_count": len(self._stimulus_round_history),
            "window_rounds": int(self._config.get("stimulus_fatigue_window_rounds", 100)),
            "threshold_count": int(self._config.get("stimulus_fatigue_threshold_count", 10)),
            "max_suppression": float(self._config.get("stimulus_fatigue_max_suppression", 1.0)),
            "suppressed_unit_count": sum(1 for item in fatigue_records if float(item.get("suppression_ratio", 0.0)) > 0.0),
            "zero_er_unit_count": sum(1 for item in fatigue_records if float(item.get("er_after_fatigue", 0.0)) <= 0.0),
            "total_er_before_fatigue": round(total_er_before_fatigue, 6),
            "total_er_after_fatigue": round(total_er_after_fatigue, 6),
            "total_er_suppressed": round(max(0.0, total_er_before_fatigue - total_er_after_fatigue), 6),
            "top_suppressed_units": sorted(
                fatigue_records,
                key=lambda item: float(item.get("suppression_ratio", 0.0)),
                reverse=True,
            )[:12],
        }

        # 所有 SA（特征 + 属性）
        all_sas = all_feature_sas + all_attribute_sas
        self._total_sa_created += len(all_sas)

        # ---- Step 9: 构建 sensor_frame ----
        self._frame_counter += 1
        sensor_frame = build_sensor_frame(
            input_text=text,
            normalized_text=normalized,
            segmentation_mode=mode,
            sa_list=all_sas,
            csa_list=all_csas,
            trace_id=trace_id,
            tick_id=tick_id,
            source_type=source_type,
            source_id=source_id or "",
            frame_no=self._frame_counter,
        )

        # ---- Step 10: 注册残响帧 ----
        if self._config.get("enable_echo", True):
            # 深拷贝 SA/CSA 作为残响副本（残响独立衰减，不影响原始对象）。
            # 这里必须复制完整 SA 集合，而不只是 feature SA，
            # 否则 echo 中的 CSA 会丢失属性成员，无法保持“实时能量 = 成员 SA 之和”。
            echo_sa_copy = copy.deepcopy(all_sas)
            echo_csa_copy = copy.deepcopy(all_csas)
            echo_frame = build_echo_frame(
                origin_frame=sensor_frame,
                sa_items=echo_sa_copy,
                csa_items=echo_csa_copy,
                round_created=self._echo_mgr.current_round,
                trace_id=trace_id,
                tick_id=tick_id,
            )
            self._echo_mgr.register_echo(echo_frame)

        # ---- Step 11: 构建 stimulus_packet ----
        active_echoes = self._echo_mgr.get_active_echo_frames()
        # 排除当前刚注册的帧（当前帧已在 current_* 中传递）
        # 残响池中最后一帧就是刚注册的，将其排除以避免重复
        if active_echoes and self._config.get("enable_echo", True):
            echo_for_packet = active_echoes[:-1]  # 历史残响帧（不含当前帧）
        else:
            echo_for_packet = []

        stimulus_packet = build_stimulus_packet(
            current_frame=sensor_frame,
            current_sa_items=all_sas,
            current_csa_items=all_csas,
            echo_frames=echo_for_packet,
            trace_id=trace_id,
            tick_id=tick_id,
            include_echo_in_objects=self._config.get(
                "include_echoes_in_stimulus_packet_objects", False
            ),
            goal_b_char_sa_string_mode=bool(self._config.get("enable_goal_b_char_sa_string_mode", False)),
        )

        # ---- Step 12: 日志 & 返回 ----
        self._total_calls += 1
        elapsed = self._elapsed_ms(start_time)

        # Brief 日志
        self._logger.brief(
            trace_id=trace_id,
            interface="ingest_text",
            success=True,
            input_summary={
                "text_len": len(text),
                "mode": mode,
                "tokenizer": self._segmenter.backend_name,
                "tokenizer_fallback": tokenizer_fallback,
            },
            output_summary={
                "feature_sa_count": len(all_feature_sas),
                "attribute_sa_count": len(all_attribute_sas),
                "csa_count": len(all_csas),
                "echo_pool_size": self._echo_mgr.pool_size,
                "total_er": round(
                    sum(sa["energy"]["er"] for sa in all_sas), 4
                ),
            },
        )

        # Detail 日志
        self._logger.detail(
            trace_id=trace_id,
            step="ingest_text_complete",
            info={
                "normalized_text": normalized,
                "char_units_count": len(char_units),
                "token_units_count": len(token_units),
                "importance_summaries": importance_summaries,
                "echo_decay_summary": decay_summary,
                "fatigue_summary": fatigue_summary,
                "elapsed_ms": elapsed,
            },
        )

        return self._make_response(
            success=True,
            code="OK",
            message="文本感受成功 / Text ingestion succeeded",
            data={
                "sensor_frame": sensor_frame,
                "echo_frames_used": [ef["id"] for ef in echo_for_packet],
                "stimulus_packet": stimulus_packet,
                "tokenization_summary": {
                    "mode": mode,
                    "char_units": len(char_units),
                    "token_units": len(token_units),
                    "tokenizer_backend": self._segmenter.backend_name,
                    "tokenizer_fallback": tokenizer_fallback,
                },
                "input_integrity": input_integrity or {
                    "status": "clean",
                    "detail": {"reason": "ok"},
                },
                "importance_summary": importance_summaries,
                "echo_decay_summary": decay_summary,
                "fatigue_summary": fatigue_summary,
                "stats": {
                    "feature_sa_count": len(all_feature_sas),
                    "attribute_sa_count": len(all_attribute_sas),
                    "csa_count": len(all_csas),
                    "total_er": round(
                        sum(sa["energy"]["er"] for sa in all_sas), 4
                    ),
                },
            },
            trace_id=trace_id,
            elapsed_ms=elapsed,
        )

    # ================================================================== #
    #         接口二: reload_config — 热加载配置                           #
    # ================================================================== #

    def reload_config(
        self,
        trace_id: str,
        config_path: str | None = None,
        apply_partial: bool = True,
    ) -> dict:
        """
        显式触发热加载配置。
        非法字段不覆盖旧值，合法字段即时生效。
        """
        start_time = time.time()
        path = config_path or self._config_path

        try:
            new_raw = _load_yaml_config(path)
            if not new_raw:
                return self._make_response(
                    success=False,
                    code="CONFIG_ERROR",
                    message=f"配置文件加载失败或为空 / Config file failed to load or empty: {path}",
                    trace_id=trace_id,
                    elapsed_ms=self._elapsed_ms(start_time),
                )

            # 逐字段校验并合并
            applied = []
            rejected = []
            for key, val in new_raw.items():
                if key in _DEFAULT_CONFIG:
                    expected_type = type(_DEFAULT_CONFIG[key])
                    if isinstance(val, expected_type) or (
                        expected_type is float and isinstance(val, (int, float))
                    ):
                        self._config[key] = val
                        applied.append(key)
                    else:
                        rejected.append({
                            "key": key,
                            "reason": f"类型不匹配 / Type mismatch: 期望/expected {expected_type.__name__}, 实际/actual {type(val).__name__}",
                        })
                else:
                    # 未知字段：允许忽略，记录 warning
                    rejected.append({"key": key, "reason": "未知配置项 / Unknown config key"})

            # 通知子模块更新
            self._normalizer.update_config(self._config)
            self._segmenter.update_config(self._config)
            self._scorer.update_config(self._config)
            self._echo_mgr.update_config(self._config)
            self._logger.update_config(
                log_dir=self._config.get("log_dir", ""),
                max_file_bytes=self._config.get("log_max_file_bytes", 0),
            )

            # 日志
            self._logger.brief(
                trace_id=trace_id,
                interface="reload_config",
                success=True,
                input_summary={"path": path},
                output_summary={
                    "applied_count": len(applied),
                    "rejected_count": len(rejected),
                },
            )

            if rejected:
                self._logger.error(
                    trace_id=trace_id,
                    interface="reload_config",
                    code="CONFIG_ERROR",
                    message=f"部分配置项被拒绝 / Some config items rejected: {len(rejected)} 项/items",
                    detail={"rejected": rejected},
                )

            return self._make_response(
                success=True,
                code="OK",
                message=f"热加载完成 / Hot reload done: {len(applied)} 项生效/applied, {len(rejected)} 项拒绝/rejected",
                data={"applied": applied, "rejected": rejected},
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

        except Exception as e:
            msg = f"热加载异常 / Hot reload exception: {e}"
            self._logger.error(
                trace_id=trace_id,
                interface="reload_config",
                code="CONFIG_ERROR",
                message=msg,
                detail={"traceback": traceback.format_exc()},
            )
            return self._make_response(
                success=False,
                code="CONFIG_ERROR",
                message=msg,
                trace_id=trace_id,
                elapsed_ms=self._elapsed_ms(start_time),
            )

    # ================================================================== #
    #         接口三: get_runtime_snapshot — 运行态快照                    #
    # ================================================================== #

    def get_runtime_snapshot(self, trace_id: str = "snapshot") -> dict:
        """查看当前运行状态，用于调试。"""
        return self._make_response(
            success=True,
            code="OK",
            message="运行态快照 / Runtime snapshot",
            data={
                "version": __version__,
                "schema_version": __schema_version__,
                "config_summary": {
                    "default_mode": self._config.get("default_mode"),
                    # Tokenizer / 分词
                    # tokenizer_backend_config: 用户配置中请求的后端
                    # tokenizer_backend_effective: 实际生效后端（缺失依赖时会自动退化到 char）
                    # tokenizer_backend: 向后兼容字段（旧版观测台/测试用）— 等同于 tokenizer_backend_effective
                    "tokenizer_backend": self._segmenter.backend_name,
                    "tokenizer_backend_config": self._config.get("tokenizer_backend"),
                    "tokenizer_backend_effective": self._segmenter.backend_name,
                    "tokenizer_available": bool(self._segmenter.tokenizer_available),
                    "tokenizer_missing_backend": str(getattr(self._segmenter, "missing_backend", "") or ""),
                    "importance_mode": self._config.get("importance_mode"),
                    "enable_echo": self._config.get("enable_echo"),
                    "enable_stimulus_intensity_attribute_sa": self._config.get("enable_stimulus_intensity_attribute_sa"),
                    "echo_decay_mode": self._config.get("echo_decay_mode"),
                    "echo_round_decay_factor": self._config.get("echo_round_decay_factor"),
                    "echo_half_life_rounds": self._config.get("echo_half_life_rounds"),
                    "enable_stimulus_fatigue": self._config.get("enable_stimulus_fatigue"),
                    "stimulus_fatigue_window_rounds": self._config.get("stimulus_fatigue_window_rounds"),
                    "stimulus_fatigue_threshold_count": self._config.get("stimulus_fatigue_threshold_count"),
                    "stimulus_fatigue_max_suppression": self._config.get("stimulus_fatigue_max_suppression"),
                },
                "echo_pool_summary": {
                    "pool_size": self._echo_mgr.pool_size,
                    "current_round": self._echo_mgr.current_round,
                },
                "statistics": {
                    "total_calls": self._total_calls,
                    "total_frames": self._frame_counter,
                    "total_sa_created": self._total_sa_created,
                    "ingest_round": self._ingest_round,
                    "fatigue_history_key_count": len(self._stimulus_round_history),
                },
            },
            trace_id=trace_id,
            elapsed_ms=0,
        )

    # ================================================================== #
    #         接口四: clear_echo_pool — 清空残响池                         #
    # ================================================================== #

    def clear_echo_pool(self, trace_id: str) -> dict:
        """
        清空感受器残响池。高风险操作，带审计日志。
        """
        audit = self._echo_mgr.clear()
        fatigue_key_count = len(self._stimulus_round_history)
        self._stimulus_round_history.clear()
        self._ingest_round = 0
        audit["cleared_fatigue_key_count"] = fatigue_key_count

        self._logger.error(
            trace_id=trace_id,
            interface="clear_echo_pool",
            code="AUDIT_HIGH_RISK",
            message=f"残响池已清空 / Echo pool cleared: {audit['cleared_frame_count']} 帧被移除/frames removed",
            detail=audit,
        )

        return self._make_response(
            success=True,
            code="OK",
            message=f"残响池已清空 / Echo pool cleared: {audit['cleared_frame_count']} 帧被移除/frames removed",
            data=audit,
            trace_id=trace_id,
            elapsed_ms=0,
        )

    # ================================================================== #
    #                     内部辅助方法                                     #
    # ================================================================== #

    def _build_config(self, override: dict | None) -> dict:
        """
        构建最终配置: 默认值 → YAML 文件 → 代码传入覆盖。
        """
        cfg = dict(_DEFAULT_CONFIG)

        # 从 YAML 文件加载
        file_cfg = _load_yaml_config(self._config_path)
        if file_cfg:
            cfg.update(file_cfg)

        # 代码覆盖
        if override:
            cfg.update(override)

        return cfg

    def preflight_input_text(
        self, text: Any, *, trace_id: str = "preflight", mode_override: Any = None
    ) -> dict[str, Any]:
        prepared_text, error, integrity = self._prepare_input_text(
            text, trace_id, mode_override
        )
        return {
            "success": error is None,
            "text": str(prepared_text or "") if error is None else "",
            "error": error,
            "integrity": integrity
            or {"status": "clean", "detail": {"reason": "ok"}},
        }

    def _prepare_input_text(
        self, text: Any, trace_id: Any, mode_override: Any
    ) -> tuple[str | None, dict | None, dict[str, Any] | None]:
        """
        输入预检。返回 (prepared_text, error, integrity_meta)。
        """
        # text 类型检查
        if not isinstance(text, str):
            return None, {
                "code": "INPUT_VALIDATION_ERROR",
                "message": f"参数 text 类型错误 / Parameter 'text' type error: 期望/expected str, 实际/actual {type(text).__name__}",
                "detail": {"param": "text", "actual_type": type(text).__name__},
            }, None

        # trace_id 必填
        if not trace_id or not isinstance(trace_id, str):
            return None, {
                "code": "INPUT_VALIDATION_ERROR",
                "message": "参数 trace_id 必填且必须为非空字符串 / Parameter 'trace_id' is required and must be a non-empty string",
                "detail": {"param": "trace_id"},
            }, None

        # mode_override 校验
        if mode_override is not None:
            valid_modes = ("simple", "advanced", "hybrid")
            if mode_override not in valid_modes:
                return None, {
                    "code": "INPUT_VALIDATION_ERROR",
                    "message": f"mode_override 值不合法 / Invalid mode_override '{mode_override}', 可选/valid: {valid_modes}",
                    "detail": {"param": "mode_override", "actual": mode_override},
                }, None

        prepared_text = str(text)
        integrity_meta: dict[str, Any] = {
            "status": "clean",
            "detail": {"reason": "ok"},
        }
        if self._config.get("reject_suspect_encoding_text", True):
            sanitized = sanitize_text_input(prepared_text)
            integrity_meta = {
                "status": str(sanitized.get("status") or "clean"),
                "detail": dict(sanitized.get("detail") or {}),
            }
            if not bool(sanitized.get("ok", False)):
                return None, {
                    "code": "INPUT_TEXT_INTEGRITY_ERROR",
                    "message": "输入文本疑似编码异常或已丢失原始字符，已在进入状态链路前拒绝 / Input text looks mojibaked or irrecoverably unreadable; rejected before ingestion",
                    "detail": integrity_meta,
                }, integrity_meta
            prepared_text = str(sanitized.get("text") or "")

        # 空文本检查
        if len(prepared_text) == 0 and not self._config.get("allow_empty_text", False):
            return None, {
                "code": "INPUT_VALIDATION_ERROR",
                "message": "空文本不被允许（可通过 allow_empty_text 配置开启） / Empty text not allowed (enable via allow_empty_text config)",
                "detail": {"param": "text", "text_len": 0},
            }, integrity_meta

        # 超长文本检查
        max_len = self._config.get("max_text_length", 10000)
        if len(prepared_text) > max_len:
            return None, {
                "code": "INPUT_VALIDATION_ERROR",
                "message": f"文本长度超过上限 / Text length {len(prepared_text)} exceeds max {max_len}",
                "detail": {"param": "text", "text_len": len(prepared_text), "max": max_len},
            }, integrity_meta

        return prepared_text, None, integrity_meta

    def _get_type_ratio(self, unit: dict) -> float:
        """
        根据切分单位的类型获取刺激量系数。
        """
        char_type = unit.get("char_type", "other")
        text = unit.get("text", "")
        cfg = self._config

        if char_type == "punctuation":
            ratio = cfg.get("punctuation_er_ratio", 0.35)
            # 问号和感叹号特殊增强
            if text in ("?", "？"):
                ratio *= cfg.get("question_mark_boost", 1.1)
            elif text in ("!", "！"):
                ratio *= cfg.get("exclamation_mark_boost", 1.1)
            return ratio
        elif char_type == "whitespace":
            return cfg.get("whitespace_er_ratio", 0.1)
        elif char_type == "emoji":
            return cfg.get("emoji_er_ratio", 1.2)
        elif char_type == "digit":
            return cfg.get("digit_er_ratio", 0.8)
        else:
            return 1.0

    def _build_stimulus_fatigue_key(self, *, kind: str, unit: dict) -> str:
        return f"{kind}:{unit.get('text', '')}"

    def _compute_stimulus_fatigue(self, *, fatigue_key: str, current_round: int) -> dict:
        window_rounds = max(1, int(self._config.get("stimulus_fatigue_window_rounds", 100)))
        threshold_count = max(1, int(self._config.get("stimulus_fatigue_threshold_count", 10)))
        max_suppression = max(0.0, min(1.0, float(self._config.get("stimulus_fatigue_max_suppression", 1.0))))
        if not self._config.get("enable_stimulus_fatigue", True):
            return {
                "window_rounds": window_rounds,
                "threshold_count": threshold_count,
                "window_count": 1,
                "suppression_ratio": 0.0,
            }
        history = self._stimulus_round_history.setdefault(fatigue_key, deque())
        min_round = max(1, int(current_round) - window_rounds + 1)
        while history and int(history[0]) < min_round:
            history.popleft()
        window_count = len(history) + 1
        suppression_ratio = 0.0
        if window_count >= threshold_count:
            numerator = window_count - threshold_count + 1
            denominator = max(1, window_rounds - threshold_count + 1)
            suppression_ratio = max_suppression * min(1.0, float(numerator) / float(denominator))
        return {
            "window_rounds": window_rounds,
            "threshold_count": threshold_count,
            "window_count": window_count,
            "suppression_ratio": round(max(0.0, min(max_suppression, suppression_ratio)), 6),
        }

    def _register_stimulus_history(self, fatigue_keys: list[str], current_round: int) -> None:
        if not self._config.get("enable_stimulus_fatigue", True):
            return
        window_rounds = max(1, int(self._config.get("stimulus_fatigue_window_rounds", 100)))
        min_round = max(1, int(current_round) - window_rounds + 1)
        for fatigue_key in fatigue_keys:
            history = self._stimulus_round_history.setdefault(fatigue_key, deque())
            history.append(int(current_round))
            while history and int(history[0]) < min_round:
                history.popleft()

    @staticmethod
    def _attach_sensor_fatigue_debug(
        sa_obj: dict,
        *,
        fatigue_state: dict,
        fatigue_key: str,
        er_before_fatigue: float,
        er_after_fatigue: float,
        sensor_round: int,
    ) -> None:
        sensor_fatigue = {
            "key": fatigue_key,
            "window_rounds": int(fatigue_state.get("window_rounds", 0)),
            "threshold_count": int(fatigue_state.get("threshold_count", 0)),
            "window_count": int(fatigue_state.get("window_count", 0)),
            "suppression_ratio": round(float(fatigue_state.get("suppression_ratio", 0.0)), 6),
            "er_before_fatigue": round(float(er_before_fatigue), 6),
            "er_after_fatigue": round(float(er_after_fatigue), 6),
            "sensor_round": int(sensor_round),
        }
        sa_obj.setdefault("energy", {})["fatigue"] = sensor_fatigue["suppression_ratio"]
        sa_obj.setdefault("ext", {})["sensor_fatigue"] = sensor_fatigue
        meta = sa_obj.setdefault("meta", {})
        meta.setdefault("debug", {})["sensor_fatigue"] = dict(sensor_fatigue)

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        """计算从 start 到当前的毫秒耗时。"""
        return int((time.time() - start) * 1000)

    @staticmethod
    def _make_response(
        success: bool,
        code: str,
        message: str,
        data: Any = None,
        error: Any = None,
        trace_id: str = "",
        elapsed_ms: int = 0,
    ) -> dict:
        """构建 AP 标准统一返回结构。"""
        return {
            "success": success,
            "code": code,
            "message": message,
            "data": data,
            "error": error,
            "meta": {
                "module": __module_name__,
                "interface": "ingest_text",
                "trace_id": trace_id,
                "elapsed_ms": elapsed_ms,
                "logged": True,
            },
        }


# ====================================================================== #
#  命令行入口提示：请使用独立验收脚本进行测试                              #
#  测试入口: python text_sensor/tests/run_verification.py                 #
#  自动测试: python -m pytest text_sensor/tests/ -v                      #
# ====================================================================== #






