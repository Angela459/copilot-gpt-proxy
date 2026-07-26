# Copilot GPT Proxy: design

## Problem statement

The observed failure is a malformed tool call:

```text
assistant -> apply_patch {}
```

The client-side executor correctly rejects it because the patch argument is empty, then the model repeats the call. A proxy can prevent the loop, but it cannot reconstruct a patch that was never generated. The design therefore separates protocol repair from recovery policy.

## Intended request path

```text
GitHub Copilot App
    -> OpenAI-compatible endpoint exposed by this proxy
    -> request normalizer and tool-call compatibility layer
    -> third-party OpenAI-compatible API / GPT-5.4
    <- response normalizer, stream assembler, and recovery policy
    <- Copilot App
```

The proxy must remain transparent for ordinary text, valid tool calls, usage data, and cancellation. Only malformed or incompatible tool messages should be changed.

## Existing foundation

The copied baseline already contains:

- an HTTP `/v1/chat/completions` server;
- request and response normalization for OpenAI-style tools;
- SSE streaming and tool-call delta aggregation;
- request tracing with authorization redaction;
- conversation-scoped state storage; and
- unit tests for protocol and streaming behavior.

These pieces are reusable. The DeepSeek-specific reasoning cache should become an optional compatibility module rather than the center of the new project.

## Compatibility layer

### 1. Canonical tool-call representation

Normalize every provider representation into one internal form:

```json
{
  "id": "call_123",
  "name": "apply_patch",
  "arguments": "*** Begin Patch ..."
}
```

Accept JSON-string arguments, object arguments, and streamed argument fragments. Preserve the original provider format only at the final response adapter.

### 2. Streaming assembly before execution

Tool-call fragments must be assembled by `(choice_index, tool_index)`. The proxy should not allow a partial tool call to be interpreted as a complete call. At the end of a tool-call turn, validate:

- tool name is non-empty;
- `apply_patch` has a non-empty string patch;
- JSON arguments are syntactically valid when the provider requires JSON; and
- the call has a stable id when the client requires one.

Text-only deltas can continue to stream. Tool-call deltas may need short buffering so an empty first fragment is not mistaken for an empty completed call.

### 3. Empty `apply_patch` recovery

When the assembled call is empty, do not emit it as an executable tool call.

1. Record a redacted diagnostic with the provider, model, call id, and reason.
2. Retry at most once, adding a short repair instruction to the existing conversation: return a complete patch string or explain that no edit is needed.
3. If the retry is valid, forward it normally.
4. If the retry is empty again, return a bounded, user-visible error and stop. Never replay the same malformed call indefinitely.

The retry must be opt-in/configurable and must preserve the original authorization and conversation scope. A proxy must not invent file contents or fabricate a patch.

### 4. Other tool normalization

Handle legacy `functions`/`function_call`, Responses-style function calls, and Chat Completions `tool_calls`. Keep unknown tools untouched where possible. Do not silently drop a valid non-`apply_patch` call.

## Configuration direction

The eventual configuration should make the provider explicit:

```yaml
base_url: https://your-openai-compatible-provider.example/v1
model: gpt-5.4
api_key: ${COPILOT_GPT_PROXY_API_KEY}
empty_apply_patch: retry_once
max_tool_retry: 1
```

Environment variables are preferable for secrets. Localhost should be the default bind address.

## Test plan

Add fixtures for:

- non-streaming `apply_patch` with valid string arguments;
- non-streaming `{}` arguments;
- streamed arguments split across multiple SSE chunks;
- an object argument that must be serialized or rejected;
- a first empty call followed by a valid retry;
- two consecutive empty calls, proving the retry limit;
- valid non-`apply_patch` tools; and
- authorization redaction in traces.

The integration test should run a fake upstream server and assert the exact number of upstream requests and client-visible SSE events. A live GPT test must remain optional and never run in CI.

## Non-goals and risks

- The proxy cannot repair a patch whose content was never produced.
- It cannot fix a Copilot client bug that rejects a valid provider response unless the response format is observable at this boundary.
- Retrying an edit request can duplicate side effects if a provider has already executed a tool; retries must happen before a tool call is exposed to the client.
- Responses API semantics are isolated in a dedicated accumulator and request path instead of spreading event-format conditionals through the Chat Completions transformer.

## Implementation status

The canonical Chat Completions guard, native Responses API passthrough, complete SSE argument assembly, one-retry policy, bounded failure response, configuration, and fake-upstream integration tests are implemented. Validation against a captured third-party request remains future work.

## Recommended implementation order

1. Keep the renamed baseline green and remove DeepSeek-specific defaults from the generic path.
2. Add the canonical tool-call model and validation helpers with pure unit tests. (Done)
3. Add buffered stream validation and a one-retry state machine. (Done)
4. Add provider adapters and Copilot-facing configuration.
5. Verify against a captured, redacted request/response pair from the user's third-party API, then test in Copilot with a disposable project.
