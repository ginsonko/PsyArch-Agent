# -*- coding: utf-8 -*-
"""
AP 文本感受器 → 状态池 端到端联动验收脚本
===========================================
本脚本演示完整数据链路：
  用户输入文本 → TextSensor 生成 stimulus_packet → StatePool 接收并处理

运行方式:
  python state_pool/tests/run_integration.py

特点:
  - 支持用户自由输入文本（非固定测试内容）
  - 每轮显示状态池全量信息
  - 支持多轮连续输入，观察对象叠加和衰减
  - 中英双语输出
"""

import sys
import os
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from text_sensor import TextSensor
from state_pool.main import StatePool
from state_pool._id_generator import reset_id_generator as reset_spm_ids


def print_divider(char="─", width=72):
    print(char * width)


def print_header(title_zh, title_en):
    print(f"\n{'═' * 72}")
    print(f"  {title_zh}")
    print(f"  {title_en}")
    print(f"{'═' * 72}\n")


def print_item_table(items, max_show=15):
    """打印状态池对象表格。"""
    if not items:
        print("  （池为空 / Pool is empty）")
        return

    # 表头
    print(f"  {'序号':>4}  {'显示内容':<12} {'类型':<6} {'er':>8}  {'ev':>8}  {'cp_abs':>8}  {'Δer':>8}  {'Δcp':>8}  {'更新次数':>6}")
    print_divider("─", 90)

    for i, item in enumerate(items[:max_show]):
        display = item.get("display", "?")[:10]
        ref_type = item.get("ref_object_type", "?")[:5]
        er = item.get("er", 0)
        ev = item.get("ev", 0)
        cp = item.get("cp_abs", 0)
        d_er = item.get("delta_er", 0)
        d_cp = item.get("delta_cp_abs", 0)
        uc = item.get("update_count", 0)
        print(f"  {i + 1:>4}  {display:<12} {ref_type:<6} {er:>8.4f}  {ev:>8.4f}  {cp:>8.4f}  {d_er:>+8.4f}  {d_cp:>+8.4f}  {uc:>6}")

    if len(items) > max_show:
        print(f"  ... 省略 {len(items) - max_show} 个对象 / {len(items) - max_show} more items omitted")


