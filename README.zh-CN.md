# Copilot GPT Proxy

简体中文 | [English](README.md)

`copilot-gpt-proxy` 是一个本地 OpenAI 兼容代理，用于缓解 GitHub Copilot 自定义模型工作流与 GPT 工具调用之间的协议兼容问题。

本项目基于 [yxlao/deepseek-cursor-proxy](https://github.com/yxlao/deepseek-cursor-proxy) 改造，复用了它的 HTTP 服务、请求规范化、SSE 流处理、trace 和测试基础。原项目的 MIT 许可证及作者信息均予以保留。

## 解决的问题

通过第三方 API 在编码代理中使用 GPT-5.4 时，模型可能生成参数为空的 `apply_patch` 调用：

```text
apply_patch {}
```

客户端执行后会报错：

```text
apply_patch requires a non-empty string input (the patch content)
```

部分客户端还会反复重试同一个错误调用。当前代理针对 Chat Completions 和 Responses API 实现了以下保护：

- 完整聚合流式工具调用参数后，再向 Copilot 输出；
- 同时识别 Responses 的 `function_call` 和 FREEFORM `custom_tool_call`；
- 拦截参数或 `input` 中没有补丁内容的 `apply_patch`；
- 从重试副本中移除已知的空调用及其错误回执，避免模型继续模仿错误历史；
- 重试时将 `apply_patch` 表示为 `input` 必填且非空的标准 function，兼容能够接收 custom 工具却无法正确生成 FREEFORM 输入的上游；
- 第二次仍为空时返回 `empty_apply_patch` 错误并立即终止；
- 不伪造模型从未生成的补丁内容。

合法的 `apply_patch`、其他工具调用以及普通文本响应不会被拦截。

## 当前限制

目前支持：

```text
POST /v1/chat/completions
POST /v1/responses
```

Responses API 的流会在代理内部缓冲到 `response.completed`，这样才能在交给 Copilot 之前检查工具调用。如果上游始终不发送完成事件，代理会返回有界错误，不会伪造 `response.completed`。

如果上游 Responses API 仍然提前断流，客户端可能看到：

```text
Responses stream ended without a completed response
```

这个错误表示上游没有在 SSE 流结束前发送 `response.completed`。可能原因包括：

1. 第三方上游声称支持 Responses API，但提前关闭了流；
2. 上游返回了 Chat Completions 格式，客户端却按 Responses 事件格式解析；
3. 中间网络设备截断了 SSE 流。

不能通过无条件伪造 `response.completed` 来修复，因为这可能把不完整的文本或工具参数标记为完整响应。需要先捕获实际请求和上游事件，再实现对应的协议适配器。

## 安装

需要 Python 3.10+ 和 [uv](https://docs.astral.sh/uv/)。

```powershell
git clone git@github.com:Angela459/copilot-gpt-proxy.git
cd copilot-gpt-proxy
uv sync
```

## 配置

首次启动会创建：

```text
~/.copilot-gpt-proxy/config.yaml
```

Windows 下通常位于：

```text
C:\Users\你的用户名\.copilot-gpt-proxy\config.yaml
```

根据第三方 API 修改主要配置：

```yaml
base_url: https://你的第三方接口地址/v1
model: gpt-5.4

host: 127.0.0.1
port: 9000
ngrok: false

empty_apply_patch: retry_once
max_tool_retries: 1
```

API Key 默认从 Copilot 请求中的 `Authorization: Bearer ...` 读取并转发，不要把真实密钥提交到仓库。

空调用策略：

- `retry_once`：拦截并重试一次，默认值；
- `reject`：不重试，直接返回有界错误；
- `allow`：关闭保护，原样转发。

## 显式导入 Copilot 配置

代理不会扫描磁盘或自动枚举 Copilot 安装目录。用户可以明确指定一个 VS Code/Copilot `settings.json`：

```powershell
uv run copilot-gpt-proxy `
  --copilot-settings "$env:APPDATA\Code\User\settings.json" `
  --copilot-model-id gpt-5.4
```

只检查配置、不启动代理：

```powershell
uv run copilot-gpt-proxy `
  --inspect-copilot-settings "$env:APPDATA\Code\User\settings.json"
```

隐私边界：

- 只读取用户在命令行明确指定的单个文件；
- 不扫描目录，不检测其他编辑器或 Copilot 安装；
- 只保留或显示 `oaicopilot.baseUrl`，以及模型的 `id`、`baseUrl`、`apiMode`、`owned_by`；
- 不访问 VS Code SecretStorage；
- 不输出 API Key、自定义请求头或其他设置值。

解析 JSON 时文件内容会在本地进程内短暂读取，但非白名单字段不会进入输出或代理配置。`openai` Chat Completions 和 `openai-responses` 两种模式均可使用。

## 启动

本地启动并显示详细日志：

```powershell
uv run copilot-gpt-proxy --no-ngrok --port 9000 --verbose
```

Chat Completions Base URL 为：

```text
http://127.0.0.1:9000/v1
```

只有当 Copilot 不允许访问本地地址时，才需要使用 ngrok 或其他 HTTPS 隧道。

## 诊断 Responses 流错误

使用 trace 模式启动：

```powershell
uv run copilot-gpt-proxy `
  --no-ngrok `
  --port 9000 `
  --verbose `
  --trace-dir .\trace-dumps
```

复现一次错误后，检查 `trace-dumps` 中最新请求，重点确认：

- 请求路径是 `/v1/chat/completions` 还是 `/v1/responses`；
- 上游 `Content-Type` 是否为 `text/event-stream`；
- 最后一个 SSE 事件是 `[DONE]`、`response.completed`、错误事件还是直接断流；
- `apply_patch` 的名称和参数分别出现在哪些事件中。

trace 可能包含提示词、文件内容和工具参数。提交 issue 或共享日志前必须删除 API Key、私有代码和其他敏感信息。

## 开发与测试

```powershell
uv run --extra dev black --check src tests
uv run --extra dev ruff check src tests
uv run python -m unittest discover -s tests
```

当前测试覆盖非流式与流式参数聚合、首次空调用后的合法重试、连续空调用的重试上限，以及原项目已有的协议和缓存行为。真实第三方 API 测试不会在 CI 中执行。

详细设计和 Responses API 适配边界见 [DESIGN.md](DESIGN.md)。
