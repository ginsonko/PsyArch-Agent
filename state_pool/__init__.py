# -*- coding: utf-8 -*-
"""
Artificial PsyArch — 状态池模块（State Pool Module, SPM）
=========================================================
AP 运行态认知层核心中枢：维护当前活跃认知图景，
接收外源/内源刺激，管理对象级能量与认知压动态。

模块职责边界：
  ✓ 接收刺激包并映射为运行态 state_item
  ✓ 维护 er/ev/认知压及其变化率
  ✓ 执行衰减、中和、淘汰、合并
  ✓ 属性绑定、脚本检查抄送、快照输出
  ✗ 不负责感受器残响、长期存储、脚本规则判断、情绪更新、行动决策
"""

__version__ = "1.0.0"
__schema_version__ = "1.1"
__module_name__ = "state_pool"

from .main import StatePool  # noqa: F401
