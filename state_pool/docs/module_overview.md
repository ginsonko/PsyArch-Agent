# AP 状态池模块总览

> 模块名：`state_pool`  
> 文档状态：按 2026-04-08 当前代码实现同步

## 模块定位
`state_pool` 是当前原型的运行态容器。它维护的不是长期记忆，而是“这一刻哪些对象在场、这些对象的 ER / EV / CP 如何变化、哪些对象正在形成认知压”。

当前已经稳定承担：

- 接收 `stimulus_packet`
- 把 SA / ST / 运行态投影映射为 `state_item`
- 维护 ER / EV / CP 与变化率
- 做衰减、中和、淘汰、合并
- 提供快照、历史窗口和脚本广播占位

## 当前输入来源
当前状态池主要接收三类输入：

1. `text_sensor` 输出的 `stimulus_packet`
2. HDB 投影回写的结构对象
3. 手动或脚本插入的运行态节点

## 当前关键约束
### 1. CSA 不作为默认运行态对象入池
当前实现中：

- `stimulus_packet` 进入状态池时，只把 `sa_items` 映射为默认运行态对象
- `csa_items` 保留为 packet 内分组、匹配、切割与显示辅助信息
- 状态池中的运行时能量只跟随 SA / ST，不跟随 CSA 自身

这与当前理论约束一致：CSA 是“绑定关系与结构约束”，不是独立能量载体。

### 2. 语义同一对象合并
当前状态池已启用：

- 同 `ref_object_id` 合并
- 语义同一对象合并
- 同包内语义同一对象先聚合

这可以避免 Echo、结构投影和多次输入造成无意义的池内膨胀。

### 3. 缓存中和 / 优先刺激中和
当前状态池包含“优先刺激中和”路径。

重要说明：

- 中和本质上是 ER 与 EV 之间的对消
- 如果当前输入几乎全是 ER，而没有可对消的 EV，就不会真正发生中和
- 即便没有真正中和，前端仍会展示“缺口 / shortfall”而不是简单显示 0

## 属性绑定当前实现
当前属性绑定能力已收敛为：

- 默认只支持绑定到运行态 `SA`
- 默认配置：`attribute_binding_supported_target_types: ["sa"]`
- 默认配置：`allow_auto_create_csa_on_attribute_bind: false`

也就是说，当前状态池不会因为属性绑定而默认自动创建新的运行态 CSA。

## Tick 维护当前顺序
每轮维护当前包括：

1. 衰减
2. 中和
3. 动态信息更新
4. 淘汰
5. 聚合统计

## 快照当前重点
`get_state_snapshot()` 当前重点返回：

- `summary`
- `top_items`
- `history_window_ref`

前端当前重点展示：

- 对象类型
- 显示文本
- ER / EV / CP
- fatigue / recency_gain
- 绑定属性信息

## 配置现状
`state_pool/config/state_pool_config.yaml` 当前同时承担：

- 模块热加载配置源
- 观测台“设置”页字段注释源

当前重要配置已经与代码默认值对齐，尤其是：

- `allow_auto_create_csa_on_attribute_bind: false`
- `attribute_binding_supported_target_types: ["sa"]`
- `recency_gain_peak: 10.0`
- `recency_gain_hold_ticks: 2`
- `recency_gain_decay_ratio: 0.9999976974`

其中，当前默认口径是：

- 新建或重新激活的运行态对象，近因增益会先抬到约 `10x`
- 保持一个很短的峰值阶段后，再按 Tick 缓慢衰减
- 按默认 `recency_gain_decay_ratio`，会在约 `1,000,000` Tick 量级回到 `1x` 附近
- 疲劳仍然是短窗重复激活抑制，不是长时间年龄衰减

## 对外接口
### `apply_stimulus_packet()`
接收刺激包并写入状态池。

### `apply_energy_update()`
对已有对象做定向 ER / EV 更新。

### `bind_attribute_node_to_object()`
把属性 SA 绑定到已有运行态对象。

### `insert_runtime_node()`
手动插入运行态节点。

### `tick_maintain_state_pool()`
执行一轮维护。

### `get_state_snapshot()`
获取当前快照。

### `reload_config()`
热加载配置。

### `clear_state_pool()`
清空状态池。

## 当前边界
`state_pool` 当前不负责：

- 长期结构化记忆持久化
- 结构级 / 刺激级查存一体
- 感应赋能
- 记忆赋能池

它的职责是：把输入、投影与运行态对象维护成“当前可被后续模块消费的状态空间”。
