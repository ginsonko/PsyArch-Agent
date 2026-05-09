# 已有 NapCat 的手动配置方法

如果你本地已经有可用的 NapCat，不需要运行 PA 仓库里的“一键拉取或更新 NapCat”脚本。只要启动 PA 后，在 NapCat WebUI 的“网络配置”里确认下面三个配置都存在并启用即可。

PA 默认地址：

```text
http://127.0.0.1:8765/api/agent/napcat/event
```

## 必须有的三个网络配置

### 1. HTTP 服务器

用于让 PA 通过 OneBot HTTP API 给 QQ 私聊或群聊发消息。

- 类型：`HTTP服务器`
- 主机：`127.0.0.1`
- 端口：`3000`
- 消息格式：`array`
- 状态：启用

### 2. HTTP 客户端

用于让 NapCat 把收到的 QQ 消息上报给 PA。

- 类型：`HTTP客户端`
- 名称建议：`PA Agent Webhook`
- URL：`http://127.0.0.1:8765/api/agent/napcat/event`
- 状态：启用

### 3. WebSocket 服务器

用于保留 OneBot WebSocket 入口，方便调试或给其他工具连接。

- 类型：`Websocket服务器`
- 主机：`127.0.0.1`
- 端口：`3001`
- 心跳间隔：`30000ms`
- 状态：启用

## 操作顺序

1. 先启动 PA，确认可以打开：

```text
http://127.0.0.1:8765/next/
```

2. 打开 NapCat WebUI，进入“网络配置”。
3. 检查上面三个网络配置是否都存在。
4. 如果缺少 HTTP 客户端，就新增一个 HTTP 客户端，URL 填：

```text
http://127.0.0.1:8765/api/agent/napcat/event
```

5. 保存并启用配置。
6. 在 PA 的“适配器”页面查看“NapCat 入站/出站日志”。QQ 收到消息后，这里应该能看到入站记录。

## 常见检查点

- PA 后端端口默认是 `8765`，如果你改过 PA 端口，HTTP 客户端 URL 也要一起改。
- NapCat HTTP 服务器默认端口是 `3000`，如果你改过端口，PA 配置里的 `NapCat HTTP API 地址` 也要同步修改。
- 如果 PA 能看到入站消息但 QQ 收不到回复，检查 PA 适配器页里的 `NapCat dry-run` 是否开启。
- 如果消息被过滤，检查主人 QQ、名单模式、用户白名单、群白名单和触发模式。
