# Copilot GPT Proxy

[简体中文](README.zh-CN.md) | English

`copilot-gpt-proxy` is a local OpenAI-compatible proxy for making GitHub Copilot's custom-model workflow more tolerant of GPT tool-call protocol differences.

The repository was bootstrapped from [yxlao/deepseek-cursor-proxy](https://github.com/yxlao/deepseek-cursor-proxy), which provides the HTTP server, streaming response handling, request normalization, tracing, and a strong test foundation. The original MIT license and attribution are preserved.

## Why this project exists

When GPT-5.4 is used through a third-party API in a coding agent, the model can emit an `apply_patch` tool call with an empty object (`{}`). The client then reports:

```text
apply_patch requires a non-empty string input (the patch content)
```

Some clients retry the same malformed call indefinitely. This is a model/tool-call integration failure, not normally a filesystem permission failure. The proxy is intended to make the boundary observable and recoverable without changing the Copilot application or the model selected by the user.

## Current status

The Copilot/GPT compatibility guard is implemented for Chat Completions and Responses API outputs. It:

- assembles streamed tool-call arguments before exposing them to Copilot;
- recognizes both Responses `function_call` and free-form `custom_tool_call` items;
- represents Copilot's free-form `apply_patch` as a required-input function on the first upstream request, avoiding a known empty custom-tool round trip;
- restores the successful function response to Copilot's original `custom_tool_call` event shape and unwraps the raw patch input, so the client can execute its registered custom tool;
- removes repeated prompt and tool definitions from Responses lifecycle events before returning them through the tunnel, while preserving the schema fields, output, and usage;
- blocks completed `apply_patch` calls whose arguments or `input` contain no patch content;
- removes known empty calls and their error outputs from the retry copy of Responses history;
- retries once if the function response is still malformed; and
- returns a bounded `empty_apply_patch` error if the retry is still empty.

The proxy never invents patch content. Valid calls and non-`apply_patch` tools pass through normally. The inherited DeepSeek reasoning repair remains available for users of that provider. See [DESIGN.md](DESIGN.md) for the protocol boundary and trade-offs.

> The server supports both `/v1/chat/completions` and `/v1/responses`. Responses
> streams are buffered until `response.completed` so malformed tool calls can be
> retried before Copilot sees them. An upstream stream that never completes is
> returned as a bounded error; the proxy never fabricates a completion event.
> Buffered SSE responses are connection-delimited rather than sent with a fixed
> `Content-Length`, avoiding tunnel-layer false truncation errors.

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

## Explicit Copilot settings import

The proxy never scans disks for Copilot installations. A user may explicitly
pass one VS Code/Copilot `settings.json` file:

```powershell
uv run copilot-gpt-proxy `
  --copilot-settings "$env:APPDATA\Code\User\settings.json" `
  --copilot-model-id gpt-5.4
```

Inspect the same file without starting the proxy:

```powershell
uv run copilot-gpt-proxy `
  --inspect-copilot-settings "$env:APPDATA\Code\User\settings.json"
```

Only `oaicopilot.baseUrl` and the model's `id`, `baseUrl`, `apiMode`, and
`owned_by` fields are retained or printed. The parser reads only the file named
by the user; it does not enumerate directories, access VS Code SecretStorage,
or print API keys and custom headers. Both `openai` Chat Completions and
`openai-responses` are supported.

## Development

Requirements: Python 3.10+ and `uv` (or an equivalent virtual environment).

```bash
uv run python -m unittest discover -s tests
uv run copilot-gpt-proxy --no-ngrok --port 9000 --verbose
```

The proxy exposes the OpenAI-compatible `/v1/chat/completions` endpoint. Do not put real API keys in source files or trace fixtures.

## Project name

The name deliberately uses `GPT` instead of a model version. The proxy is a protocol bridge, not a replacement model, and should remain useful if the upstream model changes from GPT-5.4.
