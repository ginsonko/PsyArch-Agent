# AP 文本感受器模块总览

> 模块名：`text_sensor`  
> 文档状态：按 2026-04-08 当前代码实现同步

## 模块定位
`text_sensor` 是当前原型的文本输入入口。它的职责不是直接“理解语义”，而是把文本输入整理成后续模块可以处理的 `stimulus_packet`。

当前实现已经稳定覆盖：

- 文本归一化
- 字符级 SA / 词元级 SA 生成
- 数值属性 SA 生成
- CSA 绑定生成
- Echo 残响池维护
- 带时序分组的刺激包输出

## 当前输出结构
一次 `ingest_text()` 当前会产出：

- `sensor_frame`
- `stimulus_packet`
- `echo_frames_used`
- `tokenization_summary`
- `importance_summary`
- `echo_decay_summary`

其中最重要的是 `stimulus_packet`，当前核心字段为：

- `sa_items`
- `csa_items`
- `grouped_sa_sequences`
- `energy_summary`
- 各对象上的 `ext.packet_context`

## 当前时序与展示约定
当前实现明确区分：

- 组内并列信息
- 组间时序顺序

统一展示约定为：

- 同一时序信息组：`{...}`
- 同一组内不同 SA / CSA：`+`
- CSA 组内显示：`(...)`
- 不同时序组之间：` / `

例如：

```text
{你好 + (stimulus_intensity:1.1)} / {呀 + (stimulus_intensity:1.1)} / {!}
```

这表示 3 个时序组，而不是把所有 token 扁平地看成 5 或 6 个连续层级。

## CSA 当前语义
当前代码已经对 CSA 做了明确收敛：

- CSA 是“组内绑定关系”的表达对象
- CSA 参与匹配、切割、最大共同部分发现和前端展示
- CSA 不拥有独立运行时能量
- 能量始终归属 SA / ST
- CSA 当前保留 `bundle_summary` 仅用于显示与统计

这意味着：状态池里的 ER / EV 不跟随 CSA 独立流转，CSA 更像结构化约束与显示单元。

## Echo 当前机制
Echo 当前仍然属于输入层，而不是状态池历史。

当前流程：

1. 历史 echo 先衰减并清理
2. 当前输入生成新的 SA / 属性 SA / CSA
3. 当前输入注册为新的 echo frame
4. 构造 `stimulus_packet` 时，把仍然存活的 echo 按时序组并入

当前默认配置下：

- `enable_echo = true`
- `echo_decay_mode = "round_factor"`
- `echo_round_decay_factor = 0.4`
- `echo_min_energy_threshold = 0.08`

## 配置现状
`text_sensor/config/text_sensor_config.yaml` 已作为：

- 模块热加载配置源
- 观测台“设置”页注释源

当前每个配置项都可以在观测台读取说明，并通过“保存并加载 / Save + Reload”生效。

## 对外接口
### `ingest_text()`
文本主入口，输出 `stimulus_packet`。

### `reload_config()`
热加载配置。

### `get_runtime_snapshot()`
查看当前运行摘要。

### `clear_echo_pool()`
清空残响池。

## 当前边界
`text_sensor` 当前不负责：

- 状态池生命周期管理
- 长期记忆存储
- 结构级 / 刺激级查存一体
- 感应赋能
- 记忆赋能池与记忆反哺

它的核心职责是：把文本稳定地转成“带时序分组、保留 CSA 约束、可进入后续认知循环”的刺激对象集合。
