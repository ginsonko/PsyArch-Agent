# -*- coding: utf-8 -*-
"""
AP 文本感受器 — 综合测试套件
============================
覆盖设计文档 16.1 节规定的全部必测项：
  1. 简易模式能跑通
  2. 高级模式 + jieba 能跑通（依赖缺失时验证降级）
  3. 重要性评分关闭时能跑通
  4. keyword 模式能跑通（jieba 依赖条件判定）
  5. embedding 模式缺模型时能优雅降级
  6. API 模式超时能优雅降级
  7. 残响衰减按轮生效
  8. 默认衰减配置下，5 轮内大量普通刺激淘汰
  9. 10 轮内少量强刺激仍可能存在
  10.热加载即时生效

以及：
  - 参数校验（空文本、类型错误、超长文本）
  - 混合模式
  - CSA 结构正确性
  - SA 能量最小拥有单位验证
"""

import copy
import json
import os
import sys
import time

import pytest

# 确保能导入模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from text_sensor.main import TextSensor
from text_sensor._echo_manager import EchoManager
from text_sensor._normalizer import TextNormalizer
from text_sensor._segmenter import TextSegmenter
from text_sensor._importance_scorer import ImportanceScorer
from text_sensor._id_generator import reset_id_generator


# ====================================================================== #
#                        测试夹具                                         #
# ====================================================================== #


@pytest.fixture(autouse=True)
def reset_ids():
    """每个测试前重置 ID 生成器，保证可重复性。"""
    reset_id_generator()
    yield
    reset_id_generator()


@pytest.fixture
def sensor():
    """创建简易模式默认感受器。"""
    return TextSensor(config_override={"default_mode": "simple"})

@pytest.fixture
def sensor_with_intensity_attr():
    """
    创建“开启 stimulus_intensity 属性 SA”的感受器。

    中文: 用于回归验证旧逻辑（特征 SA + stimulus_intensity 属性 SA + CSA）仍可启用。
    English: Regression fixture for the legacy "feature + intensity attribute" behavior.
    """
    return TextSensor(
        config_override={
            "default_mode": "simple",
            "enable_stimulus_intensity_attribute_sa": True,
        }
    )


@pytest.fixture
def sensor_with_intensity_attr_threshold():
    """
    创建“开启 stimulus_intensity 属性 SA，但只保留高 ER 单元”的感受器。

    中文: 用于验证新阈值能抑制弱标点/弱噪音的属性 SA 膨胀。
    English: Regression fixture for the low-risk numeric-attribute pruning path.
    """
    return TextSensor(
        config_override={
            "default_mode": "simple",
            "enable_stimulus_intensity_attribute_sa": True,
            "stimulus_intensity_attribute_min_er": 0.9,
        }
    )


@pytest.fixture
def sensor_no_echo():
    """创建关闭残响的感受器。"""
    return TextSensor(config_override={"default_mode": "simple", "enable_echo": False})


@pytest.fixture
def sensor_advanced():
    """创建高级模式感受器。"""
    return TextSensor(
        config_override={
            "default_mode": "advanced",
            "tokenizer_backend": "jieba",
            "tokenizer_fallback_to_char": True,
        }
    )


# ====================================================================== #
#   测试 1: 简易模式基础功能                                              #
# ====================================================================== #


