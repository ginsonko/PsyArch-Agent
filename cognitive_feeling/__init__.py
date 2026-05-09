# -*- coding: utf-8 -*-
"""
Artificial PsyArch — 认知感受模块（CFS）
=====================================
认知感受信号（CFS, Cognitive Feeling Signals）负责在“感应赋能后的稳定图景”上生成元认知信号，
并把关键认知感受写入状态池（StatePool, SP），使系统能在下一 tick（时间步）里“认知自己的状态”。

原型阶段目标（可运行优先）：
  - 生成结构化 cfs_signals（违和/正确事件/惊/期待/压力/繁简/重复感/把握感等）
  - 写入状态池（StatePool, SP）：以 cfs_signal 运行态对象呈现，并可选绑定属性 SA（刺激元）
  - 输出可审计的触发原因、强度与绑定目标，供观测台展示与脚本调参
"""

__version__ = "0.1.0"
__schema_version__ = "1.1"
__module_name__ = "cognitive_feeling"

from .main import CognitiveFeelingSystem  # noqa: F401
