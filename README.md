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

Windows 用户可以直接双击：

```text
start.bat
```

首次运行会打开文件选择框，让用户选择 GitHub Copilot App 安装目录中的 `github.exe`。常见位置包括：

- `%LOCALAPPDATA%\Programs\GitHub Copilot\github.exe`；
- `C:\Program Files\GitHub Copilot\github.exe`；
- 安装时自行选择的其他目录。

程序不会扫描磁盘，也不会读取或修改 VS Code 的 `settings.json`。第三方 API 地址和模型保存在项目目录下的 `config.yaml`；API Key 不会写入代理配置。

启动前请完全退出已经运行的 GitHub Copilot App。确认后，脚本会先启动代理，再通过 Copilot 官方支持的 `COPILOT_PROVIDER_*` 环境变量重新打开 App，并自动把 API Base URL 指向代理。

重新选择 Copilot App 或修改上游地址、模型：

```powershell
start.bat --reconfigure
```

Copilot App 中原有的第三方 API Key 会继续由 App 管理，程序不会读取或输出密钥和自定义请求头。

## 启动

```powershell
start.bat
```

默认本地地址：

```text
http://127.0.0.1:9000/v1
```

启动脚本会使用 Copilot 官方的环境变量将 API Base URL 临时设置为代理地址，无需修改 App 的内部配置。`config.yaml` 中的 `base_url` 仍是代理访问第三方 API 的上游地址，两者不会混用。

ngrok 默认关闭。只有 Copilot 无法访问本地地址时才需要显式启用：

```powershell
start.bat --ngrok
```

代理与 Copilot 打开的业务项目相互独立。请通过 `start.bat` 启动代理和 Copilot App；同一个代理进程可以服务 Copilot 当前打开的任意业务项目。