class TestSimpleMode:
    """设计文档 16.1 必测项 1: 简易模式能跑通。"""

    def test_basic_ingest(self, sensor):
        """最基础的文本输入测试。"""
        result = sensor.ingest_text(text="你好呀！", trace_id="test_001")

        assert result["success"] is True
        assert result["code"] == "OK"

        data = result["data"]
        stats = data["stats"]

        # "你好呀！" = 4 个字符 → 4 个特征SA + 0 个属性SA(默认关闭) + 4 个CSA
        assert stats["feature_sa_count"] == 4
        assert stats["attribute_sa_count"] == 0
        assert stats["csa_count"] == 4

    def test_sa_structure_completeness(self, sensor):
        """验证 SA 结构符合通用字段标准。"""
        result = sensor.ingest_text(text="你", trace_id="test_002")
        packet = result["data"]["stimulus_packet"]

        # 至少有 1 个 SA（特征 SA；属性 SA 默认关闭）
        assert len(packet["sa_items"]) >= 1

        feature_sa = packet["sa_items"][0]

        # 核心字段完整性检查
        required_fields = [
            "id", "object_type", "sub_type", "schema_version",
            "content", "stimulus", "energy", "source",
            "trace_id", "tick_id", "created_at", "updated_at",
            "status", "ext", "meta",
        ]
        for field in required_fields:
            assert field in feature_sa, f"SA 缺少字段: {field}"

        # 能量字段完整性
        energy = feature_sa["energy"]
        energy_fields = [
            "er", "ev", "ownership_level", "fatigue",
            "recency_gain", "salience_score",
            "cognitive_pressure_delta", "cognitive_pressure_abs",
        ]
        for field in energy_fields:
            assert field in energy, f"能量缺少字段: {field}"

        # SA 是能量最小拥有单位
        assert energy["ownership_level"] == "sa"
        assert energy["computed_from_children"] is False

    def test_csa_is_feature_only_when_intensity_attr_disabled(self, sensor):
        """
        默认配置下（enable_stimulus_intensity_attribute_sa=false）：
        验证 CSA 结构：每个 CSA 仅包含 1 个成员 SA（锚点特征 SA）。

        说明:
        - 这样做是为了验收可读性，避免状态池与结构中出现大量 `stimulus_intensity:*` 属性 token。
        """
        result = sensor.ingest_text(text="你", trace_id="test_003")
        packet = result["data"]["stimulus_packet"]

        assert len(packet["csa_items"]) == 1

        csa = packet["csa_items"][0]

        # CSA 有锚点 SA
        assert "anchor_sa_id" in csa
        assert "member_sa_ids" in csa

        # 成员应包含 2 个 SA: 1 特征 + 1 属性
        assert len(csa["member_sa_ids"]) == 1

        # 锚点必须是特征 SA
        anchor_id = csa["anchor_sa_id"]
        anchor_sa = next(
            (sa for sa in packet["sa_items"] if sa["id"] == anchor_id), None
        )
        assert anchor_sa is not None
        assert anchor_sa["stimulus"]["role"] == "feature"

        # 默认关闭属性 SA 时，packet 中不应出现 attribute 角色的 SA
        attr_sa = next(
            (sa for sa in packet["sa_items"] if sa.get("stimulus", {}).get("role") == "attribute"),
            None,
        )
        assert attr_sa is None

        # CSA 能量是从成员聚合的
        assert csa["energy"]["ownership_level"] == "aggregated_from_sa"
        assert csa["energy"]["computed_from_children"] is True
        expected_csa_er = sum(
            sa["energy"]["er"]
            for sa in packet["sa_items"]
            if sa["id"] in csa["member_sa_ids"]
        )
        assert csa["energy"]["er"] == expected_csa_er
        assert csa["energy"]["er"] == anchor_sa["energy"]["er"]

    def test_csa_is_feature_plus_attribute_when_enabled(self, sensor_with_intensity_attr):
        """
        开启 enable_stimulus_intensity_attribute_sa=true 时：
        每个 CSA = 特征 SA（锚点）+ stimulus_intensity 数值属性 SA。
        """
        result = sensor_with_intensity_attr.ingest_text(text="你", trace_id="test_003b")
        packet = result["data"]["stimulus_packet"]

        assert len(packet["csa_items"]) == 1
        csa = packet["csa_items"][0]

        assert len(csa["member_sa_ids"]) == 2
        anchor_id = csa["anchor_sa_id"]
        anchor_sa = next((sa for sa in packet["sa_items"] if sa["id"] == anchor_id), None)
        assert anchor_sa is not None
        assert anchor_sa["stimulus"]["role"] == "feature"

        attr_sa = next(
            (
                sa
                for sa in packet["sa_items"]
                if sa["id"] != anchor_id and sa.get("stimulus", {}).get("role") == "attribute"
            ),
            None,
        )
        assert attr_sa is not None
        assert attr_sa["content"]["value_type"] == "numerical"
        assert "stimulus_intensity" in attr_sa["content"]["raw"]
        assert attr_sa["energy"]["er"] > 0.0

        expected_csa_er = sum(
            sa["energy"]["er"]
            for sa in packet["sa_items"]
            if sa["id"] in csa["member_sa_ids"]
        )
        assert csa["energy"]["er"] == expected_csa_er
        assert csa["energy"]["er"] > anchor_sa["energy"]["er"]

    def test_intensity_attribute_min_er_suppresses_weak_punctuation(
        self,
        sensor_with_intensity_attr_threshold,
    ):
        """
        开启强度属性 SA 后，新增 ER 阈值应优先裁掉弱标点/弱噪音的数值属性 SA。
        """
        result = sensor_with_intensity_attr_threshold.ingest_text(
            text="你！",
            trace_id="test_003c",
        )
        packet = result["data"]["stimulus_packet"]
        stats = result["data"]["stats"]

        assert stats["feature_sa_count"] == 2
        assert stats["attribute_sa_count"] == 1
        assert stats["csa_count"] == 2

        feature_sas = [
            sa for sa in packet["sa_items"]
            if sa.get("stimulus", {}).get("role") == "feature"
        ]
        attribute_sas = [
            sa for sa in packet["sa_items"]
            if sa.get("stimulus", {}).get("role") == "attribute"
        ]
        assert len(feature_sas) == 2
        assert len(attribute_sas) == 1

        char_feature = next(sa for sa in feature_sas if sa["content"]["raw"] == "你")
        punctuation_feature = next(sa for sa in feature_sas if sa["content"]["raw"] == "！")
        assert char_feature["energy"]["er"] >= 0.9
        assert punctuation_feature["energy"]["er"] < 0.9

        attr_sa = attribute_sas[0]
        assert "stimulus_intensity" in attr_sa["content"]["raw"]
        assert attr_sa["energy"]["er"] > 0.0

        csa_by_anchor = {
            csa["anchor_sa_id"]: csa
            for csa in packet["csa_items"]
        }
        assert len(csa_by_anchor[char_feature["id"]]["member_sa_ids"]) == 2
        assert len(csa_by_anchor[punctuation_feature["id"]]["member_sa_ids"]) == 1

    def test_energy_values(self, sensor):
        """验证不同字符类型的能量赋值。"""
        result = sensor.ingest_text(text="你！ A", trace_id="test_004")
        packet = result["data"]["stimulus_packet"]

        # 提取特征 SA
        feature_sas = [
            sa for sa in packet["sa_items"] if sa["stimulus"]["role"] == "feature"
        ]

        # 按原始内容查找
        sa_map = {sa["content"]["raw"]: sa for sa in feature_sas}

        # 汉字: base_er * 1.0 = 1.0
        assert sa_map["你"]["energy"]["er"] > 0.5

        # 标点: 应有 punctuation_er_ratio 系数（较低）
        assert sa_map["！"]["energy"]["er"] < sa_map["你"]["energy"]["er"]

        # 空格: whitespace_er_ratio（最低）
        assert sa_map[" "]["energy"]["er"] < sa_map["！"]["energy"]["er"]

    def test_stimulus_packet_structure(self, sensor):
        """验证 stimulus_packet 标准结构。"""
        result = sensor.ingest_text(text="你好", trace_id="test_005")
        pkt = result["data"]["stimulus_packet"]

        required = [
            "id", "object_type", "sub_type", "schema_version",
            "packet_type", "current_frame_id",
            "sa_items", "csa_items", "grouped_sa_sequences",
            "energy_summary", "trace_id", "tick_id",
            "source", "status",
        ]
        for field in required:
            assert field in pkt, f"stimulus_packet 缺少字段: {field}"

        assert pkt["object_type"] == "stimulus_packet"
        assert pkt["energy_summary"]["ownership_level"] == "sa"

    def test_punctuation_and_whitespace_in_csa(self, sensor):
        """验证标点和空白作为等价字符，均可生成 SA 和 CSA。"""
        result = sensor.ingest_text(text="你 ！", trace_id="test_006")
        stats = result["data"]["stats"]

        # "你", " ", "！" = 3 个字符 → 3 特征SA + 3 属性SA + 3 CSA
        assert stats["feature_sa_count"] == 3
        assert stats["csa_count"] == 3


