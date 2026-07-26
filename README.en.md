# Copilot GPT Proxy

[简体中文](README.md) | English

`copilot-gpt-proxy` is a local OpenAI-compatible proxy for GitHub Copilot App. It lets users access all ChatGPT models through third-party APIs while reducing failures and repeated actions caused by tool-call compatibility issues.

See [DESIGN.md](DESIGN.md) for implementation details, protocol boundaries, and design trade-offs.

## Problem Addressed

### Symptoms

When ChatGPT models perform coding tasks through GitHub Copilot App, the model may repeatedly say that it is about to edit a file without completing the tool call. The terminal then reports errors such as `apply_patch requires a non-empty string input` or a prematurely terminated response stream, and retries fall into the same loop.

### Cause

As described in this [analysis of the `apply_patch` calling format](https://zhuanlan.zhihu.com/p/2040102122830697685), `apply_patch` expects raw patch text as free-form input. Copilot's agent adapter, a third-party API, and the underlying tool executor may interpret that tool differently. If an intermediate layer converts, wraps, escapes, truncates, or drops the free-form input, the model emits empty or malformed arguments. The executor rejects the call while the model retries against the same tool description, creating a loop. This is a tool-protocol compatibility issue, not an inability of the model to write a patch.

## How It Works

In one sentence: the proxy sits between Copilot App and the third-party API, normalizes requests and responses, intercepts malformed tool calls before they reach Copilot's executor, and forwards an executable result only after a bounded retry.

```mermaid
flowchart LR
    A["GitHub Copilot App"] -->|"Model request"| B["Copilot GPT Proxy"]
    B -->|"Normalize request"| C["Third-party OpenAI-compatible API"]
    C -->|"Model response"| B
    B -->|"Empty or malformed tool call: intercept and retry"| C
    B -->|"Normalized stream and tool calls"| A
```

## Installation

Python 3.10+ and [uv](https://docs.astral.sh/uv/) are required.

```powershell
git clone git@github.com:Angela459/copilot-gpt-proxy.git
cd copilot-gpt-proxy
uv sync
```

## Manual Configuration

Make a copy of `config.example.yaml` and rename the copy to `config.yaml`.

Open `config.yaml` and enter the original third-party API URL and model:

```yaml
base_url: "https://your-provider.example/v1"
model: "gpt-5.4"
```

Start the proxy:

```powershell
uv run copilot-gpt-proxy
```

The terminal prints the proxy URL after startup:

```text
api_base_url: http://127.0.0.1:9000/v1
```

In the third-party API settings of GitHub Copilot App, manually change API Base URL to the displayed `api_base_url`. Keep the existing API key and use the same model as `model` in `config.yaml`.

The proxy is independent of the code directory opened in Copilot, but it must remain running while Copilot sends requests.

## Acknowledgements

The project concept and parts of the code are based on [yxlao/deepseek-cursor-proxy](https://github.com/yxlao/deepseek-cursor-proxy). Thanks to the original author for their work.
