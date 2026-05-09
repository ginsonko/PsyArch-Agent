# AP 研究观测台渲染说明

## 当前渲染目标
观测台渲染层的目标不是“把原始 JSON 原样丢给用户”，而是把当前原型流程转成便于研究观察的结构化界面。当前实现重点遵循三条原则：

1. 中文优先，必要处补英文。
2. 优先显示结构内容、时序分组、能量变化，而不是只显示 ID。
3. 前端展示顺序必须和真实运行顺序一致。

## 当前数据来源
前端主要读取这些接口：

- `GET /api/dashboard`
- `GET /api/state`
- `GET /api/hdb`
- `GET /api/episodic`
- `GET /api/structure`
- `GET /api/group`
- `GET /api/config`

写接口包括：

- `POST /api/cycle`
- `POST /api/tick`
- `POST /api/check`
- `POST /api/repair`
- `POST /api/repair_all`
- `POST /api/stop_repair`
- `POST /api/clear_hdb`
- `POST /api/clear_all`
- `POST /api/reload`
- `POST /api/config/save`

## 流程渲染约定
当前前端把流程区拆成固定阶段卡片，并按运行顺序展示：

1. 状态池维护
2. 记忆体形成
3. 结构级查存一体
4. 缓存中和
5. 刺激级查存一体
6. 状态池回写与结构投影
7. 感应赋能
8. 记忆赋能池

这几个阶段的标题顺序与前端脚本和 HTML 锚点保持一致，测试中也有专门检查，避免“界面顺序”和“真实顺序”脱节。

## 文本与结构展示约定
### 1. 刺激组显示
当前前端会优先展示带组边界的文本，而不是扁平 token 串。规则是：

- 同一时序组内使用 `[...]`
- 同组内的 SA/属性 SA 使用 `+`
- 不同组之间使用 `/`

例如：

```text
[你好 + stimulus_intensity:1.1] / [呀 + stimulus_intensity:1.1] / [!]
```

这比简单输出 `你好 / stimulus_intensity:1.1 / 呀 / stimulus_intensity:1.1 / !` 更能准确表达“组内顺序不敏感、组间顺序敏感”。

### 2. 结构显示
前端优先读取以下字段展示结构内容：

- `grouped_display_text`
- `canonical_grouped_display_text`
- `raw_grouped_display_text`
- `sequence_groups`
- `display_text`

也就是说，当前会优先保留时序分组和 CSA 绑定信息，而不是把结构退化成简单扁平文本。

### 3. 残差与记忆显示
对于残差或记忆相关对象，前端当前区分：

- 原始残差信息 `raw`
- 还原结构 `canonical`
- 对应记忆 ID `em_id`

这使得观察者能分清：
- 存储时保留了什么占位信息
- 进入状态池或比较时还原成了什么结构
- 它们是否落在同一个记忆体上

## 设置页渲染约定
设置页现在不再只显示原始 JSON，而是按模块、按字段展示：

- 配置键名
- 字段类型
- 文件值
- 运行时覆盖值
- 实际生效值
- 默认值
- 配置文件中的双语注释

对于 `list` / `dict` 类型字段，前端使用文本框显示其 JSON/YAML 形式；保存时交给后端做类型校验与转换。

## HTML / JSON 导出
当前每轮仍会按配置导出：

- `observatory/outputs/cycle_XXXX.html`
- `observatory/outputs/cycle_XXXX.json`
- `observatory/outputs/latest.html`
- `observatory/outputs/latest.json`

HTML 报告面向人工阅读，JSON 报告面向回放、比较和自动化工具。

## 当前边界
当前渲染层不负责：

- 修改 HDB、StatePool、TextSensor 的核心算法
- 理论正确性的最终判定
- 替代原始数据结构

它负责的是把当前实际运行状态尽可能清晰、可读、可检视地展示出来，并保持和真实代码流程同步。
