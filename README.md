# Copilot GPT Proxy

简体中文 | [English](README.en.md)

`copilot-gpt-proxy` 是一个供 GitHub Copilot App 使用的本地 OpenAI 兼容代理，让用户可以通过第三方 API 使用 ChatGPT 的所有模型，并减少工具调用兼容问题造成的失败或重复执行。

实现原理、协议边界和设计取舍见 [DESIGN.md](DESIGN.md)。

## 安装

需要 Python 3.10+ 和 [uv](https://docs.astral.sh/uv/)。

```powershell
git clone git@github.com:Angela459/copilot-gpt-proxy.git
cd copilot-gpt-proxy
uv sync
```

## 手动配置

复制配置模板：

```powershell
Copy-Item config.example.yaml config.yaml
```

打开 `config.yaml`，填写第三方 API 的原始地址和模型：

```yaml
base_url: "https://your-provider.example/v1"
model: "gpt-5.4"
```

API Key 不需要写入 `config.yaml`。

启动代理：

```powershell
uv run copilot-gpt-proxy --config config.yaml --no-ngrok
```

代理启动后，终端会显示：

```text
api_base_url: http://127.0.0.1:9000/v1
```

在 GitHub Copilot App 的第三方 API 配置中，将 API Base URL 手动改为终端显示的 `api_base_url`。API Key 保持原值，模型应与 `config.yaml` 中的 `model` 一致。

代理与 Copilot 打开的代码目录无关，但 Copilot 发出请求时代理必须保持运行。

需要使用 ngrok 时，手动运行：

```powershell
uv run copilot-gpt-proxy --config config.yaml --ngrok
```

然后将 Copilot App 的 API Base URL 改为终端显示的新 `api_base_url`。

## 致谢

项目思路与部分代码来自 [yxlao/deepseek-cursor-proxy](https://github.com/yxlao/deepseek-cursor-proxy)，感谢原项目作者的工作。
