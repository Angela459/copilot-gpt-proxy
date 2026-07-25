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

The first run creates:

```text
~/.copilot-gpt-proxy/config.yaml
```

On Windows, this is usually:

```text
C:\Users\your-name\.copilot-gpt-proxy\config.yaml
```

Set the third-party API URL and model:

```yaml
base_url: https://your-provider.example/v1
model: your-model-id

host: 127.0.0.1
port: 9000
ngrok: false
```

The API key is read from the Copilot request and forwarded by default. Do not commit real keys to the repository.

## Connect Copilot App

This project does not scan disks or search for Copilot installations. Explicitly provide the `settings.json` file used by Copilot and the model ID:

```powershell
uv run copilot-gpt-proxy `
  --copilot-settings "$env:APPDATA\Code\User\settings.json" `
  --copilot-model-id your-model-id
```

Inspect the configuration without starting the proxy:

```powershell
uv run copilot-gpt-proxy `
  --inspect-copilot-settings "$env:APPDATA\Code\User\settings.json"
```

The program reads only the file explicitly selected by the user. It does not enumerate directories, access VS Code SecretStorage, or print API keys or custom headers.

## Start

```powershell
uv run copilot-gpt-proxy --no-ngrok --port 9000
```

Default local URL:

```text
http://127.0.0.1:9000/v1
```

Use ngrok or another HTTPS tunnel only when Copilot cannot access the local URL.
