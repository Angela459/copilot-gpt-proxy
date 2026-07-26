# Copilot GPT Proxy

简体中文 | [English](README.en.md)

`copilot-gpt-proxy` 是一个供 GitHub Copilot App 使用的本地 OpenAI 兼容代理，让用户可以通过第三方 API 使用 ChatGPT 的所有模型，并减少工具调用兼容问题造成的失败或重复执行。

实现原理、协议边界和设计取舍见 [DESIGN.md](DESIGN.md)。

## 解决的问题

### 现象

通过 GitHub Copilot App 使用 ChatGPT 模型执行代码任务时，模型可能反复表示“现在开始修改”，却没有真正完成工具调用。常见错误为：

```text
apply_patch requires a non-empty string input (the patch content).
```

此外还可能出现流式响应提前结束等错误，并在重试后再次进入相同循环。

### 原因

`apply_patch` 本应接收原始补丁文本（freeform），但 Copilot 的 Agent 适配层、第三方 API 和底层工具执行器对工具格式的理解可能不一致。freeform 语义在中间链路中被 JSON 化、包装、转义、截断或丢失后，模型会生成空参数或格式错误的调用；执行器拒绝调用，而模型仍依据相同的工具描述继续重试，于是形成循环。这是工具协议兼容问题，不是模型不会编写补丁。

## 工作原理

本项目位于 Copilot App 与第三方 API 之间，规范化请求和响应，并在错误工具调用到达 Copilot 执行器前拦截它，有限重试后只转发可执行的结果。

```mermaid
flowchart LR
    A["GitHub Copilot App"] -->|"模型请求"| B["Copilot GPT Proxy"]
    B -->|"规范化请求"| C["第三方 OpenAI 兼容 API"]
    C -->|"模型响应"| B
    B -->|"空或错误工具调用：拦截并有限重试"| C
    B -->|"规范化的流式响应与工具调用"| A
```

## 安装

需要 Python 3.10+ 和 [uv](https://docs.astral.sh/uv/)。

```powershell
git clone git@github.com:Angela459/copilot-gpt-proxy.git
cd copilot-gpt-proxy
uv sync
```

## 手动配置

复制一份 `config.example.yaml`，并将副本重命名为 `config.yaml`。

打开 `config.yaml`，配置 Provider 和模型路由：

```yaml
model: "gpt-5.4"

providers:
  OpenAI:
    base_url: "https://api.openai.com/v1"
  # OpenRouter:
  #   base_url: "https://openrouter.ai/api/v1"

models:
  OpenAI:
    - "gpt-5.4"
    # - "gpt-5.4-mini"
    # - "gpt-4.1"
  # OpenRouter:
  #   - "openai/gpt-5.4"
  #   - "anthropic/claude-sonnet-4"
```

`providers` 下直接填写 Provider 名称和对应的 `base_url`，`models` 再按相同的 Provider 名称列出模型。模型名称同时作为 Copilot 使用的模型 ID 和发送给上游的模型 ID，因此同一个模型名称不能同时出现在多个 Provider 下。

API Key 只在 GitHub Copilot App 中配置。代理不会从 `config.yaml` 或环境变量读取 API Key，也不会保存或切换 Key，只会把 Copilot 当前请求中的 Authorization 转发给所选 Provider。

### 配置项说明

| 配置项 | 可用值或格式 | 作用 |
| --- | --- | --- |
| `model` | `models` 中已启用的模型名称 | 请求未指定模型时使用的默认模型。 |
| `providers` | Provider 名称到配置的映射 | 定义代理可以访问的所有 Provider。名称由用户填写，并供 `models` 分组引用。 |
| `providers.<名称>.base_url` | 以 `http://` 或 `https://` 开头的 API 地址 | Provider 的原始 OpenAI 兼容 API Base URL，通常以 `/v1` 结尾。 |
| `models` | Provider 名称到模型列表的映射 | 定义每个 Provider 可使用的模型；分组名称必须与 `providers` 中的名称完全一致。 |
| `models.<Provider>` | 模型名称列表 | 同时作为 Copilot 模型 ID 和上游请求中的模型 ID。 |
| `thinking` | `enabled` / `disabled` | 是否启用上游推理模式。 |
| `reasoning_effort` | `low` / `medium` / `high` / `max` / `xhigh` | 指定推理强度；代理会转换为上游支持的等级。 |
| `display_reasoning` | `true` / `false` | 是否在 Copilot 输出中显示推理内容。 |
| `collapsible_reasoning` | `true` / `false` | 显示推理内容时，是否使用可折叠区域。 |
| `host` | IP 地址 | 本地代理监听地址。默认 `127.0.0.1`，仅本机可访问。 |
| `port` | 端口号 | 本地代理监听端口，默认 `9000`。 |
| `verbose` | `true` / `false` | 是否输出详细日志；开启后提示词和代码可能出现在终端中。 |
| `request_timeout` | 秒数 | 请求上游 API 的超时时间。 |
| `max_request_body_bytes` | 字节数 | Copilot 请求体允许的最大大小。 |
| `cors` | `true` / `false` | 是否返回允许跨域访问的 CORS 响应头。 |
| `empty_apply_patch` | `retry_once` / `reject` / `allow` | 空 `apply_patch` 调用的处理策略：重试一次、直接拒绝或原样放行。 |
| `max_tool_retries` | `0` / `1` | 错误工具调用最多重试几次；当前上限为 1。 |

配置文件中不能出现 `api_key` 或 `api_key_env`；如需切换使用不同 Key 的 Provider，请先在 Copilot App 中改为对应 Provider 的 API Key。

启动代理：

```powershell
uv run copilot-gpt-proxy
```

代理启动后，终端会显示：

```text
api_base_url: http://127.0.0.1:9000/v1
```

### 设置 Copilot App（必需）

**在 GitHub Copilot App 的第三方 API 配置中，将 API Base URL 手动改为终端显示的 `api_base_url`：**

```text
http://127.0.0.1:9000/v1
```

API Key 仍在 Copilot App 中填写。模型名称应使用 `config.yaml` 的 `models` 中已启用的名称。

代理与 Copilot 打开的代码目录无关，但 Copilot 发出请求时代理必须保持运行。

## 致谢

项目思路与部分代码来自 [yxlao/deepseek-cursor-proxy](https://github.com/yxlao/deepseek-cursor-proxy)，感谢原项目作者的工作。