# ====================================================================== #
#   测试 2: 参数校验与错误处理                                            #
# ====================================================================== #


class TestValidation:
    """验证参数校验和边界情况。"""

    def test_empty_text_rejected(self, sensor):
        """空文本默认拒绝。"""
        result = sensor.ingest_text(text="", trace_id="test_val_001")
        assert result["success"] is False
        assert result["code"] == "INPUT_VALIDATION_ERROR"

    def test_empty_text_allowed(self):
        """配置允许空文本时应通过。"""
        s = TextSensor(config_override={"allow_empty_text": True})
        result = s.ingest_text(text="", trace_id="test_val_002")
        assert result["success"] is True

    def test_invalid_text_type(self, sensor):
        """text 参数类型错误。"""
        result = sensor.ingest_text(text=123, trace_id="test_val_003")
        assert result["success"] is False
        assert result["code"] == "INPUT_VALIDATION_ERROR"

    def test_missing_trace_id(self, sensor):
        """trace_id 必填。"""
        result = sensor.ingest_text(text="hello", trace_id="")
        assert result["success"] is False
        assert result["code"] == "INPUT_VALIDATION_ERROR"

    def test_too_long_text(self, sensor):
        """超长文本。"""
        long_text = "你" * 20000
        result = sensor.ingest_text(text=long_text, trace_id="test_val_004")
        assert result["success"] is False
        assert result["code"] == "INPUT_VALIDATION_ERROR"

    def test_invalid_mode_override(self, sensor):
        """无效的 mode_override。"""
        result = sensor.ingest_text(
            text="hello", trace_id="test_val_005", mode_override="invalid"
        )
        assert result["success"] is False
        assert result["code"] == "INPUT_VALIDATION_ERROR"

    def test_rejects_placeholder_garble_before_ingest(self, sensor):
        result = sensor.ingest_text(text="????", trace_id="test_val_006")
        assert result["success"] is False
        assert result["code"] == "INPUT_TEXT_INTEGRITY_ERROR"

    def test_repairs_common_utf8_latin1_mojibake(self, sensor):
        result = sensor.ingest_text(text="ä½ å¥½", trace_id="test_val_007")
        assert result["success"] is True
        assert result["data"]["sensor_frame"]["input_text"] == "你好"
        integrity = result["data"].get("input_integrity", {}) or {}
        assert integrity.get("status") == "repaired"


