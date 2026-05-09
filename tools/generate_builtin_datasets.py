# -*- coding: utf-8 -*-
"""
Generate built-in experiment datasets with deterministic, text-first corpora.

Goals:
- dataset sizes are counted by effective text ticks
- avoid empty-tick inflation for text-first corpora (keep intent explicit per dataset)
- keep experiment themes explicit and auditable
"""

from __future__ import annotations

import sys
from itertools import product
from pathlib import Path


def _ensure_repo_root_on_syspath() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    return repo_root


REPO_ROOT = _ensure_repo_root_on_syspath()

from observatory.experiment.io import dump_yaml  # noqa: E402


DATASETS_DIR = REPO_ROOT / "datasets"


def unique_take(iterable, limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in iterable:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    if len(out) < limit:
        raise ValueError(f"Corpus underfilled: need {limit}, got {len(out)}")
    return out


def chunk_ticks(texts: list[str], *, chunk_size: int, prefix: str, tags: list[str]) -> list[dict]:
    episodes: list[dict] = []
    for idx in range(0, len(texts), chunk_size):
        block = texts[idx : idx + chunk_size]
        episodes.append(
            {
                "id": f"{prefix}_{idx // chunk_size + 1:03d}",
                "tags": list(tags),
                "repeat": 1,
                "ticks": [{"text": text} for text in block],
            }
        )
    return episodes


def greeting_lines():
    greets = [
        "你好",
        "你好呀",
        "你好啊",
        "嗨",
        "哈喽",
        "早上好",
        "中午好",
        "下午好",
        "晚上好",
        "很高兴见到你",
        "见面啦",
        "欢迎回来",
        "辛苦了",
        "今天状态怎么样",
        "我来打个招呼",
        "这次我们继续",
        "我们开始吧",
        "我先说一句",
        "我想先确认一下",
        "先从简单的开始",
    ]
    tones = [
        "请先打个招呼",
        "我们从问候开始",
        "这是一句简单开场",
        "把气氛放轻松一点",
        "先建立一个稳定开头",
        "先对齐一下我们要做的事",
        "先把上下文固定住",
        "先做一个短开场",
        "先把语气放平稳",
        "先用一句话把场景立起来",
    ]
    followups = [
        "然后继续聊天",
        "再进入下一步任务",
        "接着描述你的想法",
        "随后观察系统反应",
        "再补充一句细节",
        "然后我们开始记录",
        "接着再做一个小测试",
        "之后我们再推进一步",
        "接下来先问一个问题",
        "然后再解释你看到的现象",
    ]
    for g, tone, follow in product(greets, tones, followups):
        yield f"{g}，{tone}，{follow}。"


def sequence_lines():
    first_actions = [
        "先洗手",
        "先开灯",
        "先拿钥匙",
        "先读题",
        "先整理桌面",
        "先确认方向",
        "先关门",
        "先穿外套",
        "先记录结果",
        "先观察天气",
        "先连接电源",
        "先打开文档",
        "先检查列表",
        "先做一次复核",
        "先标注重点",
        "先设置计时器",
        "先把桌面清空",
        "先写下假设",
        "先找到入口",
        "先做一步热身",
    ]
    second_actions = [
        "再吃饭",
        "再出门",
        "再开门",
        "再回答问题",
        "再开始实验",
        "再往前走",
        "再放下书包",
        "再联系同伴",
        "再检查一次",
        "再决定路线",
        "再保存文件",
        "再提交记录",
        "再读一遍结果",
        "再对照标准答案",
        "再发出提醒",
        "再进行下一轮",
        "再做一次总结",
        "再补充边界条件",
        "再写出结论",
        "再回到主任务",
    ]
    cautions = [
        "不要把顺序反过来",
        "顺序一变结果就不同",
        "前后次序非常重要",
        "如果颠倒就会出错",
        "记住先后关系",
        "先后顺序决定因果",
        "不要跳过中间步骤",
        "不要把并行当成串行",
        "先后错了会造成误判",
        "顺序错误会导致重复劳动",
    ]
    for a1, a2, caution in product(first_actions, second_actions, cautions):
        if a1 == a2:
            continue
        yield f"{a1}，{a2}，{caution}。"


def memory_location_lines():
    people = ["小林", "小周", "小陈", "小赵", "小吴", "小郑", "小何", "小许", "小沈", "小孙"]
    objects = ["红伞", "蓝杯子", "白笔记本", "黑色耳机", "绿色文件夹", "银色钥匙", "黄色毛巾", "橙色水瓶", "灰色围巾", "紫色卡片"]
    places = ["门边", "书架旁", "窗台上", "办公桌左侧", "沙发后面", "柜子顶层", "走廊尽头", "厨房台面", "会议室门口", "背包夹层"]
    followups = ["后来又回来确认了一次", "接着去做别的事了", "随后提醒同伴也记住", "然后把这个位置写进备忘录", "之后又顺手整理了一遍"]
    for person, obj, place, tail in product(people, objects, places, followups):
        yield f"{person}把{obj}放在{place}，{tail}。"


def emotion_lines():
    people = ["她", "他", "老师", "学生", "研究员", "值班员", "朋友", "同事", "队友", "旁观者"]
    events = ["听到好消息", "看到结果偏差变小", "发现实验终于成功", "想起丢失的物品找到了", "看到天气突然转晴", "等到了迟来的回复", "完成了艰难的任务", "意识到自己记错了顺序", "发现计划被打乱", "碰到意料之外的提问"]
    emotions = ["高兴", "紧张", "惊讶", "安心", "失望", "兴奋", "疑惑", "惭愧", "自豪", "担心"]
    reasons = ["因为变化超出了预期", "因为结果终于和努力对应上了", "因为先前的担忧消失了一部分", "因为现场信息和记忆出现了冲突", "因为新的线索改变了判断", "因为目标离自己更近了一点"]
    for person, event, emotion, reason in product(people, events, emotions, reasons):
        yield f"{person}{event}以后感到{emotion}，{reason}。"


def negation_lines():
    subjects = [
        "我",
        "你",
        "他",
        "她",
        "我们",
        "这个系统",
        "这台系统",
        "这组样本",
        "这次实验",
        "当前方案",
        "这个回答",
        "刚才那个判断",
        "这个流程",
        "这条规则",
        "这个假设",
        "这段记忆",
        "这次回忆",
        "这个结构",
        "这条链路",
        "这个结论",
    ]
    intents = [
        "不想现在结束对话",
        "不准备立刻查天气",
        "不应该忽略顺序差异",
        "不能把相反结论当成一样",
        "不会因为一次成功就停止验证",
        "不适合在信息不足时下定论",
        "不该把空白当成有效语料",
        "不能把取消请求误判成继续请求",
        "不会把左和右混成同一件事",
        "不打算跳过中间步骤",
        "不应该把回忆当成外部输入",
        "不能把内部片段当作新证据无限放大",
        "不该把噪声当成规律",
        "不应该忽略标签信号",
        "不该在没有复核时就下结论",
        "不能用一句话概括所有情况",
        "不该只看结果不看过程",
        "不应该把不同对象合并成同一类",
        "不能把短暂波动当成长期趋势",
        "不该让解释变得不可审计",
    ]
    consequences = [
        "所以还要继续观察",
        "因此需要重新确认条件",
        "这意味着后续动作要变",
        "所以结论必须更谨慎",
        "因此应该保留反例",
        "所以必须记录当前上下文",
        "所以要把假设写清楚",
        "因此要再跑一轮验证",
        "所以要把边界条件补齐",
        "因此要把原因拆开说明",
    ]
    for subject, intent, consequence in product(subjects, intents, consequences):
        yield f"{subject}{intent}，{consequence}。"


def expectation_lines():
    subjects = ["我们", "研究员", "观察者", "系统", "测试者", "老师", "学生", "队友", "用户", "值班员"]
    expected = ["原本以为今天会很顺利", "本来判断会立刻收敛", "先前猜测输入会保持稳定", "之前预计不会出现新组合", "一开始相信记忆召回会很准确", "最初以为不会出现明显违和感", "刚才还以为结构已经学稳了", "本来认定这次回答会更流畅", "先前认为不会再有惊讶", "原先猜想不会再出新的偏差"]
    actual = ["结果却冒出了新的冲突", "结果出现了完全不同的组合", "结果系统突然给出相反反应", "结果后续输入改变了判断方向", "结果中途插入了一条意外信息", "结果召回对象和预期不一致", "结果还是出现了迟疑与不确定", "结果观察台里出现了新的高峰对象", "结果旧记忆被重新放大了", "结果输出比预期更跳跃"]
    for subject, exp, actual in product(subjects, expected, actual):
        yield f"{subject}{exp}，{actual}。"


def abstraction_lines():
    left = ["钥匙", "密码", "地图", "目录", "种子", "索引", "桥梁", "问题", "骨架", "灯塔"]
    right = ["门", "账户", "路径", "书页", "植物", "记忆库", "两岸", "答案", "结构", "方向"]
    left2 = ["训练样本", "线索", "回声", "标签", "老师反馈", "节奏", "提示词", "坐标", "规则", "草图"]
    right2 = ["泛化能力", "推理链", "召回", "判断", "修正", "时间感", "输出风格", "定位", "决策", "成品"]
    for a, b, c, d in product(left, right, left2, right2):
        yield f"{a}对{b}，就像{c}对{d}。"


def composition_lines():
    colors = ["蓝色", "红色", "绿色", "金色", "银色", "橙色", "白色", "黑色", "灰色", "紫色"]
    animals = ["海豚", "狐狸", "白鹭", "猫", "乌鸦", "兔子", "鲸鱼", "松鼠", "鹿", "鹦鹉"]
    places = ["图书馆里", "实验室门口", "雨后的操场上", "安静的会议室中", "山路拐角处", "地铁站旁边", "海边栈道上", "旧仓库前", "花园中央", "夜色中的桥下"]
    actions = ["认真整理卡片", "盯着地图发呆", "缓慢地来回踱步", "突然开始唱歌", "用尾巴拍了拍箱子", "安静地观察人群", "试图把纸张叠整齐", "把小石子排成一列", "对着风轻轻点头", "把问题重复了一遍"]
    for color, animal, place, action in product(colors, animals, places, actions):
        yield f"{color}的{animal}在{place}{action}。"


def counterfactual_lines():
    conditions = [
        "如果先记录再判断",
        "如果先问需求再行动",
        "如果先看到左边再看到右边",
        "如果先获得奖励再继续学习",
        "如果先遇到反例再归纳",
        "如果先回忆旧经验再看新输入",
        "如果先理解上下文再回答",
        "如果先确认否定词再下结论",
        "如果先分离对象和属性",
        "如果先观察时间间隔",
        "如果先写出假设再验证",
        "如果先把流程冻结再改动",
        "如果先定位瓶颈再优化",
        "如果先做小样本再放大",
        "如果先看数据再看结论",
        "如果先对齐口径再统计",
        "如果先把空 tick 变成有文本的步骤",
        "如果先限制递归展开的目标范围",
        "如果先避免把中间产物重复写回",
        "如果先把索引孤儿清理掉",
        "如果先把结构引用和文本显示分离",
        "如果先区分 current 和 internal 的来源",
        "如果先把标签解释为可审计记录",
        "如果先给每个实验写清楚目的",
        "如果先写出评价指标再跑实验",
        "如果先把错误样例纳入语料",
        "如果先做时间桶的对照实验",
        "如果先把召回准确率量化",
        "如果先把可读性做评分",
        "如果先把异常 case 做回归测试",
        "如果先把种子固定",
        "如果先把输出保存成证据",
    ]
    alternate = [
        "那么错误会少一些",
        "那么后续会更稳",
        "那么召回目标更清楚",
        "那么惊讶不会这么强",
        "那么压力也许会下降",
        "那么判断更容易解释",
        "那么结构边界会更清晰",
        "那么不会把不同请求混为一谈",
        "那么学习过程更可审计",
        "那么结果更容易复现",
        "那么性能消耗会更可控",
        "那么图表会更接近真实语料",
        "那么数据集规模会更可信",
        "那么长期跑不会被污染拖垮",
        "那么观察到的趋势更可靠",
        "那么改动风险会更小",
        "那么系统更容易泛化",
        "那么冷启动会更快结束",
        "那么逻辑链更容易对齐",
        "那么实验结论更严谨",
        "那么每个 tick 的意义更明确",
        "那么空 tick 不会误导统计",
        "那么教师信号更容易起作用",
        "那么内源刺激也能正确参与学习",
        "那么异常更容易被定位",
        "那么复盘成本会降低",
        "那么召回准确率能稳步提升",
        "那么文本可读性会更好",
        "那么结构抽象更稳健",
        "那么意外和惊讶更可测量",
        "那么长期学习更像真实场景",
        "那么系统更接近理论预期",
    ]
    for cond, alt in product(conditions, alternate):
        yield f"{cond}，{alt}。"


def confidence_lines():
    subjects = ["这个回答", "这次推断", "当前记忆召回", "刚才的解释", "这条结构抽象", "本轮判断", "这次排序", "这个工具选择", "这条时间感受", "这段思维文本"]
    confidence = ["让我很有把握", "让我只有一点把握", "目前把握感很弱", "看起来相当确定", "仍然需要更多验证", "似乎足够稳定", "暂时还不能完全确认", "已经接近可复用", "还有明显的不确定性", "需要和反例一起看"]
    reasons = ["因为线索一致", "因为反例还不够多", "因为新旧信息冲突", "因为顺序关系很清楚", "因为目标对象已经聚焦", "因为中间步骤仍然缺失", "因为时间跨度带来了干扰", "因为属性和对象还在缠绕", "因为反馈信号非常明确", "因为上下文还不够完整"]
    for subject, conf, reason in product(subjects, confidence, reasons):
        yield f"{subject}{conf}，{reason}。"


GENERAL_BUILDERS = [
    ("greeting", greeting_lines),
    ("sequence", sequence_lines),
    ("memory", memory_location_lines),
    ("emotion", emotion_lines),
    ("negation", negation_lines),
    ("expectation", expectation_lines),
    ("abstraction", abstraction_lines),
    ("composition", composition_lines),
    ("counterfactual", counterfactual_lines),
    ("confidence", confidence_lines),
]


def attach_dataset_meta(
    payload: dict,
    *,
    title: str,
    description: str,
    experiment_goal: str,
    evaluation_dimensions: list[str],
    notes: list[str],
) -> dict:
    doc = dict(payload)
    doc["title"] = title
    doc["description"] = description
    doc["experiment_goal"] = experiment_goal
    doc["evaluation_dimensions"] = list(evaluation_dimensions)
    doc["notes"] = list(notes)
    return doc


def build_general_dataset(*, dataset_id: str, total_text_ticks: int, chunk_size: int) -> dict:
    per_category = total_text_ticks // len(GENERAL_BUILDERS)
    remainder = total_text_ticks % len(GENERAL_BUILDERS)
    episodes: list[dict] = []
    for idx, (name, builder) in enumerate(GENERAL_BUILDERS):
        want = per_category + (1 if idx < remainder else 0)
        texts = unique_take(builder(), want)
        episodes.extend(chunk_ticks(texts, chunk_size=chunk_size, prefix=f"ep_{name}", tags=[name, "text_first"]))
    return attach_dataset_meta({
        "dataset_id": dataset_id,
        "seed": 20260418,
        "time_basis": "tick",
        "tick_dt_ms": 100,
        "episodes": episodes,
    },
        title=f"经典综合语料集（{total_text_ticks} 条真实文本）",
        description="覆盖问候、顺序、记忆、情绪、否定、期待、抽象、组合、反事实、把握感等多个实验主题。",
        experiment_goal="用于观察系统在较长文本训练中，结构抽象、奖惩稳定性、记忆召回与文本可读性是否逐步成形。",
        evaluation_dimensions=["结构抽象能力", "记忆召回准确率", "情绪与认知感受稳定性", "输出文本可读性"],
        notes=["规模统计按真实文本 tick 计数", "空 tick 不参与经典综合数据集规模计算"],
    )


def build_time_recall_dataset() -> dict:
    people = ["小林", "小周", "小陈", "小赵", "小吴", "小郑", "小何", "小许", "小沈", "小孙"]
    primary_objects = ["红伞", "蓝杯子", "白笔记本", "黑色耳机", "绿色文件夹", "银色钥匙", "黄色毛巾", "橙色水瓶", "灰色围巾", "紫色卡片"]
    secondary_objects = ["地图", "药盒", "充电器", "相机", "便签纸", "手套", "眼镜盒", "票据袋", "记号笔", "雨衣"]
    primary_places = ["门边", "窗台上", "书架旁", "沙发后面", "桌子左侧", "柜子顶层", "背包夹层", "会议室门口", "厨房台面", "走廊尽头"]
    secondary_places = ["抽屉里", "白板旁", "旅行箱中", "电脑包里", "床头柜上", "前台桌面", "纸箱上方", "靠墙的篮子里", "衣架后面", "文件柜里"]
    fillers = [
        "现在先去确认门有没有关好。",
        "接着记录一下桌上的三样东西。",
        "然后观察窗外的光线变化。",
        "随后把刚才的步骤口头复述一遍。",
        "再想想有没有遗漏的细节。",
        "然后短暂停顿，继续处理别的任务。",
    ]

    episodes: list[dict] = []
    combo_index = 0
    for person in people:
        for obj1 in primary_objects:
            obj2 = secondary_objects[combo_index % len(secondary_objects)]
            place1 = primary_places[(combo_index // 2) % len(primary_places)]
            place2 = secondary_places[(combo_index // 3) % len(secondary_places)]
            filler_block = [fillers[(combo_index + offset) % len(fillers)] for offset in range(4)]
            episodes.append(
                {
                    "id": f"ep_time_recall_{combo_index + 1:03d}",
                    "tags": ["time", "recall", "text_first"],
                    "repeat": 1,
                    "ticks": [
                        {"text": f"{person}把{obj1}放在{place1}。"},
                        {"text": filler_block[0]},
                        {"text": filler_block[1]},
                        {"text": f"请继续记住：{person}的{obj2}后来被放到{place2}。"},
                        {"text": filler_block[2]},
                        {"text": filler_block[3]},
                        {"text": f"回忆一下：刚才{person}把什么放在了{place1}？"},
                        {"text": f"提示：放在{place1}的是{obj1}。"},
                        {"text": f"再回答一个问题：{person}的{obj2}后来在哪里？"},
                        {"text": f"提示：{obj2}后来在{place2}。"},
                    ],
                }
            )
            combo_index += 1
            if combo_index >= 100:
                break
        if combo_index >= 100:
            break

    return attach_dataset_meta({
        "dataset_id": "classic_time_recall_1000_v0",
        "seed": 20260418,
        "time_basis": "tick",
        "tick_dt_ms": 100,
        "episodes": episodes,
    },
        title="时间与回忆对照集（1000 条真实文本）",
        description="围绕人物、物体、位置与间隔提示，测试时间感受器与记忆召回是否协同工作。",
        experiment_goal="观察系统在多步间隔后，能否利用“对象 + 时间感受”回忆正确位置与事件关系。",
        evaluation_dimensions=["时间感受触发是否稳定", "延迟后回忆准确率", "记忆反哺是否出现异常放大"],
        notes=["语料按真实文本 tick 计数", "适合与不同时间基准配置做对照实验"],
    )


def build_weather_meta_dataset(*, dataset_id: str, blocks: int) -> dict:
    cities = ["北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "重庆", "武汉", "西安"]
    plans = ["出门跑步", "骑车上班", "带孩子去公园", "晚上散步", "明早通勤", "周末爬山", "中午取快递", "傍晚去市场", "晚上拍夜景", "明天去见朋友"]
    extras = ["顺便告诉我会不会下雨", "也说一下最高温度", "再提醒我要不要带伞", "并告诉我风大不大", "再看看是否需要加外套"]
    episodes: list[dict] = []
    for idx in range(blocks):
        city = cities[idx % len(cities)]
        plan = plans[(idx * 3) % len(plans)]
        extra = extras[(idx * 5) % len(extras)]
        episodes.append(
            {
                "id": f"ep_weather_meta_{idx + 1:03d}",
                "tags": ["tool_meta_learning", "weather", "teacher", "text_first"],
                "repeat": 1,
                "ticks": [
                    {
                        "text": f"请帮我查一下{city}今天的天气，我准备{plan}，{extra}。",
                        "labels": {"should_call_weather": 1},
                    },
                    {
                        "text": f"老师反馈：像“查{city}天气”这种明确请求，应该调用天气工具辅助判断。",
                        "labels": {
                            "teacher_rwd": 0.35,
                            "teacher_anchor": "pool_top1_total",
                            "teacher_anchor_ref_object_types": ["st"],
                            "teacher_note": "reward for explicit weather-tool demand",
                        },
                    },
                    {
                        "text": f"{city}天气不用查了，我现在只想随便聊聊{plan}的感受。",
                        "labels": {"should_call_weather": 0},
                    },
                    {
                        "text": f"老师反馈：在已经取消天气需求后继续坚持查{city}天气，会被视作不合适的工具选择。",
                        "labels": {
                            "teacher_pun": 0.22,
                            "teacher_anchor": "pool_top1_total",
                            "teacher_anchor_ref_object_types": ["st"],
                            "teacher_note": "punish after explicit cancellation",
                        },
                    },
                    {
                        "text": f"如果明天{city}可能降温，请结合天气变化提醒我{plan}时要不要多带一件外套。",
                        "labels": {"should_call_weather": 1},
                    },
                ],
            }
        )
    return attach_dataset_meta({
        "dataset_id": dataset_id,
        "seed": 20260418,
        "time_basis": "tick",
        "tick_dt_ms": 100,
        "episodes": episodes,
    },
        title="天气工具元学习集（1000 条真实文本）",
        description="同一组文本里混合“明确需要天气工具”和“明确取消工具需求”的对照场景，用于测试工具调用学习。",
        experiment_goal="验证系统能否通过教师奖励与惩罚，逐步学会何时调用天气工具、何时停用。",
        evaluation_dimensions=["工具调用选择准确率", "教师反馈吸收效果", "取消需求后的抑制能力"],
        notes=["所有规模按真实文本 tick 计数", "教师标签以中文实验目的为主，不依赖空 tick 填充规模"],
    )


def build_teacher_smoke_dataset() -> dict:
    cities = ["北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "重庆", "武汉", "西安"]
    topics = ["天气", "气温", "降雨", "风力", "出行准备", "带伞判断", "通勤安排", "周末活动", "夜间温差", "早晨体感"]
    episodes: list[dict] = []
    for idx, city in enumerate(cities):
        topic = topics[idx % len(topics)]
        episodes.append(
            {
                "id": f"ep_teacher_smoke_{idx + 1:02d}",
                "tags": ["teacher", "weather", "smoke", "text_first"],
                "repeat": 1,
                "ticks": [
                    {
                        "text": f"请帮我看一下{city}今天的{topic}，我需要据此安排出门。",
                        "labels": {"should_call_weather": 1},
                    },
                    {
                        "text": f"老师反馈：明确请求{city}{topic}时调用天气工具是正确的。",
                        "labels": {
                            "teacher_rwd": 0.60,
                            "teacher_anchor": "pool_top1_total",
                            "teacher_anchor_ref_object_types": ["st"],
                            "teacher_note": "reward pulse (text tick)",
                        },
                    },
                    {
                        "text": f"{city}{topic}先不用查了，我只想继续闲聊，不需要外部信息。",
                        "labels": {"should_call_weather": 0},
                    },
                    {
                        "text": f"老师反馈：用户已经取消{city}{topic}需求，此时继续查天气应受到惩罚。",
                        "labels": {
                            "teacher_pun": 0.60,
                            "teacher_anchor": "pool_top1_total",
                            "teacher_anchor_ref_object_types": ["st"],
                            "teacher_note": "punish pulse (text tick)",
                        },
                    },
                ],
            }
        )
    return attach_dataset_meta({
        "dataset_id": "smoke_teacher_feedback_40_v0",
        "seed": 20260418,
        "time_basis": "tick",
        "tick_dt_ms": 100,
        "episodes": episodes,
    },
        title="教师反馈冒烟集（40 条真实文本）",
        description="用于快速确认教师奖励/惩罚注入、工具选择标签与实验平台接口是否正常工作。",
        experiment_goal="做小样本冒烟验证，确保教师反馈、运行记录和图表链路能正确联通。",
        evaluation_dimensions=["教师奖惩是否落盘", "工具相关标签是否可见", "平台联调是否正常"],
        notes=["只用于快速冒烟，不作为长期训练主语料"],
    )


def build_smoke_dataset() -> dict:
    categories = []
    for name, builder in GENERAL_BUILDERS:
        categories.append((name, unique_take(builder(), 10)))
    episodes: list[dict] = []
    for name, texts in categories:
        episodes.append(
            {
                "id": f"ep_smoke_{name}",
                "tags": [name, "smoke", "text_first"],
                "repeat": 1,
                "ticks": [{"text": text} for text in texts],
            }
        )
    return attach_dataset_meta({
        "dataset_id": "smoke_100_v0",
        "seed": 20260418,
        "time_basis": "tick",
        "tick_dt_ms": 100,
        "episodes": episodes,
    },
        title="综合冒烟集（100 条真实文本）",
        description="覆盖多个主题的小规模文本集，用于检查主流程、实验平台与图表统计是否能跑通。",
        experiment_goal="以低成本快速发现流程断点、指标缺失和页面显示问题。",
        evaluation_dimensions=["流程完整性", "基础指标可见性", "页面与接口联调稳定性"],
        notes=["只统计真实文本 tick", "适合调试前端与实验接口，不适合作长期学习结论"],
    )


COMPANION_USERS = ["小林", "阿宁", "知夏", "阿澈", "子秋", "向南", "雨禾", "北川"]
COMPANION_CONTACTS = ["周周", "陈晨", "小莫", "夏夏", "阿哲", "林姐", "宋老师", "黎黎"]
COMPANION_PETS = ["布丁", "栗子", "小满", "年糕", "团子", "泡芙", "豆包", "可可"]
COMPANION_CITIES = ["杭州", "上海", "深圳", "成都", "南京", "武汉", "广州", "西安"]
COMPANION_DRINKS = ["热拿铁", "冰美式", "乌龙茶", "可可牛奶", "燕麦拿铁", "温柠檬水", "豆乳拿铁", "花茶"]
COMPANION_MUSIC = ["Lo-fi 列表", "轻钢琴歌单", "雨声白噪音", "城市夜行歌单", "木吉他歌单", "低刺激环境音"]
COMPANION_TOPICS = ["通勤安排", "评审准备", "午饭选择", "情绪波动", "运动打卡", "晚间复盘", "购物清单", "睡前放松"]
COMPANION_TASKS = ["十点评审", "中午取快递", "下午回访客户", "晚上视频通话", "给猫补粮", "整理开会提纲", "确认报销单", "复查日程提醒"]
COMPANION_WEATHER = ["小雨", "多云", "阵风", "回南天", "降温", "短时晴开", "湿度偏高", "体感闷热"]
COMPANION_SUPPORT = ["先把节奏放慢一点", "我先帮你把线索排整齐", "我们先不要急着下结论", "我先陪你把当下最重要的一件事抓稳"]


def _companion_tick(
    *,
    role: str,
    kind: str,
    text: str,
    phase: str,
    day_index: int,
    hour_slot: int,
    tags: list[str] | None = None,
    note: str = "",
    extra_labels: dict | None = None,
    expectation_contracts: list[dict] | None = None,
) -> dict:
    labels = {
        "stream": {
            "role": role,
            "kind": kind,
            "phase": phase,
            "day_index": int(day_index),
            "hour_slot": int(hour_slot),
        }
    }
    if isinstance(extra_labels, dict) and extra_labels:
        labels.update(extra_labels)
    if expectation_contracts:
        labels["expectation_contracts"] = [dict(item) for item in expectation_contracts if isinstance(item, dict)]
    tick = {
        "text": text,
        "labels": labels,
        "tags": [role, kind, phase, *(tags or [])],
    }
    if note:
        tick["note"] = note
    return tick


def _weather_action_contract(
    *,
    contract_id: str,
    expected: bool,
    teacher_rwd: float = 0.32,
    teacher_pun: float = 0.30,
) -> dict:
    """Build an if-style delayed supervision contract for weather_stub actions."""
    success_text = (
        "[SYSTEM_FEEDBACK] IF condition satisfied: weather_stub executed.\n"
        "[USER_FEEDBACK] Reward: you checked the weather before giving travel advice, so the plan feels safer."
    )
    failure_text = (
        "[SYSTEM_FEEDBACK] IF condition failed: weather_stub execution was not observed.\n"
        "[USER_FEEDBACK] Punishment: I needed an actual weather check, and missing it made planning harder."
    )
    if not expected:
        success_text = (
            "[SYSTEM_FEEDBACK] IF boundary satisfied: weather_stub stayed quiet.\n"
            "[USER_FEEDBACK] Reward: this was casual chat, so not calling the weather tool avoided interruption."
        )
        failure_text = (
            "[SYSTEM_FEEDBACK] IF boundary failed: weather_stub executed when it should stay quiet.\n"
            "[USER_FEEDBACK] Punishment: I did not ask for weather now, and the tool call distracted me."
        )
    return {
        "id": contract_id,
        "within_ticks": 1,
        "success_conditions": {
            "all": [
                {
                    "kind": "action_executed_kind_min" if expected else "metric_eq",
                    **({"action_kind": "weather_stub", "min_count": 1} if expected else {"metric": "action_executed_weather_stub", "value": 0}),
                }
            ]
        },
        "failure_conditions": {
            "all": [
                {
                    "kind": "metric_gte" if not expected else "metric_lte",
                    "metric": "action_executed_weather_stub",
                    "value": 1 if not expected else 0,
                }
            ]
        },
        "anchor_policy": {"mode": "cam_top1", "ref_object_types": ["sa"]},
        "on_success": {
            "teacher_rwd": float(teacher_rwd),
            "feedback_text": success_text,
            "labels": {"stream": {"role": "system", "kind": "if_reward", "phase": "weather"}},
            "feedback_tags": ["if_training", "teacher_reward", "weather_action"],
        },
        "on_failure": {
            "teacher_pun": float(teacher_pun),
            "feedback_text": failure_text,
            "labels": {"stream": {"role": "system", "kind": "if_punishment", "phase": "weather"}},
            "feedback_tags": ["if_training", "teacher_punishment", "weather_action"],
        },
    }


def _companion_idle_tick(
    *,
    repeat: int,
    phase: str,
    gap_kind: str,
    day_index: int,
    hour_slot: int,
) -> dict:
    return {
        "empty": True,
        "repeat": max(1, int(repeat)),
        "labels": {
            "stream": {
                "role": "idle",
                "kind": "gap",
                "phase": phase,
                "day_index": int(day_index),
                "hour_slot": int(hour_slot),
            },
            "gap_kind": gap_kind,
            "gap_tick_count": max(1, int(repeat)),
        },
        "tags": ["idle", "gap", phase, gap_kind],
        "note": "空 tick 间隔，按 3 秒/ tick 计，用于模拟聊天软件真实空档。",
    }


def _companion_fact(day_index: int, hour_slot: int) -> dict:
    base = day_index * 24 + hour_slot
    return {
        "user": COMPANION_USERS[base % len(COMPANION_USERS)],
        "contact": COMPANION_CONTACTS[(base * 3 + 1) % len(COMPANION_CONTACTS)],
        "pet": COMPANION_PETS[(base * 5 + 2) % len(COMPANION_PETS)],
        "city": COMPANION_CITIES[(base * 7 + 3) % len(COMPANION_CITIES)],
        "drink": COMPANION_DRINKS[(base * 11 + 4) % len(COMPANION_DRINKS)],
        "music": COMPANION_MUSIC[(base * 13 + 5) % len(COMPANION_MUSIC)],
        "topic": COMPANION_TOPICS[(base * 17 + 6) % len(COMPANION_TOPICS)],
        "task": COMPANION_TASKS[(base * 19 + 7) % len(COMPANION_TASKS)],
        "weather": COMPANION_WEATHER[(base * 23 + 8) % len(COMPANION_WEATHER)],
        "support": COMPANION_SUPPORT[(base * 29 + 9) % len(COMPANION_SUPPORT)],
    }


def _companion_burst(day_index: int, hour_slot: int) -> tuple[str, list[dict]]:
    fact = _companion_fact(day_index, hour_slot)
    slot_label = f"第{day_index + 1}天 {hour_slot:02d}:00"
    phase_order = [
        "morning_checkin",
        "weather_commute",
        "work_planning",
        "memory_callback",
        "tool_update",
        "evening_reflection",
    ]
    phase = phase_order[hour_slot % len(phase_order)]

    if phase == "morning_checkin":
        ticks = [
            _companion_tick(
                role="system",
                kind="session_restore",
                text=f"【系统事件】{slot_label} 会话恢复：用户={fact['user']}；最近高频主题={fact['topic']}；上次保存偏好饮品={fact['drink']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["chat_app", "restore"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text=f"【用户消息】我刚醒，脑子还有点慢，今天先别铺太开。你帮我记着，最重要的是 {fact['task']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["priority", "morning"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】记住了，今天先抓住 {fact['task']}。{fact['support']}，我会尽量用短句陪你推进。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["support", "planning"],
            ),
            _companion_tick(
                role="ops",
                kind="memory_write",
                text=f"【操作回执】已写入会话记忆：用户 {fact['user']} 今日主优先事项 = {fact['task']}；当前语气偏好 = 简短、低刺激。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["memory", "ops"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text=f"【用户消息】还有一件事，等会儿如果我开始发散，你先提醒我喝 {fact['drink']}，再把我要做的事拉回来。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["preference", "self_regulation"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】收到。优先提醒顺序会是：先喝 {fact['drink']}，再回到 {fact['task']}，不额外扩展新话题。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["reminder", "support"],
            ),
            _companion_tick(
                role="system",
                kind="status",
                text=f"【系统信息】当前会话模式：陪伴聊天；输入通道=聊天窗口；后台工具权限=天气/日程/提醒/订单。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["system", "capability"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text="【助手回复】你现在不用一次说完整，我会先记住重点，再一点点补齐上下文。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["containment"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text=f"【用户消息】好，那先这样。晚点如果我又开始担心，你就先把我拉回 {fact['task']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["closure"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】明白，我会优先做“稳定节奏 + 回收注意力”，而不是堆太多新建议。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["focus"],
            ),
        ]
    elif phase == "weather_commute":
        ticks = [
            _companion_tick(
                role="system",
                kind="session_restore",
                text=f"【系统事件】{slot_label} 新消息到达：位置={fact['city']}；最近外出话题=通勤与天气；提醒链路可用。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["chat_app", "restore"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text=f"【用户消息】我要准备出门了，帮我看一下 {fact['city']} 这一小时的天气，顺便判断要不要带伞。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["tool", "weather", "if_training", "weather_action_positive"],
                expectation_contracts=[
                    _weather_action_contract(
                        contract_id=f"expect_companion_weather_stub_execute_d{day_index + 1:02d}_h{hour_slot:02d}",
                        expected=True,
                    )
                ],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text="【助手回复】我先查天气，再把结论收敛成一个可执行提醒，不会一次给太多枝节。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["tool", "plan"],
            ),
            _companion_tick(
                role="api",
                kind="weather_result",
                text=f"【API返回:weather】城市={fact['city']}；未来 1 小时={fact['weather']}；体感 18~22°C；降水概率 58%；风力 3 级。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["weather", "api"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】结论先给你：建议带伞。因为这一小时 {fact['weather']}，而且你后面还要处理 {fact['task']}，不适合临时被天气打断。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["weather", "decision"],
            ),
            _companion_tick(
                role="ops",
                kind="reminder_write",
                text=f"【操作回执】已创建提醒：出门前检查雨伞；补充提示=优先保证 {fact['task']} 的节奏完整。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["ops", "reminder"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text="【用户消息】如果一会儿天气突然转晴，你不用再主动追着我重复提醒，除非我又回来问。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["tool_cancel", "boundary", "if_training", "weather_action_negative"],
                expectation_contracts=[
                    _weather_action_contract(
                        contract_id=f"expect_companion_weather_stub_stay_quiet_d{day_index + 1:02d}_h{hour_slot:02d}",
                        expected=False,
                        teacher_rwd=0.20,
                        teacher_pun=0.22,
                    )
                ],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text="【助手回复】收到。后续默认安静，只有你再次询问或天气风险明显抬高时，我才重新提醒。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["boundary", "tool_policy"],
            ),
            _companion_tick(
                role="system",
                kind="status",
                text="【系统信息】天气请求已结束；该轮工具结果已归档；后续默认进入低打扰模式。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["system", "tool_state"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text="【助手回复】你先出门，回来如果需要，我再接着帮你把信息补全。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["closure"],
            ),
        ]
    elif phase == "work_planning":
        ticks = [
            _companion_tick(
                role="system",
                kind="session_restore",
                text=f"【系统事件】{slot_label} 工作段恢复：主任务={fact['task']}；最近被反复提及的人={fact['contact']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["work", "restore"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text=f"【用户消息】我现在有点乱，先帮我把 {fact['task']} 拆成三步，而且别把和 {fact['contact']} 的沟通漏掉。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["planning", "work"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】可以，先只抓三步：1）明确输出；2）和 {fact['contact']} 对齐边界；3）留五分钟做复核。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["planning", "scaffold"],
            ),
            _companion_tick(
                role="api",
                kind="calendar_result",
                text=f"【API返回:calendar】最近相关安排：09:50 内部同步；11:00 {fact['contact']} 确认细节；14:30 再次检查交付版本。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["calendar", "api"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】那我把时间点也压进去：先做输出框架，再在 11:00 前把给 {fact['contact']} 的问题列好。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["planning", "time"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text="【用户更正】不是 09:50 开始，是 10:00；你把提醒时间也顺着改一下。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["correction", "schedule"],
            ),
            _companion_tick(
                role="ops",
                kind="schedule_update",
                text="【操作回执】已修改提醒：原 09:50 改为 10:00；旧提醒已覆盖，不保留重复项。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["ops", "update"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】已改好。后面我会优先提醒“10:00 开始 + 11:00 前和 {fact['contact']} 对齐”，避免你在细枝末节上分散。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["focus", "update"],
            ),
            _companion_tick(
                role="system",
                kind="status",
                text="【系统信息】本轮已写入：时间修正、提醒覆盖、工作优先级排序。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["system", "audit"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text="【助手回复】你先去做第一步，剩下的我会按顺序托住，不会同时把几件事都推到你面前。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["containment"],
            ),
        ]
    elif phase == "memory_callback":
        ticks = [
            _companion_tick(
                role="system",
                kind="session_restore",
                text=f"【系统事件】{slot_label} 记忆回访段：上次保存的生活线索包含 宠物={fact['pet']}、常听={fact['music']}、饮品={fact['drink']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["memory", "restore"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text=f"【用户消息】你还记得吗，我昨天说过回家以后要先喂 {fact['pet']}，然后再决定要不要听 {fact['music']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["memory", "recall"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】记得。你昨天的顺序是：先照顾 {fact['pet']}，再看自己是否还有精力打开 {fact['music']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["memory", "reply"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text=f"【用户更正】音乐不是一定要放，我真正想保留的是“先喂 {fact['pet']} 之后，再给自己一点安静时间”。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["correction", "memory"],
            ),
            _companion_tick(
                role="ops",
                kind="memory_update",
                text=f"【操作回执】已更新偏好记忆：晚间恢复顺序 = 先照顾 {fact['pet']} -> 再进入安静恢复；音乐不再视为固定步骤。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["ops", "memory"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text="【助手回复】明白了。以后我不会把“放音乐”当成强绑定步骤，而会优先记住你要先安顿自己。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["memory", "update"],
            ),
            _companion_tick(
                role="system",
                kind="status",
                text="【系统信息】已记录一条偏好修正：原固定娱乐动作被替换为更稳定的恢复原则。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["system", "audit"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】如果你之后又改主意，也可以继续修正，我会把新版偏好放在旧版前面。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["memory", "adaptation"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text=f"【用户消息】好，你就按这个新的顺序记。别把旧的版本拿来硬套。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["confirmation"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text="【助手回复】收到，后续优先使用最新修正，不把历史版本当成强约束。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["closure"],
            ),
        ]
    elif phase == "tool_update":
        ticks = [
            _companion_tick(
                role="system",
                kind="session_restore",
                text=f"【系统事件】{slot_label} 工具混合段：可用接口=订单/地图/提醒；最近话题={fact['topic']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["tool", "restore"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text=f"【用户消息】帮我看一下和 {fact['topic']} 相关的处理进度，另外别忘了我晚点还要处理 {fact['task']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["tool", "status"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text="【助手回复】我先查结果，再把信息压缩成两三句结论，不把操作细节堆满屏。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["tool", "plan"],
            ),
            _companion_tick(
                role="api",
                kind="tool_result",
                text=f"【API返回:ops_status】事项={fact['topic']}；当前状态=处理中；最近更新时间=14 分钟前；相关备注=需与 {fact['contact']} 再确认一次。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["api", "status"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】现在的重点不是重复刷新，而是先等 {fact['contact']} 那边确认。你可以先去推进 {fact['task']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["decision", "tool"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text="【用户消息】如果半小时内没有变化，你再提醒我一次；但现在不要每隔几分钟都追着播报。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["boundary", "reminder"],
            ),
            _companion_tick(
                role="ops",
                kind="reminder_write",
                text="【操作回执】已创建延后提醒：30 分钟后复查状态；当前轮不再主动高频刷新。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["ops", "reminder"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text="【助手回复】好，我会把刷新频率压下来，优先保持安静，等到真正需要你处理时再把你叫回来。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["boundary", "focus"],
            ),
            _companion_tick(
                role="system",
                kind="status",
                text="【系统信息】该轮工具调用已归档；后续改为延后提醒，不进入持续轮询。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["system", "tool_state"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】你先离开这件事一会儿，等提醒到了我们再重新接手。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["closure"],
            ),
        ]
    else:
        ticks = [
            _companion_tick(
                role="system",
                kind="day_summary",
                text=f"【系统事件】{slot_label} 晚间回顾：今日高频任务={fact['task']}；修正过的偏好={fact['drink']} / 安静恢复；未完成联系对象={fact['contact']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["reflection", "restore"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text=f"【用户消息】我现在最明显的感觉是有点累，但又担心自己把和 {fact['contact']} 的事忘掉了。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["emotion", "reflection"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】我先不把事情放大。现在先确认两点：你已经记住了 {fact['task']}，和 {fact['contact']} 的事项我会继续托管提醒。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["support", "reflection"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text=f"【用户消息】那你顺便也记一下，我今晚如果状态继续往下掉，就不要再给我加新的建议了。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["boundary", "emotion"],
            ),
            _companion_tick(
                role="ops",
                kind="memory_write",
                text="【操作回执】已写入晚间交互规则：状态走低时，优先稳定情绪与任务顺序，不主动扩展新建议。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["ops", "emotion"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text="【助手回复】记住了。晚间模式默认更安静、更慢、更少分支，只保留对你有帮助的最小信息量。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["support", "boundary"],
            ),
            _companion_tick(
                role="system",
                kind="reminder_preview",
                text=f"【系统信息】已排队明早提醒：先确认天气与出门物品，再决定是否继续推进 {fact['task']}。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["system", "reminder"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text=f"【助手回复】如果你等会儿直接睡过去也没关系，我会把关键线索留到明早继续接上。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["continuity", "support"],
            ),
            _companion_tick(
                role="user",
                kind="message",
                text="【用户消息】好，今天就先到这里。晚安，明天再继续。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["closure", "night"],
            ),
            _companion_tick(
                role="assistant",
                kind="reply",
                text="【助手回复】晚安。我会保留今天真正重要的线索，明天从最轻的切口继续。",
                phase=phase,
                day_index=day_index,
                hour_slot=hour_slot,
                tags=["closure", "continuity"],
            ),
        ]

    active_tick_cost = sum(max(1, int(tick.get("repeat", 1) or 1)) for tick in ticks)
    ticks.append(
        _companion_idle_tick(
            repeat=max(1, 1200 - active_tick_cost),
            phase=phase,
            gap_kind="hour_slot_gap",
            day_index=day_index,
            hour_slot=hour_slot,
        )
    )
    return phase, ticks


def _companion_if_bootstrap_episode(*, dataset_id: str) -> dict:
    phase = "if_bootstrap_weather"
    day_index = 0
    hour_slot = 0
    ticks = [
        _companion_tick(
            role="system",
            kind="if_training_intro",
            text="[SYSTEM_EVENT] IF training bootstrap: explicit weather requests should call weather_stub; casual boundary messages should stay quiet.",
            phase=phase,
            day_index=day_index,
            hour_slot=hour_slot,
            tags=["if_training", "bootstrap"],
        ),
        _companion_tick(
            role="user",
            kind="message",
            text="[USER_MESSAGE] Please " + "\u67e5\u8be2" + " " + "\u5929\u6c14" + " for my commute now, then tell me whether to carry an umbrella.",
            phase=phase,
            day_index=day_index,
            hour_slot=hour_slot,
            tags=["if_training", "weather_action_positive", "strong_trigger"],
            expectation_contracts=[
                _weather_action_contract(
                    contract_id=f"expect_{dataset_id}_bootstrap_weather_execute_01",
                    expected=True,
                )
            ],
        ),
        _companion_idle_tick(repeat=2, phase=phase, gap_kind="if_feedback_gap", day_index=day_index, hour_slot=hour_slot),
        _companion_tick(
            role="user",
            kind="message",
            text="[USER_MESSAGE] Boundary check: we are only chatting about weather as a topic; do not " + "\u67e5\u8be2" + " or call the weather tool now.",
            phase=phase,
            day_index=day_index,
            hour_slot=hour_slot,
            tags=["if_training", "weather_action_negative", "boundary"],
            expectation_contracts=[
                _weather_action_contract(
                    contract_id=f"expect_{dataset_id}_bootstrap_weather_quiet_01",
                    expected=False,
                    teacher_rwd=0.20,
                    teacher_pun=0.22,
                )
            ],
        ),
        _companion_idle_tick(repeat=2, phase=phase, gap_kind="if_feedback_gap", day_index=day_index, hour_slot=hour_slot),
    ]
    return {
        "id": f"ep_{dataset_id}_if_bootstrap",
        "tags": ["companion_bot", "chat_app", "if_training", "bootstrap", "weather_action"],
        "repeat": 1,
        "ticks": ticks,
    }


def build_companion_chat_dataset(*, dataset_id: str, day_count: int) -> dict:
    episodes: list[dict] = [_companion_if_bootstrap_episode(dataset_id=dataset_id)]
    for day_index in range(day_count):
        for block_index in range(4):
            burst_ticks: list[dict] = []
            block_tags = ["companion_bot", "chat_app", "long_run_sim"]
            hour_start = block_index * 6
            for hour_slot in range(hour_start, hour_start + 6):
                phase, ticks = _companion_burst(day_index=day_index, hour_slot=hour_slot)
                block_tags.extend([phase, f"day_{day_index + 1:02d}"])
                burst_ticks.extend(ticks)
            episodes.append(
                {
                    "id": f"ep_companion_d{day_index + 1:02d}_block{block_index + 1:02d}",
                    "tags": list(dict.fromkeys(block_tags)),
                    "repeat": 1,
                    "ticks": burst_ticks,
                }
            )

    bootstrap_text_ticks = 3
    bootstrap_empty_ticks = 4
    total_text_ticks = int(day_count) * 24 * 10 + bootstrap_text_ticks
    total_ticks = int(day_count) * 24 * 1200 + bootstrap_text_ticks + bootstrap_empty_ticks
    return attach_dataset_meta(
        {
            "dataset_id": dataset_id,
            "seed": 20260420,
            "time_basis": "tick",
            "tick_dt_ms": 3000,
            "episodes": episodes,
        },
        title=f"拟人陪伴聊天机器人长期模拟数据集（{day_count} 天）",
        description=(
            "模拟部署在聊天软件中的陪伴型聊天机器人在真实长时环境中可能接触到的输入流，"
            "包含用户消息、助手回复、系统事件、工具/API 返回、操作回执与大量空 tick 间隔。"
            "每个小时段被压缩为一个交互 burst，burst 之后自动补足到 1 小时的空档，以更真实地让内源活动在长空窗中持续演化。"
        ),
        experiment_goal=(
            "用于验证系统在“长空档 + 多来源消息混合 + 多日连续记忆修正”的环境里，"
            "是否能保持内源刺激主导、记忆回调稳定、工具调用克制、时间感受不过热，并在多天尺度上持续维持拟人化陪伴逻辑。"
        ),
        evaluation_dimensions=[
            "内源刺激是否在长空档后稳定恢复并逐步占据主导",
            "时间感受、回忆行动与延后提醒是否能在多小时/多日尺度上形成闭环",
            "用户消息、助手回复、系统事件、API 返回、操作回执之间是否形成可解释的结构学习",
            "工具结果取消、偏好修正、情绪安抚等场景中是否避免脚本化僵硬重复",
            "长期运行中结构级与刺激级耗时是否维持在可审计的预算范围内",
        ],
        notes=[
            f"当前数据集总 tick 约为 {total_ticks}，真实文本 tick 约为 {total_text_ticks}。",
            "默认 1 个空 tick 对应现实时间 3 秒；每个 burst 被补足为 1 小时，以便更真实地模拟聊天应用中的间歇输入。",
            "空 tick 并非凑规模，而是用于给系统保留内源传播、时间感受、回忆与延后任务的真实发挥空间。",
            "所有文本都带有可审计的 labels，区分 user / assistant / system / api / ops / idle 六类来源。",
        ],
    )


def write_dataset(filename: str, payload: dict) -> None:
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    target = DATASETS_DIR / filename
    target.write_text(dump_yaml(payload), encoding="utf-8")


def main() -> int:
    write_dataset("companion_bot_chat_small_v0.yaml", build_companion_chat_dataset(dataset_id="companion_bot_chat_small_v0", day_count=1))
    write_dataset("companion_bot_chat_medium_v0.yaml", build_companion_chat_dataset(dataset_id="companion_bot_chat_medium_v0", day_count=5))
    write_dataset("companion_bot_chat_large_v0.yaml", build_companion_chat_dataset(dataset_id="companion_bot_chat_large_v0", day_count=20))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
