# -*- coding: utf-8 -*-
"""
AP 文本感受器 — ID 生成器
========================
原型阶段使用「前缀_时间戳_递增号」格式，保证同一进程内唯一。
后续可升级为 UUID / 雪花 ID 而不影响接口。
"""

import threading
import time


class IDGenerator:
    """
    线程安全的 ID 生成器。
    生成格式示例: sa_txt_20260318142133_000001
    """

    def __init__(self):
        self._lock = threading.Lock()
        # 每个前缀维护独立计数器，避免跨类型 ID 序号跳跃
        self._counters: dict[str, int] = {}

    def next_id(self, prefix: str) -> str:
        """
        生成下一个唯一 ID。

        参数:
            prefix: ID 前缀，如 "sa_txt", "csa_txt", "sf_text", "echo_text", "spkt"

        返回:
            格式为 "{prefix}_{YYYYMMDDHHMMSS}_{6位递增号}" 的字符串
        """
        with self._lock:
            count = self._counters.get(prefix, 0) + 1
            self._counters[prefix] = count

        # 使用当前时间戳（秒级精度即可，递增号保证唯一性）
        ts = time.strftime("%Y%m%d%H%M%S")
        return f"{prefix}_{ts}_{count:06d}"

    def reset(self):
        """重置所有计数器（仅用于测试）。"""
        with self._lock:
            self._counters.clear()


# 模块级单例，供所有子模块共享
_global_id_gen = IDGenerator()


def next_id(prefix: str) -> str:
    """模块级快捷入口。"""
    return _global_id_gen.next_id(prefix)


def reset_id_generator():
    """重置全局 ID 生成器（仅用于测试）。"""
    _global_id_gen.reset()
