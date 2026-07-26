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

## Manual Configuration

Copy the configuration template:

```powershell
Copy-Item config.example.yaml config.yaml
```

Open `config.yaml` and enter the original third-party API URL and model:

```yaml
base_url: "https://your-provider.example/v1"
model: "gpt-5.4"
```

The API key does not need to be stored in `config.yaml`.

Start the proxy:

```powershell
uv run copilot-gpt-proxy --config config.yaml --no-ngrok
```

The terminal prints the proxy URL after startup:

```text
api_base_url: http://127.0.0.1:9000/v1
```

In the third-party API settings of GitHub Copilot App, manually change API Base URL to the displayed `api_base_url`. Keep the existing API key and use the same model as `model` in `config.yaml`.

The proxy is independent of the code directory opened in Copilot, but it must remain running while Copilot sends requests.

To use ngrok, run manually:

```powershell
uv run copilot-gpt-proxy --config config.yaml --ngrok
```

Then change the Copilot App API Base URL to the new `api_base_url` shown in the terminal.

## Acknowledgements

The project concept and parts of the code are based on [yxlao/deepseek-cursor-proxy](https://github.com/yxlao/deepseek-cursor-proxy). Thanks to the original author for their work.
