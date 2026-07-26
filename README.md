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

启动程序会根据 Windows 当前登录用户自动检查以下几个固定位置，不会遍历或扫描其他目录。`%APPDATA%` 代表当前用户的应用配置文件夹，可以把下面的路径直接粘贴到文件资源管理器地址栏：

- Visual Studio Code 稳定版：`%APPDATA%\Code\User\settings.json`；
- Visual Studio Code 预览版：`%APPDATA%\Code - Insiders\User\settings.json`；
- VSCodium：`%APPDATA%\VSCodium\User\settings.json`。

只找到一个时会直接使用；找到多个时会显示编辑器名称供用户选择；都没找到时才打开文件选择框，让用户选择具体的 `settings.json` 文件。

选择模型后，脚本生成 `config.yaml`，并在修改 Copilot API Base URL 前显示“继续/取消”确认框。原始配置会备份为 `settings.json.copilot-gpt-proxy.bak`，JSONC 注释及其他设置保持不变。API Key 不会写入代理配置。

重新选择目录或模型：

```powershell
start.bat --reconfigure
```

程序不会扫描磁盘、访问 VS Code SecretStorage，或输出 API Key 和自定义请求头。

## 启动

```powershell
start.bat
```

默认本地地址：

```text
http://127.0.0.1:9000/v1
```

启动脚本会自动将所选 Copilot 模型的 API Base URL 设置为代理地址，无需再手动修改。`config.yaml` 中的 `base_url` 仍是代理访问第三方 API 的上游地址，两者不会混用。

ngrok 默认关闭。只有 Copilot 无法访问本地地址时才需要显式启用：

```powershell
start.bat --ngrok
```

代理与 Copilot 打开的业务项目相互独立。启动顺序没有严格限制，但在 Copilot 发出模型请求前，代理必须保持运行；同一个代理进程可以服务 Copilot 当前打开的任意业务项目。
