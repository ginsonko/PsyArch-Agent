# -*- coding: utf-8 -*-
"""
AP 状态池模块 — ID 生成器
==========================
与 text_sensor 的 ID 生成器独立，使用不同前缀，避免 ID 冲突。
前缀约定:
  spi_   → state_pool_item（状态池项）
  sce_   → state_change_event（状态变化事件）
  scp_   → script_check_packet（脚本检查抄送包）
  sps_   → state_pool_snapshot（状态池快照）
"""

import threading
import time


class IDGenerator:
    """
    线程安全的 ID 生成器。
    生成格式: {prefix}_{YYYYMMDDHHMMSS}_{6位递增号}
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}

    def next_id(self, prefix: str) -> str:
        """生成下一个唯一 ID。"""
        with self._lock:
            count = self._counters.get(prefix, 0) + 1
            self._counters[prefix] = count
        ts = time.strftime("%Y%m%d%H%M%S")
        return f"{prefix}_{ts}_{count:06d}"

    def reset(self):
        """重置所有计数器（仅用于测试）。"""
        with self._lock:
            self._counters.clear()


# 模块级单例
_global_id_gen = IDGenerator()


def next_id(prefix: str) -> str:
    """模块级快捷入口。"""
    return _global_id_gen.next_id(prefix)


def reset_id_generator():
    """重置全局 ID 生成器（仅用于测试）。"""
    _global_id_gen.reset()
