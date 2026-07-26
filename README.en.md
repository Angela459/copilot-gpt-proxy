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

The launcher checks only these fixed locations for the current Windows user; it does not enumerate or scan other directories. `%APPDATA%` is the current user's application configuration folder, and each path can be pasted directly into the File Explorer address bar:

- Visual Studio Code: `%APPDATA%\Code\User\settings.json`;
- Visual Studio Code Insiders: `%APPDATA%\Code - Insiders\User\settings.json`;
- VSCodium: `%APPDATA%\VSCodium\User\settings.json`.

One match is used automatically. Multiple matches are shown with editor names for selection. If none match, a file picker asks the user to select the exact `settings.json` file.

After model selection, the script generates `config.yaml` and shows a Continue/Cancel confirmation before changing the Copilot API Base URL. The original file is backed up as `settings.json.copilot-gpt-proxy.bak`; JSONC comments and unrelated settings are preserved. API keys are never written to the proxy configuration.

Select a different directory or model:

```powershell
start.bat --reconfigure
```

The program does not scan disks, access VS Code SecretStorage, or print API keys or custom headers.

## Start

```powershell
start.bat
```

Default local URL:

```text
http://127.0.0.1:9000/v1
```

The startup script automatically sets the selected Copilot model's API Base URL to the proxy, so no manual edit is required. The `base_url` in `config.yaml` remains the upstream third-party API used by the proxy; the two addresses are kept separate.

ngrok is disabled by default. Enable it explicitly only when Copilot cannot access the local URL:

```powershell
start.bat --ngrok
```

The proxy is independent of the business project opened in Copilot. There is no strict startup order, but the proxy must be running before Copilot sends a model request. One proxy process can serve whichever business project Copilot currently has open.