def run_interactive():
    from state_pool.tests.run_integration_enhanced import run_interactive as enhanced_run_interactive
    return enhanced_run_interactive()
    """启动交互式联动演示。"""
    print_header(
        "AP 文本感受器 → 状态池 端到端联动演示",
        "AP TextSensor → StatePool End-to-End Integration Demo"
    )
    print("  说明 / Instructions:")
    print("  - 输入任意文本，观察刺激如何经过感受器进入状态池")
    print("  - 输入 'tick' 执行一轮 Tick 维护（衰减+中和+淘汰）")
    print("  - 输入 'snap' 查看当前状态池快照")
    print("  - 输入 'bind' 为TOP对象绑定正确感属性")
    print("  - 输入 'energy' 为TOP对象增加能量")
    print("  - 输入 'clear' 清空状态池")
    print("  - 输入 'quit' 或 'exit' 退出")
    print()

    # 初始化模块
    print("  ⏳ 正在初始化文本感受器（首次加载分词字典可能需要 10~30 秒，请耐心等待）...")
    print("     Initializing TextSensor (first-time dictionary loading may take 10~30s)...")
    ts = TextSensor()
    print("  ✅ 文本感受器初始化完成 / TextSensor initialized\n")
    reset_spm_ids()
    pool = StatePool(config_override={
        "pool_max_items": 500,
        "enable_placeholder_interfaces": True,
        "enable_script_broadcast": True,
    })

    tick_counter = 0

    while True:
        try:
            user_input = input("  📝 请输入文本 / Enter text > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  再见 / Goodbye!")
            break

        if not user_input:
            continue

        # ---- 特殊命令 ----
        cmd = user_input.lower()

        if cmd in ("quit", "exit", "q"):
            print("  再见！ / Goodbye!")
            break

        elif cmd == "tick":
            tick_counter += 1
            print(f"\n  ⏰ 执行 Tick 维护 (第 {tick_counter} 轮) / Running Tick maintenance (round {tick_counter})")
            r = pool.tick_maintain_state_pool(trace_id=f"tick_{tick_counter}")
            d = r["data"]
            print(f"  维护结果 / Maintenance result:")
            print(f"    衰减 / Decayed:       {d['decayed_item_count']}")
            print(f"    中和 / Neutralized:    {d['neutralized_item_count']}")
            print(f"    淘汰 / Pruned:         {d['pruned_item_count']}")
            print(f"    维护前 / Before:       {d['before_item_count']}")
            print(f"    维护后 / After:        {d['after_item_count']}")
            print(f"    高认知压 / High CP:    {d['high_cp_item_count']}")
            # 显示快照
            snap = pool.get_state_snapshot(f"tick_snap_{tick_counter}", top_k=10, sort_by="cp_abs")
            print(f"\n  📊 维护后 Top-10 对象 / Post-maintenance Top-10:")
            print_item_table(snap["data"]["snapshot"]["top_items"])
            print()
            continue

        elif cmd == "snap":
            snap = pool.get_state_snapshot("user_snap", top_k=20, sort_by="cp_abs")
            s = snap["data"]["snapshot"]["summary"]
            print(f"\n  📊 状态池快照 / State Pool Snapshot:")
            print(f"    活跃对象 / Active:     {s['active_item_count']}")
            print(f"    高er对象 / High er:    {s['high_er_item_count']}")
            print(f"    高ev对象 / High ev:    {s['high_ev_item_count']}")
            print(f"    高cp对象 / High cp:    {s['high_cp_item_count']}")
            ps = snap["data"]["pool_stats"]
            print(f"    总调用次数 / Calls:    {ps['total_calls']}")
            print(f"    已创建对象 / Created:  {ps['total_items_created']}")
            print(f"\n  Top-20 对象 / Top-20 Items:")
            print_item_table(snap["data"]["snapshot"]["top_items"], max_show=20)
            print()
            continue

        elif cmd == "bind":
            snap = pool.get_state_snapshot("bind_snap", top_k=1, sort_by="cp_abs")
            top_items = snap["data"]["snapshot"]["top_items"]
            if not top_items:
                print("  ⚠️  池为空，无法绑定 / Pool is empty")
                continue
            target_id = top_items[0]["item_id"]
            target_display = top_items[0]["display"]
            attr_sa = {
                "id": f"sa_attr_correct_{int(time.time() * 1000)}", "object_type": "sa",
                "content": {"raw": "correctness:high", "display": "correctness:high", "value_type": "discrete"},
                "stimulus": {"role": "attribute", "modality": "text"},
                "energy": {"er": 0.0, "ev": 0.0},
            }
            r = pool.bind_attribute_node_to_object(target_id, attr_sa, trace_id="user_bind", source_module="user")
            if r["success"]:
                created = r["data"].get("created_new_csa", False)
                print(f"  ✅ 已为 '{target_display}' 绑定 correctness:high 属性")
                print(f"     Bound 'correctness:high' to '{target_display}'")
                if created:
                    print(f"     自动创建了绑定型 CSA / Auto-created binding CSA")
            else:
                print(f"  ❌ 绑定失败: {r['message']}")
            print()
            continue

        elif cmd == "energy":
            snap = pool.get_state_snapshot("energy_snap", top_k=1, sort_by="cp_abs")
            top_items = snap["data"]["snapshot"]["top_items"]
            if not top_items:
                print("  ⚠️  池为空 / Pool is empty")
                continue
            target_id = top_items[0]["item_id"]
            target_display = top_items[0]["display"]
            r = pool.apply_energy_update(
                target_id, delta_er=1.0, delta_ev=0.5,
                trace_id="user_energy", reason="user_boost", source_module="user",
            )
            if r["success"]:
                print(f"  ✅ 已为 '{target_display}' 增加能量: Δer=+1.0, Δev=+0.5")
                print(f"     er: {r['data']['before']['er']:.4f} → {r['data']['after']['er']:.4f}")
                print(f"     ev: {r['data']['before']['ev']:.4f} → {r['data']['after']['ev']:.4f}")
                print(f"     cp: {r['data']['cp_change']['before_cp_abs']:.4f} → {r['data']['cp_change']['after_cp_abs']:.4f}")
            print()
            continue

        elif cmd == "clear":
            r = pool.clear_state_pool("user_clear", reason="user_reset", operator="user")
            print(f"  🗑️  已清空 {r['data']['cleared_item_count']} 个对象 / Cleared {r['data']['cleared_item_count']} items")
            print()
            continue

        # ---- 正常文本输入 → 感受器 → 状态池 ----
        tick_counter += 1
        trace_id = f"input_{tick_counter}"

        print(f"\n  📥 处理文本 / Processing text: '{user_input}'")
        print_divider()

        # Step 1: 文本感受器处理
        print(f"  [1/3] 文本感受器处理中... / TextSensor processing...")
        ts_result = ts.ingest_text(
            text=user_input,
            trace_id=trace_id,
            tick_id=trace_id,
            source_type="external_user_input",
        )
        if not ts_result.get("success"):
            print(f"  ❌ 文本感受器失败 / TextSensor failed: {ts_result.get('message', '')}")
            continue

        packet = ts_result["data"]["stimulus_packet"]
        sa_count = len(packet.get("sa_items", []))
        csa_count = len(packet.get("csa_items", []))
        print(f"        → 生成 {sa_count} 个 SA, {csa_count} 个 CSA")

        # Step 2: 状态池接收
        print(f"  [2/3] 状态池接收刺激包... / StatePool receiving stimulus packet...")
        sp_result = pool.apply_stimulus_packet(
            stimulus_packet=packet,
            trace_id=trace_id,
            tick_id=trace_id,
            source_module="text_sensor",
        )
        if sp_result["success"]:
            d = sp_result["data"]
            print(f"        → 新建 {d['new_item_count']} | 更新 {d['updated_item_count']} | "
                  f"拒绝 {d['rejected_object_count']}")
            ds = d.get("state_delta_summary", {})
            print(f"        → 总体 Δer={ds.get('total_delta_er', 0):.4f}  "
                  f"高认知压对象={ds.get('high_cp_item_count', 0)}")
        else:
            print(f"  ❌ 状态池接收失败 / StatePool failed: {sp_result.get('message', '')}")
            continue

        # Step 3: 显示接收刺激后的初步状态
        print(f"  [3/5] 刺激接收后池概览 / Post-stimulus pool overview:")
        snap = pool.get_state_snapshot(f"snap_{tick_counter}_pre", top_k=5, sort_by="cp_abs")
        print_item_table(snap["data"]["snapshot"]["top_items"], max_show=5)

        # Step 4: 模拟时间流逝与自动 Tick 维护 (衰减、中和)
        print(f"\n  [4/5] ⏳ 模拟认知流逝... 自动执行两轮 Tick 维护 / Simulating time passing...")
        time.sleep(0.5)
        for i in range(2):
            r = pool.tick_maintain_state_pool(trace_id=f"auto_tick_{tick_counter}_{i}")
            d = r["data"]
            print(f"        → 第 {i+1} 轮: 衰减 {d['decayed_item_count']} | 中和 {d['neutralized_item_count']} | 淘汰 {d['pruned_item_count']}")
        
        # Step 5: 模拟脚本层根据认知压最高的对象赋予注意力/属性绑定
        print(f"\n  [5/5] 💡 模拟下游反馈... / Simulating downstream feedback...")
        snap_mid = pool.get_state_snapshot(f"snap_{tick_counter}_mid", top_k=1, sort_by="cp_abs")
        if snap_mid["data"]["snapshot"]["top_items"]:
            top = snap_mid["data"]["snapshot"]["top_items"][0]
            print(f"        → 发现全场最高认知压对象: {top['display']} (cp={top['cp_abs']:.4f})")
            
            # 自动能量更新
            print(f"        → ⚡ 自动注入预测(ev)以进行中和尝试...")
            pool.apply_energy_update(top["item_id"], delta_er=0.0, delta_ev=0.5, trace_id="", reason="demo_ev_inject")
            pool.tick_maintain_state_pool(trace_id="") # 触发一次中和
            
            # 自动属性绑定
            attr_sa = {
                "id": f"sa_attr_auto_{tick_counter}", "object_type": "sa",
                "content": {"raw": "attention:focused", "display": "attention:focused", "value_type": "discrete"},
                "stimulus": {"role": "attribute", "modality": "internal"},
                "energy": {"er": 0.0, "ev": 0.0},
            }
            print(f"        → 🔗 自动绑定属性: attention:focused")
            pool.bind_attribute_node_to_object(top["item_id"], attr_sa, trace_id="", source_module="demo")

        # 最终显示当前状态
        print(f"\n  📊 本轮处理后最终 Top-10 / Final Top-10 after processing:")
        snap_final = pool.get_state_snapshot(f"snap_{tick_counter}_final", top_k=10, sort_by="cp_abs")
        print_item_table(snap_final["data"]["snapshot"]["top_items"], max_show=10)
        print("\n  ----------------------------------------------------------------------")

    pool._logger.close()
    ts._logger.close()


if __name__ == "__main__":
    run_interactive()
