# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║   AP 文本感受器 — 交互式验收测试脚本                          ║
║   Text Sensor — Interactive Verification Script              ║
║                                                              ║
║   运行方式 / How to run:                                      ║
║     python text_sensor/tests/run_verification.py             ║
║                                                              ║
║   本脚本以中文为主、英文为辅的格式输出详细的测试过程和结果，    ║
║   方便非英文用户也能清晰理解每项测试的目的、过程和结论。        ║
╚══════════════════════════════════════════════════════════════╝
"""

import copy
import json
import os
import sys
import time

# 确保能找到模块
_project_root = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _project_root)

from text_sensor.main import TextSensor
from text_sensor._echo_manager import EchoManager
from text_sensor._id_generator import reset_id_generator


# ====================================================================== #
#                       辅助工具函数                                       #
# ====================================================================== #

# 计数器
_test_total = 0
_test_passed = 0
_test_failed = 0


def _title(text: str):
    """打印大标题"""
    print(f"\n{'═' * 64}")
    print(f"  {text}")
    print(f"{'═' * 64}")


def _section(text: str):
    """打印小节标题"""
    print(f"\n  ┌─ {text}")
    print(f"  │")


def _info(text: str):
    """打印信息行"""
    print(f"  │  {text}")


def _check(condition: bool, pass_msg: str, fail_msg: str):
    """断言并打印结果"""
    global _test_total, _test_passed, _test_failed
    _test_total += 1
    if condition:
        _test_passed += 1
        print(f"  │  ✅ 通过 / PASS: {pass_msg}")
    else:
        _test_failed += 1
        print(f"  │  ❌ 失败 / FAIL: {fail_msg}")


def _end_section():
    """结束小节"""
    print(f"  └─ 完成 / Done\n")


def _json_brief(obj: dict, max_len: int = 200) -> str:
    """JSON 简要输出"""
    s = json.dumps(obj, ensure_ascii=False)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


# ====================================================================== #
#                       测试一：简易模式基础功能                            #
# ====================================================================== #

def test_simple_mode_basic():
    """
    测试简易模式的基础功能。
    验证点:
      - 文本 "你好呀！" 应生成 4 个特征SA（每个字符一个）
      - 应生成 4 个属性SA（每个特征SA 对应一个 stimulus_intensity）
      - 应生成 4 个 CSA（每个 CSA = 特征SA + 属性SA）
      - 调用必须返回 success=True
    """
    reset_id_generator()
    _section("测试一：简易模式基础功能 / Test 1: Simple Mode Basic")
    _info("输入文本 / Input: \"你好呀！\"")
    _info("模式 / Mode: simple（字符级切分 / char-level segmentation）")
    _info("预期: 4个字符 → 4个特征SA + 4个属性SA + 4个CSA")
    _info("")

    sensor = TextSensor(config_override={"default_mode": "simple", "enable_echo": False})
    result = sensor.ingest_text(text="你好呀！", trace_id="verify_001")

    _check(result["success"], "调用成功返回 / Call succeeded", "调用失败 / Call failed")

    if result["success"]:
        stats = result["data"]["stats"]
        _check(
            stats["feature_sa_count"] == 4,
            f"特征SA数量正确: {stats['feature_sa_count']}",
            f"特征SA数量错误: 期望4, 实际{stats['feature_sa_count']}",
        )
        _check(
            stats["attribute_sa_count"] == 4,
            f"属性SA数量正确: {stats['attribute_sa_count']}",
            f"属性SA数量错误: 期望4, 实际{stats['attribute_sa_count']}",
        )
        _check(
            stats["csa_count"] == 4,
            f"CSA数量正确: {stats['csa_count']}",
            f"CSA数量错误: 期望4, 实际{stats['csa_count']}",
        )
        _info(f"总实能量 / Total er: {stats['total_er']}")

        # 展示每个特征SA的详细信息
        _info("")
        _info("── 各特征SA详情 / Feature SA Details ──")
        packet = result["data"]["stimulus_packet"]
        for sa in packet["sa_items"]:
            if sa["stimulus"]["role"] == "feature":
                _info(
                    f"   \"{sa['content']['raw']}\"  "
                    f"类型/{sa['linguistic']['char_type']}  "
                    f"er={sa['energy']['er']}  "
                    f"id={sa['id']}"
                )
    _end_section()


# ====================================================================== #
#                  测试二：CSA结构正确性                                    #
# ====================================================================== #

def test_csa_structure():
    """
    验证 CSA 结构是否符合设计:
      - CSA = 特征SA（锚点，role=feature）+ 属性SA（role=attribute）
      - 属性SA 的 value_type 应为 numerical（支持模糊/桶状匹配）
      - CSA 的能量由成员SA聚合
    """
    reset_id_generator()
    _section("测试二：CSA 结构正确性 / Test 2: CSA Structure Correctness")
    _info("核心验证: CSA = 特征SA（锚点）+ 属性SA（stimulus_intensity 数值刺激元）")
    _info("设计依据: 论文 3.3.2 节 —— CSA以特征刺激元为锚点绑定属性刺激元")
    _info("")

    sensor = TextSensor(config_override={"enable_echo": False})
    result = sensor.ingest_text(text="你", trace_id="verify_002")
    packet = result["data"]["stimulus_packet"]

    # 找到 CSA
    csa = packet["csa_items"][0]
    anchor_id = csa["anchor_sa_id"]

    # 找到锚点（特征SA）
    anchor_sa = next(sa for sa in packet["sa_items"] if sa["id"] == anchor_id)
    _check(
        anchor_sa["stimulus"]["role"] == "feature",
        f"锚点SA角色正确: role=feature",
        f"锚点SA角色错误: role={anchor_sa['stimulus']['role']}",
    )
    _check(
        anchor_sa["content"]["raw"] == "你",
        f"锚点SA内容正确: \"{anchor_sa['content']['raw']}\"",
        f"锚点SA内容错误",
    )

    # 找到属性SA
    attr_sas = [
        sa for sa in packet["sa_items"]
        if sa["id"] in csa["member_sa_ids"] and sa["stimulus"]["role"] == "attribute"
    ]
    _check(
        len(attr_sas) >= 1,
        f"属性SA存在: {len(attr_sas)}个",
        "属性SA缺失",
    )
    if attr_sas:
        attr = attr_sas[0]
        _check(
            attr["content"]["value_type"] == "numerical",
            f"属性SA值类型正确: numerical（支持模糊匹配/桶状匹配）",
            f"属性SA值类型错误: {attr['content']['value_type']}",
        )
        _check(
            "stimulus_intensity" in attr["content"]["raw"],
            f"属性SA内容正确: {attr['content']['raw']}",
            f"属性SA内容缺少 stimulus_intensity",
        )

    _check(
        csa["energy"]["ownership_level"] == "aggregated_from_sa",
        "CSA能量来源正确: 从成员SA聚合 / aggregated from member SAs",
        f"CSA能量来源错误: {csa['energy']['ownership_level']}",
    )

    _info("")
    _info("── CSA 结构概览 / CSA Structure Overview ──")
    _info(f"   CSA ID: {csa['id']}")
    _info(f"   锚点 / Anchor: {anchor_sa['content']['raw']} (id={anchor_id})")
    _info(f"   成员 / Members: {csa['member_sa_ids']}")
    _info(f"   总能量 / Total er: {csa['energy']['er']}")
    _end_section()


# ====================================================================== #
#                  测试三：参数校验                                         #
# ====================================================================== #

def test_input_validation():
    """
    验证参数校验功能:
      - 空文本拒绝
      - 类型错误拒绝
      - 超长文本拒绝
      - 无效模式拒绝
    """
    reset_id_generator()
    _section("测试三：参数校验 / Test 3: Input Validation")

    sensor = TextSensor()

    # 3.1 空文本
    _info("3.1 空文本输入 / Empty text input")
    r = sensor.ingest_text(text="", trace_id="val_001")
    _check(not r["success"], f"空文本被正确拒绝: {r['code']}", "空文本未被拒绝")
    _info(f"     返回消息: {r['message']}")
    _info("")

    # 3.2 类型错误
    _info("3.2 text参数类型错误 / Wrong type for text parameter")
    r = sensor.ingest_text(text=12345, trace_id="val_002")
    _check(not r["success"], f"类型错误被正确拒绝: {r['code']}", "类型错误未被拒绝")
    _info(f"     返回消息: {r['message']}")
    _info("")

    # 3.3 超长文本
    _info("3.3 超长文本输入 / Overlong text input")
    r = sensor.ingest_text(text="你" * 20000, trace_id="val_003")
    _check(not r["success"], f"超长文本被正确拒绝: {r['code']}", "超长文本未被拒绝")
    _info(f"     返回消息: {r['message']}")
    _info("")

    # 3.4 无效 mode
    _info("3.4 无效模式名称 / Invalid mode name")
    r = sensor.ingest_text(text="hello", trace_id="val_004", mode_override="invalid_mode")
    _check(not r["success"], f"无效模式被正确拒绝: {r['code']}", "无效模式未被拒绝")
    _info(f"     返回消息: {r['message']}")
    _end_section()


# ====================================================================== #
#                  测试四：残响衰减                                         #
# ====================================================================== #

def test_echo_decay():
    """
    验证感受器残响机制:
      - 第1轮输入后，残响池有1帧
      - 第2轮输入后，第1轮的SA能量应已衰减
      - 连续5轮后，普通刺激应显著衰减
    """
    reset_id_generator()
    _section("测试四：残响衰减验证 / Test 4: Echo Decay Verification")
    _info("衰减模式 / Decay mode: round_factor（固定每轮系数）")
    _info("每轮保留系数 / Round decay factor: 0.4")
    _info("淘汰阈值 / Threshold: 0.08")
    _info("衰减公式 / Formula: er_new = er_old × 0.4")
    _info("")

    sensor = TextSensor(config_override={
        "echo_decay_mode": "round_factor",
        "echo_round_decay_factor": 0.4,
        "echo_min_energy_threshold": 0.08,
        "echo_pool_max_frames": 20,
    })

    # 第1轮
    _info("── 第1轮: 输入 \"你\" / Round 1: Input \"你\" ──")
    r1 = sensor.ingest_text(text="你", trace_id="echo_001")
    snap1 = sensor.get_runtime_snapshot()
    pool1 = snap1["data"]["echo_pool_summary"]["pool_size"]
    _info(f"   残响池大小 / Pool size: {pool1}")
    _check(pool1 == 1, "残响帧已注册 / Echo frame registered", "残响帧未注册")
    _info("")

    # 第2轮
    _info("── 第2轮: 输入 \"好\" / Round 2: Input \"好\" ──")
    r2 = sensor.ingest_text(text="好", trace_id="echo_002")
    _info(f"   期望: \"你\" 的残响能量衰减 (er < 1.0)")

    # 检查残响中的 "你"
    pkt2 = r2["data"]["stimulus_packet"]
    echo_feature_sas = []
    for group in pkt2["grouped_sa_sequences"]:
        if group["source_type"] == "echo":
            for sa in pkt2["sa_items"]:
                if sa["id"] in group["sa_ids"] and sa["stimulus"]["role"] == "feature":
                    echo_feature_sas.append(sa)

    if echo_feature_sas:
        echo_er = echo_feature_sas[0]["energy"]["er"]
        _info(f"   \"你\" 衰减后能量 / Decayed er: {echo_er:.6f}")
        _info(f"   理论值 / Theoretical: 1.0 × 0.4 = 0.4")
        _check(echo_er < 1.0, "能量已衰减 / Energy decayed", "能量未衰减")
        _check(
            abs(echo_er - 0.4) < 0.02,
            f"衰减精度正确（误差<0.02）/ Decay precision OK",
            f"衰减精度偏差较大 / Decay precision error",
        )
    else:
        _info("   （残响帧中未找到特征SA，可能已被淘汰）")
    _info("")

    # 连续5轮
    _info("── 第3~6轮: 连续输入 / Round 3-6 ──")
    for i in range(3, 7):
        sensor.ingest_text(text=f"轮{i}", trace_id=f"echo_{i:03d}")
    active_frames = sensor._echo_mgr.get_active_echo_frames()
    surviving_feature_values = [
        sa["content"]["raw"]
        for frame in active_frames
        for sa in frame.get("sa_items", [])
        if sa.get("stimulus", {}).get("role") == "feature"
    ]
    _info(f"   6轮后残响池大小 / Pool size after 6 rounds: {len(active_frames)}")
    _check("你" not in surviving_feature_values, "首轮普通刺激已被淘汰 / First-round stimulus pruned", "首轮普通刺激仍残留")
    _check(len(active_frames) <= 20, "池大小在合理范围内 / Pool size within limit", "池大小超出限制")

    _end_section()


# ====================================================================== #
#                  测试五：残响衰减数学精确性                               #
# ====================================================================== #

def test_echo_math():
    """
    直接测试残响管理器的衰减数学:
      - 默认 round_factor 模式: 1轮后≈0.4, 2轮后≈0.16
      - 兼容 round_half_life 模式: 1轮后≈0.7071
    """
    _section("测试五：残响衰减数学精确性 / Test 5: Echo Decay Math")
    _info("使用独立的 EchoManager 验证两种衰减模式")
    _info("")

    mgr = EchoManager({
        "enable_echo": True,
        "echo_decay_mode": "round_factor",
        "echo_round_decay_factor": 0.4,
        "echo_min_energy_threshold": 0.01,
    })

    mock_sa = {
        "id": "test_sa",
        "energy": {"er": 1.0, "ev": 0.0, "cognitive_pressure_delta": 1.0,
                   "cognitive_pressure_abs": 1.0, "salience_score": 1.0},
        "stimulus": {"role": "feature"},
    }
    mock_frame = {
        "id": "test_frame",
        "sa_items": [copy.deepcopy(mock_sa)],
        "csa_items": [],
        "energy_summary": {"total_er": 1.0, "total_ev": 0.0},
        "round_created": 0, "decay_count": 0,
    }
    mgr.register_echo(mock_frame)

    expected = [(1, 0.4), (2, 0.16), (3, 0.064)]
    for round_no, expected_er in expected:
        mgr.decay_and_clean()
        frames = mgr.get_active_echo_frames()
        if frames and frames[0]["sa_items"]:
            actual_er = frames[0]["sa_items"][0]["energy"]["er"]
            ok = abs(actual_er - expected_er) < 0.01
            _check(
                ok,
                f"第{round_no}轮: er={actual_er:.4f} (期望≈{expected_er:.4f})",
                f"第{round_no}轮: er={actual_er:.4f} (期望≈{expected_er:.4f}) 偏差过大",
            )
        else:
            _info(f"   第{round_no}轮: SA已被淘汰")

    mgr_half_life = EchoManager({
        "enable_echo": True,
        "echo_decay_mode": "round_half_life",
        "echo_half_life_rounds": 2.0,
        "echo_min_energy_threshold": 0.01,
    })
    mgr_half_life.register_echo(copy.deepcopy(mock_frame))
    mgr_half_life.decay_and_clean()
    half_life_er = mgr_half_life.get_active_echo_frames()[0]["sa_items"][0]["energy"]["er"]
    _check(
        abs(half_life_er - 0.707107) < 0.02,
        f"半衰期兼容模式正常 / Half-life mode OK: er={half_life_er:.4f}",
        f"半衰期兼容模式异常 / Half-life mode error: er={half_life_er:.4f}",
    )

    _end_section()


# ====================================================================== #
#                  测试六：高级模式与降级                                   #
# ====================================================================== #

def test_advanced_and_fallback():
    """
    验证高级模式:
      - 如果 jieba 已安装，正常分词
      - 如果 jieba 未安装，自动降级到字符模式
      - 无论哪种情况都不应崩溃
    """
    reset_id_generator()
    _section("测试六：高级模式与降级 / Test 6: Advanced Mode & Fallback")

    sensor = TextSensor(config_override={
        "default_mode": "advanced",
        "tokenizer_backend": "jieba",
        "tokenizer_fallback_to_char": True,
    })

    _info("输入文本 / Input: \"今天天气真不错\"")
    _info("配置: tokenizer_backend=jieba, fallback_to_char=True")
    _info("")

    result = sensor.ingest_text(text="今天天气真不错", trace_id="adv_001")
    _check(result["success"], "调用成功（无论是否降级）/ Call succeeded", "调用失败")

    summary = result["data"]["tokenization_summary"]
    _info(f"   实际使用后端 / Backend used: {summary['tokenizer_backend']}")
    _info(f"   是否降级 / Fallback used: {'是/Yes' if summary['tokenizer_fallback'] else '否/No'}")
    _info(f"   生成SA数 / Feature SA count: {result['data']['stats']['feature_sa_count']}")

    if summary["tokenizer_fallback"]:
        _info("   ⚠ jieba 未安装，已自动降级为字符切分（这是预期行为）")
        _info("     如需启用词元切分，请运行: pip install jieba")
    else:
        _info("   词元切分成功，jieba 库可用")

    _end_section()


# ====================================================================== #
#                  测试七：重要性评分模式                                   #
# ====================================================================== #

def test_importance_scoring():
    """
    验证各重要性评分模式:
      - 关闭评分: 所有单位等权
      - rule 模式: 规则评分
      - keyword 模式: 降级到 rule（若 jieba 不可用）
      - embedding 模式: 降级到 rule（原型阶段）
      - api 模式: 降级到 rule（原型阶段）
    """
    reset_id_generator()
    _section("测试七：重要性评分模式 / Test 7: Importance Scoring Modes")

    modes = [
        ("关闭评分 / Disabled", {"enable_importance_scoring": False}),
        ("规则模式 / Rule mode", {"enable_importance_scoring": True, "importance_mode": "rule"}),
        ("关键词模式 / Keyword mode", {"enable_importance_scoring": True, "importance_mode": "keyword"}),
        ("嵌入模式 / Embedding mode", {"enable_importance_scoring": True, "importance_mode": "embedding"}),
        ("API模式 / API mode", {"enable_importance_scoring": True, "importance_mode": "api"}),
    ]

    for name, cfg in modes:
        _info(f"  {name}:")
        s = TextSensor(config_override={**cfg, "enable_echo": False})
        r = s.ingest_text(text="你好呀！", trace_id="imp_test")
        _check(r["success"], f"  {name} 调用成功 / Call succeeded", f"  {name} 调用失败")
        if r["data"].get("importance_summary"):
            for imp in r["data"]["importance_summary"]:
                _info(f"     实际模式 / Mode used: {imp.get('mode_used', 'N/A')}, "
                      f"降级 / Fallback: {'是/Yes' if imp.get('fallback_used') else '否/No'}")

    _end_section()


# ====================================================================== #
#                  测试八：多轮场景                                         #
# ====================================================================== #

def test_multi_round():
    """
    验证多轮调用场景:
      - 连续3轮输入
      - stimulus_packet 应包含当前帧和历史残响
      - grouped_sa_sequences 保留时序信息
    """
    reset_id_generator()
    _section("测试八：多轮调用场景 / Test 8: Multi-Round Scenario")

    sensor = TextSensor()
    texts = ["你", "好", "呀"]

    for i, txt in enumerate(texts, 1):
        _info(f"── 第{i}轮: 输入 \"{txt}\" / Round {i}: Input \"{txt}\" ──")
        r = sensor.ingest_text(text=txt, trace_id=f"multi_{i:03d}")
        pkt = r["data"]["stimulus_packet"]
        groups = pkt["grouped_sa_sequences"]
        echo_groups = [g for g in groups if g["source_type"] == "echo"]
        current_groups = [g for g in groups if g["source_type"] == "current"]
        _info(f"   刺激包中信息组数 / Groups in packet: {len(groups)}")
        _info(f"   残响组数 / Echo groups: {len(echo_groups)}")
        _info(f"   当前帧组数 / Current groups: {len(current_groups)}")
        _info(f"   总SA数 / Total SA count: {len(pkt['sa_items'])}")
        _info(f"   总能量 / Total er: {pkt['energy_summary']['total_er']}")
        _info("")

    snap = sensor.get_runtime_snapshot()
    _info(f"3轮后统计 / Stats after 3 rounds:")
    _info(f"   总调用次数 / Total calls: {snap['data']['statistics']['total_calls']}")
    _info(f"   残响池大小 / Pool size: {snap['data']['echo_pool_summary']['pool_size']}")
    _check(
        snap["data"]["statistics"]["total_calls"] == 3,
        "调用计数正确 / Call count correct", "调用计数错误"
    )
    _end_section()


# ====================================================================== #
#                  测试九：标点和空白平等性                                 #
# ====================================================================== #

def test_punctuation_whitespace_equality():
    """
    验证标点和空白与普通字符平等:
      - 标点生成独立的特征SA和CSA
      - 空白生成独立的特征SA和CSA
    """
    reset_id_generator()
    _section("测试九：标点和空白平等性 / Test 9: Punctuation & Whitespace Equality")
    _info("设计要求: 标点和空白与字符等价，均可生成SA和CSA")
    _info("输入: \"你 ！\"（汉字 + 空格 + 感叹号）")
    _info("")

    sensor = TextSensor(config_override={"enable_echo": False})
    result = sensor.ingest_text(text="你 ！", trace_id="eq_001")
    stats = result["data"]["stats"]

    _check(
        stats["feature_sa_count"] == 3,
        f"3个字符各生成一个特征SA: 数量={stats['feature_sa_count']}",
        f"特征SA数量错误: 期望3, 实际{stats['feature_sa_count']}",
    )
    _check(
        stats["csa_count"] == 3,
        f"3个字符各生成一个CSA: 数量={stats['csa_count']}",
        f"CSA数量错误: 期望3, 实际{stats['csa_count']}",
    )

    # 检查各自能量
    packet = result["data"]["stimulus_packet"]
    for sa in packet["sa_items"]:
        if sa["stimulus"]["role"] == "feature":
            _info(f"   \"{sa['content']['raw']}\"  "
                  f"类型={sa['linguistic']['char_type']}  "
                  f"er={sa['energy']['er']}")

    _end_section()


# ====================================================================== #
#                  测试十：日志文件验证                                     #
# ====================================================================== #

def test_log_files():
    """
    验证日志文件是否正确创建和写入。
    """
    _section("测试十：日志文件验证 / Test 10: Log File Verification")

    log_base = os.path.join(os.path.dirname(__file__), "..", "logs")
    _info(f"日志目录 / Log directory: {os.path.abspath(log_base)}")
    _info("")

    for level in ("error", "brief", "detail"):
        level_dir = os.path.join(log_base, level)
        dir_exists = os.path.isdir(level_dir)
        _check(dir_exists, f"{level}/ 目录存在 / Directory exists", f"{level}/ 目录不存在")

        if dir_exists:
            log_file = os.path.join(level_dir, f"{level}_current.log")
            if os.path.isfile(log_file):
                size = os.path.getsize(log_file)
                _info(f"   {level}_current.log: {size} 字节/bytes")
                # 读取最后一行看格式
                with open(log_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                if lines:
                    last = lines[-1].strip()
                    try:
                        record = json.loads(last)
                        has_trace = "trace_id" in record
                        has_module = "module" in record
                        _check(
                            has_trace and has_module,
                            f"   日志格式正确（含 trace_id 和 module字段）",
                            "   日志格式缺少关键字段",
                        )
                    except json.JSONDecodeError:
                        _info(f"   ⚠ 最后一行不是有效JSON")
            else:
                _info(f"   {level}_current.log 尚未创建（可能还未触发写入）")

    _end_section()


# ====================================================================== #
#                  测试十一：运行态快照                                     #
# ====================================================================== #

def test_runtime_snapshot():
    """
    验证运行态快照功能。
    """
    reset_id_generator()
    _section("测试十一：运行态快照 / Test 11: Runtime Snapshot")

    sensor = TextSensor()
    sensor.ingest_text(text="测试快照", trace_id="snap_001")
    snap = sensor.get_runtime_snapshot()

    _check(snap["success"], "快照获取成功 / Snapshot retrieved", "快照获取失败")

    data = snap["data"]
    _info(f"   模块版本 / Version: {data['version']}")
    _info(f"   Schema版本 / Schema: {data['schema_version']}")
    _info(f"   默认模式 / Default mode: {data['config_summary']['default_mode']}")
    _info(f"   分词器后端 / Tokenizer: {data['config_summary']['tokenizer_backend']}")
    _info(f"   分词器可用 / Available: {data['config_summary']['tokenizer_available']}")
    _info(f"   残响衰减模式 / Echo decay mode: {data['config_summary']['echo_decay_mode']}")
    _info(f"   每轮残响系数 / Echo round factor: {data['config_summary']['echo_round_decay_factor']}")
    _info(f"   残响池大小 / Echo pool: {data['echo_pool_summary']['pool_size']}")
    _info(f"   总调用次数 / Calls: {data['statistics']['total_calls']}")
    _info(f"   总创建SA数 / SAs created: {data['statistics']['total_sa_created']}")

    _end_section()


# ====================================================================== #
#                       主入口                                             #
# ====================================================================== #

def main():
    _title("AP 文本感受器 — 交互式验收测试")
    print("  Text Sensor — Interactive Verification")
    print(f"  运行时间 / Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Python: {sys.version.split()[0]}")
    print()
    print("  本脚本将依次运行以下验收测试项：")
    print("  ──────────────────────────────────────────")
    print("  1.  简易模式基础功能    Basic simple mode")
    print("  2.  CSA结构正确性       CSA structure")
    print("  3.  参数校验            Input validation")
    print("  4.  残响衰减            Echo decay")
    print("  5.  残响衰减数学        Echo decay math")
    print("  6.  高级模式与降级      Advanced mode & fallback")
    print("  7.  重要性评分模式      Importance scoring")
    print("  8.  多轮调用场景        Multi-round scenario")
    print("  9.  标点和空白平等性    Punctuation & whitespace")
    print("  10. 日志文件验证        Log file verification")
    print("  11. 运行态快照          Runtime snapshot")
    print()
    input("  按回车开始测试 / Press Enter to start...")

    test_simple_mode_basic()
    test_csa_structure()
    test_input_validation()
    test_echo_decay()
    test_echo_math()
    test_advanced_and_fallback()
    test_importance_scoring()
    test_multi_round()
    test_punctuation_whitespace_equality()
    test_log_files()
    test_runtime_snapshot()

    # 汇总
    _title("测试汇总 / Test Summary")
    print(f"  总计 / Total:    {_test_total} 项/tests")
    print(f"  通过 / Passed:   {_test_passed} 项/tests  ✅")
    if _test_failed:
        print(f"  失败 / Failed:   {_test_failed} 项/tests  ❌")
    else:
        print(f"  失败 / Failed:   0 项/tests")
    print()

    if _test_failed == 0:
        print("  🎉 全部测试通过！模块验收成功！")
        print("     All tests passed! Module verification succeeded!")
    else:
        print("  ⚠ 存在失败项，请检查上方详细信息。")
        print("    Some tests failed. Please review the details above.")
    print()

    print("  ── 其他可用命令 / Other Available Commands ──")
    print("  自动化测试 / Auto tests:  python -m pytest text_sensor/tests/test_text_sensor.py -v")
    print("  模块文档 / Module docs:   text_sensor/docs/module_overview.md")
    print("  配置文件 / Config file:   text_sensor/config/text_sensor_config.yaml")
    print("  日志目录 / Log directory: text_sensor/logs/")
    print()


if __name__ == "__main__":
    main()
