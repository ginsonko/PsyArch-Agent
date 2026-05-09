# -*- coding: utf-8 -*-
"""
Artificial PsyArch — 行动管理模块（Action/Drive）
===============================================
本模块对齐理论核心中的 Step 9：
  - 维护行动节点（Action Node，行动意图）
  - 计算 Drive（驱动力）并衰减
  - 当 Drive 超过阈值时尝试触发行动（消耗而非清零）

术语与缩写 / Glossary
--------------------
  - 行动管理器（Action Manager）
  - 行动节点（Action Node, AN）
  - 驱动力（Drive）
  - 状态池（StatePool, SP）
  - 认知感受信号（CFS, Cognitive Feeling Signals）
  - 情绪递质管理器（EMgr/NT）
  - 先天编码脚本管理器（IESM）
"""

__version__ = "0.1.0"
__schema_version__ = "1.1"
__module_name__ = "action"

from .main import ActionManager  # noqa: F401

