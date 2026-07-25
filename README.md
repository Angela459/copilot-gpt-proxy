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

## 配置

首次启动会创建配置文件：

```text
~/.copilot-gpt-proxy/config.yaml
```

Windows 下通常位于：

```text
C:\Users\你的用户名\.copilot-gpt-proxy\config.yaml
```

填写第三方 API 地址和要使用的模型：

```yaml
base_url: https://你的第三方接口地址/v1
model: 你的模型ID

host: 127.0.0.1
port: 9000
ngrok: false
```

API Key 默认从 Copilot 请求中读取并转发，请勿将真实密钥提交到仓库。

## 连接 Copilot App

本项目不会扫描磁盘或自动查找 Copilot 安装目录。请明确指定 Copilot 使用的 `settings.json` 和模型 ID：

```powershell
uv run copilot-gpt-proxy `
  --copilot-settings "$env:APPDATA\Code\User\settings.json" `
  --copilot-model-id 你的模型ID
```

只检查配置、不启动代理：

```powershell
uv run copilot-gpt-proxy `
  --inspect-copilot-settings "$env:APPDATA\Code\User\settings.json"
```

程序只读取用户明确指定的配置文件，不扫描目录、不访问 VS Code SecretStorage，也不会输出 API Key 或自定义请求头。

## 启动

```powershell
uv run copilot-gpt-proxy --no-ngrok --port 9000
```

默认本地地址：

```text
http://127.0.0.1:9000/v1
```

只有 Copilot 无法访问本地地址时，才需要使用 ngrok 或其他 HTTPS 隧道。