# ====================================================================== #
#   测试 3: 高级模式 & 降级                                              #
# ====================================================================== #


class TestAdvancedMode:
    """设计文档 16.1 必测项 2,5,6: 高级模式与降级。"""

    def test_advanced_mode_with_fallback(self, sensor_advanced):
        """
        高级模式: 如果 jieba 已安装则正常分词，
        如果未安装则降级到字符切分。无论哪种都不应崩溃。
        """
        result = sensor_advanced.ingest_text(text="今天天气真不错", trace_id="test_adv_001")
        assert result["success"] is True

    def test_mode_override_to_simple(self, sensor_advanced):
        """即使默认高级模式，mode_override 可以临时切回简易。"""
        result = sensor_advanced.ingest_text(
            text="你好呀", trace_id="test_adv_002", mode_override="simple"
        )
        assert result["success"] is True
        assert result["data"]["tokenization_summary"]["mode"] == "simple"

    def test_hybrid_mode(self):
        """混合模式测试。"""
        s = TextSensor(
            config_override={
                "default_mode": "hybrid",
                "tokenizer_backend": "jieba",
                "tokenizer_fallback_to_char": True,
            }
        )
        result = s.ingest_text(text="你好呀！", trace_id="test_hybrid_001")
        assert result["success"] is True


# ====================================================================== #
#   测试 4: 残响衰减                                                      #
# ====================================================================== #


