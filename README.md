# Copilot GPT Proxy

简体中文 | [English](README.en.md)

`copilot-gpt-proxy` 是一个供 GitHub Copilot App 使用的本地 OpenAI 兼容代理，让用户可以通过第三方 API 使用 ChatGPT 的所有模型，并减少工具调用兼容问题造成的失败或重复执行。

实现原理、协议边界和设计取舍见 [DESIGN.md](DESIGN.md)。

## 解决的问题

### 现象

通过 GitHub Copilot App 使用 ChatGPT 模型执行代码任务时，模型可能反复表示“现在开始修改”，却没有真正完成工具调用。常见错误为：

```text
apply_patch requires a non-empty string input
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
config_version: 1
default_model: "gpt-5.4"

api_providers:
  - name: primary
    base_url: "https://your-provider.example/v1"

models:
  - name: "gpt-5.4"
    model_identifier: "gpt-5.4"
    api_provider: primary
  - name: "gpt-5.4-mini"
    model_identifier: "gpt-5.4-mini"
    api_provider: primary
```

`default_model` 是默认模型别名；每个模型的 `name` 是 Copilot 使用的模型 ID，`model_identifier` 是发送给 `api_provider` 的真实模型名。一个代理进程可以同时路由多个 Provider 和模型。

旧版 `base_url` / `model` 以及映射形式的 `providers` / `models` 配置仍可继续使用。

如果不同 Provider 使用不同 API Key，为 Provider 配置环境变量名：

```yaml
api_providers:
  - name: backup
    base_url: "https://another-provider.example/v1"
    api_key_env: "BACKUP_PROVIDER_API_KEY"
```

启动前设置对应环境变量：

```powershell
$env:BACKUP_PROVIDER_API_KEY = "your-api-key"
```

未配置 `api_key_env` 的 Provider 会继续使用 Copilot App 中填写的 API Key。

启动代理：

```powershell
uv run copilot-gpt-proxy
```

代理启动后，终端会显示：

```text
api_base_url: http://127.0.0.1:9000/v1
```

在 GitHub Copilot App 的第三方 API 配置中，将 API Base URL 手动改为终端显示的 `api_base_url`。模型应使用 `config.yaml` 的 `models` 中定义的 `name`。

代理与 Copilot 打开的代码目录无关，但 Copilot 发出请求时代理必须保持运行。

## 致谢

项目思路与部分代码来自 [yxlao/deepseek-cursor-proxy](https://github.com/yxlao/deepseek-cursor-proxy)，感谢原项目作者的工作。
