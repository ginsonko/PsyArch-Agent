# -*- coding: utf-8 -*-
"""
Artificial PsyArch — 情绪递质模块（EMgr/NT）
=========================================
情绪管理器（EMgr, Emotion Manager）维护递质通道（NT, NeuroTransmitter channels）慢变量，
并输出调制量影响注意力、学习与行动风格。

原型阶段目标（可运行优先）：
  - 维护 nt_state 通道字典（衰减/上下限）
  - 从认知感受信号（CFS, Cognitive Feeling Signals）等输入更新通道
  - 输出 modulation（至少对注意力过滤器 AF 生效，其他先展示）
"""

__version__ = "0.1.0"
__schema_version__ = "1.1"
__module_name__ = "emotion"

from .main import EmotionManager  # noqa: F401
