# 实虚能量平衡控制器（EBC）模块说明

## 这是什么
EBC（Energy Balance Controller）是一个“可插拔闭环控制器”，用于把系统全局的：

`EV_total / ER_total`

拉回到一个目标值 `target_ratio`（默认 1.0，对应 EV≈ER）。

它不改变核心查存、学习、行动逻辑，而是输出“调制系数（scale）”，由观测台在下一 tick 应用到 HDB（全息深度数据库）的传播/诱发参数上。

## 为什么需要它
只靠固定参数很难保证：

“无论外感受器实能量输入频次怎样变化，系统长时间运行后仍能稳定并把预测对齐现实（1:1）”

原因包括：
- ER/EV 衰减系数不同带来的偏置
- 传播/诱发阈值 + Top-K 竞争导致非线性
- 状态池软上限会把“输入频次”映射为“衰减强度”

因此必须引入负反馈闭环，才能对“输入整体缩放”保持鲁棒。

## 控制律（对数域积分）
定义：
- `ratio = EV_total / (ER_total + eps)`
- `e = ln(ratio / target_ratio)`

更新：
- `ln(g_next) = clamp( ln(g) - ki * e, ln(g_min), ln(g_max) )`

输出：
- `ev_propagation_ratio_scale = g`
- `er_induction_ratio_scale = g`

最终 HDB 生效参数由 `base_value * (EMgr_scale * g)` 得到（注意是相乘合并，不是覆盖）。

## 如何验收（推荐最严苛）
1. 把外感受输入强度整体缩放（例如 x0.2 / x5），跑较长时间（数百 tick）。
2. 观察 `ratio_smooth` 是否回到 1 附近，并保持小幅波动而不发散。
3. 同时检查 `g` 是否会自动调整到一个稳定范围（而不是打到 clamp）。

## 配置项
见：`energy_balance/config/energy_balance_config.yaml`

