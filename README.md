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

仓库提供可提交的配置模板：

```text
config.example.yaml
```

真实配置由启动脚本生成在仓库根目录，并已加入 `.gitignore`：

```text
config.yaml
```

首次运行：

```powershell
.\start.ps1
```

脚本会让用户选择包含 `settings.json` 的 Copilot 配置目录，只检查用户选择的目录，并列出其中可用模型。选择模型后会生成 `config.yaml` 并启动代理。API Key 默认从 Copilot 请求中读取并转发，不会写入配置文件。

重新选择目录或模型：

```powershell
.\start.ps1 -Reconfigure
```

程序不会扫描磁盘、访问 VS Code SecretStorage，或输出 API Key 和自定义请求头。

## 启动

```powershell
.\start.ps1
```

默认本地地址：

```text
http://127.0.0.1:9000/v1
```

ngrok 默认关闭。只有 Copilot 无法访问本地地址时才需要显式启用：

```powershell
.\start.ps1 -EnableNgrok
```

代理与 Copilot 打开的业务项目相互独立。启动顺序没有严格限制，但在 Copilot 发出模型请求前，代理必须保持运行；同一个代理进程可以服务 Copilot 当前打开的任意业务项目。
