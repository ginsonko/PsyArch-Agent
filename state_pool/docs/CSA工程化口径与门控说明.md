# -*- coding: utf-8 -*-
AP 原型：CSA 工程化口径与门控说明
================================

本说明用于回答一个常见困惑：
为什么理论里有 CSA（组合刺激元），但在工程实现里我们不希望在状态池（SP, StatePool）里同时出现：
`"你好"` 以及 `CSA["你好"]` 这样的“双份对象”？

结论（推荐口径）
--------------
1. CSA（组合刺激元, Composite Stimulus Atom）在原型阶段优先视为“绑定约束信息/门控约束（gate constraint）”，而不是必须常驻 SP 的独立对象。
2. 状态池里只保留“锚点对象（anchor）”作为核心运行态对象；与锚点绑定的属性（attribute SA）被“融合/折叠”到锚点的额外字段中展示与参与门控。
3. HDB（全息深度数据库）在“完全包含/完全匹配”判断里执行 CSA 门控：结构侧某个 bundle 必须被刺激侧某一个 bundle 完整覆盖，禁止用两个 bundle 拼一个 bundle。

这样做的收益：
- 观测更清爽：避免状态池回写出现大量 `stimulus_intensity:1.1`、`CSA[...]` 的噪音条目。
- 语义更稳定：CSA 作为门控约束存在于结构匹配规则中，避免跨对象拼接造成误匹配。
- 兼容演化：当未来需要把 CSA 作为独立对象观测/脚本消费时，可通过开关打开“写入/生成”。

术语约定（中文为主，括号内为英文/简写）
------------------------------------
- SA：基础刺激元（Stimulus Atom）
- 属性 SA：属性刺激元（attribute SA），其 `stimulus.role == "attribute"`，通常通过 `parent_ids` 绑定到锚点 SA
- CSA：组合刺激元（Composite Stimulus Atom），锚点 + 多个属性的组合视图，承担门控约束
- 锚点（anchor）：同一对象的“特征 SA”（feature SA），承载主要能量与可寻址性
- bundle：工程实现里对“一个 CSA 约束单元”的称呼（用于门控检查与结构签名）

状态池（SP）侧：如何做到“不共存 SA 与独立 CSA”
----------------------------------------------
对应实现见：
- [state_pool/main.py](/H:/AP原型测试/state_pool/main.py)
- [state_pool/config/state_pool_config.yaml](/H:/AP原型测试/state_pool/config/state_pool_config.yaml)

关键开关（默认推荐）：
- `insert_csa_as_state_item: false`
  含义：不把感受器输出的 `csa_items` 写入 SP。
- `insert_attribute_sa_as_state_item: false`
  含义：不把属性 SA 作为独立 state_item 写入 SP；而是折叠进锚点对象的融合视图。
- `allow_auto_create_csa_on_attribute_bind: false`
  含义：运行态属性绑定（如 CFS 绑定）不自动创建“绑定型 CSA state_item”。

融合视图的数据落点：
- `binding_state.packet_attribute_by_name`
  存放“本次刺激包”里与锚点绑定的属性（按 attribute_name 覆写，保证稳定）。
- `ref_snapshot.attribute_displays`
  供前端展示的属性摘要（来自 packet_attribute_by_name）。
- `binding_state.bound_attribute_sa_ids` / `ref_snapshot.bound_attribute_displays`
  运行态绑定属性（例如 CFS 写回的元认知属性），用于观测与后续脚本/行动调制。

注意：
即便属性 SA 不入池，它的能量不会“凭空消失”。
原型实现会把属性 SA 的能量折叠进锚点对象的入池能量统计，避免能量守恒被破坏。

HDB 侧：CSA 门控（bundle gate）如何保证“不能拼接”
-------------------------------------------------
对应实现见：
- [hdb/_cut_engine.py](/H:/AP原型测试/hdb/_cut_engine.py)
- [hdb/_stimulus_retrieval.py](/H:/AP原型测试/hdb/_stimulus_retrieval.py)
- [hdb/_structure_retrieval.py](/H:/AP原型测试/hdb/_structure_retrieval.py)

门控语义（与理论核心 3.3.3 对齐）：
- 若结构侧包含某个 CSA bundle，则匹配方必须提供“一个”可完全包含该 bundle 内容的另一 bundle。
- 允许刺激侧 bundle 比结构侧多属性，但不能少。
- 不允许用两个刺激侧 bundle 分别覆盖结构侧 bundle 的一部分来“拼出完全覆盖”。

工程实现方式（简述）：
1. 在序列组（sequence_group）里把 CSA 表达为 `csa_bundles`（每个 bundle 有 anchor_unit_id 与 member_unit_ids）。
2. 在最大共同部分/完全包含判断中，增加 bundle gate 检查：
   - `bundle_constraints_ok_existing_included`：结构侧 bundle 是否都被刺激侧单 bundle 覆盖
   - `bundle_constraints_ok_exact`：双方互相包含都成立（用于 exact match）

如何调试/观测
------------
1. 观测台 UI：
   - 状态池条目会显示 `attribute_displays`（来自 packet 融合）与 `bound_attribute_displays`（来自运行态绑定）。
2. 如需观察“属性 SA/CSA 作为独立对象”的旧视图：
   - 将 `insert_attribute_sa_as_state_item: true` 或 `insert_csa_as_state_item: true` 打开（仅建议用于调试）。