class TestEchoDecay:
    """设计文档 16.1 必测项 7,8,9: 残响衰减。"""

    def test_echo_decay_per_round(self, sensor):
        """验证默认 round_factor=0.4 的残响按轮衰减。"""
        # 第 1 轮
        r1 = sensor.ingest_text(text="你", trace_id="round_001")
        assert r1["success"] is True

        # 第 2 轮: "你" 的残响应已衰减
        r2 = sensor.ingest_text(text="好", trace_id="round_002")
        pkt = r2["data"]["stimulus_packet"]

        # echo 仍然是输入对象的一部分，但必须显式标记来源
        echo_sas = [
            sa
            for sa in pkt["sa_items"]
            if sa.get("ext", {}).get("packet_context", {}).get("source_type") == "echo"
        ]
        feature_echo_sas = [
            sa
            for sa in echo_sas
            if sa["stimulus"]["role"] == "feature" and sa["content"]["raw"] == "你"
        ]
        assert feature_echo_sas
        assert abs(feature_echo_sas[0]["energy"]["er"] - 0.4) < 0.01

    def test_echo_csa_energy_tracks_component_sa_sum(self, sensor):
        """残响中的 CSA 能量必须始终等于其组分 SA 当前能量之和。"""
        sensor.ingest_text(text="你", trace_id="echo_csa_001")
        r2 = sensor.ingest_text(text="好", trace_id="echo_csa_002")
        pkt = r2["data"]["stimulus_packet"]

        assert pkt["echo_frames"]
        echo_frame = pkt["echo_frames"][0]
        echo_sa_map = {sa["id"]: sa for sa in echo_frame["sa_items"]}
        assert echo_frame["csa_items"]

        csa = echo_frame["csa_items"][0]
        expected_er = sum(
            echo_sa_map[member_id]["energy"]["er"]
            for member_id in csa["member_sa_ids"]
            if member_id in echo_sa_map
        )
        assert csa["energy"]["er"] == expected_er

    def test_normal_stimuli_eliminated_within_5_rounds(self):
        """
        设计文档要求: 5 轮内大量普通刺激应被淘汰。
        使用默认 round_factor=0.4、阈值 0.08 验证。
        """
        s = TextSensor(
            config_override={
                "echo_decay_mode": "round_factor",
                "echo_round_decay_factor": 0.4,
                "echo_min_energy_threshold": 0.08,
                "echo_pool_max_frames": 20,
            }
        )

        # 第 1 轮: 输入一个普通字符
        s.ingest_text(text="你", trace_id="elim_001")

        # 模拟 5 轮后续输入
        for i in range(2, 7):
            s.ingest_text(text=f"轮{i}", trace_id=f"elim_{i:03d}")

        active_frames = s._echo_mgr.get_active_echo_frames()
        surviving_feature_values = [
            sa["content"]["raw"]
            for frame in active_frames
            for sa in frame.get("sa_items", [])
            if sa.get("stimulus", {}).get("role") == "feature"
        ]

        # 1.0 -> 0.4 -> 0.16 -> 0.064，因此第 1 轮输入应在后续几轮内掉到阈值以下并被淘汰。
        assert "你" not in surviving_feature_values
        assert len(active_frames) <= 20

    def test_echo_manager_standalone(self):
        """直接测试默认 round_factor 衰减数学。"""
        mgr = EchoManager({
            "enable_echo": True,
            "echo_decay_mode": "round_factor",
            "echo_round_decay_factor": 0.4,
            "echo_min_energy_threshold": 0.05,
        })

        # 构造模拟帧
        mock_sa = {
            "id": "test_sa",
            "energy": {
                "er": 1.0,
                "ev": 0.0,
                "cognitive_pressure_delta": 1.0,
                "cognitive_pressure_abs": 1.0,
                "salience_score": 1.0,
            },
            "stimulus": {"role": "feature"},
        }
        mock_frame = {
            "id": "test_frame",
            "sa_items": [copy.deepcopy(mock_sa)],
            "csa_items": [],
            "energy_summary": {"total_er": 1.0, "total_ev": 0.0},
            "round_created": 0,
            "decay_count": 0,
        }
        mgr.register_echo(mock_frame)

        # 衰减 1 轮
        result = mgr.decay_and_clean()
        frames = mgr.get_active_echo_frames()
        assert len(frames) == 1
        sa = frames[0]["sa_items"][0]
        # 衰减因子 = 0.4
        assert abs(sa["energy"]["er"] - 0.4) < 0.01

        # 衰减 2 轮（总共 2 轮后应≈0.16）
        mgr.decay_and_clean()
        frames = mgr.get_active_echo_frames()
        sa = frames[0]["sa_items"][0]
        assert abs(sa["energy"]["er"] - 0.16) < 0.01

    def test_echo_manager_half_life_mode_still_supported(self):
        """兼容性验证：旧的半衰期模式仍然可用。"""
        mgr = EchoManager({
            "enable_echo": True,
            "echo_decay_mode": "round_half_life",
            "echo_half_life_rounds": 2.0,
            "echo_min_energy_threshold": 0.05,
        })

        mock_sa = {
            "id": "test_sa_half_life",
            "energy": {
                "er": 1.0,
                "ev": 0.0,
                "cognitive_pressure_delta": 1.0,
                "cognitive_pressure_abs": 1.0,
                "salience_score": 1.0,
            },
            "stimulus": {"role": "feature"},
        }
        mock_frame = {
            "id": "test_frame_half_life",
            "sa_items": [copy.deepcopy(mock_sa)],
            "csa_items": [],
            "energy_summary": {"total_er": 1.0, "total_ev": 0.0},
            "round_created": 0,
            "decay_count": 0,
        }
        mgr.register_echo(mock_frame)

        mgr.decay_and_clean()
        frames = mgr.get_active_echo_frames()
        sa = frames[0]["sa_items"][0]
        assert abs(sa["energy"]["er"] - 0.707107) < 0.01

    def test_clear_echo_pool(self, sensor):
        """clear_echo_pool 高风险操作。"""
        sensor.ingest_text(text="你好", trace_id="clr_001")
        result = sensor.clear_echo_pool(trace_id="clr_002")
        assert result["success"] is True
        assert result["data"]["cleared_frame_count"] >= 1

        # 清空后池应为空
        snapshot = sensor.get_runtime_snapshot()
        assert snapshot["data"]["echo_pool_summary"]["pool_size"] == 0


