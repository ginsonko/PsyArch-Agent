# -*- coding: utf-8 -*-
"""
Artificial PsyArch — 先天编码脚本管理模块（IESM）
================================================
先天编码脚本管理器（IESM, Innate Encoded Script Manager）是 AP 的“人工 DNA”：
集中管理认知感受（CFS）/情绪递质（EMgr/NT）/先天触发等关键规则，使其具备版本化、可回滚与可审计能力。

原型阶段目标（可运行优先）：
  - 可加载/热加载脚本配置
  - 提供状态窗口检查接口（state_window，对接状态池 StatePool 的 script_check_packet）
  - 输出可被其他模块消费的指令（directives，例如注意力聚焦指令）
"""

__version__ = "0.1.0"
__schema_version__ = "1.1"
__module_name__ = "innate_script"

from .main import InnateScriptManager  # noqa: F401
