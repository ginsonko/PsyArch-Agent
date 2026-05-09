# -*- coding: utf-8 -*-
"""
Artificial PsyArch — 实虚能量平衡控制器（Energy Balance Controller, EBC）
===================================================================

本模块的目标是把“预测（EV 虚能量）”与“现实（ER 实能量）”的全局比例拉回到一个目标值，
默认目标为 1:1（EV_total ≈ ER_total），从而让“预测趋近现实”的闭环更稳定、更可控。

它是一个可插拔模块：
  - 可在配置中随时启用/禁用
  - 不改变核心检索/学习逻辑，只输出“调制系数（modulation scales）”
  - 由 Observatory 在下一 tick 应用到 HDB（全息深度数据库）的传播/诱发系数等参数上

术语与缩写 / Glossary
--------------------
  - ER（实能量, Energy-Reality）
  - EV（虚能量, Energy-Virtual）
  - 目标比例（target_ratio）：希望 EV_total / ER_total 收敛到的值（默认 1.0）
  - 控制增益（g）：输出的全局缩放因子（>0）
  - 积分控制（integral control）：使用误差累积逐步修正，降低对输入频次变化的敏感性
"""

__version__ = "0.1.0"
__schema_version__ = "1.0"
__module_name__ = "energy_balance"

from .main import EnergyBalanceController  # noqa: F401

