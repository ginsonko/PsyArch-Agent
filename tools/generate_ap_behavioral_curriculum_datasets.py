# -*- coding: utf-8 -*-
"""Generate AP behavioral-curriculum datasets.

The training `text` fields stay natural utterances only. Experiment labels,
teacher signals, expectation contracts, and audit expectations are kept in
labels or the design-note Markdown so they do not become ordinary HDB content.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from observatory.experiment.dataset import (
    DatasetValidationError,
    summarize_tick_counts,
    validate_and_normalize_dataset,
)
from observatory.experiment.io import dump_yaml


DATASETS_DIR = ROOT / "datasets"
DESIGN_PATH = DATASETS_DIR / "ap_behavioral_curriculum_v1_design_notes.md"
DESIGN_V2_PATH = DATASETS_DIR / "ap_behavioral_curriculum_v2_design_notes.md"
REPORT_PATH = ROOT / "数据集研发报告_2026-05-05_AP行为课程数据集.md"
V2_REPORT_PATH = ROOT / "数据集优化报告_2026-05-05_AP行为课程数据集_v2.md"

TICK_DT_MS = 3000
GAP_TICKS_AFTER_TEXT = 5
SEED = 20260505

SIZE_SPECS = [
    ("small", "ap_behavioral_curriculum_small_v1", 50, "AP 行为课程小规模数据集"),
    ("medium", "ap_behavioral_curriculum_medium_v1", 500, "AP 行为课程中规模数据集"),
    ("large", "ap_behavioral_curriculum_large_v1", 5000, "AP 行为课程大规模数据集"),
]

SIZE_SPECS_V2 = [
    ("small", "ap_behavioral_curriculum_small_v2", 50, "AP 行为课程小规模数据集 v2"),
    ("medium", "ap_behavioral_curriculum_medium_v2", 500, "AP 行为课程中规模数据集 v2"),
    ("large", "ap_behavioral_curriculum_large_v2", 5000, "AP 行为课程大规模数据集 v2"),
]

CURRICULUM_V2_APP_CONFIG_OVERRIDE: dict[str, Any] = {
    # v2 keeps the contract-safe v1 runtime path by default. The first
    # optimization candidates were rejected after 300-tick isolation because
    # each broke the E05 weather-action contracts.
}

REJECTED_V2_RUNTIME_CANDIDATES: dict[str, dict[str, Any]] = {
    "attention12": {"attention_top_n": 12},
    "er_share075": {"growth_projection_source_er_runtime_share_ratio": 0.75},
    "new_floor008": {"induction_projection_new_target_min_energy_floor": 0.08},
    "er_share075_floor008": {
        "growth_projection_source_er_runtime_share_ratio": 0.75,
        "induction_projection_new_target_min_energy_floor": 0.08,
    },
}

NAMES = ["小林", "阿遥", "南星", "小周", "许诺", "安安", "林舟", "晴川", "小岚", "闻溪"]
TASKS = ["周报", "代码审查", "客户邮件", "论文摘要", "复盘笔记", "课程作业", "采购清单", "会议纪要", "测试报告", "资料整理"]
PROJECTS = ["聊天助手", "天气提醒", "行动闭环", "记忆测试", "情绪观察", "任务面板", "实验记录", "论文材料", "日志整理", "规则编辑"]
PLACES = ["菜市场", "地铁站", "图书馆", "办公室", "楼下超市", "医院", "学校", "咖啡店", "公园", "社区服务站"]
ITEMS = ["雨伞", "外套", "帽子", "水杯", "备用袜子", "薄衫", "雨衣", "文件夹", "充电器", "轻便鞋"]
MOODS = ["有点急", "有些犹豫", "还算平静", "有点累", "怕漏细节", "有点开心", "不太确定", "有点分心", "想稳一点", "想快一点"]
TIME_WORDS = ["早上", "上午", "中午", "下午", "傍晚", "晚上", "睡前", "开会前", "出门前", "休息后"]
RARE_WORDS = ["蓝盐钟", "纸月桥", "雾灯环", "石芽线", "银叶格", "空杯塔", "霜纹尺", "风扣盒", "微光门", "青火签"]
COMMON_GUIDES = [
    "先确认目标，再拆步骤",
    "先别急，我们一步一步来",
    "先从最重要的一件事开始",
    "把必须完成的事放在前面",
    "先做短版，再补备用细节",
]


BASE_ROWS: list[dict[str, Any]] = [
    {
        "experiment": "E01_词汇重复与句式抽象",
        "phase": "lexical_abstraction",
        "role": "system",
        "kind": "context",
        "text": "会话恢复，{name}今天继续处理{task}，主题仍然是先确认目标。",
        "purpose": "建立重复主句和任务背景。",
    },
    {
        "experiment": "E01_词汇重复与句式抽象",
        "phase": "lexical_abstraction",
        "role": "user",
        "kind": "message",
        "text": "{time_word}好，我还是想先确认目标，再开始{task}。",
        "purpose": "重复核心短语并替换时间词。",
    },
    {
        "experiment": "E01_词汇重复与句式抽象",
        "phase": "lexical_abstraction",
        "role": "assistant",
        "kind": "reply",
        "text": "{common_guide}，然后只保留三个能执行的小动作。",
        "purpose": "让稳定建议句式和轻微变体共存。",
        "teacher": {"rwd": 0.12, "note": "任务拆解清晰且压力较低。"},
    },
    {
        "experiment": "E01_词汇重复与句式抽象",
        "phase": "lexical_abstraction",
        "role": "user",
        "kind": "message",
        "text": "你用同样的办法帮我看一下{project}，也先确认目标。",
        "purpose": "跨项目复用同一抽象句式。",
    },
    {
        "experiment": "E01_词汇重复与句式抽象",
        "phase": "lexical_abstraction",
        "role": "assistant",
        "kind": "reply",
        "text": "可以，{project}也先确认目标，再拆成短步骤。",
        "purpose": "形成可泛化的重复结构。",
        "teacher": {"rwd": 0.12, "note": "复用句式准确。"},
    },
    {
        "experiment": "E02_新词违和与新颖感",
        "phase": "novelty",
        "role": "user",
        "kind": "message",
        "text": "刚才的流程我懂了，但现在突然出现一个{rare_word}，我完全没见过。",
        "purpose": "在熟悉流程后加入罕见词，观察新颖和违和。",
    },
    {
        "experiment": "E02_新词违和与新颖感",
        "phase": "novelty",
        "role": "assistant",
        "kind": "reply",
        "text": "这个词先单独放着，我们先记录它和{task}之间可能有什么关系。",
        "purpose": "不强行解释新词，保留探索姿态。",
    },
    {
        "experiment": "E02_新词违和与新颖感",
        "phase": "novelty",
        "role": "user",
        "kind": "message",
        "text": "{rare_word}不是普通物品，它只是我临时起的名字。",
        "purpose": "解释新词来源，观察违和缓解。",
    },
    {
        "experiment": "E02_新词违和与新颖感",
        "phase": "novelty",
        "role": "assistant",
        "kind": "reply",
        "text": "明白，它像一个临时标签，不一定需要马上和旧经验合并。",
        "purpose": "把新词作为临时标签处理。",
        "teacher": {"rwd": 0.10, "note": "没有过度解释未知词。"},
    },
    {
        "experiment": "E02_新词违和与新颖感",
        "phase": "novelty",
        "role": "user",
        "kind": "message",
        "text": "等一下，我又把{rare_word}换成另一个说法，这会不会让你混乱？",
        "purpose": "制造轻度不稳定映射，观察 surprise/dissonance。",
    },
    {
        "experiment": "E03_教师奖励塑形",
        "phase": "teacher_reward",
        "role": "user",
        "kind": "message",
        "text": "当我说我在，你最好先接住我，再给一个很短的建议。",
        "purpose": "定义偏好，为后续奖励塑形做锚点。",
    },
    {
        "experiment": "E03_教师奖励塑形",
        "phase": "teacher_reward",
        "role": "assistant",
        "kind": "reply",
        "text": "我在。先把眼前这一件事写下来，再决定下一步。",
        "purpose": "符合偏好的被奖励样本。",
        "teacher": {"rwd": 0.22, "note": "先接住用户，再给短建议。"},
    },
    {
        "experiment": "E03_教师奖励塑形",
        "phase": "teacher_reward",
        "role": "teacher",
        "kind": "feedback",
        "text": "这个回应方式正确，先接住，再给短建议。",
        "purpose": "显式教师奖励，不把技术标签写进自然语料。",
        "teacher": {"rwd": 0.28, "note": "强化我在和短建议的联结。"},
    },
    {
        "experiment": "E03_教师奖励塑形",
        "phase": "teacher_reward",
        "role": "user",
        "kind": "message",
        "text": "我现在回来了，也有点乱，你还在吗？",
        "purpose": "用相似语境测试奖励后联想。",
    },
    {
        "experiment": "E03_教师奖励塑形",
        "phase": "teacher_reward",
        "role": "assistant",
        "kind": "reply",
        "text": "我在。先别急，我们只看{task}的下一步。",
        "purpose": "奖励塑形后的相似回应。",
        "teacher": {"rwd": 0.18, "note": "相似语境中复用了被奖励模式。"},
    },
    {
        "experiment": "E04_教师惩罚与纠偏",
        "phase": "teacher_punish",
        "role": "user",
        "kind": "message",
        "text": "你刚才说得有点绕，我其实只想知道第一步是什么。",
        "purpose": "用户负反馈，触发惩罚和纠偏。",
        "teacher": {"pun": 0.16, "note": "回复过绕，用户需要直接结论。"},
    },
    {
        "experiment": "E04_教师惩罚与纠偏",
        "phase": "teacher_punish",
        "role": "assistant",
        "kind": "reply",
        "text": "第一步是写标题，其他内容先不展开。",
        "purpose": "惩罚后的直接修正。",
        "teacher": {"rwd": 0.14, "note": "纠偏后更直接。"},
    },
    {
        "experiment": "E04_教师惩罚与纠偏",
        "phase": "teacher_punish",
        "role": "user",
        "kind": "message",
        "text": "如果我说错了，你直接提醒我，但语气不要太重。",
        "purpose": "建立温和纠错偏好。",
    },
    {
        "experiment": "E04_教师惩罚与纠偏",
        "phase": "teacher_punish",
        "role": "assistant",
        "kind": "reply",
        "text": "可以，我会先指出不一致，再给一个轻一点的修正说法。",
        "purpose": "温和纠错策略。",
        "teacher": {"rwd": 0.12, "note": "纠错策略符合偏好。"},
    },
    {
        "experiment": "E04_教师惩罚与纠偏",
        "phase": "teacher_punish",
        "role": "teacher",
        "kind": "feedback",
        "text": "刚才的修正比原来清楚，保留这种直接但不重的语气。",
        "purpose": "奖励纠偏后的表达方式。",
        "teacher": {"rwd": 0.18, "note": "强化直接但温和的纠错。"},
    },
    {
        "experiment": "E05_先天行动与天气闭环",
        "phase": "weather_action",
        "role": "user",
        "kind": "message",
        "text": "我有点纠结出门穿什么，外面的天气怎么样？",
        "purpose": "隐式天气问句，观察中强触发。",
        "tags": ["weather_request", "implicit_weather_question"],
        "contract": "weather_implicit_success",
    },
    {
        "experiment": "E05_先天行动与天气闭环",
        "phase": "weather_action",
        "role": "assistant",
        "kind": "reply",
        "text": "我们先看你去哪里，再把天气和衣物建议放在一起。",
        "purpose": "隐式天气后的澄清式回复。",
    },
    {
        "experiment": "E05_先天行动与天气闭环",
        "phase": "weather_action",
        "role": "user",
        "kind": "message",
        "text": "我要去{place}，请帮我查询今天的天气，我想决定带不带{item}。",
        "purpose": "明确包含查询和天气，预期稳定触发 weather_stub。",
        "tags": ["weather_request", "explicit_weather_query"],
        "contract": "weather_explicit_success",
    },
    {
        "experiment": "E05_先天行动与天气闭环",
        "phase": "weather_action",
        "role": "teacher",
        "kind": "feedback",
        "text": "明确天气查询被接住时，要把结果和行动建议连起来。",
        "purpose": "强化明确查询和行动建议的联结。",
        "teacher": {"rwd": 0.20, "note": "天气行动方向正确。"},
    },
    {
        "experiment": "E05_先天行动与天气闭环",
        "phase": "weather_action",
        "role": "user",
        "kind": "message",
        "text": "我只是想到天气这件事，可能会影响明天出门。",
        "purpose": "弱天气提及，预期通常不应过度触发行动。",
        "tags": ["weather_mention", "weak_weather_only"],
        "contract": "weather_weak_no_execute",
    },
    {
        "experiment": "E06_时间间隔与近因回忆",
        "phase": "time_memory",
        "role": "system",
        "kind": "context",
        "text": "{name}短暂离开，会话进入安静间隔。",
        "purpose": "给空 tick 前后建立时间语境。",
    },
    {
        "experiment": "E06_时间间隔与近因回忆",
        "phase": "time_memory",
        "role": "user",
        "kind": "message",
        "text": "等我回来后，请提醒我继续{project}，不要先刷消息。",
        "purpose": "未来提醒和记忆锚点。",
    },
    {
        "experiment": "E06_时间间隔与近因回忆",
        "phase": "time_memory",
        "role": "assistant",
        "kind": "reply",
        "text": "记住了，你回来后先继续{project}，再处理消息。",
        "purpose": "确认并复述记忆。",
        "teacher": {"rwd": 0.14, "note": "提醒内容复述准确。"},
    },
    {
        "experiment": "E06_时间间隔与近因回忆",
        "phase": "time_memory",
        "role": "user",
        "kind": "message",
        "text": "我回来了，刚才让你提醒我的第一件事是什么？",
        "purpose": "近因回忆探针。",
    },
    {
        "experiment": "E06_时间间隔与近因回忆",
        "phase": "time_memory",
        "role": "assistant",
        "kind": "reply",
        "text": "第一件事是继续{project}，先不要刷消息。",
        "purpose": "正确回忆样本。",
        "teacher": {"rwd": 0.22, "note": "近因回忆正确。"},
    },
    {
        "experiment": "E07_复杂度与注意力调节",
        "phase": "attention_complexity",
        "role": "user",
        "kind": "message",
        "text": "我现在有五件事：{task}、{project}、出门、回消息、整理桌面，脑子有点挤。",
        "purpose": "多目标输入，观察复杂度和注意力竞争。",
    },
    {
        "experiment": "E07_复杂度与注意力调节",
        "phase": "attention_complexity",
        "role": "assistant",
        "kind": "reply",
        "text": "先只保留一个主目标，其他四件先放到后面。",
        "purpose": "聚焦行动与简化策略。",
        "teacher": {"rwd": 0.14, "note": "复杂情境下先聚焦。"},
    },
    {
        "experiment": "E07_复杂度与注意力调节",
        "phase": "attention_complexity",
        "role": "user",
        "kind": "message",
        "text": "那主目标就定为{task}，但我怕忘记{project}。",
        "purpose": "主目标与旁支目标并存。",
    },
    {
        "experiment": "E07_复杂度与注意力调节",
        "phase": "attention_complexity",
        "role": "assistant",
        "kind": "reply",
        "text": "主目标是{task}，{project}只做旁边提醒，不抢当前注意力。",
        "purpose": "维持焦点并保留旁支记忆。",
        "teacher": {"rwd": 0.16, "note": "焦点和旁支区分清楚。"},
    },
    {
        "experiment": "E07_复杂度与注意力调节",
        "phase": "attention_complexity",
        "role": "user",
        "kind": "message",
        "text": "如果我又开始跳来跳去，你要把我拉回主目标。",
        "purpose": "训练注意力回拉偏好。",
    },
    {
        "experiment": "E08_残差记忆与组合召回",
        "phase": "residual_memory",
        "role": "user",
        "kind": "message",
        "text": "刚才我们提到三件事：{task}、天气、还有明天先看{project}。",
        "purpose": "组合记忆显式锚定。",
    },
    {
        "experiment": "E08_残差记忆与组合召回",
        "phase": "residual_memory",
        "role": "assistant",
        "kind": "reply",
        "text": "对，当前主线是{task}，出门要看天气，明天先看{project}。",
        "purpose": "组合摘要并形成可激活结构。",
        "teacher": {"rwd": 0.18, "note": "组合摘要准确。"},
    },
    {
        "experiment": "E08_残差记忆与组合召回",
        "phase": "residual_memory",
        "role": "user",
        "kind": "message",
        "text": "如果只说天气，你还能联想到出门和{item}吗？",
        "purpose": "局部线索激活组合记忆。",
    },
    {
        "experiment": "E08_残差记忆与组合召回",
        "phase": "residual_memory",
        "role": "assistant",
        "kind": "reply",
        "text": "可以，天气这条线索会连到出门准备和是否带{item}。",
        "purpose": "残差记忆和局部线索联结。",
        "teacher": {"rwd": 0.14, "note": "局部线索联想合理。"},
    },
    {
        "experiment": "E08_残差记忆与组合召回",
        "phase": "residual_memory",
        "role": "teacher",
        "kind": "feedback",
        "text": "组合记忆保留得比较完整，可以继续用短线索召回相关内容。",
        "purpose": "强化组合召回。",
        "teacher": {"rwd": 0.20, "note": "奖励短线索召回。"},
    },
    {
        "experiment": "E09_矛盾调和与安抚",
        "phase": "relief_reassurance",
        "role": "user",
        "kind": "message",
        "text": "我刚才说不要复杂，但现在又想看完整清单，这两个要求会冲突吗？",
        "purpose": "制造轻度矛盾。",
    },
    {
        "experiment": "E09_矛盾调和与安抚",
        "phase": "relief_reassurance",
        "role": "assistant",
        "kind": "reply",
        "text": "不一定冲突，我们先给短版，再把完整清单放在后面备用。",
        "purpose": "矛盾调和和安抚。",
        "teacher": {"rwd": 0.18, "note": "短版和完整版调和合理。"},
    },
    {
        "experiment": "E09_矛盾调和与安抚",
        "phase": "relief_reassurance",
        "role": "user",
        "kind": "message",
        "text": "这样我就安心一点，不用在两个选择里卡住。",
        "purpose": "明确 relief/reassurance 语义。",
    },
    {
        "experiment": "E09_矛盾调和与安抚",
        "phase": "relief_reassurance",
        "role": "assistant",
        "kind": "reply",
        "text": "对，先选能推进的版本，备用内容不丢。",
        "purpose": "巩固安抚后的策略。",
        "teacher": {"rwd": 0.12, "note": "安抚后保持可执行。"},
    },
    {
        "experiment": "E09_矛盾调和与安抚",
        "phase": "relief_reassurance",
        "role": "user",
        "kind": "message",
        "text": "如果今晚没做完，也先记录已经完成的部分。",
        "purpose": "降低压力，建立复盘口径。",
    },
    {
        "experiment": "E10_重复疲劳与可控新鲜度",
        "phase": "repetition_curiosity",
        "role": "user",
        "kind": "message",
        "text": "再说一次，先确认目标，再拆步骤。",
        "purpose": "重复高频句式，观察 repetition。",
    },
    {
        "experiment": "E10_重复疲劳与可控新鲜度",
        "phase": "repetition_curiosity",
        "role": "assistant",
        "kind": "reply",
        "text": "先确认目标，再拆步骤，这次我们只换一个例子。",
        "purpose": "重复中加入轻微变化。",
    },
    {
        "experiment": "E10_重复疲劳与可控新鲜度",
        "phase": "repetition_curiosity",
        "role": "user",
        "kind": "message",
        "text": "这个例子换成{project}，但句式还是一样。",
        "purpose": "稳定句式加项目变化。",
    },
    {
        "experiment": "E10_重复疲劳与可控新鲜度",
        "phase": "repetition_curiosity",
        "role": "assistant",
        "kind": "reply",
        "text": "{project}也先确认目标，再拆步骤，不需要一次做完。",
        "purpose": "可控新鲜度下的复用。",
        "teacher": {"rwd": 0.12, "note": "重复中保留变化。"},
    },
    {
        "experiment": "E10_重复疲劳与可控新鲜度",
        "phase": "repetition_curiosity",
        "role": "user",
        "kind": "message",
        "text": "最后加一个不一样的点：{rare_word}只出现一次，看看你会不会特别注意它。",
        "purpose": "重复序列末尾加入低频新词，观察 NOV/curiosity。",
    },
]


EXPERIMENT_EXPECTATIONS = [
    {
        "id": "E01",
        "title": "词汇重复与句式抽象",
        "small_range": "真实输入 1-5",
        "expectation": "高频短语“先确认目标”“拆步骤”“我在”应逐步获得更稳定的结构表示；中/大规模中相同句式替换任务、项目、时间词后，检索应能保留句式骨架而不是只记住单句。",
        "metrics": ["stimulus_match_*", "structure_match_*", "state_pool_active_item_count", "induction_energy_graph_depth_max"],
    },
    {
        "id": "E02",
        "title": "新词违和与新颖感",
        "small_range": "真实输入 6-10",
        "expectation": "罕见词第一次出现时可出现 surprise/NOV 或轻度 dissonance；随后被解释为临时标签后，违和应下降或转为可控探索。",
        "metrics": ["cfs_surprise_max", "cfs_dissonance_max", "nt_NOV", "cfs_reassurance_live_total_energy"],
    },
    {
        "id": "E03",
        "title": "教师奖励塑形",
        "small_range": "真实输入 11-15",
        "expectation": "被奖励的“先接住用户，再给短建议”模式应在相似输入中更容易被召回，并带出 teacher_reward_signal / correctness / expectation 的局部痕迹。",
        "metrics": ["teacher_applied_count", "teacher_reward_signal_live_total_energy", "cfs_correctness_live_total_energy", "reward_signal_live_total_energy"],
    },
    {
        "id": "E04",
        "title": "教师惩罚与纠偏",
        "small_range": "真实输入 16-20",
        "expectation": "用户抱怨和教师惩罚后，应出现 pressure/dissonance 或 teacher_punish_signal；后续直接但温和的修正被奖励后，压力应被可执行策略缓解。",
        "metrics": ["teacher_pun", "teacher_punish_signal_live_total_energy", "cfs_pressure_family_live_total_energy", "cfs_relief_live_total_energy"],
    },
    {
        "id": "E05",
        "title": "先天行动与天气闭环",
        "small_range": "真实输入 21-25",
        "expectation": "明确“查询+天气”应比弱天气提及更稳定触发 weather_stub；expectation_contract_events.jsonl 应记录显式/隐式天气契约的成败，弱天气通常应保持保守。",
        "metrics": ["action_executed_weather_stub", "action_executed_weather_stub_source_visible", "expectation_contracts.success_count", "expectation_contracts.failure_count"],
    },
    {
        "id": "E06",
        "title": "时间间隔与近因回忆",
        "small_range": "真实输入 26-30",
        "expectation": "空 tick 后再问近因内容时，应能通过最近记忆和时间感受召回“回来后先继续项目”的信息；中/大规模应更容易形成稳定提醒模板。",
        "metrics": ["time_sensor_delayed_task_registered_count", "action_executed_recall", "memory_feedback_*", "cfs_expectation_live_total_energy"],
    },
    {
        "id": "E07",
        "title": "复杂度与注意力调节",
        "small_range": "真实输入 31-35",
        "expectation": "多目标输入应提升 complexity/FOC 或 attention_focus_mode 倾向；助手把旁支目标放入提醒而不抢主目标时，后续注意力应更集中。",
        "metrics": ["cfs_complexity_max", "nt_FOC", "action_attempted_focus_mode", "action_executed_focus_mode"],
    },
    {
        "id": "E08",
        "title": "残差记忆与组合召回",
        "small_range": "真实输入 36-40",
        "expectation": "短线索“天气”应能联想到出门、物品和明天安排；残差记忆投影应进入状态池并可被 attention/recall 看到。",
        "metrics": ["residual_memory_runtime_projection_*", "memory_feedback_*", "state_pool_active_item_count", "action_executed_recall"],
    },
    {
        "id": "E09",
        "title": "矛盾调和与安抚",
        "small_range": "真实输入 41-45",
        "expectation": "“不要复杂”和“完整清单”的轻度矛盾应先触发 pressure/dissonance，再因短版+备用清单方案出现 relief/reassurance。",
        "metrics": ["cfs_dissonance_max", "cfs_pressure_max", "cfs_relief_live_total_energy", "cfs_reassurance_live_total_energy"],
    },
    {
        "id": "E10",
        "title": "重复疲劳与可控新鲜度",
        "small_range": "真实输入 46-50",
        "expectation": "连续重复句式应出现 repetition 或疲劳相关迹象；末尾一次性低频词应重新拉高 NOV/curiosity，但不应破坏主句式结构。",
        "metrics": ["cfs_repetition_max", "nt_NOV", "structure_match_*", "state_pool_active_item_count"],
    },
]


def _variant_values(variant_index: int, row_index: int) -> dict[str, str]:
    offset = variant_index + row_index * 5
    return {
        "name": NAMES[offset % len(NAMES)],
        "task": TASKS[(offset // 2) % len(TASKS)],
        "project": PROJECTS[(offset // 3) % len(PROJECTS)],
        "place": PLACES[(offset // 5) % len(PLACES)],
        "item": ITEMS[(offset // 7) % len(ITEMS)],
        "mood": MOODS[(offset // 11) % len(MOODS)],
        "time_word": TIME_WORDS[(offset // 13) % len(TIME_WORDS)],
        "rare_word": RARE_WORDS[(offset // 17) % len(RARE_WORDS)],
        "common_guide": COMMON_GUIDES[(offset // 19) % len(COMMON_GUIDES)],
    }


def _looks_garbled(text: str) -> bool:
    if "\ufffd" in text:
        return True
    question_marks = text.count("?") + text.count("？")
    return question_marks >= 4 and question_marks / max(1, len(text)) > 0.25


def _validate_training_text(text: str) -> None:
    forbidden = ["【", "】", "[", "]", "```", "::", "<", ">"]
    if any(mark in text for mark in forbidden):
        raise ValueError(f"training text contains visible markup: {text!r}")
    if _looks_garbled(text):
        raise ValueError(f"training text looks garbled: {text!r}")


def _contract_id(kind: str, real_index: int) -> str:
    return f"{kind}_{real_index:05d}"


def _build_contract(kind: str, real_index: int) -> dict[str, Any]:
    if kind == "weather_explicit_success":
        return {
            "id": _contract_id(kind, real_index),
            "within_ticks": 2,
            "success_conditions": {
                "all": [{"kind": "action_executed_kind_min", "action_kind": "weather_stub", "min_count": 1}]
            },
            "anchor_policy": {"mode": "cam_top1", "ref_object_types": ["sa", "st"]},
            "on_success": {
                "teacher_rwd": 0.30,
                "feedback_text": "天气查询动作已经完成，请继续把结果和出门建议连起来。",
                "labels": {"stream": {"role": "teacher", "kind": "expectation_success", "phase": "weather_action", "pure_text": True}},
            },
            "on_failure": {
                "teacher_pun": 0.34,
                "feedback_text": "明确天气查询没有完成，用户会觉得请求没有被接住。",
                "labels": {"stream": {"role": "teacher", "kind": "expectation_failure", "phase": "weather_action", "pure_text": True}},
            },
        }
    if kind == "weather_implicit_success":
        return {
            "id": _contract_id(kind, real_index),
            "within_ticks": 2,
            "success_conditions": {
                "all": [{"kind": "action_executed_kind_min", "action_kind": "weather_stub", "min_count": 1}]
            },
            "anchor_policy": {"mode": "cam_top1", "ref_object_types": ["sa", "st"]},
            "on_success": {
                "teacher_rwd": 0.18,
                "feedback_text": "隐式天气求助也被及时处理了，这对用户有帮助。",
                "labels": {"stream": {"role": "teacher", "kind": "expectation_success", "phase": "weather_action", "pure_text": True}},
            },
            "on_failure": {
                "teacher_pun": 0.14,
                "feedback_text": "隐式天气求助没有被处理，之后需要先澄清或主动补足查询。",
                "labels": {"stream": {"role": "teacher", "kind": "expectation_failure", "phase": "weather_action", "pure_text": True}},
            },
        }
    if kind == "weather_weak_no_execute":
        return {
            "id": _contract_id(kind, real_index),
            "within_ticks": 1,
            "success_conditions": {
                "all": [{"kind": "metric_eq", "metric": "action_executed_weather_stub_source_visible", "value": 0}]
            },
            "anchor_policy": {"mode": "cam_top1", "ref_object_types": ["sa", "st"]},
            "on_success": {
                "teacher_rwd": 0.08,
                "feedback_text": "弱天气线索保持保守，没有过度执行天气动作。",
                "labels": {"stream": {"role": "teacher", "kind": "expectation_success", "phase": "weather_action", "pure_text": True}},
            },
            "on_failure": {
                "teacher_pun": 0.10,
                "feedback_text": "弱天气线索也触发了动作，记录为过度行动样本。",
                "labels": {"stream": {"role": "teacher", "kind": "expectation_failure", "phase": "weather_action", "pure_text": True}},
            },
        }
    raise ValueError(f"unsupported contract kind: {kind}")


def _labels_for_row(row: dict[str, Any], *, global_real_index: int, variant_index: int, row_index: int) -> dict[str, Any]:
    labels: dict[str, Any] = {
        "stream": {
            "role": row["role"],
            "kind": row["kind"],
            "phase": row["phase"],
            "pure_text": True,
            "variant_index": int(variant_index),
            "real_input_index": int(global_real_index),
        },
        "curriculum": {
            "experiment": row["experiment"],
            "step_in_50": int(row_index + 1),
            "purpose": row.get("purpose", ""),
        },
    }
    teacher = row.get("teacher")
    if isinstance(teacher, dict) and teacher:
        labels["teacher"] = {
            "rwd": round(float(teacher.get("rwd", 0.0) or 0.0), 8),
            "pun": round(float(teacher.get("pun", 0.0) or 0.0), 8),
            "anchor": "cam_top1",
            "ref_object_types": ["st", "sa"],
            "note": str(teacher.get("note", "") or ""),
        }
    contract_kind = str(row.get("contract", "") or "").strip()
    if contract_kind:
        labels["expectation_contracts"] = [_build_contract(contract_kind, global_real_index)]
    return labels


def _make_tick(row: dict[str, Any], *, global_real_index: int, variant_index: int, row_index: int) -> dict[str, Any]:
    text = str(row["text"]).format(**_variant_values(variant_index, row_index))
    _validate_training_text(text)
    tags = [
        "ap_behavioral_curriculum",
        str(row["phase"]),
        str(row["experiment"]).split("_", 1)[0],
        *list(row.get("tags", []) or []),
    ]
    return {
        "text": text,
        "tags": list(dict.fromkeys([tag for tag in tags if str(tag).strip()])),
        "labels": _labels_for_row(
            row,
            global_real_index=global_real_index,
            variant_index=variant_index,
            row_index=row_index,
        ),
    }


def build_dataset(
    dataset_id: str,
    title: str,
    real_text_count: int,
    *,
    version: str = "v1",
    app_config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ticks: list[dict[str, Any]] = []
    for global_real_index in range(real_text_count):
        row_index = global_real_index % len(BASE_ROWS)
        variant_index = global_real_index // len(BASE_ROWS)
        row = deepcopy(BASE_ROWS[row_index])
        ticks.append(
            _make_tick(
                row,
                global_real_index=global_real_index,
                variant_index=variant_index,
                row_index=row_index,
            )
        )
        ticks.append({"empty": True, "repeat": GAP_TICKS_AFTER_TEXT, "tags": ["idle_gap", "simulated_time_gap"]})

    doc = {
        "dataset_id": dataset_id,
        "title": title,
        "description": (
            "AP 行为课程数据集。真实 text 字段只包含自然中文输入；角色、教师奖惩、"
            "expectation contracts 和实验预期全部在 labels 或旁路设计说明中。"
        ),
        "experiment_goal": (
            "用 10 个可审计实验片段覆盖词汇抽象、新颖违和、教师奖惩、行动训练、"
            "时间回忆、注意力调节、残差记忆、矛盾安抚和重复疲劳，观察 AP 原型在冷启动语料中的局部规律学习。"
        ),
        "evaluation_dimensions": [
            "训练文本是否保持纯净，不含角色括号或技术标记",
            "重复句式是否能在替换变量后形成稳定结构",
            "教师奖励/惩罚是否被绑定到正确的当前对象或上下文对象",
            "明确天气查询、隐式天气问句、弱天气提及是否呈现不同行动倾向",
            "空 tick 后是否能观察到时间感受、状态衰减和近因召回",
            "复杂输入是否触发注意力聚焦或简化相关感受",
            "局部线索是否能激活组合记忆或残差记忆投影",
            "矛盾调和后是否出现安抚、缓解或正确感相关指标",
            "重复和可控新鲜度是否能同时暴露 repetition 与 NOV 通道",
        ],
        "notes": [
            f"每个真实文本 tick 后固定跟随 {GAP_TICKS_AFTER_TEXT} 个空 tick，总 tick = 真实输入 * 6。",
            "小规模正好覆盖 10 个实验各 5 条真实输入；中规模重复 10 个确定性变体；大规模重复 100 个确定性变体。",
            "预期不进入训练过程；LLM 审阅模块应读取旁路设计说明和运行输出进行对照。",
        ],
        "seed": SEED,
        "time_basis": "tick",
        "tick_dt_ms": TICK_DT_MS,
        "curriculum_version": version,
        "episodes": [
            {
                "id": f"{dataset_id}_main",
                "title": title,
                "tags": [
                    "ap_behavioral_curriculum",
                    "teacher_feedback",
                    "expectation_contract",
                    "time_gap",
                    "action_training",
                    "memory_probe",
                ],
                "repeat": 1,
                "ticks": ticks,
            }
        ],
    }
    if app_config_override:
        doc["app_config_override"] = deepcopy(app_config_override)
        doc["notes"].append(
            "v2 运行级覆盖只用于降低中/大规模 HDB 增长压力与提升审阅可读性，不改变 AP 默认理论主流程。"
        )
    return doc


def _write_design_notes(summaries: list[dict[str, Any]]) -> None:
    lines: list[str] = [
        "# AP 行为课程数据集 v1 设计说明",
        "",
        "本文件是旁路说明，不进入训练语料。数据集 YAML 的 `text` 字段只包含自然中文输入；实验编号、角色、教师奖惩、期望契约与审阅预期均保存在 `labels` 或本说明中。",
        "",
        "## 数据集文件",
    ]
    for item in summaries:
        lines.append(
            f"- `{item['file']}`: 真实文本 tick {item['effective_text_ticks']}，空 tick {item['empty_ticks']}，总 source tick {item['total_ticks']}，带 labels tick {item['labeled_ticks']}。"
        )
    lines.extend(
        [
            "",
            "## 规模生成规则",
            "",
            "- 小规模：50 条真实输入，每条后 5 个空 tick，共 300 source tick。",
            "- 中规模：50 条基础输入的 10 个确定性变体，共 500 条真实输入、3000 source tick。",
            "- 大规模：50 条基础输入的 100 个确定性变体，共 5000 条真实输入、30000 source tick。",
            "- 变体只替换姓名、任务、项目、地点、物品、时间词、罕见词和少量引导句，保留核心重复词和句式。",
            "",
            "## 10 个实验与理论预期",
            "",
        ]
    )
    for exp in EXPERIMENT_EXPECTATIONS:
        metrics = "、".join(exp["metrics"])
        lines.extend(
            [
                f"### {exp['id']} {exp['title']}",
                "",
                f"- 小规模区间：{exp['small_range']}。中/大规模按每 50 条真实输入重复一次同构变体。",
                f"- 预期：{exp['expectation']}",
                f"- 建议审阅指标：{metrics}。",
                "",
            ]
        )
    lines.extend(
        [
            "## 审阅建议",
            "",
            "- 优先检查 `manifest.json` 的 `source_tick_done`、`synthetic_tick_done` 与 `expectation_contracts`，不要只看 run 目录是否存在。",
            "- 天气行动实验应结合 `expectation_contract_events.jsonl` 判断显式、隐式、弱天气线索是否符合预期。",
            "- 教师奖惩实验应对照 `teacher_applied_count`、`teacher_reward_signal_live_total_energy`、`teacher_punish_signal_live_total_energy` 与 CFS 相关指标。",
            "- 记忆和时间实验应关注运行报告里的 residual-memory projection、memory feedback、time sensor delayed task 与 recall 行动。",
            "- 由于当前规模远小于百万真实输入，预期目标是暴露局部方向和指标链路，不应要求自然语言逻辑能力出现大幅跃迁。",
        ]
    )
    DESIGN_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_design_notes_v2(summaries: list[dict[str, Any]]) -> None:
    lines: list[str] = [
        "# AP 行为课程数据集 v2 设计说明",
        "",
            "本文件是旁路说明，不进入训练语料。v2 保留 v1 的自然中文训练文本、教师奖惩、天气 expectation contracts 和默认运行路径，主要优化审阅证据要求。",
        "",
        "## v1 复跑结论作为 v2 调整依据",
        "",
        "- small v1 run `codex_ap_behavioral_small_300_20260505`：300 source tick + 3 synthetic tick，3/3 天气合约成功，`residual_tail_memory_projection_applied` 303/303，旧 `runtime_residual_package_applied=0`。",
        "- medium v1 run `codex_ap_behavioral_medium_3000_silent_20260505`：3000 source tick + 30 synthetic tick，30/30 天气合约成功，`teacher_applied_count` 非零 225 tick，`cfs_signal_count` 非零 2988 tick。",
        "- medium v1 的主要压力：`hdb_structure_count` latest 39733，`timing_total_logic_ms` mean 1233ms，`timing_stimulus_level_ms` mean 683ms；identity hit mean 0.183，created mean 5.182，说明中规模仍偏冷启动/增长压力测试。",
            "- LLM 审阅共同建议：天气与教师链路先保持，优先补 identity/Top/HDB 分段证据；运行参数优化必须先做 300 tick 合约隔离。",
            "- 参数隔离结果：`attention_top_n=12`、`growth_projection_source_er_runtime_share_ratio=0.75`、`induction_projection_new_target_min_energy_floor=0.08` 及后两者组合，均在 small 300 tick 中导致天气合约 1/3 成功，因此 v2 默认不携带这些覆盖。",
        "",
        "## v2 数据集文件",
    ]
    for item in summaries:
        lines.append(
            f"- `{item['file']}`: 真实文本 tick {item['effective_text_ticks']}，空 tick {item['empty_ticks']}，总 source tick {item['total_ticks']}，带 labels tick {item['labeled_ticks']}。"
        )
    lines.extend(
        [
            "",
            "## v2 运行级覆盖",
            "",
            "v2 默认不写入 `app_config_override`，继续使用 runner 的 contract-safe growth-era 基线：",
            "",
            "```yaml",
            "app_config_override: {}",
            "```",
            "",
            "- 已拒绝 `attention_top_n=12`：降低耗时明显，但会让显式/隐式天气动作节点消失，天气合约失败。",
            "- 已拒绝 `growth_projection_source_er_runtime_share_ratio=0.75`：会削弱 weather 行动链路可见性，天气合约失败。",
            "- 已拒绝 `induction_projection_new_target_min_energy_floor=0.08`：identity hit 略升、耗时下降，但天气合约失败，不能作为默认课程参数。",
            "",
            "## v2 审阅要求",
            "",
            "- medium/large 运行后必须分段比较每 300 source tick 的 `hdb_structure_count`、`induction_growth_identity_created_count`、`induction_growth_identity_hit_count`、`induction_growth_identity_shared_cache_hit_count`。",
            "- 每 50 或 100 source tick 抽样 Top：`pool_er_top5`、`pool_ev_top5`、`pool_cp_top5`、`runtime_resolution_*` 与 `component_energy`，用于判断 Top 可读性和结构收敛。",
            "- 继续以 `expectation_contract_events.jsonl` 判断 E05 天气行动，不用执行频次高低单独下结论。",
            "- v2 成功标准不是让 HDB 增长变小本身，而是在天气/教师/CFS/尾巴 memory_id 证据不退化的同时，让 identity created/hit 比例和 Top 可读性更适合审阅。",
            "",
            "## 10 个实验与理论预期",
            "",
        ]
    )
    for exp in EXPERIMENT_EXPECTATIONS:
        metrics = "、".join(exp["metrics"])
        lines.extend(
            [
                f"### {exp['id']} {exp['title']}",
                "",
                f"- 小规模区间：{exp['small_range']}。中/大规模按每 50 条真实输入重复一次同构变体。",
                f"- 预期：{exp['expectation']}",
                f"- 建议审阅指标：{metrics}。",
                "",
            ]
        )
    DESIGN_V2_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    for _size_name, dataset_id, real_text_count, title in SIZE_SPECS:
        doc = build_dataset(dataset_id, title, real_text_count)
        try:
            normalized = validate_and_normalize_dataset(doc)
        except DatasetValidationError as exc:
            raise SystemExit(f"dataset validation failed for {dataset_id}: {exc}") from exc
        summary = summarize_tick_counts(normalized)
        expected_total = real_text_count * (1 + GAP_TICKS_AFTER_TEXT)
        if summary.get("effective_text_ticks") != real_text_count or summary.get("total_ticks") != expected_total:
            raise SystemExit(f"unexpected counts for {dataset_id}: {summary}")
        out_path = DATASETS_DIR / f"{dataset_id}.yaml"
        out_path.write_text(dump_yaml(doc), encoding="utf-8")
        summaries.append({"file": out_path.name, "dataset_id": dataset_id, **summary})

    summaries_v2: list[dict[str, Any]] = []
    for _size_name, dataset_id, real_text_count, title in SIZE_SPECS_V2:
        doc = build_dataset(
            dataset_id,
            title,
            real_text_count,
            version="v2",
            app_config_override=CURRICULUM_V2_APP_CONFIG_OVERRIDE,
        )
        try:
            normalized = validate_and_normalize_dataset(doc)
        except DatasetValidationError as exc:
            raise SystemExit(f"dataset validation failed for {dataset_id}: {exc}") from exc
        summary = summarize_tick_counts(normalized)
        expected_total = real_text_count * (1 + GAP_TICKS_AFTER_TEXT)
        if summary.get("effective_text_ticks") != real_text_count or summary.get("total_ticks") != expected_total:
            raise SystemExit(f"unexpected counts for {dataset_id}: {summary}")
        out_path = DATASETS_DIR / f"{dataset_id}.yaml"
        out_path.write_text(dump_yaml(doc), encoding="utf-8")
        summaries_v2.append({"file": out_path.name, "dataset_id": dataset_id, **summary})

    _write_design_notes(summaries)
    _write_design_notes_v2(summaries_v2)
    report_lines = [
        "# AP 行为课程数据集研发报告 2026-05-05",
        "",
        "已生成三档行为课程数据集。真实训练文本保持自然中文；实验预期和教师/契约信息不进入普通训练文本。",
        "",
        "## 生成结果",
    ]
    for item in summaries:
        report_lines.append(
            f"- `{item['file']}`: 总 source tick {item['total_ticks']}，真实文本 {item['effective_text_ticks']}，空 tick {item['empty_ticks']}，带 labels tick {item['labeled_ticks']}。"
        )
    report_lines.extend(
        [
            "",
            "## 覆盖范围",
            "",
            "覆盖 10 个实验：词汇重复与句式抽象、新词违和与新颖感、教师奖励塑形、教师惩罚与纠偏、先天行动与天气闭环、时间间隔与近因回忆、复杂度与注意力调节、残差记忆与组合召回、矛盾调和与安抚、重复疲劳与可控新鲜度。",
            "",
            "## 验证",
            "",
            "生成脚本已在写入前调用 `validate_and_normalize_dataset()` 和 `summarize_tick_counts()` 校验三档数据集的协议和计数。",
        ]
    )
    REPORT_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    v2_lines = [
        "# AP 行为课程数据集 v2 优化报告 2026-05-05",
        "",
        "v2 基于 small/medium v1 真实复跑结果和 300 tick 参数隔离结果生成。训练文本、10 个实验、教师奖惩、天气合约和默认运行路径保持 v1 设计；新增更严格的审阅证据要求。",
        "",
        "## 复跑依据",
        "",
        "- small v1：`codex_ap_behavioral_small_300_20260505`，300 source tick，3/3 contracts success，LLM 审阅评为可继续实验的健康原型。",
        "- medium v1：`codex_ap_behavioral_medium_3000_silent_20260505`，3000 source tick，30/30 contracts success，旧 residual package 为 0，growth 主链稳定；但 HDB latest 39733，平均逻辑耗时 1233ms，identity hit mean 0.183。",
        "- 中规模第一次失败 run 的根因是 runner progress print 的 Windows `OSError [Errno 22]`，已修复为控制台异常不影响实验。",
        "- v2 候选运行参数隔离：`attention_top_n: 12`、`growth_projection_source_er_runtime_share_ratio: 0.75`、`induction_projection_new_target_min_energy_floor: 0.08` 及后两者组合均导致 small 300 tick 天气合约 1/3，因此全部不进入 v2 默认。",
        "- 当前轮复验发现并修复 ActionManager idle prune 工程 bug：旧 attention_focus 节点因 `last_update_tick` 每 tick 被刷新而永不淘汰，导致 64 节点池满后 weather_stub 无法创建。修复后 small v1/v2 均恢复 3/3 天气合约。",
        "- medium v2 修复后长跑：`codex_ap_behavioral_medium_v2_after_action_prune_fix_3000_20260505`，3000 source tick + 30 synthetic tick，30/30 contracts success，weather source-visible 执行 20 tick，旧 residual package 为 0，LLM 审阅评为 B / 健康可运行原型。",
        "",
        "## v2 文件",
    ]
    for item in summaries_v2:
        v2_lines.append(
            f"- `{item['file']}`: 总 source tick {item['total_ticks']}，真实文本 {item['effective_text_ticks']}，空 tick {item['empty_ticks']}，带 labels tick {item['labeled_ticks']}。"
        )
    v2_lines.extend(
        [
            "",
            "## v2 优化点",
            "",
            "- 不再默认写入 `app_config_override`，优先保证 E05 天气行动、教师反馈、CFS 和残差尾巴 memory_id 证据不退化。",
            "- 保留 v1 语料结构，但强化运行摘要：每 300 source tick 分段统计 HDB/identity/Top，便于 LLM 审阅定位增长斜率与 Top 可读性。",
            "- 被拒绝参数仍可作为后续专项研究对象，但不能作为行为课程数据集默认配置。",
            "- 当前安全版 v2 的优化结论是“数据集与观测口径优化”，不是“默认性能参数优化”：性能/增长压力后续应通过专项 A/B 实验验证，不能并入课程默认。",
            "",
            "## 验证",
            "",
            "- 生成脚本在写入前调用 `validate_and_normalize_dataset()` 和 `summarize_tick_counts()` 校验 v1/v2 六个 YAML。",
            "- small v2 修复后 run `codex_ap_behavioral_small_v2_after_action_prune_fix_300_20260505`：3/3 contracts success；weather source-visible 执行 2；`teacher_applied_count` 非零 24；`cfs_signal_count` 非零 301；旧 runtime residual package 0。",
            "- medium v2 修复后 run `codex_ap_behavioral_medium_v2_after_action_prune_fix_3000_20260505`：30/30 contracts success；`teacher_applied_count` 非零 230；`cfs_signal_count` 非零 2985；`residual_tail_memory_projection_applied` 非零 3028/3030；旧 runtime residual package 0。",
            "- medium v2 LLM 审阅建议：不要继续调低 weather 阈值或默认 attention 参数；优先补 growth identity 成熟度分段、Top5 轻量快照、合约窗口行动切片、缓存中和零消费诊断、HDB 结构质量抽样。",
        ]
    )
    V2_REPORT_PATH.write_text("\n".join(v2_lines) + "\n", encoding="utf-8")

    print("generated")
    for item in summaries:
        print(item)


if __name__ == "__main__":
    main()
