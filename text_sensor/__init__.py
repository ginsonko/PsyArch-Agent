# -*- coding: utf-8 -*-
"""
Artificial PsyArch — 文本感受器（Text Sensor, TS）模块
=====================================================
AP 接口层第一入口：将原始文本转化为 SA / CSA 并输出统一刺激包。

模块职责边界：
  ✓ 文本接收、归一化、切分、SA/CSA 生成、初始刺激赋能
  ✓ 感受器残响管理
  ✓ 输出 stimulus_packet
  ✗ 不负责状态池维护、结构生成、行动选择、情绪调制
"""

__version__ = "1.0.0"
__schema_version__ = "1.1"
__module_name__ = "text_sensor"

from .main import TextSensor  # noqa: F401
