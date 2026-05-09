# -*- coding: utf-8 -*-
"""
Artificial PsyArch — 注意力模块（Attention Filter, AF）
======================================================
本模块负责在预算约束下，对状态池（SP）中的运行态对象进行筛选/调制，
形成 CAM（当前注意记忆体），作为结构级查存一体的入口，同时为后续内源刺激化
提供可被消耗/划拨的预算能量。

原型阶段实现策略：
  - 先落地“可运行、可观测、可验证”的 CAM 生成闭环（MVP）
  - 逐步补齐：聚焦行动器接口、IESM/CFS/EMgr 调制接口、疲劳/近因等更复杂策略
"""

__version__ = "0.1.0"
__schema_version__ = "1.1"
__module_name__ = "attention"

from .main import AttentionFilter  # noqa: F401

