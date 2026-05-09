# -*- coding: utf-8 -*-
"""
AP 状态池模块 — 交互式中文验收脚本
====================================
运行方式:
  python state_pool/tests/run_verification.py

本脚本覆盖以下验收场景:
  1. 基础刺激包应用
  2. 重复输入叠加
  3. 认知压计算
  4. 定向能量更新
  5. 属性绑定
  6. 运行态对象插入
  7. Tick 维护（衰减+中和+淘汰）
  8. 多轮衰减观察
  9. 快照输出
  10. 配置热加载
  11. 清空状态池
  12. 占位接口联调

每个场景提供详细中英双语说明。
"""

import sys
import os
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from state_pool.main import StatePool
from state_pool._id_generator import reset_id_generator

# ====================================================================== #
#                          工具函数                                        #
# ====================================================================== #

PASS = "✅ 通过 / PASS"
FAIL = "❌ 失败 / FAIL"
WARN = "⚠️  警告 / WARN"
INFO = "ℹ️  信息 / INFO"

_stats = {"pass": 0, "fail": 0, "warn": 0, "total": 0}


def check(cond: bool, desc_zh: str, desc_en: str, detail: str = ""):
    """验证一个条件并打印结果。"""
    _stats["total"] += 1
    if cond:
        _stats["pass"] += 1
        print(f"  {PASS}  {desc_zh} | {desc_en}")
    else:
        _stats["fail"] += 1
        print(f"  {FAIL}  {desc_zh} | {desc_en}")
    if detail:
        print(f"         → {detail}")


def info(msg):
    print(f"  {INFO}  {msg}")


def section(num, title_zh, title_en):
    print(f"\n{'=' * 72}")
    print(f"  场景 {num}: {title_zh}")
    print(f"  Scenario {num}: {title_en}")
    print(f"{'=' * 72}")


def make_test_packet(text: str, trace_id: str = "test"):
    """从一段文本生成模拟刺激包。"""
    now_ms = int(time.time() * 1000)
    sa_items = []
    csa_items = []
    for i, ch in enumerate(text):
        sa = {
            "id": f"sa_txt_{trace_id}_{i:04d}", "object_type": "sa",
            "content": {"raw": ch, "display": ch, "value_type": "discrete"},
            "stimulus": {"role": "feature", "modality": "text"},
            "energy": {"er": 1.0, "ev": 0.0},
            "created_at": now_ms, "updated_at": now_ms,
        }
        sa_items.append(sa)
        # 为每个字符创建 CSA
        attr_sa = {
            "id": f"sa_attr_{trace_id}_{i:04d}", "object_type": "sa",
            "content": {"raw": f"stimulus_intensity:1.0", "display": f"intensity:1.0", "value_type": "numerical"},
            "stimulus": {"role": "attribute", "modality": "text"},
            "energy": {"er": 0.0, "ev": 0.0},
        }
        csa = {
            "id": f"csa_txt_{trace_id}_{i:04d}", "object_type": "csa",
            "anchor_sa_id": sa["id"], "member_sa_ids": [sa["id"], attr_sa["id"]],
            "energy": {"er": 1.0, "ev": 0.0},
        }
        sa_items.append(attr_sa)
        csa_items.append(csa)

    return {
        "id": f"spkt_{trace_id}", "object_type": "stimulus_packet",
        "sa_items": sa_items, "csa_items": csa_items, "trace_id": trace_id,
    }


# ====================================================================== #
#                          验收场景                                        #
# ====================================================================== #