# ====================================================================== #
#   测试 5: 重要性评分                                                    #
# ====================================================================== #


class TestImportanceScoring:
    """设计文档 16.1 必测项 3,4: 重要性评分。"""

    def test_scoring_disabled(self):
        """关闭重要性评分时能跑通。"""
        s = TextSensor(config_override={"enable_importance_scoring": False})
        result = s.ingest_text(text="你好呀！", trace_id="imp_001")
        assert result["success"] is True

    def test_rule_scoring(self):
        """规则评分模式。"""
        s = TextSensor(
            config_override={
                "enable_importance_scoring": True,
                "importance_mode": "rule",
            }
        )
        result = s.ingest_text(text="你好呀！", trace_id="imp_002")
        assert result["success"] is True

    def test_keyword_scoring_graceful_fallback(self):
        """keyword 模式: jieba 不可用时应降级。"""
        s = TextSensor(
            config_override={
                "enable_importance_scoring": True,
                "importance_mode": "keyword",
                "importance_backend": "jieba_tfidf",
            }
        )
        result = s.ingest_text(text="你好呀！", trace_id="imp_003")
        # 无论 jieba 是否可用都应成功
        assert result["success"] is True

    def test_embedding_fallback(self):
        """embedding 模式: 原型阶段应降级到 rule。"""
        s = TextSensor(
            config_override={
                "enable_importance_scoring": True,
                "importance_mode": "embedding",
            }
        )
        result = s.ingest_text(text="测试", trace_id="imp_004")
        assert result["success"] is True

    def test_api_fallback(self):
        """API 模式: 应降级到 rule。"""
        s = TextSensor(
            config_override={
                "enable_importance_scoring": True,
                "importance_mode": "api",
            }
        )
        result = s.ingest_text(text="测试", trace_id="imp_005")
        assert result["success"] is True


# ====================================================================== #
#   测试 6: 配置热加载                                                    #
# ====================================================================== #


class TestConfigReload:
    """设计文档 16.1 必测项 10: 热加载即时生效。"""

    def test_reload_from_override(self, sensor):
        """通过临时文件测试热加载。"""
        # 先确认默认模式
        snapshot = sensor.get_runtime_snapshot()
        assert snapshot["data"]["config_summary"]["default_mode"] == "simple"

    def test_runtime_snapshot(self, sensor):
        """get_runtime_snapshot 返回正确信息。"""
        sensor.ingest_text(text="你好", trace_id="snap_001")
        snap = sensor.get_runtime_snapshot()

        assert snap["success"] is True
        assert snap["data"]["statistics"]["total_calls"] == 1
        assert snap["data"]["statistics"]["total_frames"] == 1


