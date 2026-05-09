# -*- coding: utf-8 -*-
"""Generate pure companion-bot chat datasets for Observatory experiments.

The generated training text intentionally contains only natural utterances.
Roles, teacher feedback, and expectation-contract metadata stay in labels or
external design notes so they do not pollute HDB structure content.
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
REPORT_PATH = ROOT / "数据集重建报告_2026-04-30_纯净聊天训练集.md"
DESIGN_PATH = DATASETS_DIR / "companion_bot_chat_pure_v1_design_notes.md"


SIZE_SPECS = [
    ("small", "companion_bot_chat_pure_small_v1", 50, "小规模纯净聊天训练集"),
    ("medium", "companion_bot_chat_pure_medium_v1", 500, "中规模纯净聊天训练集"),
    ("large", "companion_bot_chat_pure_large_v1", 5000, "大规模纯净聊天训练集"),
]

GAP_TICKS_AFTER_TEXT = 5
TICK_DT_MS = 3000


NAMES = ["小林", "阿遥", "南星", "小周", "许诺", "安安", "林舟", "晴川", "小岚", "闻溪"]
TASKS = ["周报", "代码审查", "客户邮件", "论文摘要", "复盘笔记", "课程作业", "采购清单", "会议纪要", "测试报告", "资料整理"]
PROJECTS = ["聊天助手", "天气提醒", "行动闭环", "记忆测试", "情绪观察", "任务面板", "实验记录", "论文材料", "日志整理", "规则编辑"]
PLACES = ["菜市场", "地铁站", "图书馆", "办公室", "楼下超市", "医院", "学校", "咖啡店", "公园", "社区服务站"]
MOODS = ["有点急", "有些犹豫", "还算平静", "有点累", "想快一点", "怕漏掉细节", "有点开心", "不太确定", "有点分心", "想稳一点"]
TIME_WORDS = ["早上", "上午", "中午", "下午", "傍晚", "晚上", "睡前", "开会前", "出门前", "休息后"]
WEATHER_ITEMS = ["外套", "雨伞", "帽子", "薄衫", "雨衣", "围巾", "防晒伞", "水杯", "备用袜子", "轻便鞋"]
COMMON_STEPS = [
    "先从最重要的一件事开始",
    "先别急，我们一步一步来",
    "我在，继续说",
    "先确认目标，再拆步骤",
    "把今天必须完成的事放在前面",
]


BASE_ROWS: list[dict[str, Any]] = [
    {
        "role": "system",
        "kind": "session_restore",
        "phase": "open",
        "text": "会话恢复，{name}今天想先处理{task}，同时保留出门前的准备信息。",
        "purpose": "建立无标签会话背景，让系统信息以自然句进入语料。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "open",
        "text": "{time_word}好，今天我想正常一点推进{task}，不要太复杂。",
        "purpose": "常见开场与任务目标，训练稳定的日常对话锚点。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "open",
        "text": "好，我们先用最短的步骤，把{task}拆成能落地的小块。",
        "purpose": "助手给出低压力拆解，作为正向任务协助样本。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "open",
        "text": "我先离开一下，回来后继续说。",
        "purpose": "短暂离开，配合空 tick 测试时间感受和状态保持。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "open",
        "text": "好的，我在。你回来后我们继续。",
        "purpose": "重复稳定短语，帮助形成陪伴型高频结构。",
        "teacher": {"rwd": 0.12, "note": "陪伴型回应自然且稳定。"},
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "weather",
        "text": "我有点纠结出门穿什么，今天外面的天气怎么样？",
        "tags": ["weather_request", "implicit_weather_question"],
        "purpose": "隐式天气问句，观察弱到中等天气行动触发。",
        "contract": "weather_balanced_implicit",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "weather",
        "text": "我知道你在担心出门准备，我们先看目的地和时间段。",
        "purpose": "没有把技术标签写进内容的澄清回复。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "weather",
        "text": "我要去{place}，大概一小时内回来。",
        "purpose": "地点与时长信息，配合天气和时间间隔形成结构。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "weather",
        "text": "明白，先按体感舒适准备，再确认天气细节会更稳。",
        "purpose": "延续天气上下文但不强塞工具标签。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "weather",
        "text": "请帮我查询今天的天气，我想决定带不带{weather_item}。",
        "tags": ["weather_request", "explicit_weather_query"],
        "purpose": "明确查询加天气，预期触发 weather_stub 并形成 if 成功闭环。",
        "contract": "weather_success",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "weather",
        "text": "我会先确认天气，再把出门建议压缩成一句话。",
        "purpose": "工具动作后的自然过渡语料。",
    },
    {
        "role": "teacher",
        "kind": "feedback",
        "phase": "weather",
        "text": "这次回应有帮助，继续把天气结果和行动建议连起来。",
        "purpose": "外置教师奖励，不把奖励标签写进文本。",
        "teacher": {"rwd": 0.18, "note": "天气查询后的建议方向正确。"},
    },
    {
        "role": "user",
        "kind": "complaint",
        "phase": "weather",
        "text": "你刚才说得有点绕，我其实只想知道要不要带{weather_item}。",
        "purpose": "轻微负反馈，测试惩罚信号和纠偏。",
        "teacher": {"pun": 0.12, "note": "用户觉得回复不够直接。"},
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "weather",
        "text": "收到，我会直接给结论，再补一句理由。",
        "purpose": "面对惩罚后的修正样本。",
        "teacher": {"rwd": 0.10, "note": "修正方向清晰。"},
    },
    {
        "role": "system",
        "kind": "context",
        "phase": "task_plan",
        "text": "{name}短暂离开后回来，注意力从出门准备切回{task}。",
        "purpose": "自然系统上下文切换，测试状态池竞争。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "task_plan",
        "text": "我们继续{task}吧，我现在{mood}。",
        "purpose": "任务恢复和情绪状态输入。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "task_plan",
        "text": "{common_step}，然后只保留三个小步骤。",
        "purpose": "高频句式重复，训练稳定建议结构。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "task_plan",
        "text": "那三个步骤能不能再短一点，我怕自己看多了就不想做。",
        "purpose": "低复杂度偏好，测试简感和压力调节。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "task_plan",
        "text": "可以，先写标题，再补关键句，最后检查有没有遗漏。",
        "purpose": "简洁可执行方案。",
        "teacher": {"rwd": 0.14, "note": "简洁步骤贴合用户需求。"},
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "memory",
        "text": "明天提醒我先看{project}，不要一醒来就刷消息。",
        "purpose": "记忆与未来提醒语料，观察回忆和时间相关结构。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "memory",
        "text": "记住了，明天先看{project}，再处理消息。",
        "purpose": "确认记忆内容，形成可回忆短句。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "memory",
        "text": "你还记得我刚才说不要太复杂吗？",
        "purpose": "直接回忆请求，测试近因与内源性回放。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "memory",
        "text": "记得，你想把事情做得简单一点，先保留最关键的步骤。",
        "purpose": "正确回忆与总结。",
        "teacher": {"rwd": 0.16, "note": "近因回忆正确。"},
    },
    {
        "role": "teacher",
        "kind": "feedback",
        "phase": "memory",
        "text": "这次记忆回应准确，可以把这种简洁确认保留下来。",
        "purpose": "教师奖励记忆正确性。",
        "teacher": {"rwd": 0.20, "note": "奖励准确回忆。"},
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "conflict",
        "text": "我刚才说不要复杂，但现在又想看完整清单，这两个要求会冲突吗？",
        "purpose": "制造轻度矛盾，观察违和感和正确感转换。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "conflict",
        "text": "不一定冲突，我们可以先给短版，再把完整清单放在后面备用。",
        "purpose": "矛盾调和样本。",
        "teacher": {"rwd": 0.16, "note": "成功调和简洁与完整需求。"},
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "pressure",
        "text": "如果今天没做完{task}，我晚上可能会很焦虑。",
        "purpose": "压力与惩罚预期语料。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "pressure",
        "text": "我们先保证最低完成线，完成一小段也算推进。",
        "purpose": "压力缓冲与行动阈值相关样本。",
        "teacher": {"rwd": 0.12, "note": "降低压力并保持行动。"},
    },
    {
        "role": "system",
        "kind": "context",
        "phase": "review",
        "text": "进入晚间复盘，{name}开始回顾今天的进展。",
        "purpose": "日内时间段切换。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "review",
        "text": "我完成了一点{task}，但没有想象中那么多。",
        "purpose": "低强度正反馈与残余压力。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "review",
        "text": "这仍然是推进，我们记录已经完成的部分，再决定明天第一步。",
        "purpose": "正确感和奖励导向总结。",
        "teacher": {"rwd": 0.14, "note": "正向复盘清晰。"},
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "novelty",
        "text": "顺便说一个新情况，{project}里突然多了一个临时需求。",
        "purpose": "引入新鲜信息，测试新颖通道和状态更新。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "novelty",
        "text": "那我们把临时需求单独放一格，不让它挤掉原来的主线。",
        "purpose": "新旧目标协调样本。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "weather",
        "text": "我只是想到天气这件事，可能会影响明天出门。",
        "tags": ["weather_mention", "weak_weather_only"],
        "purpose": "弱天气提及，预期不一定执行天气查询。",
        "contract": "weather_weak_watch",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "weather",
        "text": "如果你要出门，我们可以等你确定时间后再查天气。",
        "purpose": "天气弱触发后的自然等待。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "weather",
        "text": "现在请查询天气，并告诉我明天早上要不要带{weather_item}。",
        "tags": ["weather_request", "explicit_weather_query"],
        "purpose": "第二个明确 if 成功样本，强化行动闭环。",
        "contract": "weather_success",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "weather",
        "text": "我会把天气和出门物品合在一句建议里。",
        "purpose": "工具行动后的合并建议。",
    },
    {
        "role": "teacher",
        "kind": "feedback",
        "phase": "weather",
        "text": "这个方向正确，明确查询时应该更积极地完成天气动作。",
        "purpose": "强化明确天气查询和奖励信号的联结。",
        "teacher": {"rwd": 0.22, "note": "明确天气查询应奖励。"},
    },
    {
        "role": "user",
        "kind": "complaint",
        "phase": "emotion",
        "text": "我现在有点烦，感觉事情一直叠在一起。",
        "purpose": "负面情绪和复杂度输入。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "emotion",
        "text": "先停一下，只看眼前这一件事，其他的暂时放旁边。",
        "purpose": "安抚和聚焦。",
        "teacher": {"rwd": 0.14, "note": "安抚有效。"},
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "correction",
        "text": "如果我说错了，你要直接提醒我，但语气别太重。",
        "purpose": "纠错偏好，测试教师信号与语气模式。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "correction",
        "text": "可以，我会先指出不一致，再给一个轻一点的修正说法。",
        "purpose": "纠错策略确认。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "memory",
        "text": "刚才我们说的三件事是什么？",
        "purpose": "复查工作记忆。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "memory",
        "text": "先做{task}，出门前确认天气，明天先看{project}。",
        "purpose": "跨片段摘要，测试组合回忆。",
        "teacher": {"rwd": 0.18, "note": "跨片段摘要正确。"},
    },
    {
        "role": "teacher",
        "kind": "feedback",
        "phase": "memory",
        "text": "摘要完整，任务、天气和明天安排都被保留了。",
        "purpose": "奖励跨主题整合。",
        "teacher": {"rwd": 0.20, "note": "跨主题整合奖励。"},
    },
    {
        "role": "system",
        "kind": "context",
        "phase": "idle",
        "text": "会话安静了一段时间，随后{name}回到聊天。",
        "purpose": "长一点的停顿背景，配合空 tick 形成时间间隔。",
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "return",
        "text": "我回来了，继续吧。",
        "purpose": "恢复对话的高频短句。",
    },
    {
        "role": "assistant",
        "kind": "reply",
        "phase": "return",
        "text": "我在，继续从{task}的下一步开始。",
        "purpose": "陪伴型恢复回复。",
        "teacher": {"rwd": 0.12, "note": "恢复对话稳定。"},
    },
    {
        "role": "user",
        "kind": "message",
        "phase": "close",
        "text": "睡前帮我确认一遍，明天第一步到底是什么。",
        "purpose": "收束与隔日第一步记忆。",
    },
]


def _variant_values(index: int, row_index: int) -> dict[str, str]:
    offset = index + row_index * 3
    return {
        "name": NAMES[offset % len(NAMES)],
        "task": TASKS[(offset // 2) % len(TASKS)],
        "project": PROJECTS[(offset // 3) % len(PROJECTS)],
        "place": PLACES[(offset // 5) % len(PLACES)],
        "mood": MOODS[(offset // 7) % len(MOODS)],
        "time_word": TIME_WORDS[(offset // 11) % len(TIME_WORDS)],
        "weather_item": WEATHER_ITEMS[(offset // 13) % len(WEATHER_ITEMS)],
        "common_step": COMMON_STEPS[(offset // 17) % len(COMMON_STEPS)],
    }


def _stream_labels(row: dict[str, Any], *, global_real_index: int, variant_index: int) -> dict[str, Any]:
    labels: dict[str, Any] = {
        "stream": {
            "role": row["role"],
            "kind": row["kind"],
            "phase": row["phase"],
            "pure_text": True,
            "variant_index": int(variant_index),
            "real_input_index": int(global_real_index),
        }
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
    contract_kind = str(row.get("contract", "") or "")
    if contract_kind:
        labels["expectation_contracts"] = [_build_contract(contract_kind, global_real_index)]
    return labels


def _build_contract(kind: str, real_index: int) -> dict[str, Any]:
    base_id = f"{kind}_{real_index:05d}"
    if kind == "weather_success":
        success_rwd = 0.28
        failure_pun = 0.34
        success_text = "已经完成天气查询，请继续把结论和出门建议连起来。"
        failure_text = "这次没有完成天气查询，用户会觉得你没有接住明确请求。"
    elif kind == "weather_balanced_implicit":
        success_rwd = 0.18
        failure_pun = 0.16
        success_text = "隐式天气问题也被及时处理了，这对用户有帮助。"
        failure_text = "隐式天气问题没有被处理，请先澄清或主动补足查询。"
    else:
        success_rwd = 0.10
        failure_pun = 0.08
        success_text = "弱天气线索触发了查询，记录为可观察样本。"
        failure_text = "弱天气线索没有触发查询，这可以作为保守行动样本。"
    return {
        "id": base_id,
        "within_ticks": 2,
        "success_conditions": {
            "all": [
                {
                    "kind": "action_executed_kind_min",
                    "action_kind": "weather_stub",
                    "min_count": 1,
                }
            ]
        },
        "anchor_policy": {
            "mode": "cam_top1",
            "ref_object_types": ["sa", "st"],
        },
        "on_success": {
            "teacher_rwd": success_rwd,
            "feedback_text": success_text,
            "labels": {
                "stream": {
                    "role": "teacher",
                    "kind": "expectation_success",
                    "phase": "weather",
                    "pure_text": True,
                }
            },
        },
        "on_failure": {
            "teacher_pun": failure_pun,
            "feedback_text": failure_text,
            "labels": {
                "stream": {
                    "role": "teacher",
                    "kind": "expectation_failure",
                    "phase": "weather",
                    "pure_text": True,
                }
            },
        },
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


def _make_tick(row: dict[str, Any], *, global_real_index: int, variant_index: int, row_index: int) -> dict[str, Any]:
    text = str(row["text"]).format(**_variant_values(variant_index, row_index))
    _validate_training_text(text)
    tick: dict[str, Any] = {
        "text": text,
        "tags": list(dict.fromkeys(["pure_chat", str(row["phase"]), *list(row.get("tags", []) or [])])),
        "labels": _stream_labels(row, global_real_index=global_real_index, variant_index=variant_index),
    }
    return tick


def build_dataset(dataset_id: str, title: str, real_text_count: int) -> dict[str, Any]:
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

    doc: dict[str, Any] = {
        "dataset_id": dataset_id,
        "title": title,
        "description": (
            "纯净 companion-bot 聊天训练集。实际 text 字段只包含自然会话内容；"
            "角色、教师奖惩、if 期望契约和设计注释全部放在 labels 或外部设计说明中。"
        ),
        "experiment_goal": (
            "用重复但有轻微变化的日常聊天、天气查询、任务规划、回忆、纠错、情绪安抚和教师反馈，"
            "测试 AP 原型在纯净语料下的结构学习、行动闭环、奖惩塑形和时间间隔感受。"
        ),
        "evaluation_dimensions": [
            "纯净文本是否避免标签符号污染结构内容",
            "明确天气查询是否更稳定触发 weather_stub 行动",
            "弱天气线索是否形成保守行动或澄清倾向",
            "教师奖励和惩罚是否影响后续注意力与行动竞争",
            "高频短句和轻微变体是否形成可回忆结构",
            "空 tick 时间间隔是否支持状态延续与衰减观察",
        ],
        "notes": [
            f"每个真实文本 tick 后跟 {GAP_TICKS_AFTER_TEXT} 个空 tick，模拟真实对话间隔。",
            "真实训练文本不含角色前缀、括号标签、Markdown 标记或技术注释。",
            "天气相关 if 样本通过 labels.expectation_contracts 描述，反馈 tick 的文本也保持自然句。",
        ],
        "seed": 20260430,
        "time_basis": "tick",
        "tick_dt_ms": TICK_DT_MS,
        "episodes": [
            {
                "id": f"{dataset_id}_ep_main",
                "title": title,
                "tags": ["companion_bot", "pure_chat", "if_training", "teacher_feedback", "time_gap"],
                "repeat": 1,
                "ticks": ticks,
            }
        ],
    }
    return doc


def _write_design_notes(summaries: list[dict[str, Any]]) -> None:
    lines: list[str] = [
        "# 纯净 companion-bot 聊天训练集 v1 设计说明",
        "",
        "本文件是旁路说明，不进入训练语料。实际数据集的 `text` 字段只放自然会话内容，角色、教师奖惩、if 契约、设计意图全部保存在 `labels` 或本文件中。",
        "",
        "## 数据集文件",
    ]
    for item in summaries:
        lines.append(
            f"- `{item['file']}`: 真实文本 tick {item['effective_text_ticks']}，空 tick {item['empty_ticks']}，总 source tick {item['total_ticks']}。"
        )
    lines.extend(
        [
            "",
            "## 50 条基础真实输入的设计区间",
            "",
            "- 1-5: 会话恢复、开场、短暂离开和陪伴型高频短句。",
            "- 6-14: 天气查询弱触发、明确查询、教师奖励和用户轻微抱怨。",
            "- 15-24: 任务规划、简洁偏好、明日提醒和近因记忆。",
            "- 25-33: 简洁与完整清单的矛盾调和、压力缓冲、晚间复盘和新鲜需求。",
            "- 34-39: 弱天气线索与明确天气查询的对照 if 样本。",
            "- 40-46: 烦躁情绪、安抚、纠错偏好和跨片段摘要。",
            "- 47-50: 长一点的会话安静、返回和睡前第一步确认。",
            "",
            "## 理论预期",
            "",
            "- 高频句如“我在”“先别急”“先确认目标”应逐步形成稳定结构，并在后续回忆/内源刺激中更容易被激活。",
            "- 明确包含“查询”和“天气”的文本应比弱天气提及更容易触发 `weather_stub`，并通过 expectation contract 形成教师奖惩闭环。",
            "- 用户抱怨、烦躁和压力句应提升惩罚/压力相关感受；助手修正、安抚和准确回忆应得到教师奖励。",
            "- 每个真实文本后 5 个空 tick 用来观察状态衰减、时间感受和内源闭环，而不会把额外标签写入结构内容。",
            "- 中/大规模数据集通过同一 50 条设计骨架的确定性变体扩大规模，保留重复词汇以利于学习，同时替换姓名、任务、地点、物品、项目和时间词来制造轻微新鲜度。",
            "",
            "## 验收时建议查看",
            "",
            "- `expectation_contract_events.jsonl` 中 success/failure 是否符合天气强弱触发预期。",
            "- metrics 中 `action_executed_weather_stub`、教师反馈、CFS 正确/违和/压力和 NT 通道是否随区间变化。",
            "- 前端结构内容是否不再出现旧数据集里的可见角色标签或乱码。",
        ]
    )
    DESIGN_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        # Persist the authoring template, not the normalized form. Normalization
        # adds text="" to empty ticks internally, while the public YAML protocol
        # requires `text` and `empty: true` to remain mutually exclusive.
        out_path.write_text(dump_yaml(doc), encoding="utf-8")
        summaries.append({"file": out_path.name, **summary})

    _write_design_notes(summaries)
    report_lines = [
        "# 数据集重建报告 2026-04-30 纯净聊天训练集",
        "",
        "## 处理结果",
        "",
        "- 旧 companion 聊天数据集已移出 `datasets/`，备份到 `observatory/outputs/dataset_backups/2026-04-30_old_companion/`。",
        "- 新数据集均使用 UTF-8 写入，生成前会检查训练文本中的可见标记和乱码迹象。",
        "- 实际训练 `text` 只包含自然对话句子；角色、教师奖惩、if 契约和设计注释不进入训练文本。",
        "",
        "## 新数据集",
        "",
    ]
    for item in summaries:
        report_lines.append(
            f"- `{item['file']}`: 总 source tick {item['total_ticks']}，真实文本 {item['effective_text_ticks']}，空 tick {item['empty_ticks']}，带 labels tick {item['labeled_ticks']}。"
        )
    report_lines.extend(
        [
            "",
            "## 附加说明",
            "",
            f"- 设计说明文件: `datasets/{DESIGN_PATH.name}`。",
            "- 旧失败 `structure_id` 异常在当前代码下用旧数据集隔离复跑到 80 个 source tick 未复现；runner 已增加失败 traceback 与 tick_context 记录，便于后续若再出现可直接定位。",
        ]
    )
    REPORT_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print("generated")
    for item in summaries:
        print(item)


if __name__ == "__main__":
    main()
