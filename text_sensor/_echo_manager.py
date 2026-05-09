# -*- coding: utf-8 -*-
"""
AP 文本感受器 — 感受器残响池管理器
==================================
负责管理感受器层的输入拖尾（残响），与状态池的状态延续完全独立。

核心机制：
  - 每轮调用时，先对池中所有残响帧执行 SA 级能量衰减
  - 衰减支持两种模式:
      1. round_factor:     er_new = er_old × echo_round_decay_factor
      2. round_half_life:  er_new = er_old × (0.5)^(1 / half_life_rounds)
  - 低于阈值的 SA 被淘汰；全空帧被清除
  - 当前帧处理完成后，注册为新的残响帧进入残响池
  - 池容量受 max_frames 限制，超出时按策略淘汰
"""

import copy
import math
import time


class EchoManager:
    """
    感受器残响池管理器。

    不负责状态池的任何操作——残响是感受器输出层的机制。
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        # 是否启用残响
        self._enabled: bool = cfg.get("enable_echo", True)
        # 衰减模式：round_factor | round_half_life
        self._decay_mode: str = cfg.get("echo_decay_mode", "round_factor")
        # 固定轮次衰减系数。例如 0.4 表示每轮保留 40%。
        self._round_decay_factor: float = cfg.get("echo_round_decay_factor", 0.4)
        # 半衰期（以"轮"为单位）
        self._half_life: float = cfg.get("echo_half_life_rounds", 2.0)
        # SA 能量低于此阈值视为淘汰
        self._min_energy: float = cfg.get("echo_min_energy_threshold", 0.08)
        # 残响池最多保留帧数
        self._max_frames: int = cfg.get("echo_pool_max_frames", 10)
        # 容量溢出时的淘汰策略
        self._elim_strategy: str = cfg.get(
            "echo_frame_elimination_strategy", "oldest_lowest_energy"
        )

        # 残响池：按入池时间排序，最老在前
        self._pool: list[dict] = []

        # 当前轮次编号（每次 decay_and_clean 递增）
        self._round: int = 0

        # 预计算每轮衰减因子
        self._decay_factor: float = self._compute_decay_factor()

    # ------------------------------------------------------------------ #
    #                         公共接口                                     #
    # ------------------------------------------------------------------ #

    def decay_and_clean(self) -> dict:
        """
        对残响池中所有帧执行一轮衰减，并清理落入淘汰区的 SA 与空帧。

        返回:
            {
                "round": int,
                "frames_before": int,
                "frames_after": int,
                "sa_eliminated_count": int,
                "frames_eliminated_count": int,
            }
        """
        if not self._enabled:
            return {
                "round": self._round,
                "frames_before": 0,
                "frames_after": 0,
                "sa_eliminated_count": 0,
                "frames_eliminated_count": 0,
                "decay_mode": self._decay_mode,
                "decay_factor": self._decay_factor,
            }

        self._round += 1
        frames_before = len(self._pool)
        total_sa_eliminated = 0
        frames_to_remove = []

        for frame in self._pool:
            sa_eliminated = self._decay_frame(frame)
            total_sa_eliminated += sa_eliminated

            # 如果帧中所有 SA 都被淘汰，标记帧本身待清除
            if not frame.get("sa_items"):
                frames_to_remove.append(frame["id"])
            else:
                # 同步更新 CSA 列表（移除包含已淘汰 SA 的 CSA）
                self._clean_csa_in_frame(frame)

            frame["round_last_updated"] = self._round
            frame["decay_count"] = frame.get("decay_count", 0) + 1

        # 清除全空帧
        self._pool = [f for f in self._pool if f["id"] not in frames_to_remove]

        frames_after = len(self._pool)

        return {
            "round": self._round,
            "frames_before": frames_before,
            "frames_after": frames_after,
            "sa_eliminated_count": total_sa_eliminated,
            "frames_eliminated_count": frames_before - frames_after,
            "decay_mode": self._decay_mode,
            "decay_factor": self._decay_factor,
        }

    def register_echo(self, echo_frame: dict):
        """
        将新的残响帧注册到池中。
        如果池满，按淘汰策略移除最旧/最弱帧。

        参数:
            echo_frame: 由 _object_builder.build_echo_frame() 构建的 echo_frame 字典
        """
        if not self._enabled:
            return

        echo_frame["round_created"] = self._round
        echo_frame["round_last_updated"] = self._round

        self._pool.append(echo_frame)

        # 容量控制
        while len(self._pool) > self._max_frames:
            self._evict_one()

    def get_active_echo_frames(self) -> list[dict]:
        """
        获取当前残响池中所有活跃帧（按时间顺序，最旧在前）。
        返回深拷贝以防止外部修改内部状态。
        """
        return copy.deepcopy(self._pool)

    def clear(self) -> dict:
        """
        清空残响池。高风险操作，返回审计信息。
        """
        count = len(self._pool)
        self._pool.clear()
        return {
            "action": "clear_echo_pool",
            "cleared_frame_count": count,
            "round": self._round,
            "timestamp_ms": int(time.time() * 1000),
        }

    @property
    def pool_size(self) -> int:
        """当前残响池帧数。"""
        return len(self._pool)

    @property
    def current_round(self) -> int:
        """当前轮次编号。"""
        return self._round

    # ------------------------------------------------------------------ #
    #                         内部方法                                     #
    # ------------------------------------------------------------------ #

    def _decay_frame(self, frame: dict) -> int:
        """
        对一帧中的所有 SA 执行能量衰减。
        返回被淘汰的 SA 数量。
        """
        sa_list = frame.get("sa_items", [])
        eliminated = 0
        surviving = []

        for sa in sa_list:
            energy = sa.get("energy", {})
            old_er = energy.get("er", 0.0)
            old_ev = energy.get("ev", 0.0)

            # 按当前配置模式执行衰减
            new_er = old_er * self._decay_factor
            new_ev = old_ev * self._decay_factor

            # 检查是否低于淘汰阈值
            if new_er < self._min_energy and new_ev < self._min_energy:
                eliminated += 1
                continue  # 淘汰

            # 更新能量
            energy["er"] = round(new_er, 6)
            energy["ev"] = round(new_ev, 6)
            energy["cognitive_pressure_delta"] = round(new_er - new_ev, 6)
            energy["cognitive_pressure_abs"] = round(abs(new_er - new_ev), 6)
            energy["salience_score"] = round(new_er, 6)

            surviving.append(sa)

        frame["sa_items"] = surviving

        # 更新帧能量汇总
        total_er = sum(sa["energy"]["er"] for sa in surviving)
        total_ev = sum(sa["energy"]["ev"] for sa in surviving)
        frame["energy_summary"] = {
            "total_er": round(total_er, 6),
            "total_ev": round(total_ev, 6),
            "ownership_level": "aggregated_from_sa",
        }

        return eliminated

    def _clean_csa_in_frame(self, frame: dict):
        """
        清理帧中引用了已淘汰 SA 的 CSA。
        如果 CSA 的锚点 SA 已不在幸存列表中，则移除该 CSA。
        同时按当前幸存 SA 的实时能量重建 CSA 的能量映射。

        这里不能继续沿用旧的 energy_ownership_map 数值，
        因为 SA 已经在本轮 decay 中衰减了。
        如果直接拿旧映射求和，会出现“SA 衰减了，但 CSA 仍按旧值回灌”的伪能量问题。

        重要变更（为验收可读性服务）:
        - 当文本感受器关闭了 stimulus_intensity 属性 SA（enable_stimulus_intensity_attribute_sa=false）时，
          CSA 可能只包含 1 个成员（锚点特征 SA）。
        - 同样地，即便开启了属性 SA，属性成员在残响衰减中被淘汰后，CSA 也可能退化为仅锚点成员。
        - 这种“单成员 CSA”在原型阶段是允许的：它仍然提供“锚点 + 绑定容器”的语义，
          同时保持下游链路可跑通。
        """
        surviving_sa_map = {
            sa["id"]: sa
            for sa in frame.get("sa_items", [])
            if isinstance(sa, dict) and sa.get("id")
        }
        surviving_sa_ids = set(surviving_sa_map.keys())
        csa_list = frame.get("csa_items", [])
        surviving_csa = []

        for csa in csa_list:
            anchor_id = csa.get("anchor_sa_id", "")
            if anchor_id not in surviving_sa_ids:
                continue  # 锚点已淘汰，整个 CSA 移除

            # 过滤成员中已淘汰的 SA
            old_members = csa.get("member_sa_ids", [])
            new_members = [mid for mid in old_members if mid in surviving_sa_ids]
            # 允许单成员 CSA：只要锚点成员仍然存在就保留。
            if anchor_id not in new_members:
                continue
            csa["member_sa_ids"] = new_members

            # 直接用当前幸存 SA 的实时能量重建所有权映射，
            # 保证 CSA 的能量始终等于其组分 SA 的能量之和。
            new_map = []
            for member_id in new_members:
                member_sa = surviving_sa_map.get(member_id)
                if not member_sa:
                    continue
                member_energy = member_sa.get("energy", {})
                new_map.append(
                    {
                        "sa_id": member_id,
                        "er": round(member_energy.get("er", 0.0), 6),
                        "ev": round(member_energy.get("ev", 0.0), 6),
                    }
                )
            csa["bundle_summary"] = {
                "member_count": len(new_members),
                "display_total_er": round(sum(m["er"] for m in new_map), 6),
                "display_total_ev": round(sum(m["ev"] for m in new_map), 6),
            }

            # 重新聚合能量与所有权映射，保证 CSA 的能量始终等于其组分 SA 的能量之和。
            total_er = round(sum(m["er"] for m in new_map), 6)
            total_ev = round(sum(m["ev"] for m in new_map), 6)
            cp_delta = round(total_er - total_ev, 6)
            cp_abs = round(abs(cp_delta), 6)
            now_ms = int(time.time() * 1000)
            csa["energy_ownership_map"] = new_map
            csa["energy"] = {
                "er": total_er,
                "ev": total_ev,
                "ownership_level": "aggregated_from_sa",
                "computed_from_children": True,
                "fatigue": float(csa.get("energy", {}).get("fatigue", 0.0) or 0.0),
                "recency_gain": float(csa.get("energy", {}).get("recency_gain", 1.0) or 1.0),
                "salience_score": round(max(total_er, total_ev), 6),
                "cognitive_pressure_delta": cp_delta,
                "cognitive_pressure_abs": cp_abs,
                "last_decay_tick": int(self._round),
                "last_decay_at": now_ms,
            }

            surviving_csa.append(csa)

        frame["csa_items"] = surviving_csa

    def _evict_one(self):
        """
        按淘汰策略从池中移除一帧。
        默认策略 "oldest_lowest_energy"：
          在最旧的 1/4 帧中选择总能量最低的一帧移除。
        """
        if not self._pool:
            return

        if self._elim_strategy == "oldest_lowest_energy":
            # 取最旧的 1/4（至少 1 帧）
            quarter = max(1, len(self._pool) // 4)
            candidates = self._pool[:quarter]

            # 选总能量最低的
            weakest = min(
                candidates,
                key=lambda f: f.get("energy_summary", {}).get("total_er", 0),
            )
            self._pool.remove(weakest)
        else:
            # 兜底：移除最旧
            self._pool.pop(0)

    def _compute_decay_factor(self) -> float:
        """
        计算每轮衰减因子。
        支持两种模式：
        1. round_factor: 直接使用固定每轮系数
        2. round_half_life: factor = 0.5^(1/half_life)
        """
        if self._decay_mode == "round_factor":
            if 0 < self._round_decay_factor < 1:
                return float(self._round_decay_factor)
            return 0.4

        if self._half_life <= 0:
            return 0.5
        return math.pow(0.5, 1.0 / self._half_life)

    def update_config(self, config: dict):
        """热加载时更新残响配置。"""
        if "enable_echo" in config:
            self._enabled = bool(config["enable_echo"])
        if "echo_decay_mode" in config:
            self._decay_mode = config["echo_decay_mode"]
        if "echo_round_decay_factor" in config:
            val = float(config["echo_round_decay_factor"])
            if 0 < val < 1:
                self._round_decay_factor = val
        if "echo_half_life_rounds" in config:
            val = float(config["echo_half_life_rounds"])
            if val > 0:
                self._half_life = val
        if "echo_min_energy_threshold" in config:
            self._min_energy = float(config["echo_min_energy_threshold"])
        if "echo_pool_max_frames" in config:
            val = int(config["echo_pool_max_frames"])
            if val > 0:
                self._max_frames = val
        if "echo_frame_elimination_strategy" in config:
            self._elim_strategy = config["echo_frame_elimination_strategy"]
        self._decay_factor = self._compute_decay_factor()
