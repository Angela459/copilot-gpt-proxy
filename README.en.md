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

First run:

```powershell
.\start.ps1
```

The script asks the user to select the Copilot configuration directory containing `settings.json`, inspects only that directory, and lists the available models. After selection it generates `config.yaml` and starts the proxy. API keys are read from Copilot requests and are never written to the generated configuration.

Select a different directory or model:

```powershell
.\start.ps1 -Reconfigure
```

The program does not scan disks, access VS Code SecretStorage, or print API keys or custom headers.

## Start

```powershell
.\start.ps1
```

Default local URL:

```text
http://127.0.0.1:9000/v1
```

After startup, set the API Base URL used by Copilot App to the `api_base_url` printed in the terminal. The `base_url` in `config.yaml` is the upstream third-party API used by the proxy; do not interchange these two addresses.

ngrok is disabled by default. Enable it explicitly only when Copilot cannot access the local URL:

```powershell
.\start.ps1 -EnableNgrok
```

The proxy is independent of the business project opened in Copilot. There is no strict startup order, but the proxy must be running before Copilot sends a model request. One proxy process can serve whichever business project Copilot currently has open.
