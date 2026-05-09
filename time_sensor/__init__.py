# -*- coding: utf-8 -*-
"""
Artificial PsyArch — 时间感受器模块（Time Sensor）
=================================================

对齐理论核心 4.2.6~4.2.8 的原型落地目标（MVP）：
  1) 时间差（time delta）：当前时刻 - 记忆/结构的时间戳
  2) 时间桶（time buckets）：用有限数量的区间覆盖连续时间尺度（避免无限碎裂）
  3) 双表赋能（dual-bucket energization）：把一个具体时间差的能量分配到最接近的两个时间桶
  4) 为“回忆行动（recall）”提供可脚本化的触发基础：
     当“时间感受节点（时间桶节点）”在状态池中获得足够能量并超过阈值时，
     由 IESM（先天编码脚本管理器）规则触发行动模块执行 recall。

重要约束（对齐你当前的产品偏好）：
  - 中文优先；出现英文缩写时必须附中文全称
  - 状态池中不要出现大量无意义的 SA/CSA 噪音：
    时间感受节点数量必须是“有限桶数”，且 ID 稳定可合并。
"""

__version__ = "0.1.0"
__schema_version__ = "1.0"
__module_name__ = "time_sensor"

from .main import TimeSensor, TIME_SENSOR_DEFAULT_CONFIG  # noqa: F401

