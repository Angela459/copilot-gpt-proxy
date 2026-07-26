# Copilot GPT Proxy

[简体中文](README.md) | English

`copilot-gpt-proxy` is a local OpenAI-compatible proxy for GitHub Copilot App. It lets users access all ChatGPT models through third-party APIs while reducing failures and repeated actions caused by tool-call compatibility issues.

See [DESIGN.md](DESIGN.md) for implementation details, protocol boundaries, and design trade-offs.

## Installation

Python 3.10+ and [uv](https://docs.astral.sh/uv/) are required.

```powershell
git clone git@github.com:Angela459/copilot-gpt-proxy.git
cd copilot-gpt-proxy
uv sync
```

## Configuration

A tracked configuration template is provided:

```text
config.example.yaml
```

The startup script generates the real configuration in the repository root. It is ignored by Git:

```text
config.yaml
```

Windows users can double-click:

```text
start.bat
```

On first run, a file picker asks for `github.exe` in the GitHub Copilot App installation directory. Common locations include:

- `%LOCALAPPDATA%\Programs\GitHub Copilot\github.exe`;
- `C:\Program Files\GitHub Copilot\github.exe`;
- another directory selected during installation.

The program does not scan disks or read or modify VS Code `settings.json`. The upstream third-party API URL and model are stored in `config.yaml` in the project directory. API keys are never written to the proxy configuration.

Completely exit any running GitHub Copilot App before startup. After confirmation, the launcher starts the proxy and reopens the App with Copilot's supported `COPILOT_PROVIDER_*` environment variables, automatically pointing its API Base URL at the proxy.

Select a different Copilot App or change the upstream URL or model:

```powershell
start.bat --reconfigure
```

The existing third-party API key remains managed by Copilot App. The proxy does not read or print keys or custom headers.

## Start

```powershell
start.bat
```

Default local URL:

```text
http://127.0.0.1:9000/v1
```

The launcher temporarily points Copilot's API Base URL to the proxy using the officially supported environment variables, without modifying the App's internal configuration. The `base_url` in `config.yaml` remains the upstream third-party API used by the proxy; the two addresses are kept separate.

ngrok is disabled by default. Enable it explicitly only when Copilot cannot access the local URL:

```powershell
start.bat --ngrok
```

The proxy is independent of the business project opened in Copilot. Use `start.bat` to start both the proxy and Copilot App. One proxy process can serve whichever business project Copilot currently has open.

## Acknowledgements

The project concept and parts of the code are based on [yxlao/deepseek-cursor-proxy](https://github.com/yxlao/deepseek-cursor-proxy). Thanks to the original author for their work.