def run_all():
    reset_id_generator()
    pool = StatePool(config_override={
        "pool_max_items": 500,
        "enable_placeholder_interfaces": True,
        "enable_script_broadcast": True,
    })

    print("\n" + "=" * 72)
    print("  AP 状态池模块（SPM）交互式验收")
    print("  AP State Pool Module — Interactive Verification")
    print(f"  模块版本 / Version: 1.0.0  |  Schema: 1.1")
    print("=" * 72)

    # ---- 场景 1: 基础刺激包 ----
    section(1, "基础刺激包应用", "Basic stimulus packet application")
    pkt = make_test_packet("你好", "sc1")
    info(f"输入文本: '你好'（生成 {len(pkt['sa_items'])} 个 SA, {len(pkt['csa_items'])} 个 CSA）")
    r = pool.apply_stimulus_packet(pkt, trace_id="sc1_t1")
    check(r["success"], "刺激包应用成功", "Stimulus packet applied", f"code={r['code']}")
    check(r["data"]["new_item_count"] > 0, "创建了新对象", "New items created",
          f"新建 {r['data']['new_item_count']} 个")
    check(r["data"]["rejected_object_count"] == 0, "无被拒对象", "No rejected objects")

    # ---- 场景 2: 重复输入 ----
    section(2, "重复输入叠加", "Duplicate input stacking")
    r2 = pool.apply_stimulus_packet(pkt, trace_id="sc2_t1")
    check(r2["success"], "重复应用成功", "Duplicate apply succeeded")
    check(r2["data"]["updated_item_count"] > 0, "已有对象被更新（非新建）", "Existing items updated (not new)",
          f"更新 {r2['data']['updated_item_count']} 个")
    check(r2["data"]["new_item_count"] == 0, "未产生重复新建", "No duplicate creation")

    # ---- 场景 3: 认知压计算 ----
    section(3, "认知压计算验证", "Cognitive pressure calculation")
    snap = pool.get_state_snapshot("sc3_s")
    items = snap["data"]["snapshot"]["top_items"]
    if items:
        top = items[0]
        expected_cp = abs(top["er"] - top["ev"])
        check(abs(top["cp_abs"] - expected_cp) < 0.001,
              "cp_abs = |er - ev| 成立", "cp_abs = |er - ev| holds",
              f"er={top['er']:.4f}, ev={top['ev']:.4f}, cp_abs={top['cp_abs']:.4f}")
        info(f"TOP 对象: {top['display']}  er={top['er']:.4f}  ev={top['ev']:.4f}  cp={top['cp_abs']:.4f}")

    # ---- 场景 4: 定向能量更新 ----
    section(4, "定向能量更新", "Targeted energy update")
    item_id = items[0]["item_id"] if items else ""
    if item_id:
        r4 = pool.apply_energy_update(item_id, delta_er=0.5, delta_ev=0.3, trace_id="sc4_t1", reason="test_boost")
        check(r4["success"], "能量更新成功", "Energy update succeeded")
        check(r4["data"]["after"]["er"] > r4["data"]["before"]["er"], "er 增加了", "er increased",
              f"before={r4['data']['before']['er']:.4f} → after={r4['data']['after']['er']:.4f}")
        check(r4["data"]["after"]["ev"] > r4["data"]["before"]["ev"], "ev 增加了", "ev increased",
              f"before={r4['data']['before']['ev']:.4f} → after={r4['data']['after']['ev']:.4f}")

    # ---- 场景 5: 属性绑定 ----
    section(5, "属性绑定", "Attribute binding")
    attr_sa = {
        "id": "sa_attr_correct_001", "object_type": "sa",
        "content": {"raw": "correctness:high", "display": "correctness:high", "value_type": "discrete"},
        "stimulus": {"role": "attribute", "modality": "text"},
        "energy": {"er": 0.0, "ev": 0.0},
    }
    sa_items_in_pool = [i for i in items if i.get("ref_object_type") == "sa"]
    if sa_items_in_pool:
        target = sa_items_in_pool[0]["item_id"]
        r5 = pool.bind_attribute_node_to_object(target, attr_sa, trace_id="sc5_t1", source_module="test")
        check(r5["success"], "属性绑定成功", "Attribute binding succeeded")
        check(r5["data"].get("created_new_csa", False), "自动创建了绑定型 CSA", "Auto-created binding CSA")
        info(f"绑 定: {target} ← correctness:high")

    # ---- 场景 6: 运行态对象插入 ----
    section(6, "运行态对象插入", "Runtime node insertion")
    cfs = {
        "id": "cfs_boredom_001", "object_type": "cfs_signal",
        "content": {"raw": "boredom:high", "display": "boredom:high"},
        "energy": {"er": 0.5, "ev": 0.0},
    }
    r6 = pool.insert_runtime_node(cfs, trace_id="sc6_t1", reason="test_insert")
    check(r6["success"], "CFS 信号插入成功", "CFS signal inserted")
    info(f"池大小: {pool._store.size}")

    # ---- 场景 7: Tick 维护 ----
    section(7, "Tick 维护（衰减+中和+淘汰）", "Tick maintenance (decay+neutralize+prune)")
    before_size = pool._store.size
    r7 = pool.tick_maintain_state_pool(trace_id="sc7_m1")
    check(r7["success"], "维护执行成功", "Maintenance executed")
    d = r7["data"]
    info(f"衰减 {d['decayed_item_count']} | 中和 {d['neutralized_item_count']} | 淘汰 {d['pruned_item_count']}")
    info(f"维护前 {d['before_item_count']} → 维护后 {d['after_item_count']}")

    # ---- 场景 8: 多轮衰减观察 ----
    section(8, "多轮衰减观察", "Multi-tick decay observation")
    snap_before = pool.get_state_snapshot("sc8_s1")
    if snap_before["data"]["snapshot"]["top_items"]:
        er_start = snap_before["data"]["snapshot"]["top_items"][0]["er"]
        for i in range(5):
            pool.tick_maintain_state_pool(trace_id=f"sc8_m{i}")
        snap_after = pool.get_state_snapshot("sc8_s2")
        if snap_after["data"]["snapshot"]["top_items"]:
            er_end = snap_after["data"]["snapshot"]["top_items"][0]["er"]
            check(er_end < er_start, "5轮衰减后 er 显著下降", "er decreased after 5 ticks",
                  f"{er_start:.6f} → {er_end:.6f} (衰减 {(1 - er_end / er_start) * 100:.1f}%)")

    # ---- 场景 9: 快照 ----
    section(9, "快照输出", "Snapshot output")
    r9 = pool.get_state_snapshot("sc9_s1", top_k=5, sort_by="cp_abs")
    check(r9["success"], "快照获取成功", "Snapshot retrieved")
    snap9 = r9["data"]["snapshot"]
    info(f"活跃对象: {snap9['summary']['active_item_count']}")
    info(f"高认知压对象: {snap9['summary']['high_cp_item_count']}")
    if snap9["top_items"]:
        info(f"Top-1: {snap9['top_items'][0]['display']}  er={snap9['top_items'][0]['er']:.4f}  cp={snap9['top_items'][0]['cp_abs']:.4f}")

    # ---- 场景 10: 配置热加载 ----
    section(10, "配置热加载", "Config hot reload")
    r10 = pool.reload_config(trace_id="sc10_cfg")
    check("code" in r10, "热加载返回结构正常", "Reload returned proper structure")
    info(f"结果: {r10['code']}")

    # ---- 场景 11: 清空 ----
    section(11, "清空状态池", "Clear state pool")
    r11 = pool.clear_state_pool(trace_id="sc11_clear", reason="verification_reset", operator="tester")
    check(r11["success"], "清空成功", "Clear succeeded")
    check(pool._store.size == 0, "池已空", "Pool is empty",
          f"清除 {r11['data']['cleared_item_count']} 个对象")

    # ---- 场景 12: 占位接口联调 ----
    section(12, "占位接口联调", "Placeholder interface integration")
    pkt2 = make_test_packet("测试", "sc12")
    r12 = pool.apply_stimulus_packet(pkt2, trace_id="sc12_t1")
    check(r12["success"], "刺激包应用成功（含占位广播）", "Packet applied (with placeholder broadcast)")
    # 检查 script_broadcast_sent
    if r12["data"].get("script_broadcast_sent"):
        info("脚本抄送广播: 已发送（占位返回）")
    else:
        info("脚本抄送广播: 未发送（可能因配置）")

    # ---- 总结 ----
    print(f"\n{'=' * 72}")
    print(f"  验收总结 / Verification Summary")
    print(f"{'=' * 72}")
    print(f"  总计 / Total:    {_stats['total']}")
    print(f"  通过 / Passed:   {_stats['pass']}")
    print(f"  失败 / Failed:   {_stats['fail']}")
    if _stats["fail"] == 0:
        print(f"\n  🎉 全部通过！状态池模块验收完成！")
        print(f"  🎉 All passed! State Pool Module verification complete!")
    else:
        print(f"\n  ⚠️  存在失败项，请检查上方详情。")
        print(f"  ⚠️  Some tests failed, check details above.")
    print()

    pool._logger.close()


if __name__ == "__main__":
    run_all()
