# PsyArch Agent

PsyArch Agent 是一个把 AP（Artificial PsyArch，人工心灵架构）接入语言 Agent 的实验原型。它不是成熟 Bot 框架的替代品，而是一个中间版本的拟人核心示范平台：用 AP 提供连续的本地状态、记忆、认知感受和主观能动性，再由 LLM 负责把这些状态拟合成自然语言、工具调用和社交平台动作。

AP 底层项目参考：[Artificial-PsyArch](https://github.com/ginsonko/Artificial-PsyArch/)

> 当前仍是开发中原型，后续结构、接口和默认配置都可能调整。遇到 bug 可以加反馈群：`296842274`，备注 `PsyArch Agent`。

## 现在能做什么

- 主页可以直接和 PA 对话，并实时观察本轮运行阶段、LLM/API 调用日志、近期想法、AP tick、情绪 NT 与认知感受。
- 页面里的 AP 想法云会随运行过程不断更新，通常每零点几秒到一两秒可见一次状态变化，方便观察“生命体征”式的连续变化。
- AP 能为 Agent 提供纯本地、具有自学习能力的长期记忆入口，以及持续演化的情绪通道和认知感受信息。
- 这些 NT / CFS 信息来自 AP 状态池、行动系统和底层演化链路，不是 LLM 事后推理出来的情绪标签。
- AP 可以通过本地行动节点形成主动性：纯本地运行若干 tick 后，可以触发主动回复行动、唤醒 LLM、或让 LLM 再判断是否真的需要回复。
- 支持人设、模型/号池、知识库雏形、MCP / skills / 私有协议与插件入口、图片理解、多模态输入输出、绘图、表情包小偷等常见 Agent 能力。
- 支持 NapCat QQ 适配器：私聊全量、群聊艾特、关键词唤醒、群聊全量 AP 门控、群聊连续对话窗口、主动回复、图片/表情包/绘图发送等能力正在迭代中。

## 适合谁

这个项目适合想研究或复用 AP 拟人核心的人，尤其是想把“长期记忆、稳定人格核心、情绪/认知感受、主观能动性”从 LLM 提示词模拟中拆出来，交给一个本地持续演化系统来承担的开发者。

如果你只是想要一个稳定商用 QQ Bot，它目前还不如成熟 Bot 框架可靠；如果你想观察 AP 如何作为 Agent 的拟人核心模块运行，它会更有价值。

## 快速开始

### 1. 准备环境

建议环境：

- Windows 10/11
- Python 3.10+
- Git
- 如需 NapCat：Node.js 20+、pnpm/corepack、已安装 QQ NT

### 2. 安装依赖

双击：

```bat
依赖自检与安装.bat
```

脚本会创建 `.venv` 并安装 `requirements.txt`。如果安装失败，通常是 Python 没加入 PATH、网络代理问题，或 pip 源连接失败。

### 3. 启动 PA

双击：

```bat
快速启动观测台.bat
```

启动后打开：

```text
http://127.0.0.1:8765/next/
```

进入 Agent 页面后，在配置里填写：

- `Base URL`：OpenAI 兼容接口地址，默认 `https://api.openai.com`
- `API Key`：你的模型密钥
- `Model`：你的聊天模型
- 需要读图/绘图时，再配置视觉、多模态或绘图模型；对应 Key 留空时会复用主 API Key

保存配置后，就可以在主页聊天框里直接对话。

### 更新与旧版数据迁移

如果你已经有一个旧版目录，不建议再新建第二份目录来更新。优先在正在使用的 PA 目录里双击：

```bat
一键重启进程并更新.bat
```

它会先关闭占用 `8765` 端口的旧 PA 进程，再原地更新当前文件夹，最后重新启动 PA-Agent 与 AP 后端。这样配置、人设、日记、图书馆、表情包和 HDB 数据会继续留在当前目录。

如果本地已经同时出现 `PsyArch-Agent` 和 `PsyArch-Agent-main`，或需要把旧目录数据迁移到新目录，请看 [旧版数据迁移与原地更新](docs/旧版数据迁移与原地更新.md)。常用方式：

```bat
数据迁移-打包.bat
数据迁移-解压.bat
```

旧目录运行打包，新目录复制 `PA用户数据迁移包.zip` 后运行解压。

## 对接 NapCat QQ

NapCat 不会放进本仓库。需要 QQ 适配器时，按下面顺序操作。

### 1. 拉取或更新 NapCat

双击：

```bat
一键拉取或更新NapCat.bat
```

默认会把 NapCat 拉到 PA 仓库同级目录：

```text
..\NapCatQQ
```

如果目录已存在且是 Git checkout，脚本会执行 `git pull --ff-only` 更新。

### 2. 配置 NapCat 连接 PA

双击：

```bat
一键配置NapCat连接PA.bat
```

它会写入 NapCat OneBot 配置：

- HTTP Server：`127.0.0.1:3000`
- WebSocket Server：`127.0.0.1:3001`
- PA Webhook：`http://127.0.0.1:8765/api/agent/napcat/event`
- 消息格式：`array`

如果你已经有自己的 NapCat，不想使用一键配置脚本，可以按 [已有 NapCat 的手动配置方法](docs/已有NapCat手动配置.md) 检查网络配置。核心是必须启用三个项目：HTTP 服务器、HTTP 客户端、WebSocket 服务器；其中 HTTP 客户端 URL 必须填 `http://127.0.0.1:8765/api/agent/napcat/event`。

### 3. 启动 NapCat

先启动 PA，再在 Agent 适配器页面点击“一键打开 NapCat”，或双击：

```bat
一键打开NapCat.bat
```

首次运行源码版 NapCat 可能会安装依赖并构建 WebUI，需要等待一会儿。NapCat 打开后登录你的 Bot QQ，确认网络配置里有 PA Agent Webhook，就可以在 QQ 私聊或群聊中测试。

## 默认配置说明

发布默认值会尽量保持“打开即可测试，但不会泄露隐私”：

- API Key 为空，需要你自己填写。
- Base URL 使用通用 OpenAI 兼容默认值。
- 默认人设为“小澪 / 林嘉欣”模板，但主人 QQ 已脱敏为 `*********`，真实 owner QQ 需要你自己在配置中填写。
- NapCat 默认开启并关闭 dry-run，方便用户按教程配置 NapCat 后直接测试 QQ 收发；主人 QQ、白名单和群白名单默认留空作为占位，需要按自己的账号填写。若想先保守演练，请在适配器页手动打开 `NapCat dry-run`。
- 表情包小偷默认开启，用于测试图片/表情包识别与本地表情库，但运行生成的表情包目录不会入库。
- 运行输出、历史记录、日志、模型密钥、图片生成结果、表情包库等都在 `observatory/outputs/` 下，本仓库默认忽略。

## 日志与磁盘占用

新版默认只刷新 `observatory/outputs/latest.json` 和 `latest.html`，不会再为每一轮 AP tick 保留巨大的 `cycle_*.json/html` 历史报告；LLM、适配器和运行事件日志也会自动截断、压缩和轮转。

如果你从旧版本升级，发现 `observatory/outputs/` 已经占用很多空间，可以双击：

```bat
清理日志和临时输出.bat
```

建议先选择“Preview only”预览，再选择保留 1 天或清理全部目标。脚本会保留配置、HDB 数据、`latest.json/latest.html`、表情包、生成图片和收到的附件，只清理历史轮次报告、临时探针输出和过大的可轮转日志。

## 隐私与安全

发布、提 issue 或截图前，请注意：

- 不要上传 `observatory/outputs/`。
- 不要上传 API Key、私有 Base URL、QQ 号白名单、聊天历史、NapCat token。
- 不要把自己的 `agent_config.json` 直接发到公开 issue。
- QQ live 模式会真实发送消息，先用 dry-run 和白名单测试。

## 常见问题

### 打开页面空白

先确认后端还在运行，再访问：

```text
http://127.0.0.1:8765/next/
```

如果是前端静态包缺失，可以在 `observatory/frontend` 下运行：

```bat
npm install
npm run build
```

### NapCat 能收到 QQ 消息，但 PA 没反应

检查 NapCat 网络配置里是否有 HTTP Client：

```text
http://127.0.0.1:8765/api/agent/napcat/event
```

同时在 PA 适配器页面看入站/出站日志，确认消息是否被白名单、黑名单、群聊门控或触发模式过滤。

### 读图或绘图失败

确认：

- 视觉/多模态模型是否配置；
- 绘图模型是否配置；
- 对应 API Key 是否填写，或是否允许复用主 API Key；
- LLM/API 调用日志里是否出现格式错误、限流、熔断或 provider 报错。

## 开发者提示

- 后端入口：`python -m observatory`
- Agent runtime：`observatory/agent_runtime.py`
- Web API：`observatory/_web.py`
- 前端源码：`observatory/frontend/src/pages/AgentPage.tsx`
- 前端静态包：`observatory/web_static_next/`
- 运行输出：`observatory/outputs/agent/`

发布前建议至少运行：

```bat
python -m py_compile observatory\agent_runtime.py observatory\_web.py
python -m pytest observatory\tests\test_agent_public_projection.py -q
```

## 反馈

项目还很早期，欢迎反馈 bug、想法和复现步骤。

- GitHub Issues：推荐用于可公开复现的问题
- QQ 群：`296842274`
- 加群备注：`PsyArch Agent`