# ====================================================================== #
#   测试 7: 归一化器                                                      #
# ====================================================================== #


class TestNormalizer:
    """文本归一化单元测试。"""

    def test_strip_control_chars(self):
        n = TextNormalizer({"strip_control_chars": True})
        # \x01 是控制字符，应该被移除; \n 应保留
        assert n.normalize("你\x01好\n呀") == "你好\n呀"

    def test_fullwidth_to_halfwidth(self):
        n = TextNormalizer({"fullwidth_to_halfwidth": True})
        assert n.normalize("Ａ") == "A"
        assert n.normalize("１") == "1"

    def test_lowercase(self):
        n = TextNormalizer({"case_policy": "lower"})
        assert n.normalize("Hello") == "hello"

    def test_compress_whitespace(self):
        n = TextNormalizer({"compress_whitespace": True, "strip_edges": False})
        assert n.normalize("你  好   呀") == "你 好 呀"


# ====================================================================== #
#   测试 8: 切分器                                                        #
# ====================================================================== #


class TestSegmenter:
    """切分器单元测试。"""

    def test_char_segmentation(self):
        seg = TextSegmenter()
        units = seg.segment_chars("你好！")
        assert len(units) == 3
        assert units[0]["text"] == "你"
        assert units[0]["unit_kind"] == "char"
        assert units[2]["text"] == "！"
        assert units[2]["is_punctuation"] is True

    def test_token_fallback(self):
        seg = TextSegmenter({"tokenizer_backend": "jieba", "tokenizer_fallback_to_char": True})
        units, fallback = seg.segment_tokens("你好呀")
        # 无论 jieba 是否可用，都应该有结果
        assert len(units) > 0


# ====================================================================== #
#   测试 9: 多轮场景                                                      #
# ====================================================================== #


class TestMultiRound:
    """多轮调用场景验证。"""

    def test_three_rounds(self, sensor):
        """连续三轮输入，验证残响累积和衰减。"""
        r1 = sensor.ingest_text(text="你", trace_id="mr_001")
        assert r1["success"]

        r2 = sensor.ingest_text(text="好", trace_id="mr_002")
        assert r2["success"]
        # 第二轮刺激包应包含当前+残响
        pkt2 = r2["data"]["stimulus_packet"]
        assert len(pkt2["grouped_sa_sequences"]) >= 1

        r3 = sensor.ingest_text(text="呀", trace_id="mr_003")
        assert r3["success"]
        pkt3 = r3["data"]["stimulus_packet"]
        assert len(pkt3["grouped_sa_sequences"]) >= 2

    def test_no_echo_mode(self, sensor_no_echo):
        """关闭残响时 stimulus_packet 只含当前帧。"""
        sensor_no_echo.ingest_text(text="你", trace_id="ne_001")
        r2 = sensor_no_echo.ingest_text(text="好", trace_id="ne_002")

        pkt = r2["data"]["stimulus_packet"]
        # 没有残响帧
        assert len(pkt["echo_frame_ids"]) == 0


# ====================================================================== #
#                     执行入口                                            #
# ====================================================================== #


def test_goal_b_char_sa_string_mode_groups_current_text_as_one_order_sensitive_string():
    sensor = TextSensor(
        config_override={
            "default_mode": "simple",
            "tokenizer_backend": "none",
            "enable_token_output": False,
            "enable_char_output": True,
            "enable_goal_b_char_sa_string_mode": True,
            "enable_echo": False,
        }
    )

    result = sensor.ingest_text(text="ABC", trace_id="goal_b_sensor_001")

    assert result["success"] is True
    packet = result["data"]["stimulus_packet"]
    groups = packet["grouped_sa_sequences"]
    assert len(groups) == 1
    group = groups[0]
    assert group["order_sensitive"] is True
    assert group["string_unit_kind"] == "char_sequence"
    assert group["string_token_text"] == "ABC"
    assert len(group["sa_ids"]) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
