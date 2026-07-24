# Copilot GPT Proxy

`copilot-gpt-proxy` is a local OpenAI-compatible proxy for making GitHub Copilot's custom-model workflow more tolerant of GPT tool-call protocol differences.

The repository was bootstrapped from [yxlao/deepseek-cursor-proxy](https://github.com/yxlao/deepseek-cursor-proxy), which provides the HTTP server, streaming response handling, request normalization, tracing, and a strong test foundation. The original MIT license and attribution are preserved.

## Why this project exists

When GPT-5.4 is used through a third-party API in a coding agent, the model can emit an `apply_patch` tool call with an empty object (`{}`). The client then reports:

```text
apply_patch requires a non-empty string input (the patch content)
```

Some clients retry the same malformed call indefinitely. This is a model/tool-call integration failure, not normally a filesystem permission failure. The proxy is intended to make the boundary observable and recoverable without changing the Copilot application or the model selected by the user.

## Current status

The Copilot/GPT compatibility guard is implemented for Chat Completions responses. It:

- assembles streamed tool-call arguments before exposing them to Copilot;
- blocks completed `apply_patch` calls whose arguments contain no patch content;
- retries the upstream request once with a focused repair instruction; and
- returns a bounded `empty_apply_patch` error if the retry is still empty.

The proxy never invents patch content. Valid calls and non-`apply_patch` tools pass through normally. The inherited DeepSeek reasoning repair remains available for users of that provider. See [DESIGN.md](DESIGN.md) for the protocol boundary and trade-offs.

The current executable is:

```text
copilot-gpt-proxy
```

The default configuration path is:

```text
~/.copilot-gpt-proxy/config.yaml
```

The guard is enabled by default:

```yaml
empty_apply_patch: retry_once
max_tool_retries: 1
```

Use `empty_apply_patch: reject` to block an empty call without retrying, or `empty_apply_patch: allow` to disable the guard. For streamed requests, the proxy buffers one complete assistant response so it can validate tool arguments before Copilot executes them.

## Development

Requirements: Python 3.10+ and `uv` (or an equivalent virtual environment).

```bash
uv run python -m unittest discover -s tests
uv run copilot-gpt-proxy --no-ngrok --port 9000 --verbose
```

The proxy exposes the OpenAI-compatible `/v1/chat/completions` endpoint. Do not put real API keys in source files or trace fixtures.

## Project name

The name deliberately uses `GPT` instead of a model version. The proxy is a protocol bridge, not a replacement model, and should remain useful if the upstream model changes from GPT-5.4.
